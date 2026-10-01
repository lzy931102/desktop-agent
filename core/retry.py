"""任务重试：工具调用失败时按指数退避自动重试（1s、2s、4s，最多 3 次重试）。

哪些工具可重试由 core/guard.RETRYABLE_TOOLS 标记（幂等操作）；
高危操作（需用户确认的删除类）失败后不自动重试，交回模型决策。
"""
import time

MAX_RETRIES = 3
BACKOFF_SECONDS = (1, 2, 4)

FAIL_MARKERS = ("错误", "error", "failed")

# 确定性失败（T6）：白名单未命中/参数或配置校验不过/参数引用的对象不存在，
# 重试也不可能成功，命中即停止退避——2026-09-30 晚 open_app("chrome") 白名单
# 拒绝被盲目重试 3 次；2026-10-01 重放中 list_ui_elements("旧窗口名") 在页面
# 跳转后连续 4 次 UIA 超时（每次约 2 分钟）共烧 8 分钟。措辞与各工具的拒绝
# 文案对齐（open_app/open_url/agent_vision UIA 助手），新增拒绝类返回请带上
# 这些词之一。
NON_RETRYABLE_MARKERS = ("仅支持", "不支持", "无法识别", "请先填写",
                         "找不到窗口", "找不到标题包含", "找不到名为",
                         "没有可见窗口", "没有任何可枚举")


def is_failed_result(result) -> bool:
    """工具返回文本含失败标记即视为失败"""
    text = str(result).lower()
    return any(m in text for m in FAIL_MARKERS)


def is_permanent_failure(result) -> bool:
    """确定性失败：重试注定同样结果，立即返回交回模型换方法"""
    text = str(result)
    return any(m in text for m in NON_RETRYABLE_MARKERS)


def run_with_retry(exec_fn, tool_name: str, retryable: bool,
                   auditor=None, on_retry=None, max_retries: int = MAX_RETRIES):
    """执行 exec_fn 并按需重试。

    返回 (result, attempts, final_ok)：
    - result        最后一次的返回值
    - attempts      实际执行次数（含首次）
    - final_ok      最终是否成功
    on_retry(attempt, max_retries, wait) 在每次决定重试时回调。
    """
    attempts = 0
    while True:
        attempts += 1
        try:
            result = exec_fn()
        except Exception as e:
            result = f"错误: {e}"

        failed = is_failed_result(result)
        if not failed or not retryable or attempts > max_retries:
            return result, attempts, not failed
        if is_permanent_failure(result):
            return result, attempts, False

        wait = BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
        if auditor:
            # reason=（T10，2026-10-01）：记录当次失败文本，排障无需再按
            # seq 前后拼接 tool_result 才能还原原因
            auditor.emit("retry", tool=tool_name, attempt=attempts,
                         max_retries=max_retries, wait_s=wait,
                         reason=str(result)[:120])
        if on_retry:
            try:
                on_retry(attempts, max_retries, wait)
            except Exception:
                pass
        time.sleep(wait)
