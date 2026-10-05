"""agent_loop 对 guard 分级的处理路径回归测试（issue #2：medium 落地验证）。

用假 LLM（沿用 e2e/test_early_stop.py 的 mock 模式）+ 桩工具注册表驱动
DesktopAgent._run_loop，验证三条分级路径互不等价：

- high  ：走 approval（AutoDenyPolicy 下被拒），工具不执行
- medium：不拦截、工具正常执行，但触发 medium_risk 审计事件
          + "[敏感操作]" 界面提示行
- none  ：静默执行，无 medium_risk 事件、无提示行

修复前行为：agent_loop 只处理 risk == "high"，medium 与 none 完全等价
（无审计事件、无提示，静默执行）。
"""
import ast
import hashlib
import json
import time
from pathlib import Path

import pytest

import agent_loop
import agent_vision
from agent_loop import DesktopAgent
from core.audit import AuditLogger
from core.approval import AutoDenyPolicy
from core.settings import cloud_ready, should_show_onboarding


class _FakeLLM:
    """按序返回预设响应的最小 LLM 桩"""

    def __init__(self, responses):
        self._responses = list(responses)

    def chat(self, messages, tools):
        return self._responses.pop(0)


class _StubTool:
    """记录调用参数的工具桩"""

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
def env(tmp_path, monkeypatch):
    """桩工具注册表 + 桩动作后校验（避免读写真实剪贴板/屏幕）"""
    stub = _StubTool()
    monkeypatch.setattr(agent_loop, "TOOL_FUNCTIONS",
                        {"clipboard_write": stub, "press_key": stub})
    monkeypatch.setattr(agent_loop.core_verify, "verify_clipboard",
                        lambda text: (True, "stub"))
    logs = []
    auditor = AuditLogger(log_dir=tmp_path)
    agent = DesktopAgent(llm=None, auditor=auditor, approval=AutoDenyPolicy())
    agent.on_log = logs.append
    return agent, stub, logs, tmp_path


def _run(agent, responses):
    agent.llm = _FakeLLM(responses)
    return agent.run("回归测试任务")


def test_medium_executes_with_audit_and_hint(env):
    """medium 命中：照常执行（不拦截），但必须留下审计事件 + 界面提示。
    修复前：与 none 等价——静默执行，无 medium_risk 事件、无提示行。"""
    agent, stub, logs, tmp_path = env
    result = _run(agent, [
        _tool_call("c1", "clipboard_write", {"text": "my password is 123"}),
        _final(),
    ])
    assert len(stub.calls) == 1                       # 不拦截：确实执行了
    assert result == "任务完成"
    assert any("[敏感操作]" in m and "clipboard_write" in m for m in logs)
    entries = _read_audit(tmp_path)
    medium = [e for e in entries if e["type"] == "medium_risk"]
    assert len(medium) == 1
    assert medium[0]["tool"] == "clipboard_write"
    assert "敏感词" in medium[0]["reason"]


def test_medium_hint_deduped_but_audit_every_time(env):
    """降噪（UX-P1-8）：同一来源一次会话只提示首次；审计每次照记、执行不衰减。
    修复前：每次 medium 调用都刷一行"[敏感操作] …已放行"。"""
    agent, stub, logs, tmp_path = env
    result = _run(agent, [
        _tool_call("c1", "clipboard_write", {"text": "password one"}),
        _tool_call("c2", "clipboard_write", {"text": "password two"}),
        _final(),
    ])
    assert result == "任务完成"
    assert len(stub.calls) == 2                     # 降噪只作用于提示行，不拦执行
    hints = [m for m in logs if "[敏感操作]" in m and "clipboard_write" in m]
    assert len(hints) == 1                          # 同一工具只提示首次
    entries = _read_audit(tmp_path)
    medium = [e for e in entries if e["type"] == "medium_risk"]
    assert len(medium) == 2                         # 审计不受降噪影响


