import sys
import tempfile
import unittest
import base64
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui.modern_host import ModernUIBridge


class AppearanceSettingsCore:
    def __init__(self):
        self.settings = {}

    def _load_app_settings(self):
        return dict(self.settings)

    def _save_app_settings(self, settings):
        self.settings = dict(settings)
        return True


class ModernAppearanceTests(unittest.TestCase):
    def setUp(self):
        self.core = AppearanceSettingsCore()
        self.bridge = ModernUIBridge(self.core)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_theme_and_background_preferences_are_saved_in_namespaced_settings(self):
        image = Path(self.temp.name) / "wallpaper.png"
        image.write_bytes(b"png-fixture")
        self.core.settings["download_official_first"] = True

        result = self.bridge.set_appearance_settings("light", str(image), 24)

        self.assertTrue(result["ok"])
        self.assertEqual(result["settings"]["theme"], "light")
        self.assertEqual(result["settings"]["background_path"], str(image))
        self.assertEqual(result["settings"]["background_opacity"], 24)
        self.assertTrue(self.core.settings["download_official_first"])
        self.assertEqual(self.bridge.get_appearance_settings()["settings"], result["settings"])

    def test_background_image_is_served_as_a_data_url_without_copying_user_file(self):
        image = Path(self.temp.name) / "wallpaper.webp"
        image.write_bytes(b"webp-fixture")
        self.bridge.set_appearance_settings("dark", str(image), 18)

        result = self.bridge.get_appearance_background()

        self.assertTrue(result["ok"])
        self.assertTrue(result["data_url"].startswith("data:image/webp;base64,"))
        self.assertEqual(image.read_bytes(), b"webp-fixture")

    def test_recent_image_preview_returns_a_small_thumbnail_and_rejects_missing_paths(self):
        from PIL import Image

        image = Path(self.temp.name) / "wallpaper.png"
        Image.new("RGB", (640, 480), (64, 128, 192)).save(image)

        result = self.bridge.get_appearance_image_preview(str(image), thumbnail=True)
        missing = self.bridge.get_appearance_image_preview(str(Path(self.temp.name) / "gone.png"), thumbnail=True)

        self.assertTrue(result["ok"])
        self.assertTrue(result["data_url"].startswith("data:image/webp;base64,"))
        preview_bytes = base64.b64decode(result["data_url"].split(",", 1)[1])
        with Image.open(BytesIO(preview_bytes)) as thumbnail:
            self.assertEqual(thumbnail.size, (144, 144))
        self.assertFalse(missing["ok"])

    def test_background_opacity_accepts_full_zero_to_one_hundred_percent_range(self):
        image = Path(self.temp.name) / "wallpaper.png"
        image.write_bytes(b"png-fixture")

        full = self.bridge.set_appearance_settings("dark", str(image), 100)
        self.assertTrue(full["ok"])
        self.assertEqual(full["settings"]["background_opacity"], 100)

        above_range = self.bridge.set_appearance_settings("dark", str(image), 130)
        self.assertTrue(above_range["ok"])
        self.assertEqual(above_range["settings"]["background_opacity"], 100)

        below_range = self.bridge.set_appearance_settings("dark", str(image), -5)
        self.assertTrue(below_range["ok"])
        self.assertEqual(below_range["settings"]["background_opacity"], 0)

    def test_ui_opacity_and_idle_fade_settings_are_saved_and_clamped(self):
        low = self.bridge.set_appearance_settings("dark", "", 18, 0, True)
        self.assertTrue(low["ok"])
        self.assertEqual(low["settings"]["component_opacity"], 0)
        self.assertTrue(low["settings"]["idle_fade_enabled"])

        high = self.bridge.set_appearance_settings("dark", "", 18, 140, False)
        self.assertTrue(high["ok"])
        self.assertEqual(high["settings"]["component_opacity"], 100)
        self.assertFalse(high["settings"]["idle_fade_enabled"])

    def test_background_history_keeps_local_paths_marks_missing_and_is_limited(self):
        existing = Path(self.temp.name) / "wallpaper.png"
        existing.write_bytes(b"png-fixture")
        missing = Path(self.temp.name) / "removed-drive" / "old-wallpaper.png"
        history = [str(Path(self.temp.name) / f"image-{index}.png") for index in range(10)]

        saved = self.bridge.set_appearance_settings(
            "light", str(existing), 36, 82, True, [str(missing), *history]
        )

        self.assertTrue(saved["ok"])
        entries = saved["settings"]["background_history"]
        self.assertEqual(len(entries), 8)
        self.assertEqual(entries[0], {"path": str(existing), "available": True})
        self.assertEqual(entries[1], {"path": str(missing), "available": False})
        self.assertEqual(self.core.settings["modern_ui_background_history"][0], str(existing))
        self.assertEqual(existing.read_bytes(), b"png-fixture")

        removed = self.bridge.set_appearance_settings("light", "", 36, 82, True, [])
        self.assertTrue(removed["ok"])
        self.assertEqual(removed["settings"]["background_history"], [])

    def test_legacy_appearance_settings_receive_new_defaults_and_keep_missing_current_path(self):
        missing = Path(self.temp.name) / "offline.png"
        self.core.settings.update({
            "modern_ui_theme": "light",
            "modern_ui_background": str(missing),
            "modern_ui_background_opacity": 43,
        })

        settings = self.bridge.get_appearance_settings()["settings"]

        self.assertEqual(settings["theme"], "light")
        self.assertEqual(settings["background_source_path"], str(missing))
        self.assertEqual(settings["background_opacity"], 43)
        self.assertFalse(settings["background_available"])
        self.assertEqual(settings["background_history"], [{"path": str(missing), "available": False}])
        self.assertEqual(settings["component_opacity"], 100)
        self.assertFalse(settings["idle_fade_enabled"])

    def test_cropped_background_is_saved_as_an_independent_copy_and_survives_reload(self):
        from PIL import Image

        source = Path(self.temp.name) / "original.png"
        Image.new("RGB", (80, 60), (120, 20, 40)).save(source)
        original_bytes = source.read_bytes()
        crop = BytesIO()
        Image.new("RGB", (24, 18), (20, 180, 90)).save(crop, format="PNG")
        crop_data_url = "data:image/png;base64," + base64.b64encode(crop.getvalue()).decode("ascii")
        assets = Path(self.temp.name) / "appearance-assets"
        self.bridge._appearance_assets_dir = lambda: str(assets)

        saved = self.bridge.set_appearance_settings(
            "dark", str(source), 18, 100, False, [str(source)], str(source), crop_data_url
        )

        self.assertTrue(saved["ok"], saved.get("error"))
        cropped_path = Path(saved["settings"]["background_path"])
        self.assertNotEqual(cropped_path, source)
        self.assertTrue(cropped_path.is_file())
        self.assertEqual(cropped_path.read_bytes(), crop.getvalue())
        self.assertEqual(source.read_bytes(), original_bytes)
        self.assertEqual(saved["settings"]["background_source_path"], str(source))
        self.assertEqual(saved["settings"]["background_history"][0], {"path": str(source), "available": True})
        self.assertEqual(self.bridge.get_appearance_settings()["settings"]["background_path"], str(cropped_path))

    def test_replacing_and_failing_to_save_crops_only_removes_owned_copies(self):
        from PIL import Image

        source = Path(self.temp.name) / "original.png"
        legacy_image = Path(self.temp.name) / "legacy-user-image.png"
        Image.new("RGB", (80, 60), (120, 20, 40)).save(source)
        Image.new("RGB", (80, 60), (40, 20, 120)).save(legacy_image)
        source_bytes = source.read_bytes()
        legacy_bytes = legacy_image.read_bytes()
        assets = Path(self.temp.name) / "appearance-assets"
        self.bridge._appearance_assets_dir = lambda: str(assets)

        def crop_data(color):
            crop = BytesIO()
            Image.new("RGB", (24, 18), color).save(crop, format="PNG")
            return "data:image/png;base64," + base64.b64encode(crop.getvalue()).decode("ascii")

        self.core.settings["modern_ui_background"] = str(legacy_image)
        first = self.bridge.set_appearance_settings(
            "dark", str(source), 18, 100, False, [str(source)], str(source), crop_data((20, 180, 90))
        )
        self.assertTrue(first["ok"], first.get("error"))
        first_copy = Path(first["settings"]["background_path"])
        self.assertTrue(legacy_image.is_file())

        second = self.bridge.set_appearance_settings(
            "dark", str(source), 18, 100, False, [str(source)], str(source), crop_data((220, 80, 40))
        )
        self.assertTrue(second["ok"], second.get("error"))
        second_copy = Path(second["settings"]["background_path"])
        self.assertFalse(first_copy.exists())
        self.assertTrue(second_copy.is_file())

        self.core._save_app_settings = lambda _settings: False
        failed = self.bridge.set_appearance_settings(
            "dark", str(source), 18, 100, False, [str(source)], str(source), crop_data((10, 100, 200))
        )
        self.assertFalse(failed["ok"])
        self.assertTrue(second_copy.exists())
        self.assertEqual(list(assets.iterdir()), [second_copy])
        self.assertEqual(source.read_bytes(), source_bytes)
        self.assertEqual(legacy_image.read_bytes(), legacy_bytes)

    def test_invalid_theme_and_unreadable_or_oversized_image_are_rejected(self):
        image = Path(self.temp.name) / "wallpaper.gif"
        image.write_bytes(b"image")
        oversized = Path(self.temp.name) / "oversized.png"
        oversized.write_bytes(b"x" * (8 * 1024 * 1024 + 1))

        self.assertFalse(self.bridge.set_appearance_settings("neon", "", 18)["ok"])
        self.assertFalse(self.bridge.set_appearance_settings("dark", str(image), 18)["ok"])
        self.assertFalse(self.bridge.set_appearance_settings("dark", str(image) + ".png", 18)["ok"])
        self.assertFalse(self.bridge.set_appearance_settings("dark", str(oversized), 18)["ok"])


if __name__ == "__main__":
    unittest.main()
