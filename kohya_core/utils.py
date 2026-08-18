# -*- coding: utf-8 -*-
"""通用工具函数（渐进式拆分，从 Kohya一键工具.py 迁出）。
原文件通过 `from kohya_core.utils import *` 使用。
"""
import os
import sys
import re
import subprocess
import shutil
import json
import threading
import time
import urllib.request
import socket
from urllib.parse import urlparse

from kohya_core.configs import PY_MIN, PY_MAX
from kohya_core.paths import get_kohya_dir

# 手动停止 / 进程管理的全局状态（迁移到本包时一并保留，供 run_stream / stop_active_process / reset_stop 使用）
_STOP_EVENT = threading.Event()
_ACTIVE_LOCK = threading.Lock()
_ACTIVE_PROC = None

# 显式导出全部名字（含下划线开头），供 `from kohya_core.utils import *` 使用。
__all__ = [
    "StopRequested", "format_eta", "_terminate_tree", "stop_active_process", "reset_stop",
    "build_env", "build_direct_env", "clear_proxy_env", "proxy_reachable", "run_stream", "_download", "find_git", "_py_version", "find_python",
    "venv_python", "_yq", "split_triggers", "system_proxy",
]

class StopRequested(Exception):
    """用户手动停止当前任务（训练/预处理/安装等）。"""

def format_eta(sec):
    """把秒数格式化成 时:分:秒。"""
    if sec is None or sec < 0:
        return "--:--"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def _terminate_tree(proc):
    """Windows 上终止整个进程树（accelerate 会拉起训练子进程）。"""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True, timeout=30,
        )
        return
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass

def stop_active_process():
    """请求停止当前正在运行的子进程（训练/预处理/安装等）。"""
    global _ACTIVE_PROC
    _STOP_EVENT.set()
    with _ACTIVE_LOCK:
        proc = _ACTIVE_PROC
    if proc is not None and proc.poll() is None:
        _terminate_tree(proc)
    return True

def reset_stop():
    """开始新任务前调用，清除上一次的停止信号。"""
    _STOP_EVENT.clear()

_PROXY_ENV_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def proxy_reachable(proxy):
    """判断代理地址是否可连接；本机代理端口关闭时返回 False。"""
    if not proxy:
        return False
    try:
        raw = proxy if "://" in proxy else "http://" + proxy
        u = urlparse(raw)
        host, port = u.hostname, u.port
        if not host or not port:
            return False
        if host.lower() in ("127.0.0.1", "localhost", "::1"):
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.5)
                return sock.connect_ex((host, port)) == 0
        return True
    except Exception:
        return False


def clear_proxy_env(env):
    """清除 requests/pip/curl 代理变量，用于国内镜像直连。"""
    for key in _PROXY_ENV_KEYS:
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    return env


def build_env(extra_dirs=()):
    env = dict(os.environ)
    # PATH 必须先拆成独立目录再过滤。旧实现把完整 PATH 当成一个元素，
    # 因此永远无法命中/移除 PyInstaller 目录，外部 venv 仍会被 DLL 污染。
    paths = list(extra_dirs) + env.get("PATH", "").split(os.pathsep)
    # 清除会污染外部 Python 子进程的变量：打包版 / PATH 上其他 Python 可能
    # 通过 PYTHONHOME/PYTHONPATH 把错误的 DLL、模块塞进 venv 子进程
    # （典型现象：venv 是 Python 3.10，却报 "Module use of python312.dll conflicts"）。
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONSTARTUP", None)
    # 移除 PyInstaller 解包目录：它的 python312.dll 等 DLL 不应出现在外部
    # Python 子进程的 PATH 搜索里，避免跨 Python 版本 DLL 冲突。
    _meipass = getattr(sys, "_MEIPASS", None)
    blocked = set()
    if _meipass:
        blocked.add(os.path.normcase(os.path.abspath(_meipass)))
    if getattr(sys, "frozen", False):
        blocked.add(os.path.normcase(os.path.abspath(os.path.dirname(sys.executable))))
    paths = [p for p in paths if p and
             os.path.normcase(os.path.abspath(p.strip().strip('"'))) not in blocked]
    env["PATH"] = os.pathsep.join(paths)
    # 清除已经失效的代理，避免国内镜像被送进已关闭的 Clash/v2ray 端口。
    for key in _PROXY_ENV_KEYS:
        value = env.get(key)
        if value and not proxy_reachable(value):
            env.pop(key, None)
    # 网络不稳时 pip 容易 IncompleteRead 中断：全局加大重试次数与超时
    env.setdefault("PIP_RETRIES", "10")
    env.setdefault("PIP_TIMEOUT", "120")
    return env


def build_direct_env(extra_dirs=()):
    """构造国内镜像直连环境：不继承系统/历史代理。"""
    return clear_proxy_env(build_env(extra_dirs))


