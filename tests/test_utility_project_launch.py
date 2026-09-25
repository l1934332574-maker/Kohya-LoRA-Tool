import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kohya_gui import _schedule_initial_project_action


class FakeRoot:
    def __init__(self):
        self.timers = []
        self.idle_callbacks = []
        self.after = Mock(side_effect=self._after)
        self.after_idle = Mock(side_effect=self._after_idle)

    def _after(self, _delay, callback):
        self.timers.append(callback)
        return len(self.timers)

    def _after_idle(self, callback):
        self.idle_callbacks.append(callback)
        return len(self.idle_callbacks)

    def run_modal_nested_loop(self):
        # A Tk message box runs a nested event loop while the project loader is
        # still on the stack. Any independently scheduled timer can fire here.
        while self.timers:
            self.timers.pop(0)()

    def run_idle(self):
        while self.idle_callbacks:
            self.idle_callbacks.pop(0)()


class UtilityProjectLaunchTests(unittest.TestCase):
    def test_project_action_waits_until_project_restore_modal_returns(self):
        root = FakeRoot()
        state = {"project_loaded": False}
        events = []

        def open_project():
            events.append("project restore started")
            root.run_modal_nested_loop()
            state["project_loaded"] = True
            events.append("project restore finished")

        def open_utility():
            events.append("utility opened with project=%s" % state["project_loaded"])

        _schedule_initial_project_action(
            root,
            open_project,
            open_utility,
            lambda: state["project_loaded"],
        )

        root.timers.pop(0)()
        self.assertEqual(events, ["project restore started", "project restore finished"])

        root.run_idle()
        self.assertEqual(events[-1], "utility opened with project=True")

    def test_failed_project_restore_does_not_open_project_scoped_utility(self):
        root = FakeRoot()
        events = []

        _schedule_initial_project_action(
            root,
            lambda: events.append("project restore failed"),
            lambda: events.append("utility opened"),
            lambda: False,
            on_skip=lambda: events.append("utility host closed"),
        )

        root.timers.pop(0)()
        root.run_idle()
        self.assertEqual(events, ["project restore failed", "utility host closed"])


if __name__ == "__main__":
    unittest.main()
