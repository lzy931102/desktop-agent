"""core - DesktopAgent 的企业化基础设施模块包

设计原则：三档演进（个人 → 企业 → 大型企业平台）时，
只替换模块实现，主干（agent_loop / gui）不动。

模块清单：
- paths     数据目录解析（%LOCALAPPDATA%/DesktopAgent）
- audit     审计日志（防篡改哈希链；个人=本地 JSONL，企业=集中上报）
- guard     危险操作识别规则库（数据驱动，可独立更新规则）
- approval  操作确认策略（个人=GUI 弹窗；企业=审批流）
- history   任务历史（个人=本地 JSONL；企业=数据库）
"""
