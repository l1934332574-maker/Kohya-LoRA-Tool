import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kohya_core import paths


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

    def test_packaged_app_keeps_the_existing_install_adjacent_data_root(self):
        # A populated AppData root must not silently replace the established 0.17.x location.
        self._write_data(self.data_root)
        self._write_data(self.install_data, "output/current.safetensors")

        self.assertEqual(Path(paths.data_dir()), self.install_data)

    def test_empty_packaged_install_uses_adjacent_root_without_persisting_it(self):
        paths._settings_path()

        self.assertEqual(Path(paths.data_dir()), self.install_data)
        settings_path = Path(paths._settings_path())
        if settings_path.is_file():
            self.assertNotIn("data_dir", json.loads(settings_path.read_text(encoding="utf-8")))

    def test_source_run_uses_appdata_when_install_following_is_unavailable(self):
        with patch.object(sys, "frozen", False):
            self.assertEqual(Path(paths.data_dir()), self.data_root)

    def test_explicit_data_root_wins_even_when_install_root_has_files(self):
        custom = self.root / "ChosenData"
        custom.mkdir()
        self._write_data(self.install_data, "projects/other.json")
        self.assertTrue(paths.save_data_setting(str(custom)))

        self.assertEqual(Path(paths.data_dir()), custom)

    def test_get_kohya_dir_reuses_kernel_from_other_known_data_root(self):
        custom = self.root / "ChosenData"
        custom.mkdir()
        kernel = self.install_data / "kohya_ss"
        (kernel / "sd-scripts").mkdir(parents=True)
        (kernel / "sd-scripts" / "train_network.py").write_text("# installed", encoding="utf-8")
        pointer = self.root / "Install" / "kohya_dir.txt"

        with patch.object(paths, "_read_data_setting", return_value=str(custom)), \
                patch.object(paths, "KOHYA_DIR_FILE", str(pointer)):
            self.assertEqual(Path(paths.get_kohya_dir()), kernel)

    def test_get_kohya_dir_keeps_explicit_installed_kernel_precedence(self):
        custom = self.root / "ChosenData"
        custom.mkdir()
        kernel = self.root / "ManualKernel"
        (kernel / "sd-scripts").mkdir(parents=True)
        (kernel / "sd-scripts" / "train_network.py").write_text("# installed", encoding="utf-8")
        pointer = self.root / "Install" / "kohya_dir.txt"
        pointer.write_text(str(kernel), encoding="utf-8")

        with patch.object(paths, "_read_data_setting", return_value=str(custom)), \
                patch.object(paths, "KOHYA_DIR_FILE", str(pointer)):
            self.assertEqual(Path(paths.get_kohya_dir()), kernel)

    def test_project_training_images_fall_back_to_the_existing_legacy_root(self):
        selected = self.root / "ChosenData"
        selected.mkdir()
        current_train = selected / "dataset" / "project-a" / "train_character"
        current_train.mkdir(parents=True)
        legacy_train = self.data_root / "dataset" / "project-a" / "train_character"
        legacy_train.mkdir(parents=True)
        (legacy_train / "image.jpg").write_bytes(b"image")
        pointer = self.root / "Install" / "kohya_dir.txt"

        with patch.object(paths, "_read_data_setting", return_value=str(selected)), \
                patch.object(paths, "KOHYA_DIR_FILE", str(pointer)):
            self.assertEqual(
                Path(paths.dataset_train_dir("character", "project-a")), legacy_train,
            )

    def test_shared_legacy_training_images_remain_available(self):
        selected = self.root / "ChosenData"
        selected.mkdir()
        current_train = selected / "dataset" / "train"
        current_train.mkdir(parents=True)
        legacy_train = self.data_root / "dataset" / "train"
        legacy_train.mkdir(parents=True)
        (legacy_train / "style.png").write_bytes(b"image")
        pointer = self.root / "Install" / "kohya_dir.txt"

        with patch.object(paths, "_read_data_setting", return_value=str(selected)), \
                patch.object(paths, "KOHYA_DIR_FILE", str(pointer)):
            self.assertEqual(Path(paths.dataset_train_dir("style")), legacy_train)

    def test_project_data_folder_falls_back_to_the_root_with_existing_files(self):
        selected = self.root / "ChosenData"
        selected.mkdir()
        current_project = selected / "dataset" / "project-a"
        current_project.mkdir(parents=True)
        legacy_project = self.data_root / "dataset" / "project-a"
        legacy_project.mkdir(parents=True)
        (legacy_project / "train_character" / "image.txt").parent.mkdir()
        (legacy_project / "train_character" / "image.txt").write_text("caption", encoding="utf-8")
        pointer = self.root / "Install" / "kohya_dir.txt"

        with patch.object(paths, "_read_data_setting", return_value=str(selected)), \
                patch.object(paths, "KOHYA_DIR_FILE", str(pointer)):
            self.assertEqual(Path(paths.project_data_dir("project-a")), legacy_project)

    def test_projects_in_an_alternate_known_root_remain_listed_and_edit_in_place(self):
        selected = self.root / "ChosenData"
        selected.mkdir()
        legacy_project = self.data_root / "projects" / "project-a.json"
        legacy_project.parent.mkdir(parents=True)
        legacy_project.write_text(
            json.dumps({"name": "project-a", "mode": "character"}), encoding="utf-8",
        )
        pointer = self.root / "Install" / "kohya_dir.txt"

        with patch.object(paths, "_read_data_setting", return_value=str(selected)), \
                patch.object(paths, "KOHYA_DIR_FILE", str(pointer)):
            self.assertEqual([p["name"] for p in paths.list_projects()], ["project-a"])
            self.assertEqual(paths.load_project("project-a")["mode"], "character")
            self.assertTrue(paths.save_project("project-a", {"mode": "style"}))

        self.assertEqual(json.loads(legacy_project.read_text(encoding="utf-8"))["mode"], "style")

    def test_project_output_falls_back_to_existing_legacy_output(self):
        selected = self.root / "ChosenData"
        selected.mkdir()
        legacy_output = self.data_root / "output" / "project-a"
        legacy_output.mkdir(parents=True)
        (legacy_output / "trained.safetensors").write_bytes(b"model")
        pointer = self.root / "Install" / "kohya_dir.txt"

        with patch.object(paths, "_read_data_setting", return_value=str(selected)), \
                patch.object(paths, "KOHYA_DIR_FILE", str(pointer)):
            self.assertEqual(Path(paths.project_output_dir("project-a")), legacy_output)

if __name__ == "__main__":
    unittest.main()
