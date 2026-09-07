# -*- coding: utf-8 -*-
"""训练队列窗口：多选已保存项目 → 入队 → 逐项“预处理→训练”自动跑。

仅运行期有效；失败项保留在队列里可重新开始；停止 = 停当前项并中止整队。
"""
import os
import queue as _q
import threading
import tkinter as tk
import customtkinter as ctk

import Kohya一键工具 as core
from kohya_core import queue as queue_core


class TrainQueueWindow:
    def __init__(self, master, app):
        self.app = app
        self._master = master
        self.queue = []            # 待跑项目名（运行期）
        self._running = False
        self._stop = False
        self._lines = []
        self.win = ctk.CTkToplevel(master)
        self.win.title("训练队列（多选项目排队）")
        self.win.geometry("860x620")
        self.win.minsize(720, 520)
        try:
            self.win.transient(master)
        except Exception:
            pass
        try:
            import kohya_gui as G
            self.BG = G.BG; self.CARD = G.CARD; self.CARD2 = G.CARD2; self.TXT = G.TXT
            self.SUB = G.SUB; self.HINT = G.HINT; self.ACC = G.ACC; self.ACC_H = G.ACC_H
            self.BORDER = G.BORDER; self.SELBAR = G.SELBAR; self.TITLE_C = G.TITLE_C
            self.FONT_BODY = G.FONT_BODY; self.FONT_HINT = G.FONT_HINT; self.FONT_TITLE = G.FONT_TITLE
        except Exception:
            self.BG="#20232a"; self.CARD="#272b34"; self.CARD2="#2b303a"; self.TXT="#d6dae3"
            self.SUB="#9aa0ad"; self.HINT="#7c8290"; self.ACC="#6d7f99"; self.ACC_H="#7c8fa8"
            self.BORDER="#373d49"; self.SELBAR="#7a8aa5"; self.TITLE_C="#e2e5ec"
            self.FONT_BODY=("Microsoft YaHei UI",13,"normal"); self.FONT_HINT=("Microsoft YaHei UI",11,"normal")
            self.FONT_TITLE=("Microsoft YaHei UI",15,"normal")
        self.win.configure(fg_color=self.BG)
        self._build_ui()
        self.refresh_projects()
        self._poll()

    # ---------- UI ----------
    def _build_ui(self):
        w = self.win
        top = ctk.CTkFrame(w, fg_color="transparent"); top.pack(fill="x", padx=18, pady=(14, 4))
        ctk.CTkLabel(top, text="🎯 训练队列", font=self.FONT_TITLE, text_color=self.TITLE_C).pack(side="left")
        self.status_var = tk.StringVar(value="空闲")
        ctk.CTkLabel(top, textvariable=self.status_var, font=self.FONT_HINT, text_color=self.ACC,
                     anchor="e").pack(side="right")

        body = ctk.CTkFrame(w, fg_color="transparent"); body.pack(fill="both", expand=True, padx=18, pady=(6, 4))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        # 左：所有项目（多选）
        left = ctk.CTkFrame(body, fg_color=self.CARD, corner_radius=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ctk.CTkLabel(left, text="① 所有项目（Ctrl/Shift 多选）", font=self.FONT_HINT, text_color=self.TITLE_C).pack(anchor="w", padx=12, pady=(10, 4))
        self._all_lb = self._mk_list(left)
        lrow = ctk.CTkFrame(left, fg_color="transparent"); lrow.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkButton(lrow, text="➕ 加入队列", width=120, height=28, fg_color=self.ACC, hover_color=self.ACC_H,
                      corner_radius=6, font=self.FONT_HINT, command=self._add_selected).pack(side="left")
        ctk.CTkButton(lrow, text="↻ 刷新项目", width=100, height=28, fg_color=self.CARD2, hover_color="#343a46",
                      border_width=1, border_color=self.BORDER, text_color=self.TXT, corner_radius=6,
                      font=self.FONT_HINT, command=self.refresh_projects).pack(side="left", padx=(8, 0))
        # 右：队列
        right = ctk.CTkFrame(body, fg_color=self.CARD, corner_radius=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(right, text="② 训练队列（按顺序跑，失败项保留）", font=self.FONT_HINT, text_color=self.TITLE_C).pack(anchor="w", padx=12, pady=(10, 4))
        self._q_lb = self._mk_list(right, multi=False)
        rrow = ctk.CTkFrame(right, fg_color="transparent"); rrow.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkButton(rrow, text="➖ 移除选中", width=100, height=28, fg_color="#4a3a3a", hover_color="#5a4646",
                      corner_radius=6, font=self.FONT_HINT, command=self._remove_selected).pack(side="left")
        ctk.CTkButton(rrow, text="🗑 清空队列", width=100, height=28, fg_color="#4a3a3a", hover_color="#5a4646",
                      corner_radius=6, font=self.FONT_HINT, command=self._clear_queue).pack(side="left", padx=(8, 0))
        ctk.CTkButton(rrow, text="▶ 开始", width=90, height=30, fg_color="#3f6b4a", hover_color="#4c7f59",
                      corner_radius=6, font=self.FONT_HINT, command=self.start).pack(side="right")
        ctk.CTkButton(rrow, text="⏹ 停止", width=90, height=30, fg_color="#6b3f3f", hover_color="#7f4c4c",
                      corner_radius=6, font=self.FONT_HINT, command=self.stop).pack(side="right", padx=(0, 8))
        # 底部日志
        logf = ctk.CTkFrame(w, fg_color=self.CARD, corner_radius=8)
        logf.pack(fill="both", expand=True, padx=18, pady=(6, 14))
        ctk.CTkLabel(logf, text="运行日志", font=self.FONT_HINT, text_color=self.TITLE_C).pack(anchor="w", padx=12, pady=(8, 2))
        self.logbox = ctk.CTkTextbox(logf, height=150, fg_color="#16181e", text_color="#b6bcc9",
                                     corner_radius=6, border_width=1, border_color=self.BORDER, font=("Consolas", 11))
        self.logbox.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        ctk.CTkLabel(w, text="提示：队列只在本次运行内有效；会逐项执行“预处理→训练”，H3 视频项目暂不支持入队。",
                     font=self.FONT_HINT, text_color=self.HINT).pack(anchor="w", padx=20, pady=(0, 8))
        self.win.protocol("WM_DELETE_WINDOW", self.close)

    def _mk_list(self, parent, multi=True):
        lf = ctk.CTkFrame(parent, fg_color="transparent")
        lf.pack(fill="both", expand=True, padx=8, pady=(2, 6))
        mode = "extended" if multi else "single"
        lb = tk.Listbox(lf, bg=self.CARD2, fg=self.TXT, selectbackground=self.SELBAR, selectforeground="#ffffff",
                        font=self.FONT_BODY, highlightthickness=0, borderwidth=0,
                        activestyle="none", exportselection=False, selectmode=mode)
        lb.pack(side="left", fill="both", expand=True)
        sb = ctk.CTkScrollbar(lf, command=lb.yview)
        sb.pack(side="right", fill="y")
        lb.configure(yscrollcommand=sb.set)
        return lb

    # ---------- 数据 ----------
    def refresh_projects(self):
        try:
            projects = core.list_projects()
        except Exception:
            projects = []
        self._projects = projects
        self._all_lb.delete(0, "end")
        for it in projects:
            mode = it.get("mode") or "?"
            label = core.MODE_LABELS.get(mode, mode)
            self._all_lb.insert("end", "%s  ·  %s" % (it.get("name") or "", label))
        self._render_queue()

    def _render_queue(self):
        self._q_lb.delete(0, "end")
        for n in self.queue:
            mode = "?"
            for it in self._projects:
                if (it.get("name") or "") == n:
                    mode = core.MODE_LABELS.get(it.get("mode"), it.get("mode") or "?")
                    break
            self._q_lb.insert("end", "%s  ·  %s" % (n, mode))

    def _add_selected(self):
        for i in self._all_lb.curselection():
            it = self._projects[i]
            name = it.get("name") or ""
            if name and name not in self.queue:
                self.queue.append(name)
        self._render_queue()

    def _remove_selected(self):
        idxs = sorted(self._q_lb.curselection(), reverse=True)
        for i in idxs:
            if 0 <= i < len(self.queue):
                self.queue.pop(i)
        self._render_queue()

    def _clear_queue(self):
        self.queue = []
        self._render_queue()

    # ---------- 运行 ----------
    def start(self):
        if self._running:
            self._sink("[队列] 已在运行中")
            return
        if not self.queue:
            self._sink("[队列] 队列为空，请先添加项目")
            return
        self._running = True
        self._stop = False
        self.status_var.set("运行中…")
        names = list(self.queue)
        threading.Thread(target=self._worker, args=(names,), daemon=True).start()

    def stop(self):
        if not self._running:
            return
        self._stop = True
        self._sink("[队列] 收到停止请求：正在停止当前项…")
        try:
            core.stop_active_process()
        except Exception:
            pass

    def _worker(self, names):
        ok_list, failed = [], []
        try:
            for name in names:
                if self._stop:
                    break
                self._sink("\n======== 开始队列项：%s ========" % name)
                try:
                    ok, msg = queue_core.run_queue_item(name, logf=self._sink)
                except core.StopRequested:
                    self._sink("[队列] 已停止（进度快照保留，可断点续训）")
                    break
                except Exception as e:
                    failed.append(name)
                    self._sink("[队列] 项目「%s」失败：%s" % (name, e))
                    continue
                if ok:
                    ok_list.append(name)
                    if name in self.queue:
                        self.queue.remove(name)
                    self._sink("[队列] 项目「%s」%s" % (name, msg))
                else:
                    failed.append(name)
                    self._sink("[队列] 项目「%s」未完成：%s（已保留在队列，可修复后重跑）" % (name, msg))
            self._sink("\n======== 队列结束：完成 %d，失败/未完成 %d ========" % (len(ok_list), len(failed)))
            if failed:
                self._sink("未完成：%s" % "、".join(failed))
        finally:
            self._running = False
            try:
                self.win.after(0, self._done_ui)
            except Exception:
                pass

    def _done_ui(self):
        self.status_var.set("空闲（失败项仍在队列中，可点开始重跑）")
        self._render_queue()
        self.refresh_projects()

    def _sink(self, text):
        self._lines.append(str(text))
        try:
            self.app._log(str(text))
        except Exception:
            pass

    def _poll(self):
        try:
            if self._lines:
                lines = self._lines
                self._lines = []
                for ln in lines:
                    self.logbox.insert("end", ln + "\n")
                    self.logbox.see("end")
        except Exception:
            pass
        try:
            self.win.after(250, self._poll)
        except Exception:
            pass

    def close(self):
        self._stop = True
        try:
            core.stop_active_process()
        except Exception:
            pass
        try:
            app = self.app
            if getattr(app, "_queue_win", None) is self:
                app._queue_win = None
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass
