"""按需下载外部小工具（目前只有 cloudflared），带进度回调。

为什么不在打包时塞进去：cloudflared 有 55 MB，比整个助手的一半还大。
为一个"可能用不上"的外网功能让所有用户都多下 55 MB 不划算，
所以改成"第一次要出门用的时候再下"，下到用户数据目录，只下一次。

安全约定：下载的是 Cloudflare 官方发布地址，且必须由用户在界面上确认后才发起；
下载不执行任何东西——执行发生在 tunnel.py，且地址写死在官方域名。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import ssl
import tempfile
from pathlib import Path
from typing import Callable, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

CLOUDFLARED_URL = ("https://github.com/cloudflare/cloudflared/releases/latest/"
                   "download/cloudflared-windows-amd64.exe")
CLOUDFLARED_MIN_BYTES = 20 * 1024 * 1024      # 明显小于这个数说明下到的是错误页
CHUNK = 256 * 1024


class DownloadError(RuntimeError):
    """下载失败，信息面向用户可直接展示。"""


def tools_dir() -> Path:
    """外部工具的落盘位置：%LOCALAPPDATA%/DesktopAgent/tools"""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = Path(base) / "DesktopAgent" / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cloudflared_path() -> Path:
    return tools_dir() / "cloudflared.exe"


def _ssl_context() -> ssl.SSLContext:
    """国内部分网络证书吊销检查会失败（CRYPT_E_NO_REVOCATION_CHECK），
    这里关掉吊销校验——我们校验的是"字节数 + 来源域名"，够用。"""
    ctx = ssl.create_default_context()
    try:
        ctx.verify_flags &= ~ssl.VERIFY_CRL_CHECK_LEAF
    except Exception:
        pass
    return ctx


def download_cloudflared(progress: Optional[Callable[[int, int], None]] = None,
                         timeout: int = 900) -> Path:
    """下载 cloudflared，返回落盘路径。progress(已下载字节, 总字节)。"""
    dest = cloudflared_path()
    tmp_fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent), suffix=".part")
    os.close(tmp_fd)
    tmp = Path(tmp_name)
    try:
        req = Request(CLOUDFLARED_URL, headers={"User-Agent": "DesktopAgent"})
        with urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with open(tmp, "wb") as fh:
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
        if dest.exists():
            dest.unlink()
        shutil.move(str(tmp), str(dest))
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
