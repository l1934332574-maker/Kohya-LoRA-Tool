import sys
import tempfile
import unittest
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
        self.assertEqual(settings["background_opacity"], 43)
        self.assertFalse(settings["background_available"])
        self.assertEqual(settings["background_history"], [{"path": str(missing), "available": False}])
        self.assertEqual(settings["component_opacity"], 100)
        self.assertFalse(settings["idle_fade_enabled"])

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
