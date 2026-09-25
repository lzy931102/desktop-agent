"""DesktopAgent 发布前冒烟测试：覆盖 core 基础设施与 agent 接入。

运行：python tests_smoke.py
（云端真机用例在存在有效 API Key / 环境变量时自动执行，否则跳过）
"""
import json
import tempfile
import time
from pathlib import Path

from core.audit import AuditLogger
from core.guard import evaluate, is_retryable
from core.retry import run_with_retry, MAX_RETRIES
from core.approval import AutoDenyPolicy, GuiApprovalBridge
from core.history import TaskHistory
from core.scheduler import Scheduler
from core.settings import (Settings, validate_public_https, resolve_api_key)
from core import verify

failures = []


def check(name, cond, detail=""):
    global failures
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# ================= guard（危险操作规则 + 幂等标记） =================
check("guard: delete 按键高危", evaluate("press_key", {"key": "delete"})[0] == "high")
check("guard: alt+f4 高危", evaluate("hotkey", {"keys": ["alt", "f4"]})[0] == "high")
check("guard: 点删除按钮高危",
      evaluate("click_ui_element", {"name": "删除所选"})[0] == "high")
check("guard: 正常操作放行", evaluate("press_key", {"key": "enter"})[0] == "none")
check("guard: 可重试标记", is_retryable("click") and not is_retryable("nonexistent_tool"))

# ================= audit（哈希链） =================
tmp = Path(tempfile.mkdtemp())
audit = AuditLogger(log_dir=tmp)
for i in range(3):
    audit.emit("tool_call", tool="click", args={"x": i, "y": i})
entries = [json.loads(l) for l in
           (tmp / f"audit-{audit._day}.jsonl").read_text(encoding="utf-8").splitlines()]
check("audit: 记录与 seq", len(entries) == 3 and [e["seq"] for e in entries] == [0, 1, 2])
check("audit: 哈希链衔接",
      all(entries[i]["prev"] == entries[i - 1]["hash"] for i in (1, 2)))

# ================= approval =================
bridge = GuiApprovalBridge(timeout=5)
import threading
threading.Thread(target=lambda: (time.sleep(0.1),
                                 (lambda r: bridge.complete(r, True))(bridge.pending())),
                 daemon=True).start()
check("approval: 批准路径", bridge.decide("x", {}, "high", "r") is True)
check("approval: AutoDeny", AutoDenyPolicy().decide("x", {}, "high", "r") is False)

# ================= history =================
hist = TaskHistory(file_path=tmp / "h.jsonl")
tid = hist.start("打开计算器")
hist.end(tid, "success", "计算器已打开", turns=2, elapsed_s=19.5)
rows = hist.recent()
check("history: 记录与回看", rows[0]["id"] == tid and rows[0]["status"] == "success")

# ================= retry =================
calls = {"n": 0}
def flaky():
    calls["n"] += 1
    if calls["n"] < 3:
        return "错误: 偶发失败"
    return "opened calc"
result, attempts, ok = run_with_retry(flaky, "open_app", True)
check("retry: 重试后成功", ok and attempts == 3)
result, attempts, ok = run_with_retry(lambda: "错误: 持续失败", "click", True)
check("retry: 3 次耗尽", attempts == MAX_RETRIES + 1 and not ok)
_, attempts, _ = run_with_retry(lambda: "错误: 高危失败", "press_key", False)
check("retry: 高危不重试", attempts == 1)

# ================= verify =================
check("verify: 文件存在", verify.verify_file_exists(__file__)[0] is True)
check("verify: 文件缺失", verify.verify_file_exists("_no_such__.xyz")[0] is False)

# ================= scheduler =================
sched = Scheduler(on_due=lambda t: None, file_path=tmp / "st.json")
sched.add("打开计算器", "interval", interval_minutes=30)
recs = sched.load()
recs[0]["last_run"] = time.time() - 31 * 60
sched.save(recs)
check("scheduler: 间隔到点触发", len(sched.check_due()) == 1)
check("scheduler: 触发后不重复", len(sched.check_due()) == 0)

