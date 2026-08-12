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

# ---------- 全局隐藏子进程窗口 ----------
# GUI 程序没有控制台窗口，直接 subprocess 启动的子进程（git/python/nvidia-smi/powershell 等）
# 默认会各自弹出一个新的黑色 cmd 窗口；这里统一给所有 Popen 加 CREATE_NO_WINDOW，
# 让任何子进程都后台静默运行，不再弹窗。（subprocess.run/call 内部都走 Popen，自动生效）
if os.name == "nt":
    _orig_popen = subprocess.Popen

    def _popen_no_window(*args, **kwargs):
        kwargs.setdefault("creationflags", 0x08000000)  # CREATE_NO_WINDOW
        return _orig_popen(*args, **kwargs)

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
APP_VERSION = "0.5.0"

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


# ---------- 基础路径 ----------

def kit_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

KIT_DIR = kit_dir()
KOHYA_DIR_FILE = os.path.join(KIT_DIR, "kohya_dir.txt")

# ---------- 双模式预设 ----------

MODE_LABELS = {
    "style": "🎨 画风LoRA模式",
    "character": "👤 人物角色LoRA模式",
    "krea2": "🖼 Krea 2 图像LoRA",
}
MODE_KEYS = ["style", "character", "krea2"]

# 架构注册表（对标秋叶：SD1.5 / SDXL / FLUX.1 / Anima）
# family: sd=U-Net 架构；flux=DiT；anima=DiT+Qwen3
# tokenizers: [(model_id, kind)] kind='clip'=CLIPTokenizer, 'auto'=AutoTokenizer
ARCH_INFO = {
    "sd15": {
        "label": "SD1.5（512px）", "resolution": 512, "script": "train_network.py",
        "network_module": "networks.lora", "mixed": "fp16", "save_precision": "fp16",
        "min_bucket": 256, "max_bucket": 1024, "family": "sd",
        "min_vram": 8, "recommend_vram": 12, "hint": "",
        "tokenizers": [("openai/clip-vit-large-patch14", "clip")],
    },
    "sdxl": {
        "label": "SDXL 1.0（1024px）", "resolution": 1024, "script": "sdxl_train_network.py",
        "network_module": "networks.lora", "mixed": "bf16", "save_precision": "bf16",
        "min_bucket": 512, "max_bucket": 2048, "family": "sd",
        "min_vram": 12, "recommend_vram": 16,
        "hint": "⚠ SDXL 底模推荐 16G 及以上显存，否则容易显存不足。",
        "tokenizers": [("laion/CLIP-ViT-bigG-14-laion2B-39B-b160k", "clip")],
    },
    "flux": {
        "label": "FLUX.1（1024px）", "resolution": 1024, "script": "flux_train_network.py",
        "network_module": "networks.lora_flux", "mixed": "fp16", "save_precision": "bf16",
        "min_bucket": 256, "max_bucket": 1024, "family": "flux",
        "min_vram": 12, "recommend_vram": 16,
        "hint": "⚠ FLUX.1 是 12B 大模型，官方建议 16G 显存；8G 显存基本跑不动，请谨慎选择。",
        "tokenizers": [("openai/clip-vit-large-patch14", "clip"), ("google/t5-v1_1-xxl", "auto")],
    },
    "anima": {
        "label": "Anima（1024px）", "resolution": 1024, "script": "anima_train_network.py",
        "network_module": "networks.lora_anima", "mixed": "bf16", "save_precision": "bf16",
        "min_bucket": 512, "max_bucket": 2048, "family": "anima",
        "min_vram": 8, "recommend_vram": 12,
        "hint": "⚠ Anima 是 2026 最新架构（2B DiT + Qwen3 文本编码器），8G 显存可跑（需开省显存），推荐 12G+。",
        "tokenizers": [("Qwen/Qwen3-0.6B", "auto"), ("google/t5-v1_1-xxl", "auto")],
    },
}

BASE_TYPE_KEYS = list(ARCH_INFO.keys())
BASE_TYPE_LABELS = {k: v["label"] for k, v in ARCH_INFO.items()}
BASE_TYPE_HINTS = {k: v["hint"] for k, v in ARCH_INFO.items()}