def run_stream(cmd, cwd=None, env=None, logf=print):
    """运行命令并把 stdout/stderr 实时交给 logf。返回退出码。

    支持手动停止：stop_active_process() 会终止当前进程树，
    并在读取循环中抛出 StopRequested（调用方按“用户主动停止”处理）。
    """
    global _ACTIVE_PROC
    if logf:
        logf("$ " + " ".join(str(x) for x in cmd))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
        bufsize=1, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    with _ACTIVE_LOCK:
        _ACTIVE_PROC = proc
    if _STOP_EVENT.is_set():
        _terminate_tree(proc)
    try:
        for line in proc.stdout:
            if logf:
                logf(line.rstrip("\n").rstrip("\r"))
            if _STOP_EVENT.is_set():
                _terminate_tree(proc)
                if logf:
                    logf("[停止] 已收到停止请求，正在终止进程…")
                break
    finally:
        with _ACTIVE_LOCK:
            if _ACTIVE_PROC is proc:
                _ACTIVE_PROC = None
    proc.wait()
    if _STOP_EVENT.is_set():
        raise StopRequested("任务已手动停止")
    return proc.returncode

def _download(url, dest, logf=print):
    """带进度地下载文件。"""
    logf(f"[下载] {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        last = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total and got - last > 5 * 1024 * 1024:
                last = got
                logf(f"[下载] {got / 1048576:.0f}/{total / 1048576:.0f} MB")
    logf(f"[下载] 完成 -> {dest}")

def find_git():
    cands = []
    p = shutil.which("git")
    if p:
        cands.append(p)
    for c in (
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Git\cmd\git.exe"),
    ):
        if os.path.isfile(c):
            cands.append(c)
    for c in cands:
        try:
            r = subprocess.run([c, "--version"], capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                return c
        except Exception:
            pass
    return None

def _py_version(p):
    try:
        r = subprocess.run(
            [p, "-c", "import sys;print('%d.%d.%d'%sys.version_info[:3])"],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode == 0:
            s = r.stdout.strip()
            parts = tuple(int(x) for x in s.split("."))
            return s, parts
    except Exception:
        pass
    return None, None

def _py_has_venv(p):
    """校验该 python 能创建虚拟环境（有 venv/ensurepip）。

    排除 ComfyUI 等便携版自带的精简嵌入式 python（能跑、版本正常，
    但没有 venv 模块，拿去 `-m venv` 会报 No module named venv）。
    """
    try:
        r = subprocess.run([p, "-c", "import venv, ensurepip"],
                           capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def find_python():
    """找一个能创建虚拟环境的 Python，优先 3.12（与内置 cp312 wheel 匹配），
    其次 3.11 / 3.10；PATH 里的 python 放最后（可能是精简版/版本不可控）。

    之前 PATH python 排最前：若用户 PATH 里是 3.10（或 ComfyUI 精简版），
    建出来的 venv 是 3.10，而内置离线 wheel 是 cp312，导致 numpy/torch 装不上
    （训练只有 CPU 版 torch → 'accelerator device: cpu' 卡死）。"""
    cands = []
    # 标准安装路径全扫一遍（3.12 优先）：PATH 里即使只有 ComfyUI 等精简 python，
    # 也能找到真正可建 venv 的 Python；且 3.12 与内置离线 wheel（cp312）匹配。
    for c in (
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Python\Python312\python.exe"),
        r"C:\Python312\python.exe",
        r"C:\Program Files\Python312\python.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Python\Python311\python.exe"),
        r"C:\Python311\python.exe",
        r"C:\Program Files\Python311\python.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Python\Python310\python.exe"),
        r"C:\Python310\python.exe",
        r"C:\Program Files\Python310\python.exe",
    ):
        if os.path.isfile(c):
            cands.append(c)
    p = shutil.which("python")
    if p:
        cands.append(p)
    for c in cands:
        s, parts = _py_version(c)
        if not (s and PY_MIN <= parts < PY_MAX):
            continue
        if not _py_has_venv(c):
            continue
        return c, s
    return None, None

def venv_python(kdir=None):
    kdir = kdir or get_kohya_dir()
    return os.path.join(kdir, "venv", "Scripts", "python.exe")

def _yq(s):
    """生成合法 yaml 字符串标量（含中文/空格/转义都安全）。"""
    import json
    return json.dumps(str(s), ensure_ascii=False)

def split_triggers(s):
    """把逗号分隔的多个 trigger 拆成列表。"""
    return [t.strip() for t in (s or "").split(",") if t.strip()]

def system_proxy():
    """读取 Windows 系统代理设置，返回代理地址或 None。"""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        try:
            enable, _ = winreg.QueryValueEx(k, "ProxyEnable")
            server, _ = winreg.QueryValueEx(k, "ProxyServer")
        finally:
            winreg.CloseKey(k)
        if enable and server:
            proxy = server if "://" in server else "http://" + server
            return proxy if proxy_reachable(proxy) else None
    except Exception:
        pass
    return None
