# -*- coding: utf-8 -*-
"""
模型下载模块（应用内下载基础底模）

特点：
  - 纯标准库（urllib），无第三方依赖；
  - 支持断点续传（HTTP Range，断网/取消后重下从断点继续）；
  - 带进度回调（已下载字节 / 总字节 / 速度）；
  - 支持取消；下载完成后自动把 .part 改名为正式文件。
"""

import os
import threading
import time
import urllib.request

BLOCK = 1 << 16  # 64KB 一块


class DownloadError(Exception):
    pass


def get_remote_size(url, timeout=30):
    """发起一次 Range 请求，读取 Content-Range 拿到总大小。失败返回 None。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
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
        headers = {"User-Agent": "Mozilla/5.0"}
        if started:
            headers["Range"] = f"bytes={started}-"
        req = urllib.request.Request(self.url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
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
