"""手机连接的鉴权：长期令牌（放二维码链接里）+ 连接口令 + 失败限速。

设计取舍（为什么不是账号密码）：
- 用户是非技术背景，手机端不该出现"登录框"。令牌直接编进二维码，
  扫一次就带着走，之后每次请求由页面自动带上。
- 但"扫码即得到电脑控制权"风险太高，所以额外做两件事：
  ① 令牌可一键更换（GUI「换一个」），旧手机立刻失效；
  ② 连续试错的来源会被临时冷处理（限速），防止局域网里有人暴力猜。

本模块只依赖标准库，可独立测试。
"""
from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass, field
from typing import Dict, Tuple

TOKEN_BYTES = 24          # 令牌随机字节数（urlsafe base64 后约 32 字符）
PAIR_CODE_DIGITS = 6      # 连接口令位数

MAX_FAILS = 10            # 窗口内允许的失败次数
FAIL_WINDOW_S = 60.0      # 失败统计窗口（秒）
COOLDOWN_S = 60.0         # 触发后冷处理时长（秒）


def new_token() -> str:
    """生成一个新令牌（URL 安全字符，不会破坏链接与二维码）。"""
    return secrets.token_urlsafe(TOKEN_BYTES)


def new_pair_code() -> str:
    """生成 6 位数字连接口令，给用户在电脑上核对"是不是这台"。"""
    return "".join(secrets.choice("0123456789") for _ in range(PAIR_CODE_DIGITS))


def mask_token(token: str) -> str:
    """展示用：只露头尾，避免截图/投屏时泄漏完整令牌。"""
    if not token:
        return ""
    if len(token) <= 8:
        return "•" * len(token)
    return f"{token[:4]}{'•' * 8}{token[-4:]}"


@dataclass
class PairingAuth:
    """令牌与口令的持有者，附带按来源的失败限速。"""

    token: str = field(default_factory=new_token)
    pair_code: str = field(default_factory=new_pair_code)
    max_fails: int = MAX_FAILS
    fail_window_s: float = FAIL_WINDOW_S
    cooldown_s: float = COOLDOWN_S
    # 内部：来源 → 失败时间戳列表 / 冷处理截止时间
    _fails: Dict[str, list] = field(default_factory=dict, repr=False)
    _blocked_until: Dict[str, float] = field(default_factory=dict, repr=False)

    # ---- 令牌管理 ----
    def rotate(self) -> Tuple[str, str]:
        """换一套令牌与口令，返回 (新令牌, 新口令)。旧链接立即作废。"""
        self.token = new_token()
        self.pair_code = new_pair_code()
        self.reset_limits()
        return self.token, self.pair_code

    def check(self, supplied: str, source: str = "") -> bool:
        """校验令牌。令牌对 → True；令牌错 → 记一次失败并返回 False。

        处于冷处理的来源直接拒绝（不给试错机会）。
        """
        if source and self.is_blocked(source):
            return False
        ok = bool(supplied) and hmac.compare_digest(str(supplied), self.token)
        if not ok and source:
            self._record_failure(source)
        return ok

    # ---- 口令核对（电脑上肉眼比对，不走网络）----
    def matches_pair_code(self, code: str) -> bool:
        return bool(code) and hmac.compare_digest(str(code), self.pair_code)

    # ---- 失败限速 ----
    def _record_failure(self, source: str) -> None:
        now = time.time()
        hits = [t for t in self._fails.get(source, []) if now - t < self.fail_window_s]
        hits.append(now)
        self._fails[source] = hits
        if len(hits) >= self.max_fails:
            self._blocked_until[source] = now + self.cooldown_s
            self._fails[source] = []

    def is_blocked(self, source: str) -> bool:
        until = self._blocked_until.get(source, 0.0)
        if until and time.time() < until:
            return True
        if until:
            self._blocked_until.pop(source, None)
        return False

    def blocked_seconds_left(self, source: str) -> int:
        until = self._blocked_until.get(source, 0.0)
        left = until - time.time()
        return int(left) + 1 if left > 0 else 0

    def reset_limits(self) -> None:
        self._fails.clear()
        self._blocked_until.clear()