# 内置预设参数（按 模式 × 底模类型；切换自动填充；手动改过的不再被覆盖，只有「恢复预设」重写）
PRESETS = {
    "style": {
        "sd15": {"rank": "12", "alpha": "6", "unet_lr": "3e-4", "te_lr": "1.5e-4",
                 "repeats": "5", "max_epochs": "8"},
        "sdxl": {"rank": "16", "alpha": "8", "unet_lr": "1.5e-4", "te_lr": "7.5e-5",
                 "repeats": "5", "max_epochs": "8"},
        "flux": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "5", "max_epochs": "8"},
        "anima": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "1e-4",
                  "repeats": "5", "max_epochs": "8"},
    },
    "character": {
        "sd15": {"rank": "24", "alpha": "12", "unet_lr": "1.5e-4", "te_lr": "8e-5",
                 "repeats": "3", "max_epochs": "6"},
        "sdxl": {"rank": "32", "alpha": "16", "unet_lr": "7e-5", "te_lr": "4e-5",
                 "repeats": "3", "max_epochs": "6"},
        "flux": {"rank": "16", "alpha": "16", "unet_lr": "8e-5", "te_lr": "8e-5",
                 "repeats": "3", "max_epochs": "6"},
        "anima": {"rank": "16", "alpha": "16", "unet_lr": "8e-5", "te_lr": "8e-5",
                  "repeats": "3", "max_epochs": "6"},
    },
    "krea2": {
        "sd15": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "5", "max_epochs": "16"},
        "sdxl": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "5", "max_epochs": "16"},
        "flux": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "5", "max_epochs": "16"},
        "anima": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                  "repeats": "5", "max_epochs": "16"},
    },
}

RESOLUTIONS = {k: v["resolution"] for k, v in ARCH_INFO.items()}
MIN_IMAGES = {"style": 20, "character": 15, "krea2": 15}   # 一键训练最少可用图片数
MAX_AUTO_STEPS = 12000                          # 一键训练自动约束的最大总步数（防过拟合）

PARAM_LABELS = {
    "rank": "rank",
    "alpha": "alpha",
    "unet_lr": "学习率",
    "te_lr": "文本编码器学习率",
    "repeats": "repeats",
    "max_epochs": "最大epoch",
}

# 高级参数通俗中文提示（鼠标悬停显示）
PARAM_TIPS = {
    "rank": "LoRA 秩：越大学得越细、越像，也越容易过拟合；一般 8~64。",
    "alpha": "缩放系数：一般取 rank 的一半，影响 LoRA 的强度。",
    "unet_lr": "UNet 学习率：越大学得越快，太大容易崩或过拟合。",
    "te_lr": "文本编码器学习率：控制提示词理解的学习速度，建议比 UNet 学习率低。",
    "repeats": "每张图片重复次数：越多学得越用力，小心过拟合。",
    "max_epochs": "最大训练轮数：轮数越多学得越久，够用就好。",
}

TRIGGER_HINT_CHARACTER = ("💡提示：填一个网上很少见到的英文单词，比如 my_oc01\n"
                          "不要用 girl 这种普通单词！\n"
                          "训练之后输入这个单词，就能画出这个人物。\n"
                          "不填也可以正常训练。")
TRIGGER_HINT_KREA2 = ("💡提示：填一个网上很少见到的英文单词（如 my_k2_01）\n"
                      "训练后输入这个单词，就能召唤这个角色/风格。\n"
                      "⚠ Krea 2 模式需先把模型放进 models/krea2/ 并安装第二引擎。")
TRIGGER_HINT_STYLE = ("💡提示：填一个网上很少见到的英文单词，比如 my_style01\n"
                      "不要用 sketch 这种普通单词！\n"
                      "⚠重要：你的训练图片不能全是同一个人，不然画风套不到别的东西上。\n"
                      "训练之后输入这个单词，就能一键套用这个画风。\n"
                      "不填也可以正常训练。")
DATASET_TIPS = {
    "style": "📌 数据集提示：建议 20~60 张图片，尽量多不同人物、不同姿态，避免五官固化。画风模式自动过滤强人物五官标签；可填画风专属触发词，不需要正则图。",
    "character": "📌 数据集提示：建议 15~30 张同一人物，多角度、不同服装，推荐设置唯一 trigger 触发词；可配合正则数据集防过拟合。",
    "krea2": "📌 数据集提示：建议 15~30 张同一人物/风格，多角度多服装；训练前先把 Krea 2 模型放进 models/krea2/（RAW+VAE+文本编码器）。推荐 12G+ 显存。",
}

OUTPUT_NAMES = {"style": "anime_style_lora", "character": "character_lora", "krea2": "krea2_lora"}



PY_MIN = (3, 10, 9)
PY_MAX = (3, 13, 0)


# ---------- 通用工具 ----------

class StopRequested(Exception):
    """用户手动停止当前任务（训练/预处理/安装等）。"""