def test_none_stays_silent(env):
    """对照组：none（无敏感词）不产生 medium_risk 事件、无提示行。"""
    agent, stub, logs, tmp_path = env
    _run(agent, [
        _tool_call("c1", "clipboard_write", {"text": "hello world"}),
        _final(),
    ])
    assert len(stub.calls) == 1
    assert not any("敏感操作" in m for m in logs)
    assert not any(e["type"] == "medium_risk"
                   for e in _read_audit(tmp_path))


def test_high_goes_to_approval_and_denied(env):
    """对照组：high 仍走 approval；AutoDenyPolicy 下被拒，工具不执行。
    medium 分支不得把 high 的行为改掉。"""
    agent, stub, logs, tmp_path = env
    _run(agent, [
        _tool_call("c1", "press_key", {"key": "delete"}),
        _final(),
    ])
    assert stub.calls == []                           # 被拒：未执行
    assert any("[拦截]" in m for m in logs)
    entries = _read_audit(tmp_path)
    approval = [e for e in entries if e["type"] == "approval"]
    assert len(approval) == 1 and approval[0]["allowed"] is False
    assert not any(e["type"] == "medium_risk" for e in entries)


def test_medium_without_auditor_still_executes(env, monkeypatch):
    """无审计注入时 medium 不应报错：降级为仅界面提示，操作照常。"""
    agent, stub, logs, _ = env
    monkeypatch.setattr(agent, "auditor", None)
    result = _run(agent, [
        _tool_call("c1", "clipboard_write", {"text": "我的密码"}),
        _final(),
    ])
    assert len(stub.calls) == 1
    assert result == "任务完成"
    assert any("[敏感操作]" in m for m in logs)


# ================= wait 工具：上限钳位 + 分段停止（UX-P1-4） =================

def test_wait_clamps_seconds_to_60(monkeypatch):
    """seconds=100000 不许真睡：钳到 WAIT_MAX_SECONDS。

    生产上限是 60 秒（真等 60 秒套件受不了），这里把上限压小验证
    "大输入被钳到上限、而不是按输入睡"这一行为本身。
    """
    monkeypatch.setattr(agent_loop, "WAIT_MAX_SECONDS", 0.05)
    start = time.monotonic()
    result = agent_loop._wait_tool({"seconds": 100000})
    assert time.monotonic() - start < 5
    assert result == "waited 0.05s"


def test_wait_garbage_and_negative_seconds():
    """非法/负数输入不抛异常：非法按 1 秒，负数按 0 秒（立即返回）。"""
    assert agent_loop._wait_tool({"seconds": "abc"}) == "waited 1s"
    assert agent_loop._wait_tool({"seconds": None}) == "waited 1s"
    assert agent_loop._wait_tool({"seconds": -5}) == "waited 0s"


def test_wait_stop_flag_breaks_sleep_quickly():
    """sleep 期间停止标志已置位 → 秒级返回，不等睡满。"""
    start = time.monotonic()
    result = agent_loop._wait_tool({"seconds": 60}, stop_requested=lambda: True)
    assert time.monotonic() - start < 2
    assert "停止" in result


def test_wait_checks_stop_each_segment_not_zero_times():
    """停止标志在第 2 秒才翻转 → 应睡满约 2 秒后返回，证明分段检查真的在跑。"""
    start = time.monotonic()
    flip_at = start + 2.0

    result = agent_loop._wait_tool(
        {"seconds": 60},
        stop_requested=lambda: time.monotonic() >= flip_at)
    elapsed = time.monotonic() - start
    assert elapsed >= 1.9
    assert "停止" in result


def test_execute_tool_wait_honors_agent_stop_flag():
    """接线回归：_execute_tool 必须把 self 的停止标志传给 wait（防止特判被删）。"""
    agent = DesktopAgent()
    agent._stop_requested = True
    start = time.monotonic()
    result = agent._execute_tool("wait", {"seconds": 100000}, "none")
    assert time.monotonic() - start < 2
    assert "停止" in result


# ============ 审计哈希链续链 + 界面失败判定收敛（REL-P1-1 / REL-P1-2） ============

