import json
import struct
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from kohya_core import lora_continue as continuation


def write_lora(path, style="down"):
    stem = "diffusion_model.block"
    names = ("lora_down", "lora_up") if style == "down" else ("lora_A", "lora_B")
    chunks = [struct.pack("<4f", 1, 2, 3, 4), struct.pack("<4f", 5, 6, 7, 8), struct.pack("<f", 2)]
    keys = [stem + "." + names[0] + ".weight", stem + "." + names[1] + ".weight", stem + ".alpha"]
    shapes = [[2, 2], [2, 2], []]
    header, offset = {}, 0
    for key, shape, data in zip(keys, shapes, chunks):
        header[key] = {"dtype": "F32", "shape": shape, "data_offsets": [offset, offset + len(data)]}
        offset += len(data)
    raw = json.dumps(header, separators=(",", ":")).encode()
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + b"".join(chunks))


class FakeCore:
    def __init__(self, root):
        self.root = root
        self.saved = {}
    def data_sub(self, *parts):
        p = self.root.joinpath(*parts)
        p.mkdir(parents=True, exist_ok=True)
        return str(p)
    def dataset_train_dir(self, mode, project):
        return str(self.root / "dataset" / project / ("train" if mode == "style" else "train_character"))
    def save_project(self, name, config):
        self.saved[name] = config
        return True


class ContinueTrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_supported_weight_formats_and_truncated_file(self):
        for style in ("down", "ab"):
            path = self.root / (style + ".safetensors")
            write_lora(path, style)
            info = continuation.inspect(path)
            self.assertEqual((info["rank"], info["alpha"], info["modules"]), (2, 2, 1))
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaises(ValueError):
                continuation.inspect(path)

    def test_sample_match_requires_exact_checkpoint(self):
        output = self.root / "output"
        output.mkdir()
        a = output / "moss-000006.safetensors"
        write_lora(a)
        rows, selected = continuation.checkpoints(output, "sample/moss-e000006_00_123.png")
        self.assertEqual(selected, str(a.resolve()))
        self.assertEqual(len(rows), 1)
        self.assertEqual(continuation.checkpoints(output, "sample/moss-e000007_00_123.png")[1], "")

    def test_creates_separate_project_with_original_image_and_current_caption(self):
        core = FakeCore(self.root)
        raw = self.root / "original"
        raw.mkdir()
        Image.new("RGB", (1200, 800), "red").save(raw / "photo.png")
        (raw / "photo.txt").write_text("old caption", encoding="utf-8")
        trained = Path(core.dataset_train_dir("character", "parent"))
        trained.mkdir(parents=True)
        Image.new("RGB", (512, 341), "red").save(trained / "photo.png")
        (trained / "photo.txt").write_text("edited caption", encoding="utf-8")
        lora = self.root / "model.safetensors"
        write_lora(lora)
        config = {"mode": "character", "base_type": "sdxl", "raw_dir": str(raw), "params": {"resolution": 512}}
        name, child = continuation.create(core, config, "parent", {"source_path": str(lora), "kind": "refine", "resolution": 1024, "epochs": 2, "steps": 200})
        self.assertNotEqual(name, "parent")
        self.assertEqual(config["raw_dir"], str(raw))
        copied = Path(child["raw_dir"]) / "photo.png"
        with Image.open(copied) as image:
            self.assertEqual(image.size, (1200, 800))
        self.assertEqual(copied.with_suffix(".txt").read_text(encoding="utf-8"), "edited caption")
        self.assertEqual(Path(child["initial_lora"]).read_bytes(), lora.read_bytes())
        self.assertEqual(core.saved[name]["params"]["resolution"], 1024)

    def test_failed_snapshot_cleans_only_child_output(self):
        core = FakeCore(self.root)
        raw = self.root / "original"
        raw.mkdir()
        Image.new("RGB", (100, 100)).save(raw / "missing-caption.png")
        lora = self.root / "model.safetensors"
        write_lora(lora)
        config = {"mode": "character", "raw_dir": str(raw), "params": {"resolution": 512}}
        with self.assertRaises(ValueError):
            continuation.create(core, config, "parent", {"source_path": str(lora), "resolution": 512})
        self.assertEqual(list((self.root / "output").iterdir()), [])
        self.assertTrue(lora.is_file())


if __name__ == "__main__":
    unittest.main()
