"""T24e 网址/路径高亮 + 可点击（统一所有区域）回归测试。

覆盖：
  1. setup_rich_tags/insert_rich 落到 CTkTextbox（日志区路径）：
     三 tag 颜色、段范围正确、时间戳等普通文本不染
  2. 落到原生 tk.Text（对话流气泡路径）：重构后行为不变
  3. 点击逻辑（坐标→tag 段→后台线程动作）与悬停手型接线
  4. gui.py 日志区三处（setup/_log_line/_replay_log）确实走统一入口，
     不许再回落裸 insert（防回归）

 Tk 测试注记：withdrawn 窗口未映射，event_generate 不触发 Text 的
 tag 级绑定分发（2026-10-04 实测 Button-1/Motion 均不触发），所以
 点击逻辑直接调 _handle_click；悬停接线用 tk.eval 查绑定脚本后带
 19 个替换参数手动调起（text tag bind 的查询/调用 tkinter 包装层
 不支持，CTkTextbox.tag_bind 连查询都要求 func 必填——只能走 Tcl 层）。
 「点在 tag 外不动作」不单独设用例：Tk 只在指针命中 tag 字符时才分发
 tag 绑定（分发即闸门，生产不可达 handler-外-调用场景），而
 tag_prevrange 对范围外的取值本来就是「最近前一段」——直调测它等于
 测一个真实交互中不存在的情况；普通文字不可点由 tag 只绑 url/path
 （test_click_and_hover_wiring）与普通段不打 tag（test_plain_
 segments_untagged）共同保证。
"""
import pathlib
import threading

import pytest

from ui import richtext
from ui.theme import KEYC, LINK, PATHC


def _bind_cmd(native, tag, seq):
    """查 text tag 绑定脚本里的回调命令名；未绑定返回 None"""
    script = native.tk.eval(f"{native} tag bind {tag} {seq}")
    if not script:
        return None
    return script[script.index("[") + 1:].split(" ")[0]


@pytest.fixture(scope="module")
def tk_env(ctk_root):
    """会话级共享 CTk 实例（conftest.ctk_root）——同进程反复建/销毁
    Tk 解释器不稳定，全测试会话只建一次（T24b 踩坑，见其模块注释）"""
    return ctk_root


def _tag_text(widget, tag):
    rng = widget.tag_ranges(tag)
    return [widget.get(rng[i], rng[i + 1]) for i in range(0, len(rng), 2)]


def _native(widget):
    return getattr(widget, "_textbox", widget)


# ==================== 1/2. 插入与配色（两种控件） ====================

def test_insert_rich_on_ctk_textbox_log_path(tk_env):
    """日志区载体：网址/路径/快捷键段带 tag，时间戳与普通文字不染"""
    ctk, root = tk_env
    box = ctk.CTkTextbox(root, width=400, height=80)
    richtext.setup_rich_tags(box)
    richtext.insert_rich(box, "[12:00:01] 已打开 https://example.com/guide\n"
                         "[12:00:02] 截图已保存 F:\\笔记\\图.png\n"
                         "[12:00:03] 按 Ctrl+S 保存")
    assert _tag_text(box, "url") == ["https://example.com/guide"]
    assert _tag_text(box, "path") == ["F:\\笔记\\图.png"]
    assert _tag_text(box, "key") == ["Ctrl+S"]
    assert box.tag_cget("url", "foreground") == LINK
    assert box.tag_cget("path", "foreground") == PATHC
    assert box.tag_cget("key", "foreground") == KEYC


def test_insert_rich_on_native_text_chat_path(tk_env):
    """对话流载体（原生 tk.Text）：重构走 richtext 后 tag/配色不变"""
    import tkinter as tkbase
    ctk, root = tk_env
    body = tkbase.Text(root, bg="#21262D", fg="#E6EDF3")
    richtext.setup_rich_tags(body)
    richtext.insert_rich(body, "教程见 https://example.com/guide，存到 F:\\笔记.txt")
    assert _tag_text(body, "url") == ["https://example.com/guide"]
    assert _tag_text(body, "path") == ["F:\\笔记.txt"]


def test_plain_segments_untagged(tk_env):
    """纯文本（含时间戳/序号）不进任何高亮 tag：高亮有节制"""
    ctk, root = tk_env
    box = ctk.CTkTextbox(root, width=400, height=80)
    richtext.setup_rich_tags(box)
    richtext.insert_rich(box, "[12:00:01] 第 1 轮 完成，用时 3 秒\n")
    for tag in ("url", "path", "key"):
        assert not box.tag_ranges(tag), tag


