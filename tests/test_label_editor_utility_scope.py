import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import customtkinter as ctk
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import Kohya一键工具 as core
import kohya_gui
from kohya_gui import (
    App,
    LabelEditorWindow,
    _resolve_label_editor_project,
    _run_mainloop_and_destroy,
)


class FakeRoot:
    def __init__(self):
        self.idle_callbacks = []
        self.events = []
        self.in_mainloop = False
        self.exists = True
        self.allow_inloop_destroy = False

    def after_idle(self, callback):
        self.idle_callbacks.append(callback)
        return len(self.idle_callbacks)

    def mainloop(self):
        self.events.append("mainloop started")
        self.in_mainloop = True
        while self.idle_callbacks:
            self.idle_callbacks.pop(0)()
        self.in_mainloop = False
        self.events.append("mainloop returned")

    def winfo_exists(self):
        return self.exists

    def quit(self):
        self.events.append("quit requested")

    def destroy(self):
        if self.in_mainloop and not self.allow_inloop_destroy:
            raise AssertionError("Tk root was destroyed before mainloop returned")
        self.exists = False
        self.events.append("root destroyed")


class FakePopup:
    def bind(self, _sequence, callback, add=None):
        self.destroy_callback = callback

    def destroy(self):
        self.destroy_callback(SimpleNamespace(widget=self))


class LabelEditorUtilityScopeTests(unittest.TestCase):
    def test_project_scoped_utility_uses_the_explicit_project_dataset(self):
        project = _resolve_label_editor_project(
            current_project="9.26饭团anima",
            utility_only=True,
            expected_project="9.26饭团anima",
        )

        self.assertEqual(project, "9.26饭团anima")
        self.assertTrue(
            core.dataset_train_dir("style", project).endswith(
                os.path.join("dataset", "9.26饭团anima", "train")
            )
        )

    def test_project_scoped_utility_rejects_missing_or_mismatched_project(self):
        with self.assertRaisesRegex(ValueError, "项目"):
            _resolve_label_editor_project(
                current_project=None,
                utility_only=True,
                expected_project=None,
            )

        with self.assertRaisesRegex(ValueError, "不一致"):
            _resolve_label_editor_project(
                current_project="another project",
                utility_only=True,
                expected_project="requested project",
            )

    def test_classic_non_utility_editor_keeps_shared_dataset_compatibility(self):
        self.assertEqual(
            _resolve_label_editor_project(current_project=None, utility_only=False),
            "",
        )

    def test_label_editor_command_passes_project_scope_to_dataset_window(self):
        app = App.__new__(App)
        app.current_project = "9.26饭团anima"
        app._utility_only = True
        app._utility_project_name = "9.26饭团anima"
        app._collect_params = Mock(return_value={"mode": "style"})
        app._label_editor = None
        app.root = object()
        app._log = Mock()
        captured = {}

        class CapturingEditor:
            def __init__(self, _root, _app, params):
                captured.update(params)
                self.win = object()

        with patch.object(kohya_gui, "LabelEditorWindow", CapturingEditor), \
                patch.object(kohya_gui.messagebox, "showerror") as showerror, \
                patch.object(kohya_gui.traceback, "print_exc"):
            app.cmd_label_editor()

        showerror.assert_not_called()
        self.assertEqual(captured["project"], "9.26饭团anima")

    def test_label_editor_command_reports_missing_utility_project_without_opening(self):
        app = App.__new__(App)
        app.current_project = None
        app._utility_only = True
        app._utility_project_name = ""
        app._collect_params = Mock(return_value={"mode": "style"})
        app._label_editor = None
        app._log = Mock()

        with patch.object(kohya_gui, "LabelEditorWindow") as editor, \
                patch.object(kohya_gui.messagebox, "showerror") as showerror, \
                patch.object(kohya_gui.traceback, "print_exc"):
            app.cmd_label_editor()

        editor.assert_not_called()
        showerror.assert_called_once()
        self.assertIn("共享数据集", showerror.call_args.args[1])

    def test_label_editor_close_cancels_pending_preview_resize(self):
        editor = LabelEditorWindow.__new__(LabelEditorWindow)
        editor._current = None
        editor._dirty = set()
        editor._prev_job = "resize-preview"
        editor.app = SimpleNamespace(_label_editor=editor)
        editor.win = SimpleNamespace(after_cancel=Mock(), destroy=Mock())

        editor._close()

        editor.win.after_cancel.assert_called_once_with("resize-preview")
        editor.win.destroy.assert_called_once_with()
        self.assertIsNone(editor._prev_job)
        self.assertIsNone(editor.app._label_editor)

    def test_closing_project_utility_quits_loop_before_destroying_root(self):
        root = FakeRoot()
        popup = FakePopup()
        app = App.__new__(App)
        app._utility_only = True
        app.root = root
        app._find_utility_popup = lambda: popup

        app._finish_utility_only()
        popup.destroy()
        _run_mainloop_and_destroy(root)

        self.assertEqual(
            root.events,
            ["mainloop started", "quit requested", "mainloop returned", "root destroyed"],
        )

    def test_mainloop_cleanup_does_not_destroy_root_twice_after_updater_shutdown(self):
        root = FakeRoot()
        root.allow_inloop_destroy = True

        def updater_shutdown_mainloop():
            root.events.append("mainloop started")
            root.in_mainloop = True
            root.destroy()
            root.in_mainloop = False
            root.events.append("mainloop returned")

        root.mainloop = updater_shutdown_mainloop
        _run_mainloop_and_destroy(root)

        self.assertEqual(
            root.events,
            ["mainloop started", "root destroyed", "mainloop returned"],
        )

    def test_real_tk_popup_close_exits_loop_before_root_destroy(self):
        try:
            root = ctk.CTk()
            root.withdraw()
            popup = ctk.CTkToplevel(root)
            popup.withdraw()
        except tk.TclError as exc:
            self.skipTest("Tk display is unavailable: %s" % exc)

        app = App.__new__(App)
        app._utility_only = True
        app.root = root
        app._find_utility_popup = lambda: popup
        app._finish_utility_only()
        root.after(100, popup.destroy)
        timed_out = []
        root.after(1500, lambda: (timed_out.append(True), root.quit()))

        _run_mainloop_and_destroy(root)
        self.assertFalse(timed_out, "utility close failed to exit the Tk mainloop")


if __name__ == "__main__":
    unittest.main()