def _chain_verified(entries):
    """全链校验：seq 递增无重复、prev 逐条相接、每条哈希可复算。"""
    prev = ""
    seqs = []
    for e in entries:
        assert e["prev"] == prev
        check = {k: v for k, v in e.items() if k != "hash"}
        digest = hashlib.sha256(json.dumps(
            check, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16]
        assert digest == e["hash"]
        prev = e["hash"]
        seqs.append(e["seq"])
    assert seqs == sorted(set(seqs))   # 递增且无重复
    return seqs


def test_audit_chain_resumes_after_same_day_restart(tmp_path):
    """同日重启续链（REL-P1-1）：写两条 → 重建实例 → 再写一条，全文件
    哈希链校验通过、seq 递增无重复；文件尾损坏时照常续链，但新条目带
    chain_repaired 标记（不静默）。
    修复前：重建实例从 seq=0/prev="" 起链——同日重启后 seq 重复、链断裂，
    防篡改无法区分"重启"与"篡改"。"""
    a = AuditLogger(log_dir=tmp_path)
    a.emit("task_start", task="任务A")
    a.emit("tool_call", tool="click")
    a.close()

    b = AuditLogger(log_dir=tmp_path)   # 重建实例，模拟同日重启
    b.emit("tool_result", tool="click", result="ok")
    b.close()

    entries = _read_audit(tmp_path)
    assert len(entries) == 3
    assert _chain_verified(entries) == [0, 1, 2]      # 修复前：0,1,0

    # 文件尾损坏（篡改行，不带换行尾——即崩溃半行的形态）：原样留在文件，
    # 从最后一条可验证记录续链，下一条如实标记 chain_repaired
    day_file = tmp_path / f"audit-{time.strftime('%Y%m%d')}.jsonl"
    with open(day_file, "a", encoding="utf-8") as f:
        f.write('{"ts": "tampered", "type": "tool_call", "seq": 99}')
    c = AuditLogger(log_dir=tmp_path)
    c.emit("approval", tool="del")
    c.close()

    good = [json.loads(l) for l in day_file.read_text(
        encoding="utf-8").splitlines() if l.strip() and "hash" in json.loads(l)]
    assert len(good) == 4
    assert _chain_verified(good) == [0, 1, 2, 3]      # 损坏行不占用 seq
    assert all("chain_repaired" not in e for e in good[:3])
    assert good[-1]["chain_repaired"] is True


def test_gui_tool_result_judgement_uses_is_failed_result():
    """界面侧失败判定与重试层同源（REL-P1-2）："failed to connect" 不带
    "错误" 前缀，修复前 startswith("错误") 判定漏放——界面打 ✓、重试层
    （is_failed_result）判失败，两套语义；收敛后界面必须同样判负。"""
    from gui import AgentGUI, TaskSession

    app = AgentGUI.__new__(AgentGUI)   # 绕过 __init__：不建 Tk 窗口，只测状态逻辑
    app.active = None                  # 非当前 Tab → 不触碰 chat 控件
    app._log_line = lambda *a, **k: None

    def _apply(result):
        s = TaskSession("判定回归")
        ev = s.add("tool", name="open_app", args={}, state="run",
                   result="", note="", img=None)
        AgentGUI._apply_tool_result(app, s, "open_app", {}, result)
        return ev

    # 文档点名的形态：不带"错误"前缀的失败（修复前在这里打 ✓）
    assert _apply("无法连接模型服务: failed to connect to Ollama")["state"] == "err"
    assert _apply("错误: 未知工具 foo")["state"] == "err"   # 传统前缀形态仍判负
    assert _apply("已打开 记事本")["state"] == "ok"          # 正常结果不误伤


# ================= 首启引导判定状态机（UX-P1-6，core/settings） =================

@pytest.fixture
def no_cloud_env(monkeypatch):
    """清掉云端 Key 环境变量：cloud_ready 只看 settings 里存没存"""
    from core.settings import CLOUD_PRESETS
    for preset in CLOUD_PRESETS.values():
        monkeypatch.delenv(preset["env"], raising=False)


def _bare_settings(tmp_path):
    from core.settings import Settings
    return Settings(file_path=tmp_path / "settings.json")


def test_onboarding_fresh_user_gets_card(tmp_path, no_cloud_env):
    """清空配置首启（无 Ollama、无 Key）→ 弹引导卡；连上了就不弹"""
    s = _bare_settings(tmp_path)
    assert cloud_ready(s) is False
    assert should_show_onboarding(s, connected=False) is True
    assert should_show_onboarding(s, connected=True) is False


def test_onboarding_veteran_with_cloud_key_not_disturbed(tmp_path, no_cloud_env,
                                                         monkeypatch):
    """已配好云端路径的老用户不弹：settings 存了 Key，或对应环境变量有值"""
    s = _bare_settings(tmp_path)
    s.set("cloud", {"provider": "zhipu", "api_key": "sk-test"})
    assert cloud_ready(s) is True
    assert should_show_onboarding(s, connected=False) is False

    s2 = _bare_settings(tmp_path)
    monkeypatch.setenv("ZHIPU_API_KEY", "env-key")
    assert cloud_ready(s2) is True
    assert should_show_onboarding(s2, connected=False) is False


def test_onboarding_later_reminds_once_then_stops(tmp_path, no_cloud_env):
    """"稍后再说"状态机：later 下次启动仍提醒一次，dismissed 后不再打扰。
    later→dismissed 的推进发生在 GUI 弹出前（gui._show_onboarding）。"""
    s = _bare_settings(tmp_path)
    assert should_show_onboarding(s, connected=False) is True    # 首启
    s.set("onboarding_choice", "later")
    assert should_show_onboarding(s, connected=False) is True    # 最后一次提醒
    s.set("onboarding_choice", "dismissed")
    assert should_show_onboarding(s, connected=False) is False   # 不再自动弹
    for chosen in ("cloud", "local"):
        s.set("onboarding_choice", chosen)
        assert should_show_onboarding(s, connected=False) is False


# ================= 出网代理策略一致性（SEC-P1-2：trust_env=False 全覆盖） =================

_ONE_SHOT_HTTP_ATTRS = {"get", "post", "put", "patch", "delete", "head", "options", "request"}
_POLICY_SCAN_SUBDIRS = ("core", "skill_system", "plugin_system", "phone_bridge")


def _production_py_files():
    """策略扫描范围：随包发布的源码 = 根目录 *.py（排除 test_*）+ 四个子包。
    agent/（gitignore 的旧架构遗留，待任务 14 出清单）与 build/dist 等产物不扫。"""
    root = Path(__file__).resolve().parent
    files = [p for p in root.glob("*.py") if not p.name.startswith("test_")]
    for sub in _POLICY_SCAN_SUBDIRS:
        files.extend(p for p in (root / sub).rglob("*.py")
                     if "__pycache__" not in p.parts)
    return files


def _is_requests_session_call(node):
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Session"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "requests")


def _target_key(node):
    """赋值目标的归一化键：剥离 Store/Load 上下文，只比较变量名/属性链"""
    if isinstance(node, ast.Name):
        return ("name", node.id)
    if isinstance(node, ast.Attribute):
        return ("attr", _target_key(node.value), node.attr)
    return ("other", ast.dump(node))


def _sets_trust_env_false(stmt, owners):
    """stmt 是否为 `owners[0].trust_env = False`，且赋值对象就是刚创建的会话"""
    if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1):
        return False
    target = stmt.targets[0]
    return (isinstance(target, ast.Attribute) and target.attr == "trust_env"
            and len(owners) == 1
            and isinstance(owners[0], (ast.Name, ast.Attribute))
            and _target_key(target.value) == _target_key(owners[0])
            and isinstance(stmt.value, ast.Constant) and stmt.value.value is False)


