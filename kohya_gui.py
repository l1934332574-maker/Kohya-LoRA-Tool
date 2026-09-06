# -*- coding: utf-8 -*-
"""Kohya-LoRA 一键训练工具 · 新版 CustomTkinter UI（kohya_gui.py）
业务逻辑全部复用 Kohya一键工具.py，本文件只负责界面。
入口：python kohya_gui.py
"""
import os
import sys
import queue
import threading
import platform
import subprocess
import functools
import traceback
import re
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox
import webbrowser

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFilter, ImageTk

import Kohya一键工具 as core
try:
    from model_downloader import ModelDownloader as _ModelDownloader
except Exception:
    _ModelDownloader = None

def _family_chain():
    s = platform.system()
    if s == "Windows": return ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI")
    if s == "Darwin":  return ("San Francisco", "PingFang SC")
    if s == "Linux":   return ("Noto Sans", "Noto Sans SC")
    return ("Arial",)
FONT_CHAIN = _family_chain()

def ui_font(ft):
    family = FONT_CHAIN[0]
    try:
        avail = set(tkfont.families())
        for c in FONT_CHAIN:
            if c in avail:
                family = c
                break
    except Exception:
        pass
    return (family, ft[-2], ft[-1])

FONT_TITLE = (*FONT_CHAIN, 16, "normal")
FONT_BODY  = (*FONT_CHAIN, 13, "normal")
FONT_HINT  = (*FONT_CHAIN, 11, "normal")
FONT_BADGE = (*FONT_CHAIN, 11, "normal")
FONT_LOG   = ("Consolas", "Microsoft YaHei", 12, "normal")

THEMES = {
    "dark": {
        "BG": "#1e2128", "SIDEBG": "#20232a", "CARD": "#272b34", "CARD2": "#2b303a",
        "BORDER": "#373d49", "ACC": "#6d7f99", "ACC_H": "#7c8fa8", "TXT": "#d6dae3",
        "SUB": "#9aa0ad", "HINT": "#7c8290", "TITLE_C": "#e2e5ec", "SEL": "#262b34",
        "SELBAR": "#7a8aa5", "OK_BG": "#343c33", "OK_TX": "#b7c6a8", "HW_BG": "#333a46",
        "HW_TX": "#b9c3d2", "LOG_BG": "#16181e", "STEP_DONE": "#5c7c66", "STEP_CUR": "#7a8aa5", "STEP_PEND": "#3a4150",
    },
    "light": {
        "BG": "#f2f3f5", "SIDEBG": "#e9ebef", "CARD": "#ffffff", "CARD2": "#eef0f4",
        "BORDER": "#d5d9e0", "ACC": "#5b6f96", "ACC_H": "#4d6188", "TXT": "#2a2d33",
        "SUB": "#6b7080", "HINT": "#8b909e", "TITLE_C": "#1f2228", "SEL": "#e2e6ee",
        "SELBAR": "#5b6f96", "OK_BG": "#dceadc", "OK_TX": "#2f5d3a", "HW_BG": "#dce3f0",
        "HW_TX": "#33456b", "LOG_BG": "#1e2128", "STEP_DONE": "#7fa383", "STEP_CUR": "#5b6f96", "STEP_PEND": "#c6cad2",
    },
}

LOG_OK   = "#9ecb8f"
LOG_WARN = "#d4b06a"
LOG_ERR  = "#e08a8a"
LOG_INFO = "#8fa8d4"
LOG_TRAIN= "#8fb0c9"
def _apply_theme_globals(key):
    global BG, SIDEBG, CARD, CARD2, BORDER, ACC, ACC_H, TXT, SUB, HINT, TITLE_C
    global SEL, SELBAR, OK_BG, OK_TX, HW_BG, HW_TX, LOG_BG, STEP_DONE, STEP_CUR, STEP_PEND
    t = THEMES.get(key, THEMES["dark"])
    BG, SIDEBG, CARD, CARD2, BORDER = t["BG"], t["SIDEBG"], t["CARD"], t["CARD2"], t["BORDER"]
    ACC, ACC_H, TXT, SUB, HINT, TITLE_C = t["ACC"], t["ACC_H"], t["TXT"], t["SUB"], t["HINT"], t["TITLE_C"]
    SEL, SELBAR, OK_BG, OK_TX, HW_BG, HW_TX = t["SEL"], t["SELBAR"], t["OK_BG"], t["OK_TX"], t["HW_BG"], t["HW_TX"]
    LOG_BG, STEP_DONE, STEP_CUR, STEP_PEND = t["LOG_BG"], t["STEP_DONE"], t["STEP_CUR"], t["STEP_PEND"]

_apply_theme_globals("dark")

# 风格预设（高级参数快捷填入）：动漫 / 写实
STYLE_PRESETS = {
    "动漫": {"rank": "32", "alpha": "16", "unet_lr": "7e-5", "te_lr": "4e-5", "repeats": "6", "max_epochs": "6"},
    "写实": {"rank": "24", "alpha": "12", "unet_lr": "1e-4", "te_lr": "6e-5", "repeats": "4", "max_epochs": "6"},
}

# AMD ROCm 官方 Windows 发布版本（升级 ROCm 时只改这里）
# wheel 地址模板：https://repo.radeon.com/rocm/windows/rocm-rel-<ver>/...
AMD_ROC_VERSION = "7.2.1"
AMD_TORCH_VERSION = "2.9.1"
AMD_TORCHVISION_VERSION = "0.24.1"
AMD_DRIVER_MIN = "26.2.2"

_MAIN_BTN_TIPS = {
    "数据预处理": "缩放/去黑边/去水印/打标签。一键开始训练会自动做，老手可单独用。",
    "一键训练": "用已经预处理好的数据直接训练（需要先选好底模）。",
    "打开输出文件夹": "打开训练产物目录：模型、使用模板、参数报告、中间快照。",
    "使用说明": "打开新手教学 & 常见问题窗口。",
    "标签编辑器": "打开标签编辑器：逐张看图改标签、批量删除/替换标签、置顶 trigger、标签频率统计、整理成 repeats_名称 子目录结构。训练前改好标签，模型学得更准。",
}

# GUI 显示 → 训练参数 optimizer 映射（resolve_optimizer 接受小写）
_OPT_GUI_MAP = {"自动": "auto", "AdamW": "adamw", "Lion": "lion", "AdamW8bit": "adamw8bit"}
# GUI 显示 → Krea2/FLUX.2 底模量化方式（auto=按显存档位自动选 fp8/int8）
_QUANT_GUI_MAP = {"自动": "auto", "fp8": "fp8", "int8": "int8", "nf4": "nf4"}
# 预处理裁切比例：显示文本 -> 宽:高（"" = 不裁切保比例）
_CROP_RATIO_PRESETS = {
    "不裁切（保比例）": "",
    "1:1 正方形": "1:1",
    "3:4 竖图": "3:4",
    "4:3 横图": "4:3",
    "9:16 竖图": "9:16",
    "16:9 横图": "16:9",
}
_CROP_RATIO_LABELS = {v: k for k, v in _CROP_RATIO_PRESETS.items()}

def _crop_ratio_parse(text):
    """界面显示文本 -> 宽:高 比例（"" = 不裁切）；预设之外支持自定义输入（如 2:3）。"""
    text = (text or "").strip()
    if text in _CROP_RATIO_PRESETS:
        return _CROP_RATIO_PRESETS[text]
    return core.normalize_crop_ratio(text)

def _crop_ratio_label(ratio):
    """宽:高 比例 -> 界面显示文本（自定义比例原样回填）。"""
    ratio = (ratio or "").strip()
    if ratio in _CROP_RATIO_LABELS:
        return _CROP_RATIO_LABELS[ratio]
    return ratio or "不裁切（保比例）"

# 方案A：侧边栏引擎导航（引擎 → 模式；模式选择替代顶部训练模式下拉）
ENGINE_GROUPS = [
    ("第一引擎 · kohya", ("style", "character", "concept")),
    ("第二引擎 · musubi", ("krea2", "flux2")),
    ("第三引擎 · ai-toolkit", ("video", "krea2_at", "qwen_image", "zimage")),
    ("第四引擎 · fizgig", ("krea2_fz",)),
]
SHORT_MODE_LABELS = {
    "style": "画风", "character": "人物", "concept": "概念", "krea2": "Krea2", "flux2": "FLUX.2",
    "krea2_fz": "Krea2F", "video": "视频H3", "krea2_at": "Krea2AT", "qwen_image": "Qwen", "zimage": "Z-Image",
}

class Tooltip:
    """鼠标悬停显示通俗中文说明的气泡（适配 customtkinter 控件）。"""

    def __init__(self, widget, text, wrap=360):
        self.widget = widget
        self.text = text
        self.wrap = wrap
        self.tip = None
        self._bind_recursive(widget, "<Enter>", self._enter)
        self._bind_recursive(widget, "<Leave>", self._leave)

    def _bind_recursive(self, w, ev, cb):
        try:
            w.bind(ev, cb, add="+")
        except Exception:
            pass
        try:
            for child in w.winfo_children():
                self._bind_recursive(child, ev, cb)
        except Exception:
            pass

    def _enter(self, _e=None):
        if self.tip is not None or not self.text:
            return
        try:
            root = self.widget.winfo_toplevel()
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
            self.tip = tk.Toplevel(root)
            self.tip.wm_overrideredirect(True)
            self.tip.wm_geometry(f"+{x}+{y}")
            self.tip.attributes("-topmost", True)
            lbl = tk.Label(self.tip, text=self.text, justify="left", bg="#2f343d",
                           fg="#e2e5ec", relief="solid", borderwidth=1, wraplength=self.wrap,
                           font=("Microsoft YaHei UI", 10), padx=9, pady=6)
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

def _hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

@functools.lru_cache(maxsize=256)
def _make_shadow(cw, ch, corner, color, alpha, ox, oy, blur, pad):
    W, H = cw + 2*pad, ch + 2*pad
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    r, g, b = _hex2rgb(color)
    a = int(255 * alpha)
    x0, y0 = pad + ox, pad + oy
    x1, y1 = x0 + cw, y0 + ch
    for scale, rblur in ((1.0, blur), (0.5, blur + 3), (0.22, blur + 6)):
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dd = ImageDraw.Draw(lay)
        dd.rounded_rectangle([x0, y0, x1, y1], radius=corner, fill=(r, g, b, int(a * scale)))
        lay = lay.filter(ImageFilter.GaussianBlur(radius=rblur))
        img = Image.alpha_composite(img, lay)
    return ImageTk.PhotoImage(img)

def create_soft_shadow_card(parent, corner_radius=8, pad=10, offset=(1, 2),
                            blur=9, shadow="#101318", alpha=0.28, fg_color=None, bg=None):
    if bg is None:
        bg = parent.cget("fg_color")
        if isinstance(bg, (tuple, list)):
            bg = bg[0]
        if not isinstance(bg, str) or not bg.startswith("#"):
            bg = BG
    if fg_color is None:
        fg_color = CARD
    canvas = tk.Canvas(parent, bg=bg, highlightthickness=0, bd=0, height=10)
    inner = ctk.CTkFrame(canvas, corner_radius=corner_radius, fg_color=fg_color)
    wid = canvas.create_window(pad, pad, window=inner, anchor="nw")
    _st = {"key": None, "after": None}
    def _render(key, cw, ch):
        _st["after"] = None
        if _st["key"] == key:
            return
        img = _make_shadow(cw, ch, corner_radius, shadow, alpha, offset[0], offset[1], blur, pad)
        canvas.delete("shd")
        canvas.create_image(0, 0, image=img, anchor="nw", tags="shd")
        canvas.tag_lower("shd")
        canvas.itemconfigure(wid, width=cw)
        canvas.configure(height=ch + 2 * pad)
        canvas._shadow_img = img
        _st["key"] = key
    def _layout(_e=None):
        cw = inner.winfo_reqwidth()
        ch = inner.winfo_reqheight()
        cw_avail = canvas.winfo_width() - 2 * pad
        if cw_avail > 20:
            cw = max(cw, cw_avail)
        if cw <= 10 or ch <= 10:
            return
        key = (cw, ch, corner_radius)
        if key == _st["key"]:
            return
        # 防抖：快速缩放/滚动时等 40ms 后再算一次，避免每帧都做高斯模糊
        if _st["after"] is not None:
            try:
                canvas.after_cancel(_st["after"])
            except Exception:
                pass
        _st["after"] = canvas.after(40, lambda: _render(key, cw, ch))
    inner.bind("<Configure>", _layout)
    canvas.bind("<Configure>", _layout)
    return canvas, inner

# ---------- 一键导出日志（反馈/求助时直接发这个 txt，含环境信息） ----------
def _collect_env_lines():
    """收集环境信息文本行（导出日志用；任一步失败不阻塞，只跳过该行）。"""
    out = []
    try:
        out.append("操作系统: %s" % platform.platform())
    except Exception:
        pass
    try:
        _py, _ver = core.find_python()
        out.append("检测到 Python: %s (%s)" % (_py, _ver or "?"))
    except Exception:
        pass
    try:
        _git = core.find_git()
        out.append("Git: %s" % (_git or "未找到"))
    except Exception:
        pass
    try:
        _gi = core.detect_gpu_info()
        out.append("显卡: %s（厂商 %s，显存 %sGB）" % (_gi.get("name") or "?", _gi.get("vendor") or "?", _gi.get("vram_gb") or "?"))
        if not _gi.get("gpu_ok"):
            out.append("⚠ 未检测到可用独立显卡驱动（重装系统后常见）：请先安装显卡驱动，否则无法训练。")
        elif _gi.get("nvidia_smi_broken"):
            out.append("⚠ nvidia-smi 不可用（NVIDIA 驱动异常）：建议重装/更新显卡驱动。")
    except Exception:
        pass
    try:
        _ram = core.detect_ram_gb()
        out.append("系统内存: %sGB" % ("%.1f" % _ram if _ram else "?"))
    except Exception:
        pass
    try:
        _r = core.safe_nvidia_smi(["--query-gpu=driver_version", "--format=csv,noheader"], timeout=6)
        if _r and _r.returncode == 0 and (_r.stdout or "").strip():
            out.append("NVIDIA 驱动: %s" % _r.stdout.strip().splitlines()[0].strip())
    except Exception:
        pass
    out.append("安装目录: %s" % core.KIT_DIR)
    out.append("数据目录: %s" % core.data_dir())
    try:
        _st = core.system_status()
        out.append("第一引擎(kohya): %s" % ("已安装" if _st.get("kohya_ok") else "未安装"))
        out.append("第二引擎(musubi): %s" % ("已安装" if _st.get("musubi_ok") else "未安装"))
        out.append("第三引擎(ai-toolkit): %s" % ("已安装" if _st.get("at_ok") else "未安装"))
        out.append("第四引擎(fizgig): %s" % ("已安装" if _st.get("fizgig_ok") else "未安装"))
    except Exception:
        pass
    try:
        _vpy = core.venv_python(core.get_kohya_dir())
        if _vpy and os.path.isfile(_vpy):
            out.append("训练环境 torch 后端: %s" % (core.detect_torch_backend(_vpy) or "无法检测"))
    except Exception:
        pass
    return out

