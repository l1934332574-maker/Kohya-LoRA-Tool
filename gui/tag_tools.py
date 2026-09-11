# -*- coding: utf-8 -*-
"""标签工具：中英离线词典查询窗（标签编辑器入口 + 主页小工具独立入口共用）。

- 编辑器入口：TagLookupWindow(master, editor) → 额外提供「插入当前图标签」「翻译当前图标签」
- 独立入口：TagLookupWindow(master)（editor=None）→ 双击/按钮 = 复制到剪贴板，多一个「标签篮」

本模块不持有业务逻辑：词典查询走 kohya_core.tagging；样式/常量延迟引用
kohya_gui（由 kohya_gui 在运行时惰性 import 本模块，避免启动循环依赖）。
"""
import tkinter as tk

import customtkinter as ctk

# ---------- 词典单例（懒加载，整个进程只解析一次） ----------
_DICT = None

# 分类筛选项：(显示名, 分类值或 None=全部)。分类值含义见 kohya_core.tagging.CAT_LABELS
_CAT_FILTERS = [
    ("全部分类", None),
    ("通用", 0),
    ("角色", 4),
    ("作品", 3),
    ("画师", 1),
    ("元数据", 5),
]
_SORTS = ["默认顺序", "按热度", "按字母 A-Z"]


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
    """中英离线词典窗：英文补全 / 中文反查 / 分类筛选 / 复制或插入当前图片。"""

    def __init__(self, master, editor=None):
        self.editor = editor
        self.standalone = editor is None      # 独立模式：无当前图片，动作用「复制 + 标签篮」
        self._basket = []                     # 标签篮（仅内存，不落盘）
        self._basket_win = None
        self._rows = []
        self.win = ctk.CTkToplevel(master)
        km = _kmod()
        self.win.title("标签中英词典 · 离线" if not self.standalone else "离线标签词典 · 中英互译 / 补全")
        self.win.geometry("820x680" if self.standalone else "760x640")
        self.win.minsize(600, 440)
        self.win.transient(master)
        self.win.configure(fg_color=km.BG)
        self._dict = editor.get_tagdict() if hasattr(editor, "get_tagdict") else get_dict()
        self._build()
        if self._dict and self._dict.available():
            self._title_var.set("离线标签词典 · 内置词条 %d 条（中英互译 / 自动补全）" % len(self._dict))
        else:
            self._title_var.set("离线标签词典 · 未找到离线词典数据文件")

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
        # 「翻译当前图标签」只在编辑器入口有意义
        if not self.standalone:
            self.btn_caption.pack(side="left", padx=(8, 0))

        # 第二行：分类筛选 + 排序（+ 独立模式的标签篮入口）
        row2 = ctk.CTkFrame(w, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=(8, 0))
        ctk.CTkLabel(row2, text="分类", font=km.ui_font(km.FONT_HINT), text_color=km.SUB).pack(side="left")
        self.cat_var = tk.StringVar(value=_CAT_FILTERS[0][0])
        self.cat_menu = ctk.CTkComboBox(
            row2, values=[c[0] for c in _CAT_FILTERS], width=120, height=28,
            variable=self.cat_var, state="readonly",
            fg_color=km.CARD2, border_color=km.BORDER, text_color=km.TXT,
            button_color="#3a4150", button_hover_color="#454d5e",
            dropdown_fg_color=km.CARD, dropdown_text_color=km.TXT, dropdown_hover_color="#2b303a",
            font=km.ui_font(km.FONT_HINT), command=lambda _e: self._search())
        self.cat_menu.pack(side="left", padx=(8, 16))
        ctk.CTkLabel(row2, text="排序", font=km.ui_font(km.FONT_HINT), text_color=km.SUB).pack(side="left")
        self.sort_var = tk.StringVar(value=_SORTS[0])
        self.sort_menu = ctk.CTkComboBox(
            row2, values=_SORTS, width=140, height=28,
            variable=self.sort_var, state="readonly",
            fg_color=km.CARD2, border_color=km.BORDER, text_color=km.TXT,
            button_color="#3a4150", button_hover_color="#454d5e",
            dropdown_fg_color=km.CARD, dropdown_text_color=km.TXT, dropdown_hover_color="#2b303a",
            font=km.ui_font(km.FONT_HINT), command=lambda _e: self._search())
        self.sort_menu.pack(side="left", padx=(8, 0))
        if self.standalone:
            self.btn_basket = ctk.CTkButton(
                row2, text=self._basket_label(), width=132, height=28,
                fg_color=km.CARD2, hover_color="#343a46", border_width=1, border_color=km.BORDER,
                text_color=km.TXT, corner_radius=6, font=km.ui_font(km.FONT_HINT),
                command=self._open_basket)
            self.btn_basket.pack(side="right")

        self.hint_var = tk.StringVar()
        ctk.CTkLabel(w, textvariable=self.hint_var, font=km.ui_font(km.FONT_HINT),
                     text_color=km.HINT, anchor="w").pack(fill="x", padx=16, pady=(6, 2))

        box = ctk.CTkFrame(w, fg_color=km.CARD, corner_radius=8)
        box.pack(fill="both", expand=True, padx=16, pady=(4, 10))
        self.scroll = ctk.CTkScrollableFrame(box, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=6, pady=6)

        foot = ctk.CTkFrame(w, fg_color="transparent")
        foot.pack(fill="x", padx=16, pady=(0, 12))
        tip = ("双击条目或点「复制」→ 复制英文标签；右键可复制中英对照；「+」加入标签篮"
               if self.standalone else
               "双击条目或点「插入」→ 追加到当前图片标签末尾（重复标签自动跳过）；右键可复制中英对照")
        ctk.CTkLabel(foot, text=tip, font=km.ui_font(km.FONT_HINT), text_color=km.HINT).pack(side="left")
        ctk.CTkButton(foot, text="清空", width=64, height=26, fg_color=km.CARD2, hover_color="#343a46",
                      border_width=1, border_color=km.BORDER, text_color=km.TXT, corner_radius=6,
                      font=km.ui_font(km.FONT_HINT), command=self._clear_rows).pack(side="right")

    def _basket_label(self):
        return "🧺 已收集 %d" % len(self._basket)

    # ---------- 查询 ----------
    def _cat_filter_value(self):
        name = self.cat_var.get()
        for label, val in _CAT_FILTERS:
            if label == name:
                return val
        return None

    def _apply_filter_sort(self, rows):
        """分类筛选 + 排序。rows: [(name, cn, cat, cnt)]"""
        try:
            cat = self._cat_filter_value()
            if cat is not None:
                rows = [r for r in rows if len(r) > 2 and r[2] == cat]
            mode = self.sort_var.get()
            if mode == "按字母 A-Z":
                rows = sorted(rows, key=lambda r: str(r[0]).lower())
            elif mode == "按热度":
                rows = sorted(rows, key=lambda r: -(r[3] if len(r) > 3 else 0))
            # 「默认顺序」= 保持上游顺序（编辑器模式=数据集优先，独立模式=词典热度）
        except Exception:
            pass
        return rows

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
            base_hint = "中文 → 英文联想（最多 60 条）"
        else:
            tags = self._user_freq()
            from kohya_core.tagging import complete
            rows = complete.suggest_en(self._dict, text, user_tags=tags, limit=60)
            base_hint = "英文补全"
        rows = self._apply_filter_sort(rows)
        cat_txt = self.cat_var.get()
        self.hint_var.set("%s · %s · %s（%d 条）" % (base_hint, cat_txt, self.sort_var.get(), len(rows)))
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
            row.bind("<Double-Button-1>", lambda _e, n=name: self._primary(n))
            row.bind("<Button-3>", lambda e, n=name, c=cn: self._popup(e, n, c))
            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True, padx=10, pady=4)
            lbl = ctk.CTkLabel(left, text=name, font=km.ui_font(km.FONT_BODY), text_color=km.TXT, anchor="w")
            lbl.pack(anchor="w")
            lbl.bind("<Double-Button-1>", lambda _e, n=name: self._primary(n))
            lbl.bind("<Button-3>", lambda e, n=name, c=cn: self._popup(e, n, c))
            sub = ""
            if cn and cn != name:
                sub += cn
            extra = []
            c = _fmt_count(cnt)
            if c:
                extra.append(c)
            # 独立模式：分类已由顶部筛选器控制，逐行不再显示，省出空间
            if not self.standalone:
                cat_s = _cat_short(self._dict, cat)
                if cat_s:
                    extra.append(cat_s)
            if extra:
                sub += ("  ·  " if sub else "") + " / ".join(extra)
            ctk.CTkLabel(left, text=sub or "（无中文翻译）", font=km.ui_font(km.FONT_HINT),
                         text_color=km.HINT if (sub and cn != name) else km.SUB, anchor="w").pack(anchor="w")
            if self.standalone:
                btn_add = ctk.CTkButton(row, text="+", width=34, height=26, fg_color="#3a4658",
                                        hover_color="#46546a", text_color="#cfd6e2", corner_radius=6,
                                        font=km.ui_font(km.FONT_HINT), command=lambda n=name: self._collect(n))
                btn_add.pack(side="right", padx=(0, 8), pady=6)
                btn = ctk.CTkButton(row, text="复制", width=56, height=26, fg_color="#3a4658",
                                    hover_color="#46546a", text_color="#cfd6e2", corner_radius=6,
                                    font=km.ui_font(km.FONT_HINT), command=lambda n=name: self._copy(n))
                btn.pack(side="right", padx=(0, 6), pady=6)
            else:
                btn = ctk.CTkButton(row, text="插入", width=56, height=26, fg_color="#3a4658",
                                    hover_color="#46546a", text_color="#cfd6e2", corner_radius=6,
                                    font=km.ui_font(km.FONT_HINT), command=lambda n=name: self._insert(n))
                btn.pack(side="right", padx=8, pady=6)
        self._rows = rows

    # ---------- 动作 ----------
    def _primary(self, name):
        """双击的默认动作：独立模式=复制，编辑器模式=插入当前图。"""
        if self.standalone:
            self._copy(name)
        else:
            self._insert(name)

    def _copy(self, name, with_zh=False):
        try:
            text = str(name)
            if with_zh:
                zh = ""
                try:
                    zh = self._dict.to_zh(name) or ""
                except Exception:
                    zh = ""
                if zh:
                    text = "%s\n%s" % (name, zh)
            self.win.clipboard_clear()
            self.win.clipboard_append(text)
            self.hint_var.set("已复制：%s" % text.replace("\n", "  "))
        except Exception as e:
            self.hint_var.set("复制失败：%s" % e)

    def _popup(self, event, name, cn):
        km = _kmod()
        try:
            m = tk.Menu(self.win, tearoff=0)
            m.add_command(label="复制标签", command=lambda: self._copy(name))
            if cn and cn != name:
                m.add_command(label="复制中英对照", command=lambda: self._copy(name, with_zh=True))
            if self.standalone:
                m.add_separator()
                m.add_command(label="加入标签篮", command=lambda: self._collect(name))
                m.add_command(label="只复制中文", command=lambda: self._copy(cn or name))
            else:
                m.add_separator()
                m.add_command(label="插入当前图", command=lambda: self._insert(name))
            m.tk_popup(event.x_root, event.y_root)
        except Exception:
            pass

    def _collect(self, name):
        if name not in self._basket:
            self._basket.append(name)
        try:
            self.btn_basket.configure(text=self._basket_label())
        except Exception:
            pass
        self.hint_var.set("已加入标签篮（共 %d 个）：%s" % (len(self._basket), name))
        if self._basket_win is not None and getattr(self._basket_win, "winfo_exists", lambda: False)():
            try:
                self._refresh_basket()
            except Exception:
                pass

    def _open_basket(self):
        km = _kmod()
        try:
            if self._basket_win is not None and self._basket_win.winfo_exists():
                self._basket_win.lift()
                self._refresh_basket()
                return
            bw = ctk.CTkToplevel(self.win)
            bw.title("🧺 标签篮")
            bw.geometry("520x520")
            bw.transient(self.win)
            bw.configure(fg_color=km.BG)
            self._basket_win = bw
            ctk.CTkLabel(bw, text="标签篮（内存中，关软件即清空）", font=km.ui_font(km.FONT_BODY),
                         text_color=km.TITLE_C, anchor="w").pack(fill="x", padx=16, pady=(14, 6))
            self._basket_scroll = ctk.CTkScrollableFrame(bw, fg_color=km.CARD)
            self._basket_scroll.pack(fill="both", expand=True, padx=16, pady=(0, 8))
            foot = ctk.CTkFrame(bw, fg_color="transparent")
            foot.pack(fill="x", padx=16, pady=(0, 12))
            ctk.CTkButton(foot, text="📋 全部复制", width=110, height=30, fg_color=km.ACC,
                          hover_color=km.ACC_H, corner_radius=6, font=km.ui_font(km.FONT_BODY),
                          command=self._basket_copy_all).pack(side="left")
            ctk.CTkButton(foot, text="清空", width=70, height=30, fg_color=km.CARD2,
                          hover_color="#343a46", border_width=1, border_color=km.BORDER, text_color=km.TXT,
                          corner_radius=6, font=km.ui_font(km.FONT_HINT),
                          command=self._basket_clear).pack(side="left", padx=(8, 0))
            ctk.CTkLabel(foot, text="全部复制 = 逗号分隔一行，可直接粘进提示词",
                         font=km.ui_font(km.FONT_HINT), text_color=km.HINT).pack(side="left", padx=(10, 0))
            self._refresh_basket()
        except Exception as e:
            self.hint_var.set("打开标签篮失败：%s" % e)

    def _refresh_basket(self):
        km = _kmod()
        if self._basket_win is None or not self._basket_win.winfo_exists():
            return
        for child in self._basket_scroll.winfo_children():
            child.destroy()
        if not self._basket:
            ctk.CTkLabel(self._basket_scroll, text="（还在空——在上一条搜索结果里点「+」收集）",
                         font=km.ui_font(km.FONT_HINT), text_color=km.HINT).pack(anchor="w", padx=10, pady=10)
            return
        for i, name in enumerate(list(self._basket)):
            row = ctk.CTkFrame(self._basket_scroll, fg_color=km.CARD2, corner_radius=6)
            row.pack(fill="x", padx=6, pady=3)
            cn = ""
            try:
                cn = self._dict.to_zh(name) or ""
            except Exception:
                cn = ""
            ctk.CTkLabel(row, text=name, font=km.ui_font(km.FONT_BODY), text_color=km.TXT,
                         anchor="w").pack(side="left", padx=10, pady=6)
            if cn and cn != name:
                ctk.CTkLabel(row, text="· " + cn, font=km.ui_font(km.FONT_HINT),
                             text_color=km.HINT).pack(side="left")
            ctk.CTkButton(row, text="移除", width=52, height=24, fg_color="transparent",
                          hover_color="#3a2a2a", border_width=1, border_color=km.BORDER, text_color=km.SUB,
                          corner_radius=6, font=km.ui_font(km.FONT_HINT),
                          command=lambda n=name: self._basket_remove(n)).pack(side="right", padx=8, pady=4)

    def _basket_remove(self, name):
        try:
            self._basket.remove(name)
        except ValueError:
            pass
        self._refresh_basket()
        try:
            self.btn_basket.configure(text=self._basket_label())
        except Exception:
            pass

    def _basket_clear(self):
        self._basket = []
        self._refresh_basket()
        try:
            self.btn_basket.configure(text=self._basket_label())
        except Exception:
            pass

    def _basket_copy_all(self):
        if not self._basket:
            self.hint_var.set("标签篮是空的")
            return
        text = ", ".join(self._basket)
        try:
            self.win.clipboard_clear()
            self.win.clipboard_append(text)
            self.hint_var.set("已复制 %d 个标签：%s" % (len(self._basket), text))
        except Exception as e:
            self.hint_var.set("复制失败：%s" % e)

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
