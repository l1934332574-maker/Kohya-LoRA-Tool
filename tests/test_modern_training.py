import json
import mimetypes
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kohya_core.configs import PROJECT_TEMPLATES
from gui.modern_host import ModernUIBridge, _ensure_web_asset_mimetypes


class FakeStopRequested(Exception):
    pass


class FakeTrainMonitor:
    def __init__(self):
        self.data = {"step": 0, "total": 0, "speed": 0, "loss": None, "phase_label": None}

    def start(self, total=0):
        self.data.update(step=0, total=total)

    def set_total(self, total):
        self.data["total"] = total

    def on_line(self, _line):
        return True

    def snapshot(self):
        return dict(self.data)

    def finish(self):
        pass


class FakeCore:
    MODE_KEYS = ("style", "character", "concept", "krea2", "krea2_at", "krea2_fz", "flux2", "flux2_fz", "video", "qwen_image", "zimage")
    MODE_LABELS = {"qwen_image": "Qwen-Image", "zimage": "Z-Image", "character": "人物", "style": "画风", "concept": "概念"}
    MIN_IMAGES = {"qwen_image": 15, "zimage": 15, "character": 15, "style": 20, "concept": 15, "video": 3}
    ARCH_INFO = {"anima": {"recommend_vram": 12, "script": "anima_train_network.py"},
                 "sdxl": {"recommend_vram": 16, "script": "sdxl_train_network.py"}}
    BASE_TYPE_LABELS = {"sdxl": "SDXL", "anima": "Anima"}
    BASE_TYPE_KEYS = ("sdxl", "anima")
    StopRequested = FakeStopRequested
    TrainMonitor = FakeTrainMonitor

    def __init__(self, root):
        self.root = Path(root)
        self.raw = self.root / "raw"
        self.raw.mkdir()
        for index in range(15):
            (self.raw / f"sample-{index:02d}.png").write_bytes(b"test fixture")
        self.project = {
            "mode": "qwen_image", "base_type": "sdxl", "raw_dir": str(self.raw),
            "at_sub_mode": "character", "trigger": "test_subject", "params": {},
        }
        self.preprocess_calls = []
        self.training_calls = []
        self.kohya_calls = []
        self.engine_training_calls = []
        self.resume_state = None
        self.detected_base_type = "anima"

    def load_project(self, _name):
        return dict(self.project)

    def preset_for(self, _mode, _base_type):
        return {"rank": 16, "alpha": 16, "unet_lr": "1e-4", "resolution": 1024, "video_steps": 2000}

    @staticmethod
    def normalize_crop_ratio(value):
        return value

    @staticmethod
    def count_images(_directory):
        return 15

    @staticmethod
    def ai_toolkit_engine_status():
        return True, "ready", "at-python"

    @staticmethod
    def at_image_info(_mode):
        return {"arch": "qwen_image", "label": "Qwen-Image-2512", "model_id": "Qwen/Qwen-Image-2512", "size": "40GB", "min_vram": 16}

    @staticmethod
    def at_image_custom_get(_mode):
        return {}

    @staticmethod
    def at_image_model_ready(_mode):
        return True

    @staticmethod
    def detect_vram_gb():
        return 24

    @staticmethod
    def detect_gpu_vendor():
        return "nvidia"

    @staticmethod
    def detect_nvidia_gpu():
        return True

    def data_sub(self, *parts):
        path = self.root.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    @staticmethod
    def at_image_local_dir(_mode):
        return "models/qwen"

    @staticmethod
    def output_name_for(_mode, _style):
        return "qwen_image_lora"

    def find_latest_state(self, _directory, _name):
        return self.resume_state

    @staticmethod
    def preprocess_mode(_mode, _submode):
        return "character"

    @staticmethod
    def is_concept_mode(_mode, _submode):
        return False

    @staticmethod
    def style_target_code(_style):
        return "anime"

    def preprocess(self, logf, **kwargs):
        self.preprocess_calls.append(kwargs)
        with open(kwargs["report"], "w", encoding="utf-8") as handle:
            json.dump({"ok": 15, "skipped_existing": 0}, handle)
        logf("[预处理] test finished")

    def dataset_train_dir(self, _mode, _project):
        return str(self.root / "train")

    def reset_stop(self):
        pass

    def train_at_image(self, logf, *, mode, params, vram_gb, resume_from, progress):
        self.training_calls.append((mode, params, vram_gb, resume_from))
        progress.start(2000)
        progress.set_total(2000)
        logf("[Qwen-Image] mock trainer called")

    def export_project_named_lora(self, *_args, **_kwargs):
        pass

    def system_status(self):
        kdir = self.root / "kohya"
        scripts = kdir / "sd-scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "anima_train_network.py").write_text("# fixture", encoding="utf-8")
        (scripts / "sdxl_train_network.py").write_text("# fixture", encoding="utf-8")
        return {"kohya_ok": True, "kohya_dir": str(kdir)}

    def detect_base_type(self, _path):
        return self.detected_base_type

    @staticmethod
    def anima_component_status():
        return {"qwen3": {"path": "models/qwen3"}, "vae": {"path": "models/vae.safetensors"}}

    @staticmethod
    def get_kohya_dir():
        return "kohya"

    @staticmethod
    def venv_python(_kdir):
        return "kohya/venv/Scripts/python.exe"

    @staticmethod
    def amd_env_status(_vpy):
        return True, "rocm", "ready"

    def train(self, logf, *, base_model, mode, params, vram_gb, resume_from, progress):
        self.kohya_calls.append((base_model, mode, params, vram_gb, resume_from))
        progress.start(100)
        progress.set_total(100)
        logf("[Anima] mock kohya trainer called")

    @staticmethod
    def preset_for(mode, base_type):
        if base_type == "anima":
            return {"rank": 12, "alpha": 6, "unet_lr": "3e-4", "resolution": 1024,
                    "repeats": 5, "max_epochs": 8}
        return {"rank": 16, "alpha": 16, "unet_lr": "1e-4", "resolution": 1024, "video_steps": 2000}

    def get_mode_workspace(self, mode, _project_name=""):
        return {"ok": True, "mode": mode, "label": mode, "engine_ready": True,
                "missing_models": [], "asset_dir": "models/%s" % mode, "gpu_vendor": "nvidia"}

    @staticmethod
    def param_supports(_key, _mode):
        return False

    @staticmethod
    def scan_video_dataset(_directory):
        return (["one.mp4", "two.mp4", "three.mp4"], 30.0, 0)

    def __getattr__(self, name):
        dispatch = {
            "train_krea2", "train_flux2", "train_video", "train_krea2_at",
            "train_krea2_fizgig", "train_flux2_fizgig",
        }
        if name not in dispatch:
            raise AttributeError(name)

        def train_engine(logf, *, mode, params, vram_gb, resume_from, progress):
            self.engine_training_calls.append((name, mode, dict(params), vram_gb, resume_from))
            progress.start(100)
            progress.set_total(100)
            logf("[%s] mock trainer called" % mode)
        return train_engine


