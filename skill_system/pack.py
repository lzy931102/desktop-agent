"""技能包契约：一个技能包 = skills 目录下的一个文件夹，里面放一个 SKILL.md。

SKILL.md 是纯文本说明书（不执行代码），用 --- 包住的头块声明元信息：

    ---
    name: 会议纪要助手            # 显示名，2~30 个字（面板展示）
    version: 1.0.0               # 版本号（面板展示，可省略）
    type: skill                  # skill=技能（教 AI 做事的说明书）
                                 # expert=专家（给 AI 换个角色/说话方式）
    description: 一句话描述干什么用（面板展示 + 进提示词的简介）
    triggers: 会议纪要, 整理要点  # 什么时候适用，逗号分隔（可省略）
    ---

    正文：给 AI 的具体指南。包启用后正文会注入 system prompt，
    保持简短（建议 50 行以内），太长会被截断。

两类包对齐 WorkBuddy 的概念：
- 技能（skill）＝说明书：教 AI 某类任务的标准做法
- 专家（expert）＝角色卡：改变 AI 的说话方式与侧重
- 连接器（可执行工具插件）由 plugin_system 管理，不在本系统内

与 plugin_system 的契约风格一致：错误信息面向包作者、说人话、可直接照着改；
任何一个包坏掉只影响它自己（fail-closed），其余包与主程序照常。
"""
import re
from dataclasses import dataclass

MAX_BODY_CHARS = 2500   # 正文注入上限：太长会挤占小模型上下文（glm-4-flash 等）

VALID_TYPES = ("skill", "expert")
TYPE_LABELS = {"skill": "技能", "expert": "专家"}


class SkillPackError(ValueError):
    """技能包不符合契约。str(e) 面向包作者，可直接照着改。"""


@dataclass
class SkillInfo:
    """单个技能包的加载结果（插件面板展示与启停的最小单元）"""
    folder: str                # 文件夹名，settings 里的启停标识
    path: object = None        # Path(SKILL.md)
    name: str = ""             # 显示名
    version: str = ""
    kind: str = "skill"        # skill | expert
    description: str = ""
    triggers: tuple = ()       # 适用场景词（面板展示用）
    body: str = ""             # 给 AI 的指南正文
    enabled: bool = True
    error: str = ""            # 非空 = 加载失败（面向作者的可操作信息）

    @property
    def status(self) -> str:
        """ok=已启用且解析成功；disabled=已停用；error=解析失败"""
        if self.error:
            return "error"
        return "ok" if self.enabled else "disabled"

    @property
    def display_name(self) -> str:
        return self.name or self.folder

    @property
    def type_label(self) -> str:
        return TYPE_LABELS.get(self.kind, self.kind)


def _parse_header_line(line: str, where: str):
    if ":" not in line:
        raise SkillPackError(
            f"{where}：这行没有冒号，应写成「字段名: 值」：{line[:40]}")
    key, _, value = line.partition(":")
    key = key.strip().lower()
    if not key:
        raise SkillPackError(f"{where}：字段名为空：{line[:40]}")
    return key, value.strip()


def parse_skill_md(text: str, where: str = "SKILL.md") -> dict:
    """解析 SKILL.md 文本 → 元信息 dict。任何格式问题抛 SkillPackError。

    只认「--- 包住的头块 + 正文」，不做完整 YAML（不引依赖）；
    头块里多写的字段忽略，兼容不同模板。
    """
    if not isinstance(text, str) or not text.strip():
        raise SkillPackError(f"{where}：文件是空的，按 docs/技能包指南.md 的格式写")
    text = text.lstrip("\ufeff")                  # 去 BOM（记事本另存可能带）
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillPackError(f"{where}：第一行必须是 ---（头块开始标记）")
    header = {}
    end = None
    for i in range(1, len(lines)):
        s = lines[i].strip()
        if s == "---":
            end = i
            break
        if not s or s.startswith("#"):
            continue                              # 空行 / 注释行跳过
        key, value = _parse_header_line(s, where)
        header[key] = value
    if end is None:
        raise SkillPackError(f"{where}：头块没有结束：第二行 --- 缺失")
    body = "\n".join(lines[end + 1:]).strip()

    name = header.get("name", "").strip()
    if not 2 <= len(name) <= 30:
        raise SkillPackError(
            f"{where}：name 必须是 2~30 个字（面板显示名），当前：{name!r}")
    kind = (header.get("type", "skill") or "skill").strip().lower()
    if kind not in VALID_TYPES:
        raise SkillPackError(
            f"{where}：type 只能是 skill（技能）或 expert（专家），当前：{kind!r}")
    description = header.get("description", "").strip()
    if not description:
        raise SkillPackError(f"{where}：缺少 description：写一句话描述干什么用")
    if len(description) > 60:
        description = description[:60] + "…"
    triggers = tuple(
        t.strip() for t in re.split(r"[,，、]", header.get("triggers", ""))
        if t.strip())[:6]
    if len(body) > MAX_BODY_CHARS:
        body = (body[:MAX_BODY_CHARS]
                + "\n…（正文过长已截断，请精简 SKILL.md，建议 50 行以内）")
    return {"name": name, "version": header.get("version", "").strip(),
            "kind": kind, "description": description,
            "triggers": triggers, "body": body}


def load_pack(folder: str, skill_md_path) -> SkillInfo:
    """读一个包文件夹里的 SKILL.md → SkillInfo。解析失败 → 带 error 的 SkillInfo。"""
    try:
        text = skill_md_path.read_text(encoding="utf-8")
        meta = parse_skill_md(text, where=f"{folder}/SKILL.md")
    except SkillPackError as e:
        return SkillInfo(folder=folder, path=skill_md_path, enabled=True, error=str(e))
    except Exception as e:   # 编码错误等：隔离成一条错误，不影响其他包
        return SkillInfo(folder=folder, path=skill_md_path, enabled=True,
                         error=f"SKILL.md 读不出来（{type(e).__name__}: {e}）")
    return SkillInfo(folder=folder, path=skill_md_path, enabled=True, **meta)
