"""数据目录：exe 可能被装在只读目录，数据一律放 %LOCALAPPDATA%/DesktopAgent"""
import os
from pathlib import Path


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = Path(base) / "DesktopAgent"
    (d / "logs").mkdir(parents=True, exist_ok=True)
    return d


def plugins_dir() -> Path:
    """插件目录：把 .py 插件放进来即安装（在用户数据目录，不随 exe 打包）"""
    d = data_dir() / "plugins"
    d.mkdir(parents=True, exist_ok=True)
    return d


def skills_dir() -> Path:
    """技能包目录：技能/专家包（文件夹 + SKILL.md）放进来即安装（不随 exe 打包）"""
    d = data_dir() / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return d
