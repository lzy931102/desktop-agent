"""P0 三连修复的回归测试（2026-09-30 晚实跑日志暴露的问题，见 docs/任务修改列表）。

- T7 轮次上限：默认 30、DesktopAgent 可注入、最后 2 轮注入收束提示
- T6 open_url + 确定性失败不重试：白名单/校验类拒绝立即返回，不再白烧 3 次退避
- T8 空回复假成功：模型空回复时 history 状态不得记为 success（0f38d020 实录）

用假 LLM（沿用 test_agent_loop_guard.py 的 mock 模式）驱动 DesktopAgent._run_loop，
不碰真实屏幕/浏览器；open_url 的公网校验用桩 getaddrinfo 保证离线确定性。
"""
import json
from pathlib import Path

import pytest

import agent_loop
from agent_loop import DesktopAgent, _create_folder, _open_url
from core.audit import AuditLogger
from core.history import TaskHistory
from core.retry import run_with_retry
from core.guard import evaluate as guard_evaluate
from core.settings import DEFAULTS, MAX_TURNS, validate_public_url


class _FakeLLM:
    """按序返回预设响应的最小 LLM 桩"""

    def __init__(self, responses):
        self._responses = list(responses)

    def chat(self, messages, tools):
        return self._responses.pop(0)


class _StubTool:
    def __init__(self):
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        return "stub ok"


def _tool_call(call_id, name, args):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": name,
                                         "arguments": json.dumps(args)}}]}


def _final(text="任务完成"):
    return {"role": "assistant", "content": text, "tool_calls": []}


