# -*- coding: utf-8 -*-
"""
模型下载模块（应用内下载基础底模）

特点：
  - 纯标准库（urllib），无第三方依赖；
  - 支持断点续传（HTTP Range，断网/取消后重下从断点继续）；
  - 带进度回调（已下载字节 / 总字节 / 速度）；
  - 支持取消；下载完成后自动把 .part 改名为正式文件。
"""

# 外部 venv Python 直接运行此辅助脚本时，避免从应用安装目录误加载打包版
# Python 的 C 扩展。PyInstaller frozen 进程必须保留 bundle root，供 PYZ finder 导入。
import glob as _glob2
import os as _os
import sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))


def _sanitize_utility_sys_path(here, sys_path, frozen):
    """Remove bundled-Python DLL roots only for an external Python process."""
    if frozen:
        return
    if any(_glob2.glob(_os.path.join(here, pattern))
           for pattern in ("python3*.dll", "_socket.pyd", "_ctypes.pyd")):
        normalized_here = _os.path.normcase(_os.path.abspath(here))
        sys_path[:] = [path for path in sys_path
                       if _os.path.normcase(_os.path.abspath(path or _os.getcwd())) != normalized_here]


_sanitize_utility_sys_path(_HERE, _sys.path, bool(getattr(_sys, "frozen", False)))

import os
import hashlib
import json
import re
import struct
import tempfile
import zipfile
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

BLOCK = 1 << 16  # 64KB 一块
_DIRECT_HOSTS = ("modelscope.cn", "hf-mirror.com", "mirrors.aliyun.com", "mirror.sjtu.edu.cn", "pypi.tuna.tsinghua.edu.cn")


def _trusted_auth_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == "huggingface.co" or host.endswith(".huggingface.co"))


class _TokenSafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and not _trusted_auth_url(newurl):
            redirected.remove_header("Authorization")
        return redirected


def _base_headers(url=""):
    """User-Agent + 可选 HF_TOKEN（门禁模型如 Krea-2-Raw/Turbo 需要 Bearer 授权）。"""
    h = {"User-Agent": "Mozilla/5.0"}
    tok = os.environ.get("HF_TOKEN", "").strip()
    if tok and _trusted_auth_url(url):
        h["Authorization"] = "Bearer " + tok
    return h


def _opener_for(url):
    """国内镜像默认直连，避免 Windows 遗留代理端口导致必须开代理。"""
    host = (urlparse(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in _DIRECT_HOSTS):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}), _TokenSafeRedirect())
    return urllib.request.build_opener(_TokenSafeRedirect())


class DownloadError(Exception):
    pass


def get_remote_size(url, timeout=30):
    """发起一次 Range 请求，读取 Content-Range 拿到总大小。失败返回 None。"""
    try:
        req = urllib.request.Request(url, headers=dict(_base_headers(url), Range="bytes=0-0"))
        with _opener_for(url).open(req, timeout=timeout) as r:
            cr = r.headers.get("Content-Range") or ""
            if "/" in cr:
                return int(cr.split("/")[-1].strip())
            return None
    except Exception:
        return None


