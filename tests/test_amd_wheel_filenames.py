"""Exercise the real AMD installer with simulated downloads and pip filename validation."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from packaging.utils import parse_wheel_filename

import Kohya一键工具 as core


class AmdWheelFilenameTests(unittest.TestCase):
    def run_install(self, folder, urls, downloader):
        installed = []

        def validate_pip_inputs(venv, paths, logf):
            for path in paths:
                parse_wheel_filename(Path(path).name)
                installed.append(Path(path))
            return 0

        with patch.object(core, "data_dir", return_value=str(folder)), \
             patch.object(core, "_require_healthy_amd_venv"), \
             patch.object(core, "_amd_torch_wheels", return_value=urls), \
             patch.object(core, "_download_with_resume", side_effect=downloader), \
             patch.object(core, "_wheel_valid", return_value=True), \
             patch.object(core, "run_pip_in_venv", side_effect=validate_pip_inputs):
            core.install_amd_torch("fixture-venv", lambda _: None)
        return installed

    def test_rx6900xt_actual_urls_have_valid_local_names(self):
        with tempfile.TemporaryDirectory() as folder:
            downloaded = []

            def download(url, dest, *args, **kwargs):
                downloaded.append(url)
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                Path(dest).write_bytes(b"fixture")
                return True

            installed = self.run_install(folder, core.AMD_GFX103X_TORCH_WHEELS, download)
            self.assertEqual(downloaded, core.AMD_GFX103X_TORCH_WHEELS)
            self.assertEqual(len(installed), 3)
            self.assertTrue(all("+rocmsdk" in path.name and "%2B" not in path.name for path in installed))

    def test_valid_legacy_encoded_cache_is_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            url = core.AMD_GFX103X_TORCH_WHEELS[0]
            cached = Path(folder) / "installer_cache" / "amd_torch" / os.path.basename(url)
            cached.parent.mkdir(parents=True)
            cached.write_bytes(b"x" * (1024 * 1024 + 1))
            with patch.object(core, "_download_with_resume") as download:
                installed = self.run_install(folder, [url], download)
                download.assert_not_called()
            self.assertEqual(installed[0].stat().st_size, 1024 * 1024 + 1)
            self.assertFalse(cached.exists())

    def test_small_torchaudio_cache_is_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            url = core.AMD_GFX103X_TORCH_WHEELS[1]
            name = "torchaudio-2.9.0+rocmsdk20251207-cp312-cp312-win_amd64.whl"
            cached = Path(folder) / "installer_cache" / "amd_torch" / name
            cached.parent.mkdir(parents=True)
            cached.write_bytes(b"small-valid-wheel-fixture")
            with patch.object(core, "_download_with_resume") as download:
                installed = self.run_install(folder, [url], download)
                download.assert_not_called()
            self.assertEqual(installed, [cached])

    def test_partial_legacy_download_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            url = core.AMD_GFX103X_TORCH_WHEELS[0]
            cache = Path(folder) / "installer_cache" / "amd_torch"
            cache.mkdir(parents=True)
            old_part = cache / (os.path.basename(url) + ".part")
            old_part.write_bytes(b"partial")

            def download(_url, dest, *args, **kwargs):
                self.assertEqual(Path(str(dest) + ".part").read_bytes(), b"partial")
                Path(dest).write_bytes(b"completed")
                return True

            self.run_install(folder, [url], download)
            self.assertFalse(old_part.exists())

    def test_official_url_and_query_are_decoded(self):
        with tempfile.TemporaryDirectory() as folder:
            url = "https://example.test/torch-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl?download=1"

            def download(_url, dest, *args, **kwargs):
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                Path(dest).write_bytes(b"fixture")
                return True

            installed = self.run_install(folder, [url], download)
            self.assertEqual(installed[0].name, "torch-2.9.1+rocm7.2.1-cp312-cp312-win_amd64.whl")


if __name__ == "__main__":
    unittest.main()
