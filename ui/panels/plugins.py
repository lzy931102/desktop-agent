"""插件中心面板（T4 Phase 2 从 gui.py 抽出，纯搬运零逻辑变更）。

_show_plugins 原样保留 self 语义，AgentGUI 在 gui.py 里经 Mixin 组合继承；
技能/专家/连接器三类外部能力的管理界面，经 note()/reopen() 与主窗口对话流
及自身重建交互，全部走 self。"""
import sys
import threading
from tkinter import messagebox

import customtkinter as ctk

try:
    from plugin_system import PluginManager
except ImportError:
    PluginManager = None  # 插件系统未安装，fallback 到纯内置工具

try:
    from skill_system import SkillManager
except ImportError:
    SkillManager = None  # 技能系统未安装，fallback 到无技能模式

from ui.theme import (ACCENT, ACCENT_HOVER, BG, BORDER, CARD, CARD_2, ERR,
                      FAINT, INPUT_BG, MUTED, STATUS_COLOR, STATUS_ICON,
                      STATUS_TEXT, TEXT)
from ui.chat_stream import attach_modal_dialog

class PluginsMixin:
    def _show_plugins(self):
        """插件中心：三类外部能力统一管理（对齐 WorkBuddy 的 技能/专家/连接器）。

        - 技能：SKILL.md 说明书，教 AI 做某类事（纯文本，不执行代码）
        - 专家：SKILL.md 角色卡，改变 AI 的说话方式与侧重
        - 连接器：.py 工具插件，给 AI 接上外部工具（plugin_system）
        """
        from core.paths import plugins_dir, skills_dir

        dlg = ctk.CTkToplevel(self.root, fg_color=BG)
        dlg.title("插件：技能 / 专家 / 连接器")
        dlg.geometry("720x720")
        attach_modal_dialog(dlg, self.root)

        body = ctk.CTkFrame(dlg, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=14)
        ctk.CTkLabel(body, text="🔌 插件中心", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(body,
                     text="技能＝教 AI 做事的说明书　·　专家＝给 AI 换个角色　·　连接器＝给 AI 接外部工具",
                     font=ctk.CTkFont(size=13), text_color=MUTED).pack(
            anchor="w", pady=(2, 0))

        tabs = ctk.CTkTabview(body, fg_color="transparent",
                              segmented_button_selected_color=ACCENT,
                              segmented_button_selected_hover_color=ACCENT_HOVER,
                              text_color=TEXT)
        tabs.pack(fill="both", expand=True, pady=(12, 0))
        tab_skill = tabs.add("🧭 技能")
        tab_expert = tabs.add("🎭 专家")
        tab_conn = tabs.add("🔌 连接器")

        plugin_manager = (PluginManager(self.settings, directory=plugins_dir())
                          if PluginManager is not None else None)
        skill_manager = (SkillManager(self.settings, directory=skills_dir())
                         if SkillManager is not None else None)

        # ---- 公用小工具 ----

        def reopen():
            """重建面板（刷新/启停/安装后统一走这里，状态一定是最新的）"""
            dlg.destroy()
            self._show_plugins()

        def open_folder(path):
            import subprocess
            try:
                if sys.platform == "win":
                    subprocess.Popen(["explorer", str(path)])
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(path)])
                else:
                    subprocess.Popen(["xdg-open", str(path)])
            except Exception:
                pass

        def note(text, ok=True):
            """往当前任务对话流里加一条系统提示（没有任务就静默跳过）"""
            s = self.active
            if s:
                ev = s.add("system", text=("✓ " if ok else "✗ ") + text,
                           tone="ok" if ok else "err")
                if self.active is s:
                    self.chat.append(ev)

        # ---- 技能/专家包：通用行渲染 ----

        def render_pack_row(parent, info, manager):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=8)

            # 状态徽章（与任务列表同款图标）
            status_icon = STATUS_ICON.get(info.status, "·")
            status_text = STATUS_TEXT.get(info.status, "未知")
            status_color = STATUS_COLOR.get(info.status, FAINT)
            ctk.CTkLabel(row, text=f"{status_icon} {status_text}",
                         font=ctk.CTkFont(size=13),
                         text_color=status_color).pack(side="left", padx=(0, 8))

            # 包信息：名字 + 版本 + 一句话描述 + 什么时候用
            info_frame = ctk.CTkFrame(row, fg_color="transparent")
            info_frame.pack(side="left", fill="both", expand=True)
            ctk.CTkLabel(info_frame, text=info.display_name,
                         font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=TEXT).pack(anchor="w")
            meta = []
            if info.version:
                meta.append(f"v{info.version}")
            if info.description:
                meta.append(info.description[:46] + "…"
                            if len(info.description) > 46 else info.description)
            if info.triggers:
                meta.append("什么时候用：" + "、".join(info.triggers[:4]))
            if meta:
                ctk.CTkLabel(info_frame, text=" · ".join(meta),
                             font=ctk.CTkFont(size=13), text_color=MUTED).pack(
                    anchor="w", pady=(2, 0))
            if info.error:
                ctk.CTkLabel(info_frame, text=f"错误: {info.error[:70]}",
                             font=ctk.CTkFont(size=12), text_color=ERR).pack(
                    anchor="w", pady=(4, 0))

            # 删除（纯文本包，删了随时能重装；二次确认防手滑）
            def delete(i=info):
                if messagebox.askyesno("删除确认",
                                       f"确定删除「{i.display_name}」吗？",
                                       parent=dlg):
                    ok, msg = manager.remove(i.folder)
                    note(msg, ok=ok)
                    reopen()

            ctk.CTkButton(row, text="🗑", width=36, height=28,
                          fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                          command=delete).pack(side="right", padx=(8, 0))

            # 启停开关（对下一个任务生效）
            enabled_var = ctk.BooleanVar(value=info.enabled)
            switch = ctk.CTkSwitch(row, text="", variable=enabled_var,
                                   progress_color=ACCENT, text_color=TEXT,
                                   font=ctk.CTkFont(size=13),
                                   command=lambda i=info, e=enabled_var:
                                   manager.set_enabled(i.folder, e.get()))
            switch.pack(side="right", padx=(8, 0))
            switch.select() if info.enabled else switch.deselect()

        # ---- 技能/专家 Tab（同一套逻辑，类型不同） ----

        def render_pack_tab(tab, kind, sample_label):
            list_frame = ctk.CTkScrollableFrame(
                tab, fg_color=CARD, corner_radius=10,
                border_width=1, border_color=BORDER)
            list_frame.pack(fill="both", expand=True)

            if skill_manager is None:
                ctk.CTkLabel(list_frame, text="技能系统不可用（skill_system 未安装）",
                             font=ctk.CTkFont(size=12), text_color=MUTED).pack(
                    padx=12, pady=16)
                return

            packs = skill_manager.list_by_type(kind)
            if not packs:
                ctk.CTkLabel(list_frame,
                             text=f"还没有{sample_label.split('-')[0]}。点下面的「✨ 生成示例」"
                                  f"看个例子，或把别人分享的技能包文件夹放进技能目录",
                             font=ctk.CTkFont(size=12), text_color=MUTED).pack(
                    padx=12, pady=16)
            for info in packs:
                render_pack_row(list_frame, info, skill_manager)

            # 按钮两行：管理 + 安装
            btns1 = ctk.CTkFrame(tab, fg_color="transparent")
            btns1.pack(fill="x", pady=(10, 0))
            btns2 = ctk.CTkFrame(tab, fg_color="transparent")
            btns2.pack(fill="x", pady=(8, 0))

            def refresh():
                skill_manager.reload()
                reopen()

            def gen_sample():
                from skill_system.sample import write_sample
                write_sample(kind, skills_dir())
                skill_manager.reload()
                note(f"已生成示例：{sample_label}。可以打开技能目录，照着它的写法做自己的")
                reopen()

            def install_folder():
                from tkinter import filedialog
                src = filedialog.askdirectory(
                    title="选技能包文件夹（里面要有一个 SKILL.md）")
                if not src:
                    return
                ok, msg = skill_manager.install(src)
                note(msg, ok=ok)
                reopen()

            def install_url():
                u = ctk.CTkToplevel(dlg, fg_color=BG)
                u.title("从网址安装技能包")
                u.geometry("500x190")
                attach_modal_dialog(u, dlg)
                ctk.CTkLabel(u, text="粘贴技能包的网址（.zip 或 .md）",
                             font=ctk.CTkFont(size=13, weight="bold"),
                             text_color=TEXT).pack(anchor="w", padx=16, pady=(14, 4))
                ctk.CTkLabel(u, text="只装可信来源的技能包；AI 在任务里也能自己装",
                             font=ctk.CTkFont(size=12), text_color=MUTED).pack(
                    anchor="w", padx=16)
                entry = ctk.CTkEntry(u, placeholder_text="https://…/技能包.zip",
                                     fg_color=INPUT_BG, border_color=BORDER)
                entry.pack(fill="x", padx=16, pady=(6, 4))

                def do_install():
                    url = entry.get().strip()
                    if not url:
                        return
                    u.destroy()
                    note("正在下载并安装技能包…")

                    def worker():
                        ok, msg = skill_manager.install(url)

                        def done():
                            note(msg, ok=ok)
                            reopen()
                        self.root.after(0, done)
                    threading.Thread(target=worker, daemon=True).start()

                ctk.CTkButton(u, text="安装", width=120, height=34, corner_radius=8,
                              fg_color=ACCENT, hover_color=ACCENT_HOVER,
                              command=do_install).pack(pady=10)

            ctk.CTkButton(btns1, text="📂 打开技能目录", height=32,
                          fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                          command=lambda: open_folder(skills_dir())).pack(
                side="left", padx=(0, 8))
            ctk.CTkButton(btns1, text="🔄 刷新", height=32,
                          fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                          command=refresh).pack(side="left", padx=(0, 8))
            ctk.CTkButton(btns1, text="✨ 生成示例", height=32,
                          fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                          command=gen_sample).pack(side="left")
            ctk.CTkButton(btns2, text="📁 从文件夹安装", height=34,
                          fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT,
                          command=install_folder).pack(side="left", padx=(0, 8))
            ctk.CTkButton(btns2, text="🔗 从网址安装", height=34,
                          fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT,
                          command=install_url).pack(side="left")

        render_pack_tab(tab_skill, "skill", "示例技能-会议纪要")
        render_pack_tab(tab_expert, "expert", "示例专家-耐心讲解员")

        # ---- 连接器 Tab（.py 工具插件，plugin_system） ----

        conn_list = ctk.CTkScrollableFrame(tab_conn, fg_color=CARD, corner_radius=10,
                                           border_width=1, border_color=BORDER)
        conn_list.pack(fill="both", expand=True)

        if plugin_manager is None:
            ctk.CTkLabel(conn_list, text="插件系统不可用（plugin_system 未安装）",
                         font=ctk.CTkFont(size=12), text_color=MUTED).pack(
                padx=12, pady=16)
        else:
            infos = plugin_manager.list()
            if not infos:
                ctk.CTkLabel(conn_list,
                             text="还没有连接器。点下面的「✨ 生成示例插件」看个例子",
                             font=ctk.CTkFont(size=12), text_color=MUTED).pack(
                    padx=12, pady=16)
            for info in infos:
                row = ctk.CTkFrame(conn_list, fg_color="transparent")
                row.pack(fill="x", padx=10, pady=8)

                status_icon = STATUS_ICON.get(info.status, "·")
                status_text = STATUS_TEXT.get(info.status, "未知")
                status_color = STATUS_COLOR.get(info.status, FAINT)
                ctk.CTkLabel(row, text=f"{status_icon} {status_text}",
                             font=ctk.CTkFont(size=13),
                             text_color=status_color).pack(side="left", padx=(0, 8))

                info_frame = ctk.CTkFrame(row, fg_color="transparent")
                info_frame.pack(side="left", fill="both", expand=True)
                ctk.CTkLabel(info_frame, text=info.display_name,
                             font=ctk.CTkFont(size=13, weight="bold"),
                             text_color=TEXT).pack(anchor="w")
                meta = []
                if info.version:
                    meta.append(f"v{info.version}")
                if info.description:
                    meta.append(info.description[:46] + "…"
                                if len(info.description) > 46 else info.description)
                if meta:
                    ctk.CTkLabel(info_frame, text=" · ".join(meta),
                                 font=ctk.CTkFont(size=13), text_color=MUTED).pack(
                        anchor="w", pady=(2, 0))
                if info.error:
                    ctk.CTkLabel(info_frame, text=f"错误: {info.error[:70]}",
                                 font=ctk.CTkFont(size=12), text_color=ERR).pack(
                        anchor="w", pady=(4, 0))

                enabled_var = ctk.BooleanVar(value=info.enabled)
                switch = ctk.CTkSwitch(row, text="", variable=enabled_var,
                                       progress_color=ACCENT, text_color=TEXT,
                                       font=ctk.CTkFont(size=13),
                                       command=lambda i=info, e=enabled_var:
                                       plugin_manager.set_enabled(i.stem, e.get()))
                switch.pack(side="right", padx=(8, 0))
                switch.select() if info.enabled else switch.deselect()

        conn_btns = ctk.CTkFrame(tab_conn, fg_color="transparent")
        conn_btns.pack(fill="x", pady=(10, 0))

        def conn_refresh():
            if plugin_manager is not None:
                plugin_manager.reload()
            reopen()

        def conn_sample():
            from plugin_system.sample import SAMPLE_FILENAME, SAMPLE_PLUGIN_SOURCE
            plugins_dir().mkdir(parents=True, exist_ok=True)
            (plugins_dir() / SAMPLE_FILENAME).write_text(
                SAMPLE_PLUGIN_SOURCE, encoding="utf-8")
            if plugin_manager is not None:
                plugin_manager.reload()
            note(f"已生成示例插件：{SAMPLE_FILENAME}")
            reopen()

        ctk.CTkButton(conn_btns, text="📂 打开插件目录", height=32,
                      fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                      command=lambda: open_folder(plugins_dir())).pack(
            side="left", padx=(0, 8))
        ctk.CTkButton(conn_btns, text="🔄 刷新", height=32,
                      fg_color=CARD_2, hover_color=BORDER, text_color=TEXT,
                      command=conn_refresh).pack(side="left", padx=(0, 8))
        ctk.CTkButton(conn_btns, text="✨ 生成示例插件", height=32,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=TEXT,
                      command=conn_sample).pack(side="left")