def _export_log_text(log_text, project, env_lines=None):
    """组装导出日志全文（纯函数，便于测试；env_lines 为空时自动收集环境信息）。"""
    if env_lines is None:
        env_lines = _collect_env_lines()
    L = []
    L.append("=" * 58)
    L.append("Kohya-LoRA 一键训练工具 · 运行日志")
    L.append("=" * 58)
    L.append("导出时间: %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    L.append("软件版本: v%s" % core.APP_VERSION)
    L.append("项目: %s" % (project or "（未打开项目）"))
    L.append("")
    L.append("【环境信息】")
    L.extend(env_lines or [])
    L.append("")
    L.append("【运行日志】")
    L.append(log_text if log_text else "（暂无日志）")
    return "\n".join(L)

class App:
    def __init__(self):
        self.q = queue.Queue()
        # 完整运行日志（不分行数保留，导出用；界面日志框另有 3000 行显示上限，避免 Tk 内存/GDI 耗尽）
        self._full_log = []
        self.mode = "character"
        self.base_type = "sd15"
        self.busy = False
        self._manual_override = set()
        self._applying_preset = False
        self._base_models = []
        self._base_items = []
        self._dl = None
        self._dl_kind = "base"          # 当前下载任务类型：base=底模 / h3=H3模型
        self.ui_proc = None
        self._label_editor = None
        # ---- 项目化管理状态 ----
        self.current_project = None          # 当前打开的项目名（None=主页）
        self._saving = False                 # 自动保存防递归标志
        self._autosave_after = None          # 防抖定时器

        self.root = ctk.CTk()
        self.project_name_var = tk.StringVar()
        self.root.title(core.APP_NAME + " · v" + getattr(core, "APP_VERSION", "0.0.0"))
        self.root.geometry("1180x900")
        self.root.minsize(1040, 780)
        self.root.configure(fg_color=BG)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        try:
            ico = os.path.join(core.KIT_DIR, "app.ico")
            if os.path.isfile(ico):
                self.root.iconbitmap(ico)
        except Exception:
            pass

        self.param_vars = {}
        self.raw_dir_var = tk.StringVar()
        self.trigger_var = tk.StringVar()
        # 人物强绑定（默认开）：自动把 trigger + 100% 一致特征词固定到标签开头，一个词绑定一个人物
        self.strong_bind_var = tk.BooleanVar(value=True)
        # 训练中采样出图预览（默认开；低显存 <10G 训练时自动关闭）
        self.sample_preview_var = tk.BooleanVar(value=True)
        # 采样预览提示词（留空=自动生成；填了用用户整句，训练不再覆盖）
        self.sample_prompt_var = tk.StringVar()
        # 预处理裁切比例（默认不裁切保比例）：可选手动 1:1/3:4/9:16 等，或直接输入自定义 宽:高（如 2:3）
        self.crop_ratio_var = tk.StringVar(value="不裁切（保比例）")
        # Qwen-Image / Z-Image 的画风/人物子模式（AT_SUB_LABELS 见类级常量）
        self.at_sub_var = tk.StringVar(value="人物（保留全部标签）")
        self.reg_var = tk.StringVar()
        self.global_pos_var = tk.StringVar()
        self.global_neg_var = tk.StringVar()
        self.base_model_var = tk.StringVar()
        self.unet_only_var = tk.BooleanVar(value=False)
        self.guide_status = {"env": "未做", "kohya": "未做", "base": "未选", "raw": "未选"}
        self._guide_vars = {}          # 动态引导：步骤 id -> StringVar
        self._guide_row_widgets = []   # 动态引导：已渲染的行控件
        self._guide_hl_after = None    # 引导高亮闪烁定时器
        self._guide_hl_step = None     # 当前高亮的步骤 id
        self._badge_widgets = []
        self._main_widgets = []
        self._adv_entries = {}
        self._adv_frames = {}
        self._main_btns = {}
        self.amd_var = tk.BooleanVar(value=False)
        self.amd_env_var = tk.StringVar()
        self.train_env_var = tk.StringVar()
        try:
            self._gpu_info = core.detect_gpu_info()
        except Exception:
            self._gpu_info = {"vendor": "unknown", "name": None, "vram_gb": None}

        self._build_ui()
        self._scan_base_models()
        self._apply_presets()
        self._update_mode_ui()
        self._build_home()
        self._show_home()
        self._bind_autosave_traces()
        # 环境/显卡检测放后台线程预热，界面先秒开，避免启动卡顿
        self._refresh_status_async()
        self.root.after(100, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # 启动 8 秒后后台检查新版本（不阻塞界面，有新版本才提示）
        try:
            self.root.after(8000, self._auto_check_update)
        except Exception:
            pass

    # ---------- 日志 ----------
    def _log(self, text):
        text = str(text)
        if getattr(self, "_full_log", None) is None:
            self._full_log = []
        self._full_log.append(text)
        self.log.insert("end", text + "\n")
        # 界面日志框行数上限（防 Tk 内存/GDI 耗尽弹窗）；完整日志在 self._full_log，导出不受影响。
        try:
            _MAX_LOG_LINES = 3000
            _cur = int(self.log.index("end-1c").split(".")[0])
            if _cur > _MAX_LOG_LINES:
                self.log.delete("1.0", "%d.0" % (_cur - _MAX_LOG_LINES))
        except Exception:
            pass
        tag = None
        if any(k in text for k in ("[OK]", "完成", "成功")):
            tag = "ok"
        elif any(k in text for k in ("[WARN]", "警告", "注意")):
            tag = "warn"
        elif any(k in text for k in ("[ERROR]", "失败", "错误", "✘")):
            tag = "err"
        elif any(k in text for k in ("[训练]", "loss")):
            tag = "train"
        elif any(k in text for k in ("[底模]", "[预处理]", "[WD14]", "[环境]", "[Kohya]")):
            tag = "info"
        if tag:
            self.log.tag_add(tag, "end-2l", "end-1l")
        self.log.see("end")

    # ---------- 线程 / 队列 ----------
    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                self._handle(item)
        except queue.Empty:
            pass
        self._poll_n = getattr(self, "_poll_n", 0) + 1
        if self._poll_n % 8 == 0:
            self._refresh_monitor()
        self.root.after(120, self._poll)

    def _handle(self, item):
        if item == "__DONE__":
            self._set_busy(False)
        elif isinstance(item, tuple):
            kind = item[0]
            if kind == "LOG":
                self._log(item[1])
            elif kind == "STATUS":
                self._refresh_status()
            elif kind == "BASE_DETECTED":
                self._refresh_status()
            elif kind == "BASE_SCAN_DONE":
                self._apply_base_models(item[1] if len(item) > 1 else [])
            elif kind == "AUTO_CONFIRM":
                self._handle_auto_confirm(item[1], item[2], item[3] if len(item) > 3 else None)
            elif kind == "DL_PROGRESS":
                self._dl_progress_ui(item[1], item[2])
            elif kind == "DL_DONE":
                self._handle_dl_done(item[1], item[2])
            elif kind == "UPDATE_CHECK":
                self._handle_update_check(item[1])
            elif kind == "AUTO_UPDATE":
                self._handle_auto_update(item[1])
            elif kind == "UPDATE_PROGRESS":
                self._handle_update_progress(item[1], item[2] if len(item) > 2 else None)
            elif kind == "UPDATE_DONE":
                self._handle_update_done(item[1], item[2], item[3] if len(item) > 3 else None)

    def _start_worker(self, fn, title):
        # 防重入：同一时间只允许一个后台任务（安装/预处理/训练），
        # 避免连点「② 安装训练内核」导致两个 pip 同时写同一个 venv（文件锁冲突 WinError 32）。
        if self.busy:
            messagebox.showinfo(core.APP_NAME, "有任务正在运行，请先等待当前任务完成。")
            return
        self._set_busy(True)
        self._log("开始：" + title)
        threading.Thread(target=fn, daemon=True).start()

    def _set_busy(self, v):
        self.busy = v
        state = ("disabled" if v else "normal")
        # 左侧引导按钮（①环境 ②安装 ③底模 ④图片）
        for b in getattr(self, "_guide_btns", {}).values():
            try:
                b.configure(state=state)
            except Exception:
                pass
        # 右侧主操作按钮（预处理/训练/打开输出/使用说明）
        for b in getattr(self, "_main_btns", {}).values():
            try:
                b.configure(state=state)
            except Exception:
                pass
        # 其它操作按钮
        for name in ("btn_pick_base", "btn_refresh_base", "btn_download_base",
                     "btn_pick_raw", "btn_pick_reg", "btn_toggle_adv", "btn_reset_preset",
                     "btn_amd_env", "btn_pick_train_env",
                     "btn_back_home", "btn_new_project"):
            b = getattr(self, name, None)
            if b is not None:
                try:
                    b.configure(state=state)
                except Exception:
                    pass
        # 一键开始训练：忙碌时禁用；空闲时按引导完成状态恢复
        try:
            if v:
                self.btn_one_click.configure(state="disabled")
            else:
                self._refresh_one_click_state()
        except Exception:
            pass
        # 停止按钮：任务进行中显示并可点，空闲时隐藏
        try:
            if v:
                self.btn_stop.configure(state="normal")
                self.btn_stop.pack(fill="x", padx=14, pady=(4, 2), before=self._sidebar_spacer)
            else:
                self.btn_stop.pack_forget()
        except Exception:
            pass

    def _refresh_status_async(self):
        """后台线程预热环境检测，完成后回到主线程刷新徽章/引导状态（启动秒开）。"""
        def _w():
            try:
                core.system_status(force=True)   # 后台跑 git/python/gpu 检测
            except Exception:
                pass
            try:
                self.q.put(("STATUS",))
            except Exception:
                pass
        try:
            threading.Thread(target=_w, daemon=True).start()
        except Exception:
            pass

    def _build_monitor_bar(self, parent):
        """训练实时监控面板（步数/loss/显存/预计时间/loss曲线）。"""
        self.mon = ctk.CTkFrame(parent, fg_color="#16181e", corner_radius=0)
        self.mon_row1 = ctk.CTkFrame(self.mon, fg_color="transparent"); self.mon_row1.pack(fill="x", padx=26, pady=(10, 0))
        ctk.CTkLabel(self.mon_row1, text="📊 训练监控", font=ui_font(FONT_TITLE), text_color=TITLE_C).pack(side="left")
        self.mon_step_var = tk.StringVar(value="步数 0 / 0（0%）")
        ctk.CTkLabel(self.mon_row1, textvariable=self.mon_step_var, font=ui_font(FONT_BODY),
                     text_color=SUB).pack(side="left", padx=(18, 0))
        ctk.CTkButton(self.mon_row1, text="📤 导出日志", width=100, height=26, fg_color="transparent",
                      hover_color="#252a36", border_width=1, border_color=BORDER, text_color=SUB,
                      corner_radius=6, font=ui_font(FONT_HINT), command=self.cmd_export_log).pack(side="right")
        self.mon_progress = ctk.CTkProgressBar(self.mon, height=10, corner_radius=5,
                                               fg_color="#2b303a", progress_color="#7AA2F7")
        self.mon_progress.set(0)
        self.mon_progress.pack(fill="x", padx=26, pady=(6, 0))
        self.mon_row2 = ctk.CTkFrame(self.mon, fg_color="transparent"); self.mon_row2.pack(fill="x", padx=26, pady=(6, 0))
        self.mon_loss_var = tk.StringVar(value="loss: --")
        self.mon_lr_var = tk.StringVar(value="lr: --")
        self.mon_speed_var = tk.StringVar(value="速度: --")
        self.mon_eta_var = tk.StringVar(value="预计剩余: --")
        self.mon_vram_var = tk.StringVar(value="显存: --")
        for v in (self.mon_loss_var, self.mon_lr_var, self.mon_speed_var, self.mon_eta_var, self.mon_vram_var):
            ctk.CTkLabel(self.mon_row2, textvariable=v, font=ui_font(FONT_HINT), text_color=SUB).pack(side="left", padx=(0, 16))
        self.mon_canvas = tk.Canvas(self.mon, height=70, bg="#14161c", highlightthickness=0)
        self.mon_canvas.pack(fill="x", padx=26, pady=(0, 10))
        self.mon_canvas.create_text(10, 10, text="等待训练数据…", anchor="nw", fill="#7c8290", font=("Microsoft YaHei", 10))
        # 采样预览（训练中每 N 步出图后显示最新一张）
        self.mon_sample_txt = tk.StringVar(value="采样预览：--")
        ctk.CTkLabel(self.mon, textvariable=self.mon_sample_txt, font=ui_font(FONT_HINT),
                     text_color=SUB).pack(anchor="w", padx=26, pady=(4, 2))
        self.mon_sample_lbl = ctk.CTkLabel(self.mon, text="（训练中每 100 步出一张预览图）",
                                           font=ui_font(FONT_HINT), text_color="#7c8290")
        self.mon_sample_lbl.pack(anchor="w", padx=26, pady=(0, 10))
        self._mon_visible = False

    def _show_monitor(self, v):
        try:
            if v and not self._mon_visible:
                self.mon.pack(fill="x", side="bottom", pady=(0, 0), before=self.logbar_ref)
                self._mon_visible = True
            elif not v and self._mon_visible:
                self.mon.pack_forget()
                self._mon_visible = False
        except Exception:
            pass

    def _refresh_monitor(self):
        mon = getattr(self, "_train_mon", None)
        if mon is None or not getattr(self, "_mon_visible", False):
            return
        try:
            snap = mon.snapshot()
            phase = snap.get("phase") or "idle"
            total = snap.get("total") or 0
            step = snap.get("step") or 0
            if phase == "cache":
                # 数据集缓存阶段：缓存 tqdm 是批次进度，不是训练步数，单独提示
                self.mon_progress.set(0.0)
                self.mon_step_var.set("正在缓存数据集…（非训练进度）")
                self.mon_eta_var.set("预计剩余: --")
                return
            # 无进展超时提示：训练已启动但长时间没有任何新日志/loss
            # （如 CPU 训练极慢、子进程卡死/静默退出），给出明确提示而不是一直挂着"等待训练数据"。
            if snap.get("running") and phase in ("idle", "train") and (snap.get("loss") is None) and (snap.get("step") or 0) == 0:
                _last = snap.get("last_activity") or snap.get("started_at") or time.time()
                _idle = time.time() - _last
                if _idle > 180:
                    self.mon_step_var.set(f"⚠ 已 {int(_idle // 60)} 分钟无训练输出，训练可能卡住或已退出，请看上方日志")
                    self.mon_progress.set(0.0)
                    self.mon_eta_var.set("预计剩余: --")
                    return
            pct = (step / total) if total else 0.0
            self.mon_progress.set(min(max(pct, 0.0), 1.0))
            self.mon_step_var.set(f"步数 {step} / {total}（{pct*100:.0f}%）")
            loss = snap.get("loss")
            if loss is not None:
                diff = ""
                if snap.get("loss_prev") is not None:
                    d = loss - snap["loss_prev"]
                    diff = " ↓" if d < 0 else (" ↑" if d > 0 else " →")
                self.mon_loss_var.set(f"loss: {loss:.4f}{diff}")
            else:
                self.mon_loss_var.set("loss: --")
            lr = snap.get("lr")
            self.mon_lr_var.set(f"lr: {lr:.2e}" if lr else "lr: --")
            sp = snap.get("speed") or 0.0
            # 速度单位与训练日志（tqdm）统一：>=1 it/s 用 it/s，否则用 s/it（两者互为倒数）
            if sp <= 0:
                self.mon_speed_var.set("速度: --")
            elif sp >= 1.0:
                self.mon_speed_var.set(f"速度: {sp:.2f} it/s")
            else:
                self.mon_speed_var.set(f"速度: {1.0 / sp:.2f} s/it")
            self.mon_eta_var.set("预计剩余: " + core.format_eta(snap.get("eta")))
            # 显存（N 卡）：用安全 nvidia-smi 封装（驱动缺失/损坏时首次失败后不再调用，
            # 避免每 ~1s 刷一次监控就弹一次「应用程序错误」+ GUI 线程卡死）+ 5 秒节流
            if self._gpu_info.get("vendor") == "nvidia" and time.time() - getattr(self, "_mon_vram_last", 0) >= 5:
                self._mon_vram_last = time.time()
                try:
                    r = core.safe_nvidia_smi(["--query-gpu=memory.used,memory.total",
                                              "--format=csv,noheader,nounits"], timeout=3)
                    if r and r.returncode == 0:
                        parts = [p.strip() for p in r.stdout.strip().split(",")]
                        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                            self.mon_vram_var.set(f"显存: {int(parts[0])/1024:.1f}/{int(parts[1])/1024:.1f} GB")
                except Exception:
                    pass
            self._draw_loss_curve(snap.get("loss_history") or [])
            self._refresh_sample_preview()
        except Exception:
            pass

    def _is_sample_file(self, fname, dirname):
        """判断是否训练采样图：ai-toolkit sample_xxx.png / kohya·musubi sample/ 子目录 + <name>_<step>_...png。"""
        low = fname.lower()
        if not low.endswith((".png", ".jpg", ".jpeg", ".webp")):
            return False
        if "sample" in low:
            return True
        if dirname.lower() in ("sample", "samples"):
            return True
        if re.search(r"_\d{4,}_", low) or re.search(r"-\d+\.", low):
            return True
        return False

    def _refresh_sample_preview(self):
        """轮询当前项目输出目录（含 sample/ 子目录），显示最新一张训练采样预览图（2 秒节流，只读不干扰训练）。"""
        now = time.time()
        if now - getattr(self, "_sample_last", 0) < 2.0:
            return
        self._sample_last = now
        try:
            proj = (self.current_project or "").strip()
            out_dir = core.data_sub("output", proj if proj else "_")
            newest = None
            for root, _dirs, files in os.walk(out_dir):
                for f in files:
                    if not self._is_sample_file(f, os.path.basename(root)):
                        continue
                    p = os.path.join(root, f)
                    if newest is None or os.path.getmtime(p) > os.path.getmtime(newest):
                        newest = p
            if newest is None or newest == getattr(self, "_sample_shown", None):
                return
            self._sample_shown = newest
            img = Image.open(newest).convert("RGB")
            img.thumbnail((220, 220))
            photo = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self.mon_sample_lbl.configure(image=photo, text="")
            self.mon_sample_lbl.image = photo
            self.mon_sample_txt.set(f"采样预览：{os.path.basename(newest)}")
        except Exception:
            pass

    def _draw_loss_curve(self, hist):
        try:
            c = self.mon_canvas
            c.delete("all")
            w = max(c.winfo_width(), 10)
            h = max(c.winfo_height(), 10)
            if len(hist) < 2:
                c.create_text(10, 10, text="等待训练数据…（loss 曲线）", anchor="nw",
                              fill="#7c8290", font=("Microsoft YaHei", 10))
                return
            data = hist[-50:]
            mn, mx = min(data), max(data)
            span = (mx - mn) or 1.0
            pad = 6
            for gy in (0.25, 0.5, 0.75):
                yy = pad + gy * (h - 2 * pad)
                c.create_line(pad, yy, w - pad, yy, fill="#22262e", width=1)
            pts = []
            for i, v in enumerate(data):
                x = pad + i * (w - 2 * pad) / (len(data) - 1)
                y = h - pad - (v - mn) / span * (h - 2 * pad)
                pts.append((x, y))
            flat = [p for pt in pts for p in pt]
            c.create_line(flat, fill="#7AA2F7", width=2, smooth=True)
            c.create_text(w - pad, 4, text=f"loss 最近{len(data)}步 ↓", anchor="ne",
                          fill="#9aa0ad", font=("Microsoft YaHei", 9))
        except Exception:
            pass

    def _on_close(self):
        try:
            if getattr(self, "current_project", None):
                self._autosave()
        except Exception:
            pass
        try:
            if self.ui_proc is not None and self.ui_proc.poll() is None:
                self.ui_proc.terminate()
        except Exception:
            pass
        self.root.destroy()

    # ============ 总布局：左侧新手引导 + 右侧（顶部条 + 可滚动主区 + 底部日志） ============
    def _build_ui(self):
        # ---------- 左侧：新手引导（环境/安装/选底模/选图片/一键） ----------
        self.sidebar = ctk.CTkFrame(self.root, fg_color=SIDEBG, width=252, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        logo = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo.pack(fill="x", padx=16, pady=(20, 12))
        ctk.CTkFrame(logo, width=26, height=26, fg_color="#4a5568", corner_radius=5).pack(side="left")
        ctk.CTkLabel(logo, text="Kohya-LoRA", font=ui_font(FONT_BODY), text_color=TXT).pack(side="left", padx=(9, 0))
        # 方案A：引擎导航（模式一级入口，替代顶部训练模式下拉）
        self.engine_nav = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.engine_nav.pack(fill="x", padx=10, pady=(10, 2))
        self._nav_mode_btns = {}
        for _gi, (_gname, _modes) in enumerate(ENGINE_GROUPS):
            ctk.CTkLabel(self.engine_nav, text="▍" + _gname, font=ui_font(FONT_HINT),
                         text_color=SUB, anchor="w").pack(fill="x", padx=(2, 0), pady=(8 if _gi else 0, 2))
            _rf = ctk.CTkFrame(self.engine_nav, fg_color="transparent"); _rf.pack(fill="x")
            if len(_modes) >= 4:
                # 4 个模式（第三引擎：视频H3/Krea2AT/Qwen/Z-Image）：单行 4×64px 超出侧边栏（252px）会挤压，
                # 改 2×2 网格等宽铺满；1~2 个模式的引擎组保持原单行布局。
                _rf.grid_columnconfigure(0, weight=1)
                _rf.grid_columnconfigure(1, weight=1)
                for _mi, _mk in enumerate(_modes):
                    _btn = ctk.CTkButton(_rf, text=SHORT_MODE_LABELS.get(_mk, _mk), height=26,
                                         fg_color=CARD2, hover_color="#3a4150", corner_radius=6,
                                         font=ui_font(FONT_HINT), text_color=TXT,
                                         command=lambda m=_mk: self._nav_select_mode(m))
                    _btn.grid(row=_mi // 2, column=_mi % 2, sticky="ew", padx=(2, 4), pady=2)
                    self._nav_mode_btns[_mk] = _btn
            else:
                for _mk in _modes:
                    _btn = ctk.CTkButton(_rf, text=SHORT_MODE_LABELS.get(_mk, _mk), width=64, height=26,
                                         fg_color=CARD2, hover_color="#3a4150", corner_radius=6,
                                         font=ui_font(FONT_HINT), text_color=TXT,
                                         command=lambda m=_mk: self._nav_select_mode(m))
                    _btn.pack(side="left", padx=(2, 4), pady=2)
                    self._nav_mode_btns[_mk] = _btn
        self._guide_dots = {}
        self._guide_btns = {}
        self._guide_vars = {}
        # 引导区：固定位置（logo 正下方，不参与顶部 pack 顺序变动），内容按模式动态切换
        self.guide_area = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.guide_area.pack(fill="x", padx=14, pady=(0, 6))
        self.guide_title = ctk.CTkLabel(self.guide_area, text="🎓 新手引导（按顺序做）", font=ui_font(FONT_HINT), text_color=SUB)
        self.guide_placeholder = ctk.CTkLabel(self.guide_area,
                                              text="👆 请先打开/新建项目\n然后选择训练模式\n\n引导会按模式自动生成",
                                              font=ui_font(FONT_HINT), text_color=SUB, justify="left")
        self.guide_placeholder.pack(anchor="w", pady=(6, 2))
        self.guide_host = ctk.CTkFrame(self.guide_area, fg_color="transparent")

        self.btn_one_click = ctk.CTkButton(self.sidebar, text="🚀 一键开始训练", height=42,
                                           fg_color=CARD2, hover_color="#343a46", corner_radius=8,
                                           font=ui_font(FONT_BODY), state="disabled",
                                           command=self.cmd_one_click_train)
        self.btn_one_click.pack(fill="x", padx=14, pady=(14, 2))
        self.btn_one_click_hint = ctk.CTkLabel(self.sidebar, text="完成 ①②③④ 后自动点亮", font=ui_font(FONT_HINT), text_color=HINT)
        self.btn_one_click_hint.pack(anchor="w", padx=16, pady=(0, 4))

        self.btn_stop = ctk.CTkButton(self.sidebar, text="⏹ 停止当前任务", height=34,
                                      fg_color="#4a3535", hover_color="#5a4141", corner_radius=8,
                                      font=ui_font(FONT_BODY), state="disabled",
                                      command=self.cmd_stop)
        # 平时不显示，任务进行中（_set_busy(True)）才显示在「一键开始训练」下方

        sp = ctk.CTkFrame(self.sidebar, fg_color="transparent"); sp.pack(expand=True)
        self._sidebar_spacer = sp
        # 注：深浅主题切换有兼容问题，暂移除，固定深色

        # ---------- 右侧 ----------
        right = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        right.pack(side="left", fill="both", expand=True)

        # 主页容器（项目列表，默认显示）；工作容器（打开项目后的配置页，默认隐藏）
        self.home_frame = ctk.CTkFrame(right, fg_color=BG, corner_radius=0)
        self.home_frame.pack(fill="both", expand=True)
        self.work_frame = ctk.CTkFrame(right, fg_color=BG, corner_radius=0)

        # 顶部条：标题 + 模式切换 + 底模 + 状态徽章
        top = ctk.CTkFrame(self.work_frame, fg_color="transparent")
        top.pack(fill="x", padx=26, pady=(18, 0))
        row1 = ctk.CTkFrame(top, fg_color="transparent"); row1.pack(fill="x")
        self.btn_back_home = ctk.CTkButton(row1, text="← 返回项目", width=90, height=28, fg_color=CARD2,
                                           hover_color="#343a46", border_width=1, border_color=BORDER,
                                           text_color=TXT, corner_radius=6, font=ui_font(FONT_HINT),
                                           command=self.cmd_back_home)
        self.btn_back_home.pack(side="left", padx=(0, 12))
        self.home_title = ctk.CTkLabel(row1, text="人物角色 LoRA 训练", font=ui_font(FONT_TITLE), text_color=TITLE_C)
        self.home_title.pack(side="left")
        self.proj_title = ctk.CTkLabel(row1, text="", font=ui_font(FONT_BODY), text_color=ACC)
        self.proj_title.pack(side="left", padx=(14, 0))
        st = ctk.CTkFrame(top, fg_color="transparent"); st.pack(fill="x", pady=(8, 0))
        self.badge_frame = st

        row2 = ctk.CTkFrame(top, fg_color="transparent"); row2.pack(fill="x", pady=(10, 0))
        # 训练模式改由侧边栏「引擎导航」选择（方案A）；下拉保留供程序内部同步、不再显示
        self.mode_combo = ctk.CTkComboBox(row2, values=[core.MODE_LABELS[k] for k in core.MODE_KEYS], width=180, height=30,
                                          fg_color=CARD2, border_color=BORDER, button_color=CARD2, button_hover_color="#3a4150",
                                          text_color=TXT, font=ui_font(FONT_BODY), dropdown_font=ui_font(FONT_BODY),
                                          dropdown_fg_color=CARD2, dropdown_hover_color="#3a4150",
                                          command=lambda _e: self._on_mode_change())
        # 不 pack：隐藏（侧边栏导航是唯一入口）
        self.base_label = ctk.CTkLabel(row2, text="基础底模", font=ui_font(FONT_BODY), text_color=SUB)
        self.base_label.pack(side="left")
        self.base_combo = ctk.CTkComboBox(row2, values=[], width=200, height=30,
                                          fg_color=CARD2, border_color=BORDER, button_color=CARD2, button_hover_color="#3a4150",
                                          text_color=TXT, font=ui_font(FONT_BODY), dropdown_font=ui_font(FONT_BODY),
                                          dropdown_fg_color=CARD2, dropdown_hover_color="#3a4150",
                                          command=lambda _e: self._on_base_change())
        self.base_combo.pack(side="left", padx=(10, 10))
        self.btn_pick_base = ctk.CTkButton(row2, text="选择底模文件…", width=108, height=30, fg_color=CARD2, hover_color="#343a46",
                                           border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                                           font=ui_font(FONT_BODY), command=self.cmd_pick_base)
        self.btn_pick_base.pack(side="left", padx=4)
        self.btn_refresh_base = ctk.CTkButton(row2, text="↻ 刷新", width=58, height=30, fg_color=CARD2, hover_color="#343a46",
                                              border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                                              font=ui_font(FONT_BODY), command=self.cmd_refresh_base)
        self.btn_refresh_base.pack(side="left", padx=4)
        self.btn_download_base = ctk.CTkButton(row2, text="没有模型？点这里下载", width=148, height=30,
                                               fg_color="transparent", hover_color="#252a36",
                                               border_width=1, border_color=ACC, text_color=ACC, corner_radius=6,
                                               font=ui_font(FONT_BODY), command=self.cmd_download_base)
        self.btn_download_base.pack(side="left", padx=4)
        # Krea2 模型状态（仅 Krea2 模式显示，独立一行占满宽度）
        self.krea2_row = ctk.CTkFrame(top, fg_color="transparent")
        self.krea2_model_var = tk.StringVar(value="")
        ctk.CTkLabel(self.krea2_row, textvariable=self.krea2_model_var, font=ui_font(FONT_BODY), text_color=ACC).pack(side="left")
        self.btn_krea2_models = ctk.CTkButton(self.krea2_row, text="📂 打开 Krea2 模型文件夹", width=170, height=30,
                                              fg_color=CARD2, hover_color="#343a46", border_width=1, border_color=BORDER,
                                              text_color=TXT, corner_radius=6, font=ui_font(FONT_BODY),
                                              command=self.cmd_open_krea2_models)
        self.btn_krea2_models.pack(side="left", padx=(10, 4))
        self.btn_krea2_dl = ctk.CTkButton(self.krea2_row, text="⬇ 下载 Krea2 模型", width=122, height=30,
                                          fg_color=ACC, hover_color=ACC_H, corner_radius=6,
                                          text_color="#ffffff", font=ui_font(FONT_BODY),
                                          command=self.cmd_dl_krea2_models)
        self.btn_krea2_dl.pack(side="left", padx=(4, 4))
        ctk.CTkLabel(self.krea2_row, text="RAW 训练 → LoRA 可用于 Turbo 出图", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left", padx=(8, 0))
        self.btn_krea2_guide = ctk.CTkButton(self.krea2_row, text="📖 使用引导", width=92, height=30,
                                             fg_color="transparent", hover_color="#252a36", border_width=1, border_color=ACC,
                                             text_color=ACC, corner_radius=6, font=ui_font(FONT_BODY),
                                             command=self._show_krea2_guide)
        self.btn_krea2_guide.pack(side="left", padx=(6, 4))
        self.btn_fizgig_install = ctk.CTkButton(self.krea2_row, text="⚙ 安装第四引擎", width=112, height=30,
                                                fg_color="transparent", hover_color="#252a36", border_width=1,
                                                border_color=ACC, text_color=ACC, corner_radius=6, font=ui_font(FONT_BODY),
                                                command=self.cmd_install_fizgig)
        # FLUX.2 模型状态（仅 FLUX.2 模式显示，独立一行占满宽度）
        self.flux2_row = ctk.CTkFrame(top, fg_color="transparent")
        self.flux2_model_var = tk.StringVar(value="")
        ctk.CTkLabel(self.flux2_row, textvariable=self.flux2_model_var, font=ui_font(FONT_BODY), text_color=ACC).pack(side="left")
        self.btn_flux2_models = ctk.CTkButton(self.flux2_row, text="📂 打开 FLUX.2 模型文件夹", width=170, height=30,
                                              fg_color=CARD2, hover_color="#343a46", border_width=1, border_color=BORDER,
                                              text_color=TXT, corner_radius=6, font=ui_font(FONT_BODY),
                                              command=self.cmd_open_flux2_models)
        self.btn_flux2_models.pack(side="left", padx=(10, 4))
        self.btn_flux2_dl = ctk.CTkButton(self.flux2_row, text="⬇ 下载 FLUX.2 模型", width=122, height=30,
                                          fg_color=ACC, hover_color=ACC_H, corner_radius=6,
                                          text_color="#ffffff", font=ui_font(FONT_BODY),
                                          command=self.cmd_dl_flux2_models)
        self.btn_flux2_dl.pack(side="left", padx=(4, 4))
        ctk.CTkLabel(self.flux2_row, text="base 4B 训练 → LoRA 可用于 klein 出图", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left", padx=(8, 0))
        self.btn_flux2_guide = ctk.CTkButton(self.flux2_row, text="📖 使用引导", width=92, height=30,
                                             fg_color="transparent", hover_color="#252a36", border_width=1, border_color=ACC,
                                             text_color=ACC, corner_radius=6, font=ui_font(FONT_BODY),
                                             command=self._show_flux2_guide)
        self.btn_flux2_guide.pack(side="left", padx=(6, 4))
        # MiniMax H3 模型状态（仅视频模式显示，独立一行占满宽度）
        self.h3_row = ctk.CTkFrame(top, fg_color="transparent")
        self.h3_model_var = tk.StringVar(value="")
        ctk.CTkLabel(self.h3_row, textvariable=self.h3_model_var, font=ui_font(FONT_BODY), text_color=ACC).pack(side="left")
        self.btn_h3_models = ctk.CTkButton(self.h3_row, text="📂 打开 H3 模型文件夹", width=170, height=30,
                                           fg_color=CARD2, hover_color="#343a46", border_width=1, border_color=BORDER,
                                           text_color=TXT, corner_radius=6, font=ui_font(FONT_BODY),
                                           command=self.cmd_open_h3_models)
        self.btn_h3_models.pack(side="left", padx=(10, 4))
        self.btn_h3_dl = ctk.CTkButton(self.h3_row, text="⬇ 下载 H3 模型", width=120, height=30,
                                       fg_color=ACC, hover_color=ACC_H, corner_radius=6,
                                       text_color="#ffffff", font=ui_font(FONT_BODY),
                                       command=self.cmd_dl_h3_models)
        self.btn_h3_dl.pack(side="left", padx=(4, 4))
        # 第二行：引擎/字幕操作（避免 8 个按钮挤一行被挤出窗口）
        self.h3_row2 = ctk.CTkFrame(top, fg_color="transparent")
        self.btn_at_install = ctk.CTkButton(self.h3_row2, text="⚙ 安装第三引擎", width=108, height=30,
                                            fg_color="transparent", hover_color="#252a36", border_width=1,
                                            border_color=ACC, text_color=ACC, corner_radius=6, font=ui_font(FONT_BODY),
                                            command=self.cmd_install_at)
        self.btn_at_install.pack(side="left", padx=(4, 4))
        self.btn_at_import = ctk.CTkButton(self.h3_row2, text="📂 导入已装环境", width=116, height=30,
                                           fg_color=CARD2, hover_color="#343a46", border_width=1, border_color=BORDER,
                                           text_color=TXT, corner_radius=6, font=ui_font(FONT_BODY),
                                           command=self.cmd_import_at_env)
        self.btn_at_import.pack(side="left", padx=(4, 4))
        self.btn_h3_captions = ctk.CTkButton(self.h3_row2, text="一键生成占位字幕", width=120, height=30,
                                             fg_color=CARD2, hover_color="#343a46", border_width=1, border_color=BORDER,
                                             text_color=TXT, corner_radius=6, font=ui_font(FONT_BODY),
                                             command=self.cmd_gen_h3_captions)
        self.btn_h3_captions.pack(side="left", padx=(4, 4))
        self.btn_h3_caption_ai = ctk.CTkButton(self.h3_row2, text="✨ AI 自动描述", width=112, height=30,
                                               fg_color=CARD2, hover_color="#343a46", border_width=1,
                                               border_color=BORDER, text_color=TXT, corner_radius=6,
                                               font=ui_font(FONT_BODY),
                                               command=self.cmd_video_caption)
        self.btn_h3_caption_ai.pack(side="left", padx=(4, 4))
        self.btn_h3_guide = ctk.CTkButton(self.h3_row, text="📖 使用引导", width=92, height=30,
                                          fg_color="transparent", hover_color="#252a36", border_width=1,
                                          border_color=ACC, text_color=ACC, corner_radius=6, font=ui_font(FONT_BODY),
                                          command=self._show_h3_guide)
        self.btn_h3_guide.pack(side="left", padx=(6, 4))
        ctk.CTkLabel(self.h3_row, text="24G 显存推荐 · NVIDIA 专属（实验性）", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left", padx=(8, 0))
        # AI Toolkit 图像模型状态行（Qwen-Image / Z-Image 模式显示）
        self.at_row = ctk.CTkFrame(top, fg_color="transparent")
        self.at_model_var = tk.StringVar(value="")
        ctk.CTkLabel(self.at_row, textvariable=self.at_model_var, font=ui_font(FONT_BODY), text_color=ACC).pack(side="left")
        self.btn_at_install = ctk.CTkButton(self.at_row, text="⚙ 安装第三引擎", width=108, height=30,
                                            fg_color="transparent", hover_color="#252a36", border_width=1,
                                            border_color=ACC, text_color=ACC, corner_radius=6, font=ui_font(FONT_BODY),
                                            command=self.cmd_install_at)
        self.btn_at_install.pack(side="left", padx=(10, 4))
        self.btn_at_model_help = ctk.CTkButton(self.at_row, text="📖 模型/显存说明", width=116, height=30,
                                               fg_color=CARD2, hover_color="#343a46", border_width=1,
                                               border_color=BORDER, text_color=TXT, corner_radius=6,
                                               font=ui_font(FONT_BODY), command=self.cmd_at_model_help)
        self.btn_at_model_help.pack(side="left", padx=(4, 4))
        self.btn_at_import2 = ctk.CTkButton(self.at_row, text="📂 导入已装环境", width=116, height=30,
                                            fg_color=CARD2, hover_color="#343a46", border_width=1, border_color=BORDER,
                                            text_color=TXT, corner_radius=6, font=ui_font(FONT_BODY),
                                            command=self.cmd_import_at_env)
        self.btn_at_import2.pack(side="left", padx=(4, 4))

        # AMD 兼容模式（实验性）：仅 AMD 显卡显示
        self.amd_bar = ctk.CTkFrame(top, fg_color="transparent")
        if self._gpu_info.get("vendor") == "amd":
            self.amd_bar.pack(fill="x", pady=(8, 0))
            amd_row1 = ctk.CTkFrame(self.amd_bar, fg_color="transparent"); amd_row1.pack(fill="x")
            self.amd_sw = ctk.CTkSwitch(amd_row1, text="AMD 兼容模式（实验性）", variable=self.amd_var,
                                        command=self._on_amd_toggle, font=ui_font(FONT_HINT), text_color=SUB,
                                        progress_color=ACC, fg_color="#3a4150")
            self.amd_sw.pack(side="left")
            self.btn_amd_env = ctk.CTkButton(amd_row1, text="环境检查 / 安装引导", width=140, height=26,
                                             fg_color=CARD2, hover_color="#343a46", border_width=1,
                                             border_color=BORDER, text_color=TXT, corner_radius=6,
                                             font=ui_font(FONT_HINT), command=self.cmd_amd_env)
            self.btn_amd_env.pack(side="left", padx=(10, 0))
            ctk.CTkLabel(amd_row1, textvariable=self.amd_env_var, font=ui_font(FONT_HINT),
                         text_color=HINT, anchor="w").pack(side="left", padx=(10, 0))
            amd_row2 = ctk.CTkFrame(self.amd_bar, fg_color="transparent"); amd_row2.pack(fill="x", pady=(6, 0))
            ctk.CTkLabel(amd_row2, text="训练环境(venv，留空=默认 kohya 环境)", font=ui_font(FONT_HINT),
                         text_color=HINT).pack(side="left")
            self.train_env_entry = ctk.CTkEntry(amd_row2, width=280, height=26, textvariable=self.train_env_var,
                                                fg_color=CARD2, border_color=BORDER, text_color=TXT,
                                                placeholder_text="例如 C:\\kohya_amd_env",
                                                font=ui_font(FONT_HINT))
            self.train_env_entry.pack(side="left", padx=(8, 6))
            self.btn_pick_train_env = ctk.CTkButton(amd_row2, text="选择训练环境…", width=108, height=26,
                                                    fg_color=CARD2, hover_color="#343a46", border_width=1,
                                                    border_color=BORDER, text_color=TXT, corner_radius=6,
                                                    font=ui_font(FONT_HINT), command=self.cmd_pick_train_env)
            self.btn_pick_train_env.pack(side="left")
        self.preset_summary = ctk.CTkLabel(top, text="", font=ui_font(FONT_HINT), text_color=SUB, anchor="w")
        self.preset_summary.pack(fill="x", pady=(8, 0))

        # 可滚动主区
        self.scroll = ctk.CTkScrollableFrame(self.work_frame, fg_color=BG, corner_radius=0)
        self.scroll.pack(fill="both", expand=True, padx=26, pady=(14, 0))
        try:
            self.scroll._parent_canvas.configure(yscrollincrement=2)  # 降低滚轮单格滚动距离，更平滑
        except Exception:
            pass
        # 主卡片延迟构建：启动只显示主页，打开项目时才构建训练配置页（加快首屏，减少启动卡顿）
        self._main_cards_built = False

        # 底部独立日志面板
        logbar = ctk.CTkFrame(right, fg_color="#16181e", corner_radius=0)
        self.logbar_ref = logbar
        logbar.pack(fill="x", side="bottom", pady=(8, 0))
        log_hdr = ctk.CTkFrame(logbar, fg_color="transparent")
        log_hdr.pack(fill="x", padx=26, pady=(8, 2))
        ctk.CTkLabel(log_hdr, text="运行日志", font=ui_font(FONT_TITLE), text_color=TITLE_C).pack(side="left")
        ctk.CTkButton(log_hdr, text="📤 导出日志", width=120, height=28, fg_color="transparent",
                      hover_color="#252a36", border_width=1, border_color=BORDER, text_color=SUB,
                      corner_radius=6, font=ui_font(FONT_HINT), command=self.cmd_export_log).pack(side="right")
        self.log = ctk.CTkTextbox(logbar, height=150, fg_color="#14161c", text_color="#b6bcc9", corner_radius=6,
                                  border_width=1, border_color=BORDER, font=ui_font(FONT_LOG))
        self.log.pack(fill="x", padx=26, pady=(0, 14))
        for tag, col in [("ok", LOG_OK), ("warn", LOG_WARN), ("err", LOG_ERR), ("info", LOG_INFO), ("train", LOG_TRAIN)]:
            self.log.tag_config(tag, foreground=col)
        # 训练监控面板（平时隐藏，训练时 pack 在日志上方）
        self._build_monitor_bar(right)
        self._log("欢迎使用 Kohya-LoRA 一键训练工具")
        self._log("按左侧新手引导 ①②③④ 顺序操作，最后点下方「一键开始训练」")
        self._attach_tooltips()
    # ==================== 项目化管理：主页 / 新建 / 打开 / 自动保存 ====================

    def _build_home(self):
        """主页：项目卡片列表 + 新建按钮。"""
        for w in getattr(self, "_home_widgets", []):
            try:
                w.destroy()
            except Exception:
                pass
        self._home_widgets = []
        f = self.home_frame
        head = ctk.CTkFrame(f, fg_color="transparent")
        head.pack(fill="x", padx=26, pady=(24, 6))
        self._home_widgets.append(head)
        ctk.CTkLabel(head, text="🏠 我的项目", font=ui_font(FONT_TITLE), text_color=TITLE_C).pack(side="left")
        self.btn_new_project = ctk.CTkButton(head, text="➕ 新建项目", width=110, height=32,
                                             fg_color=ACC, hover_color=ACC_H, corner_radius=6,
                                             font=ui_font(FONT_BODY), command=self.cmd_new_project)
        self.btn_new_project.pack(side="right")
        self._home_widgets.append(self.btn_new_project)
        self.btn_data_dir = ctk.CTkButton(head, text="💾 数据目录", width=104, height=32,
                                            fg_color="transparent", hover_color="#252a36",
                                            border_width=1, border_color=BORDER, text_color=SUB,
                                            corner_radius=6, font=ui_font(FONT_BODY), command=self.cmd_data_dir)
        self.btn_data_dir.pack(side="right", padx=(0, 6))
        self._home_widgets.append(self.btn_data_dir)
        self.btn_check_update = ctk.CTkButton(head, text="🔄 检查更新", width=104, height=32,
                                              fg_color="transparent", hover_color="#252a36",
                                              border_width=1, border_color=BORDER, text_color=SUB,
                                              corner_radius=6, font=ui_font(FONT_BODY), command=self.cmd_check_update)
        self.btn_check_update.pack(side="right", padx=(0, 6))
        self._home_widgets.append(self.btn_check_update)
        # 🧰 小工具：训练前通用操作（查看显存 / 清理显存 / 清理内存 / 清理缓存 / 一键清理）
        self.btn_tools = ctk.CTkButton(head, text="🧰 小工具", width=104, height=32,
                                       fg_color="transparent", hover_color="#252a36",
                                       border_width=1, border_color=BORDER, text_color=SUB,
                                       corner_radius=6, font=ui_font(FONT_BODY), command=self.cmd_open_tools)
        self.btn_tools.pack(side="right", padx=(0, 6))
        self._home_widgets.append(self.btn_tools)
        _hint = ctk.CTkLabel(f, text="每个项目保存一套完整的训练配置（模式 / 底模 / 数据集 / 触发词 / 全部参数），下次直接打开继续用。",
                             font=ui_font(FONT_HINT), text_color=HINT)
        _hint.pack(anchor="w", padx=26, pady=(0, 10))
        self._home_widgets.append(_hint)
        # 项目卡片滚动区
        card_area = ctk.CTkScrollableFrame(f, fg_color=BG, corner_radius=0)
        card_area.pack(fill="both", expand=True, padx=26, pady=(0, 10))
        self._home_widgets.append(card_area)
        projects = core.list_projects()
        if not projects:
            empty = ctk.CTkFrame(card_area, fg_color=CARD2, corner_radius=8)
            empty.pack(fill="x", pady=8)
            self._home_widgets.append(empty)
            ctk.CTkLabel(empty, text="还没有项目。\n点右上角「➕ 新建项目」开始，软件会自动保存你的每一次配置。",
                         font=ui_font(FONT_BODY), text_color=SUB, justify="center").pack(pady=28)
        for info in projects:
            self._build_project_card(card_area, info)

    def _build_project_card(self, parent, info):
        name = info.get("name", "")
        mode_l = core.MODE_LABELS.get(info.get("mode", "style"), "画风")
        bt_l = core.BASE_TYPE_LABELS.get(info.get("base_type", "sd15"), info.get("base_type", "sd15"))
        card = ctk.CTkFrame(parent, fg_color=CARD2, corner_radius=8)
        card.pack(fill="x", pady=5)
        self._home_widgets.append(card)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=10)
        # 左侧信息
        info_col = ctk.CTkFrame(row, fg_color="transparent")
        info_col.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(info_col, text=name, font=ui_font(FONT_BODY), text_color=TXT, anchor="w").pack(anchor="w")
        sub = f"{mode_l} · {bt_l}"
        raw = info.get("raw_dir") or ""
        if raw:
            sub += f"  |  图集: {raw}"
        upd = info.get("updated") or ""
        if upd:
            sub += f"  |  更新: {upd}"
        ctk.CTkLabel(info_col, text=sub, font=ui_font(FONT_HINT), text_color=HINT, anchor="w").pack(anchor="w", pady=(2, 0))
        # 右侧按钮
        btn_col = ctk.CTkFrame(row, fg_color="transparent")
        btn_col.pack(side="right")
        ctk.CTkButton(btn_col, text="打开", width=62, height=28, fg_color=ACC, hover_color=ACC_H,
                      corner_radius=6, font=ui_font(FONT_HINT),
                      command=lambda n=name: self.cmd_open_project(n)).pack(side="left", padx=3)
        ctk.CTkButton(btn_col, text="重命名", width=68, height=28, fg_color=CARD2, hover_color="#343a46",
                      border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                      font=ui_font(FONT_HINT),
                      command=lambda n=name: self.cmd_rename_project(n)).pack(side="left", padx=3)
        ctk.CTkButton(btn_col, text="删除", width=62, height=28, fg_color="#4a3535", hover_color="#5a4141",
                      text_color="#e0b0b0", corner_radius=6, font=ui_font(FONT_HINT),
                      command=lambda n=name: self.cmd_delete_project(n)).pack(side="left", padx=3)

    def _show_home(self):
        """显示主页（项目列表），隐藏工作区。"""
        self.current_project = None
        self.work_frame.pack_forget()
        self.home_frame.pack(fill="both", expand=True)
        self._build_home()
        # 徽章在 work_frame（主页不可见），主页只渲染引导占位（不显示步骤）
        try:
            self._render_guide()
        except Exception:
            pass

    def _ensure_main_cards(self):
        """首次打开工作区时才构建主卡片（延迟加载，避免启动卡顿）。"""
        if getattr(self, "_main_cards_built", False):
            return
        try:
            self._build_main_cards()
            self._attach_main_tooltips()
        finally:
            self._main_cards_built = True
        # 卡片构建后才刷新模式相关行的显隐（人物强绑定等按模式显示）
        try:
            self._update_mode_ui()
        except Exception:
            pass

    def _show_work(self):
        """显示工作区（训练配置页），隐藏主页。"""
        self.home_frame.pack_forget()
        self._ensure_main_cards()
        self.work_frame.pack(fill="both", expand=True)
        try:
            self._render_guide()
        except Exception:
            pass

    def _refresh_guide_only(self):
        """只刷新左侧引导状态（用缓存的环境结果），不重复跑子进程检测。"""
        self._refresh_guide()

    def _current_steps(self):
        """当前模式的新手引导步骤（数据驱动，来自 core.GUIDE_STEPS）。"""
        return list(core.GUIDE_STEPS.get(self.mode, []))

    def _guide_done(self, check):
        """按 check 类型判定引导步骤是否完成（环境/引擎/模型=全局；底模/数据=当前项目）。"""
        try:
            if check == "env":
                sts = core.system_status()
                return bool(sts.get("git") and sts.get("python"))
            if check == "kohya":
                return bool(core.system_status().get("kohya_ok"))
            if check == "musubi":
                return bool(core.system_status().get("musubi_ok"))
            if check == "at":
                return bool(core.system_status().get("at_ok"))
            if check == "fizgig":
                return bool(core.system_status().get("fizgig_ok"))
            if check == "krea2_models":
                return not core.krea2_missing_models()
            if check == "krea2_at_models":
                return not core.krea2_at_missing_models()
            if check == "flux2_models":
                return not core.flux2_missing_models()
            if check == "h3_models":
                return not core.h3_missing_models()
            if check == "at_model":
                return core.at_image_model_ready(self.mode)
            if check == "base":
                return bool(self.base_model_var.get())
            if check == "raw":
                return bool(self.raw_dir_var.get())
        except Exception:
            pass
        return False

    def _stop_guide_highlight(self):
        self._guide_hl_step = None
        if self._guide_hl_after:
            try:
                self.root.after_cancel(self._guide_hl_after)
            except Exception:
                pass
            self._guide_hl_after = None
        for btn in list(self._guide_btns.values()):
            try:
                btn.configure(fg_color=CARD2, hover_color="#343a46", text_color=TXT)
            except Exception:
                pass

    def _highlight_guide(self, step_id):
        """第一个未完成步骤的按钮做呼吸闪烁，引导小白点它。"""
        self._stop_guide_highlight()
        if not step_id or step_id not in self._guide_btns:
            return
        btn = self._guide_btns[step_id]
        self._guide_hl_step = step_id
        self._guide_hl_toggle = False

        def _pulse():
            if getattr(self, "_guide_hl_step", None) != step_id:
                return
            self._guide_hl_toggle = not self._guide_hl_toggle
            try:
                btn.configure(fg_color=(ACC if self._guide_hl_toggle else CARD2),
                              text_color=("#ffffff" if self._guide_hl_toggle else TXT))
            except Exception:
                pass
            self._guide_hl_after = self.root.after(500, _pulse)

        _pulse()

    def _render_guide(self):
        """按当前模式重建左侧新手引导（主页=占位；工作区=该模式专属步骤）。"""
        for w in self._guide_row_widgets:
            try:
                w.destroy()
            except Exception:
                pass
        self._guide_row_widgets = []
        self._guide_dots = {}
        self._guide_btns = {}
        self._guide_vars = {}
        self._stop_guide_highlight()
        try:
            self.guide_title.pack_forget()
            self.guide_host.pack_forget()
            self.guide_placeholder.pack_forget()
        except Exception:
            pass
        if self.current_project is None:
            self.guide_placeholder.configure(text="👆 请先打开/新建项目\\n然后选择训练模式\\n\\n引导会按模式自动生成")
            self.guide_placeholder.pack(anchor="w", pady=(6, 2))
            return
        self.guide_title.pack(anchor="w", pady=(0, 4))
        steps = self._current_steps()
        if not steps:
            self.guide_placeholder.configure(text="👆 请先选择训练模式\\n\\n引导会按模式自动生成")
            self.guide_placeholder.pack(anchor="w", pady=(6, 2))
            return
        self.guide_host.pack(fill="x", pady=3)
        for step in steps:
            row = ctk.CTkFrame(self.guide_host, fg_color="transparent")
            row.pack(fill="x", pady=3)
            dot = ctk.CTkFrame(row, width=10, height=10, corner_radius=5, fg_color="#4a3636")
            dot.pack(side="left", padx=(2, 8), pady=9)
            ctk.CTkLabel(row, text=step["label"], font=ui_font(FONT_BODY), text_color=TXT,
                         width=88, anchor="w").pack(side="left")
            var = tk.StringVar(value="·")
            ctk.CTkLabel(row, textvariable=var, font=ui_font(FONT_HINT), text_color=HINT,
                         width=18, anchor="w").pack(side="left")
            btn = ctk.CTkButton(row, text=step["btn"], width=68, height=32, fg_color=CARD2,
                                hover_color="#343a46", border_width=1, border_color=BORDER,
                                text_color=TXT, corner_radius=6, font=ui_font(FONT_HINT),
                                command=getattr(self, step["act"], lambda: None))
            btn.pack(side="right")
            self._guide_dots[step["id"]] = dot
            self._guide_vars[step["id"]] = var
            self._guide_btns[step["id"]] = btn
            self._guide_row_widgets.append(row)
            if step.get("tip"):
                self._tip(btn, step["tip"])
        self._refresh_guide()

    def _refresh_guide(self):
        """刷新引导步骤状态：✓/·、圆点颜色、高亮第一个未完成步骤、一键按钮状态。

        模型自动下载类步骤（at_model）只显示状态、不阻塞一键训练、不高亮。
        """
        first_pending = None
        for step in self._current_steps():
            done = self._guide_done(step["check"])
            var = self._guide_vars.get(step["id"])
            if var is not None:
                var.set("✓" if done else "·")
            dot = self._guide_dots.get(step["id"])
            if dot is not None:
                try:
                    dot.configure(fg_color=("#5c7c66" if done else "#6e4545"))
                except Exception:
                    pass
            if step["check"] == "at_model":
                continue  # 模型自动下载，不作为待办步骤
            if not done and first_pending is None:
                first_pending = step["id"]
        self._highlight_guide(first_pending)
        self._refresh_one_click_state()

    def _bind_autosave_traces(self):
        """给所有输入控件绑定变更回调，自动保存项目。"""
        try:
            def _on_any(*_a):
                self._schedule_autosave()
            for v in (self.trigger_var, self.reg_var, self.raw_dir_var,
                      self.global_pos_var, self.global_neg_var,
                      self.base_model_var, self.train_env_var):
                try:
                    v.trace_add("write", _on_any)
                except Exception:
                    pass
            for k, v in self.param_vars.items():
                try:
                    v.trace_add("write", _on_any)
                except Exception:
                    pass
            try:
                self.unet_only_var.trace_add("write", _on_any)
            except Exception:
                pass
            try:
                self.strong_bind_var.trace_add("write", _on_any)
            except Exception:
                pass
            try:
                self.amd_var.trace_add("write", _on_any)
            except Exception:
                pass
        except Exception:
            pass

    def cmd_back_home(self):
        if self.busy:
            messagebox.showinfo(core.APP_NAME, "任务正在运行，请先等待完成或停止。")
            return
        if self.current_project and messagebox.askyesno(core.APP_NAME,
                f"返回项目列表？\n当前项目「{self.current_project}」的配置已自动保存。"):
            self._autosave()
            self._show_home()
        elif not self.current_project:
            self._show_home()

    # ---------- 新建 / 打开 / 重命名 / 删除 ----------
    def _reset_project_ui(self):
        """新建项目前清空上一次项目遗留的界面状态，避免新项目继承旧配置/旧图集路径。

        只清空"项目专属"字段（图集/底模/触发词/正则/全局提示词/参数覆盖标记）；
        模式/架构/预设随后由所选模板重新填充。
        """
        self._manual_override.clear()
        self.raw_dir_var.set("")
        self.base_model_var.set("")
        self.trigger_var.set("")
        self.reg_var.set("")
        self.global_pos_var.set("")
        self.global_neg_var.set("")
        self.unet_only_var.set(False)
        self.strong_bind_var.set(True)
        try:
            self.train_env_var.set("")
        except Exception:
            pass
        try:
            self.base_combo.set(core.BASE_TYPE_LABELS.get(self.base_type, list(core.BASE_TYPE_LABELS.values())[0]))
        except Exception:
            pass
        try:
            self._apply_presets()
            self._update_mode_ui()
            self._refresh_preset_summary()
            self._refresh_one_click_state()
        except Exception:
            pass

    def cmd_new_project(self):
        """新建项目：选择模板 + 填项目名。"""
        if self.busy:
            messagebox.showinfo(core.APP_NAME, "任务正在运行，请先等待完成或停止。")
            return
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("新建项目")
        dlg.geometry("460x330")
        dlg.transient(self.root)
        dlg.grab_set()
        body = ctk.CTkFrame(dlg, fg_color=BG)
        body.pack(fill="both", expand=True, padx=18, pady=16)
        ctk.CTkLabel(body, text="选择预设模板", font=ui_font(FONT_BODY), text_color=TXT).pack(anchor="w")
        tpl_var = tk.StringVar(value="动漫画风")
        tpl_menu = ctk.CTkOptionMenu(body, values=list(core.PROJECT_TEMPLATES.keys()),
                                     variable=tpl_var, width=220, height=30,
                                     fg_color=CARD2, button_color=CARD2, button_hover_color="#3a4150",
                                     text_color=TXT, font=ui_font(FONT_BODY),
                                     dropdown_font=ui_font(FONT_BODY), dropdown_fg_color=CARD2,
                                     dropdown_hover_color="#3a4150")
        tpl_menu.pack(anchor="w", pady=(4, 2))
        tpl_note = ctk.CTkLabel(body, text="", font=ui_font(FONT_HINT), text_color=HINT, wraplength=420, justify="left")
        tpl_note.pack(anchor="w", pady=(0, 8))
        def _tpl_note(_e=None):
            tpl_note.configure(text=core.PROJECT_TEMPLATES.get(tpl_var.get(), {}).get("note", ""))
        tpl_menu.configure(command=lambda v: _tpl_note())
        _tpl_note()
        ctk.CTkLabel(body, text="项目名称", font=ui_font(FONT_BODY), text_color=TXT).pack(anchor="w")
        name_var = tk.StringVar(value=core.default_project_name())
        name_entry = ctk.CTkEntry(body, textvariable=name_var, width=300, height=30,
                                  fg_color=CARD2, border_color=BORDER, text_color=TXT, font=ui_font(FONT_BODY))
        name_entry.pack(anchor="w", pady=(4, 2))
        ctk.CTkLabel(body, text="项目名建议用英文或简短中文，避免特殊字符。", font=ui_font(FONT_HINT),
                     text_color=HINT).pack(anchor="w", pady=(0, 12))
        def _do_create():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning(core.APP_NAME, "请填写项目名称。")
                return
            if core.load_project(name):
                if not messagebox.askyesno(core.APP_NAME, f"已存在同名项目「{name}」，覆盖它吗？"):
                    return
            tpl = core.PROJECT_TEMPLATES.get(tpl_var.get(), {})
            # 关键：先清空界面残留的旧项目状态，再套用模板，
            # 否则新项目会继承上一个项目（甚至已删除项目）的图集/底模/触发词/参数
            self._reset_project_ui()
            # 应用模板：模式 / 底模类型 / 参数
            if tpl.get("mode"):
                self.mode = tpl["mode"]
                try:
                    self.mode_combo.set(core.MODE_LABELS[self.mode])
                except Exception:
                    pass
            if tpl.get("base_type"):
                self.base_type = tpl["base_type"]
                try:
                    self.base_combo.set(core.BASE_TYPE_LABELS[self.base_type])
                except Exception:
                    pass
            self._apply_presets()
            self._update_mode_ui()
            for k, v in (tpl.get("params") or {}).items():
                self.param_vars.setdefault(k, tk.StringVar()).set(v)
            self._refresh_preset_summary()
            # 导入配置：完全覆盖模板/预设（模式/底模/参数）
            if getattr(self, "_pending_import_config", None):
                self._apply_imported_config(self._pending_import_config)
                self._pending_import_config = None
                self._log("[配置] 已应用导入的配置（新建项目参数已按导入覆盖）")
            data = self._collect_project_data(template=tpl_var.get())
            data["created"] = None  # save 时会自动补
            ok = core.save_project(name, data)
            if not ok:
                messagebox.showerror(core.APP_NAME, "保存项目失败，请检查磁盘/权限。")
                return
            self._log(f"[项目] 已新建项目「{name}」（模板：{tpl_var.get()}）")
            self.current_project = name
            self.proj_title.configure(text="项目：" + name)
            dlg.destroy()
            self._show_work()
            self._refresh_status_async()
        import_note = ctk.CTkLabel(body, text="（可选）导入上次/他人的配置，自动套用模式与参数",
                                   font=ui_font(FONT_HINT), text_color=HINT, wraplength=420, justify="left")
        import_note.pack(anchor="w", pady=(2, 2))
        def _pick_import():
            from tkinter import filedialog
            fp = filedialog.askopenfilename(title="选择要导入的配置", filetypes=[("配置 JSON", "*.json")])
            if not fp:
                return
            try:
                import io as _io
                _cfg, _sum = core.parse_config_json(_io.open(fp, encoding="utf-8").read())
            except Exception as _e:
                messagebox.showerror(core.APP_NAME, f"配置导入失败：{_e}")
                return
            self._pending_import_config = _cfg
            try:
                import_note.configure(text=f"✅ 已导入配置（应用 {_sum['applied']} 项 / 忽略 {_sum['ignored']} 项）：{os.path.basename(fp)}")
            except Exception:
                pass
        ctk.CTkButton(body, text="📥 导入配置", width=110, height=34, fg_color=CARD2, hover_color="#3a4150",
                      border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                      font=ui_font(FONT_HINT), command=_pick_import).pack(side="left", pady=(8, 0))
        self._refresh_status_async()
        ctk.CTkButton(body, text="创建并打开", width=120, height=34, fg_color=ACC, hover_color=ACC_H,
                      corner_radius=6, font=ui_font(FONT_BODY), command=_do_create).pack(side="right", pady=(8, 0))
        ctk.CTkButton(body, text="取消", width=80, height=34, fg_color=CARD2, hover_color="#343a46",
                      border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                      font=ui_font(FONT_BODY), command=dlg.destroy).pack(side="right", padx=(0, 10), pady=(8, 0))
        name_entry.focus_set()

    def cmd_open_project(self, name):
        """打开项目：恢复模式/底模/数据集/参数。"""
        if self.busy:
            messagebox.showinfo(core.APP_NAME, "任务正在运行，请先等待完成或停止。")
            return
        data = core.load_project(name)
        if not data:
            messagebox.showwarning(core.APP_NAME, f"项目「{name}」不存在或已损坏。")
            self._build_home()
            return
        try:
            self._apply_project_data(data)
        except Exception as e:
            # 手动改过 json（字段类型/结构异常）时不能静默无反应：提示并按默认配置打开。
            self._log(f"[项目] 配置恢复遇到异常（可能是手动修改 json 导致），已按默认配置打开：{e}")
            traceback.print_exc()
            try:
                self._apply_project_data({})
            except Exception:
                pass
        self.current_project = name
        self.proj_title.configure(text="项目：" + name)
        self._show_work()
        self._refresh_status_async()
        self._log(f"[项目] 已打开项目「{name}」，全部配置已恢复。")
        # 旧版共享数据集一次性导入（每个项目从此独立，不混用）
        try:
            self._maybe_migrate_legacy_dataset(name)
        except Exception as _e:
            self._log(f"[数据集] 旧数据集导入失败（忽略）: {_e}")

    def cmd_rename_project(self, old):
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("重命名项目")
        dlg.geometry("380x160")
        dlg.transient(self.root)
        dlg.grab_set()
        body = ctk.CTkFrame(dlg, fg_color=BG)
        body.pack(fill="both", expand=True, padx=18, pady=16)
        ctk.CTkLabel(body, text="新项目名：", font=ui_font(FONT_BODY), text_color=TXT).pack(anchor="w")
        v = tk.StringVar(value=old)
        e = ctk.CTkEntry(body, textvariable=v, width=300, height=30, fg_color=CARD2,
                         border_color=BORDER, text_color=TXT, font=ui_font(FONT_BODY))
        e.pack(anchor="w", pady=(4, 12))
        def _do():
            new = v.get().strip()
            if not new:
                return
            if new == old:
                dlg.destroy()
                return
            if core.load_project(new):
                messagebox.showwarning(core.APP_NAME, f"已存在同名项目「{new}」。")
                return
            data = core.load_project(old)
            if not data:
                dlg.destroy()
                return
            core.save_project(new, data)
            core.delete_project(old)
            # 项目数据集目录跟着改名，避免数据"丢失"
            try:
                _old_ds = os.path.join(core.data_dir(), "dataset", core._sanitize_dirname(old))
                _new_ds = os.path.join(core.data_dir(), "dataset", core._sanitize_dirname(new))
                if os.path.isdir(_old_ds) and not os.path.isdir(_new_ds):
                    os.rename(_old_ds, _new_ds)
                    self._log(f"[数据集] 项目数据集目录已同步改名：{_new_ds}")
            except Exception as _e:
                self._log(f"[数据集] 数据集目录改名失败（忽略，可在新项目里重新预处理）: {_e}")
            if self.current_project == old:
                self.current_project = new
                self.proj_title.configure(text="项目：" + new)
                self._autosave()
            self._log(f"[项目] 已重命名「{old}」→「{new}」")
            dlg.destroy()
            if not self.current_project:
                self._build_home()
        ctk.CTkButton(body, text="确定", width=90, height=32, fg_color=ACC, hover_color=ACC_H,
                      corner_radius=6, font=ui_font(FONT_BODY), command=_do).pack(side="right")
        ctk.CTkButton(body, text="取消", width=80, height=32, fg_color=CARD2, hover_color="#343a46",
                      border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                      font=ui_font(FONT_BODY), command=dlg.destroy).pack(side="right", padx=(0, 10))
        e.focus_set()

    def cmd_delete_project(self, name):
        if not messagebox.askyesno(core.APP_NAME,
                f"确定删除项目「{name}」吗？\n删除后不可恢复（训练产物仍在 output 文件夹）。"):
            return
        core.delete_project(name)
        self._log(f"[项目] 已删除项目「{name}」")
        if self.current_project == name:
            self._show_home()
        else:
            self._build_home()

    # ---------- 数据收集 / 应用 / 自动保存 ----------
    def _collect_project_data(self, template="自定义"):
        """收集当前界面全部状态，供保存到项目 json。"""
        params = self._collect_params()
        return {
            "name": self.current_project or "",
            "template": template,
            "mode": params.get("mode", self.mode),
            "base_type": params.get("base_type", self.base_type),
            "at_sub_mode": params.get("at_sub_mode") or "character",
            "fast_tier": params.get("fast_tier") or "auto",
            "base_model": params.get("base_model") or "",
            "raw_dir": params.get("raw_dir") or "",
            "trigger": params.get("trigger") or "",
            "reg_dir": params.get("reg_dir") or "",
            "global_pos": params.get("global_pos") or "",
            "global_neg": params.get("global_neg") or "",
            "unet_only": params.get("train_text_encoder") is False,
            "train_env": params.get("train_env") or "",
            "params": {
                "rank": params.get("rank"),
                "alpha": params.get("alpha"),
                "unet_lr": params.get("unet_lr"),
                "te_lr": params.get("te_lr"),
                "repeats": params.get("repeats"),
                "max_epochs": params.get("max_epochs"),
                "save_every": params.get("save_every"),
                "optimizer": params.get("optimizer") or "auto",
                "strong_bind": bool(params.get("strong_bind", True)),
                "crop_ratio": params.get("crop_ratio") or "",
                "sample_prompt": params.get("sample_prompt") or "",
            },
        }

    def _apply_project_data(self, data):
        """把项目 json 恢复回界面。"""
        self._loading_project = True
        self._manual_override.clear()
        try:
            m = data.get("mode", "character")
            if not isinstance(m, str):
                m = "character"
            if m in core.MODE_LABELS:
                self.mode = m
                try:
                    self.mode_combo.set(core.MODE_LABELS[m])
                except Exception:
                    pass
            bt = data.get("base_type", "sdxl")
            if not isinstance(bt, str):
                bt = "sdxl"
            if bt in core.BASE_TYPE_LABELS:
                self.base_type = bt
                try:
                    self.base_combo.set(core.BASE_TYPE_LABELS[bt])
                except Exception:
                    pass
            try:
                _sub = data.get("at_sub_mode") or "character"
                self.at_sub_var.set(core.AT_SUB_LABELS.get(_sub, core.AT_SUB_LABELS["character"]))
            except Exception:
                pass
            try:
                _ft = data.get("fast_tier") or "auto"
                self.fast_tier_var.set(core.FAST_TIER_LABELS.get(_ft, core.FAST_TIER_LABELS["auto"]))
            except Exception:
                pass
            self.trigger_var.set(data.get("trigger") or "")
            self.reg_var.set(data.get("reg_dir") or "")
            self.raw_dir_var.set(data.get("raw_dir") or "")
            self.global_pos_var.set(data.get("global_pos") or "")
            self.global_neg_var.set(data.get("global_neg") or "")
            bm = data.get("base_model") or ""
            if not isinstance(bm, str):
                bm = ""
            if bm:
                self.base_model_var.set(bm)
                bt2 = core.detect_base_type(bm)
                if bt2 in core.BASE_TYPE_KEYS:
                    self._set_base_type(bt2)
                    try:
                        self.base_combo.set(core.BASE_TYPE_LABELS[bt2])
                    except Exception:
                        pass
            self.unet_only_var.set(bool(data.get("unet_only", False)))
            te = data.get("train_env") or ""
            if te:
                self.train_env_var.set(te)
            p = data.get("params") or {}
            if not isinstance(p, dict):
                p = {}
            _opt_gui = {v: k for k, v in _OPT_GUI_MAP.items()}.get((p.get("optimizer") or "auto"), "自动")
            try:
                self.optimizer_var.set(_opt_gui)
            except Exception:
                pass
            _quant_gui = {v: k for k, v in _QUANT_GUI_MAP.items()}.get((p.get("quant_mode") or "auto"), "自动")
            try:
                self.quant_var.set(_quant_gui)
            except Exception:
                pass
            _swap_gui = str(p.get("blocks_to_swap") or "自动")
            try:
                self.swap_var.set(_swap_gui if str(_swap_gui).isdigit() else "自动")
            except Exception:
                pass
            try:
                self.compile_var.set(bool(p.get("compile")))
            except Exception:
                pass
            for k, v in p.items():
                if k in ("optimizer", "quant_mode", "blocks_to_swap", "compile"):
                    continue
                if k == "strong_bind":
                    try:
                        self.strong_bind_var.set(bool(v))
                    except Exception:
                        pass
                    continue
                if k == "crop_ratio":
                    try:
                        self.crop_ratio_var.set(_crop_ratio_label(v))
                    except Exception:
                        pass
                    continue
                if k == "sample_prompt":
                    try:
                        self.sample_prompt_var.set(str(v or ""))
                    except Exception:
                        pass
                    continue
                if v is not None:
                    self.param_vars.setdefault(k, tk.StringVar()).set(str(v))
                    self._manual_override.add(k)   # 项目参数优先，不被预设覆盖
            self._apply_presets()   # 填充缺失参数（不覆盖项目已有值）
            self._update_mode_ui()
            self._refresh_preset_summary()
            self._refresh_one_click_state()
        finally:
            self._loading_project = False

    def _schedule_autosave(self):
        """防抖自动保存：输入停止 800ms 后写盘。"""
        if self.current_project is None or getattr(self, "_loading_project", False):
            return
        if self._autosave_after is not None:
            try:
                self.root.after_cancel(self._autosave_after)
            except Exception:
                pass
        self._autosave_after = self.root.after(800, self._autosave)

    def _autosave(self):
        self._autosave_after = None
        if self.current_project is None or self._saving:
            return
        self._saving = True
        try:
            data = self._collect_project_data()
            data["created"] = None
            core.save_project(self.current_project, data)
        except Exception as e:
            self._log(f"[项目] 自动保存失败：{e}")
        finally:
            self._saving = False

    # ============ 主区卡片（可滚动） ============
    def _build_main_cards(self):
        for w in self._main_widgets:
            try:
                w.destroy()
            except Exception:
                pass
        self._main_widgets = []
        s = self.scroll

        # 卡片1：数据准备
        c1, card1 = create_soft_shadow_card(s); c1.pack(fill="x", pady=(2, 10))
        self._main_widgets += [c1, card1]
        self.card1_title = ctk.CTkLabel(card1, text="① 准备图片数据", font=ui_font(FONT_TITLE), text_color=TITLE_C)
        self.card1_title.pack(anchor="w", padx=22, pady=(14, 8))
        r1 = ctk.CTkFrame(card1, fg_color="transparent"); r1.pack(fill="x", padx=22, pady=(0, 4))
        ctk.CTkLabel(r1, text="原始图片文件夹", font=ui_font(FONT_BODY), text_color=SUB).pack(side="left")
        self.raw_entry = ctk.CTkEntry(r1, width=400, height=30, textvariable=self.raw_dir_var,
                                      fg_color=CARD2, border_color=BORDER, text_color=TXT, font=ui_font(FONT_BODY))
        self.raw_entry.pack(side="left", padx=(12, 8))
        self.btn_pick_raw = ctk.CTkButton(r1, text="浏览…", width=76, height=30, fg_color=CARD2, hover_color="#343a46",
                                          border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                                          font=ui_font(FONT_BODY), command=self.cmd_pick_raw)
        self.btn_pick_raw.pack(side="left")
        self.card1_hint = ctk.CTkLabel(card1, text="人物模式建议 15~30 张同一人物；画风模式建议 20~60 张不同人物。图片越清晰越好",
                                        font=ui_font(FONT_HINT), text_color=HINT)
        self.card1_hint.pack(anchor="w", padx=22, pady=(2, 14))

        # 卡片2：触发词 + 正则（人物模式）
        c2, card2 = create_soft_shadow_card(s); c2.pack(fill="x", pady=(0, 10))
        self._main_widgets += [c2, card2]
        self.trig_card = card2
        self.trig_card_title = ctk.CTkLabel(card2, text="② 设置触发词（人物模式）", font=ui_font(FONT_TITLE), text_color=TITLE_C)
        self.trig_card_title.pack(anchor="w", padx=22, pady=(14, 8))
        # Qwen-Image / Z-Image 专属：画风/人物 训练类型切换（默认隐藏，仅这两个模式显示）
        self.at_sub_row = ctk.CTkFrame(card2, fg_color="transparent")
        ctk.CTkLabel(self.at_sub_row, text="训练类型", font=ui_font(FONT_BODY), text_color=SUB).pack(side="left")
        self.at_sub_combo = ctk.CTkComboBox(
            self.at_sub_row, values=[core.AT_SUB_LABELS["character"], core.AT_SUB_LABELS["style"], core.AT_SUB_LABELS["concept"]],
            width=230, height=30, variable=self.at_sub_var, state="readonly",
            fg_color=CARD2, border_color=BORDER, text_color=TXT,
            button_color="#3a4150", button_hover_color="#454d5e",
            dropdown_fg_color=CARD, dropdown_text_color=TXT, dropdown_hover_color="#2b303a",
            font=ui_font(FONT_BODY), command=lambda _e: self._on_at_sub_change())
        self.at_sub_combo.pack(side="left", padx=(12, 0))
        self.at_sub_hint = ctk.CTkLabel(self.at_sub_row, text="人物=保留全部标签；画风=过滤人物标签；概念=形态/种族（trigger 吸收原型）", font=ui_font(FONT_HINT), text_color=HINT)
        self.at_sub_hint.pack(side="left", padx=(12, 0))
        self.at_sub_row.pack_forget()
        # Z-Image 专属：⚡ 快跑档手动开关（8G 自动触发，可强制开/关；默认隐藏仅 zimage 显示）
        self.fast_tier_row = ctk.CTkFrame(card2, fg_color="transparent")
        ctk.CTkLabel(self.fast_tier_row, text="⚡ 快跑档", font=ui_font(FONT_BODY), text_color=SUB).pack(side="left")
        self.fast_tier_var = tk.StringVar(value=core.FAST_TIER_LABELS["auto"])
        self.fast_tier_menu = ctk.CTkComboBox(
            self.fast_tier_row, values=list(core.FAST_TIER_LABELS.values()),
            width=150, height=30, variable=self.fast_tier_var, state="readonly",
            fg_color=CARD2, border_color=BORDER, text_color=TXT,
            button_color="#3a4150", button_hover_color="#454d5e",
            dropdown_fg_color=CARD, dropdown_text_color=TXT, dropdown_hover_color="#2b303a",
            font=ui_font(FONT_BODY), command=lambda _e: None)
        self.fast_tier_menu.pack(side="left", padx=(12, 0))
        self.fast_tier_hint = ctk.CTkLabel(self.fast_tier_row,
            text="自动=仅 ≤8G 显存生效；开=强制（分辨率 384/512 + 层交换 + 关采样）；关=完全按常规参数",
            font=ui_font(FONT_HINT), text_color=HINT)
        self.fast_tier_hint.pack(side="left", padx=(12, 0))
        self.fast_tier_row.pack_forget()
        r2 = ctk.CTkFrame(card2, fg_color="transparent"); r2.pack(fill="x", padx=22, pady=(0, 4))
        ctk.CTkLabel(r2, text="Trigger 触发词", font=ui_font(FONT_BODY), text_color=SUB).pack(side="left")
        self.trigger_entry = ctk.CTkEntry(r2, width=200, height=30, textvariable=self.trigger_var,
                                          fg_color=CARD2, border_color=BORDER, text_color=TXT,
                                          placeholder_text="Yanami Anna", font=ui_font(FONT_BODY))
        self.trigger_entry.pack(side="left", padx=(12, 18))
        ctk.CTkLabel(r2, text="正则数据集（可选）", font=ui_font(FONT_BODY), text_color=SUB).pack(side="left")
        self.reg_entry = ctk.CTkEntry(r2, width=240, height=30, textvariable=self.reg_var,
                                      fg_color=CARD2, border_color=BORDER, text_color=TXT, font=ui_font(FONT_BODY))
        self.reg_entry.pack(side="left", padx=(12, 8))
        self.btn_pick_reg = ctk.CTkButton(r2, text="选择文件夹…", width=96, height=30, fg_color=CARD2, hover_color="#343a46",
                                          border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                                          font=ui_font(FONT_BODY), command=self.cmd_pick_reg)
        self.btn_pick_reg.pack(side="left")
        # 人物强绑定（人物模式显示，默认勾选）
        self.strong_bind_row = ctk.CTkFrame(card2, fg_color="transparent")
        self.chk_strong_bind = ctk.CTkCheckBox(
            self.strong_bind_row, text="人物强绑定（自动把 trigger + 100% 一致特征词固定到标签开头）",
            variable=self.strong_bind_var, fg_color=ACC, hover_color=ACC_H,
            text_color=TXT, font=ui_font(FONT_BODY))
        self.chk_strong_bind.pack(side="left")
        self.strong_bind_row.pack_forget()
        # 训练中采样预览（所有模式显示）
        self.sample_preview_row = ctk.CTkFrame(card2, fg_color="transparent")
        self.chk_sample_preview = ctk.CTkCheckBox(
            self.sample_preview_row, text="训练中采样预览（每 100 步用当前 LoRA 出一张预览图，低显存自动关闭）",
            variable=self.sample_preview_var, fg_color=ACC, hover_color=ACC_H,
            text_color=TXT, font=ui_font(FONT_BODY))
        self.chk_sample_preview.pack(side="left")
        self.sample_preview_row.pack(fill="x", pady=(10, 0))
        # 采样预览提示词（所有模式显示）：留空=自动（trigger + portrait…）；填了用用户整句
        self.sample_prompt_row = ctk.CTkFrame(card2, fg_color="transparent")
        ctk.CTkLabel(self.sample_prompt_row, text="采样预览提示词", font=ui_font(FONT_BODY), text_color=SUB).pack(side="left")
        self.sample_prompt_entry = ctk.CTkEntry(self.sample_prompt_row, width=340, height=30,
                                                textvariable=self.sample_prompt_var, fg_color=CARD2, border_color=BORDER,
                                                text_color=TXT, placeholder_text="留空=自动（trigger + portrait, masterpiece, best quality）",
                                                font=ui_font(FONT_BODY))
        self.sample_prompt_entry.pack(side="left", padx=(12, 8))
        ctk.CTkLabel(self.sample_prompt_row, text="填了整句生效（是否带 trigger 自己定），不再被覆盖", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        self.sample_prompt_row.pack(fill="x", pady=(6, 0))
        # 预处理裁切比例（所有模式显示）：默认不裁切保比例；下拉可选 1:1/3:4/9:16 等，或直接输入自定义 宽:高（如 2:3）
        self.crop_ratio_row = ctk.CTkFrame(card2, fg_color="transparent")
        ctk.CTkLabel(self.crop_ratio_row, text="预处理裁切比例", font=ui_font(FONT_BODY), text_color=SUB).pack(side="left")
        self.crop_ratio_combo = ctk.CTkComboBox(
            self.crop_ratio_row, variable=self.crop_ratio_var,
            values=list(_CROP_RATIO_PRESETS.keys()), width=200, height=30,
            fg_color=CARD2, border_color=BORDER, button_color=CARD2, button_hover_color="#3a4150",
            text_color=TXT, font=ui_font(FONT_BODY), dropdown_font=ui_font(FONT_BODY),
            dropdown_fg_color=CARD2, dropdown_hover_color="#3a4150")
        self.crop_ratio_combo.pack(side="left", padx=(12, 8))
        ctk.CTkLabel(self.crop_ratio_row, text="默认不裁切（保比例，人脸不易被切）；可输入自定义如 2:3", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        self.crop_ratio_row.pack(fill="x", pady=(10, 0))
        # 画风描述词（画风模式专用，默认隐藏）
        self.style_caption_var = tk.StringVar()
        self.style_caption_row = ctk.CTkFrame(card2, fg_color="transparent")
        ctk.CTkLabel(self.style_caption_row, text="画风描述词（可选）", font=ui_font(FONT_BODY), text_color=SUB).pack(side="left")
        self.style_caption_entry = ctk.CTkEntry(self.style_caption_row, width=300, height=30, textvariable=self.style_caption_var,
                                                fg_color=CARD2, border_color=BORDER, text_color=TXT,
                                                placeholder_text="如 hand-drawn sketch / black and white line art", font=ui_font(FONT_BODY))
        self.style_caption_entry.pack(side="left", padx=(12, 8))
        ctk.CTkLabel(self.style_caption_row, text="留空=自动打标；填了用它（画风更准）", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        # 默认隐藏，画风模式显示
        self.trigger_hint_var = tk.StringVar()
        self.trigger_hint = ctk.CTkLabel(card2, textvariable=self.trigger_hint_var, font=ui_font(FONT_HINT), text_color=HINT)
        self.trigger_hint.pack(anchor="w", padx=22, pady=(2, 14))

        # 卡片3：高级参数（折叠）
        c3, card3 = create_soft_shadow_card(s); c3.pack(fill="x", pady=(0, 10))
        self._main_widgets += [c3, card3]
        h3 = ctk.CTkFrame(card3, fg_color="transparent"); h3.pack(fill="x", padx=22, pady=(14, 14))
        ctk.CTkLabel(h3, text="高级参数（老手可展开，参数已按模式/底模自动填好）", font=ui_font(FONT_BODY), text_color=SUB).pack(side="left")
        self.btn_toggle_adv = ctk.CTkButton(h3, text="展开 ▾", width=64, height=26, fg_color="transparent",
                                            hover_color="#343a46", border_width=1, border_color=BORDER,
                                            text_color=HINT, corner_radius=6, font=ui_font(FONT_HINT),
                                            command=self._toggle_adv)
        self.btn_toggle_adv.pack(side="right")
        self.adv_body = ctk.CTkFrame(card3, fg_color="transparent")
        self.adv_collapsed = True

        # 操作按钮
        btns = ctk.CTkFrame(s, fg_color="transparent"); btns.pack(fill="x", pady=(4, 14))
        self._main_widgets.append(btns)
        for t, w, cmd in [("数据预处理", 110, self.cmd_preprocess), ("标签编辑器", 112, self.cmd_label_editor),
                          ("一键训练", 96, self.cmd_train), ("打开输出文件夹", 112, self.cmd_open_output),
                          ("📤 导出配置", 96, self.cmd_export_config), ("使用说明", 90, self.cmd_readme)]:
            b = ctk.CTkButton(btns, text=t, width=w, height=38, fg_color=CARD2, hover_color="#343a46",
                              border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                              font=ui_font(FONT_BODY), command=cmd)
            b.pack(side="left", padx=5)
            self._main_btns[t] = b
        ctk.CTkLabel(s, text="💡 训练前可用「标签编辑器」检查/修正每张图的标签：WD14 自动打的标签偶尔不准，手动改好后 LoRA 学得更准。",
                     font=ui_font(FONT_HINT), text_color=HINT).pack(anchor="w", padx=22, pady=(2, 12))

    def _build_badges(self):
        for w in self._badge_widgets:
            try:
                w.destroy()
            except Exception:
                pass
        self._badge_widgets = []
        st = self.badge_frame
        sts = core.system_status()
        def _badge(text, bg, fg):
            f = ctk.CTkFrame(st, fg_color=bg, corner_radius=4, height=22)
            f.pack(side="left", padx=(0, 8))
            ctk.CTkLabel(f, text=text, text_color=fg, font=ui_font(FONT_BADGE)).pack(padx=10, pady=2)
            self._badge_widgets.append(f)
        _badge("● Git 就绪" if sts.get("git") else "● Git 未装", OK_BG if sts.get("git") else "#3a3333",
               OK_TX if sts.get("git") else "#c9a8a8")
        _badge("● Python 3.12" if sts.get("python") else "● Python 未装", OK_BG if sts.get("python") else "#3a3333",
               OK_TX if sts.get("python") else "#c9a8a8")
        _badge("● Kohya-SS 就绪" if sts.get("kohya_ok") else "● Kohya 未装", OK_BG if sts.get("kohya_ok") else "#3a3333",
               OK_TX if sts.get("kohya_ok") else "#c9a8a8")
        _badge("● 第四引擎(Fizgig) 就绪" if sts.get("fizgig_ok") else "● 第四引擎未装",
               OK_BG if sts.get("fizgig_ok") else "#3a3333",
               OK_TX if sts.get("fizgig_ok") else "#c9a8a8")
        _gpu = sts.get("gpu")
        _badge(f"● {_gpu}" if _gpu else "● 未检测到 N 卡", HW_BG, HW_TX)
        try:
            self._refresh_guide()
        except Exception:
            pass
        try:
            self._refresh_h3_status()
        except Exception:
            pass

    def _refresh_status(self):
        try:
            self._build_badges()
        except Exception:
            pass
        try:
            if self._gpu_info.get("vendor") == "amd":
                ok, bk, detail = core.amd_env_status(self._amd_vpy())
                self.amd_env_var.set(("✓ 环境就绪（%s）" % bk) if ok else "环境未就绪 · 点「环境检查」查看")
        except Exception:
            pass

    # ============ 环境 / 安装 ============
    def cmd_install_musubi(self):
        """安装第二训练引擎（Krea2 图像 LoRA + 视频 LoRA）。"""
        if self.busy:
            messagebox.showinfo(core.APP_NAME, "有任务正在运行，请先等待当前任务完成。")
            return
        if not messagebox.askyesno(core.APP_NAME,
                "安装第二训练引擎（Krea2 图像 LoRA + 视频 LoRA）？\n\n"
                "· 使用独立环境，完全不影响现有画风/人物训练\n"
                "· 需下载 PyTorch cu128（约 2.5GB，首次可能较慢）\n"
                "· Krea2 / 视频模型按需另行下载（国内镜像）\n\n是否开始安装？"):
            return
        self._start_worker(self._install_musubi_worker, "安装第二引擎")

    def _install_musubi_worker(self):
        try:
            core.install_musubi_engine(self._log)
            core.clear_status_cache()
            self.q.put(("STATUS",))
        except Exception as e:
            self._log(f"[ERROR] 第二引擎安装失败：{e}")
            traceback.print_exc()
        finally:
            self.q.put("__DONE__")

    def cmd_env(self):
        self._start_worker(self._env_worker, "环境准备（Git / Python）")

    def _env_worker(self):
        core.reset_stop()
        try:
            core.ensure_prereqs(self._log)
            self._log("[OK] Git / Python 环境就绪")
        except core.StopRequested:
            self._log("[停止] 环境准备已手动停止")
        except Exception as e:
            self._log(f"[ERROR] 环境准备失败：{e}")
            traceback.print_exc()
        finally:
            self.q.put("__DONE__")
            self.q.put(("STATUS",))

    def cmd_install(self):
        self._start_worker(self._install_worker, "安装 Kohya-SS 训练内核")

    def _install_worker(self):
        core.reset_stop()
        try:
            core.install_kohya(self._log)
            core.clear_status_cache()
            self._log("[OK] Kohya-SS 安装完成")
        except core.StopRequested:
            self._log("[停止] 安装已手动停止（已解压/已装的部分会保留，可重跑继续）")
        except Exception as e:
            self._log(f"[ERROR] 安装失败：{e}")
            traceback.print_exc()
        finally:
            self.q.put("__DONE__")
            self.q.put(("STATUS",))

    # ============ 模式 / 底模 ============
    def _current_mode(self):
        try:
            val = self.mode_combo.get()
            for k in core.MODE_KEYS:
                if core.MODE_LABELS[k] == val:
                    return k
        except Exception:
            pass
        return self.mode

    def _refresh_preset_summary(self):
        try:
            pre = core.preset_for(self.mode, self.base_type)
            te = "仅UNet" if self.unet_only_var.get() else "UNet+文本编码器"
            if self.mode == "video":
                self.preset_summary.configure(
                    text=f"当前预设：rank {pre.get('rank')} · alpha {pre.get('alpha')} · "
                         f"学习率 {pre.get('unet_lr')} · 训练步数 {pre.get('video_steps')} · 视频 24fps")
            else:
                self.preset_summary.configure(
                    text=f"当前预设：rank {pre.get('rank')} · alpha {pre.get('alpha')} · "
                         f"学习率 {pre.get('unet_lr')} · 文本编码器学习率 {pre.get('te_lr')} · "
                         f"repeats {pre.get('repeats')} · 最大epoch {pre.get('max_epochs')} · "
                         f"分辨率 {pre.get('resolution')}px · {te}")
        except Exception:
            pass

    def _apply_presets(self):
        self._applying_preset = True
        try:
            pre = core.preset_for(self.mode, self.base_type)
            for k, v in pre.items():
                if k not in self._manual_override:
                    self.param_vars.setdefault(k, tk.StringVar()).set(v)
        finally:
            self._applying_preset = False
        self._refresh_preset_summary()

    def _at_sub_label(self):
        """Qwen-Image / Z-Image 子模式：返回 'style' 或 'character'。"""
        try:
            _m = {v: k for k, v in core.AT_SUB_LABELS.items()}
            return _m.get(self.at_sub_var.get(), "character")
        except Exception:
            return "character"

    def _on_at_sub_change(self):
        """Qwen-Image / Z-Image 的画风/人物切换：刷新提示与自动保存。"""
        try:
            self._update_mode_ui()
        except Exception:
            pass
        try:
            self._render_guide()
        except Exception:
            pass
        self._schedule_autosave()

    def _nav_select_mode(self, mk):
        """方案A：侧边栏引擎导航点击模式 → 同步下拉并走统一切换流程。"""
        if mk not in core.MODE_KEYS:
            return
        try:
            self.mode_combo.set(core.MODE_LABELS[mk])
        except Exception:
            pass
        self._on_mode_change()
        self._refresh_nav_highlight()

    def _refresh_nav_highlight(self):
        """高亮当前模式对应的导航按钮。"""
        cur = getattr(self, "mode", None)
        for _mk, _btn in getattr(self, "_nav_mode_btns", {}).items():
            try:
                if _mk == cur:
                    _btn.configure(fg_color=ACC, text_color="#ffffff", hover_color=ACC_H)
                else:
                    _btn.configure(fg_color=CARD2, text_color=TXT, hover_color="#3a4150")
            except Exception:
                pass

    def _on_mode_change(self):
        self.mode = self._current_mode()
        # 模式切换：底模类型与新模式不匹配（如 style+flux2）→ 回该模式默认档，避免预设查表 KeyError 卡死界面
        try:
            _pres = core.PRESETS.get(self.mode) or {}
            if self.base_type not in _pres and _pres:
                self._set_base_type("sd15")
                try:
                    self.base_combo.set(core.BASE_TYPE_LABELS.get("sd15", "SD1.5"))
                except Exception:
                    pass
        except Exception:
            pass
        self._apply_presets()
        self._update_mode_ui()
        try:
            self._render_guide()
        except Exception:
            pass
        self._schedule_autosave()

    def _update_mode_ui(self):
        self._refresh_nav_highlight()
        try:
            self.home_title.configure(text=core.MODE_LABELS.get(self.mode, self.mode) + " 训练")
        except Exception:
            pass
        # Qwen-Image / Z-Image：显示「画风/人物」训练类型切换；其他模式隐藏
        try:
            _is_at = self.mode in ("qwen_image", "zimage", "krea2", "krea2_fz", "krea2_at", "flux2")
            if _is_at:
                self.at_sub_row.pack(fill="x", padx=22, pady=(0, 6))
            else:
                self.at_sub_row.pack_forget()
            # ⚡ 快跑档手动开关：仅 Z-Image 模式显示
            try:
                _fr = getattr(self, "fast_tier_row", None)
                if _fr is not None:
                    if self.mode == "zimage":
                        _fr.pack(fill="x", padx=22, pady=(0, 6))
                    else:
                        _fr.pack_forget()
            except Exception:
                pass
        except Exception:
            pass
        try:
            if self.mode == "video":
                _hint = core.TRIGGER_HINT_VIDEO
            elif self.mode in ("qwen_image", "zimage", "krea2", "krea2_fz", "krea2_at", "flux2"):
                if self._at_sub_label() == "concept":
                    _hint = core.TRIGGER_HINT_CONCEPT
                if self._at_sub_label() == "style":
                    _hint = core.TRIGGER_HINT_STYLE
                elif self.mode in ("qwen_image", "zimage"):
                    _hint = core.TRIGGER_HINT_AT
                elif self.mode in ("krea2", "krea2_fz"):
                    _hint = core.TRIGGER_HINT_KREA2
                elif self.mode == "krea2_at":
                    _hint = core.TRIGGER_HINT_KREA2_AT
                else:
                    _hint = core.TRIGGER_HINT_FLUX2
            elif self.mode == "concept":
                _hint = core.TRIGGER_HINT_CONCEPT
            elif self.mode == "character":
                _hint = core.TRIGGER_HINT_CHARACTER
            else:
                _hint = core.TRIGGER_HINT_STYLE
            self.trigger_hint_var.set(_hint)
        except Exception:
            pass
        # Krea2 模式：隐藏底模下拉，显示 Krea2 模型状态（Krea2 不用 SD/SDXL/FLUX/Anima 底模）
        try:
            _tef = getattr(self, "_adv_frames", {}).get("te_lr")
            if _tef is not None:
                if self.mode in ("krea2", "krea2_fz", "krea2_at", "flux2", "video", "qwen_image", "zimage"):
                    _tef.grid_remove()   # Krea2/FLUX.2/视频/AI图像：文本编码器不训练，该参数无效
                else:
                    try:
                        _tef.grid()
                    except Exception:
                        pass
        except Exception:
            pass
        # torch.compile 加速只接第二引擎 musubi 的 Krea2/FLUX.2（--compile）；第三引擎（ai-toolkit）yaml 无 compile 配置，
        # 显示在视频H3/Krea2AT/Qwen/Z-Image 是误导，隐藏（2026-09-01 群友 16G 第三引擎误勾加速导致困惑）。
        try:
            _cr = getattr(self, "compile_row", None)
            if _cr is not None:
                if self.mode in ("video", "krea2_at", "qwen_image", "zimage"):
                    _cr.pack_forget()
                else:
                    try:
                        _cr.pack(anchor="w", pady=(4, 0))
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            _hide_base = self.mode in ("krea2", "krea2_fz", "krea2_at", "flux2", "video", "qwen_image", "zimage")
            for w in (self.base_label, self.base_combo, self.btn_pick_base, self.btn_refresh_base, self.btn_download_base):
                try:
                    if _hide_base:
                        w.pack_forget()
                except Exception:
                    pass
            if not _hide_base:
                for _w, _p in ((self.base_label, 0), (self.base_combo, (10, 10)),
                               (self.btn_pick_base, 4), (self.btn_refresh_base, 4), (self.btn_download_base, 4)):
                    try:
                        _w.pack(side="left", padx=_p)
                    except Exception:
                        pass
            try:
                if self.mode in ("krea2", "krea2_fz", "krea2_at"):
                    self._refresh_krea2_status()
                    self.krea2_row.pack(fill="x", pady=(8, 0))
                    try:
                        _fzb = getattr(self, "btn_fizgig_install", None)
                        if _fzb is not None:
                            if self.mode == "krea2_fz":
                                _fzb.pack(side="left", padx=(6, 4))
                            else:
                                _fzb.pack_forget()
                    except Exception:
                        pass
                else:
                    try:
                        self.krea2_row.pack_forget()
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                if self.mode == "flux2":
                    self._refresh_flux2_status()
                    self.flux2_row.pack(fill="x", pady=(8, 0))
                else:
                    try:
                        self.flux2_row.pack_forget()
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                if self.mode == "video":
                    self._refresh_h3_status()
                    self.h3_row.pack(fill="x", pady=(8, 0))
                    try:
                        self.h3_row2.pack(fill="x", pady=(2, 0))
                    except Exception:
                        pass
                else:
                    try:
                        self.h3_row.pack_forget()
                    except Exception:
                        pass
                    try:
                        self.h3_row2.pack_forget()
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                if self.mode in ("qwen_image", "zimage"):
                    self._refresh_at_status()
                    self.at_row.pack(fill="x", pady=(8, 0))
                else:
                    try:
                        self.at_row.pack_forget()
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            pass
        # 视频/AI图像模式：repeats/max_epochs/分辨率 无效，隐藏；显示"训练步数"
        try:
            _adv = getattr(self, "_adv_frames", {})
            _use_steps = self.mode in ("video", "qwen_image", "zimage")
            _show_reso = self.mode in ("qwen_image", "zimage")   # AI 图像：按步训练但分辨率可调（8G 建议 512，训练端会自动钳制）
            for _k in ("repeats", "max_epochs", "resolution"):
                _f = _adv.get(_k)
                if _f is not None:
                    try:
                        if _k == "resolution":
                            if _show_reso:
                                _f.grid()          # Qwen/Z-Image 显示分辨率
                            elif _use_steps:
                                _f.grid_remove()   # 视频模式仍隐藏分辨率
                            else:
                                _f.grid()
                        elif _use_steps:
                            _f.grid_remove()
                        else:
                            _f.grid()
                    except Exception:
                        pass
            _vf = _adv.get("video_steps")
            if _vf is not None:
                try:
                    if _use_steps:
                        _vf.grid()
                    else:
                        _vf.grid_remove()
                except Exception:
                    pass
        except Exception:
            pass
        # 主卡片①/② 文案：视频模式切换提示
        try:
            if self.mode == "video":
                self.card1_title.configure(text="① 准备视频数据")
                self.card1_hint.configure(text="3~10 段 3~10 秒的同角色/同风格 mp4，每段配同名 .txt 字幕；H3 训练需 24G 显存")
                self.trig_card_title.configure(text="② 设置触发词（视频模式）")
            elif self.mode in ("qwen_image", "zimage"):
                self.card1_title.configure(text="① 准备图片数据")
                self.card1_hint.configure(text="人物模式建议 15~30 张同一人物；画风模式建议 20~60 张不同人物。图片越清晰越好")
                self.trig_card_title.configure(text="② 设置触发词（" + ("画风模式，一个词即可激活画风" if self._at_sub_label() == "style" else "人物模式") + "）")
            elif self.mode == "concept":
                self.card1_title.configure(text="① 准备图片数据")
                self.card1_hint.configure(text="15~30 张同一形态/种族（如美人鱼/半人马），刻意混不同画风/3D/实拍，避免 trigger 把画风一起吸进去")
                self.trig_card_title.configure(text="② 设置触发词（概念模式：一个词绑定整个形态/种族）")
            elif self.mode == "style":
                self.card1_title.configure(text="① 准备图片数据")
                self.card1_hint.configure(text="人物模式建议 15~30 张同一人物；画风模式建议 20~60 张不同人物。图片越清晰越好")
                self.trig_card_title.configure(text="② 设置触发词（画风模式，一个词即可激活画风）")
            else:
                self.card1_title.configure(text="① 准备图片数据")
                self.card1_hint.configure(text="人物模式建议 15~30 张同一人物；画风模式建议 20~60 张不同人物。图片越清晰越好")
                self.trig_card_title.configure(text="② 设置触发词（人物模式）")
        except Exception:
            pass
        # 画风描述词行：仅画风模式显示
        try:
            if self.mode == "style":
                self.style_caption_row.pack(fill="x", padx=22, pady=(0, 4))
            else:
                self.style_caption_row.pack_forget()
        except Exception:
            pass
        # 人物强绑定行：仅「人物」语义的模式显示（人物模式 / AI 图像・Krea2・FLUX.2 的人物子模式）
        try:
            _is_person = (self.mode == "character") or (
                self.mode in ("qwen_image", "zimage", "krea2", "krea2_fz", "krea2_at", "flux2")
                and self._at_sub_label() == "character")
            if _is_person:
                self.strong_bind_row.pack(fill="x", padx=22, pady=(0, 4))
            else:
                self.strong_bind_row.pack_forget()
        except Exception:
            pass
        # 画风模式：隐藏触发词/正则卡片内容（用 pack_forget 显示/隐藏行）
        try:
            self.trigger_entry.master.master.master.configure(
                fg_color=CARD if self.mode == "character" else CARD)
        except Exception:
            pass

    def _scan_base_models(self):
        """后台扫描底模目录（safetensors 只读头部秒级；.ckpt 用 torch 读取可能较慢，放后台不阻塞启动）。"""
        def _w():
            try:
                models = core.scan_base_models()
            except Exception:
                models = []
            try:
                self.q.put(("BASE_SCAN_DONE", models))
            except Exception:
                pass
        try:
            threading.Thread(target=_w, daemon=True).start()
        except Exception:
            pass

    def _apply_base_models(self, models):
        """主线程：把扫描结果填进底模下拉。"""
        self._base_models = models or []
        items, self._base_items, self._base_labels = [], [], []
        for bt in core.BASE_TYPE_KEYS:
            # 第一引擎（画风/人物）不支持 FLUX.2：底模下拉不列出，避免误选后报
            # 「sd-scripts 缺失 flux_2_train_network.py」（2026-08-29 六十九待办）
            if self.mode in ("style", "character") and bt == "flux2":
                continue
            items.append(core.BASE_TYPE_LABELS[bt])
            self._base_items.append(("type", bt))
            self._base_labels.append(core.BASE_TYPE_LABELS[bt])
        for p, n, t in self._base_models:
            label = f"📄 {n}" + (f"（{core.BASE_TYPE_LABELS[t]}）" if t else "")
            items.append(label)
            self._base_items.append(("file", p))
            self._base_labels.append(label)
        try:
            self.base_combo.configure(values=items)
            _cur = core.BASE_TYPE_LABELS.get(self.base_type)
            if _cur not in items:
                _cur = items[0]
            self.base_combo.set(_cur)
        except Exception:
            pass

    def _on_base_change(self):
        val = ""
        try:
            val = self.base_combo.get()
        except Exception:
            pass
        if val not in self._base_labels:
            return
        idx = self._base_labels.index(val)
        kind, payload = self._base_items[idx]
        if kind == "type":
            self._set_base_type(payload)
            model = self._find_model_of_type(payload)
            if model:
                self.base_model_var.set(model[0])
                self._log(f"[底模] 目录里找到 {core.BASE_TYPE_LABELS[payload]} 模型：{model[1]}")
            else:
                self.base_model_var.set("")
                self._log(f"[底模] {core.BASE_TYPE_LABELS[payload]} 目录里暂无模型")
                self.root.after(60, lambda: self._ask_download_or_open(payload))
        else:
            self.base_model_var.set(payload)
            bt = core.detect_base_type(payload)
            if bt in core.BASE_TYPE_KEYS:
                if self.mode in ("style", "character") and bt == "flux2":
                    self._log(f"[底模] ⚠ 检测到 FLUX.2 底模 {os.path.basename(payload)}：FLUX.2 训练请用第二引擎的「FLUX.2 图像LoRA」模式（需先装第二引擎），模型放 models/flux2/。第一引擎不支持 FLUX.2。")
                else:
                    self._set_base_type(bt)
                    self._log(f"[底模] 已选择 {os.path.basename(payload)}（{core.BASE_TYPE_LABELS[bt]}）")
            else:
                if core._looks_like_krea2(payload):
                    self._log(f"[底模] ⚠ 检测到 Krea2 底模 {os.path.basename(payload)}：Krea2 训练请用第二引擎的「Krea2」模式（需先装第二引擎），模型放 models/krea2/raw.safetensors；第一引擎不支持 Krea2。")
                else:
                    self._log(f"[底模] 已选择 {os.path.basename(payload)}（类型待确认）")

    def _set_base_type(self, bt):
        if bt not in core.BASE_TYPE_KEYS:
            return
        self.base_type = bt
        self._apply_presets()
        try:
            # FLUX / Anima 默认只训练 UNet/DiT 部分（省显存）
            self.unet_only_var.set(bt in ("flux", "anima"))
        except Exception:
            pass
        hint = core.BASE_TYPE_HINTS.get(bt)
        if hint:
            try:
                self._log(hint)
            except Exception:
                pass
        self._schedule_autosave()

    def _find_model_of_type(self, bt):
        for p, n, t in self._base_models:
            if t == bt:
                return (p, n, t)
        return None

    def cmd_refresh_base(self):
        self._scan_base_models()
        self._log(f"[底模] 已刷新模型列表（目录：{core.base_models_dir()}）")

    def cmd_pick_base(self):
        d = core.base_models_dir()
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        f = filedialog.askopenfilename(title="选择底模（.safetensors / .ckpt）", initialdir=d,
                                       filetypes=[("模型文件", "*.safetensors *.ckpt"), ("所有文件", "*.*")])
        if not f:
            return
        if not os.path.isfile(f):
            messagebox.showwarning(core.APP_NAME, "请选择模型文件（.safetensors 或 .ckpt），不要选文件夹。")
            return
        if not f.lower().endswith((".safetensors", ".ckpt")):
            messagebox.showwarning(core.APP_NAME, "请选择 .safetensors 或 .ckpt 格式的底模文件。")
            return
        self.base_model_var.set(f)
        self._refresh_guide()
        bt = core.detect_base_type(f)
        if bt in core.BASE_TYPE_KEYS:
            self._set_base_type(bt)
            try:
                self.base_combo.set(core.BASE_TYPE_LABELS[bt])
            except Exception:
                pass
            self._log(f"[底模] 已选择 {os.path.basename(f)}（自动识别为 {core.BASE_TYPE_LABELS[bt]}）")
        else:
            self._log(f"[底模] 已选择 {os.path.basename(f)}（类型待确认）")

    def cmd_download_base(self):
        self._download_choice_dialog()

    def cmd_pick_raw(self):
        _title = "选择视频数据集文件夹（mp4 + 同名txt字幕）" if self.mode == "video" else "选择原始图片文件夹"
        d = filedialog.askdirectory(title=_title)
        if d:
            self.raw_dir_var.set(d)
            self._refresh_guide()
            self._log(f"[预处理] 已选{'视频' if self.mode == 'video' else '原始图片'}文件夹：{d}")

    def cmd_pick_reg(self):
        d = filedialog.askdirectory(title="选择正则数据集文件夹（人物模式）")
        if d:
            self.reg_var.set(d)
            self._log(f"[预处理] 已选正则数据集：{d}")

    def cmd_open_output(self):
        if self.current_project:
            os.startfile(core.data_sub("output", self.current_project))
        else:
            os.startfile(core.data_sub("output"))

    def _apply_imported_config(self, cfg):
        """把导入的配置应用到当前（新）项目界面：完全覆盖模式/底模/参数（复用项目恢复逻辑）。"""
        bm = cfg.get("base_model") or ""
        full = core.find_model_by_filename(bm, cfg.get("mode")) if bm else None
        if full:
            self._log(f"[配置] 已自动定位底模：{full}")
        elif bm:
            self._log(f"[配置] ⚠ 本机未找到底模 {bm}，请重新选择底模。")
        data = {
            "mode": cfg.get("mode"),
            "base_type": cfg.get("base_type"),
            "at_sub_mode": cfg.get("at_sub_mode") or "character",
            "trigger": cfg.get("trigger") or "",
            "global_pos": cfg.get("global_pos") or "",
            "global_neg": cfg.get("global_neg") or "",
            "reg_dir": "",
            "raw_dir": "",
            "train_env": "",
            "base_model": full or "",
            "unet_only": bool(cfg.get("unet_only", False)),
            "params": cfg.get("params") or {},
        }
        self._apply_project_data(data)
        sc = cfg.get("style_caption")
        if sc:
            try:
                self.style_caption_var.set(sc)
            except Exception:
                pass
        sp = cfg.get("sample_prompt")
        if sp:
            try:
                self.sample_prompt_var.set(sp)
            except Exception:
                pass
        self._update_mode_ui()
        self._refresh_preset_summary()

    def cmd_export_config(self):
        """导出当前项目配置为可分享 JSON（不含本机路径/提示词，提示词可选勾选）。"""
        if not self.current_project:
            messagebox.showinfo(core.APP_NAME, "请先打开或新建一个项目，再导出配置。")
            return
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("导出配置")
        dlg.geometry("480x240")
        dlg.transient(self.root)
        dlg.grab_set()
        body = ctk.CTkFrame(dlg, fg_color=BG)
        body.pack(fill="both", expand=True, padx=18, pady=16)
        ctk.CTkLabel(body, text="配置名称", font=ui_font(FONT_BODY), text_color=TXT).pack(anchor="w")
        name_var = tk.StringVar(value=(self.current_project or "配置") + "_配置")
        name_entry = ctk.CTkEntry(body, textvariable=name_var, width=320, height=30,
                                  fg_color=CARD2, border_color=BORDER, text_color=TXT, font=ui_font(FONT_BODY))
        name_entry.pack(anchor="w", pady=(4, 2))
        ctk.CTkLabel(body, text="保存位置：桌面（.json）", font=ui_font(FONT_HINT), text_color=HINT).pack(anchor="w", pady=(0, 6))
        inc_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(body, text="包含 trigger 与提示词（画风描述词/采样提示词/全局提示词）",
                        variable=inc_var, fg_color=ACC, hover_color=ACC_H, text_color=TXT,
                        font=ui_font(FONT_HINT)).pack(anchor="w", pady=(4, 2))

        def _do_export():
            import json as _json
            name = name_var.get().strip() or ((self.current_project or "配置") + "_配置")
            cfg = core.export_config_json(self._collect_params(), include_prompts=inc_var.get())
            safe = re.sub(r'[\\/:*?"<>|\r\n\t ]+', "_", name)[:60] or "配置"
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            if not os.path.isdir(desktop):
                desktop = os.path.expanduser("~")
            path = os.path.join(desktop, safe + ".json")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    _json.dump(cfg, f, ensure_ascii=False, indent=2)
            except Exception as e:
                messagebox.showerror(core.APP_NAME, f"导出失败：{e}")
                return
            self._log(f"[配置] 已导出到 {path}")
            messagebox.showinfo(core.APP_NAME, f"配置已导出：\n{path}\n\n可分享给他人，或下次新建项目时点「导入配置」复用。")
            dlg.destroy()

        ctk.CTkButton(body, text="导出", width=110, height=34, fg_color=ACC, hover_color=ACC_H,
                      corner_radius=6, font=ui_font(FONT_BODY), command=_do_export).pack(side="right", pady=(8, 0))
        ctk.CTkButton(body, text="取消", width=90, height=34, fg_color=CARD2, hover_color="#343a46",
                      border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                      font=ui_font(FONT_BODY), command=dlg.destroy).pack(side="right", padx=(8, 0), pady=(8, 0))

    def cmd_readme(self):
        self._show_help_window()

    def cmd_export_log(self):
        """一键导出运行日志 + 环境信息（反馈/求助时直接把 txt 发给维护者）。"""
        log_text = ""
        try:
            log_text = "\n".join(getattr(self, "_full_log", None) or [])
        except Exception:
            pass
        project = (self.current_project or "").strip() or "tool"
        self._log("[导出] 正在收集运行日志与环境信息…")
        def work():
            try:
                text = _export_log_text(log_text, project)
                fname = "KohyaLoRA_%s_%s.txt" % (
                    re.sub(r'[\\/:*?"<>|\r\n\t ]+', "_", project)[:40] or "日志",
                    time.strftime("%Y%m%d_%H%M%S"))
                dest = None
                try:
                    _d = os.path.join(os.path.expanduser("~"), "Desktop", fname)
                    with open(_d, "w", encoding="utf-8") as f:
                        f.write(text)
                    dest = _d
                except Exception:
                    _d = os.path.join(core.data_sub("logs"), fname)
                    os.makedirs(os.path.dirname(_d), exist_ok=True)
                    with open(_d, "w", encoding="utf-8") as f:
                        f.write(text)
                    dest = _d
                self.root.after(0, lambda: self._log("[导出] 日志已导出：" + dest))
                self.root.after(0, lambda: self._show_export_dialog(dest))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror(core.APP_NAME, "导出日志失败：\n%s" % e))
        threading.Thread(target=work, daemon=True).start()

    def _show_export_dialog(self, dest):
        """导出成功弹窗：打开文件 / 打开所在文件夹 / 复制路径。"""
        try:
            w = ctk.CTkToplevel(self.root)
            w.title("导出日志")
            w.geometry("620x235")
            w.transient(self.root)
            ctk.CTkLabel(w, text="✅ 运行日志已导出", font=ui_font(FONT_TITLE), text_color=TITLE_C).pack(anchor="w", padx=18, pady=(16, 4))
            ctk.CTkLabel(w, text="把这个 txt 发给维护者 / 贴到评论区即可完整定位问题（已自动附带环境信息）。",
                         font=ui_font(FONT_HINT), text_color=HINT).pack(anchor="w", padx=18)
            var = tk.StringVar(value=dest)
            ctk.CTkEntry(w, width=580, height=30, textvariable=var, state="readonly").pack(padx=18, pady=(10, 4))
            btn_row = ctk.CTkFrame(w, fg_color="transparent"); btn_row.pack(fill="x", padx=18, pady=(4, 12))
            ctk.CTkButton(btn_row, text="📄 打开文件", width=120, height=34, fg_color=ACC, hover_color=ACC_H,
                          corner_radius=6, font=ui_font(FONT_BODY),
                          command=lambda: os.startfile(dest)).pack(side="left")
            ctk.CTkButton(btn_row, text="📂 打开所在文件夹", width=150, height=34, fg_color="transparent",
                          hover_color="#252a36", border_width=1, border_color=BORDER, text_color=SUB,
                          corner_radius=6, font=ui_font(FONT_BODY),
                          command=lambda: subprocess.Popen(["explorer", "/select," + dest])).pack(side="left", padx=(10, 0))
            ctk.CTkButton(btn_row, text="📋 复制路径", width=110, height=34, fg_color="transparent",
                          hover_color="#252a36", border_width=1, border_color=BORDER, text_color=SUB,
                          corner_radius=6, font=ui_font(FONT_BODY),
                          command=lambda: (w.clipboard_clear(), w.clipboard_append(dest))).pack(side="left", padx=(10, 0))
            ctk.CTkButton(btn_row, text="关闭", width=80, height=34, fg_color="transparent",
                          hover_color="#252a36", border_width=1, border_color=BORDER, text_color=SUB,
                          corner_radius=6, font=ui_font(FONT_BODY), command=w.destroy).pack(side="right")
        except Exception:
            messagebox.showinfo(core.APP_NAME, "运行日志已导出：\n" + dest)

    def cmd_data_dir(self):
        """数据 / 引擎目录管理：查看占用，迁移到其他盘（解决 C 盘占用）。"""
        try:
            if getattr(self, "_data_dir_win", None) and self._data_dir_win.winfo_exists():
                self._data_dir_win.lift()
                return
        except Exception:
            pass
        w = ctk.CTkToplevel(self.root)
        w.title("数据 / 引擎目录")
        w.geometry("640x420")
        w.transient(self.root)
        try:
            from tkinter import filedialog
            cur = core.data_dir()
            size_mb = core.data_dir_size() / 1048576.0
            cur_var = tk.StringVar(value=cur)
            size_var = tk.StringVar(value="%.0f MB" % size_mb)
            ctk.CTkLabel(w, text="📁 数据 / 引擎目录", font=ui_font(FONT_TITLE), text_color=TITLE_C).pack(anchor="w", padx=18, pady=(16, 6))
            ctk.CTkLabel(w, text="训练引擎、数据集、模型缓存等都在这里。默认在 C 盘 AppData；装在其他盘时可迁移到安装盘，释放 C 盘空间。",
                         font=ui_font(FONT_HINT), text_color=HINT, wraplength=580, justify="left").pack(anchor="w", padx=18, pady=(0, 8))
            ctk.CTkLabel(w, text="当前目录", font=ui_font(FONT_BODY), text_color=SUB).pack(anchor="w", padx=18)
            ctk.CTkEntry(w, width=580, height=30, textvariable=cur_var, state="readonly").pack(padx=18, pady=(2, 4))
            ctk.CTkLabel(w, text="占用大小", font=ui_font(FONT_BODY), text_color=SUB).pack(anchor="w", padx=18)
            ctk.CTkLabel(w, textvariable=size_var, font=ui_font(FONT_BODY), text_color=TXT).pack(anchor="w", padx=18, pady=(2, 10))

            def _do_migrate(target):
                if not messagebox.askyesno(
                        core.APP_NAME,
                        "将把数据目录迁移到：\\n" + target + "\\n\\n"
                        "过程先复制、校验后删除旧目录（视数据量约几分钟）。\\n"
                        "迁移完成后请完全退出并重新打开软件。是否继续？"):
                    return
                def work():
                    self._log(f"[迁移] 开始迁移数据目录到 {target} …")
                    ok, msg = core.migrate_data_dir(target, logf=self._log)
                    if ok:
                        self._log("[迁移] " + msg)
                        messagebox.showinfo(core.APP_NAME, "迁移完成！请完全退出并重新打开软件。")
                    else:
                        self._log("[迁移] 失败：" + msg)
                        messagebox.showerror(core.APP_NAME, "迁移失败：\\n" + msg)
                    try:
                        w.destroy()
                    except Exception:
                        pass
                threading.Thread(target=work, daemon=True).start()

            def _pick_and_migrate():
                d = filedialog.askdirectory(title="选择新的数据目录（建议选安装盘，如 D:\\KohyaLoraTool_data）")
                if d:
                    _do_migrate(d)

            def _follow_install():
                _do_migrate(os.path.join(os.path.dirname(os.path.abspath(core.KIT_DIR)), "KohyaLoraTool_data"))

            btn_row = ctk.CTkFrame(w, fg_color="transparent"); btn_row.pack(fill="x", padx=18, pady=(8, 4))
            ctk.CTkButton(btn_row, text="选择目录并迁移…", width=150, height=34, fg_color=ACC, hover_color=ACC_H,
                          corner_radius=6, font=ui_font(FONT_BODY), command=_pick_and_migrate).pack(side="left")
            ctk.CTkButton(btn_row, text="跟随安装位置（自动）", width=170, height=34, fg_color="transparent",
                          hover_color="#252a36", border_width=1, border_color=BORDER, text_color=SUB,
                          corner_radius=6, font=ui_font(FONT_BODY), command=_follow_install).pack(side="left", padx=(10, 0))
            ctk.CTkLabel(w, text="提示：迁移后 C 盘 AppData 里的旧数据会被清理；若中途失败会保留源目录，可重试。",
                         font=ui_font(FONT_HINT), text_color=HINT, wraplength=580).pack(anchor="w", padx=18, pady=(10, 0))
            self._data_dir_win = w
        except Exception as e:
            messagebox.showerror(core.APP_NAME, "打开数据目录设置失败：" + str(e))

    def cmd_check_update(self):
        """检查更新（手动按钮）。"""
        if getattr(self, "_checking_update", False):
            return
        self._checking_update = True
        self._log("[更新] 正在检查新版本…")
        def work():
            try:
                info = core.check_update()
            except Exception:
                info = None
            try:
                self.q.put(("UPDATE_CHECK", info))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _handle_update_check(self, info):
        self._checking_update = False
        if not info:
            self._log("[更新] 检查失败（网络或 GitHub 限流），可稍后重试。")
            messagebox.showinfo(core.APP_NAME,
                                "检查更新失败：无法连接 GitHub（网络或限流问题）。\n可稍后重试，或直接到 GitHub Releases 手动下载。")
            return
        if not info.get("newer"):
            self._log(f"[更新] 已是最新版本 v{core.APP_VERSION}")
            messagebox.showinfo(core.APP_NAME, f"当前已是最新版本 v{core.APP_VERSION} ✅")
            return
        ver = info["version"]
        self._log(f"[更新] 发现新版本 {ver}")
        if messagebox.askyesno(
                core.APP_NAME,
                f"发现新版本 {ver}（当前 v{core.APP_VERSION}）\n\n"
                f"{(info.get('notes') or '').strip()[:180]}\n\n"
                "是否下载并安装？\n（约 445MB，支持断点续传，装完自动重启）"):
            self._start_update(info["setup_url"], ver, info.get("setup_url_cn"))

    def _auto_check_update(self):
        """启动后台静默检查：有新版本才提示。"""
        if getattr(self, "_checking_update", False):
            return
        try:
            self._log("[更新] 后台检查新版本…")
        except Exception:
            pass
        def work():
            try:
                info = core.check_update()
            except Exception:
                info = None
            try:
                self.q.put(("AUTO_UPDATE", info))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _handle_auto_update(self, info):
        if not info or not info.get("newer"):
            return
        ver = info["version"]
        self._log(f"[更新] 发现新版本 {ver}（当前 v{core.APP_VERSION}）")
        if messagebox.askyesno(
                core.APP_NAME,
                f"发现新版本 {ver}（当前 v{core.APP_VERSION}）\n\n"
                f"{(info.get('notes') or '').strip()[:180]}\n\n"
                "是否下载并安装？\n（约 445MB，支持断点续传，装完自动重启）"):
            self._start_update(info["setup_url"], ver, info.get("setup_url_cn"))

    def _start_update(self, url, ver, url_cn=""):
        if getattr(self, "_updating", False):
            return
        try:
            os.makedirs(core.data_sub("cache", "update"), exist_ok=True)
        except Exception:
            pass
        # 国内镜像优先（如果有），GitHub 兜底
        use = (url_cn or "").strip() or url
        dest = os.path.join(core.data_sub("cache", "update"),
                            "KohyaLoraTool_Setup_%s.exe" % ver.replace("v", ""))
        self._updating = True
        self._set_busy(True)
        self._upd_ver = ver
        self._log(f"[更新] 开始下载 {ver}（约 445MB，断点续传，完成自动重启）…")
        self._log(f"[更新] 下载源：{'国内魔搭镜像' if (url_cn or '').strip() else 'GitHub 兜底'}")
        def work():
            ok = False
            last_th = [0]
            def _prog(size, total):
                # 进度反馈：total 已知时每 10% 一行；未知时每 20MB 一行（避免刷屏）
                try:
                    if total:
                        pct = int(size * 100.0 / total)
                        if pct // 10 > last_th[0]:
                            last_th[0] = pct // 10
                            self.q.put(("UPDATE_PROGRESS", size, total))
                    else:
                        mb = size / 1048576
                        if mb >= last_th[0] + 20:
                            last_th[0] = int(mb)
                            self.q.put(("UPDATE_PROGRESS", size, None))
                except Exception:
                    pass
            try:
                ok = core._download_with_resume(use, dest, self._log, progress_cb=_prog)
            except Exception as e:
                self._log(f"[更新] 下载异常：{e}")
            try:
                self.q.put(("UPDATE_DONE", ok, dest, ver))
            except Exception:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _handle_update_progress(self, size, total):
        """更新包下载进度显示（不刷屏）。"""
        try:
            ver = getattr(self, "_upd_ver", "")
            if total:
                mb = size / 1048576
                tmb = total / 1048576
                self._log(f"[更新] 正在下载 {ver}：{mb:.1f}MB / {tmb:.1f}MB（{int(size * 100.0 / total)}%）…")
            else:
                self._log(f"[更新] 正在下载 {ver}：已下载 {size / 1048576:.1f}MB …")
        except Exception:
            pass

    def _handle_update_done(self, ok, dest, ver):
        self._updating = False
        try:
            self._set_busy(False)
        except Exception:
            pass
        if not ok or not (dest and os.path.isfile(dest)):
            self._log("[更新] 下载失败或已取消，可重试（断点续传）")
            messagebox.showerror(core.APP_NAME, "更新包下载失败，请稍后重试（支持断点续传）。")
            return
        self._log(f"[更新] 下载完成，正在静默安装 {ver} …（装完自动重启）")
        try:
            subprocess.Popen([dest, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
        except Exception as e:
            self._log(f"[更新] 启动安装失败：{e}")
            messagebox.showerror(core.APP_NAME, f"启动安装失败：{e}")
            return
        # 关闭本程序，让安装器覆盖文件
        self.root.after(1500, self.root.destroy)
    # ==================== 🧰 小工具：训练前通用操作 ====================
    def cmd_open_tools(self):
        """主页 🧰 小工具：训练前通用操作（查看 / 清理显存 / 清理内存 / 清理临时缓存 / 一键清理）。"""
        try:
            if getattr(self, "_tools_win", None) is not None and self._tools_win.winfo_exists():
                self._tools_win.lift()
                return
            w = ctk.CTkToplevel(self.root)
            w.title("🧰 小工具（训练前通用操作）")
            w.geometry("840x820")
            w.transient(self.root)
            w.minsize(680, 560)
            self._tools_win = w
            body = ctk.CTkScrollableFrame(w, fg_color="transparent")
            body.pack(fill="both", expand=True, padx=16, pady=(12, 12))
            self._tool_busy = {}
            self._vram_rows = []   # [(proc_dict, BooleanVar, row_frame)]

            try:
                _vendor = core.detect_gpu_info().get("vendor") or "unknown"
            except Exception:
                _vendor = "unknown"

            def _sec(title, hint=""):
                f = ctk.CTkFrame(body, fg_color="transparent")
                f.pack(fill="x", pady=(0, 10))
                ctk.CTkLabel(f, text=title, font=ui_font(FONT_BODY), text_color=TXT).pack(side="left")
                if hint:
                    ctk.CTkLabel(f, text=hint, font=ui_font(FONT_HINT), text_color=HINT).pack(side="left", padx=(10, 0))
                return f

            # ① 查看
            s1 = _sec("① 查看显卡 / 显存占用")
            self.btn_tools_view = ctk.CTkButton(s1, text="🔄 刷新", width=84, height=26, fg_color="transparent",
                                                hover_color="#252a36", border_width=1, border_color=BORDER, text_color=SUB,
                                                corner_radius=6, font=ui_font(FONT_HINT))
            self.btn_tools_view.pack(side="right")
            self.btn_tools_view.configure(command=lambda: self._tools_run("view", self.btn_tools_view, self.tools_view_box,
                                                                           core.gpu_status_text, "小工具·查看显卡", str))
            self.tools_view_box = self._tools_result_box(body, 130)

            # ② 清理显存（仅 N 卡）
            s2 = _sec("② 清理残留训练进程", "结束残留的训练进程释放显存/内存（N 卡 + AMD 通用）；正在跑的训练会自动排除")
            self.btn_tools_kill = ctk.CTkButton(s2, text="结束所选", width=104, height=26, fg_color="transparent",
                                                hover_color="#252a36", border_width=1, border_color=BORDER, text_color=SUB,
                                                corner_radius=6, font=ui_font(FONT_HINT), command=self._tools_kill_vram)
            self.btn_tools_kill.pack(side="right")
            self.btn_tools_scan = ctk.CTkButton(s2, text="🔍 扫描残留", width=96, height=26, fg_color="transparent",
                                                hover_color="#252a36", border_width=1, border_color=BORDER, text_color=SUB,
                                                corner_radius=6, font=ui_font(FONT_HINT), command=self._tools_scan_vram)
            self.btn_tools_scan.pack(side="right", padx=(0, 6))
            # 勾选列表框：有残留进程时才显示（pack），平时隐藏避免空框把下面模块挤下去
            self.tools_vram_list = ctk.CTkFrame(body, fg_color="transparent")
            self.tools_vram_box = self._tools_result_box(body, 90)
            if _vendor not in ("nvidia", "amd"):
                for _b in (self.btn_tools_scan, self.btn_tools_kill):
                    try:
                        _b.configure(state="disabled")
                    except Exception:
                        pass
                self._tools_set_text(self.tools_vram_box, "「清理残留进程」当前不可用（未知显卡：%s）；其他工具不受影响。" % _vendor)

            # ③ 清理内存
            s3 = _sec("③ 清理内存", "对所有进程压缩工作集（安全），显示前后空闲内存")
            self.btn_tools_mem = ctk.CTkButton(s3, text="🧹 清理内存", width=104, height=26, fg_color="transparent",
                                               hover_color="#252a36", border_width=1, border_color=BORDER, text_color=SUB,
                                               corner_radius=6, font=ui_font(FONT_HINT))
            self.btn_tools_mem.pack(side="right")
            self.btn_tools_mem.configure(command=lambda: self._tools_run("mem", self.btn_tools_mem, self.tools_mem_box,
                                                                          core.clear_memory, "小工具·清理内存", self._fmt_mem))
            self.tools_mem_box = self._tools_result_box(body, 84)

            # ④ 清理临时缓存
            s4 = _sec("④ 清理临时缓存", "只清可再生缓存（更新包/采样提示词/临时文件），绝不动模型·数据集·输出·断点")
            self.btn_tools_cache = ctk.CTkButton(s4, text="🧹 清理缓存", width=104, height=26, fg_color="transparent",
                                                 hover_color="#252a36", border_width=1, border_color=BORDER, text_color=SUB,
                                                 corner_radius=6, font=ui_font(FONT_HINT))
            self.btn_tools_cache.pack(side="right")
            self.btn_tools_cache.configure(command=lambda: self._tools_run("cache", self.btn_tools_cache, self.tools_cache_box,
                                                                           core.clear_temp_cache, "小工具·清理缓存", self._fmt_cache))
            self.tools_cache_box = self._tools_result_box(body, 84)

            # ⑤ 一键全部清理
            s5 = _sec("⑤ 一键全部清理", "结束残留训练进程 → 清内存 → 清缓存（不可用项自动跳过）")
            self.btn_tools_all = ctk.CTkButton(s5, text="⚡ 一键清理", width=104, height=28, fg_color=ACC,
                                               hover_color=ACC_H, corner_radius=6, font=ui_font(FONT_BODY), command=self._tools_oneclick)
            self.btn_tools_all.pack(side="right")
            self.tools_all_box = self._tools_result_box(body, 110)

            # ⑥ 下载源：国内镜像太慢时切官方源（需代理）
            s6 = _sec("⑥ 下载源", "国内镜像太慢/失败时，改用官方源（PyTorch 官方 / GitHub / HuggingFace，需开代理）")
            self.var_official_src = ctk.BooleanVar(value=bool(core._load_app_settings().get("download_official_first")))

            def _toggle_official_src():
                try:
                    _d = dict(core._load_app_settings())
                    _d["download_official_first"] = bool(self.var_official_src.get())
                    core._save_app_settings(_d)
                    self._log("[下载源] %s官方源优先（PyTorch 官方 / GitHub / HuggingFace，需开代理）；国内镜像仍作备用。" %
                              ("已启用" if self.var_official_src.get() else "已关闭，恢复"))
                except Exception as _e:
                    self._log("[下载源] 保存设置失败：%s" % _e)

            self.chk_official_src = ctk.CTkCheckBox(
                s6, text="国内镜像太慢时改用官方源（需开代理）", variable=self.var_official_src,
                command=_toggle_official_src, font=ui_font(FONT_BODY), text_color=TXT)
            self.chk_official_src.pack(side="left", padx=(0, 10))
            ctk.CTkLabel(
                s6, text="当前：%s（影响 torch 大轮子 / 引擎源码 / 底模下载，立即生效）" %
                         ("官方源优先" if self.var_official_src.get() else "国内镜像优先"),
                font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
            # 打开窗口自动跑一次「查看」
            self._tools_run("view", self.btn_tools_view, self.tools_view_box, core.gpu_status_text, "小工具·查看显卡", str)
        except Exception as e:
            messagebox.showerror(core.APP_NAME, "打开小工具失败：%s" % e)

    def _tools_set_text(self, box, text):
        try:
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("1.0", text if text else "（无输出）")
            box.configure(state="disabled")
        except Exception:
            pass

    def _tools_result_box(self, parent, height=90):
        box = ctk.CTkTextbox(parent, height=height, fg_color="#14161c", text_color="#b6bcc9", corner_radius=6,
                             border_width=1, border_color=BORDER, font=ui_font(FONT_LOG), state="disabled", wrap="word")
        box.pack(fill="x", pady=(4, 0))
        return box

    def _tools_run(self, tid, btn, box, fn, label, formatter=None):
        """后台线程执行一个工具；执行期间禁用按钮，结果回填 + 写主日志。"""
        if self._tool_busy.get(tid):
            return
        self._tool_busy[tid] = True
        try:
            btn.configure(state="disabled")
        except Exception:
            pass
        self._tools_set_text(box, "执行中…")
        def work():
            try:
                res = fn()
                text = formatter(res) if formatter else str(res)
            except Exception as e:
                text = "执行失败：%s" % e
            def done():
                try:
                    self._tools_set_text(box, text)
                    self._log("[小工具] %s：\n%s" % (label, text))
                except Exception:
                    pass
                finally:
                    self._tool_busy[tid] = False
                    try:
                        btn.configure(state="normal")
                    except Exception:
                        pass
            try:
                self.root.after(0, done)
            except Exception:
                self._tool_busy[tid] = False
        threading.Thread(target=work, daemon=True).start()

    def _fmt_mem(self, res):
        before, after, ok, skip = res
        released = (after - before) if (before and after and after >= before) else None
        return ("清理前空闲内存: %s MB\n清理后空闲内存: %s MB%s\n成功 %d 个进程，跳过 %d 个（系统/权限受限属正常）"
                % (before, after, ("（释放约 %s MB）" % released) if released is not None else "", ok, skip))

    def _fmt_cache(self, res):
        if not res:
            return "没有可清理的缓存 ✅"
        lines = ["已清理 %d 项：" % len(res)]
        tot = 0.0
        for label, path, mb in res:
            lines.append("· %s：%s（%.2f MB）" % (label, path, mb))
            tot += mb
        lines.append("合计释放约 %.2f MB" % tot)
        return "\n".join(lines)

    def _tools_scan_vram(self):
        """扫描残留训练进程，勾选后点「结束所选」。"""
        if self._tool_busy.get("vram"):
            return
        self._tool_busy["vram"] = True
        try:
            self.btn_tools_scan.configure(state="disabled")
        except Exception:
            pass
        self._tools_set_text(self.tools_vram_box, "扫描中…")
        def work():
            try:
                procs = core.vram_residual_processes()
            except Exception:
                procs = None
            def done():
                try:
                    for _p, _v, row in getattr(self, "_vram_rows", []):
                        try:
                            row.destroy()
                        except Exception:
                            pass
                    self._vram_rows = []
                    if procs is None:
                        self.tools_vram_list.pack_forget()
                        self._tools_set_text(self.tools_vram_box, "扫描失败（nvidia-smi 不可用，驱动可能未安装/损坏）")
                        self.btn_tools_kill.configure(text="结束所选")
                    elif not procs:
                        self.tools_vram_list.pack_forget()
                        self._tools_set_text(self.tools_vram_box, "没有残留的训练进程占用显存 ✅")
                        self.btn_tools_kill.configure(text="结束所选")
                    else:
                        self.tools_vram_list.pack(fill="x", before=self.tools_vram_box)
                        self._tools_set_text(self.tools_vram_box, "找到 %d 个残留训练进程（已勾选，可取消后点「结束所选」）：" % len(procs))
                        for p in procs:
                            var = tk.BooleanVar(value=True)
                            row = ctk.CTkFrame(self.tools_vram_list, fg_color="transparent")
                            row.pack(fill="x")
                            ctk.CTkCheckBox(row, text="PID %d | %s | %d MiB" % (p["pid"], p["name"], p["mem_mb"]),
                                            variable=var, fg_color=ACC, hover_color=ACC_H, text_color=TXT,
                                            font=ui_font(FONT_HINT)).pack(side="left")
                            self._vram_rows.append((p, var, row))
                        self.btn_tools_kill.configure(text="结束所选 %d 个进程" % len(procs))
                finally:
                    self._tool_busy["vram"] = False
                    try:
                        self.btn_tools_scan.configure(state="normal")
                    except Exception:
                        pass
            try:
                self.root.after(0, done)
            except Exception:
                self._tool_busy["vram"] = False
        threading.Thread(target=work, daemon=True).start()

    def _tools_kill_vram(self):
        sel = [(p, var) for p, var, _row in getattr(self, "_vram_rows", []) if var.get()]
        if not sel:
            messagebox.showinfo(core.APP_NAME, "没有勾选要结束的进程（可先点「扫描残留」）")
            return
        if self._tool_busy.get("vramkill"):
            return
        self._tool_busy["vramkill"] = True
        pids = [p["pid"] for p, _v in sel]
        try:
            self.btn_tools_kill.configure(state="disabled")
        except Exception:
            pass
        before = core.nvidia_vram_used_mb()
        def work():
            try:
                ok, fail = core.kill_processes(pids)
                after = core.nvidia_vram_used_mb()
                if before is None and after is None:
                    text = "已结束 %d 个进程，失败 %d 个%s" % (
                        len(ok), len(fail),
                        ("：" + ",".join(str(p) for p in fail)) if fail else "")
                else:
                    text = "清理前已用显存: %s MB\n已结束 %d 个进程，失败 %d 个%s\n清理后已用显存: %s MB" % (
                        before, len(ok), len(fail),
                        ("：" + ",".join(str(p) for p in fail)) if fail else "", after)
            except Exception as e:
                text = "执行失败：%s" % e
            def done():
                try:
                    self._tools_set_text(self.tools_vram_box, text)
                    self._log("[小工具] 清理显存：\n%s" % text)
                    for _p, _v, row in getattr(self, "_vram_rows", []):
                        try:
                            row.destroy()
                        except Exception:
                            pass
                    self._vram_rows = []
                    try:
                        self.tools_vram_list.pack_forget()
                    except Exception:
                        pass
                    self.btn_tools_kill.configure(text="结束所选")
                finally:
                    self._tool_busy["vramkill"] = False
                    try:
                        self.btn_tools_kill.configure(state="normal")
                    except Exception:
                        pass
            try:
                self.root.after(0, done)
            except Exception:
                self._tool_busy["vramkill"] = False
        threading.Thread(target=work, daemon=True).start()

    def _tools_oneclick(self):
        """一键清理：结束残留训练进程 → 清内存 → 清缓存（不可用项自动跳过）。"""
        if self._tool_busy.get("all"):
            return
        self._tool_busy["all"] = True
        try:
            self.btn_tools_all.configure(state="disabled")
        except Exception:
            pass
        self._tools_set_text(self.tools_all_box, "执行中…")
        def work():
            parts = []
            try:
                vendor = core.detect_gpu_info().get("vendor") or "unknown"
            except Exception:
                vendor = "unknown"
            # 1) 显存残留（仅 N 卡）
            if vendor == "nvidia":
                try:
                    procs = core.vram_residual_processes()
                    if procs:
                        ok, fail = core.kill_processes([p["pid"] for p in procs])
                        parts.append("① 清理显存：结束 %d 个残留训练进程（失败 %d 个）" % (len(ok), len(fail)))
                    else:
                        parts.append("① 清理显存：没有残留训练进程")
                except Exception as e:
                    parts.append("① 清理显存：失败 %s" % e)
            else:
                parts.append("① 清理显存：当前非 N 卡，跳过")
            # 2) 内存
            try:
                before, after, ok, skip = core.clear_memory()
                parts.append("② 清理内存：空闲 %s → %s MB（%d 个进程成功，跳过 %d 个）" % (before, after, ok, skip))
            except Exception as e:
                parts.append("② 清理内存：失败 %s" % e)
            # 3) 缓存
            try:
                res = core.clear_temp_cache()
                tot = sum(mb for _l, _p, mb in res)
                parts.append("③ 清理缓存：%d 项，释放 %.2f MB" % (len(res), tot))
            except Exception as e:
                parts.append("③ 清理缓存：失败 %s" % e)
            text = "\n".join(parts)
            def done():
                try:
                    self._tools_set_text(self.tools_all_box, text)
                    self._log("[小工具] 一键清理：\n%s" % text)
                finally:
                    self._tool_busy["all"] = False
                    try:
                        self.btn_tools_all.configure(state="normal")
                    except Exception:
                        pass
            try:
                self.root.after(0, done)
            except Exception:
                self._tool_busy["all"] = False
        threading.Thread(target=work, daemon=True).start()

    def _toggle_adv(self):
        self.adv_collapsed = not self.adv_collapsed
        if self.adv_collapsed:
            self.adv_body.pack_forget()
            self.btn_toggle_adv.configure(text="展开 ▾")
        else:
            if not self.adv_body.winfo_children():
                self._build_adv_body()
            self.adv_body.pack(fill="x", padx=22, pady=(0, 14))
            self.btn_toggle_adv.configure(text="收起 ▴")

    def _build_adv_body(self):
        g = ctk.CTkFrame(self.adv_body, fg_color="transparent")
        g.pack(fill="x")
        prow = ctk.CTkFrame(self.adv_body, fg_color="transparent"); prow.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(prow, text="风格预设（一键填入常用数值）", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        self.style_preset_menu = ctk.CTkOptionMenu(
            prow, values=["自定义", "动漫", "写实"], width=120, height=26,
            fg_color=CARD2, button_color=CARD2, button_hover_color="#3a4150",
            text_color=SUB, font=ui_font(FONT_HINT), dropdown_font=ui_font(FONT_HINT),
            dropdown_fg_color=CARD2, dropdown_hover_color="#3a4150", command=self._apply_style_preset)
        self.style_preset_menu.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(prow, text="（动漫偏精细、写实偏自然；选完仍可手动微调）", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left", padx=(10, 0))
        items = [("rank", "rank"), ("alpha", "alpha"), ("学习率", "unet_lr"),
                 ("文本编码器学习率", "te_lr"), ("repeats", "repeats"), ("最大 epoch", "max_epochs"),
                 ("训练分辨率", "resolution"), ("训练步数", "video_steps")]
        for i, (label, key) in enumerate(items):
            f = ctk.CTkFrame(g, fg_color="transparent"); f.grid(row=0, column=i, padx=10, pady=8, sticky="w")
            ctk.CTkLabel(f, text=label, font=ui_font(FONT_HINT), text_color=HINT).pack(anchor="w")
            v = self.param_vars.setdefault(key, tk.StringVar())
            try:
                v.trace_add("write", lambda *a: self._schedule_autosave())
            except Exception:
                pass
            entry = ctk.CTkEntry(f, width=80, height=28, justify="center", textvariable=v,
                                 fg_color=CARD2, border_color=BORDER, text_color=TXT, font=ui_font(FONT_BODY))
            entry.pack(pady=(3, 0))
            self._adv_entries[key] = entry
            self._adv_frames[key] = f
        # 模型保存间隔：画风/人物=每 N 步，Krea2/FLUX.2=每 N 轮（留空用默认）
        sf = ctk.CTkFrame(g, fg_color="transparent")
        sf.grid(row=1, column=0, columnspan=9, sticky="w", padx=10, pady=(0, 8))
        ctk.CTkLabel(sf, text="模型保存间隔", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        _sv = self.param_vars.setdefault("save_every", tk.StringVar())
        try:
            _sv.trace_add("write", lambda *a: self._schedule_autosave())
        except Exception:
            pass
        _se = ctk.CTkEntry(sf, width=80, height=28, justify="center", textvariable=_sv,
                           fg_color=CARD2, border_color=BORDER, text_color=TXT, font=ui_font(FONT_BODY))
        _se.pack(side="left", padx=(10, 8))
        ctk.CTkLabel(sf, text="（画风/人物=每 N 步，Krea2/FLUX.2=每 N 轮；留空=默认 200 步 / 1 轮）",
                     font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        self._adv_entries["save_every"] = _se
        self._adv_frames["save_every"] = sf
        cb = ctk.CTkFrame(self.adv_body, fg_color="transparent"); cb.pack(anchor="w", pady=(4, 0))
        self.chk_unet_only = ctk.CTkCheckBox(cb, text="只训练 UNet（不训练文本编码器）", variable=self.unet_only_var,
                                             fg_color=ACC, hover_color=ACC_H, text_color=TXT, font=ui_font(FONT_BODY),
                                             command=self._refresh_preset_summary)
        self.chk_unet_only.pack(side="left")
        self.btn_reset_preset = ctk.CTkButton(cb, text="↺ 恢复预设", width=92, height=26, fg_color="transparent",
                                              hover_color="#343a46", border_width=1, border_color=BORDER,
                                              text_color=HINT, corner_radius=6, font=ui_font(FONT_HINT),
                                              command=self.cmd_reset_presets)
        self.btn_reset_preset.pack(side="left", padx=(20, 0))
        ow = ctk.CTkFrame(self.adv_body, fg_color="transparent"); ow.pack(anchor="w", pady=(6, 0))
        ctk.CTkLabel(ow, text="优化器", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        self.optimizer_var = tk.StringVar(value="自动")
        try:
            self.optimizer_var.trace_add("write", lambda *a: self._schedule_autosave())
        except Exception:
            pass
        self.optimizer_menu = ctk.CTkOptionMenu(
            ow, variable=self.optimizer_var,
            values=["自动", "AdamW", "Lion", "AdamW8bit"], width=130, height=26,
            fg_color=CARD2, button_color=CARD2, button_hover_color="#3a4150",
            text_color=SUB, font=ui_font(FONT_HINT), dropdown_font=ui_font(FONT_HINT),
            dropdown_fg_color=CARD2, dropdown_hover_color="#3a4150")
        self.optimizer_menu.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(ow, text="（自动=按环境预检选 AdamW8bit 或降级；若报 bitsandbytes 崩溃，改选 AdamW/Lion）",
                     font=ui_font(FONT_HINT), text_color=HINT).pack(side="left", padx=(10, 0))
        qw = ctk.CTkFrame(self.adv_body, fg_color="transparent"); qw.pack(anchor="w", pady=(6, 0))
        ctk.CTkLabel(qw, text="量化方式（Krea2/FLUX.2）", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        self.quant_var = tk.StringVar(value="自动")
        try:
            self.quant_var.trace_add("write", lambda *a: self._schedule_autosave())
        except Exception:
            pass
        self.quant_menu = ctk.CTkOptionMenu(
            qw, variable=self.quant_var,
            values=["自动", "fp8", "int8", "nf4"], width=130, height=26,
            fg_color=CARD2, button_color=CARD2, button_hover_color="#3a4150",
            text_color=SUB, font=ui_font(FONT_HINT), dropdown_font=ui_font(FONT_HINT),
            dropdown_fg_color=CARD2, dropdown_hover_color="#3a4150")
        self.quant_menu.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(qw, text="（自动=16G 及以上 fp8、8~12G int8；fp8 为 musubi 官方/社区 16G 主流，int8 适合带宽紧张的低显存）",
                     font=ui_font(FONT_HINT), text_color=HINT).pack(side="left", padx=(10, 0))
        bw = ctk.CTkFrame(self.adv_body, fg_color="transparent"); bw.pack(anchor="w", pady=(6, 0))
        ctk.CTkLabel(bw, text="块交换数（Krea2/FLUX.2）", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        self.swap_var = tk.StringVar(value="自动")
        try:
            self.swap_var.trace_add("write", lambda *a: self._schedule_autosave())
        except Exception:
            pass
        self.swap_menu = ctk.CTkOptionMenu(
            bw, variable=self.swap_var,
            values=["自动", "0", "2", "4", "6", "8", "10", "12"], width=130, height=26,
            fg_color=CARD2, button_color=CARD2, button_hover_color="#3a4150",
            text_color=SUB, font=ui_font(FONT_HINT), dropdown_font=ui_font(FONT_HINT),
            dropdown_fg_color=CARD2, dropdown_hover_color="#3a4150")
        self.swap_menu.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(bw, text="（自动=按显存档位；0=全部驻留显存；块越少越快但越吃显存）",
                     font=ui_font(FONT_HINT), text_color=HINT).pack(side="left", padx=(10, 0))
        cc = ctk.CTkFrame(self.adv_body, fg_color="transparent"); cc.pack(anchor="w", pady=(4, 0))
        self.compile_row = cc
        self.compile_var = tk.BooleanVar(value=False)
        try:
            self.compile_var.trace_add("write", lambda *a: self._schedule_autosave())
        except Exception:
            pass
        self.chk_compile = ctk.CTkCheckBox(cc, text="torch.compile 加速（实验性，Krea2/FLUX.2）",
                                           variable=self.compile_var, fg_color=ACC, hover_color=ACC_H,
                                           text_color=TXT, font=ui_font(FONT_HINT))
        self.chk_compile.pack(side="left")
        ctk.CTkLabel(cc, text="（musubi 编译 28 个块提速；16G 卡建议配合关闭采样预览；Windows 下可能编译失败，慎开）",
                     font=ui_font(FONT_HINT), text_color=HINT).pack(side="left", padx=(10, 0))
        self.global_frame = ctk.CTkFrame(self.adv_body, fg_color="transparent")
        self.global_frame.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(self.global_frame, text="附加全局提示词（可选，训练时自动加到标签最前面，不写入图片 txt）",
                     font=ui_font(FONT_HINT), text_color=HINT).pack(anchor="w")
        gr = ctk.CTkFrame(self.global_frame, fg_color="transparent"); gr.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(gr, text="正向", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        self.global_pos_entry = ctk.CTkEntry(gr, width=320, height=28, textvariable=self.global_pos_var, fg_color=CARD2,
                                             border_color=BORDER, text_color=TXT, font=ui_font(FONT_BODY))
        self.global_pos_entry.pack(side="left", padx=(8, 14))
        ctk.CTkLabel(gr, text="负向", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        self.global_neg_entry = ctk.CTkEntry(gr, width=320, height=28, textvariable=self.global_neg_var, fg_color=CARD2,
                                             border_color=BORDER, text_color=TXT, font=ui_font(FONT_BODY))
        self.global_neg_entry.pack(side="left", padx=(8, 0))
        self._attach_adv_tooltips()

    def _apply_style_preset(self, val):
        if val in STYLE_PRESETS:
            for k, v in STYLE_PRESETS[val].items():
                self.param_vars.setdefault(k, tk.StringVar()).set(v)
                self._manual_override.add(k)
            self._log(f"[预设] 已应用「{val}」风格参数（rank/alpha/学习率/repeats/epochs）")
            self._refresh_preset_summary()
        else:
            self._log("[预设] 自定义：参数保持当前值，可手动微调")

    def cmd_reset_presets(self):
        self._manual_override.clear()
        self._apply_presets()
        self._log("已恢复当前模式+底模的全部预设参数")

    # ============ 停止当前任务 ============
    def cmd_stop(self):
        """一键停止当前任务：终止正在运行的训练/预处理/安装进程。"""
        if not self.busy:
            return
        if not messagebox.askyesno(
                core.APP_NAME,
                "确定要停止当前任务吗？\n\n"
                "· 训练中途停止：进度快照已保留，下次运行会自动询问是否断点续训\n"
                "· 预处理/安装中途停止：已完成的文件会保留\n\n是否停止？"):
            return
        self._log("[停止] 正在请求停止当前任务…")
        try:
            core.stop_active_process()
        except Exception as e:
            self._log(f"[停止] 请求失败：{e}")

    # ============ 悬停提示 ============
    def _tip(self, widget, text):
        if widget is not None and text:
            try:
                Tooltip(widget, text)
            except Exception:
                pass

    def _attach_tooltips(self):
        """悬停提示：只绑顶部/侧边栏（主卡片提示在 _ensure_main_cards 后补绑，避免启动时引用未构建的控件）。"""
        tips = [
            (getattr(self, "mode_combo", None), "训练模式：🎨画风=只学绘画风格（不学脸/角色）；👤人物=学某个角色的脸、服饰、特征。切换会自动填好推荐参数。"),
            (getattr(self, "base_combo", None), "底模架构：SD1.5/SDXL 是经典架构；FLUX.1 画质新但非常吃显存（8G 不推荐）；Anima 是 2026 最新架构、显存友好。点「选择底模文件」选完会自动识别。"),
            (getattr(self, "btn_pick_base", None), "手动浏览选择本机的 .safetensors / .ckpt 底模；选完自动识别类型。"),
            (getattr(self, "btn_refresh_base", None), "重新扫描默认模型文件夹，把新放入的底模列进下拉。"),
            (getattr(self, "btn_download_base", None), "没有底模？点这里选下载方式：推荐「应用内下载」（软件里直接下载，带进度/断点续传/下完自动识别）。"),
            (getattr(self, "btn_one_click", None), "小白专用：自动过滤模糊/过小/损坏图 → 正方形裁剪 → 去重 → 打标签 → 开始训练，全程不用管。"),
            (getattr(self, "btn_stop", None), "任务进行中（训练/预处理/安装）可用：立即终止当前进程。训练中断后进度快照会保留，下次可断点续训。"),
            (getattr(self, "btn_krea2_models", None), "打开 Krea2 模型文件夹（models/krea2），把 RAW/VAE/文本编码器 3 个文件放进去；软件内提供国内镜像下载链接。"),
            (getattr(self, "btn_krea2_guide", None), "打开 Krea2 训练详细逐步引导（装环境→下模型→选图→预处理→训练→出图，含常见问题）。"),
            (getattr(self, "btn_h3_models", None), "打开 MiniMax H3 模型文件夹（models/minimax_h3），把下载的 DiT/文本编码器/VAE 文件放进去。"),
            (getattr(self, "btn_h3_dl", None), "应用内下载 H3 模型（约 40GB，带进度/断点续传，下完自动识别）。"),
            (getattr(self, "btn_at_install", None), "安装第三训练引擎（AI Toolkit）：MiniMax H3 视频 LoRA 专用，独立环境，不影响其他模式。"),
            (getattr(self, "btn_h3_captions", None), "为没有字幕的视频生成占位 txt（内容=触发词），避免训练缺字幕报错；建议之后手动改成具体描述。"),
            (getattr(self, "btn_h3_caption_ai", None), "用 Qwen2.5-VL 自动给视频生成英文描述（首次下载模型约 6~7GB，已有 txt 的会跳过）。"),
            (getattr(self, "btn_h3_guide", None), "打开 MiniMax H3 视频 LoRA 训练详细引导（装引擎→下模型→准备视频→训练→出视频）。"),
            (getattr(self, "btn_at_install", None), "安装第三引擎 AI Toolkit（Qwen-Image / Z-Image 模式需要）。"),
            (getattr(self, "btn_at_model_help", None), "查看模型与显存说明：Qwen-Image 16G 起步/24G 舒服，Z-Image 12G 起步/16G 舒服。"),
        ]
        for w, t in tips:
            self._tip(w, t)
        if hasattr(self, "amd_sw"):
            self._tip(self.amd_sw, "AMD 兼容模式（实验性）：开启后训练自动改用 sdpa + bf16 + AdamW，并做环境检查。第一次用请先点「环境检查 / 安装引导」。")
        if hasattr(self, "btn_amd_env"):
            self._tip(self.btn_amd_env, "检查 AMD 训练环境是否就绪，并打开详细安装引导（驱动 / Python / ROCm / PyTorch 一步步教你装）。")
        if hasattr(self, "train_env_entry"):
            self._tip(self.train_env_entry, "AMD 官方 ROCm 版 PyTorch 需要 Python 3.12，所以要新建一个训练环境，把它的文件夹路径填在这里（留空=用默认 kohya 环境）。")

    def _attach_main_tooltips(self):
        """主卡片构建完成后补绑悬停提示。"""
        tips = [
            (getattr(self, "raw_entry", None), "放原始图片的文件夹（支持 jpg/png/webp/bmp/tif/gif）。"),
            (getattr(self, "btn_pick_raw", None), "选择原始图片文件夹。"),
            (getattr(self, "trigger_entry", None), "触发词=模型的“召唤词”：人物模式=角色名；画风模式=画风专属词。训练后画图写上它就能唤出角色/画风。支持多个，用英文逗号分隔。"),
            (getattr(self, "reg_entry", None), "正则图：同一角色的参考图文件夹，训练时防止模型学过头（可选）。"),
            (getattr(self, "btn_pick_reg", None), "选择正则数据集文件夹（人物模式可选）。"),
        ]
        for w, t in tips:
            self._tip(w, t)
        for name, btn in getattr(self, "_main_btns", {}).items():
            self._tip(btn, _MAIN_BTN_TIPS.get(name))

    def _attach_adv_tooltips(self):
        for key, entry in getattr(self, "_adv_entries", {}).items():
            tip = core.PARAM_TIPS.get(key)
            if tip:
                self._tip(entry, tip)
        self._tip(self.style_preset_menu, "一键填入常用数值：动漫偏精细、写实偏自然；选完仍可手动微调。")
        self._tip(self.chk_unet_only, "只训练 UNet（不训练文本编码器）：更省显存、更稳，画风类可以勾选。")
        self._tip(self.btn_reset_preset, "把当前模式+底模的所有参数恢复成推荐预设（手动改过的会被重置）。")
        self._tip(self.global_pos_entry, "附加全局正向提示词：训练时自动加到每张图片标签最前面（例如 masterpiece），不写进图片的 txt 文件，可留空。")
        self._tip(self.global_neg_entry, "附加全局负向提示词：会写进使用模板和参数报告；kohya 训练本身不使用负向提示词，可留空。")

    # ============ 参数收集 ============
    def _collect_params(self):
        def _getv(key, default=""):
            try:
                return self.param_vars[key].get().strip() or default
            except Exception:
                return default
        return {
            "mode": self.mode,
            "base_type": self.base_type,
            "at_sub_mode": self._at_sub_label(),
            "fast_tier": (core.fast_tier_code(self.fast_tier_var.get())
                          if getattr(self, "fast_tier_var", None) is not None else "auto"),
            "trigger": self.trigger_var.get().strip(),
            "strong_bind": bool(self.strong_bind_var.get()),
            "sample_preview": bool(self.sample_preview_var.get()),
            "sample_prompt": self.sample_prompt_var.get().strip(),
            "crop_ratio": _crop_ratio_parse(self.crop_ratio_var.get()),
            "reg_dir": self.reg_var.get().strip() or None,
            "raw_dir": self.raw_dir_var.get().strip(),
            "base_model": self.base_model_var.get().strip() or None,
            "rank": int(float(_getv("rank", "12"))),
            "alpha": int(float(_getv("alpha", "6"))),
            "unet_lr": float(_getv("unet_lr", "3e-4")),
            "te_lr": float(_getv("te_lr", "1.5e-4")),
            "repeats": int(float(_getv("repeats", "5"))),
            "max_epochs": int(float(_getv("max_epochs", "8"))),
            "resolution": int(float(_getv("resolution", "1024" if self.mode in ("krea2", "krea2_fz", "krea2_at", "flux2") else str(core.RESOLUTIONS.get(self.base_type, 512))))),
            "video_steps": int(float(_getv("video_steps", "2000"))),
            "save_every": (lambda _s: int(_s) if str(_s).isdigit() else None)(_getv("save_every", "")),
            "train_text_encoder": not self.unet_only_var.get(),
            "style_caption": getattr(self, "style_caption_var", tk.StringVar()).get().strip(),
            "global_pos": self.global_pos_var.get().strip(),
            "global_neg": self.global_neg_var.get().strip(),
            "amd_mode": bool(self.amd_var.get()),
            "train_env": self.train_env_var.get().strip() or None,
            "optimizer": (_OPT_GUI_MAP.get(self.optimizer_var.get()) if hasattr(self, "optimizer_var") else "auto"),
            "quant_mode": (_QUANT_GUI_MAP.get(self.quant_var.get()) if hasattr(self, "quant_var") else "auto"),
            "blocks_to_swap": (self.swap_var.get() if (hasattr(self, "swap_var") and str(self.swap_var.get()).isdigit()) else ""),
            "compile": ("1" if (hasattr(self, "compile_var") and self.compile_var.get()) else ""),
        }

    def _maybe_migrate_legacy_dataset(self, name):
        """打开项目时：若本项目还没有数据集，而旧版共享数据集里有图，询问是否导入。"""
        try:
            legacy = core.dataset_train_dir(self.mode)          # 旧版共享目录
            target = core.dataset_train_dir(self.mode, name)
            n_legacy = core.count_images(legacy)
            n_target = core.count_images(target)
        except Exception:
            return
        if n_target > 0 or n_legacy == 0:
            return
        if messagebox.askyesno(core.APP_NAME,
                f"检测到旧版共享数据集里还有 {n_legacy} 张图片。\n\n"
                f"是否把它们导入到当前项目「{name}」？（以后每个项目的数据都是独立的，不会互相混用）"):
            try:
                t2, migrated = core.migrate_legacy_dataset(name, self.mode)
                n2 = core.count_images(t2)
                if migrated:
                    self._log(f"[数据集] 已把旧版共享数据集导入当前项目（{n2} 张图）：{t2}")
                    messagebox.showinfo(core.APP_NAME, f"已导入 {n2} 张图片到当前项目「{name}」。")
            except Exception as e:
                self._log(f"[数据集] 导入失败（忽略）: {e}")

    # ============ 标签编辑器 ============
    def cmd_label_editor(self):
        """打开标签编辑器（浏览/修改/批量操作/统计/整理数据集）。"""
        try:
            if self._collect_params().get("mode") == "video":
                messagebox.showinfo(core.APP_NAME,
                                    "视频模式没有「标签编辑器」。\n\n"
                                    "视频的字幕是视频文件夹里的同名 .txt（如 myvideo.mp4 + myvideo.txt），\n"
                                    "直接用记事本打开修改即可；也可用「一键生成占位字幕」或「AI 视频自动打标」。")
                return
            if self._label_editor is not None:
                try:
                    self._label_editor.win.lift()
                    self._label_editor.win.focus_force()
                    return
                except Exception:
                    self._label_editor = None
            params = self._collect_params()
            params["project"] = self.current_project or ""
            self._label_editor = LabelEditorWindow(self.root, self, params)
        except Exception as e:
            self._log(f"[ERROR] 打开标签编辑器失败：{e}")
            traceback.print_exc()

    def cmd_open_flux2_models(self):
        d = core.flux2_models_dir()
        try:
            os.makedirs(d, exist_ok=True)
            os.startfile(d)
        except Exception as e:
            messagebox.showerror(core.APP_NAME, f"打开失败：{e}")

    def _show_flux2_guide(self):
        """FLUX.2 图像 LoRA 训练 · 详细逐步引导（小白版）。"""
        w = ctk.CTkToplevel(self.root)
        w.title("FLUX.2 图像 LoRA · 使用引导")
        w.geometry("780x800")
        w.transient(self.root)
        txt = ctk.CTkTextbox(w, fg_color="#16181e", text_color="#c6ccd8", corner_radius=8,
                             border_width=1, border_color=BORDER, font=ui_font(FONT_BODY), wrap="word")
        txt.pack(fill="both", expand=True, padx=18, pady=18)
        f2 = core.FLUX2_MODEL_LINKS
        guide = (
            "📖 FLUX.2 图像 LoRA 训练 · 详细引导（小白版）\n\n"
            "▍原理一句话\n"
            "FLUX.2 klein 是 2026 最新架构（4B DiT + Qwen3 文本编码器）。用 15~30 张图就能训出「你的角色/风格」LoRA。\n"
            "训练用 base 4B 底模，训完的 LoRA 可用于 FLUX.2 klein 系列出图。\n\n"
            "▍第 1 步：安装第二引擎\n"
            "· 左侧点「②' 第二引擎(可选)」→「去安装」\n"
            "· 自动创建独立环境（完全不影响现有画风/人物训练）\n"
            "· 下载 PyTorch 约 2.5GB，10~30 分钟（国内镜像，断了自动续传）\n"
            "· 装完绿点变「已装」\n\n"
            "▍第 2 步：下载 FLUX.2 模型（3 个文件，放进 models/flux2/，共约 16GB）\n"
            f"1) {f2['dit'][0]} —— {f2['dit'][1]}\n"
            f"   国内镜像：{f2['dit'][2]}\n"
            f"2) {f2['te'][0]} —— {f2['te'][1]}\n"
            f"   国内镜像：{f2['te'][2]}\n"
            f"3) {f2['vae'][0]} —— {f2['vae'][1]}\n"
            f"   国内镜像：{f2['vae'][2]}\n"
            "· 点「⬇ 下载 FLUX.2 模型」应用内下载（断点续传、下完自动识别），或点「📂 打开 FLUX.2 模型文件夹」手动放文件\n"
            "· 顶部状态变成「FLUX.2 模型：齐全 ✓」即可\n\n"
            "▍第 3 步：打开项目，切到 FLUX.2 模式\n"
            "· 顶部训练模式选「🖼 FLUX.2 图像LoRA」\n"
            "· 自动填好推荐参数（rank32 / alpha32 / lr 1e-4 / epochs16）\n\n"
            "▍第 4 步：准备数据 + 一键训练\n"
            "· 选 15~30 张同一人物/风格的图片文件夹，点「④ 数据预处理」\n"
            "· 填一个唯一的英文触发词（如 my_f2_01）\n"
            "· 点下方「一键开始训练」：自动缓存 latents → 缓存文本编码器 → 训练\n"
            "· 8G 显存自动开 fp8 + blocks_to_swap 省显存（较慢），推荐 12G+\n\n"
            "▍出图\n"
            "训练完成后模型在 output 文件夹，配 FLUX.2 klein 底模 + LoRA（权重 0.6~0.9）使用。\n"
        )
        txt.insert("1.0", guide)
        txt.configure(state="disabled")

    def cmd_dl_flux2_models(self):
        """FLUX.2 模型下载对话框：DiT+文本编码器+VAE，应用内下载（断点续传）。"""
        self._build_links_dialog(
            "下载 FLUX.2 模型",
            "FLUX.2 训练需要以下文件（共约 16GB，应用内下载带断点续传、断了接着下）：",
            core.FLUX2_MODEL_LINKS, core.flux2_model_files(),
            "📂 打开 FLUX.2 模型文件夹", self.cmd_open_flux2_models, self.cmd_dl_flux2_models,
            self._start_flux2_dl, "保存到 models/flux2/，下完自动识别（顶部状态变「齐全 ✓」）。")

    def _start_flux2_dl(self, key):
        self._start_model_file_dl(key, core.FLUX2_MODEL_LINKS, core.flux2_models_dir(), "flux2", "FLUX.2 模型")

    def _refresh_flux2_status(self):
        """FLUX.2 模型状态（顶部状态行）。"""
        try:
            _files = core.flux2_model_files()
            _short = {"dit": "DiT", "te": "文本编码器", "vae": "VAE"}
            _miss = "、".join(_short[k] for k in ("dit", "te", "vae") if not _files.get(k))
            self.flux2_model_var.set(("FLUX.2 模型：缺 " + _miss + "（点⬇应用内下载）") if _miss else "FLUX.2 模型：齐全 ✓")
        except Exception:
            pass

    def cmd_open_krea2_models(self):
        d = core.krea2_models_dir()
        try:
            os.makedirs(d, exist_ok=True)
            os.startfile(d)
        except Exception as e:
            messagebox.showerror(core.APP_NAME, f"打开失败：{e}")

    def _show_krea2_guide(self):
        """Krea2 图像 LoRA 训练 · 详细逐步引导（小白版）。"""
        w = ctk.CTkToplevel(self.root)
        w.title("Krea 2 图像 LoRA · 使用引导")
        w.geometry("760x760")
        w.transient(self.root)
        txt = ctk.CTkTextbox(w, fg_color="#16181e", text_color="#c6ccd8", corner_radius=8,
                             border_width=1, border_color=BORDER, font=ui_font(FONT_BODY), wrap="word")
        txt.pack(fill="both", expand=True, padx=18, pady=18)
        k2 = core.KREA2_MODEL_LINKS
        guide = (
            "📖 Krea 2 图像 LoRA 训练 · 详细引导（小白版）\n\n"
            "▍原理一句话\n"
            "Krea 2 是 12.9B 大模型，用 15~30 张图就能训出「你的角色/风格」LoRA。\n"
            "训练用 RAW 底模，训完的 LoRA 可用于 Krea 2（含 Turbo）出图。\n\n"
            "▍第 1 步：安装第二引擎\n"
            "· 左侧点「②' 第二引擎(可选)」→「去安装」\n"
            "· 自动创建独立环境（完全不影响现有画风/人物训练）\n"
            "· 下载 PyTorch 约 2.5GB，10~30 分钟（国内镜像，断了自动续传）\n"
            "· 装完绿点变「已装」\n\n"
            "▍第 2 步：下载 Krea 2 模型（3 个文件，放进 models/krea2/）\n"
            f"1) {k2['raw'][0]} —— {k2['raw'][1]}\n"
            f"   国内镜像：{k2['raw'][2]}\n"
            f"2) {k2['vae'][0]} —— {k2['vae'][1]}\n"
            f"   国内镜像：{k2['vae'][2]}\n"
            f"3) {k2['te'][0]} —— {k2['te'][1]}\n"
            f"   国内镜像：{k2['te'][2]}\n"
            "· 点「⬇ 下载 Krea2 模型」应用内下载（断点续传、下完自动识别），或点「📂 打开 Krea2 模型文件夹」手动放文件\n"
            "· 顶部状态变成「Krea2 模型：齐全 ✓」即可\n\n"
            "▍第 3 步：打开项目，切到 Krea2 模式\n"
            "· 顶部训练模式选「🖼 Krea 2 图像LoRA」\n"
            "· 自动填好推荐参数（rank32 / alpha32 / 学习率1e-4 / 1024px / repeats2）\n\n"
            "▍第 4 步：准备图片\n"
            "· 人物：15~30 张同一人物，多角度、不同服装\n"
            "· 风格：20~60 张同一风格\n"
            "· 建议 1024px 清晰大图；模糊/过小/重复图会自动过滤\n"
            "· 填一个 Trigger 触发词（网上少见的英文词，如 my_k2_01）\n\n"
            "▍第 5 步：预处理 + 一键训练\n"
            "· 点「🚀 一键开始训练」：自动 过滤→裁切→去重→WD14 打标→训练\n"
            "· 显存：推荐 16G（最低 12G）；自动开 fp8 + block swap 省显存\n"
            "· 自动约束步数防过拟合；每轮保存 checkpoint，可挑最优权重\n\n"
            "▍第 6 步：训练完成\n"
            "· 模型在 output\\<项目名>\\krea2_lora.safetensors\n"
            "· 该 LoRA 用于 Krea 2 底模（含 Turbo）出图，正向提示词以 Trigger 开头\n\n"
            "❓ 常见问题\n"
            "Q: 显存不够 OOM？\n"
            "A: 工具会自动开 fp8 + block swap；12G 以下不建议训练（只能预处理/看界面）。\n\n"
            "Q: 下载慢/老断？\n"
            "A: 内置断点续传，断了自动接着下；模型走国内镜像，不要挂代理反而更快。\n\n"
            "Q: 效果过拟合（只会复刻原图）？\n"
            "A: 减少 repeats 或 epochs，或减少图片数量；用中间的 checkpoint 挑效果最好的。\n\n"
            "Q: 为什么训练用 RAW 不是 Turbo？\n"
            "A: 官方推荐「Train on RAW → Run on Turbo」：RAW 泛化好，训完的 LoRA 在 Turbo 上出图又快又稳。\n"
        )
        txt.insert("1.0", guide)
        txt.configure(state="disabled")

    def cmd_open_h3_models(self):
        d = core.h3_models_dir()
        try:
            os.makedirs(d, exist_ok=True)
            os.startfile(d)
        except Exception as e:
            messagebox.showerror(core.APP_NAME, f"打开失败：{e}")

    def cmd_install_fizgig(self):
        """安装第四训练引擎（Fizgig：Krea2 图像 LoRA，NVIDIA/AMD 双平台）。"""
        if self.busy:
            messagebox.showinfo(core.APP_NAME, "有任务正在运行，请先等待当前任务完成。")
            return
        if not messagebox.askyesno(core.APP_NAME,
                "安装第四训练引擎（Fizgig · Krea2 图像 LoRA）？\n\n"
                "· 独立环境，完全不影响现有引擎\n"
                "· NVIDIA 显卡走 CUDA 路径（torch cu128 约 2.9GB，国内镜像断点续传）\n"
                "· AMD 显卡走 ROCm 路径（AMD nightly 钉死版本）\n"
                "· Krea2 模型与第二/三引擎共用 models/krea2/\n\n是否开始安装？"):
            return
        self._start_worker(self._install_fizgig_worker, "安装第四引擎")

    def _install_fizgig_worker(self):
        try:
            core.install_fizgig_engine(self._log)
            core.clear_status_cache()
            self.q.put(("STATUS",))
        except Exception as e:
            self._log(f"[ERROR] 第四引擎安装失败：{e}")
            traceback.print_exc()
        finally:
            self.q.put("__DONE__")

    def cmd_import_at_env(self):
        """导入已装好的第三引擎（AI Toolkit）环境：选择源码目录或根目录，软件直接复用，不用重新部署。"""
        cur = core.at_custom_dir() or ""
        if cur and not messagebox.askyesno(core.APP_NAME,
                f"当前已导入自定义环境：\n{cur}\n\n是否清除并重新选择？"):
            return
        d = filedialog.askdirectory(
            title="选择已装好的 AI Toolkit 文件夹（含 run.py 的源码目录，或含 ai-toolkit 子目录的根目录）",
            initialdir=cur or os.path.expanduser("~"))
        if not d:
            return
        _d = dict(core._load_app_settings())
        _d["at_dir"] = d
        core._save_app_settings(_d)
        core.clear_status_cache()
        ok, detail, _vp = core.ai_toolkit_engine_status()
        if ok:
            self._log(f"[第三引擎] 已导入自定义环境并检测可用：{d}")
            messagebox.showinfo(core.APP_NAME,
                                f"✅ 已检测到装好的第三引擎环境可用：\n{d}\n\n无需重新部署，可直接训练。")
        else:
            self._log(f"[第三引擎] 已记录自定义目录，但环境不完整：{detail}")
            messagebox.showwarning(core.APP_NAME,
                                   f"已记录目录：{d}\n但未检测到完整环境（{detail}）。\n\n"
                                   "请确认该目录里有：\n· ai-toolkit 源码（含 run.py）\n· venv（ai_toolkit_venv 或 venv，含 python.exe）\n\n"
                                   "也可以点「📂 导入已装环境」重新选择，或点「⚙ 安装第三引擎」走标准安装。")
        self.q.put(("STATUS",))

    def cmd_install_at(self):
        """安装第三训练引擎（AI Toolkit · MiniMax H3 视频 LoRA）。"""
        if self.busy:
            messagebox.showinfo(core.APP_NAME, "有任务正在运行，请先等待当前任务完成。")
            return
        if not messagebox.askyesno(core.APP_NAME,
                "安装第三训练引擎（AI Toolkit · MiniMax H3 视频 LoRA）？\n\n"
                "· 独立环境，完全不影响现有画风/人物/Krea2 训练\n"
                "· 需下载 PyTorch cu130（约 3GB，需较新 NVIDIA 驱动）\n"
                "· H3 模型 40GB+ 按需另行下载（国内镜像）\n\n是否开始安装？"):
            return
        self._start_worker(self._install_at_worker, "安装第三引擎")

    def _install_at_worker(self):
        try:
            core.install_ai_toolkit_engine(self._log)
            core.clear_status_cache()
            self.q.put(("STATUS",))
        except Exception as e:
            self._log(f"[ERROR] 第三引擎安装失败：{e}")
            traceback.print_exc()
        finally:
            self.q.put("__DONE__")

    def cmd_gen_h3_captions(self):
        """为无字幕视频生成占位字幕（内容=触发词或 a video）。"""
        params = self._collect_params()
        d = params.get("raw_dir") or ""
        if not d or not os.path.isdir(d):
            messagebox.showwarning(core.APP_NAME, "请先选择视频数据集文件夹。")
            return
        n = core.h3_generate_placeholder_captions(d, params.get("trigger") or "", self._log)
        if n:
            messagebox.showinfo(core.APP_NAME,
                                f"已为 {n} 个视频生成占位字幕（内容=触发词或 a video）。\n建议手动打开 txt 改成更具体的画面描述（英文效果更好）。")
        else:
            messagebox.showinfo(core.APP_NAME, "所有视频都已有同名 txt 字幕，无需生成。")

    def cmd_video_caption(self):
        """用 Qwen2.5-VL 给视频自动生成英文描述（写同名 txt）。"""
        params = self._collect_params()
        d = params.get("raw_dir") or ""
        if not d or not os.path.isdir(d):
            messagebox.showwarning(core.APP_NAME, "请先选择视频数据集文件夹。")
            return
        videos, _t, _n = core.scan_video_dataset(d)
        if not videos:
            messagebox.showwarning(core.APP_NAME, "视频文件夹里没有找到视频。")
            return
        if self.busy:
            messagebox.showinfo(core.APP_NAME, "有任务正在运行，请先等待当前任务完成。")
            return
        if not messagebox.askyesno(core.APP_NAME,
                "用 Qwen2.5-VL 给视频自动生成英文描述？\n\n"
                "· 首次使用会下载打标模型（约 6~7GB，国内镜像）\n"
                "· 已有 txt 的视频会跳过（不覆盖手写描述）\n"
                "· 需要 4G+ 显存（N 卡优先；没有会回退 CPU，较慢）\n\n是否开始？"):
            return
        params = self._collect_params()
        self._start_worker(lambda: self._video_caption_worker(params), "视频自动打标")

    def _video_caption_worker(self, params):
        core.reset_stop()
        try:
            core.run_video_caption(self._log, video_dir=params["raw_dir"],
                                   trigger=params.get("trigger") or "", frames=6)
            self._log("[OK] 视频自动打标完成")
        except core.StopRequested:
            self._log("[停止] 打标已手动停止")
        except Exception as e:
            self._log(f"[ERROR] 视频自动打标失败：{e}")
            traceback.print_exc()
        finally:
            self.q.put("__DONE__")

    def _refresh_at_status(self):
        try:
            info = core.AT_IMAGE_MODELS.get(self.mode, {})
            ok_e = core.ai_toolkit_engine_status()[0]
            ok_m = core.at_image_model_ready(self.mode)
            label = info.get("label", "")
            if not ok_e:
                self.at_model_var.set(f"{label}：第三引擎未装（点⚙安装） · 模型：未下载")
            elif not ok_m:
                self.at_model_var.set(f"{label}：模型未下载（开始训练前自动预下载 {info.get('size','')}，hf-mirror，可续传）")
            else:
                self.at_model_var.set(f"{label}：模型已就绪 ✓")
        except Exception:
            pass

    def cmd_at_model_help(self):
        """Qwen-Image / Z-Image 模型与显存说明弹窗。"""
        info = core.AT_IMAGE_MODELS.get(self.mode, {})
        d = core.data_sub("models")  # 说明弹窗用
        msg = (
            f"📖 {info.get('label', '')} 说明\n\n"
            f"· 模型：{info.get('model_id', '')}（{info.get('size', '')}）\n"
            f"· 显存：{info.get('hint', '')}\n\n"
            "· 模型会在开始训练前自动预下载到数据目录（hf-mirror 国内直连、断点续传），无需手动下载。\n"
            "· 训练用基础版模型；出图可配合 Turbo 等加速版使用。\n\n"
            "· 训练数据：选 15~30 张同一人物/风格的图片，自动过滤/裁切/打标签。"
        )
        messagebox.showinfo(core.APP_NAME, msg)

    def _ensure_at_image_ready(self):
        """Qwen-Image / Z-Image 模式训练前检查：第三引擎已装 + 数据集有图。模型开始训练前自动预下载（hf-mirror 可续传）。"""
        try:
            ok, detail, _ = core.ai_toolkit_engine_status()
        except Exception as e:
            ok, detail = False, str(e)
        if not ok:
            messagebox.showwarning(core.APP_NAME,
                                   "第三训练引擎未安装。\n请点顶部「⚙ 安装第三引擎」安装。\n\n" + detail)
            return False
        vd = (self._collect_params().get("raw_dir") or "")
        if not vd or not os.path.isdir(vd):
            messagebox.showwarning(core.APP_NAME, "请先选择图片数据集文件夹。")
            return False
        return True

    def _ensure_video_ready(self):
        """视频模式训练前检查：第三引擎已装 + H3 模型齐全 + 数据集有视频与字幕。返回是否可继续。"""
        try:
            ok, detail, _ = core.ai_toolkit_engine_status()
        except Exception as e:
            ok, detail = False, str(e)
        if not ok:
            messagebox.showwarning(core.APP_NAME,
                                   "第三训练引擎未安装。\n请点顶部「⚙ 安装第三引擎」安装。\n\n" + detail)
            return False
        missing = core.h3_missing_models()
        if missing:
            d = core.h3_models_dir()
            if messagebox.askyesno(core.APP_NAME,
                    "MiniMax H3 还缺少模型文件，需要先下载放入 models/minimax_h3/：\n\n" + "\n".join(missing) +
                    f"\n\n模型文件夹：{d}\n\n是否现在打开该文件夹？（下载完成后把文件放进去）"):
                try:
                    os.makedirs(d, exist_ok=True)
                    os.startfile(d)
                except Exception:
                    pass
            return False
        vd = (self._collect_params().get("raw_dir") or "")
        videos, _t, no_cap = core.scan_video_dataset(vd)
        if not videos:
            messagebox.showwarning(core.APP_NAME, "请先选择视频数据集文件夹（放 .mp4 + 同名 .txt 字幕）。")
            return False
        if no_cap == len(videos):
            messagebox.showwarning(core.APP_NAME,
                                   "所有视频都没有同名 .txt 字幕。\n\n每个视频需要一个同名 txt 描述内容（如 myvideo.mp4 + myvideo.txt）。\n"
                                   "可以点「一键生成占位字幕」先用触发词顶上。")
            return False
        return True

    def _refresh_h3_status(self):
        try:
            ok, detail, _ = core.ai_toolkit_engine_status()
            _files = core.h3_model_files()
            _miss_parts = []
            if not (_files.get("dit") or _files.get("dit_nvfp4")):
                _miss_parts.append("dit")
            for k in ("te", "video_vae"):
                if not _files.get(k):
                    _miss_parts.append(k)
            _miss = "、".join(_miss_parts)
            if not ok:
                self.h3_model_var.set("第三引擎：未装（点⚙安装） · H3 模型：" + ("缺 " + _miss if _miss else "齐全"))
            elif _miss:
                self.h3_model_var.set("H3 模型：缺 " + _miss + "（点📂查看文件名/镜像）")
            else:
                self.h3_model_var.set("H3 模型：齐全 ✓ 第三引擎：就绪")
        except Exception:
            pass

    def _show_h3_guide(self):
        """MiniMax H3 视频 LoRA 训练 · 详细逐步引导（小白版）。"""
        w = ctk.CTkToplevel(self.root)
        w.title("MiniMax H3 视频 LoRA · 使用引导")
        w.geometry("780x840")
        w.transient(self.root)
        txt = ctk.CTkTextbox(w, fg_color="#16181e", text_color="#c6ccd8", corner_radius=8,
                             border_width=1, border_color=BORDER, font=ui_font(FONT_BODY), wrap="word")
        txt.pack(fill="both", expand=True, padx=18, pady=18)
        h3 = core.H3_MODEL_LINKS
        guide = (
            "📖 MiniMax H3 视频 LoRA 训练 · 详细引导（小白版）\n\n"
            "▍原理一句话\n"
            "H3 是 33.1B 的全模态视频模型（视频+声音一起生成）。用几段短视频就能训出「你的角色/风格」视频 LoRA。\n"
            "⚠ 实验性功能：推荐 24G+ NVIDIA 显存；12~16G 用 nvfp4 主模型可跑（软件自动开低显存模式，较慢）；模型文件 40GB+，训练一次要数小时。\n\n"
            "▍第 1 步：安装第三引擎\n"
            "· 切到「🎬 视频LoRA（MiniMax H3）」模式 → 点「⚙ 安装第三引擎」\n"
            "· 自动创建独立环境（不影响现有画风/人物/Krea2）\n"
            "· 下载 PyTorch cu130 约 3GB；需较新 NVIDIA 驱动（570+）\n"
            "· 装完状态行变「第三引擎：就绪」\n\n"
            "▍第 2 步：下载 H3 模型（3~4 个文件，放进 models/minimax_h3/）\n"
            f"1) {h3['dit'][0]} —— {h3['dit'][1]}\n"
            f"   国内镜像：{h3['dit'][2]}\n"
            f"   （12~16G 显存建议用 nvfp4 版：{h3['dit_nvfp4'][0]}（约 11.7GB，更小更稳）\n"
            f"    下载：{h3['dit_nvfp4'][2]}）\n"
            f"2) {h3['te'][0]} —— {h3['te'][1]}\n"
            f"   国内镜像：{h3['te'][2]}\n"
            f"3) {h3['video_vae'][0]} —— {h3['video_vae'][1]}\n"
            f"   国内镜像：{h3['video_vae'][2]}\n"
            f"4)（可选）{h3['audio_vae'][0]} —— {h3['audio_vae'][1]}\n"
            f"   国内镜像：{h3['audio_vae'][2]}\n"
            "· 下完放进去，状态变「H3 模型：齐全 ✓」\n\n"
            "▍第 3 步：准备视频数据集\n"
            "· 新建一个文件夹，放 3~10 段 3~10 秒的同角色/同风格 mp4\n"
            "· 每个视频配一个同名 .txt 字幕（描述画面内容，英文效果最好）\n"
            "· 例：myvideo.mp4 + myvideo.txt（内容如：a girl with red hair walking in rain）\n"
            "· 没字幕可先点「一键生成占位字幕」用触发词顶上，再手动补\n\n"
            "▍第 4 步：训练\n"
            "· 顶部选「🎬 视频LoRA（MiniMax H3）」→ 选视频文件夹 → 填 Trigger 触发词\n"
            "· 点「🚀 一键开始训练」；首次要加载 30GB+ 模型，请耐心等待\n"
            "· 默认 2000 步，可改「训练步数」（上限 3000，防过拟合）\n\n"
            "▍第 5 步：训练完成\n"
            "· 模型在 output\\<项目名>\\ 下（.safetensors），并自动生成使用模板\n"
            "· 该 LoRA 只能用于 MiniMax H3 系列模型出视频\n\n"
            "❓ 常见问题\n"
            "Q: 显存不够？\n"
            "A: 12~16G 请下载 nvfp4 主模型（约 11.7GB，见第 2 步），软件自动开低显存模式（low_vram + 分层交换）能跑但会慢；24G+ 用 int8 主模型。\n\n"
            "Q: AMD 显卡能训吗？\n"
            "A: 不能。AI Toolkit 训练走 CUDA/NVFP4，是 NVIDIA 专属；AMD 用户请继续用画风/人物/Krea2 模式。\n\n"
            "Q: 下载慢/老断？\n"
            "A: 模型走国内镜像（hf-mirror），支持断点续传，断了接着下。\n\n"
            "Q: 训练完视频召唤不出来？\n"
            "A: 提示词以触发词开头；确认训练时字幕里带了触发词。\n\n"
            "⚠ 许可提醒：MiniMax H3 为社区许可证（开放权重），商用请自行确认条款。\n"
        )
        txt.insert("1.0", guide)
        txt.configure(state="disabled")

    # ============ 预处理 / 训练 ============
    def cmd_preprocess(self):
        params = self._collect_params()
        if not params["raw_dir"]:
            messagebox.showwarning(core.APP_NAME, "请先选择原始图片文件夹（步骤④）。")
            return
        self._start_worker(lambda: self._preprocess_worker(params), "数据预处理")

    def _preprocess_worker(self, params):
        core.reset_stop()
        try:
            report = os.path.join(os.environ.get("TEMP", "."), "kohya_auto_report.json")
            if params.get("mode") == "video":
                # 视频模式「数据预处理」只做检查提示，不自动进入训练（避免误触发训练流程）。
                videos, _t, no_cap = core.scan_video_dataset(params.get("raw_dir"))
                if not videos:
                    self._log("[预处理] 视频文件夹里没有找到视频，请先选择视频数据集文件夹。")
                else:
                    self._log(f"[预处理] 视频数据已就绪：{len(videos)} 个视频，{no_cap} 个缺字幕。"
                              "视频无需图片预处理；字幕请用「AI 视频自动打标」或放同名 .txt，然后直接点【一键训练】。")
                return
            pp_mode = core.preprocess_mode(params.get("mode"), params.get("at_sub_mode"))
            core.preprocess(
                self._log, input_dir=params["raw_dir"],
                size=int(params.get("resolution") or (core.KREA2_RESOLUTION if params.get("mode") in ("krea2", "krea2_fz", "krea2_at") else core.RESOLUTIONS.get(params["base_type"], 512))),
                mode=pp_mode, trigger=params["trigger"],
                reg_dir=params["reg_dir"], repeats=params["repeats"],
                dedup=True, wd14=True, square_crop=False, crop_ratio=params.get("crop_ratio") or "",
                min_size=256, blur_threshold=30.0, report=report,
                keep_tokens=None, project=self.current_project,
                style_caption=params.get("style_caption") or "",
                dataset_mode="character" if params.get("mode") != "style" else None,
                strong_bind=params.get("strong_bind", True))
            self._log("[OK] 预处理完成")
        except core.StopRequested:
            self._log("[停止] 预处理已手动停止")
        except Exception as e:
            self._log(f"[ERROR] 预处理失败：{e}")
            traceback.print_exc()
        finally:
            self.q.put("__DONE__")

    def cmd_train(self):
        params = self._collect_params()
        if params.get("mode") in ("qwen_image", "zimage"):
            if not self._ensure_at_image_ready():
                return
        elif params.get("mode") == "video":
            if not self._ensure_video_ready():
                return
        elif params.get("mode") == "krea2":
            if not self._ensure_krea2_ready():
                return
        elif params.get("mode") == "krea2_at":
            if not self._ensure_krea2_at_ready():
                return
        elif params.get("mode") == "krea2_fz":
            if not self._ensure_krea2_fz_ready():
                return
        else:
            if not params["base_model"]:
                messagebox.showwarning(core.APP_NAME, "请先选择底模（步骤③）。")
                return
        if not self._anima_merged_ok(params):
            return
        if not self._warn_no_nvidia():
            return
        if not self._warn_low_vram(params):
            return
        resume = self._ask_resume(params)
        if not self._confirm_training(params, resume):
            return
        self._start_worker(lambda: self._train_worker(params, resume), "一键训练")

    def _train_worker(self, params, resume=None):
        core.reset_stop()
        self._train_mon = core.TrainMonitor()
        self._show_monitor(True)
        try:
            vram = core.detect_vram_gb()
            params["project"] = self.current_project or ""
            if params.get("mode") in ("qwen_image", "zimage"):
                core.train_at_image(self._log, mode=params["mode"], params=params,
                                    vram_gb=vram, resume_from=resume, progress=self._train_mon)
            elif params.get("mode") == "video":
                core.train_video(self._log, mode="video", params=params,
                                 vram_gb=vram, resume_from=resume, progress=self._train_mon)
            elif params.get("mode") == "krea2":
                core.train_krea2(self._log, mode="krea2", params=params,
                                 vram_gb=vram, resume_from=resume, progress=self._train_mon)
            elif params.get("mode") == "krea2_at":
                core.train_krea2_at(self._log, mode="krea2_at", params=params,
                                    vram_gb=vram, resume_from=resume, progress=self._train_mon)
            elif params.get("mode") == "krea2_fz":
                core.train_krea2_fizgig(self._log, mode="krea2_fz", params=params,
                                        vram_gb=vram, resume_from=resume, progress=self._train_mon)
            elif params.get("mode") == "flux2":
                core.train_flux2(self._log, mode="flux2", params=params,
                                 vram_gb=vram, resume_from=resume, progress=self._train_mon)
            else:
                core.train(self._log, base_model=params["base_model"], mode=params["mode"],
                           params=params, vram_gb=vram, resume_from=resume, progress=self._train_mon)
            self._log("[OK] 训练完成，模型在 output 文件夹")
        except core.StopRequested:
            if getattr(self._train_mon, "nan_detected", False):
                self._log("[停止] 检测到训练 loss 为 NaN/Inf（数值异常），已自动停止，避免卡在保存。"
                         "常见原因：AMD RDNA2（RX 6000）+ bf16、模型/数据问题。请更新到最新版或检查数据。")
            else:
                self._log("[停止] 训练已手动停止，进度快照已保留，下次可断点续训")
        except Exception as e:
            self._log(f"[ERROR] 训练失败：{e}")
            traceback.print_exc()
        finally:
            try:
                self._train_mon.finish()
            except Exception:
                pass
            self._show_monitor(False)
            self.q.put("__DONE__")

    def cmd_one_click_train(self):
        params = self._collect_params()
        if not params["raw_dir"]:
            messagebox.showwarning(core.APP_NAME, "请先选择原始图片/视频文件夹（步骤④）。")
            return
        if params.get("mode") in ("qwen_image", "zimage"):
            if not self._ensure_at_image_ready():
                return
        elif params.get("mode") == "video":
            if not self._ensure_video_ready():
                return
        elif params.get("mode") == "krea2":
            if not self._ensure_krea2_ready():
                return
        elif params.get("mode") == "krea2_at":
            if not self._ensure_krea2_at_ready():
                return
        elif params.get("mode") == "krea2_fz":
            if not self._ensure_krea2_fz_ready():
                return
        elif params.get("mode") == "flux2":
            if not self._ensure_flux2_ready():
                return
        else:
            if not params["base_model"]:
                messagebox.showwarning(core.APP_NAME, "请先选择底模（步骤③）。")
                return
        if not self._anima_merged_ok(params):
            return
        _need_trigger = (self.mode == "character") or (self.mode == "concept") or \
            (self.mode in ("qwen_image", "zimage", "krea2", "krea2_fz", "krea2_at", "flux2") and self._at_sub_label() in ("character", "concept"))
        if _need_trigger and not params["trigger"]:
            messagebox.showwarning(core.APP_NAME, "人物模式建议填写 Trigger 触发词（步骤②）。")
            return
        self._start_worker(lambda: self._one_click_worker(params), "一键开始训练")

    def _one_click_worker(self, params):
        core.reset_stop()
        try:
            report = os.path.join(os.environ.get("TEMP", "."), "kohya_auto_report.json")
            try:
                if os.path.isfile(report):
                    os.remove(report)
            except Exception:
                pass
            pp_mode = core.preprocess_mode(params.get("mode"), params.get("at_sub_mode"))
            core.preprocess(
                self._log, input_dir=params["raw_dir"],
                size=int(params.get("resolution") or (core.KREA2_RESOLUTION if params.get("mode") in ("krea2", "krea2_fz", "krea2_at") else core.RESOLUTIONS.get(params["base_type"], 512))),
                mode=pp_mode, trigger=params["trigger"],
                reg_dir=params["reg_dir"], repeats=params["repeats"],
                dedup=True, wd14=True, square_crop=False, crop_ratio=params.get("crop_ratio") or "",
                min_size=256, blur_threshold=30.0, report=report,
                keep_tokens=None, project=self.current_project,
                style_caption=params.get("style_caption") or "",
                dataset_mode="character" if params.get("mode") != "style" else None,
                strong_bind=params.get("strong_bind", True))
            stats = {}
            if os.path.isfile(report):
                try:
                    import json
                    with open(report, "r", encoding="utf-8") as f:
                        stats = json.load(f)
                except Exception:
                    stats = {}
            ok_n = stats.get("ok", 0) + stats.get("skipped_existing", 0)
            self.q.put(("AUTO_CONFIRM", params, stats, ok_n))
        except core.StopRequested:
            self._log("[停止] 一键训练已手动停止（已预处理的部分保留，可重跑继续）")
            self.q.put("__DONE__")
        except Exception as e:
            self._log(f"[ERROR] 一键训练失败：{e}")
            traceback.print_exc()
            self.q.put("__DONE__")

    # ============ 训练前预检弹窗 / 缺模引导 ============
    def cmd_open_base_dir(self):
        d = core.base_models_dir()
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        os.startfile(d)

    def _ask_download_or_open(self, base_type=None):
        bt = base_type or self.base_type
        label = core.BASE_TYPE_LABELS.get(bt, bt)
        ans = messagebox.askyesnocancel(
            core.APP_NAME,
            f"未检测到{label}版本的基础底模，训练必须要有基础底模。\n\n"
            "点击【是】跳转国内镜像下载；\n点击【否】打开模型文件夹；\n点击【取消】手动选择底模文件。")
        if ans is True:
            self.cmd_download_base()
        elif ans is False:
            self.cmd_open_base_dir()

    def _amd_vpy(self):
        """AMD 模式当前使用的训练环境 python（优先用户指定，否则默认 kohya venv）。"""
        env_dir = self.train_env_var.get().strip()
        if env_dir and os.path.isfile(os.path.join(env_dir, "Scripts", "python.exe")):
            return os.path.join(env_dir, "Scripts", "python.exe")
        kdir = core.get_kohya_dir()
        return core.venv_python(kdir) if kdir else None

    def _on_amd_toggle(self):
        if self.amd_var.get():
            self._log("[AMD] 已开启 AMD 兼容模式（实验性）：训练将自动使用 sdpa + bf16 + AdamW")
            try:
                ok, bk, detail = core.amd_env_status(self._amd_vpy())
                if not ok:
                    self._log(f"[AMD] 训练环境未就绪：{detail}")
                    if messagebox.askyesno(
                            core.APP_NAME,
                            "AMD 兼容模式已开启，但训练环境还没配置好。\n\n"
                            f"当前状态：{detail}\n\n"
                            "要不要现在打开「安装引导」？\n"
                            "引导会一步步告诉你装什么驱动、下载什么、点哪里。\n"
                            "（装好之前先不要训练，否则会失败）"):
                        self._open_amd_guide()
            except Exception:
                pass
        else:
            self._log("[AMD] 已关闭 AMD 兼容模式")
        self._refresh_status()

    def cmd_pick_train_env(self):
        """选择 AMD 训练环境（含 Scripts\\python.exe 的 venv 文件夹）。"""
        d = filedialog.askdirectory(title="选择训练环境（venv 文件夹，需包含 Scripts\\python.exe）")
        if not d:
            return
        if not os.path.isfile(os.path.join(d, "Scripts", "python.exe")):
            messagebox.showwarning(
                core.APP_NAME,
                "该文件夹不是有效的 Python 虚拟环境（缺少 Scripts\\python.exe）。\n\n"
                "请选择 venv 文件夹本身，例如：C:\\kohya_amd_env")
            return
        self.train_env_var.set(d)
        self._log(f"[AMD] 训练环境已指定：{d}")
        self._refresh_status()

    def cmd_amd_env(self):
        """AMD 兼容模式环境检查 + 打开详细安装引导窗口。"""
        self._open_amd_guide()

    def _recheck_amd(self, win=None):
        try:
            if win is not None:
                win.destroy()
        except Exception:
            pass
        self._open_amd_guide()

    def _open_amd_guide(self):
        """AMD 训练环境安装引导窗口（面向小白：自动检测 + 动态命令 + 半自动创建环境）。"""
        try:
            if getattr(self, "_amd_guide_win", None) and self._amd_guide_win.winfo_exists():
                self._amd_guide_win.lift()
                return
        except Exception:
            pass
        vpy = self._amd_vpy()
        ok, bk, detail = core.amd_env_status(vpy)
        ginfo = core.detect_gpu_info()
        name = ginfo.get("name") or "未知"
        vram = ginfo.get("vram_gb")
        env_dir = self.train_env_var.get().strip() or "（默认 kohya 环境）"

        # 检测系统 Python，动态生成 wheel URL（cp310 / cp311 / cp312）
        sys_vers = core.detect_system_pythons()
        py_ver = ("3.12" if "3.12" in sys_vers else
                  "3.11" if "3.11" in sys_vers else
                  "3.10" if "3.10" in sys_vers else None)
        cp = {"3.10": "cp310", "3.11": "cp311"}.get(py_ver, "cp312")
        if sys_vers:
            py_line = "检测到系统 Python：" + "、".join(sys_vers)
            if py_ver is None:
                py_line += "（⚠ AMD 官方仅支持 3.11/3.12，请安装 Python 3.12）"
            elif py_ver == "3.10":
                py_line += "（⚠ AMD 官方仅验证 3.11/3.12，3.10 的 wheel 可能不存在，建议安装 Python 3.12）"
            elif py_ver == "3.11":
                py_line += "（官方验证版为 3.12，3.11 的 wheel 见发布目录确认）"
        else:
            py_line = "未检测到 Python（请先安装 3.12，见第 2 步）"

        rocm_cmd = ("pip install --no-cache-dir "
                    f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/rocm_sdk_core-{AMD_ROC_VERSION}-py3-none-win_amd64.whl "
                    f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/rocm_sdk_devel-{AMD_ROC_VERSION}-py3-none-win_amd64.whl "
                    f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/rocm_sdk_libraries_custom-{AMD_ROC_VERSION}-py3-none-win_amd64.whl "
                    f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/rocm-{AMD_ROC_VERSION}.tar.gz")
        torch_cmd = ("pip install --no-cache-dir "
                     f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/torch-{AMD_TORCH_VERSION}%2Brocm{AMD_ROC_VERSION}-{cp}-{cp}-win_amd64.whl "
                     f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/torchaudio-{AMD_TORCH_VERSION}%2Brocm{AMD_ROC_VERSION}-{cp}-{cp}-win_amd64.whl "
                     f"https://repo.radeon.com/rocm/windows/rocm-rel-{AMD_ROC_VERSION}/torchvision-{AMD_TORCHVISION_VERSION}%2Brocm{AMD_ROC_VERSION}-{cp}-{cp}-win_amd64.whl")
        deps_cmd = ("pip install transformers diffusers accelerate safetensors omegaconf "
                    "numpy pillow av opencv-python einops sentencepiece")

        default_env = os.path.join(core.data_dir(), "venv_amd")
        status_txt = ("✅ 环境就绪（%s）" % bk) if ok else ("❌ 环境未就绪：" + (detail or "未知"))

        w = ctk.CTkToplevel(self.root)
        self._amd_guide_win = w
        w.title("AMD 显卡 · 训练环境安装引导（实验性）")
        w.geometry("860x740")
        w.minsize(780, 580)
        w.transient(self.root)

        txt = ctk.CTkTextbox(w, fg_color="#16181e", text_color="#c6ccd8", corner_radius=8,
                             border_width=1, border_color=BORDER, font=ui_font(FONT_BODY), wrap="word")
        txt.pack(fill="both", expand=True, padx=16, pady=(16, 6))

        help_text = (
            "AMD 显卡 · 训练环境安装引导（实验性）\n"
            "==================================================\n"
            "⚠ 提示：AMD 显卡训练属于实验性支持，可能遇到兼容问题；按步骤来，报错发给我们排查。\n\n"
            "▍当前状态\n"
            f"· 显卡：{name}" + (f"（约 {vram:.1f}GB）" if vram else "") + "\n"
            f"· {py_line}\n"
            f"· 当前训练环境：{env_dir}\n"
            f"· {status_txt}\n\n"
            "工具默认安装的是 NVIDIA 版 PyTorch，AMD 卡无法直接使用。\n"
            "AMD 官方为 Windows 提供 ROCm 版 PyTorch（推荐 Python 3.12）。\n"
            "下面按步骤来（约 30~60 分钟，主要是下载）。\n\n"
            "▍路线一：ROCm 原生（推荐，RX 7000/9000 系官方支持）\n"
            "--------------------------------------------------\n"
            "第 1 步：更新显卡驱动（≥ " + AMD_DRIVER_MIN + "）\n"
            "   打开 AMD 官方驱动下载页，下载安装 Adrenalin " + AMD_DRIVER_MIN + " 或更新版本。\n\n"
            "第 2 步：安装 Python 3.12\n"
            "   直接点下方「自动安装 Python 3.12」按钮（已内置安装包，静默安装约 1 分钟，\n"
            "   不用自己下载）。装完点「重新检查」刷新。\n\n"
            "第 3 步：创建训练环境\n"
            "   推荐直接点下方「自动创建训练环境」（自动建到默认位置，也可手动改）：\n"
            "   " + default_env + "\n"
            "   手动方式：py -3.12 -m venv " + default_env + "\n\n"
            "第 4~6 步：安装 AMD 运行库 + PyTorch + 训练依赖（全自动）\n"
            "   直接点下方「🚀 自动安装全部依赖」按钮，软件会自动装好这三样\n"
            "   （文件较大共约 3~5GB，视网速 20~60 分钟，可随时点「停止当前任务」）。\n"
            "   老手也可点「复制 ROCm/复制 PyTorch/复制依赖」命令手动装。\n"
            "   ⚠ 不要手动安装 xformers 和 bitsandbytes（AMD 不支持，本工具会自动避开）\n\n"
            "第 7 步：把环境告诉本工具\n"
            "   回到工具界面，在「AMD 兼容模式」旁边：\n"
            "   ① 点「选择训练环境…」，选中上面那个 venv 文件夹\n"
            "   ② 点「环境检查 / 安装引导」，看到“✅ 环境就绪（rocm）”\n"
            "   ③ 开启「AMD 兼容模式（实验性）」开关，就可以开始训练了\n\n"
            "▍路线二：ZLUDA（进阶，成功率看显卡，不推荐小白）\n"
            "--------------------------------------------------\n"
            "原理：让 CUDA 版 PyTorch 通过 ZLUDA 翻译层跑在 AMD 卡上，不用换 Python/torch。\n"
            "步骤概要：\n"
            " ① 安装 AMD HIP SDK（版本须与 ZLUDA 匹配，见其发布说明）\n"
            " ② 从 GitHub 下载 ZLUDA Windows 预编译 zip\n"
            " ③ 备份并把 ZLUDA 的 nvcuda.dll 等放入训练环境 torch/lib 目录\n"
            " ④ 设置系统环境变量 HIP_PATH（指向已安装的 ROCm/HIP 目录）\n"
            " ⑤ 运行 import torch; print(torch.cuda.is_available())，为 True 即成功\n"
            "⚠ 性能一般、稳定性差（官方声明 PyTorch 支持有限），仅建议折腾型用户。\n"
            "GitHub：https://github.com/lshqqytiger/ZLUDA\n"
            "参考教程：https://github.com/vladmandic/sdnext/wiki/ZLUDA\n\n"
            "官方文档：https://rocm.docs.amd.com/projects/radeon-ryzen/zh-cn/latest/index.html\n\n"
            "遇到问题把报错发给我们，按步骤排查即可。本工具只负责检测与参数适配，不对 AMD 环境稳定性作任何承诺。"
        )
        txt.insert("1.0", help_text)
        txt.configure(state="disabled")

        progress_frame = ctk.CTkFrame(w, fg_color=CARD, corner_radius=8,
                                      border_width=1, border_color=BORDER)
        progress_frame.pack(fill="x", padx=16, pady=(2, 8))
        progress_title = ctk.CTkLabel(progress_frame, text="等待开始 AMD 环境安装",
                                      text_color=TXT, anchor="w", font=ui_font(FONT_BODY))
        progress_title.pack(fill="x", padx=12, pady=(8, 2))
        progress_bar = ctk.CTkProgressBar(progress_frame, height=8, corner_radius=4,
                                          progress_color=ACC, fg_color=CARD2, mode="determinate")
        progress_bar.pack(fill="x", padx=12, pady=3)
        progress_bar.set(0)
        progress_detail = ctk.CTkLabel(progress_frame, text="下载开始后将在这里实时显示速度和进度",
                                       text_color=SUB, anchor="w", font=ui_font(FONT_HINT))
        progress_detail.pack(fill="x", padx=12, pady=(2, 8))
        progress_state = {"key": None, "bytes": 0, "time": 0.0, "indeterminate": False}

        def _progress_ui(title, detail, fraction=None):
            try:
                if not w.winfo_exists():
                    return
                progress_title.configure(text=title)
                progress_detail.configure(text=detail)
                if fraction is None:
                    if not progress_state["indeterminate"]:
                        progress_bar.configure(mode="indeterminate")
                        progress_bar.start()
                        progress_state["indeterminate"] = True
                else:
                    if progress_state["indeterminate"]:
                        progress_bar.stop()
                        progress_bar.configure(mode="determinate")
                        progress_state["indeterminate"] = False
                    progress_bar.set(max(0.0, min(1.0, fraction)))
            except Exception:
                pass

        def _set_progress_phase(title, detail, fraction=None):
            self.root.after(0, lambda: _progress_ui(title, detail, fraction))

        def _amd_download_progress(stage, filename, done, total, index, count):
            now = time.monotonic()
            key = (stage, filename)
            if progress_state["key"] != key:
                progress_state.update(key=key, bytes=done, time=now)
                speed = 0.0
            else:
                elapsed = now - progress_state["time"]
                speed = ((done - progress_state["bytes"]) / elapsed) if elapsed > 0 else 0.0
                progress_state.update(bytes=done, time=now)
            done_mb = done / (1024 * 1024)
            speed_text = f" · {speed / (1024 * 1024):.1f} MB/s" if speed > 0 else ""
            if total and total > 0:
                total_mb = total / (1024 * 1024)
                fraction = done / total
                detail = f"{done_mb:.1f} / {total_mb:.1f} MB（{fraction * 100:.1f}%）{speed_text}"
            else:
                fraction = None
                detail = f"已下载 {done_mb:.1f} MB{speed_text} · 正在获取文件总大小"
            phase = 1 if stage == "ROCm" else 2
            title = f"阶段 {phase}/3 · {stage} 下载 {index}/{count} · {filename}"
            self.root.after(0, lambda: _progress_ui(title, detail, fraction))

        def _amd_install_status(stage, status):
            phase = 1 if stage == "ROCm" else 2
            if status == "downloading":
                _set_progress_phase(f"阶段 {phase}/3 · 准备下载 {stage}",
                                    "正在连接 AMD 官方下载服务器…", None)
            elif status == "installing":
                _set_progress_phase(f"阶段 {phase}/3 · 正在安装 {stage}",
                                    "下载已完成，正在写入训练环境…", None)
            elif status == "complete":
                _set_progress_phase(f"阶段 {phase}/3 · {stage} 安装完成",
                                    "正在进入下一阶段…", 1.0)

        btns = ctk.CTkFrame(w, fg_color="transparent"); btns.pack(fill="x", padx=16, pady=(0, 14))

        def _btn(t, cb):
            b = ctk.CTkButton(btns, text=t, height=30, fg_color=CARD2, hover_color="#343a46",
                              border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                              font=ui_font(FONT_HINT), command=cb)
            b.pack(side="left", padx=4)
            return b

        def _copy(s):
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(s)
            except Exception:
                pass
            self._log("[AMD] 命令已复制到剪贴板，去 cmd 里粘贴运行")
            messagebox.showinfo(core.APP_NAME, "命令已复制到剪贴板。\n请打开「命令提示符」粘贴运行。")

        def _auto_venv():
            pv = py_ver
            if not pv:
                messagebox.showwarning(
                    core.APP_NAME,
                    "未检测到 Python 3.11/3.12。\n\n请先点「自动安装 Python 3.12」，\n装完再点「重新检查」，然后点「自动创建训练环境」。")
                return
            target = os.path.join(core.data_dir(), "venv_amd")
            self._log(f"[AMD] 正在用 Python {pv} 创建训练环境：{target} …")

            def work():
                ok2, msg2 = core.create_python_venv(pv, target)
                self.root.after(0, lambda: self._venv_done(ok2, msg2, target, pv))
            threading.Thread(target=work, daemon=True).start()

        def _auto_py312():
            self._log("[AMD] 开始自动安装 Python 3.12（内置安装包，静默安装，约 1 分钟）…")

            def work():
                ok3, msg3 = core.install_python_312(self._log)
                self.root.after(0, lambda: self._py312_done(ok3, msg3))
            threading.Thread(target=work, daemon=True).start()

        def _auto_install_all():
            venv = self.train_env_var.get().strip()
            if not venv or not os.path.isfile(os.path.join(venv, "Scripts", "python.exe")):
                messagebox.showwarning(core.APP_NAME, "请先点「自动创建训练环境」，再点「自动安装全部依赖」。")
                return
            if not messagebox.askyesno(
                    core.APP_NAME,
                    "即将自动安装 AMD 训练依赖（ROCm 运行库 + AMD 版 PyTorch + 训练依赖）。\n\n"
                    "文件较大（共约 3~5GB），视网速需要 20~60 分钟，期间可随时点「停止当前任务」。\n\n"
                    "确定开始吗？"):
                return
            self._set_busy(True)
            self._log("[AMD] 开始自动安装全部依赖（可在底部点「停止当前任务」中断）…")
            progress_state.update(key=None, bytes=0, time=0.0)
            _set_progress_phase("正在准备 AMD 环境安装", "即将连接 AMD 官方下载服务器…", None)

            def work():
                try:
                    core.install_amd_rocm(venv, self._log, _amd_download_progress, _amd_install_status)
                    core.install_amd_torch(venv, self._log, _amd_download_progress, _amd_install_status)
                    _set_progress_phase("阶段 3/3 · 正在安装训练依赖",
                                        "正在通过 PyPI 镜像安装其余依赖…", None)
                    core.install_amd_deps(venv, self._log)
                    okv, ver, avail = core.verify_amd_torch(venv)
                    if okv and avail:
                        _set_progress_phase("AMD 环境安装完成", ver, 1.0)
                    else:
                        _set_progress_phase("AMD 依赖已安装，但环境验证失败", ver, 0.0)
                    self.root.after(0, lambda: self._amd_install_done(okv and avail, ver, avail))
                except core.StopRequested:
                    _set_progress_phase("AMD 环境安装已停止", "已保留下载缓存，下次会从断点继续", 0.0)
                    self.root.after(0, lambda: self._amd_install_done(False, "已手动停止", False))
                except Exception as e:
                    _err = str(e)
                    _set_progress_phase("AMD 环境安装失败", _err, 0.0)
                    self.root.after(0, lambda _err=_err: self._amd_install_done(False, _err, False))
                finally:
                    self.root.after(0, lambda: self._set_busy(False))
            threading.Thread(target=work, daemon=True).start()

        _btn("🚀 自动安装全部依赖", _auto_install_all)
        _btn("自动安装 Python 3.12", _auto_py312)
        _btn("自动创建训练环境", _auto_venv)
        _btn("复制 ROCm 命令", lambda: _copy(rocm_cmd))
        _btn("复制 PyTorch 命令", lambda: _copy(torch_cmd))
        _btn("复制依赖命令", lambda: _copy(deps_cmd))
        _btn("打开 ROCm 发布目录", lambda: webbrowser.open("https://repo.radeon.com/rocm/windows/"))
        _btn("重新检查", lambda: self._recheck_amd(w))
        _btn("关闭", w.destroy)

    def _venv_done(self, ok, msg, target, py_ver):
        """自动创建训练环境完成后的回调（主线程）。"""
        if ok:
            self.train_env_var.set(target)
            self._log(f"[AMD] 训练环境创建成功：{target}")
            self._refresh_status()
            messagebox.showinfo(
                core.APP_NAME,
                "训练环境创建成功！\n\n已自动填入「训练环境」输入框。\n\n接下来在同一个 cmd 窗口（环境已激活状态下）：\n"
                "① 点「复制 ROCm 命令」粘贴运行\n"
                "② 点「复制 PyTorch 命令」粘贴运行\n"
                "③ 点「复制依赖命令」粘贴运行\n\n"
                "完成后回到本工具点「重新检查」，看到“✅ 环境就绪（rocm）”即可训练。")
        else:
            self._log(f"[AMD] 创建训练环境失败：{msg}")
            messagebox.showerror(
                core.APP_NAME,
                f"创建训练环境失败：\n{msg}\n\n"
                f"可手动在 cmd 里运行：\npy -{py_ver} -m venv {target}")

    def _py312_done(self, ok, msg):
        """自动安装 Python 3.12 完成后的回调（主线程）。"""
        if ok:
            self._log("[OK] Python 3.12 安装完成")
            messagebox.showinfo(core.APP_NAME, "Python 3.12 安装成功！\n\n点「重新检查」刷新，然后点「自动创建训练环境」继续。")
            try:
                self._recheck_amd()
            except Exception:
                pass
        else:
            self._log(f"[ERROR] Python 3.12 安装失败：{msg}")
            messagebox.showerror(core.APP_NAME, f"Python 3.12 安装失败：\n{msg}")

    def _amd_install_done(self, ok, info, avail):
        """自动安装全部依赖完成后的回调（主线程）。"""
        if ok and avail:
            self._log("[OK] AMD 训练依赖安装完成，torch 可用")
            messagebox.showinfo(
                core.APP_NAME,
                "✅ AMD 训练依赖安装完成！\n\n"
                f"torch 版本：{info}\nGPU 可用：{avail}\n\n"
                "点「重新检查」，看到「✅ 环境就绪（rocm）」即可开始训练。")
        elif ok:
            self._log(f"[WARN] 依赖安装完成但 torch 验证未通过：{info}")
            messagebox.showwarning(core.APP_NAME, f"依赖安装完成，但 torch 验证未通过：\n{info}")
        else:
            self._log(f"[ERROR] AMD 环境验证失败：{info}")
            messagebox.showerror(
                core.APP_NAME,
                f"AMD 依赖已安装，但环境验证失败：\n{info}\n\n"
                "请先根据上方真实错误排查：\n"
                "· DLL/torch 导入错误 → 重新运行本窗口的自动安装，修复 ROCm/PyTorch 组件\n"
                "· GPU 不可用 → 更新 AMD 驱动，并确认显卡受当前 ROCm 版本支持\n"
                "· Python/venv 路径错误 → 重新创建 AMD 训练环境后再安装")

    def _ensure_krea2_ready(self):
        """Krea2 模式训练前检查：第二引擎已装 + Krea2 模型齐全。返回是否可继续。"""
        try:
            ok, detail, _ = core.musubi_engine_status()
        except Exception as e:
            ok, detail = False, str(e)
        if not ok:
            messagebox.showwarning(core.APP_NAME,
                                   "第二训练引擎未安装。\n请先点左侧「②' 第二引擎(可选)」安装。\n\n" + detail)
            return False
        missing = core.krea2_missing_models()
        if missing:
            d = core.krea2_models_dir()
            if messagebox.askyesno(core.APP_NAME,
                    "Krea 2 模式还缺少模型文件，需要先下载放入 models/krea2/：\n\n" + "\n".join(missing) +
                    f"\n\n是否现在打开「应用内下载」对话框？（带断点续传，下完自动识别）"):
                try:
                    os.makedirs(d, exist_ok=True)
                except Exception:
                    pass
                self.cmd_dl_krea2_models()
            return False
        return True

    def _ensure_krea2_fz_ready(self):
        """Krea2(Fizgig) 模式训练前检查：第四引擎已装 + Krea2 模型齐全。返回是否可继续。"""
        try:
            ok, detail, _, _ = core.fizgig_engine_status()
        except Exception as e:
            ok, detail = False, str(e)
        if not ok:
            messagebox.showwarning(core.APP_NAME,
                                   "第四训练引擎未安装。\n请点「⚙ 安装第四引擎」安装。\n\n" + detail)
            return False
        missing = core.krea2_missing_models()
        if missing:
            d = core.krea2_models_dir()
            if messagebox.askyesno(core.APP_NAME,
                    "Krea 2 模式还缺少模型文件，需要先下载放入 models/krea2/：\n\n" + "\n".join(missing) +
                    f"\n\n是否现在打开「应用内下载」对话框？（带断点续传，下完自动识别）"):
                try:
                    os.makedirs(d, exist_ok=True)
                except Exception:
                    pass
                self.cmd_dl_krea2_models()
            return False
        return True

    def _ensure_flux2_ready(self):
        """FLUX.2 模式训练前检查：第二引擎已装 + FLUX.2 模型齐全。返回是否可继续。"""
        try:
            ok, detail, _ = core.musubi_engine_status()
        except Exception as e:
            ok, detail = False, str(e)
        if not ok:
            messagebox.showwarning(core.APP_NAME,
                                   "第二训练引擎未安装。\n请先点左侧「②' 第二引擎(可选)」安装。\n\n" + detail)
            return False
        missing = core.flux2_missing_models()
        if missing:
            d = core.flux2_models_dir()
            if messagebox.askyesno(core.APP_NAME,
                    "FLUX.2 模式还缺少模型文件，需要先下载放入 models/flux2/：\n\n" + "\n".join(missing) +
                    f"\n\n是否现在打开「应用内下载」对话框？（带断点续传，下完自动识别）"):
                try:
                    os.makedirs(d, exist_ok=True)
                except Exception:
                    pass
                self.cmd_dl_flux2_models()
            return False
        return True

    def _ensure_krea2_at_ready(self):
        """Krea2（AI-Toolkit 引擎）模式训练前检查：第三引擎已装 + RAW/VAE 模型齐全。返回是否可继续。

        文本编码器（Qwen3-VL-4B-Instruct）与 AT 专用 VAE 目录首次训练时自动下载（国内镜像），
        这里只要求用户手动放好的 26GB RAW 底模（与第二引擎 Krea2 共用 models/krea2/）。
        """
        try:
            ok, detail, _ = core.ai_toolkit_engine_status()
        except Exception as e:
            ok, detail = False, str(e)
        if not ok:
            messagebox.showwarning(core.APP_NAME,
                                   "第三训练引擎未安装。\n请先点顶部「⚙ 安装第三引擎」安装。\n\n" + detail)
            return False
        missing = core.krea2_at_missing_models()
        if missing:
            d = core.krea2_models_dir()
            if messagebox.askyesno(core.APP_NAME,
                    "Krea2（AI-Toolkit）模式还缺少模型文件，需要先下载放入 models/krea2/：\n\n" + "\n".join(missing) +
                    f"\n\n是否现在打开「应用内下载」对话框？（带断点续传，下完自动识别）"):
                try:
                    os.makedirs(d, exist_ok=True)
                except Exception:
                    pass
                self.cmd_dl_krea2_models()
            return False
        return True

    def _ask_fix_cpu_torch(self, params):
        """训练前自愈：NVIDIA 卡 + torch 为 CPU 版时，询问是否自动重装 cu128（须主线程调用）。
        返回 True=要自动重装 cu128；否则不触发。"""
        try:
            if params.get("amd_mode"):
                return False  # AMD 走 ROCm/ZLUDA，不适用 cu128 重装
            if not core.detect_nvidia_gpu():
                return False
            vpy = core.venv_python()
            if not vpy or not os.path.isfile(vpy):
                return False
            if core.detect_torch_backend(vpy) != "cpu":
                return False
        except Exception:
            return False
        # 方案 B：Krea2（12.9B）8G 显存强提示（fp8 在部分显卡退化 + 重度层换内存，每步数十秒以上）
        if params.get("mode") in ("krea2", "krea2_fz", "krea2_at") and vram < 12:
            return messagebox.askyesno(
                core.APP_NAME,
                f"Krea 2 是 12.9B 大模型，建议 16G+ 显存；你的显卡只有约 {vram:.1f}G。\n\n"
                "8G 显存即使开 fp8 + 层换内存（blocks_to_swap），训练也会非常慢（每步数十秒以上），"
                "且 fp8 在部分显卡上可能退化成 float32 计算。\n\n"
                "强烈不建议在此显卡上训练 Krea 2，是否仍要继续？")

        return messagebox.askyesno(
            core.APP_NAME,
            "检测到当前训练环境是 CPU 版 PyTorch（CUDA 不可用）。\n\n"
            "这样训练会全程 CPU，非常慢（每步可能数百秒）。\n\n"
            "是否自动重装 CUDA 版（cu128）PyTorch？\n"
            "· 约 3.3GB，国内镜像，断点续传，可随时点停止\n"
            "· 选「否」将继续用 CPU 训练（不推荐）")

    def _warn_no_nvidia(self):
        """显卡兼容检查：N 卡直接放行；AMD 卡走兼容模式；其他保持原警告。返回 True=继续。"""
        if getattr(self, "mode", None) == "krea2_fz":
            return True   # Fizgig 双平台（NVIDIA/AMD ROCm），不强制 AMD 兼容模式
        try:
            if core.detect_nvidia_gpu():
                return True
        except Exception:
            return True
        try:
            vendor = self._gpu_info.get("vendor") or core.detect_gpu_vendor()
        except Exception:
            vendor = "unknown"
        if vendor == "amd":
            if not self.amd_var.get():
                ans = messagebox.askyesno(
                    core.APP_NAME,
                    "检测到 AMD 显卡（Radeon）。\n\n"
                    "本工具默认面向 NVIDIA 优化；AMD 卡需要先开启「AMD 兼容模式（实验性）」\n"
                    "并配置 ROCm 版 PyTorch 或 ZLUDA 训练环境，否则无法正常训练。\n\n"
                    "是否现在开启 AMD 兼容模式？")
                if ans:
                    self.amd_var.set(True)
                    self._log("[AMD] 已开启 AMD 兼容模式（实验性，不承诺稳定）")
                return False
            ok, bk, detail = core.amd_env_status(self._amd_vpy())
            if not ok:
                self._log(f"[AMD] 环境未就绪：{detail}")
                messagebox.showwarning(
                    core.APP_NAME,
                    "AMD 兼容模式：训练环境未就绪。\n\n"
                    f"检测结果：{detail}\n\n"
                    "请点击顶部「环境检查 / 安装引导」查看两条配置路线（ROCm / ZLUDA）和下载链接。")
                return False
            self._log(f"[AMD] 兼容模式环境就绪（{bk}），可尝试训练（实验性）")
            return True
        return messagebox.askyesno(
            core.APP_NAME,
            "未检测到 NVIDIA 显卡。\n"
            "AMD/Intel 显卡在 Windows 下没有开箱即用支持，需要自行配置 ZLUDA/ROCm，存在兼容性风险。\n\n是否继续？")

    def _warn_low_vram(self, params):
        """按架构显存建议弹窗警告（须在主线程调用）。返回 True=继续。"""
        if params.get("mode") == "video":
            need = 24
            label = "MiniMax H3 视频（33.1B）"
        elif params.get("mode") in ("qwen_image", "zimage"):
            info = core.AT_IMAGE_MODELS.get(params["mode"], {})
            need = info.get("min_vram", 16)
            label = info.get("label", params["mode"])
        elif params.get("mode") == "krea2_fz":
            need = 10
            label = "Krea 2（Fizgig 引擎，NF4 最低 8G）"
        elif params.get("mode") in ("krea2", "krea2_fz", "krea2_at"):
            need = 16
            label = "Krea 2（12.9B）"
        else:
            info = core.ARCH_INFO.get(params.get("base_type", "sd15"), {})
            need = info.get("recommend_vram", 12)
            label = info.get("label", params.get("base_type"))
        vram = core.detect_vram_gb()
        if vram is None or vram >= need:
            return True
        return messagebox.askyesno(
            core.APP_NAME,
            f"当前架构：{label}\n"
            f"建议显存：{need}G 及以上；你的显卡约 {vram:.1f}G。\n\n"
            "训练可能卡顿或显存不足（OOM），工具会自动开启省显存设置。\n是否继续？")

    def _ask_resume(self, params):
        output_name = core.OUTPUT_NAMES.get(params["mode"], "anime_style_lora")
        # 断点续训要在当前项目的输出目录里找快照：
        # params 里通常没有 project 字段（_collect_params 不生成），直接用 self.current_project。
        _proj = (self.current_project or "").strip() or (params.get("project") or "").strip()
        _odir = core.data_sub("output", _proj) if _proj else core.data_sub("output")
        # 第四引擎（Fizgig）断点目录是 {name}-NNNNNN-state（按 epoch），用专门查找
        if params.get("mode") == "krea2_fz":
            state = core.find_fizgig_state(_odir, output_name)
        else:
            state = core.find_latest_state(_odir, output_name)
        if state:
            return state if messagebox.askyesno(
                core.APP_NAME,
                f"发现上次中断留下的训练进度快照：\n{os.path.basename(state)}\n\n"
                "要不要从上次断点继续训练？（选否则从头重新训练）") else None
        return None

    def _anima_merged_ok(self, params):
        """Anima 合并包底模提示：确认后训练端自动剥离 DiT 并缓存。返回 False=用户取消。"""
        try:
            if params.get("base_type") != "anima":
                return True
            base = (params.get("base_model") or "").strip()
            if not base or not os.path.isfile(base):
                return True
            from kohya_core import anima_ckpt as _ack
            if _ack.checkpoint_kind(base) != "merged":
                return True
        except Exception:
            return True
        return messagebox.askyesno(
            core.APP_NAME,
            "检测到合并版 Anima 底模（内含 Qwen3 文本编码器，适合推理/出图）。\n\n"
            "Anima 训练需要「纯 DiT」底模，直接用这个文件训练会报 Unexpected keys 错误。\n\n"
            "是否自动剥离 DiT 并缓存后再训练？\n"
            "（推荐；大文件首次剥离约 1~3 分钟，之后自动复用缓存）\n"
            "选「否」将取消本次训练，请改用纯 DiT 底模（如 anima-base-v1.0）。")

    def _confirm_training(self, params, resume=None):
        if params.get("mode") in ("krea2", "krea2_fz", "krea2_at"):
            files = core.krea2_model_files()
            msg = (
                "即将开始 Krea 2 训练，请确认以下参数：\n\n"
                f"模式        : {core.MODE_LABELS.get(params['mode'], params['mode'])}" + ("（AI-Toolkit 引擎）" if params.get('mode') == 'krea2_at' else "（Fizgig 引擎）" if params.get('mode') == 'krea2_fz' else "") + "\n"
                f"底模(RAW)   : {os.path.basename(files.get('raw') or '？')}\n"
                f"rank / alpha: {params['rank']} / {params['alpha']}\n"
                f"学习率      : {params['unet_lr']}\n"
                f"repeats     : {params['repeats']}\n"
                f"最大 epoch  : {params['max_epochs']}\n"
                f"分辨率      : {params.get('resolution', 1024)}px\n"
                f"Trigger     : {params['trigger'] or '（未填写）'}"
            )
        elif params.get("mode") == "video":
            _files = core.h3_model_files()
            msg = (
                "即将开始 MiniMax H3 视频训练，请确认以下参数：\n\n"
                f"模式        : {core.MODE_LABELS.get('video')}\n"
                f"H3 底模     : {os.path.basename(_files.get('dit') or '？')}\n"
                f"rank / alpha: {params['rank']} / {params['alpha']}\n"
                f"学习率      : {params['unet_lr']}\n"
                f"训练步数    : {params.get('video_steps', 2000)}\n"
                f"Trigger     : {params['trigger'] or '（未填写）'}"
            )
        elif params.get("mode") in ("qwen_image", "zimage"):
            _info = core.AT_IMAGE_MODELS.get(params["mode"], {})
            msg = (
                "即将开始 " + (_info.get("label", "") if _info else "") + " 训练，请确认以下参数：\n\n"
                f"模式        : {core.MODE_LABELS.get(params['mode'], params['mode'])}\n"
                f"训练类型    : {'画风（过滤人物标签）' if params.get('at_sub_mode') == 'style' else '人物（保留全部标签）'}\n"
                f"模型        : {_info.get('model_id', '？') if _info else '？'}\n"
                f"rank / alpha: {params['rank']} / {params['alpha']}\n"
                f"学习率      : {params['unet_lr']}\n"
                f"训练步数    : {params.get('video_steps', 2000)}\n"
                f"Trigger     : {params['trigger'] or '（未填写）'}"
            )
            if params.get("mode") == "zimage":
                _ftv = params.get("fast_tier") or "auto"
                _ft_txt = {"auto": "自动（仅 8G 显存生效）", "on": "开（强制快跑档）", "off": "关（常规）"}.get(str(_ftv), str(_ftv))
                msg += f"快跑档      : {_ft_txt}\n"
        else:
            base = core.BASE_TYPE_LABELS.get(params["base_type"], params["base_type"])
            msg = (
                "即将开始训练，请确认以下参数：\n\n"
                f"模式        : {core.MODE_LABELS.get(params['mode'], params['mode'])}\n"
                f"底模类型    : {base}\n"
                f"rank / alpha: {params['rank']} / {params['alpha']}\n"
                f"学习率      : {params['unet_lr']}\n"
                f"文本编码器学习率: {params['te_lr']}\n"
                f"repeats     : {params['repeats']}\n"
                f"最大 epoch  : {params['max_epochs']}\n"
                f"分辨率      : {params.get('resolution', core.RESOLUTIONS.get(params['base_type'], 512))}px\n"
                f"训练目标    : {'UNet + 文本编码器' if params['train_text_encoder'] else '仅 UNet'}\n"
                f"Trigger     : {params['trigger'] or '（未填写）'}\n"
                f"正则数据集  : {params['reg_dir'] or '（未使用）'}"
                + ("\nAMD 兼容模式: 开启（实验性）" if params.get("amd_mode") else "")
            )
        if resume:
            msg += f"\n\n（将从断点续训：{os.path.basename(resume)}）"
        return messagebox.askokcancel(core.APP_NAME, msg)

    def _handle_auto_confirm(self, params, stats, ok_n=None):
        if ok_n is None:
            ok_n = stats.get("ok", 0) + stats.get("skipped_existing", 0)
        min_n = core.MIN_IMAGES.get(params["mode"], 20)
        if ok_n < min_n:
            messagebox.showwarning(
                core.APP_NAME,
                f"可用图片太少：处理后只有 {ok_n} 张（{core.MODE_LABELS.get(params['mode'])} 至少需要 {min_n} 张）。\n"
                "请补充更多清晰、有效的图片后再试。")
            self._set_busy(False)
            return
        self._log(f"[OK] 可用图片 {ok_n} 张")
        if not self._warn_no_nvidia():
            self._set_busy(False)
            return
        # 自愈：CPU 版 torch（NVIDIA 卡）→ 弹窗确认是否自动重装 cu128，决定传给训练线程
        params["fix_cpu_torch"] = self._ask_fix_cpu_torch(params)
        if not self._warn_low_vram(params):
            self._set_busy(False)
            return
        resume = self._ask_resume(params)
        if not self._confirm_training(params, resume):
            self._set_busy(False)
            return
        # 阶段1（一键训练=预处理）线程已结束但未释放 busy，
        # 这里先释放，否则 _start_worker 的防重入检查会拦截训练启动。
        self._set_busy(False)
        self._start_worker(lambda: self._train_worker(params, resume), "训练")

    # ============ 底模下载（应用内 / 浏览器） ============
    def _show_arch_download_help(self, bt):
        """新架构（FLUX/Anima）没有应用内一键下载，给出准备指引。"""
        if bt == "flux":
            msg = (
                "FLUX.1 支持应用内一键下载：\n\n"
                "点「没有模型？点这里下载」会打开 FLUX 下载对话框，\n"
                "4 个文件（DiT / clip_l / t5xxl_fp16 / ae）可逐个应用内下载（断点续传）到 models/base/，\n"
                "下完点「↻ 刷新」即可在底模列表看到 flux1-dev.safetensors。\n\n"
                "手动备选（国内 hf-mirror 镜像）：\n"
                "· DiT：Comfy-Org/flux1-dev → flux1-dev.safetensors（23.8GB）\n"
                "· clip_l / t5xxl_fp16：comfyanonymous/flux_text_encoders\n"
                "· ae：Kijai/flux-fp8 → flux-vae-bf16.safetensors（保存为 ae.safetensors）")
        else:
            msg = (
                "Anima 没有应用内一键下载。\n\n"
                "需要：\n"
                "· Anima DiT .safetensors（约 5GB，作为底模选择）\n"
                "· Qwen3-0.6B 文本编码器（训练时自动从 hf-mirror 下载）\n"
                "· Qwen-Image VAE（训练时自动下载）\n\n"
                "DiT 下载：HuggingFace circlestone-labs/Anima，或国内镜像 hf-mirror.com。\n"
                "下载后放进 models/base，点「选择底模文件」选择即可。")
        messagebox.showinfo(core.APP_NAME, msg)
        self.cmd_open_base_dir()

    def _download_choice_dialog(self, bt=None):
        bt = bt or self.base_type
        if bt == "flux":
            # FLUX 需要 4 个文件（DiT + CLIP-L + T5-XXL + AE），走专用多文件下载对话框
            self.cmd_dl_flux_models()
            return
        label = core.BASE_TYPE_LABELS.get(bt, "底模")
        models = core.get_download_models(bt)
        if not models:
            self._show_arch_download_help(bt)
            return
        sel = {"m": core.get_default_download_model(bt) or models[0]}
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("下载基础底模")
        dlg.geometry("540x340")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        ctk.CTkLabel(dlg, text=f"当前底模类型：{label}\n选择要下载的底模（建议选「动漫」系列，并和你出图用的底模同一系列）：",
                     font=ui_font(FONT_BODY), text_color=TXT, justify="left", wraplength=480).pack(padx=20, pady=(16, 8), anchor="w")
        names = [f"{m['name']}（{m['size']}）" for m in models]
        menu = ctk.CTkOptionMenu(dlg, values=names, width=460, height=30,
                                 fg_color=CARD2, button_color=CARD2, button_hover_color="#3a4150",
                                 text_color=TXT, font=ui_font(FONT_BODY), dropdown_font=ui_font(FONT_BODY),
                                 dropdown_fg_color=CARD2, dropdown_hover_color="#3a4150")
        menu.pack(padx=20, pady=(0, 6))
        default = core.get_default_download_model(bt) or models[0]
        menu.set(names[models.index(default)])
        info_lbl = ctk.CTkLabel(dlg, text=default["note"], font=ui_font(FONT_HINT), text_color=HINT,
                                justify="left", wraplength=480)
        info_lbl.pack(padx=20, pady=(0, 4), anchor="w")
        def _pick(_v=None):
            try:
                idx = names.index(menu.get())
                sel["m"] = models[idx]
                info_lbl.configure(text=models[idx]["note"])
            except Exception:
                pass
        menu.configure(command=_pick)
        ctk.CTkLabel(dlg, text=f"保存到：{core.base_models_dir()}\n应用内下载带进度、断点续传，下完自动识别并加入底模列表。",
                     font=ui_font(FONT_HINT), text_color=SUB, justify="left", wraplength=480).pack(padx=20, pady=(2, 10), anchor="w")
        def _act(k):
            m = sel["m"]
            dlg.destroy()
            if k == "inapp":
                self.cmd_dl_in_app(bt, m)
            elif k == "web_fast":
                import webbrowser; webbrowser.open(m.get("url") or core.HF_MIRROR_URL)
            elif k == "web_fallback":
                import webbrowser; webbrowser.open(m.get("fallback") or m.get("url") or core.HF_MIRROR_URL)
            elif k == "open":
                self.cmd_open_base_dir()
        bf = ctk.CTkFrame(dlg, fg_color="transparent"); bf.pack(pady=(0, 16))
        for t, k in [("⬇ 应用内下载（推荐）", "inapp"), ("🌐 浏览器极速", "web_fast"),
                     ("🔁 备用下载", "web_fallback"), ("📂 打开文件夹", "open")]:
            ctk.CTkButton(bf, text=t, width=104, height=30, fg_color=CARD2, hover_color="#343a46",
                          border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                          font=ui_font(FONT_HINT), command=lambda kk=k: _act(kk)).pack(side="left", padx=4)
        self._tip(menu, "选择训练用的底模：动漫 LoRA 建议选「动漫」系列；最好和你出图用的底模同一系列（例如 Forge 用 AniShadow 就选 AniShadow/Illustrious）。")
        dlg.grab_set()

    def cmd_dl_in_app(self, bt=None, model=None):
        if _ModelDownloader is None:
            messagebox.showerror(core.APP_NAME, "下载模块加载失败，请使用「浏览器极速下载」。")
            return
        if getattr(self, "_downloading", False):
            messagebox.showinfo(core.APP_NAME, "已有下载任务在进行中，请先完成或取消。")
            return
        bt = bt or self.base_type
        if model is None:
            model = core.get_default_download_model(bt)
        if model is None:
            messagebox.showerror(core.APP_NAME, "暂无可下载的底模选项。")
            return
        url = model.get("url") or core.MODELSCOPE_URLS.get(bt) or core.HF_MIRROR_URL
        if core._official_source_preferred():
            # 官方源优先：HuggingFace 直连（需代理），魔搭/hf-mirror 作备用
            _hf_direct = (model.get("fallback") or "").replace("https://hf-mirror.com/", "https://huggingface.co/")
            if _hf_direct:
                url = _hf_direct
                self._log("[下载] 已启用「官方源优先」：从 HuggingFace 直连下载（需开代理）")
        fname, fsize = model["file"], model["size"]
        dest = os.path.join(core.base_models_dir(), fname)
        try:
            os.makedirs(core.base_models_dir(), exist_ok=True)
        except Exception:
            pass
        if os.path.isfile(dest):
            messagebox.showinfo(core.APP_NAME, f"{fname} 已存在，无需重复下载。")
            self._scan_base_models()
            return
        part = dest + ".part"
        if os.path.isfile(part) and os.path.getsize(part) > 0:
            if not messagebox.askyesno(core.APP_NAME,
                    f"发现上次未完成的下载进度（{os.path.getsize(part)/1048576:.1f} MB）。\n要不要从断点继续下载？"):
                try:
                    os.remove(part)
                except Exception:
                    pass
        self._downloading = True
        self._dl_kind = "base"
        self._show_dl_ui(fname, fsize)
        self._log(f"[下载] 开始下载底模：{fname}（{fsize}）")
        self._log(f"[下载] 保存到：{dest}")
        self._dl = _ModelDownloader(url, dest,
                                    progress_cb=self._dl_progress_cb,
                                    done_cb=self._dl_done_cb,
                                    logf=self._log)
        self._dl.start()

    def _show_dl_ui(self, fname, fsize):
        self.dl_win = ctk.CTkToplevel(self.root)
        self.dl_win.title("下载进度")
        self.dl_win.geometry("460x160")
        self.dl_win.resizable(False, False)
        self.dl_win.transient(self.root)
        self.dl_status_var = tk.StringVar(value=f"正在准备下载 {fname}（{fsize}）…")
        ctk.CTkLabel(self.dl_win, textvariable=self.dl_status_var, font=ui_font(FONT_BODY), text_color=TXT).pack(padx=20, pady=(16, 8), anchor="w")
        self.dl_progress = ctk.CTkProgressBar(self.dl_win, height=10, fg_color=CARD2, progress_color=ACC)
        self.dl_progress.pack(fill="x", padx=20, pady=(0, 8))
        self.dl_progress.set(0)
        ctk.CTkButton(self.dl_win, text="取消下载", width=90, height=28, fg_color=CARD2, hover_color="#343a46",
                      border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                      font=ui_font(FONT_HINT), command=self.cmd_dl_cancel).pack(pady=(4, 12))

    def _dl_progress_cb(self, done, total, speed):
        pct = (done / total * 100) if total else 0
        self.q.put(("DL_PROGRESS", pct, f"已下载 {done/1048576:.1f} / {total/1048576:.1f} MB，速度 {speed/1048576:.1f} MB/s"))

    def _dl_done_cb(self, ok, dest):
        self.q.put(("DL_DONE", ok, dest))

    def _dl_progress_ui(self, pct, status):
        try:
            self.dl_progress.set(pct / 100)
            self.dl_status_var.set(status)
        except Exception:
            pass

    def _handle_dl_done(self, ok, dest):
        self._downloading = False
        kind = getattr(self, "_dl_kind", "base")
        self._dl_kind = "base"
        try:
            self.dl_win.destroy()
        except Exception:
            pass
        if ok:
            if kind == "h3":
                self._log(f"[H3] 下载完成：{dest}")
                self._refresh_h3_status()
                messagebox.showinfo(core.APP_NAME, f"H3 模型下载完成：\n{os.path.basename(dest)}\n\n已自动识别（状态已刷新）。")
            elif kind == "flux":
                self._log(f"[FLUX] 下载完成：{dest}")
                self._scan_base_models()
                messagebox.showinfo(core.APP_NAME, f"FLUX 模型下载完成：\n{os.path.basename(dest)}\n\n已自动扫描底模列表；若还有其他 FLUX 文件没下完，回到下载对话框继续点「⬇ 应用内」。")
            elif kind == "krea2":
                self._log(f"[Krea2] 下载完成：{dest}")
                self._refresh_krea2_status()
                messagebox.showinfo(core.APP_NAME, f"Krea2 模型下载完成：\n{os.path.basename(dest)}\n\n已自动识别（状态已刷新）。")
            elif kind == "flux2":
                self._log(f"[FLUX.2] 下载完成：{dest}")
                self._refresh_flux2_status()
                messagebox.showinfo(core.APP_NAME, f"FLUX.2 模型下载完成：\n{os.path.basename(dest)}\n\n已自动识别（状态已刷新）。")
            else:
                self._log(f"[底模] 下载完成：{dest}")
                self._scan_base_models()
                messagebox.showinfo(core.APP_NAME, f"底模下载完成：\n{dest}\n\n已自动扫描并加入底模列表。")
        else:
            self._log("[ERROR] 下载失败或已取消")

    def _build_links_dialog(self, title, intro, links, files, open_label, open_cmd, rebuild_cmd, dl_fn, hint=""):
        """通用模型文件下载对话框（H3 / FLUX / Krea2 共用）：每文件应用内下载或浏览器直链。"""
        dlg = ctk.CTkToplevel(self.root)
        dlg.title(title)
        dlg.geometry("700x430")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        ctk.CTkLabel(dlg, text=intro, font=ui_font(FONT_BODY), text_color=TXT, justify="left", wraplength=640).pack(padx=20, pady=(14, 8), anchor="w")
        for key, (fname, desc, url) in links.items():
            row = ctk.CTkFrame(dlg, fg_color="transparent"); row.pack(fill="x", padx=20, pady=3)
            done = files.get(key) is not None
            mark = "✓" if done else "○"
            ctk.CTkLabel(row, text=f"{mark} {fname}", font=ui_font(FONT_HINT),
                         text_color=(OK_TX if done else TXT), width=370, anchor="w").pack(side="left")
            if done:
                ctk.CTkLabel(row, text="已下载", font=ui_font(FONT_HINT), text_color=OK_TX).pack(side="left", padx=6)
            else:
                ctk.CTkButton(row, text="⬇ 应用内", width=76, height=26, fg_color=ACC, hover_color=ACC_H,
                              corner_radius=6, font=ui_font(FONT_HINT),
                              command=lambda k=key: dl_fn(k)).pack(side="left", padx=4)
                ctk.CTkButton(row, text="🌐 浏览器", width=76, height=26, fg_color=CARD2, hover_color="#343a46",
                              border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                              font=ui_font(FONT_HINT), command=lambda u=url: webbrowser.open(u)).pack(side="left", padx=4)
            self._tip(row, desc)
        if hint:
            ctk.CTkLabel(dlg, text=hint, font=ui_font(FONT_HINT), text_color=SUB, justify="left", wraplength=640).pack(padx=20, pady=(2, 4), anchor="w")
        bf = ctk.CTkFrame(dlg, fg_color="transparent"); bf.pack(pady=(10, 14))
        ctk.CTkButton(bf, text=open_label, width=150, height=28, fg_color=CARD2, hover_color="#343a46",
                      border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6, font=ui_font(FONT_HINT),
                      command=open_cmd).pack(side="left", padx=4)
        ctk.CTkButton(bf, text="刷新状态", width=92, height=28, fg_color=CARD2, hover_color="#343a46",
                      border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6, font=ui_font(FONT_HINT),
                      command=lambda: (dlg.destroy(), rebuild_cmd())).pack(side="left", padx=4)
        ctk.CTkButton(bf, text="关闭", width=72, height=28, fg_color=CARD2, hover_color="#343a46",
                      border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6, font=ui_font(FONT_HINT),
                      command=dlg.destroy).pack(side="left", padx=4)
        dlg.grab_set()
        return dlg

    def cmd_dl_h3_models(self):
        """H3 模型下载对话框：列出 4 个文件，应用内下载（断点续传）或浏览器直链。"""
        self._build_links_dialog(
            "下载 MiniMax H3 模型",
            "MiniMax H3 训练需要以下文件（共约 40GB，应用内下载带断点续传、断了接着下）：",
            core.H3_MODEL_LINKS, core.h3_model_files(),
            "📂 打开 H3 模型文件夹", self.cmd_open_h3_models, self.cmd_dl_h3_models,
            self._start_h3_dl, "保存到 models/minimax_h3/，下完自动识别。")

    def cmd_dl_flux_models(self):
        """FLUX.1 模型下载对话框：4 个文件放进 models/base/，应用内下载（断点续传）。"""
        self._build_links_dialog(
            "下载 FLUX.1 模型",
            "FLUX.1 训练需要 4 个文件放在同一个文件夹（共约 33GB，应用内下载带断点续传）：",
            core.FLUX_MODEL_LINKS, core.flux_model_files(),
            "📂 打开底模文件夹", self.cmd_open_base_dir, self.cmd_dl_flux_models,
            self._start_flux_dl, "保存到 models/base/，下完点「↻ 刷新」即可在底模列表看到 flux1-dev.safetensors。")

    def cmd_dl_krea2_models(self):
        """Krea2 模型下载对话框：RAW+VAE+文本编码器（turbo 可选），应用内下载（断点续传）。"""
        self._build_links_dialog(
            "下载 Krea 2 模型",
            "Krea 2 训练需要以下文件（RAW 必需；turbo 可选用于出图；应用内下载带断点续传）：",
            core.KREA2_MODEL_LINKS, core.krea2_model_files(),
            "📂 打开 Krea2 模型文件夹", self.cmd_open_krea2_models, self.cmd_dl_krea2_models,
            self._start_krea2_dl, "保存到 models/krea2/，下完自动识别（顶部状态变「齐全 ✓」）。")

    def _start_model_file_dl(self, key, links, dest_dir, kind, label):
        """启动单个模型文件的应用内下载（断点续传），H3 / FLUX / Krea2 共用。"""
        if _ModelDownloader is None:
            messagebox.showerror(core.APP_NAME, "下载模块加载失败，请使用「🌐 浏览器」下载。")
            return
        if getattr(self, "_downloading", False):
            messagebox.showinfo(core.APP_NAME, "已有下载任务在进行中，请先完成或取消。")
            return
        fname, desc, url = links[key]
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except Exception:
            pass
        dest = os.path.join(dest_dir, fname)
        if os.path.isfile(dest):
            messagebox.showinfo(core.APP_NAME, f"{fname} 已存在，无需重复下载。")
            if kind == "h3":
                self._refresh_h3_status()
            elif kind == "krea2":
                self._refresh_krea2_status()
            elif kind == "flux":
                self._scan_base_models()
            return
        part = dest + ".part"
        if os.path.isfile(part) and os.path.getsize(part) > 0:
            if not messagebox.askyesno(core.APP_NAME,
                    f"发现上次未完成的下载进度（{os.path.getsize(part)/1048576:.1f} MB）。\n要不要从断点继续下载？"):
                try:
                    os.remove(part)
                except Exception:
                    pass
        # 兜底预检：Krea2 raw/turbo 已改走魔搭官方转存（免许可直链）；仅当源仍拒绝时提示
        if kind == "krea2" and key in ("raw", "turbo"):
            _st = core._http_status(url)
            if _st in (401, 403):
                self._log(f"[下载] {fname} 返回 {_st}：下载源异常（已内置魔搭 ModelScope 官方转存直链）。")
                messagebox.showwarning(
                    core.APP_NAME,
                    f"{fname} 下载被源拒绝（{_st}）。\n\n"
                    "已内置魔搭（ModelScope）官方转存直链，正常情况下无需接受许可即可一键下载。\n"
                    "若仍报 401/403，多为源临时故障：稍后重试；或用「🌐 浏览器」打开下方链接手动下载后放进 models/krea2/ 文件夹：\n"
                    f"{url}")
                return
        self._downloading = True
        self._dl_kind = kind
        self._show_dl_ui(fname, desc)
        self._log(f"[下载] 开始下载 {label}：{fname}（{desc}）")
        self._log(f"[下载] 保存到：{dest}")
        self._dl = _ModelDownloader(url, dest,
                                    progress_cb=self._dl_progress_cb,
                                    done_cb=self._dl_done_cb,
                                    logf=self._log)
        self._dl.start()

    def _start_h3_dl(self, key):
        self._start_model_file_dl(key, core.H3_MODEL_LINKS, core.h3_models_dir(), "h3", "H3 模型")

    def _start_flux_dl(self, key):
        self._start_model_file_dl(key, core.FLUX_MODEL_LINKS, core.base_models_dir(), "flux", "FLUX 模型")

    def _start_krea2_dl(self, key):
        self._start_model_file_dl(key, core.KREA2_MODEL_LINKS, core.krea2_models_dir(), "krea2", "Krea2 模型")

    def _refresh_krea2_status(self):
        """Krea2 模型状态（顶部状态行；krea2_at 模式还提示 AI-Toolkit 文本编码器/VAE 训练时自动下载）。"""
        try:
            if getattr(self, "mode", None) == "krea2_at":
                _files = core.krea2_model_files()
                _miss = []
                if not _files.get("raw"):
                    _miss.append("RAW")
                if not _files.get("vae"):
                    _miss.append("VAE")
                if _miss:
                    self.krea2_model_var.set("Krea2 模型：缺 " + "、".join(_miss) + "（点⬇应用内下载）")
                elif not core.krea2_at_model_ready():
                    self.krea2_model_var.set("Krea2 模型：底模齐全 ✓（AT 文本编码器/VAE 训练时自动下载）")
                else:
                    self.krea2_model_var.set("Krea2 模型：齐全 ✓")
            else:
                _files = core.krea2_model_files()
                _short = {"raw": "RAW", "vae": "VAE", "te": "文本编码器"}
                _miss = "、".join(_short[k] for k in ("raw", "vae", "te") if not _files.get(k))
                self.krea2_model_var.set(("Krea2 模型：缺 " + _miss + "（点⬇应用内下载）") if _miss else "Krea2 模型：齐全 ✓")
        except Exception:
            pass

    def cmd_dl_cancel(self):
        try:
            if self._dl is not None:
                self._dl.cancel()
        except Exception:
            pass

    def _refresh_one_click_state(self):
        steps = [s for s in self._current_steps() if s["check"] != "at_model"]
        ready = bool(steps) and all(self._guide_done(s["check"]) for s in steps)
        try:
            self.btn_one_click.configure(state=("normal" if ready else "disabled"),
                                         fg_color=(ACC if ready else CARD2),
                                         hover_color=(ACC_H if ready else "#343a46"))
            if ready:
                self.btn_one_click_hint.configure(text="✓ 准备就绪，点击开始训练")
            else:
                pend = next((s for s in steps if not self._guide_done(s["check"])), None)
                self.btn_one_click_hint.configure(
                    text=("还差「%s」" % pend["label"]) if pend else "完成引导后自动点亮")
        except Exception:
            pass

    def _show_help_window(self):
        w = ctk.CTkToplevel(self.root)
        w.title("新手教学 & 常见问题")
        w.geometry("680x640")
        w.resizable(True, True)
        w.transient(self.root)
        txt = ctk.CTkTextbox(w, fg_color="#16181e", text_color="#c6ccd8", corner_radius=8,
                             border_width=1, border_color=BORDER, font=ui_font(FONT_BODY), wrap="word")
        txt.pack(fill="both", expand=True, padx=18, pady=18)
        help_text = (
            "📖 新手教学 & 常见问题\n\n"
            "▍第一步：准备图片\n"
            "· 人物模式：15~30 张同一个人的图，多角度、不同服装\n"
            "· 画风模式：20~60 张不同人物的图\n"
            "· 图片越清晰越好（别用太小太糊的缩略图）\n\n"
            "▍第二步：选底模（画图的底子）\n"
            "· 软件不附带底模，需要自己下载（点「没有模型？点这里下载」）\n"
            "· 底模分四种架构（程序自动识别）：\n"
            "   · SD1.5：512 分辨率，显存要求低，画风偏基础\n"
            "   · SDXL：1024 分辨率，效果更好，推荐 16G 显存；8G 也能跑（勾「只训练 UNet」）\n"
            "   · FLUX.1：1024，12B 大模型，推荐 16G 显存，需同目录放配套文件\n"
            "   · Anima：1024，2026 新架构，8G 可跑（开省显存），推荐 12G+\n"
            "· 下载的 .safetensors 放进 models/base 文件夹，自动识别并切换对应架构\n\n"
            "▍第三步：填触发词（人物模式）\n"
            "· 触发词 = 角色的“名字”，训练后画图写上它就能唤出角色\n"
            "· 建议用网上很少见的英文单词（如 my_oc01），别用 girl 这种常见词\n\n"
            "▍第四步：开始训练\n"
            "· 左侧「一键开始训练」会自动完成预处理 + 训练\n"
            "· 训练完的 LoRA 在 output 文件夹\n\n"
            "❓ 常见问题\n\n"
            "Q：训练太慢 / 显存不够？\n"
            "A：高级参数里勾选「只训练 UNet」，省显存、速度快很多（8G 跑 SDXL/Anima、以及 FLUX 强烈建议勾）。\n\n"
            "Q：想中途停掉训练？\n"
            "A：任务进行中，左下角会出现「⏹ 停止当前任务」按钮，点一下即可中断。\n\n"
            "Q：练出来的模型没效果？\n"
            "A：出图底模要和 LoRA 匹配：SD1.5 的 LoRA 用 SD1.5 底模出图，SDXL 的用 SDXL。\n\n"
            "Q：图片太少被拦住？\n"
            "A：人物至少 15 张、画风至少 20 张（过滤后），不够会提示补图。\n\n"
            "Q：训练中断了？\n"
            "A：软件自动检测断点，下次训练会问你是否续训。\n\n"
            "Q：底模在哪下载？\n"
            "A：点顶部「没有模型？点这里下载」，选「应用内下载」或浏览器下载。\n\n"
            "Q：LoRA 怎么用？\n"
            "A：把 output 里的 .safetensors 放进生图工具（如 WebUI）的 models/Lora 文件夹，\n"
            "   出图时选上它，人物模式用「触发词」开头，画风模式直接写画风描述。\n\n"
            "Q：怎么检查/修改每张图的标签？\n"
            "A：主界面点「标签编辑器」：可逐张看图改标签、批量删除/替换标签、置顶 trigger、\n"
            "   标签频率统计。WD14 自动打的标签偶尔不准，改好后 LoRA 学得更准。\n\n"
            "Q：数据集里的 repeats_名称 是什么？\n"
            "A：秋叶式目录结构：在数据集里建「数字_名称」子目录（如 3_yanami_01），\n"
            "   表示这组图片在训练时重复 3 次。标签编辑器里点「整理为 repeats_名称」\n"
            "   可一键把平铺图片整理成这种结构（不同概念可以放不同子目录、用不同 repeats）。\n\n"
            "Q：我是 AMD 显卡，能用吗？\n"
            "A：能，但属于实验性支持：界面顶部会出现「AMD 兼容模式（实验性）」开关，\n"
            "   开启后训练会自动改成 sdpa + bf16 + AdamW 并做环境检查；第一次用请先点「环境检查 / 安装引导」\n"
            "   按两条路线（ROCm 原生 / ZLUDA）配置训练环境，配置好再训练。"
        )
        txt.insert("1.0", help_text)
        txt.configure(state="disabled")

class LabelEditorWindow:
    """标签编辑器：浏览/修改每张图标签、批量删除/替换、置顶 trigger、标签频率统计、整理 repeats_名称 结构。"""

    def __init__(self, master, app, params):
        self.app = app
        self.mode = params.get("mode", "character")
        self.project = (params.get("project") or "").strip()
        self.win = ctk.CTkToplevel(master)
        _title = "标签编辑器 · " + core.MODE_LABELS.get(self.mode, self.mode)
        if self.project:
            _title += " · 项目：" + self.project
        self.win.title(_title)
        self.win.geometry("1140x780")
        self.win.minsize(920, 640)
        self.win.transient(master)
        self.win.configure(fg_color=BG)
        # 每个项目独立数据集：dataset/<项目名>/train_character（不混用其他项目的数据）
        self.train_dir = core.dataset_train_dir(self.mode, self.project)
        self.records = []
        self._thumbs = {}
        self._current = None      # 当前选中的 record 下标
        self._dirty = set()       # 有未保存修改的 record 下标
        self._tagdict = None      # 离线中英词典（惰性加载，词典窗/统计共用）
        self._dict_win = None     # 中英词典窗引用（避免重复开多个）
        self._build_ui()
        self.refresh()

    # ---------- 布局 ----------
    def _build_ui(self):
        w = self.win
        top = ctk.CTkFrame(w, fg_color="transparent"); top.pack(fill="x", padx=18, pady=(14, 6))
        self.info_var = tk.StringVar()
        ctk.CTkLabel(top, textvariable=self.info_var, font=ui_font(FONT_HINT), text_color=HINT, anchor="w").pack(side="left")
        ctk.CTkButton(top, text="打开文件夹", width=96, height=28, fg_color=CARD2, hover_color="#343a46",
                      border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                      font=ui_font(FONT_HINT), command=self._open_dir).pack(side="right")
        ctk.CTkButton(top, text="↻ 刷新", width=76, height=28, fg_color=CARD2, hover_color="#343a46",
                      border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                      font=ui_font(FONT_HINT), command=self.refresh).pack(side="right", padx=(0, 8))

        body = ctk.CTkFrame(w, fg_color="transparent"); body.pack(fill="both", expand=True, padx=18, pady=(4, 8))
        body.grid_columnconfigure(0, minsize=280, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # 左：图片列表
        left = ctk.CTkFrame(body, fg_color=CARD, corner_radius=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.list_title = ctk.CTkLabel(left, text="图片列表（0 张）", font=ui_font(FONT_BODY), text_color=TITLE_C)
        self.list_title.pack(anchor="w", padx=12, pady=(10, 6))
        lf = ctk.CTkFrame(left, fg_color="transparent")
        lf.pack(fill="both", expand=True, padx=8, pady=(0, 10))
        self.listbox = tk.Listbox(lf, bg=CARD2, fg=TXT, selectbackground=SELBAR, selectforeground="#ffffff",
                                  font=ui_font(FONT_BODY), highlightthickness=0, borderwidth=0,
                                  activestyle="none", exportselection=False)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb = ctk.CTkScrollbar(lf, command=self.listbox.yview)
        sb.pack(side="right", fill="y")
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.listbox.bind("<Double-Button-1>", lambda e: self._open_image())

        # 右：预览 + 标签编辑
        right = ctk.CTkFrame(body, fg_color=CARD, corner_radius=8)
        right.grid(row=0, column=1, sticky="nsew")
        ctk.CTkLabel(right, text="预览", font=ui_font(FONT_BODY), text_color=TITLE_C).pack(anchor="w", padx=12, pady=(10, 4))
        self.preview = ctk.CTkLabel(right, text="（选中左侧图片后显示缩略图）", font=ui_font(FONT_HINT), text_color=HINT,
                                    width=220, height=140)
        self.preview.pack(anchor="w", padx=12)
        self.fname_var = tk.StringVar()
        ctk.CTkLabel(right, textvariable=self.fname_var, font=ui_font(FONT_HINT), text_color=SUB, anchor="w").pack(anchor="w", padx=12, pady=(4, 0))
        ctk.CTkLabel(right, text="标签内容（可直接修改，保存后写入同名 .txt，支持多行）", font=ui_font(FONT_HINT), text_color=HINT).pack(anchor="w", padx=12, pady=(10, 4))
        self.caption = ctk.CTkTextbox(right, fg_color=CARD2, text_color=TXT, corner_radius=6,
                                      border_width=1, border_color=BORDER, font=ui_font(FONT_BODY), wrap="word")
        self.caption.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.caption.bind("<KeyRelease>", self._mark_dirty)
        save_row = ctk.CTkFrame(right, fg_color="transparent"); save_row.pack(fill="x", padx=12, pady=(0, 10))
        self.btn_save_one = ctk.CTkButton(save_row, text="💾 保存当前标签", width=136, height=30, fg_color=CARD2,
                                          hover_color="#343a46", border_width=1, border_color=BORDER,
                                          text_color=TXT, corner_radius=6, font=ui_font(FONT_BODY),
                                          command=self._save_current)
        self.btn_save_one.pack(side="left")
        ctk.CTkLabel(save_row, text="提示：切换图片前先保存，未保存的修改会丢失", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left", padx=(10, 0))

        # 底部批量工具栏
        tools = ctk.CTkFrame(w, fg_color=CARD, corner_radius=8)
        tools.pack(fill="x", padx=18, pady=(0, 6))
        r1 = ctk.CTkFrame(tools, fg_color="transparent"); r1.pack(fill="x", padx=12, pady=(10, 4))
        ctk.CTkLabel(r1, text="批量删除标签", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        self.del_entry = ctk.CTkEntry(r1, width=200, height=28, fg_color=CARD2, border_color=BORDER, text_color=TXT,
                                      placeholder_text="如: 1girl, solo（逗号分隔）", font=ui_font(FONT_HINT))
        self.del_entry.pack(side="left", padx=(8, 6))
        self.btn_del = ctk.CTkButton(r1, text="执行删除", width=84, height=28, fg_color=CARD2, hover_color="#343a46",
                                     border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                                     font=ui_font(FONT_HINT), command=self._do_remove)
        self.btn_del.pack(side="left")
        ctk.CTkLabel(r1, text="　", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        ctk.CTkLabel(r1, text="批量替换", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        self.rep_find = ctk.CTkEntry(r1, width=120, height=28, fg_color=CARD2, border_color=BORDER, text_color=TXT,
                                     placeholder_text="原标签", font=ui_font(FONT_HINT))
        self.rep_find.pack(side="left", padx=(8, 4))
        ctk.CTkLabel(r1, text="→", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        self.rep_to = ctk.CTkEntry(r1, width=120, height=28, fg_color=CARD2, border_color=BORDER, text_color=TXT,
                                   placeholder_text="新标签", font=ui_font(FONT_HINT))
        self.rep_to.pack(side="left", padx=(4, 6))
        self.btn_rep = ctk.CTkButton(r1, text="执行替换", width=84, height=28, fg_color=CARD2, hover_color="#343a46",
                                     border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                                     font=ui_font(FONT_HINT), command=self._do_replace)
        self.btn_rep.pack(side="left")

        r2 = ctk.CTkFrame(tools, fg_color="transparent"); r2.pack(fill="x", padx=12, pady=(0, 10))
        self.btn_pin = ctk.CTkButton(r2, text="📌 置顶 Trigger", width=120, height=30, fg_color=CARD2, hover_color="#343a46",
                                     border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                                     font=ui_font(FONT_HINT), command=self._do_pin)
        self.btn_pin.pack(side="left")
        self.btn_stats = ctk.CTkButton(r2, text="📊 标签统计", width=100, height=30, fg_color=CARD2, hover_color="#343a46",
                                       border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                                       font=ui_font(FONT_HINT), command=self._show_stats)
        self.btn_stats.pack(side="left", padx=(8, 0))
        self.btn_dict = ctk.CTkButton(r2, text="🌐 中英词典", width=104, height=30, fg_color=CARD2, hover_color="#343a46",
                                      border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                                      font=ui_font(FONT_HINT), command=self._open_dict)
        self.btn_dict.pack(side="left", padx=(8, 0))
        self.btn_organize = ctk.CTkButton(r2, text="📁 整理为 repeats_名称", width=156, height=30, fg_color=CARD2,
                                          hover_color="#343a46", border_width=1, border_color=BORDER, text_color=TXT,
                                          corner_radius=6, font=ui_font(FONT_HINT), command=self._do_organize)
        self.btn_organize.pack(side="left", padx=(8, 0))
        self.btn_del_img = ctk.CTkButton(r2, text="🗑 删除选中图片", width=116, height=30, fg_color="#4a3535", hover_color="#5a4141",
                                         border_width=1, border_color="#5a4141", text_color="#e0b0b0", corner_radius=6,
                                         font=ui_font(FONT_HINT), command=self._do_delete_image)
        self.btn_del_img.pack(side="left", padx=(8, 0))
        self.status_var = tk.StringVar(value="就绪")
        ctk.CTkLabel(tools, textvariable=self.status_var, font=ui_font(FONT_HINT), text_color=HINT, anchor="w").pack(fill="x", padx=12, pady=(0, 8))

        self.win.protocol("WM_DELETE_WINDOW", self._close)

    # ---------- 数据 ----------
    def refresh(self):
        if self._current is not None and self._current in self._dirty:
            if messagebox.askyesno("标签编辑器", "当前标签有未保存的修改，是否先保存？"):
                self._save_current(quiet=True)
            else:
                self._dirty.discard(self._current)
        self.records = core.list_dataset_images(self.train_dir)
        self._thumbs = {}
        self._dirty = set()
        self._current = None
        self.listbox.delete(0, "end")
        for it in self.records:
            rel = it["rel"]
            label = (rel + " / " if rel and rel != "." else "") + os.path.basename(it["img"])
            self.listbox.insert("end", label)
        self.list_title.configure(text=f"图片列表（{len(self.records)} 张）")
        if os.path.isdir(self.train_dir):
            try:
                n_sub = sum(1 for f in os.listdir(self.train_dir)
                            if os.path.isdir(os.path.join(self.train_dir, f)) and re.match(r"^\d+_", f))
            except Exception:
                n_sub = 0
            sub_txt = f"，{n_sub} 个 repeats 子目录" if n_sub else ""
            self.info_var.set(f"数据集: {self.train_dir}  |  {len(self.records)} 张图{sub_txt}")
        else:
            self.info_var.set(f"数据集: {self.train_dir}（目录不存在）")
            self._set_status("还没有预处理数据：请先在主界面执行【数据预处理】或【一键开始训练】")
        self.preview.configure(text="（选中左侧图片后显示缩略图）", image="")
        self.fname_var.set("")
        self.caption.delete("1.0", "end")

    def _on_select(self, _e=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if idx >= len(self.records):
            return
        if self._current is not None and self._current in self._dirty:
            if messagebox.askyesno("标签编辑器", "当前标签有未保存的修改，是否先保存？"):
                self._save_current(quiet=True)
            else:
                self._dirty.discard(self._current)
        self._current = idx
        it = self.records[idx]
        disp = os.path.join(it["rel"], os.path.basename(it["img"])) if it["rel"] else os.path.basename(it["img"])
        self.fname_var.set(disp)
        self.caption.delete("1.0", "end")
        self.caption.insert("1.0", it["caption"])
        self._load_preview(it["img"])
        self._dirty.discard(idx)

    def _load_preview(self, img_path):
        try:
            im = Image.open(img_path).convert("RGB")
            im.thumbnail((220, 140))
            photo = ImageTk.PhotoImage(im)
            self._thumbs[img_path] = photo
            # 缩略图缓存上限：只保留最近 50 张，超出释放旧 PhotoImage（避免 GDI 对象累积）
            try:
                if len(self._thumbs) > 50:
                    for _k in list(self._thumbs)[:-50]:
                        self._thumbs.pop(_k, None)
            except Exception:
                pass
            self.preview.configure(image=photo, text="")
        except Exception:
            self.preview.configure(image="", text="（无法预览）")

    def _mark_dirty(self, _e=None):
        if self._current is not None:
            self._dirty.add(self._current)
            self._set_status("当前标签已修改，记得点「保存当前标签」")

    def _save_current(self, quiet=False):
        if self._current is None:
            return
        it = self.records[self._current]
        text = self.caption.get("1.0", "end").strip()
        try:
            core.save_caption(it["txt"], text)
            it["caption"] = text
            self._dirty.discard(self._current)
            if not quiet:
                self._set_status(f"已保存: {os.path.basename(it['txt'])}")
            self._log_app(f"[标签] 已保存 {it['txt']}")
        except Exception as e:
            messagebox.showerror("保存失败", f"写入失败：{e}")

    def _do_delete_image(self):
        """删除当前选中的图片及其同名 txt/npz（把质量差的训练图移出数据集）。"""
        if self._current is None:
            messagebox.showinfo("删除图片", "请先在左侧选中要删除的图片。")
            return
        it = self.records[self._current]
        disp = os.path.join(it["rel"], os.path.basename(it["img"])) if it["rel"] else os.path.basename(it["img"])
        if not messagebox.askyesno("删除图片", f"确定从数据集删除这张图吗？\n\n{disp}\n\n同时会删除它的标签文件（.txt）。此操作不可恢复。"):
            return
        removed = []
        for cand in (it["img"], it["txt"]):
            try:
                if os.path.isfile(cand):
                    os.remove(cand)
                    removed.append(os.path.basename(cand))
            except Exception as e:
                messagebox.showerror("删除失败", f"{cand}\n{e}")
                return
        # 同名 npz 缓存一并删除
        stem = os.path.splitext(it["img"])[0]
        for fn in list(os.listdir(os.path.dirname(it["img"]))):
            if fn.startswith(os.path.basename(stem)) and fn.lower().endswith(".npz"):
                try:
                    os.remove(os.path.join(os.path.dirname(it["img"]), fn))
                except Exception:
                    pass
        self._set_status(f"已删除：{'、'.join(removed)}")
        self._log_app(f"[标签] 已删除 {disp}" + ("（含 npz 缓存）" if removed else ""))
        self._dirty.discard(self._current)
        self._current = None
        self.refresh()

    # ---------- 批量操作 ----------
    def _do_remove(self):
        tags = self.del_entry.get().strip()
        if not tags:
            messagebox.showinfo("批量删除标签", "请先输入要删除的标签（逗号分隔）。")
            return
        self._begin_batch("正在批量删除标签…（批量操作会覆盖未保存的手动修改）")
        try:
            files, removed = core.batch_remove_tags(self.train_dir, tags, logf=self._log_app)
            msg = f"批量删除完成：修改 {files} 个文件，删除 {removed} 个标签。"
            self._set_status(msg)
            self._log_app("[标签] " + msg)
        except Exception as e:
            messagebox.showerror("批量删除失败", str(e))
        finally:
            self._end_batch()

    def _do_replace(self):
        find = self.rep_find.get().strip()
        if not find:
            messagebox.showinfo("批量替换", "请先输入要替换的原标签。")
            return
        to = self.rep_to.get().strip()
        self._begin_batch("正在批量替换标签…（批量操作会覆盖未保存的手动修改）")
        try:
            files = core.batch_replace_tags(self.train_dir, find, to, logf=self._log_app)
            msg = f"批量替换完成：修改 {files} 个文件（{find} → {to or '（删除）'}）。"
            self._set_status(msg)
            self._log_app("[标签] " + msg)
        except Exception as e:
            messagebox.showerror("批量替换失败", str(e))
        finally:
            self._end_batch()

    def _do_pin(self):
        params = self.app._collect_params()
        trigger = (params.get("trigger") or "").strip()
        if not trigger:
            messagebox.showinfo("置顶 Trigger", "当前模式的 Trigger 触发词为空，无法置顶。\n请先回主界面填写触发词。")
            return
        self._begin_batch("正在把 Trigger 置顶…")
        try:
            n = core.pin_trigger_to_labels(self.train_dir, trigger, logf=self._log_app)
            msg = f"Trigger「{trigger}」已置顶到 {n} 个标签文件第一行。"
            self._set_status(msg)
            self._log_app("[标签] " + msg)
        except Exception as e:
            messagebox.showerror("置顶失败", str(e))
        finally:
            self._end_batch()

    def _do_organize(self):
        params = self.app._collect_params()
        repeats = params.get("repeats", 5)
        default_name = (params.get("trigger") or "").strip() or "dataset"
        dlg = ctk.CTkInputDialog(
            text=f"输入概念名（会生成子目录 {repeats}_{default_name}，把根目录平铺的图片/标签移进去）：\n\n"
                 "提示：repeats_名称 是秋叶式目录结构，repeats 表示这组图片的训练重复次数，名称随意（英文/中文都行）。",
            title="整理为 repeats_名称 结构")
        name = dlg.get_input()
        if name is None or not name.strip():
            return
        self._begin_batch("正在整理数据集…")
        try:
            moved, target = core.organize_dataset_repeats(self.train_dir, repeats, name.strip())
            msg = f"已整理：把 {moved} 个文件移入 {os.path.basename(target)}（repeats={repeats}）。"
            self._set_status(msg)
            self._log_app("[标签] " + msg)
            self.refresh()
        except Exception as e:
            messagebox.showerror("整理失败", str(e))
        finally:
            self._end_batch()

    def _show_stats(self):
        stats = core.tag_frequency(self.train_dir, top_n=300)
        if not stats:
            messagebox.showinfo("标签统计", "数据集里还没有标签。")
            return
        w = ctk.CTkToplevel(self.win)
        w.title("标签统计")
        w.geometry("580x660")
        w.transient(self.win)
        w.configure(fg_color=BG)
        ctk.CTkLabel(w, text="标签出现频率（点击「删除」可从全部标签中移除该词）", font=ui_font(FONT_BODY), text_color=TITLE_C).pack(anchor="w", padx=16, pady=(14, 6))
        scroll = ctk.CTkScrollableFrame(w, fg_color=CARD, corner_radius=8)
        scroll.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        for tag, cnt in stats:
            row = ctk.CTkFrame(scroll, fg_color="transparent"); row.pack(fill="x", padx=6, pady=2)
            ctk.CTkLabel(row, text=f"{cnt:4d} 次", font=ui_font(FONT_HINT), text_color=ACC, width=64, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=tag, font=ui_font(FONT_BODY), text_color=TXT, anchor="w").pack(side="left", padx=(6, 0))
            _zd = self.get_tagdict()
            _zh = _zd.to_zh(tag) if _zd else None
            if _zh and _zh != tag:
                ctk.CTkLabel(row, text="/ " + _zh, font=ui_font(FONT_HINT), text_color=HINT, anchor="w").pack(side="left", padx=(2, 0))
            ctk.CTkButton(row, text="删除", width=56, height=24, fg_color="#4a3535", hover_color="#5a4141",
                          corner_radius=6, font=ui_font(FONT_HINT),
                          command=lambda t=tag, win=w: self._stats_delete(t, win)).pack(side="right")

    def _stats_delete(self, tag, win):
        try:
            files, removed = core.batch_remove_tags(self.train_dir, tag, logf=self._log_app)
            self._log_app(f"[标签] 从统计窗口删除「{tag}」：{files} 个文件，{removed} 个标签")
        except Exception as e:
            messagebox.showerror("删除失败", str(e))
            return
        try:
            win.destroy()
        except Exception:
            pass
        self._set_status(f"已删除标签「{tag}」")
        self._show_stats()

    # ---------- 辅助 ----------
    def _begin_batch(self, status):
        self._dirty.clear()
        self._set_status(status)
        for b in (self.btn_del, self.btn_rep, self.btn_pin, self.btn_stats, self.btn_dict, self.btn_organize, self.btn_del_img, self.btn_save_one):
            try:
                b.configure(state="disabled")
            except Exception:
                pass
        self.win.update_idletasks()

    def _end_batch(self):
        for b in (self.btn_del, self.btn_rep, self.btn_pin, self.btn_stats, self.btn_dict, self.btn_organize, self.btn_del_img, self.btn_save_one):
            try:
                b.configure(state="normal")
            except Exception:
                pass
        self.refresh()

    def _set_status(self, text):
        self.status_var.set(str(text))

    def _log_app(self, text):
        try:
            self.app._log(str(text))
        except Exception:
            pass


    # ---------- 中英词典（v1 离线词条） ----------
    def get_tagdict(self):
        """惰性加载离线中英词典（编辑器/统计/词典窗共用，进程内只解析一次）。"""
        if self._tagdict is None:
            try:
                from kohya_core.tagging import TagDict
                self._tagdict = TagDict()
                self._log_app("[标签] 已加载离线中英词典：%d 条" % len(self._tagdict))
            except Exception as e:
                self._log_app("[标签] 加载离线词典失败：%s" % e)
                self._tagdict = False
        td = self._tagdict
        return td if td is not None and td is not False else None

    def insert_tag_to_caption(self, en_tag):
        """把词典选中的英文标签追加到当前图片标签末尾（已存在则跳过）。
        返回 True=已插入；False=未插入（无当前图 / 已存在 / 空输入）。"""
        tag = (en_tag or "").strip()
        if not tag:
            return False
        if self._current is None:
            messagebox.showinfo("中英词典", "请先在左侧选中一张图片，再插入标签。")
            return False
        cur = self.caption.get("1.0", "end")
        if any(p.strip().lower() == tag.lower() for p in re.split(r"[,，\n]", cur) if p.strip()):
            self._set_status("标签「%s」已存在，未重复添加" % tag)
            return False
        base = cur.rstrip("\n")
        new = (base + ", " + tag) if base.strip() else tag
        self.caption.delete("1.0", "end")
        self.caption.insert("1.0", new + "\n")
        self._mark_dirty()
        self._set_status("已把「%s」加入当前图片标签" % tag)
        self._log_app("[标签] 词典插入: %s" % tag)
        return True

    def _open_dict(self):
        """打开中英词典窗（翻译 / 补全 / 插入当前图）。"""
        try:
            if self._dict_win is not None:
                try:
                    self._dict_win.win.lift()
                    self._dict_win.win.focus_force()
                    return
                except Exception:
                    self._dict_win = None
            import gui.tag_tools
            self._dict_win = gui.tag_tools.TagLookupWindow(self.win, self)
        except Exception as e:
            messagebox.showerror("中英词典", "打开词典失败：%s" % e)

    def _open_dir(self):
        try:
            os.makedirs(self.train_dir, exist_ok=True)
            os.startfile(self.train_dir)
        except Exception as e:
            messagebox.showerror("打开文件夹", str(e))

    def _open_image(self):
        if self._current is None:
            return
        try:
            os.startfile(self.records[self._current]["img"])
        except Exception as e:
            messagebox.showerror("打开图片", str(e))

    def _close(self):
        if self._current is not None and self._current in self._dirty:
            if messagebox.askyesno("标签编辑器", "有未保存的标签修改，是否保存后再关闭？"):
                self._save_current(quiet=True)
        try:
            if getattr(self.app, "_label_editor", None) is self:
                self.app._label_editor = None
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass

def main():
    app = App()
    app.root.mainloop()
    return 0

if __name__ == "__main__":
    sys.exit(main())
