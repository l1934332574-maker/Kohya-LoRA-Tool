import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_legacy_tool():
    """Load the classic app module without leaving its Windows Popen wrapper installed."""
    source = ROOT / "Kohya一键工具.py"
    spec = importlib.util.spec_from_file_location("kohya_legacy_anima_integrity_test", source)
    module = importlib.util.module_from_spec(spec)
    previous_popen = subprocess.Popen
    try:
        spec.loader.exec_module(module)
    finally:
        subprocess.Popen = previous_popen
    return module


legacy = _load_legacy_tool()


def _write_safetensors(path, tensors, payload_size=None, trailing=b""):
    """Write a small synthetic safetensors file; offsets are (start, end) pairs."""
    header = {
        name: {"dtype": "U8", "shape": [end - start], "data_offsets": [start, end]}
        for name, start, end in tensors
    }
    raw = json.dumps(header, separators=(",", ":")).encode("utf-8")
    with open(path, "wb") as handle:
        handle.write(struct.pack("<Q", len(raw)))
        handle.write(raw)
        handle.truncate(8 + len(raw) + (payload_size if payload_size is not None else max(
            (end for _name, _start, end in tensors), default=0,
        )))
        if trailing:
            handle.seek(0, os.SEEK_END)
            handle.write(trailing)


def _write_sparse_model(path, payload_size, trailing=b""):
    _write_safetensors(path, [("embed_tokens.weight", 0, payload_size)], payload_size, trailing)


