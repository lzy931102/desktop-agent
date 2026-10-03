"""首启引导卡与高危确认入口（T4 Phase 2 从 gui.py 抽出，纯搬运零逻辑变更）。

方法原样保留 self 语义，AgentGUI 在 gui.py 里经 Mixin 组合继承；
跨面板调用（如引导卡「用云端」→ 设置面板）仍走 self.xxx。"""
import threading
import webbrowser
import customtkinter as ctk
from ui.theme import (ACCENT, ACCENT_HOVER, BG, BORDER, CARD_2,
                      CLOUD_TUTORIAL_URL, ERR, FAINT, MUTED, OK,
                      OLLAMA_DOWNLOAD_URL, TEXT, WARN)
from ui.chat_stream import attach_modal_dialog

class DialogsMixin:
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