def _statement_lists(tree):
    """所有语句列表（函数/类/分支/异常处理器体），供"创建后紧跟配置"的成对检查"""
    for node in ast.walk(tree):
        for attr in ("body", "orelse", "finalbody"):
            stmts = getattr(node, attr, None)
            if (isinstance(stmts, list) and stmts
                    and all(isinstance(s, ast.stmt) for s in stmts)):
                yield stmts
        for handler in getattr(node, "handlers", None) or []:
            yield handler.body


def test_all_network_call_points_disable_trust_env():
    """SEC-P1-2 一致性回归：生产代码所有 requests 网络出口必须 trust_env=False。

    trust_env 不是请求级参数——给 requests.post 这类一次性调用直接传
    trust_env 会 TypeError，统一策略只能落在 Session 上，故用两条 AST 规则表达：
    1) 禁止裸 requests.get/post/... 一次性调用（必须经配置过的 Session）；
    2) 每处 requests.Session() 创建后必须紧跟 trust_env=False（赋值形/with 形都认）。
    未来新增网络出口漏配会在此红灯；测试脚本（test_*）不在约束范围。
    """
    problems, configured = [], 0
    scanned = set()
    root = Path(__file__).resolve().parent
    for path in _production_py_files():
        rel = path.relative_to(root).as_posix()
        scanned.add(rel)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in _ONE_SHOT_HTTP_ATTRS
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "requests"):
                problems.append(f"{rel}:{node.lineno} 裸 requests.{node.func.attr} 一次性调用")
        for stmts in _statement_lists(tree):
            for i, stmt in enumerate(stmts):
                if (isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)
                        and _is_requests_session_call(stmt.value)):
                    nxt = stmts[i + 1] if i + 1 < len(stmts) else None
                    if _sets_trust_env_false(nxt, stmt.targets):
                        configured += 1
                    else:
                        problems.append(
                            f"{rel}:{stmt.lineno} requests.Session 创建后未紧跟 trust_env=False")
                elif isinstance(stmt, ast.With):
                    for item in stmt.items:
                        if (item.optional_vars is not None
                                and isinstance(item.context_expr, ast.Call)
                                and _is_requests_session_call(item.context_expr)):
                            first = stmt.body[0] if stmt.body else None
                            if _sets_trust_env_false(first, [item.optional_vars]):
                                configured += 1
                            else:
                                problems.append(
                                    f"{rel}:{stmt.lineno} with requests.Session 体内首行未设 trust_env=False")

    # 扫描面自检：已知网络出口文件必须在内、合规出口必须够数（防扫描路径写错静默通过）
    # （ai_brain.py 为遗留模块，已于任务 14 清理删除，不再在扫描面内）
    for must in ("agent_loop.py", "agent_vision.py",
                 "core/feishu.py", "skill_system/manager.py"):
        assert must in scanned, f"策略扫描漏掉了 {must}"
    assert configured >= 5, f"合规 Session 出口仅 {configured} 处，扫描可能失效"
    assert not problems, "存在未按统一策略出网的调用点：\n" + "\n".join(problems)


