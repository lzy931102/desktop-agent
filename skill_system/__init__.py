"""skill_system：技能包/专家包系统（对齐 WorkBuddy 的 技能/专家 概念）。

- 技能（skill）：SKILL.md 说明书，教 AI 某类任务的标准做法
- 专家（expert）：SKILL.md 角色卡，改变 AI 的说话方式与侧重
- 连接器（可执行工具 .py 插件）在 plugin_system，两套系统互不干涉

一个技能包 = skills 目录下一个文件夹 + 一个 SKILL.md（纯文本，不执行代码）。
"""
from .manager import SkillManager
from .pack import SkillInfo, SkillPackError, parse_skill_md
from .sample import write_sample

__all__ = ["SkillManager", "SkillInfo", "SkillPackError",
           "parse_skill_md", "write_sample"]
