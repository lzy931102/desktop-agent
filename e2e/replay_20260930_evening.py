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

# 沙箱用例（原晚场 f96ef97a / 3378ee4a 的安全改写，见 docs/任务修改列表 T 系列讨论）：
# 5 只允许碰 F:\test_downloads（预先放置测试文件）；6 只算账+记事本，不发邮件
SANDBOX_DIR = Path(r"F:\test_downloads")
TASKS["5"] = ("沙箱·整理文件夹",
              "请帮我整理 F:\\test_downloads 这个文件夹。在里面新建三个子文件夹："
              "图片、文档、压缩包。然后把该文件夹根目录下的 .jpg 和 .png 文件移动到"
              "'图片'，.pdf 和 .txt 移动到'文档'，.zip 移动到'压缩包'。"
              "注意：只允许操作 F:\\test_downloads 这个文件夹，其他任何文件夹都不要动。",
              None)
TASKS["6"] = ("沙箱·计算器记账",
              "打开电脑自带的计算器，计算 345 乘以 12 得出结果。然后打开记事本，"
              "把算式和结果输入进去（345 × 12 = ？）。不需要保存文件，也不需要发送"
              "邮件或消息，输入完告诉我结果就行。",
              None)

WATCHDOG_SECONDS = 600


def make_sandbox_fixture():
    """用例 5 的测试夹具：若干假文件（内容随便，扩展名是真的）。
    幂等：已存在的不重建；每次运行前把上次移动过的归位到根目录"""
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    names = {"照片1.jpg": b"\xff\xd8\xff\xe0fake-jpeg",
             "照片2.png": b"\x89PNG\r\n\x1a\nfake-png",
             "说明.pdf": b"%PDF-1.4 fake",
             "笔记.txt": "这是测试文件".encode("utf-8"),
             "安装包.zip": b"PK\x03\x04fake"}
    for sub in ("图片", "文档", "压缩包"):
        (SANDBOX_DIR / sub).mkdir(exist_ok=True)
        for f in (SANDBOX_DIR / sub).iterdir():
            f.rename(SANDBOX_DIR / f.name)   # 归位到根目录
    for name, data in names.items():
        (SANDBOX_DIR / name).write_bytes(data)


def check_sandbox_5():
    """根目录应只剩三个子文件夹，无散落文件"""
    leftovers = [f.name for f in SANDBOX_DIR.iterdir() if f.is_file()]
    moved = {sub: [f.name for f in (SANDBOX_DIR / sub).iterdir()]
             for sub in ("图片", "文档", "压缩包")}
    return not leftovers, f"根目录残留:{leftovers or '无'} 分布:{moved}"


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
        if key == "5":
            make_sandbox_fixture()
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
        ok = status == "success"
        if key == "5":
            clean, detail = check_sandbox_5()
            effect = f"沙箱{'干净' if clean else '未整理'}（{detail}）"
            ok = ok and clean
        elif key == "6":
            # 千分位写法（4,140 / 4，140）与纯数字（4140）都算命中：
            # 2026-10-01 客户机重放实录——模型记事本输入与最终回复均为"4,140"，
            # 纯子串比对把功能成功的用例误判为 FAIL
            normalized = (result or "").replace(",", "").replace("，", "")
            hit = "4140" in normalized
            effect = "结果含 4140" if hit else "最终回复未见 4140"
            ok = ok and hit
        elif expect_file is not None:
            effect = ("产物已生成" if expect_file.exists()
                      else f"产物缺失：{expect_file}")
            ok = ok and expect_file.exists()
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
