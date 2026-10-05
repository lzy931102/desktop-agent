"""test_t26_stop_manual.py - T26 手动验证：停止立即响应 + 简单任务耗时

真实云端链路验证（model_mode=cloud，glm-4.5-flash；需要网络与 .env 的
API Key。pyautogui failsafe 保持开启——工作准则 §五.5）：

  A. 停止立即响应：跑「看看现在有哪些窗口」（只读任务，两轮 LLM），
     第 2 秒（约在第 1 轮 LLM 流式生成中）点 agent.stop()，
     断言 run() 在 2 秒内返回且返回停止文案。
     修复前实测：2026-10-05 07:15 任务点停止后 27 秒才真停
     （audit：07:15:28 第 2 轮 LLM 开始 → 07:15:55 task_end）。
  B. 简单任务耗时：完整跑同一任务，断言 <10 秒。
     修复前实测：2026-10-04 07:49 同任务 47.1 秒（LLM 两轮 10+37s，
     37 秒耗在 glm-4.5-flash 深度思考上；本次 thinking 默认禁用）。

运行：在仓库根目录 `python e2e/test_t26_stop_manual.py`
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pyautogui  # noqa: E402  物理急停保持开启（工作准则 §五.5）
pyautogui.FAILSAFE = True

import agent_loop  # noqa: E402
from core.settings import Settings  # noqa: E402

RESULTS = []
TASK = "看看现在有哪些窗口"


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))


def make_agent():
    llm = agent_loop.build_llm_client(Settings())
    agent = agent_loop.DesktopAgent(llm=llm)
    agent.on_log = lambda m: None  # 静默（不刷屏；耗时数字见结尾汇总）
    return agent


def scenario_a():
    print("\n---- 场景 A：第 2 秒点停止（应在 LLM 流式调用中）----")
    agent = make_agent()
    box = {}

    def run():
        box["result"] = agent.run(TASK)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    time.sleep(2.0)
    t_stop = time.time()
    agent.stop()
    th.join(timeout=30)
    latency = time.time() - t_stop
    if th.is_alive():
        check("停止后 run() 返回", False, "30 秒仍未返回")
        return
    result = box.get("result") or ""
    check(f"停止时延 <2s（实测 {latency:.2f}s）", latency < 2)
    check("返回停止文案", "停止" in result, result[:40])


def scenario_b():
    print("\n---- 场景 B：简单任务完整耗时（thinking 已默认禁用）----")
    agent = make_agent()
    t0 = time.time()
    result = agent.run(TASK)
    elapsed = time.time() - t0
    ok = (not agent_loop.final_reply_failed(result)) and "窗口" in (result or "")
    check(f"任务完成且回复含窗口列表", ok, (result or "")[:60].replace("\n", " "))
    check(f"总耗时 <10s（实测 {elapsed:.1f}s，含 LLM 两轮）", elapsed < 10)


def main():
    scenario_a()
    scenario_b()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{'=' * 46}\nT26 手动验证：{len(RESULTS) - len(failed)}/{len(RESULTS)} 项通过")
    if failed:
        for name, _ok, detail in failed:
            print(f"  FAIL: {name}  {detail}")
        return 1
    print("全部通过——停止立即响应，简单任务不再被思考拖慢")
    return 0


if __name__ == "__main__":
    sys.exit(main())
