"""UI-independent startup checks and a bounded, redacted diagnostic record."""
from __future__ import annotations

import ctypes
import hashlib
from html.parser import HTMLParser
import json
import logging
import os
from pathlib import Path
import platform
import threading
import time
import sys
from ctypes import wintypes
from urllib.parse import unquote, urlsplit

from kohya_core.diagnostics import SessionLog, redact


class _PageAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "script" and fields.get("src"):
            self.paths.append(fields["src"])
        elif tag == "link" and fields.get("rel") in ("stylesheet", "modulepreload") and fields.get("href"):
            self.paths.append(fields["href"])


def check_page_assets(index: Path, log):
    """Check the page's actual references and, on new builds, every emitted asset."""
    root = index.parent.resolve()
    if not index.is_file():
        raise RuntimeError("新版页面文件缺失，请使用完整安装包覆盖安装。")
    parser = _PageAssets()
    parser.feed(index.read_text(encoding="utf-8"))
    local_paths = []
    for reference in parser.paths:
        parts = urlsplit(reference)
        if parts.scheme or parts.netloc:
            raise RuntimeError("新版页面引用了外部程序文件，请使用完整安装包覆盖安装。")
        # Vite references ./assets/...; bundle keys are assets/.... Compare
        # canonical relative paths, retaining the boundary check before lookup.
        asset_path = (root / unquote(parts.path).lstrip("/")).resolve()
        if not asset_path.is_relative_to(root):
            raise RuntimeError("新版页面的程序文件路径超出了页面目录，请使用完整安装包覆盖安装。")
        local_paths.append(asset_path.relative_to(root).as_posix())
    manifest = root / "ui-manifest.json"
    hashes = {}
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        hashes = data.get("sha256", {})
        if data.get("schema") != 1 or not isinstance(hashes, dict) or not hashes or "index.html" not in hashes:
            raise RuntimeError("新版页面校验清单无效，请使用完整安装包覆盖安装。")
        unmatched = [name for name in local_paths if name not in hashes]
        if unmatched:
            log.append("首页引用未列入校验清单: " + ", ".join(unmatched[:20]))
            raise RuntimeError("新版页面与校验清单不匹配，请使用完整安装包覆盖安装。")
    problems = []
    for name in sorted(set(local_paths) | set(hashes)):
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size == 0:
            problems.append("缺失或不可读取: " + name)
        elif name in hashes and hashlib.sha256(path.read_bytes()).hexdigest() != hashes[name]:
            problems.append("内容校验失败: " + name)
    if not local_paths:
        problems.append("首页没有程序文件引用")
    if problems:
        for problem in problems[:20]:
            log.append(problem)
        raise RuntimeError("新版页面文件缺失、损坏或版本混用：\n%s\n\n请用完整安装包覆盖安装原位置。" % "\n".join(problems[:6]))
    log.append("页面资源检查通过；引用 %s 项，校验 %s 项。" % (len(local_paths), len(hashes)))


class _StartupLogHandler(logging.Handler):
    def __init__(self, monitor):
        super().__init__(logging.WARNING)
        self.monitor = monitor

    def emit(self, record):
        try:
            self.monitor.record("webview_warning", self.format(record))
        except Exception:
            pass


