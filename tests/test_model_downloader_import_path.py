import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model_downloader import _sanitize_utility_sys_path


class ModelDownloaderImportPathTests(unittest.TestCase):
    def test_dll_root_is_kept_when_frozen_and_removed_for_external_python(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle_root = Path(temp) / "bundle"
            bundle_root.mkdir()
            (bundle_root / "python312.dll").write_bytes(b"fixture")
            equivalent_bundle_path = str(bundle_root) + "\\."
            other_path = str(Path(temp) / "venv" / "Lib")

            frozen_path = [str(bundle_root), equivalent_bundle_path, other_path]
            _sanitize_utility_sys_path(str(bundle_root), frozen_path, frozen=True)
            self.assertEqual(frozen_path, [str(bundle_root), equivalent_bundle_path, other_path])

            external_path = [str(bundle_root), equivalent_bundle_path, other_path]
            _sanitize_utility_sys_path(str(bundle_root), external_path, frozen=False)
            self.assertEqual(external_path, [other_path])


if __name__ == "__main__":
    unittest.main()
