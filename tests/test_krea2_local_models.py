"""Krea 2 local path selection; no model weights, native dialogs or GPU required."""
import copy
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gui.modern_host import ModernUIBridge
from kohya_core import krea2_models as local
from kohya_core.fizgig_adapter import models, missing
from kohya_core.project_config import training_params
from kohya_core.fizgig_engine import VERSION


class Core:
    KREA2_MODEL_LINKS = {
        "raw": ("raw.safetensors", "RAW", "https://example.invalid/raw"),
        "turbo": ("turbo.safetensors", "Turbo", "https://example.invalid/turbo"),
        "vae": ("qwen_image_vae.safetensors", "VAE", "https://example.invalid/vae"),
        "te": ("qwen3vl_4b_bf16.safetensors", "BF16", "https://example.invalid/te"),
    }
    KREA2_FZ_MODEL_LINKS = {**KREA2_MODEL_LINKS,
        "te_fp8": ("qwen3vl_4b_fp8_scaled.safetensors", "FP8", "https://example.invalid/fp8")}

    def __init__(self, root):
        self.root = Path(root)
        self.project = {"mode": "krea2_fz", "base_type": "sdxl", "trigger": "keep-me",
                        "params": {"rank": 32, "fizgig_version": VERSION}}
        self.saves = 0

    def load_project(self, name):
        return copy.deepcopy(self.project) if name == "demo" else None

    def save_project(self, name, config):
        self.project = copy.deepcopy(config)
        self.saves += 1
        return True

    def krea2_models_dir(self):
        return str(self.root / "models")

    def krea2_model_files(self):
        return {key: str(p) if p.is_file() else None for key, entry in self.KREA2_MODEL_LINKS.items()
                for p in [self.root / "models" / entry[0]]}

    def krea2_fz_model_files(self, selection=None):
        return local.files(self, selection)

    def data_sub(self, *parts):
        return str(self.root.joinpath(*parts))

    model_url_list = staticmethod(lambda entry: [entry[2]])
    clear_status_cache = staticmethod(lambda: None)
    preset_for = staticmethod(lambda *_: {})
    normalize_crop_ratio = staticmethod(lambda value: value)


class LocalModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.core = Core(self.root)
        self.bridge = ModernUIBridge(self.core)

    def file(self, name="已有 底模.safetensors"):
        p = self.root / name
        p.write_bytes(b"fixture; no model payload")
        return str(p)

    @staticmethod
    def fixture_validate(path, key):
        if not Path(path).is_file():
            raise ValueError("文件不存在")
        return "fixture header check"

    def mocked_checks(self):
        return patch.object(local, "validate", side_effect=self.fixture_validate)

    def test_all_five_v7_rows_expose_local_picker(self):
        result = self.bridge.get_model_downloads("krea2_fz", "demo")
        self.assertTrue(result["ok"])
        self.assertEqual({row["key"] for row in result["items"]}, set(self.core.KREA2_FZ_MODEL_LINKS))
        self.assertTrue(all(row["local_select"] for row in result["items"]))
        self.assertFalse(any(row["local_select"] for row in self.bridge.get_model_downloads("krea2_fz")["items"]))

    def select(self, key, path):
        with self.mocked_checks(), patch("gui.modern_host.validate_krea2_component", side_effect=self.fixture_validate), \
                patch.object(self.bridge, "choose_path", return_value={"ok": True, "path": path}):
            return self.bridge.select_krea2_component("demo", key)

    def test_local_path_is_saved_without_copy_or_rename(self):
        path = self.file()
        original = Path(path).read_bytes()
        result = self.select("raw", path)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.core.project["krea2_models"]["raw"], path)
        self.assertEqual(self.core.project["params"]["rank"], 32)
        self.assertEqual(self.core.project["trigger"], "keep-me")
        self.assertEqual(Path(path).read_bytes(), original)
        self.assertFalse((self.root / "models" / "raw.safetensors").exists())
        with self.mocked_checks():
            row = next(row for row in self.bridge.get_model_downloads("krea2_fz", "demo")["items"] if row["key"] == "raw")
        self.assertTrue(row["present"])
        self.assertTrue(row["manual"])
        self.assertEqual(row["path"], path)

    def test_explicit_bf16_is_not_replaced_by_default_fp8(self):
        folder = self.root / "models"
        folder.mkdir()
        (folder / self.core.KREA2_FZ_MODEL_LINKS["te_fp8"][0]).write_bytes(b"fixture")
        bf16 = self.file("自定义 BF16.safetensors")
        self.assertTrue(self.select("te", bf16)["ok"])
        self.assertTrue(self.bridge.select_krea2_encoder("demo", "te")["ok"])
        params = training_params(self.core, self.core.project, "demo")
        with self.mocked_checks():
            self.assertEqual(models(self.core, "krea2", params)["te"], bf16)
            rows = self.bridge.get_model_downloads("krea2_fz", "demo")["items"]
        self.assertEqual([row["key"] for row in rows if row["required"] and row["key"].startswith("te")], ["te"])
        self.assertTrue(self.bridge.select_krea2_component("demo", "te", "default")["ok"])
        self.assertEqual(self.core.project["krea2_models"]["text_encoder"], "te")
        with self.mocked_checks():
            self.assertIsNone(models(self.core, "krea2", self.core.project)["te"])
        self.assertTrue(self.bridge.select_krea2_encoder("demo", "auto")["ok"])
        with self.mocked_checks():
            self.assertEqual(models(self.core, "krea2", self.core.project)["te"], str(folder / self.core.KREA2_FZ_MODEL_LINKS["te_fp8"][0]))

    def test_file_paths_do_not_switch_the_explicit_encoder_choice(self):
        bf16, fp8 = self.file("BF16.safetensors"), self.file("FP8.safetensors")
        self.assertTrue(self.bridge.select_krea2_encoder("demo", "te")["ok"])
        self.assertTrue(self.select("te_fp8", fp8)["ok"])
        self.assertTrue(self.select("te", bf16)["ok"])
        with self.mocked_checks():
            self.assertEqual(models(self.core, "krea2", self.core.project)["te"], bf16)
        self.assertTrue(self.select("te_fp8", fp8)["ok"])
        with self.mocked_checks():
            self.assertEqual(models(self.core, "krea2", self.core.project)["te"], bf16)
        self.assertTrue(self.bridge.select_krea2_encoder("demo", "te_fp8")["ok"])
        with self.mocked_checks():
            self.assertEqual(models(self.core, "krea2", self.core.project)["te"], fp8)
        self.assertEqual(self.core.project["krea2_models"]["te"], bf16)

    def test_deleted_manual_encoder_does_not_silently_fall_back(self):
        bf16, fp8 = self.file("BF16.safetensors"), self.file("FP8.safetensors")
        self.assertTrue(self.select("te", bf16)["ok"])
        self.assertTrue(self.select("te_fp8", fp8)["ok"])
        self.assertTrue(self.bridge.select_krea2_encoder("demo", "te_fp8")["ok"])
        Path(fp8).unlink()
        with self.mocked_checks():
            self.assertIsNone(models(self.core, "krea2", self.core.project)["te"])
            self.assertIn("缺少文本编码器", missing(self.core, "krea2", self.core.project))
            with self.assertRaises(ValueError):
                local.validate_selected(self.core, local.settings(self.core.project))

    def test_auto_prefers_ready_fp8_and_tracks_active_required_file(self):
        bf16, fp8 = self.file("BF16.safetensors"), self.file("FP8.safetensors")
        self.assertTrue(self.select("te", bf16)["ok"])
        self.assertEqual(self.core.project["krea2_models"]["text_encoder"], "auto")
        with self.mocked_checks():
            first = self.bridge.get_model_downloads("krea2_fz", "demo")
        self.assertEqual(first["encoder"]["active_key"], "te")
        self.assertTrue(self.select("te_fp8", fp8)["ok"])
        with self.mocked_checks():
            result = self.bridge.get_model_downloads("krea2_fz", "demo")
            params = training_params(self.core, self.core.project, "demo")
            self.assertEqual(models(self.core, "krea2", params)["te"], fp8)
        self.assertEqual(result["encoder"]["choice"], "auto")
        self.assertEqual(result["encoder"]["path"], fp8)
        self.assertTrue(result["encoder"]["ready"])
        self.assertEqual([row["key"] for row in result["items"] if row["in_use"]], ["te_fp8"])
        self.assertFalse(next(row for row in result["items"] if row["key"] == "te")["required"])

    def test_explicit_missing_encoder_blocks_even_with_ready_alternative(self):
        self.assertTrue(self.select("te", self.file("BF16.safetensors"))["ok"])
        self.assertTrue(self.bridge.select_krea2_encoder("demo", "te_fp8")["ok"])
        with self.mocked_checks():
            result = self.bridge.get_model_downloads("krea2_fz", "demo")
            self.assertIsNone(models(self.core, "krea2", self.core.project)["te"])
            self.assertIn("缺少文本编码器", missing(self.core, "krea2", self.core.project))
        self.assertFalse(result["encoder"]["ready"])
        active = next(row for row in result["items"] if row["key"] == "te_fp8")
        self.assertTrue(active["required"])
        self.assertTrue(active["selected"])
        self.assertFalse(active["in_use"])

    def test_older_path_only_settings_keep_their_intended_choice(self):
        for key in local.ENCODERS:
            selection = {key: "external.safetensors"}
            self.assertEqual(local.encoder_choice(selection), key)
            self.assertEqual(local.change(selection, "raw", path="raw.safetensors")["text_encoder"], key)
            self.assertEqual(local.encoder_key({"te": "bf16", "te_fp8": "fp8"}, selection), key)
        self.assertEqual(local.encoder_key({"te": "bf16", "te_fp8": "fp8"}, {"te": "bf16", "text_encoder": "auto"}), "te_fp8")

    def test_encoder_endpoint_guards_version_busy_agent_and_save_failure(self):
        self.assertFalse(self.bridge.select_krea2_encoder("missing", "te")["ok"])
        self.assertFalse(self.bridge.select_krea2_encoder("demo", "unknown")["ok"])
        self.core.project["params"]["fizgig_version"] = "v6.5.0"
        self.assertFalse(self.bridge.select_krea2_encoder("demo", "te_fp8")["ok"])
        self.assertTrue(self.bridge.select_krea2_encoder("demo", "te")["ok"])
        count = self.core.saves
        for status in ("running", "awaiting_review"):
            self.bridge._task = {"status": status}
            self.assertFalse(self.bridge.select_krea2_encoder("demo", "auto")["ok"])
        self.bridge._task = None
        with patch.object(self.bridge, "_agent_guard", return_value={"ok": False, "error": "guard"}):
            self.assertFalse(self.bridge.select_krea2_encoder("demo", "auto")["ok"])
        with patch.object(self.core, "save_project", return_value=False):
            self.assertFalse(self.bridge.select_krea2_encoder("demo", "auto")["ok"])
        self.assertEqual(self.core.saves, count)
        self.assertEqual(self.core.project["krea2_models"]["text_encoder"], "te")
        self.core.project["mode"] = "h3_fz"
        self.assertFalse(self.bridge.select_krea2_encoder("demo", "te")["ok"])

    def test_choice_survives_disk_save_and_reopen(self):
        from kohya_core import paths
        target = str(self.root / "demo.json")
        with patch.object(paths, "_project_path", return_value=target):
            self.assertTrue(paths.save_project("demo", self.core.project))
            self.core.load_project = paths.load_project
            self.core.save_project = paths.save_project
            self.assertTrue(self.bridge.select_krea2_encoder("demo", "te")["ok"])
            reopened = ModernUIBridge(self.core)
            self.assertEqual(reopened.get_model_downloads("krea2_fz", "demo")["encoder"]["choice"], "te")
            self.assertEqual(training_params(self.core, paths.load_project("demo"), "demo")["krea2_models"]["text_encoder"], "te")

    def test_workspace_badges_guide_and_components_share_the_encoder_resolution(self):
        core = self.core
        core.MODE_KEYS = ("krea2_fz",)
        core.MODE_LABELS = {"krea2_fz": "Krea2 图像LoRA"}
        core.GUIDE_STEPS = {"krea2_fz": [
            {"id": "env", "label": "①", "check": "env", "act": "cmd_env"},
            {"id": "models", "label": "③", "check": "krea2_models", "act": "cmd_dl_krea2_models"}]}
        core.system_status = lambda: {"python": True, "git": True, "fizgig_ok": True}
        core.fizgig_engine_update_status = lambda: {"versions": [VERSION]}
        core.param_supports = lambda *_: False
        core.detect_gpu_vendor = lambda: "nvidia"
        core.project["krea2_models"] = {key: self.file(key + ".safetensors") for key in ("raw", "vae", "te")}
        core.project["krea2_models"]["text_encoder"] = "te"
        runtime = {"python": sys.executable, "source": str(self.root)}
        with self.mocked_checks(), patch("gui.modern_host.fizgig_runtime", return_value=runtime), \
                patch("gui.modern_host.fizgig_source_version", return_value=VERSION):
            result = self.bridge.get_mode_workspace("krea2_fz", "demo")
            self.assertEqual(result["missing_models"], [])
            self.assertEqual(result["krea2_components"]["encoder"]["active_key"], "te")
            self.assertEqual(len([row for row in result["krea2_components"]["items"] if row["required"]]), 3)
            guide = next(step for step in result["guide_steps"] if step["id"] == "models")
            self.assertTrue(guide["done"])
            self.assertTrue(guide["persistent"])
            self.assertIn("模型与配套组件", guide["label"])
            self.assertTrue(self.bridge.select_krea2_encoder("demo", "te_fp8")["ok"])
            missing_result = self.bridge.get_mode_workspace("krea2_fz", "demo")
        self.assertFalse(missing_result["krea2_components"]["encoder"]["ready"])
        self.assertEqual(len(missing_result["missing_models"]), 1)
        self.assertFalse(next(step for step in missing_result["guide_steps"] if step["id"] == "models")["done"])

    def test_cancel_invalid_file_and_busy_task_do_not_change_project(self):
        with patch.object(self.bridge, "choose_path", return_value={"ok": True, "cancelled": True}):
            self.assertTrue(self.bridge.select_krea2_component("demo", "raw")["cancelled"])
        bad = self.file("wrong.png")
        with patch.object(self.bridge, "choose_path", return_value={"ok": True, "path": bad}):
            self.assertFalse(self.bridge.select_krea2_component("demo", "raw")["ok"])
        self.bridge._task = {"status": "running"}
        self.assertFalse(self.bridge.select_krea2_component("demo", "raw", "default")["ok"])
        self.assertEqual(self.core.saves, 0)

    def test_picker_reloads_project_and_guards_new_task(self):
        path = self.file()
        def choose(*_args):
            self.core.project["trigger"] = "changed while picking"
            self.core.project["params"]["rank"] = 64
            return {"ok": True, "path": path}
        with self.mocked_checks(), patch("gui.modern_host.validate_krea2_component", side_effect=self.fixture_validate), \
                patch.object(self.bridge, "choose_path", side_effect=choose):
            self.assertTrue(self.bridge.select_krea2_component("demo", "raw")["ok"])
        self.assertEqual(self.core.project["params"]["rank"], 64)
        self.assertEqual(self.core.project["trigger"], "changed while picking")
        def start_task(*_args):
            self.bridge._task = {"status": "running"}
            return {"ok": True, "path": path}
        with self.mocked_checks(), patch("gui.modern_host.validate_krea2_component", side_effect=self.fixture_validate), \
                patch.object(self.bridge, "choose_path", side_effect=start_task):
            self.assertFalse(self.bridge.select_krea2_component("demo", "vae")["ok"])
        self.assertNotIn("vae", self.core.project["krea2_models"])

    def test_only_turbo_can_be_disabled_and_reset_does_not_delete_files(self):
        path = self.file("Turbo.safetensors")
        self.assertTrue(self.select("turbo", path)["ok"])
        self.assertTrue(self.bridge.select_krea2_component("demo", "turbo", "disable")["ok"])
        self.assertEqual(self.core.project["krea2_models"]["turbo"], "")
        with self.mocked_checks():
            self.assertIsNone(models(self.core, "krea2", self.core.project)["preview_checkpoint"])
        for key in ("raw", "vae", "te", "te_fp8"):
            self.assertFalse(self.bridge.select_krea2_component("demo", key, "disable")["ok"])
        self.assertTrue(self.bridge.select_krea2_component("demo", "turbo", "default")["ok"])
        self.assertNotIn("turbo", self.core.project["krea2_models"])
        self.assertTrue(Path(path).is_file())

    def test_legacy_project_has_bf16_only_and_uses_local_paths(self):
        self.core.project["params"]["fizgig_version"] = "v6.5.0"
        bf16 = self.file("legacy BF16.safetensors")
        self.assertTrue(self.select("te", bf16)["ok"])
        with self.mocked_checks():
            result = self.bridge.get_model_downloads("krea2_fz", "demo")
            self.assertEqual(local.files(self.core, local.settings(self.core.project), allow_fp8=False)["te"], bf16)
        self.assertNotIn("te_fp8", {row["key"] for row in result["items"]})
        self.assertTrue(all(row["local_select"] for row in result["items"]))
        self.assertFalse(self.bridge.select_krea2_component("demo", "te_fp8", "default")["ok"])

    def test_wrong_project_or_unknown_key_is_rejected(self):
        self.assertFalse(self.bridge.select_krea2_component("missing", "raw")["ok"])
        self.assertFalse(self.bridge.select_krea2_component("demo", "dit")["ok"])
        self.core.project["mode"] = "h3_fz"
        self.assertFalse(self.bridge.select_krea2_component("demo", "raw")["ok"])

    def test_raw_vae_turbo_and_encoder_reach_adapter_parameters(self):
        selected = {key: self.file(key + " local.safetensors") for key in ("raw", "vae", "turbo", "te_fp8")}
        self.core.project["krea2_models"] = {**selected, "text_encoder": "te_fp8"}
        params = training_params(self.core, self.core.project, "demo")
        with self.mocked_checks():
            resolved = models(self.core, "krea2", params)
            self.assertFalse(missing(self.core, "krea2", params))
        self.assertEqual(resolved["dit"], selected["raw"])
        self.assertEqual(resolved["vae"], selected["vae"])
        self.assertEqual(resolved["te"], selected["te_fp8"])
        self.assertEqual(resolved["preview_checkpoint"], selected["turbo"])

    def test_project_paths_survive_disk_save_and_reopen(self):
        from kohya_core import paths
        path = self.file("persistent RAW.safetensors")
        target = str(self.root / "demo.json")
        with patch.object(paths, "_project_path", return_value=target):
            self.assertTrue(paths.save_project("demo", self.core.project))
            self.core.load_project = paths.load_project
            self.core.save_project = paths.save_project
            self.assertTrue(self.select("raw", path)["ok"])
            reopened = ModernUIBridge(self.core)
            with self.mocked_checks():
                row = next(row for row in reopened.get_model_downloads("krea2_fz", "demo")["items"] if row["key"] == "raw")
            self.assertEqual(row["path"], path)
            self.assertTrue(row["manual"])

    def test_queue_normalization_keeps_the_component_paths(self):
        from kohya_core import paths, queue
        selected = {"raw": self.file(), "text_encoder": "te"}
        self.core.project["krea2_models"] = selected
        with patch.object(paths, "load_project", return_value=self.core.project), \
                patch.dict(sys.modules, {"Kohya一键工具": self.core}):
            result = queue.params_from_project("demo")
        self.assertEqual(result["krea2_models"], selected)

    def test_v7_cache_train_and_preview_commands_use_selected_paths(self):
        from kohya_core import fizgig_adapter as adapter
        selected = {key: self.file(key + " external.safetensors") for key in ("raw", "vae", "te_fp8", "turbo")}
        self.core.project["krea2_models"] = {**selected, "text_encoder": "te_fp8"}
        params = training_params(self.core, self.core.project, "demo")
        data = self.root / "dataset"
        data.mkdir()
        (data / "sample.png").write_bytes(b"mock dataset")
        calls, logs = [], []
        core = self.core
        core.MIN_IMAGES = {"krea2_fz": 1}
        core.FIZGIG_IMAGE_EXTS = {".png"}
        core._safetensors_complete = lambda _: True
        core._safetensors_is_prequantized = lambda _: False
        core.dataset_train_dir = lambda *_: str(data)
        core._fizgig_qwen_image_subsets = lambda *_: ([(str(data), 1, 1)], [])
        core._sanitize_dirname = lambda value: value or ""
        core.output_name_for = lambda *_: "krea2-test"
        core.check_stop = lambda: None
        core._write_fizgig_subset_config = lambda _a, _b, path, _r: Path(path).write_text("mock config", encoding="utf-8")
        core.run_stream = lambda cmd, **_kw: calls.append(cmd) or 0
        core._save_every_note = lambda *_: 1
        core._attach_train_monitor = lambda logf, *_a, **_kw: logf
        core._sample_preview_enabled = lambda *_: True
        core._fizgig_sample_epochs = lambda *_: 1
        core._sample_seed = lambda *_: 42
        core._record_effective = lambda **_kw: None
        core._fizgig_warmup_log_filter = lambda logf: logf
        record = {"version": "v7.3.1", "source": str(self.root / "source"), "python": sys.executable}
        with self.mocked_checks(), patch.object(adapter, "source_version", return_value=VERSION), \
                patch.object(adapter, "_env", return_value={}), patch.object(adapter, "_helper_configs", return_value=None):
            adapter.train_lora(core, record, logs.append, "krea2_fz", params, 8, None, None)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][calls[0].index("--model") + 1], selected["vae"])
        self.assertEqual(calls[1][calls[1].index("--model") + 1], selected["te_fp8"])
        for flag, key in (("--dit", "raw"), ("--vae", "vae"), ("--text_encoder", "te_fp8"), ("--preview_checkpoint", "turbo")):
            self.assertEqual(calls[2][calls[2].index(flag) + 1], selected[key])
        self.assertTrue(any(selected["raw"] in line for line in logs))

    def test_downloading_alternate_fp8_does_not_override_bf16_choice(self):
        bf16 = self.file("explicit bf16.safetensors")
        self.core.project["krea2_models"] = {"te": bf16, "text_encoder": "te"}
        def factory(_url, dest, **kwargs):
            self.download_dest, self.download_done = dest, kwargs["done_cb"]
            return SimpleNamespace(start=lambda: None)
        with self.mocked_checks(), patch("gui.modern_host.ModelDownloader", side_effect=factory):
            self.assertTrue(self.bridge.start_model_download("krea2_fz", "te_fp8", "demo")["ok"])
        Path(self.download_dest).write_bytes(b"fixture")
        with patch("gui.modern_host.validate_krea2_component", side_effect=self.fixture_validate), self.mocked_checks():
            self.download_done(True, self.download_dest)
            result = self.bridge.get_model_downloads("krea2_fz", "demo")
            self.assertEqual(models(self.core, "krea2", self.core.project)["te"], bf16)
        self.assertEqual(result["encoder"]["choice"], "te")
        self.assertTrue(next(row for row in result["items"] if row["key"] == "te_fp8")["present"])

    def test_download_repairs_stale_override_without_switching_encoder(self):
        old = str(self.root / "missing raw.safetensors")
        self.core.project["krea2_models"] = {"raw": old, "text_encoder": "te"}
        def factory(_url, dest, **kwargs):
            self.download_dest, self.download_done = dest, kwargs["done_cb"]
            return SimpleNamespace(start=lambda: None)
        with self.mocked_checks(), patch("gui.modern_host.ModelDownloader", side_effect=factory):
            result = self.bridge.start_model_download("krea2_fz", "raw", "demo")
        self.assertTrue(result["ok"], result)
        self.core.project["trigger"] = "changed during download"
        Path(self.download_dest).write_bytes(b"download fixture")
        with patch("gui.modern_host.validate_krea2_component", side_effect=self.fixture_validate):
            self.download_done(True, self.download_dest)
        self.assertEqual(self.bridge._task["status"], "completed")
        self.assertEqual(self.core.project["krea2_models"]["raw"], self.download_dest)
        self.assertEqual(self.core.project["krea2_models"]["text_encoder"], "te")
        self.assertEqual(self.core.project["trigger"], "changed during download")

    def test_download_failure_keeps_selection_and_reports_failed(self):
        old = str(self.root / "missing raw.safetensors")
        self.core.project["krea2_models"] = {"raw": old}
        def factory(_url, _dest, **kwargs):
            self.download_done = kwargs["done_cb"]
            return SimpleNamespace(start=lambda: None)
        with self.mocked_checks(), patch("gui.modern_host.ModelDownloader", side_effect=factory):
            self.assertTrue(self.bridge.start_model_download("krea2_fz", "raw", "demo")["ok"])
        with patch("gui.modern_host.validate_krea2_component", side_effect=ValueError("bad header")):
            self.download_done(True, self.file("downloaded.safetensors"))
        self.assertEqual(self.bridge._task["status"], "failed")
        self.assertIn("bad header", self.bridge._task["message"])
        self.assertEqual(self.core.project["krea2_models"]["raw"], old)

    def test_valid_local_model_does_not_trigger_a_duplicate_download(self):
        path = self.file()
        self.core.project["krea2_models"] = {"raw": path}
        with self.mocked_checks(), patch("gui.modern_host.ModelDownloader") as downloader:
            result = self.bridge.start_model_download("krea2_fz", "raw", "demo")
            self.assertFalse(result["ok"])
            downloader.assert_not_called()



