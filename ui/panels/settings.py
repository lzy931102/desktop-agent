"""设置面板（T4 Phase 2 从 gui.py 抽出，纯搬运零逻辑变更）。

_show_settings 原样保留 self 语义，AgentGUI 在 gui.py 里经 Mixin 组合继承；
手机/邮件分区（_build_phone_section/_build_mail_section）此刻仍在 AgentGUI
本体上，经 self 调用，后续拆分不受影响。"""
import os
import threading
from tkinter import messagebox

import customtkinter as ctk

import agent_vision
from agent_loop import LLMClient, LLMConfig, LLMProvider
from core.settings import (CLOUD_PRESETS, PROVIDER_ENUM,
                           VISION_MODEL_OPTIONS, resolve_api_key)

try:
    from phone_bridge import PhoneBridge
except ImportError:
    PhoneBridge = None  # 手机连接组件未装齐（如缺 segno），设置面板不显示该分区

from ui.theme import (ACCENT, ACCENT_HOVER, BG, BORDER, CARD, CARD_2,
                      DEFAULT_MAX_CONCURRENT, ERR, FAINT, INPUT_BG, MODEL_NAME,
                      MUTED, OK, OLLAMA_URL, TEXT, WARN, MSG_RESHOW_WELCOME)
from ui.formatters import _effective_max_turns
from ui.chat_stream import attach_modal_dialog