class AvifCountingCore(FakeCore):
    @staticmethod
    def count_images(_directory):
        # Model the legacy helper's image filter, which predates AVIF support.
        return 0


class ProjectCreationCore:
    PRESET_VERSION = 3
    MODE_LABELS = {"style": "画风", "character": "人物", "concept": "概念"}
    BASE_TYPE_LABELS = {"sdxl": "SDXL", "sd15": "SD1.5", "flux": "FLUX.1", "anima": "Anima"}
    MODE_KEYS = ("style", "character", "concept")
    PROJECT_TEMPLATES = PROJECT_TEMPLATES

    def __init__(self, imported_config=None):
        self.projects = {}
        self.imported_config = imported_config

    def list_projects(self):
        return [{"name": name, **data} for name, data in self.projects.items()]

    @staticmethod
    def default_project_name():
        return "新项目"

    def save_project(self, name, data):
        self.projects[name] = dict(data)
        return True

    def parse_config_json(self, _config_json):
        return dict(self.imported_config), {"applied": 1, "ignored": 0}


class ModernTrainingTests(unittest.TestCase):
    def test_file_picker_starts_at_field_path_and_remembers_each_location(self):
        class PickerCore:
            def __init__(self):
                self.settings = {}

            def _load_app_settings(self):
                return dict(self.settings)

            def _save_app_settings(self, settings):
                self.settings = dict(settings)
                return True

        class PickerWindow:
            def __init__(self):
                self.calls = []
                self.selection = None

            def create_file_dialog(self, dialog_type, **kwargs):
                self.calls.append((dialog_type, kwargs))
                return self.selection

        with tempfile.TemporaryDirectory() as temp:
            model_dir = Path(temp) / "models"
            image_dir = Path(temp) / "images"
            next_image_dir = Path(temp) / "next-images"
            for directory in (model_dir, image_dir, next_image_dir):
                directory.mkdir()
            model_file = model_dir / "model.safetensors"
            model_file.write_bytes(b"model")
            core = PickerCore()
            window = PickerWindow()
            bridge = ModernUIBridge(core)
            bridge._window = window

            window.selection = (str(model_file),)
            self.assertTrue(bridge.choose_path("model", str(model_file), "base_model")["ok"])
            self.assertEqual(window.calls[-1][1]["directory"], str(model_dir))

            window.selection = (str(next_image_dir),)
            self.assertTrue(bridge.choose_path("folder", str(image_dir), "raw_dir")["ok"])
            self.assertEqual(window.calls[-1][1]["directory"], str(image_dir))

            reopened = ModernUIBridge(core)
            reopened._window = window
            window.selection = None
            self.assertTrue(reopened.choose_path("folder", "", "raw_dir")["cancelled"])
            self.assertEqual(window.calls[-1][1]["directory"], str(next_image_dir))
            self.assertTrue(reopened.choose_path("model", "", "base_model")["cancelled"])
            self.assertEqual(window.calls[-1][1]["directory"], str(next_image_dir))
            self.assertTrue(reopened.choose_path("model", str(model_file), "base_model")["cancelled"])
            self.assertEqual(window.calls[-1][1]["directory"], str(model_dir))

    def test_model_download_list_returns_items_for_flux2(self):
        with tempfile.TemporaryDirectory() as temp:
            links = {
                "dit": ("model.safetensors", "FLUX.2 base", "https://example.test/model"),
                "te": ("text.safetensors", "Qwen3", "https://example.test/text"),
                "vae": ("vae.safetensors", "VAE", "https://example.test/vae"),
            }
            core = SimpleNamespace(
                FLUX2_MODEL_LINKS=links,
                flux2_models_dir=lambda: temp,
                flux2_model_files=lambda: {},
            )
            result = ModernUIBridge(core).get_model_downloads("flux2")

            self.assertIsInstance(result, dict)
            self.assertTrue(result["ok"])
            self.assertEqual(result["asset_dir"], temp)
            self.assertEqual([item["key"] for item in result["items"]], ["dit", "te", "vae"])
            self.assertTrue(all(item["required"] for item in result["items"]))

    def test_web_asset_mime_types_override_contaminated_registry_mappings(self):
        database = mimetypes.MimeTypes()
        for extension in (".js", ".mjs", ".css"):
            database.add_type("text/plain", extension, strict=True)

        with patch.object(mimetypes, "_db", database):
            _ensure_web_asset_mimetypes()

            self.assertEqual(mimetypes.guess_type("assets/app.js")[0], "text/javascript")
            self.assertEqual(mimetypes.guess_type("assets/app.mjs")[0], "text/javascript")
            self.assertEqual(mimetypes.guess_type("assets/app.css")[0], "text/css")

    def test_new_modern_projects_store_current_preset_version(self):
        core = ProjectCreationCore()
        result = ModernUIBridge(core).create_project("new-project", "SDXL")

        self.assertTrue(result["ok"], result)
        self.assertEqual(core.projects["new-project"]["preset_version"], core.PRESET_VERSION)
        self.assertEqual(core.projects["new-project"]["mode"], "character")
        self.assertEqual(core.projects["new-project"]["base_type"], "sdxl")

    def test_new_project_architecture_templates_choose_the_matching_base_type(self):
        for template_name, expected_base_type in (("SD1.5", "sd15"), ("SDXL", "sdxl"), ("FLUX.1", "flux"), ("Anima", "anima")):
            with self.subTest(template=template_name):
                core = ProjectCreationCore()
                result = ModernUIBridge(core).create_project("new-project", template_name)

                self.assertTrue(result["ok"], result)
                project = core.projects["new-project"]
                self.assertEqual(project["mode"], "character")
                self.assertEqual(project["base_type"], expected_base_type)

    def test_new_project_mode_override_changes_mode_but_keeps_architecture(self):
        core = ProjectCreationCore()
        result = ModernUIBridge(core).create_project("style-project", "SDXL", mode_override="style")

        self.assertTrue(result["ok"], result)
        self.assertEqual(core.projects["style-project"]["mode"], "style")
        self.assertEqual(core.projects["style-project"]["base_type"], "sdxl")

    def test_mode_override_does_not_change_other_engine_template(self):
        core = ProjectCreationCore()
        result = ModernUIBridge(core).create_project(
            "krea-project", "Krea 2 图像 LoRA", mode_override="style",
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(core.projects["krea-project"]["mode"], "krea2")

    def test_legacy_first_engine_template_names_remain_creatable(self):
        legacy_templates = {
            "人物 LoRA（SDXL）": ("character", "sdxl"),
            "画风 LoRA（SDXL）": ("style", "sdxl"),
            "画风 LoRA（SD1.5）": ("style", "sd15"),
            "概念 LoRA（SDXL）": ("concept", "sdxl"),
        }
        for index, (template_name, expected) in enumerate(legacy_templates.items()):
            with self.subTest(template=template_name):
                core = ProjectCreationCore()
                result = ModernUIBridge(core).create_project("legacy-%d" % index, template_name)

                self.assertTrue(result["ok"], result)
                self.assertEqual(
                    (core.projects["legacy-%d" % index]["mode"], core.projects["legacy-%d" % index]["base_type"]),
                    expected,
                )

    def test_bootstrap_shows_compact_first_engine_templates_and_keeps_other_engines(self):
        core = ProjectCreationCore()
        names = [item["name"] for item in ModernUIBridge(core).bootstrap()["templates"]]

        self.assertEqual(names[:5], ["自定义", "SD1.5", "SDXL", "FLUX.1", "Anima"])
        self.assertNotIn("人物 LoRA（SDXL）", names)
        self.assertNotIn("画风 LoRA（SDXL）", names)
        self.assertNotIn("画风 LoRA（SD1.5）", names)
        self.assertNotIn("概念 LoRA（SDXL）", names)
        self.assertIn("FLUX.2 人物", names)
        self.assertIn("Krea 2 图像 LoRA", names)
        self.assertIn("Qwen-Image", names)

    def test_imported_modern_projects_store_current_preset_version(self):
        core = ProjectCreationCore({"mode": "character", "base_type": "sdxl", "params": {"rank": 32}})
        result = ModernUIBridge(core).create_project(
            "imported-project", "SD1.5", '{"params": {"rank": 32}}', "invalid-override",
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(core.projects["imported-project"]["preset_version"], core.PRESET_VERSION)
        self.assertEqual(core.projects["imported-project"]["mode"], "character")
        self.assertEqual(core.projects["imported-project"]["base_type"], "sdxl")

    def test_task_log_cursor_keeps_working_when_old_logs_are_trimmed(self):
        bridge = ModernUIBridge(object())
        task_id = bridge._begin_task("test", "training")
        for index in range(10001):
            bridge._task_log(task_id, "line %d" % index)

        status = bridge.get_task_status(task_id, 0)
        self.assertEqual(status["next_offset"], 10001)
        self.assertEqual(status["logs"][0], "line 2001")
        bridge._task_log(task_id, "line 10001")
        following = bridge.get_task_status(task_id, status["next_offset"])
        self.assertEqual(following["logs"], ["line 10001"])
        self.assertEqual(following["next_offset"], 10002)

    def test_preflight_and_worker_call_existing_qwen_pipeline(self):
        with tempfile.TemporaryDirectory() as temp:
            core = FakeCore(temp)
            bridge = ModernUIBridge(core)

            prepared = bridge.prepare_training("demo")
            self.assertTrue(prepared["ok"], prepared)
            self.assertEqual(prepared["plan"]["steps"], 2000)
            self.assertEqual(prepared["plan"]["image_count"], 15)

            started = bridge.start_training("demo")
            self.assertTrue(started["ok"], started)
            task_id = started["task_id"]
            deadline = time.time() + 5
            status = bridge.get_task_status(task_id, 0)
            while status.get("status") == "running" and time.time() < deadline:
                time.sleep(0.02)
                status = bridge.get_task_status(task_id, status.get("next_offset", 0))

            self.assertEqual(status["status"], "awaiting_review")
            self.assertEqual(core.training_calls, [])
            continued = bridge.continue_training(task_id)
            self.assertTrue(continued["ok"], continued)
            deadline = time.time() + 5
            status = bridge.get_task_status(task_id, status.get("next_offset", 0))
            while status.get("status") == "running" and time.time() < deadline:
                time.sleep(0.02)
                status = bridge.get_task_status(task_id, status.get("next_offset", 0))

            self.assertEqual(status["status"], "completed", status)
            self.assertEqual(len(core.preprocess_calls), 1)
            self.assertEqual(len(core.training_calls), 1)
            mode, params, vram, resume = core.training_calls[0]
            self.assertEqual(mode, "qwen_image")
            self.assertEqual(params["project"], "demo")
            self.assertEqual(params["rank"], 16)
            self.assertEqual(vram, 24)
            self.assertIsNone(resume)

    def test_preflight_and_worker_call_existing_anima_pipeline_without_classic_ui(self):
        with tempfile.TemporaryDirectory() as temp:
            core = FakeCore(temp)
            base_model = Path(temp) / "anima-base-v1.0.safetensors"
            base_model.write_bytes(b"test fixture")
            core.project = {
                "mode": "character", "base_type": "anima", "base_model": str(base_model),
                "raw_dir": str(core.raw), "trigger": "test_anima", "unet_only": True,
                "params": {
                    "rank": "32", "alpha": "16", "unet_lr": "7e-5", "repeats": "3",
                    "max_epochs": "6", "resolution": "1024", "crop_ratio": "3:4",
                    "wd14_model": "swinv2-v3", "strong_bind": True, "sample_preview": True,
                },
            }
            bridge = ModernUIBridge(core)

            prepared = bridge.prepare_training("anima-demo")
            self.assertTrue(prepared["ok"], prepared)
            self.assertEqual(prepared["plan"]["training_engine"], "kohya")
            self.assertEqual(prepared["plan"]["schedule_value"], "6 轮 · 每张图重复 3 次")
            self.assertEqual(prepared["plan"]["training_target"], "仅训练 DiT；Anima 的 Qwen3 文本编码器固定冻结")
            self.assertFalse(prepared["plan"]["model_download_required"])

            started = bridge.start_training("anima-demo")
            self.assertTrue(started["ok"], started)
            task_id = started["task_id"]
            deadline = time.time() + 5
            status = bridge.get_task_status(task_id, 0)
            while status.get("status") == "running" and time.time() < deadline:
                time.sleep(0.02)
                status = bridge.get_task_status(task_id, status.get("next_offset", 0))

            self.assertEqual(status["status"], "awaiting_review")
            self.assertEqual(core.kohya_calls, [])
            continued = bridge.continue_training(task_id)
            self.assertTrue(continued["ok"], continued)
            deadline = time.time() + 5
            status = bridge.get_task_status(task_id, status.get("next_offset", 0))
            while status.get("status") == "running" and time.time() < deadline:
                time.sleep(0.02)
                status = bridge.get_task_status(task_id, status.get("next_offset", 0))

            self.assertEqual(status["status"], "completed", status)
            self.assertEqual(len(core.preprocess_calls), 1)
            self.assertEqual(core.preprocess_calls[0]["mode"], "character")
            self.assertEqual(core.preprocess_calls[0]["project"], "anima-demo")
            self.assertEqual(core.preprocess_calls[0]["dataset_mode"], "character")
            self.assertEqual(len(core.kohya_calls), 1)
            self.assertEqual(core.training_calls, [])
            model, mode, params, vram, resume = core.kohya_calls[0]
            self.assertEqual(model, str(base_model))
            self.assertEqual(mode, "character")
            self.assertEqual(params["project"], "anima-demo")
            self.assertEqual(params["rank"], 32)
            self.assertEqual(params["crop_ratio"], "3:4")
            self.assertFalse(params["train_text_encoder"])
            self.assertTrue(params["sample_preview"])
            self.assertEqual(vram, 24)
            self.assertIsNone(resume)

    def test_all_remaining_modes_call_their_existing_engine_function_directly(self):
        route = {
            "krea2": "train_krea2", "flux2": "train_flux2", "krea2_at": "train_krea2_at",
            "krea2_fz": "train_krea2_fizgig", "flux2_fz": "train_flux2_fizgig", "video": "train_video",
        }
        for mode, function_name in route.items():
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                core = FakeCore(temp)
                core.project = {
                    "mode": mode, "base_type": "sdxl", "raw_dir": str(core.raw),
                    "at_sub_mode": "character", "trigger": "test_trigger",
                    "params": {"rank": "24", "alpha": "12", "unet_lr": "8e-5", "repeats": "2",
                               "max_epochs": "4", "resolution": "768", "video_steps": "321",
                               "video_frames": "73", "crop_ratio": "3:4", "sample_preview": True},
                }
                bridge = ModernUIBridge(core)
                bridge.get_mode_workspace = lambda requested_mode, project_name="": {
                    "ok": True, "mode": requested_mode, "label": requested_mode,
                    "engine_ready": True, "missing_models": [], "asset_dir": "models/%s" % requested_mode,
                    "gpu_vendor": "nvidia",
                }
                prepared = bridge.prepare_training("engine-demo")
                self.assertTrue(prepared["ok"], prepared)
                self.assertEqual(prepared["plan"]["mode"], mode)
                started = bridge.start_training("engine-demo")
                self.assertTrue(started["ok"], started)
                task_id = started["task_id"]
                deadline = time.time() + 5
                status = bridge.get_task_status(task_id, 0)
                while status.get("status") == "running" and time.time() < deadline:
                    time.sleep(0.02)
                    status = bridge.get_task_status(task_id, status.get("next_offset", 0))
                self.assertEqual(status["status"], "awaiting_review", status)
                self.assertTrue(bridge.continue_training(task_id)["ok"])
                deadline = time.time() + 5
                status = bridge.get_task_status(task_id, status.get("next_offset", 0))
                while status.get("status") == "running" and time.time() < deadline:
                    time.sleep(0.02)
                    status = bridge.get_task_status(task_id, status.get("next_offset", 0))
                self.assertEqual(status["status"], "completed", status)
                self.assertEqual(core.engine_training_calls[0][0], function_name)
                self.assertEqual(core.engine_training_calls[0][1], mode)
                self.assertEqual(core.engine_training_calls[0][2]["project"], "engine-demo")
                self.assertEqual(core.engine_training_calls[0][2]["rank"], 24)

    def test_kohya_sdxl_project_uses_classic_parameters_and_direct_kohya_entrypoint(self):
        with tempfile.TemporaryDirectory() as temp:
            core = FakeCore(temp)
            core.detected_base_type = "sdxl"
            base_model = Path(temp) / "sdxl-base.safetensors"
            base_model.write_bytes(b"fixture")
            core.project = {
                "mode": "character", "base_type": "sdxl", "base_model": str(base_model),
                "raw_dir": str(core.raw), "trigger": "subject", "params": {"rank": "24", "max_epochs": "3"},
            }
            prepared = ModernUIBridge(core).prepare_training("sdxl-demo")
            self.assertTrue(prepared["ok"], prepared)
            self.assertEqual(prepared["plan"]["engine_label"], "Kohya / sd-scripts · SDXL")
            params = ModernUIBridge(core)._classic_training_params(core.project, "sdxl-demo")
            self.assertEqual(params["base_type"], "sdxl")
            self.assertEqual(params["rank"], 24)

    def test_anima_preflight_and_worker_pass_existing_resume_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            core = FakeCore(temp)
            base_model = Path(temp) / "anima-base-v1.0.safetensors"
            base_model.write_bytes(b"test fixture")
            resume_state = str(Path(temp) / "output" / "anima-demo" / "character_lora-step00000200-state")
            core.resume_state = resume_state
            core.project = {
                "mode": "character", "base_type": "anima", "base_model": str(base_model),
                "raw_dir": str(core.raw), "trigger": "test_anima", "unet_only": True,
                "params": {"sample_preview": True},
            }
            bridge = ModernUIBridge(core)

            prepared = bridge.prepare_training("anima-demo")
            self.assertTrue(prepared["ok"], prepared)
            self.assertEqual(prepared["plan"]["resume_path"], resume_state)

            started = bridge.start_training("anima-demo", use_resume=True)
            self.assertTrue(started["ok"], started)
            task_id = started["task_id"]
            deadline = time.time() + 5
            status = bridge.get_task_status(task_id, 0)
            while status.get("status") == "running" and time.time() < deadline:
                time.sleep(0.02)
                status = bridge.get_task_status(task_id, status.get("next_offset", 0))
            self.assertEqual(status["status"], "awaiting_review")

            continued = bridge.continue_training(task_id)
            self.assertTrue(continued["ok"], continued)
            deadline = time.time() + 5
            status = bridge.get_task_status(task_id, status.get("next_offset", 0))
            while status.get("status") == "running" and time.time() < deadline:
                time.sleep(0.02)
                status = bridge.get_task_status(task_id, status.get("next_offset", 0))

            self.assertEqual(status["status"], "completed", status)
            self.assertEqual(len(core.kohya_calls), 1)
            self.assertEqual(core.kohya_calls[0][4], resume_state)

    def test_resume_state_lookup_uses_engine_specific_support(self):
        with tempfile.TemporaryDirectory() as temp:
            core = FakeCore(temp)
            bridge = ModernUIBridge(core)
            with patch.object(core, "find_latest_state", return_value="step-state") as latest, \
                    patch.object(core, "find_musubi_state", return_value="musubi-state", create=True) as musubi, \
                    patch.object(core, "find_fizgig_state", return_value="fizgig-state", create=True) as fizgig:
                self.assertEqual(bridge._resume_path("demo", "character", {}), "step-state")
                self.assertEqual(bridge._resume_path("demo", "krea2", {}), "musubi-state")
                self.assertEqual(bridge._resume_path("demo", "krea2_fz", {}), "fizgig-state")
                self.assertIsNone(bridge._resume_path("demo", "qwen_image", {}))
                self.assertIsNone(bridge._resume_path("demo", "video", {}))
            self.assertEqual(latest.call_count, 1)
            self.assertEqual(musubi.call_count, 1)
            self.assertEqual(fizgig.call_count, 1)

    def test_anima_sample_preview_explicit_off_and_auto_are_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            core = FakeCore(temp)
            base_model = Path(temp) / "anima-base-v1.0.safetensors"
            base_model.write_bytes(b"test fixture")
            bridge = ModernUIBridge(core)
            config = {
                "mode": "character", "base_type": "anima", "base_model": str(base_model),
                "raw_dir": str(core.raw), "params": {"sample_preview": False},
            }

            explicit_off = bridge._anima_training_params(config, "anima-demo")
            self.assertIs(explicit_off["sample_preview"], False)

            config["params"]["sample_preview"] = None
            automatic = bridge._anima_training_params(config, "anima-demo")
            self.assertNotIn("sample_preview", automatic)

    def test_anima_preflight_counts_avif_images_supported_by_preprocessor(self):
        with tempfile.TemporaryDirectory() as temp:
            core = AvifCountingCore(temp)
            raw = Path(temp) / "raw-avif"
            raw.mkdir()
            for index in range(15):
                (raw / f"sample-{index:02d}.avif").write_bytes(b"avif fixture")
            base_model = Path(temp) / "anima-base-v1.0.safetensors"
            base_model.write_bytes(b"test fixture")
            core.project = {
                "mode": "character", "base_type": "anima", "base_model": str(base_model),
                "raw_dir": str(raw), "trigger": "test_anima", "unet_only": True, "params": {},
            }

            prepared = ModernUIBridge(core).prepare_training("anima-avif")

            self.assertTrue(prepared["ok"], prepared)
            self.assertEqual(prepared["plan"]["image_count"], 15)

    def test_export_log_defaults_to_desktop(self):
        with tempfile.TemporaryDirectory() as temp:
            core = FakeCore(temp)
            core.APP_VERSION = "0.18.4"
            bridge = ModernUIBridge(core)
            desktop = Path(temp) / "Desktop"

            with patch.object(bridge, "_desktop_directory", return_value=str(desktop), create=True):
                result = bridge.run_action("export_log")

            self.assertTrue(result["ok"], result)
            exported = Path(result["message"].split("：", 1)[1])
            self.assertEqual(exported.parent, desktop)
            self.assertTrue(exported.is_file())
            content = exported.read_text(encoding="utf-8")
            self.assertIn("软件版本: v0.18.4", content)
            self.assertIn("【运行日志】", content)
            self.assertIn("欢迎使用 Kohya-LoRA 一键训练工具", content)

    def test_cancel_during_label_review_does_not_start_engine(self):
        with tempfile.TemporaryDirectory() as temp:
            core = FakeCore(temp)
            bridge = ModernUIBridge(core)
            started = bridge.start_training("demo")
            self.assertTrue(started["ok"], started)
            task_id = started["task_id"]
            deadline = time.time() + 5
            status = bridge.get_task_status(task_id, 0)
            while status.get("status") == "running" and time.time() < deadline:
                time.sleep(0.02)
                status = bridge.get_task_status(task_id, status.get("next_offset", 0))

            self.assertEqual(status["status"], "awaiting_review")
            cancelled = bridge.cancel_task(task_id)
            self.assertTrue(cancelled["ok"], cancelled)
            status = bridge.get_task_status(task_id, status.get("next_offset", 0))
            self.assertEqual(status["status"], "cancelled")
            self.assertEqual(core.training_calls, [])

    def test_secondary_windows_use_popup_only_classic_host(self):
        with tempfile.TemporaryDirectory() as temp:
            core = FakeCore(temp)
            bridge = ModernUIBridge(core)
            launched = []
            bridge._spawn_classic = lambda *args: launched.append(args)

            project_actions = (
                "label_editor", "export_config", "readme", "at_model_help",
                "at_engine_update", "anima_components", "krea2_guide", "flux2_guide",
                "h3_guide", "video_caption_stub", "video_caption", "amd_env",
            )
            global_actions = ("tools", "check_update", "data_dir", "queue", "env_locations")
            messages = {}
            for action in project_actions:
                result = bridge.run_action(action, "demo")
                self.assertTrue(result["ok"], result)
                messages[action] = result["message"]
            for action in global_actions:
                result = bridge.run_action(action)
                self.assertTrue(result["ok"], result)
                messages[action] = result["message"]

            self.assertIn("标签编辑器", messages["label_editor"])
            self.assertIn("新版训练页和当前项目会保留", messages["label_editor"])
            self.assertIn("关闭此窗口即可继续操作", messages["label_editor"])
            self.assertEqual(messages["tools"], "已在单独窗口打开「小工具」；新版训练页保持打开，关闭工具窗口即可返回。")
            self.assertNotIn("check_update", messages["check_update"])

            self.assertEqual(len(launched), len(project_actions) + len(global_actions))
            for args in launched:
                self.assertIn("--utility-only", args)
            for action, args in zip(project_actions, launched):
                self.assertEqual(args[args.index("--action") + 1], action)
                self.assertEqual(args[args.index("--project") + 1], "demo")
            for action, args in zip(global_actions, launched[len(project_actions):]):
                self.assertEqual(args[args.index("--action") + 1], action)
                self.assertNotIn("--project", args)

            before = len(launched)
            self.assertFalse(bridge.run_action("mode:character")["ok"])
            self.assertFalse(bridge.run_action("train")["ok"])
            self.assertEqual(len(launched), before)

    def test_preprocess_action_uses_modern_task_workflow(self):
        with tempfile.TemporaryDirectory() as temp:
            core = FakeCore(temp)
            bridge = ModernUIBridge(core)
            launched = []
            bridge._spawn_classic = lambda *args: launched.append(args)

            started = bridge.run_action("preprocess", "demo")

            self.assertTrue(started["ok"], started)
            self.assertEqual(launched, [])
            task_id = started["task_id"]
            deadline = time.time() + 5
            status = bridge.get_task_status(task_id, 0)
            while status.get("status") == "running" and time.time() < deadline:
                time.sleep(0.02)
                status = bridge.get_task_status(task_id, status.get("next_offset", 0))
            self.assertEqual(status["status"], "completed", status)
            self.assertEqual(len(core.preprocess_calls), 1)
            self.assertEqual(core.training_calls, [])

    def test_project_name_suggestions_advance_past_existing_and_reserved_names(self):
        with tempfile.TemporaryDirectory() as temp:
            core = FakeCore(temp)
            base = "项目_0925_1100"
            core.default_project_name = lambda: base
            core.list_projects = lambda: [
                {"name": base, "mode": "character"},
                {"name": base + "_2", "mode": "character"},
            ]
            bridge = ModernUIBridge(core)

            suggestions = [bridge.suggest_project_name()["name"] for _ in range(3)]

            self.assertEqual(suggestions, [base + "_3", base + "_4", base + "_5"])

    def test_manual_preprocess_runs_without_starting_training(self):
        with tempfile.TemporaryDirectory() as temp:
            core = FakeCore(temp)
            bridge = ModernUIBridge(core)
            started = bridge.start_preprocess_task("demo")
            self.assertTrue(started["ok"], started)
            task_id = started["task_id"]
            deadline = time.time() + 5
            status = bridge.get_task_status(task_id, 0)
            while status.get("status") == "running" and time.time() < deadline:
                time.sleep(0.02)
                status = bridge.get_task_status(task_id, status.get("next_offset", 0))

            self.assertEqual(status["status"], "completed", status)
            self.assertEqual(len(core.preprocess_calls), 1)
            self.assertEqual(core.training_calls, [])


if __name__ == "__main__":
    unittest.main()