def _read_audit(log_dir: Path):
    entries = []
    for f in log_dir.glob("audit-*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
    return entries


@pytest.fixture
def stub_tools(monkeypatch):
    stub = _StubTool()
    monkeypatch.setattr(agent_loop, "TOOL_FUNCTIONS",
                        {"clipboard_write": stub, "press_key": stub})
    return stub


@pytest.fixture
def no_sleep(monkeypatch):
    """退避重试测试不等真实 1+2+4 秒"""
    monkeypatch.setattr(agent_loop.time, "sleep", lambda s: None)
    import core.retry as retry_mod
    monkeypatch.setattr(retry_mod.time, "sleep", lambda s: None)


# ---- T7：轮次上限 ----

def test_max_turns_default_is_30():
    assert MAX_TURNS == 30
    assert DEFAULTS["max_turns"] == 30


def test_agent_honors_max_turns_param():
    assert DesktopAgent().max_turns == MAX_TURNS
    assert DesktopAgent(max_turns=5).max_turns == 5
    # 非法值回落默认，不出 0/负数
    assert DesktopAgent(max_turns=0).max_turns == MAX_TURNS


def test_low_turns_hint_injected_before_last_turns(stub_tools):
    """max_turns=3 的任务应收到"还剩 2 轮/1 轮/最后一轮"三轮提示，
    且提示在 LLM 调用前进入对话（模型下一轮就能看见）"""
    agent = DesktopAgent(llm=None, max_turns=3)
    agent.llm = _FakeLLM([
        _tool_call("t1", "clipboard_write", {"text": "a"}),
        _tool_call("t2", "clipboard_write", {"text": "b"}),
        _tool_call("t3", "clipboard_write", {"text": "c"}),
    ])
    result = agent.run("回归：轮次提示")
    assert "最大轮次" in result
    hints = [m for m in agent.messages
             if m.get("role") == "user" and "【系统提示】" in m.get("content", "")]
    assert len(hints) == 3
    assert "还剩 2 轮" in hints[0]["content"]
    assert "还剩 1 轮" in hints[1]["content"]
    assert "最后一轮" in hints[2]["content"]


def test_no_hint_when_turns_are_plentiful(stub_tools):
    """轮次富余（默认 30）时不该提前打扰"""
    agent = DesktopAgent(llm=None)
    agent.llm = _FakeLLM([_tool_call("t1", "clipboard_write", {"text": "a"}),
                          _final()])
    agent.run("回归：无提示")
    hints = [m for m in agent.messages
             if m.get("role") == "user" and "【系统提示】" in m.get("content", "")]
    assert hints == []


# ---- T6：open_url 与确定性失败不重试 ----

@pytest.fixture
def fake_dns(monkeypatch):
    """域名解析桩（服务端请求路径 validate_public_https 的 check_dns=True 用）：
    baidu → 公网；internal.test → 内网；localhost → 环回"""
    import socket as socket_mod

    def fake_getaddrinfo(host, *a, **kw):
        table = {"internal.test": ["10.0.0.5"],
                 "localhost": ["127.0.0.1"],
                 "metadata.google.internal": ["169.254.169.254"]}
        ip = table.get(host, ["93.184.216.34"])[0]
        return [(socket_mod.AF_INET, socket_mod.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr("core.settings.socket.getaddrinfo", fake_getaddrinfo)


def test_validate_public_url_allows_http_rejects_private(fake_dns):
    ok, why = validate_public_url("https://www.baidu.com/", require_https=False)
    assert ok, why
    ok, _ = validate_public_url("http://example.com/page", require_https=False)
    assert ok
    # http 允许、ftp 不允许
    ok, why = validate_public_url("ftp://example.com", require_https=False)
    assert not ok and "http" in why
    # IP 字面量：内网/环回直接拒绝，无需解析
    for bad in ("http://192.168.1.5/", "http://127.0.0.1:8080/",
                "http://169.254.169.254/latest/meta-data/"):
        ok, _ = validate_public_url(bad, require_https=False)
        assert not ok, bad
    # 本地主机名模式直接拒绝（无 DNS 模式下的兜底）
    for bad in ("http://localhost:8080/", "http://router.local/",
                "http://nas.internal/"):
        ok, _ = validate_public_url(bad, require_https=False, check_dns=False)
        assert not ok, bad


def test_browser_open_skips_dns_check_server_path_keeps_it(fake_dns):
    """2026-10-01 实测：系统 DNS 把 github.com 指向 127.0.0.1（拦截策略）而
    浏览器经 DoH/代理可达——浏览器路径不做 DNS 预校验（避免误杀），
    服务端请求路径（云端 API/飞书 webhook）保留 DNS 级校验"""
    # 浏览器路径（check_dns=False）：域名不做本进程解析判定
    ok, why = validate_public_url("http://github.com/trending",
                                  require_https=False, check_dns=False)
    assert ok, why
    # 同一域名走服务端语义（check_dns=True）：解析到内网仍然拒绝
    ok, _ = validate_public_url("http://internal.test/",
                                require_https=False, check_dns=True)
    assert not ok


def test_open_url_rejects_then_opens_public(monkeypatch, fake_dns):
    opened = []
    monkeypatch.setattr(agent_loop.os, "startfile", lambda u: opened.append(u))
    # 字面量内网/环回/本地主机名拒绝且不触发浏览器
    for bad in ("http://192.168.1.5/", "http://localhost:8080/",
                "http://router.local/", "file:///C:/Windows/System32/", ""):
        result = _open_url({"url": bad})
        assert result.startswith("错误"), bad
    assert opened == []
    # 公网域名放行并交给默认浏览器（域名不做本进程 DNS 判定）
    result = _open_url({"url": "https://www.baidu.com/s?wd=weather"})
    assert result.startswith("opened in default browser")
    assert opened == ["https://www.baidu.com/s?wd=weather"]


def test_open_url_risk_is_medium():
    """出网动作按 medium 记录（不拦截不确认），与发飞书同级"""
    risk, reason = guard_evaluate("open_url", {"url": "https://www.baidu.com"})
    assert risk == "medium"
    assert reason


def test_permanent_failure_skips_backoff(no_sleep):
    """白名单拒绝等确定性失败：重试清单内的工具也只执行 1 次"""
    attempts = {"n": 0}

    def always_whitelist_miss():
        attempts["n"] += 1
        return agent_loop._open_app({"app_name": "chrome"})  # T22 起签名是 args 字典

    result, used, ok = run_with_retry(always_whitelist_miss, "open_app",
                                      retryable=True, max_retries=3)
    assert attempts["n"] == 1, "确定性拒绝不该重试"
    assert not ok
    assert "仅支持" in result


def test_transient_failure_still_retries(no_sleep):
    """瞬时失败仍走满退避重试——确认收紧没有误伤重试机制"""
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        return "错误: 窗口未出现"

    _, used, ok = run_with_retry(flaky, "open_app", retryable=True, max_retries=3)
    assert attempts["n"] == 4, "1 次首发 + 3 次重试"
    assert not ok


def test_window_not_found_is_permanent(no_sleep):
    """UIA 助手的"找不到窗口/控件"是确定性失败（2026-10-01 重放实录：
    页面跳转后旧窗口名连续 4 次 UIA 超时、每次约 2 分钟，共烧 8 分钟）"""
    attempts = {"n": 0}

    def stale_window():
        attempts["n"] += 1
        return "错误: 找不到窗口「百度一下，你就知道」。可见窗口有: 今天天气_百度搜索"

    result, used, ok = run_with_retry(stale_window, "list_ui_elements",
                                      retryable=True, max_retries=3)
    assert attempts["n"] == 1
    assert not ok
    assert "找不到窗口" in result


def test_open_app_whitelist_miss_never_retries_end_to_end(tmp_path, no_sleep):
    """端到端：open_app("chrome") 在完整 agent 循环里只产生一次工具调用，
    审计里没有 retry 事件（2026-09-30 晚 12 次无用 retry 的回归保护）"""
    agent = DesktopAgent(llm=None, auditor=AuditLogger(log_dir=tmp_path))
    agent.llm = _FakeLLM([
        _tool_call("t1", "open_app", {"app_name": "chrome"}),
        _final("浏览器打不开，已用其他方式说明"),
    ])
    agent.run("回归：open_app 确定性拒绝")
    entries = _read_audit(tmp_path)
    assert sum(1 for e in entries if e.get("type") == "tool_call") == 1
    assert not [e for e in entries if e.get("type") == "retry"]


def test_system_prompt_forbids_uia_on_browsers():
    """T11 缓解（2026-10-01 重放实录：Chrome 上单次 UIA 调用 121 秒）——
    提示词必须引导模型在浏览器场景绕开 UIA、走视觉路线"""
    prompt = agent_loop.SYSTEM_PROMPT
    assert "浏览器例外" in prompt
    assert "Chrome" in prompt
    assert "禁止" in prompt and "list_ui_elements" in prompt


def test_browser_uia_block():
    """T11 结构性约束：浏览器窗口类直接拒绝 UIA 控件操作。2026-10-01 重放实测
    glm-4-flash 两度无视提示词与工具描述（150 秒/次 × 5），软引导不够——
    在 agent_vision 助手层硬拦，把 150 秒浪费变成一条即时错误"""
    from agent_vision import _browser_uia_block

    class _W:
        def __init__(self, cls):
            self._cls = cls

        def class_name(self):
            return self._cls

    for browser_cls in ("Chrome_WidgetWin_1", "MozillaWindowClass"):
        msg = _browser_uia_block(_W(browser_cls))
        assert "不支持" in msg, browser_cls
    assert _browser_uia_block(_W("Notepad")) == ""


# ---- T8：空回复不得记为 success ----

def test_empty_reply_recorded_as_empty_reply(tmp_path, stub_tools):
    agent = DesktopAgent(llm=None, history=TaskHistory(tmp_path / "h.jsonl"))
    agent.llm = _FakeLLM([{"role": "assistant", "content": "", "tool_calls": []}])
    result = agent.run("回归：空回复")
    assert "模型未返回有效内容" in result
    rec = agent.history.recent(1)[0]
    assert rec["status"] == "empty_reply", "空回复不该落 success（0f38d020 形态）"
    assert rec["status"] not in ("success",)


def test_normal_reply_still_success(tmp_path, stub_tools):
    """防收紧误伤：正常答复仍记 success"""
    agent = DesktopAgent(llm=None, history=TaskHistory(tmp_path / "h.jsonl"))
    agent.llm = _FakeLLM([_final("已把结果整理好放在桌面")])
    agent.run("回归：正常收尾")
    assert agent.history.recent(1)[0]["status"] == "success"


def test_empty_reply_flag_resets_between_tasks(tmp_path, stub_tools):
    """逐任务复位：上一任务空回复不污染下一任务定态"""
    agent = DesktopAgent(llm=None, history=TaskHistory(tmp_path / "h.jsonl"))
    agent.llm = _FakeLLM([{"role": "assistant", "content": "", "tool_calls": []}])
    agent.run("回归：第一条空")
    assert agent.history.recent(1)[0]["status"] == "empty_reply"
    agent.llm = _FakeLLM([_final("这次正常完成")])
    agent.run("回归：第二条正常")
    assert agent.history.recent(1)[0]["status"] == "success"


# ---- 发现 D：history 落 tool_calls 实数（2026-10-01） ----

def test_history_records_tool_calls_count(tmp_path, stub_tools, monkeypatch):
    """发现 D（沙箱用例 5 实录：模型纯文本拒做却记 success）：history 落
    本任务实际工具调用数。0 + success = 对话完成但没动手，GUI 据此打
    "⚠未调用工具"标注；纯问答任务的 success 语义不变（T8 契约保持）"""
    monkeypatch.setattr(agent_loop, "TOOL_FUNCTIONS",
                        {"wait": lambda a: "waited"})

    agent = DesktopAgent(llm=None, history=TaskHistory(tmp_path / "h1.jsonl"))
    agent.llm = _FakeLLM([_final("我目前没有直接操作文件系统的工具，"
                                 "建议您手动处理")])
    agent.run("回归：纯文本答复（零工具）")
    rec = agent.history.recent(1)[0]
    assert rec["status"] == "success"          # 答复语义不变
    assert rec["tool_calls"] == 0              # 但"没动手"可见

    agent2 = DesktopAgent(llm=None, history=TaskHistory(tmp_path / "h2.jsonl"))
    agent2.llm = _FakeLLM([
        _tool_call("t1", "wait", {"seconds": 1}),
        _final("已完成")])
    agent2.run("回归：有动手")
    assert agent2.history.recent(1)[0]["tool_calls"] == 1


# ---- 发现 G′：open_url 支持本地文件夹（2026-10-01） ----

def test_open_url_local_folder(tmp_path, monkeypatch):
    """G′（整理下载用例实录：agent 开了资源管理器只会落在主文件夹，没有
    导航到目标目录的手段）：文件夹路径经 os.startfile 交给资源管理器打开，
    不走公网网址校验"""
    opened = []
    monkeypatch.setattr(agent_loop.os, "startfile", lambda p: opened.append(p))
    out = _open_url({"url": str(tmp_path)})
    assert "opened folder" in out
    assert opened == [str(tmp_path)]


def test_open_url_rejects_local_file(tmp_path):
    """安全红线：os.startfile 对文件会调起关联程序（exe/bat 等会被执行）——
    文件路径一律拒绝，只放行已存在的目录"""
    f = tmp_path / "evil.bat"
    f.write_text("echo hi", encoding="ascii")
    out = _open_url({"url": str(f)})
    assert "只接受本地文件夹" in out


def test_open_url_nonexistent_path_hint(tmp_path):
    """不存在的路径：明确报不存在并提示网址需带 https:// 前缀"""
    out = _open_url({"url": str(tmp_path / "不存在的文件夹")})
    assert "不存在" in out and "https://" in out


# ---- T18：内置 create_folder 工具（2026-10-01，T16 第 5 跑实录催生） ----

@pytest.fixture
def allow_root(monkeypatch, tmp_path):
    """把放行根目录收窄到测试沙箱，测试结果与宿主用户目录布局无关"""
    monkeypatch.setattr(agent_loop, "CREATE_FOLDER_ALLOWED_ROOTS", (tmp_path,))
    return tmp_path


def test_create_folder_creates_nested(allow_root):
    """根目录内一次建多级：返回 created 且目录真实落盘"""
    target = allow_root / "整理" / "文档"
    out = _create_folder({"path": str(target)})
    assert "created folder" in out
    assert target.is_dir()


def test_create_folder_existing_dir_ok(allow_root):
    """已存在同名文件夹按成功返回（"确保存在"语义），模型不会当失败重试"""
    target = allow_root / "已存在"
    target.mkdir()
    out = _create_folder({"path": str(target)})
    assert "already exists" in out


def test_create_folder_rejects_outside_roots(allow_root):
    """放行根目录外一律拒绝（fail-closed），且不落盘"""
    outside = allow_root.parent / "t18_outside_should_not_exist"
    out = _create_folder({"path": str(outside)})
    assert "不支持" in out
    assert not outside.exists()


def test_create_folder_rejects_dotdot_escape(allow_root):
    """路径经 resolve() 归一后校验，".." 逃逸到根目录外被拒"""
    tricky = allow_root / "a" / ".." / ".." / "escaped"
    out = _create_folder({"path": str(tricky)})
    assert "不支持" in out
    assert not (allow_root.parent / "escaped").exists()


def test_create_folder_rejects_relative_and_unc(allow_root):
    """相对路径与 UNC 网络路径直接拒绝（不碰网络资源）"""
    assert "不支持相对路径" in _create_folder({"path": "相对/文件夹"})
    assert "不支持网络路径" in _create_folder({"path": "\\\\server\\share\\x"})


def test_create_folder_rejects_existing_file(allow_root):
    """同名文件占用 → 明确拒绝并给出可读原因（不静默吞掉 mkdir 失败）"""
    f = allow_root / "占用名字.txt"
    f.write_text("x", encoding="ascii")
    out = _create_folder({"path": str(f)})
    assert "同名文件" in out


def test_create_folder_guard_risk_none():
    """定级 none（T18 设计决策）：空文件夹创建无破坏性，不进高危/敏感路径，
    调用与结果照常经 tool_call/tool_result 进审计哈希链"""
    assert guard_evaluate("create_folder", {"path": "C:/x"}) == ("none", "")


def test_create_folder_end_to_end_loop(allow_root):
    """接线冒烟：FakeLLM 驱动完整 _run_loop，risk=none 免确认直接执行落盘"""
    target = allow_root / "下载" / "图片"
    agent = DesktopAgent(llm=None, history=TaskHistory(allow_root / "h.jsonl"))
    agent.llm = _FakeLLM([
        _tool_call("t1", "create_folder", {"path": str(target)}),
        _final("文件夹已建好")])
    out = agent.run("在下载里建个图片文件夹")
    assert "文件夹已建好" in out
    assert target.is_dir()
    assert agent.history.recent(1)[0]["tool_calls"] == 1
