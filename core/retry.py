"""任务重试：工具调用失败时按指数退避自动重试（1s、2s、4s，最多 3 次重试）。

哪些工具可重试由 core/guard.RETRYABLE_TOOLS 标记（幂等操作）；
高危操作（需用户确认的删除类）失败后不自动重试，交回模型决策。
"""
import time

MAX_RETRIES = 3
BACKOFF_SECONDS = (1, 2, 4)

FAIL_MARKERS = ("错误", "error", "failed")


def is_failed_result(result) -> bool:
    """工具返回文本含失败标记即视为失败"""
    text = str(result).lower()
    return any(m in text for m in FAIL_MARKERS)


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

        wait = BACKOFF_SECONDS[min(attempts - 1, len(BACKOFF_SECONDS) - 1)]
        if auditor:
            auditor.emit("retry", tool=tool_name, attempt=attempts,
                         max_retries=max_retries, wait_s=wait)
        if on_retry:
            try:
                on_retry(attempts, max_retries, wait)
            except Exception:
                pass
        time.sleep(wait)