# ==================== click 校验分级接线（REL-P1-4，任务 17） ====================

from core import retry as core_retry


def _click_agent(tmp_path, monkeypatch, capture, strong_results):
    """构造关键点击测试环境：UIA 采集与强校验全部打桩，click 不碰真鼠标。

    capture: capture_click_target 的返回值；strong_results: 强校验按次序返回值。
    返回 (agent, logs, tmp_path)。
    """
    monkeypatch.setattr(agent_loop, "TOOL_FUNCTIONS",
                        {"click": lambda args: "clicked at (5, 5)"})
    monkeypatch.setattr(agent_loop.pyautogui, "screenshot", lambda: None)
    monkeypatch.setattr(agent_loop.core_verify, "capture_click_target",
                        lambda x, y: capture)
    seq = list(strong_results)

    def fake_strong(info, before_img, threshold=0.004):
        return seq.pop(0) if len(seq) > 1 else seq[0]
    monkeypatch.setattr(agent_loop.core_verify, "verify_click_strong", fake_strong)
    monkeypatch.setattr(core_retry.time, "sleep", lambda s: None)

    logs = []
    auditor = AuditLogger(log_dir=tmp_path)
    agent = DesktopAgent(llm=None, auditor=auditor, approval=AutoDenyPolicy())
    agent.on_log = logs.append
    return agent, logs, tmp_path