class AnimaComponentIntegrityTests(unittest.TestCase):
    def test_safetensors_must_cover_the_entire_payload_exactly(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            exact = root / "exact.safetensors"
            trailing = root / "trailing.safetensors"
            gap = root / "gap.safetensors"
            overlap = root / "overlap.safetensors"
            empty = root / "empty.safetensors"
            _write_safetensors(exact, [("a", 0, 2), ("b", 2, 5)], payload_size=5)
            _write_safetensors(trailing, [("a", 0, 2)], payload_size=2, trailing=b"x")
            _write_safetensors(gap, [("a", 0, 1), ("b", 2, 3)], payload_size=3)
            _write_safetensors(overlap, [("a", 0, 2), ("b", 1, 3)], payload_size=3)
            _write_safetensors(empty, [("empty", 0, 0)], payload_size=0)

            self.assertTrue(legacy._safetensors_complete(str(exact)))
            self.assertTrue(legacy._safetensors_complete(str(empty)))
            self.assertFalse(legacy._safetensors_complete(str(trailing)))
            self.assertFalse(legacy._safetensors_complete(str(gap)))
            self.assertFalse(legacy._safetensors_complete(str(overlap)))

    def test_qwen_finder_and_manual_file_validation_reject_bad_safetensors(self):
        with tempfile.TemporaryDirectory() as temp:
            qwen_dir = Path(temp) / "Qwen3-0.6B"
            qwen_dir.mkdir()
            (qwen_dir / "config.json").write_text('{"model_type":"qwen3"}', encoding="utf-8")
            weight = qwen_dir / "model.safetensors"
            _write_safetensors(weight, [("embed_tokens.weight", 0, 2)], payload_size=2, trailing=b"x")

            self.assertIsNone(legacy._anima_find_qwen3(str(Path(temp))))
            ok, reason = legacy._anima_component_ok("qwen3", str(weight))
            self.assertFalse(ok)
            self.assertIn("safetensors", reason.lower())

    def test_qwen_finder_rejects_undersized_official_single_weight(self):
        with tempfile.TemporaryDirectory() as temp:
            qwen_dir = Path(temp) / "Qwen3-0.6B"
            qwen_dir.mkdir()
            (qwen_dir / "config.json").write_text('{"model_type":"qwen3"}', encoding="utf-8")
            weight = qwen_dir / "model.safetensors"
            _write_sparse_model(weight, 925_000_000)

            # This is below the standard Qwen3-0.6B download's existing 1 GB minimum.
            self.assertTrue(legacy._safetensors_complete(str(weight)))
            self.assertIsNone(legacy._anima_find_qwen3(str(Path(temp))))
            ok, reason = legacy._anima_component_ok("qwen3", str(qwen_dir))
            self.assertFalse(ok)
            self.assertIn("权重", reason)

    def test_anima_preflight_uses_training_loader_and_stops_on_bad_weight(self):
        with tempfile.TemporaryDirectory() as temp:
            weight = Path(temp) / "model.safetensors"
            weight.write_bytes(b"broken")
            response = SimpleNamespace(returncode=1, stderr="SafetensorError: MetadataIncompleteBuffer",
                                       stdout="")
            with patch.object(legacy.subprocess, "run", return_value=response) as run:
                with self.assertRaisesRegex(RuntimeError, "MetadataIncompleteBuffer"):
                    legacy._anima_verify_qwen3_loader(str(Path(temp)), "train-python.exe",
                                                      logf=lambda _line: None)
            self.assertEqual(run.call_args.args[0][0], "train-python.exe")
            self.assertEqual(run.call_args.args[0][-1], str(weight))

    def test_qwen_shards_need_complete_index_or_filename_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            qwen_dir = Path(temp) / "Qwen3-0.6B"
            qwen_dir.mkdir()
            (qwen_dir / "config.json").write_text('{"model_type":"qwen3"}', encoding="utf-8")
            first = qwen_dir / "model-00001-of-00002.safetensors"
            second = qwen_dir / "model-00002-of-00002.safetensors"
            _write_safetensors(first, [("a", 0, 1)], payload_size=1)

            self.assertIsNone(legacy._anima_find_qwen3(str(Path(temp))))
            _write_safetensors(second, [("b", 0, 1)], payload_size=1)
            self.assertEqual(legacy._anima_find_qwen3(str(Path(temp))), str(qwen_dir))

            index = qwen_dir / "model.safetensors.index.json"
            index.write_text(json.dumps({"weight_map": {"a": first.name, "b": "missing.safetensors"}}),
                             encoding="utf-8")
            self.assertIsNone(legacy._anima_find_qwen3(str(Path(temp))))

    def test_qwen_directory_with_legacy_pytorch_bin_remains_usable(self):
        with tempfile.TemporaryDirectory() as temp:
            qwen_dir = Path(temp) / "Qwen3-0.6B"
            qwen_dir.mkdir()
            (qwen_dir / "config.json").write_text('{"model_type":"qwen3"}', encoding="utf-8")
            (qwen_dir / "pytorch_model.bin").write_bytes(b"legacy checkpoint")

            self.assertEqual(legacy._anima_find_qwen3(str(Path(temp))), str(qwen_dir))

    def test_selected_data_root_precedes_appdata_and_legacy_roots_remain(self):
        selected = Path("F:/Kohya/KohyaLoraTool_data")
        with patch.object(legacy, "data_dir", return_value=str(selected)), \
                patch.dict(os.environ, {"APPDATA": "C:/Users/test/AppData/Roaming"}):
            bases = legacy._anima_bases()

        self.assertEqual(Path(bases[0]), selected / "anima")
        self.assertIn(os.path.join("KohyaLoraTool", "anima"), bases[1])
        self.assertIn(os.path.join("Kohya_ss"), bases[2])

    def test_qwen_scan_prefers_selected_root_then_reuses_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            selected_data = root / "ChosenData"
            selected_base = selected_data / "anima"
            legacy_base = root / "Roaming" / "KohyaLoraTool" / "anima"

            def add_model(base):
                model = base / "Qwen3-0.6B"
                model.mkdir(parents=True)
                (model / "config.json").write_text('{"model_type":"qwen3"}', encoding="utf-8")
                _write_safetensors(model / "model.safetensors", [("a", 0, 1)], payload_size=1)
                return model

            selected_model = add_model(selected_base)
            legacy_model = add_model(legacy_base)
            with patch.object(legacy, "data_dir", return_value=str(selected_data)), \
                    patch.object(legacy, "anima_get_component", return_value=None), \
                    patch.object(legacy, "_QWEN3_STANDARD_SINGLE_MIN_BYTES", 0), \
                    patch.dict(os.environ, {"APPDATA": str(root / "Roaming")}):
                self.assertEqual(legacy._anima_find_qwen3_any()[0], str(selected_model))
                import shutil
                shutil.rmtree(selected_model)
                self.assertEqual(legacy._anima_find_qwen3_any()[0], str(legacy_model))

    def test_modelscope_redownloads_corrupt_weight_and_keeps_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            qwen_dir = Path(temp) / "Qwen3-0.6B"
            qwen_dir.mkdir()
            (qwen_dir / "config.json").write_text(
                '{"model_type":"qwen3"}' + " " * 200, encoding="utf-8",
            )
            (qwen_dir / "generation_config.json").write_text(
                '{"eos_token_id":0}' + " " * 200, encoding="utf-8",
            )
            (qwen_dir / "merges.txt").write_text("x" * 100_000, encoding="utf-8")
            (qwen_dir / "tokenizer.json").write_text("{}" + " " * 1_000_000, encoding="utf-8")
            (qwen_dir / "tokenizer_config.json").write_text("{}" + " " * 500, encoding="utf-8")
            (qwen_dir / "vocab.json").write_text("{}" + " " * 100_000, encoding="utf-8")
            weight = qwen_dir / "model.safetensors"
            _write_sparse_model(weight, 1_000_000_000, trailing=b"x")
            original_size = weight.stat().st_size
            downloads = []

            def download(_url, dest, _logf, direct=False):
                downloads.append(Path(dest).name)
                self.assertFalse(Path(dest).exists(), "corrupt destination should be backed up first")
                _write_sparse_model(dest, 1_000_000_000)
                return True

            with patch.object(legacy, "_download_with_resume", side_effect=download):
                self.assertTrue(legacy._download_qwen3_from_modelscope(str(qwen_dir), logf=lambda _line: None))

            self.assertEqual(downloads, ["model.safetensors"])
            backups = list(qwen_dir.glob("model.safetensors.corrupt_*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].stat().st_size, original_size)
            self.assertTrue(legacy._safetensors_complete(str(weight)))

    def test_dataset_bucket_configuration_does_not_start_training_progress(self):
        monitor = legacy.TrainMonitor()
        monitor.start(total=9280)

        monitor.on_line("bucket_reso_steps: 64")
        monitor.on_line("0/29 [00:00<?, ?it/s]")
        monitor.on_line("29/29 [00:12<00:00, 2.37it/s]")
        snapshot = monitor.snapshot()

        self.assertEqual(snapshot["total"], 9280)
        self.assertEqual(snapshot["phase"], "idle")
        self.assertEqual(snapshot["step"], 0)

    def test_real_steps_and_epoch_lines_still_enter_training_phase(self):
        by_steps = legacy.TrainMonitor()
        by_steps.start(total=100)
        by_steps.on_line("steps: 12, loss: 0.1")
        self.assertEqual(by_steps.snapshot()["phase"], "train")
        self.assertEqual(by_steps.snapshot()["step"], 12)

        by_epoch = legacy.TrainMonitor()
        by_epoch.start(total=100)
        by_epoch.on_line("epoch: 1/2")
        self.assertEqual(by_epoch.snapshot()["phase"], "train")


if __name__ == "__main__":
    unittest.main()