class SettingsMixin:
    def _show_settings(self, focus=None):
        """设置面板。focus="cloud"：从首启引导「用云端」进来——高亮云端区块
        并滚动到位，让用户一眼看到该填 Key 的地方（UX-P1-6）。"""
        dlg = ctk.CTkToplevel(self.root, fg_color=BG)
        dlg.title("设置")
        # 小屏（如 1366×768）按屏高压窗口，内容靠滚动条够到；固定 900 会让「保存」够不着
        dlg.geometry(f"620x{min(900, int(dlg.winfo_screenheight() * 0.8))}")
        attach_modal_dialog(dlg, self.root)

        body = ctk.CTkScrollableFrame(dlg, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=14)
        ctk.CTkLabel(body, text="⚙ 设置", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEXT).pack(anchor="w")

        # ---- 模型模式 ----
        ctk.CTkLabel(body, text="模型模式", font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(anchor="w", pady=(12, 2))
        mode_var = ctk.StringVar(value=self.settings.get("model_mode", "local"))
        mode_row = ctk.CTkFrame(body, fg_color="transparent")
        mode_row.pack(anchor="w")
        for label, val in (("只用本地", "local"), ("只用云端", "cloud"),
                           ("自动（本地优先）", "auto")):
            ctk.CTkRadioButton(mode_row, text=label, variable=mode_var, value=val,
                               text_color=TEXT, fg_color=ACCENT).pack(
                side="left", padx=(0, 14))

        # ---- 并行任务数 ----
        ctk.CTkLabel(body, text="同时执行的任务数（1-5，多任务会排队）",
                     font=ctk.CTkFont(size=12), text_color=MUTED).pack(
            anchor="w", pady=(12, 2))
        conc_var = ctk.StringVar(value=str(max(1, min(5, int(
            self.settings.get("max_concurrent", DEFAULT_MAX_CONCURRENT))))))
        ctk.CTkOptionMenu(body, values=["1", "2", "3", "4", "5"],
                          variable=conc_var, width=100, fg_color=INPUT_BG,
                          button_color=ACCENT, button_hover_color=ACCENT_HOVER).pack(
            anchor="w")

        # ---- 单任务最大轮次（T7）----
        # 10 轮对"开网页→看页面→记事本→保存"这类多步任务必顶格失败
        # （2026-09-30 晚 4/6 任务 max_turns），默认 30；复杂任务可再调大
        ctk.CTkLabel(body, text="单个任务最多执行几轮（复杂任务建议 25 以上）",
                     font=ctk.CTkFont(size=12), text_color=MUTED).pack(
            anchor="w", pady=(12, 2))
        turns_var = ctk.StringVar(value=str(_effective_max_turns(self.settings)))
        ctk.CTkOptionMenu(body, values=["10", "15", "20", "25", "30", "40", "50"],
                          variable=turns_var, width=100, fg_color=INPUT_BG,
                          button_color=ACCENT, button_hover_color=ACCENT_HOVER).pack(
            anchor="w")

        # ---- 本地配置 ----
        ctk.CTkLabel(body, text="本地模型（Ollama，数据不出本机）",
                     font=ctk.CTkFont(size=12), text_color=MUTED).pack(
            anchor="w", pady=(12, 2))
        model_var = ctk.StringVar(value=self.settings.get("local", {}).get(
            "model", self.settings.get("model", MODEL_NAME)))
        model_menu = ctk.CTkOptionMenu(body, values=["加载中…"], variable=model_var,
                                       width=320, fg_color=INPUT_BG,
                                       button_color=ACCENT,
                                       button_hover_color=ACCENT_HOVER)
        model_menu.pack(anchor="w")
        local_hint = ctk.CTkLabel(body, text="正在读取模型列表…",
                                  font=ctk.CTkFont(size=13), text_color=FAINT)
        local_hint.pack(anchor="w", pady=(4, 0))

        def refresh_models():
            # 网络请求放后台线程：Ollama 没开时主线程会冻 5 秒（踩坑.md 条目 4）
            def work():
                models = LLMClient(LLMConfig(
                    provider=LLMProvider.OLLAMA,
                    base_url=OLLAMA_URL)).list_models()

                def done():
                    if models:
                        model_menu.configure(values=models)
                        if model_var.get() not in models:
                            model_var.set(models[0])
                        local_hint.configure(text=f"共 {len(models)} 个本地模型可用")
                    else:
                        local_hint.configure(
                            text="读不到模型列表：本机 Ollama 没连上。请先启动 Ollama"
                                 "（任务栏右下角有它的图标才算在运行），关掉设置窗口重新"
                                 "打开即可刷新；不想装本机模型，也可以在下方「云端模型」"
                                 "填 API Key",
                            wraplength=560)
                self.root.after(0, done)
            threading.Thread(target=work, daemon=True).start()

        # ---- 云端配置 ----
        focus_cloud = (focus == "cloud")
        cloud_box = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10,
                                 border_width=2 if focus_cloud else 1,
                                 border_color=ACCENT if focus_cloud else BORDER)
        cloud_box.pack(fill="x", pady=(14, 0))
        if focus_cloud:
            ctk.CTkLabel(cloud_box, text="↑ 就在这里：选好服务商，粘贴 API Key，"
                                         "拉到底部点「保存」",
                         font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=ACCENT).pack(anchor="w", padx=14, pady=(10, 0))
        ctk.CTkLabel(cloud_box, text="云端模型", font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=14, pady=(10, 2))

        cloud_cfg = dict(self.settings.get("cloud", {}))
        preset_names = list(CLOUD_PRESETS.keys())
        provider_by_name = {name: CLOUD_PRESETS[name]["provider"]
                            for name in preset_names}
        name_by_provider = {v: k for k, v in provider_by_name.items()}
        provider_var = ctk.StringVar(value=name_by_provider.get(
            cloud_cfg.get("provider", "zhipu"), "智谱"))
        api_var = ctk.StringVar(value=cloud_cfg.get("api_key", ""))
        cmodel_var = ctk.StringVar(value=cloud_cfg.get("model", "glm-4-flash"))
        cbase_var = ctk.StringVar(value=cloud_cfg.get(
            "base_url", CLOUD_PRESETS["智谱"]["base_url"]))

        prow = ctk.CTkFrame(cloud_box, fg_color="transparent")
        prow.pack(fill="x", padx=14)
        ctk.CTkLabel(prow, text="服务商", font=ctk.CTkFont(size=13),
                     text_color=MUTED).pack(side="left")
        provider_menu = ctk.CTkOptionMenu(prow, values=preset_names,
                                          variable=provider_var, width=130,
                                          fg_color=INPUT_BG, button_color=ACCENT)
        provider_menu.pack(side="left", padx=(8, 0))

        def on_provider_change(_=None):
            preset = CLOUD_PRESETS.get(provider_var.get())
            if preset:
                cbase_var.set(preset["base_url"])
                cmodel_var.set(preset["model"])
        provider_menu.configure(command=on_provider_change)

        ctk.CTkLabel(cloud_box, text="API Key（留空则使用环境变量）",
                     font=ctk.CTkFont(size=13), text_color=MUTED).pack(
            anchor="w", padx=14, pady=(8, 2))
        api_entry = ctk.CTkEntry(cloud_box, textvariable=api_var, show="*",
                                 width=340, fg_color=INPUT_BG, border_color=BORDER)
        api_entry.pack(anchor="w", padx=14)

        crow = ctk.CTkFrame(cloud_box, fg_color="transparent")
        crow.pack(fill="x", padx=14, pady=(8, 4))
        ctk.CTkLabel(crow, text="模型名", font=ctk.CTkFont(size=13),
                     text_color=MUTED).pack(side="left")
        ctk.CTkEntry(crow, textvariable=cmodel_var, width=170,
                     fg_color=INPUT_BG, border_color=BORDER).pack(side="left",
                                                                  padx=(8, 12))
        ctk.CTkLabel(crow, text="接口地址", font=ctk.CTkFont(size=13),
                     text_color=MUTED).pack(side="left")
        ctk.CTkEntry(crow, textvariable=cbase_var, width=250,
                     fg_color=INPUT_BG, border_color=BORDER).pack(side="left",
                                                                  padx=(8, 0))

        # ---- 看屏幕（视觉理解）----
        # 2026-09-28：看屏幕从「本机 qwen-vl」改走云端（本机一张屏 107 秒，必然超时）
        vision_cfg = dict(self.settings.get("vision", {}) or {})
        _VIS_LABELS = {"auto": "自动（推荐）", "cloud": "只用云端",
                       "local": "只用本机"}
        _VIS_BY_LABEL = {v: k for k, v in _VIS_LABELS.items()}
        vis_mode_var = ctk.StringVar(value=_VIS_LABELS.get(
            vision_cfg.get("mode", "auto"), "自动（推荐）"))
        vis_model_var = ctk.StringVar(value=vision_cfg.get(
            "cloud_model", VISION_MODEL_OPTIONS[0]))

        vrow = ctk.CTkFrame(cloud_box, fg_color="transparent")
        vrow.pack(fill="x", padx=14, pady=(8, 0))
        ctk.CTkLabel(vrow, text="看屏幕", font=ctk.CTkFont(size=13),
                     text_color=MUTED).pack(side="left")
        ctk.CTkOptionMenu(vrow, values=list(_VIS_LABELS.values()),
                          variable=vis_mode_var, width=118,
                          fg_color=INPUT_BG, button_color=ACCENT).pack(
            side="left", padx=(8, 12))
        ctk.CTkLabel(vrow, text="视觉模型", font=ctk.CTkFont(size=13),
                     text_color=MUTED).pack(side="left")
        ctk.CTkOptionMenu(vrow, values=list(VISION_MODEL_OPTIONS),
                          variable=vis_model_var, width=170,
                          fg_color=INPUT_BG, button_color=ACCENT).pack(
            side="left", padx=(8, 0))
        ctk.CTkLabel(cloud_box,
                     text="看屏幕会把当前截图上传给服务商；选「只用本机」则不上传（慢很多）",
                     font=ctk.CTkFont(size=12), text_color=MUTED).pack(
            anchor="w", padx=14, pady=(4, 0))

        test_row = ctk.CTkFrame(cloud_box, fg_color="transparent")
        test_row.pack(fill="x", padx=14, pady=(6, 12))
        test_result = ctk.CTkLabel(test_row, text="", font=ctk.CTkFont(size=13),
                                   text_color=MUTED, anchor="w")
        preset = CLOUD_PRESETS.get(provider_var.get(), {})
        if preset and os.environ.get(preset["env"]):
            test_result.configure(text="✓ 检测到环境变量，优先使用", text_color=OK)

        def run_test():
            test_result.configure(text="测试中…", text_color=MUTED)

            def work():
                cfg = LLMConfig(
                    provider=LLMProvider(PROVIDER_ENUM.get(
                        provider_by_name.get(provider_var.get(), "zhipu"), "other")),
                    api_key=api_var.get().strip() or resolve_api_key(
                        {"provider": provider_by_name.get(provider_var.get(), "zhipu")})[0],
                    base_url=cbase_var.get().strip(),
                    model=cmodel_var.get().strip(),
                )
                ok, msg = LLMClient(cfg).ping()
                # 后台线程不碰控件，结果投回主线程更新（对齐 _check_connection）
                self.root.after(0, lambda: test_result.configure(
                    text=("✓ " if ok else "✗ ") + msg,
                    text_color=OK if ok else ERR))
            threading.Thread(target=work, daemon=True).start()

        ctk.CTkButton(test_row, text="测试连接", width=100, height=26,
                      corner_radius=6, fg_color=CARD_2, hover_color=BORDER,
                      text_color=TEXT, command=run_test).pack(side="left")
        test_result.pack(side="left", padx=10)

        # ---- 其他 ----
        tray_var = ctk.BooleanVar(value=self.settings.get("minimize_to_tray", True))
        ctk.CTkSwitch(body, text="关闭窗口时最小化到系统托盘", variable=tray_var,
                      progress_color=ACCENT, text_color=TEXT,
                      font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(14, 0))

        # 「重新显示引导」（T24 任务 1 第 4 点）：第一次用没看懂，随时回来看。
        # 先关设置窗再弹卡——两张模态卡叠着会互抢焦点（attach_modal_dialog
        # 禁用的都是主窗口，设置窗不会自己让位）
        ctk.CTkButton(body, text=MSG_RESHOW_WELCOME, height=32, corner_radius=8,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=MUTED, hover_color=CARD_2,
                      font=ctk.CTkFont(size=12), anchor="w",
                      command=lambda: (dlg.destroy(), self._show_welcome())
                      ).pack(anchor="w", pady=(10, 0))

        # ---- 飞书群通知 ----
        feishu_var = ctk.StringVar(value=self.settings.get("feishu_webhook", ""))
        feishu_box = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10,
                                  border_width=1, border_color=BORDER)
        feishu_box.pack(fill="x", pady=(14, 0))
        ctk.CTkLabel(feishu_box, text="飞书群通知（电脑↔手机）",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(feishu_box,
                     text="粘贴群机器人的 Webhook 地址后，Agent 可直接给飞书群发消息",
                     font=ctk.CTkFont(size=13), text_color=MUTED).pack(
            anchor="w", padx=14)
        ctk.CTkEntry(feishu_box, textvariable=feishu_var,
                     placeholder_text="https://open.feishu.cn/open-apis/bot/v2/hook/…",
                     fg_color=INPUT_BG, border_color=BORDER).pack(
            fill="x", padx=14, pady=(6, 12))

        # ---- 手机连接（任务 16 接线）----
        # 唯一入口就在设置面板：手机连接是把电脑控制权递出去的通道，克制
        # 不加托盘/顶栏快捷入口；开关即时生效、不经「保存」，也**不持久化**——
        # 每次启动重新手动打开（令牌每次启动都是新的，手机重新扫码即可）
        if PhoneBridge is not None:
            phone_box = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10,
                                     border_width=1, border_color=BORDER)
            phone_box.pack(fill="x", pady=(14, 0))
            self._build_phone_section(dlg, phone_box)

            def _phone_ui_gone(event=None):
                # <Destroy> 对每个子控件都触发，只认对话框自身（同模态钩子）
                if event is not None and str(event.widget) != str(dlg):
                    return
                self._phone_ui = None
            dlg.bind("<Destroy>", _phone_ui_gone)

        # ---- 邮件远程（mail_remote 独立模块，任务 18）----
        # 与手机连接同一条拍板：控制权通道默认关闭、手动开启、不持久化；
        # 邮箱授权码照 settings.json 本机留存（同云端 API Key 的凭据策略）
        mail_box = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10,
                                border_width=1, border_color=BORDER)
        mail_box.pack(fill="x", pady=(14, 0))
        self._build_mail_section(dlg, mail_box)

        def _mail_ui_gone(event=None):
            if event is not None and str(event.widget) != str(dlg):
                return
            self._mail_ui = None
        dlg.bind("<Destroy>", _mail_ui_gone)

        def save():
            self.settings.set("model_mode", mode_var.get())
            self.settings.set("max_concurrent", int(conc_var.get()))
            self.settings.set("max_turns", int(turns_var.get()))
            self.settings.set("local", {**self.settings.get("local", {}),
                                        "model": model_var.get(),
                                        "base_url": OLLAMA_URL,
                                        "provider": "ollama"})
            self.settings.set("cloud", {
                "provider": provider_by_name.get(provider_var.get(), "zhipu"),
                "api_key": api_var.get().strip(),
                "base_url": cbase_var.get().strip(),
                "model": cmodel_var.get().strip(),
            })
            self.settings.set("vision", {
                **self.settings.get("vision", {}),
                "mode": _VIS_BY_LABEL.get(vis_mode_var.get(), "auto"),
                "cloud_model": vis_model_var.get().strip(),
            })
            agent_vision.reset_vision()  # 让新的视觉配置立刻生效
            self.settings.set("minimize_to_tray", bool(tray_var.get()))
            self.settings.set("feishu_webhook", feishu_var.get().strip())
            s = self.active
            if s:
                s.add("system", text="⚙ 设置已保存，马上生效。", tone="ok")
                if self.active is s:
                    self.chat.append(s.events[-1])
            self._sync_privacy_banner()
            threading.Thread(target=self._check_connection, daemon=True).start()
            dlg.destroy()

        ctk.CTkButton(body, text="保存", width=170, height=38, corner_radius=8,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      command=save).pack(anchor="w", pady=(16, 0))
        body.after(200, refresh_models)

        if focus_cloud:
            def scroll_to_cloud():
                dlg.update_idletasks()
                try:
                    canvas = getattr(body, "_parent_canvas")
                    total = max(1, body.winfo_reqheight())
                    canvas.yview_moveto(
                        min(1.0, max(0.0, (cloud_box.winfo_y() - 10) / total)))
                except Exception:
                    pass  # 滚不到就靠高亮边框 + 提示条定位，不影响使用
            dlg.after(180, scroll_to_cloud)
