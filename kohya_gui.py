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
    if s == "Windows": return ("Segoe UI", "Microsoft YaHei")
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

FONT_TITLE = (*FONT_CHAIN, 14, "normal")
FONT_BODY  = (*FONT_CHAIN, 12, "normal")
FONT_HINT  = (*FONT_CHAIN, 10, "normal")
FONT_BADGE = (*FONT_CHAIN, 10, "normal")
FONT_LOG   = ("Consolas", "Microsoft YaHei", 11, "normal")

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
class App:
    def __init__(self):
        self.q = queue.Queue()
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
        self.log.insert("end", text + "\n")
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
        self.mon_canvas.create_text(10, 10, text="等待训练数据…", anchor="nw", fill="#7c8290", font=("Microsoft YaHei", 9))
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
            total = snap.get("total") or 0
            step = snap.get("step") or 0
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
            # 显存（N 卡）
            if self._gpu_info.get("vendor") == "nvidia":
                try:
                    r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total",
                                        "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3)
                    if r.returncode == 0:
                        parts = [p.strip() for p in r.stdout.strip().split(",")]
                        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                            self.mon_vram_var.set(f"显存: {int(parts[0])/1024:.1f}/{int(parts[1])/1024:.1f} GB")
                except Exception:
                    pass
            self._draw_loss_curve(snap.get("loss_history") or [])
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
                              fill="#7c8290", font=("Microsoft YaHei", 9))
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
                          fill="#9aa0ad", font=("Microsoft YaHei", 8))
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
        self.sidebar = ctk.CTkFrame(self.root, fg_color=SIDEBG, width=230, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        logo = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo.pack(fill="x", padx=16, pady=(20, 12))
        ctk.CTkFrame(logo, width=26, height=26, fg_color="#4a5568", corner_radius=5).pack(side="left")
        ctk.CTkLabel(logo, text="Kohya-LoRA", font=ui_font(FONT_BODY), text_color=TXT).pack(side="left", padx=(9, 0))
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
        ctk.CTkLabel(row2, text="训练模式", font=ui_font(FONT_BODY), text_color=SUB).pack(side="left")
        self.mode_combo = ctk.CTkComboBox(row2, values=[core.MODE_LABELS[k] for k in core.MODE_KEYS], width=180, height=30,
                                          fg_color=CARD2, border_color=BORDER, button_color=CARD2, button_hover_color="#3a4150",
                                          text_color=TXT, font=ui_font(FONT_BODY), dropdown_font=ui_font(FONT_BODY),
                                          dropdown_fg_color=CARD2, dropdown_hover_color="#3a4150",
                                          command=lambda _e: self._on_mode_change())
        self.mode_combo.pack(side="left", padx=(10, 22))
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
        self.btn_at_install = ctk.CTkButton(self.h3_row, text="⚙ 安装第三引擎", width=108, height=30,
                                            fg_color="transparent", hover_color="#252a36", border_width=1,
                                            border_color=ACC, text_color=ACC, corner_radius=6, font=ui_font(FONT_BODY),
                                            command=self.cmd_install_at)
        self.btn_at_install.pack(side="left", padx=(4, 4))
        self.btn_h3_captions = ctk.CTkButton(self.h3_row, text="一键生成占位字幕", width=120, height=30,
                                             fg_color=CARD2, hover_color="#343a46", border_width=1, border_color=BORDER,
                                             text_color=TXT, corner_radius=6, font=ui_font(FONT_BODY),
                                             command=self.cmd_gen_h3_captions)
        self.btn_h3_captions.pack(side="left", padx=(4, 4))
        self.btn_h3_caption_ai = ctk.CTkButton(self.h3_row, text="✨ AI 自动描述", width=112, height=30,
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
        ctk.CTkLabel(logbar, text="运行日志", font=ui_font(FONT_TITLE), text_color=TITLE_C).pack(anchor="w", padx=26, pady=(8, 2))
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
        self.btn_check_update = ctk.CTkButton(head, text="🔄 检查更新", width=104, height=32,
                                              fg_color="transparent", hover_color="#252a36",
                                              border_width=1, border_color=BORDER, text_color=SUB,
                                              corner_radius=6, font=ui_font(FONT_BODY), command=self.cmd_check_update)
        self.btn_check_update.pack(side="right", padx=(0, 6))
        self._home_widgets.append(self.btn_check_update)
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
            if check == "krea2_models":
                return not core.krea2_missing_models()
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
                         width=100, anchor="w").pack(side="left")
            var = tk.StringVar(value="·")
            ctk.CTkLabel(row, textvariable=var, font=ui_font(FONT_HINT), text_color=HINT,
                         width=18, anchor="w").pack(side="left")
            btn = ctk.CTkButton(row, text=step["btn"], width=62, height=28, fg_color=CARD2,
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
            self._refresh_status()
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
        self._apply_project_data(data)
        self.current_project = name
        self.proj_title.configure(text="项目：" + name)
        self._show_work()
        self._refresh_status()
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
            },
        }

    def _apply_project_data(self, data):
        """把项目 json 恢复回界面。"""
        self._loading_project = True
        self._manual_override.clear()
        try:
            m = data.get("mode", "character")
            if m in core.MODE_LABELS:
                self.mode = m
                try:
                    self.mode_combo.set(core.MODE_LABELS[m])
                except Exception:
                    pass
            bt = data.get("base_type", "sdxl")
            if bt in core.BASE_TYPE_LABELS:
                self.base_type = bt
                try:
                    self.base_combo.set(core.BASE_TYPE_LABELS[bt])
                except Exception:
                    pass
            self.trigger_var.set(data.get("trigger") or "")
            self.reg_var.set(data.get("reg_dir") or "")
            self.raw_dir_var.set(data.get("raw_dir") or "")
            self.global_pos_var.set(data.get("global_pos") or "")
            self.global_neg_var.set(data.get("global_neg") or "")
            bm = data.get("base_model") or ""
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
            for k, v in p.items():
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
                          ("使用说明", 90, self.cmd_readme)]:
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
            pre = core.PRESETS[self.mode][self.base_type]
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
            pre = core.PRESETS[self.mode][self.base_type]
            for k, v in pre.items():
                if k not in self._manual_override:
                    self.param_vars.setdefault(k, tk.StringVar()).set(v)
        finally:
            self._applying_preset = False
        self._refresh_preset_summary()

    def _on_mode_change(self):
        self.mode = self._current_mode()
        self._apply_presets()
        self._update_mode_ui()
        try:
            self._render_guide()
        except Exception:
            pass
        self._schedule_autosave()

    def _update_mode_ui(self):
        try:
            self.home_title.configure(text=core.MODE_LABELS.get(self.mode, self.mode) + " 训练")
        except Exception:
            pass
        try:
            if self.mode == "video":
                _hint = core.TRIGGER_HINT_VIDEO
            elif self.mode in ("qwen_image", "zimage"):
                _hint = core.TRIGGER_HINT_AT
            elif self.mode == "krea2":
                _hint = core.TRIGGER_HINT_KREA2
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
                if self.mode in ("krea2", "video", "qwen_image", "zimage"):
                    _tef.grid_remove()   # Krea2/视频/AI图像：文本编码器不训练，该参数无效
                else:
                    try:
                        _tef.grid()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            _hide_base = self.mode in ("krea2", "video", "qwen_image", "zimage")
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
                if self.mode == "krea2":
                    self._refresh_krea2_status()
                    self.krea2_row.pack(fill="x", pady=(8, 0))
                else:
                    try:
                        self.krea2_row.pack_forget()
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                if self.mode == "video":
                    self._refresh_h3_status()
                    self.h3_row.pack(fill="x", pady=(8, 0))
                else:
                    try:
                        self.h3_row.pack_forget()
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
            for _k in ("repeats", "max_epochs", "resolution"):
                _f = _adv.get(_k)
                if _f is not None:
                    try:
                        if _use_steps:
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
            self.base_combo.set(core.BASE_TYPE_LABELS.get(self.base_type, items[0]))
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
                self._set_base_type(bt)
                self._log(f"[底模] 已选择 {os.path.basename(payload)}（{core.BASE_TYPE_LABELS[bt]}）")
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

    def cmd_readme(self):
        self._show_help_window()

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
    # ============ 高级参数 ============
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
            "trigger": self.trigger_var.get().strip(),
            "reg_dir": self.reg_var.get().strip() or None,
            "raw_dir": self.raw_dir_var.get().strip(),
            "base_model": self.base_model_var.get().strip() or None,
            "rank": int(float(_getv("rank", "12"))),
            "alpha": int(float(_getv("alpha", "6"))),
            "unet_lr": float(_getv("unet_lr", "3e-4")),
            "te_lr": float(_getv("te_lr", "1.5e-4")),
            "repeats": int(float(_getv("repeats", "5"))),
            "max_epochs": int(float(_getv("max_epochs", "8"))),
            "resolution": int(float(_getv("resolution", "1024" if self.mode == "krea2" else str(core.RESOLUTIONS.get(self.base_type, 512))))),
            "video_steps": int(float(_getv("video_steps", "2000"))),
            "train_text_encoder": not self.unet_only_var.get(),
            "style_caption": getattr(self, "style_caption_var", tk.StringVar()).get().strip(),
            "global_pos": self.global_pos_var.get().strip(),
            "global_neg": self.global_neg_var.get().strip(),
            "amd_mode": bool(self.amd_var.get()),
            "train_env": self.train_env_var.get().strip() or None,
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
                self.at_model_var.set(f"{label}：模型未下载（首次训练自动下载 {info.get('size','')}，国内镜像）")
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
            "· 模型会自动下载到 HuggingFace 缓存目录（国内镜像 hf-mirror），首次训练时自动完成，无需手动下载。\n"
            "· 训练用基础版模型；出图可配合 Turbo 等加速版使用。\n\n"
            "· 训练数据：选 15~30 张同一人物/风格的图片，自动过滤/裁切/打标签。"
        )
        messagebox.showinfo(core.APP_NAME, msg)

    def _ensure_at_image_ready(self):
        """Qwen-Image / Z-Image 模式训练前检查：第三引擎已装 + 数据集有图。模型首次训练自动下载。"""
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
            _miss = "、".join(k for k in ("dit", "te", "video_vae") if not _files.get(k))
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
            "⚠ 实验性功能：需要 24G+ NVIDIA 显存，模型文件 40GB+，训练一次要数小时。\n\n"
            "▍第 1 步：安装第三引擎\n"
            "· 切到「🎬 视频LoRA（MiniMax H3）」模式 → 点「⚙ 安装第三引擎」\n"
            "· 自动创建独立环境（不影响现有画风/人物/Krea2）\n"
            "· 下载 PyTorch cu130 约 3GB；需较新 NVIDIA 驱动（570+）\n"
            "· 装完状态行变「第三引擎：就绪」\n\n"
            "▍第 2 步：下载 H3 模型（3~4 个文件，放进 models/minimax_h3/）\n"
            f"1) {h3['dit'][0]} —— {h3['dit'][1]}\n"
            f"   国内镜像：{h3['dit'][2]}\n"
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
            "A: H3 是 33B 大模型，16G 以下不建议训练（会 OOM 或极慢）；24G 是推荐起点。\n\n"
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
                videos, _t, _n = core.scan_video_dataset(params.get("raw_dir"))
                stats = {"ok": len(videos), "skipped_existing": 0}
                self.q.put(("AUTO_CONFIRM", params, stats, len(videos)))
                return
            pp_mode = "character" if params.get("mode") in ("krea2", "qwen_image", "zimage") else params["mode"]
            core.preprocess(
                self._log, input_dir=params["raw_dir"],
                size=int(params.get("resolution") or (core.KREA2_RESOLUTION if params.get("mode") == "krea2" else core.RESOLUTIONS.get(params["base_type"], 512))),
                mode=pp_mode, trigger=params["trigger"],
                reg_dir=params["reg_dir"], repeats=params["repeats"],
                dedup=True, wd14=True, square_crop=True,
                min_size=256, blur_threshold=30.0, report=report,
                keep_tokens=None, project=self.current_project,
                style_caption=params.get("style_caption") or "")
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
        else:
            if not params["base_model"]:
                messagebox.showwarning(core.APP_NAME, "请先选择底模（步骤③）。")
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
            else:
                core.train(self._log, base_model=params["base_model"], mode=params["mode"],
                           params=params, vram_gb=vram, resume_from=resume, progress=self._train_mon)
            self._log("[OK] 训练完成，模型在 output 文件夹")
        except core.StopRequested:
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
        else:
            if not params["base_model"]:
                messagebox.showwarning(core.APP_NAME, "请先选择底模（步骤③）。")
                return
        if self.mode == "character" and not params["trigger"]:
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
            pp_mode = "character" if params.get("mode") == "krea2" else params["mode"]
            core.preprocess(
                self._log, input_dir=params["raw_dir"],
                size=int(params.get("resolution") or (core.KREA2_RESOLUTION if params.get("mode") == "krea2" else core.RESOLUTIONS.get(params["base_type"], 512))),
                mode=pp_mode, trigger=params["trigger"],
                reg_dir=params["reg_dir"], repeats=params["repeats"],
                dedup=True, wd14=True, square_crop=True,
                min_size=256, blur_threshold=30.0, report=report,
                keep_tokens=None, project=self.current_project,
                style_caption=params.get("style_caption") or "")
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

        # 检测系统 Python，动态生成 wheel URL（cp311 / cp312）
        sys_vers = core.detect_system_pythons()
        py_ver = "3.12" if "3.12" in sys_vers else ("3.11" if "3.11" in sys_vers else None)
        cp = "cp311" if py_ver == "3.11" else "cp312"
        if sys_vers:
            py_line = "检测到系统 Python：" + "、".join(sys_vers)
            if py_ver is None:
                py_line += "（⚠ AMD 官方仅支持 3.11/3.12，请安装 Python 3.12）"
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

            def work():
                try:
                    core.install_amd_rocm(venv, self._log)
                    core.install_amd_torch(venv, self._log)
                    core.install_amd_deps(venv, self._log)
                    okv, ver, avail = core.verify_amd_torch(venv)
                    self.root.after(0, lambda: self._amd_install_done(okv and avail, ver, avail))
                except core.StopRequested:
                    self.root.after(0, lambda: self._amd_install_done(False, "已手动停止", False))
                except Exception as e:
                    _err = str(e)
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
            self._log(f"[ERROR] AMD 依赖安装失败：{info}")
            messagebox.showerror(
                core.APP_NAME,
                f"AMD 依赖安装失败：\n{info}\n\n"
                "可能原因：\n"
                "· 网络中断/镜像慢 → 可挂代理后点「重新检查」再试，或点「复制命令」手动装\n"
                "· 权限不足 → 训练环境在 %APPDATA% 下一般无需管理员；若仍报权限错误，\n"
                "   请确认 %APPDATA%\\KohyaLoraTool\\venv_amd 目录可写")

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

    def _warn_no_nvidia(self):
        """显卡兼容检查：N 卡直接放行；AMD 卡走兼容模式；其他保持原警告。返回 True=继续。"""
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
        elif params.get("mode") == "krea2":
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
        state = core.find_latest_state(_odir, output_name)
        if state:
            return state if messagebox.askyesno(
                core.APP_NAME,
                f"发现上次中断留下的训练进度快照：\n{os.path.basename(state)}\n\n"
                "要不要从上次断点继续训练？（选否则从头重新训练）") else None
        return None

    def _confirm_training(self, params, resume=None):
        if params.get("mode") == "krea2":
            files = core.krea2_model_files()
            msg = (
                "即将开始 Krea 2 训练，请确认以下参数：\n\n"
                f"模式        : {core.MODE_LABELS.get('krea2')}\n"
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
                f"模型        : {_info.get('model_id', '？') if _info else '？'}\n"
                f"rank / alpha: {params['rank']} / {params['alpha']}\n"
                f"学习率      : {params['unet_lr']}\n"
                f"训练步数    : {params.get('video_steps', 2000)}\n"
                f"Trigger     : {params['trigger'] or '（未填写）'}"
            )
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
        """Krea2 模型状态（顶部状态行）。"""
        try:
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
        for b in (self.btn_del, self.btn_rep, self.btn_pin, self.btn_stats, self.btn_organize, self.btn_del_img, self.btn_save_one):
            try:
                b.configure(state="disabled")
            except Exception:
                pass
        self.win.update_idletasks()

    def _end_batch(self):
        for b in (self.btn_del, self.btn_rep, self.btn_pin, self.btn_stats, self.btn_organize, self.btn_del_img, self.btn_save_one):
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