def test_critical_click_verify_fail_triggers_retry(tmp_path, monkeypatch):
    """关键点击确定落空（控件无变化且像素无变化）→ 判失败并触发既定重试策略：
    第二次尝试强通过即收敛，审计链留 retry + verify 事件。"""
    capture = ("critical", {"x": 5, "y": 5, "runtime_id": [42],
                            "control_type": "Button", "name": "确定",
                            "was_focused": False})
    agent, logs, tmp_path = _click_agent(
        tmp_path, monkeypatch, capture,
        [(False, "强校验失败：测试桩", "fail"),
         (True, "强校验通过：测试桩", "strong")])
    result = _run(agent, [
        _tool_call("c1", "click", {"x": 5, "y": 5}),
        _final(),
    ])
    assert result == "任务完成"
    assert "错误" not in "".join(logs) or any("重试" in m for m in logs)
    entries = _read_audit(tmp_path)
    retries = [e for e in entries if e["type"] == "retry"]
    verifies = [e for e in entries if e["type"] == "verify"]
    assert len(retries) == 1 and retries[0]["tool"] == "click"   # 落空后重试了一次
    assert [v["ok"] for v in verifies] == [False, True]          # 两次校验都进链


def test_critical_click_weak_pass_no_retry(tmp_path, monkeypatch):
    """元素原样但界面在动（动画/计时器）→ 弱校验通过：不重试（防重复提交），
    标注随工具结果返回给模型。"""
    capture = ("critical", {"x": 5, "y": 5, "runtime_id": [42],
                            "control_type": "Button", "name": "发送",
                            "was_focused": False})
    agent, logs, tmp_path = _click_agent(
        tmp_path, monkeypatch, capture,
        [(True, "弱校验：目标控件无变化，仅界面像素有变化", "weak")])
    result = _run(agent, [
        _tool_call("c1", "click", {"x": 5, "y": 5}),
        _final(),
    ])
    assert result == "任务完成"
    assert "弱校验" in "".join(logs)
    entries = _read_audit(tmp_path)
    assert not [e for e in entries if e["type"] == "retry"]      # 无重试
    verifies = [e for e in entries if e["type"] == "verify"]
    assert len(verifies) == 1 and verifies[0]["ok"] is True


def test_plain_click_keeps_pixel_verify(tmp_path, monkeypatch):
    """回归：点在空白处（plain）走旧像素校验路径，不触发强校验"""
    calls = {"strong": 0, "old": 0}

    def fake_old(before_img, threshold=0.004):
        calls["old"] += 1
        return True, "界面已变化（差异 2.0%）"

    capture = ("plain", None)
    monkeypatch.setattr(agent_loop, "TOOL_FUNCTIONS",
                        {"click": lambda args: "clicked at (5, 5)"})
    monkeypatch.setattr(agent_loop.pyautogui, "screenshot", lambda: object())
    monkeypatch.setattr(agent_loop.core_verify, "capture_click_target",
                        lambda x, y: capture)
    monkeypatch.setattr(agent_loop.core_verify, "verify_click", fake_old)

    def fake_strong(info, before_img, threshold=0.004):
        calls["strong"] += 1
        return True, "强校验", "strong"
    monkeypatch.setattr(agent_loop.core_verify, "verify_click_strong", fake_strong)
    monkeypatch.setattr(core_retry.time, "sleep", lambda s: None)

    logs = []
    agent = DesktopAgent(llm=None, auditor=AuditLogger(log_dir=tmp_path),
                         approval=AutoDenyPolicy())
    agent.on_log = logs.append
    result = _run(agent, [
        _tool_call("c1", "click", {"x": 5, "y": 5}),
        _final(),
    ])
    assert result == "任务完成"
    assert calls["old"] == 1 and calls["strong"] == 0            # 走旧路径，未进强校验


