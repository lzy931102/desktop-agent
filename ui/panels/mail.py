"""设置面板「邮件远程」分区（T4 Phase 2 从 gui.py 抽出，纯搬运零逻辑变更）。

_build_mail_section 原样保留 self 语义，AgentGUI 在 gui.py 里经 Mixin 组合
继承；邮件远程的接线（_ensure_mail_remote/_mail_forward 等）属主窗口核心
装配，仍留在 gui.py，经 self 互相调用。"""
from tkinter import messagebox

import customtkinter as ctk

from mail_remote import MailConfigError
from ui.theme import (ACCENT, BORDER, FAINT, INPUT_BG, MUTED, OK, TEXT,
                      WARN)

class MailSectionMixin:
    def _build_mail_section(self, dlg, box):
        """设置面板「邮件远程」分区（任务 18）：开关即时生效、不经「保存」。

        凭据（授权码）照云端 API Key 同一策略落本机 settings.json；
        开关不持久化——每次启动手动开启，与手机连接同一条控制权拍板。
        """
        mail_cfg = dict(self.settings.get("mail_remote", {}) or {})
        ctk.CTkLabel(box, text="✉️ 邮件远程（手机发邮件遥控电脑）",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(
            box,
            text="手机给上面的电脑邮箱发邮件就能下任务、查状态、停止，"
                 "结果自动回信到手机——出门在外不用同一 WiFi、不用隧道。"
                 "主题格式：[da] 任务内容 ／ [da] 状态 ／ [da] 停止",
            font=ctk.CTkFont(size=12), text_color=MUTED,
            wraplength=560, justify="left", anchor="w").pack(
            anchor="w", padx=14)

        grid = ctk.CTkFrame(box, fg_color="transparent")
        grid.pack(fill="x", padx=14, pady=(6, 0))
        user_var = ctk.StringVar(value=mail_cfg.get("username", ""))
        code_var = ctk.StringVar(value=mail_cfg.get("auth_code", ""))
        senders_var = ctk.StringVar(value=mail_cfg.get("allowed_senders", ""))
        imap_var = ctk.StringVar(value=mail_cfg.get("imap_host", ""))
        smtp_var = ctk.StringVar(value=mail_cfg.get("smtp_host", ""))
        poll_var = ctk.StringVar(value=str(mail_cfg.get("poll_seconds", 60)))

        def _row(label, var, show="", width=300, placeholder=""):
            r = ctk.CTkFrame(grid, fg_color="transparent")
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text=label, font=ctk.CTkFont(size=13),
                         text_color=MUTED, width=110, anchor="w").pack(
                side="left")
            ctk.CTkEntry(r, textvariable=var, show=show, width=width,
                         fg_color=INPUT_BG, border_color=BORDER,
                         placeholder_text=placeholder).pack(side="left",
                                                            padx=(6, 0))

        _row("电脑邮箱账号", user_var, width=300,
             placeholder="user@qq.com（收任务指令和回信都用它）")
        _row("授权码", code_var, show="*", width=300,
             placeholder="邮箱设置里开启 IMAP/SMTP 后生成，不是登录密码")
        _row("白名单发件人", senders_var, width=300,
             placeholder="手机邮箱，多个用逗号隔开（名单外一律不受理）")
        _row("收件服务器", imap_var, width=300,
             placeholder="留空自动识别（如 imap.qq.com）")
        _row("发件服务器", smtp_var, width=300,
             placeholder="留空自动识别（如 smtp.qq.com）")
        _row("轮询间隔（秒）", poll_var, width=120, placeholder="60")

        sw = ctk.CTkSwitch(box, text="启用邮件远程", progress_color=ACCENT,
                           text_color=TEXT, font=ctk.CTkFont(size=13))
        sw.pack(anchor="w", padx=14, pady=(8, 2))

        status_lbl = ctk.CTkLabel(box, text="", font=ctk.CTkFont(size=12),
                                  text_color=MUTED, wraplength=560,
                                  justify="left", anchor="w")
        status_lbl.pack(anchor="w", padx=14, pady=(4, 10))

        def refresh():
            try:
                if not status_lbl.winfo_exists():
                    return
                if sw.get() and self.mail_remote and self.mail_remote.running:
                    err = self.mail_remote.last_error
                    status_lbl.configure(
                        text=(f"✓ 已开启：{self.mail_remote.username} 正在监听"
                              if not err else f"⚠ 已开启，但最近一次检查失败：{err}"),
                        text_color=OK if not err else WARN)
                else:
                    status_lbl.configure(text="○ 未开启", text_color=FAINT)
            except Exception:
                pass

        def toggle():
            if sw.get():
                cfg = {"username": user_var.get(), "auth_code": code_var.get(),
                       "imap_host": imap_var.get(), "smtp_host": smtp_var.get(),
                       "allowed_senders": senders_var.get(),
                       "poll_seconds": poll_var.get(),
                       "subject_prefix": mail_cfg.get("subject_prefix", "[da]")}
                try:
                    self._ensure_mail_remote().start(cfg)
                except MailConfigError as e:
                    messagebox.showerror("邮件远程", str(e), parent=dlg)
                    sw.deselect()
                except Exception as e:
                    messagebox.showerror("邮件远程",
                                         f"开启失败：{type(e).__name__}: {e}",
                                         parent=dlg)
                    sw.deselect()
                    return
                # 凭据/配置照云端 Key 同策略落本机 settings.json，下次预填
                self.settings.set("mail_remote", {
                    **mail_cfg,
                    "username": user_var.get().strip(),
                    "auth_code": code_var.get().strip(),
                    "imap_host": imap_var.get().strip(),
                    "smtp_host": smtp_var.get().strip(),
                    "allowed_senders": senders_var.get().strip(),
                    "poll_seconds": poll_var.get().strip(),
                })
            else:
                if self.mail_remote:
                    self.mail_remote.stop()
            refresh()

        sw.configure(command=toggle)
        self._mail_ui = refresh
        refresh()