class TrainMonitor:
    """训练实时监控：从 kohya 训练日志里解析 步数/loss/lr/速度/预计剩余时间。
    线程安全（内部用锁）；GUI 主线程通过 snapshot() 轮询刷新面板。"""

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

        注意：tqdm 格式（N/M [）优先，因为它带真实总步数。
        格式1（steps: N）要排除 kohya 启动时打印的
        'total optimization steps: 2916' / 'gradient accumulation steps: N' 等，
        否则会把"总步数"误当成"当前步数"，导致监控进度条瞬间拉满/跳变。
        """
        try:
            s = str(line)
            step = None
            total = None
            # 格式2（优先）：tqdm 进度条 N/M [  或 N/M [..] it/s
            m = re.search(r"(\d+)\s*/\s*(\d+)\s*\[", s)
            if m:
                step = int(m.group(1))
                total = int(m.group(2))
            else:
                # 格式1：独立的 'steps: N'（排除百分比 'steps: 1%'，排除 total/gradient/num 等前缀）
                if not re.search(r"(?:total|gradient|num|infer|sampling|val)[^:]*steps:", s, re.I):
                    m = re.search(r"steps:\s*(\d+)(?!%)", s)
                    if m:
                        step = int(m.group(1))
            if step is None:
                return False
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
            with self._lock:
                self.step = step
                if total and total > 0:
                    self.total = total
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
            }

    def finish(self):
        with self._lock:
            self.running = False


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

_STOP_EVENT = threading.Event()
_ACTIVE_LOCK = threading.Lock()
_ACTIVE_PROC = None


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


def build_env(extra_dirs=()):
    env = dict(os.environ)
    paths = list(extra_dirs) + [env.get("PATH", "")]
    env["PATH"] = ";".join(p for p in paths if p)
    return env


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


# ---------- 环境检测 / 安装 ----------

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


def find_python():
    cands = []
    p = shutil.which("python")
    if p:
        cands.append(p)
    for c in (
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Programs\Python\Python310\python.exe"),
        r"C:\Python310\python.exe",
        r"C:\Program Files\Python310\python.exe",
    ):
        if os.path.isfile(c):
            cands.append(c)
    for c in cands:
        s, parts = _py_version(c)
        if s and PY_MIN <= parts < PY_MAX:
            return c, s
    return None, None


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
    # 优先使用内置安装包（离线，无需联网/代理）
    exe = _bundled_path("python")
    if exe:
        logf(f"[Python] 使用内置安装包: {exe}")
        subprocess.run(
            [exe, "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=1",
             "Include_test=0", "Include_doc=0", "Include_tcltk=1", "Include_pip=1"],
            timeout=1800,
        )
        py, ver = find_python()
        if py:
            return py, ver
        raise RuntimeError("内置 Python 安装后仍未找到，请手动安装 https://www.python.org/downloads/")
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

def get_kohya_dir():
    """定位 kohya_ss 训练内核目录。

    优先级：
    1) kohya_dir.txt 记录（最优先，尊重用户/历史选择）
    2) APPDATA 数据目录下的 KohyaLoraTool 文件夹里的 kohya_ss（新默认：
       和 dataset/output 放一起，升级/重装软件不删 APPDATA，训练环境直接保留，不用每次重装）
    3) 安装目录内 kohya_ss（旧版位置，向后兼容：老用户覆盖升级不重装）
    4) 用户主目录下的 kohya_ss（更早版本的兜底位置）
    5) 都不存在 -> 返回 APPDATA 数据目录下的 kohya_ss（新装到这里）
    """
    if os.path.isfile(KOHYA_DIR_FILE):
        with open(KOHYA_DIR_FILE, "r", encoding="utf-8") as f:
            p = f.read().strip().lstrip("\ufeff").strip()
        if p and os.path.isdir(p):
            return p
    # 新默认：数据目录（升级/重装软件保留，不用重装环境）
    d = os.path.join(data_dir(), "kohya_ss")
    if os.path.isdir(d):
        return d
    # 向后兼容：安装目录内（旧版位置，覆盖升级不重装）
    d_old = os.path.join(KIT_DIR, "kohya_ss")
    if os.path.isdir(d_old):
        return d_old
    # 更早版本的兜底位置
    d_legacy = os.path.join(os.path.expanduser("~"), "kohya_ss")
    if os.path.isdir(d_legacy):
        return d_legacy
    return d


def venv_python(kdir=None):
    kdir = kdir or get_kohya_dir()
    return os.path.join(kdir, "venv", "Scripts", "python.exe")


def _git_proxy_reachable():
    """检查 git 全局代理是否可用。本地代理(127.0.0.1)端口未监听视为不可用。"""
    try:
        r = subprocess.run(["git", "config", "--global", "--get", "http.proxy"],
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
    env = build_env([os.path.dirname(git)])
    cmd = ["git", "clone", "--depth", "1", url, dest]
    if not _git_proxy_reachable():
        logf("[Git] 检测到 git 代理不可用，本次克隆绕过代理直连…")
        cmd = ["git", "-c", "http.proxy=", "-c", "https.proxy="] + cmd
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
        if not os.path.isfile(vpy):
            logf("[Kohya] 创建 Python 虚拟环境…")
            if run_stream([py, "-m", "venv", "venv"], cwd=kdir, logf=logf) != 0 or not os.path.isfile(vpy):
                raise RuntimeError("创建 venv 失败")
        # 已安装验证：venv 里 torch 可用 + sd-scripts 存在 => 跳过重复安装
        try:
            r = subprocess.run([vpy, "-c", "import torch; print(torch.__version__)"],
                               capture_output=True, text=True, timeout=120)
            torch_ok = r.returncode == 0
        except Exception:
            torch_ok = False
        if torch_ok and os.path.isdir(os.path.join(kdir, "sd-scripts")):
            logf("[Kohya] 检测到已安装环境（torch 可用），跳过重复安装。")
            with open(KOHYA_DIR_FILE, "w", encoding="utf-8") as f:
                f.write(kdir)
            return kdir
        logf("[Kohya] 设置 pip 镜像源（清华 pypi + 阿里 pytorch cu128，无需代理）…")
        subprocess.run([vpy, "-m", "pip", "config", "set", "global.index-url",
                        "https://pypi.tuna.tsinghua.edu.cn/simple"], capture_output=True, timeout=60)
        subprocess.run([vpy, "-m", "pip", "config", "set", "global.extra-index-url",
                        "https://mirrors.aliyun.com/pytorch-wheels/cu128"], capture_output=True, timeout=60)
        logf("[Kohya] 升级 pip / setuptools / wheel …")
        if run_stream([vpy, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel", "-q"], cwd=kdir, logf=logf) != 0:
            raise RuntimeError("pip 升级失败（可能是网络或安装目录被占用），请重试")
        logf("[Kohya] 安装全部依赖（官方无人值守模式，约 10-30 分钟）…")
        env = build_env([os.path.dirname(git)])
        env.setdefault("PIP_EXTRA_INDEX_URL", "https://mirrors.aliyun.com/pytorch-wheels/cu128")
        if run_stream([vpy, "setup\\setup_windows.py", "--headless"], cwd=kdir, env=env, logf=logf) != 0:
            raise RuntimeError("依赖安装失败，请向上滚动查看 pip 报错")
        with open(KOHYA_DIR_FILE, "w", encoding="utf-8") as f:
            f.write(kdir)
        try:
            r = subprocess.run(
                [vpy, "-c", "import torch;print(torch.__version__);print(torch.cuda.is_available())"],
                capture_output=True, text=True, timeout=180,
            )
            lines = (r.stdout or "").strip().splitlines()
            torchv = lines[0] if lines else "?"
            cuda = lines[1] if len(lines) > 1 else "?"
            logf(f"[Kohya] 验证：torch {torchv} | CUDA 可用: {cuda}")
        except Exception as e:
            logf(f"[Kohya] 验证 torch 失败: {e}")
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
        # 3) 已装验证：torch + musubi_tuner 可用 => 跳过
        try:
            r = subprocess.run(
                [vpy, "-c", "import torch; import musubi_tuner; from musubi_tuner.krea2_train_network import main"],
                capture_output=True, text=True, timeout=180)
            torch_ok = r.returncode == 0
        except Exception:
            torch_ok = False
        if torch_ok:
            logf("[第二引擎] 检测到已安装（torch + musubi_tuner 可用），跳过重复安装。")
            return vpy
        # 4) pip 镜像（清华 pypi + 阿里 pytorch 额外源，与 kohya 一致）
        subprocess.run([vpy, "-m", "pip", "config", "set", "global.index-url",
                        "https://pypi.tuna.tsinghua.edu.cn/simple"], capture_output=True, timeout=60)
        subprocess.run([vpy, "-m", "pip", "config", "set", "global.extra-index-url",
                        "https://mirrors.aliyun.com/pytorch-wheels/cu128"], capture_output=True, timeout=60)
        logf("[第二引擎] 升级 pip / setuptools / wheel …")
        if run_stream([vpy, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel", "-q"],
                      cwd=kdir, logf=logf) != 0:
            raise RuntimeError("pip 升级失败，请重试")
        # 5) torch cu128（与 kohya 同源；首次可能较慢/需网络）
        logf("[第二引擎] 安装 PyTorch cu128（约 2.5GB，与 kohya 同源，首次可能较慢）…")
        env = build_env([os.path.dirname(git)])
        if run_stream(
            [vpy, "-m", "pip", "install", "torch==2.7.1+cu128", "torchvision==0.22.0+cu128",
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


# ---------- 预处理 / UI / 训练 ----------

def preprocess(logf=print, input_dir=None, size=512, mode="style", trigger="",
               reg_dir=None, repeats=5, dedup=False, wd14=True,
               square_crop=False, min_size=0, blur_threshold=0.0, report=None,
               keep_tokens=None, project=None):
    vpy = venv_python()
    if not os.path.isfile(vpy):
        raise RuntimeError("Kohya 尚未安装，请先点击【一键安装】")
    if not input_dir or not os.path.isdir(input_dir):
        raise RuntimeError("请选择图片文件夹")
    out = dataset_train_dir(mode, project)
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


def detect_nvidia_gpu():
    """检测是否有 NVIDIA 显卡（调用 nvidia-smi）。返回 bool。"""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=20)
        return r.returncode == 0 and bool((r.stdout or "").strip())
    except Exception:
        return False


def detect_vram_gb():
    """检测显卡显存（GB）。优先 nvidia-smi（N 卡）；失败回退注册表 qwMemorySize（AMD/其他）。失败返回 None。"""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode == 0:
            vals = []
            for line in r.stdout.strip().splitlines():
                line = line.strip()
                if line.replace(".", "").isdigit():
                    vals.append(float(line))
            if vals:
                return vals[0] / 1024.0
    except Exception:
        pass
    return _registry_vram_gb()


def _registry_vram_gb():
    """从显卡注册表读取真实显存（HardwareInformation.qwMemorySize，QWORD，单位字节）。
    兼容 AMD / Intel 显卡（WMI 的 AdapterRAM 会溢出到 4GB，不可靠）。"""
    try:
        import winreg
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base + "\\" + sub) as sk:
                        val, _ = winreg.QueryValueEx(sk, "HardwareInformation.qwMemorySize")
                        if val:
                            gb = float(val) / (1024.0 ** 3)
                            if gb > 0:
                                return gb
                except Exception:
                    continue
    except Exception:
        pass
    return None


def detect_gpu_vendor():
    """检测显卡厂商：'nvidia' | 'amd' | 'intel' | 'unknown'（任何异常都不抛出）。"""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0 and (r.stdout or "").strip():
            return "nvidia"
    except Exception:
        pass
    try:
        ps = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
              "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name + '|' + $_.AdapterCompatibility }"]
        r = subprocess.run(ps, capture_output=True, text=True, timeout=30)
        low = (r.stdout or "").lower()
        if any(k in low for k in ("amd", "ati", "radeon")):
            return "amd"
        if "intel" in low:
            return "intel"
    except Exception:
        pass
    return "unknown"


def detect_gpu_name():
    """返回显卡名称（N 卡走 nvidia-smi；其他走 WMI）。失败返回 None。"""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            lines = [ln.strip() for ln in (r.stdout or "").strip().splitlines() if ln.strip()]
            if lines:
                return lines[0]
    except Exception:
        pass
    try:
        ps = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
              "Get-CimInstance Win32_VideoController | Select-Object -First 1 -ExpandProperty Name"]
        r = subprocess.run(ps, capture_output=True, text=True, timeout=30)
        name = (r.stdout or "").strip()
        if name:
            return name
    except Exception:
        pass
    return None


def detect_gpu_info():
    """统一显卡信息：{'vendor','name','vram_gb'}。任何一步失败都不抛异常。"""
    return {"vendor": detect_gpu_vendor(), "name": detect_gpu_name(), "vram_gb": detect_vram_gb()}


def detect_torch_backend(vpy=None):
    """检测训练环境（kohya venv）里 torch 的后端：
    'rocm'=AMD ROCm 版 | 'zluda'=AMD 卡 + CUDA torch 且可用（ZLUDA 生效）
    | 'cuda'=N 卡 CUDA | 'cpu'=无 GPU 后端 | None=无法读取。"""
    if not vpy or not os.path.isfile(vpy):
        return None
    code = ("import torch;"
            "print('CUDA=%s' % (getattr(torch.version,'cuda',None) or ''));"
            "print('HIP=%s' % (getattr(torch.version,'hip',None) or ''));"
            "print('AVAIL=%s' % torch.cuda.is_available());"
            "print('NAME=%s' % (torch.cuda.get_device_name(0) if torch.cuda.is_available() else ''))")
    try:
        r = subprocess.run([vpy, "-c", code], capture_output=True, text=True, timeout=120)
        info = {}
        for ln in (r.stdout or "").strip().splitlines():
            if "=" in ln:
                k, v = ln.split("=", 1)
                info[k] = v
        if info.get("HIP"):
            return "rocm"
        if info.get("AVAIL") == "True":
            if detect_gpu_vendor() == "amd":
                return "zluda"
            return "cuda"
        return "cpu"
    except Exception:
        return None


def detect_system_pythons():
    """列出系统已安装的 Python 版本（Windows py launcher + 注册表 + 已知路径）。
    返回 ['3.12','3.11',...] 或 []。
    仅靠 py -0p 在刚装完 Python 时可能检测不到（launcher 缓存/环境变量未刷新），
    所以补充注册表与已知目录扫描。"""
    vers = []
    def _add(v):
        if v and v not in vers:
            vers.append(v)
    # 1) py launcher（只匹配标准版本行：-V:3.12 / -V:3.12-64，排除 Astral/uv 等第三方）
    try:
        r = subprocess.run(["py", "-0p"], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            for ln in (r.stdout or "").splitlines():
                m = re.search(r"-V:(\d+\.\d+)", ln)
                if m:
                    _add(m.group(1))
    except Exception:
        pass
    # 2) 注册表：HKCU / HKLM 的 Software\Python\PythonCore\<ver>
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
                        if m:
                            _add(m.group(1))
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
                    if os.path.isfile(py):
                        _add(f"{m.group(1)}.{m.group(2)}")
        for c in (r"C:\Python312\python.exe",
                  r"C:\Program Files\Python312\python.exe"):
            if os.path.isfile(c):
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
AMD_TRAIN_DEPS = "transformers diffusers accelerate safetensors omegaconf numpy pillow av opencv-python einops sentencepiece"


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
    """按训练环境 Python 版本生成 AMD 版 PyTorch wheel URL（cp311/cp312）。"""
    ver = venv_python_version(venv_dir) or "3.12"
    cp = "cp311" if ver.startswith("3.11") else "cp312"
    return [
        f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/torch-{AMD_TORCH_VERSION}%2Brocm{AMD_ROC_VERSION}-{cp}-{cp}-win_amd64.whl",
        f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/torchaudio-{AMD_TORCH_VERSION}%2Brocm{AMD_ROC_VERSION}-{cp}-{cp}-win_amd64.whl",
        f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/torchvision-{AMD_TORCHVISION_VERSION}%2Brocm{AMD_ROC_VERSION}-{cp}-{cp}-win_amd64.whl",
    ]


def run_pip_in_venv(venv_dir, args, logf=print):
    """在训练环境（venv）里运行 pip install。返回退出码；可被停止按钮中断。"""
    py = os.path.join(venv_dir, "Scripts", "python.exe")
    if not os.path.isfile(py):
        raise RuntimeError(f"训练环境无效，找不到 {py}，请先创建训练环境。")
    cmd = [py, "-m", "pip", "install", "--no-cache-dir"] + args
    env = build_env()
    env.setdefault("PIP_NO_INPUT", "1")
    return run_stream(cmd, env=env, logf=logf)


def install_amd_rocm(venv_dir, logf=print):
    """自动安装 AMD ROCm 运行库（阶段 1/3，约 1~2GB，视网速 10~60 分钟）。"""
    logf("[AMD] 阶段 1/3：安装 AMD ROCm 运行库（文件较大，请耐心等待，可随时点停止）…")
    rc = run_pip_in_venv(venv_dir, AMD_ROC_WHEELS, logf)
    if rc != 0:
        raise RuntimeError(f"ROCm 运行库安装失败（退出码 {rc}），请向上查看日志。")
    logf("[OK] AMD ROCm 运行库安装完成")
    return True


def install_amd_torch(venv_dir, logf=print):
    """自动安装 AMD 版 PyTorch（阶段 2/3，约 2~3GB）。"""
    logf("[AMD] 阶段 2/3：安装 AMD 版 PyTorch（文件较大，请耐心等待）…")
    rc = run_pip_in_venv(venv_dir, _amd_torch_wheels(venv_dir), logf)
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


def split_triggers(s):
    """把逗号分隔的多个 trigger 拆成列表。"""
    return [t.strip() for t in (s or "").split(",") if t.strip()]


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
    """训练完成后生成 txt 使用模板（画风=画风提示词；人物=带 trigger/全局提示词示例）。"""
    out_dir = out_dir or data_sub("output")
    path = os.path.join(out_dir, output_name + "_使用模板.txt")
    base = params.get("base_type", "sd15")
    reso = RESOLUTIONS.get(base, 512)
    gpos = (params.get("global_pos") or "").strip()
    neg = (params.get("global_neg") or "").strip() or (
        "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, "
        "fewer digits, cropped, worst quality, low quality, jpeg artifacts, signature, "
        "watermark, username, blurry, bad quality")
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
            "2. 推荐 LoRA 权重 0.6 ~ 0.9（按底模微调）。\n"
            f"3. 负面提示词建议：{neg}\n"
            "4. 想强调角色时提高权重，想自然融入时用 0.6 左右。\n"
        )
    else:
        pos_example = ((gpos + ", ") if gpos else "") + (
            "anime cel-shading, clean thin black outlines, flat color, simple soft cel shading, "
            "tv anime screenshot, limited color palette, 1girl, cherry blossoms")
        text = (
            "【画风 LoRA 使用模板】\n"
            f"模型文件：{output_name}.safetensors\n"
            "本 LoRA 无 trigger 触发词，提示词直接写画风标签即可。\n"
            f"训练分辨率：{reso}px\n\n"
            "使用建议：\n"
            "1. 推荐 LoRA 权重 0.5 ~ 0.7。\n"
            f"2. 正向提示词示例：{pos_example}\n"
            "3. 不要输入角色名/trigger 词（这个 LoRA 没有也不应该有）。\n"
            f"4. 负面提示词建议：{neg}\n"
            "5. 想弱化风格时把权重降到 0.4。\n"
        )
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(text)
    return path


def _ensure_tokenizer_cached(cache_dir, model_id, logf=print, kind="clip"):
    """预缓存分词器（kohya 期望的平铺目录格式），避免训练时联网下载失败。

    kind: 'clip'=CLIPTokenizer；其他（t5/qwen3 等）=AutoTokenizer。
    """
    target = os.path.join(cache_dir, model_id.replace("/", "_"))
    if os.path.isfile(os.path.join(target, "vocab.json")) or os.path.isfile(os.path.join(target, "tokenizer.json")):
        return True
    try:
        if kind == "clip":
            from transformers import CLIPTokenizer
            tok = CLIPTokenizer.from_pretrained(model_id)
        else:
            from transformers import AutoTokenizer
            tok = AutoTokenizer.from_pretrained(model_id, use_fast=True)
        os.makedirs(target, exist_ok=True)
        tok.save_pretrained(target)
        logf(f"[训练] 已预缓存分词器 {model_id} -> {target}")
        return True
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

    resolution = arch_info["resolution"]
    train_dir = dataset_train_dir(mode, params.get("project"))
    if count_images(train_dir) == 0:
        raise RuntimeError(f"缺少预处理数据：{train_dir}\n请先执行【数据预处理】或【一键开始训练】")
    cfg_path = os.path.join(KIT_DIR, "configs", "dataset_config.toml")
    data_sub("output")
    data_sub("logs")
    for _tid, _kind in arch_info["tokenizers"]:
        _ensure_tokenizer_cached(data_sub("tokenizers"), _tid, logf, _kind)

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
    if mode == "character":
        keep_tokens = max(1, len(split_triggers(params.get("trigger"))))
        # 训练前把当前 trigger 同步进标签：用户可能改过 trigger 但没重新预处理，
        # 若标签第一行没有当前 trigger，LoRA 就学不到它，生图"召唤不出来"。
        try:
            _synced = _sync_trigger_to_labels(train_dir, params.get("trigger"), logf)
            if _synced:
                logf(f"[训练] 已把 trigger「{params.get('trigger')}」同步到 {_synced} 张标签第一行")
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
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
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
            return server if "://" in server else "http://" + server
    except Exception:
        pass
    return None


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
    data = {
        "git": git or None,
        "python": f"{ver}" if ver else None,
        "kohya_ok": kohya_ok,
        "kohya_dir": kdir if kohya_ok else None,
        "gpu": gpu,
        "musubi_ok": _musubi_ok,
    }
    _SYSTEM_STATUS_CACHE["t"] = _now
    _SYSTEM_STATUS_CACHE["data"] = data
    return data


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


def base_models_dir():
    """默认基础底模存放目录（项目内 models/base，软件不内置底模）。"""
    return os.path.join(KIT_DIR, "models", "base")


def data_dir():
    """运行期可写数据目录：重定向到 %APPDATA%\\KohyaLoraTool，避开安装目录权限问题。

    output / dataset / logs / tokenizers 等会写入的数据全部放这里；
    models/base、configs 保留在程序安装目录（只读资源）。
    """
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "KohyaLoraTool")


def data_sub(*parts):
    d = os.path.join(data_dir(), *parts)
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def _sanitize_dirname(name):
    """把项目名清洗成可用的文件夹名（兼容中文，去掉路径非法字符）。"""
    return re.sub(r'[\\/:*?"<>|\r\n]', "_", (name or "").strip()).strip(" .")


def dataset_train_dir(mode="style", project=None):
    """当前模式对应的训练数据集目录（人物=train_character，画风=train）。

    - project 为空：旧版共享目录 dataset/train_character（兼容历史数据）；
    - project 非空：项目独立目录 dataset/<项目名>/train_character，
      每个项目的数据互不混用（标签编辑器/预处理/训练都按项目隔离）。
    """
    proj = _sanitize_dirname(project)
    sub = "train" if mode == "style" else "train_character"
    if proj:
        return os.path.join(data_dir(), "dataset", proj, sub)
    return os.path.join(data_dir(), "dataset", sub)


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

def projects_dir():
    """项目保存目录（数据目录下，随软件重装保留）。"""
    return data_sub("projects")


def _project_path(name):
    return os.path.join(projects_dir(), (name or "").strip() + ".json")


def list_projects():
    """列出所有项目，按修改时间倒序。返回 [{name, updated, mode, base_type, raw_dir, base_model}]。"""
    d = projects_dir()
    out = []
    try:
        for fn in os.listdir(d):
            if not fn.lower().endswith(".json"):
                continue
            fp = os.path.join(d, fn)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            out.append({
                "name": data.get("name") or os.path.splitext(fn)[0],
                "updated": data.get("updated", ""),
                "mode": data.get("mode", "style"),
                "base_type": data.get("base_type", "sd15"),
                "raw_dir": data.get("raw_dir", ""),
                "base_model": data.get("base_model", ""),
            })
    except Exception:
        pass
    out.sort(key=lambda x: x.get("updated", ""), reverse=True)
    return out


def load_project(name):
    """读取项目。返回 dict 或 None。"""
    fp = _project_path(name)
    if not os.path.isfile(fp):
        return None
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_project(name, data):
    """保存项目（自动写 updated 时间）。返回是否成功。"""
    name = (name or "").strip()
    if not name:
        return False
    import datetime
    data = dict(data or {})
    data["name"] = name
    data["updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not data.get("created"):
        data["created"] = data["updated"]
    try:
        os.makedirs(projects_dir(), exist_ok=True)
        with open(_project_path(name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def delete_project(name):
    """删除项目文件。"""
    fp = _project_path(name)
    try:
        if os.path.isfile(fp):
            os.remove(fp)
            return True
    except Exception:
        pass
    return False


def default_project_name():
    """生成默认项目名：项目_MMDD_HHMM。"""
    import datetime
    return "项目_" + datetime.datetime.now().strftime("%m%d_%H%M")


# 新建项目时的预设模板（填入模式 + 参数；底模/数据集用户自己选）
PROJECT_TEMPLATES = {
    "动漫画风": {
        "mode": "style",
        "base_type": "sdxl",
        "note": "适合动漫/插画风格 LoRA：默认 SDXL 分辨率 1024，rank 16，低学习率防过拟合。",
        "params": {"rank": "16", "alpha": "8", "unet_lr": "1.5e-4", "te_lr": "7.5e-5",
                   "repeats": "5", "max_epochs": "8"},
    },
    "写实人物": {
        "mode": "character",
        "base_type": "sdxl",
        "note": "适合真人/角色 LoRA：默认 SDXL 分辨率 1024，rank 32，配 trigger 触发词效果更好。",
        "params": {"rank": "32", "alpha": "16", "unet_lr": "7e-5", "te_lr": "4e-5",
                   "repeats": "3", "max_epochs": "6"},
    },
    "SD1.5 动漫": {
        "mode": "style",
        "base_type": "sd15",
        "note": "轻量底模（512 分辨率），显存要求低，适合老显卡快速出效果。",
        "params": {"rank": "12", "alpha": "6", "unet_lr": "3e-4", "te_lr": "1.5e-4",
                   "repeats": "5", "max_epochs": "8"},
    },
    "自定义": {
        "mode": "character",
        "base_type": "sdxl",
        "note": "全部参数自己调，程序按当前模式+底模填默认值。",
        "params": {},
    },
}


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


def _hf_download(repo, local_dir, logf, allow_patterns=None):
    """用 huggingface_hub 走 hf-mirror 下载仓库到 local_dir。"""
    import os as _os
    from huggingface_hub import snapshot_download
    old = _os.environ.get("HF_ENDPOINT")
    _os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    try:
        snapshot_download(repo, local_dir=local_dir, allow_patterns=allow_patterns)
    finally:
        if old is None:
            _os.environ.pop("HF_ENDPOINT", None)
        else:
            _os.environ["HF_ENDPOINT"] = old


def _ensure_anima_components(logf=print):
    """确保 Anima 的 Qwen3-0.6B 文本编码器和 Qwen-Image VAE 就位。

    返回 (qwen3 路径, vae 路径)；缺失时自动从 hf-mirror 下载。
    """
    base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "KohyaLoraTool", "anima")
    os.makedirs(base, exist_ok=True)
    qwen3_dir = os.path.join(base, "Qwen3-0.6B")
    if not (os.path.isdir(qwen3_dir) and os.path.isfile(os.path.join(qwen3_dir, "config.json"))):
        logf("[Anima] 首次使用需要下载 Qwen3-0.6B 文本编码器（约 1.2GB，走 hf-mirror）…")
        try:
            _hf_download("Qwen/Qwen3-0.6B", qwen3_dir, logf)
        except Exception as e:
            raise RuntimeError(f"Qwen3-0.6B 自动下载失败：{e}\n可手动下载后放到：{qwen3_dir}")
        if not (os.path.isdir(qwen3_dir) and os.path.isfile(os.path.join(qwen3_dir, "config.json"))):
            raise RuntimeError(f"Qwen3-0.6B 下载不完整，请检查：{qwen3_dir}")
    vae_dir = os.path.join(base, "Anima_vae")
    vae_file = None
    if os.path.isdir(vae_dir):
        for root, _dirs, files in os.walk(vae_dir):
            for f in files:
                if f.lower().endswith((".safetensors", ".pth")):
                    vae_file = os.path.join(root, f)
                    break
            if vae_file:
                break
    if not vae_file:
        logf("[Anima] 首次使用需要下载 Qwen-Image VAE（走 hf-mirror）…")
        try:
            _hf_download("circlestone-labs/Anima", vae_dir, logf, allow_patterns=["split_files/vae/*"])
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
    logf(f"[Anima] Qwen3: {qwen3_dir}")
    logf(f"[Anima] VAE: {vae_file}")
    return qwen3_dir, vae_file


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
            if bt in ("sd15", "sdxl"):
                self._set_base_type(bt)
                self._log(f"[底模] 已选择 {os.path.basename(path)}（{BASE_TYPE_LABELS[bt]}）")
            else:
                self._log(f"[底模] 已选择 {os.path.basename(path)}（类型待确认，可点「选择底模文件」重新识别）")
        self._refresh_guide()

    def _set_base_type(self, bt):
        """设置底模类型并应用预设（不触发下拉事件）。"""
        if bt not in ("sd15", "sdxl"):
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
        if bt in ("sd15", "sdxl"):
            self._set_base_type(bt)
            self._log(f"[底模] 自动识别为 {BASE_TYPE_LABELS[bt]}：{os.path.basename(path)}")
        else:
            self._log(f"[底模] 未能自动识别：{os.path.basename(path)}，请手动选择底模类型。")
        return bt

    def _handle_base_detected(self, path, bt):
        self._refresh_status()
        if bt in ("sd15", "sdxl"):
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
