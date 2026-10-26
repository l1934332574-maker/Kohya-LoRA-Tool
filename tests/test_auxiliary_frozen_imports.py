"""Auxiliary imports must keep the frozen PYZ path usable after dataset scans."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AuxiliaryFrozenImportsTests(unittest.TestCase):
    def run_import(self, module, frozen, bundled_dll):
        with tempfile.TemporaryDirectory(prefix="kohya-import-test-") as temporary:
            root = Path(temporary)
            (root / (module + ".py")).write_bytes((ROOT / (module + ".py")).read_bytes())
            if bundled_dll:
                (root / "python312.dll").write_bytes(b"fixture")
            (root / "kohya_bundled_workers.py").write_text("FILES = {}\n", encoding="utf-8")
            code = """
import argparse, functools, json, os, re, shutil, subprocess, sys, time, traceback
from pathlib import Path
root = sys.argv[1]
sys.path.insert(0, root)
sys.frozen = sys.argv[3] == "True"
before = list(sys.path)
__import__(sys.argv[2])
result = {"before": before, "after": list(sys.path)}
if sys.frozen:
    import kohya_bundled_workers
    result["lazy_worker_import"] = True
print(json.dumps(result))
"""
            run = subprocess.run([sys.executable, "-I", "-c", code, str(root), module, str(frozen)],
                                 cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            return json.loads(run.stdout)

    def test_frozen_import_keeps_path_and_later_worker_import(self):
        for module in ("preprocess", "video_caption", "model_downloader"):
            with self.subTest(module=module):
                result = self.run_import(module, frozen=True, bundled_dll=True)
                self.assertEqual(result["after"], result["before"])
                self.assertTrue(result["lazy_worker_import"])

    def test_external_python_still_removes_bundled_dll_root(self):
        for module in ("preprocess", "video_caption", "model_downloader"):
            with self.subTest(module=module):
                result = self.run_import(module, frozen=False, bundled_dll=True)
                self.assertEqual(result["after"], result["before"][1:])

    def test_source_import_without_bundled_dll_keeps_path(self):
        for module in ("preprocess", "video_caption", "model_downloader"):
            with self.subTest(module=module):
                result = self.run_import(module, frozen=False, bundled_dll=False)
                self.assertEqual(result["after"], result["before"])


if __name__ == "__main__":
    unittest.main()
