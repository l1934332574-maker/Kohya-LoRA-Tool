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
import functools
import traceback
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox

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
    def _layout(_e=None):
        cw = inner.winfo_reqwidth()
        ch = inner.winfo_reqheight()
        cw_avail = canvas.winfo_width() - 2 * pad
        if cw_avail > 20:
            cw = max(cw, cw_avail)
        if cw <= 10 or ch <= 10:
            return
        img = _make_shadow(cw, ch, corner_radius, shadow, alpha, offset[0], offset[1], blur, pad)
        canvas.delete("shd")
        canvas.create_image(0, 0, image=img, anchor="nw", tags="shd")
        canvas.tag_lower("shd")
        canvas.itemconfigure(wid, width=cw)
        canvas.configure(height=ch + 2 * pad)
        canvas._shadow_img = img
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
        self.ui_proc = None

        self.root = ctk.CTk()
        self.root.title(core.APP_NAME + " · 新界面")
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
        self._badge_widgets = []
        self._main_widgets = []

        self._build_ui()
        self._scan_base_models()
        self._apply_presets()
        self._update_mode_ui()
        self._refresh_status()
        self.root.after(100, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

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
            elif kind == "AUTO_CONFIRM":
                self._handle_auto_confirm(item[1], item[2], item[3] if len(item) > 3 else None)
            elif kind == "DL_PROGRESS":
                self._dl_progress_ui(item[1], item[2])
            elif kind == "DL_DONE":
                self._handle_dl_done(item[1], item[2])

    def _start_worker(self, fn, title):
        self._set_busy(True)
        self._log("开始：" + title)
        threading.Thread(target=fn, daemon=True).start()

    def _set_busy(self, v):
        self.busy = v
        try:
            self.btn_one_click.configure(state=("disabled" if v else "normal"))
        except Exception:
            pass

    def _on_close(self):
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
        ctk.CTkLabel(self.sidebar, text="🎓 新手引导（按顺序做）", font=ui_font(FONT_HINT),
                     text_color=SUB).pack(anchor="w", padx=16, pady=(0, 4))

        self._guide_dots = {}
        def _guide(key, label, var, btn_text, cmd):
            row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=3)
            dot = ctk.CTkFrame(row, width=10, height=10, corner_radius=5, fg_color="#4a3636")
            dot.pack(side="left", padx=(2, 8), pady=9)
            self._guide_dots[key] = dot
            ctk.CTkLabel(row, text=label, font=ui_font(FONT_BODY), text_color=TXT, width=92, anchor="w").pack(side="left")
            ctk.CTkLabel(row, textvariable=var, font=ui_font(FONT_HINT), text_color=HINT, width=26, anchor="w").pack(side="left")
            ctk.CTkButton(row, text=btn_text, width=56, height=28, fg_color=CARD2, hover_color="#343a46",
                          border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                          font=ui_font(FONT_HINT), command=cmd).pack(side="right")

        self.guide_env_var = tk.StringVar(value="未装")
        self.guide_kohya_var = tk.StringVar(value="未装")
        self.guide_base_var = tk.StringVar(value="未选")
        self.guide_raw_var = tk.StringVar(value="未选")
        _guide("env", "① 环境准备", self.guide_env_var, "去准备", self.cmd_env)
        _guide("kohya", "② 安装训练内核", self.guide_kohya_var, "去安装", self.cmd_install)
        _guide("base", "③ 选择底模+模式", self.guide_base_var, "去选底模", self.cmd_pick_base)
        _guide("raw", "④ 选择图片文件夹", self.guide_raw_var, "去选文件夹", self.cmd_pick_raw)

        self.btn_one_click = ctk.CTkButton(self.sidebar, text="🚀 一键开始训练", height=42,
                                           fg_color=CARD2, hover_color="#343a46", corner_radius=8,
                                           font=ui_font(FONT_BODY), state="disabled",
                                           command=self.cmd_one_click_train)
        self.btn_one_click.pack(fill="x", padx=14, pady=(14, 2))
        self.btn_one_click_hint = ctk.CTkLabel(self.sidebar, text="完成 ①②③④ 后自动点亮", font=ui_font(FONT_HINT), text_color=HINT)
        self.btn_one_click_hint.pack(anchor="w", padx=16, pady=(0, 4))

        sp = ctk.CTkFrame(self.sidebar, fg_color="transparent"); sp.pack(expand=True)
        ctk.CTkLabel(self.sidebar, text="外观主题", font=ui_font(FONT_HINT), text_color=HINT).pack(anchor="w", padx=18)
        self.theme_menu = ctk.CTkOptionMenu(
            self.sidebar, values=["跟随系统", "深色", "浅色"], width=170, height=28,
            fg_color=CARD2, button_color=CARD2, button_hover_color="#3a4150",
            text_color=SUB, font=ui_font(FONT_HINT), dropdown_font=ui_font(FONT_HINT),
            dropdown_fg_color=CARD2, dropdown_hover_color="#3a4150", command=self._switch_theme)
        self.theme_menu.pack(padx=16, pady=(2, 20))

        # ---------- 右侧 ----------
        right = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        right.pack(side="left", fill="both", expand=True)

        # 顶部条：标题 + 模式切换 + 底模 + 状态徽章
        top = ctk.CTkFrame(right, fg_color="transparent")
        top.pack(fill="x", padx=26, pady=(18, 0))
        row1 = ctk.CTkFrame(top, fg_color="transparent"); row1.pack(fill="x")
        self.home_title = ctk.CTkLabel(row1, text="人物角色 LoRA 训练", font=ui_font(FONT_TITLE), text_color=TITLE_C)
        self.home_title.pack(side="left")
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
        ctk.CTkLabel(row2, text="基础底模", font=ui_font(FONT_BODY), text_color=SUB).pack(side="left")
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
        self.preset_summary = ctk.CTkLabel(top, text="", font=ui_font(FONT_HINT), text_color=SUB, anchor="w")
        self.preset_summary.pack(fill="x", pady=(8, 0))

        # 可滚动主区
        self.scroll = ctk.CTkScrollableFrame(right, fg_color=BG, corner_radius=0)
        self.scroll.pack(fill="both", expand=True, padx=26, pady=(14, 0))
        try:
            self.scroll._parent_canvas.configure(yscrollincrement=2)  # 降低滚轮单格滚动距离，更平滑
        except Exception:
            pass
        self._build_main_cards()

        # 底部独立日志面板
        logbar = ctk.CTkFrame(right, fg_color="#16181e", corner_radius=0)
        logbar.pack(fill="x", side="bottom", pady=(8, 0))
        ctk.CTkLabel(logbar, text="运行日志", font=ui_font(FONT_TITLE), text_color=TITLE_C).pack(anchor="w", padx=26, pady=(8, 2))
        self.log = ctk.CTkTextbox(logbar, height=150, fg_color="#14161c", text_color="#b6bcc9", corner_radius=6,
                                  border_width=1, border_color=BORDER, font=ui_font(FONT_LOG))
        self.log.pack(fill="x", padx=26, pady=(0, 14))
        for tag, col in [("ok", LOG_OK), ("warn", LOG_WARN), ("err", LOG_ERR), ("info", LOG_INFO), ("train", LOG_TRAIN)]:
            self.log.tag_config(tag, foreground=col)
        self._log("欢迎使用 Kohya-LoRA 一键训练工具")
        self._log("按左侧新手引导 ①②③④ 顺序操作，最后点下方「一键开始训练」")
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
        ctk.CTkLabel(card1, text="① 准备图片数据", font=ui_font(FONT_TITLE), text_color=TITLE_C).pack(anchor="w", padx=22, pady=(14, 8))
        r1 = ctk.CTkFrame(card1, fg_color="transparent"); r1.pack(fill="x", padx=22, pady=(0, 4))
        ctk.CTkLabel(r1, text="原始图片文件夹", font=ui_font(FONT_BODY), text_color=SUB).pack(side="left")
        self.raw_entry = ctk.CTkEntry(r1, width=400, height=30, textvariable=self.raw_dir_var,
                                      fg_color=CARD2, border_color=BORDER, text_color=TXT, font=ui_font(FONT_BODY))
        self.raw_entry.pack(side="left", padx=(12, 8))
        self.btn_pick_raw = ctk.CTkButton(r1, text="浏览…", width=76, height=30, fg_color=CARD2, hover_color="#343a46",
                                          border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                                          font=ui_font(FONT_BODY), command=self.cmd_pick_raw)
        self.btn_pick_raw.pack(side="left")
        ctk.CTkLabel(card1, text="人物模式建议 15~30 张同一人物；画风模式建议 20~60 张不同人物。图片越清晰越好",
                     font=ui_font(FONT_HINT), text_color=HINT).pack(anchor="w", padx=22, pady=(2, 14))

        # 卡片2：触发词 + 正则（人物模式）
        c2, card2 = create_soft_shadow_card(s); c2.pack(fill="x", pady=(0, 10))
        self._main_widgets += [c2, card2]
        self.trig_card = card2
        ctk.CTkLabel(card2, text="② 设置触发词（人物模式）", font=ui_font(FONT_TITLE), text_color=TITLE_C).pack(anchor="w", padx=22, pady=(14, 8))
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
        for t, w, cmd in [("数据预处理", 110, self.cmd_preprocess), ("一键训练", 96, self.cmd_train),
                          ("打开输出文件夹", 112, self.cmd_open_output), ("使用说明", 90, self.cmd_readme)]:
            ctk.CTkButton(btns, text=t, width=w, height=38, fg_color=CARD2, hover_color="#343a46",
                          border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                          font=ui_font(FONT_BODY), command=cmd).pack(side="left", padx=5)

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
        _badge("● RTX 4070 · 8GB" if sts.get("gpu") else "● 未检测到 N 卡", HW_BG, HW_TX)
        self.guide_env_var.set("已装" if sts.get("git") and sts.get("python") else "未装")
        self.guide_kohya_var.set("已装" if sts.get("kohya_ok") else "未装")
        def _dot(key, ok_):
            try:
                self._guide_dots[key].configure(fg_color=("#5c7c66" if ok_ else "#6e4545"))
            except Exception:
                pass
        _dot("env", bool(sts.get("git") and sts.get("python")))
        _dot("kohya", bool(sts.get("kohya_ok")))
        _dot("base", bool(self.base_model_var.get()))
        _dot("raw", bool(self.raw_dir_var.get()))
        self._refresh_one_click_state()

    def _refresh_status(self):
        try:
            self._build_badges()
        except Exception:
            pass

    # ============ 环境 / 安装 ============
    def cmd_env(self):
        self._start_worker(self._env_worker, "环境准备（Git / Python）")

    def _env_worker(self):
        try:
            core.ensure_prereqs(self._log)
            self._log("[OK] Git / Python 环境就绪")
        except Exception as e:
            self._log(f"[ERROR] 环境准备失败：{e}")
            traceback.print_exc()
        finally:
            self.q.put("__DONE__")
            self.q.put(("STATUS",))

    def cmd_install(self):
        self._start_worker(self._install_worker, "安装 Kohya-SS 训练内核")

    def _install_worker(self):
        try:
            core.install_kohya(self._log)
            self._log("[OK] Kohya-SS 安装完成")
        except Exception as e:
            self._log(f"[ERROR] 安装失败：{e}")
            traceback.print_exc()
        finally:
            self.q.put("__DONE__")
            self.q.put(("STATUS",))

    # ============ 模式 / 底模 ============
    def _switch_theme(self, val):
        key = "dark" if val != "浅色" else "light"
        ctk.set_appearance_mode("dark" if key == "dark" else "light")
        _apply_theme_globals(key)
        try:
            self.sidebar.destroy()
        except Exception:
            pass
        try:
            self.main.destroy()
        except Exception:
            pass
        self._main_widgets = []
        self._badge_widgets = []
        self._build_ui()
        self._scan_base_models()
        self._apply_presets()
        self._update_mode_ui()
        self._refresh_status()
        try:
            self.theme_menu.set(val)
        except Exception:
            pass

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
            self.preset_summary.configure(
                text=f"当前预设：rank {pre.get('rank')} · alpha {pre.get('alpha')} · "
                     f"学习率 {pre.get('unet_lr')} · 文本编码器学习率 {pre.get('te_lr')} · "
                     f"repeats {pre.get('repeats')} · 最大epoch {pre.get('max_epochs')} · {te}")
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

    def _update_mode_ui(self):
        try:
            self.home_title.configure(text=core.MODE_LABELS.get(self.mode, self.mode) + " 训练")
        except Exception:
            pass
        self.trigger_hint_var.set(core.TRIGGER_HINT_CHARACTER if self.mode == "character" else core.TRIGGER_HINT_STYLE)
        # 画风模式：隐藏触发词/正则卡片内容（用 pack_forget 显示/隐藏行）
        try:
            self.trigger_entry.master.master.master.configure(
                fg_color=CARD if self.mode == "character" else CARD)
        except Exception:
            pass

    def _scan_base_models(self):
        try:
            self._base_models = core.scan_base_models()
        except Exception:
            self._base_models = []
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
        self.base_combo.configure(values=items)
        try:
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
                self.guide_base_var.set("已选")
                self._log(f"[底模] 目录里找到 {core.BASE_TYPE_LABELS[payload]} 模型：{model[1]}")
            else:
                self.base_model_var.set("")
                self._log(f"[底模] {core.BASE_TYPE_LABELS[payload]} 目录里暂无模型")
                self.root.after(60, lambda: self._ask_download_or_open(payload))
        else:
            self.base_model_var.set(payload)
            self.guide_base_var.set("已选")
            bt = core.detect_base_type(payload)
            if bt in ("sd15", "sdxl"):
                self._set_base_type(bt)
                self._log(f"[底模] 已选择 {os.path.basename(payload)}（{core.BASE_TYPE_LABELS[bt]}）")
            else:
                self._log(f"[底模] 已选择 {os.path.basename(payload)}（类型待确认）")

    def _set_base_type(self, bt):
        if bt not in ("sd15", "sdxl"):
            return
        self.base_type = bt
        self._apply_presets()

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
        self.guide_base_var.set("已选")
        self._refresh_one_click_state()
        try:
            self._guide_dots["base"].configure(fg_color="#5c7c66")
        except Exception:
            pass
        bt = core.detect_base_type(f)
        if bt in ("sd15", "sdxl"):
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
        d = filedialog.askdirectory(title="选择原始图片文件夹")
        if d:
            self.raw_dir_var.set(d)
            self.guide_raw_var.set("已选")
            self._refresh_one_click_state()
            try:
                self._guide_dots["raw"].configure(fg_color="#5c7c66")
            except Exception:
                pass
            self._log(f"[预处理] 已选原始图片文件夹：{d}")

    def cmd_pick_reg(self):
        d = filedialog.askdirectory(title="选择正则数据集文件夹（人物模式）")
        if d:
            self.reg_var.set(d)
            self._log(f"[预处理] 已选正则数据集：{d}")

    def cmd_open_output(self):
        os.startfile(core.data_sub("output"))

    def cmd_readme(self):
        self._show_help_window()
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
                 ("文本编码器学习率", "te_lr"), ("repeats", "repeats"), ("最大 epoch", "max_epochs")]
        for i, (label, key) in enumerate(items):
            f = ctk.CTkFrame(g, fg_color="transparent"); f.grid(row=0, column=i, padx=10, pady=8, sticky="w")
            ctk.CTkLabel(f, text=label, font=ui_font(FONT_HINT), text_color=HINT).pack(anchor="w")
            v = self.param_vars.setdefault(key, tk.StringVar())
            ctk.CTkEntry(f, width=80, height=28, justify="center", textvariable=v,
                         fg_color=CARD2, border_color=BORDER, text_color=TXT, font=ui_font(FONT_BODY)).pack(pady=(3, 0))
        cb = ctk.CTkFrame(self.adv_body, fg_color="transparent"); cb.pack(anchor="w", pady=(4, 0))
        ctk.CTkCheckBox(cb, text="只训练 UNet（不训练文本编码器）", variable=self.unet_only_var,
                        fg_color=ACC, hover_color=ACC_H, text_color=TXT, font=ui_font(FONT_BODY),
                        command=self._refresh_preset_summary).pack(side="left")
        ctk.CTkButton(cb, text="↺ 恢复预设", width=92, height=26, fg_color="transparent", hover_color="#343a46",
                      border_width=1, border_color=BORDER, text_color=HINT, corner_radius=6,
                      font=ui_font(FONT_HINT), command=self.cmd_reset_presets).pack(side="left", padx=(20, 0))
        self.global_frame = ctk.CTkFrame(self.adv_body, fg_color="transparent")
        self.global_frame.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(self.global_frame, text="附加全局提示词（可选，训练时自动加到标签最前面，不写入图片 txt）",
                     font=ui_font(FONT_HINT), text_color=HINT).pack(anchor="w")
        gr = ctk.CTkFrame(self.global_frame, fg_color="transparent"); gr.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(gr, text="正向", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        ctk.CTkEntry(gr, width=320, height=28, textvariable=self.global_pos_var, fg_color=CARD2,
                     border_color=BORDER, text_color=TXT, font=ui_font(FONT_BODY)).pack(side="left", padx=(8, 14))
        ctk.CTkLabel(gr, text="负向", font=ui_font(FONT_HINT), text_color=HINT).pack(side="left")
        ctk.CTkEntry(gr, width=320, height=28, textvariable=self.global_neg_var, fg_color=CARD2,
                     border_color=BORDER, text_color=TXT, font=ui_font(FONT_BODY)).pack(side="left", padx=(8, 0))

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
            "train_text_encoder": not self.unet_only_var.get(),
            "global_pos": self.global_pos_var.get().strip(),
            "global_neg": self.global_neg_var.get().strip(),
        }

    # ============ 预处理 / 训练 ============
    def cmd_preprocess(self):
        params = self._collect_params()
        if not params["raw_dir"]:
            messagebox.showwarning(core.APP_NAME, "请先选择原始图片文件夹（步骤④）。")
            return
        self._start_worker(lambda: self._preprocess_worker(params), "数据预处理")

    def _preprocess_worker(self, params):
        try:
            report = os.path.join(os.environ.get("TEMP", "."), "kohya_auto_report.json")
            core.preprocess(
                self._log, input_dir=params["raw_dir"],
                size=core.RESOLUTIONS.get(params["base_type"], 512),
                mode=params["mode"], trigger=params["trigger"],
                reg_dir=params["reg_dir"], repeats=params["repeats"],
                dedup=True, wd14=True, square_crop=True,
                min_size=256, blur_threshold=30.0, report=report,
                keep_tokens=None)
            self._log("[OK] 预处理完成")
        except Exception as e:
            self._log(f"[ERROR] 预处理失败：{e}")
            traceback.print_exc()
        finally:
            self.q.put("__DONE__")

    def cmd_train(self):
        params = self._collect_params()
        if not params["base_model"]:
            messagebox.showwarning(core.APP_NAME, "请先选择底模（步骤③）。")
            return
        if not self._warn_no_nvidia():
            return
        resume = self._ask_resume(params)
        if not self._confirm_training(params, resume):
            return
        self._start_worker(lambda: self._train_worker(params, resume), "一键训练")

    def _train_worker(self, params, resume=None):
        try:
            vram = core.detect_vram_gb()
            core.train(self._log, base_model=params["base_model"], mode=params["mode"],
                       params=params, vram_gb=vram, resume_from=resume)
            self._log("[OK] 训练完成，模型在 output 文件夹")
        except Exception as e:
            self._log(f"[ERROR] 训练失败：{e}")
            traceback.print_exc()
        finally:
            self.q.put("__DONE__")

    def cmd_one_click_train(self):
        params = self._collect_params()
        if not params["raw_dir"]:
            messagebox.showwarning(core.APP_NAME, "请先选择原始图片文件夹（步骤④）。")
            return
        if not params["base_model"]:
            messagebox.showwarning(core.APP_NAME, "请先选择底模（步骤③）。")
            return
        if self.mode == "character" and not params["trigger"]:
            messagebox.showwarning(core.APP_NAME, "人物模式建议填写 Trigger 触发词（步骤②）。")
            return
        self._start_worker(lambda: self._one_click_worker(params), "一键开始训练")

    def _one_click_worker(self, params):
        try:
            report = os.path.join(os.environ.get("TEMP", "."), "kohya_auto_report.json")
            try:
                if os.path.isfile(report):
                    os.remove(report)
            except Exception:
                pass
            core.preprocess(
                self._log, input_dir=params["raw_dir"],
                size=core.RESOLUTIONS.get(params["base_type"], 512),
                mode=params["mode"], trigger=params["trigger"],
                reg_dir=params["reg_dir"], repeats=params["repeats"],
                dedup=True, wd14=True, square_crop=True,
                min_size=256, blur_threshold=30.0, report=report,
                keep_tokens=None)
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

    def _warn_no_nvidia(self):
        try:
            if core.detect_nvidia_gpu():
                return True
        except Exception:
            return True
        return messagebox.askyesno(
            core.APP_NAME,
            "本工具针对 NVIDIA 显卡优化。\n"
            "AMD/Intel 显卡在 Windows 下没有开箱即用支持，需要自行配置 ZLUDA/ROCm，存在兼容性风险。\n\n是否继续？")

    def _ask_resume(self, params):
        output_name = core.OUTPUT_NAMES.get(params["mode"], "anime_style_lora")
        state = core.find_latest_state(core.data_sub("output"), output_name)
        if state:
            return state if messagebox.askyesno(
                core.APP_NAME,
                f"发现上次中断留下的训练进度快照：\n{os.path.basename(state)}\n\n"
                "要不要从上次断点继续训练？（选否则从头重新训练）") else None
        return None

    def _confirm_training(self, params, resume=None):
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
            f"训练目标    : {'UNet + 文本编码器' if params['train_text_encoder'] else '仅 UNet'}\n"
            f"Trigger     : {params['trigger'] or '（未填写）'}\n"
            f"正则数据集  : {params['reg_dir'] or '（未使用）'}"
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
        resume = self._ask_resume(params)
        if not self._confirm_training(params, resume):
            self._set_busy(False)
            return
        self._start_worker(lambda: self._train_worker(params, resume), "训练")



    # ============ 底模下载（应用内 / 浏览器） ============
    def _download_choice_dialog(self, bt=None):
        bt = bt or self.base_type
        label = core.BASE_TYPE_LABELS.get(bt, "底模")
        fname, fsize = core.HF_MODEL_INFO.get(bt, ("模型文件", ""))
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("下载基础底模")
        dlg.geometry("460x240")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        ctk.CTkLabel(dlg, text=f"当前底模类型：{label}\n将下载：{fname}（{fsize}）\n保存到：{core.base_models_dir()}\n\n推荐「应用内下载」：带进度、断点续传、下完自动识别",
                     font=ui_font(FONT_BODY), text_color=TXT, justify="left", wraplength=420).pack(padx=20, pady=(18, 14))
        def _act(k):
            dlg.destroy()
            if k == "inapp":
                self.cmd_dl_in_app(bt)
            elif k == "web_fast":
                import webbrowser; webbrowser.open(core.MODELSCOPE_URLS.get(bt, core.HF_MIRROR_URL))
            elif k == "web_fallback":
                import webbrowser; webbrowser.open(core.HF_MIRROR_URLS.get(bt, core.HF_MIRROR_URL))
            elif k == "open":
                self.cmd_open_base_dir()
        bf = ctk.CTkFrame(dlg, fg_color="transparent"); bf.pack(pady=(0, 18))
        for t, k in [("⬇ 应用内下载（推荐）", "inapp"), ("🌐 浏览器极速", "web_fast"),
                     ("🔁 备用下载", "web_fallback"), ("📂 打开文件夹", "open")]:
            ctk.CTkButton(bf, text=t, width=104, height=30, fg_color=CARD2, hover_color="#343a46",
                          border_width=1, border_color=BORDER, text_color=TXT, corner_radius=6,
                          font=ui_font(FONT_HINT), command=lambda kk=k: _act(kk)).pack(side="left", padx=4)
        dlg.grab_set()

    def cmd_dl_in_app(self, bt=None):
        if _ModelDownloader is None:
            messagebox.showerror(core.APP_NAME, "下载模块加载失败，请使用「浏览器极速下载」。")
            return
        if getattr(self, "_downloading", False):
            messagebox.showinfo(core.APP_NAME, "已有下载任务在进行中，请先完成或取消。")
            return
        bt = bt or self.base_type
        url = core.MODELSCOPE_URLS.get(bt) or core.HF_MIRROR_URLS.get(bt) or core.HF_MIRROR_URL
        fname, fsize = core.HF_MODEL_INFO.get(bt, (os.path.basename(url), ""))
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
        try:
            self.dl_win.destroy()
        except Exception:
            pass
        if ok:
            self._log(f"[底模] 下载完成：{dest}")
            self._scan_base_models()
            messagebox.showinfo(core.APP_NAME, f"底模下载完成：\n{dest}\n\n已自动扫描并加入底模列表。")
        else:
            self._log("[ERROR] 底模下载失败或已取消")

    def cmd_dl_cancel(self):
        try:
            if self._dl is not None:
                self._dl.cancel()
        except Exception:
            pass



    def _refresh_one_click_state(self):
        ready = (self.guide_env_var.get() == "已装" and self.guide_kohya_var.get() == "已装"
                 and bool(self.base_model_var.get()) and bool(self.raw_dir_var.get()))
        try:
            self.btn_one_click.configure(state=("normal" if ready else "disabled"),
                                         fg_color=(ACC if ready else CARD2),
                                         hover_color=(ACC_H if ready else "#343a46"))
            self.btn_one_click_hint.configure(
                text=("✓ 准备就绪，点击开始训练" if ready else "完成 ①②③④ 后自动点亮"))
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
            "· 软件不附带底模，需要自己下载\n"
            "· 底模分两种：\n"
            "   · SD1.5：512 分辨率，显存要求低，画风偏基础\n"
            "   · SDXL：1024 分辨率，效果更好，推荐 16G 显存；8G 也能跑（记得勾「只训练 UNet」）\n"
            "· 下载的 .safetensors 文件放进 models/base 文件夹，点「↻ 刷新」自动识别\n\n"
            "▍第三步：填触发词（人物模式）\n"
            "· 触发词 = 角色的“名字”，训练后画图写上它就能唤出角色\n"
            "· 建议用网上很少见的英文单词（如 my_oc01），别用 girl 这种常见词\n\n"
            "▍第四步：开始训练\n"
            "· 左侧「一键开始训练」会自动完成预处理 + 训练\n"
            "· 训练完的 LoRA 在 output 文件夹\n\n"
            "❓ 常见问题\n\n"
            "Q：训练太慢 / 显存不够？\n"
            "A：高级参数里勾选「只训练 UNet」，省显存、速度快很多（8G 跑 SDXL 强烈建议勾）。\n\n"
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
            "   出图时选上它，人物模式用「触发词」开头，画风模式直接写画风描述。"
        )
        txt.insert("1.0", help_text)
        txt.configure(state="disabled")


def main():
    app = App()
    app.root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())