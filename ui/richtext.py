# 富文本高亮的 GUI 应用层（T24e）：tag 配置 + 插入 + 点击动作，一处实现。
# 分词是纯函数，在 ui/formatters.tokenize_rich；本模块只负责把它落到
# tk.Text 类控件上（原生 Text 与 CTkTextbox 皆可——后者的 tag_*/insert
# 全是透传）。ui/chat_stream.py 助手气泡与 gui.py 运行日志区共用此模块，
# 新增文本区域要接入高亮时也走这里，不许各自再写一份。
import os
import subprocess
import threading
import webbrowser

from core.settings import validate_public_url
from ui.formatters import tokenize_rich
from ui.theme import KEYC, LINK, PATHC


def open_target(kind, value):
    """高亮段点击动作（后台线程执行，T30）：网址→系统浏览器；路径→定位。

    必须异步：os.path.exists 对失效盘符/网络路径可能阻塞数十秒、
    webbrowser.open 走系统 shell——2026-10-04 一次无痕冻结后立规，
    点击回调里绝不放同步 IO。目标不合法/不存在时静默不动作：
    网址过 scheme 白名单 + 非内网校验（用户主动点击，浏览器自身解析
    为准，同 open_url 的无 DNS 模式）；路径不存在可能是被分词截断。
    """
    threading.Thread(target=_open_target_work, args=(kind, value),
                     daemon=True, name="open-target").start()


def _open_target_work(kind, value):
    if kind == "url":
        ok, _err = validate_public_url(value, require_https=False,
                                       check_dns=False)
        if ok:
            try:
                webbrowser.open(value)
            except Exception:
                pass
    elif kind == "path":
        p = os.path.normpath(value.strip())
        if os.path.exists(p):
            try:
                subprocess.Popen(["explorer", "/select,", p])
            except Exception:
                pass


def _handle_click(widget, kind, x, y):
    """点击坐标 → 命中 tag 段 → 触发动作。独立成函数供 tag_bind 与测试
    直接调用；异常一律吞掉——点击只是锦上添花，绝不因它炸泵。"""
    try:
        idx = widget.index(f"@{x},{y}")
        rng = widget.tag_prevrange(kind, idx + "+1c")
        if rng:
            open_target(kind, widget.get(rng[0], rng[1]))
    except Exception:
        pass


def setup_rich_tags(widget):
    """在 tk.Text / CTkTextbox 上配好三个高亮 tag：颜色、点击、悬停手型。

    tag 名即类型（url/path/key），按 tag 绑定对全文生效——先 setup 后续
    insert_rich 打上的段自动可点。悬停变 hand2、移出恢复原光标
    （Text 默认 xterm 选字光标 / 气泡 arrow）。返回 widget 便于链式使用。
    """
    widget.tag_config("url", foreground=LINK, underline=True)
    widget.tag_config("path", foreground=PATHC, underline=True)
    widget.tag_config("key", foreground=KEYC)
    for kind in ("url", "path"):
        widget.tag_bind(kind, "<Button-1>",
                        lambda e, w=widget, k=kind: _handle_click(w, k, e.x, e.y))
        saved = widget.cget("cursor")
        widget.tag_bind(kind, "<Enter>",
                        lambda _e, w=widget: w.configure(cursor="hand2"))
        widget.tag_bind(kind, "<Leave>",
                        lambda _e, w=widget, c=saved: w.configure(cursor=c))
    return widget


def insert_rich(widget, text):
    """按 tokenize_rich 的分词插入文本：网址/路径/快捷键段带对应 tag
    （高亮 + 可点），普通段原样。state=disabled 的控件同样适用
    （日志区常态禁用，tag 与点击不受禁用影响）。"""
    for seg, kind in tokenize_rich(text):
        if kind == "text":
            widget.insert("end", seg)
        else:
            widget.insert("end", seg, kind)
