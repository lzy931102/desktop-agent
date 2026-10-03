"""设置面板「手机连接」分区（T4 Phase 2 从 gui.py 抽出，纯搬运零逻辑变更）。

_build_phone_section/_phone_render_status 原样保留 self 语义，AgentGUI 在
gui.py 里经 Mixin 组合继承；手机桥的接线（_ensure_phone_bridge/_phone_forward
等）属主窗口核心装配，仍留在 gui.py，经 self 互相调用。"""
import threading
from tkinter import messagebox

import customtkinter as ctk
import tkinter as tk

try:
    from phone_bridge import ST_FAILED, ST_RUNNING, ST_STARTING
except ImportError:
    ST_FAILED = ST_RUNNING = ST_STARTING = None  # 手机连接组件未装齐时本分区不会被调用

from ui.theme import (ACCENT, ACCENT_HOVER, BORDER, CARD, CARD_2, ERR, FAINT,
                      MUTED, OK, TEXT, TOOLC, WARN)

class PhoneSectionMixin:
    def _build_phone_section(self, dlg, box):
        """设置面板「手机连接」分区：开关 + 二维码/链接 + 令牌重置 + 外网通道。

        开关即时生效、不经「保存」（开/关控制权通道都该是当下明确的动作）；
        动态区注册到 self._phone_ui，bridge 的 on_change（含隧道状态变化）
        经 _on_phone_change 防抖后到这里刷新。
        """
        ctk.CTkLabel(box, text="📱 手机连接（用手机遥控这台电脑）",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT).pack(anchor="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(box,
                     text="打开开关后手机扫码连接：在家用同一 WiFi 直连；"
                          "出门在外可开外网通道（地址每次都不同，需重新扫码）。",
                     font=ctk.CTkFont(size=12), text_color=MUTED,
                     wraplength=560, justify="left", anchor="w").pack(
            anchor="w", padx=14)

        sw = ctk.CTkSwitch(box, text="开启手机连接", progress_color=ACCENT,
                           text_color=TEXT, font=ctk.CTkFont(size=13))
        live = ctk.CTkFrame(box, fg_color="transparent")
        live.pack(fill="x", padx=14, pady=(6, 12))

        def refresh():
            try:
                for w in live.winfo_children():
                    w.destroy()
                bridge = self.phone_bridge
                if sw.get() and bridge is not None and bridge.running:
                    self._phone_render_status(live, bridge, refresh)
                else:
                    ctk.CTkLabel(live, text="○ 未开启。打开上面的开关，"
                                           "这里会出现二维码。",
                                 font=ctk.CTkFont(size=13),
                                 text_color=FAINT).pack(anchor="w")
            except Exception:
                self._phone_ui = None    # 面板正在销毁，不再刷新

        def toggle():
            if sw.get():
                try:
                    self._ensure_phone_bridge().start()
                except OSError as e:     # 端口附近全被占
                    messagebox.showerror("手机连接", f"开启失败：{e}",
                                         parent=dlg)
                    sw.deselect()
            else:
                if self.phone_bridge:
                    self.phone_bridge.stop()   # 外网通道一并收掉
            refresh()

        sw.configure(command=toggle)
        sw.pack(anchor="w", padx=14, pady=(8, 2))
        self._phone_ui = refresh
        refresh()


    def _phone_render_status(self, live, bridge, refresh):
        """「手机连接」开启后的动态区：二维码 + 链接 + 钥匙 + 外网通道。"""
        st = bridge.status()

        # ---- 在家（局域网直连，主路径）----
        head = f"✓ 已开启 · 电脑地址 {st['host_ip']}:{st['port']}"
        ctk.CTkLabel(live, text=head, font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=OK).pack(anchor="w")
        ctk.CTkLabel(live, text=st.get("network_hint", ""),
                     font=ctk.CTkFont(size=12), text_color=FAINT).pack(
            anchor="w")

        qr_row = ctk.CTkFrame(live, fg_color="transparent")
        qr_row.pack(fill="x", pady=(6, 0))
        try:
            img = tk.PhotoImage(data=bridge.qr_base64("lan", scale=5))
            lbl = tk.Label(qr_row, image=img, bg=CARD, bd=0,
                           highlightthickness=0)
            lbl.image = img      # 防 GC：PhotoImage 被回收二维码就花了
            lbl.pack(side="left")
        except Exception:
            ctk.CTkLabel(qr_row, text="二维码生成失败，请用下面这条链接手动打开",
                         font=ctk.CTkFont(size=12), text_color=WARN).pack(
                side="left")

        info = ctk.CTkFrame(qr_row, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=(14, 0))
        ctk.CTkLabel(info, text="手机扫码，或复制链接到手机浏览器打开",
                     font=ctk.CTkFont(size=12), text_color=MUTED,
                     wraplength=300, justify="left", anchor="w").pack(anchor="w")
        ctk.CTkLabel(info, text=st["lan_url"],
                     font=ctk.CTkFont(family="Consolas", size=11),
                     text_color=TOOLC, wraplength=300, justify="left",
                     anchor="w").pack(anchor="w", pady=(2, 0))
        ctk.CTkButton(info, text="📋 复制链接", width=88, height=24,
                      corner_radius=6, fg_color=CARD_2, hover_color=BORDER,
                      text_color=TEXT, font=ctk.CTkFont(size=12),
                      command=lambda: self._copy_text(st["lan_url"])
                      ).pack(anchor="w", pady=(4, 0))

        key_row = ctk.CTkFrame(info, fg_color="transparent")
        key_row.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(key_row, text=f"🔑 {st['token_masked']}",
                     font=ctk.CTkFont(size=12), text_color=FAINT).pack(
            side="left")

        def rotate():
            bridge.rotate_token()    # 旧链接/旧二维码立刻作废
            refresh()
        ctk.CTkButton(key_row, text="换一把钥匙", width=96, height=24,
                      corner_radius=6, fg_color=CARD_2, hover_color=BORDER,
                      text_color=TEXT, font=ctk.CTkFont(size=12),
                      command=rotate).pack(side="left", padx=(10, 0))

        # ---- 出门（cloudflared 外网通道，可选）----
        tun = st["tunnel"]
        ctk.CTkLabel(live, text="出门在外（外网通道）",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT).pack(anchor="w", pady=(12, 0))
        tun_row = ctk.CTkFrame(live, fg_color="transparent")
        tun_row.pack(fill="x", pady=(2, 0))

        def tunnel_on():
            bridge.enable_external()   # 结果经 on_change → refresh 呈现
            refresh()

        def tunnel_off():
            bridge.disable_external()
            refresh()

        if tun.get("has_binary"):
            if tun["state"] == ST_RUNNING:
                ctk.CTkButton(tun_row, text="关闭外网通道", width=110,
                              height=26, corner_radius=6, fg_color=CARD_2,
                              hover_color=BORDER, text_color=TEXT,
                              command=tunnel_off).pack(side="left")
            else:
                ctk.CTkButton(tun_row, text="开启外网通道", width=110,
                              height=26, corner_radius=6, fg_color=ACCENT,
                              hover_color=ACCENT_HOVER,
                              command=tunnel_on).pack(side="left")
        else:
            dl_lbl = ctk.CTkLabel(tun_row, text="", font=ctk.CTkFont(size=12),
                                  text_color=MUTED)
            dl_lbl.pack(side="left", padx=(10, 0))

            def start_download():
                dl_lbl.configure(text="准备下载…", text_color=MUTED)

                def prog(done, total):
                    if not total:
                        return
                    pct = min(100, done * 100 // total)

                    def upd(p=pct):
                        try:
                            if dl_lbl.winfo_exists():
                                dl_lbl.configure(text=f"下载中… {p}%")
                        except Exception:
                            pass
                    self.root.after(0, upd)

                def work():
                    from phone_bridge import fetcher
                    try:
                        fetcher.download_cloudflared(progress=prog)
                    except Exception as e:
                        msg = str(e) or f"下载失败（{type(e).__name__}）"

                        def fail(m=msg):
                            try:
                                if dl_lbl.winfo_exists():
                                    dl_lbl.configure(text=f"✗ {m}",
                                                     text_color=ERR)
                            except Exception:
                                pass
                        self.root.after(0, fail)
                        return

                    def ok():
                        tunnel_on()      # 下完直接开，少一次来回
                    self.root.after(0, ok)

                threading.Thread(target=work, daemon=True).start()

            ctk.CTkButton(tun_row, text="下载外网通道组件（约 60 MB，只下一次）",
                          width=250, height=26, corner_radius=6,
                          fg_color=ACCENT, hover_color=ACCENT_HOVER,
                          command=start_download).pack(side="left")

        tstate = tun["state"]
        if tstate == ST_RUNNING:
            tun_text, tun_color = (f"✓ {tun['message'] or '外网通道已开好'}", OK)
        elif tstate == ST_STARTING:
            tun_text, tun_color = (f"⏳ {tun['message'] or '正在开一条通往外网的路…'}",
                                   WARN)
        elif tstate == ST_FAILED:
            tun_text, tun_color = (f"✗ {tun['message'] or '开启失败'}", ERR)
        else:
            tun_text, tun_color = "○ 未开启", FAINT
        ctk.CTkLabel(live, text=tun_text, font=ctk.CTkFont(size=12),
                     text_color=tun_color, wraplength=560, justify="left",
                     anchor="w").pack(anchor="w", pady=(4, 0))
        if st["wan_url"]:
            ctk.CTkLabel(live, text="出门用这个地址（手机流量也能连；"
                                    "部分家用路由器解析不了它，连不上就回家用上面的码）：",
                         font=ctk.CTkFont(size=12), text_color=MUTED,
                         wraplength=560, justify="left", anchor="w").pack(
                anchor="w")
            ctk.CTkLabel(live, text=st["wan_url"],
                         font=ctk.CTkFont(family="Consolas", size=11),
                         text_color=TOOLC, wraplength=560, justify="left",
                         anchor="w").pack(anchor="w")

        ctk.CTkLabel(live,
                     text="⚠ 链接就是钥匙：二维码和链接只给家里人，别转发。"
                          "手机丢了或转发过截图，点「换一把钥匙」，旧的立刻作废。",
                     font=ctk.CTkFont(size=12), text_color=FAINT,
                     wraplength=560, justify="left", anchor="w").pack(
            anchor="w", pady=(10, 0))