def test_url_keeps_trailing_chinese_punct_out(tk_env):
    """句末中文标点不吃进网址（点开会 404 的老毛病）"""
    ctk, root = tk_env
    box = ctk.CTkTextbox(root, width=400, height=80)
    richtext.setup_rich_tags(box)
    richtext.insert_rich(box, "教程 https://example.com/a。好了")
    assert _tag_text(box, "url") == ["https://example.com/a"]


# ==================== 3. 绑定与点击 ====================

def test_click_and_hover_wiring(tk_env):
    """url/path 两 tag 都绑了点击与悬停接线；key 只配色不可点"""
    ctk, root = tk_env
    box = ctk.CTkTextbox(root, width=400, height=80)
    richtext.setup_rich_tags(box)
    nat = _native(box)
    for tag in ("url", "path"):
        assert _bind_cmd(nat, tag, "<Button-1>"), f"{tag} 未绑点击"
        assert _bind_cmd(nat, tag, "<Enter>"), f"{tag} 未绑悬停"
        assert _bind_cmd(nat, tag, "<Leave>"), f"{tag} 未绑移出恢复"
    assert not _bind_cmd(nat, "key", "<Button-1>")


def _fake_open_target(monkeypatch):
    done = threading.Event()
    seen = []

    def fake_work(kind, value):
        seen.append((kind, value))
        done.set()

    monkeypatch.setattr(richtext, "_open_target_work", fake_work)
    return done, seen


def test_handle_click_url_resolves_tag_range(tk_env, monkeypatch):
    """点在网址段内 → 取整段网址 → 后台线程动作（真布局坐标，非硬编码）"""
    ctk, root = tk_env
    box = ctk.CTkTextbox(root, width=400, height=80)
    box.pack()
    richtext.setup_rich_tags(box)
    richtext.insert_rich(box, "https://example.com/guide 教程")
    box.update_idletasks()
    box.update()
    bb = box.bbox("1.5")                    # 网址第 6 个字符上
    assert bb, "withdrawn 窗口下应有文本布局坐标"
    done, seen = _fake_open_target(monkeypatch)
    richtext._handle_click(box, "url", bb[0] + bb[2] // 2, bb[1] + bb[3] // 2)
    assert done.wait(2.0)
    assert seen == [("url", "https://example.com/guide")]
    box.destroy()


def test_hover_cursor_enters_hand_and_restores(tk_env):
    """悬停手型：Enter 变 hand2、Leave 恢复原光标（驱动真实绑定回调）"""
    ctk, root = tk_env
    box = ctk.CTkTextbox(root, width=400, height=80)
    box.pack()
    before = str(box.cget("cursor"))
    richtext.setup_rich_tags(box)
    box.update_idletasks()
    box.update()
    nat = _native(box)
    enter, leave = _bind_cmd(nat, "url", "<Enter>"), _bind_cmd(nat, "url", "<Leave>")
    box.tk.call(enter, *(["0"] * 10 + ["?"] * 9))   # 19 个事件替换参数
    assert str(box.cget("cursor")) == "hand2"
    box.tk.call(leave, *(["0"] * 10 + ["?"] * 9))
    assert str(box.cget("cursor")) == before
    box.destroy()


# ==================== 4. gui.py 日志区接线（防回归） ====================

def test_gui_log_lines_route_through_insert_rich():
    """gui.py 的日志写入/重放必须走统一入口，不许回落裸 insert；
    日志区创建时必须 setup 富文本 tag。源码级检查，防改回去。"""
    src = pathlib.Path(__file__).parent.joinpath("gui.py").read_text("utf-8")
    for fn in ("_log_line", "_replay_log"):
        body = src.split(f"def {fn}", 1)[1].split("\n    def ", 1)[0]
        assert "insert_rich(self.logbox" in body, f"{fn} 未走 insert_rich"
        assert 'self.logbox.insert("end", line' not in body, \
            f"{fn} 残留裸 insert（绕过统一高亮）"
    setup_part = src.split("self.logbox.pack(fill=\"x\", pady=(2, 0))", 1)[1]
    assert "setup_rich_tags(self.logbox)" in setup_part


def test_chat_stream_delegates_to_richtext():
    """对话流渲染与日志区共用同一实现（一套逻辑两处使用，不许复制粘贴）"""
    import inspect
    from ui import chat_stream
    src = inspect.getsource(chat_stream._make_rich_text)
    assert "richtext.setup_rich_tags" in src
    assert "richtext.insert_rich" in src
    assert "tag_config" not in src           # 本地私配 tag = 复制粘贴，禁止
    assert not hasattr(chat_stream, "_open_target_work")   # 已迁居 richtext
