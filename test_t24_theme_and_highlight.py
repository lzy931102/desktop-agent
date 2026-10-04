"""T24 对话流配色改造（GitHub Dark 主题）回归测试。

四组覆盖：
  1. theme 色板：任务书点名的 GitHub Dark 常量在位、既有语义常量
     （BG/BUBBLE_USER/BORDER/INPUT_BG…）正确映射到新色板、无旧值残留
  2. tokenize_rich 分词：网址/路径/快捷键识别，中文邻接边界
     （「按F4键」）、误报排除（GIF4、孤立 Shift）、标点剥离
  3. 渲染层（真 Tk withdraw）：用户/Agent 气泡新色与圆角、富文本 tag
     颜色与点击绑定、自适应高度合理
  4. 点击动作：内网网址不开浏览器、不存在的路径不动作（防误触）
"""
import pytest

from ui import chat_stream
from ui.formatters import tokenize_rich
from ui.theme import (ACCENT_BLUE, BG, BG_PRIMARY, BG_SECONDARY, BG_TERTIARY,
                      BORDER, BUBBLE_USER, CARD, CARD_2, INPUT_BG, KEYC, LINK,
                      PATHC, TEXT_PRIMARY, TEXT_SECONDARY)


# ==================== 1. 色板 ====================

def test_github_dark_constants_match_spec():
    """任务书点名的色值一字不差"""
    assert BG_PRIMARY == "#0D1117"
    assert BG_SECONDARY == "#161B22"
    assert BG_TERTIARY == "#21262D"
    assert BORDER == "#30363D"
    assert TEXT_PRIMARY == "#E6EDF3"
    assert TEXT_SECONDARY == "#8B949E"
    assert ACCENT_BLUE == "#58A6FF"
    assert PATHC == "#3FB950"
    assert KEYC == "#D29922"


def test_legacy_constants_map_to_new_palette():
    """既有引用零改动的前提：旧名字全部映射到新色板"""
    assert BG == BG_PRIMARY
    assert CARD == BG_TERTIARY
    assert CARD_2 == BG_SECONDARY
    assert INPUT_BG == BG_SECONDARY
    assert BUBBLE_USER == ACCENT_BLUE          # 用户气泡 = 最亮的蓝


def test_no_old_palette_values_left_in_theme():
    """旧 gray-900 体系色值不得残留在 theme（防止半改不改）"""
    import ui.theme as t
    old = {"#111827", "#0D1526", "#1F2937", "#374151", "#4B5563",
           "#3B82F6", "#1E40AF", "#F3F4F6", "#34D399", "#F87171"}
    live = {v for k, v in vars(t).items()
            if k.isupper() and isinstance(v, str) and v.startswith("#")}
    assert not old & live, old & live


# ==================== 2. tokenize_rich ====================

def kinds_of(text):
    return [(seg, kind) for seg, kind in tokenize_rich(text) if kind != "text"]


def test_tokenize_url():
    assert kinds_of("详情见 https://github.com/a/b#readme。") == [
        ("https://github.com/a/b#readme", "url")]
    assert kinds_of("http://example.com/x?q=1") == [
        ("http://example.com/x?q=1", "url")]


def test_tokenize_path_chinese_and_slash():
    assert kinds_of("已保存到 F:\\笔记.txt，记得看。") == [
        ("F:\\笔记.txt", "path")]
    assert kinds_of("看 F:/笔记/a.txt 就行") == [("F:/笔记/a.txt", "path")]


def test_tokenize_hotkey_chinese_boundary():
    """中文邻接的快捷键必须命中（\\b 在中文处永不成立，已实测修掉）"""
    assert ("Alt+F4", "key") in kinds_of("按Alt+F4退出")
    assert ("F4", "key") in kinds_of("按F4键刷新")
    assert ("Ctrl+Shift+N", "key") in kinds_of("先按 Ctrl+Shift+N 新建")


def test_tokenize_no_false_positives():
    """孤立 Shift / GIF4 这类英文词不高亮；普通句子零命中"""
    assert kinds_of("我把礼物（gift）送给他，F 站不错") == []
    assert kinds_of("GIF4 不是快捷键") == []


def test_tokenize_url_wins_over_path():
    """URL 整体优先， scheme 里的字母不吃成路径"""
    assert kinds_of("https://example.com/F1") == [
        ("https://example.com/F1", "url")]


def test_tokenize_plain_text_roundtrip():
    """纯文本拼回原样（不丢字符）"""
    text = "普通一句话，没有特殊内容。Another plain line 123."
    assert "".join(seg for seg, _ in tokenize_rich(text)) == text


# ==================== 3. 渲染层（真 Tk，withdraw 不弹窗） ====================

