# -*- coding: utf-8 -*-
"""标签编辑器配套工具：中英词典 / 翻译 / 自动补全 / 插入当前图标签。

本模块不持有业务逻辑：词典查询走 kohya_core.tagging；样式/常量延迟引用
kohya_gui（由 kohya_gui 在运行时惰性 import 本模块，避免启动循环依赖）。
"""
import tkinter as tk

import customtkinter as ctk


# ---------- 词典单例（懒加载，整个进程只解析一次） ----------
_DICT = None


def get_dict():
    global _DICT
    if _DICT is None:
        from kohya_core.tagging import TagDict
        _DICT = TagDict()
        _DICT._ensure()  # 提前载入，让窗口能显示词条数
    return _DICT


def _fmt_count(c):
    try:
        c = int(c or 0)
    except Exception:
        return ""
    if c >= 100000000:
        return "%.1f亿" % (c / 100000000.0)
    if c >= 10000:
        return "%.1f万" % (c / 10000.0)
    if c > 0:
        return str(c)
    return ""


def _cat_short(d, cat):
    try:
        from kohya_core.tagging import cat_label
        return cat_label(cat)
    except Exception:
        return ""


class TagLookupWindow(object):
    """中英词典查询窗：输入英文补全（显示中文），输入中文反查英文，可插入当前图片。"""

    def __init__(self, master, editor):
        self.editor = editor
        self.win = ctk.CTkToplevel(master)
        km = _kmod()
        self.win.title("标签中英词典 · 离线")
        self.win.geometry("760x640")
        self.win.minsize(560, 420)
        self.win.transient(master)
        self.win.configure(fg_color=km.BG)
        self._dict = editor.get_tagdict() if hasattr(editor, "get_tagdict") else get_dict()
        self._rows = []
        self._build()
        if self._dict and self._dict.available():
            self._title_var.set("标签中英词典 · 内置离线词条 %d 条（中英互译 / 自动补全）" % len(self._dict))
        else:
            self._title_var.set("标签中英词典 · 未找到离线词典数据文件")

    # ---------- 布局 ----------
    def _build(self):
        km = _kmod()
        w = self.win
        self._title_var = tk.StringVar()
        ctk.CTkLabel(w, textvariable=self._title_var, font=km.ui_font(km.FONT_BODY),
                     text_color=km.TITLE_C, anchor="w").pack(fill="x", padx=16, pady=(14, 4))

        top = ctk.CTkFrame(w, fg_color="transparent")
        top.pack(fill="x", padx=16)
        self.entry = ctk.CTkEntry(top, height=32, fg_color=km.CARD2, border_color=km.BORDER,
                                  text_color=km.TXT, placeholder_text="输入英文或中文标签… 如 blue ／ 蓝发 ／ 初音",
                                  font=km.ui_font(km.FONT_BODY))
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<KeyRelease>", lambda e: self._search())
        self.entry.bind("<Return>", lambda e: self._search())
        self.btn_caption = ctk.CTkButton(top, text="翻译当前图标签", width=132, height=32,
                                         fg_color=km.CARD2, hover_color="#343a46", border_width=1,
                                         border_color=km.BORDER, text_color=km.TXT, corner_radius=6,
                                         font=km.ui_font(km.FONT_HINT), command=self._show_caption_translate)
        self.btn_caption.pack(side="left", padx=(8, 0))

        self.hint_var = tk.StringVar()
        ctk.CTkLabel(w, textvariable=self.hint_var, font=km.ui_font(km.FONT_HINT),
                     text_color=km.HINT, anchor="w").pack(fill="x", padx=16, pady=(6, 2))

        box = ctk.CTkFrame(w, fg_color=km.CARD, corner_radius=8)
        box.pack(fill="both", expand=True, padx=16, pady=(4, 10))
        self.scroll = ctk.CTkScrollableFrame(box, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=6, pady=6)

        foot = ctk.CTkFrame(w, fg_color="transparent")
        foot.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(foot, text="双击条目或点「插入」→ 追加到当前图片标签末尾（重复标签自动跳过）",
                     font=km.ui_font(km.FONT_HINT), text_color=km.HINT).pack(side="left")
        ctk.CTkButton(foot, text="清空", width=64, height=26, fg_color=km.CARD2, hover_color="#343a46",
                      border_width=1, border_color=km.BORDER, text_color=km.TXT, corner_radius=6,
                      font=km.ui_font(km.FONT_HINT), command=self._clear_rows).pack(side="right")

    # ---------- 查询 ----------
    def _search(self):
        if self._dict is None:
            self.hint_var.set("未找到离线词典数据文件，无法查询")
            self._clear_rows()
            return
        text = self.entry.get().strip()
        if not text:
            self.hint_var.set("")
            self._clear_rows()
            return
        from kohya_core.tagging import normalize, translate
        if normalize.has_cjk(text):
            rows = translate.to_en(self._dict, text, limit=60)
            self.hint_var.set("中文 → 英文联想（前 60 条，按热度排序）")
        else:
            tags = self._user_freq()
            from kohya_core.tagging import complete
            rows = complete.suggest_en(self._dict, text, user_tags=tags, limit=60)
            self.hint_var.set("英文补全（数据集里出现过的排前面；双击插入）")
        self._fill(rows)

    def _user_freq(self):
        try:
            from kohya_core.tagging import complete
            return complete.freq_of(self.editor.records)
        except Exception:
            return {}

    def _show_caption_translate(self):
        if self._dict is None:
            self.hint_var.set("未找到离线词典数据文件，无法翻译")
            return
        try:
            from kohya_core.tagging import translate
            rows = []
            tags = self.editor.caption.get("1.0", "end").strip()
            for tag, zh in translate.translate_tags(self._dict, tags):
                rows.append((tag, zh, 0, 0))
            if rows:
                self.hint_var.set("当前图片标签中英对照（未收录的保留原名）")
            else:
                self.hint_var.set("当前图片没有可翻译的标签")
            self._fill(rows)
        except Exception as e:
            self.hint_var.set("翻译失败：%s" % e)

    # ---------- 结果区 ----------
    def _clear_rows(self):
        for child in self.scroll.winfo_children():
            child.destroy()
        self._rows = []

    def _fill(self, rows):
        self._clear_rows()
        km = _kmod()
        if not rows:
            ctk.CTkLabel(self.scroll, text="（没有匹配结果）", font=km.ui_font(km.FONT_HINT),
                         text_color=km.HINT).pack(anchor="w", padx=8, pady=8)
            return
        for name, cn, cat, cnt in rows:
            row = ctk.CTkFrame(self.scroll, fg_color=km.CARD2, corner_radius=6)
            row.pack(fill="x", padx=2, pady=2)
            row.bind("<Double-Button-1>", lambda _e, n=name: self._insert(n))
            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True, padx=10, pady=4)
            lbl = ctk.CTkLabel(left, text=name, font=km.ui_font(km.FONT_BODY), text_color=km.TXT, anchor="w")
            lbl.pack(anchor="w")
            lbl.bind("<Double-Button-1>", lambda _e, n=name: self._insert(n))
            sub = ""
            if cn and cn != name:
                sub += cn
            extra = []
            c = _fmt_count(cnt)
            if c:
                extra.append(c)
            cat_s = _cat_short(self._dict, cat)
            if cat_s:
                extra.append(cat_s)
            if extra:
                sub += ("  ·  " if sub else "") + " / ".join(extra)
            ctk.CTkLabel(left, text=sub or "（无中文翻译）", font=km.ui_font(km.FONT_HINT),
                         text_color=km.HINT if (sub and cn != name) else km.SUB, anchor="w").pack(anchor="w")
            btn = ctk.CTkButton(row, text="插入", width=56, height=26, fg_color="#3a4658",
                                hover_color="#46546a", text_color="#cfd6e2", corner_radius=6,
                                font=km.ui_font(km.FONT_HINT), command=lambda n=name: self._insert(n))
            btn.pack(side="right", padx=8, pady=6)
        self._rows = rows

    def _insert(self, name):
        try:
            ok = self.editor.insert_tag_to_caption(name)
            if ok:
                self.win.lift()
        except Exception as e:
            import tkinter.messagebox as mb
            mb.showerror("插入标签", "插入失败：%s" % e, parent=self.win)


def _kmod():
    """延迟拿到 kohya_gui 模块（样式常量已初始化）。"""
    import kohya_gui
    return kohya_gui
