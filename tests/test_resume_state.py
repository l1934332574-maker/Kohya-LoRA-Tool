import os
import tempfile
import time
import unittest
from pathlib import Path

from tests.test_anima_component_integrity import legacy


class ResumeStateTests(unittest.TestCase):
    def test_musubi_epoch_state_is_found_and_completed_run_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            name = "krea2_lora"
            empty = output / f"{name}-000003-state"
            empty.mkdir()
            first = output / f"{name}-000001-state"
            second = output / f"{name}-000002-state"
            for state in (first, second):
                state.mkdir()
                (state / "optimizer.bin").write_bytes(b"state")
            stamp = time.time() - 60
            os.utime(second, (stamp, stamp))

            self.assertEqual(legacy.find_musubi_state(str(output), name), str(second))
            self.assertEqual(legacy.resume_step_from(str(second), steps_per_epoch=120), 240)

            final = output / f"{name}.safetensors"
            final.write_bytes(b"finished")
            self.assertIsNone(legacy.find_musubi_state(str(output), name))
            os.utime(final, (stamp - 1, stamp - 1))
            self.assertEqual(legacy.find_musubi_state(str(output), name), str(second))

    def test_new_interruption_wins_over_old_completed_run(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            base_time = time.time() - 1000
            for name, finder, old_suffix, new_suffix, marker in (
                ("kohya", legacy.find_latest_state, "step00000900", "step00000100", None),
                ("musubi", legacy.find_musubi_state, "000009", "000001", "optimizer.bin"),
                ("fizgig", legacy.find_fizgig_state, "000009", "000001", "training_state.json"),
            ):
                old_state = output / f"{name}-{old_suffix}-state"
                new_state = output / f"{name}-{new_suffix}-state"
                for state in (old_state, new_state):
                    state.mkdir()
                    if marker:
                        (state / marker).write_bytes(b"state")
                final = output / f"{name}.safetensors"
                final.write_bytes(b"finished")
                os.utime(old_state, (base_time, base_time))
                os.utime(final, (base_time + 10, base_time + 10))
                os.utime(new_state, (base_time + 20, base_time + 20))
                self.assertEqual(finder(str(output), name), str(new_state))


if __name__ == "__main__":
    unittest.main()
