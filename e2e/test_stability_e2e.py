#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
T8 连续 10 局稳定性测试
验证 Agent 长时间运行的稳定性。
"""

import time
import sys
import random
import datetime
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from run_target_game import TargetGame, ClickResult

SCREENSHOT_DIR = Path("screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

TOTAL_GAMES = 10
TARGETS_PER_GAME = 10
RADIUS = 50
SPEED = 0
GAME_AREA = (50, 50, 750, 550)


@dataclass
class GameRecord:
    game_id: int
    duration: float = 0.0
    clicks: int = 0
    hits: int = 0
    hit_rate: float = 0.0
    avg_latency_ms: float = 0.0
    avg_deviation_px: float = 0.0
    memory_mb: float = 0.0
    success: bool = False
    error: Optional[str] = None
    screenshot: Optional[str] = None


@dataclass
class StabilityReport:
    records: List[GameRecord] = field(default_factory=list)
    total_games: int = 0
    passed_games: int = 0
    total_duration: float = 0.0
    avg_duration: float = 0.0
    std_duration: float = 0.0
    avg_hit_rate: float = 0.0
    memory_start_mb: float = 0.0
    memory_end_mb: float = 0.0
    memory_growth_mb: float = 0.0
    stability_pass: bool = False


def log(message: str, level: str = "INFO"):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    try:
        print(f"[{ts}] [{level}] {message}")
    except UnicodeEncodeError:
        print(f"[{ts}] [{level}] {message.encode('gbk', errors='replace').decode('gbk')}")


def get_memory_mb() -> float:
    if not HAS_PSUTIL:
        return 0.0
    try:
        proc = psutil.Process()
        return proc.memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


def take_screenshot(filename: str) -> str:
    try:
        import pyautogui
        path = SCREENSHOT_DIR / filename
        pyautogui.screenshot().save(str(path))
        return str(path)
    except Exception:
        return ""


def play_one_game(game_id: int) -> GameRecord:
    record = GameRecord(game_id=game_id)
    start_time = time.time()

    try:
        game = TargetGame(prefer_mss=True)
        hits = 0
        latencies = []
        deviations = []

        for i in range(TARGETS_PER_GAME):
            target_x = random.randint(GAME_AREA[0] + RADIUS, GAME_AREA[2] - RADIUS)
            target_y = random.randint(GAME_AREA[1] + RADIUS, GAME_AREA[3] - RADIUS)

            result: ClickResult = game.click_target(target_x, target_y, RADIUS, predict=True)

            record.clicks += 1
            if result.success:
                hits += 1
            latencies.append(result.latency_ms)
            deviations.append(result.deviation_px)
            time.sleep(0.05)

        record.hits = hits
        record.hit_rate = hits / TARGETS_PER_GAME * 100
        record.avg_latency_ms = sum(latencies) / len(latencies) if latencies else 0
        record.avg_deviation_px = sum(deviations) / len(deviations) if deviations else 0
        record.memory_mb = get_memory_mb()
        record.success = True

        game.close()

    except Exception as e:
        record.error = str(e)
        record.success = False
        record.screenshot = take_screenshot(f"t8_error_game{game_id}_{int(time.time())}.png")

    record.duration = time.time() - start_time
    return record


def calculate_stats(records: List[GameRecord]) -> StabilityReport:
    report = StabilityReport()
    report.records = records
    report.total_games = len(records)
    report.passed_games = sum(1 for r in records if r.success)

    durations = [r.duration for r in records]
    report.total_duration = sum(durations)
    report.avg_duration = report.total_duration / len(durations) if durations else 0

    if len(durations) > 1:
        mean = report.avg_duration
        variance = sum((d - mean) ** 2 for d in durations) / (len(durations) - 1)
        report.std_duration = variance ** 0.5
    else:
        report.std_duration = 0

    hit_rates = [r.hit_rate for r in records if r.success]
    report.avg_hit_rate = sum(hit_rates) / len(hit_rates) if hit_rates else 0

    memory_values = [r.memory_mb for r in records if r.memory_mb > 0]
    if memory_values:
        report.memory_start_mb = memory_values[0]
        report.memory_end_mb = memory_values[-1]
        report.memory_growth_mb = report.memory_end_mb - report.memory_start_mb

    stability_checks = [
        report.passed_games == report.total_games,
        report.std_duration < report.avg_duration * 0.3 if report.avg_duration > 0 else True,
        report.memory_growth_mb < 50,
    ]
    report.stability_pass = all(stability_checks)

    return report


def generate_report(report: StabilityReport) -> str:
    lines = [
        "=" * 70,
        "T8 连续 10 局稳定性测试报告",
        "=" * 70,
        f"测试时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"总局数: {report.total_games}",
        f"通过局数: {report.passed_games}/{report.total_games}",
        f"总耗时: {report.total_duration:.2f} 秒",
        "",
        "每局详情:",
        "-" * 70,
        f"{'局数':>4} | {'耗时':>6} | {'点击':>4} | {'命中':>4} | {'命中率':>6} | {'内存MB':>7} | {'状态':>4}",
        "-" * 70,
    ]

    for r in report.records:
        status = "PASS" if r.success else "FAIL"
        lines.append(
            f"{r.game_id:>4} | {r.duration:>5.2f}s | {r.clicks:>4} | {r.hits:>4} | {r.hit_rate:>5.1f}% | {r.memory_mb:>6.1f} | {status:>4}"
        )

    lines.extend([
        "-" * 70,
        "",
        "统计汇总:",
        f"  平均耗时: {report.avg_duration:.2f} 秒",
        f"  耗时标准差: {report.std_duration:.2f} 秒",
        f"  标准差/平均值: {report.std_duration/report.avg_duration*100:.1f}%" if report.avg_duration > 0 else "  标准差/平均值: N/A",
        f"  平均命中率: {report.avg_hit_rate:.1f}%",
        f"  内存起始: {report.memory_start_mb:.1f} MB",
        f"  内存结束: {report.memory_end_mb:.1f} MB",
        f"  内存增长: {report.memory_growth_mb:.1f} MB",
        "",
        "验收标准:",
        f"  [✓] 10/10 通关: {'PASS' if report.passed_games == report.total_games else 'FAIL'}",
        f"  [✓] 耗时稳定 (std < 30%): {'PASS' if report.std_duration < report.avg_duration * 0.3 else 'FAIL'}" if report.avg_duration > 0 else "  [✓] 耗时稳定: N/A",
        f"  [✓] 内存增长 < 50MB: {'PASS' if report.memory_growth_mb < 50 else 'FAIL'}",
        "",
        f"最终结果: {'✓ 稳定性测试通过' if report.stability_pass else '✗ 稳定性测试失败'}",
        "=" * 70,
    ])

    if report.records and report.records[-1].error:
        lines.append(f"\n最后错误: {report.records[-1].error}")
    if report.records and report.records[-1].screenshot:
        lines.append(f"错误截图: {report.records[-1].screenshot}")

    return "\n".join(lines)


def main():
    log("=" * 70)
    log("T8 连续 10 局稳定性测试开始")
    log("=" * 70)

    if not HAS_PSUTIL:
        log("psutil 未安装，内存监控不可用", "WARNING")

    memory_start = get_memory_mb()
    log(f"初始内存: {memory_start:.1f} MB")

    records = []
    for game_id in range(1, TOTAL_GAMES + 1):
        log(f"\n--- 第 {game_id}/{TOTAL_GAMES} 局 ---")
        record = play_one_game(game_id)
        records.append(record)

        if record.success:
            log(f"✓ 耗时={record.duration:.2f}s 命中率={record.hit_rate:.1f}% 内存={record.memory_mb:.1f}MB")
        else:
            log(f"✗ 失败: {record.error}", "ERROR")

        if game_id < TOTAL_GAMES:
            time.sleep(1)

    report = calculate_stats(records)
    report_text = generate_report(report)
    print(report_text)

    report_file = f"t8_stability_report_{int(time.time())}.txt"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_text)
    log(f"\n报告已保存到: {report_file}")

    if report.stability_pass:
        log("\n✓ 稳定性测试通过", "SUCCESS")
        sys.exit(0)
    else:
        log("\n✗ 稳定性测试失败", "FAILURE")
        sys.exit(1)


if __name__ == "__main__":
    main()
