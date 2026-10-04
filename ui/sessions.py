# 任务会话状态。
# T4 Phase 1 从 gui.py 原样抽出；Tk 渲染全在主线程，本模块只管状态与线程。
import queue
import threading
import time
import traceback

from agent_loop import DesktopAgent, build_llm_client, final_reply_failed
from core import blackbox
from core.approval import GuiApprovalBridge
from ui.formatters import _effective_max_turns, humanize_error

try:
    from plugin_system import PluginManager
except ImportError:
    PluginManager = None  # 插件系统未安装，fallback 到纯内置工具

try:
    from skill_system import SkillManager
except ImportError:
    SkillManager = None  # 技能系统未安装，fallback 到无技能模式

class TaskSession:
    """一个任务会话 = 一个 Tab。只管状态与线程，Tk 渲染全在主线程。"""
    _seq = 0

    def __init__(self, title="新任务"):
        TaskSession._seq += 1
        self.id = f"t{TaskSession._seq}"
        self.title = title
        self.status = "draft"          # draft/queued/running/done/failed/stopped
        self.task_text = ""
        self.draft = ""                # 切走 Tab 时暂存输入框内容
        self.events = []               # 事件序列（tool/confirm 卡原地更新）
        self.ui_queue = queue.Queue()  # 工作线程 → 主线程 pump
        self.agent = None
        self.turn = 0
        self.start_time = None
        self.elapsed = None
        self.tokens = 0
        self.approval = GuiApprovalBridge()  # 每个任务独立审批桥，互不串扰
        self.stop_flag = False
        self.log_lines = []            # 实时日志（滚动区展示，可选中复制）
        self.current_action = ""       # 当前步骤描述（状态条展示）
        self.closing = False           # 已确认关闭、等线程收尾后再从列表摘除
        self.stop_requested_at = None  # 请求停止的时刻（30 秒兜底提示用）
        self.phone_task_id = None      # 手机下发的任务号（hub 对照）；本地任务为 None
        self.mail_task_id = None       # 邮件远程下发的任务号；本地任务为 None
        self._thread = None            # 工作线程引用（T23：僵尸会话判定用）

    # ---- 事件（主线程调用） ----
    def add(self, kind, **kw):
        ev = {"kind": kind}
        ev.update(kw)
        self.events.append(ev)
        return ev

    def last_tool_event(self, name):
        for ev in reversed(self.events):
            if ev.get("kind") == "tool" and ev.get("name") == name \
                    and ev.get("state") in ("run", "err"):
                return ev
        return None

    # ---- 执行（工作线程） ----
    def launch(self, app):
        self.status = "running"
        self.start_time = time.time()
        self.turn = 0
        self.closing = False
        self.stop_requested_at = None
        self._thread = threading.Thread(target=self._run, args=(app,),
                                        daemon=True)
        blackbox.write(f"task {self.id} thread-start", self.task_text[:100])
        self._thread.start()

    def _run(self, app):
        delivered = {"done": False}

        def _emit_done(ok, result, stopped):
            if delivered["done"]:
                return  # 终态幂等：任何路径只发一次
            delivered["done"] = True
            self.ui_queue.put(("done", (ok, result, stopped)))

        try:
            blackbox.write(f"task {self.id} run-enter")
            llm = build_llm_client(
                app.settings,
                on_fallback=lambda err: self.ui_queue.put(
                    ("log", f"⚠ 本地模型调用失败，自动切换云端：{err[:60]}")))

            # 插件管理器（可选）：有插件目录就创建，没有则跳过
            plugins = None
            if PluginManager is not None:
                from core.paths import plugins_dir
                plugins = PluginManager(app.settings, directory=plugins_dir())

            # 技能包管理器（可选）：技能/专家包指南注入 + install_skill 工具
            skills = None
            if SkillManager is not None:
                from core.paths import skills_dir
                skills = SkillManager(app.settings, directory=skills_dir())

            agent = DesktopAgent(llm, auditor=app.audit, history=app.history,
                                 approval=self.approval, plugins=plugins,
                                 skills=skills,
                                 max_turns=_effective_max_turns(app.settings))
            agent.on_log = lambda m: self.ui_queue.put(("log", m))
            agent.on_tool_call = lambda n, a: self.ui_queue.put(("tool_call", (n, a)))
            agent.on_tool_result = lambda n, a, r: self.ui_queue.put(
                ("tool_result", (n, a, r)))
            agent.on_retry = lambda n, i, mx: self.ui_queue.put(("retry", (n, i, mx)))
            # T24 过程可视化：每轮动手前的一句「为什么」进对话流
            agent.on_thought = lambda t: self.ui_queue.put(("thought", t))
            self.agent = agent
            result = agent.run(self.task_text)
            self.tokens = agent.total_tokens
            blackbox.write(f"task {self.id} run-exit", str(result)[:200])
            stopped = "停止" in (result or "")
            # 防假成功：流程走完 ≠ 任务成功，最终回复带失败信号按失败处理
            ok = (result is not None and not stopped
                  and not final_reply_failed(result))
            _emit_done(ok, result or "", stopped)
        except Exception as e:
            blackbox.write(f"task {self.id} exception", traceback.format_exc())
            _emit_done(False, humanize_error(str(e)), False)
        finally:
            # T23：任何退出路径（含 except Exception 接不住的 BaseException）
            # 都必须给界面一个终态——绝不留"执行中"僵尸会话
            if not delivered["done"]:
                blackbox.write(f"task {self.id} silent-exit")
                _emit_done(False, "任务线程意外退出，界面已复位；"
                                  "详情见 logs 下的 gui 日志。", False)

    def stop(self):
        self.stop_flag = True
        if self.agent:
            self.agent.stop()
        elif self._thread is not None and not self._thread.is_alive():
            # T23：僵尸会话（线程已死、done 已丢）直接给界面终态，停止不再空等
            blackbox.write(f"task {self.id} zombie-stop")
            self.ui_queue.put(("done", (False, "任务线程已不在运行，界面已复位。",
                                        False)))