class StartupMonitor:
    def __init__(self, core):
        self._log = SessionLog(core.data_sub("logs"))
        self._log.path = self._log.path.with_name(self._log.path.name.replace("session_", "ui_startup_", 1))
        self._lock = threading.RLock()
        self._visible = threading.Event()
        self._closed = threading.Event()
        self._connected = False
        self._classic = False
        self._window = None
        self._count = 0
        self._handler = _StartupLogHandler(self)
        self.record("host_start", "version=%s; frozen=%s; os=%s" % (
            getattr(core, "APP_VERSION", "unknown"), bool(getattr(sys, "frozen", False)), platform.platform()))

    @property
    def path(self):
        return self._log.path

    @property
    def classic_requested(self):
        with self._lock:
            return self._classic

    def record(self, stage, detail=""):
        with self._lock:
            if self._count >= 160:
                return
            self._count += 1
            self._log.append("[启动/%s] %s" % (stage, redact(str(detail))[:8000]))

    def frontend_report(self, stage, detail=""):
        if stage not in {"ui_visible", "workspace_connected", "page_error", "bridge_timeout", "bootstrap_timeout"}:
            return {"ok": False}
        with self._lock:
            if stage == "ui_visible":
                self._visible.set()
            elif stage == "workspace_connected":
                self._connected = True
            self.record(stage, detail)
        return {"ok": True}

    def open_report(self):
        try:
            os.startfile(str(self.path))
            return {"ok": True}
        except OSError:
            return {"ok": False, "error": "无法打开启动诊断文件。", "path": str(self.path)}

    def request_classic(self):
        with self._lock:
            if self._connected or self._closed.is_set() or self._window is None:
                return {"ok": False, "error": "工作区已连接，请正常退出后使用经典界面入口。"}
            if self._classic:
                return {"ok": True}
            self.record("classic_requested")
            self._classic = True
        # Return the bridge response before destroying its WebView control.
        def close():
            try:
                self._window.destroy()
            except Exception as exc:
                with self._lock:
                    self._classic = False
                self.record("close_failed", exc)
        timer = threading.Timer(0.4, close)
        timer.daemon = True
        timer.start()
        return {"ok": True}

    def attach(self, window):
        self._window = window
        logging.getLogger("pywebview").addHandler(self._handler)
        window.events.shown += lambda: self.record("window_shown")
        window.events.loaded += lambda: self.record("document_loaded")
        window.events.closed += self._closed.set
        window.events.before_show += self._attach_native_events

    def _attach_native_events(self, window):
        """Observe the native control on its UI thread; never recreate it here."""
        try:
            control = window.native.webview
            def initialized(sender, args):
                self.record("webview_initialized", "success=%s; error=%s" % (
                    args.IsSuccess, args.InitializationException if not args.IsSuccess else ""))
                if args.IsSuccess:
                    self.record("webview_runtime", sender.CoreWebView2.Environment.BrowserVersionString)
                    sender.CoreWebView2.ProcessFailed += process_failed
            def navigation(sender, args):
                self.record("navigation_completed", "success=%s; status=%s" % (args.IsSuccess, args.WebErrorStatus))
            def process_failed(sender, args):
                self.record("webview_process_failed", "kind=%s; reason=%s" % (
                    args.ProcessFailedKind, getattr(args, "Reason", "unknown")))
            # Keep delegate targets alive for the lifetime of the control.
            self._native_handlers = (initialized, navigation, process_failed)
            control.CoreWebView2InitializationCompleted += initialized
            control.NavigationCompleted += navigation
            if control.CoreWebView2 is not None:
                control.CoreWebView2.ProcessFailed += process_failed
                self.record("webview_runtime", control.CoreWebView2.Environment.BrowserVersionString)
        except Exception as exc:
            self.record("native_observer_unavailable", exc)

    def watch(self):
        deadline = time.monotonic() + 60
        while not self._closed.is_set() and not self._visible.is_set():
            if time.monotonic() >= deadline:
                break
            self._closed.wait(0.5)
        if self._closed.is_set() or self._visible.is_set():
            return
        self.record("startup_timeout", "60 秒内未收到界面已显示的确认。")
        # A native message remains usable even when the renderer cannot paint HTML.
        try:
            if self._window is None or not self._window.events.shown.is_set():
                return
            hwnd = int(self._window.native.Handle.ToInt64())
            text = ("新版页面启动未完成，或本机连接未能确认。启动诊断记录位置：\n%s\n\n"
                    "是否关闭此窗口，改用经典界面？\n"
                    "选择‘否’可保留当前窗口继续等待。") % self.path
            message_box = ctypes.windll.user32.MessageBoxW
            message_box.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
            message_box.restype = ctypes.c_int
            result = message_box(hwnd, text, "新版页面启动异常", 0x00000004 | 0x00000030)
            # Recheck after the user answers: initialization may have completed while waiting.
            if result == 6 and not self._visible.is_set():
                self.request_classic()
        except Exception as exc:
            self.record("native_notice_failed", exc)

    def detach(self):
        self._closed.set()
        logging.getLogger("pywebview").removeHandler(self._handler)
