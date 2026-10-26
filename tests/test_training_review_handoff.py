"""Force confirmation between Event.wait timeout and the worker status check."""
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import gui.modern_host as host
from tests.bridge_fixture import ModernUIBridge
from tests.test_modern_training import FakeCore


class ReviewBoundaryEvent(threading.Event):
    def __init__(self):
        super().__init__()
        self.at_timeout_boundary = threading.Event()
        self.release_timeout = threading.Event()
        self.first_wait = True

    def wait(self, timeout=None):
        if timeout == 0.1 and self.first_wait:
            self.first_wait = False
            self.at_timeout_boundary.set()
            if not self.release_timeout.wait(5):
                raise AssertionError("test failed to release the review timeout")
            # A legal Event.wait result: timed out just before confirmation.
            return False
        return super().wait(timeout)


class TrainingReviewHandoffTests(unittest.TestCase):
    def run_boundary(self, mode, action):
        with tempfile.TemporaryDirectory(prefix="kohya-review-race-") as temporary:
            core = FakeCore(temporary)
            bridge = ModernUIBridge(core)
            params = bridge._classic_training_params(core.project, "demo")
            params.update(mode=mode, training_kind="multi_character" if mode == "moss_fz" else "lora", multi_character={})
            plan = {"mode": mode, "mode_label": "多角色 LoRA" if mode == "moss_fz" else "普通 LoRA", "engine_label": "Fizgig" if mode == "moss_fz" else "AI Toolkit",
                    "vram_gb": 24, "min_images": 15}
            bridge.prepare_training = lambda name: {"ok": True, "plan": plan}
            bridge._classic_training_params = lambda config, name: dict(params)
            fizgig_calls = []
            core.train_fizgig_lora = lambda *args, **kwargs: fizgig_calls.append(kwargs)
            gate = ReviewBoundaryEvent()
            events = iter((gate, threading.Event()))
            threads = []

            def startable_thread(*args, **kwargs):
                thread = threading.Thread(*args, **kwargs)
                threads.append(thread)
                return thread

            proxy = SimpleNamespace(Event=lambda: next(events), Thread=startable_thread)
            with patch.object(host, "threading", proxy):
                try:
                    started = bridge.start_training("demo")
                    self.assertTrue(started["ok"], started)
                    self.assertTrue(gate.at_timeout_boundary.wait(3), bridge.get_task_status(started["task_id"], 0))
                    task_id = started["task_id"]
                    if action == "continue":
                        self.assertTrue(bridge.continue_training(task_id)["ok"])
                        self.assertFalse(bridge.continue_training(task_id)["ok"])
                    else:
                        self.assertTrue(bridge.cancel_task(task_id)["ok"])
                    gate.release_timeout.set()
                    for thread in threads:
                        thread.join(3)
                    self.assertTrue(all(not thread.is_alive() for thread in threads))
                    calls = fizgig_calls if mode == "moss_fz" else core.training_calls
                    status = bridge.get_task_status(task_id, 0)
                    self.assertEqual(len(calls), 1 if action == "continue" else 0, status)
                    self.assertEqual(status["status"], "completed" if action == "continue" else "cancelled", status)
                finally:
                    gate.release_timeout.set()
                    for thread in threads:
                        thread.join(3)

    def test_multi_character_confirmation_at_timeout_starts_engine_once(self):
        self.run_boundary("moss_fz", "continue")

    def test_other_training_confirmation_at_timeout_starts_engine_once(self):
        self.run_boundary("qwen_image", "continue")

    def test_cancellation_at_timeout_never_starts_engine(self):
        self.run_boundary("moss_fz", "cancel")


if __name__ == "__main__":
    unittest.main()
