"""按需下载外部小工具（目前只有 cloudflared），带进度回调与哈希校验。

为什么不在打包时塞进去：cloudflared 有 60 多 MB，比整个助手的一半还大。
为一个"可能用不上"的外网功能让所有用户都多下 60 MB 不划算，
所以改成"第一次要出门用的时候再下"，下到用户数据目录，只下一次。

安全约定（P2-3 接线时加固）：
- 来源与版本都写死：不用 latest 地址——它随 Cloudflare 更新而变，
  没有可预先固定的校验基准，哈希校验就无从谈起。锁死版本后 URL 与
  SHA-256 都恒定，"篡改下载源 → 校验失败 → 拒绝执行"才成立。
  预期哈希取自官方发布说明的 SHA256 Checksums 清单，并与 GitHub API
  的 asset digest 双源核对一致（2026-09-30 取证）；升级时把版本号与
  哈希两个常量一起换。
- 下载不执行任何东西——执行发生在 tunnel.py，且地址写死在官方域名。
- 落盘位置限制在 tools 目录内：临时文件与目标文件都先规范化路径并
  校验同目录，再写入/替换。
"""
from __future__ import annotations

import hashlib
import os
import ssl
import tempfile
from pathlib import Path
from typing import Callable, Optional
from urllib.error import URLError
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

# 版本与哈希成对维护（取证与升级方式见文件头安全约定）
CLOUDFLARED_VERSION = "2026.2.0"
CLOUDFLARED_URL = ("https://github.com/cloudflare/cloudflared/releases/"
                   f"download/{CLOUDFLARED_VERSION}/"
                   "cloudflared-windows-amd64.exe")
CLOUDFLARED_SHA256 = (
    "b3279f2186a1c3c438ad5865e802bbbec26090c5d3fdb4ac1113f1143a94837a")
CLOUDFLARED_MIN_BYTES = 20 * 1024 * 1024      # 明显小于这个数说明下到的是错误页
CHUNK = 256 * 1024


class DownloadError(RuntimeError):
    """下载失败，信息面向用户可直接展示。"""


def tools_dir() -> Path:
    """外部工具的落盘位置：%LOCALAPPDATA%/DesktopAgent/tools"""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = Path(base) / "DesktopAgent" / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d.resolve()


def cloudflared_path() -> Path:
    return tools_dir() / "cloudflared.exe"


def _ssl_context() -> ssl.SSLContext:
    """国内部分网络证书吊销检查会失败（CRYPT_E_NO_REVOCATION_CHECK），
    这里关掉吊销校验——内容完整性由 SHA-256 校验兜底，吊销检查不是
    唯一防线。"""
    ctx = ssl.create_default_context()
    try:
        ctx.verify_flags &= ~ssl.VERIFY_CRL_CHECK_LEAF
    except Exception:
        pass
    return ctx


def _opener():
    """代理拍板（任务 09 遗留收口）：与全仓 trust_env=False 同策略——
    环境变量里的代理残留（FastGithub 等）会把请求劫持去不可达的地址，
    宁可直连失败，绝不静默走代理；下到的内容还有 SHA-256 校验兜底。"""
    return build_opener(ProxyHandler({}),
                        HTTPSHandler(context=_ssl_context()))


def download_cloudflared(progress: Optional[Callable[[int, int], None]] = None,
                         timeout: int = 900,
                         expected_sha256: str = CLOUDFLARED_SHA256) -> Path:
    """下载 cloudflared，返回落盘路径。progress(已下载字节, 总字节)。

    哈希与官方值对不上时抛 DownloadError 并丢弃临时文件——绝不把校验
    不通过的二进制留给 tunnel.py 去执行。
    """
    dest = cloudflared_path()
    tmp_fd, tmp_name = tempfile.mkstemp(dir=dest.parent, suffix=".part")
    os.close(tmp_fd)
    tmp = Path(tmp_name)
    if tmp.parent != dest.parent:
        # 落盘位置必须限制在 tools 目录内（路径规范化校验）
        raise DownloadError("下载临时目录异常，已取消")
    try:
        req = Request(CLOUDFLARED_URL, headers={"User-Agent": "DesktopAgent"})
        with _opener().open(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with tmp.open("wb") as fh:
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        try:
                            progress(done, total)
                        except Exception:
                            pass
        size = tmp.stat().st_size
        if size < CLOUDFLARED_MIN_BYTES:
            raise DownloadError(
                f"下载到的文件不完整（只有 {size // 1024} KB）。请检查网络后重试。")
        actual = sha256_of(tmp)
        if actual.lower() != expected_sha256.lower():
            raise DownloadError(
                "下载的组件校验不通过（SHA-256 与官方发布不一致），已拒绝使用。"
                "请检查网络环境后重试；反复出现说明下载通道可能被劫持。")
        tmp.replace(dest)          # 原子替换：校验通过才轮到 dest 更新
        return dest
    except DownloadError:
        raise
    except (URLError, OSError, ssl.SSLError) as e:
        raise DownloadError(
            "下载外网通道组件失败。请确认电脑能正常上网，再点一次「开启外网连接」。"
            f"（原因：{type(e).__name__}）") from e
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()