@pytest.fixture(scope="module")
def tk_env(ctk_root):
    """会话级共享 CTk 实例（conftest.ctk_root）。

    同进程反复创建/销毁 Tk 解释器不稳定（init.tcl source 偶发失败），
    全测试会话只建一次；逐条建/销毁另有 teardown 偶发 Tcl
    "invalid command name" 残留——两个问题一个解法。"""
    return ctk_root


def test_user_bubble_color_and_radius(tk_env):
    ctk, root = tk_env
    app = type("A", (), {"root": root, "settings": {}})
    cs = chat_stream.ChatStream(root, app)
    cs.append({"kind": "user", "text": "打开记事本"}, scroll=False)
    frames = [w for w in cs.frame.winfo_children()[0].winfo_children()]
    assert any(str(f.cget("fg_color")) == BUBBLE_USER and
               int(f.cget("corner_radius")) == 12 for f in frames)


def test_assistant_bubble_color_and_radius(tk_env):
    ctk, root = tk_env
    app = type("A", (), {"root": root, "settings": {}})
    cs = chat_stream.ChatStream(root, app)
    cs.append({"kind": "assistant", "text": "搞定了。"}, scroll=False)
    frames = cs.frame.winfo_children()[0].winfo_children()
    assert any(str(f.cget("fg_color")) == CARD and
               int(f.cget("corner_radius")) == 12 for f in frames)


def test_assistant_rich_tags_configured_and_height_fits(tk_env):
    """网址/路径/快捷键三个 tag 都配置了对应前景色且绑定了点击；高度自适应"""
    ctk, root = tk_env
    import tkinter as tkbase
    app = type("A", (), {"root": root, "settings": {}})
    cs = chat_stream.ChatStream(root, app)
    text = ("搞定了：结果存在 F:\\笔记.txt，"
            "教程见 https://example.com/guide，保存按 Ctrl+S。")
    cs.append({"kind": "assistant", "text": text}, scroll=False)

    def walk(w):
        yield w
        for c in w.winfo_children():
            yield from walk(c)

    body = next(w for w in walk(cs.frame) if isinstance(w, tkbase.Text))
    assert body.tag_cget("url", "foreground") == LINK
    assert body.tag_cget("path", "foreground") == PATHC
    assert body.tag_cget("key", "foreground") == KEYC
    assert body.tag_ranges("url")             # URL 段确实被打上 tag
    assert body.tag_ranges("path")
    assert body.tag_ranges("key")
    # 行数自适应是异步的（等几何稳定后量，tk.Text height 单位是「行」），
    # 驱动事件循环让三次量高跑完再断言：三五行的短回复行数应是个位数
    #（像素被当行数的病态值是几百，如 1407px→31"行"→527px 高的空泡）
    import time as _t
    end = _t.time() + 2.0
    while _t.time() < end:
        root.update()
        _t.sleep(0.02)
    assert 1 <= int(body.cget("height")) < 10


# ==================== 4. 点击动作 ====================

def test_open_target_work_rejects_non_public_url(monkeypatch):
    """内网/非法网址不允许点击打开（scheme 白名单 + 非内网校验）"""
    opened = []
    monkeypatch.setattr(chat_stream.webbrowser, "open",
                        lambda u: opened.append(u))
    chat_stream._open_target_work("url", "http://127.0.0.1:8080/x")
    chat_stream._open_target_work("url", "javascript:alert(1)")
    chat_stream._open_target_work("url", "file:///C:/Windows/System32")
    assert opened == []
    chat_stream._open_target_work("url", "https://example.com/ok")
    assert opened == ["https://example.com/ok"]


def test_open_target_work_path_must_exist(monkeypatch):
    """不存在的路径（可能被分词截断）不动作；存在的目录 explorer 定位"""
    calls = []
    monkeypatch.setattr(chat_stream.subprocess, "Popen",
                        lambda cmd: calls.append(cmd))
    chat_stream._open_target_work("path", "F:\\不存在的路径_xyz\\a.txt")
    assert calls == []
    tmp = __import__("pathlib").Path(__import__("tempfile").mkdtemp())
    chat_stream._open_target_work("path", str(tmp))
    assert len(calls) == 1 and "/select," in calls[0]


def test_open_target_runs_in_background_thread(monkeypatch):
    """点击回调绝不在主线程做同步 IO（失效盘符/浏览器 shell 可阻塞数十秒，
    2026-10-04 无痕冻结后立规）——_open_target 只负责起 daemon 线程"""
    import threading as th
    done = th.Event()
    seen_threads = []

    def fake_work(kind, value):
        seen_threads.append(th.current_thread())
        done.set()

    monkeypatch.setattr(chat_stream, "_open_target_work", fake_work)
    chat_stream._open_target("url", "https://example.com/x")
    assert done.wait(2.0)
    assert seen_threads and seen_threads[0] is not th.main_thread()
