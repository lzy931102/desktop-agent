"""一次性回归：重放 2026-09-30 晚失败的任务用例（T6/T7/T8 修复验收）。

真实驱动 DesktopAgent（云端 glm-4-flash + 真实鼠标键盘），审计/历史照常落盘。
用法：python -m e2e.replay_20260930_evening [编号…]（缺省跑 1-4）

1) 百度天气·短版（晚场 7ade93a6，max_turns 失败）
2) 百度天气·长版（晚场 b3b0b32a，max_turns 失败）
3) GitHub 热点→记事本→桌面存档（晚场 9df02642，max_turns 失败）
4) 百度图片→桌面存 cybercat.jpg（晚场 0f38d020，空回复假成功）

晚场另外两个任务不入本重放：
- f96ef97a 整理"下载"文件夹：会真实移动用户文件，需用户本人在场时跑
- 3378ee4a 计算器+发邮件：包含真实外发邮件动作，同上

每个任务带 10 分钟看门狗（到点 agent.stop()），pyautogui 角落 failsafe 仍在。
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_loop import DesktopAgent, build_llm_client
from core.audit import AuditLogger
from core.history import TaskHistory
from core.paths import data_dir, plugins_dir, skills_dir
from core.settings import MAX_TURNS, Settings


def _effective_max_turns(settings):
    """与 gui._effective_max_turns 同逻辑（settings.max_turns，缺省回落）"""
    try:
        return max(1, int(settings.get("max_turns", MAX_TURNS)))
    except (TypeError, ValueError):
        return MAX_TURNS

TASKS = {
    "1": ("百度天气·短版", "开 Chrome，访问百度，搜索今天天气，告诉我第一条结果", None),
    "2": ("百度天气·长版",
          "开 Chrome 浏览器，在一个新的标签页里访问 https://www.baidu.com。"
          "在搜索框里输入'今天天气'，然后截图告诉我搜索结果里第一条天气信息是什么。",
          None),
    "3": ("GitHub热点存档",
          "打开浏览器，访问 GitHub 的 Trending 页面（https://github.com/trending）。"
          "帮我看一下当前排名前 3 的开源项目分别是什么。把它们的'项目名称'、"
          "'主要使用的编程语言'和'今日获得的 Star 数量'提取出来。然后打开电脑上的记事本，"
          "把这三条信息以清晰的格式写进去，保存到桌面，命名为 今日GitHub热点.txt。",
          Path.home() / "Desktop" / "今日GitHub热点.txt"),
    "4": ("赛博朋克猫图片",
          "去百度图片搜索'赛博朋克风格的猫'，把搜到的第一张图片保存到电脑桌面上，"
          "命名为 cybercat.jpg。如果遇到弹窗或者登录提示，请自己想办法关闭或绕过它们，"
          "确保任务完成。",
          Path.home() / "Desktop" / "cybercat.jpg"),
}

WATCHDOG_SECONDS = 600


def main():
    picks = sys.argv[1:] or list(TASKS)
    settings = Settings()  # 读真实 %LOCALAPPDATA% 配置，与 GUI 同源
    llm = build_llm_client(settings)
    print(f"模型模式={settings.get('model_mode')}  最大轮次="
          f"{_effective_max_turns(settings)}", flush=True)

    from plugin_system import PluginManager
    from skill_system import SkillManager
    plugins = PluginManager(settings, directory=plugins_dir())
    skills = SkillManager(settings, directory=skills_dir())

    summary = []
    for key in picks:
        name, text, expect_file = TASKS[key]
        print(f"\n===== 任务{key} {name} =====", flush=True)
        agent = DesktopAgent(
            llm, auditor=AuditLogger(), history=TaskHistory(),
            plugins=plugins, skills=skills,
            max_turns=_effective_max_turns(settings))
        agent.on_log = lambda m: print(m, flush=True)
        watchdog = threading.Timer(WATCHDOG_SECONDS, agent.stop)
        watchdog.daemon = True
        watchdog.start()
        t0 = time.time()
        try:
            result = agent.run(text)
        finally:
            watchdog.cancel()
        elapsed = time.time() - t0
        rec = agent.history.recent(1)[0]
        status = rec.get("status")
        effect = "无产物要求"
        if expect_file is not None:
            effect = ("产物已生成" if expect_file.exists()
                      else f"产物缺失：{expect_file}")
        ok = status == "success" and (expect_file is None or expect_file.exists())
        summary.append((key, name, status, ok, elapsed, effect))
        print(f"\n>>> 任务{key} 状态={status} 用时={elapsed:.0f}s {effect}", flush=True)
        print(f">>> 最终回复：{result[:300]}", flush=True)

    print("\n===== 重放汇总 =====", flush=True)
    passed = 0
    for key, name, status, ok, elapsed, effect in summary:
        print(f"任务{key} {name}: {'PASS' if ok else 'FAIL'}"
              f"（status={status}, {elapsed:.0f}s, {effect}）", flush=True)
        passed += ok
    print(f"\n通过 {passed}/{len(summary)}"
          f"（晚场同题 0/4：4×max_turns + 1×假成功）", flush=True)


if __name__ == "__main__":
    main()
