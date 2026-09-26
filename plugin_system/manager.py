"""插件管理器：扫描插件目录 → 动态加载 → 契约校验 → 输出可用工具。

设计要点（对应 docs/插件模块化方案.md §4）：
- fail-closed：任何一个插件坏掉只影响它自己（面板标红 + 可操作的原因），
  其余插件和主程序照常；
- 停用的插件根本不加载（不 import、不执行一行代码）；
- 工具清单按文件名排序输出，保证注入 system prompt 的顺序稳定
  （LLM 对工具清单顺序敏感，顺序抖动会影响效果）；
- reload() 全量重扫。插件是本地小文件、个位数数量级，成本可忽略。
"""
import importlib.util
from pathlib import Path

from core.paths import plugins_dir

from .contract import PluginContractError, PluginInfo, build_tools


def _short(text: str, limit: int = 240) -> str:
    text = str(text).strip() or "(无错误信息)"
    return text if len(text) <= limit else text[:limit] + "…"


class PluginManager:
    """插件加载与启停管理。gui 与 agent_loop 只依赖本类的四个公开方法。"""

    def __init__(self, settings, directory: Path = None):
        self.settings = settings
        self.dir = Path(directory) if directory else plugins_dir()
        self._infos = {}
        self.reload()

    # ---------- 对外接口 ----------

    def reload(self):
        """全量重扫插件目录。用户丢新文件 / 改文件 / 点面板「刷新」后调用。"""
        disabled = self._disabled_set()
        infos = {}
        seen_names, seen_tools = {}, {}
        for path in sorted(self.dir.glob("*.py"), key=lambda p: p.stem):
            stem = path.stem
            if stem.startswith("_"):
                continue   # _ 开头视为内部文件，不当插件
            if stem in disabled:
                # 停用 = 代码一行不跑，连 import 都不做；
                # 面板显示文件名，启用后重扫才能拿到 NAME 等元信息
                infos[stem] = PluginInfo(stem=stem, path=path, enabled=False)
                continue
            infos[stem] = self._load_one(path, seen_names, seen_tools)
        self._infos = infos

    def list(self):
        """全部插件的 PluginInfo（按文件名排序），供插件面板展示。"""
        return [self._infos[k] for k in sorted(self._infos)]

    def enabled_tools(self):
        """启用且加载成功的插件工具（按文件名排序，顺序稳定）。"""
        out = []
        for stem in sorted(self._infos):
            info = self._infos[stem]
            if info.status == "ok":
                out.extend(info.tools)
        return tuple(out)

    def set_enabled(self, stem: str, enabled: bool):
        """启停写回 settings.json（plugins.disabled 名单），对下一个任务生效。"""
        disabled = self._disabled_set()
        if enabled:
            disabled.discard(stem)
        else:
            disabled.add(stem)
        cfg = dict(self.settings.get("plugins", {}) or {})
        cfg["disabled"] = sorted(disabled)
        self.settings.set("plugins", cfg)

    def is_enabled(self, stem: str) -> bool:
        return stem not in self._disabled_set()

    # ---------- 内部实现 ----------

    def _disabled_set(self) -> set:
        cfg = self.settings.get("plugins", {}) or {}
        val = cfg.get("disabled", [])
        return {str(x) for x in val} if isinstance(val, list) else set()

    def _load_one(self, path: Path, seen_names: dict, seen_tools: dict) -> PluginInfo:
        stem = path.stem
        try:
            mod = self._import(path)

            name = getattr(mod, "NAME", None)
            if not isinstance(name, str) or not 2 <= len(name.strip()) <= 30:
                raise PluginContractError(
                    '缺少合法的 NAME：文件顶部加 NAME = "插件名"（2~30 个字）')
            name = name.strip()
            if name in seen_names:
                raise PluginContractError(
                    f"插件名「{name}」与 {seen_names[name]}.py 里的重复，请改名")

            getter = getattr(mod, "get_tools", None)
            if not callable(getter):
                raise PluginContractError(
                    "缺少 get_tools() 函数：def get_tools(): 返回工具定义列表")
            raw = getter()
            if not isinstance(raw, (list, tuple)):
                raise PluginContractError(
                    f"get_tools() 返回了 {type(raw).__name__}，应为列表")

            version = str(getattr(mod, "VERSION", "") or "").strip()
            desc = str(getattr(mod, "DESCRIPTION", "") or "").strip()
            # 先在副本上校验登记，全部通过才合并——半途失败的插件不留残余登记
            local_tools = dict(seen_tools)
            tools = build_tools(list(raw), name, local_tools)
        except PluginContractError as e:
            return PluginInfo(stem=stem, path=path, enabled=True, error=str(e))
        except Exception as e:   # 插件顶层代码的任意异常：隔离成一条错误，不影响其他插件
            return PluginInfo(stem=stem, path=path, enabled=True,
                              error=f"代码在加载阶段抛出异常 "
                                    f"{type(e).__name__}: {_short(e)}")
        seen_names[name] = stem
        seen_tools.update(local_tools)
        return PluginInfo(stem=stem, path=path, name=name, version=version,
                          description=desc, enabled=True, tools=tools)

    @staticmethod
    def _import(path: Path):
        """把 .py 文件加载成模块。不注册进 sys.modules：插件应为自包含单文件。"""
        spec = importlib.util.spec_from_file_location(f"_da_plugin_{path.stem}", path)
        if spec is None or spec.loader is None:
            raise PluginContractError("无法作为 Python 模块读取（检查文件名与编码）")
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except SyntaxError as e:
            raise PluginContractError(
                f"Python 语法错误（第 {e.lineno} 行）：{e.msg}") from None
        except Exception as e:
            raise PluginContractError(
                f"加载时代码抛出异常 {type(e).__name__}: {_short(e)}") from None
        return mod
