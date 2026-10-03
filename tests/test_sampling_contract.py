"""Sampling switches must reach the engine configuration consistently."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

import Kohya一键工具 as core


class SamplingContractTests(unittest.TestCase):
    def test_auto_preview_keeps_high_vram_sampling_enabled(self):
        self.assertTrue(core._sample_preview_enabled({"sample_preview": None}, 24))
        self.assertFalse(core._sample_preview_enabled({"sample_preview": None}, 16))
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(core, "data_sub", side_effect=lambda *parts: os.path.join(temporary, *parts)):
                path = core._write_sample_prompts(
                    "auto", {"sample_preview": None, "trigger": "subject"}, "character"
                )
            self.assertTrue(path and Path(path).is_file())

    def test_h3_disabled_preview_reaches_training_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            cfg = os.path.join(temporary, "h3.yaml")
            core.write_h3_train_yaml(
                {"project": "sampling", "sample_preview": False, "resolution": 512},
                temporary, temporary, cfg, vram_gb=24, logf=lambda _line: None,
            )
            text = Path(cfg).read_text(encoding="utf-8")
            self.assertIn("disable_sampling: true", text)
            self.assertIn("      sample:\n", text)

    def test_classic_preview_retries_an_image_still_being_written(self):
        import kohya_gui as gui
        from PIL import Image

        class Value:
            def __init__(self):
                self.text = ""

            def set(self, text):
                self.text = text

        class Label:
            def configure(self, **_kwargs):
                pass

        with tempfile.TemporaryDirectory() as temporary:
            image_path = Path(temporary, "output", "project", "sample", "step_100.png")
            image_path.parent.mkdir(parents=True)
            Image.new("RGB", (8, 8), "white").save(image_path)
            current = SimpleNamespace(
                current_project="project", _sample_last=0, _sample_shown=None,
                mon_sample_txt=Value(), mon_sample_lbl=Label(),
            )
            current._is_sample_file = lambda name, dirname: gui.App._is_sample_file(current, name, dirname)
            with patch.object(gui.core, "data_sub", side_effect=lambda *parts: str(Path(temporary, *parts))), \
                    patch.object(gui.Image, "open", side_effect=[OSError("file still being written"), Image.new("RGB", (8, 8), "white")]), \
                    patch.object(gui.ctk, "CTkImage", side_effect=lambda **kwargs: kwargs):
                gui.App._refresh_sample_preview(current)
                self.assertIsNone(current._sample_shown)
                current._sample_last = 0
                gui.App._refresh_sample_preview(current)
            self.assertEqual(current._sample_shown[0], str(image_path))
            self.assertIn("step_100.png", current.mon_sample_txt.text)

    def test_krea2_ai_toolkit_uses_selected_preview_interval(self):
        with tempfile.TemporaryDirectory() as temporary:
            cfg = os.path.join(temporary, "krea2.yaml")
            with patch.object(core, "krea2_model_files", return_value={"raw": os.path.join(temporary, "raw.safetensors")}), \
                    patch.object(core, "count_images", return_value=4):
                core.write_krea2_at_yaml(
                    {"project": "sampling", "sample_preview": True,
                     "sample_interval": 30, "resolution": 512},
                    temporary, temporary, cfg, vram_gb=24, logf=lambda _line: None,
                )
            text = Path(cfg).read_text(encoding="utf-8")
            self.assertIn("sample_every: 30", text)


if __name__ == "__main__":
    unittest.main()
