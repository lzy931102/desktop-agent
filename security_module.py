#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Security 模块 - Agent 操作安全拦截器 v2.0
修复：
1. 发送消息改为默认拦截 + 白名单放行
2. shell 命令独立分类（不再误分类为 file_delete）
3. 日志文案修复（放行/拦截/记录）
"""

import os
import re
import json
import time
import datetime
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any, Set
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps


CONFIG_FILE = Path("agent_config.json")
DEFAULT_CONFIG = {
    "security": {
        "trusted_contacts": [],
        "trusted_groups": [],
        "max_recipients_without_approval": 1,
        "sensitive_keywords": ["密码", "验证码", "银行卡", "身份证", "password", "code"]
    }
}


def load_config() -> Dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_CONFIG


class RiskLevel(Enum):
    SAFE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @classmethod
    def from_string(cls, s: str) -> "RiskLevel":
        mapping = {
            "safe": cls.SAFE, "low": cls.LOW, "medium": cls.MEDIUM,
            "high": cls.HIGH, "critical": cls.CRITICAL,
        }
        return mapping.get(s.lower(), cls.SAFE)

    def to_string(self) -> str:
        return self.name.lower()


@dataclass
class SecurityAction:
    action_type: str
    target: str
    command: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.SAFE
    description: str = ""
    recipients: List[str] = field(default_factory=list)
    content: str = ""
    attachments: List[str] = field(default_factory=list)


@dataclass
class SecurityCheckResult:
    allowed: bool
    risk_level: RiskLevel
    reason: str
    requires_approval: bool = False
    logged: bool = True
    action_taken: str = ""


SHELL_COMMAND_CATEGORIES = {
    "file_delete": {
        "patterns": [r"\brm\b", r"\bdel\b", r"\brmdir\b", r"\bunlink\b"],
        "keywords": ["rm -rf", "rm -r", "del ", "rmdir", "unlink"],
        "risk_level": RiskLevel.CRITICAL,
    },
    "network_download": {
        "patterns": [r"\bcurl\b", r"\bwget\b", r"\binvoke-webrequest\b"],
        "keywords": ["curl", "wget", "Invoke-WebRequest", "download"],
        "risk_level": RiskLevel.CRITICAL,
    },
    "system_control": {
        "patterns": [r"\bshutdown\b", r"\breboot\b", r"\bpoweroff\b"],
        "keywords": ["shutdown", "reboot", "poweroff"],
        "risk_level": RiskLevel.CRITICAL,
    },
    "system_modify": {
        "patterns": [r"\breg\s+add\b", r"\bsystemctl\b", r"\bsc\s+config\b"],
        "keywords": ["reg add", "systemctl", "sc config", "net user"],
        "risk_level": RiskLevel.CRITICAL,
    },
    "shell_command_unknown": {
        "patterns": [], "keywords": [],
        "risk_level": RiskLevel.CRITICAL,
    },
}

SYSTEM_DIRECTORIES = [
    r"C:\Windows\System32", r"C:\Windows\SysWOW64",
    r"C:\Program Files", r"C:\Program Files (x86)",
    "/etc", "/bin", "/sbin", "/usr", "/root",
]

DANGEROUS_RULES = [
    {"pattern": r"(delete|remove|unlink)\s+.*", "action_type": "file_delete", "risk_level": RiskLevel.HIGH,
     "keywords": ["删除", "delete", "remove", "unlink"], "requires_approval": True},
    {"pattern": r"(format|mkfs)\s+", "action_type": "format_disk", "risk_level": RiskLevel.CRITICAL,
     "keywords": ["format", "mkfs", "格式化"], "requires_approval": True},
    {"pattern": r"format\s+[a-zA-Z]:", "action_type": "format_disk", "risk_level": RiskLevel.CRITICAL,
     "keywords": ["format c:", "format d:"], "requires_approval": True},
    {"pattern": r"(subprocess\.run|os\.system|exec|eval)\s*\(.*\)", "action_type": "shell_command",
     "risk_level": RiskLevel.CRITICAL, "keywords": ["subprocess.run", "os.system", "exec", "eval"],
     "requires_approval": True},
    {"pattern": r"(cmd|powershell|bash|sh)\s+(-c|/c)\s+", "action_type": "shell_command",
     "risk_level": RiskLevel.CRITICAL, "keywords": ["cmd /c", "powershell -c", "bash -c"],
     "requires_approval": True},
    {"pattern": r"(shutdown|reboot|restart)\s+", "action_type": "system_power",
     "risk_level": RiskLevel.CRITICAL, "keywords": ["shutdown", "reboot", "restart"],
     "requires_approval": True},
    {"pattern": r"(reg\s+add|regedit|systemctl|net\s+user)\s+", "action_type": "system_config",
     "risk_level": RiskLevel.CRITICAL, "keywords": ["reg add", "regedit", "systemctl", "net user"],
     "requires_approval": True},
    {"pattern": r"(diskpart|fdisk|parted)\s+", "action_type": "disk_operation",
     "risk_level": RiskLevel.CRITICAL, "keywords": ["diskpart", "fdisk", "parted"],
     "requires_approval": True},
    {"pattern": r"file://", "action_type": "ssrf", "risk_level": RiskLevel.CRITICAL,
     "keywords": ["file://"], "requires_approval": True},
    {"pattern": r"echo\s+.*(\||>)", "action_type": "shell_piping", "risk_level": RiskLevel.HIGH,
     "keywords": ["echo", "|", ">"], "requires_approval": True},
]

SAFE_ACTIONS = [
    {"action_type": "open_app", "keywords": ["notepad", "记事本", "calc", "计算器"]},
    {"action_type": "read_file", "keywords": ["read", "cat", "type", "读取"]},
    {"action_type": "search", "keywords": ["search", "find", "grep", "搜索"]},
    {"action_type": "screenshot", "keywords": ["screenshot", "截图"]},
    {"action_type": "keyboard", "keywords": ["type", "press", "hotkey", "键盘"]},
]

SAFE_APPS = [
    "notepad", "notepad.exe", "calc", "calc.exe",
    "explorer", "explorer.exe", "mspaint", "mspaint.exe",
    "word", "winword.exe", "excel", "chrome", "msedge",
    "code", "code.exe",
]


class SecurityModule:
    def __init__(self, log_dir: str = "security_logs", auto_approve: bool = False):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.auto_approve = auto_approve
        self.config = load_config()
        self.security_config = self.config.get("security", DEFAULT_CONFIG["security"])
        self._log_file = self.log_dir / f"security_{datetime.datetime.now().strftime('%Y%m%d')}.jsonl"

    def check(self, action: SecurityAction) -> SecurityCheckResult:
        # 1. 白名单 → 放行
        if self._is_safe_action(action):
            result = SecurityCheckResult(
                allowed=True, risk_level=RiskLevel.SAFE,
                reason="安全操作，允许执行", requires_approval=False,
                logged=True, action_taken="放行"
            )
            self._log(action, result)
            return result

        # 2. 危险规则 → 拦截
        risk_level, matched_rule = self._check_dangerous_rules(action)

        if action.action_type == "send_message":
            risk_level, reason = self._check_message_risk(action)
            if risk_level == RiskLevel.CRITICAL:
                result = SecurityCheckResult(
                    allowed=False, risk_level=risk_level,
                    reason=reason, requires_approval=False,
                    logged=True, action_taken="拦截"
                )
            elif risk_level == RiskLevel.HIGH:
                result = SecurityCheckResult(
                    allowed=False, risk_level=risk_level,
                    reason=reason, requires_approval=True,
                    logged=True, action_taken="拦截"
                )
            else:
                result = SecurityCheckResult(
                    allowed=True, risk_level=risk_level,
                    reason=reason, requires_approval=False,
                    logged=True, action_taken="放行" if risk_level == RiskLevel.SAFE else "记录"
                )
            self._log(action, result)
            return result

        if action.action_type == "shell_command" and action.command:
            sub_type, sub_risk = self._classify_shell_command(action.command)
            if sub_risk.value >= RiskLevel.CRITICAL.value:
                result = SecurityCheckResult(
                    allowed=False, risk_level=sub_risk,
                    reason=f"shell命令拦截: {sub_type}", requires_approval=True,
                    logged=True, action_taken="拦截"
                )
                self._log(action, result)
                return result

        if risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]:
            requires_approval = matched_rule.get("requires_approval", True) if matched_rule else True
            result = SecurityCheckResult(
                allowed=False, risk_level=risk_level,
                reason=f"危险操作拦截: {matched_rule.get('action_type', 'unknown') if matched_rule else 'unknown'}",
                requires_approval=requires_approval, logged=True, action_taken="拦截"
            )
            self._log(action, result)
            return result

        # 3. 灰名单（未知操作）→ 需要审批
        if action.action_type == "open_app":
            target_lower = action.target.lower().split("\\")[-1]
            is_system_path = any(action.target.lower().startswith(p) for p in
                               ["c:\\windows\\", "c:\\program files\\", "c:\\program files (x86)\\"])
            if is_system_path:
                result = SecurityCheckResult(
                    allowed=True, risk_level=RiskLevel.LOW,
                    reason=f"系统程序放行: {action.target}", requires_approval=False,
                    logged=True, action_taken="记录"
                )
            else:
                result = SecurityCheckResult(
                    allowed=True, risk_level=RiskLevel.MEDIUM,
                    reason=f"打开未知程序: {action.target}", requires_approval=True,
                    logged=True, action_taken="记录"
                )
            self._log(action, result)
            return result

        # 4. 其他 → 记录后放行
        result = SecurityCheckResult(
            allowed=True, risk_level=risk_level if risk_level.value > 0 else RiskLevel.LOW,
            reason=f"风险等级: {risk_level.to_string()}，已记录",
            requires_approval=False, logged=True, action_taken="记录"
        )
        self._log(action, result)
        return result

    def _is_safe_action(self, action: SecurityAction) -> bool:
        if action.action_type == "open_app":
            target_lower = action.target.lower().split("\\")[-1]
            if target_lower in SAFE_APPS:
                return True
            return False
        for safe in SAFE_ACTIONS:
            if action.action_type != safe["action_type"]:
                continue
            for keyword in safe["keywords"]:
                if keyword.lower() in action.target.lower():
                    return True
                if action.command and keyword.lower() in action.command.lower():
                    return True
            return False
        return False
    def _check_dangerous_rules(self, action: SecurityAction) -> Tuple[RiskLevel, Optional[Dict]]:
        highest_risk = RiskLevel.SAFE
        matched_rule = None

        for rule in DANGEROUS_RULES:
            if action.action_type == rule["action_type"]:
                if rule["risk_level"].value > highest_risk.value:
                    highest_risk = rule["risk_level"]
                    matched_rule = rule

        text_to_check = f"{action.target} {action.command or ''}"
        for rule in DANGEROUS_RULES:
            for keyword in rule.get("keywords", []):
                if keyword.lower() in text_to_check.lower():
                    if rule["risk_level"].value > highest_risk.value:
                        highest_risk = rule["risk_level"]
                        matched_rule = rule
                    break
            if rule.get("pattern"):
                try:
                    if re.search(rule["pattern"], text_to_check, re.IGNORECASE):
                        if rule["risk_level"].value > highest_risk.value:
                            highest_risk = rule["risk_level"]
                            matched_rule = rule
                except re.error:
                    pass

        return highest_risk, matched_rule

    def _classify_shell_command(self, command: str) -> Tuple[str, RiskLevel]:
        cmd_lower = command.lower()
        for cat_name, cat_info in SHELL_COMMAND_CATEGORIES.items():
            if cat_name == "shell_command_unknown":
                continue
            for pattern in cat_info["patterns"]:
                if re.search(pattern, cmd_lower):
                    return cat_name, cat_info["risk_level"]
            for keyword in cat_info["keywords"]:
                if keyword.lower() in cmd_lower:
                    return cat_name, cat_info["risk_level"]
        return "shell_command_unknown", RiskLevel.CRITICAL

    def _check_message_risk(self, action: SecurityAction) -> Tuple[RiskLevel, str]:
        config = self.security_config
        sensitive_keywords = config.get("sensitive_keywords", [])
        trusted_contacts = set(config.get("trusted_contacts", []))
        max_recipients = config.get("max_recipients_without_approval", 1)

        for keyword in sensitive_keywords:
            if keyword.lower() in action.content.lower():
                return RiskLevel.CRITICAL, f"消息包含敏感词: {keyword}"

        if len(action.recipients) > max_recipients:
            return RiskLevel.HIGH, f"群发消息: {len(action.recipients)} 人 > {max_recipients}"

        if action.attachments:
            return RiskLevel.HIGH, "消息包含附件"

        for recipient in action.recipients:
            if recipient not in trusted_contacts:
                return RiskLevel.HIGH, f"非白名单对象: {recipient}"

        return RiskLevel.LOW, "白名单对象，安全"

    def _log(self, action: SecurityAction, result: SecurityCheckResult):
        log_entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "action": {
                "type": action.action_type, "target": action.target,
                "command": action.command, "risk_level": action.risk_level.to_string() if hasattr(action.risk_level, 'to_string') else str(action.risk_level.value),
            },
            "result": {
                "allowed": result.allowed, "risk_level": result.risk_level.to_string() if hasattr(result.risk_level, 'to_string') else str(result.risk_level.value),
                "reason": result.reason, "requires_approval": result.requires_approval,
                "action_taken": result.action_taken,
            }
        }
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"安全日志写入失败: {e}")

    def get_logs(self, date: Optional[str] = None) -> List[Dict]:
        if date is None:
            date = datetime.datetime.now().strftime("%Y%m%d")
        log_file = self.log_dir / f"security_{date}.jsonl"
        logs = []
        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            logs.append(json.loads(line))
            except Exception:
                pass
        return logs

    def get_intercepted_actions(self, date: Optional[str] = None) -> List[Dict]:
        logs = self.get_logs(date)
        return [log for log in logs if not log["result"]["allowed"]]


_security_instance: Optional[SecurityModule] = None


def get_security_module() -> SecurityModule:
    global _security_instance
    if _security_instance is None:
        _security_instance = SecurityModule()
    return _security_instance


def check_action(action_type: str, target: str, command: Optional[str] = None, **kwargs) -> SecurityCheckResult:
    action = SecurityAction(action_type=action_type, target=target, command=command, params=kwargs)
    return get_security_module().check(action)


if __name__ == "__main__":
    security = SecurityModule()
    test_actions = [
        SecurityAction("file_delete", "E:\\test.txt", "del E:\\test.txt"),
        SecurityAction("format_disk", "C:", "format C:"),
        SecurityAction("send_message", "user@example.com", recipients=["user@example.com"], content="你好"),
        SecurityAction("shell_command", "/", "subprocess.run('rm -rf /')"),
        SecurityAction("open_app", "notepad.exe", "notepad"),
    ]
    print("安全模块测试:")
    for action in test_actions:
        result = security.check(action)
        status = "[放行]" if result.allowed else "[拦截]"
        print(f"{status} | {action.action_type} | {action.target} | {result.reason}")
