# -*- coding: utf-8 -*-
"""
模型下载模块（应用内下载基础底模）

特点：
  - 纯标准库（urllib），无第三方依赖；
  - 支持断点续传（HTTP Range，断网/取消后重下从断点继续）；
  - 带进度回调（已下载字节 / 总字节 / 速度）；
  - 支持取消；下载完成后自动把 .part 改名为正式文件。
"""

# ★ 2026-09-27 关键修复：剔除「本脚本所在目录」在 sys.path 中的条目 ✗
#   本模块**必然** import urllib.request（→ 间接 import _socket）✗
#   而打包版把 python312.dll / _socket.pyd 等 3.12 的 C 扩展与本脚本平铺在同一目录，
#   Python 又把脚本目录放进 sys.path[0] ✗ → 命中 3.12 的 _socket.pyd ✗
#   → `ImportError: Module use of python312.dll conflicts with this version of Python`
#   这正是用户反馈「0.18 开始下不了模型」的根因（下载功能 0.18 才引入 ✓，
#   细节见 preprocess.py 同段注释 ✓）
#   ⚠️ 必须是所有 import 之前的第一件事 ✓
import glob as _glob2
import os as _os
import sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
# ⚠️ 必须**条件成立才剔除** ✗：仅当本目录确实含打包版 C 扩展时才动手 ✓
#   （开发环境下本目录就是项目根，还放着 kohya_core 等本地包 ——
#    无条件剔除会把它们也屏蔽掉，直接 import 失败 ✓）
if any(_glob2.glob(_os.path.join(_HERE, _p))
       for _p in ("python3*.dll", "_socket.pyd", "_ctypes.pyd")):
    _sys.path[:] = [p for p in _sys.path
                    if _os.path.normcase(_os.path.abspath(p or _os.getcwd())) != _os.path.normcase(_HERE)]

import os
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

BLOCK = 1 << 16  # 64KB 一块
_DIRECT_HOSTS = ("modelscope.cn", "hf-mirror.com", "mirrors.aliyun.com", "mirror.sjtu.edu.cn", "pypi.tuna.tsinghua.edu.cn")


def _base_headers():
    """User-Agent + 可选 HF_TOKEN（门禁模型如 Krea-2-Raw/Turbo 需要 Bearer 授权）。"""
    h = {"User-Agent": "Mozilla/5.0"}
    tok = os.environ.get("HF_TOKEN", "").strip()
    if tok:
        h["Authorization"] = "Bearer " + tok
    return h


def _opener_for(url):
    """国内镜像默认直连，避免 Windows 遗留代理端口导致必须开代理。"""
    host = (urlparse(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in _DIRECT_HOSTS):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


class DownloadError(Exception):
    pass


def get_remote_size(url, timeout=30):
    """发起一次 Range 请求，读取 Content-Range 拿到总大小。失败返回 None。"""
    try:
        req = urllib.request.Request(url, headers=dict(_base_headers(), Range="bytes=0-0"))
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

    def __init__(self, url, dest, progress_cb=None, done_cb=None, logf=print):
        super().__init__(daemon=True)
        self.url = url
        self.dest = dest
        self.part = dest + ".part"
        self.progress_cb = progress_cb
        self.done_cb = done_cb
        self.logf = logf
        self._cancel = threading.Event()
        self.error = None

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

    def _download(self):
        if os.path.isfile(self.dest):
            if self.logf:
                self.logf("[下载] 目标文件已存在，跳过。")
            return
        started = os.path.getsize(self.part) if os.path.isfile(self.part) else 0
        if started:
            if self.logf:
                self.logf(f"[下载] 检测到断点，从 {started / 1048576:.1f} MB 继续…")
        headers = _base_headers()
        if started:
            headers["Range"] = f"bytes={started}-"
        req = urllib.request.Request(self.url, headers=headers)
        with _opener_for(self.url).open(req, timeout=30) as r:
            # 服务端若不支持 Range 会返回 200 全文，此时从头下
            if r.status == 200 and started > 0:
                started = 0
            total = None
            cr = r.headers.get("Content-Range") or ""
            if "/" in cr:
                try:
                    total = int(cr.split("/")[-1].strip())
                except Exception:
                    total = None
            if total is None:
                try:
                    total = int(r.headers.get("Content-Length") or 0) + started
                except Exception:
                    total = None
            mode = "ab" if started else "wb"
            with open(self.part, mode) as f:
                done = started
                last_t = time.time()
                last_done = done
                speed = 0.0
                while True:
                    if self._cancel.is_set():
                        raise DownloadError("已取消（进度已保留，可再次下载从断点继续）")
                    chunk = r.read(BLOCK)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    now = time.time()
                    if now - last_t >= 0.5:
                        speed = (done - last_done) / max(0.001, now - last_t)
                        last_t, last_done = now, done
                    if self.progress_cb:
                        self.progress_cb(done, total, speed)
        if total is not None and done < total:
            raise DownloadError(f"下载不完整（{done}/{total} 字节）")
        os.replace(self.part, self.dest)
        if self.logf:
            self.logf(f"[下载] 完成：{self.dest}")