# ==================== retry 审计带失败原因（T10，2026-10-01） ====================

def test_retry_audit_record_carries_reason(monkeypatch):
    """T10：retry 审计记录自带当次失败文本（截断 120 字），排障无需再按
    seq 前后拼接 tool_result 才能还原原因。"""
    monkeypatch.setattr(core_retry.time, "sleep", lambda s: None)
    events = []

    class _StubAuditor:
        def emit(self, type, **kw):
            events.append((type, kw))

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            return "错误: 窗口还没出现"
        return "ok"

    result, attempts, ok = core_retry.run_with_retry(
        flaky, "open_app", True, auditor=_StubAuditor(), on_retry=lambda *a: None)
    assert ok and attempts == 2 and result == "ok"
    retries = [kw for t, kw in events if t == "retry"]
    assert len(retries) == 1 and retries[0]["tool"] == "open_app"
    assert "窗口还没出现" in retries[0]["reason"]


def test_retry_audit_reason_truncated(monkeypatch):
    """超长失败文本截断到 120 字符，审计行不吞整个 tool_result"""
    monkeypatch.setattr(core_retry.time, "sleep", lambda s: None)
    events = []

    class _StubAuditor:
        def emit(self, type, **kw):
            events.append((type, kw))

    core_retry.run_with_retry(lambda: "错误: " + "长" * 300, "wait", True,
                              auditor=_StubAuditor(), on_retry=lambda *a: None,
                              max_retries=1)
    reason = next(kw for t, kw in events if t == "retry")["reason"]
    assert len(reason) == 120 and reason.endswith("长")


# ==================== 发现 A：type_text 回显必须无歧义完整（2026-10-01） ====================

def test_type_text_echo_explicit_complete(monkeypatch):
    """发现 A（重放实录：回显截断 50 字符 → 模型误以为没输完，同一内容
    重输 6 遍烧 12 轮）：短文本全文回显 + 明确字数；长文本明确字数不回显"""
    monkeypatch.setattr(agent_loop, "_type_text_with_space",
                        lambda text, interval, target_hwnd=0: "")
    short = agent_loop.TOOL_FUNCTIONS["type_text"]({"text": "345"})
    assert "typed: 345" in short and "已完整输入" in short
    long_msg = agent_loop.TOOL_FUNCTIONS["type_text"]({"text": "长" * 200})
    assert "已完整输入 200 字符" in long_msg
    assert ("长" * 10) not in long_msg      # 长文本不回显，杜绝"看起来被截断"


# ==================== 发现 G③：同参同错熔断（2026-10-01 真实用例） ====================

def test_same_args_same_error_breaks_loop(env):
    """focus_window「匹配到多个」后模型原样重试 20+ 次烧光轮次——
    同参同错第 3 次必须注入熔断提示，且同一次连击只注入一次"""
    agent, stub, logs, tmp_path = env

    def always_fail(args):
        return "错误: 匹配到多个窗口"

    agent_loop.TOOL_FUNCTIONS["press_key"] = always_fail
    _run(agent, [
        _tool_call("k1", "press_key", {"key": "enter"}),
        _tool_call("k2", "press_key", {"key": "enter"}),
        _tool_call("k3", "press_key", {"key": "enter"}),
        _tool_call("k4", "press_key", {"key": "enter"}),
        _final(),
    ])
    prompts = [m["content"] for m in agent.messages
               if m["role"] == "user" and "连续 3 次" in m.get("content", "")]
    assert len(prompts) == 1, "同一次连击只注入一次熔断提示"


# ==================== 发现 G②：open_app 校验轮询 + explorer 标题词 ====================