# ================= settings / url / 工厂 / fallback =================
st = Settings(file_path=tmp / "s.json")
check("settings: 默认 local 模式", st.get("model_mode") == "local")
check("url: https 公网通过", validate_public_https("https://open.bigmodel.cn/api")[0])
check("url: 内网拒绝", not validate_public_https("https://192.168.1.10/v1")[0])
check("url: 环回拒绝", not validate_public_https("https://127.0.0.1/v1")[0])

# ================= feishu（webhook 通知通道） =================
from unittest import mock
from core.feishu import validate_webhook, send_feishu_message
import agent_loop as _al
check("feishu: 未配置给提示", "未配置" in validate_webhook(""))
check("feishu: http 拒绝", "https" in validate_webhook("http://open.feishu.cn/hook/x"))
check("feishu: 非官方域名拒绝", "官方域名" in validate_webhook("https://example.com/hook"))
check("feishu: 假冒子域拒绝",
      "官方域名" in validate_webhook("https://open.feishu.cn.evil.com/hook"))
check("feishu: 官方域名通过",
      validate_webhook("https://open.feishu.cn/open-apis/bot/v2/hook/xxxx") is None)

class _FeishuResp:
    status_code = 200
    def json(self):
        return {"code": 0, "msg": "success"}
with mock.patch.object(_al.requests, "post", return_value=_FeishuResp()) as mp:
    ok, detail = send_feishu_message(
        "你好", "https://open.feishu.cn/open-apis/bot/v2/hook/xxxx")
check("feishu: 发送成功解析", ok and detail == "已发送到飞书群")
check("feishu: 请求体格式", mp.call_args.kwargs["json"] ==
      {"msg_type": "text", "content": {"text": "你好"}})
check("feishu: agent 工具已注册",
      any(f["function"]["name"] == "send_feishu_message" for f in _al.TOOLS_SCHEMA)
      and "send_feishu_message" in _al.TOOL_FUNCTIONS)

from agent_loop import (build_llm_client, LLMClient, LLMConfig, LLMProvider,
                        FallbackLLMClient)
c = build_llm_client(st)
check("factory: local 模式", isinstance(c, LLMClient)
      and c.config.provider == LLMProvider.OLLAMA)

s_cloud = Settings(file_path=tmp / "cloud.json")
s_cloud.set("model_mode", "cloud")
s_cloud.set("cloud", {"provider": "openai", "api_key": ""})
try:
    build_llm_client(s_cloud)
    check("factory: cloud 无 key 报错", False)
except RuntimeError:
    check("factory: cloud 无 key 报错", True)

s_auto = Settings(file_path=tmp / "auto.json")
s_auto.set("model_mode", "auto")
s_auto.set("cloud", {"provider": "openai", "api_key": ""})
check("factory: auto 无 key 降级本地",
      build_llm_client(s_auto).config.provider == LLMProvider.OLLAMA)

class FakeClient:
    def __init__(self, behavior):
        self.behavior, self.calls, self.config = behavior, 0, None
    def chat(self, messages, tools=None):
        self.calls += 1
        if self.behavior == "fail":
            raise RuntimeError("boom")
        return {"role": "assistant", "content": "ok", "tool_calls": []}

loc, cld = FakeClient("fail"), FakeClient("ok")
resp = FallbackLLMClient(loc, cld).chat([{"role": "user", "content": "hi"}])
check("fallback: 本地失败切云端", resp["content"] == "ok" and loc.calls == 1 and cld.calls == 1)

# ================= 云端真机（有凭据才跑） =================
key, src = resolve_api_key(Settings().get("cloud"))
if key:
    from agent_loop import TOOLS_SCHEMA
    cloud_cfg = Settings().get("cloud")
    cc = LLMClient(LLMConfig(provider=LLMProvider("zhipu"), api_key=key,
                             base_url=cloud_cfg.get("base_url"),
                             model=cloud_cfg.get("model")))
    ok, msg = cc.ping()
    check("cloud: 智谱 ping", ok, msg)
    if ok:
        r = cc.chat([{"role": "user", "content": "请帮我打开计算器"}], TOOLS_SCHEMA)
        check("cloud: 智谱 tool_calls",
              bool(r.get("tool_calls")) and
              r["tool_calls"][0]["function"]["name"] == "open_app")
else:
    print("SKIP cloud: 本机未配置云端凭据")

print()
print("RESULT:", "ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}")
raise SystemExit(0 if not failures else 1)
