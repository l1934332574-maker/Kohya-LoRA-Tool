#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kohya-SS LoRA 一键工具（Windows 桌面应用，画风 / 人物角色 双模式）

功能：
  1. 环境准备：自动检测并安装 Git / Python（缺失时用 winget 或官方安装包静默安装）
  2. 一键安装：自动克隆 kohya_ss 官方仓库 + 创建 venv + 安装全部依赖
  3. 数据预处理：1024px 缩放 / 去黑边 / 去水印 / 去重 / WD14 打标
     - 画风模式：统一画风 caption（过滤强人物五官/角色标签，无 trigger）
     - 人物模式：完整保留标签 + trigger 触发词 + 正则数据集
  4. 启动 Web UI：直接打开 kohya-ss 训练界面
  5. 一键训练：按所选模式组装参数，训练 LoRA（SDXL）
  6. 导出：safetensors 不变，额外生成 txt 使用模板
"""


import os
import re
import sys
import json
import time
import queue
import shutil
import socket
import threading
import subprocess
import traceback
import tempfile
import webbrowser
import urllib.request
import ctypes

# ---------- 全局隐藏子进程窗口 ----------
# GUI 程序没有控制台窗口，直接 subprocess 启动的子进程（git/python/nvidia-smi/powershell 等）
# 默认会各自弹出一个新的黑色 cmd 窗口；这里统一给所有 Popen 加 CREATE_NO_WINDOW，
# 让任何子进程都后台静默运行，不再弹窗。（subprocess.run/call 内部都走 Popen，自动生效）
if os.name == "nt":
    _orig_popen = subprocess.Popen
    _popen_dll_lock = threading.RLock()

    def _clean_child_env(env=None):
        """为外部 Python/Git/pip 清除打包程序注入的 Python/DLL 路径。

        PyInstaller onedir 会把 exe 目录加入 DLL/PATH 搜索路径。若直接从 GUI
        启动用户的 venv Python，外部解释器可能误加载应用自带的 python312.dll、
        libcrypto 等文件，随后出现 ``Module use of python312.dll conflicts`` 或
        ``DLL load failed``。所有子进程都应使用一份净化后的独立环境。
        """
        child_env = dict(os.environ if env is None else env)
        for key in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP"):
            child_env.pop(key, None)
        blocked = set()
        _meipass = getattr(sys, "_MEIPASS", None)
        if _meipass:
            blocked.add(os.path.normcase(os.path.abspath(_meipass)))
        if getattr(sys, "frozen", False):
            blocked.add(os.path.normcase(os.path.abspath(os.path.dirname(sys.executable))))
        if blocked:
            clean_path = []
            for part in child_env.get("PATH", "").split(os.pathsep):
                raw = part.strip().strip('"')
                if raw and os.path.normcase(os.path.abspath(raw)) in blocked:
                    continue
                clean_path.append(part)
            child_env["PATH"] = os.pathsep.join(clean_path)
        return child_env

    def _get_dll_directory():
        """读取当前进程 SetDllDirectory 值；未设置时返回 None。"""
        try:
            kernel32 = ctypes.windll.kernel32
            size = kernel32.GetDllDirectoryW(0, None)
            if not size:
                return None
            buf = ctypes.create_unicode_buffer(size + 1)
            if kernel32.GetDllDirectoryW(len(buf), buf):
                return buf.value or None
        except Exception:
            pass
        return None

    def _popen_no_window(*args, **kwargs):
        kwargs.setdefault("creationflags", 0x08000000)  # CREATE_NO_WINDOW
        kwargs["env"] = _clean_child_env(kwargs.get("env"))
        # PyInstaller 官方建议：启动外部程序前在 Windows 清除其设置的 DLL
        # 搜索目录，CreateProcess 返回后再恢复，避免污染 venv Python。
        with _popen_dll_lock:
            previous = _get_dll_directory()
            try:
                ctypes.windll.kernel32.SetDllDirectoryW(None)
                return _orig_popen(*args, **kwargs)
            finally:
                ctypes.windll.kernel32.SetDllDirectoryW(previous)

    subprocess.Popen = _popen_no_window

try:
    from model_downloader import ModelDownloader as _ModelDownloader
except Exception:
    _ModelDownloader = None

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, scrolledtext, messagebox
    _HAS_TK = True
except Exception:  # pragma: no cover
    _HAS_TK = False

APP_NAME = "Kohya-SS LoRA 一键工具（画风 / 人物）"
# 应用版本号：安装包/窗口标题/关于 共用；发布新包时同步更新这里和 installer.iss
APP_VERSION = "0.9.12"

# ---------- 配色主题（Material 浅色） ----------
INDIGO = "#5B5FE6"
INDIGO_HOVER = "#7B7FF0"
SUCCESS = "#22C55E"
WARN = "#F59E0B"
ERROR = "#EF4444"
PANEL_BG = "#FFFFFF"
ROOT_BG = "#F0F2F5"
BORDER = "#E2E5EA"
LOG_BG = "#1A1B26"
LOG_FG = "#D5D6E0"


def _lerp_color(c1, c2, t):
    """在 #RRGGBB 之间线性插值，t∈[0,1]。"""
    r1, g1, b1 = (int(c1[i:i + 2], 16) for i in (1, 3, 5))
    r2, g2, b2 = (int(c2[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02X%02X%02X" % (round(r1 + (r2 - r1) * t),
                              round(g1 + (g2 - g1) * t),
                              round(b1 + (b2 - b1) * t))

from kohya_core.configs import *  # noqa: E402,F401（模式注册表配置）
from kohya_core import KIT_DIR, KOHYA_DIR_FILE  # noqa: E402
from kohya_core.utils import *  # noqa: E402,F401（通用工具函数）
from kohya_core.paths import *  # noqa: E402,F401（路径与项目管理）
from kohya_core.gpu import *  # noqa: E402,F401（显卡检测）


# 模式注册表配置已迁移到 kohya_core/configs.py（下方 import * 导入）



# ---------- 通用工具 ----------



class TrainMonitor:
    """训练实时监控：从 kohya 训练日志里解析 步数/loss/lr/速度/预计剩余时间。
    线程安全（内部用锁）；GUI 主线程通过 snapshot() 轮询刷新面板。"""

    # 数据集缓存阶段的日志标志：此阶段输出的 tqdm 是缓存进度（批次），不是训练步数，
    # 不能当成训练进度显示（否则会出现"假 20/20 100%"卡住错觉）。
    _CACHE_MARKERS = (
        "caching latents", "caching latent", "caching text encoder",
        "caching vae", "cache latents", "cache text encoder", "cache vae",
    )
    # 缓存结束标志：出现后认为进入训练阶段（后续 tqdm 是训练步数）
    _CACHE_END_MARKERS = (
        "latents cached", "latent cached", "cached latents", "text encoder outputs cached",
        "latent cache done", "caching done", "cache done",
        "latents are cached", "latent are cached", "text encoder outputs are cached",
        "caching finished", "finished caching",
    )

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self._reset_locked()

    def _reset_locked(self):
        """锁内复位（避免 start() 里嵌套获取同一把非重入锁导致死锁）。"""
        self.step = 0
        self.total = 0
        self.loss = None
        self.loss_prev = None
        self.loss_history = []
        self.lr = None
        self.speed = 0.0            # 步/秒
        self.eta = None             # 预计剩余秒数
        self.running = False
        self.phase = "idle"         # idle / cache / train（train 才更新训练步数）
        self.phase_label = None     # 阶段提示文案（如"正在缓存数据集…"）
        self._last_step = 0
        self._last_time = None

    def start(self, total=0):
        with self._lock:
            self._reset_locked()
            self.running = True
            self.total = int(total or 0)
            self._last_time = time.time()

    def set_total(self, total):
        with self._lock:
            self.total = int(total or 0)

    def set_lr(self, lr):
        """预填学习率（kohya 的 tqdm 日志里通常不输出 lr 字段，
        所以训练启动时把配置的学习率填进去，面板就能显示真实生效值）。"""
        try:
            lr = float(lr)
        except Exception:
            return
        with self._lock:
            self.lr = lr

    def on_line(self, line):
        """解析一行训练日志（兼容 kohya 两种格式：'steps: N ... loss: x lr: y' 与 tqdm 'N/M [..] loss=..'）。

        阶段判定：
        - 检测到"缓存 latents / 缓存文本编码器"等日志时进入 cache 阶段，此阶段所有 tqdm
          都视为缓存进度，不更新训练步数（避免把缓存进度误当成训练进度，出现"假 20/20"）。
        - 出现训练标志（steps: / epoch:）或缓存结束标志，或 tqdm 总数与已设置的总步数一致时，
          进入 train 阶段，正常解析步数/loss。
        """
        try:
            s = str(line)
            low = s.lower()
            # run_stream 打印的命令行回显（"$ ..."）不参与阶段判定
            if low.startswith("$ "):
                return False
            # 缓存阶段检测
            if any(m in low for m in self._CACHE_MARKERS):
                with self._lock:
                    if self.phase != "train":
                        self.phase = "cache"
                        self.phase_label = "正在缓存数据集…"
                return True
            # 缓存结束 → 训练阶段
            if any(m in low for m in self._CACHE_END_MARKERS):
                with self._lock:
                    if self.phase != "train":
                        self.phase = "train"
                        self.phase_label = None
                return True
            step = None
            total = None
            is_tqdm = False
            # 格式2（优先）：tqdm 进度条 N/M [  或 N/M [..] it/s
            m = re.search(r"(\d+)\s*/\s*(\d+)\s*\[", s)
            if m:
                is_tqdm = True
                step = int(m.group(1))
                total = int(m.group(2))
            else:
                # 格式1：独立的 'steps: N'（排除百分比 'steps: 1%'，排除 total/gradient/num 等前缀）
                if not re.search(r"(?:total|gradient|num|infer|sampling|val)[^:]*steps:", s, re.I):
                    m = re.search(r"steps:\s*(\d+)(?!%)", s)
                    if m:
                        step = int(m.group(1))
            # 训练开始标志：独立的 steps: / epoch: 日志 → 进入训练阶段
            if (not is_tqdm) and (step is not None or re.search(r"\bepoch\s*:", s, re.I)):
                with self._lock:
                    if self.phase != "train":
                        self.phase = "train"
                        self.phase_label = None
            if step is None:
                return False
            with self._lock:
                # 缓存阶段：tqdm 是缓存进度，不更新训练步数
                if self.phase != "train":
                    # 兜底：tqdm 总数与已设置的总步数一致 → 视为训练 tqdm
                    #（覆盖"短训练全程只有 tqdm、没有 steps: 日志"的场景，如 sd-scripts <200 步）
                    if is_tqdm and total and total > 0 and self.total and total == self.total:
                        self.phase = "train"
                        self.phase_label = None
                    else:
                        return True
                self.step = step
                if total and total > 0:
                    self.total = total
                # loss：兼容 'loss:' 与 'loss='；同样 lr
                ml = re.search(r"loss[=:]\s*([0-9.eE+-]+)", s)
                loss = float(ml.group(1)) if ml else None
                mr = re.search(r"lr[=:]\s*([0-9.eE+-]+)", s)
                lr = float(mr.group(1)) if mr else None
                # 速度：tqdm 的 'x.xx it/s' 或 'x.xx s/it'
                speed = None
                ms = re.search(r"([0-9.]+)\s*it/s", s)
                if ms:
                    speed = float(ms.group(1))
                else:
                    ms = re.search(r"([0-9.]+)\s*s/it", s)
                    if ms and float(ms.group(1)) > 0:
                        speed = 1.0 / float(ms.group(1))
                now = time.time()
                if loss is not None:
                    self.loss_prev = self.loss
                    self.loss = loss
                    self.loss_history.append(loss)
                    if len(self.loss_history) > 200:
                        self.loss_history = self.loss_history[-200:]
                if lr is not None:
                    self.lr = lr
                if speed is not None and speed > 0:
                    self.speed = speed
                    if self.total > 0:
                        remain = self.total - step
                        self.eta = remain / speed
                elif self._last_time and now > self._last_time:
                    dt = now - self._last_time
                    if dt > 0:
                        dstep = step - self._last_step
                        if dstep > 0:
                            self.speed = dstep / dt
                            if self.speed > 0 and self.total > 0:
                                remain = self.total - step
                                self.eta = remain / self.speed
                self._last_step = step
                self._last_time = now
            return True
        except Exception:
            return False

    def snapshot(self):
        with self._lock:
            return {
                "step": self.step, "total": self.total,
                "loss": self.loss, "loss_prev": self.loss_prev,
                "loss_history": list(self.loss_history),
                "lr": self.lr, "speed": self.speed, "eta": self.eta,
                "running": self.running,
                "phase": self.phase, "phase_label": self.phase_label,
            }

    def finish(self):
        with self._lock:
            self.running = False


def _winget_install(pkg_id, logf):
    logf(f"[winget] 安装 {pkg_id} …")
    try:
        r = subprocess.run(
            ["winget", "install", "-e", "--id", pkg_id, "--scope", "user",
             "--silent", "--accept-package-agreements", "--accept-source-agreements",
             "--disable-interactivity"],
            capture_output=True, text=True, timeout=1800,
        )
        out = (r.stdout or "").strip()
        if out:
            logf(out)
        if r.stderr and r.stderr.strip():
            logf((r.stderr or "").strip())
        return r.returncode == 0
    except Exception as e:
        logf(f"[winget] 异常: {e}")
        return False


def _git_download_url():
    try:
        with urllib.request.urlopen(
            "https://api.github.com/repos/git-for-windows/git/releases/latest",
            timeout=30,
        ) as r:
            data = json.load(r)
        for a in data.get("assets", []):
            n = a.get("name", "")
            if re.fullmatch(r"Git-\d+\.\d+\.\d+.*-64-bit\.exe", n):
                return a["browser_download_url"]
    except Exception:
        pass
    return None


def install_git(logf=print):
    g = find_git()
    if g:
        logf(f"[环境] 已找到 Git: {g}")
        return g
    # 优先使用内置安装包（离线，无需联网/代理）
    exe = _bundled_path("git")
    if exe:
        logf(f"[Git] 使用内置安装包: {exe}")
        subprocess.run([exe, "/VERYSILENT", "/NORESTART", "/SP-", "/SUPPRESSMSGBOXES", "/NOCANCEL"], timeout=1800)
        g = find_git()
        if g:
            return g
        raise RuntimeError("内置 Git 安装后仍未找到，请手动安装 https://git-scm.com/download/win")
    # 兜底：winget / 官方安装包（需联网）
    logf("[环境] 未找到 Git，开始自动安装（可能弹出 UAC，请点“是”）…")
    if _winget_install("Git.Git", logf):
        g = find_git()
        if g:
            return g
    logf("[Git] winget 不可用或失败，改用官方安装包…")
    url = _git_download_url()
    if not url:
        raise RuntimeError("无法获取 Git 下载地址，请手动安装 https://git-scm.com/download/win")
    exe = os.path.join(tempfile.gettempdir(), os.path.basename(url))
    _download(url, exe, logf)
    logf("[Git] 运行安装程序…")
    subprocess.run([exe, "/VERYSILENT", "/NORESTART", "/SP-", "/SUPPRESSMSGBOXES", "/NOCANCEL"], timeout=1800)
    g = find_git()
    if not g:
        raise RuntimeError("Git 安装后仍未找到，请手动安装 https://git-scm.com/download/win")
    return g


def _bundled_python_installer():
    """内置 Python 安装包：优先 3.12（与内置 cp312 wheel 匹配、安装器更新更稳），
    其次 3.11 / 3.10（版本从高到低）。"""
    folder = os.path.join(KIT_DIR, "installers", "python")
    if not os.path.isdir(folder):
        return None
    pat = re.compile(r"^python-(\d+)\.(\d+)\.(\d+)-amd64\.exe$")
    names = [f for f in os.listdir(folder) if pat.match(f)]
    if not names:
        return None
    names.sort(key=lambda n: tuple(int(x) for x in pat.match(n).groups()), reverse=True)
    return os.path.join(folder, names[0])


def _detect_installed_python():
    """安装后综合检测：先 find_python（常规路径 + PATH），再扫用户级安装目录。
    返回 (py, ver) 或 (None, None)。"""
    py, ver = find_python()
    if py:
        return py, ver
    try:
        base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python")
        if os.path.isdir(base):
            for name in sorted(os.listdir(base), reverse=True):
                m = re.match(r"^Python(\d)(\d+)$", name)
                if not m:
                    continue
                c = os.path.join(base, name, "python.exe")
                s, parts = _py_version(c)
                if not (s and PY_MIN <= parts < PY_MAX):
                    continue
                if not _py_has_venv(c):
                    continue
                return c, s
    except Exception:
        pass
    return None, None


def _localappdata_python_summary():
    """诊断用：列出用户级安装目录里已检测到的 Python（版本号 + python.exe 是否缺失）。"""
    try:
        base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python")
        if not os.path.isdir(base):
            return ""
        vers = []
        for name in os.listdir(base):
            m = re.match(r"^Python(\d)(\d+)$", name)
            if not m:
                continue
            c = os.path.join(base, name, "python.exe")
            s, _ = _py_version(c) if os.path.isfile(c) else (None, None)
            vers.append("%s (%s)" % (name, s or "python.exe 缺失"))
        return "、".join(vers)
    except Exception:
        return ""


def install_python(logf=print):
    py, ver = find_python()
    if py and ver:
        try:
            parts = tuple(int(x) for x in ver.split("."))
        except Exception:
            parts = None
        if parts and PY_MIN <= parts < PY_MAX:
            logf(f"[环境] 已找到 Python {ver}: {py}")
            return py, ver
    # 优先使用内置安装包（离线，无需联网/代理）：3.12 优先，其次 3.11 / 3.10
    exe = _bundled_python_installer()
    if exe:
        logf(f"[Python] 使用内置安装包: {exe}")
        r = subprocess.run(
            [exe, "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=1",
             "Include_test=0", "Include_doc=0", "Include_tcltk=1", "Include_pip=1"],
            capture_output=True, text=True, timeout=1800,
        )
        py, ver = _detect_installed_python()
        if py:
            logf(f"[Python] 安装成功：Python {ver}（{py}）")
            return py, ver
        if r.returncode != 0:
            raise RuntimeError(
                "内置 Python 安装程序异常退出（退出码 %s），安装未完成。\n"
                "请关闭其他安装程序后重试，或手动安装 https://www.python.org/downloads/" % r.returncode)
        found = _localappdata_python_summary()
        if found:
            raise RuntimeError(
                "内置 Python 安装程序已退出，但软件暂未识别到可用的 Python（检测到：%s）。\n"
                "请重启软件后再点「环境准备」；仍不行请手动安装 https://www.python.org/downloads/" % found)
        raise RuntimeError(
            "内置 Python 安装程序已退出，但未在常规位置找到 Python（可能被安全软件拦截）。\n"
            "请手动安装 https://www.python.org/downloads/ 后再点「环境准备」")
    # 兜底：winget / 官方安装包（需联网）
    logf("[环境] 未找到兼容 Python（需 3.10.9 ~ 3.12.x），开始自动安装 Python 3.10 …")
    if _winget_install("Python.Python.3.10", logf):
        py, ver = find_python()
        if py and ver:
            try:
                parts = tuple(int(x) for x in ver.split("."))
            except Exception:
                parts = None
            if parts and PY_MIN <= parts < PY_MAX:
                return py, ver
    logf("[Python] winget 不可用或失败，改用官方安装包…")
    url = "https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe"
    exe = os.path.join(tempfile.gettempdir(), "python-3.10.11-amd64.exe")
    _download(url, exe, logf)
    logf("[Python] 静默安装（仅当前用户，自动加入 PATH）…")
    subprocess.run(
        [exe, "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=1",
         "Include_test=0", "Include_doc=0", "Include_tcltk=1", "Include_pip=1"],
        timeout=1800,
    )
    py, ver = find_python()
    if not py:
        raise RuntimeError("Python 安装后仍未找到，请手动安装 https://www.python.org/downloads/")
    return py, ver


def ensure_prereqs(logf=print):
    g = install_git(logf)
    py, ver = install_python(logf)
    logf(f"[环境] 就绪：Git={os.path.basename(g)}，Python={ver}")
    return g, py, ver


# ---------- Kohya 安装 ----------





def _git_proxy_reachable(git=None):
    """检查 git 全局代理是否可用。本地代理(127.0.0.1)端口未监听视为不可用。"""
    try:
        git_exe = git or find_git() or "git"
        r = subprocess.run([git_exe, "config", "--global", "--get", "http.proxy"],
                           capture_output=True, text=True, timeout=15)
        proxy = (r.stdout or "").strip()
        if not proxy:
            return True  # 没配代理，直接直连
        m = re.match(r"https?://([^:/]+):(\d+)", proxy)
        if not m:
            return True
        host, port = m.group(1), int(m.group(2))
        if host in ("127.0.0.1", "localhost", "::1"):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                return s.connect_ex((host, port)) == 0
        return True
    except Exception:
        return True


def _git_clone(git, url, dest, logf):
    """克隆仓库；若 git 全局代理不可用则绕过代理直连。"""
    git_exe = git or find_git() or "git"
    env = build_env([os.path.dirname(git_exe)])
    # 使用绝对 git.exe，避免 PATH 中存在同名程序或打包环境找错 Git。
    # 注意 -c 是 git 的全局参数，必须放在 clone 子命令前；不能再拼一个 "git"，
    # 否则会形成 `git -c ... git clone` 并报 "git is not a git command"。
    cmd = [git_exe]
    if not _git_proxy_reachable(git_exe):
        logf("[Git] 检测到 git 代理不可用，本次克隆绕过代理直连…")
        cmd += ["-c", "http.proxy=", "-c", "https.proxy="]
    cmd += ["clone", "--depth", "1", url, dest]
    return run_stream(cmd, env=env, logf=logf)


def _bundled_path(kind):
    """在 installers 里找内置安装包。kind: 'git' / 'python'。"""
    if kind == "git":
        folder = os.path.join(KIT_DIR, "installers", "git")
        pat = re.compile(r"^Git-.*-64-bit\.exe$")
    else:
        folder = os.path.join(KIT_DIR, "installers", "python")
        pat = re.compile(r"^python-\d+\.\d+\.\d+-amd64\.exe$")
    if os.path.isdir(folder):
        for f in os.listdir(folder):
            if pat.match(f):
                return os.path.join(folder, f)
    return None


def _bundled_kohya_zip():
    folder = os.path.join(KIT_DIR, "installers", "kohya_ss")
    if not os.path.isdir(folder):
        return None
    for f in os.listdir(folder):
        if f.startswith("kohya_ss-") and f.endswith(".zip"):
            return os.path.join(folder, f)
    return None


def _bundled_sd_zip():
    folder = os.path.join(KIT_DIR, "installers", "kohya_ss")
    if not os.path.isdir(folder):
        return None
    for f in os.listdir(folder):
        if f.startswith("sd-scripts-") and f.endswith(".zip"):
            return os.path.join(folder, f)
    return None


def _bundled_musubi_zip():
    """第二训练引擎（musubi-tuner）内置离线源码包。"""
    folder = os.path.join(KIT_DIR, "installers", "musubi-tuner")
    if not os.path.isdir(folder):
        return None
    for f in os.listdir(folder):
        if f.startswith("musubi-tuner-") and f.endswith(".zip"):
            return os.path.join(folder, f)
    return None


def _extract_zip(zip_path, dest):
    """解压 zip 到 dest，并自动上移顶层文件夹（如 xxx-master/）。"""
    import zipfile

    os.makedirs(dest, exist_ok=True)
    top = None
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if names:
            first = names[0]
            top = first.split("/", 1)[0] if "/" in first else None
        z.extractall(dest)
    if top:
        top_dir = os.path.join(dest, top)
        if os.path.isdir(top_dir) and os.path.abspath(top_dir) != os.path.abspath(dest):
            for item in os.listdir(top_dir):
                shutil.move(os.path.join(top_dir, item), dest)
            shutil.rmtree(top_dir)


def _acquire_kohya_install_lock(kdir, logf=print):
    """跨进程安装锁：同一 kohya 目录同一时间只允许一个安装进程。返回锁句柄或 None。"""
    try:
        import msvcrt
    except Exception:
        return None
    lock_path = os.path.join(os.path.dirname(kdir), os.path.basename(kdir) + ".install.lock")
    try:
        f = open(lock_path, "w+")
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            f.close()
            return None
        f.seek(0)
        f.write(str(os.getpid()))
        f.flush()
        return f
    except Exception:
        try:
            f.close()
        except Exception:
            pass
        return None


def _release_kohya_install_lock(lock_f):
    """释放跨进程安装锁并删除锁文件。"""
    if lock_f is None:
        return
    try:
        import msvcrt
        lock_f.seek(0)
        msvcrt.locking(lock_f.fileno(), msvcrt.LK_UNLCK, 1)
    except Exception:
        pass
    try:
        lock_f.close()
    except Exception:
        pass
    try:
        os.remove(lock_f.name)
    except Exception:
        pass


def _preinstall_torch(vpy, kdir, logf=print, torch_ver="2.7.0", tv_ver="0.22.0",
                      xf_ver=None, ta_ver=None, cu="cu128", label="Kohya", force=False):
    """预下载并安装 PyTorch 大轮子（torch/torchvision[/xformers][/torchaudio]）。

    官方 pip 直连下载大轮子（2~3GB）无断点续传，国内网络一断就 IncompleteRead/卡死
    （kohya / musubi / ai-toolkit 三个引擎都踩过）。这里先用 curl 断点续传从
    阿里 pytorch 镜像下到本地缓存，再 pip 装进 venv；之后官方 pip 检测到版本已满足就跳过下载。
    返回 True=成功；失败抛 RuntimeError（调用方回退到 pip 直连）。
    """
    tag = None
    try:
        r = subprocess.run([vpy, "-c", "import sys;print('cp%d%d'%sys.version_info[:2])"],
                           capture_output=True, text=True, timeout=60)
        tag = (r.stdout or "").strip()
    except Exception:
        tag = None
    if tag not in ("cp310", "cp311", "cp312"):
        raise RuntimeError("暂不支持该 Python 版本的 PyTorch 预装: %s" % (tag or "未知"))
    base = "https://mirrors.aliyun.com/pytorch-wheels/%s" % cu
    wheels = [
        ("torch-%s%%2B%s-%s-%s-win_amd64.whl" % (torch_ver, cu, tag, tag), 1_000_000_000),
        ("torchvision-%s%%2B%s-%s-%s-win_amd64.whl" % (tv_ver, cu, tag, tag), 5_000_000),
    ]
    if xf_ver:
        wheels.append(("xformers-%s-%s-%s-win_amd64.whl" % (xf_ver, tag, tag), 50_000_000))
    if ta_ver:
        wheels.append(("torchaudio-%s%%2B%s-%s-%s-win_amd64.whl" % (ta_ver, cu, tag, tag), 1_000_000))
    cache = data_sub("cache", "pytorch_wheels")
    paths = []
    for name, minsize in wheels:
        # 本地文件名必须是合法 wheel 名：%2B 是 URL 编码的 '+'，pip 本地安装按文件名解析版本，
        # 含 %2B 会报 "Invalid wheel filename (invalid version)"。下载 URL 保持 %2B，本地名解码成 +。
        local_name = name.replace("%2B", "+")
        dest = os.path.join(cache, local_name)
        # 兼容旧版本残留的 %2B 文件名缓存（完整则改名复用，避免重新下载 3GB）
        legacy = os.path.join(cache, name)
        if (not os.path.isfile(dest)) and os.path.isfile(legacy) and os.path.getsize(legacy) >= minsize:
            try:
                os.replace(legacy, dest)
                logf("[%s] 已把旧 %2B 文件名缓存改名为合法名: %s" % (label, local_name))
            except Exception:
                pass
        if os.path.isfile(dest) and os.path.getsize(dest) >= minsize and _wheel_valid(dest):
            logf("[%s] 已存在缓存轮子，跳过下载: %s" % (label, local_name))
        else:
            if os.path.isfile(dest):
                logf("[%s] 缓存轮子不完整或损坏，重新下载: %s" % (label, local_name))
                try:
                    os.remove(dest)
                except Exception:
                    pass
            logf("[%s] 下载 %s（断点续传，可随时停止/重试）…" % (label, local_name))
            if not _download_with_resume(base + "/" + name, dest, logf):
                raise RuntimeError("下载失败，可重试（会从断点续传）: %s" % local_name)
            if not (os.path.isfile(dest) and os.path.getsize(dest) >= minsize and _wheel_valid(dest)):
                raise RuntimeError("下载不完整: %s" % local_name)
        paths.append(dest)
    logf("[%s] 本地安装 PyTorch 轮子（依赖走清华镜像）…" % label)
    env = build_env()
    env.setdefault("PIP_RETRIES", "10")
    env.setdefault("PIP_TIMEOUT", "120")
    _px = system_proxy()
    if _px:
        env.setdefault("HTTP_PROXY", _px)
        env.setdefault("HTTPS_PROXY", _px)
    cmd = [vpy, "-m", "pip", "install", "--no-cache-dir", "--retries", "10", "--timeout", "120"]
    if force:
        cmd.append("--force-reinstall")
    cmd += paths
    if run_stream(cmd, cwd=kdir, env=env, logf=logf) != 0:
        raise RuntimeError("本地安装 PyTorch 轮子失败，请查看上方日志")
    r = subprocess.run([vpy, "-c", "import torch, torchvision;print(torch.__version__);print(torch.cuda.is_available())"],
                       capture_output=True, text=True, timeout=180)
    logf("[%s] 验证：" % label + ((r.stdout or "").strip().replace("\n", " | ")))
    if r.returncode != 0:
        raise RuntimeError("torch 安装后导入失败")
    return True


def install_kohya(logf=print):
    git = find_git()
    py, pyver = find_python()
    if not git or not py:
        raise RuntimeError("请先点击【环境准备】安装 Git / Python")
    kdir = get_kohya_dir()
    logf(f"[Kohya] 安装目录: {kdir}")
    # 跨进程锁：防止重复点击/双开导致两个安装同时写同一个 venv（WinError 32 文件占用）
    lock_f = _acquire_kohya_install_lock(kdir, logf)
    if lock_f is None:
        raise RuntimeError(
            "检测到另一个「安装训练内核」正在运行（同一安装目录被占用）。\n"
            "请先等待完成，或关闭重复打开的软件窗口后重试；避免两个安装同时写文件导致失败。"
        )
    try:
        try:
            if detect_gpu_vendor() == "amd":
                logf("[Kohya] 检测到 AMD 显卡：默认安装的是 NVIDIA CUDA 版 PyTorch，AMD 卡无法直接使用。")
                logf("[Kohya] 安装完成后，请开启「AMD 兼容模式（实验性）」并按「环境检查 / 安装引导」配置 ROCm / ZLUDA 环境。")
        except Exception:
            pass
        os.makedirs(os.path.dirname(kdir), exist_ok=True)
        kohya_ok = (os.path.isdir(os.path.join(kdir, ".git"))
                    or os.path.isfile(os.path.join(kdir, "kohya_gui.py")))
        if kohya_ok:
            logf("[Kohya] 已存在 kohya_ss，跳过解压/克隆")
        else:
            if os.path.exists(kdir) and os.listdir(kdir):
                raise RuntimeError(f"目标目录非空且不是 kohya_ss: {kdir}")
            zip_src = _bundled_kohya_zip()
            if zip_src:
                logf(f"[Kohya] 使用内置源码包解压: {os.path.basename(zip_src)}")
                _extract_zip(zip_src, kdir)
            else:
                logf("[Kohya] 未找到内置源码包，改用 git 克隆（需联网）…")
                logf("[Kohya] 配置 Git（openssl 后端，解决 GitHub 连接报错）…")
                for c in (["git", "config", "--global", "http.sslBackend", "openssl"],
                          ["git", "config", "--global", "http.version", "HTTP/1.1"],
                          ["git", "config", "--global", "http.postBuffer", "524288000"]):
                    try:
                        subprocess.run(c, capture_output=True, timeout=30)
                    except Exception:
                        pass
                if _git_clone(git, "https://github.com/bmaltais/kohya_ss.git", kdir, logf) != 0:
                    raise RuntimeError("git clone 失败，请检查网络/代理后重试")
        # sd-scripts 子模块：内置包优先（避免联网拉子模块）
        sd_dir = os.path.join(kdir, "sd-scripts")
        if not os.path.isfile(os.path.join(sd_dir, "sdxl_train_network.py")):
            sd_zip = _bundled_sd_zip()
            if sd_zip:
                logf(f"[Kohya] 解压内置 sd-scripts 子模块: {os.path.basename(sd_zip)}")
                os.makedirs(sd_dir, exist_ok=True)
                _extract_zip(sd_zip, sd_dir)
            else:
                logf("[Kohya] 未找到内置 sd-scripts，稍后由 kohya 安装脚本联网拉取子模块（需网络）")
        vpy = venv_python(kdir)
        if os.path.isfile(vpy):
            _vok, _vdetail = _venv_python_ok(vpy)
            if not _vok:
                # venv 损坏（base Python 缺失，常见于数据目录迁移/换用户/原 Python 被卸载）：
                # 自动把旧 venv 改名保留，用当前 Python 重建，随后正常安装流程重装依赖。
                logf(f"[Kohya] ⚠ 检测到 venv 已损坏：{_vdetail}")
                logf("[Kohya] 常见原因：数据目录迁移到新盘/更换系统用户后，venv 指向的 Python 已不存在。")
                logf("[Kohya] 正在自动重建 venv（旧 venv 重命名保留，需重新安装依赖）…")
                _bak = os.path.join(kdir, "venv_broken_%s" % time.strftime("%Y%m%d_%H%M%S"))
                if os.path.exists(_bak):
                    _bak += "_1"
                try:
                    os.rename(os.path.join(kdir, "venv"), _bak)
                    logf(f"[Kohya] 旧 venv 已保留到: {os.path.basename(_bak)}")
                except Exception as _e:
                    raise RuntimeError("旧 venv 重命名失败（%s），请手动删除/移动 %s 后重试" % (_e, os.path.join(kdir, "venv")))
            else:
                # venv 健康但缺 pip（创建中断/ensurepip 缺失/被杀软清理）：
                # 先 ensurepip 自愈；自愈失败则与损坏 venv 一样改名保留，走下方重建。
                if not _ensure_venv_pip(vpy, os.path.join(kdir, "venv"), logf, label="Kohya"):
                    logf("[Kohya] ⚠ venv 缺 pip 且自愈失败，自动重建（旧 venv 保留）…")
                    _bak = os.path.join(kdir, "venv_broken_%s" % time.strftime("%Y%m%d_%H%M%S"))
                    if os.path.exists(_bak):
                        _bak += "_1"
                    try:
                        os.rename(os.path.join(kdir, "venv"), _bak)
                        logf(f"[Kohya] 旧 venv 已保留到: {os.path.basename(_bak)}")
                    except Exception as _e:
                        raise RuntimeError("旧 venv 重命名失败（%s），请手动删除/移动 %s 后重试" % (_e, os.path.join(kdir, "venv")))
        if not os.path.isfile(vpy):
            logf("[Kohya] 创建 Python 虚拟环境…")
            if run_stream([py, "-m", "venv", "venv"], cwd=kdir, logf=logf) != 0 or not os.path.isfile(vpy):
                raise RuntimeError("创建 venv 失败")
        # venv Python 版本校验：软件内置离线 wheel 是 cp312（Python 3.12），
        # 若 venv 是 3.10/3.11，内置 wheel 装不上会报 not supported，
        # torch 也会退化成 CPU 版 → 训练只有 'accelerator device: cpu'。
        try:
            _venv_ver = venv_python_version(os.path.join(kdir, "venv"))
        except Exception:
            _venv_ver = None
        if _venv_ver and not _venv_ver.startswith("3.12"):
            logf(f"[Kohya] ⚠ venv 是 Python {_venv_ver}，而软件内置依赖为 3.12（cp312）。"
                 f"若非 3.12，numpy/torch 内置 wheel 会装不上，建议安装 Python 3.12 后重建 venv。")
        # 已安装验证：torch（NVIDIA 卡需 CUDA 可用）+ Pillow + numpy + sd-scripts 齐全才算装好，
        # 否则可能被中断的安装坑到（例如有 torch 但缺 Pillow，预处理会失败）。
        def _dep_ok(code):
            try:
                return subprocess.run([vpy, "-c", code], capture_output=True, text=True,
                                      timeout=120).returncode == 0
            except Exception:
                return False
        try:
            _gpu_vendor = detect_gpu_vendor()
        except Exception:
            _gpu_vendor = None
        # CPU 版 torch（Torch not compiled with CUDA enabled）会让训练全程 CPU：
        # NVIDIA 卡上"已安装"判定要求 CUDA 可用，CPU 版不算装好，触发重装 cu128。
        if _gpu_vendor == "amd":
            torch_ok = _dep_ok("import torch; print(torch.__version__)")
        else:
            torch_ok = _dep_ok("import torch; assert torch.cuda.is_available()")
        if not torch_ok and _dep_ok("import torch; print(torch.__version__)"):
            # torch 能导入但 CUDA 不可用：明确记录为 CPU/驱动问题，后续会重装 cu128。
            logf("[Kohya] 已检测到 torch，但 CUDA 不可用，将重新安装 CUDA 版 PyTorch…")
        deps_ok = _dep_ok("import PIL, numpy")
        if torch_ok and deps_ok and os.path.isdir(os.path.join(kdir, "sd-scripts")):
            logf("[Kohya] 检测到已安装环境（torch + Pillow/numpy 可用），跳过重复安装。")
            with open(KOHYA_DIR_FILE, "w", encoding="utf-8") as f:
                f.write(kdir)
            return kdir
        if torch_ok and not deps_ok and os.path.isdir(os.path.join(kdir, "sd-scripts")):
            # 部分安装/中断导致缺 Pillow/numpy：快速补装，不必重跑整个安装
            logf("[Kohya] 检测到已装 torch 但缺 Pillow/numpy（可能之前安装被中断），正在快速补装…")
            _env2 = build_env()
            _ok2 = False
            _wheels2 = _wheels_for_python(_bundled_pip_wheels(), vpy)
            if _wheels2:
                logf("[Kohya] 使用内置离线 wheel 安装 Pillow/numpy…")
                if run_stream([vpy, "-m", "pip", "install", "--no-input", "--no-index"] + _wheels2,
                              cwd=kdir, env=_env2, logf=logf) == 0:
                    _ok2 = True
            if not _ok2:
                for _idx2 in ("https://pypi.tuna.tsinghua.edu.cn/simple",
                              "https://mirrors.aliyun.com/pypi/simple/"):
                    if run_stream([vpy, "-m", "pip", "install", "--no-input", "--retries", "10", "--timeout", "120",
                                   "--index-url", _idx2, "pillow", "numpy"], cwd=kdir, env=_env2, logf=logf) == 0:
                        _ok2 = True
                        break
                    logf("[Kohya] 当前镜像下载失败，切换备用镜像重试…")
            if not _ok2 or not _dep_ok("import PIL, numpy"):
                raise RuntimeError("自动补装 Pillow/numpy 失败（网络不稳或镜像不可达），请检查网络后重试")
            logf("[Kohya] Pillow/numpy 补装完成。")
            with open(KOHYA_DIR_FILE, "w", encoding="utf-8") as f:
                f.write(kdir)
            return kdir
        logf("[Kohya] 设置 pip 镜像源（清华 pypi + 阿里 pytorch cu128，无需代理）…")
        subprocess.run([vpy, "-m", "pip", "config", "set", "global.index-url",
                        "https://pypi.tuna.tsinghua.edu.cn/simple"], capture_output=True, timeout=60)
        subprocess.run([vpy, "-m", "pip", "config", "set", "global.extra-index-url",
                        "https://mirrors.aliyun.com/pytorch-wheels/cu128"], capture_output=True, timeout=60)
        logf("[Kohya] 升级 pip / setuptools / wheel …")
        if not _upgrade_pip(vpy, kdir, logf, label="Kohya"):
            raise RuntimeError(
                "pip 升级失败：清华/阿里镜像均不可达（常见：网络/防火墙/镜像临时故障）。\n"
                "请检查网络后重试；若手动验证，可运行：\n"
                f"  {vpy} -m pip install --upgrade pip setuptools wheel\n"
                "若提示 No module named pip，请直接重跑【② 安装训练内核】自动重建环境。")
        if not torch_ok:
            # 3.3GB 的 torch 大轮子用 pip 直连下载容易卡死（无续传）：
            # 先 curl 断点续传预下载并装进 venv，官方 setup 检测到已装就会跳过。
            logf("[Kohya] 预下载 PyTorch 大轮子（torch ~3.3GB，curl 断点续传，避免安装卡死）…")
            try:
                _preinstall_torch(vpy, kdir, logf, xf_ver="0.0.30", label="Kohya")
                torch_ok = _dep_ok("import torch; print(torch.__version__)")
                if torch_ok:
                    logf("[Kohya] PyTorch 预装成功，官方安装脚本将跳过 torch 下载。")
            except Exception as e:
                logf(f"[Kohya] PyTorch 预下载失败（{e}），改由官方安装脚本处理（可能较慢，需多次重试）。")
        logf("[Kohya] 安装全部依赖（官方无人值守模式，约 10-30 分钟）…")
        env = build_env([os.path.dirname(git)])
        env.setdefault("PIP_EXTRA_INDEX_URL", "https://mirrors.aliyun.com/pytorch-wheels/cu128")
        if run_stream([vpy, "setup\\setup_windows.py", "--headless"], cwd=kdir, env=env, logf=logf) != 0:
            raise RuntimeError("依赖安装失败，请向上滚动查看 pip 报错")
        with open(KOHYA_DIR_FILE, "w", encoding="utf-8") as f:
            f.write(kdir)
        try:
            r = subprocess.run(
                [vpy, "-c", "import torch;print(torch.__version__);print(torch.version.cuda or '');print(torch.cuda.is_available())"],
                capture_output=True, text=True, timeout=180,
            )
            lines = (r.stdout or "").strip().splitlines()
            torchv = lines[0] if lines else "?"
            cudav = lines[1] if len(lines) > 1 else "?"
            cuda = lines[2] if len(lines) > 2 else "?"
            logf(f"[Kohya] 验证：torch {torchv} | CUDA 构建: {cudav or '无'} | CUDA 可用: {cuda}")
            if r.returncode != 0:
                detail = ((r.stderr or "") + (r.stdout or "")).strip()
                logf(f"[Kohya] ✖ torch 导入失败（不是 CPU 版，而是环境/依赖未能加载）：{detail[-800:] or '未知错误'}")
                raise RuntimeError(
                    "Kohya 安装后 torch 验证失败，未完成安装。请重跑【② 安装训练内核】；"
                    "如果仍失败，请把本行上方的 torch 导入错误发来。"
                )
            if _gpu_vendor != "amd" and cuda != "True":
                logf("[Kohya] ⚠ torch 未启用 CUDA（可能是 CPU 版）。训练会全程 CPU 且极慢，"
                     "请重跑【一键安装】确保装 cu128 版 PyTorch，或检查 NVIDIA 驱动。")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Kohya 安装后 torch 验证失败：{e}。请重跑【② 安装训练内核】")
        return kdir
    finally:
        _release_kohya_install_lock(lock_f)


# ---------- 第二训练引擎（musubi-tuner：Krea2 图像 + 视频 LoRA） ----------

def _musubi_marker_ok():
    """第二引擎快速标记检查（秒级、不跑 import，供 system_status 缓存使用）。

    判定：musubi-venv 存在 + site-packages 里有 musubi-tuner（editable 装会留下
    *.dist-info / *_editable_impl_musubi_tuner.pth）+ 源码里有 krea2_train_network.py。
    """
    kdir = get_kohya_dir()
    vpy = os.path.join(kdir, "musubi-venv", "Scripts", "python.exe")
    if not os.path.isfile(vpy):
        return False
    if not os.path.isfile(os.path.join(kdir, "musubi-tuner", "krea2_train_network.py")):
        return False
    sp = os.path.join(kdir, "musubi-venv", "Lib", "site-packages")
    if not os.path.isdir(sp):
        return False
    try:
        return any("musubi" in n.lower() for n in os.listdir(sp))
    except Exception:
        return False


# 第二引擎固定 PyTorch 配对：torch 2.7.1+cu128 ↔ torchvision 0.22.1+cu128
MUSUBI_TORCH_VERSION = "2.7.1"
MUSUBI_TORCHVISION_VERSION = "0.22.1"
MUSUBI_CUDA_VERSION = "12.8"


def _parse_musubi_torch_pair(text, gpu_vendor="nvidia"):
    """解析第二引擎版本检查输出，返回 (ok, detail)。纯函数，便于测试。"""
    info = {}
    for line in (text or "").strip().splitlines():
        if "=" in line:
            k, _, val = line.partition("=")
            info[k.strip()] = val.strip()
    torch_v = info.get("TORCH", "")
    tv_v = info.get("TV", "")
    cuda = info.get("CUDA", "")
    avail = info.get("AVAIL", "False")
    if not torch_v:
        return False, "未检测到 torch（musubi-venv 内 torch 未安装）"
    if not tv_v:
        return False, "未检测到 torchvision（torch %s 缺少配套 torchvision）" % torch_v
    if torch_v != MUSUBI_TORCH_VERSION:
        return False, "torch 版本不符：%s（本工具第二引擎要求 %s+cu128）" % (torch_v, MUSUBI_TORCH_VERSION)
    if tv_v != MUSUBI_TORCHVISION_VERSION:
        return False, ("torch/torchvision 版本不匹配：torch %s 配 torchvision %s；"
                       "应为 torch %s + torchvision %s（torch 2.7.1 配 0.22.0 会依赖冲突装不上）"
                       % (torch_v, tv_v, MUSUBI_TORCH_VERSION, MUSUBI_TORCHVISION_VERSION))
    if cuda != MUSUBI_CUDA_VERSION:
        return False, "torch 非 cu128 构建（CUDA %s），第二引擎要求 cu128（CUDA %s）" % (cuda or "无", MUSUBI_CUDA_VERSION)
    if gpu_vendor != "amd" and avail != "True":
        return False, "torch 未启用 CUDA（疑似 CPU 版 torch），第二引擎无法训练"
    return True, "torch %s+cu128 + torchvision %s+cu128" % (torch_v, tv_v)


def _musubi_torch_pair_check(vpy):
    """校验 musubi-venv 中 torch/torchvision 是否为本工具要求的配对组合。

    torch 2.7.x 必须搭配 torchvision 0.22.x 同小版本：2.7.0→0.22.0、2.7.1→0.22.1。
    旧版本曾写错成 torch 2.7.1 + torchvision 0.22.0（依赖冲突/装不上），
    这里按版本号严格校验，不匹配的旧环境会被识别为“需要修复”。
    返回 (ok, detail)。
    """
    code = (
        "import importlib.metadata as md\n"
        "import torch, torchvision\n"
        "def _v(n):\n"
        "    try:\n"
        "        return (md.version(n) or '').split('+')[0]\n"
        "    except Exception:\n"
        "        return ''\n"
        "print('TORCH=' + _v('torch'))\n"
        "print('TV=' + _v('torchvision'))\n"
        "print('CUDA=' + str(getattr(torch.version, 'cuda', '') or ''))\n"
        "print('AVAIL=' + str(torch.cuda.is_available()))\n"
    )
    try:
        r = subprocess.run([vpy, "-c", code], capture_output=True, text=True, timeout=180)
    except Exception as e:
        return False, "torch 版本检查失败：%s" % e
    try:
        vendor = detect_gpu_vendor()
    except Exception:
        vendor = "nvidia"
    return _parse_musubi_torch_pair(r.stdout, gpu_vendor=vendor)


def musubi_engine_status():
    """第二训练引擎（musubi-tuner）状态：返回 (ok, detail, venv_python)。

    独立 musubi-venv（不碰 kohya venv，避免 transformers 版本冲突）。
    这是权威检查（会 import 验证）；徽章/缓存请用 _musubi_marker_ok（秒级）。
    """
    kdir = get_kohya_dir()
    vpy = os.path.join(kdir, "musubi-venv", "Scripts", "python.exe")
    src_ok = os.path.isfile(os.path.join(kdir, "musubi-tuner", "krea2_train_network.py"))
    if not os.path.isfile(vpy):
        return False, "未安装（musubi-venv 不存在）", vpy
    if not src_ok:
        return False, "musubi-tuner 源码缺失", vpy
    try:
        pair_ok, pair_detail = _musubi_torch_pair_check(vpy)
    except Exception as e:
        pair_ok, pair_detail = False, "torch 版本检查失败：%s" % e
    if not pair_ok:
        return False, pair_detail, vpy
    try:
        r = subprocess.run(
            [vpy, "-c", "import torch; import musubi_tuner; from musubi_tuner.krea2_train_network import main; print('ok')"],
            capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            return True, "已就绪（Krea2 + 视频）", vpy
        return False, "环境异常（import 失败）", vpy
    except Exception:
        return False, "环境异常", vpy


def install_musubi_engine(logf=print):
    """安装第二训练引擎 musubi-tuner（Krea2 图像 LoRA + 视频 LoRA）。

    - 独立 musubi-venv（不碰 kohya venv，避免 transformers 版本冲突）；
    - 源码用内置离线包，依赖走国内镜像；torch cu128 与 kohya 同源（官方 index，国内暂无稳定 cu128 镜像）；
    - 已安装则跳过（幂等）。返回 musubi-venv 的 python 路径。
    """
    git = find_git()
    py, pyver = find_python()
    if not git or not py:
        raise RuntimeError("请先点击【环境准备】安装 Git / Python")
    kdir = get_kohya_dir()
    logf(f"[第二引擎] 安装目录: {kdir}")
    lock_f = _acquire_kohya_install_lock(kdir, logf)
    if lock_f is None:
        raise RuntimeError("检测到另一个安装任务正在运行，请先等待完成后再试。")
    try:
        # 1) 源码
        mt_dir = os.path.join(kdir, "musubi-tuner")
        if not os.path.isfile(os.path.join(mt_dir, "krea2_train_network.py")):
            zip_src = _bundled_musubi_zip()
            if zip_src:
                logf(f"[第二引擎] 解压内置 musubi-tuner 源码: {os.path.basename(zip_src)}")
                _extract_zip(zip_src, mt_dir)
            else:
                logf("[第二引擎] 未找到内置源码包，改用 git 克隆（需联网）…")
                os.makedirs(mt_dir, exist_ok=True)
                if _git_clone(git, "https://github.com/kohya-ss/musubi-tuner.git", mt_dir, logf) != 0:
                    raise RuntimeError("git clone musubi-tuner 失败，请检查网络/代理后重试")
        else:
            logf("[第二引擎] musubi-tuner 源码已存在，跳过解压")
        # 2) 独立 venv
        mv = os.path.join(kdir, "musubi-venv")
        vpy = os.path.join(mv, "Scripts", "python.exe")
        if not os.path.isfile(vpy):
            logf("[第二引擎] 创建独立虚拟环境 musubi-venv（不影响 kohya venv）…")
            if run_stream([py, "-m", "venv", mv], cwd=kdir, logf=logf) != 0 or not os.path.isfile(vpy):
                raise RuntimeError("创建 musubi-venv 失败")
            if not _ensure_venv_pip(vpy, mv, logf, label="第二引擎"):
                raise RuntimeError("musubi-venv 创建后无 pip，请检查 Python 安装是否完整")
        else:
            # venv 已存在：先做健康检查（base Python 缺失 / DLL 跨版本混用），
            # 再确保 pip 可用（创建中断/ensurepip 缺失/被杀软清理都可能导致无 pip）。
            _vok, _vdetail = _venv_python_ok(vpy)
            _need_rebuild = False
            if not _vok:
                logf(f"[第二引擎] ⚠ 检测到 musubi-venv 已损坏：{_vdetail}")
                logf("[第二引擎] 常见原因：数据目录迁移到新盘/更换系统用户/混入其他版本 Python 的依赖。")
                _need_rebuild = True
            elif not _ensure_venv_pip(vpy, mv, logf, label="第二引擎"):
                logf("[第二引擎] ⚠ musubi-venv 缺 pip 且自愈失败，自动重建（旧 venv 保留）…")
                _need_rebuild = True
            if _need_rebuild:
                _bak = os.path.join(kdir, "musubi-venv_broken_%s" % time.strftime("%Y%m%d_%H%M%S"))
                if os.path.exists(_bak):
                    _bak += "_1"
                try:
                    os.rename(mv, _bak)
                    logf(f"[第二引擎] 旧 venv 已保留到: {os.path.basename(_bak)}")
                except Exception as _e:
                    raise RuntimeError("旧 musubi-venv 重命名失败（%s），请手动删除/移动 %s 后重试" % (_e, mv))
                logf("[第二引擎] 用当前 Python 重建 musubi-venv…")
                if run_stream([py, "-m", "venv", mv], cwd=kdir, logf=logf) != 0 or not os.path.isfile(vpy):
                    raise RuntimeError("重建 musubi-venv 失败")
                if not _ensure_venv_pip(vpy, mv, logf, label="第二引擎"):
                    raise RuntimeError("musubi-venv 重建后仍无 pip，请检查 Python 安装是否完整")
        # 3) 已装验证：torch/torchvision 配对正确 + musubi_tuner 可用 => 跳过
        try:
            pair_ok, pair_detail = _musubi_torch_pair_check(vpy)
        except Exception as e:
            pair_ok, pair_detail = False, "torch 版本检查失败：%s" % e
        musubi_ok = pair_ok
        if musubi_ok:
            try:
                r = subprocess.run(
                    [vpy, "-c", "import torch; import musubi_tuner; from musubi_tuner.krea2_train_network import main"],
                    capture_output=True, text=True, timeout=180)
                musubi_ok = r.returncode == 0
            except Exception:
                musubi_ok = False
        if musubi_ok:
            logf("[第二引擎] 检测到已安装（torch 2.7.1 + torchvision 0.22.1 + musubi_tuner 可用），跳过重复安装。")
            return vpy
        if not pair_ok:
            logf(f"[第二引擎] {pair_detail}；将自动重装 torch {MUSUBI_TORCH_VERSION}+cu128 + "
                 f"torchvision {MUSUBI_TORCHVISION_VERSION}+cu128 …")
        # 4) pip 镜像（清华 pypi + 阿里 pytorch 额外源，与 kohya 一致）
        subprocess.run([vpy, "-m", "pip", "config", "set", "global.index-url",
                        "https://pypi.tuna.tsinghua.edu.cn/simple"], capture_output=True, timeout=60)
        logf("[第二引擎] 升级 pip / setuptools / wheel …")
        if not _upgrade_pip(vpy, kdir, logf, label="第二引擎"):
            raise RuntimeError(
                "第二引擎 pip 升级失败：清华/阿里镜像均不可达（常见：网络/防火墙/镜像临时故障）。\n"
                "请检查网络后重试；若提示 No module named pip，工具已在上一步自动 ensurepip 自愈或重建。")
        # 5) torch cu128：阿里镜像 curl 断点续传预下载大轮子 → 本地安装
        #    （阿里 pytorch-wheels 是文件仓库，curl 直链可下；pip 不能把它当 index 解析，
        #      所以预下载+本地装是主路径，重试 3 次断点续传；彻底失败才回退官方 index）
        env = build_env([os.path.dirname(git)])
        _torch_ok = False
        for _try in range(3):
            try:
                _preinstall_torch(vpy, kdir, logf, torch_ver="2.7.1", tv_ver="0.22.1",
                                  cu="cu128", label="第二引擎", force=True)
                logf("[第二引擎] PyTorch 预装成功（阿里镜像 + 本地安装）。")
                _torch_ok = True
                break
            except Exception as e:
                logf(f"[第二引擎] PyTorch 预下载失败（第{_try + 1}/3 次）：{e}（断点续传，可重试）")
        if not _torch_ok:
            logf("[第二引擎] 阿里镜像预下载多次失败，改用 pip 官方 index 直装（国内需代理，或稍后重试）…")
            if run_stream(
                [vpy, "-m", "pip", "install", "torch==2.7.1+cu128", "torchvision==0.22.1+cu128",
                 "--extra-index-url", "https://download.pytorch.org/whl/cu128"],
                cwd=kdir, env=env, logf=logf) != 0:
                raise RuntimeError("torch cu128 安装失败，请检查网络/代理后重试")
        # 6) musubi-tuner（editable，带全套钉死依赖）
        logf("[第二引擎] 安装 musubi-tuner（Krea2/视频训练内核）…")
        if run_stream([vpy, "-m", "pip", "install", "-e", mt_dir], cwd=kdir, env=env, logf=logf) != 0:
            raise RuntimeError("musubi-tuner 安装失败")
        # 7) 验证
        try:
            r = subprocess.run(
                [vpy, "-c", "import torch;from musubi_tuner.krea2_train_network import main;print(torch.__version__);print(torch.cuda.is_available())"],
                capture_output=True, text=True, timeout=300)
            out = (r.stdout or "").strip().splitlines()
            logf(f"[第二引擎] 验证：torch {out[0] if out else '?'} | CUDA 可用: {out[1] if len(out) > 1 else '?'}")
            if r.returncode != 0:
                raise RuntimeError("第二引擎验证失败：" + (r.stderr or "")[-200:])
            pair_ok, pair_detail = _musubi_torch_pair_check(vpy)
            if not pair_ok:
                raise RuntimeError("第二引擎验证失败：" + pair_detail)
            logf(f"[第二引擎] {pair_detail}，配对校验通过。")
        except Exception as e:
            logf(f"[第二引擎] 验证失败: {e}")
            raise
        logf("[第二引擎] 安装完成：Krea2 图像 LoRA + 视频 LoRA 可用。")
        return vpy
    finally:
        _release_kohya_install_lock(lock_f)


# ---------- Krea2 图像 LoRA 训练（第二引擎 musubi-tuner） ----------

KREA2_RESOLUTION = 1024
KREA2_MAX_STEPS = 6000          # Krea2 自动约束最大总步数（防过拟合）

# Krea2 模型文件（放 models/krea2/，不内置；国内镜像直链）
KREA2_MODEL_LINKS = {
    "raw": ("raw.safetensors", "Krea 2 RAW 底模（约 13~26GB，训练必需）",
            "https://hf-mirror.com/krea/Krea-2-Raw/resolve/main/raw.safetensors"),
    "turbo": ("turbo.safetensors", "Krea 2 Turbo（可选，推理/训练采样用）",
              "https://hf-mirror.com/krea/Krea-2-Turbo/resolve/main/turbo.safetensors"),
    "vae": ("qwen_image_vae.safetensors", "Qwen-Image VAE（约 0.3GB）",
            "https://hf-mirror.com/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors"),
    "te": ("qwen3vl_4b_bf16.safetensors", "Qwen3-VL-4B 文本编码器（约 8GB）",
           "https://hf-mirror.com/Comfy-Org/Qwen3-VL/resolve/main/text_encoders/qwen3vl_4b_bf16.safetensors"),
}


def krea2_models_dir():
    return os.path.join(KIT_DIR, "models", "krea2")


def krea2_model_files():
    """扫描 models/krea2，返回 {raw,vae,te,turbo} 路径或 None。"""
    d = krea2_models_dir()
    out = {"raw": None, "vae": None, "te": None, "turbo": None}
    if os.path.isdir(d):
        for f in os.listdir(d):
            low = f.lower()
            p = os.path.join(d, f)
            if not os.path.isfile(p):
                continue
            if low == "raw.safetensors":
                out["raw"] = p
            elif low == "turbo.safetensors":
                out["turbo"] = p
            elif low == "qwen_image_vae.safetensors":
                out["vae"] = p
            elif low == "qwen3vl_4b_bf16.safetensors":
                out["te"] = p
    return out


def krea2_missing_models():
    """返回缺失的 Krea2 模型说明列表（含国内镜像直链）；turbo 可选不算缺失。"""
    files = krea2_model_files()
    missing = []
    for key, (fname, desc, url) in KREA2_MODEL_LINKS.items():
        if key == "turbo":
            continue
        if not files.get(key):
            missing.append(f"· {desc}\n  文件: {fname}\n  下载: {url}")
    return missing


# ---------- FLUX.2 图像 LoRA 训练（第二引擎 musubi-tuner） ----------
FLUX2_MODEL_VERSION = "klein-4b"     # musubi --model_version（klein-4b：4B 蒸馏/基础版）
FLUX2_RESOLUTION = 1024
FLUX2_MAX_STEPS = 6000               # FLUX.2 自动约束最大总步数（防过拟合）

# FLUX.2 klein 4B 模型文件（放 models/flux2/，不内置；Comfy-Org 非门禁 repack，国内镜像直链）
FLUX2_MODEL_LINKS = {
    "dit": ("flux-2-klein-base-4b.safetensors", "FLUX.2 klein 4B DiT 底模（base 版，约 7.2GB，训练必需）",
            "https://hf-mirror.com/Comfy-Org/flux2-klein-4B/resolve/main/split_files/diffusion_models/flux-2-klein-base-4b.safetensors"),
    "te": ("qwen_3_4b.safetensors", "Qwen3 4B 文本编码器（约 7.5GB，训练必需）",
           "https://hf-mirror.com/Comfy-Org/flux2-klein-4B/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors"),
    "vae": ("flux2-vae.safetensors", "FLUX.2 klein VAE（约 320MB，训练必需）",
            "https://hf-mirror.com/Comfy-Org/flux2-klein-4B/resolve/main/split_files/vae/flux2-vae.safetensors"),
}


def flux2_models_dir():
    return os.path.join(KIT_DIR, "models", "flux2")


def flux2_model_files():
    """扫描 models/flux2，返回 {dit,te,vae} 路径或 None。"""
    d = flux2_models_dir()
    out = {}
    for key, (fname, _desc, _url) in FLUX2_MODEL_LINKS.items():
        p = os.path.join(d, fname)
        if os.path.isfile(p):
            out[key] = p
    return out


def flux2_missing_models():
    """返回缺失的 FLUX.2 模型说明列表（含国内镜像直链）。"""
    files = flux2_model_files()
    missing = []
    for key, (fname, desc, url) in FLUX2_MODEL_LINKS.items():
        if not files.get(key):
            missing.append(f"· {desc}\n  文件: {fname}\n  下载: {url}")
    return missing


def write_musubi_dataset_config(image_dir, cache_dir, config_path, resolution=1024,
                                num_repeats=1, keep_tokens=1, caption_extension=".txt"):
    """musubi-tuner 数据集配置（与 kohya 不同：image_directory / cache_directory）。

    注意：musubi 的 schema 只接受 resolution/caption_extension/batch_size/num_repeats/
    enable_bucket/bucket_no_upscale（general 或 datasets 级），keep_tokens/shuffle_caption
    会被 voluptuous 校验拒绝，因此这里不输出。trigger 保护靠标签第一行（不 shuffle 即可）。
    """
    image_dir = os.path.abspath(image_dir).replace("\\", "/")
    cache_dir = os.path.abspath(cache_dir).replace("\\", "/")
    text = (
        "# Auto-generated by Kohya-LoRA tool (musubi-tuner dataset config).\n"
        "[general]\n"
        f"resolution = [{int(resolution)}, {int(resolution)}]\n"
        f'caption_extension = "{caption_extension}"\n'
        "batch_size = 1\n"
        "enable_bucket = true\n"
        "bucket_no_upscale = false\n"
        "\n"
        "[[datasets]]\n"
        f'image_directory = "{image_dir}"\n'
        f'cache_directory = "{cache_dir}"\n'
        f"num_repeats = {int(num_repeats)}\n"
    )
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(text)
    return image_dir


def train_krea2(logf=print, mode="krea2", params=None, vram_gb=None, resume_from=None, progress=None):
    """Krea2 图像 LoRA 训练（第二引擎 musubi-tuner）。

    流程：校验 musubi 环境 → 校验模型文件 → 写 musubi 数据集配置 → 缓存 latents/文本编码器 → 训练。
    模型需放入 models/krea2/（国内镜像下载，见 krea2_missing_models）。
    """
    params = params or {}
    ok, detail, mvpy = musubi_engine_status()
    if not ok:
        raise RuntimeError("第二训练引擎未安装，请先在左侧点「②' 第二引擎(可选)」安装。\n" + detail)
    kdir = get_kohya_dir()
    mt_dir = os.path.join(kdir, "musubi-tuner")
    accel = os.path.join(os.path.dirname(mvpy), "accelerate.exe")
    if not os.path.isfile(accel):
        raise RuntimeError("musubi-venv 缺少 accelerate，请重装第二引擎")
    files = krea2_model_files()
    missing = krea2_missing_models()
    if missing:
        raise RuntimeError(
            "Krea2 训练缺少模型文件，请下载放入 models/krea2/ 文件夹：\n\n" + "\n".join(missing) +
            "\n\n（在软件里点「打开 Krea2 模型文件夹」，用浏览器打开上面的国内镜像直链下载后放进去）")
    train_dir = dataset_train_dir(mode, params.get("project"))
    if count_images(train_dir) == 0:
        raise RuntimeError(f"缺少预处理数据：{train_dir}\n请先执行【数据预处理】")
    # 数据集配置 + 独立缓存目录
    proj = _sanitize_dirname(params.get("project")) or "krea2"
    cfg_path = os.path.join(KIT_DIR, "configs", "krea2_dataset_config.toml")
    cache_dir = os.path.join(data_dir(), "dataset", proj, "krea2_cache")
    os.makedirs(cache_dir, exist_ok=True)
    resolution = int(params.get("resolution") or KREA2_RESOLUTION)
    write_musubi_dataset_config(train_dir, cache_dir, cfg_path, resolution=resolution,
                                num_repeats=int(params.get("repeats", 5)), keep_tokens=1)
    logf(f"[Krea2] 数据集: {train_dir}（{resolution}px, repeats={params.get('repeats', 5)}）")
    # 预缓存 latents
    logf("[Krea2] 缓存 latents …")
    if run_stream([mvpy, os.path.join(mt_dir, "krea2_cache_latents.py"),
                   "--dataset_config", cfg_path, "--vae", files["vae"], "--num_workers", "1"],
                  cwd=mt_dir, logf=logf) != 0:
        raise RuntimeError("latents 缓存失败，请查看上方日志")
    # 预缓存文本编码器输出
    logf("[Krea2] 缓存文本编码器输出 …")
    if run_stream([mvpy, os.path.join(mt_dir, "krea2_cache_text_encoder_outputs.py"),
                   "--dataset_config", cfg_path, "--text_encoder", files["te"], "--batch_size", "1", "--num_workers", "1"],
                  cwd=mt_dir, logf=logf) != 0:
        raise RuntimeError("文本编码器缓存失败，请查看上方日志")
    # 训练参数
    rank = int(params.get("rank", 32))
    alpha = int(params.get("alpha", 32))
    lr = params.get("unet_lr", 1e-4)
    epochs = int(params.get("max_epochs", 16))
    gc_on = decide_gradient_checkpointing(params.get("gc", "自动"), vram_gb)
    # 显存适配：fp8 + blocks_to_swap（需实测校准）
    fp8 = vram_gb is None or vram_gb < 24
    swap = 2
    if vram_gb is None or vram_gb < 12:
        swap = 20
    elif vram_gb < 16:
        swap = 12
    elif vram_gb < 24:
        swap = 6
    # 防过拟合：总步数 ≈ 图片数 × repeats × epochs
    per_epoch = int(params.get("repeats", 5)) * count_images(train_dir)
    if per_epoch * epochs > KREA2_MAX_STEPS:
        new_epochs = max(1, int(KREA2_MAX_STEPS / max(1, per_epoch)))
        logf(f"[Krea2] 自动约束：为防过拟合，epoch 由 {epochs} 调整为 {new_epochs}（总步数约 {per_epoch * new_epochs}）")
        epochs = new_epochs
    if progress is not None:
        try:
            progress.set_total(per_epoch * epochs)
        except Exception:
            pass
    out_dir = data_sub("output", proj)
    output_name = "krea2_lora"
    cmd = [
        accel, "launch", "--num_cpu_threads_per_process", "1", "--mixed_precision", "bf16",
        os.path.join(mt_dir, "krea2_train_network.py"),
        "--dit", files["raw"], "--vae", files["vae"],
        "--dataset_config", cfg_path,
        "--sdpa", "--mixed_precision", "bf16",
        "--timestep_sampling", "shift", "--weighting_scheme", "none", "--discrete_flow_shift", "2.5",
        "--optimizer_type", "adamw8bit", "--learning_rate", str(lr), "--gradient_checkpointing",
        "--max_data_loader_n_workers", "1",
        "--network_module", "networks.lora_krea2", "--network_dim", str(rank), "--network_alpha", str(alpha),
        "--max_train_epochs", str(epochs), "--save_every_n_epochs", "1", "--seed", "42",
        "--output_dir", out_dir, "--output_name", output_name,
    ]
    if fp8:
        cmd += ["--fp8_base", "--fp8_scaled"]
    if swap > 0:
        cmd += ["--blocks_to_swap", str(swap)]
    if gc_on:
        cmd += ["--gradient_checkpointing"]
    logf(f"[Krea2] 底模(RAW): {files['raw']}")
    logf(f"[Krea2] LoRA 参数: dim={rank}, alpha={alpha}, lr={lr}, epochs={epochs}, repeats={params.get('repeats', 5)}")
    logf(f"[Krea2] fp8={'开' if fp8 else '关'} | blocks_to_swap={swap} | 梯度检查点={'开' if gc_on else '关'}（显存 {vram_gb if vram_gb else '?'}GB 智能适配）")
    rc = run_stream(cmd, cwd=mt_dir, logf=logf)
    if rc != 0:
        raise RuntimeError(f"Krea2 训练结束，退出码 {rc}，请查看上方日志")
    model_path = os.path.join(out_dir, output_name + ".safetensors")
    logf(f"[Krea2] 完成！模型: {model_path}")
    try:
        _write_krea2_template(mode, params, output_name, out_dir=out_dir)
        write_params_report(mode, params, output_name, out_dir=out_dir)
    except Exception as e:
        logf(f"[Krea2] 生成模板/报告失败（忽略）: {e}")
    return model_path


def _write_krea2_template(mode, params, output_name, out_dir=None):
    """Krea2 LoRA 使用模板。"""
    out_dir = out_dir or data_sub("output")
    path = os.path.join(out_dir, output_name + "_使用模板.txt")
    trig = ", ".join(split_triggers(params.get("trigger"))) if params.get("trigger") else "<你的触发词>"
    text = (
        "【Krea 2 图像 LoRA 使用模板】\n"
        f"模型文件：{output_name}.safetensors\n"
        f"Trigger 触发词：{trig}\n"
        "适用底模：Krea 2（RAW 训练 / Turbo 推理）\n"
        "训练分辨率：1024px\n\n"
        "使用建议：\n"
        f"1. 正向提示词以触发词开头：{trig}, <描述>\n"
        "2. 推荐 LoRA 权重 0.6 ~ 0.9\n"
        "3. 该 LoRA 只能用于 Krea 2 系列底模（不支持 SD/SDXL）。\n"
    )
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(text)
    return path



def train_flux2(logf=print, mode="flux2", params=None, vram_gb=None, resume_from=None, progress=None):
    """FLUX.2 klein 图像 LoRA 训练（第二引擎 musubi-tuner）。

    流程：校验 musubi 环境 → 校验模型文件 → 写 musubi 数据集配置 → 缓存 latents/文本编码器 → 训练。
    模型需放入 models/flux2/（国内镜像下载，见 flux2_missing_models）。
    """
    params = params or {}
    ok, detail, mvpy = musubi_engine_status()
    if not ok:
        raise RuntimeError("第二训练引擎未安装，请先在左侧点「②' 第二引擎(可选)」安装。\n" + detail)
    kdir = get_kohya_dir()
    mt_dir = os.path.join(kdir, "musubi-tuner")
    accel = os.path.join(os.path.dirname(mvpy), "accelerate.exe")
    if not os.path.isfile(accel):
        raise RuntimeError("musubi-venv 缺少 accelerate，请重装第二引擎")
    files = flux2_model_files()
    missing = flux2_missing_models()
    if missing:
        raise RuntimeError(
            "FLUX.2 训练缺少模型文件，请下载放入 models/flux2/ 文件夹：\n\n" + "\n".join(missing) +
            "\n\n（在软件里点「打开 FLUX.2 模型文件夹」，用应用内下载或浏览器打开上面的国内镜像直链下载后放进去）")
    train_dir = dataset_train_dir(mode, params.get("project"))
    if count_images(train_dir) == 0:
        raise RuntimeError(f"缺少预处理数据：{train_dir}\n请先执行【数据预处理】")
    # 数据集配置 + 独立缓存目录
    proj = _sanitize_dirname(params.get("project")) or "flux2"
    cfg_path = os.path.join(KIT_DIR, "configs", "flux2_dataset_config.toml")
    cache_dir = os.path.join(data_dir(), "dataset", proj, "flux2_cache")
    os.makedirs(cache_dir, exist_ok=True)
    resolution = int(params.get("resolution") or FLUX2_RESOLUTION)
    write_musubi_dataset_config(train_dir, cache_dir, cfg_path, resolution=resolution,
                                num_repeats=int(params.get("repeats", 2)), keep_tokens=1)
    logf(f"[FLUX.2] 数据集: {train_dir}（{resolution}px, repeats={params.get('repeats', 2)}）")
    # 预缓存 latents
    logf("[FLUX.2] 缓存 latents …")
    if run_stream([mvpy, os.path.join(mt_dir, "flux_2_cache_latents.py"),
                   "--dataset_config", cfg_path, "--vae", files["vae"],
                   "--model_version", FLUX2_MODEL_VERSION, "--num_workers", "1"],
                  cwd=mt_dir, logf=logf) != 0:
        raise RuntimeError("latents 缓存失败，请查看上方日志")
    # 预缓存文本编码器输出
    logf("[FLUX.2] 缓存文本编码器输出 …")
    if run_stream([mvpy, os.path.join(mt_dir, "flux_2_cache_text_encoder_outputs.py"),
                   "--dataset_config", cfg_path, "--text_encoder", files["te"],
                   "--batch_size", "1", "--num_workers", "1", "--model_version", FLUX2_MODEL_VERSION],
                  cwd=mt_dir, logf=logf) != 0:
        raise RuntimeError("文本编码器缓存失败，请查看上方日志")
    # 训练参数
    rank = int(params.get("rank", 32))
    alpha = int(params.get("alpha", 32))
    lr = params.get("unet_lr", 1e-4)
    epochs = int(params.get("max_epochs", 16))
    gc_on = decide_gradient_checkpointing(params.get("gc", "自动"), vram_gb)
    # 显存适配：fp8（DiT+文本编码器）+ blocks_to_swap（klein-4b 上限 13）
    fp8 = vram_gb is None or vram_gb < 24
    swap = 0
    if vram_gb is None or vram_gb < 12:
        swap = 10
    elif vram_gb < 16:
        swap = 6
    elif vram_gb < 24:
        swap = 2
    swap = min(swap, 13)
    # 防过拟合：总步数 ≈ 图片数 × repeats × epochs
    per_epoch = int(params.get("repeats", 2)) * count_images(train_dir)
    if per_epoch * epochs > FLUX2_MAX_STEPS:
        new_epochs = max(1, int(FLUX2_MAX_STEPS / max(1, per_epoch)))
        logf(f"[FLUX.2] 自动约束：为防过拟合，epoch 由 {epochs} 调整为 {new_epochs}（总步数约 {per_epoch * new_epochs}）")
        epochs = new_epochs
    if progress is not None:
        try:
            progress.set_total(per_epoch * epochs)
        except Exception:
            pass
    out_dir = data_sub("output", proj)
    output_name = "flux2_lora"
    cmd = [
        accel, "launch", "--num_cpu_threads_per_process", "1", "--mixed_precision", "bf16",
        os.path.join(mt_dir, "flux_2_train_network.py"),
        "--model_version", FLUX2_MODEL_VERSION,
        "--dit", files["dit"], "--vae", files["vae"], "--text_encoder", files["te"],
        "--dataset_config", cfg_path,
        "--sdpa", "--mixed_precision", "bf16",
        "--timestep_sampling", "flux2_shift", "--weighting_scheme", "none",
        "--optimizer_type", "adamw8bit", "--learning_rate", str(lr),
        "--max_data_loader_n_workers", "1",
        "--network_module", "networks.lora_flux_2", "--network_dim", str(rank), "--network_alpha", str(alpha),
        "--max_train_epochs", str(epochs), "--save_every_n_epochs", "1", "--seed", "42",
        "--output_dir", out_dir, "--output_name", output_name,
    ]
    if fp8:
        cmd += ["--fp8_base", "--fp8_scaled", "--fp8_text_encoder"]
    if swap > 0:
        cmd += ["--blocks_to_swap", str(swap)]
    if gc_on:
        cmd += ["--gradient_checkpointing"]
    logf(f"[FLUX.2] 底模: {files['dit']}")
    logf(f"[FLUX.2] LoRA 参数: dim={rank}, alpha={alpha}, lr={lr}, epochs={epochs}, repeats={params.get('repeats', 2)}")
    logf(f"[FLUX.2] fp8={'开' if fp8 else '关'} | blocks_to_swap={swap} | 梯度检查点={'开' if gc_on else '关'}（显存 {vram_gb if vram_gb else '?'}GB 智能适配）")
    rc = run_stream(cmd, cwd=mt_dir, logf=logf)
    if rc != 0:
        raise RuntimeError(f"FLUX.2 训练结束，退出码 {rc}，请查看上方日志")
    model_path = os.path.join(out_dir, output_name + ".safetensors")
    logf(f"[FLUX.2] 完成！模型: {model_path}")
    try:
        _write_flux2_template(mode, params, output_name, out_dir=out_dir)
        write_params_report(mode, params, output_name, out_dir=out_dir)
    except Exception as e:
        logf(f"[FLUX.2] 生成模板/报告失败（忽略）: {e}")
    return model_path


def _write_flux2_template(mode, params, output_name, out_dir=None):
    """FLUX.2 LoRA 使用模板。"""
    out_dir = out_dir or data_sub("output")
    path = os.path.join(out_dir, output_name + "_使用模板.txt")
    trig = ", ".join(split_triggers(params.get("trigger"))) if params.get("trigger") else "<你的触发词>"
    text = (
        "【FLUX.2 图像 LoRA 使用模板】\n"
        f"模型文件：{output_name}.safetensors\n"
        f"Trigger 触发词：{trig}\n"
        "适用底模：FLUX.2 klein 系列（训练用 base 4B，出图可配 klein 4B/Turbo）\n"
        "训练分辨率：1024px\n\n"
        "使用建议：\n"
        f"1. 正向提示词以触发词开头：{trig}, <描述>\n"
        "2. 推荐 LoRA 权重 0.6 ~ 0.9\n"
        "3. 该 LoRA 只能用于 FLUX.2 系列底模（不支持 SD/SDXL/FLUX.1）。\n"
    )
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(text)
    return path


# ---------- 第三训练引擎（AI Toolkit：MiniMax H3 视频 LoRA） ----------
# MiniMax-H3：33.1B 全模态视频 DiT（24fps + 32kHz 立体声音频），开放权重（社区许可证）。
# 训练内核用 Ostris AI Toolkit（已官方支持 H3 T2V/I2V LoRA，消费级 GPU 优化）。
# 权重用 Comfy-Org/MiniMax-H3 repack：pruned int8 DiT + nvfp4 AWQ Qwen3-VL-32B + fp16 视频VAE + fp32 音频VAE。

H3_FPS = 24
H3_MAX_STEPS = 3000            # 视频训练步数上限（防过拟合）
H3_DEFAULT_STEPS = 2000        # 默认总训练步数
H3_FRAMES = 73                 # 默认抽帧数（17n+5=73，约 3 秒 @24fps）

# H3 模型文件（放 models/minimax_h3/，不内置；国内镜像直链）
H3_MODEL_LINKS = {
    "dit": ("minimax_h3_fl2va_pruned_int8_convrot.safetensors", "H3 主模型 FL2VA（pruned int8，约 22GB，训练必需）",
            "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors"),
    "te": ("qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "Qwen3-VL-32B 文本编码器（nvfp4 AWQ，约 18GB）",
           "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"),
    "video_vae": ("minimax_h3_video_vae_fp16.safetensors", "视频 VAE（fp16，约 1GB）",
                  "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_fp16.safetensors"),
    "audio_vae": ("minimax_h3_audio_vae_fp32.safetensors", "音频 VAE（fp32，约 1GB，可选）",
                  "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors"),
}
FLUX_MODEL_LINKS = {
    "dit": ("flux1-dev.safetensors", "FLUX.1-dev DiT 主模型（约 23.8GB，训练必需；非门禁镜像）",
            "https://hf-mirror.com/Comfy-Org/flux1-dev/resolve/main/flux1-dev.safetensors"),
    "clip_l": ("clip_l.safetensors", "CLIP-L 文本编码器（约 0.25GB）",
               "https://hf-mirror.com/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors"),
    "t5xxl": ("t5xxl_fp16.safetensors", "T5-XXL 文本编码器 fp16（约 9.2GB）",
              "https://hf-mirror.com/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors"),
    "ae": ("ae.safetensors", "FLUX AE（VAE，约 0.2GB；非门禁镜像，自动存为 ae.safetensors）",
           "https://hf-mirror.com/Kijai/flux-fp8/resolve/main/flux-vae-bf16.safetensors"),
}

VIDEO_EXTS = {".mp4", ".avi", ".mov", ".webm", ".mkv", ".wmv", ".m4v", ".flv"}


def h3_models_dir():
    return os.path.join(KIT_DIR, "models", "minimax_h3")


def h3_model_files():
    """扫描 models/minimax_h3（含子目录），返回 {dit,te,video_vae,audio_vae} 路径或 None。"""
    d = h3_models_dir()
    out = {"dit": None, "te": None, "video_vae": None, "audio_vae": None}
    if not os.path.isdir(d):
        return out
    want = {
        "dit": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        "te": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        "video_vae": "minimax_h3_video_vae_fp16.safetensors",
        "audio_vae": "minimax_h3_audio_vae_fp32.safetensors",
    }
    for root, _dirs, files in os.walk(d):
        for f in files:
            low = f.lower()
            for key, fname in want.items():
                if out[key] is None and low == fname:
                    out[key] = os.path.join(root, f)
    return out


def h3_missing_models():
    """返回缺失的 H3 模型说明列表（含国内镜像直链）；音频 VAE 可选不算缺失。"""
    files = h3_model_files()
    missing = []
    for key in ("dit", "te", "video_vae"):
        if not files.get(key):
            fname, desc, url = H3_MODEL_LINKS[key]
            missing.append(f"· {desc}\n  文件: {fname}\n  下载: {url}")
    return missing


def flux_model_files():
    """扫描 models/base，返回 {dit,clip_l,t5xxl,ae} 路径或 None（FLUX 4 件套）。"""
    d = base_models_dir()
    out = {"dit": None, "clip_l": None, "t5xxl": None, "ae": None}
    if not os.path.isdir(d):
        return out
    want = {k: v[0].lower() for k, v in FLUX_MODEL_LINKS.items()}
    for f in os.listdir(d):
        low = f.lower()
        for key, fname in want.items():
            if out[key] is None and low == fname:
                out[key] = os.path.join(d, f)
    return out


def flux_missing_models():
    """返回缺失的 FLUX 模型说明列表（含国内镜像直链）；4 个文件都必需。"""
    files = flux_model_files()
    missing = []
    for key in ("dit", "clip_l", "t5xxl", "ae"):
        if not files.get(key):
            fname, desc, url = FLUX_MODEL_LINKS[key]
            missing.append(f"· {desc}\n  文件: {fname}\n  下载: {url}")
    return missing


def _load_app_settings():
    """读取用户设置（settings.json 固定放 %APPDATA%\\KohyaLoraTool，不随数据目录移动）。"""
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_app_settings(d):
    """保存用户设置（settings.json 固定放 %APPDATA%\\KohyaLoraTool）。"""
    try:
        with open(_settings_path(), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def data_dir_size():
    """当前数据目录总大小（字节）。"""
    total = 0
    try:
        for root, _dirs, files in os.walk(data_dir()):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except Exception:
                    pass
    except Exception:
        pass
    return total


def _copy_data_tree(src, dst, logf=print):
    """递归复制数据目录（跳过 src 根目录的 settings.json），返回 (文件数, 字节数)。"""
    n = 0
    total = 0
    os.makedirs(dst, exist_ok=True)
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        tgt = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(tgt, exist_ok=True)
        for f in files:
            if f == "settings.json" and os.path.abspath(root) == os.path.abspath(src):
                continue
            sp = os.path.join(root, f)
            dp = os.path.join(tgt, f)
            try:
                sz = os.path.getsize(sp)
                shutil.copy2(sp, dp)
                n += 1
                total += sz
            except Exception as e:
                logf(f"[迁移] 复制失败（跳过）: {sp} ({e})")
    return n, total


def migrate_data_dir(target, logf=print):
    """把当前数据目录整体迁移到 target（新盘/新位置）。

    流程：算大小 → 校验目标盘空间 → 复制 → 校验文件数 → 删源 → 写设置 → 清 kohya_dir.txt。
    大目录跨盘耗时，建议在后台线程调用。返回 (ok, msg)。
    """
    src = os.path.abspath(data_dir())
    target = os.path.abspath(target or "")
    if not target:
        return False, "未选择目标目录"
    if src.lower() == target.lower():
        return True, "目标目录与当前数据目录相同"
    size = data_dir_size()
    logf(f"[迁移] 当前数据目录: {src}（约 {size / 1048576:.0f} MB）")
    logf(f"[迁移] 目标目录: {target}")
    # 目标盘剩余空间校验
    try:
        _base = target if os.path.isdir(target) else (os.path.dirname(target) or ".")
        free = shutil.disk_usage(_base).free
    except Exception:
        free = None
    if free is not None and free < size:
        return False, f"目标盘剩余空间不足：需要约 {size / 1048576:.0f} MB，剩余 {free / 1048576:.0f} MB"
    # 复制（先复制后删源，中断也不丢数据）
    os.makedirs(target, exist_ok=True)
    try:
        n, copied = _copy_data_tree(src, target, logf)
    except Exception as e:
        return False, f"复制失败：{e}"
    logf(f"[迁移] 已复制 {n} 个文件（{copied / 1048576:.0f} MB）→ {target}")
    # 校验（settings.json 固定不迁移，需排除后再比）
    def _cnt(path):
        n = 0
        for root, _dirs, files in os.walk(path):
            for f in files:
                if f == "settings.json" and os.path.abspath(root) == os.path.abspath(path):
                    continue
                n += 1
        return n
    src_n = _cnt(src)
    tgt_n = _cnt(target)
    if tgt_n < src_n:
        return False, f"复制校验不完整（源 {src_n} 文件，目标 {tgt_n}），已保留源目录，请检查后重试"
    # 删源
    try:
        shutil.rmtree(src, ignore_errors=True)
        logf(f"[迁移] 已清理旧数据目录: {src}")
    except Exception as e:
        logf(f"[迁移] 旧目录清理失败（可手动删除）: {e}")
    # 写设置 + 清 kohya_dir.txt（让 get_kohya_dir 走新 data_dir/kohya_ss）
    if not save_data_setting(target):
        return False, "迁移完成但设置保存失败，请手动在「设置」里指定数据目录"
    try:
        if os.path.isfile(KOHYA_DIR_FILE):
            os.remove(KOHYA_DIR_FILE)
    except Exception:
        pass
    logf(f"[迁移] 完成！数据目录已切换为: {target}")
    return True, "迁移完成"


def at_custom_dir():
    """用户导入的第三引擎（AI Toolkit）自定义目录（含 ai-toolkit 源码或 run.py 所在目录）。"""
    return (_load_app_settings().get("at_dir") or "").strip()


def _at_dirs():
    """返回第三引擎实际目录 (venv_py, at_src_dir)。

    优先用户导入的自定义目录（可能指向 ai-toolkit 源码目录本身，或含 ai-toolkit 子目录的根目录）；
    否则用标准位置 kdir/ai_toolkit_venv + kdir/ai-toolkit。
    """
    custom = at_custom_dir()
    kdir = get_kohya_dir()
    if custom:
        cand = os.path.abspath(custom)
        if os.path.isfile(os.path.join(cand, "run.py")):
            src = cand
        elif os.path.isfile(os.path.join(cand, "ai-toolkit", "run.py")):
            src = os.path.join(cand, "ai-toolkit")
        else:
            src = cand
        vp = None
        for base in (src, os.path.dirname(src), cand, os.path.dirname(cand)):
            for v in ("ai_toolkit_venv", "venv"):
                p = os.path.join(base, v, "Scripts", "python.exe")
                if os.path.isfile(p):
                    vp = p
                    break
            if vp:
                break
        if vp and os.path.isfile(os.path.join(src, "run.py")):
            return vp, src
    return (os.path.join(kdir, "ai_toolkit_venv", "Scripts", "python.exe"),
            os.path.join(kdir, "ai-toolkit"))


def clear_status_cache():
    """清空环境检测缓存（安装/导入完成后调用，让界面立即反映最新状态）。"""
    _SYSTEM_STATUS_CACHE["t"] = 0.0
    _SYSTEM_STATUS_CACHE["data"] = None


def _at_marker_ok():
    """第三引擎快速标记检查（秒级）：venv + ai-toolkit 源码 + run.py（支持用户导入的自定义目录）。"""
    vpy, at_dir = _at_dirs()
    if not os.path.isfile(vpy):
        return False
    return os.path.isfile(os.path.join(at_dir, "run.py"))


def ai_toolkit_engine_status():
    """第三训练引擎（AI Toolkit）状态：返回 (ok, detail, venv_python)。支持用户导入的自定义目录。"""
    vpy, at_dir = _at_dirs()
    if not os.path.isfile(vpy):
        return False, "未安装（未检测到 venv）", vpy
    if not os.path.isfile(os.path.join(at_dir, "run.py")):
        return False, "ai-toolkit 源码缺失", vpy
    try:
        r = subprocess.run(
            [vpy, "-c", "import torch; from toolkit.config_modules import ModelConfig; print('ok')"],
            capture_output=True, text=True, timeout=120, cwd=at_dir)
        if r.returncode == 0:
            return True, "已就绪（MiniMax H3 视频）", vpy
        return False, "环境异常（import 失败）", vpy
    except Exception:
        return False, "环境异常", vpy


def install_ai_toolkit_engine(logf=print):
    """安装第三训练引擎 AI Toolkit（MiniMax H3 视频 LoRA）。

    - 独立 ai_toolkit_venv（不碰 kohya / musubi venv）；
    - 源码 git clone（无内置包）；torch cu130 + requirements 走国内镜像；
    - 已安装则跳过（幂等）。返回 ai_toolkit_venv 的 python 路径。
    """
    git = find_git()
    py, pyver = find_python()
    if not git or not py:
        raise RuntimeError("请先点击【环境准备】安装 Git / Python")
    # PyTorch cu130 需要 NVIDIA 驱动 570+：驱动过旧时装完首次初始化 CUDA 可能驱动崩溃（蓝屏）。
    # 提前检测并阻止，引导用户先更新驱动。
    try:
        _drv = nvidia_driver_version()
        if _drv is not None and _drv < 570:
            raise RuntimeError(
                "检测到 NVIDIA 驱动版本过低（当前 %d，PyTorch cu130 需要 570+）。\n\n"
                "直接安装可能导致首次运行 CUDA 时驱动崩溃（蓝屏）。\n"
                "请先更新 NVIDIA 显卡驱动到 570 及以上版本（GeForce 官网或 Windows 更新），再重试安装第三引擎。" % _drv)
    except RuntimeError:
        raise
    except Exception:
        pass
    kdir = get_kohya_dir()
    # 用户已导入自定义环境且可用：直接复用，不重复部署
    if at_custom_dir():
        _vp, _ad = _at_dirs()
        if os.path.isfile(_vp) and os.path.isfile(os.path.join(_ad, "run.py")):
            try:
                r = subprocess.run(
                    [_vp, "-c", "import torch; from toolkit.config_modules import ModelConfig; print('ok')"],
                    capture_output=True, text=True, timeout=120, cwd=_ad)
                if r.returncode == 0:
                    logf(f"[第三引擎] 检测到已导入的自定义环境可用，跳过安装：{_ad}")
                    return _vp
            except Exception:
                pass
        logf(f"[第三引擎] 已导入自定义目录但环境不完整，将安装到标准位置：{kdir}")
    logf(f"[第三引擎] 安装目录: {kdir}")
    lock_f = _acquire_kohya_install_lock(kdir, logf)
    if lock_f is None:
        raise RuntimeError("检测到另一个安装任务正在运行，请先等待完成后再试。")
    try:
        at_dir = _at_dirs()[1]
        if not os.path.isfile(os.path.join(at_dir, "run.py")):
            # 目录存在但源码不完整（clone 中断残留等），清理后重新克隆，避免 git clone 到非空目录失败
            if os.path.isdir(at_dir):
                logf("[第三引擎] ai-toolkit 目录不完整（缺 run.py），正在清理后重新克隆…")
                try:
                    shutil.rmtree(at_dir, ignore_errors=True)
                except Exception:
                    pass
            logf("[第三引擎] git clone ai-toolkit（Ostris，H3 视频训练内核）…")
            os.makedirs(at_dir, exist_ok=True)
            if _git_clone(git, "https://github.com/ostris/ai-toolkit.git", at_dir, logf) != 0:
                raise RuntimeError("git clone ai-toolkit 失败，请检查网络/代理后重试")
        else:
            logf("[第三引擎] ai-toolkit 源码已存在，跳过克隆")
        av = os.path.join(kdir, "ai_toolkit_venv")
        vpy = os.path.join(av, "Scripts", "python.exe")
        if not os.path.isfile(vpy):
            logf("[第三引擎] 创建独立虚拟环境 ai_toolkit_venv（不影响 kohya/musubi）…")
            if run_stream([py, "-m", "venv", av], cwd=kdir, logf=logf) != 0 or not os.path.isfile(vpy):
                raise RuntimeError("创建 ai_toolkit_venv 失败")
        # 已装验证
        try:
            r = subprocess.run(
                [vpy, "-c", "import torch; from toolkit.config_modules import ModelConfig"],
                capture_output=True, text=True, timeout=180, cwd=at_dir)
            torch_ok = r.returncode == 0
        except Exception:
            torch_ok = False
        if torch_ok:
            logf("[第三引擎] 检测到已安装（torch + ai-toolkit 可用），跳过重复安装。")
            return vpy
        # pip 镜像
        subprocess.run([vpy, "-m", "pip", "config", "set", "global.index-url",
                        "https://pypi.tuna.tsinghua.edu.cn/simple"], capture_output=True, timeout=60)
        logf("[第三引擎] 升级 pip / setuptools / wheel …")
        if run_stream([vpy, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel", "-q"],
                      cwd=kdir, logf=logf) != 0:
            raise RuntimeError("pip 升级失败，请重试")
        env = build_env([os.path.dirname(git)])
        # torch cu130：阿里镜像 curl 断点续传预下载大轮子 → 本地安装（重试 3 次，彻底失败回退官方 index）
        _torch_ok = False
        for _try in range(3):
            try:
                _preinstall_torch(vpy, kdir, logf, torch_ver="2.13.0", tv_ver="0.28.0",
                                  ta_ver="2.11.0", cu="cu130", label="第三引擎")
                logf("[第三引擎] PyTorch 预装成功（阿里镜像 + 本地安装）。")
                _torch_ok = True
                break
            except Exception as e:
                logf(f"[第三引擎] PyTorch 预下载失败（第{_try + 1}/3 次）：{e}（断点续传，可重试）")
        if not _torch_ok:
            logf("[第三引擎] 阿里镜像预下载多次失败，改用 pip 官方 index 直装（国内需代理，或稍后重试）…")
            if run_stream(
                [vpy, "-m", "pip", "install", "torch==2.13.0+cu130", "torchvision==0.28.0+cu130", "torchaudio==2.11.0+cu130",
                 "--index-url", "https://download.pytorch.org/whl/cu130"],
                cwd=kdir, env=env, logf=logf) != 0:
                raise RuntimeError("torch cu130 安装失败，请检查网络/代理/驱动后重试")
        # ai-toolkit 依赖
        logf("[第三引擎] 安装 ai-toolkit 依赖（较大，国内镜像 + 重试）…")
        if run_stream([vpy, "-m", "pip", "install", "--no-input", "--retries", "10", "--timeout", "120",
                       "-r", os.path.join(at_dir, "requirements.txt")], cwd=at_dir, env=env, logf=logf) != 0:
            raise RuntimeError("ai-toolkit 依赖安装失败")
        # 验证
        try:
            r = subprocess.run(
                [vpy, "-c", "import torch; from toolkit.config_modules import ModelConfig;"
                            "from extensions_built_in.diffusion_models.minimax_h3 import MinimaxH3Model;"
                            "print(torch.__version__)"],
                capture_output=True, text=True, timeout=300, cwd=at_dir)
            out = (r.stdout or "").strip().splitlines()
            logf(f"[第三引擎] 验证：torch {out[0] if out else '?'} | H3 扩展已注册（验证不初始化 CUDA，避免旧驱动崩溃）")
            if r.returncode != 0:
                raise RuntimeError("第三引擎验证失败：" + (r.stderr or "")[-300:])
        except Exception as e:
            logf(f"[第三引擎] 验证失败: {e}")
            raise
        logf("[第三引擎] 安装完成：MiniMax H3 视频 LoRA 可用。")
        return vpy
    finally:
        _release_kohya_install_lock(lock_f)


def scan_video_dataset(folder):
    """扫描视频数据集文件夹，返回 (视频文件列表, 总时长秒, 无字幕视频数)。

    AI Toolkit 数据集：文件夹内 .mp4 等视频 + 同名 .txt 字幕（myvideo.mp4 + myvideo.txt）。
    """
    if not folder or not os.path.isdir(folder):
        return [], 0.0, 0
    videos = []
    no_caption = 0
    for f in sorted(os.listdir(folder)):
        p = os.path.join(folder, f)
        if os.path.isfile(p) and os.path.splitext(f)[1].lower() in VIDEO_EXTS:
            videos.append(p)
            if not os.path.isfile(os.path.splitext(p)[0] + ".txt"):
                no_caption += 1
    total = 0.0
    ff = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    if ff:
        for v in videos[:60]:
            try:
                r = subprocess.run([ff, "-v", "error", "-show_entries", "format=duration",
                                    "-of", "default=noprint_wrappers=1:nokey=1", v],
                                   capture_output=True, text=True, timeout=60)
                if r.returncode == 0 and r.stdout.strip():
                    try:
                        total += float(r.stdout.strip())
                    except Exception:
                        pass
            except Exception:
                pass
    return videos, total, no_caption


def h3_generate_placeholder_captions(folder, trigger="", logf=print):
    """为没有字幕的视频生成占位 txt（内容 = trigger 或通用描述），避免训练缺字幕报错。"""
    if not folder or not os.path.isdir(folder):
        return 0
    base = trigger.strip() if trigger.strip() else "a video"
    n = 0
    for f in os.listdir(folder):
        p = os.path.join(folder, f)
        if os.path.isfile(p) and os.path.splitext(f)[1].lower() in VIDEO_EXTS:
            txt = os.path.splitext(p)[0] + ".txt"
            if not os.path.isfile(txt):
                try:
                    with open(txt, "w", encoding="utf-8") as fh:
                        fh.write(base + "\n")
                    n += 1
                except Exception:
                    pass
    if n:
        logf(f"[视频] 已为 {n} 个无字幕视频生成占位字幕（内容：{base}）")
    return n


def run_video_caption(logf=print, video_dir="", trigger="", frames=6, overwrite=False):
    """用 Qwen2.5-VL 给视频文件夹里的视频自动生成英文描述（写同名 txt）。

    用 kohya venv（transformers 4.54 已支持 Qwen2.5-VL），模型按需下载（走 hf-mirror）。
    已有同名 txt 默认跳过（避免覆盖手写描述），overwrite=True 强制重写。
    """
    vpy = venv_python()
    if not os.path.isfile(vpy):
        raise RuntimeError("Kohya 尚未安装，请先点击【一键安装】")
    if not video_dir or not os.path.isdir(video_dir):
        raise RuntimeError("请先选择视频数据集文件夹")
    script = os.path.join(KIT_DIR, "video_caption.py")
    if not os.path.isfile(script):
        raise RuntimeError("缺少 video_caption.py（打包异常），请重新安装")
    # 确保 kohya venv 依赖可用（transformers 等）
    _ensure_kohya_deps(vpy, get_kohya_dir(), logf)
    env = build_env()
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    _px = system_proxy()
    if _px:
        env.setdefault("HTTP_PROXY", _px)
        env.setdefault("HTTPS_PROXY", _px)
    cmd = [vpy, script, "--video_dir", video_dir, "--frames", str(frames)]
    if trigger:
        cmd += ["--trigger", trigger]
    if overwrite:
        cmd += ["--overwrite"]
    logf(f"[打标] 启动 Qwen2.5-VL 自动描述：{video_dir}（首次会下载模型约 6~7GB，请耐心等待）")
    rc = run_stream(cmd, cwd=KIT_DIR, env=env, logf=logf)
    if rc != 0:
        raise RuntimeError(f"视频自动打标失败（退出码 {rc}），请查看上方日志")
    return True



# AMD 版 PyTorch 分布式兼容补丁（sitecustomize，仅训练进程生效）
_AMD_DIST_PATCH = """# Auto-generated by Kohya-LoRA tool：AMD 版 PyTorch 的 torch.distributed 残缺时补默认接口。
import sys as _sys
_argv = " ".join(_sys.argv)
if any(_k in _argv for _k in ("train_network", "sdxl_train", "anima_train", "flux_train",
                              "krea2_train", "hv_train", "wan_train", "run.py")):
    try:
        import torch.distributed as _d
        if not hasattr(_d, "is_initialized"):
            _d.is_initialized = lambda: False
        if not hasattr(_d, "is_available"):
            _d.is_available = lambda: False
        if not hasattr(_d, "get_rank"):
            _d.get_rank = lambda: 0
        if not hasattr(_d, "destroy_process_group"):
            _d.destroy_process_group = lambda: None
    except Exception:
        pass
"""


def _ensure_amd_distributed_compat(vpy, logf=print):
    """AMD 版 PyTorch 的 torch.distributed 可能是残缺构建（缺 is_initialized 等），
    训练收尾时 accelerate 会崩、最终模型保存失败。

    检测缺接口后，在 venv 的 site-packages 写入 sitecustomize.py（条件生效：
    仅训练脚本启动时补接口，不拖慢 pip/普通 python）。幂等：不残缺则跳过。
    """
    try:
        venv_dir = os.path.dirname(os.path.dirname(vpy))
        sp = os.path.join(venv_dir, "Lib", "site-packages")
        if not os.path.isdir(sp) or not os.path.isfile(vpy):
            return
        need = False
        try:
            r = subprocess.run([vpy, "-c",
                                "import torch.distributed as d;print('ok' if hasattr(d,'is_initialized') else 'bad')"],
                               capture_output=True, text=True, timeout=180)
            need = (r.stdout or "").strip() == "bad" or r.returncode != 0
        except Exception:
            need = True
        if not need:
            return
        target = os.path.join(sp, "sitecustomize.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write(_AMD_DIST_PATCH)
        logf("[AMD] 检测到 torch.distributed 残缺，已写入兼容补丁（sitecustomize.py），训练收尾将不再崩溃")
    except Exception as e:
        logf(f"[AMD] 分布式兼容补丁写入失败（忽略，可手动修复）：{e}")





def write_h3_train_yaml(params, video_dir, out_dir, cfg_path):
    """生成 AI Toolkit 的 MiniMax H3 训练 yaml（增量、可复用）。返回 yaml 路径。"""
    name = _sanitize_dirname(params.get("project")) or "h3_video_lora"
    rank = int(params.get("rank", 32))
    alpha = int(params.get("alpha", 32))
    lr = float(params.get("unet_lr", 2e-4))
    steps = int(params.get("video_steps", H3_DEFAULT_STEPS))
    steps = max(100, min(H3_MAX_STEPS, steps))
    frames = int(params.get("video_frames", H3_FRAMES))
    trig = params.get("trigger") or ""
    model_dir = h3_models_dir().replace("\\", "/")
    video_dir = os.path.abspath(video_dir).replace("\\", "/")
    out_dir = os.path.abspath(out_dir).replace("\\", "/")
    sample_prompt = (trig + ", ") if trig else ""
    text = (
        "job: extension\n"
        "config:\n"
        "  name: " + _yq(name) + "\n"
        "  process:\n"
        "    - type: 'sd_trainer'\n"
        "      training_folder: " + _yq(out_dir) + "\n"
        "      device: cuda:0\n"
        "      trigger_word: " + _yq(trig) + "\n"
        "      network:\n"
        "        type: \"lora\"\n"
        "        linear: " + str(rank) + "\n"
        "        linear_alpha: " + str(alpha) + "\n"
        "      save:\n"
        "        dtype: float16\n"
        "        save_every: 200\n"
        "        max_step_saves_to_keep: 5\n"
        "      datasets:\n"
        "        - folder_path: " + _yq(video_dir) + "\n"
        "          caption_ext: \"txt\"\n"
        "          num_frames: " + str(frames) + "\n"
        "          resolution: [1280, 1280]\n"
        "      train:\n"
        "        batch_size: 1\n"
        "        steps: " + str(steps) + "\n"
        "        gradient_accumulation: 1\n"
        "        train_unet: true\n"
        "        train_text_encoder: false\n"
        "        gradient_checkpointing: true\n"
        "        noise_scheduler: \"flowmatch\"\n"
        "        timestep_type: 'linear'\n"
        "        optimizer: \"adamw8bit\"\n"
        "        lr: " + repr(lr) + "\n"
        "        dtype: bf16\n"
        "        cache_text_embeddings: true\n"
        "      model:\n"
        "        name_or_path: " + _yq(model_dir) + "\n"
        "        arch: 'minimax_h3'\n"
        "        model_kwargs:\n"
        "          partition: \"fl2va_pruned\"\n"
        "        quantize: false\n"
        "      sample:\n"
        "        sampler: \"flowmatch\"\n"
        "        sample_every: 250\n"
        "        width: 1280\n"
        "        height: 720\n"
        "        num_frames: " + str(frames) + "\n"
        "        fps: 24\n"
        "        prompts:\n"
        "          - " + _yq(sample_prompt + "a subject performing a simple action, cinematic lighting, high quality") + "\n"
        "        seed: 42\n"
        "        walk_seed: true\n"
        "        guidance_scale: 1.0\n"
        "        sample_steps: 20\n"
        "meta:\n"
        "  name: " + _yq(name) + "\n"
        "  version: '1.0'\n"
    )
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(text)
    return cfg_path


def _find_latest_safetensors(root):
    best, best_t = None, 0
    if not os.path.isdir(root):
        return None
    for dp, _dirs, fns in os.walk(root):
        for fn in fns:
            if fn.endswith(".safetensors"):
                p = os.path.join(dp, fn)
                try:
                    t = os.path.getmtime(p)
                except Exception:
                    continue
                if t > best_t:
                    best, best_t = p, t
    return best


def train_video(logf=print, mode="video", params=None, vram_gb=None, resume_from=None, progress=None):
    """MiniMax H3 视频 LoRA 训练（第三引擎 AI Toolkit，T2V）。"""
    params = params or {}
    ok, detail, vpy = ai_toolkit_engine_status()
    if not ok:
        raise RuntimeError("第三训练引擎未安装，请点顶部「⚙ 安装第三引擎」安装。\n" + detail)
    kdir = get_kohya_dir()
    at_dir = _at_dirs()[1]
    if not os.path.isfile(os.path.join(at_dir, "run.py")):
        raise RuntimeError("ai-toolkit 源码缺失，请重装第三引擎")
    missing = h3_missing_models()
    if missing:
        raise RuntimeError(
            "MiniMax H3 训练缺少模型文件，请下载放入 models/minimax_h3/ 文件夹：\n\n" + "\n".join(missing) +
            "\n\n（在软件里点「📂 打开 H3 模型文件夹」，用浏览器打开上面的国内镜像直链下载后放进去）")
    video_dir = params.get("raw_dir") or ""
    if not os.path.isdir(video_dir):
        raise RuntimeError("请先选择视频数据集文件夹（放 .mp4 + 同名 .txt 字幕）")
    videos, total_sec, no_cap = scan_video_dataset(video_dir)
    if not videos:
        raise RuntimeError(f"视频文件夹里没有找到视频文件（支持 mp4/avi/mov/webm/mkv/wmv/m4v/flv）：{video_dir}")
    if no_cap == len(videos):
        raise RuntimeError(
            "所有视频都没有同名 .txt 字幕。\n\n每个视频需要一个同名 txt 描述内容（如 myvideo.mp4 + myvideo.txt）。\n"
            "也可以在「📖 使用引导」里用「一键生成占位字幕」先用触发词顶上。")
    if vram_gb is not None and vram_gb < 24:
        logf(f"[视频] ⚠ 检测到显存 {vram_gb}GB：MiniMax H3 训练推荐 24GB 及以上（NVIDIA），显存不足容易 OOM 或极慢。")
    proj = _sanitize_dirname(params.get("project")) or "video"
    out_dir = data_sub("output", proj)
    os.makedirs(out_dir, exist_ok=True)
    cfg_path = os.path.join(KIT_DIR, "configs", "h3_train.yaml")
    write_h3_train_yaml(params, video_dir, out_dir, cfg_path)
    steps = int(params.get("video_steps", H3_DEFAULT_STEPS))
    logf(f"[视频] 数据集: {video_dir}（{len(videos)} 个视频，共约 {total_sec/60:.1f} 分钟，{no_cap} 个缺字幕）")
    _files = h3_model_files()
    logf(f"[视频] H3 模型: {os.path.basename(_files.get('dit') or '？')}")
    logf(f"[视频] LoRA 参数: dim={params.get('rank',32)}, alpha={params.get('alpha',32)}, lr={params.get('unet_lr','2e-4')}, steps={steps}")
    logf(f"[视频] 显存 {vram_gb if vram_gb else '?'}GB（推荐 24GB+）| bf16 + 梯度检查点 + 文本嵌入缓存")
    env = build_env()
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    _px = system_proxy()
    if _px:
        env.setdefault("HTTP_PROXY", _px)
        env.setdefault("HTTPS_PROXY", _px)
    if progress is not None:
        try:
            progress.set_total(steps)
        except Exception:
            pass
    logf("[视频] 启动 AI Toolkit 训练（首次要加载 30GB+ 模型，请耐心等待）…")
    rc = run_stream([vpy, os.path.join(at_dir, "run.py"), cfg_path], cwd=at_dir, env=env, logf=logf)
    if rc != 0:
        raise RuntimeError(f"MiniMax H3 训练结束，退出码 {rc}，请查看上方日志")
    model_path = _find_latest_safetensors(out_dir) or os.path.join(out_dir, "h3_video_lora.safetensors")
    logf(f"[视频] 完成！模型: {model_path}")
    try:
        _write_h3_template(mode, params, os.path.splitext(os.path.basename(model_path))[0], out_dir=os.path.dirname(model_path))
        write_params_report(mode, params, os.path.splitext(os.path.basename(model_path))[0], out_dir=os.path.dirname(model_path))
    except Exception as e:
        logf(f"[视频] 生成模板/报告失败（忽略）: {e}")
    return model_path


def _write_h3_template(mode, params, output_name, out_dir=None):
    """MiniMax H3 视频 LoRA 使用模板。"""
    out_dir = out_dir or data_sub("output")
    path = os.path.join(out_dir, output_name + "_使用模板.txt")
    trig = ", ".join(split_triggers(params.get("trigger"))) if params.get("trigger") else "<你的触发词>"
    text = (
        "【MiniMax H3 视频 LoRA 使用模板】\n"
        f"模型文件：{output_name}.safetensors\n"
        f"Trigger 触发词：{trig}\n"
        "适用底模：MiniMax H3（33.1B 全模态视频模型，含音频）\n"
        "训练方式：T2V（文生视频，约 24fps）\n\n"
        "使用建议：\n"
        f"1. 提示词以触发词开头：{trig}, <角色/风格描述>, <动作/运镜>，例如 {trig}, a girl walking in the rain, cinematic\n"
        "2. 该 LoRA 只能用于 MiniMax H3 系列模型（不支持 SD/SDXL/Wan/Hunyuan）。\n"
        "3. 生成视频建议 480~720p、3~10 秒，显存不足请降低分辨率或缩短时长。\n"
        "4. 许可：MiniMax H3 为社区许可证（开放权重），商用请自行确认条款。\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path



# ---------- AI Toolkit 图像 LoRA（Qwen-Image / Z-Image） ----------
# 走第三引擎 AI Toolkit（与 H3 视频同引擎）：diffusers 格式，首次训练自动下载模型（国内镜像）。
# 显存说明（写进引导/提示）：Qwen-Image 20B = 16G 起步、24G 舒服；Z-Image 8B = 12G 起步、16G 舒服。
AT_IMAGE_MODELS = {
    "qwen_image": {
        "label": "Qwen-Image（20B）",
        "arch": "qwen_image",
        "model_id": "Qwen/Qwen-Image-2512",
        "min_vram": 16, "rec_vram": 24,
        "size": "约 40GB",
        "hint": "Qwen-Image 是 20B 大模型：16G 显存起步、24G 舒服（推荐）。首次训练自动下载模型（约 40GB，国内镜像）。",
    },
    "zimage": {
        "label": "Z-Image（8B）",
        "arch": "zimage",
        "model_id": "Tongyi-MAI/Z-Image",
        "min_vram": 12, "rec_vram": 16,
        "size": "约 16GB",
        "hint": "Z-Image 是 8B 轻量模型：12G 显存起步、16G 舒服。首次训练自动下载模型（约 16GB，国内镜像）。训练用基础版，出图可配合 Turbo 加速。",
    },
}


def at_image_model_ready(mode):
    """检查 AI Toolkit 图像模型是否已下载（HF 缓存目录存在）。"""
    info = AT_IMAGE_MODELS.get(mode)
    if not info:
        return False
    try:
        cache_root = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
        folder = "models--" + info["model_id"].replace("/", "--")
        return os.path.isdir(os.path.join(cache_root, folder))
    except Exception:
        return False


def write_at_image_yaml(params, info, train_dir, out_dir, cfg_path):
    """生成 AI Toolkit 图像 LoRA 训练 yaml（Qwen-Image / Z-Image 共用）。"""
    name = _sanitize_dirname(params.get("project")) or "at_lora"
    rank = int(params.get("rank", 16))
    alpha = int(params.get("alpha", 16))
    lr = float(params.get("unet_lr", 1e-4))
    steps = max(100, min(6000, int(params.get("video_steps", 2000))))
    trig = params.get("trigger") or ""
    reso = int(params.get("resolution", 1024))
    train_dir = os.path.abspath(train_dir).replace("\\", "/")
    out_dir = os.path.abspath(out_dir).replace("\\", "/")
    sample_prompt = (trig + ", ") if trig else ""
    text = (
        "job: extension\n"
        "config:\n"
        "  name: " + _yq(name) + "\n"
        "  process:\n"
        "    - type: 'sd_trainer'\n"
        "      training_folder: " + _yq(out_dir) + "\n"
        "      device: cuda:0\n"
        "      trigger_word: " + _yq(trig) + "\n"
        "      network:\n"
        "        type: \"lora\"\n"
        "        linear: " + str(rank) + "\n"
        "        linear_alpha: " + str(alpha) + "\n"
        "      save:\n"
        "        dtype: float16\n"
        "        save_every: 200\n"
        "        max_step_saves_to_keep: 5\n"
        "      datasets:\n"
        "        - folder_path: " + _yq(train_dir) + "\n"
        "          caption_ext: \"txt\"\n"
        "          caption_dropout_rate: 0.05\n"
        "          num_frames: 1\n"
        "          resolution: [" + str(reso) + ", " + str(reso) + "]\n"
        "      train:\n"
        "        batch_size: 1\n"
        "        steps: " + str(steps) + "\n"
        "        gradient_accumulation: 1\n"
        "        train_unet: true\n"
        "        train_text_encoder: false\n"
        "        gradient_checkpointing: true\n"
        "        noise_scheduler: \"flowmatch\"\n"
        "        timestep_type: 'linear'\n"
        "        optimizer: \"adamw8bit\"\n"
        "        lr: " + repr(lr) + "\n"
        "        optimizer_params:\n"
        "          weight_decay: 1e-4\n"
        "        dtype: bf16\n"
        "        cache_text_embeddings: true\n"
        "      model:\n"
        "        name_or_path: " + _yq(info["model_id"]) + "\n"
        "        arch: '" + info["arch"] + "'\n"
        "        quantize: true\n"
        "        qtype: \"qfloat8\"\n"
        "        low_vram: true\n"
        "      sample:\n"
        "        sampler: \"flowmatch\"\n"
        "        sample_every: 250\n"
        "        width: " + str(reso) + "\n"
        "        height: " + str(reso) + "\n"
        "        num_frames: 1\n"
        "        prompts:\n"
        "          - " + _yq(sample_prompt + "a high quality detailed portrait, masterpiece, best quality") + "\n"
        "        seed: 42\n"
        "        walk_seed: true\n"
        "        guidance_scale: 4.0\n"
        "        sample_steps: 20\n"
        "meta:\n"
        "  name: " + _yq(name) + "\n"
        "  version: '1.0'\n"
    )
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(text)
    return cfg_path


def train_at_image(logf=print, mode="qwen_image", params=None, vram_gb=None, resume_from=None, progress=None):
    """AI Toolkit 图像 LoRA 训练（Qwen-Image / Z-Image，第三引擎）。"""
    params = params or {}
    info = AT_IMAGE_MODELS.get(mode)
    if not info:
        raise RuntimeError(f"未知模式: {mode}")
    ok, detail, vpy = ai_toolkit_engine_status()
    if not ok:
        raise RuntimeError("第三训练引擎未安装，请点顶部「⚙ 安装第三引擎」安装。\n" + detail)
    kdir = get_kohya_dir()
    at_dir = _at_dirs()[1]
    if not os.path.isfile(os.path.join(at_dir, "run.py")):
        raise RuntimeError("ai-toolkit 源码缺失，请重装第三引擎")
    train_dir = dataset_train_dir(mode, params.get("project"))
    if count_images(train_dir) == 0:
        raise RuntimeError(f"缺少预处理数据：{train_dir}\n请先执行【数据预处理】或【一键开始训练】")
    if vram_gb is not None and vram_gb < info["min_vram"]:
        logf(f"[{info['label']}] ⚠ 显存 {vram_gb}GB 低于建议 {info['min_vram']}G：{info['hint']}")
    proj = _sanitize_dirname(params.get("project")) or mode
    out_dir = data_sub("output", proj)
    os.makedirs(out_dir, exist_ok=True)
    cfg_path = os.path.join(KIT_DIR, "configs", mode + "_train.yaml")
    write_at_image_yaml(params, info, train_dir, out_dir, cfg_path)
    steps = int(params.get("video_steps", 2000))
    logf(f"[{info['label']}] 数据集: {train_dir}（{count_images(train_dir)} 张）")
    logf(f"[{info['label']}] 模型: {info['model_id']}（首次训练自动下载 {info['size']}，国内镜像）")
    logf(f"[{info['label']}] LoRA: dim={params.get('rank',16)}, alpha={params.get('alpha',16)}, lr={params.get('unet_lr','1e-4')}, steps={steps}")
    env = build_env()
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    _px = system_proxy()
    if _px:
        env.setdefault("HTTP_PROXY", _px)
        env.setdefault("HTTPS_PROXY", _px)
    if progress is not None:
        try:
            progress.set_total(steps)
        except Exception:
            pass
    logf("[训练] 启动 AI Toolkit 训练（首次要下载/加载大模型，请耐心等待）…")
    rc = run_stream([vpy, os.path.join(at_dir, "run.py"), cfg_path], cwd=at_dir, env=env, logf=logf)
    if rc != 0:
        raise RuntimeError(f"训练结束，退出码 {rc}，请查看上方日志")
    model_path = _find_latest_safetensors(out_dir) or os.path.join(out_dir, "lora.safetensors")
    logf(f"[{info['label']}] 完成！模型: {model_path}")
    try:
        _write_at_image_template(mode, params, os.path.splitext(os.path.basename(model_path))[0], out_dir=os.path.dirname(model_path))
        write_params_report(mode, params, os.path.splitext(os.path.basename(model_path))[0], out_dir=os.path.dirname(model_path))
    except Exception as e:
        logf(f"生成模板/报告失败（忽略）: {e}")
    return model_path


def _write_at_image_template(mode, params, output_name, out_dir=None):
    """Qwen-Image / Z-Image LoRA 使用模板。"""
    out_dir = out_dir or data_sub("output")
    path = os.path.join(out_dir, output_name + "_使用模板.txt")
    info = AT_IMAGE_MODELS.get(mode, {})
    trig = ", ".join(split_triggers(params.get("trigger"))) if params.get("trigger") else "<你的触发词>"
    text = (
        "【" + (info.get("label", "AI 图像") if info else "AI 图像") + " LoRA 使用模板】\n"
        f"模型文件：{output_name}.safetensors\n"
        f"Trigger 触发词：{trig}\n"
        f"适用模型：{info.get('model_id', '')}（" + (info.get("size", "") if info else "") + "）\n\n"
        "使用建议：\n"
        f"1. 提示词以触发词开头：{trig}, <描述>\n"
        "2. 推荐 LoRA 权重 0.6 ~ 0.9\n"
        "3. 该 LoRA 只能用于对应模型系列（不支持 SD/SDXL）。\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path




# ---------- 预处理 / UI / 训练 ----------

def preprocess(logf=print, input_dir=None, size=512, mode="style", trigger="",
               reg_dir=None, repeats=5, dedup=False, wd14=True,
               square_crop=False, min_size=0, blur_threshold=0.0, report=None,
               keep_tokens=None, project=None, style_caption="", dataset_mode=None):
    """dataset_mode：数据存储目录用的模式（默认跟随 mode）。

    Qwen-Image/Z-Image/Krea2 数据统一放 train_character 目录（与训练读取一致），
    即使画风子模式 mode=style 也传 dataset_mode="character"，避免预处理/训练目录不一致。
    """
    vpy = venv_python()
    if not os.path.isfile(vpy):
        raise RuntimeError("Kohya 尚未安装，请先点击【一键安装】")
    _vok, _vdetail = _venv_python_ok(vpy)
    if not _vok:
        raise RuntimeError(
            "Kohya 训练环境已损坏（%s）。\n"
            "常见原因：数据目录迁移到新盘/更换系统用户后，venv 指向的 Python 已不存在。\n"
            "请先重跑【② 安装训练内核】自动重建环境。" % _vdetail)
    if not input_dir or not os.path.isdir(input_dir):
        raise RuntimeError("请选择图片文件夹")
    # 预处理依赖自检：kohya venv 必须能 import Pillow/numpy（部分中断安装会缺，导致预处理永远失败）。
    # 缺失时自动补装（国内镜像，几秒），实现自愈，不用重装整个 kohya。
    try:
        _r = subprocess.run([vpy, "-c", "import PIL, numpy"], capture_output=True, text=True, timeout=120)
        _deps_ok = _r.returncode == 0
    except Exception:
        _deps_ok = False
    if not _deps_ok:
        logf("[预处理] kohya venv 缺少 Pillow/numpy（可能之前安装被中断），正在自动补装…")
        _kd = get_kohya_dir()
        _env = build_env()
        _ok = False
        # 优先用内置离线 wheel（彻底绕开网络不稳）
        _wheels = _wheels_for_python(_bundled_pip_wheels(), vpy)
        if _wheels:
            logf("[预处理] 使用内置离线 wheel 安装 Pillow/numpy…")
            if run_stream([vpy, "-m", "pip", "install", "--no-input", "--no-index"] + _wheels,
                          cwd=_kd, env=_env, logf=logf) == 0:
                _ok = True
        if not _ok:
            for _idx in ("https://pypi.tuna.tsinghua.edu.cn/simple",
                         "https://mirrors.aliyun.com/pypi/simple/"):
                if run_stream([vpy, "-m", "pip", "install", "--no-input", "--retries", "10", "--timeout", "120",
                               "--index-url", _idx, "pillow", "numpy"], cwd=_kd, env=_env, logf=logf) == 0:
                    _ok = True
                    break
                logf("[预处理] 当前镜像下载失败，切换备用镜像重试…")
        if not _ok:
            raise RuntimeError("自动补装 Pillow/numpy 失败（网络不稳或镜像不可达），请检查网络后重试，或重跑【② 安装训练内核】")
        logf("[预处理] Pillow/numpy 补装完成")
    out = dataset_train_dir(dataset_mode or mode, project)
    os.environ["TRIGGER_WORD"] = trigger or ""
    os.environ["MODE"] = mode
    os.makedirs(out, exist_ok=True)
    logf(f"[预处理] 输入: {input_dir}")
    logf(f"[预处理] 输出: {out}  |  模式: {MODE_LABELS.get(mode, mode)}  |  分辨率 {size}px")
    cmd = [
        vpy, os.path.join(KIT_DIR, "preprocess.py"), "--input", input_dir,
        "--output", out, "--size", str(size), "--mode", mode,
        "--repeats", str(repeats),
    ]
    if mode == "character":
        if keep_tokens is None:
            keep_tokens = max(1, len(split_triggers(trigger)))
        cmd += ["--keep-tokens", str(keep_tokens)]
        if trigger:
            cmd += ["--trigger", trigger]
        if reg_dir:
            cmd += ["--reg-dir", reg_dir]
        if dedup:
            cmd.append("--dedup")
        if not wd14:
            cmd.append("--no-wd14")
    else:
        if trigger:
            cmd += ["--trigger", trigger]
        if (style_caption or "").strip():
            cmd += ["--caption", style_caption.strip()]
        if dedup:
            cmd.append("--dedup")
    if square_crop:
        cmd.append("--square-crop")
    if min_size:
        cmd += ["--min-size", str(min_size)]
    if blur_threshold:
        cmd += ["--blur-threshold", str(blur_threshold)]
    if report:
        cmd += ["--report", report]
    rc = run_stream(cmd, logf=logf)
    if rc != 0:
        raise RuntimeError("预处理失败，请查看上方日志")
    logf("[预处理] 完成。configs/dataset_config.toml 已自动更新。")


def start_ui(logf=print):
    kdir = get_kohya_dir()
    vpy = venv_python(kdir)
    if not os.path.isfile(vpy):
        raise RuntimeError("Kohya 尚未安装，请先点击【一键安装】")
    cmd = [vpy, "kohya_gui.py", "--server_port", "7860", "--inbrowser"]
    if " " in kdir:
        cmd.append("--noverify")
    _torchlib = os.path.join(kdir, "venv", "Lib", "site-packages", "torch", "lib")
    if amd_mode and (params.get("train_env") or "").strip():
        _torchlib = os.path.join((params.get("train_env") or "").strip(), "Lib", "site-packages", "torch", "lib")
    env = build_env([_torchlib])
    logf("[UI] 正在启动 Kohya-SS Web UI …")
    logf("[UI] 若浏览器未自动打开，请访问 http://127.0.0.1:7860")
    proc = subprocess.Popen(
        cmd, cwd=kdir, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    return proc




















def detect_system_pythons():
    """列出系统已安装的 Python 版本（Windows py launcher + 注册表 + 已知路径）。
    返回 ['3.12','3.11',...] 或 []。

    注意：每个候选都会校验其 python.exe 真实存在且能运行，避免注册表 / py launcher
    的残留记录（装失败 / 卸载残留 / 路径失效）导致误报“已安装”而跳过安装。
    同时保留多来源扫描（刚装完 Python 时 launcher 缓存可能未刷新）。"""
    vers = []
    def _add(v):
        if v and v not in vers:
            vers.append(v)
    def _runnable(p):
        """python.exe 真实存在且能跑出版本号。"""
        if not p or not os.path.isfile(p):
            return False
        try:
            s, _parts = _py_version(p)
            return bool(s)
        except Exception:
            return False
    # 1) py launcher：解析版本 + 实际路径，校验路径真实存在（排除 Astral/uv 等第三方）
    try:
        r = subprocess.run(["py", "-0p"], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            for ln in (r.stdout or "").splitlines():
                toks = ln.split()
                if not toks or not toks[0].startswith("-V:"):
                    continue
                ver = toks[0][3:]
                if not re.match(r"^\d+\.\d+", ver):
                    continue
                rest = toks[1:]
                if rest and rest[0] == "*":
                    rest = rest[1:]
                path = " ".join(rest).strip()
                if _runnable(path):
                    _add(ver)
    except Exception:
        pass
    # 2) 注册表：HKCU / HKLM 的 Software\Python\PythonCore\<ver>，读 InstallPath 校验 exe
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, r"Software\Python\PythonCore") as k:
                    i = 0
                    while True:
                        try:
                            sub = winreg.EnumKey(k, i)
                            i += 1
                        except OSError:
                            break
                        m = re.match(r"^(\d+\.\d+)", sub)
                        if not m:
                            continue
                        ver = m.group(1)
                        try:
                            with winreg.OpenKey(hive, r"Software\Python\PythonCore\%s\InstallPath" % sub) as sk:
                                p, _ = winreg.QueryValueEx(sk, "")
                                if _runnable(os.path.join(p, "python.exe")):
                                    _add(ver)
                        except OSError:
                            pass
            except OSError:
                pass
    except Exception:
        pass
    # 3) 已知安装目录（用户级 InstallAllUsers=0 默认装到 LOCALAPPDATA\Programs\Python）
    try:
        base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python")
        if os.path.isdir(base):
            for name in os.listdir(base):
                m = re.match(r"^Python(\d)(\d+)$", name)
                if m:
                    py = os.path.join(base, name, "python.exe")
                    if _runnable(py):
                        _add(f"{m.group(1)}.{m.group(2)}")
        for c in (r"C:\Python312\python.exe",
                  r"C:\Program Files\Python312\python.exe"):
            if _runnable(c):
                _add("3.12")
    except Exception:
        pass
    return vers


# Python 3.12 安装包国内镜像（内置包缺失时兜底下载）
PY312_DOWNLOAD_URLS = [
    "https://mirrors.huaweicloud.com/python/3.12.10/python-3.12.10-amd64.exe",
    "https://registry.npmmirror.com/-/binary/python/3.12.10/python-3.12.10-amd64.exe",
]


def install_python_312(logf=print):
    """安装 Python 3.12：内置安装包优先（installers/python/python-3.12*.exe），
    没有则从国内镜像下载后静默安装。返回 (ok, msg)。"""
    try:
        if "3.12" in detect_system_pythons():
            logf("[AMD] Python 3.12 已安装，跳过。")
            return True, "Python 3.12 已安装"
        import glob
        builtin = glob.glob(os.path.join(KIT_DIR, "installers", "python", "python-3.12*.exe"))
        exe = builtin[0] if builtin else None
        if not exe:
            exe = os.path.join(KIT_DIR, "installers", "python", "python-3.12.10-amd64.exe")
            try:
                os.makedirs(os.path.dirname(exe), exist_ok=True)
            except Exception:
                pass
            logf("[AMD] 未找到内置 Python 3.12 安装包，正在从国内镜像下载（约 26MB）…")
            ok = False
            for u in PY312_DOWNLOAD_URLS:
                try:
                    logf(f"[AMD] 下载：{u}")
                    _download(u, exe, logf)
                    if os.path.isfile(exe) and os.path.getsize(exe) > 10_000_000:
                        ok = True
                        break
                except Exception as e:
                    logf(f"[AMD] 镜像下载失败：{e}")
            if not ok:
                return False, "Python 3.12 安装包下载失败，请检查网络；也可手动安装（点「打开 Python 下载页」）。"
        logf("[AMD] 正在静默安装 Python 3.12（约 1 分钟）…")
        r = subprocess.run(
            [exe, "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=1",
             "Include_test=0", "Include_doc=0", "Include_tcltk=1", "Include_pip=1"],
            capture_output=True, text=True, timeout=1800)
        # 安装程序退出码 0 表示成功；此时 py launcher 可能缓存未刷新，
        # 用「检测 + 已知路径 + 注册表」综合判断，避免误报失败。
        ok312 = ("3.12" in detect_system_pythons())
        if not ok312:
            # 用户级安装默认路径
            user_py = os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Python\Python312\python.exe")
            for c in (user_py, r"C:\Python312\python.exe", r"C:\Program Files\Python312\python.exe"):
                if os.path.isfile(c):
                    s, parts = _py_version(c)
                    if s and parts[:2] == (3, 12):
                        ok312 = True
                        break
        if ok312:
            logf("[OK] Python 3.12 安装成功！")
            return True, "Python 3.12 安装成功"
        if r.returncode == 0:
            # 退出码 0 但没检测到：可能是路径非常规，引导用户确认（不再判失败）
            logf("[AMD] 安装程序已成功退出（退出码 0），但暂未在常规路径检测到 Python 3.12。")
            logf("[AMD] 请点击「重新检查」；若仍检测不到，可手动安装 Python 3.12（点「打开 Python 下载页」）。")
            return False, "安装程序已执行（退出码 0），但未检测到 Python 3.12，请点「重新检查」确认；若仍无，请手动安装。"
        return False, f"安装程序退出码 {r.returncode}，请手动安装 Python 3.12。"
    except Exception as e:
        return False, str(e)


# AMD ROCm 官方 Windows 发布版本（升级 ROCm 时只改这里）
AMD_ROC_VERSION = "7.2.1"
AMD_TORCH_VERSION = "2.9.1"
AMD_TORCHVISION_VERSION = "0.24.1"
AMD_ROC_WHEELS = [
    f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/rocm_sdk_core-{AMD_ROC_VERSION}-py3-none-win_amd64.whl",
    f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/rocm_sdk_devel-{AMD_ROC_VERSION}-py3-none-win_amd64.whl",
    f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/rocm_sdk_libraries_custom-{AMD_ROC_VERSION}-py3-none-win_amd64.whl",
    f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/rocm-{AMD_ROC_VERSION}.tar.gz",
]
AMD_TRAIN_DEPS = "transformers==4.54.1 diffusers==0.32.1 accelerate safetensors omegaconf numpy pillow av opencv-python einops sentencepiece toml voluptuous imagesize rich ftfy"


def _venv_python_ok(vpy):
    """检测 venv 是否“重度损坏”（base 解释器缺失 / 标准库 DLL 跨版本混用）。

    Windows venv 跨盘复制 / 更换系统用户 / 原 Python 被卸载 / 混入其他版本
    Python 的依赖后：
    - pyvenv.cfg 里 home 指向的 base Python 不存在 → 启动即报 "No Python at ..."；
    - venv 是 3.10 却混入 3.12 编译的扩展 → import socket/ssl 报
      "Module use of python312.dll conflicts with this version of Python"。
    这些都属于重度损坏，任何依赖检查/安装都会失败，返回 (False, detail)。
    注意：缺 pip 属于轻度问题（ensurepip 可自愈），不在这里判死，
    由 _ensure_venv_pip 单独处理。返回 (ok, detail)。"""
    if not vpy or not os.path.isfile(vpy):
        return False, "venv 的 python.exe 不存在"
    # 1) base 解释器是否还在（pyvenv.cfg 的 home 指向的 python.exe）
    try:
        cfg = os.path.join(os.path.dirname(os.path.dirname(vpy)), "pyvenv.cfg")
        if os.path.isfile(cfg):
            home = None
            try:
                with open(cfg, encoding="utf-8", errors="replace") as _f:
                    for _line in _f:
                        if _line.lower().startswith("home"):
                            home = _line.split("=", 1)[1].strip()
                            break
            except Exception:
                home = None
            if home and not os.path.isfile(os.path.join(home, "python.exe")):
                return False, "venv 指向的 Python 已不存在（No Python at ...），venv 已损坏"
    except Exception:
        pass
    # 2) 解释器 + 标准库实际可运行：DLL 跨版本混用会在 socket/ssl 导入时暴露
    code = ("import sys;"
            "import socket, ssl, ctypes, sqlite3;"
            "print('%d.%d'%sys.version_info[:2])")
    try:
        r = subprocess.run([vpy, "-c", code], capture_output=True, text=True, timeout=60)
    except Exception as e:
        return False, str(e)[:160]
    if r.returncode == 0 and re.match(r"^\d+\.\d+", (r.stdout or "").strip()):
        return True, (r.stdout or "").strip()
    err = ((r.stderr or "") + (r.stdout or "")).strip()
    if "No Python" in err:
        return False, "venv 指向的 Python 已不存在（No Python at ...），venv 已损坏"
    if "python312.dll" in err or "conflicts with this version of Python" in err or "DLL load failed" in err:
        return False, "venv 内 Python 与已装扩展版本不一致（跨版本 DLL 冲突），venv 已损坏"
    return False, (err or "venv python 启动失败")[:160]


def _ensure_venv_pip(vpy, venv_dir, logf=print, label="环境"):
    """确保 venv 里有可用的 pip：缺失时用 ensurepip 自愈。

    常见场景：venv 创建被中断 / 创建它的 Python 缺 ensurepip（如 ComfyUI 嵌入式
    python）/ 杀软清理了 pip，导致 `python -m pip` 报 "No module named pip"
    （用户 C 反馈：第二引擎安装卡死在 pip 升级）。
    返回 True=pip 可用；False=自愈失败（调用方应重建 venv）。
    """
    if not vpy or not os.path.isfile(vpy):
        return False
    try:
        r = subprocess.run([vpy, "-m", "pip", "--version"], capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            return True
    except Exception:
        pass
    logf(f"[{label}] 检测到 venv 缺少 pip（No module named pip），尝试 ensurepip 自愈…")
    try:
        r = subprocess.run([vpy, "-m", "ensurepip", "--upgrade"], capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            logf(f"[{label}] ensurepip 自愈失败：{((r.stderr or r.stdout or '未知错误').strip())[-200:]}")
            return False
        r = subprocess.run([vpy, "-m", "pip", "--version"], capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except Exception as e:
        logf(f"[{label}] ensurepip 自愈异常：{e}")
        return False


def _upgrade_pip(vpy, cwd, logf=print, label="环境"):
    """升级 pip / setuptools / wheel；主源失败自动切换阿里备用源重试。

    用户反馈过 pip 升级报 “Could not find a version that satisfies the requirement
    wheel (from versions: none)”——这是当前 pip 源（默认清华）不可达或返回空，
    不是目录占用。这里主源失败后自动切阿里源再试一次，并返回是否成功。"""
    if not vpy or not os.path.isfile(vpy):
        return False
    if run_stream([vpy, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel", "-q"],
                  cwd=cwd, logf=logf) == 0:
        return True
    logf(f"[{label}] pip 升级失败，切换备用镜像（阿里）重试…")
    return run_stream([vpy, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel", "-q",
                       "--index-url", "https://mirrors.aliyun.com/pypi/simple/",
                       "--retries", "10", "--timeout", "120"],
                      cwd=cwd, logf=logf) == 0


def _venv_torch_version(vpy):
    """读取 venv 内 torch 版本（如 2.7.1），未安装返回 None。"""
    try:
        r = subprocess.run(
            [vpy, "-c", "import importlib.metadata as md;print((md.version('torch') or '').split('+')[0])"],
            capture_output=True, text=True, timeout=60)
        return (r.stdout or "").strip() or None
    except Exception:
        return None


def _torch_torchvision_pair(torch_v):
    """torch x.y.z ↔ torchvision 0.(y+15).z（2.7.0→0.22.0、2.7.1→0.22.1、2.6.0→0.21.0）。"""
    try:
        p = (torch_v or "").split("+")[0].split(".")
        if len(p) >= 3 and p[0] == "2":
            return ".".join(p[:3]), "0.%d.%s" % (int(p[1]) + 15, p[2])
    except Exception:
        pass
    return "2.7.1", "0.22.1"


def _venv_imports_ok(vpy, mods):
    """用 find_spec 快速检查 venv 里模块是否都在（不 import，秒级）。"""
    try:
        code = ("import importlib.util;import sys;"
                "sys.exit(0 if all(importlib.util.find_spec(x) is not None for x in %r) else 1)" % list(mods))
        return subprocess.run([vpy, "-c", code], capture_output=True, text=True, timeout=60).returncode == 0
    except Exception:
        return False


def venv_python_version(venv_dir):
    """读取 venv 的 Python 版本，返回 '3.12' 或 None。"""
    try:
        py = os.path.join(venv_dir, "Scripts", "python.exe")
        if not os.path.isfile(py):
            return None
        r = subprocess.run([py, "-c", "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
                           capture_output=True, text=True, timeout=60)
        return (r.stdout or "").strip() or None
    except Exception:
        return None


def _amd_torch_wheels(venv_dir):
    """按训练环境 Python 版本生成 AMD 版 PyTorch wheel URL（cp310/cp311/cp312）。

    注意：之前 3.10 会错配成 cp312，导致 AMD 环境 torch 装不上。"""
    ver = venv_python_version(venv_dir) or "3.12"
    cp = {"3.10": "cp310", "3.11": "cp311", "3.12": "cp312"}.get(
        ".".join(ver.split(".")[:2]), "cp312")
    return [
        f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/torch-{AMD_TORCH_VERSION}%2Brocm{AMD_ROC_VERSION}-{cp}-{cp}-win_amd64.whl",
        f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/torchaudio-{AMD_TORCH_VERSION}%2Brocm{AMD_ROC_VERSION}-{cp}-{cp}-win_amd64.whl",
        f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/torchvision-{AMD_TORCHVISION_VERSION}%2Brocm{AMD_ROC_VERSION}-{cp}-{cp}-win_amd64.whl",
    ]


def _bundled_pip_wheels():
    """内置离线 wheel（pillow/numpy，供预处理自愈离线安装，绕开网络不稳）。"""
    d = os.path.join(KIT_DIR, "installers", "python_libs")
    wheels = []
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.lower().endswith((".whl", ".tar.gz")):
                wheels.append(os.path.join(d, f))
    return wheels


def _wheels_for_python(wheels, vpy):
    """按 venv Python 版本过滤内置 wheel：cpXXX 标签不匹配的跳过，
    避免"3.10 venv 装 cp312 wheel 报 not supported"（numpy/torch 装不上 → 训练只有 CPU 版 torch）。

    纯 Python wheel（py3-none-any）与 sdist（.tar.gz）保留；无法判断标签的保留（pip 会自行拒绝）。"""
    if not wheels:
        return wheels
    ver = None
    try:
        r = subprocess.run([vpy, "-c", "import sys;print('%d%d'%sys.version_info[:2])"],
                           capture_output=True, text=True, timeout=60)
        ver = (r.stdout or "").strip()
    except Exception:
        ver = None
    if not ver:
        return wheels
    out = []
    for w in wheels:
        name = os.path.basename(str(w)).lower()
        if name.endswith(".tar.gz") or "-py3-none-any" in name or "-py2.py3-none-any" in name:
            out.append(w)
            continue
        # wheel 文件名带 cpXXX 标签：必须与 venv 一致，否则 pip 会拒绝
        if re.search(r"-cp\d+[0-9]-", name):
            if ("-cp%s-" % ver) in name.replace("+", "-"):
                out.append(w)
        else:
            out.append(w)
    return out


def _wheel_valid(path):
    """校验下载的 wheel/压缩包完整性（防止断点残留或下载损坏的残片被当成可用）。

    之前只用 zipfile.is_zipfile() 查文件头魔数，会放行“头部完好但内部损坏”的文件
    （AMD 用户反馈：rocm_sdk_devel 下载损坏，大小与官方不一致，pip 装时报
    BadZipFile）。这里升级为全量校验：zip 遍历所有条目做 CRC 校验（testzip），
    tar.gz 读取中央目录，损坏即判 False，触发重新下载。"""
    try:
        low = path.lower()
        if low.endswith((".whl", ".zip")):
            import zipfile
            if not zipfile.is_zipfile(path):
                return False
            with zipfile.ZipFile(path) as z:
                if z.testzip() is not None:
                    return False
            return True
        if low.endswith((".tar.gz", ".tgz")):
            import tarfile
            with tarfile.open(path, "r:gz") as t:
                # 读取中央目录：文件损坏（截断/追加垃圾字节）会在此抛错
                t.getmembers()
            return True
        return os.path.getsize(path) > 0
    except Exception:
        return False


def _ensure_kohya_deps(vpy, kdir, logf=print):
    """确保训练环境具备工具运行时需要的依赖，缺失自动补装（内置 wheel + 国内镜像 + 重试）。

    覆盖：PIL/numpy（预处理）、transformers/huggingface_hub（分词器缓存 + Anima/FLUX 组件下载）、
    toml/voluptuous/safetensors/diffusers/accelerate/omegaconf（sd-scripts 训练）。
    返回 True=就绪；False=补装失败（网络问题）。
    """
    # venv 健康检查：venv 指向的 base Python 不存在时（迁移/换用户/卸载），
    # 一切依赖检查与安装都会失败，直接给出明确指引，而不是误导性的"网络不稳"。
    _vok, _vdetail = _venv_python_ok(vpy)
    if not _vok:
        raise RuntimeError(
            "训练环境已损坏（%s）。\n"
            "常见原因：数据目录迁移到新盘/更换系统用户后，venv 指向的 Python 已不存在。\n"
            "请重跑【② 安装训练内核】自动重建环境（旧 venv 会保留并重新安装依赖）。" % _vdetail)
    # 用 find_spec 只查包是否存在（不 import，秒级；import transformers 太重会拖慢每次训练启动）
    # sd-scripts 训练需要的依赖（不含 NVIDIA 专属的 bitsandbytes/tensorflow/onnxruntime-gpu）
    # 只检查「模块加载时必需」的核心依赖；lion-pytorch/schedulefree/prodigy 等可选优化器
    # 不查（工具只用 AdamW/AdamW8bit，装全量时顺带补上即可）
    code = ("import importlib.util;m=['PIL','numpy','torch','torchvision','transformers','huggingface_hub','toml',"
            "'voluptuous','safetensors','diffusers','accelerate','omegaconf','imagesize','rich',"
            "'ftfy','einops','cv2','sentencepiece','google.protobuf'];"
            "import sys;sys.exit(0 if all(importlib.util.find_spec(x) is not None for x in m) else 1)")
    need_install = True
    try:
        r = subprocess.run([vpy, "-c", code], capture_output=True, text=True, timeout=60)
        need_install = r.returncode != 0
    except Exception:
        need_install = True
    if not need_install:
        # 版本兼容：kohya sd-scripts 需要 transformers 4.x / diffusers 0.32.x；
        # 5.x / 0.39 改了 CLIP 文本编码器结构，加载 SD1.5 底模会报 state_dict key 不匹配
        vcode = ("from importlib.metadata import version;import sys;"
                 "t=version('transformers').split('.');d=version('diffusers').split('.');"
                 "s=version('scipy').split('.');"
                 "scipy_ok=int(s[0])>1 or (int(s[0])==1 and int(s[1])>=13);"
                 "sys.exit(0 if t[0]=='4' and d[0]=='0' and d[1]=='32' and scipy_ok else 1)")
        try:
            rv = subprocess.run([vpy, "-c", vcode], capture_output=True, text=True, timeout=60)
            need_install = rv.returncode != 0
            if need_install:
                logf("[环境] transformers/diffusers 版本不兼容 kohya（需要 transformers 4.54 / diffusers 0.32），正在校正版本…")
        except Exception:
            need_install = True
    if not need_install:
        return True
    logf("[环境] 训练环境需要补装/校正依赖（PIL/numpy/transformers/huggingface_hub/toml 等），正在处理…")
    subprocess.run([vpy, "-m", "pip", "config", "set", "global.index-url",
                    "https://pypi.tuna.tsinghua.edu.cn/simple"], capture_output=True, timeout=60)
    env = build_env()
    _all_wheels = _bundled_pip_wheels()
    wheels = _wheels_for_python(_all_wheels, vpy)
    if _all_wheels and not wheels:
        logf("[环境] 内置离线 wheel 与 venv Python 版本不匹配（venv 非 3.12），改用镜像安装对应版本…")

    if wheels:
        if run_stream([vpy, "-m", "pip", "install", "--no-input", "--no-index"] + wheels,
                      cwd=kdir, env=env, logf=logf) == 0:
            _r = subprocess.run([vpy, "-c",
                                 "import importlib.util; import sys; sys.exit(0 if importlib.util.find_spec('PIL') and importlib.util.find_spec('numpy') else 1)"],
                                capture_output=True, text=True, timeout=60)
            if _r.returncode != 0:
                logf("[环境] pillow/numpy 离线安装异常，改走镜像…")
                wheels = []
    # sd-scripts 训练完整依赖（AMD 环境用，不含 bitsandbytes 等 NVIDIA 专属包）
    # transformers/diffusers 钉 kohya 兼容版本，防止装到 5.x/0.39 导致 CLIP 加载失败
    pkgs = ["transformers==4.54.1", "huggingface-hub", "toml", "voluptuous", "safetensors",
            "diffusers==0.32.1", "accelerate", "omegaconf", "imagesize", "rich", "ftfy",
            "lion-pytorch", "schedulefree", "pytorch-optimizer",
            "prodigy-plus-schedule-free", "prodigyopt", "einops", "opencv-python", "sentencepiece",
            "scipy", "protobuf"]   # scipy 太旧(<1.13)与 numpy2 冲突会崩 transformers；protobuf 为 tokenizer 加载必需
    ok = False
    for _round in range(2):
        for _idx in ("https://pypi.tuna.tsinghua.edu.cn/simple", "https://mirrors.aliyun.com/pypi/simple/"):
            if run_stream([vpy, "-m", "pip", "install", "--no-input", "--retries", "10", "--timeout", "120",
                           "--index-url", _idx] + pkgs, cwd=kdir, env=env, logf=logf) == 0:
                ok = True
                break
            logf("[环境] 当前镜像下载失败，切换备用镜像重试…")
        if ok:
            break
        logf("[环境] 补装失败（多为网络波动/下载中断），自动重试第 %d 轮…" % (_round + 2))
    if not ok:
        # 区分“真缺模块”和“只是版本升级失败”：核心模块齐全时，网络失败
        # 不再一刀切卡死训练（用户A 反馈：scipy 1.11 需升级，下载 IncompleteRead 中断，
        # 挂不挂梯子都过不去，训练被拦死）。降级为警告继续，让用户有机会尝试。
        if _venv_imports_ok(vpy, ("PIL", "numpy", "transformers", "huggingface_hub", "toml",
                                  "voluptuous", "safetensors", "diffusers", "accelerate",
                                  "omegaconf", "imagesize", "rich", "ftfy", "einops", "cv2",
                                  "sentencepiece", "google.protobuf")):
            logf("[环境] ⚠ 依赖升级/补装因网络失败，但核心模块已齐全，将尝试继续训练。")
            logf("[环境] 若训练中报 scipy/numpy 相关错误，请网络稳定后重跑【② 安装训练内核】。")
        else:
            return False
    # torch/torchvision 配对补装：安装中断常见“有 torch 没 torchvision”，
    # 缺 torchvision 会在训练 import 时直接报 ModuleNotFoundError（用户 A 反馈）。
    # torchvision 是 CUDA 大轮子，不走 pypi 镜像，按 torch 版本走 _preinstall_torch。
    if not _venv_imports_ok(vpy, ("torch", "torchvision")):
        if detect_gpu_vendor() == "amd":
            raise RuntimeError("AMD 训练环境缺少 torchvision，请重跑 AMD 环境引导重新安装 ROCm torchvision")
        _tv = _venv_torch_version(vpy)
        if not _tv:
            raise RuntimeError("训练环境缺少 PyTorch，请重跑【② 安装训练内核】自动安装 cu128 版 PyTorch")
        _tvv, _tvv2 = _torch_torchvision_pair(_tv)
        logf(f"[环境] 检测到 torch {_tvv} 缺少配套 torchvision，自动补装 torchvision {_tvv2}+cu128 …")
        try:
            _preinstall_torch(vpy, kdir, logf, torch_ver=_tvv, tv_ver=_tvv2, label="Kohya", force=False)
        except Exception as e:
            raise RuntimeError("自动补装 torchvision 失败：%s\n请重跑【② 安装训练内核】" % e)
        if not _venv_imports_ok(vpy, ("torch", "torchvision")):
            raise RuntimeError("torchvision 补装后仍不可用，请重跑【② 安装训练内核】")
    logf("[环境] 训练环境运行时依赖补装完成")
    return True


def _http_total_size(url, timeout=20):
    """尽力获取下载文件总大小（字节）；失败返回 None（不影响下载）。"""
    try:
        import urllib.request
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            cl = r.headers.get("Content-Length")
            if cl:
                return int(cl)
    except Exception:
        pass
    return None


def _download_with_resume(url, dest, logf=print, progress_cb=None):
    """用 curl 断点续传下载大文件（repo.radeon.com 网络不稳时关键，断了可续传）。

    返回 True=成功。优先 curl（Windows 自带，支持 -C - 续传 + 重试）；否则 urllib 分段下载。
    progress_cb(size_bytes, total_bytes_or_None) 可选：下载期间周期性回调已下载大小，
    供界面显示进度（curl 是 -sS 静默模式，不回调的话界面上完全看不到进度）。
    """
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    curl = shutil.which("curl")
    total = _http_total_size(url)
    stop_mon = threading.Event()
    if progress_cb is not None:
        def _monitor():
            last = -1
            while not stop_mon.is_set():
                try:
                    size = os.path.getsize(dest) if os.path.isfile(dest) else 0
                except Exception:
                    size = 0
                if size != last:
                    last = size
                    try:
                        progress_cb(size, total)
                    except Exception:
                        pass
                stop_mon.wait(1)
        threading.Thread(target=_monitor, daemon=True).start()
    try:
        if curl and os.path.isfile(curl):
            cmd = [curl, "-sS", "-L", "-C", "-", "--retry", "5", "--retry-delay", "5", "--retry-all-errors",
                   "--connect-timeout", "20", "--max-time", "10800", "-o", dest, url]
            _px = system_proxy()
            if _px:
                cmd = [curl, "-sS", "-L", "-C", "-", "--retry", "5", "--retry-delay", "5", "--retry-all-errors",
                       "--connect-timeout", "20", "--max-time", "10800", "--proxy", _px, "-o", dest, url]
            return run_stream(cmd, env=build_env(), logf=logf) == 0
        # urllib 兜底：Range 断点续传
        import urllib.request
        tmp = dest + ".part"
        exist = os.path.getsize(tmp) if os.path.isfile(tmp) else 0
        try:
            req = urllib.request.Request(url, headers={"Range": "bytes=%d-" % exist} if exist else {})
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "ab") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    if progress_cb is not None:
                        try:
                            progress_cb(exist + os.path.getsize(tmp), total)
                        except Exception:
                            pass
            os.replace(tmp, dest)
            return True
        except Exception as e:
            logf(f"[下载] 中断（{e}），已保留 {tmp}，重试时自动续传")
            return False
    finally:
        stop_mon.set()


def run_pip_in_venv(venv_dir, args, logf=print):
    """在训练环境（venv）里运行 pip install。返回退出码；可被停止按钮中断。"""
    py = os.path.join(venv_dir, "Scripts", "python.exe")
    if not os.path.isfile(py):
        raise RuntimeError(f"训练环境无效，找不到 {py}，请先创建训练环境。")
    cmd = [py, "-m", "pip", "install", "--no-cache-dir", "--retries", "10", "--timeout", "120"] + args
    env = build_env()
    env.setdefault("PIP_NO_INPUT", "1")
    # 网络被掐断时走系统代理（朋友机器实测直连 pip 镜像被稳定掐断）
    _px = system_proxy()
    if _px:
        env.setdefault("HTTP_PROXY", _px)
        env.setdefault("HTTPS_PROXY", _px)
    return run_stream(cmd, env=env, logf=logf)


def install_amd_rocm(venv_dir, logf=print):
    """自动安装 AMD ROCm 运行库（阶段 1/3，约 1~2GB，视网速 10~60 分钟）。

    先断点续传下载 wheel 到本地缓存（repo.radeon.com 网络不稳，避免半途失败），再本地安装。
    """
    logf("[AMD] 阶段 1/3：安装 AMD ROCm 运行库（文件较大，支持断点续传，可随时点停止）…")
    cache = os.path.join(data_dir(), "installer_cache", "amd_rocm")
    local = []
    for _u in AMD_ROC_WHEELS:
        _fn = os.path.basename(_u)
        _dst = os.path.join(cache, _fn)
        if not (os.path.isfile(_dst) and os.path.getsize(_dst) > 1024 * 1024 and _wheel_valid(_dst)):
            if os.path.isfile(_dst):
                logf(f"[AMD] {_fn} 缓存文件不完整，重新下载…")
                try:
                    os.remove(_dst)
                except Exception:
                    pass
            logf(f"[AMD] 下载 {_fn}（可断点续传）…")
            if not _download_with_resume(_u, _dst, logf):
                raise RuntimeError(f"ROCm 组件下载失败：{_fn}（网络不稳，请重试，已支持断点续传）")
        local.append(_dst)
    logf("[AMD] ROCm 组件下载完成，开始安装 …")
    rc = run_pip_in_venv(venv_dir, local, logf)
    if rc != 0:
        raise RuntimeError(f"ROCm 运行库安装失败（退出码 {rc}），请向上查看日志。")
    logf("[OK] AMD ROCm 运行库安装完成")
    return True


def install_amd_torch(venv_dir, logf=print):
    """自动安装 AMD 版 PyTorch（阶段 2/3，约 2~3GB，支持断点续传）。"""
    logf("[AMD] 阶段 2/3：安装 AMD 版 PyTorch（文件较大，支持断点续传，请耐心等待）…")
    cache = os.path.join(data_dir(), "installer_cache", "amd_torch")
    local = []
    for _u in _amd_torch_wheels(venv_dir):
        _fn = os.path.basename(_u)
        _dst = os.path.join(cache, _fn)
        if not (os.path.isfile(_dst) and os.path.getsize(_dst) > 1024 * 1024 and _wheel_valid(_dst)):
            if os.path.isfile(_dst):
                logf(f"[AMD] {_fn} 缓存文件不完整，重新下载…")
                try:
                    os.remove(_dst)
                except Exception:
                    pass
            logf(f"[AMD] 下载 {_fn}（可断点续传）…")
            if not _download_with_resume(_u, _dst, logf):
                raise RuntimeError(f"PyTorch 组件下载失败：{_fn}（网络不稳，请重试，已支持断点续传）")
        local.append(_dst)
    logf("[AMD] PyTorch 组件下载完成，开始安装 …")
    rc = run_pip_in_venv(venv_dir, local, logf)
    if rc != 0:
        raise RuntimeError(f"AMD 版 PyTorch 安装失败（退出码 {rc}），请向上查看日志。")
    logf("[OK] AMD 版 PyTorch 安装完成")
    return True


def install_amd_deps(venv_dir, logf=print):
    """自动安装训练依赖（阶段 3/3）。"""
    logf("[AMD] 阶段 3/3：安装训练依赖（transformers/diffusers 等）…")
    rc = run_pip_in_venv(venv_dir, AMD_TRAIN_DEPS.split(), logf)
    if rc != 0:
        raise RuntimeError(f"训练依赖安装失败（退出码 {rc}），请向上查看日志。")
    logf("[OK] 训练依赖安装完成")
    return True


def verify_amd_torch(venv_dir):
    """验证训练环境里的 torch 是否可用。返回 (ok, torch_ver, cuda_avail)。"""
    try:
        py = os.path.join(venv_dir, "Scripts", "python.exe")
        if not os.path.isfile(py):
            return False, "?", False
        r = subprocess.run(
            [py, "-c", "import torch;print(torch.__version__);print(torch.cuda.is_available())"],
            capture_output=True, text=True, timeout=300)
        lines = (r.stdout or "").strip().splitlines()
        ver = lines[0] if lines else "?"
        avail = "True" in "\n".join(lines)
        return r.returncode == 0 and avail, ver, avail
    except Exception:
        return False, "?", False


def create_python_venv(py_ver, target, logf=print):
    """用指定 Python 版本创建虚拟环境（py -<ver> -m venv <target>）。返回 (ok, msg)。"""
    try:
        if os.path.isfile(os.path.join(target, "Scripts", "python.exe")):
            return True, "环境已存在，跳过创建"
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        r = subprocess.run(["py", "-" + py_ver, "-m", "venv", target],
                           capture_output=True, text=True, timeout=600)
        if r.returncode == 0 and os.path.isfile(os.path.join(target, "Scripts", "python.exe")):
            logf(f"[AMD] 训练环境创建成功：{target}")
            return True, "创建成功"
        return False, (r.stderr or r.stdout or "未知错误").strip()[-400:]
    except Exception as e:
        return False, str(e)


def amd_env_status(vpy=None):
    """AMD 兼容模式环境状态。返回 (ok, backend, detail)。"""
    if not vpy or not os.path.isfile(vpy):
        return False, None, "未找到 kohya 训练环境（请先完成【一键安装】）。"
    bk = detect_torch_backend(vpy)
    if bk == "rocm":
        return True, bk, "检测到 ROCm 版 PyTorch，可直接训练（实验性）。"
    if bk == "zluda":
        return True, bk, "检测到 ZLUDA 生效（CUDA 版 PyTorch 运行在 AMD 卡上），可直接训练（实验性，更不稳定）。"
    if bk == "cuda":
        return False, bk, "当前 torch 是 NVIDIA CUDA 版，AMD 卡上无法使用，需要安装 ROCm 版 PyTorch 或 ZLUDA。"
    if bk == "cpu":
        return False, bk, "torch 可用但只有 CPU 后端，请安装 ROCm 版 PyTorch 或 ZLUDA。"
    return False, None, "无法读取训练环境 torch 状态。"


def decide_gradient_checkpointing(gc_choice, vram_gb):
    """梯度检查点开关：自动 = 显存未知或 <16GB 时开启；否则跟随手动选择。"""
    if gc_choice == "开启":
        return True
    if gc_choice == "关闭":
        return False
    return (vram_gb is None) or (vram_gb < 16.0)




def _sync_trigger_to_labels(train_dir, trigger, logf=print):
    """训练前把当前 trigger 同步到数据集所有 txt 第一行（人物模式）。

    背景：用户可能在预处理后修改了 trigger，但标签 txt 不会自动跟着变，
    导致 LoRA 没学到当前 trigger，生图时"召唤不出来"。

    关键点：kohya 用 keep_tokens 保护的是「标签第一行开头的 token」，
    所以必须保证 trigger 出现在第一行最前面。不能按"整行里出现过该词"判断
    （例如角色本名 "Yanami Anna" 里含 YANAMI，但 YANAMI 不在开头=没被保护）。
    这里只认「第一行以 trigger 开头」，否则把 trigger 插到最前。
    返回本次实际插入（修改）的 txt 数量。
    """
    trigger = (trigger or "").strip()
    if not trigger:
        return 0
    if not os.path.isdir(train_dir):
        return 0
    n = 0
    for root, _dirs, files in os.walk(train_dir):
        for fn in files:
            if not fn.lower().endswith(".txt"):
                continue
            fp = os.path.join(root, fn)
            try:
                with open(fp, "r", encoding="utf-8-sig") as f:
                    cur = f.read()
            except Exception:
                continue
            text = cur.strip("\ufeff").strip("\r\n").strip()
            if not text:
                continue
            first = text.splitlines()[0].strip()
            # 已以 trigger 开头（如 "YANAMI, 1girl" 或 "YANAMI"）-> 跳过
            if re.match(re.escape(trigger) + r"(\s*[,，]|\s*$)", first, re.IGNORECASE):
                continue
            # 否则插入到最前：trigger, 原内容
            new = trigger + ", " + text
            try:
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(new)
                n += 1
            except Exception:
                pass
    return n


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")


def count_images_in(folder):
    """统计 folder 根目录下的图片数量（不递归子目录）。"""
    if not os.path.isdir(folder):
        return 0
    return sum(1 for f in os.listdir(folder)
               if f.lower().endswith(IMAGE_EXTS))


def count_images(folder):
    """递归统计数据集目录下的图片总数（支持 repeats_名称 子目录结构）。"""
    if not os.path.isdir(folder):
        return 0
    n = 0
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        n += sum(1 for f in files if f.lower().endswith(IMAGE_EXTS))
    return n


def scan_dataset_subsets(train_dir, fallback_repeats=1):
    """扫描数据集目录，支持秋叶式「repeats_概念名」子目录结构。

    返回 [(image_dir, num_repeats, img_count), ...]：
    - 直接放在根目录的图片：一组，repeats=fallback_repeats（对应高级面板的 repeats）
    - 名为 <N>_<名称> 的子目录：各自一组，repeats=N（每个子目录独立重复次数）
    训练时按这些子集生成 kohya dataset_config，并据此计算总步数。
    """
    subs = []
    flat = count_images_in(train_dir)
    if flat > 0:
        subs.append((train_dir, max(1, int(fallback_repeats)), flat))
    if os.path.isdir(train_dir):
        for name in sorted(os.listdir(train_dir)):
            p = os.path.join(train_dir, name)
            if not os.path.isdir(p) or name.startswith("."):
                continue
            m = re.match(r"^(\d+)[_\-](.+)", name)
            n = int(m.group(1)) if m else None
            cnt = count_images_in(p)
            if cnt > 0:
                subs.append((p, n if n and n > 0 else max(1, int(fallback_repeats)), cnt))
    return subs


def dataset_per_epoch_steps(train_dir, fallback_repeats=1, batch_size=1):
    """计算每 epoch 的训练步数（含 repeats 与 batch），并返回子集列表。"""
    subs = scan_dataset_subsets(train_dir, fallback_repeats)
    weighted = sum(n * c for _, n, c in subs)
    return weighted // max(1, batch_size), subs


# ============================================================
# 标签编辑器辅助函数（浏览 / 批量修改 / 置顶 / 统计 / 整理数据集）
# 供 kohya_gui.py 的「标签编辑器」窗口调用，也便于命令行/脚本复用。
# ============================================================

def list_dataset_images(train_dir):
    """递归列出数据集内全部图片及其同名 txt 标签。

    返回 [{rel, img, txt, caption}]，按路径排序；rel 为空串表示根目录。
    """
    out = []
    if not os.path.isdir(train_dir):
        return out
    for root, dirs, files in os.walk(train_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in sorted(files):
            if not f.lower().endswith(IMAGE_EXTS):
                continue
            img = os.path.join(root, f)
            stem = os.path.splitext(f)[0]
            txt = os.path.join(root, stem + ".txt")
            cap = ""
            if os.path.isfile(txt):
                try:
                    with open(txt, "r", encoding="utf-8-sig") as fh:
                        cap = fh.read()
                except Exception:
                    cap = ""
            out.append({
                "rel": os.path.relpath(root, train_dir),
                "img": img,
                "txt": txt,
                "caption": cap,
            })
    return out


def save_caption(txt_path, text):
    """保存单张图片的标签（UTF-8，自动去掉首尾空白，保留换行）。"""
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write((text or "").strip() + "\n")


def _split_tags(caption):
    """把逗号分隔的标签拆成去空白列表（兼容中英文逗号）。"""
    return [p.strip() for p in re.split(r"[,，]", caption or "") if p.strip()]


def batch_remove_tags(train_dir, tags, logf=print):
    """从全部标签中删除指定标签（支持逗号分隔多个；精确匹配、忽略大小写）。

    返回 (处理文件数, 删除标签个数)。
    """
    tag_list = [t.strip() for t in re.split(r"[,，]", tags or "") if t.strip()]
    if not tag_list:
        return 0, 0
    low_tags = {t.lower() for t in tag_list}
    files, removed = 0, 0
    for item in list_dataset_images(train_dir):
        txt = item["txt"]
        if not os.path.isfile(txt):
            continue
        parts = _split_tags(item["caption"])
        kept = [p for p in parts if p.lower() not in low_tags]
        if len(kept) != len(parts):
            try:
                save_caption(txt, ", ".join(kept))
                files += 1
                removed += len(parts) - len(kept)
            except Exception as e:
                logf(f"[标签] 写入失败 {txt}: {e}")
    return files, removed


def batch_replace_tags(train_dir, find, replace, logf=print):
    """把全部标签中「精确等于 find」的标签替换为 replace（不替换子串，避免误伤）。

    返回处理文件数。
    """
    find = (find or "").strip()
    if not find:
        return 0
    replace = (replace or "").strip()
    files = 0
    for item in list_dataset_images(train_dir):
        txt = item["txt"]
        if not os.path.isfile(txt):
            continue
        parts = _split_tags(item["caption"])
        new_parts = [replace if p == find else p for p in parts]
        if new_parts != parts:
            try:
                save_caption(txt, ", ".join(new_parts))
                files += 1
            except Exception as e:
                logf(f"[标签] 写入失败 {txt}: {e}")
    return files


def pin_trigger_to_labels(train_dir, trigger, logf=print):
    """把 trigger 插到数据集所有标签第一行（已以 trigger 开头则跳过）。

    返回实际修改的 txt 数量。trigger 为空返回 0。
    """
    return _sync_trigger_to_labels(train_dir, trigger, logf)


def tag_frequency(train_dir, top_n=200):
    """统计全部标签出现频率，返回 [(标签, 次数)] 按次数倒序。"""
    from collections import Counter
    cnt = Counter()
    for item in list_dataset_images(train_dir):
        for p in _split_tags(item["caption"]):
            cnt[p] += 1
    return cnt.most_common(top_n)


def organize_dataset_repeats(train_dir, repeats, name):
    """把数据集根目录平铺的图片+标签整理成 <repeats>_<名称> 子目录（秋叶式结构）。

    只移动根目录直接放置的文件（图片/同名 txt/npz 缓存）；已存在的子目录不动。
    返回 (移动文件数, 目标目录)。
    """
    name = re.sub(r'[\\/:*?"<>|\r\n]', "_", (name or "dataset").strip()) or "dataset"
    repeats = max(1, int(repeats or 1))
    target = os.path.join(train_dir, f"{repeats}_{name}")
    os.makedirs(target, exist_ok=True)
    moved = 0
    for f in list(os.listdir(train_dir)):
        fp = os.path.join(train_dir, f)
        if not os.path.isfile(fp):
            continue
        low = f.lower()
        if low.endswith(IMAGE_EXTS) or low.endswith(".txt") or low.endswith(".npz"):
            try:
                shutil.move(fp, os.path.join(target, f))
                moved += 1
            except Exception:
                pass
    return moved, target


def find_latest_state(output_dir, output_name):
    """在输出目录找最新的 kohya 训练状态目录（断点续训用）。

    只找带 step 的目录（如 character_lora-step00000200-state），这些才是中断点；
    纯 '<name>-state' 是训练正常完成时 kohya 保存的最终状态，不代表中断，
    不用于续训提示（否则每次跑完都会误问要不要续训）。"""
    if not os.path.isdir(output_dir):
        return None
    cands = []
    search_dirs = [output_dir, os.path.join(output_dir, "snapshots")]
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            p = os.path.join(d, f)
            if not os.path.isdir(p) or not f.startswith(output_name):
                continue
            if "-step" in f and f.endswith("-state"):
                cands.append(p)
    if not cands:
        return None
    # 按 step 号取最大（比 mtime 可靠）
    def _step_no(p):
        m = re.search(r"-step(\d+)-state", os.path.basename(p))
        return int(m.group(1)) if m else -1
    return max(cands, key=_step_no)


def auto_training_setup(vram_gb, base_type):
    """根据显存智能适配 (batch_size, use_xformers, gc_suggest)。"""
    if base_type in ("flux", "anima"):
        # 新架构统一：batch=1、sdpa、开梯度检查点省显存
        return 1, False, True
    if base_type == "sdxl":
        if vram_gb is None or vram_gb < 16:
            return 1, True, True
        if vram_gb < 24:
            return 1, False, True
        return 2, False, False
    # SD1.5
    if vram_gb is None or vram_gb < 8:
        return 1, True, True
    if vram_gb < 12:
        return 1, True, False
    return 2, False, False


def make_global_caption_dataset(train_dir, mode, global_pos):
    """生成带全局正向提示词的临时数据集（硬链接图片 + 新 caption），不修改原 txt。

    支持 repeats_名称 子目录结构：子目录会原样复制（硬链接），repeats 语义保持不变。
    返回临时目录；global_pos 为空返回 None（直接用原数据集）。
    """
    global_pos = (global_pos or "").strip()
    if not global_pos:
        return None
    tmp = os.path.join(data_dir(), "dataset", "_global_cache", mode)
    if os.path.isdir(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    n = 0
    for root, dirs, files in os.walk(train_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        rel = os.path.relpath(root, train_dir)
        dst_dir = tmp if rel == "." else os.path.join(tmp, rel)
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except Exception:
            continue
        for f in files:
            if not f.lower().endswith(IMAGE_EXTS):
                continue
            stem = os.path.splitext(f)[0]
            src_img = os.path.join(root, f)
            dst_img = os.path.join(dst_dir, f)
            try:
                os.link(src_img, dst_img)  # 硬链接省空间
            except OSError:
                shutil.copy2(src_img, dst_img)
            cap = ""
            txt = os.path.join(root, stem + ".txt")
            if os.path.isfile(txt):
                try:
                    with open(txt, "r", encoding="utf-8") as fh:
                        cap = fh.read().strip()
                except Exception:
                    cap = ""
            with open(os.path.join(dst_dir, stem + ".txt"), "w", encoding="utf-8") as fh:
                fh.write((global_pos + (", " + cap if cap else "")))
            n += 1
    if n == 0:
        shutil.rmtree(tmp, ignore_errors=True)
        return None
    return tmp


def cap_epochs_by_steps(per_epoch_steps, batch, epochs, max_steps=MAX_AUTO_STEPS):
    """按总步数自动约束 epoch，防止过拟合；返回 (epochs, total_steps)。

    per_epoch_steps：每个 epoch 的步数（已计入 repeats 与 batch_size）。
    """
    per_epoch_steps = max(1, int(per_epoch_steps))
    total = per_epoch_steps * max(1, epochs)
    if total <= max_steps:
        return epochs, total
    new_epochs = max(1, int(max_steps / per_epoch_steps))
    return new_epochs, per_epoch_steps * new_epochs


def write_params_report(mode, params, output_name, extra=None, out_dir=None):
    """训练结束后生成完整参数报告 txt。"""
    out_dir = out_dir or data_sub("output")
    path = os.path.join(out_dir, output_name + "_参数报告.txt")
    base = params.get("base_type", "sd15")
    lines = [
        "【LoRA 训练参数报告】",
        f"生成时间      : {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"训练模式      : {MODE_LABELS.get(mode, mode)}",
        f"底模类型      : {BASE_TYPE_LABELS.get(base, base)}",
        f"底模文件      : {params.get('base_model') or '（未记录）'}",
        f"训练分辨率    : {RESOLUTIONS.get(base, 512)}px",
        f"rank / alpha  : {params.get('rank')} / {params.get('alpha')}",
        f"学习率        : {params.get('unet_lr')}",
        f"文本编码器学习率: {params.get('te_lr')}",
        f"repeats       : {params.get('repeats')}",
        f"最大 epoch    : {params.get('max_epochs')}",
        f"训练目标      : {'UNet + 文本编码器' if params.get('train_text_encoder', True) else '仅 UNet'}",
        f"batch_size    : {params.get('batch_size', 1)}",
        f"梯度检查点    : {params.get('gc')}",
        f"附加全局正向提示词: {params.get('global_pos') or '（无）'}",
        f"附加全局负向提示词: {params.get('global_neg') or '（无）'}",
    ]
    if mode == "character":
        lines += [
            f"Trigger 触发词: {params.get('trigger') or '（未填写）'}",
            f"正则数据集    : {params.get('reg_dir') or '（未使用）'}",
        ]
    if extra:
        lines.append("")
        lines.append("运行备注：")
        lines.extend("  " + str(x) for x in extra)
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines) + "\n")
    return path


def write_usage_template(mode, params, output_name, out_dir=None):
    """训练完成后生成 txt 使用模板（画风=画风提示词；人物=带 trigger/全局提示词示例）。

    模板里的「你的训练标签示例」会读取当前项目训练集里真实写入的 caption，
    每个用户的模板对应各自实际的标签，而不是固定示例。
    """
    out_dir = out_dir or data_sub("output")
    path = os.path.join(out_dir, output_name + "_使用模板.txt")
    base = params.get("base_type", "sd15")
    reso = RESOLUTIONS.get(base, 512)
    gpos = (params.get("global_pos") or "").strip()
    neg = (params.get("global_neg") or "").strip() or (
        "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, "
        "fewer digits, cropped, worst quality, low quality, jpeg artifacts, signature, "
        "watermark, username, blurry, bad quality")

    def _sample_caption():
        """读取当前项目训练集里第一张真实 caption（用于模板示例）。"""
        try:
            d = dataset_train_dir(mode, params.get("project"))
            if os.path.isdir(d):
                for fn in sorted(os.listdir(d)):
                    if fn.lower().endswith(".txt"):
                        c = io.open(os.path.join(d, fn), encoding="utf-8").read().strip()
                        if c:
                            return c
        except Exception:
            pass
        return None

    cap = _sample_caption()

    if mode == "character":
        triggers = split_triggers(params.get("trigger"))
        trig_line = ", ".join(triggers) if triggers else "<你的触发词>"
        reg = "已启用" if params.get("reg_dir") else "未启用"
        pos_example = ((gpos + ", ") if gpos else "") + ((trig_line + ", ") if triggers else "") + "1girl, solo, <其他标签…>"
        text = (
            "【人物角色 LoRA 使用模板】\n"
            f"模型文件：{output_name}.safetensors\n"
            f"Trigger 触发词：{trig_line}\n"
            f"正则数据集：{reg}\n"
            f"训练分辨率：{reso}px\n\n"
            "使用建议：\n"
            f"1. 正向提示词以触发词开头：{pos_example}\n"
            + (f"   你的训练标签示例：{cap}\n" if cap else "")
            + "2. 推荐 LoRA 权重 0.6 ~ 0.9（按底模微调）。\n"
            f"3. 负面提示词建议：{neg}\n"
            "4. 想强调角色时提高权重，想自然融入时用 0.6 左右。\n"
        )
    else:
        _trig2 = ", ".join(split_triggers(params.get("trigger")))
        if _trig2:
            example = cap if cap else (
                _trig2 + ", anime cel-shading, clean thin black outlines, flat color, "
                "simple soft cel shading, tv anime screenshot, limited color palette")
            text = (
                "【画风 LoRA 使用模板】\n"
                f"模型文件：{output_name}.safetensors\n"
                f"Trigger 触发词：{_trig2}\n"
                f"训练分辨率：{reso}px\n\n"
                "使用建议：\n"
                "1. 推荐 LoRA 权重 0.5 ~ 0.7。\n"
                "2. 正向提示词以触发词开头，并**带上训练时的画风标签**一起输入：\n"
                f"   你的训练标签示例：{example}\n"
                f"   出图时直接复制这段标签 + 你想画的内容，例如：{example}, 1girl, <动作/场景>\n"
                "3. ⚠ 单独输入一个触发词召唤效果较弱（画风信息分散在标签里），建议「触发词 + 画风标签」一起用。\n"
                f"4. 负面提示词建议：{neg}\n"
                "5. 想弱化风格时把权重降到 0.4。\n"
            )
        else:
            example = cap if cap else (
                "anime cel-shading, clean thin black outlines, flat color, "
                "simple soft cel shading, tv anime screenshot, limited color palette")
            text = (
                "【画风 LoRA 使用模板】\n"
                f"模型文件：{output_name}.safetensors\n"
                "本 LoRA 无 trigger 触发词，提示词直接写画风标签即可。\n"
                f"训练分辨率：{reso}px\n\n"
                "使用建议：\n"
                "1. 推荐 LoRA 权重 0.5 ~ 0.7。\n"
                "2. 正向提示词直接写训练时的画风标签：\n"
                f"   你的训练标签示例：{example}\n"
                f"   出图示例：{example}, 1girl, cherry blossoms\n"
                "3. 不要输入角色名/trigger 词（这个 LoRA 没有也不应该有）。\n"
                f"4. 负面提示词建议：{neg}\n"
                "5. 想弱化风格时把权重降到 0.4。\n"
            )
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(text)
    return path


def _ensure_tokenizer_cached(cache_dir, model_id, logf=print, kind="clip", vpy=None):
    """预缓存分词器（kohya 期望的平铺目录格式），完整性校验 + 不完整自动重建。

    用训练环境（kohya/AMD venv）的 python 执行下载，避免打包环境无 transformers；
    缓存目录不完整（缺关键文件）会被清理重建，防止训练时 from_pretrained 崩。
    kind: 'clip'=CLIPTokenizer；其他（t5/qwen3 等）=AutoTokenizer。
    """
    target = os.path.join(cache_dir, model_id.replace("/", "_"))

    def _complete():
        try:
            if kind == "clip":
                need = ("vocab.json", "merges.txt", "tokenizer_config.json", "special_tokens_map.json")
            else:
                need = ("tokenizer_config.json", "tokenizer.json")
            return all(os.path.isfile(os.path.join(target, n)) for n in need)
        except Exception:
            return False

    if _complete():
        return True
    if os.path.isdir(target):
        try:
            shutil.rmtree(target)
            logf(f"[训练] 分词器缓存不完整，已清理重建 {model_id}")
        except Exception:
            pass
    py = vpy or venv_python()
    if not os.path.isfile(py):
        return False
    cls = "CLIPTokenizer" if kind == "clip" else "AutoTokenizer"
    code = ("import sys, os;"
            "from transformers import " + cls + ";"
            "t=" + cls + ".from_pretrained(%r);"
            "os.makedirs(%r, exist_ok=True);"
            "t.save_pretrained(%r);"
            "print('tok_ok')") % (model_id, target, target)
    # 强制走国内镜像：缓存失败通常就是直连 huggingface.co 超时（用户 A 反馈），
    # 不能依赖父进程是否设置了 HF_ENDPOINT。
    _tok_env = build_env()
    _hf0 = _tok_env.get("HF_ENDPOINT", "")
    if not _hf0 or "huggingface.co" in _hf0:
        _tok_env["HF_ENDPOINT"] = "https://hf-mirror.com"
    try:
        r = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=900, env=_tok_env)
        if r.returncode == 0 and "tok_ok" in (r.stdout or ""):
            logf(f"[训练] 已预缓存分词器 {model_id}")
            return True
        logf(f"[训练] 分词器 {model_id} 预缓存失败（{(r.stderr or '')[-160:]}），将尝试联网加载")
        return False
    except Exception as e:
        logf(f"[训练] 分词器 {model_id} 预缓存失败（{e}），将尝试联网加载")
        return False


def train(logf=print, base_model=None, mode="style", params=None, vram_gb=None, resume_from=None, progress=None):
    params = params or {}
    amd_mode = bool(params.get("amd_mode", False))
    if progress is not None:
        _orig_logf = logf
        def logf(line):
            try:
                progress.on_line(str(line))
            except Exception:
                pass
            _orig_logf(line)
        try:
            progress.start()
        except Exception:
            pass
    kdir = get_kohya_dir()
    vpy = venv_python(kdir)
    if not os.path.isfile(vpy):
        raise RuntimeError("Kohya 尚未安装，请先点击【一键安装】")
    if amd_mode:
        _env_dir = (params.get("train_env") or "").strip()
        if _env_dir and os.path.isfile(os.path.join(_env_dir, "Scripts", "python.exe")):
            vpy = os.path.join(_env_dir, "Scripts", "python.exe")
            logf(f"[训练] AMD 兼容模式：使用自定义训练环境 {_env_dir}")
        _bk = detect_torch_backend(vpy)
        if _bk not in ("rocm", "zluda"):
            raise RuntimeError(
                "AMD 兼容模式（实验性）：未检测到可用的训练环境。\n\n"
                "当前 torch 后端：%s\n\n"
                "AMD 显卡需要先配置 ROCm 版 PyTorch 或 ZLUDA 才能训练。\n"
                "请按「使用说明」的 AMD 章节配置环境，或在界面关闭 AMD 兼容模式。" % (_bk or "未知"))
        logf("[训练] AMD 兼容模式（实验性）：torch 后端 = %s，参数已自动适配" % _bk)
    # 自愈：确保训练环境（AMD=venv_amd，普通=kohya venv）具备完整运行时依赖
    # （PIL/numpy/transformers/huggingface_hub/toml 等，缺了会导致分词器缓存、
    #  Anima/FLUX 组件下载、sd-scripts 训练报 ModuleNotFoundError）
    if not _ensure_kohya_deps(vpy, kdir, logf):
        raise RuntimeError("训练环境依赖补装失败（网络不稳），请检查网络后重试，或重跑【② 安装训练内核 / AMD 环境引导】")
    if amd_mode:
        # AMD 版 PyTorch 的 torch.distributed 可能残缺（收尾崩、最终模型不保存），自动补兼容层
        try:
            _ensure_amd_distributed_compat(vpy, logf)
        except Exception:
            pass
    sds = os.path.join(kdir, "sd-scripts")
    base_type = params.get("base_type", "sd15")
    arch_info = ARCH_INFO.get(base_type, ARCH_INFO["sd15"])
    script = arch_info["script"]
    family = arch_info["family"]
    if not os.path.isfile(os.path.join(sds, script)):
        raise RuntimeError(f"sd-scripts 缺失 {script}（当前架构 {BASE_TYPE_LABELS.get(base_type, base_type)}），请重跑【一键安装】")
    if not base_model or not os.path.isfile(base_model):
        raise RuntimeError("请选择底模（.safetensors）")
    if amd_mode and (params.get("train_env") or "").strip():
        accel = os.path.join((params.get("train_env") or "").strip(), "Scripts", "accelerate.exe")
    else:
        accel = os.path.join(kdir, "venv", "Scripts", "accelerate.exe")
    if not os.path.isfile(accel):
        raise RuntimeError("accelerate 缺失，请重跑【一键安装】")

    resolution = int(params.get("resolution") or arch_info["resolution"])
    train_dir = dataset_train_dir(mode, params.get("project"))
    if count_images(train_dir) == 0:
        raise RuntimeError(f"缺少预处理数据：{train_dir}\n请先执行【数据预处理】或【一键开始训练】")
    cfg_path = os.path.join(KIT_DIR, "configs", "dataset_config.toml")
    data_sub("output")
    data_sub("logs")
    for _tid, _kind in arch_info["tokenizers"]:
        _ensure_tokenizer_cached(data_sub("tokenizers"), _tid, logf, _kind, vpy)

    # ---- 全局正向提示词：训练期注入（不写进原 txt） ----
    global_dataset = None
    try:
        global_dataset = make_global_caption_dataset(train_dir, mode, params.get("global_pos"))
    except Exception as e:
        logf(f"[训练] 全局提示词注入失败，忽略（{e}）")
        global_dataset = None
    dataset_dir = global_dataset or train_dir
    if global_dataset:
        logf(f"[训练] 已注入全局正向提示词，使用临时数据集: {global_dataset}")

    keep_tokens = 0
    if mode in ("character", "style"):
        _trig = params.get("trigger") or ""
        if _trig.strip():
            keep_tokens = max(1, len(split_triggers(_trig)))
            _tlabel = "画风" if mode == "style" else ""
            # 训练前把当前 trigger 同步进标签：用户可能改过 trigger 但没重新预处理，
            # 若标签第一行没有当前 trigger，LoRA 就学不到它，生图"召唤不出来"。
            try:
                _synced = _sync_trigger_to_labels(train_dir, _trig, logf)
                if _synced:
                    logf(f"[训练] 已把{_tlabel} trigger「{_trig}」同步到 {_synced} 张标签第一行")
            except Exception as _e:
                logf(f"[训练] trigger 标签同步失败（忽略）: {_e}")
    # 数据集子集：支持秋叶式 repeats_名称 子目录结构（每个子目录独立 repeats）
    try:
        subsets = scan_dataset_subsets(dataset_dir, int(params.get("repeats", 5)))
    except Exception:
        subsets = [(dataset_dir, max(1, int(params.get("repeats", 5))), count_images(dataset_dir))]
    reg_subsets = None
    if mode == "character" and params.get("reg_dir"):
        try:
            reg_subsets = scan_dataset_subsets(params["reg_dir"], 1)
        except Exception:
            reg_subsets = None
    import preprocess as _pp
    _pp.write_dataset_config(
        dataset_dir, cfg_path, resolution=resolution,
        num_repeats=params.get("repeats", 5),
        subsets=subsets,
        reg_dir=(params.get("reg_dir") if mode == "character" else None),
        reg_subsets=reg_subsets,
        keep_tokens=keep_tokens,
    )
    logf(f"[训练] 数据集: {dataset_dir}（{resolution}px）")
    for _d, _n, _c in subsets:
        _tag = os.path.basename(os.path.normpath(_d))
        logf(f"[训练]   · {_tag}：{_c} 张 × {_n} repeats")
    if mode == "character" and params.get("reg_dir"):
        logf(f"[训练] 正则数据集: {params.get('reg_dir')}")

    rank = params.get("rank", 12)
    alpha = params.get("alpha", 6)
    unet_lr = params.get("unet_lr", 3e-4)
    te_lr = params.get("te_lr", 1.5e-4)
    epochs = params.get("max_epochs", 8)
    train_te = params.get("train_text_encoder", True)
    gc_on = decide_gradient_checkpointing(params.get("gc", "自动"), vram_gb)
    batch_size = int(params.get("batch_size", 1))
    use_xformers = bool(params.get("use_xformers", False))
    optimizer_type = "AdamW8bit"
    if amd_mode:
        use_xformers = False          # AMD 无 xformers，强制 sdpa
        optimizer_type = "AdamW"      # AMD 下 bitsandbytes(AdamW8bit) 不可用，改用纯 PyTorch 优化器
    output_name = OUTPUT_NAMES.get(mode, "anime_style_lora")
    # 项目分组输出：output/<项目名>/（没开项目则直接 output/）
    _proj = (params.get("project") or "").strip()
    if _proj:
        out_dir = data_sub("output", _proj)
    else:
        out_dir = data_sub("output")
    mixed = arch_info["mixed"]
    if amd_mode:
        mixed = "bf16"                # AMD RDNA3 原生支持 bf16，统一用 bf16 更稳
    save_precision = arch_info["save_precision"]
    min_bucket, max_bucket = arch_info["min_bucket"], arch_info["max_bucket"]
    network_module = arch_info["network_module"]

    # 自动约束 epoch（防过拟合）：总步数按 repeats_名称 子目录加权计算
    per_epoch_steps = sum(n * c for _, n, c in subsets) // max(1, batch_size)
    epochs_eff, total_steps = cap_epochs_by_steps(per_epoch_steps, batch_size, epochs)
    if epochs_eff != epochs:
        logf(f"[训练] 自动约束：为防过拟合，epoch 由 {epochs} 调整为 {epochs_eff}（总步数约 {total_steps}）")
        epochs = epochs_eff
    if progress is not None:
        try:
            progress.set_total(total_steps)
        except Exception:
            pass
        # kohya 的 tqdm 日志不输出 lr，训练启动时把配置的学习率预填进监控面板
        try:
            progress.set_lr(unet_lr)
        except Exception:
            pass

    # 保存节奏：约每 1/10 步保存一次（至少 100 步），用于中间快照与断点续训
    save_every = 200

    cmd = [
        accel, "launch", "--num_cpu_threads_per_process", "2", script,
        f"--pretrained_model_name_or_path={base_model}",
        f"--dataset_config={cfg_path}",
        f"--tokenizer_cache_dir={data_sub('tokenizers')}",
        f"--output_dir={out_dir}",
        f"--output_name={output_name}",
        f"--logging_dir={data_sub('logs')}",
        "--save_model_as=safetensors", f"--save_precision={save_precision}",
        f"--network_module={network_module}",
        f"--network_dim={rank}", f"--network_alpha={alpha}",
        f"--learning_rate={unet_lr}",
    ]
    if family == "sd":
        cmd += [f"--unet_lr={unet_lr}", f"--text_encoder_lr={te_lr}"]
    if not train_te or family == "anima":
        # FLUX/Anima 默认只训练 DiT 部分（Anima 的 Qwen3 文本编码器始终冻结）
        cmd.append("--network_train_unet_only")
    if family == "flux":
        clip_l, t5xxl, ae = find_flux_components(base_model)
        missing = [n for n, p in (("CLIP-L", clip_l), ("T5-XXL", t5xxl), ("AE", ae)) if not p]
        if missing:
            raise RuntimeError(
                "FLUX 训练需要 4 个文件放在同一个文件夹：\n"
                "  · flux1-dev.safetensors（已选的底模）\n"
                "  · clip_l.safetensors\n  · t5xxl_fp16.safetensors\n  · ae.safetensors\n\n"
                f"缺少：{'、'.join(missing)}\n"
                "下载地址：HuggingFace black-forest-labs/FLUX.1-dev（DiT+AE）、"
                "comfyanonymous/flux_text_encoders（clip_l/t5xxl），国内可用 hf-mirror.com。")
        cmd += [f"--clip_l={clip_l}", f"--t5xxl={t5xxl}", f"--ae={ae}", "--guidance_scale=1.0"]
        if vram_gb is None or vram_gb < 12:
            cmd += ["--fp8_base", "--blocks_to_swap=20"]
        elif vram_gb < 16:
            cmd += ["--fp8_base"]
    elif family == "anima":
        qwen3, vae = _ensure_anima_components(logf)
        cmd += [f"--qwen3={qwen3}", f"--vae={vae}",
                "--qwen_image_vae_2d", "--vae_chunk_size=64"]
        # 8~12G 显存：把 DiT 层搬到内存省显存（Anima 不支持 fp8，只能用 blocks_to_swap），
        # 否则 1024px 下 2B DiT + Qwen3 + 优化器超出 8G 显存 → 系统换页 → 每步 100+ 秒。
        # 文本编码器始终冻结 → 缓存其输出，省掉每步的前向计算。
        if vram_gb is None or vram_gb < 12:
            cmd += ["--blocks_to_swap=16"]
        elif vram_gb < 16:
            cmd += ["--blocks_to_swap=8"]
        cmd.append("--cache_text_encoder_outputs")
    cmd += [
        f"--optimizer_type={optimizer_type}", "--lr_scheduler=cosine", "--lr_warmup_steps=120",
        f"--max_train_epochs={epochs}",
        f"--train_batch_size={batch_size}",
        # 0 = 数据加载在主进程内完成：Windows 下 n_workers>0 会用 multiprocessing 额外开子进程，
        # 每次加载数据都弹黑色 cmd 窗口并抢资源；设 0 彻底不弹窗，训练速度几乎不受影响。
        "--max_data_loader_n_workers=0",
        "--seed=1234", f"--mixed_precision={mixed}", "--cache_latents", "--cache_latents_to_disk",
        "--enable_bucket", "--bucket_no_upscale",
        f"--min_bucket_reso={min_bucket}", f"--max_bucket_reso={max_bucket}",
        "--bucket_reso_steps=64", "--caption_extension=.txt",
        f"--save_every_n_steps={save_every}", "--save_state",
    ]
    if base_type == "sdxl" and not train_te:
        cmd.append("--cache_text_encoder_outputs")
    if family == "sd":
        if use_xformers:
            cmd.append("--xformers")
        else:
            cmd.append("--sdpa")
        if gc_on:
            cmd.append("--gradient_checkpointing")
    else:
        # FLUX / Anima 固定用 sdpa + 梯度检查点（省显存）
        cmd.append("--sdpa")
        if gc_on or vram_gb is None or vram_gb < 16:
            cmd.append("--gradient_checkpointing")
    if resume_from:
        cmd.append(f"--resume={resume_from}")
        logf(f"[训练] 断点续训：从 {resume_from} 继续")

    logf(f"[训练] 底模: {base_model}（{BASE_TYPE_LABELS.get(base_type, base_type)}）")
    logf(f"[训练] 模式: {MODE_LABELS.get(mode, mode)} | 脚本: {script} | 分辨率: {resolution}px")
    logf(f"[训练] LoRA 参数: dim={rank}, alpha={alpha}, lr={unet_lr}, te_lr={te_lr}, epochs={epochs}, repeats={params.get('repeats', 5)}")
    logf(f"[训练] batch={batch_size} | 混合精度={mixed} | 注意力: {'xformers' if use_xformers else 'sdpa'} | 梯度检查点: {'开' if gc_on else '关'}"
         + (f"（显存 {vram_gb:.1f}GB 智能适配）" if vram_gb else ""))
    if mode == "character":
        logf(f"[训练] trigger: {params.get('trigger') or '（未填写）'}"
             + (f" | 正则数据集: {params.get('reg_dir')}" if params.get("reg_dir") else " | 未使用正则数据集"))
    else:
        logf("[训练] 画风模式：无 trigger，不传递正则相关参数。")
    if params.get("global_pos"):
        logf(f"[训练] 附加全局正向提示词: {params.get('global_pos')}")
    if params.get("global_neg"):
        logf("[训练] 附加全局负向提示词: 仅记录进报告/模板（kohya 训练不使用负向提示词）。")
    if amd_mode:
        logf("[训练] AMD 兼容模式：sdpa + bf16 + AdamW 优化器（实验性，不承诺稳定）")

    env = build_env([os.path.join(kdir, "venv", "Lib", "site-packages", "torch", "lib")])
    _px = system_proxy()
    if _px:
        env.setdefault("HTTP_PROXY", _px)
        env.setdefault("HTTPS_PROXY", _px)
    # 国内镜像：transformers/huggingface_hub 走 hf-mirror，避免直连 huggingface.co 超时
    # 用覆盖而不是 setdefault：用户系统若已有 HF_ENDPOINT=https://huggingface.co，
    # setdefault 不会生效，训练时仍直连官方站超时（用户 A 反馈）。
    _hf0 = env.get("HF_ENDPOINT", "")
    if not _hf0 or "huggingface.co" in _hf0:
        env["HF_ENDPOINT"] = "https://hf-mirror.com"
    if amd_mode:
        _gname = (detect_gpu_name() or "")
        if re.search(r"RX\s*6\d{3}", _gname, re.I):   # RX 6000 系（RDNA2）需 GFX 版本覆盖
            env.setdefault("HSA_OVERRIDE_GFX_VERSION", "10.3.0")
            logf("[训练] AMD 兼容模式：RX 6000 系已设置 HSA_OVERRIDE_GFX_VERSION=10.3.0")
        env.setdefault("DISABLE_ADDMM_CUDA_LT", "1")  # ZLUDA/ROCm 兼容
        env.setdefault("MIOPEN_FIND_MODE", "2")       # ROCm 卷积搜索加速
    try:
        rc = run_stream(cmd, cwd=sds, env=env, logf=logf)
    except StopRequested:
        # 手动停止：清理全局提示词临时数据集后原样抛出，由界面层友好提示
        if progress is not None:
            try:
                progress.finish()
            except Exception:
                pass
        if global_dataset:
            try:
                shutil.rmtree(global_dataset, ignore_errors=True)
            except Exception:
                pass
        raise
    if rc != 0:
        if progress is not None:
            try:
                progress.finish()
            except Exception:
                pass
        raise RuntimeError(f"训练结束，退出码 {rc}，请查看上方日志（可用断点续训继续）")
    if progress is not None:
        try:
            progress.finish()
        except Exception:
            pass
    model_path = os.path.join(out_dir, output_name + ".safetensors")
    logf(f"[训练] 完成！模型: {model_path}")
    # 把中间快照（step-* 模型 + 续训状态目录）归拢到 output\snapshots\，根目录只留成品
    try:
        snap_dir = os.path.join(out_dir, "snapshots")
        os.makedirs(snap_dir, exist_ok=True)
        moved = 0
        for name in list(os.listdir(out_dir)):
            if name.startswith(output_name + "-step") or name == output_name + "-state":
                s0 = os.path.join(out_dir, name)
                d0 = os.path.join(snap_dir, name)
                if not os.path.exists(d0):
                    shutil.move(s0, d0)
                    moved += 1
        if moved:
            logf(f"[导出] 已把 {moved} 个中间快照/续训状态整理到: {snap_dir}")
    except Exception as e:
        logf(f"[导出] 整理中间快照失败（忽略）: {e}")
    try:
        tpl = write_usage_template(mode, params, output_name, out_dir=out_dir)
        logf(f"[导出] 已生成使用模板: {tpl}")
    except Exception as e:
        logf(f"[导出] 生成使用模板失败: {e}")
    try:
        rep = write_params_report(mode, params, output_name,
                                  extra=[f"总步数约 {total_steps}", f"保存间隔 {save_every} 步"],
                                  out_dir=out_dir)
        logf(f"[导出] 已生成参数报告: {rep}")
    except Exception as e:
        logf(f"[导出] 生成参数报告失败: {e}")
    if mode == "style":
        logf("[训练] 推理时 LoRA 权重建议 0.5~0.7，提示词直接用画风标签。")
    else:
        logf(f"[训练] 推理时 LoRA 权重建议 0.6~0.9，提示词以 trigger「{params.get('trigger') or '触发词'}」开头。")
    if global_dataset:
        try:
            shutil.rmtree(global_dataset, ignore_errors=True)
        except Exception:
            pass




# system_status 结果缓存：环境/显卡检测要跑多个子进程（git/python/nvidia-smi/WMI），
# 页面切换（主页<->项目）高频调用时缓存 30 秒，避免每次卡 5~10 秒。
_SYSTEM_STATUS_CACHE = {"t": 0.0, "data": None}
SYSTEM_STATUS_TTL = 30.0


def system_status(force=False):
    _now = time.time()
    if (not force) and _SYSTEM_STATUS_CACHE["data"] is not None             and (_now - _SYSTEM_STATUS_CACHE["t"]) < SYSTEM_STATUS_TTL:
        return _SYSTEM_STATUS_CACHE["data"]
    git = find_git()
    py, ver = find_python()
    kdir = get_kohya_dir()
    vpy = venv_python(kdir)
    kohya_ok = os.path.isfile(vpy) and os.path.isdir(os.path.join(kdir, "sd-scripts"))
    gpu = detect_gpu_name() or "?"
    try:
        _musubi_ok = _musubi_marker_ok()
    except Exception:
        _musubi_ok = False
    try:
        _at_ok = _at_marker_ok()
    except Exception:
        _at_ok = False
    data = {
        "git": git or None,
        "python": f"{ver}" if ver else None,
        "kohya_ok": kohya_ok,
        "kohya_dir": kdir if kohya_ok else None,
        "gpu": gpu,
        "musubi_ok": _musubi_ok,
        "at_ok": _at_ok,
    }
    _SYSTEM_STATUS_CACHE["t"] = _now
    _SYSTEM_STATUS_CACHE["data"] = data
    return data


GITHUB_REPO = "l1934332574-maker/Kohya-LoRA-Tool"
MODELSCOPE_MIRROR = "FGtiancai/Kohya-LoRA-Tool"  # 魔搭国内镜像（Setup.exe + update.json）


def parse_version(v):
    """'v0.8.3' / '0.8.3' -> (0,8,3)；无法解析返回 None。"""
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", str(v or ""))
    if m:
        return tuple(int(x) for x in m.groups())
    return None


def check_update(timeout=15):
    """检查最新版本（多源取最高版本，避免单个 CDN 缓存滞后误判"已是最新"）。

    源（全部拉取，取版本号最高的结果）：
      1) 魔搭 update.json（国内快）
      2) raw.githubusercontent update.json（即时）
      3) jsDelivr CDN update.json（国内快，可能有缓存延迟）
      4) GitHub Releases API（最准，但未登录限流 60 次/小时/IP）

    返回 dict 或 None（全部失败返回 None）：
      {'version','setup_url','setup_url_cn','notes','newer'}
    """
    import json
    cur = parse_version(APP_VERSION)

    def _pick(best, item):
        # 保留版本号更高的；同版本优先保留 setup_url_cn 更完整（国内直链）的
        if item is None:
            return best
        if best is None:
            return item
        lv = parse_version(item["version"]) or (0, 0, 0)
        bv = parse_version(best["version"]) or (0, 0, 0)
        if lv > bv:
            return item
        if lv == bv and item.get("setup_url_cn") and not best.get("setup_url_cn"):
            return item
        return best

    best = None
    # 1)~3) 静态 update.json：全部尝试，取最高版本，而不是"第一个能解析就拍板"
    for u in (
        "https://modelscope.cn/models/%s/resolve/master/update.json" % MODELSCOPE_MIRROR,
        "https://raw.githubusercontent.com/%s/main/update.json" % GITHUB_REPO,
        "https://cdn.jsdelivr.net/gh/%s@main/update.json" % GITHUB_REPO,
    ):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
            r = urllib.request.urlopen(req, timeout=timeout)
            data = json.loads(r.read().decode("utf-8", "replace"))
            tag = (data.get("version") or "").strip()
            if not parse_version(tag):
                continue
            item = {
                "version": tag,
                "setup_url": (data.get("setup_url") or "").strip(),
                "setup_url_cn": (data.get("setup_url_cn") or "").strip(),
                "notes": (data.get("notes") or "").strip()[:400],
                "newer": bool(cur and parse_version(tag) > cur),
            }
            best = _pick(best, item)
        except Exception:
            continue
    # 4) 兜底：GitHub Releases API（版本更高才采纳）
    try:
        url = "https://api.github.com/repos/%s/releases/latest" % GITHUB_REPO
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github+json"})
        r = urllib.request.urlopen(req, timeout=timeout)
        rel = json.loads(r.read().decode("utf-8", "replace"))
        tag = (rel.get("tag_name") or "").strip()
        setup_url = None
        for a in rel.get("assets", []) or []:
            if (a.get("name") or "").lower() == "setup.exe":
                setup_url = a.get("browser_download_url") or a.get("url")
        if parse_version(tag) and setup_url:
            item = {
                "version": tag,
                "setup_url": setup_url,
                "setup_url_cn": "",
                "notes": (rel.get("body") or "").strip()[:400],
                "newer": bool(cur and parse_version(tag) > cur),
            }
            best = _pick(best, item)
    except Exception:
        pass
    return best


# ---------- 桌面 UI ----------

# 基础底模不内置，从这里引导小白下载（两条国内直链）
HF_MIRROR_URL = "https://hf-mirror.com"
# 极速直链：阿里 ModelScope（魔搭）CDN，国内快约 6 倍
MODELSCOPE_URLS = {
    "sd15": "https://modelscope.cn/models/AI-ModelScope/stable-diffusion-v1-5/resolve/master/v1-5-pruned-emaonly.safetensors",
    "sdxl": "https://modelscope.cn/models/AI-ModelScope/stable-diffusion-xl-base-1.0/resolve/master/sd_xl_base_1.0.safetensors",
}
# 备用直链：hf-mirror（resolve 直链，浏览器打开即弹出保存）
HF_MIRROR_URLS = {
    "sd15": "https://hf-mirror.com/stable-diffusion-v1-5/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors?download=true",
    "sdxl": "https://hf-mirror.com/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors?download=true",
}
HF_MODEL_INFO = {
    "sd15": ("v1-5-pruned-emaonly.safetensors", "约 4.3 GB"),
    "sdxl": ("sd_xl_base_1.0.safetensors", "约 6.9 GB"),
}

# 应用内/浏览器可选的底模下载目录（key 稳定；name 面向小白用户；rec=True 为默认推荐项）
# 说明：训练底模建议和你出图时用的底模同一系列/同类型，效果最稳；
#       动漫 LoRA 一般建议直接用「动漫」系列底模训练，而不是原版通用底模。
DOWNLOAD_MODELS = {
    "sd15": [
        {
            "key": "anime_anything5", "rec": True,
            "name": "动漫 anything-v5",
            "file": "AnythingV5Ink_ink.safetensors",
            "size": "约 2.0 GB",
            "url": "https://modelscope.cn/models/licyks/sd-model/resolve/master/sd_1.5/AnythingV5Ink_ink.safetensors",
            "fallback": "https://modelscope.cn/models/licyks/sd-model/resolve/master/sd_1.5/AnythingV5Ink_ink.safetensors",
            "note": "经典动漫底模（SD1.5 动漫首选），画风/人物 LoRA 都通用；训练后出图也建议用动漫底模。",
        },
        {
            "key": "anime_meinamix",
            "name": "动漫 MeinaMix V11",
            "file": "meinamix_meinaV11.safetensors",
            "size": "约 2.0 GB",
            "url": "https://modelscope.cn/models/licyks/sd-model/resolve/master/sd_1.5/meinamix_meinaV11.safetensors",
            "fallback": "https://modelscope.cn/models/licyks/sd-model/resolve/master/sd_1.5/meinamix_meinaV11.safetensors",
            "note": "综合动漫底模，风格泛化好，画风多样时更稳。",
        },
        {
            "key": "vanilla",
            "name": "通用 SD1.5 原版",
            "file": "v1-5-pruned-emaonly.safetensors",
            "size": "约 4.0 GB",
            "url": "https://modelscope.cn/models/AI-ModelScope/stable-diffusion-v1-5/resolve/master/v1-5-pruned-emaonly.safetensors",
            "fallback": "https://hf-mirror.com/stable-diffusion-v1-5/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors?download=true",
            "note": "2022 年的原版通用底模，适合写实/通用；动漫效果一般，不推荐动漫 LoRA 首选。",
        },
    ],
    "sdxl": [
        {
            "key": "anime_illustrious20", "rec": True,
            "name": "动漫 Illustrious-XL v2.0-stable",
            "file": "Illustrious-XL-v2.0-stable.safetensors",
            "size": "约 6.5 GB",
            "url": "https://modelscope.cn/models/licyks/sd-model/resolve/master/sdxl_1.0/Illustrious-XL-v2.0-stable.safetensors",
            "fallback": "https://modelscope.cn/models/licyks/sd-model/resolve/master/sdxl_1.0/Illustrious-XL-v2.0-stable.safetensors",
            "note": "2025 年发布的 Illustrious 最新稳定版，当前动漫 LoRA 主流底模，画质/细节好（eps 预测，直接训练即可）。",
        },
        {
            "key": "anime_noobai_eps11",
            "name": "动漫 NoobAI-XL eps 1.1",
            "file": "noobaiXLNAIXL_epsilonPred11Version.safetensors",
            "size": "约 6.6 GB",
            "url": "https://modelscope.cn/models/licyks/sd-model/resolve/master/sdxl_1.0/noobaiXLNAIXL_epsilonPred11Version.safetensors",
            "fallback": "https://modelscope.cn/models/licyks/sd-model/resolve/master/sdxl_1.0/noobaiXLNAIXL_epsilonPred11Version.safetensors",
            "note": "2025 年 NoobAI 的 eps 版本，动漫人物/画风都强；eps 预测，直接训练即可（v-pred 版需要额外参数，未收录）。",
        },
        {
            "key": "anime_nova",
            "name": "动漫 Nova Anime XL（2026）",
            "file": "novaAnimeXL_ilV30HappyNewYear.safetensors",
            "size": "约 6.5 GB",
            "url": "https://modelscope.cn/models/ModelE/Nova-Anime-XL/resolve/master/novaAnimeXL_ilV30HappyNewYear.safetensors",
            "fallback": "https://modelscope.cn/models/ModelE/Nova-Anime-XL/resolve/master/novaAnimeXL_ilV30HappyNewYear.safetensors",
            "note": "2026 年更新的合体底模（NoobAI eps 1.1 + Illustrious v2.0-stable + ChenkinNoob），细节/对比度更好，最新选择。",
        },
        {
            "key": "anime_anishadow52",
            "name": "动漫 AniShadow V5.2",
            "file": "sd_xl_anime_V52.safetensors",
            "size": "约 6.5 GB",
            "url": "https://modelscope.cn/models/licyks/sd-model/resolve/master/sdxl_1.0/sd_xl_anime_V52.safetensors",
            "fallback": "https://modelscope.cn/models/licyks/sd-model/resolve/master/sdxl_1.0/sd_xl_anime_V52.safetensors",
            "note": "和你 Forge 里的 AniShadow V5 同系列，训练后直接配它出图效果最一致。",
        },
        {
            "key": "anime_animagine40",
            "name": "动漫 Animagine XL 4.0",
            "file": "animagine-xl-4.0.safetensors",
            "size": "约 6.5 GB",
            "url": "https://modelscope.cn/models/licyks/sd-model/resolve/master/sdxl_1.0/animagine-xl-4.0.safetensors",
            "fallback": "https://modelscope.cn/models/licyks/sd-model/resolve/master/sdxl_1.0/animagine-xl-4.0.safetensors",
            "note": "老牌动漫底模 Animagine 的新版本，动漫风格成熟。",
        },
        {
            "key": "vanilla",
            "name": "通用 SDXL 1.0 原版",
            "file": "sd_xl_base_1.0.safetensors",
            "size": "约 6.5 GB",
            "url": "https://modelscope.cn/models/AI-ModelScope/stable-diffusion-xl-base-1.0/resolve/master/sd_xl_base_1.0.safetensors",
            "fallback": "https://hf-mirror.com/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors?download=true",
            "note": "2023 年的原版通用底模，动漫效果一般，不推荐动漫 LoRA 首选。",
        },
    ],
    "anima": [
        {
            "key": "anima_base", "rec": True,
            "name": "Anima DiT（anima-base-v1.0）",
            "file": "anima-base-v1.0.safetensors",
            "size": "约 4.0 GB",
            "url": "https://hf-mirror.com/circlestone-labs/Anima/resolve/main/split_files/diffusion_models/anima-base-v1.0.safetensors",
            "fallback": "https://hf-mirror.com/circlestone-labs/Anima/resolve/main/split_files/diffusion_models/anima-base-v1.0.safetensors",
            "note": "Anima DiT 底模（约 4GB）。Qwen3-0.6B 文本编码器和 Qwen-Image VAE 会在首次训练时自动下载（国内镜像），无需手动准备。",
        },
    ],
}


def get_download_models(base_type):
    """返回该底模类型的可选下载模型列表。"""
    return DOWNLOAD_MODELS.get(base_type, [])


def get_default_download_model(base_type):
    """返回默认推荐下载模型（带 rec 标记的第一个，否则第一个）。"""
    models = get_download_models(base_type)
    if not models:
        return None
    for m in models:
        if m.get("rec"):
            return m
    return models[0]












def migrate_legacy_dataset(project, mode):
    """把旧版共享数据集迁移到当前项目独立目录（一次性，仅当项目目录为空且共享目录有图时）。

    返回 (目标目录, 是否发生了迁移)。
    """
    proj = _sanitize_dirname(project)
    if not proj:
        return dataset_train_dir(mode), False
    target = dataset_train_dir(mode, project)
    legacy = dataset_train_dir(mode)          # 旧版共享目录
    if os.path.abspath(target) == os.path.abspath(legacy):
        return target, False
    if count_images(target) > 0:              # 项目已有自己的数据，不动
        return target, False
    if count_images(legacy) == 0:             # 共享目录没有数据，无需迁移
        return target, False
    os.makedirs(target, exist_ok=True)
    n = 0
    for name in sorted(os.listdir(legacy)):
        if name.startswith("."):
            continue
        fp = os.path.join(legacy, name)
        try:
            if os.path.isdir(fp):
                shutil.move(fp, os.path.join(target, name)); n += 1
            elif name.lower().endswith(IMAGE_EXTS) or name.lower().endswith(".txt") or name.lower().endswith(".npz"):
                shutil.move(fp, os.path.join(target, name)); n += 1
        except Exception:
            pass
    return target, n > 0


# ============================================================
# 项目化管理：每个项目保存 模式/底模/数据集/trigger/全部参数/全局提示词
# 项目文件存 %APPDATA%\KohyaLoraTool\projects\<项目名>.json
# ============================================================















# 新建项目时的预设模板（填入模式 + 参数；底模/数据集用户自己选）


def scan_base_models():
    """扫描基础底模目录，返回 [(路径, 文件名, 识别类型或None)]。safetensors 秒级识别类型。"""
    d = base_models_dir()
    out = []
    if not os.path.isdir(d):
        return out
    for f in sorted(os.listdir(d)):
        low = f.lower()
        if low.endswith((".safetensors", ".ckpt")):
            p = os.path.join(d, f)
            bt = None
            if low.endswith(".safetensors"):
                try:
                    bt = detect_base_type(p)
                except Exception:
                    bt = None
            out.append((p, f, bt))
    return out


class Tooltip:
    """鼠标悬停显示通俗中文说明的小气泡。"""

    def __init__(self, widget, text, wrap=360):
        self.widget = widget
        self.text = text
        self.wrap = wrap
        self.tip = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._leave, add="+")

    def _enter(self, _e=None):
        if self.tip is not None:
            return
        try:
            x = self.widget.winfo_rootx() + 16
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            self.tip = tk.Toplevel(self.widget)
            self.tip.wm_overrideredirect(True)
            self.tip.wm_geometry(f"+{x}+{y}")
            lbl = tk.Label(self.tip, text=self.text, justify="left", background="#ffffe6",
                           relief="solid", borderwidth=1, wraplength=self.wrap,
                           font=("Microsoft YaHei UI", 9), padx=8, pady=6)
            lbl.pack()
        except Exception:
            self.tip = None

    def _leave(self, _e=None):
        if self.tip is not None:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None


# ---------- 底模类型自动识别 ----------

def _safetensors_keys(path):
    """只读 safetensors 头部 JSON，拿全部张量键名（不加载权重，秒级）。

    兼容两种头部格式：
      - 标准：{"tensors": {键: 信息}, "__metadata__": ...}
      - 扁平：{键: 信息}（部分工具导出格式）
    """
    import json

    with open(path, "rb") as f:
        head = f.read(8)
        if len(head) < 8:
            return []
        ln = int.from_bytes(head, "little")
        data = json.loads(f.read(ln))
    if isinstance(data, dict) and isinstance(data.get("tensors"), dict):
        return list(data["tensors"].keys())
    if isinstance(data, dict):
        return list(data.keys())
    return []


def _ckpt_keys(path):
    """用 torch 读取 ckpt 键名（weights_only 安全模式）。"""
    import torch

    sd = torch.load(path, map_location="cpu", weights_only=True)
    if isinstance(sd, dict) and "state_dict" in sd:
        sd = sd["state_dict"]
    return list(sd.keys()) if isinstance(sd, dict) else []


def _classify_base_keys(keys):
    joined = "\n".join(keys or [])
    # FLUX.2：4B DiT（double/single stream modulation 是 FLUX.2 特有，须在 FLUX.1 判断之前）
    if ("double_stream_modulation_img." in joined or "double_stream_modulation_txt." in joined
            or "single_stream_modulation." in joined):
        return "flux2"
    # FLUX：DiT（single/double transformer blocks + guidance embed）
    if ("single_transformer_blocks." in joined or "double_blocks." in joined
            or "guidance_embed." in joined or "model.diffusion_model.single_blocks." in joined):
        return "flux"
    # Anima：MiniTrainDIT + LLM adapter（Qwen3→T5 桥）
    if "llm_adapter." in joined and ("adaln_modulation." in joined or "x_embedder." in joined):
        return "anima"
    # SDXL：conditioner 双文本编码器（open_clip + clip）
    if "conditioner.embedders.0.transformer" in joined or "conditioner.embedders.1.transformer" in joined:
        return "sdxl"
    # SD1.x / SD2.x：cond_stage_model（单个文本编码器）
    if "cond_stage_model." in joined and ("model.diffusion_model." in joined or "first_stage_model." in joined):
        return "sd15"
    if "model.diffusion_model.input_blocks.0.0.weight" in joined:
        return "sd15"
    return None


def detect_base_type(model_path):
    """自动识别底模类型：返回 'sd15' / 'sdxl' / 'flux' / 'anima' / None（无法识别）。"""
    try:
        ext = os.path.splitext(model_path or "")[1].lower()
        if ext == ".safetensors":
            keys = _safetensors_keys(model_path)
        elif ext == ".ckpt":
            keys = _ckpt_keys(model_path)
        else:
            return None
        return _classify_base_keys(keys)
    except Exception:
        return None


# ---------- FLUX / Anima 组件 ----------

def _pick_sibling(base_model, predicate):
    """在底模同目录找一个符合条件的配套文件。"""
    d = os.path.dirname(os.path.abspath(base_model))
    try:
        names = os.listdir(d)
    except Exception:
        names = []
    for name in sorted(names):
        low = name.lower()
        if not low.endswith((".safetensors", ".sft", ".pth")):
            continue
        if predicate(low):
            return os.path.join(d, name)
    return None


def find_flux_components(base_model):
    """FLUX 训练需要 DiT + CLIP-L + T5-XXL + AE 四个文件，自动在底模同目录找另外三个。

    返回 (clip_l, t5xxl, ae)，找不到的为 None。
    """
    def _clip(name):
        stem = os.path.splitext(name)[0]
        return stem in ("clip_l", "clip-l", "clip_l_fp16", "clip-l-fp16", "clip_l_fp8", "clip_l.safetensors") or stem.startswith("clip_l") or stem.startswith("clip-l")
    def _t5(name):
        stem = os.path.splitext(name)[0]
        return stem.startswith("t5xxl") or stem.startswith("t5_xxl") or stem.startswith("t5-xxl")
    def _ae(name):
        stem = os.path.splitext(name)[0]
        return stem in ("ae", "ae_fp16", "ae_fp8", "ae_bf16", "vae", "vae_fp16") or stem.startswith("ae.") or stem.startswith("vae.")
    clip_l = _pick_sibling(base_model, _clip)
    t5xxl = _pick_sibling(base_model, _t5)
    ae = _pick_sibling(base_model, _ae)
    return clip_l, t5xxl, ae


def _hf_download(repo, local_dir, logf=print, allow_patterns=None):
    """用 kohya venv 的 huggingface_hub 走 hf-mirror 下载仓库到 local_dir。

    GUI 进程（含打包版）不带 huggingface_hub 依赖，这里改用训练环境的
    venv python 执行 snapshot_download（该环境必然有 huggingface_hub），
    顺带支持进度日志与手动停止。
    """
    vpy = venv_python()
    if not os.path.isfile(vpy):
        raise RuntimeError("Kohya 尚未安装，无法下载模型组件，请先安装训练内核。")
    os.makedirs(local_dir, exist_ok=True)
    # 预检 huggingface_hub：venv Python 与依赖版本错配（如 3.10 venv 混入 cp312 扩展）时
    # import 会崩（python312.dll conflicts），这里给出明确提示而不是晦涩的 ImportError；
    # 同时清掉父进程可能带进来的 PYTHONHOME/PYTHONPATH，避免把错误 DLL 塞给子进程。
    _env = build_env()
    _hf0 = _env.get("HF_ENDPOINT", "")
    if not _hf0 or "huggingface.co" in _hf0:
        _env["HF_ENDPOINT"] = "https://hf-mirror.com"
    try:
        _r = subprocess.run(
            [vpy, "-c", "import socket, ssl; from huggingface_hub import snapshot_download; print('ok')"],
            capture_output=True, text=True, timeout=120, env=_env)
        _hf_ok = _r.returncode == 0
        _hf_err = ((_r.stderr or _r.stdout or "").strip().splitlines() or ["未知错误"])[-1]
    except Exception as e:
        _hf_ok, _hf_err = False, str(e)
    if not _hf_ok:
        raise RuntimeError(
            "venv 的 huggingface_hub 无法运行（常见：venv 是 Python 3.10/3.11，却混入了 3.12 编译的扩展，"
            "import 报 python312.dll conflicts）。\n"
            "解决办法（任选）：\n"
            "1) 直接重跑【② 安装训练内核】：新版会自动检测这种损坏 venv 并重建（旧 venv 保留）（推荐）；\n"
            "2) 或按下方提示手动放置模型文件，避免走自动下载。\n"
            f"详细信息：{_hf_err}")
    code = (
        "import os\n"
        "os.environ['HF_ENDPOINT']='https://hf-mirror.com'\n"
        "from huggingface_hub import snapshot_download\n"
        "snapshot_download(%s, local_dir=%s%s)\n"
        % (repr(repo), repr(local_dir),
           (", allow_patterns=%s" % repr(list(allow_patterns)) if allow_patterns else ""))
    )
    logf(f"[下载] 开始下载模型组件：{repo} → {local_dir}（走 hf-mirror，可随时停止）")
    rc = run_stream([vpy, "-c", code], env=build_env(), logf=logf)
    if rc != 0:
        raise RuntimeError(f"模型组件下载失败（退出码 {rc}）：{repo}")


def _anima_bases():
    """Anima 组件可能存在的根目录（兼容新旧安装目录）。

    老版本安装目录是 %APPDATA%\\Kohya_ss（提示让用户放 Kohya_ss\\Qwen3-0.6B），
    新版本是 %APPDATA%\\KohyaLoraTool\\anima。都扫一遍，避免"放到指定文件夹也没用"。
    """
    ap = os.environ.get("APPDATA", os.path.expanduser("~"))
    return [
        os.path.join(ap, "KohyaLoraTool", "anima"),
        os.path.join(ap, "Kohya_ss"),
        os.path.join(ap, "Kohya_ss", "kohya_ss"),
    ]


def _anima_find_qwen3_any():
    """遍历所有可能目录找 Qwen3，返回 (路径, 所在 base)。"""
    for base in _anima_bases():
        p = _anima_find_qwen3(base)
        if p:
            return p, base
    return None, None


def _anima_find_qwen3(base):
    """在 anima 目录找 Qwen3 文本编码器，返回可用路径或 None。

    支持两种手动放置方式：
      1) 完整模型目录（含 config.json）→ 返回目录路径
      2) 单个 .safetensors 权重文件 → 返回文件路径
         （sd-scripts 会自动用内置 configs/qwen3_06b/ 的 config/tokenizer 加载）
    """
    qwen3_dir = os.path.join(base, "Qwen3-0.6B")
    if os.path.isdir(qwen3_dir):
        if os.path.isfile(os.path.join(qwen3_dir, "config.json")):
            return qwen3_dir
        # 目录里只有 safetensors 权重（无 config.json）：取第一个（sd-scripts 单文件模式）
        for root, _dirs, files in os.walk(qwen3_dir):
            for f in sorted(files):
                if f.lower().endswith(".safetensors"):
                    return os.path.join(root, f)
    # anima 根目录下直接放的单文件
    if os.path.isdir(base):
        for f in sorted(os.listdir(base)):
            if f.lower().endswith(".safetensors") and f.lower().startswith("qwen"):
                return os.path.join(base, f)
    return None


def _ensure_anima_components(logf=print):
    """确保 Anima 的 Qwen3-0.6B 文本编码器和 Qwen-Image VAE 就位。

    返回 (qwen3 路径, vae 路径)；缺失时自动从 hf-mirror 下载。
    """
    bases = _anima_bases()
    base = bases[0]
    os.makedirs(base, exist_ok=True)
    # Qwen3 就绪判定：①完整目录（含 config.json）②单个 safetensors 权重（sd-scripts 单文件模式）
    # 兼容新旧安装目录（KohyaLoraTool\\anima 与老版 Kohya_ss），用户按提示手动放置也能识别。
    qwen3_path, qwen3_base = _anima_find_qwen3_any()
    if qwen3_path is None:
        qwen3_dir = os.path.join(base, "Qwen3-0.6B")
        logf("[Anima] 首次使用需要下载 Qwen3-0.6B 文本编码器（约 1.2GB，走 hf-mirror）…")
        try:
            _hf_download("Qwen/Qwen3-0.6B", qwen3_dir, logf)
            qwen3_path, qwen3_base = _anima_find_qwen3_any()
        except Exception as e:
            raise RuntimeError(
                f"Qwen3-0.6B 自动下载失败：{e}\n\n"
                "可手动下载，两种方式任选：\n"
                f"1) 完整模型文件夹（含 config.json + 权重 + tokenizer），解压后放到：\n   {os.path.join(base, 'Qwen3-0.6B')}\n"
                "2) 只下一个 Qwen3-0.6B 的 .safetensors 权重文件（如 model.safetensors），\n"
                f"   放到 {os.path.join(base, 'Qwen3-0.6B')} 文件夹里即可（程序会自动用内置配置加载）\n\n"
                "下载地址（国内镜像）：https://hf-mirror.com/Qwen/Qwen3-0.6B")
        if qwen3_path is None:
            raise RuntimeError(f"Qwen3-0.6B 仍未就绪，请检查：{os.path.join(base, 'Qwen3-0.6B')}")
    vae_dir = os.path.join(base, "Anima_vae")
    vae_file = None
    # 兼容新旧目录：先扫标准位置，再扫旧版 Kohya_ss 目录
    for _b in bases:
        _vd = os.path.join(_b, "Anima_vae")
        if os.path.isdir(_vd):
            for root, _dirs, files in os.walk(_vd):
                for f in files:
                    if f.lower().endswith((".safetensors", ".pth")):
                        vae_file = os.path.join(root, f)
                        break
                if vae_file:
                    break
        if vae_file:
            break
    if not vae_file:
        # 用国内直链直接下载（与 Krea2/FLUX2 模型下载一致），不依赖 huggingface_hub 的
        # snapshot_download（snapshot_download 对 allow_patterns 匹配/repo 结构敏感，易失败）
        logf("[Anima] 首次使用需要下载 Qwen-Image VAE（约 0.3GB，国内直链）…")
        vae_url = "https://hf-mirror.com/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors"
        vae_dest = os.path.join(vae_dir, "qwen_image_vae.safetensors")
        try:
            os.makedirs(vae_dir, exist_ok=True)
            if not (os.path.isfile(vae_dest) and os.path.getsize(vae_dest) > 1024 * 1024):
                if not _download_with_resume(vae_url, vae_dest, logf):
                    raise RuntimeError("下载中断，请重试（断点续传）")
            vae_file = vae_dest
        except Exception as e:
            raise RuntimeError(f"Qwen-Image VAE 自动下载失败：{e}")
        if os.path.isdir(vae_dir):
            for root, _dirs, files in os.walk(vae_dir):
                for f in files:
                    if f.lower().endswith((".safetensors", ".pth")):
                        vae_file = os.path.join(root, f)
                        break
                if vae_file:
                    break
    if not vae_file:
        raise RuntimeError(f"未找到 Qwen-Image VAE 文件，请手动下载后放到：{vae_dir}")
    logf(f"[Anima] Qwen3: {qwen3_path}")
    logf(f"[Anima] VAE: {vae_file}")
    return qwen3_path, vae_file


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.busy = False
        self.ui_proc = None
        self.mode = "style"
        self.base_type = "sd15"
        self._manual_override = set()
        self._applying_preset = False
        self._env_ok = False
        self._kohya_ok = False
        self._base_models = []
        self._base_items = []
        self._downloading = False
        self._dl = None
        self._btn_anim = {}
        self._build_ui()
        self._refresh_status()
        self._scan_base_models()
        # 首次打开即创建可写数据目录（output/logs/dataset/tokenizers 重定向到 %APPDATA%）
        for _sub in ("output", "logs", "dataset", "tokenizers"):
            data_sub(_sub)
        self.root.after(100, self._poll)

    def _build_ui(self):
        self.root.title(APP_NAME)
        self.root.geometry("1180x860")
        self.root.minsize(1040, 760)

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        self.style = style
        self.root.configure(bg=ROOT_BG)
        # 窗口标题栏图标（存在则用）
        try:
            ico = os.path.join(KIT_DIR, "app.ico")
            if os.path.isfile(ico):
                self.root.iconbitmap(ico)
        except Exception:
            pass

        style.configure("TFrame", background=ROOT_BG)
        style.configure("TLabel", background=ROOT_BG, foreground="#374151")
        style.configure("TPanedwindow", background=ROOT_BG)
        style.configure("Header.TLabel", font=("Microsoft YaHei UI", 14, "bold"),
                        background=ROOT_BG, foreground="#1F2937")
        style.configure("Hint.TLabel", font=("Microsoft YaHei UI", 9),
                        background=ROOT_BG, foreground="#6B7280")
        style.configure("Tip.TLabel", font=("Microsoft YaHei UI", 9),
                        background=ROOT_BG, foreground="#1a7f37")
        style.configure("Warn.TLabel", font=("Microsoft YaHei UI", 9),
                        background=ROOT_BG, foreground="#b3261e")
        style.configure("Guide.TLabel", font=("Microsoft YaHei UI", 10),
                        background=ROOT_BG, foreground="#374151")

        # 按钮：主色底白字（clam 圆角平底）
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(14, 7),
                        background=INDIGO, foreground="#FFFFFF", borderwidth=0,
                        focusthickness=0, relief="flat")
        style.map("TButton", background=[("active", INDIGO_HOVER), ("pressed", INDIGO)],
                  foreground=[("disabled", "#B8BCC6")], relief=[("pressed", "flat")])
        # 悬停渐变样式组（5 帧）
        self._btn_ramp_names = []
        for i, c in enumerate([_lerp_color(INDIGO, INDIGO_HOVER, t) for t in (i / 4.0 for i in range(5))]):
            n = f"Accent{i}.TButton"
            style.configure(n, font=("Microsoft YaHei UI", 10), padding=(14, 7),
                            background=c, foreground="#FFFFFF", borderwidth=0,
                            focusthickness=0, relief="flat")
            self._btn_ramp_names.append(n)
        style.configure("AccentFlash.TButton", font=("Microsoft YaHei UI", 10), padding=(14, 7),
                        background="#FFFFFF", foreground=INDIGO, borderwidth=0,
                        focusthickness=0, relief="flat")
        # 一键大按钮（12 号加粗，悬停轻微放大）
        self._big_ramp_names = []
        for i, c in enumerate([_lerp_color(INDIGO, INDIGO_HOVER, t) for t in (i / 4.0 for i in range(5))]):
            n = f"BigAccent{i}.TButton"
            style.configure(n, font=("Microsoft YaHei UI", 12, "bold"), padding=(14 + i * 2, 8 + i * 2),
                            background=c, foreground="#FFFFFF", borderwidth=0,
                            focusthickness=0, relief="flat")
            self._big_ramp_names.append(n)
        # 禁用态（训练中按钮置灰但保留底色）
        for n in self._btn_ramp_names + self._big_ramp_names:
            try:
                self.style.map(n, background=[("disabled", "#A6A9D8")],
                               foreground=[("disabled", "#F0F1FF")])
            except Exception:
                pass
        # 提示文字淡入帧
        for i, fg in enumerate(["#9CA3AF", "#6B7280", "#111827"]):
            self.style.configure(f"TipFade{i}.TLabel", font=("Microsoft YaHei UI", 9),
                                 background=ROOT_BG, foreground=fg)

        # LabelFrame：标题加粗、淡边框
        style.configure("TLabelframe", background=ROOT_BG, bordercolor=BORDER,
                        relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=ROOT_BG, foreground="#1F2937",
                        font=("Microsoft YaHei UI", 10, "bold"))
        # Combobox / Entry：浅色圆角边框
        style.configure("TCombobox", fieldbackground="#FFFFFF", background="#FFFFFF",
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                        arrowcolor=INDIGO, foreground="#1F2937", padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", "#FFFFFF")],
                  selectbackground=[("readonly", "#FFFFFF")])
        style.configure("TEntry", fieldbackground="#FFFFFF", bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER, foreground="#1F2937", padding=4)
        style.configure("TCheckbutton", background=ROOT_BG, foreground="#374151")
        style.map("TCheckbutton", background=[("active", ROOT_BG)])
        style.configure("TProgressbar", background=INDIGO, troughcolor="#E5E7EB",
                        bordercolor="#E5E7EB", lightcolor=INDIGO)
        style.configure("Vertical.TScrollbar", background="#C9CDD6", troughcolor=ROOT_BG,
                        bordercolor=ROOT_BG, arrowcolor="#6B7280", width=12, relief="flat")
        style.map("Vertical.TScrollbar", background=[("active", INDIGO)])

        top = ttk.Frame(self.root, padding=(12, 12, 12, 0))
        top.pack(side="top", fill="x")
        ttk.Label(top, text=APP_NAME, style="Header.TLabel").pack(anchor="w")
        self.status_var = tk.StringVar(value="正在检测环境…")
        self.status_row = ttk.Frame(top)
        self.status_row.pack(anchor="w", pady=(4, 0))
        self._status_dots = {}
        self._status_texts = {}
        for i, key in enumerate(["git", "python", "kohya", "gpu", "vram"]):
            if i:
                ttk.Label(self.status_row, text="|", style="Hint.TLabel").pack(side="left", padx=6)
            c = tk.Canvas(self.status_row, width=12, height=12, bg=ROOT_BG, highlightthickness=0)
            c.pack(side="left", padx=(0, 4))
            self._status_dots[key] = c
            lbl = ttk.Label(self.status_row, text="", style="Hint.TLabel")
            lbl.pack(side="left")
            self._status_texts[key] = lbl
        ttk.Label(top, textvariable=self.status_var, style="Hint.TLabel").pack(anchor="w", pady=(2, 0))

        # ---- 顶部：训练模式 + 底模选择 ----
        mode_row = ttk.Frame(top)
        mode_row.pack(fill="x", pady=(8, 2))
        ttk.Label(mode_row, text="训练模式：", font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        self.mode_combo = ttk.Combobox(mode_row, state="readonly", width=20,
                                       values=[MODE_LABELS[k] for k in MODE_KEYS])
        self.mode_combo.current(0)
        self.mode_combo.pack(side="left", padx=(0, 10))
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_change)

        ttk.Label(mode_row, text="底模：", font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        self.base_combo = ttk.Combobox(mode_row, state="readonly", width=16,
                                       values=[BASE_TYPE_LABELS[k] for k in BASE_TYPE_KEYS])
        self.base_combo.current(0)
        self.base_combo.pack(side="left", padx=(0, 6))
        self.base_combo.bind("<<ComboboxSelected>>", self._on_base_change)
        self.btn_pick_base = ttk.Button(mode_row, text="选择底模文件…", command=self.cmd_pick_base)
        self.btn_pick_base.pack(side="left", padx=(0, 6))
        self.base_model_var = tk.StringVar()
        self.base_disp_var = tk.StringVar()
        self.base_disp_var.set("（未选择模型，点【选择底模文件…】或下载）")
        self.base_model_lbl = ttk.Label(mode_row, textvariable=self.base_disp_var, style="Hint.TLabel",
                                        width=34, anchor="w")
        self.base_model_lbl.pack(side="left", padx=(0, 6))
        self.btn_refresh_base = ttk.Button(mode_row, text="↻ 刷新", command=self.cmd_refresh_base)
        self.btn_refresh_base.pack(side="left", padx=(0, 4))
        self.btn_open_base_dir = ttk.Button(mode_row, text="打开模型文件夹", command=self.cmd_open_base_dir)
        self.btn_open_base_dir.pack(side="left", padx=(0, 4))
        self.btn_download_base = ttk.Button(mode_row, text="没有模型？点这里下载", command=self.cmd_download_base)
        self.btn_download_base.pack(side="left", padx=(0, 10))
        ttk.Button(mode_row, text="↺ 恢复预设", command=self.cmd_reset_presets).pack(side="left")

        # ---- 原始图片文件夹行（一键按钮在左侧新手引导第⑤步） ----
        data_row = ttk.Frame(top)
        data_row.pack(fill="x", pady=(6, 2))
        ttk.Label(data_row, text="原始图片文件夹：").pack(side="left")
        self.raw_dir_var = tk.StringVar()
        self.raw_entry = ttk.Entry(data_row, textvariable=self.raw_dir_var, width=58)
        self.raw_entry.pack(side="left", padx=(0, 6))
        self.btn_pick_raw = ttk.Button(data_row, text="浏览…", command=self.cmd_pick_raw)
        self.btn_pick_raw.pack(side="left")
        ttk.Label(data_row, text="（按左侧新手引导 ①②③④⑤ 顺序操作）", style="Hint.TLabel").pack(side="left", padx=(8, 0))

        # ---- Trigger 触发词（两种模式都显示；人物=角色名，画风=画风专属词） ----
        self.trig_frame = ttk.LabelFrame(top, text="🔑 Trigger 触发词（可选）", padding=8)
        r1 = ttk.Frame(self.trig_frame)
        r1.pack(fill="x")
        ttk.Label(r1, text="Trigger 触发词：").pack(side="left")
        self.trigger_var = tk.StringVar()
        self.trigger_entry = ttk.Entry(r1, textvariable=self.trigger_var, width=30)
        self.trigger_entry.pack(side="left", padx=(0, 6))
        ttk.Label(r1, text="（支持逗号分隔多个；自动插入每张标签最开头）", style="Hint.TLabel").pack(side="left")
        self.trigger_hint_var = tk.StringVar()
        self.trigger_hint = ttk.Label(self.trig_frame, textvariable=self.trigger_hint_var,
                                      style="Hint.TLabel", justify="left", wraplength=660)
        self.trigger_hint.pack(fill="x", pady=(4, 0))
        self.trig_frame.pack(fill="x", pady=(4, 0))

        # ---- 人物模式专属控件（正则数据集，画风模式自动隐藏，带滑入动画） ----
        self.char_slide = tk.Canvas(top, height=0, bg=ROOT_BG, highlightthickness=0)
        self.char_frame = ttk.LabelFrame(self.char_slide, text="👤 人物模式专属设置（正则数据集，画风模式自动隐藏）", padding=8)
        self._char_win = self.char_slide.create_window((0, 0), window=self.char_frame, anchor="nw")
        self.char_slide.bind("<Configure>", lambda e: self.char_slide.itemconfigure(self._char_win, width=e.width))
        r2 = ttk.Frame(self.char_frame)
        r2.pack(fill="x")
        ttk.Label(r2, text="正则数据集：").pack(side="left")
        self.reg_var = tk.StringVar()
        self.reg_entry = ttk.Entry(r2, textvariable=self.reg_var, width=44)
        self.reg_entry.pack(side="left", padx=(0, 6))
        self.btn_pick_reg = ttk.Button(r2, text="选择文件夹…", command=self.cmd_pick_reg)
        self.btn_pick_reg.pack(side="left")
        ttk.Label(r2, text="（可选，用于防过拟合）", style="Hint.TLabel").pack(side="left", padx=(6, 0))

        # ---- 全局提示词（两种模式都显示；不写入图片 txt） ----
        self.global_frame = ttk.LabelFrame(top, text="✨ 附加全局提示词（训练全局参数，不写入图片标签，可留空）", padding=8)
        gr1 = ttk.Frame(self.global_frame)
        gr1.pack(fill="x")
        ttk.Label(gr1, text="正向全局提示词：").pack(side="left")
        self.global_pos_var = tk.StringVar()
        self.global_pos_entry = ttk.Entry(gr1, textvariable=self.global_pos_var, width=52)
        self.global_pos_entry.pack(side="left", padx=(0, 6))
        ttk.Label(gr1, text="（训练时自动加到每张标签最前面）", style="Hint.TLabel").pack(side="left")
        gr2 = ttk.Frame(self.global_frame)
        gr2.pack(fill="x", pady=(6, 0))
        ttk.Label(gr2, text="负向全局提示词：").pack(side="left")
        self.global_neg_var = tk.StringVar()
        self.global_neg_entry = ttk.Entry(gr2, textvariable=self.global_neg_var, width=52)
        self.global_neg_entry.pack(side="left", padx=(0, 6))
        ttk.Label(gr2, text="（写入使用模板/参数报告；kohya 训练不使用负向提示词）", style="Hint.TLabel").pack(side="left")
        self.global_frame.pack(fill="x", pady=(4, 0))

        self.tip_label = ttk.Label(top, textvariable=None, style="Tip.TLabel",
                                   wraplength=1080, justify="left")
        self.tip_var = tk.StringVar()
        self.tip_label.configure(textvariable=self.tip_var)
        self.tip_label.pack(anchor="w", pady=(2, 4), fill="x")

        main = ttk.Panedwindow(self.root, orient="horizontal")
        main.pack(fill="both", expand=True, padx=12, pady=(8, 12))

        # ---- 左侧可滚动容器（内容多时自动出现滚动条） ----
        left_wrap = ttk.Frame(main)
        main.add(left_wrap, weight=0)
        self.left_canvas = tk.Canvas(left_wrap, width=410, highlightthickness=0, bg=ROOT_BG)
        self.left_sb = ttk.Scrollbar(left_wrap, orient="vertical", style="Vertical.TScrollbar",
                                     command=self.left_canvas.yview)
        self.left_canvas.configure(yscrollcommand=self.left_sb.set)
        self.left_canvas.pack(side="left", fill="both", expand=True)
        self.left_sb.pack(side="right", fill="y")
        left = ttk.Frame(self.left_canvas, padding=6)
        self._left_id = self.left_canvas.create_window((0, 0), window=left, anchor="nw")

        def _on_left_configure(_e=None):
            self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all"))

        def _on_canvas_configure(e):
            self.left_canvas.itemconfigure(self._left_id, width=e.width)

        def _on_wheel(e):
            self.left_canvas.yview_scroll(int(-e.delta / 120), "units")

        left.bind("<Configure>", _on_left_configure)
        self.left_canvas.bind("<Configure>", _on_canvas_configure)
        self.left_canvas.bind("<MouseWheel>", _on_wheel)
        left.bind("<MouseWheel>", _on_wheel)

        # ---- 新手引导（按顺序做） ----
        guide = ttk.LabelFrame(left, text="🎓 新手引导（按顺序做，鼠标悬停看说明）", padding=6)
        guide.pack(fill="x", pady=(0, 6))
        self.guide_env = tk.StringVar()
        self.guide_kohya = tk.StringVar()
        self.guide_base = tk.StringVar()
        self.guide_raw = tk.StringVar()

        def _grow(row, text, var, btn_text, cmd, width=10):
            ttk.Label(guide, text=text, style="Guide.TLabel", anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 6), pady=2)
            ttk.Label(guide, textvariable=var, width=9, anchor="w").grid(row=row, column=1, sticky="w")
            b = ttk.Button(guide, text=btn_text, command=cmd, width=width)
            b.grid(row=row, column=2, sticky="e", pady=2)
            return b

        self.btn_env = _grow(0, "① 环境准备（Git / Python）", self.guide_env, "去准备", self.cmd_env)
        self.btn_install = _grow(1, "② 安装训练内核（Kohya-SS）", self.guide_kohya, "去安装", self.cmd_install)
        self.btn_guide_base = _grow(2, "③ 选择底模 + 训练模式", self.guide_base, "去选底模", self.cmd_pick_base)
        self.btn_guide_raw = _grow(3, "④ 选择原始图片文件夹", self.guide_raw, "去选文件夹", self.cmd_pick_raw)
        self.btn_one_click = ttk.Button(guide, text="🚀 一键开始训练（自动预处理+训练）",
                                        command=self.cmd_one_click_train, style="BigAccent0.TButton")
        self.btn_one_click.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 2))
        self.busy_spin = ttk.Label(guide, text="", style="Hint.TLabel", font=("Microsoft YaHei UI", 12))
        self.busy_spin.grid(row=4, column=3, padx=(6, 0))
        self.guide_next = tk.StringVar()
        ttk.Label(guide, textvariable=self.guide_next, style="Tip.TLabel", wraplength=300,
                  justify="left").grid(row=5, column=0, columnspan=3, sticky="w", pady=(2, 0))

        # ---- 老手 / 附加工具 ----
        tools = ttk.LabelFrame(left, text="🔧 老手 / 附加工具", padding=6)
        tools.pack(fill="x", pady=(0, 6))
        self.btn_pre = ttk.Button(tools, text="③ 数据预处理", command=self.cmd_preprocess)
        self.btn_pre.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        self.btn_train = ttk.Button(tools, text="⑥ 一键训练", command=self.cmd_train)
        self.btn_train.grid(row=0, column=1, sticky="ew", padx=2, pady=2)
        self.btn_ui = ttk.Button(tools, text="④ 启动 Web UI", command=self.cmd_start_ui)
        self.btn_ui.grid(row=1, column=0, sticky="ew", padx=2, pady=2)
        self.btn_ui_stop = ttk.Button(tools, text="⑤ 停止 Web UI", command=self.cmd_stop_ui)
        self.btn_ui_stop.grid(row=1, column=1, sticky="ew", padx=2, pady=2)
        self.btn_readme = ttk.Button(tools, text="⑦ 使用说明", command=self.cmd_readme)
        self.btn_readme.grid(row=2, column=0, sticky="ew", padx=2, pady=2)
        self.btn_out = ttk.Button(tools, text="⑧ 输出文件夹", command=self.cmd_open_output)
        self.btn_out.grid(row=2, column=1, sticky="ew", padx=2, pady=2)
        self.btn_about = ttk.Button(tools, text="⑨ 关于", command=self.cmd_about)
        self.btn_about.grid(row=3, column=0, columnspan=2, sticky="ew", padx=2, pady=2)
        tools.columnconfigure(0, weight=1)
        tools.columnconfigure(1, weight=1)

        # ---- 高级参数面板（默认收起） ----
        self.adv = ttk.LabelFrame(left, text="高级参数（老手向，默认收起）", padding=8)
        adv = self.adv
        adv.pack(fill="x", pady=(0, 6))
        self.adv_collapsed = tk.BooleanVar(value=True)
        ttk.Checkbutton(adv, text="展开高级参数（可手动修改，改过后不再被自动覆盖）",
                        variable=self.adv_collapsed, command=self._toggle_adv).grid(
            row=0, column=0, columnspan=4, sticky="w")
        self.adv_canvas = tk.Canvas(adv, height=0, bg=ROOT_BG, highlightthickness=0)
        self.adv_canvas.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        self.adv_body = ttk.Frame(self.adv_canvas)
        self._adv_win = self.adv_canvas.create_window((0, 0), window=self.adv_body, anchor="nw")
        self.adv_canvas.bind("<Configure>", lambda e: self.adv_canvas.itemconfigure(self._adv_win, width=e.width))
        self.param_vars = {}

        def _mk(key, label, row, col):
            ttk.Label(self.adv_body, text=label).grid(row=row, column=col * 2, sticky="w", padx=(0, 4), pady=2)
            var = tk.StringVar()
            ent = ttk.Entry(self.adv_body, textvariable=var, width=11)
            ent.grid(row=row, column=col * 2 + 1, sticky="w", pady=2)
            var.trace_add("write", self._manual_trace(key))
            Tooltip(ent, PARAM_TIPS.get(key, ""))
            self.param_vars[key] = var
            return var

        _mk("rank", "rank（LoRA秩）", 0, 0)
        _mk("alpha", "alpha（缩放）", 0, 1)
        _mk("unet_lr", "学习率", 1, 0)
        _mk("te_lr", "文本编码器学习率", 1, 1)
        _mk("repeats", "repeats（重复次数）", 2, 0)
        _mk("max_epochs", "最大 epoch", 2, 1)

        self.unet_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.adv_body, text="只训练 UNet（不训练文本编码器）",
                        variable=self.unet_only_var).grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Label(self.adv_body, text="梯度检查点：").grid(row=4, column=0, sticky="w", pady=(4, 0))
        self.gc_var = tk.StringVar(value="自动")
        ttk.Combobox(self.adv_body, textvariable=self.gc_var, state="readonly", width=8,
                     values=["自动", "开启", "关闭"]).grid(row=4, column=1, columnspan=2, sticky="w", pady=(4, 0))

        self.disclaimer_lbl = ttk.Label(left, text="⚠ 免责：禁止训练版权画师作品、受版权保护的真人素材。\n基于 kohya-ss sd-scripts（Apache-2.0）二次封装，MIT 开源。",
                                        style="Warn.TLabel", wraplength=300, justify="left")
        self.disclaimer_lbl.pack(anchor="w", pady=(4, 0))
        # 滚轮在左侧各面板上也可滚动
        for _w in (guide, tools, self.adv, self.disclaimer_lbl):
            try:
                _w.bind("<MouseWheel>", _on_wheel)
            except Exception:
                pass

        right = ttk.Frame(main, padding=6)
        main.add(right, weight=1)
        ttk.Label(right, text="运行日志", style="Header.TLabel").pack(anchor="w", pady=(0, 6))

        # ---- 底模下载进度区（默认隐藏） ----
        self.dl_frame = ttk.LabelFrame(right, text="⬇ 底模下载", padding=6)
        self.dl_status_var = tk.StringVar(value="")
        ttk.Label(self.dl_frame, textvariable=self.dl_status_var, style="Hint.TLabel",
                  wraplength=680, justify="left").pack(anchor="w", fill="x")
        self.dl_progress = ttk.Progressbar(self.dl_frame, maximum=100, value=0)
        self.dl_progress.pack(fill="x", pady=(4, 4))
        self.btn_dl_cancel = ttk.Button(self.dl_frame, text="取消下载", command=self.cmd_dl_cancel)
        self.btn_dl_cancel.pack(anchor="e")

        log_border = tk.Frame(right, height=2, bg=BORDER)
        log_border.pack(fill="x", pady=(0, 4))
        self.txt = scrolledtext.ScrolledText(right, state="disabled", wrap="word",
                                             font=("Consolas", 9), background=LOG_BG,
                                             foreground=LOG_FG, borderwidth=0,
                                             highlightthickness=0, padx=6, pady=6)
        self.txt.tag_configure("ok", foreground="#9ECE6A")
        self.txt.tag_configure("warn", foreground="#E0AF68")
        self.txt.tag_configure("err", foreground="#F7768E")
        self.txt.tag_configure("train", foreground="#7AA2F7")
        self.txt.tag_configure("model", foreground="#BB9AF7")
        self.txt.tag_configure("info", foreground=LOG_FG)
        self.txt.pack(fill="both", expand=True)
        try:
            self.txt.vbar.configure(relief="flat", width=12, bg="#2A2C3A", troughcolor=LOG_BG,
                                    activebackground=INDIGO, highlightthickness=0, borderwidth=0)
        except Exception:
            pass

        self._toggle_adv()
        self._attach_tooltips()
        self._refresh_guide()
        self._on_mode_change()
        # 引导状态随输入自动刷新（env/kohya 状态由 _refresh_status 更新）
        self.raw_dir_var.trace_add("write", lambda *a: self._refresh_guide())
        self.base_model_var.trace_add("write", lambda *a: self._refresh_guide())
        self._apply_hover_all()

    def _refresh_guide(self):
        """刷新新手引导各步骤状态与「下一步该做什么」提示。"""
        try:
            env_ok = getattr(self, "_env_ok", False)
            kohya_ok = getattr(self, "_kohya_ok", False)
            base = self.base_model_var.get().strip()
            base_ok = bool(base) and os.path.isfile(base)
            raw = self.raw_dir_var.get().strip()
            raw_ok = bool(raw) and os.path.isdir(raw) and any(
                f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"))
                for f in os.listdir(raw)) if (raw and os.path.isdir(raw)) else False

            self.guide_env.set("✓ 已完成" if env_ok else "○ 未完成")
            self.guide_kohya.set("✓ 已完成" if kohya_ok else "○ 未完成")
            self.guide_base.set("✓ 已选" if base_ok else "○ 未选")
            self.guide_raw.set("✓ 已选" if raw_ok else "○ 未选")

            if not env_ok:
                nxt = "① 先点「去准备」安装 Git / Python"
                target = self.btn_env
            elif not kohya_ok:
                nxt = "② 先点「去安装」装好训练内核"
                target = self.btn_install
            elif not base_ok:
                nxt = "③ 在顶部选择底模（会自动识别 SD1.5 / SDXL）"
                target = self.btn_guide_base
            elif not raw_ok:
                nxt = "④ 在顶部选择原始图片文件夹"
                target = self.btn_guide_raw
            else:
                nxt = "⑤ 全部就绪，点【🚀 一键开始训练】！"
                target = self.btn_one_click
            self.guide_next.set("▶ 下一步：" + nxt)
            self._highlight_next(target if not getattr(self, "busy", False) else None)
        except Exception:
            pass

    def _tip(self, widget, text):
        if widget is not None and hasattr(widget, "bind") and text:
            Tooltip(widget, text)

    def _attach_tooltips(self):
        """给所有控件挂通俗中文悬停提示。"""
        tips = [
            (self.mode_combo, "训练模式：🎨画风=只学绘画风格（不学脸/角色）；👤人物=学某个角色的脸、服饰、特征。切换会自动填好推荐参数。"),
            (self.base_combo, "底模类型：SD1.5 用 512 分辨率；SDXL 用 1024 分辨率（更吃显存）。点「选择底模文件」选完会自动识别。"),
            (self.btn_pick_base, "手动浏览选择本机的 .safetensors / .ckpt 底模；选完自动识别类型。"),
            (self.btn_refresh_base, "重新扫描默认模型文件夹，把新放入的底模列进下拉。"),
            (self.btn_open_base_dir, "打开默认底模存放文件夹（项目内 models\\base）。"),
            (self.btn_download_base, "没有底模？点这里选下载方式：推荐「应用内下载」（软件里直接下载，带进度/断点续传/下完自动识别），也可选浏览器极速下载（魔搭）或备用下载（hf-mirror）。"),
            (self.base_model_lbl, "当前选中的底模文件（显示文件名）。未选择时点【选择底模文件…】或【没有模型？点这里下载】。"),
            (self.raw_entry, "放原始图片的文件夹（支持 jpg/png/webp/bmp/tif/gif）。"),
            (self.btn_pick_raw, "选择原始图片文件夹。"),
            (self.btn_guide_base, "第③步：选择底模（会自动识别 SD1.5 / SDXL）。"),
            (self.btn_guide_raw, "第④步：选择原始图片文件夹。"),
            (self.btn_one_click, "小白专用：自动过滤模糊/过小/损坏图 → 正方形裁剪 → 去重 → 打标签 → 开始训练，全程不用管。"),
            (self.trigger_entry, "触发词：相当于模型的“召唤词”。人物模式=角色名；画风模式=画风专属词。推理时用它唤起。支持多个，用英文逗号分隔（如 ohwx, mychar）。"),
            (self.reg_entry, "正则图：同一角色的参考图文件夹，训练时防止模型学过头（可选）。"),
            (self.btn_pick_reg, "选择正则数据集文件夹（人物模式可选）。"),
            (self.global_pos_entry, "附加全局正向提示词：训练时自动加到每张图片标签最前面（例如 masterpiece），不写进图片的 txt 文件，可留空。"),
            (self.global_neg_entry, "附加全局负向提示词：会写进使用模板和参数报告；kohya 训练本身不使用负向提示词，可留空。"),
            (self.unet_only_var, "只训练 UNet（不训练文本编码器）：更省显存、更稳，画风类可以勾选。"),
            (self.gc_var, "梯度检查点：省显存换速度；「自动」= 按你的显存自动决定开/关。"),
            (self.btn_env, "第①步：检测并安装 Git 和 Python（项目内置安装包，一般无需手动装）。"),
            (self.btn_install, "第②步：安装 Kohya-SS 训练内核（内置源码包 + 国内镜像，不需要代理/GitHub）。"),
            (self.btn_pre, "数据预处理：缩放/去黑边/去水印/打标签。一键开始训练会自动做，老手可单独用。"),
            (self.btn_ui, "打开 kohya 网页界面（高级用户用）。"),
            (self.btn_ui_stop, "停止正在运行的网页界面。"),
            (self.btn_train, "用已经预处理好的数据直接训练（老手流程，⑥）。"),
            (self.btn_readme, "打开使用说明文档（README）。"),
            (self.btn_out, "打开输出文件夹：模型、使用模板、参数报告、中间快照。"),
            (self.btn_about, "开源协议（MIT + kohya Apache-2.0）与免责提示。"),
        ]
        for w, t in tips:
            self._tip(w, t)

    # ---------- 动画 ----------
    def _apply_hover_all(self):
        """给所有 ttk.Button 挂悬停渐变。"""
        def walk(w):
            for child in w.winfo_children():
                if isinstance(child, ttk.Button):
                    self._bind_hover(child, big=(child is self.btn_one_click))
                walk(child)
        walk(self.root)

    def _bind_hover(self, btn, big=False):
        key = id(btn)
        self._btn_anim[key] = {"names": self._big_ramp_names if big else self._btn_ramp_names,
                               "idx": 0, "after": None}
        def _enter(_e=None):
            if btn is getattr(self, "_guide_flash_btn", None):
                self._stop_guide_flash()
            self._anim_btn(btn, 4)
        def _leave(_e=None):
            self._anim_btn(btn, 0)
        btn.bind("<Enter>", _enter, add="+")
        btn.bind("<Leave>", _leave, add="+")

    def _anim_btn(self, btn, target):
        key = id(btn)
        st = self._btn_anim.get(key)
        if not st:
            return
        if st["after"]:
            try:
                self.root.after_cancel(st["after"])
            except Exception:
                pass
            st["after"] = None
        def step():
            cur = st["idx"]
            if cur < target:
                cur += 1
            elif cur > target:
                cur -= 1
            st["idx"] = cur
            try:
                btn.configure(style=st["names"][cur])
            except Exception:
                pass
            if cur != target:
                st["after"] = self.root.after(30, step)
            else:
                st["after"] = None
        step()

    def _start_busy_anim(self):
        """训练中：按钮文字动态省略号 + 旋转图标。"""
        self._stop_busy_anim()
        st = {"dots": 0, "spin": 0, "after": None}
        self._busy_anim = st
        self._oneclick_text = self.btn_one_click.cget("text")
        def tick():
            st["dots"] = (st["dots"] + 1) % 4
            try:
                self.btn_one_click.configure(text="训练中" + "." * st["dots"])
                self.busy_spin.configure(text="\u25d0\u25d3\u25d1\u25d2"[st["spin"] % 4])
            except Exception:
                pass
            st["spin"] += 1
            st["after"] = self.root.after(500, tick)
        tick()

    def _stop_busy_anim(self):
        st = getattr(self, "_busy_anim", None)
        if st and st.get("after"):
            try:
                self.root.after_cancel(st["after"])
            except Exception:
                pass
        self._busy_anim = None
        try:
            self.btn_one_click.configure(text=getattr(self, "_oneclick_text", "🚀 一键开始训练（自动预处理+训练）"))
            self.busy_spin.configure(text="")
        except Exception:
            pass

    def _highlight_next(self, btn):
        """新手引导“下一步”按钮呼吸闪烁。"""
        if btn is getattr(self, "_guide_flash_btn", None):
            return
        self._stop_guide_flash()
        if btn is None:
            return
        self._guide_flash_btn = btn
        st = {"on": False, "after": None}
        self._guide_flash_state = st
        def tick():
            st["on"] = not st["on"]
            try:
                if btn is self.btn_one_click:
                    btn.configure(style="BigAccent4.TButton" if st["on"] else "BigAccent0.TButton")
                else:
                    btn.configure(style="AccentFlash.TButton" if st["on"] else "Accent0.TButton")
            except Exception:
                pass
            st["after"] = self.root.after(800, tick)
        tick()

    def _stop_guide_flash(self):
        st = getattr(self, "_guide_flash_state", None)
        if st and st.get("after"):
            try:
                self.root.after_cancel(st["after"])
            except Exception:
                pass
        self._guide_flash_state = None
        btn = getattr(self, "_guide_flash_btn", None)
        self._guide_flash_btn = None
        if btn is not None:
            try:
                btn.configure(style="BigAccent0.TButton" if btn is self.btn_one_click else "Accent0.TButton")
            except Exception:
                pass

    def _fade_tip(self):
        """tip 文字淡入（灰→黑 3 帧）。"""
        if getattr(self, "_fade_after", None):
            try:
                self.root.after_cancel(self._fade_after)
            except Exception:
                pass
        self._fade_step = 0
        def step():
            i = self._fade_step
            try:
                self.tip_label.configure(style=f"TipFade{i}.TLabel")
            except Exception:
                pass
            self._fade_step += 1
            if i < 2:
                self._fade_after = self.root.after(40, step)
            else:
                self._fade_after = None
        step()

    def _slide_char(self, open_):
        """人物专属面板滑入/滑出。"""
        if getattr(self, "_char_after", None):
            try:
                self.root.after_cancel(self._char_after)
            except Exception:
                pass
            self._char_after = None
        if open_:
            self.char_slide.pack(fill="x", pady=(4, 0), before=self.global_frame)
            target = self.char_frame.winfo_reqheight()
            if target < 10:
                target = 140
            self.char_slide.configure(height=0)
            cur = 0
        else:
            cur = self.char_slide.winfo_height()
            target = 0
        steps = 10
        delta = (target - cur) / steps
        def step(i=0):
            h = int(cur + delta * (i + 1))
            if h < 0:
                h = 0
            self.char_slide.configure(height=h)
            if i < steps - 1:
                self._char_after = self.root.after(15, lambda: step(i + 1))
            else:
                self._char_after = None
                if not open_:
                    self.char_slide.pack_forget()
        step()

    def _anim_adv(self, open_):
        """高级参数面板平滑展开/收起。"""
        if getattr(self, "_adv_after", None):
            try:
                self.root.after_cancel(self._adv_after)
            except Exception:
                pass
            self._adv_after = None
        target = self.adv_body.winfo_reqheight() if open_ else 0
        if target < 10 and open_:
            target = 160
        cur = self.adv_canvas.winfo_height() if not open_ else 0
        steps = 10
        delta = (target - cur) / steps
        def step(i=0):
            h = int(cur + delta * (i + 1))
            if h < 0:
                h = 0
            self.adv_canvas.configure(height=h)
            if i < steps - 1:
                self._adv_after = self.root.after(20, lambda: step(i + 1))
            else:
                self._adv_after = None
        step()

    def _toggle_adv(self):
        open_ = not self.adv_collapsed.get()
        self._anim_adv(open_)

    def _btn(self, parent, text, cb):
        b = ttk.Button(parent, text=text, command=cb)
        b.pack(fill="x", pady=3)
        return b

    # ---- 模式/底模切换 / 预设 ----
    def _current_mode(self):
        try:
            return MODE_KEYS[self.mode_combo.current()]
        except Exception:
            return "style"

    def _current_base_type(self):
        try:
            return BASE_TYPE_KEYS[self.base_combo.current()]
        except Exception:
            return "sd15"

    def _manual_trace(self, key):
        def _on_write(*_a):
            if not getattr(self, "_applying_preset", False):
                self._manual_override.add(key)
        return _on_write

    def _apply_presets(self):
        self._applying_preset = True
        try:
            pre = PRESETS[self.mode][self.base_type]
            for k, v in pre.items():
                if k not in self._manual_override:
                    self.param_vars[k].set(v)
        finally:
            self._applying_preset = False

    def _on_mode_change(self, _event=None):
        self.mode = self._current_mode()
        self._apply_presets()
        self._update_mode_ui()

    def _on_base_change(self, _event=None):
        idx = self.base_combo.current()
        if idx < 0 or not getattr(self, "_base_items", None) or idx >= len(self._base_items):
            return
        kind, payload = self._base_items[idx][1], self._base_items[idx][2]
        if kind == "type":
            self._set_base_type(payload)
            model = self._find_model_of_type(payload)
            if model:
                self._set_base_model(model[0])
                self._log(f"[底模] 目录里找到 {BASE_TYPE_LABELS[payload]} 模型：{model[1]}")
            else:
                self._set_base_model("")
                # 延迟弹出，避免在下拉事件里直接弹窗卡界面
                self.root.after(60, lambda: self._ask_download_or_open(payload, allow_manual=False))
        elif kind == "file":
            path = payload
            self._set_base_model(path)
            bt = detect_base_type(path)
            if bt in BASE_TYPE_KEYS:
                self._set_base_type(bt)
                self._log(f"[底模] 已选择 {os.path.basename(path)}（{BASE_TYPE_LABELS[bt]}）")
            else:
                self._log(f"[底模] 已选择 {os.path.basename(path)}（类型待确认，可点「选择底模文件」重新识别）")
        self._refresh_guide()

    def _set_base_type(self, bt):
        """设置底模类型并应用预设（不触发下拉事件）。"""
        if bt not in BASE_TYPE_KEYS:
            return
        self.base_type = bt
        self._apply_presets()
        self._update_mode_ui()
        try:
            self.base_combo.current(BASE_TYPE_KEYS.index(bt))
        except Exception:
            pass
        self._refresh_guide()

    def _scan_base_models(self):
        """扫描默认底模目录，填充底模下拉（快捷类型 + 扫描到的模型文件）。"""
        try:
            d = base_models_dir()
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        self._base_models = scan_base_models()
        items = []
        for bt in BASE_TYPE_KEYS:
            items.append((BASE_TYPE_LABELS[bt], "type", bt))
        for p, n, t in self._base_models:
            label = f"📄 {n}"
            label += (f"（{BASE_TYPE_LABELS[t]}）" if t else "（待识别）")
            items.append((label, "file", p))
        self._base_items = items
        self.base_combo.configure(values=[i[0] for i in items])
        cur = self.base_model_var.get().strip()
        if cur:
            for i, it in enumerate(items):
                if it[2] == cur:
                    self.base_combo.current(i)
                    break
            else:
                self.base_combo.current(BASE_TYPE_KEYS.index(self.base_type))
        else:
            self.base_combo.current(BASE_TYPE_KEYS.index(self.base_type))
        self._refresh_guide()

    def _find_model_of_type(self, bt):
        for p, n, t in getattr(self, "_base_models", []):
            if t == bt:
                return (p, n, t)
        return None

    def _ask_download_or_open(self, base_type, allow_manual=False):
        """缺少底模弹窗：跳转下载（国内镜像）/ 打开模型文件夹（训练兜底时可选手动选文件）。"""
        label = BASE_TYPE_LABELS.get(base_type, "所选类型")
        dlg = tk.Toplevel(self.root)
        dlg.title("缺少基础底模")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        fname, fsize = HF_MODEL_INFO.get(base_type, ("模型文件", ""))
        msg = (f"未检测到对应版本的基础底模（{label}），训练必须要有基础底模。\n\n"
               f"点击【🚀 极速下载】用阿里魔搭直链下载（{fname}，{fsize}，国内快约 6 倍）；\n"
               "若太慢可点【备用下载】用 hf-mirror 下载；\n"
               "点击【打开模型文件夹】打开存放目录，下载完成后把模型文件丢到此文件夹即可。")
        tk.Label(dlg, text=msg, justify="left", wraplength=400, padx=18, pady=14,
                 font=("Microsoft YaHei UI", 10)).pack()
        btns = ttk.Frame(dlg)
        btns.pack(pady=(0, 14))
        result = {}

        def _act(k):
            result["action"] = k
            dlg.destroy()

        btns1 = ttk.Frame(dlg)
        btns1.pack(pady=(10, 2))
        ttk.Button(btns1, text="⬇ 应用内下载", command=lambda: _act("inapp")).pack(side="left", padx=6)
        ttk.Button(btns1, text="🚀 极速下载（魔搭）", command=lambda: _act("download_fast")).pack(side="left", padx=6)
        ttk.Button(btns1, text="备用下载（hf-mirror）", command=lambda: _act("download_fallback")).pack(side="left", padx=6)
        btns2 = ttk.Frame(dlg)
        btns2.pack(pady=(0, 14))
        ttk.Button(btns2, text="打开模型文件夹", command=lambda: _act("open")).pack(side="left", padx=6)
        if allow_manual:
            ttk.Button(btns2, text="手动选择文件", command=lambda: _act("manual")).pack(side="left", padx=6)
        else:
            ttk.Button(btns2, text="取消", command=lambda: _act(None)).pack(side="left", padx=6)
        dlg.grab_set()
        self.root.wait_window(dlg)
        action = result.get("action")
        if action == "inapp":
            self.cmd_dl_in_app(base_type)
        elif action == "download_fast":
            self._open_download_page(base_type, source="fast")
        elif action == "download_fallback":
            self._open_download_page(base_type, source="fallback")
        elif action == "open":
            self.cmd_open_base_dir()
        return action

    def _ensure_base_model(self):
        """确保已选底模：优先已选；否则用目录里第一个；都没有则弹窗引导。返回路径或 None。"""
        base = self.base_model_var.get().strip()
        if base and os.path.isfile(base):
            return base
        if getattr(self, "_base_models", None):
            p, n, t = self._base_models[0]
            self._set_base_model(p)
            if t:
                self._set_base_type(t)
            self._log(f"[底模] 自动选用目录模型：{n}")
            return p
        action = self._ask_download_or_open(self.base_type, allow_manual=True)
        if action == "manual":
            f = filedialog.askopenfilename(
                title="选择底模（.safetensors / .ckpt）",
                initialdir=base_models_dir(),
                filetypes=[("模型文件", "*.safetensors *.ckpt"), ("所有文件", "*.*")],
            )
            if f:
                self._set_base_model(f)
                self._detect_and_apply(f)
                return f
        return None

    def cmd_refresh_base(self):
        self._scan_base_models()
        self._log(f"[底模] 已刷新模型列表（目录：{base_models_dir()}）")

    def cmd_open_base_dir(self):
        d = base_models_dir()
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        os.startfile(d)  # noqa

    def _open_download_page(self, base_type=None, source="fast"):
        """打开对应版本底模的下载页。

        source="fast" 用阿里魔搭极速直链；source="fallback" 用 hf-mirror 备用直链。
        """
        bt = base_type or self.base_type
        if source == "fallback":
            url = HF_MIRROR_URLS.get(bt, HF_MIRROR_URL)
        else:
            url = MODELSCOPE_URLS.get(bt, HF_MIRROR_URL)
        webbrowser.open(url)

    def cmd_download_base(self):
        """“没有模型？点这里下载”按钮：弹出下载方式选择。"""
        self._download_choice_dialog()

    def _download_choice_dialog(self, bt=None):
        bt = bt or self.base_type
        label = BASE_TYPE_LABELS.get(bt, "底模")
        fname, fsize = HF_MODEL_INFO.get(bt, ("模型文件", ""))
        dlg = tk.Toplevel(self.root)
        dlg.title("下载基础底模")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        tk.Label(dlg, text=(
            f"当前底模类型：{label}\n"
            f"将下载：{fname}（{fsize}）\n"
            f"保存到：{base_models_dir()}\n\n"
            "推荐用「应用内下载」：软件里直接下载，带进度、断点续传、下完自动识别。"),
            justify="left", wraplength=440, padx=18, pady=12,
            font=("Microsoft YaHei UI", 10)).pack()
        btns = ttk.Frame(dlg)
        btns.pack(pady=(0, 14))
        result = {}

        def _act(k):
            result["action"] = k
            dlg.destroy()

        ttk.Button(btns, text="⬇ 应用内下载（推荐）", command=lambda: _act("inapp")).pack(side="left", padx=6)
        ttk.Button(btns, text="🌐 浏览器极速下载", command=lambda: _act("web_fast")).pack(side="left", padx=6)
        ttk.Button(btns, text="🔁 备用下载", command=lambda: _act("web_fallback")).pack(side="left", padx=6)
        ttk.Button(btns, text="📂 打开文件夹", command=lambda: _act("open")).pack(side="left", padx=6)
        dlg.grab_set()
        self.root.wait_window(dlg)
        action = result.get("action")
        if action == "inapp":
            self.cmd_dl_in_app(bt)
        elif action == "web_fast":
            self._open_download_page(bt, source="fast")
        elif action == "web_fallback":
            self._open_download_page(bt, source="fallback")
        elif action == "open":
            self.cmd_open_base_dir()

    def cmd_dl_in_app(self, bt=None):
        """应用内下载底模（带进度/断点续传/取消，下完自动识别）。"""
        if _ModelDownloader is None:
            messagebox.showerror(APP_NAME, "下载模块加载失败，请使用「浏览器极速下载」。")
            return
        if getattr(self, "_downloading", False):
            messagebox.showinfo(APP_NAME, "已有下载任务在进行中，请先完成或取消。")
            return
        bt = bt or self.base_type
        url = MODELSCOPE_URLS.get(bt) or HF_MIRROR_URLS.get(bt) or HF_MIRROR_URL
        fname, fsize = HF_MODEL_INFO.get(bt, (os.path.basename(url), ""))
        dest_dir = base_models_dir()
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except Exception:
            pass
        dest = os.path.join(dest_dir, fname)
        if os.path.isfile(dest):
            messagebox.showinfo(APP_NAME, f"{fname} 已存在，无需重复下载。")
            self._scan_base_models()
            return
        part = dest + ".part"
        if os.path.isfile(part) and os.path.getsize(part) > 0:
            if not messagebox.askyesno(
                    APP_NAME,
                    f"发现上次未完成的下载进度（{os.path.getsize(part) / 1048576:.1f} MB）。\n"
                    "要不要从断点继续下载？"):
                try:
                    os.remove(part)
                except Exception:
                    pass
        self._downloading = True
        self.btn_download_base.configure(state="disabled")
        self._show_dl_ui(True)
        self.dl_progress.configure(value=0, maximum=100)
        self.dl_status_var.set(f"正在准备下载 {fname}（{fsize}）…")
        self._log(f"[下载] 开始下载底模：{fname}（{fsize}）")
        self._log(f"[下载] 保存到：{dest}")
        self._dl = _ModelDownloader(url, dest,
                                    progress_cb=self._dl_progress_cb,
                                    done_cb=self._dl_done_cb,
                                    logf=self._log)
        self._dl.start()

    def _dl_progress_cb(self, done, total, speed):
        self.q.put(("DL_PROGRESS", done, total, speed))

    def _dl_done_cb(self, ok, dest):
        self.q.put(("DL_DONE", ok, dest))

    def _handle_dl_progress(self, done, total, speed):
        try:
            pct = (done / total * 100) if total else 0
            self.dl_progress.configure(value=pct)
            tot_mb = (total or 0) / 1048576
            mb = done / 1048576
            spd = (speed or 0) / 1048576
            self.dl_status_var.set(f"已下载 {mb:.1f} MB / {tot_mb:.1f} MB（{spd:.1f} MB/s）")
        except Exception:
            pass

    def _handle_dl_done(self, ok, dest):
        self._downloading = False
        self.btn_download_base.configure(state="normal")
        self._show_dl_ui(False)
        if ok:
            messagebox.showinfo(APP_NAME, f"底模下载完成：\n{dest}\n\n已自动扫描并加入底模列表。")
            self._scan_base_models()
        else:
            messagebox.showwarning(APP_NAME,
                                   "下载未完成（可能被取消或网络中断）。\n"
                                   "进度已保留，可再次下载从断点继续。")

    def cmd_dl_cancel(self):
        if getattr(self, "_dl", None) and self._dl.is_alive():
            self._dl.cancel()
            self.dl_status_var.set("正在取消…")

    def _show_dl_ui(self, visible):
        if visible:
            self.dl_frame.pack(fill="x", pady=(0, 6), before=self.txt)
        else:
            self.dl_frame.pack_forget()

    def _update_mode_ui(self):
        char_visible = (self.mode == "character")
        self._slide_char(char_visible)
        tip = DATASET_TIPS[self.mode]
        if BASE_TYPE_HINTS.get(self.base_type):
            tip += "\n" + BASE_TYPE_HINTS[self.base_type]
        self.tip_var.set(tip)
        self._fade_tip()
        if self.mode == "character":
            self.trigger_hint_var.set(TRIGGER_HINT_CHARACTER)
            self.btn_pre.configure(text="③ 数据预处理（人物）")
            self.btn_train.configure(text="⑥ 一键训练（人物 LoRA）")
        else:
            self.trigger_hint_var.set(TRIGGER_HINT_STYLE)
            self.btn_pre.configure(text="③ 数据预处理（画风）")
            self.btn_train.configure(text="⑥ 一键训练（画风 LoRA）")

    def cmd_reset_presets(self):
        self._manual_override.clear()
        self._apply_presets()
        self._log("已恢复当前模式+底模的全部预设参数（手动修改记录已清空）。")

    def _set_base_model(self, path):
        """设置当前底模路径，并在界面显示清晰的模型名/占位提示。"""
        self.base_model_var.set(path or "")
        p = (path or "").strip()
        if p and os.path.isfile(p) and p.lower().endswith((".safetensors", ".ckpt")):
            self.base_disp_var.set(f"📄 {os.path.basename(p)}")
        elif p:
            self.base_disp_var.set(f"⚠ {os.path.basename(p)}（不是有效的底模文件）")
        else:
            self.base_disp_var.set("（未选择模型，点【选择底模文件…】或下载）")

    def cmd_pick_base(self):
        d = base_models_dir()
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        f = filedialog.askopenfilename(
            title="选择底模（.safetensors / .ckpt，SD1.5 或 SDXL）",
            initialdir=d,
            filetypes=[("模型文件", "*.safetensors *.ckpt"), ("所有文件", "*.*")],
        )
        if not f:
            return
        if not os.path.isfile(f):
            messagebox.showwarning(APP_NAME, "请选择一个模型文件（.safetensors 或 .ckpt），不要选择文件夹。")
            return
        if not f.lower().endswith((".safetensors", ".ckpt")):
            messagebox.showwarning(APP_NAME, "请选择 .safetensors 或 .ckpt 格式的底模文件。")
            return
        self._set_base_model(f)
        self._detect_base_async(f)

    def _detect_base_async(self, path):
        self.status_var.set("正在识别底模类型…")
        threading.Thread(target=self._detect_base_worker, args=(path,), daemon=True).start()

    def _detect_base_worker(self, path):
        try:
            bt = detect_base_type(path)
        except Exception:
            bt = None
        self.q.put(("BASE_DETECTED", path, bt))

    def _detect_and_apply(self, path):
        """同步识别并应用底模类型（返回识别结果）。"""
        bt = detect_base_type(path)
        if bt in BASE_TYPE_KEYS:
            self._set_base_type(bt)
            self._log(f"[底模] 自动识别为 {BASE_TYPE_LABELS[bt]}：{os.path.basename(path)}")
        else:
            self._log(f"[底模] 未能自动识别：{os.path.basename(path)}，请手动选择底模类型。")
        return bt

    def _handle_base_detected(self, path, bt):
        self._refresh_status()
        if bt in BASE_TYPE_KEYS:
            self._set_base_type(bt)
            self._log(f"[底模] 自动识别为 {BASE_TYPE_LABELS[bt]}：{os.path.basename(path)}")
        else:
            self._log(f"[底模] 未能自动识别：{os.path.basename(path)}，请手动选择底模类型。")
            messagebox.showinfo(APP_NAME,
                                "没能认出这个底模是 SD1.5 还是 SDXL，\n请在「底模」下拉里手动选一下。")

    def cmd_pick_raw(self):
        d = filedialog.askdirectory(title="选择原始图片文件夹（小白一键流程用）")
        if d:
            self.raw_dir_var.set(d)

    def cmd_pick_reg(self):
        d = filedialog.askdirectory(title="选择正则数据集文件夹（人物模式）")
        if d:
            self.reg_var.set(d)

    def _collect_params(self):
        def _num(key, cast):
            s = self.param_vars[key].get().strip()
            try:
                return cast(s)
            except Exception:
                raise ValueError(f"参数「{PARAM_LABELS[key]}」格式错误：{s}")

        return {
            "mode": self.mode,
            "base_type": self.base_type,
            "base_model": self.base_model_var.get().strip() or None,
            "raw_dir": self.raw_dir_var.get().strip() or None,
            "rank": _num("rank", int),
            "alpha": _num("alpha", int),
            "unet_lr": _num("unet_lr", float),
            "te_lr": _num("te_lr", float),
            "repeats": _num("repeats", int),
            "max_epochs": _num("max_epochs", int),
            "train_text_encoder": not self.unet_only_var.get(),
            "gc": self.gc_var.get(),
            "trigger": self.trigger_var.get().strip(),
            "reg_dir": self.reg_var.get().strip() or None,
            "global_pos": self.global_pos_var.get().strip(),
            "global_neg": self.global_neg_var.get().strip(),
        }

    def _confirm_training(self, params, base_model, extra=None):
        lines = [
            f"即将开始训练：{MODE_LABELS[params['mode']]}",
            "─" * 44,
            f"底模            : {os.path.basename(base_model) if base_model else '（未选择）'}",
            f"底模类型        : {BASE_TYPE_LABELS.get(params.get('base_type', 'sd15'), '')}",
            f"训练分辨率      : {RESOLUTIONS.get(params.get('base_type', 'sd15'), 512)}px",
            f"rank / alpha    : {params['rank']} / {params['alpha']}",
            f"学习率          : {params['unet_lr']}",
            f"文本编码器学习率: {params['te_lr']}",
            f"repeats         : {params['repeats']}",
            f"最大 epoch      : {params['max_epochs']}",
            f"训练目标        : {'UNet + 文本编码器' if params['train_text_encoder'] else '仅 UNet'}",
            f"梯度检查点      : {params['gc']}",
        ]
        if params.get("batch_size"):
            lines.append(f"batch_size      : {params['batch_size']}")
        if params["mode"] == "character":
            lines.append(f"Trigger         : {params['trigger'] or '（未填写）'}")
            lines.append(f"正则数据集      : {params['reg_dir'] or '（未使用）'}")
        lines.append(f"附加全局正向    : {params.get('global_pos') or '（无）'}")
        lines.append(f"附加全局负向    : {params.get('global_neg') or '（无）'}")
        lines.append(f"输出模型        : output/{OUTPUT_NAMES[params['mode']]}.safetensors")
        if extra:
            lines.append("")
            lines.extend(str(x) for x in extra)
        lines.append("")
        lines.append("是否开始训练？")
        return messagebox.askyesno(APP_NAME, "\n".join(lines))

    # ---- 日志 ----
    def _log(self, msg):
        self.q.put(str(msg))

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if isinstance(item, tuple) and item and item[0] == "DL_PROGRESS":
                    self._handle_dl_progress(item[1], item[2], item[3])
                    continue
                if isinstance(item, tuple) and item and item[0] == "DL_DONE":
                    self._handle_dl_done(item[1], item[2])
                    continue
                if isinstance(item, tuple) and item and item[0] == "BASE_DETECTED":
                    self._handle_base_detected(*item[1:])
                    continue
                if isinstance(item, tuple) and item and item[0] == "AUTO_CONFIRM":
                    self._handle_auto_confirm(*item[1:])
                    continue
                if item == "__DONE__":
                    self._set_busy(False)
                    self._refresh_status()
                    continue
                self.txt.configure(state="normal")
                self.txt.insert("end", item + "\n", *self._log_tags(item))
                self.txt.see("end")
                self.txt.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _set_busy(self, busy):
        self.busy = busy
        for b in (self.btn_env, self.btn_install, self.btn_pre, self.btn_ui,
                  self.btn_ui_stop, self.btn_train, self.btn_one_click,
                  self.btn_guide_base, self.btn_guide_raw,
                  self.btn_refresh_base, self.btn_open_base_dir, self.btn_download_base):
            b.configure(state="disabled" if busy else "normal")
        self.mode_combo.configure(state="disabled" if busy else "readonly")
        self.base_combo.configure(state="disabled" if busy else "readonly")
        self.status_var.set("正在运行…" if busy else self.status_var.get())
        if busy:
            self._start_busy_anim()
            self._start_breathe()
            self._stop_guide_flash()
        else:
            self._stop_busy_anim()
            self._stop_breathe()
            self._refresh_guide()

    def _refresh_status(self):
        try:
            st = system_status()
            self._env_ok = bool(st.get("git") and st.get("python"))
            self._kohya_ok = bool(st.get("kohya_ok"))
            gray = "#9CA3AF"
            self._set_status_dot("git", SUCCESS if st.get("git") else gray,
                                 ("✓ Git" if st.get("git") else "✗ Git"))
            self._set_status_dot("python", SUCCESS if st.get("python") else gray,
                                 (f"Python {st['python']}" if st.get("python") else "✗ Python"))
            self._set_status_dot("kohya", SUCCESS if st.get("kohya_ok") else gray,
                                 ("✓ Kohya-SS" if st.get("kohya_ok") else "✗ Kohya-SS"))
            gpu = st.get("gpu")
            gpu_ok = bool(gpu) and gpu != "?"
            self._set_status_dot("gpu", SUCCESS if gpu_ok else gray,
                                 (f"GPU {gpu}" if gpu_ok else "✗ GPU"))
            vram = detect_vram_gb()
            if vram is not None:
                self._set_status_dot("vram", SUCCESS, f"显存 {vram:.1f}GB")
            else:
                self._set_status_dot("vram", gray, "显存 ?")
            self.status_var.set("环境检测完成")
        except Exception as e:
            self.status_var.set(f"状态检测失败: {e}")
        self._refresh_guide()

    def _draw_dot(self, canvas, color):
        canvas.delete("all")
        canvas.create_oval(1, 1, 11, 11, fill=color, outline=color)

    def _set_status_dot(self, key, color, text):
        c = self._status_dots.get(key)
        if c is not None:
            self._draw_dot(c, color)
        lbl = self._status_texts.get(key)
        if lbl is not None:
            lbl.configure(text=text)

    def _start_breathe(self):
        """状态圆点蓝色呼吸灯（每 500ms 深浅切换）。"""
        self._stop_breathe()
        state = {"on": False}
        def tick():
            state["on"] = not state["on"]
            col = "#60A5FA" if state["on"] else "#3B82F6"
            for c in self._status_dots.values():
                self._draw_dot(c, col)
            state["after"] = self.root.after(500, tick)
        tick()
        self._breathe_state = state

    def _stop_breathe(self):
        st = getattr(self, "_breathe_state", None)
        if st and st.get("after"):
            try:
                self.root.after_cancel(st["after"])
            except Exception:
                pass
        self._breathe_state = None
        try:
            self._refresh_status()
        except Exception:
            pass

    @staticmethod
    def _log_tags(msg):
        tags = []
        if any(k in msg for k in ("[训练]", "loss")):
            tags.append("train")
        if any(k in msg for k in ("[底模]", "[预处理]", "[WD14]", "[下载]")):
            tags.append("model")
        if any(k in msg for k in ("[OK]", "完成", "成功")):
            tags.append("ok")
        if any(k in msg for k in ("[WARN]", "警告", "注意")):
            tags.append("warn")
        if any(k in msg for k in ("[ERROR]", "失败", "错误", "✘")):
            tags.append("err")
        if not tags:
            tags.append("info")
        return tags

    def _run(self, fn, title):
        if self.busy:
            messagebox.showinfo(APP_NAME, "有任务正在运行，请稍候。")
            return
        self._start_worker(fn, title)

    def _start_worker(self, fn, title):
        self._set_busy(True)
        self._log("=" * 60)
        self._log(f"开始：{title}")
        threading.Thread(target=self._worker, args=(fn, title), daemon=True).start()

    def _worker(self, fn, title):
        try:
            fn()
            self._log(f"✔ 完成：{title}")
        except Exception as e:
            self._log(f"✘ 失败：{title} -> {e}")
            self._log(traceback.format_exc())
        finally:
            self.q.put("__DONE__")

    # ---- 命令 ----
    def cmd_env(self):
        self._run(lambda: ensure_prereqs(self._log), "环境准备")

    def cmd_install(self):
        self._run(lambda: install_kohya(self._log), "安装 Kohya-SS")

    def cmd_preprocess(self):
        d = filedialog.askdirectory(title="选择原始图片文件夹")
        if not d:
            return
        try:
            params = self._collect_params()
        except ValueError as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        if self.mode == "character":
            msg = ("人物模式预处理说明：\n"
                   "· 自动调用 WD14 打标（原图自带 .txt 会完整保留）；\n"
                   "· 已开启去重（MD5）；\n"
                   "· 将把全部 trigger 插入每张标签最开头。")
            if not params["trigger"]:
                msg += "\n\n⚠ 尚未填写 Trigger 触发词，建议填写唯一触发词。"
            if not params["reg_dir"]:
                msg += "\n⚠ 尚未选择正则数据集（可选）。"
            messagebox.showinfo(APP_NAME, msg)
        _mode = params["mode"]
        reso = RESOLUTIONS.get(params["base_type"], 512)
        self._run(lambda: preprocess(
            self._log, input_dir=d, size=reso,
            mode=_mode,
            trigger=params["trigger"],
            reg_dir=params["reg_dir"],
            repeats=params["repeats"],
            dedup=(_mode == "character"),
            wd14=True,
        ), "数据预处理")

    def cmd_start_ui(self):
        if self.busy:
            return
        if self.ui_proc and self.ui_proc.poll() is None:
            messagebox.showinfo(APP_NAME, "Web UI 已在运行（http://127.0.0.1:7860）。")
            return
        try:
            self.ui_proc = start_ui(self._log)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"启动失败：{e}")
            return
        threading.Thread(target=self._ui_reader, daemon=True).start()
        self._log("Web UI 已在后台运行，可点击 ⑤ 停止。")

    def _ui_reader(self):
        proc = self.ui_proc
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            self._log(line.rstrip("\n").rstrip("\r"))
        self._log("[UI] Web UI 已退出。")

    def cmd_stop_ui(self):
        if self.ui_proc and self.ui_proc.poll() is None:
            try:
                self.ui_proc.terminate()
                self._log("[UI] 已发送停止信号。")
            except Exception as e:
                self._log(f"[UI] 停止失败：{e}")
        else:
            self._log("[UI] 当前没有运行中的 Web UI。")

    def cmd_train(self):
        if self.busy:
            messagebox.showinfo(APP_NAME, "有任务正在运行，请稍候。")
            return
        try:
            params = self._collect_params()
        except ValueError as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        base = self._ensure_base_model()
        if not base:
            return
        params["base_model"] = base
        params["base_type"] = self.base_type
        if not self._warn_no_nvidia():
            return
        vram = detect_vram_gb()
        params["vram"] = vram
        batch, xformers, _gc = auto_training_setup(vram, params["base_type"])
        params["batch_size"] = batch
        params["use_xformers"] = xformers
        need = ARCH_INFO.get(params["base_type"], {}).get("recommend_vram", 12)
        if vram is not None and vram < need:
            if not messagebox.askyesno(
                    APP_NAME,
                    f"你的显卡显存约 {vram:.1f}G，带这个底模有点吃力，\n"
                    "可能会卡顿或者直接内存爆掉（OOM）。\n"
                    "工具已经自动开了省显存模式，要不要再试一次？"):
                return
        if not self._confirm_training(params, base):
            return
        resume = self._ask_resume(params)
        self._run(lambda: train(self._log, base_model=base, mode=params["mode"],
                                params=params, vram_gb=vram, resume_from=resume), "一键训练")

    def cmd_one_click_train(self):
        if self.busy:
            messagebox.showinfo(APP_NAME, "有任务正在运行，请稍候。")
            return
        raw = self.raw_dir_var.get().strip()
        if not raw or not os.path.isdir(raw):
            raw = filedialog.askdirectory(title="选择原始图片文件夹（自动预处理 + 训练）")
            if not raw:
                return
            self.raw_dir_var.set(raw)
        base = self._ensure_base_model()
        if not base:
            return
        try:
            params = self._collect_params()
        except ValueError as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        params["raw_dir"] = raw
        params["base_model"] = base
        self._set_busy(True)
        self._log("=" * 60)
        self._log("开始：一键开始训练（自动预处理 + 训练）")
        threading.Thread(target=self._one_click_worker, args=(params,), daemon=True).start()

    def _one_click_worker(self, params):
        try:
            report = os.path.join(tempfile.gettempdir(), "kohya_auto_report.json")
            try:
                if os.path.isfile(report):
                    os.remove(report)
            except Exception:
                pass
            preprocess(
                self._log, input_dir=params["raw_dir"],
                size=RESOLUTIONS.get(params["base_type"], 512),
                mode=params["mode"], trigger=params["trigger"],
                reg_dir=params["reg_dir"], repeats=params["repeats"],
                dedup=True, wd14=True, square_crop=True,
                min_size=256, blur_threshold=30.0, report=report,
                keep_tokens=None,
            )
            stats = {}
            if os.path.isfile(report):
                try:
                    with open(report, "r", encoding="utf-8") as f:
                        stats = json.load(f)
                except Exception:
                    stats = {}
            self.q.put(("AUTO_CONFIRM", params, stats))
        except Exception as e:
            self._log(f"✘ 失败：自动预处理 -> {e}")
            self._log(traceback.format_exc())
            self.q.put("__DONE__")

    def _handle_auto_confirm(self, params, stats):
        ok_n = stats.get("ok", 0)
        skipped_n = stats.get("skipped_existing", 0)
        usable = ok_n + skipped_n
        min_n = MIN_IMAGES.get(params["mode"], 20)
        filtered = (stats.get("duplicates", 0) + stats.get("blurry", 0)
                    + stats.get("too_small", 0) + stats.get("corrupt", 0))
        if usable < min_n:
            self._set_busy(False)
            messagebox.showwarning(
                APP_NAME,
                f"可用图片太少啦：处理后只有 {usable} 张（{MODE_LABELS[params['mode']]} 至少需要 {min_n} 张）。\n"
                f"本次新处理 {ok_n} 张，另有 {skipped_n} 张是之前已处理过的。\n"
                f"已过滤：重复 {stats.get('duplicates', 0)} 张、模糊 {stats.get('blurry', 0)} 张、"
                f"过小 {stats.get('too_small', 0)} 张、损坏 {stats.get('corrupt', 0)} 张。\n\n"
                "请补充更多清晰、有效的图片后再试。")
            return
        if filtered:
            messagebox.showinfo(
                APP_NAME,
                f"图片预处理完成：共处理 {stats.get('total', 0)} 张，可用 {usable} 张。\n"
                f"自动过滤：重复 {stats.get('duplicates', 0)}、模糊 {stats.get('blurry', 0)}、"
                f"过小 {stats.get('too_small', 0)}、损坏 {stats.get('corrupt', 0)}。")
        vram = detect_vram_gb()
        params["vram"] = vram
        batch, xformers, _gc = auto_training_setup(vram, params["base_type"])
        params["batch_size"] = batch
        params["use_xformers"] = xformers
        if not self._warn_no_nvidia():
            self._set_busy(False)
            return
        need = ARCH_INFO.get(params["base_type"], {}).get("recommend_vram", 12)
        if vram is not None and vram < need:
            if not messagebox.askyesno(
                    APP_NAME,
                    f"你的显卡显存约 {vram:.1f}G，带这个底模有点吃力，\n"
                    "可能会卡顿或者直接内存爆掉（OOM）。\n"
                    "工具已经自动开了省显存模式，要不要再试一次？"):
                self._set_busy(False)
                return
        extra = [f"可用图片：{usable} 张（已过滤 {filtered} 张）",
                 f"batch_size：{batch}（按显存自动）"]
        if not self._confirm_training(params, params.get("base_model") or "", extra=extra):
            self._set_busy(False)
            return
        resume = self._ask_resume(params)
        self._start_worker(lambda: train(
            self._log, base_model=params["base_model"], mode=params["mode"],
            params=params, vram_gb=vram, resume_from=resume), "一键开始训练")

    def _warn_no_nvidia(self):
        """训练前检查：无 NVIDIA 显卡时弹出兼容性提示。返回 True=继续。"""
        if detect_nvidia_gpu():
            return True
        return messagebox.askyesno(
            APP_NAME,
            "本工具针对NVIDIA显卡优化。\n"
            "AMD/Intel显卡Windows无开箱即用支持，需要自行配置ZLUDA/ROCm，存在兼容性风险，是否继续？")

    def _ask_resume(self, params):
        output_name = OUTPUT_NAMES.get(params["mode"], "anime_style_lora")
        state = find_latest_state(data_sub("output"), output_name)
        if state:
            if messagebox.askyesno(
                    APP_NAME,
                    f"发现上次中断留下的训练进度快照：\n{os.path.basename(state)}\n\n"
                    "要不要从上次断点继续训练？（选否则从头重新训练）"):
                return state
        return None

    def cmd_readme(self):
        p = os.path.join(KIT_DIR, "README_使用说明.md")
        if os.path.isfile(p):
            os.startfile(p)  # noqa
        else:
            messagebox.showinfo(APP_NAME, "README 未找到。")

    def cmd_open_output(self):
        d = data_sub("output")
        os.startfile(d)  # noqa

    def cmd_about(self):
        messagebox.showinfo(
            APP_NAME,
            "Kohya-SS LoRA 一键工具（画风 / 人物角色 双模式）\n\n"
            "本项目基于 kohya-ss / sd-scripts（Apache-2.0 开源协议）二次封装，\n"
            "项目本体以 MIT 协议开源。\n\n"
            "⚠ 免责提示：\n"
            "· 禁止训练受版权保护的画师作品；\n"
            "· 禁止训练受版权保护的真人素材（肖像权）；\n"
            "· 请仅使用你拥有版权或已获授权的图片。\n\n"
            "kohya-ss: https://github.com/bmaltais/kohya_ss\n"
            "sd-scripts: https://github.com/kohya-ss/sd-scripts")


def main():
    if not _HAS_TK:
        print("错误：缺少 tkinter，无法启动图形界面。")
        return 1
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