def test_verify_open_app_polls_until_window(monkeypatch):
    """应用冷启动慢：校验从"只查一次"改为轮询（最多 4 秒），窗口晚到不假阴性"""
    seq = [[], [], ["主文件夹 - 文件资源管理器"]]
    monkeypatch.setattr(agent_loop.core_verify, "_window_titles",
                        lambda: seq.pop(0) if len(seq) > 1 else seq[0])
    monkeypatch.setattr(agent_loop.core_verify.time, "sleep", lambda s: None)
    ok, _ = agent_loop.core_verify.verify_open_app("explorer")
    assert ok


def test_verify_open_app_explorer_hint_matches(monkeypatch):
    """explorer 的中文窗口标题必须能命中（修复前关键词表为空、exe 名兜底
    也命不中中文标题——校验对 explorer 永远假阴性）"""
    monkeypatch.setattr(agent_loop.core_verify, "_window_titles",
                        lambda: ["主文件夹 - 文件资源管理器"])
    ok, _ = agent_loop.core_verify.verify_open_app("explorer")
    assert ok


# ==================== 发现 B：analyze_screen 默认限定活动窗口（2026-10-01） ====================

def _vision_with_stub(monkeypatch, captured, fg_rect):
    """构造云端视觉实例：截屏/前台矩形/云端应答全部打桩"""
    import agent_vision

    class _Img:
        def __init__(self, size):
            self.size = size

        def crop(self, box):
            return _Img((box[2] - box[0], box[3] - box[1]))

        def convert(self, mode):
            return self

        def save(self, buf, format=None, **kwargs):
            # 编码长度随图像尺寸变化：裁剪与否可以从 b64 长度区分
            buf.write(b"x" * (self.size[0] * self.size[1] // 100))

    monkeypatch.setattr(agent_vision.pyautogui, "screenshot",
                        lambda: _Img((400, 300)))
    monkeypatch.setattr(agent_vision, "_foreground_rect", lambda: fg_rect)
    cfg = {"mode": "cloud", "width": 1600, "timeout": 5,
           "cloud_base_url": "https://x", "cloud_api_key": "k",
           "cloud_model": "m"}
    v = agent_vision.ScreenVision(cfg=cfg)
    monkeypatch.setattr(v, "_ask_cloud",
                        lambda q, b64, t: (captured.setdefault("len", len(b64)), None)[::-1])
    return v


def test_analyze_screen_crops_to_foreground(monkeypatch):
    """发现 B（重放实录：全屏截图把无关窗口文字读进视觉结果，任务 3 编造
    项目名、任务 4 串扰记事本旧内容）：默认裁到前台窗口，full 才看整屏"""
    captured = {}
    v = _vision_with_stub(monkeypatch, captured, (50, 60, 350, 260))
    v.ask("测试", scope="active")
    active_len = captured["len"]
    captured.clear()
    v.ask("测试", scope="full")
    full_len = captured["len"]
    assert active_len < full_len          # 裁剪图更小 → 编码更短


def test_crop_fallback_tiny_or_missing_rect(monkeypatch):
    """前台窗口过小（最小化/异常）或取不到 → 回退整屏，不裁出废图"""
    captured = {}
    v = _vision_with_stub(monkeypatch, captured, (10, 10, 30, 20))
    v.ask("测试", scope="active")
    tiny_len = captured["len"]
    captured.clear()
    monkeypatch.setattr(agent_vision, "_foreground_rect", lambda: None)
    v.ask("测试", scope="active")
    none_len = captured["len"]
    assert tiny_len == none_len           # 两者都回退了整屏


# ==================== T16：explorer 工作流提示（2026-10-01） ====================

def test_system_prompt_has_explorer_shortcuts():
    """T16（第 4 跑实录：模型在控件列表里找不到"文档"类名字，30 轮建不出
    一个子文件夹）：SYSTEM_PROMPT 必须给出快捷键路线（Ctrl+Shift+N/
    Ctrl+X/V/F2）与"控件名随视图变化、每步先确认"的告诫"""
    assert "Ctrl+Shift+N" in agent_loop.SYSTEM_PROMPT
    assert "Ctrl+V" in agent_loop.SYSTEM_PROMPT
    assert "文件资源管理器提示" in agent_loop.SYSTEM_PROMPT