class ModelDownloader(threading.Thread):
    """后台下载线程。

    progress_cb(done, total, speed_bps)：进度回调（0.5 秒一次，任意线程调用，注意线程安全）；
    done_cb(ok, dest)：结束回调（成功或失败/取消都会调用）。
    """

    def __init__(self, url, dest, progress_cb=None, done_cb=None, logf=print, expected_size=None, expected_sha256=None):
        super().__init__(daemon=True)
        self.url = url
        self.dest = dest
        self.part = dest + ".part"
        self.metadata = self.part + ".json"
        self.expected_size = expected_size
        self.expected_sha256 = expected_sha256
        self.progress_cb = progress_cb
        self.done_cb = done_cb
        self.logf = logf
        self._cancel = threading.Event()
        self.error = None

    def _log(self, message):
        if self.logf:
            self.logf(message)

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            self._download()
            if self.done_cb:
                self.done_cb(True, self.dest)
        except Exception as e:
            self.error = e
            if self.logf:
                if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403):
                    self.logf("[下载] 失败：源拒绝访问（401/403）——该文件可能是 HuggingFace 门禁模型（需接受许可/登录）或源已失效。")
                    self.logf("[下载] 建议：1) 用「🌐 浏览器」手动下载；2) 已接受许可的可在环境变量设置 HF_TOKEN=你的token 后重试；3) 等维护者提供国内镜像。")
                else:
                    self.logf(f"[下载] 失败：{e}")
            if self.done_cb:
                self.done_cb(False, self.dest)

    def _validate_file(self, path):
        size = os.path.getsize(path)
        if size <= 0 or (self.expected_size is not None and size != self.expected_size):
            raise DownloadError("模型文件为空或大小不匹配")
        with open(path, "rb") as handle:
            prefix = handle.read(256).lstrip().lower()
            if prefix.startswith((b"<!doctype html", b"<html", b"<?xml")):
                raise DownloadError("下载源返回了网页或错误页，未得到模型文件")
            if self.dest.lower().endswith(".safetensors"):
                handle.seek(0)
                raw = handle.read(8)
                length = struct.unpack("<Q", raw)[0] if len(raw) == 8 else 0
                if not 2 <= length <= min(100_000_000, size - 8):
                    raise DownloadError("safetensors 文件头不完整")
                try:
                    header = json.loads(handle.read(length))
                    offsets = [entry["data_offsets"] for key, entry in header.items() if key != "__metadata__"]
                    valid = bool(offsets) and all(isinstance(pair, list) and len(pair) == 2
                        and all(isinstance(v, int) for v in pair) and 0 <= pair[0] <= pair[1] <= size - 8 - length for pair in offsets)
                    if not valid or max(pair[1] for pair in offsets) != size - 8 - length:
                        raise ValueError("tensor data incomplete")
                except (ValueError, TypeError, KeyError, AttributeError) as exc:
                    raise DownloadError("safetensors 权重数据不完整或格式无效") from exc
        if self.dest.lower().endswith((".zip", ".whl")) and not zipfile.is_zipfile(path):
            raise DownloadError("下载的压缩包不完整")
        if self.expected_sha256:
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
            if digest.hexdigest().lower() != self.expected_sha256.lower():
                raise DownloadError("文件 SHA256 校验失败")

    def _write_metadata(self, value):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(os.path.abspath(self.part)), delete=False) as handle:
                temporary = handle.name
                json.dump(value, handle)
            os.replace(temporary, self.metadata)
        finally:
            if temporary and os.path.exists(temporary):
                os.remove(temporary)

    def _download(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.dest)), exist_ok=True)
        if os.path.isfile(self.dest):
            try:
                self._validate_file(self.dest)
            except DownloadError as exc:
                self._log("[下载] 已有文件校验未通过，将重新下载：%s" % exc)
            else:
                self._log("[下载] 已有文件通过完整性检查，跳过。")
                return
        source = hashlib.sha256(self.url.encode("utf-8")).hexdigest()
        try:
            with open(self.metadata, encoding="utf-8") as handle:
                metadata = json.load(handle)
        except (OSError, ValueError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        validator = metadata.get("validator")
        started = (os.path.getsize(self.part) if os.path.isfile(self.part)
                   and isinstance(metadata, dict) and metadata.get("source") == source and validator else 0)
        headers = _base_headers(self.url)
        if started:
            headers.update({"Range": "bytes=%d-" % started, "If-Range": validator})
            self._log("[下载] 检测到可校验断点，从 %.1f MB 继续…" % (started / 1048576))
        req = urllib.request.Request(self.url, headers=headers)
        with _opener_for(self.url).open(req, timeout=30) as response:
            if response.status == 200:
                started = 0
            elif response.status != 206:
                raise DownloadError("下载源返回了不支持的状态码：%s" % response.status)
            if "text/html" in (response.headers.get("Content-Type") or "").lower():
                raise DownloadError("下载源返回网页，请更换下载源或检查模型授权")
            total = None
            content_range = response.headers.get("Content-Range") or ""
            if response.status == 206:
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range.strip())
                if not match or int(match[1]) != started or not started <= int(match[2]) < int(match[3]):
                    self._write_metadata({})
                    raise DownloadError("续传范围不匹配；下次重试会从头下载")
                total = int(match[3])
                response_validator = response.headers.get("ETag") or response.headers.get("Last-Modified")
                if started and ((metadata.get("total") is not None and metadata["total"] != total)
                                or (response_validator and response_validator != validator)):
                    self._write_metadata({})
                    raise DownloadError("下载源文件版本或大小已变化；下次重试会从头下载")
            elif response.headers.get("Content-Length"):
                total = int(response.headers["Content-Length"])
            self._write_metadata({"source": source, "validator": response.headers.get("ETag") or response.headers.get("Last-Modified"), "total": total})
            with open(self.part, "ab" if started else "wb") as handle:
                done = started
                last_t, last_done, speed = time.monotonic(), done, 0.0
                while True:
                    if self._cancel.is_set():
                        raise DownloadError("已取消（断点已保留）")
                    chunk = response.read(BLOCK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last_t >= .5:
                        speed = (done - last_done) / (now - last_t)
                        last_t, last_done = now, done
                    if self.progress_cb:
                        self.progress_cb(done, total, speed)
        if self._cancel.is_set():
            raise DownloadError("已取消（断点已保留）")
        if total is not None and done != total:
            raise DownloadError("下载不完整（%s/%s 字节）" % (done, total))
        self._validate_file(self.part)
        os.replace(self.part, self.dest)
        try:
            os.remove(self.metadata)
        except OSError:
            pass
        if self.progress_cb:
            self.progress_cb(done, total, speed)
        self._log("[下载] 完成并已检查：%s" % self.dest)
