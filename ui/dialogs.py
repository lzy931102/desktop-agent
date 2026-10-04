"""首启引导卡与高危确认入口（T4 Phase 2 从 gui.py 抽出）。

方法原样保留 self 语义，AgentGUI 在 gui.py 里经 Mixin 组合继承；
跨面板调用（如引导卡「用云端」→ 设置面板）仍走 self.xxx。
T24a 重做「怎么用」引导（_show_welcome）：不再用独立弹窗（深底大蓝
按钮像警告不像欢迎，用户实测反馈），改嵌在对话区顶部、用户一开始
输入就 500ms 柔和淡出；与 _show_onboarding（选模型路线）仍是两张卡，
路线卡解决连不上模型，仍按 onboarding_choice 状态机弹。"""
import threading
import webbrowser
import customtkinter as ctk
from ui.theme import (ACCENT, ACCENT_HOVER, BG, BORDER, CARD_2,
                      CLOUD_TUTORIAL_URL, ERR, FAINT, MUTED, OK,
                      OLLAMA_DOWNLOAD_URL, TEXT, WARN,
                      WELCOME_BG, WELCOME_CARD_HEAD, WELCOME_CARD_LINES)
from ui.chat_stream import attach_modal_dialog


def _lerp_color(c1, c2, t):
    """两个 #RRGGBB 间线性插值（t=0 返回 c1，t=1 返回 c2）——渐隐动画用"""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}"
                         for x, y in zip(a, b))


