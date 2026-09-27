"""示例技能/专家包源码（单一事实来源）。

GUI 的「生成示例」按钮按这里的内容往技能目录写包，改示例只改这里。
两个示例分别演示两类包的写法（格式说明见 docs/技能包指南.md）。
"""
from pathlib import Path

SAMPLE_SKILL_FOLDER = "示例技能-会议纪要"
SAMPLE_SKILL_MD = '''---
name: 会议纪要助手
version: 1.0.0
type: skill
description: 教 AI 把看到的屏幕内容整理成清楚的会议纪要
triggers: 会议纪要, 开会记录, 整理要点
---

整理会议纪要时，按这个格式输出：
1. 标题：日期 + 会议主题
2. 要点：一条一行，每条不超过 30 字，先说结论再说细节
3. 待办：谁、做什么、什么时候完成（会上没提到就写「未明确」）
4. 全文用大白话，不用「赋能」「抓手」这类词
'''

SAMPLE_EXPERT_FOLDER = "示例专家-耐心讲解员"
SAMPLE_EXPERT_MD = '''---
name: 耐心讲解员
version: 1.0.0
type: expert
description: 把 AI 变成对电脑新手很耐心的讲解员，说话慢、简单、一步步来
triggers: 教我, 怎么用, 讲解
---

你面对的是电脑新手，说话遵守：
1. 每次只讲一步，等这一步做完了再讲下一步
2. 不用专业词；必须用时，用一句大白话解释清楚
3. 每一步都说清「点哪里、会看到什么」
4. 对方说「没看到 / 没找到」时，换一种说法再讲一遍，不要责备
'''

# (类型, 文件夹名, SKILL.md 内容)
SAMPLES = (
    ("skill", SAMPLE_SKILL_FOLDER, SAMPLE_SKILL_MD),
    ("expert", SAMPLE_EXPERT_FOLDER, SAMPLE_EXPERT_MD),
)


def write_sample(kind: str, directory) -> Path:
    """把示例包写进技能目录，返回包文件夹路径（GUI 一键生成用）。"""
    for k, folder, md in SAMPLES:
        if k == kind:
            pack = Path(directory) / folder
            pack.mkdir(parents=True, exist_ok=True)
            (pack / "SKILL.md").write_text(md, encoding="utf-8")
            return pack
    raise ValueError(f"未知示例类型：{kind}（只支持 skill / expert）")
