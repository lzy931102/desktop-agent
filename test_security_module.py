#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
T10 安全拦截测试 v2.0
验证 Agent 在执行危险操作前会拦截并要求审批。
13 个场景，含 8 个绕过测试。
"""

import subprocess
import time
import os
import sys
import datetime
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

from security_module import (
    SecurityModule, SecurityAction, SecurityCheckResult,
    RiskLevel, check_action
)

SCREENSHOT_DIR = Path("screenshots")
SECURITY_LOG_DIR = Path("security_logs")
SCREENSHOT_DIR.mkdir(exist_ok=True)
SECURITY_LOG_DIR.mkdir(exist_ok=True)


class ScenarioResult(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


@dataclass
class ScenarioReport:
    name: str
    result: ScenarioResult = ScenarioResult.FAIL
    steps: List[Dict] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    duration: float = 0.0
    interception_success: bool = False

    def add_step(self, name: str, success: bool, details: str = "", duration: float = 0.0):
        self.steps.append({"name": name, "success": success, "details": details, "duration": duration})

    def add_screenshot(self, path: str):
        self.screenshots.append(path)


@dataclass
class TestReport:
    scenarios: List[ScenarioReport] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    total_duration: float = 0.0

    def add_scenario(self, report: ScenarioReport):
        self.scenarios.append(report)

    def generate(self) -> str:
        self.total_duration = time.time() - self.start_time
        lines = [
            "=" * 70, "T10 安全拦截测试报告 v2.0", "=" * 70,
            f"测试时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"总耗时: {self.total_duration:.2f} 秒", "",
            "场景结果汇总:", "-" * 40,
        ]
        pass_count = sum(1 for s in self.scenarios if s.result == ScenarioResult.PASS)
        fail_count = sum(1 for s in self.scenarios if s.result == ScenarioResult.FAIL)
        error_count = sum(1 for s in self.scenarios if s.result == ScenarioResult.ERROR)

        for i, scenario in enumerate(self.scenarios, 1):
            icon = {"PASS": "✓", "FAIL": "✗", "ERROR": "!"}[scenario.result.value]
            lines.append(f"  {icon} 场景{i}: {scenario.name} - {scenario.result.value} ({scenario.duration:.2f}秒)")
            if scenario.interception_success:
                lines.append(f"    → 符合预期")
            if scenario.error_message:
                lines.append(f"    → 错误: {scenario.error_message}")

        lines.extend(["", f"通过: {pass_count}/{len(self.scenarios)}", f"失败: {fail_count}/{len(self.scenarios)}", f"错误: {error_count}/{len(self.scenarios)}", "", "详细步骤:", "-" * 40])

        for i, scenario in enumerate(self.scenarios, 1):
            lines.append(f"\n场景{i}: {scenario.name}")
            for step in scenario.steps:
                s = "✓" if step["success"] else "✗"
                lines.append(f"  {s} {step['name']}: {step['details']} ({step['duration']:.2f}秒)")

        lines.append("=" * 70)
        return "\n".join(lines)


def log(message: str, level: str = "INFO"):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    try:
        print(f"[{ts}] [{level}] {message}")
    except UnicodeEncodeError:
        print(f"[{ts}] [{level}] {message.encode('gbk', errors='replace').decode('gbk')}")


def take_screenshot(filename: str) -> str:
    try:
        import pyautogui
        path = SCREENSHOT_DIR / filename
        pyautogui.screenshot().save(str(path))
        return str(path)
    except Exception as e:
        log(f"截图失败: {e}", "ERROR")
        return ""


def run_scenario(name: str, scenario_func) -> ScenarioReport:
    log(f"\n{'='*50}")
    log(f"运行 {name}")
    log(f"{'='*50}")
    report = ScenarioReport(name=name)
    start = time.time()
    try:
        scenario_func(report)
    except Exception as e:
        report.error_message = str(e)
        report.result = ScenarioResult.ERROR
        sp = take_screenshot(f"t10_error_{int(time.time())}.png")
        if sp:
            report.add_screenshot(sp)
    report.duration = time.time() - start
    log(f"结果: {report.result.value}")
    return report


# ==================== 场景1-5（原有） ====================

def scenario1_delete_file(report: ScenarioReport):
    security = SecurityModule(log_dir=str(SECURITY_LOG_DIR))
    action = SecurityAction("file_delete", r"E:\agent_test\test_delete.txt", command=r"del E:\agent_test\test_delete.txt")
    report.add_step("构造操作", True, f"目标: {action.target}")
    result = security.check(action)
    report.add_step("安全检查", True, f"允许: {result.allowed}, 风险: {result.risk_level.to_string()}, 原因: {result.reason}")
    report.interception_success = not result.allowed
    report.add_step("验证拦截", report.interception_success, "操作被成功拦截" if report.interception_success else "未拦截")
    sp = take_screenshot(f"t10_s1_{int(time.time())}.png")
    if sp: report.add_screenshot(sp)
    report.result = ScenarioResult.PASS if report.interception_success else ScenarioResult.FAIL


def scenario2_format_disk(report: ScenarioReport):
    security = SecurityModule(log_dir=str(SECURITY_LOG_DIR))
    action = SecurityAction("format_disk", "C:", command="format C:")
    report.add_step("构造操作", True, f"目标: {action.target}")
    result = security.check(action)
    report.add_step("安全检查", True, f"允许: {result.allowed}, 风险: {result.risk_level.to_string()}")
    report.interception_success = not result.allowed
    report.add_step("验证拦截", report.interception_success, "操作被成功拦截" if report.interception_success else "未拦截")
    sp = take_screenshot(f"t10_s2_{int(time.time())}.png")
    if sp: report.add_screenshot(sp)
    report.result = ScenarioResult.PASS if report.interception_success else ScenarioResult.FAIL


def scenario3_send_message(report: ScenarioReport):
    security = SecurityModule(log_dir=str(SECURITY_LOG_DIR))
    action = SecurityAction("send_message", "user@example.com", recipients=["user@example.com"], content="你好")
    report.add_step("构造操作", True, f"目标: {action.target}")
    result = security.check(action)
    report.add_step("安全检查", True, f"允许: {result.allowed}, 风险: {result.risk_level.to_string()}, 原因: {result.reason}")
    report.interception_success = not result.allowed
    report.add_step("验证拦截", report.interception_success, "非白名单消息应拦截" if report.interception_success else "绕过成功")
    sp = take_screenshot(f"t10_s3_{int(time.time())}.png")
    if sp: report.add_screenshot(sp)
    report.result = ScenarioResult.PASS if report.interception_success else ScenarioResult.FAIL


def scenario4_shell_command(report: ScenarioReport):
    security = SecurityModule(log_dir=str(SECURITY_LOG_DIR))
    action = SecurityAction("shell_command", "/", command='subprocess.run("rm -rf /")')
    report.add_step("构造操作", True, f"命令: {action.command}")
    result = security.check(action)
    report.add_step("安全检查", True, f"允许: {result.allowed}, 风险: {result.risk_level.to_string()}")
    report.interception_success = not result.allowed
    report.add_step("验证拦截", report.interception_success, "操作被成功拦截" if report.interception_success else "未拦截")
    sp = take_screenshot(f"t10_s4_{int(time.time())}.png")
    if sp: report.add_screenshot(sp)
    report.result = ScenarioResult.PASS if report.interception_success else ScenarioResult.FAIL


def scenario5_safe_operation(report: ScenarioReport):
    security = SecurityModule(log_dir=str(SECURITY_LOG_DIR))
    action = SecurityAction("open_app", "notepad.exe", command="notepad")
    report.add_step("构造操作", True, f"目标: {action.target}")
    result = security.check(action)
    report.add_step("安全检查", True, f"允许: {result.allowed}, 原因: {result.reason}")
    report.interception_success = result.allowed
    report.add_step("验证放行", report.interception_success, f"[放行] {result.reason}" if report.interception_success else "安全操作被误拦截")
    sp = take_screenshot(f"t10_s5_{int(time.time())}.png")
    if sp: report.add_screenshot(sp)
    report.result = ScenarioResult.PASS if report.interception_success else ScenarioResult.FAIL


# ==================== 场景6-13（新增绕过测试） ====================

def scenario6_disguised_shell(report: ScenarioReport):
    security = SecurityModule(log_dir=str(SECURITY_LOG_DIR))
    action = SecurityAction("shell_command", "safe.txt", command='echo "rm -rf /" > safe.txt')
    report.add_step("构造操作", True, f"命令: {action.command}")
    result = security.check(action)
    report.add_step("安全检查", True, f"允许: {result.allowed}, 风险: {result.risk_level.to_string()}")
    report.interception_success = not result.allowed
    report.add_step("验证拦截", report.interception_success, "不能因文件名 safe 而放行" if report.interception_success else "绕过成功，存在漏洞")
    sp = take_screenshot(f"t10_s6_{int(time.time())}.png")
    if sp: report.add_screenshot(sp)
    report.result = ScenarioResult.PASS if report.interception_success else ScenarioResult.FAIL


def scenario7_base64_encoded(report: ScenarioReport):
    security = SecurityModule(log_dir=str(SECURITY_LOG_DIR))
    action = SecurityAction("shell_command", "/", command='echo "c3VkbyBybSAtcmYgLw==" | base64 -d | sh')
    report.add_step("构造操作", True, f"命令: {action.command}")
    result = security.check(action)
    report.add_step("安全检查", True, f"允许: {result.allowed}, 风险: {result.risk_level.to_string()}")
    report.interception_success = not result.allowed
    report.add_step("验证拦截", report.interception_success, "base64编码的危险命令应拦截" if report.interception_success else "绕过成功")
    sp = take_screenshot(f"t10_s7_{int(time.time())}.png")
    if sp: report.add_screenshot(sp)
    report.result = ScenarioResult.PASS if report.interception_success else ScenarioResult.FAIL


def scenario8_ssrf_file_protocol(report: ScenarioReport):
    security = SecurityModule(log_dir=str(SECURITY_LOG_DIR))
    action = SecurityAction("shell_command", "/etc/passwd", command="file:///etc/passwd")
    report.add_step("构造操作", True, f"命令: {action.command}")
    result = security.check(action)
    report.add_step("安全检查", True, f"允许: {result.allowed}, 风险: {result.risk_level.to_string()}")
    report.interception_success = not result.allowed
    report.add_step("验证拦截", report.interception_success, "file:// SSRF风险应拦截" if report.interception_success else "绕过成功")
    sp = take_screenshot(f"t10_s8_{int(time.time())}.png")
    if sp: report.add_screenshot(sp)
    report.result = ScenarioResult.PASS if report.interception_success else ScenarioResult.FAIL


def scenario9_system_directory_delete(report: ScenarioReport):
    security = SecurityModule(log_dir=str(SECURITY_LOG_DIR))
    action = SecurityAction("shell_command", r"C:\Windows\System32\*.dll", command=r"del C:\Windows\System32\*.dll")
    report.add_step("构造操作", True, f"命令: {action.command}")
    result = security.check(action)
    report.add_step("安全检查", True, f"允许: {result.allowed}, 风险: {result.risk_level.to_string()}")
    report.interception_success = not result.allowed
    report.add_step("验证拦截", report.interception_success, "系统目录删除应拦截" if report.interception_success else "绕过成功")
    sp = take_screenshot(f"t10_s9_{int(time.time())}.png")
    if sp: report.add_screenshot(sp)
    report.result = ScenarioResult.PASS if report.interception_success else ScenarioResult.FAIL


def scenario10_registry_modify(report: ScenarioReport):
    security = SecurityModule(log_dir=str(SECURITY_LOG_DIR))
    action = SecurityAction("system_config", r"HKLM\Software\Microsoft\Windows\CurrentVersion\Run",
                           command=r'reg add HKLM\Software\Microsoft\Windows\CurrentVersion\Run /v evil /d calc.exe')
    report.add_step("构造操作", True, f"命令: {action.command}")
    result = security.check(action)
    report.add_step("安全检查", True, f"允许: {result.allowed}, 风险: {result.risk_level.to_string()}")
    report.interception_success = not result.allowed
    report.add_step("验证拦截", report.interception_success, "注册表自启动应拦截" if report.interception_success else "绕过成功")
    sp = take_screenshot(f"t10_s10_{int(time.time())}.png")
    if sp: report.add_screenshot(sp)
    report.result = ScenarioResult.PASS if report.interception_success else ScenarioResult.FAIL


def scenario11_whitelist_message(report: ScenarioReport):
    security = SecurityModule(log_dir=str(SECURITY_LOG_DIR))
    security.security_config["trusted_contacts"] = ["trusted@example.com"]
    action = SecurityAction("send_message", "trusted@example.com",
                           recipients=["trusted@example.com"], content="你好")
    report.add_step("构造操作", True, f"收件人: trusted@example.com (白名单)")
    result = security.check(action)
    report.add_step("安全检查", True, f"允许: {result.allowed}, 风险: {result.risk_level.to_string()}, 原因: {result.reason}")
    report.interception_success = result.allowed and result.risk_level.value <= RiskLevel.LOW.value
    report.add_step("验证放行", report.interception_success, f"[放行] {result.reason}" if report.interception_success else "白名单消息被误拦截")
    sp = take_screenshot(f"t10_s11_{int(time.time())}.png")
    if sp: report.add_screenshot(sp)
    report.result = ScenarioResult.PASS if report.interception_success else ScenarioResult.FAIL


def scenario12_non_whitelist_message(report: ScenarioReport):
    security = SecurityModule(log_dir=str(SECURITY_LOG_DIR))
    action = SecurityAction("send_message", "stranger@unknown.com",
                           recipients=["stranger@unknown.com"], content="你好")
    report.add_step("构造操作", True, f"收件人: stranger@unknown.com (非白名单)")
    result = security.check(action)
    report.add_step("安全检查", True, f"允许: {result.allowed}, 风险: {result.risk_level.to_string()}, 原因: {result.reason}")
    report.interception_success = not result.allowed
    report.add_step("验证拦截", report.interception_success, "非白名单消息应拦截" if report.interception_success else "绕过成功")
    sp = take_screenshot(f"t10_s12_{int(time.time())}.png")
    if sp: report.add_screenshot(sp)
    report.result = ScenarioResult.PASS if report.interception_success else ScenarioResult.FAIL


def scenario13_sensitive_content_message(report: ScenarioReport):
    security = SecurityModule(log_dir=str(SECURITY_LOG_DIR))
    action = SecurityAction("send_message", "user@example.com",
                           recipients=["user@example.com"], content="验证码是123456")
    report.add_step("构造操作", True, f"内容: {action.content}")
    result = security.check(action)
    report.add_step("安全检查", True, f"允许: {result.allowed}, 风险: {result.risk_level.to_string()}, 原因: {result.reason}")
    report.interception_success = not result.allowed and result.risk_level == RiskLevel.CRITICAL
    report.add_step("验证拦截", report.interception_success, "敏感词消息应永久拦截" if report.interception_success else "绕过成功")
    sp = take_screenshot(f"t10_s13_{int(time.time())}.png")
    if sp: report.add_screenshot(sp)
    report.result = ScenarioResult.PASS if report.interception_success else ScenarioResult.FAIL


def scenario14_open_unknown_app(report: ScenarioReport):
    security = SecurityModule(log_dir=str(SECURITY_LOG_DIR))
    action = SecurityAction("open_app", "evil.exe", command="evil.exe")
    report.add_step("构造操作", True, f"目标: {action.target}")
    result = security.check(action)
    report.add_step("安全检查", True, f"允许: {result.allowed}, 风险: {result.risk_level.to_string()}, 原因: {result.reason}")
    report.interception_success = result.requires_approval
    report.add_step("验证需审批", report.interception_success, "未知程序应需审批" if report.interception_success else "绕过成功")
    sp = take_screenshot(f"t10_s14_{int(time.time())}.png")
    if sp: report.add_screenshot(sp)
    report.result = ScenarioResult.PASS if report.interception_success else ScenarioResult.FAIL


# ==================== 主测试 ====================

class T10_SecurityTest:
    def __init__(self):
        self.report = TestReport()

    def run_all(self) -> TestReport:
        log("=" * 70)
        log("T10 安全拦截测试 v2.0 开始")
        log("=" * 70)

        scenarios = [
            ("场景1: 删除文件拦截", scenario1_delete_file),
            ("场景2: 格式化磁盘拦截", scenario2_format_disk),
            ("场景3: 发送消息拦截", scenario3_send_message),
            ("场景4: 危险shell命令拦截", scenario4_shell_command),
            ("场景5: 安全操作放行", scenario5_safe_operation),
            ("场景6: 伪装shell命令", scenario6_disguised_shell),
            ("场景7: base64编码命令", scenario7_base64_encoded),
            ("场景8: file:// SSRF", scenario8_ssrf_file_protocol),
            ("场景9: 系统目录删除", scenario9_system_directory_delete),
            ("场景10: 注册表修改", scenario10_registry_modify),
            ("场景11: 白名单消息放行", scenario11_whitelist_message),
            ("场景12: 非白名单消息拦截", scenario12_non_whitelist_message),
            ("场景13: 敏感词消息拦截", scenario13_sensitive_content_message),
            ("场景14: 未知程序拦截", scenario14_open_unknown_app),
        ]

        for name, func in scenarios:
            sr = run_scenario(name, func)
            self.report.add_scenario(sr)

        report_text = self.report.generate()
        print(report_text)

        report_file = f"t10_test_report_{int(time.time())}.txt"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report_text)
        log(f"\n报告已保存到: {report_file}")

        security = SecurityModule(log_dir=str(SECURITY_LOG_DIR))
        logs = security.get_logs()
        intercepted = security.get_intercepted_actions()
        log(f"\n安全日志: 总数={len(logs)}, 拦截={len(intercepted)}")
        if intercepted:
            log("最新拦截记录:")
            last = intercepted[-1]
            log(f"  [{last['result']['action_taken']}] {last['action']['type']} | {last['action']['target']} | {last['result']['reason']}")

        return self.report


def main():
    try:
        from security_module import SecurityModule
        log("安全模块加载成功")
    except ImportError as e:
        log(f"错误: {e}", "ERROR")
        sys.exit(1)

    test = T10_SecurityTest()
    report = test.run_all()

    all_passed = all(s.result == ScenarioResult.PASS for s in report.scenarios)
    if all_passed:
        log("\n✓ 所有场景通过", "SUCCESS")
        sys.exit(0)
    else:
        log("\n✗ 部分场景失败", "FAILURE")
        sys.exit(1)


if __name__ == "__main__":
    main()
