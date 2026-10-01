"""test_vision_backend.py - 视觉后端（看屏幕）回归测试

覆盖 2026-09-28 的改动：看屏幕从本机 qwen-vl（107 秒/张，必然超时）
改走云端视觉（glm-4v-flash，1~5 秒）。

运行：
    python test_vision_backend.py            # 跳过真实网络调用
    python test_vision_backend.py --live      # 额外做一次真实的云端看屏
"""
import sys
import time

import agent_vision
from agent_vision import ScreenVision, VISION_CLOUD_MODEL, VISION_MODEL, VISION_WIDTH

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'✓' if cond else '✗'} {name}" + (f"  —— {detail}" if detail else ""))


def vision_cfg(**over):
    cfg = {"mode": "auto", "width": 1600, "timeout": 45,
           "cloud_base_url": "https://open.bigmodel.cn/api/paas/v4",
           "cloud_api_key": "k", "cloud_model": "glm-4v-flash",
           "cloud_provider": "zhipu"}
    cfg.update(over)
    return cfg


# ---------------- 1. 后端选择逻辑 ----------------

def test_backend_selection():
    check("auto + 有 Key → 走云端",
          ScreenVision(cfg=vision_cfg()).backend == "cloud")
    check("auto + 没 Key → 回退本机",
          ScreenVision(cfg=vision_cfg(cloud_api_key="")).backend == "local")
    check("local 模式 → 永远本机",
          ScreenVision(cfg=vision_cfg(mode="local")).backend == "local")
    check("cloud 模式 + 没 Key → 仍报云端（让报错说清原因）",
          ScreenVision(cfg=vision_cfg(mode="cloud", cloud_api_key="")).backend
          == "cloud")


def test_active_model_and_ready():
    v = ScreenVision(cfg=vision_cfg())
    check("云端模式模型名", v.active_model == "glm-4v-flash", v.active_model)
    check("云端就绪判定不依赖 Ollama（不发请求，秒回）", v.is_available() is True)
    check("云端模式 describe 含模型名", "glm-4v-flash" in v.describe(),
          v.describe())
    dead = ScreenVision(cfg=vision_cfg(mode="cloud", cloud_api_key=""))
    check("云端没 Key → 明确报未就绪", dead.is_available() is False)


# ---------------- 2. 缺 Key 时的报错要清楚 ----------------

def test_missing_key_message():
    # 显式要求「只用云端」但没配 Key：必须立刻说清原因，
    # 而不是偷偷换回本机慢模型（本机一张屏 107 秒，用户只会以为它卡死了）
    t0 = time.time()
    out = ScreenVision(cfg=vision_cfg(mode="cloud", cloud_api_key="")).ask(
        "屏幕上有什么？")
    dt = time.time() - t0
    check("云端没 Key 时返回错误而不是静默变慢",
          out.startswith("错误") and "API Key" in out, out[:70])
    check("没 Key 瞬时返回（没去等网络）", dt < 10, f"{dt:.1f}s")
    check("默认写死了本机兜底模型是谁", VISION_MODEL == "qwen-vl")


# ---------------- 3. 编码：宽度必须跟上设置 ----------------

def test_encode_width():
    """编码后必须是目标宽度——直接解回图片量，别只信参数传递"""
    import base64
    import io
    from PIL import Image

    v = ScreenVision(cfg=vision_cfg(width=1600))
    big = Image.new("RGB", (1920, 1080), (30, 30, 30))
    out = v._encode(big)
    got = Image.open(io.BytesIO(base64.b64decode(out)))
    check("1920 宽截图被缩到 1600", got.size == (1600, 900), str(got.size))

    v2 = ScreenVision(cfg=vision_cfg(width=1600))
    small = Image.new("RGB", (1280, 720), (30, 30, 30))
    got2 = Image.open(io.BytesIO(base64.b64decode(v2._encode(small))))
    check("比目标窄的截图不放大", got2.size == (1280, 720), str(got2.size))

    v3 = ScreenVision(cfg=vision_cfg(width=1600))
    check("编码结果是 base64 字符串且非空",
          isinstance(v3._encode(small), str) and len(v3._encode(small)) > 100)


# ---------------- 4. 默认值来自设置 ----------------

def test_settings_defaults():
    from core.settings import DEFAULTS, VISION_MODEL_OPTIONS
    vis = DEFAULTS["vision"]
    check("默认 vision.mode = auto", vis["mode"] == "auto")
    check("默认视觉宽度 1600（实测比 1024 准得多）", vis["width"] == 1600)
    check("默认云端视觉模型在候选清单里",
          vis["cloud_model"] in VISION_MODEL_OPTIONS, vis["cloud_model"])
    check("云端默认模型 = glm-4v-flash", VISION_CLOUD_MODEL == "glm-4v-flash")


def test_real_settings_read():
    """真机上读一次设置，确认能解析出云端 Key 与地址（没配也不算失败）"""
    cfg = agent_vision._vision_config()
    check("能读到 vision 段配置", "mode" in cfg and "width" in cfg, str(cfg["mode"]))


# ---------------- 5. 重试清单 ----------------

def test_retryable():
    from core import guard
    check("analyze_screen 已纳入可重试清单（云端只需几秒）",
          guard.is_retryable("analyze_screen") is True)


# ---------------- 6. 真实云端看屏（--live）----------------

def test_live_cloud():
    v = agent_vision.get_vision()
    if v.backend != "cloud":
        print(f"⚠ 当前后端是 {v.backend}（未配云端 Key），跳过真实看屏")
        return
    t0 = time.time()
    out = v.ask("屏幕上当前最主要显示的是哪个软件的窗口？只回答一两句话。")
    dt = time.time() - t0
    ok = not out.startswith("错误") and len(out) > 4
    check(f"真实云端看屏（{v.active_model}）", ok, f"{dt:.1f}s：{out[:120]}")
    check("真实看屏耗时在 15 秒内", dt < 15, f"{dt:.1f}s")


if __name__ == "__main__":
    print("=" * 66)
    test_backend_selection()
    test_active_model_and_ready()
    test_missing_key_message()
    test_encode_width()
    test_settings_defaults()
    test_real_settings_read()
    test_retryable()
    if "--live" in sys.argv:
        print("-" * 66)
        test_live_cloud()
    print("=" * 66)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
    sys.exit(1 if FAIL else 0)


# ---------------- 发现 G①：focus_window 歧义必须给出候选明细（2026-10-01） ----------------

def test_focus_window_ambiguity_lists_candidates(monkeypatch):
    """发现 G①（真实用例实录：只回一句"匹配到多个"时模型原样重试同一调用
    20+ 次烧光轮次）：歧义报错必须逐窗口列候选（标题+位置）并明确告知
    勿重复原调用"""
    class _R:
        def __repr__(self):
            return "(0, 0, 640, 480)"

    titles = [("主文件夹 - 文件资源管理器", _R(), 101),
              ("主文件夹 - 文件资源管理器", _R(), 202)]
    monkeypatch.setattr(agent_vision, "_enum_windows", lambda: titles)
    out = agent_vision.focus_window("主文件夹")
    assert "匹配到多个窗口" in out
    assert out.count("主文件夹 - 文件资源管理器") == 2   # 逐窗口候选
    assert "不要重复" in out
