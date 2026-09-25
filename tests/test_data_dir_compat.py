import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kohya_core import paths
import kohya_gui


class DataDirCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.appdata = self.root / "Roaming"
        self.data_root = self.appdata / "KohyaLoraTool"
        self.kit_dir = self.root / "Install" / "Kohya一键工具"
        self.install_data = self.root / "Install" / "KohyaLoraTool_data"
        self.appdata.mkdir()
        self.kit_dir.mkdir(parents=True)
        self._patches = [
            patch.dict(os.environ, {"APPDATA": str(self.appdata)}, clear=False),
            patch.object(paths, "KIT_DIR", str(self.kit_dir)),
            patch.object(sys, "frozen", True, create=True),
            patch.object(paths, "_STARTUP_DATA_DIR", ""),
        ]
        for item in self._patches:
            item.start()
            self.addCleanup(item.stop)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _write_data(root, relative="projects/legacy.json"):
        path = Path(root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"name":"legacy"}', encoding="utf-8")
        return path

    def test_adopts_populated_appdata_and_persists_it(self):
        marker = self._write_data(self.data_root)

        result = paths.resolve_data_dir_startup()

        self.assertEqual(result["status"], "adopt")
        self.assertTrue(result["persisted"])
        self.assertEqual(Path(paths.data_dir()), self.data_root)
        self.assertTrue(marker.is_file())
        settings = json.loads(Path(paths._settings_path()).read_text(encoding="utf-8"))
        self.assertEqual(settings["data_dir"], str(self.data_root))

    def test_adopts_populated_install_data_when_it_is_the_only_existing_root(self):
        marker = self._write_data(self.install_data, "output/legacy.safetensors")

        result = paths.resolve_data_dir_startup()

        self.assertEqual(result["status"], "adopt")
        self.assertEqual(Path(paths.data_dir()), self.install_data)
        self.assertTrue(marker.is_file())

    def test_conflict_requires_a_choice_and_keeps_both_roots(self):
        appdata_marker = self._write_data(self.data_root)
        install_marker = self._write_data(self.install_data, "output/current.safetensors")

        unresolved = paths.resolve_data_dir_startup()
        self.assertFalse(unresolved["ok"])
        self.assertEqual(unresolved["status"], "conflict")
        self.assertEqual(len(unresolved["options"]), 2)

        chosen = paths.resolve_data_dir_startup(str(self.data_root))

        self.assertTrue(chosen["ok"])
        self.assertEqual(Path(paths.data_dir()), self.data_root)
        self.assertTrue(appdata_marker.is_file())
        self.assertTrue(install_marker.is_file())

    def test_empty_new_install_uses_adjacent_root_without_migrating_settings(self):
        # The settings file alone is not treated as user data.
        paths._settings_path()

        inspected = paths.inspect_data_dir_startup()
        result = paths.resolve_data_dir_startup()

        self.assertEqual(inspected["status"], "default")
        self.assertEqual(Path(result["path"]), self.install_data)
        self.assertEqual(Path(paths.data_dir()), self.install_data)
        settings_path = Path(paths._settings_path())
        if settings_path.is_file():
            self.assertNotIn("data_dir", json.loads(settings_path.read_text(encoding="utf-8")))

    def test_explicit_data_root_wins_even_when_another_root_has_files(self):
        custom = self.root / "ChosenData"
        custom.mkdir()
        self._write_data(self.install_data, "projects/other.json")
        self.assertTrue(paths.save_data_setting(str(custom)))

        inspected = paths.inspect_data_dir_startup()
        result = paths.resolve_data_dir_startup()

        self.assertEqual(inspected["status"], "configured")
        self.assertEqual(Path(result["path"]), custom)
        self.assertEqual(Path(paths.data_dir()), custom)

    def test_startup_prompt_routes_yes_to_appdata_and_no_to_install(self):
        appdata = str(self.data_root)
        install = str(self.install_data)
        info = {"status": "conflict", "appdata": appdata, "install": install}

        for answer, expected in ((True, appdata), (False, install)):
            with self.subTest(answer=answer):
                root = Mock()
                with patch.object(kohya_gui.core, "inspect_data_dir_startup", return_value=info), \
                        patch.object(kohya_gui.core, "resolve_data_dir_startup",
                                     return_value={"ok": True, "path": expected, "persisted": True}), \
                        patch.object(kohya_gui.tk, "Tk", return_value=root), \
                        patch.object(kohya_gui.messagebox, "askyesnocancel", return_value=answer), \
                        patch.object(kohya_gui.messagebox, "showinfo"):
                    self.assertTrue(kohya_gui._prepare_data_dir_startup())
                    kohya_gui.core.resolve_data_dir_startup.assert_called_with(expected)
                root.destroy.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