class DialogsMixin:
    def _maybe_show_welcome(self):
        """T24 任务 1：首次使用在对话区顶部显示「怎么用」引导卡，看过
        （开始输入）即淡出并记 welcome_shown=True，之后不再自动显示。
        由 __init__ 的 root.after(600, …) 调度（主窗口先立起来）。"""
        try:
            shown = bool(self.settings.get("welcome_shown", False))
        except Exception:
            shown = True   # 设置读不出来时宁可少打扰
        if not shown:
            self._show_welcome()

    def _show_welcome(self):
        """「怎么用」引导卡（T24a）：嵌入对话区顶部（Tab 栏下、对话流上，
        走布局流不遮挡任何东西），柔和配色、无按钮。用户在输入框敲下
        第一个字时 _on_input_changed 触发 500ms 渐隐；已看过即记
        welcome_shown=True（清空输入框也不复活）。设置面板「重看使用
        引导」也走这里；正在显示/正在淡出时不重复叠卡。"""
        card = getattr(self, "_welcome_card", None)
        if card is not None and card.winfo_exists():
            return
        if getattr(self, "_welcome_fading", False):
            return
        card = ctk.CTkFrame(self.main_col, fg_color=WELCOME_BG,
                            border_width=1, border_color=BORDER,
                            corner_radius=12)
        # CTkScrollableFrame 被 pack 进主列的是它内部容器（_parent_frame，
        # 与 chat_stream._scroll_end 用 _parent_canvas 同类私有属性）；
        # before 让卡片插到对话流上方。锚失效时退化为排主列末尾，仍可用
        anchor = getattr(self.chat.frame, "_parent_frame", self.chat.frame)
        try:
            card.pack(fill="x", before=anchor, pady=(0, 4))
        except Exception:
            card.pack(fill="x", pady=(0, 4))
        ctk.CTkLabel(card, text=WELCOME_CARD_HEAD,
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT, anchor="w").pack(
            anchor="w", padx=16, pady=(12, 4))
        fade_items = [(card, "fg_color", WELCOME_BG),
                      (card, "border_color", BORDER)]
        for line in WELCOME_CARD_LINES:
            if not line:
                continue
            lbl = ctk.CTkLabel(card, text=line, font=ctk.CTkFont(size=13),
                               text_color=MUTED, justify="left",
                               anchor="w")
            lbl.pack(anchor="w", padx=16, pady=1)
            fade_items.append((lbl, "text_color", MUTED))
        ctk.CTkLabel(card, text="").pack(pady=(0, 8))
        self._welcome_card = card
        self._welcome_fade_items = fade_items
        self._welcome_fading = False

    def _on_input_changed(self, _=None):
        """输入框 <<Modified>> 哨兵：有第一个真实字符（非占位符）就淡出
        引导卡。edit_modified(False) 复位哨兵会再发一次事件，靠先查
        modified 状态防递归。"""
        try:
            if not self.input_text.edit_modified():
                return
            self.input_text.edit_modified(False)
            has_ph = bool(self.input_text.tag_ranges("ph"))
            text = self.input_text.get("1.0", "end").strip()
        except Exception:
            return
        card = getattr(self, "_welcome_card", None)
        if card is None or not card.winfo_exists():
            return
        if getattr(self, "_welcome_fading", False) or has_ph or not text:
            return
        self._fade_out_welcome()

    def _fade_out_welcome(self):
        """引导卡淡出（任务书约 500ms）：Tk 子控件没有逐件透明度，用
        「颜色向主背景渐隐」等效实现。4 步 × 25ms 名义 100ms——实测可见
        窗口下每步 CTk 重绘 ~160ms 才是大头（2026-10-04 帧率实测），
        4×25 墙钟约 0.7s，每步 25% 色变读起来仍是柔和的化开而非闪跳。
        淡出即记 welcome_shown=True：清空输入框后卡片也不复活。"""
        self._welcome_fading = True
        try:
            if not self.settings.get("welcome_shown", False):
                self.settings.set("welcome_shown", True)
        except Exception:
            pass   # 记不住标志最多下次启动再看一次，不能反噬淡出流程
        items = list(self._welcome_fade_items or [])
        steps, step_ms = 4, 25

        def step(i):
            t = i / steps
            for widget, opt, orig in items:
                try:
                    if widget.winfo_exists():
                        widget.configure(**{opt: _lerp_color(orig, BG, t)})
                except Exception:
                    pass   # 卡片正被销毁等竞态：淡出是锦上添花，绝不炸泵
            if i < steps:
                self.root.after(step_ms, step, i + 1)
            else:
                try:
                    if card.winfo_exists():
                        card.destroy()
                except Exception:
                    pass
                self._welcome_card = None
                self._welcome_fade_items = None
                self._welcome_fading = False

        card = self._welcome_card
        step(0)

    def _show_onboarding(self, auto=False):
        """检测不到模型服务时的三选一引导：云端 / 本地 / 稍后再说。

        auto=True 是启动自动弹出，受 onboarding_choice 状态约束（已选过路线
        的老用户不弹；"稍后再说"只再提醒一次）；顶栏徽章点击唤出时
        auto=False，不受约束，随时可看。
        """
        prev_choice = str(self.settings.get("onboarding_choice", "") or "")
        if auto and prev_choice == "later":
            # "稍后再说"后的最后一次自动提醒：先记为已引导——这次无论怎么
            # 关（选别的、点 ×），都不会再有自动弹出；徽章仍可手动唤出
            self.settings.set("onboarding_choice", "dismissed")

        dlg = ctk.CTkToplevel(self.root, fg_color=BG)
        dlg.title("欢迎使用 Desktop Agent")
        dlg.geometry("560x440")
        dlg.resizable(False, False)
        attach_modal_dialog(dlg, self.root)
        dlg.attributes("-topmost", True)
        dlg.after(200, dlg.lift)

        def pick(choice):
            self.settings.set("onboarding_choice", choice)

        def pick_later():
            # "" → later：下次启动仍未连上时再提醒一次；已是 later（本次就是
            # 那次提醒，或徽章唤出后再次婉拒）→ dismissed，不再自动弹
            pick("dismissed" if prev_choice == "later" else "later")
            dlg.destroy()

        wrap = ctk.CTkFrame(dlg, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=26, pady=(22, 18))

        def build_home():
            for w in wrap.winfo_children():
                w.destroy()
            connected = bool(self.ollama_ok)
            ctk.CTkLabel(wrap, text="🤖 欢迎使用 Desktop Agent",
                         font=ctk.CTkFont(size=17, weight="bold"),
                         text_color=TEXT).pack(anchor="w")
            ctk.CTkLabel(wrap, text=("✓ 模型服务已连接，可以直接开始用"
                                     if connected else
                                     "○ 还没连上模型服务——连上一个 AI 模型才能开始帮你干活"),
                         font=ctk.CTkFont(size=13),
                         text_color=OK if connected else WARN).pack(
                anchor="w", pady=(6, 0))
            ctk.CTkLabel(wrap, text="选一种方式开始（以后随时可在「设置」里更改）：",
                         font=ctk.CTkFont(size=13), text_color=MUTED).pack(
                anchor="w", pady=(2, 16))
            ctk.CTkButton(wrap, text="☁  我不太懂，用云端（推荐）", height=46,
                          corner_radius=10, font=ctk.CTkFont(size=13, weight="bold"),
                          fg_color=ACCENT, hover_color=ACCENT_HOVER,
                          command=lambda: self._onboarding_pick_cloud(dlg, pick)
                          ).pack(fill="x", pady=(0, 8))
            link = ctk.CTkLabel(wrap, text=f"先看看图文教程（网页）：{CLOUD_TUTORIAL_URL}",
                                font=ctk.CTkFont(size=12), text_color=ACCENT,
                                cursor="hand2")
            link.pack(anchor="w", pady=(0, 14))
            link.bind("<Button-1>", lambda e: webbrowser.open(CLOUD_TUTORIAL_URL))
            ctk.CTkButton(wrap, text="💻  我要用本地（数据不出本机，需先安装 Ollama）",
                          height=46, corner_radius=10,
                          font=ctk.CTkFont(size=13, weight="bold"),
                          fg_color=CARD_2, hover_color=BORDER,
                          command=lambda: self._onboarding_pick_local(wrap, pick)
                          ).pack(fill="x", pady=(0, 8))
            ctk.CTkButton(wrap, text="⏰  稍后再说", height=40, corner_radius=10,
                          font=ctk.CTkFont(size=13),
                          fg_color="transparent", border_width=1,
                          border_color=BORDER, text_color=MUTED,
                          hover_color=CARD_2,
                          command=pick_later).pack(fill="x", pady=(14, 0))

        build_home()


    def _onboarding_pick_cloud(self, dlg, pick):
        """云端路线：记住选择 → 直接打开设置并定位到「云端模型」区"""
        pick("cloud")
        dlg.destroy()
        self._show_settings(focus="cloud")


    def _onboarding_pick_local(self, wrap, pick):
        """本地路线：切到第二步——Ollama 下载直链 + 装好后重新检测"""
        pick("local")
        for w in wrap.winfo_children():
            w.destroy()
        ctk.CTkLabel(wrap, text="💻 用本地模型（数据不出本机）",
                     font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(wrap, text="第 1 步：下载并安装 Ollama（约 500MB，装完它会在后台运行）",
                     font=ctk.CTkFont(size=13), text_color=MUTED).pack(
            anchor="w", pady=(14, 6))
        ctk.CTkButton(wrap, text="打开 Ollama 官方下载页", height=40,
                      corner_radius=10, font=ctk.CTkFont(size=13),
                      fg_color=CARD_2, hover_color=BORDER,
                      command=lambda: webbrowser.open(OLLAMA_DOWNLOAD_URL)
                      ).pack(fill="x")
        ctk.CTkLabel(wrap, text="第 2 步：装好后点下面的按钮重新检测，变绿就能开始用",
                     font=ctk.CTkFont(size=13), text_color=MUTED).pack(
            anchor="w", pady=(14, 6))
        status_lbl = ctk.CTkLabel(wrap, text="", font=ctk.CTkFont(size=13),
                                  text_color=MUTED, anchor="w", wraplength=480,
                                  justify="left")
        status_lbl.pack(anchor="w", pady=(0, 6))

        dlg = wrap.master

        def recheck():
            status_lbl.configure(text="正在检测…", text_color=MUTED)

            def done(ok, _text):
                status_lbl.configure(
                    text=("✓ 已连上，可以开始用了！窗口马上自动关闭" if ok
                          else "○ 还没连上。请确认 Ollama 已安装并在运行，再点一次重试"),
                    text_color=OK if ok else ERR)
                if ok:
                    dlg.after(1400, dlg.destroy)
            threading.Thread(target=self._check_connection,
                             args=(done,), daemon=True).start()

        ctk.CTkButton(wrap, text="✓ 我装好了，重新检测", height=44,
                      corner_radius=10, font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=recheck).pack(fill="x")
        ctk.CTkButton(wrap, text="关  闭", height=36, corner_radius=10,
                      font=ctk.CTkFont(size=12),
                      fg_color="transparent", border_width=1,
                      border_color=BORDER, text_color=MUTED, hover_color=CARD_2,
                      command=dlg.destroy).pack(fill="x", pady=(14, 0))


    def _show_confirm(self, req: dict):
        """兼容旧入口：转成当前活动会话的确认卡"""
        ev = self.active.add("confirm", req=req, state="pending")
        self.chat.append(ev)