class HeaderTests(unittest.TestCase):
    def test_rejects_truncated_weights_without_loading_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "broken.safetensors"
            h = json.dumps({"weight": {"dtype": "BF16", "shape": [10], "data_offsets": [0, 20]}}).encode()
            p.write_bytes(struct.pack("<Q", len(h)) + h + b"x")
            with self.assertRaises(ValueError):
                local.validate(str(p), "raw")

    def test_bf16_and_fp8_encoder_variants_cannot_be_mixed(self):
        header = {"model.language_model.embed_tokens.weight": {"dtype": "BF16", "shape": [151936, 2560]},
                  "model.visual.patch_embed.proj.weight": {"dtype": "BF16", "shape": [1024, 3, 2, 16, 16]}}
        for i in range(36):
            header[f"model.language_model.layers.{i}.input_layernorm.weight"] = {"dtype": "BF16", "shape": [2560]}
        self.assertIn("BF16", local._validate_header(header, {}, "te"))
        with self.assertRaises(ValueError):
            local._validate_header(header, {}, "te_fp8")
        key = "model.language_model.layers.0.mlp.down_proj"
        header[key + ".weight"] = {"dtype": "F8_E4M3", "shape": [2560, 9728]}
        header[key + ".weight_scale"] = {"dtype": "F32", "shape": []}
        self.assertIn("FP8", local._validate_header(header, {key: {"format": "float8_e4m3fn"}}, "te_fp8"))
        with self.assertRaises(ValueError):
            local._validate_header(header, {}, "te")

    def test_wrong_model_family_and_prequantized_raw_are_rejected(self):
        header = {"first.weight": {"dtype": "BF16", "shape": [6144, 64]},
                  "last.linear.weight": {"dtype": "F32", "shape": [64, 6144]}}
        for i in range(28):
            header[f"blocks.{i}.attn.wq.weight"] = {"dtype": "BF16", "shape": [6144, 6144]}
        self.assertIn("RAW", local._validate_header(header, {}, "raw"))
        with self.assertRaises(ValueError):
            local._validate_header(header, {}, "vae")
        header["blocks.0.attn.wq.weight"]["dtype"] = "F8_E4M3"
        with self.assertRaises(ValueError):
            local._validate_header(header, {}, "raw")


if __name__ == "__main__":
    unittest.main()
