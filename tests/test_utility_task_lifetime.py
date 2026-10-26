import ast
import queue
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kohya_gui
from kohya_gui import App, _run_mainloop_and_destroy


class Root:
    def __init__(self):
        self.idle = []
        self.timers = []
        self.quit = Mock()
        self.destroy = Mock()

    def after_idle(self, callback):
        self.idle.append(callback)

    def after(self, delay, callback):
        self.timers.append((delay, callback))

    def run_idle(self):
        callbacks, self.idle = self.idle, []
        for callback in callbacks:
            callback()


class Popup:
    transient = Mock()
    after = Mock()
    def bind(self, sequence, callback, add=None):
        self.on_destroy = callback

    def destroy(self):
        self.on_destroy(SimpleNamespace(widget=self))


class UtilityTaskLifetimeTests(unittest.TestCase):
    def app(self):
        app = App.__new__(App)
        app.root = Root()
        app._utility_only = True
        app._utility_owner = 0
        app._utility_final_check_done = True
        app._find_utility_popup = Mock(return_value=None)
        app._log = Mock()
        app._set_busy = Mock()
        app.q = queue.Queue()
        return app

    def test_popup_handoff_keeps_download_alive(self):
        app = self.app()
        selection, progress = Popup(), Popup()
        app._find_utility_popup.return_value = selection
        app._finish_utility_only()
        selection.destroy()
        app._downloading = True
        app._find_utility_popup.return_value = progress
        app.root.run_idle()
        self.assertIs(app._utility_bound_popup, progress)
        app.root.quit.assert_not_called()
        progress.destroy()
        app._find_utility_popup.return_value = None
        app.root.run_idle()
        app.root.quit.assert_not_called()
        app._downloading = False
        app.root.timers.pop(0)[1]()
        app.root.run_idle()
        app.root.quit.assert_called_once()

    def test_queued_quit_rechecks_new_popup(self):
        app = self.app()
        app._finish_utility_only()
        popup = Popup()
        app._find_utility_popup.return_value = popup
        app.root.run_idle()
        app.root.quit.assert_not_called()
        self.assertIs(app._utility_bound_popup, popup)

    def test_queued_quit_rechecks_download_started_after_scheduling(self):
        app = self.app()
        app._finish_utility_only()
        app._downloading = True
        app.root.run_idle()
        app.root.quit.assert_not_called()
        self.assertTrue(app.root.timers)

    def test_tool_worker_survives_tools_window_close_until_result(self):
        app = self.app()
        app._tool_busy = {"cache": True}
        app._finish_utility_only()
        app.root.run_idle()
        app.root.quit.assert_not_called()
        self.assertTrue(app.root.timers)
        app._tool_busy["cache"] = False
        app.root.timers.pop(0)[1]()
        app.root.run_idle()
        app.root.quit.assert_called_once()

    def test_log_export_survives_owner_popup_close(self):
        app = self.app()
        app._diagnostics_thread = SimpleNamespace(is_alive=lambda: True)
        app._finish_utility_only()
        app.root.run_idle()
        app.root.quit.assert_not_called()
        self.assertTrue(app.root.timers)

    def test_update_installer_result_is_checked_before_utility_exit(self):
        app = self.app()
        app._updating = True
        proc = SimpleNamespace(poll=lambda: 1)
        app._update_blocked_help = Mock()
        with patch.object(kohya_gui.os.path, "isfile", return_value=True), \
                patch.object(kohya_gui.subprocess, "Popen", return_value=proc):
            app._handle_update_done(True, "setup.exe", "test-version", "ok")
        app._finish_utility_only()
        app.root.run_idle()
        app.root.quit.assert_not_called()
        installer_check = next(callback for delay, callback in app.root.timers if delay == 2500)
        installer_check()
        app._update_blocked_help.assert_called_once()
        app._finish_utility_only()
        app.root.run_idle()
        app.root.quit.assert_called_once()

    def test_new_tk_popup_is_detected_before_first_paint(self):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            popup = tk.Toplevel(root)
            app = App.__new__(App)
            app.root = root
            self.assertFalse(popup.winfo_ismapped())
            self.assertIs(app._find_utility_popup(), popup)
        finally:
            root.destroy()

    def test_queue_worker_cleanup_survives_queue_popup_close(self):
        app = self.app()
        app._queue_win = None
        app._queue_worker = SimpleNamespace(is_alive=lambda: True)
        app._finish_utility_only()
        app.root.run_idle()
        app.root.quit.assert_not_called()
        self.assertTrue(app.root.timers)

    def test_amd_setup_buttons_register_workers_and_completion(self):
        source = Path(kohya_gui.__file__).read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        guide = next(node for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef) and node.name == "_open_amd_guide")
        for name in ("_auto_venv", "_auto_py312"):
            with self.subTest(button=name):
                app = self.app()
                app._start_worker = Mock()
                app._venv_done = Mock()
                app._py312_done = Mock()
                node = next(node for node in guide.body
                            if isinstance(node, ast.FunctionDef) and node.name == name)
                namespace = dict(vars(kohya_gui), self=app, py_ver="3.12")
                exec(compile(ast.Module(body=[node], type_ignores=[]), "<amd button>", "exec"), namespace)
                with patch.object(kohya_gui.core, "data_dir", return_value="test-data"), \
                        patch.object(kohya_gui.threading, "Thread") as direct_thread:
                    namespace[name]()
                app._start_worker.assert_called_once()
                direct_thread.assert_not_called()
                worker = app._start_worker.call_args.args[0]
                with patch.object(kohya_gui.core, "create_python_venv", return_value=(True, "ok")), \
                        patch.object(kohya_gui.core, "install_python_312", return_value=(True, "ok")):
                    worker()
                self.assertEqual(app.q.get_nowait(), "__DONE__")
                app.root.timers.pop(0)[1]()
                callback = app._venv_done if name == "_auto_venv" else app._py312_done
                callback.assert_called_once()

    def test_real_tk_download_handoff_with_and_without_content_length(self):
        import customtkinter as ctk
        payload = b"local download fixture\n" * 4096

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                if self.path == "/known":
                    self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                time.sleep(0.35)
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            for route in ("known", "unknown"):
                with self.subTest(route=route), tempfile.TemporaryDirectory() as directory:
                    root = ctk.CTk()
                    root.withdraw()
                    app = App.__new__(App)
                    app.root = root
                    app._utility_only = True
                    app._utility_owner = 0
                    app._utility_final_check_done = True
                    app._log = Mock()
                    app._scan_base_models = Mock()
                    app.q = queue.Queue()
                    app._dl = None
                    selection = ctk.CTkToplevel(root)
                    app._finish_utility_only()
                    results, timed_out, tk_errors = [], [], []
                    root.report_callback_exception = lambda *exc: tk_errors.append("".join(traceback.format_exception(*exc)))
                    original_done = app._handle_dl_done

                    def done(ok, dest):
                        results.append(ok)
                        original_done(ok, dest)

                    app._handle_dl_done = done

                    def poll():
                        while not app.q.empty():
                            app._handle(app.q.get_nowait())
                        root.after(10, poll)

                    dest = str(Path(directory) / "fixture.bin")
                    url = "http://127.0.0.1:%d/%s" % (server.server_port, route)

                    def launch():
                        self.assertTrue(app._launch_model_download(url, dest, "fixture.bin", "96 KB", "base", "test"))
                        selection.destroy()
                        poll()

                    root.after(700, launch)
                    root.after(5000, lambda: (timed_out.append([(str(w), w.state()) for w in root.winfo_children()]), root.quit()))
                    original_quit = root.quit
                    def quit_cleanly():
                        for timer in root.tk.call("after", "info"):
                            root.after_cancel(timer)
                        original_quit()
                    root.quit = quit_cleanly
                    with patch.object(kohya_gui.messagebox, "showinfo"), \
                            patch.object(kohya_gui.messagebox, "showerror") as showerror:
                        _run_mainloop_and_destroy(root)
                    if app._dl is not None:
                        app._dl.join(timeout=1)
                    self.assertFalse(timed_out, "utility failed to exit after download finished: results=%s" % results)
                    self.assertFalse(tk_errors, tk_errors)
                    self.assertEqual(results, [True], "auxiliary process exited before download completion")
                    showerror.assert_not_called()
                    self.assertEqual(Path(dest).read_bytes(), payload)
        finally:
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=1)

    def test_export_waits_for_main_thread_notification_after_worker_exits(self):
        for fail in (False, True):
            with self.subTest(failure=fail):
                app = self.app()
                app._diagnostics_thread = None
                app._full_log = []
                app.current_project = None
                app._task_title = ""
                app.busy = False
                app._session_log = None
                app._show_export_dialog = Mock()

                def immediate_thread(target, **kwargs):
                    return SimpleNamespace(start=target, is_alive=lambda: False)

                with patch.object(kohya_gui.threading, "Thread", side_effect=immediate_thread), \
                        patch.object(kohya_gui, "write_bundle", side_effect=RuntimeError("fixture failure") if fail else None,
                                     return_value="fixture.txt"), \
                        patch.object(kohya_gui.messagebox, "showerror") as showerror:
                    app.cmd_export_diagnostics()
                    app._finish_utility_only()
                    app.root.run_idle()
                    app.root.quit.assert_not_called()
                    self.assertTrue(app._exporting_diagnostics)
                    next(callback for delay, callback in app.root.timers if delay == 0)()
                    self.assertFalse(app._exporting_diagnostics)
                    if fail:
                        showerror.assert_called_once()
                        app._show_export_dialog.assert_not_called()
                    else:
                        app._show_export_dialog.assert_called_once_with("fixture.txt")
                    app._finish_utility_only()
                    app.root.run_idle()
                    app.root.quit.assert_called_once()

    def test_queue_registers_worker_until_stopping_cleanup_finishes(self):
        from gui.queue_window import TrainQueueWindow
        app = self.app()
        window = TrainQueueWindow.__new__(TrainQueueWindow)
        window.app = app
        window._master = app.root
        window.win = Mock()
        window.win.winfo_exists.return_value = False
        window.status_var = Mock()
        window._running = False
        window.queue = ["fixture"]
        window._lines = []
        app._queue_win = window
        worker = Mock()
        worker.is_alive.return_value = True
        with patch("gui.queue_window.threading.Thread", return_value=worker), \
                patch.object(kohya_gui.core, "stop_active_process"):
            window.start()
            self.assertIs(app._queue_worker, worker)
            worker.start.assert_called_once()
            window.close()
            self.assertIsNone(app._queue_win)
            app._finish_utility_only()
            app.root.run_idle()
            app.root.quit.assert_not_called()
            window._worker(["fixture"])
            next(callback for delay, callback in app.root.timers if delay == 0)()
            self.assertEqual(window.status_var.set.call_count, 1)
        worker.is_alive.return_value = False
        app._finish_utility_only()
        app.root.run_idle()
        app.root.quit.assert_called_once()
        self.assertEqual(app.q.get_nowait()[0], "LOG")

    def test_failed_download_launch_resets_state_and_reports_error(self):
        app = self.app()
        app.dl_win = SimpleNamespace(destroy=Mock())
        app._show_dl_ui = Mock()
        with patch.object(kohya_gui, "_ModelDownloader") as downloader, \
                patch.object(kohya_gui.messagebox, "showerror") as showerror:
            downloader.return_value.start.side_effect = RuntimeError("fixture failure")
            self.assertFalse(app._launch_model_download("fixture-url", "fixture.bin", "fixture.bin", "1 KB", "base", "test"))
            showerror.assert_called_once()
        self.assertFalse(app._downloading)
        self.assertIsNone(app.dl_win)

    def test_cancel_keeps_task_alive_until_downloader_completion(self):
        app = self.app()
        app._downloading = True
        app._dl = SimpleNamespace(cancel=Mock(), error="cancelled")
        app.dl_status_var = Mock()
        app.dl_cancel_button = Mock()
        app.dl_win = SimpleNamespace(destroy=Mock())
        app.cmd_dl_cancel()
        app._dl.cancel.assert_called_once()
        self.assertTrue(app._downloading)
        app._finish_utility_only()
        app.root.run_idle()
        app.root.quit.assert_not_called()
        with patch.object(kohya_gui.messagebox, "showinfo") as showinfo:
            app._handle_dl_done(False, "fixture.bin")
            showinfo.assert_called_once()
        self.assertFalse(app._downloading)
        self.assertIsNone(app.dl_win)

    def test_closing_classic_app_detects_model_download(self):
        app = self.app()
        app._downloading = True
        with patch.object(kohya_gui.core, "active_process_pids", return_value=[]):
            self.assertTrue(app._task_running())


if __name__ == "__main__":
    unittest.main()
