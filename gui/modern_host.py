"""Windows WebView host and narrow bridge for the modern training UI."""

from __future__ import annotations

import os
import re
import mimetypes
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

try:
    from model_downloader import ModelDownloader
except Exception:  # pragma: no cover - desktop package may omit the optional helper
    ModelDownloader = None


_MODERN_PROJECT_TEMPLATES = {
    "概念 LoRA（SDXL）": {"mode": "concept", "base_type": "sdxl", "note": "第一引擎概念训练；支持形态、服装、物品和身体部位。"},
    "Krea 2 图像 LoRA": {"mode": "krea2", "base_type": "sdxl", "note": "第二引擎 musubi；模型文件放在 models/krea2。"},
    "H3 视频 LoRA": {"mode": "video", "base_type": "sdxl", "note": "第三引擎 AI Toolkit；使用视频文件和同名字幕。"},
    "Krea2 图像 LoRA（AI Toolkit）": {"mode": "krea2_at", "base_type": "sdxl", "note": "第三引擎 AI Toolkit；Krea2 RAW 模型放在 models/krea2。"},
    "Z-Image LoRA": {"mode": "zimage", "base_type": "sdxl", "note": "第三引擎 AI Toolkit；轻量图像模型，按步训练。"},
    "Krea2 图像 LoRA（Fizgig）": {"mode": "krea2_fz", "base_type": "sdxl", "note": "第四引擎 Fizgig；NVIDIA / AMD 通道，复用 models/krea2。"},
    "Klein 9B LoRA（Fizgig）": {"mode": "flux2_fz", "base_type": "sdxl", "note": "第四引擎 Fizgig；Klein 9B 图像 LoRA，模型放在 models/flux2。"},
}

_WORKSPACE_PARAM_KEYS = (
    "rank", "alpha", "unet_lr", "te_lr", "repeats", "max_epochs", "resolution",
    "save_every", "sample_interval", "video_steps", "video_frames", "optimizer",
    "strong_bind", "clean_concept", "sample_preview", "compile", "crop_ratio",
    "sample_prompt", "noise_offset", "min_snr_gamma", "quant_mode", "blocks_to_swap",
    "wd14_model", "overwrite", "amd_mode", "global_pos", "global_neg",
)

# These fields are accepted by the modern workspace save bridge, but were added
# after the classic JSON importer whitelist was defined. Preserve them when a
# modern project is created from a compatible JSON file.
_MODERN_IMPORT_EXTRA_PARAMS = {
    "sample_interval", "video_frames", "noise_offset", "min_snr_gamma",
    "wd14_model", "overwrite", "amd_mode",
}

_APPEARANCE_BACKGROUND_HISTORY_LIMIT = 8


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _has_webview2_runtime() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        client_id = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
        registry_paths = (
            (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{client_id}"),
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{client_id}"),
            (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{client_id}"),
        )
        for hive, path in registry_paths:
            try:
                with winreg.OpenKey(hive, path) as key:
                    version, _ = winreg.QueryValueEx(key, "pv")
                numbers = tuple(int(part) for part in re.findall(r"\d+", str(version))[:4])
                if numbers >= (86, 0, 622, 0):
                    return True
            except OSError:
                continue
    except Exception:
        return False
    return False


def _ensure_web_asset_mimetypes() -> None:
    """Protect local WebView assets from Windows registry MIME overrides.

    ``mimetypes`` imports Windows extension mappings from the registry. A bad
    ``.js`` Content Type makes pywebview's Bottle server return JavaScript as
    ``text/plain``; Chromium then refuses the module script and leaves a blank
    page. Add the standard web types after registry initialization to override
    any per-machine or per-user mapping.
    """
    mimetypes.add_type("text/javascript", ".js", strict=True)
    mimetypes.add_type("text/javascript", ".mjs", strict=True)
    mimetypes.add_type("text/css", ".css", strict=True)


class ModernUIBridge:
    """Expose a small JSON-shaped interface to the Vue frontend."""

    def __init__(self, core, engine_groups=(), short_mode_labels=None):
        self.core = core
        self.engine_groups = engine_groups
        self.short_mode_labels = short_mode_labels or {}
        # Keep the native pywebview Window out of the public JS API surface.
        # pywebview 6 recursively inspects public object attributes while
        # building the bridge; exposing this object can stall initialization.
        self._window = None
        self.logs = [
            "欢迎使用 Kohya-LoRA 一键训练工具",
            "按左侧新手引导顺序操作；打开项目后进入新版训练页。",
        ]
        self._task_lock = threading.RLock()
        self._task = None
        self._task_downloader = None
        self._project_name_reservations = set()

    @staticmethod
    def _count_preprocessable_images(directory):
        """Count source images using the same extensions and scan rule as preprocess.py."""
        from preprocess import IMAGE_EXTS as supported_extensions

        root_images = [
            filename for filename in os.listdir(directory)
            if os.path.splitext(filename)[1].lower() in supported_extensions
            and os.path.isfile(os.path.join(directory, filename))
        ]
        if root_images:
            return len(root_images)

        count = 0
        for root, dirs, files in os.walk(directory):
            dirs[:] = [name for name in dirs if not name.startswith(".")]
            count += sum(
                1 for filename in files
                if os.path.splitext(filename)[1].lower() in supported_extensions
            )
        return count

    @staticmethod
    def _desktop_directory():
        return os.path.join(os.path.expanduser("~"), "Desktop")

    def _log(self, message):
        self.logs.append(str(message))
        if len(self.logs) > 3000:
            del self.logs[:-3000]

    def _task_log(self, task_id, message):
        message = str(message)
        with self._task_lock:
            task = self._task
            if task and task.get("id") == task_id:
                task["logs"].append(message)
                if len(task["logs"]) > 10000:
                    dropped = len(task["logs"]) - 8000
                    del task["logs"][:dropped]
                    task["log_offset"] = int(task.get("log_offset", 0) or 0) + dropped
        self._log(message)

    def get_task_status(self, task_id, after=0):
        """Return incremental output for an in-app setup/download dialog."""
        with self._task_lock:
            task = self._task
            if not task or task.get("id") != str(task_id or ""):
                return {"ok": False, "error": "任务已不存在，请重新打开操作。"}
            try:
                offset = max(0, int(after or 0))
            except (TypeError, ValueError):
                offset = 0
            logs = task.get("logs", [])
            log_offset = int(task.get("log_offset", 0) or 0)
            return {
                "ok": True,
                "id": task["id"],
                "title": task["title"],
                "status": task["status"],
                "message": task.get("message", ""),
                "progress": task.get("progress"),
                "detail": task.get("detail", ""),
                "logs": logs[max(0, offset - log_offset):],
                "next_offset": log_offset + len(logs),
            }

    def _begin_task(self, title, kind, mode="", key=""):
        with self._task_lock:
            if self._task and self._task.get("status") in ("running", "awaiting_review"):
                return None
            task_id = uuid.uuid4().hex
            self._task = {
                "id": task_id, "title": str(title), "kind": kind, "mode": mode,
                "key": key, "status": "running", "message": "正在启动…",
                "progress": None, "detail": "", "logs": [], "log_offset": 0,
                "started": time.time(), "review_event": None,
            }
            self._task_downloader = None
            return task_id

    def start_setup_task(self, action):
        """Run existing prerequisite/engine installers behind the modern task dialog."""
        action = str(action or "")
        installers = {
            "cmd_env": ("环境准备（Git / Python）", self.core.ensure_prereqs),
            "cmd_install": ("安装 Kohya 训练内核", self.core.install_kohya),
            "cmd_install_musubi": ("安装第二引擎 · musubi", self.core.install_musubi_engine),
            "cmd_install_at": ("安装第三引擎 · AI Toolkit", self.core.install_ai_toolkit_engine),
            "cmd_install_fizgig": ("安装第四引擎 · Fizgig", self.core.install_fizgig_engine),
        }
        spec = installers.get(action)
        if not spec:
            return {"ok": False, "error": "这个安装任务尚未接入新版训练页。"}
        title, installer = spec
        task_id = self._begin_task(title, "setup")
        if not task_id:
            return {"ok": False, "error": "已有环境、引擎或模型下载任务正在运行，请等它完成后再试。"}

        def worker():
            try:
                self.core.reset_stop()
                installer(lambda line: self._task_log(task_id, line))
                self.core.clear_status_cache()
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task.update(status="completed", message="操作完成。")
                self._task_log(task_id, "[完成] %s" % title)
            except getattr(self.core, "StopRequested", Exception) as exc:
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task.update(status="cancelled", message="操作已停止。")
                self._task_log(task_id, "[停止] %s" % (exc or "用户已停止操作"))
            except Exception as exc:
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task.update(status="failed", message=str(exc))
                self._task_log(task_id, "[失败] %s" % exc)

        threading.Thread(target=worker, name="ModernSetupTask", daemon=True).start()
        return {"ok": True, "task_id": task_id}

    def _model_download_spec(self, mode):
        mode = str(mode or "")
        specs = {
            "krea2": ("Krea 2 模型", "Krea2 训练文件", "KREA2_MODEL_LINKS", "krea2_models_dir", "krea2_model_files", {"raw", "vae", "te"}),
            "krea2_at": ("Krea2 模型", "Krea2 AI Toolkit 训练文件", "KREA2_MODEL_LINKS", "krea2_models_dir", "krea2_model_files", {"raw", "vae"}),
            "krea2_fz": ("Krea2 模型", "Krea2 Fizgig 训练文件", "KREA2_MODEL_LINKS", "krea2_models_dir", "krea2_model_files", {"raw", "vae", "te"}),
            "flux2": ("FLUX.2 模型", "FLUX.2 4B 训练文件", "FLUX2_MODEL_LINKS", "flux2_models_dir", "flux2_model_files", {"dit", "te", "vae"}),
            "flux2_fz": ("Klein 9B 模型", "FLUX.2 Klein 9B 训练文件", "FLUX2FZ_MODEL_LINKS", "flux2_models_dir", "flux2_fz_model_files", {"dit", "te", "vae"}),
            "video": ("H3 模型", "MiniMax H3 视频训练文件", "H3_MODEL_LINKS", "h3_models_dir", "h3_model_files", {"te", "video_vae"}),
        }
        return specs.get(mode)

    def get_model_downloads(self, mode):
        spec = self._model_download_spec(mode)
        if not spec:
            return {"ok": False, "error": "该模式没有可在新版训练页管理的模型下载列表。"}
        title, description, links_name, dir_name, files_name, required = spec
        links = getattr(self.core, links_name, {})
        asset_dir = str(getattr(self.core, dir_name)())
        existing = getattr(self.core, files_name)()
        partial_sizes = {}
        items = []
        for key, value in links.items():
            filename, label, url = value
            present = bool(existing.get(key))
            path = str(existing.get(key) or os.path.join(asset_dir, filename))
            try:
                part_size = os.path.getsize(path + ".part") if os.path.isfile(path + ".part") else 0
            except OSError:
                part_size = 0
            main_choice = mode == "video" and key in ("dit", "dit_nvfp4")
            items.append({
                "key": key, "filename": filename, "label": self._plain_ui_text(label),
                "url": url, "path": path, "present": present,
                "required": key in required,
                "required_group": "主模型（二选一）" if main_choice else "",
                "optional": key not in required and not main_choice,
                "part_size": part_size,
            })
        note = ""
        if mode == "krea2_at":
            note = "AI Toolkit 的文本编码器会在首次训练时按需准备；RAW 底模和 VAE 可在此提前下载。"
        elif mode == "video":
            note = "主模型可选 int8 或 nvfp4 其中一个；文本编码器和视频 VAE 需要准备，音频 VAE 可选。"
        else:
            note = "下载支持断点续传；取消或中断后再次点击同一文件即可接着下载。"
        params = {
            "ok": True, "mode": mode, "title": title, "description": description,
            "asset_dir": asset_dir, "note": note, "items": items,
        }

    def start_model_download(self, mode, key):
        spec = self._model_download_spec(mode)
        if not spec:
            return {"ok": False, "error": "该模式没有模型下载入口。"}
        if ModelDownloader is None:
            return {"ok": False, "error": "模型下载模块不可用，请重新安装软件。"}
        _title, _description, links_name, dir_name, files_name, _required = spec
        links = getattr(self.core, links_name, {})
        if key not in links:
            return {"ok": False, "error": "所选模型文件不存在。"}
        filename, label, url = links[key]
        asset_dir = str(getattr(self.core, dir_name)())
        os.makedirs(asset_dir, exist_ok=True)
        dest = os.path.join(asset_dir, os.path.basename(filename))
        existing = getattr(self.core, files_name)()
        if existing.get(key) and os.path.isfile(existing[key]):
            return {"ok": False, "error": "该模型文件已存在，无需重复下载。"}
        task_id = self._begin_task("下载模型文件", "download", mode=mode, key=key)
        if not task_id:
            return {"ok": False, "error": "已有环境、引擎或模型下载任务正在运行，请等它完成后再试。"}

        def progress(done, total, speed):
            pct = (float(done) / float(total)) if total else None
            message = "已下载 %.1f / %.1f MB · %.1f MB/s" % (
                done / 1048576.0, total / 1048576.0, speed / 1048576.0
            ) if total else "已下载 %.1f MB · %.1f MB/s" % (done / 1048576.0, speed / 1048576.0)
            with self._task_lock:
                if self._task and self._task.get("id") == task_id:
                    self._task.update(progress=pct, detail=message, message=message)

        def done(ok, path):
            with self._task_lock:
                if self._task and self._task.get("id") == task_id:
                    self._task.update(
                        status="completed" if ok else "failed",
                        message="下载完成。" if ok else "下载失败；已保留可续传的部分文件。",
                        progress=1.0 if ok else self._task.get("progress"), detail=str(path),
                    )
            self._task_log(task_id, "[下载完成] %s" % path if ok else "[下载失败] %s" % path)
            self.core.clear_status_cache()

        self._task_log(task_id, "[下载] %s：%s" % (label, filename))
        downloader = ModelDownloader(url, dest, progress_cb=progress,
                                     done_cb=done,
                                     logf=lambda line: self._task_log(task_id, line))
        with self._task_lock:
            self._task_downloader = downloader
        downloader.start()
        return {"ok": True, "task_id": task_id}

    def cancel_task(self, task_id):
        with self._task_lock:
            if not self._task or self._task.get("id") != str(task_id or "") or self._task.get("status") not in ("running", "awaiting_review"):
                return {"ok": False, "error": "当前没有可停止的任务。"}
            downloader = self._task_downloader
            kind = self._task.get("kind")
            awaiting_review = self._task.get("status") == "awaiting_review"
            review_event = self._task.get("review_event")
            self._task["message"] = "正在请求停止…"
            if awaiting_review:
                self._task.update(status="cancelled", message="已取消后续训练；预处理结果已保留。")
        if awaiting_review:
            if review_event is not None:
                review_event.set()
            self._task_log(str(task_id), "[取消] 用户取消了后续训练；预处理数据已保留。")
            return {"ok": True}
        if downloader is not None:
            downloader.cancel()
        elif kind in ("setup", "training", "preprocess"):
            self.core.stop_active_process()
        return {"ok": True}

    def continue_training(self, task_id):
        """Resume a training task after the user reviews preprocessed captions."""
        with self._task_lock:
            task = self._task
            if not task or task.get("id") != str(task_id or "") or task.get("status") != "awaiting_review":
                return {"ok": False, "error": "当前任务不在等待检查标签的状态。"}
            review_event = task.get("review_event")
            if review_event is None:
                return {"ok": False, "error": "训练确认状态已失效，请重新启动训练。"}
            task.update(status="running", message="已确认标签，正在启动训练引擎…", detail="模型加载可能需要几分钟")
            review_event.set()
        self._task_log(str(task_id), "[训练] 用户已检查标签并确认继续。")
        return {"ok": True}

    def start_preprocess_task(self, project_name):
        """Run the existing image/video preparation path in the modern task dialog."""
        project_name = str(project_name or "").strip()
        config = self.core.load_project(project_name) if project_name else None
        if not isinstance(config, dict):
            return {"ok": False, "error": "项目不存在或配置文件已损坏。"}
        raw_dir = str(config.get("raw_dir") or "").strip()
        if not raw_dir or not os.path.isdir(raw_dir):
            return {"ok": False, "error": "请先在新版训练页选择有效的数据文件夹。"}

        mode = str(config.get("mode") or "character")
        if mode == "video":
            has_videos = bool(self.core.scan_video_dataset(raw_dir)[0])
            if not has_videos:
                return {"ok": False, "error": "当前文件夹没有找到可用的视频文件。"}
        elif self._count_preprocessable_images(raw_dir) <= 0:
            return {"ok": False, "error": "当前文件夹没有找到可处理的图片。"}

        stored = config.get("params") if isinstance(config.get("params"), dict) else {}
        try:
            preset = dict(self.core.preset_for(mode, config.get("base_type") or "sdxl") or {})
        except Exception:
            preset = {}
        size = self._training_number(
            stored.get("resolution"),
            preset.get("resolution", getattr(self.core, "RESOLUTIONS", {}).get(config.get("base_type"), 512)),
            int,
        )
        if mode in ("krea2", "krea2_fz", "krea2_at") and not stored.get("resolution"):
            size = int(getattr(self.core, "KREA2_RESOLUTION", size))
        elif mode == "flux2_fz" and not stored.get("resolution"):
            size = int(getattr(self.core, "FLUX2FZ_RESOLUTION", size))
        task_id = self._begin_task("%s 数据预处理" % self.core.MODE_LABELS.get(mode, mode), "preprocess", mode=mode)
        if not task_id:
            return {"ok": False, "error": "已有安装、预处理或训练任务正在运行，请等它完成后再试。"}
        self.core.reset_stop()

        def worker():
            import json
            import tempfile

            report_path = os.path.join(tempfile.gettempdir(), "kohya_modern_manual_preprocess_%s.json" % task_id)
            try:
                if mode == "video":
                    videos, duration, no_caption = self.core.scan_video_dataset(raw_dir)
                    self._task_log(task_id, "[预处理] 视频数据已就绪：%d 个视频，%.1f 秒，%d 个缺字幕。视频无需图片预处理。" % (
                        len(videos), duration, no_caption
                    ))
                    message = "视频数据检查完成。"
                else:
                    self._task_log(task_id, "[预处理] 正在检查、整理并打标当前图集…")
                    with self._task_lock:
                        if self._task and self._task.get("id") == task_id:
                            self._task.update(message="正在预处理图片与标签…", detail="调用原有预处理器")
                    at_sub_mode = str(config.get("at_sub_mode") or "character")
                    preprocess_mode = self.core.preprocess_mode(mode, at_sub_mode)
                    args = {
                        "input_dir": raw_dir, "size": size,
                        "mode": preprocess_mode, "trigger": str(config.get("trigger") or ""),
                        "reg_dir": str(config.get("reg_dir") or ""),
                        "repeats": self._training_number(stored.get("repeats"), preset.get("repeats", 1), int),
                        "dedup": True, "wd14": True, "square_crop": False,
                        "crop_ratio": str(stored.get("crop_ratio") or "不裁切（保比例）"),
                        "wd14_model": str(stored.get("wd14_model") or "swinv2-v3"),
                        "min_size": 256, "blur_threshold": 30.0, "report": report_path,
                        "keep_tokens": None, "project": project_name,
                        "style_caption": str(config.get("style_caption") or ""),
                        "dataset_mode": "character" if mode != "style" else None,
                        "strong_bind": bool(stored.get("strong_bind", True)),
                        "concept_type": str(config.get("concept_type") or ""),
                        "clean_concept": bool(stored.get("clean_concept", True)),
                        "concept_mode": self.core.is_concept_mode(mode, at_sub_mode),
                        "style_target": self.core.style_target_code(config.get("style_preset")),
                        "overwrite": bool(stored.get("overwrite", False)),
                    }
                    if mode == "style" and config.get("base_type") == "anima":
                        args["dataset_mode"] = None
                    self.core.preprocess(lambda line: self._task_log(task_id, line), **args)
                    stats = {}
                    if os.path.isfile(report_path):
                        try:
                            with open(report_path, "r", encoding="utf-8") as handle:
                                stats = json.load(handle)
                        except Exception:
                            pass
                    count = int(stats.get("ok", 0) or 0) + int(stats.get("skipped_existing", 0) or 0)
                    self._task_log(task_id, "[预处理] 已完成，可用图片 %d 张；可以打开标签编辑器检查结果。" % count)
                    message = "数据预处理完成；可以打开标签编辑器检查标签。"
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task.update(status="completed", message=message, progress=1.0, detail="预处理结果已保存到当前项目数据集")
            except getattr(self.core, "StopRequested", Exception):
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task.update(status="cancelled", message="数据预处理已停止；已完成的结果保留。")
                self._task_log(task_id, "[停止] 数据预处理已停止；已完成的结果保留。")
            except Exception as exc:
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task.update(status="failed", message="数据预处理失败：%s" % exc)
                self._task_log(task_id, "[失败] 数据预处理失败：%s" % exc)
            finally:
                try:
                    if os.path.isfile(report_path):
                        os.remove(report_path)
                except OSError:
                    pass

        threading.Thread(target=worker, name="ModernPreprocess", daemon=True).start()
        self._log("[预处理] 已从新版训练页启动「%s」项目的数据预处理。" % project_name)
        return {"ok": True, "task_id": task_id}

    @staticmethod
    def _training_number(value, fallback, cast):
        if value in (None, ""):
            return cast(fallback)
        try:
            return cast(float(value)) if cast is int else cast(value)
        except (TypeError, ValueError, OverflowError):
            return cast(fallback)

    def _qwen_training_params(self, config, project_name):
        """Build the existing AI Toolkit argument shape from a saved modern project."""
        mode = str(config.get("mode") or "")
        if mode not in ("qwen_image", "zimage"):
            raise ValueError("新版训练页直连训练目前只接入 Qwen-Image / Z-Image。")
        stored = config.get("params") if isinstance(config.get("params"), dict) else {}
        base_type = str(config.get("base_type") or "sdxl")
        preset = dict(self.core.preset_for(mode, base_type) or {})

        def value(key, default=None):
            candidate = stored.get(key)
            return preset.get(key, default) if candidate in (None, "") else candidate

        def integer(key, default):
            return self._training_number(value(key, default), default, int)

        params = {
            "mode": mode,
            "base_type": base_type,
            "at_sub_mode": str(config.get("at_sub_mode") or "character"),
            "concept_type": str(config.get("concept_type") or "form"),
            "clean_concept": bool(value("clean_concept", True)),
            "fast_tier": str(config.get("fast_tier") or "auto"),
            "trigger": str(config.get("trigger") or "").strip(),
            "strong_bind": bool(value("strong_bind", True)),
            "raw_dir": str(config.get("raw_dir") or "").strip(),
            "reg_dir": str(config.get("reg_dir") or "").strip() or None,
            "base_model": str(config.get("base_model") or "").strip() or None,
            "rank": integer("rank", 16),
            "alpha": integer("alpha", 16),
            "unet_lr": str(value("unet_lr", "1e-4")),
            "te_lr": str(value("te_lr", "1e-4")),
            "repeats": integer("repeats", 1),
            "max_epochs": integer("max_epochs", 20),
            "resolution": integer("resolution", 1024),
            "video_steps": integer("video_steps", 2000),
            "save_every": value("save_every", None),
            "sample_interval": integer("sample_interval", 0),
            "sample_prompt": str(value("sample_prompt", "") or ""),
            "optimizer": str(value("optimizer", "auto") or "auto"),
            "crop_ratio": self.core.normalize_crop_ratio(value("crop_ratio", "")),
            "train_text_encoder": not bool(config.get("unet_only", False)),
            "style_preset": str(config.get("style_preset") or "自定义"),
            "style_caption": str(config.get("style_caption") or "").strip(),
            "wd14_model": str(value("wd14_model", "swinv2-v3") or "swinv2-v3"),
            "overwrite": bool(value("overwrite", False)),
            "amd_mode": bool(value("amd_mode", False)),
            "train_env": str(config.get("train_env") or "").strip() or None,
            "project": project_name,
        }
        if stored.get("sample_preview") is not None:
            params["sample_preview"] = bool(stored.get("sample_preview"))
        for key in ("compile", "quant_mode", "blocks_to_swap", "noise_offset", "min_snr_gamma", "global_pos", "global_neg"):
            if key in stored:
                params[key] = stored[key]
        return params

    def prepare_training(self, project_name):
        """Run read-only preflight for a modern workspace's directly supported path."""
        project_name = str(project_name or "").strip()
        config = self.core.load_project(project_name) if project_name else None
        if not isinstance(config, dict):
            return {"ok": False, "error": "项目不存在或配置文件已损坏。"}
        mode = str(config.get("mode") or "")
        if mode in ("qwen_image", "zimage"):
            return self._prepare_qwen_training(project_name)
        if mode in ("character", "style", "concept"):
            return self._prepare_anima_training(project_name, config)
        return self._prepare_engine_training(project_name, config)

    def _prepare_engine_training(self, project_name, config):
        """Preflight the existing musubi, Fizgig and AI Toolkit engine functions."""
        mode = str(config.get("mode") or "")
        if mode not in getattr(self.core, "MODE_KEYS", ()):
            return {"ok": False, "error": "未知的训练模式。"}
        try:
            params = self._classic_training_params(config, project_name)
        except (ValueError, KeyError, TypeError) as exc:
            return {"ok": False, "error": "无法读取训练参数：%s" % exc}
        raw_dir = params.get("raw_dir") or ""
        if not raw_dir or not os.path.isdir(raw_dir):
            return {"ok": False, "error": "请先在新版训练页选择有效的数据集文件夹。"}
        try:
            details = self.get_mode_workspace(mode, project_name)
        except Exception as exc:
            return {"ok": False, "error": "无法读取训练模式状态：%s" % exc}
        if not details.get("engine_ready"):
            engine_names = {
                "krea2": "第二引擎 musubi", "flux2": "第二引擎 musubi",
                "krea2_fz": "第四引擎 Fizgig", "flux2_fz": "第四引擎 Fizgig",
                "video": "第三引擎 AI Toolkit", "krea2_at": "第三引擎 AI Toolkit",
            }
            return {"ok": False, "error": "%s 尚未就绪；请先从左侧新手引导安装对应引擎。" % engine_names.get(mode, "训练引擎")}
        missing = list(details.get("missing_models") or [])
        if missing:
            return {"ok": False, "error": "当前模式的必需模型文件尚未齐全：\n%s\n\n模型目录：%s" % (
                "\n".join(str(item) for item in missing), details.get("asset_dir") or "未指定")}

        warnings = []
        min_count = int(getattr(self.core, "MIN_IMAGES", {}).get(mode, 15))
        if mode == "video":
            try:
                videos, duration, no_caption = self.core.scan_video_dataset(raw_dir)
            except Exception as exc:
                return {"ok": False, "error": "无法读取视频数据集：%s" % exc}
            image_count = len(videos)
            if image_count < min_count:
                return {"ok": False, "error": "视频数据只有 %d 段；至少需要 %d 段。" % (image_count, min_count)}
            if no_caption == image_count:
                return {"ok": False, "error": "所有视频都没有同名 .txt 字幕；先用新版训练页的占位字幕或 AI 描述工具生成字幕。"}
            if no_caption:
                warnings.append("有 %d 段视频缺少字幕，训练引擎会忽略无字幕视频。" % no_caption)
            if str(details.get("gpu_vendor") or "").lower() == "amd":
                return {"ok": False, "error": "MiniMax H3 视频训练目前不支持 Windows AMD 通道。"}
            vram = self._safe_vram()
            if vram is not None and vram < 24:
                warnings.append("当前显存约 %.1f GB，H3 推荐 24GB 以上；训练可能很慢或显存不足。" % vram)
            model_label = "MiniMax H3"
            schedule_value = "%d 步 · %d 帧" % (params.get("video_steps") or 2000, params.get("video_frames") or 73)
            steps = int(params.get("video_steps") or 2000)
        else:
            try:
                image_count = self._count_preprocessable_images(raw_dir)
            except Exception as exc:
                return {"ok": False, "error": "无法读取图集：%s" % exc}
            if image_count < min_count:
                return {"ok": False, "error": "图集只有 %d 张图片；%s 至少需要 %d 张。" % (
                    image_count, self.core.MODE_LABELS.get(mode, mode), min_count)}
            model_label = details.get("label") or self.core.MODE_LABELS.get(mode, mode)
            schedule_value = "%d 轮 · 每张图重复 %d 次" % (params.get("max_epochs") or 1, params.get("repeats") or 1)
            steps = 0

        try:
            vendor = str(self.core.detect_gpu_vendor() or "unknown").lower()
        except Exception:
            vendor = str(details.get("gpu_vendor") or "unknown").lower()
        vram = self._safe_vram()
        supports_amd = bool(getattr(self.core, "param_supports", lambda *_: False)("amd_mode", mode))
        if vendor == "amd" and supports_amd and not params.get("amd_mode"):
            return {"ok": False, "error": "检测到 AMD 显卡；请在新版训练页开启 AMD 兼容模式并保存，再开始训练。"}
        if vendor != "amd":
            try:
                if not self.core.detect_nvidia_gpu():
                    warnings.append("没有检测到 NVIDIA GPU；请确认训练环境支持当前显卡。")
            except Exception:
                pass
        resume_path = self._resume_path(project_name, mode, params)
        plan = {
            "project_name": project_name, "mode": mode,
            "mode_label": self.core.MODE_LABELS.get(mode, mode),
            "training_engine": self._engine_kind_for_mode(mode),
            "engine_label": self._engine_label_for_mode(mode),
            "model_label": model_label,
            "model_path": str(details.get("asset_dir") or "由引擎管理"),
            "model_download_required": False, "model_size": "",
            "raw_dir": raw_dir, "image_count": image_count, "min_images": min_count,
            "training_type": params.get("at_sub_mode") or mode,
            "training_target": "按当前模式调用已有训练引擎入口",
            "schedule_label": "训练计划", "schedule_value": schedule_value,
            "rank": params["rank"], "alpha": params["alpha"],
            "learning_rate": str(params["unet_lr"]), "resolution": params["resolution"],
            "steps": steps, "trigger": params["trigger"],
            "gpu_vendor": vendor, "vram_gb": vram, "warnings": warnings,
            "resume_path": str(resume_path or ""),
        }
        return {"ok": True, "plan": plan}

    def _safe_vram(self):
        try:
            return self.core.detect_vram_gb()
        except Exception:
            return None

    @staticmethod
    def _engine_kind_for_mode(mode):
        return {"style": "kohya", "character": "kohya", "concept": "kohya",
                "krea2": "musubi", "flux2": "musubi", "krea2_fz": "fizgig", "flux2_fz": "fizgig",
                "video": "ai_toolkit", "krea2_at": "ai_toolkit", "qwen_image": "ai_toolkit", "zimage": "ai_toolkit"}.get(mode, "unknown")

    @staticmethod
    def _engine_label_for_mode(mode):
        return {"style": "Kohya / sd-scripts", "character": "Kohya / sd-scripts", "concept": "Kohya / sd-scripts",
                "krea2": "musubi-tuner", "flux2": "musubi-tuner", "krea2_fz": "Fizgig", "flux2_fz": "Fizgig",
                "video": "AI Toolkit", "krea2_at": "AI Toolkit", "qwen_image": "AI Toolkit", "zimage": "AI Toolkit"}.get(mode, "训练引擎")

    def _resume_path(self, project_name, mode, params):
        try:
            output_dir = self.core.data_sub("output", project_name)
            return self.core.find_latest_state(output_dir, self.core.output_name_for(mode, params.get("style_preset")))
        except Exception:
            return None

    def _prepare_qwen_training(self, project_name):
        """Run the existing read-only preflight for the AI Toolkit path."""
        project_name = str(project_name or "").strip()
        config = self.core.load_project(project_name) if project_name else None
        if not isinstance(config, dict):
            return {"ok": False, "error": "项目不存在或配置文件已损坏。"}
        try:
            params = self._qwen_training_params(config, project_name)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if params["at_sub_mode"] not in ("character", "style", "concept"):
            return {"ok": False, "error": "训练类型配置无效，请重新选择人物、画风或概念模式。"}
        if params["concept_type"] not in getattr(self.core, "CONCEPT_TYPE_KEYS", ("form", "outfit", "object", "bodypart")):
            return {"ok": False, "error": "概念类型配置无效，请重新选择概念类型。"}
        try:
            learning_rate = float(params["unet_lr"])
        except (TypeError, ValueError):
            return {"ok": False, "error": "学习率不是有效数字，请检查后再开始训练。"}
        if not (learning_rate > 0 and learning_rate < float("inf")):
            return {"ok": False, "error": "学习率必须是大于 0 的有限数值。"}
        raw_dir = params["raw_dir"]
        if not raw_dir or not os.path.isdir(raw_dir):
            return {"ok": False, "error": "请先在新版训练页选择一个有效的原始图片文件夹。"}
        try:
            image_count = self._count_preprocessable_images(raw_dir)
        except Exception as exc:
            return {"ok": False, "error": "无法读取图集：%s" % exc}
        min_images = int(getattr(self.core, "MIN_IMAGES", {}).get(params["mode"], 15))
        if image_count < min_images:
            return {"ok": False, "error": "图集只有 %d 张图片；%s 至少需要 %d 张。" % (
                image_count, self.core.MODE_LABELS.get(params["mode"], params["mode"]), min_images
            )}
        try:
            engine_ok, engine_detail, _vpy = self.core.ai_toolkit_engine_status()
        except Exception as exc:
            engine_ok, engine_detail, _vpy = False, str(exc), None
        if not engine_ok:
            return {"ok": False, "error": "AI Toolkit 第三引擎尚未就绪：\n%s" % engine_detail}

        info = self.core.at_image_info(params["mode"])
        if not info:
            return {"ok": False, "error": "无法读取当前训练模型设置。"}
        custom = self.core.at_image_custom_get(params["mode"])
        if custom.get("local_dir") and not self.core.at_image_model_dir_ready(
            custom["local_dir"], arch=info.get("arch")
        ):
            return {"ok": False, "error": "指定的本地模型不完整或与所选模型架构不匹配，请重新选择模型。"}
        if info.get("arch") == "qwen_image_2":
            for key, label in (("text_encoder_path", "文本编码器"), ("vae_path", "VAE")):
                path = str(custom.get(key) or "").strip()
                if path and not self.core.at_image_qwen21_component_file_ready(path):
                    return {"ok": False, "error": "指定的 Qwen-Image-2.1 %s 文件已不存在或不完整：\n%s" % (label, path)}

        try:
            model_ready = bool(self.core.at_image_model_ready(params["mode"]))
        except Exception:
            model_ready = False
        try:
            vram_gb = self.core.detect_vram_gb()
        except Exception:
            vram_gb = None
        try:
            vendor = str(self.core.detect_gpu_vendor() or "unknown").lower()
        except Exception:
            vendor = "unknown"
        warnings = []
        if vendor == "amd":
            if not params["amd_mode"]:
                return {"ok": False, "error": "检测到 AMD 显卡；请先在高级参数中开启 AMD 兼容模式，再开始训练。"}
            try:
                amd_ok, _backend, amd_detail = self.core.ai_toolkit_amd_status(_vpy)
            except Exception as exc:
                amd_ok, amd_detail = False, str(exc)
            if not amd_ok:
                return {"ok": False, "error": "AI Toolkit 的 AMD ROCm 环境尚未就绪：\n%s" % amd_detail}
        else:
            try:
                has_nvidia = bool(self.core.detect_nvidia_gpu())
            except Exception:
                has_nvidia = False
            if not has_nvidia:
                warnings.append("没有检测到 NVIDIA GPU；请确认当前训练环境已配置并支持你的显卡。")
        need_vram = int(info.get("min_vram") or 16)
        if vram_gb is not None and vram_gb < need_vram:
            warnings.append("当前显存约 %.1f GB，低于模型建议的 %d GB；训练可能较慢或显存不足。" % (vram_gb, need_vram))
        if not model_ready:
            warnings.append("训练模型尚未完整保存在本机；开始后 AI Toolkit 会按需准备约 %s 的模型文件。" % (info.get("size") or "大体积"))

        resume_path = None
        try:
            output_dir = self.core.data_sub("output", project_name)
            output_name = self.core.output_name_for(params["mode"], params.get("style_preset"))
            resume_path = self.core.find_latest_state(output_dir, output_name)
        except Exception:
            resume_path = None
        return {
            "ok": True,
            "plan": {
                "project_name": project_name,
                "mode": params["mode"],
                "mode_label": self.core.MODE_LABELS.get(params["mode"], params["mode"]),
                "training_engine": "ai_toolkit",
                "model_label": info.get("label") or info.get("model_id") or "当前模型",
                "model_path": str(custom.get("local_dir") or self.core.at_image_local_dir(params["mode"])),
                "model_download_required": not model_ready,
                "model_size": str(info.get("size") or ""),
                "raw_dir": raw_dir,
                "image_count": image_count,
                "min_images": min_images,
                "training_type": params["at_sub_mode"],
                "rank": params["rank"], "alpha": params["alpha"],
                "learning_rate": params["unet_lr"],
                "resolution": params["resolution"], "steps": params["video_steps"],
                "trigger": params["trigger"],
                "gpu_vendor": vendor,
                "vram_gb": vram_gb,
                "warnings": warnings,
                "resume_path": str(resume_path or ""),
            },
        }

    def _anima_training_params(self, config, project_name):
        """Build the existing Kohya trainer's parameter shape for first-engine modes."""
        mode = str(config.get("mode") or "")
        if mode not in ("character", "style", "concept"):
            raise ValueError("Kohya 训练只支持人物、画风或概念模式。")
        base_type = str(config.get("base_type") or "sdxl")
        if base_type not in getattr(self.core, "ARCH_INFO", {}):
            raise ValueError("请选择有效的底模架构。")
        if base_type == "flux2":
            raise ValueError("FLUX.2 需使用第二训练引擎的 FLUX.2 模式。")
        stored = config.get("params") if isinstance(config.get("params"), dict) else {}
        preset = dict(self.core.preset_for(mode, base_type) or {})

        def value(key, default=None):
            candidate = stored.get(key)
            return preset.get(key, default) if candidate in (None, "") else candidate

        def integer(key, default):
            return self._training_number(value(key, default), default, int)

        def optional_integer(key):
            candidate = value(key, None)
            if candidate in (None, ""):
                return None
            try:
                parsed = int(float(candidate))
                return parsed if parsed > 0 else None
            except (TypeError, ValueError, OverflowError):
                return None

        params = {
            "mode": mode,
            "base_type": base_type,
            "at_sub_mode": str(config.get("at_sub_mode") or "character"),
            "concept_type": str(config.get("concept_type") or "form"),
            "clean_concept": bool(value("clean_concept", True)),
            "fast_tier": str(config.get("fast_tier") or "auto"),
            "trigger": str(config.get("trigger") or "").strip(),
            "strong_bind": bool(value("strong_bind", True)),
            "raw_dir": str(config.get("raw_dir") or "").strip(),
            "reg_dir": str(config.get("reg_dir") or "").strip() or None,
            "base_model": str(config.get("base_model") or "").strip() or None,
            "rank": integer("rank", 12),
            "alpha": integer("alpha", 6),
            "unet_lr": str(value("unet_lr", "3e-4")),
            "te_lr": str(value("te_lr", "1.5e-4")),
            "repeats": integer("repeats", 5),
            "max_epochs": integer("max_epochs", 8),
            "resolution": integer("resolution", 1024),
            "video_steps": integer("video_steps", 2000),
            "save_every": optional_integer("save_every"),
            "sample_interval": integer("sample_interval", 0),
            "sample_prompt": str(value("sample_prompt", "") or ""),
            "train_text_encoder": not bool(config.get("unet_only", False)),
            "style_preset": str(config.get("style_preset") or "自定义"),
            "style_caption": str(config.get("style_caption") or "").strip(),
            "crop_ratio": self.core.normalize_crop_ratio(value("crop_ratio", "")),
            "noise_offset": value("noise_offset", ""),
            "min_snr_gamma": value("min_snr_gamma", ""),
            "global_pos": str(config.get("global_pos") or "").strip(),
            "global_neg": str(config.get("global_neg") or "").strip(),
            "optimizer": str(value("optimizer", "auto") or "auto"),
            "quant_mode": str(value("quant_mode", "auto") or "auto"),
            "blocks_to_swap": value("blocks_to_swap", ""),
            "compile": bool(value("compile", False)),
            "wd14_model": str(value("wd14_model", "swinv2-v3") or "swinv2-v3"),
            "overwrite": bool(value("overwrite", False)),
            "amd_mode": bool(value("amd_mode", False)),
            "train_env": str(config.get("train_env") or "").strip() or None,
            "project": project_name,
        }
        # Keep the legacy trainer's VRAM-based default when the modern UI is in
        # "auto" mode (None is removed from the saved config). An explicit
        # on/off selection must cross this bridge unchanged.
        if stored.get("sample_preview") is not None:
            params["sample_preview"] = bool(stored.get("sample_preview"))
        return params

    def _classic_training_params(self, config, project_name):
        """Normalize an engine project's saved fields to the legacy trainer contract."""
        mode = str(config.get("mode") or "")
        if mode in ("character", "style", "concept"):
            return self._anima_training_params(config, project_name)
        if mode in ("qwen_image", "zimage"):
            return self._qwen_training_params(config, project_name)
        stored = config.get("params") if isinstance(config.get("params"), dict) else {}
        base_type = str(config.get("base_type") or "sdxl")
        preset = dict(self.core.preset_for(mode, base_type) or {})

        def value(key, default=None):
            candidate = stored.get(key)
            return preset.get(key, default) if candidate in (None, "") else candidate

        def integer(key, default):
            return self._training_number(value(key, default), default, int)

        def optional_integer(key):
            candidate = value(key, None)
            if candidate in (None, ""):
                return None
            try:
                parsed = int(float(candidate))
                return parsed if parsed > 0 else None
            except (TypeError, ValueError, OverflowError):
                return None

        params = {
            "mode": mode, "base_type": base_type,
            "at_sub_mode": str(config.get("at_sub_mode") or "character"),
            "concept_type": str(config.get("concept_type") or "form"),
            "clean_concept": bool(value("clean_concept", True)),
            "fast_tier": str(config.get("fast_tier") or "auto"),
            "trigger": str(config.get("trigger") or "").strip(),
            "strong_bind": bool(value("strong_bind", True)),
            "raw_dir": str(config.get("raw_dir") or "").strip(),
            "reg_dir": str(config.get("reg_dir") or "").strip() or None,
            "base_model": str(config.get("base_model") or "").strip() or None,
            "rank": integer("rank", 32), "alpha": integer("alpha", 32),
            "unet_lr": str(value("unet_lr", "1e-4")), "te_lr": str(value("te_lr", "1e-4")),
            "repeats": integer("repeats", 1), "max_epochs": integer("max_epochs", 16),
            "resolution": integer("resolution", 1024),
            "video_steps": integer("video_steps", 2000),
            "video_frames": integer("video_frames", getattr(self.core, "H3_FRAMES", 73)),
            "save_every": optional_integer("save_every"),
            "sample_interval": integer("sample_interval", 0),
            "sample_prompt": str(value("sample_prompt", "") or ""),
            "train_text_encoder": not bool(config.get("unet_only", False)),
            "style_preset": str(config.get("style_preset") or "自定义"),
            "style_caption": str(config.get("style_caption") or "").strip(),
            "crop_ratio": self.core.normalize_crop_ratio(value("crop_ratio", "")),
            "noise_offset": value("noise_offset", ""), "min_snr_gamma": value("min_snr_gamma", ""),
            "global_pos": str(config.get("global_pos") or "").strip(),
            "global_neg": str(config.get("global_neg") or "").strip(),
            "optimizer": str(value("optimizer", "auto") or "auto"),
            "quant_mode": str(value("quant_mode", "auto") or "auto"),
            "blocks_to_swap": value("blocks_to_swap", ""),
            "compile": bool(value("compile", False)),
            "wd14_model": str(value("wd14_model", "swinv2-v3") or "swinv2-v3"),
            "overwrite": bool(value("overwrite", False)),
            "amd_mode": bool(value("amd_mode", False)),
            "train_env": str(config.get("train_env") or "").strip() or None,
            "project": project_name,
        }
        if stored.get("sample_preview") is not None:
            params["sample_preview"] = bool(stored.get("sample_preview"))
        return params

    def _prepare_anima_training(self, project_name, config):
        """Check the existing Kohya prerequisites without launching classic UI."""
        try:
            params = self._anima_training_params(config, project_name)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        base_type = params["base_type"]
        base_label = getattr(self.core, "BASE_TYPE_LABELS", {}).get(base_type, base_type)
        if not params["base_model"] or not os.path.isfile(params["base_model"]):
            return {"ok": False, "error": "请在新版训练页选择有效的 %s 底模文件（.safetensors 或 .ckpt）。" % base_label}
        if not params["base_model"].lower().endswith((".safetensors", ".ckpt")):
            return {"ok": False, "error": "%s 底模需为 .safetensors 或 .ckpt 文件。" % base_label}
        if not params["raw_dir"] or not os.path.isdir(params["raw_dir"]):
            return {"ok": False, "error": "请先在新版训练页选择有效的原始图片文件夹。"}
        try:
            detected_type = str(self.core.detect_base_type(params["base_model"]) or "")
        except Exception:
            detected_type = ""
        if detected_type and detected_type != base_type:
            label = getattr(self.core, "BASE_TYPE_LABELS", {}).get(detected_type, detected_type)
            return {"ok": False, "error": "选中的底模识别为 %s，与当前 %s 架构不匹配。请更换底模或切换架构。" % (label, base_label)}
        try:
            image_count = self._count_preprocessable_images(params["raw_dir"])
        except Exception as exc:
            return {"ok": False, "error": "无法读取图集：%s" % exc}
        min_images = int(getattr(self.core, "MIN_IMAGES", {}).get(params["mode"], 15))
        if image_count < min_images:
            return {"ok": False, "error": "图集只有 %d 张图片；%s 至少需要 %d 张。" % (
                image_count, self.core.MODE_LABELS.get(params["mode"], params["mode"]), min_images
            )}
        try:
            learning_rate = float(params["unet_lr"])
        except (TypeError, ValueError):
            return {"ok": False, "error": "学习率不是有效数字，请检查后再开始训练。"}
        if not (learning_rate > 0 and learning_rate < float("inf")):
            return {"ok": False, "error": "学习率必须是大于 0 的有限数值。"}

        try:
            system = self.core.system_status()
        except Exception as exc:
            return {"ok": False, "error": "无法读取 Kohya 环境状态：%s" % exc}
        if not system.get("kohya_ok"):
            return {"ok": False, "error": "第一引擎 Kohya 尚未就绪，请先完成左侧「安装训练内核」。"}
        try:
            kdir = str(system.get("kohya_dir") or self.core.get_kohya_dir())
            train_script = self.core.ARCH_INFO[base_type]["script"]
            if not os.path.isfile(os.path.join(kdir, "sd-scripts", train_script)):
                return {"ok": False, "error": "当前 Kohya 安装缺少 %s 训练脚本「%s」，请先更新或重新安装第一引擎。" % (base_label, train_script)}
        except (KeyError, TypeError, AttributeError):
            pass

        warnings = []
        try:
            vendor = str(self.core.detect_gpu_vendor() or "unknown").lower()
        except Exception:
            vendor = "unknown"
        try:
            vram_gb = self.core.detect_vram_gb()
        except Exception:
            vram_gb = None
        if vendor == "amd":
            if not params["amd_mode"]:
                return {"ok": False, "error": "检测到 AMD 显卡；请在新版训练页开启「AMD 兼容模式」，保存后再开始训练。"}
            try:
                vpy = self.core.venv_python(self.core.get_kohya_dir())
                if params["train_env"]:
                    custom_python = os.path.join(params["train_env"], "Scripts", "python.exe")
                    if os.path.isfile(custom_python):
                        vpy = custom_python
                amd_ok, _backend, amd_detail = self.core.amd_env_status(vpy)
            except Exception as exc:
                amd_ok, amd_detail = False, str(exc)
            if not amd_ok:
                return {"ok": False, "error": "第一引擎 AMD 训练环境尚未就绪：\n%s" % amd_detail}
            warnings.append("AMD 训练通道为实验性兼容模式；本机实测结果取决于显卡、ROCm / ZLUDA 和驱动版本。")
        else:
            try:
                has_nvidia = bool(self.core.detect_nvidia_gpu())
            except Exception:
                has_nvidia = False
            if not has_nvidia:
                warnings.append("没有检测到 NVIDIA GPU；请确认训练环境支持当前显卡。")
        if vram_gb is not None:
            try:
                need_vram = int(self.core.ARCH_INFO.get(base_type, {}).get("recommend_vram") or 12)
            except Exception:
                need_vram = 12
            if vram_gb < need_vram:
                warning = "当前显存约 %.1f GB，低于 %s 建议的 %d GB；训练可能较慢或显存不足。" % (vram_gb, base_label, need_vram)
                if base_type == "anima":
                    swap_blocks = 16 if vram_gb < 12 else 8
                    warning = "当前显存约 %.1f GB，低于 Anima 建议的 %d GB；Kohya 会自动设置 blocks_to_swap=%d 省显存，速度可能较慢，仍有显存不足的风险。" % (vram_gb, need_vram, swap_blocks)
                warnings.append(warning)

        if base_type == "anima":
            try:
                components = self.core.anima_component_status()
            except Exception:
                components = {}
            missing_components = [label for key, label in (("qwen3", "Qwen3 文本编码器"), ("vae", "Qwen-Image VAE"))
                                 if not (components.get(key) or {}).get("path")]
            if missing_components:
                warnings.append("本机未找到%s；训练引擎会自动准备这些组件，约需下载 1.5GB。" % "、".join(missing_components))
            try:
                from kohya_core import anima_ckpt
                if anima_ckpt.checkpoint_kind(params["base_model"]) == "merged":
                    warnings.append("检测到推理用合并版 Anima 模型；训练时会自动剥离并缓存纯 DiT，首次需要额外等待 1–3 分钟。")
            except Exception:
                pass

        try:
            output_dir = self.core.data_sub("output", project_name)
            output_name = self.core.output_name_for(params["mode"], params.get("style_preset"))
            resume_path = self.core.find_latest_state(output_dir, output_name)
        except Exception:
            resume_path = None
        model_label = os.path.basename(params["base_model"]) or base_label
        training_type = {"character": "人物", "style": "画风", "concept": "概念"}[params["mode"]]
        target = "仅训练 DiT；Anima 的 Qwen3 文本编码器固定冻结" if base_type == "anima" else (
            "仅训练 U-Net / DiT，不训练文本编码器" if not params["train_text_encoder"] else "按当前参数训练模型与文本编码器")
        return {
            "ok": True,
            "plan": {
                "project_name": project_name,
                "mode": params["mode"],
                "mode_label": self.core.MODE_LABELS.get(params["mode"], params["mode"]),
                "training_engine": "kohya",
                "engine_label": "Kohya / sd-scripts · %s" % base_label,
                "model_label": model_label,
                "model_path": params["base_model"],
                "model_download_required": False,
                "model_size": "",
                "raw_dir": params["raw_dir"],
                "image_count": image_count,
                "min_images": min_images,
                "training_type": training_type,
                "training_target": target,
                "schedule_label": "训练计划",
                "schedule_value": "%d 轮 · 每张图重复 %d 次" % (params["max_epochs"], params["repeats"]),
                "rank": params["rank"], "alpha": params["alpha"],
                "learning_rate": str(params["unet_lr"]),
                "resolution": params["resolution"], "steps": 0,
                "trigger": params["trigger"],
                "gpu_vendor": vendor,
                "vram_gb": vram_gb,
                "warnings": warnings,
                "resume_path": str(resume_path or ""),
            },
        }

    def start_training(self, project_name, use_resume=False):
        """Run an existing engine pipeline without opening the classic Tk workspace."""
        project_name = str(project_name or "").strip()
        preflight = self.prepare_training(project_name)
        if not preflight.get("ok"):
            return preflight
        plan = preflight["plan"]
        resume_path = plan.get("resume_path") if use_resume else None
        if use_resume and not resume_path:
            return {"ok": False, "error": "没有找到可续训的快照，请重新检查项目输出目录。"}
        config = self.core.load_project(project_name)
        try:
            params = self._classic_training_params(config, project_name)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        task_id = self._begin_task("%s 训练" % plan["mode_label"], "training", mode=plan["mode"])
        if not task_id:
            return {"ok": False, "error": "已有环境、模型或训练任务正在运行，请等它完成后再试。"}
        review_event = threading.Event()
        with self._task_lock:
            if self._task and self._task.get("id") == task_id:
                self._task["review_event"] = review_event
        self.core.reset_stop()

        def worker():
            import json
            import tempfile

            report_path = os.path.join(tempfile.gettempdir(), "kohya_modern_preprocess_%s.json" % task_id)
            monitor = None
            monitor_stop = threading.Event()
            monitor_thread = None
            try:
                self._task_log(task_id, "[预处理] 自动检查、整理并打标当前图集…")
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task.update(message="正在预处理图片与标签…", detail="预处理阶段")
                if params["mode"] == "video":
                    videos, duration, no_caption = self.core.scan_video_dataset(params["raw_dir"])
                    if no_caption == len(videos):
                        raise RuntimeError("所有视频都没有同名 .txt 字幕，不能开始训练。")
                    processed_count = len(videos) - no_caption
                    self._task_log(task_id, "[预处理] 视频无需图片预处理；数据集 %d 段，约 %.1f 秒，%d 段缺少字幕。" % (
                        len(videos), duration, no_caption))
                else:
                    is_kohya = params["mode"] in ("character", "style", "concept")
                    preprocess_mode = self.core.preprocess_mode(params["mode"], params["at_sub_mode"])
                    preprocess_args = {
                        "input_dir": params["raw_dir"], "size": params["resolution"],
                        "mode": preprocess_mode, "trigger": params["trigger"],
                        "reg_dir": params["reg_dir"], "repeats": params["repeats"],
                        "dedup": True, "wd14": True, "square_crop": False,
                        "crop_ratio": params["crop_ratio"], "wd14_model": params["wd14_model"],
                        "min_size": 256, "blur_threshold": 30.0, "report": report_path,
                        "keep_tokens": None, "project": project_name,
                        "style_caption": params["style_caption"],
                        "dataset_mode": None if is_kohya and params["base_type"] == "anima" and params["mode"] == "style" else "character",
                        "strong_bind": params["strong_bind"], "concept_type": params["concept_type"],
                        "clean_concept": params["clean_concept"],
                        "concept_mode": self.core.is_concept_mode(params["mode"], params["at_sub_mode"]),
                        "style_target": self.core.style_target_code(params["style_preset"]),
                        "overwrite": params["overwrite"],
                    }
                    self.core.preprocess(lambda line: self._task_log(task_id, line), **preprocess_args)
                    stats = {}
                    if os.path.isfile(report_path):
                        try:
                            with open(report_path, "r", encoding="utf-8") as handle:
                                stats = json.load(handle)
                        except Exception:
                            stats = {}
                    processed_count = int(stats.get("ok", 0) or 0) + int(stats.get("skipped_existing", 0) or 0)
                    if processed_count <= 0:
                        processed_count = int(self.core.count_images(self.core.dataset_train_dir(params["mode"], project_name)))
                if processed_count < plan["min_images"]:
                    label = "可用视频" if params["mode"] == "video" else "可用图片"
                    raise RuntimeError("预处理后只有 %d 个%s；%s 至少需要 %d。" % (
                        processed_count, label, plan["mode_label"], plan["min_images"]))
                engine_name = plan.get("engine_label") or self._engine_label_for_mode(params["mode"])
                review_message = ("视频字幕检查完成；确认后启动 %s。" % engine_name if params["mode"] == "video"
                                  else "可以打开标签编辑器查看或修改标签；确认后才会启动 %s。" % engine_name)
                self._task_log(task_id, "[预处理] 已完成，可用数据 %d 个。请检查数据后确认是否继续训练。" % processed_count)
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task.update(
                            status="awaiting_review",
                            message="预处理已完成，请检查图片和标签。",
                            progress=None,
                            detail=review_message,
                        )
                while not review_event.wait(0.1):
                    with self._task_lock:
                        if not self._task or self._task.get("id") != task_id or self._task.get("status") != "awaiting_review":
                            return
                with self._task_lock:
                    if not self._task or self._task.get("id") != task_id or self._task.get("status") != "running":
                        return
                self._task_log(task_id, "[训练] 正在启动 %s…" % engine_name)
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task.update(message="正在启动训练引擎…", progress=None, detail="模型加载可能需要几分钟")

                monitor = self.core.TrainMonitor()

                def monitor_worker():
                    while not monitor_stop.wait(0.8):
                        snapshot = monitor.snapshot()
                        total = int(snapshot.get("total") or 0)
                        step = int(snapshot.get("step") or 0)
                        speed = float(snapshot.get("speed") or 0)
                        loss = snapshot.get("loss")
                        detail = ("Step %d / %d" % (step, total)) if total else (snapshot.get("phase_label") or "正在加载 / 缓存模型")
                        if speed > 0:
                            detail += " · %.2f step/s" % speed
                        if loss is not None:
                            detail += " · loss %s" % loss
                        with self._task_lock:
                            if self._task and self._task.get("id") == task_id and self._task.get("status") == "running":
                                self._task.update(
                                    message="训练中 · " + detail,
                                    progress=(min(1.0, max(0.0, step / total)) if total else None),
                                    detail=detail,
                                )

                monitor_thread = threading.Thread(target=monitor_worker, name="ModernTrainProgress", daemon=True)
                monitor_thread.start()
                mode = params["mode"]
                if mode in ("character", "style", "concept"):
                    self.core.train(
                        lambda line: self._task_log(task_id, line), base_model=params["base_model"],
                        mode=params["mode"], params=params, vram_gb=plan.get("vram_gb"),
                        resume_from=resume_path, progress=monitor,
                    )
                elif mode in ("qwen_image", "zimage"):
                    self.core.train_at_image(
                        lambda line: self._task_log(task_id, line), mode=params["mode"], params=params,
                        vram_gb=plan.get("vram_gb"), resume_from=resume_path, progress=monitor,
                    )
                elif mode == "video":
                    self.core.train_video(
                        lambda line: self._task_log(task_id, line), mode=mode, params=params,
                        vram_gb=plan.get("vram_gb"), resume_from=resume_path, progress=monitor,
                    )
                elif mode == "krea2":
                    self.core.train_krea2(
                        lambda line: self._task_log(task_id, line), mode=mode, params=params,
                        vram_gb=plan.get("vram_gb"), resume_from=resume_path, progress=monitor,
                    )
                elif mode == "flux2":
                    self.core.train_flux2(
                        lambda line: self._task_log(task_id, line), mode=mode, params=params,
                        vram_gb=plan.get("vram_gb"), resume_from=resume_path, progress=monitor,
                    )
                elif mode == "krea2_at":
                    self.core.train_krea2_at(
                        lambda line: self._task_log(task_id, line), mode=mode, params=params,
                        vram_gb=plan.get("vram_gb"), resume_from=resume_path, progress=monitor,
                    )
                elif mode == "krea2_fz":
                    self.core.train_krea2_fizgig(
                        lambda line: self._task_log(task_id, line), mode=mode, params=params,
                        vram_gb=plan.get("vram_gb"), resume_from=resume_path, progress=monitor,
                    )
                elif mode == "flux2_fz":
                    self.core.train_flux2_fizgig(
                        lambda line: self._task_log(task_id, line), mode=mode, params=params,
                        vram_gb=plan.get("vram_gb"), resume_from=resume_path, progress=monitor,
                    )
                else:
                    raise RuntimeError("新版训练页尚未注册「%s」训练模式。" % mode)
                try:
                    self.core.export_project_named_lora(
                        params.get("mode"), project_name,
                        logf=lambda line: self._task_log(task_id, line),
                        prefer_prefix=params.get("output_name") or self.core.output_name_for(
                            params.get("mode"), params.get("style_preset")
                        ),
                    )
                except Exception as exc:
                    self._task_log(task_id, "[导出] 按项目名导出成品失败（忽略）：%s" % exc)
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task.update(status="completed", message="训练完成。", progress=1.0, detail="模型已保存到项目 output 文件夹")
                self._task_log(task_id, "[完成] 训练结束；模型已保存到项目 output 文件夹。")
            except getattr(self.core, "StopRequested", Exception) as exc:
                try:
                    latest = self.core.find_latest_state(
                        self.core.data_sub("output", project_name),
                        self.core.output_name_for(params.get("mode"), params.get("style_preset")),
                    )
                except Exception:
                    latest = None
                message = "训练已停止。" if latest else "训练已停止；本次没有可续训快照。"
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task.update(status="cancelled", message=message)
                self._task_log(task_id, "[停止] %s%s" % (message, " " + os.path.basename(latest) if latest else ""))
            except Exception as exc:
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task.update(status="failed", message="训练失败：%s" % exc)
                self._task_log(task_id, "[失败] %s" % exc)
            finally:
                monitor_stop.set()
                if monitor is not None:
                    try:
                        monitor.finish()
                    except Exception:
                        pass
                if monitor_thread is not None:
                    monitor_thread.join(timeout=1)
                try:
                    if os.path.isfile(report_path):
                        os.remove(report_path)
                except OSError:
                    pass

        threading.Thread(target=worker, name="ModernTraining", daemon=True).start()
        self._log("[训练] 已从新版训练页启动「%s」项目。" % project_name)
        return {"ok": True, "task_id": task_id}

    def get_env_locations(self):
        configured = self.core.get_env_paths()
        python, version = self.core.find_python()
        git = self.core.find_git() or ""
        return {
            "ok": True,
            "configured": configured,
            "python": {"path": python or "", "version": version or "", "custom": bool(configured.get("python_exe") or configured.get("python_dir"))},
            "git": {"path": git, "custom": bool(configured.get("git_exe"))},
        }

    def set_env_location(self, kind, directory):
        kind = str(kind or "")
        directory = str(directory or "").strip()
        if kind not in ("python", "git") or not directory or not os.path.isdir(directory):
            return {"ok": False, "error": "请选择有效的文件夹。"}
        if kind == "python":
            candidates = self.core.scan_python_dir(directory)
            valid = [item for item in candidates if len(item) > 3 and item[1]]
            if not valid:
                why = candidates[0][3] if candidates else "这个文件夹里没有找到 python.exe"
                return {"ok": False, "error": "该文件夹里的 Python 不能创建训练环境，设置未更改。\n\n原因：%s" % why}
            executable, _ok, version, _why = valid[0]
            if not self.core.set_env_paths(python_dir=directory, python_exe=executable):
                return {"ok": False, "error": "保存 Python 路径失败。"}
            self._log("[环境] 已改用指定 Python %s：%s" % (version, executable))
        else:
            candidates = self.core.scan_git_dir(directory)
            valid = [item for item in candidates if len(item) > 2 and item[1]]
            if not valid:
                return {"ok": False, "error": "该文件夹里没有找到可用的 git.exe，设置未更改。"}
            executable, _ok, version = valid[0]
            if not self.core.set_env_paths(git_exe=executable):
                return {"ok": False, "error": "保存 Git 路径失败。"}
            self._log("[环境] 已改用指定 Git：%s（%s）" % (executable, version))
        return self.get_env_locations()

    def reset_env_locations(self):
        if not self.core.clear_env_paths():
            return {"ok": False, "error": "恢复自动检测失败。"}
        self._log("[环境] 已恢复自动查找 Python / Git。")
        return self.get_env_locations()

    def bootstrap(self):
        labels = getattr(self.core, "MODE_LABELS", {})
        templates = getattr(self.core, "PROJECT_TEMPLATES", {})
        public_templates = [
            {
                "name": name,
                "mode": template.get("mode", "style"),
                "mode_label": labels.get(template.get("mode", "style"), "画风"),
                "base_type": template.get("base_type", ""),
                "note": template.get("note", ""),
            }
            for name, template in templates.items()
        ]
        if not any(item["mode"] == "qwen_image" for item in public_templates):
            public_templates.append({
                "name": "Qwen-Image",
                "mode": "qwen_image",
                "mode_label": labels.get("qwen_image", "Qwen-Image"),
                "note": "创建 Qwen-Image 项目；模型选择、参数配置和训练均在新版训练页完成。",
            })
        existing_template_names = {item["name"] for item in public_templates}
        for name, template in _MODERN_PROJECT_TEMPLATES.items():
            if name in existing_template_names:
                continue
            mode = template["mode"]
            public_templates.append({
                "name": name,
                "mode": mode,
                "mode_label": self._plain_mode_label(labels.get(mode, mode)),
                "base_type": template["base_type"],
                "note": template["note"],
            })
        return {
            "schema_version": 1,
            "app_name": getattr(self.core, "APP_NAME", "Kohya-LoRA"),
            "version": getattr(self.core, "APP_VERSION", "0.0.0"),
            "default_project_name": self.core.default_project_name(),
            "modes": [{"key": key, "label": value} for key, value in labels.items()],
            "templates": public_templates,
            "engine_groups": [
                {
                    "label": name,
                    "modes": [{"key": key, "label": self.short_mode_labels.get(key, key)} for key in modes],
                }
                for name, modes in self.engine_groups
            ],
            "logs": list(self.logs),
            "projects": self.list_projects(),
        }

    def list_projects(self):
        labels = getattr(self.core, "MODE_LABELS", {})
        base_labels = getattr(self.core, "BASE_TYPE_LABELS", {})
        projects = []
        for item in self.core.list_projects():
            mode = item.get("mode", "style")
            projects.append({
                "name": str(item.get("name", "")),
                "updated": str(item.get("updated", "")),
                "mode": mode,
                "mode_label": self._plain_mode_label(labels.get(mode, mode)),
                "base_type": str(item.get("base_type", "")),
                "base_type_label": base_labels.get(item.get("base_type", ""), str(item.get("base_type", ""))),
                "raw_dir": str(item.get("raw_dir", "")),
                "base_model": str(item.get("base_model", "")),
            })
        return projects

    def load_project_config(self, name):
        name = str(name or "").strip()
        if not name:
            return {"ok": False, "error": "项目名称为空。"}
        config = self.core.load_project(name)
        if not isinstance(config, dict):
            return {"ok": False, "error": "项目不存在或配置文件已损坏。"}
        return {"ok": True, "config": config}

    def save_project_config(self, name, patch):
        """Merge fields supported by the modern training workspaces into a project."""
        name = str(name or "").strip()
        if not name or not isinstance(patch, dict):
            return {"ok": False, "error": "项目名称或配置内容无效。"}
        config = self.core.load_project(name)
        if not isinstance(config, dict):
            return {"ok": False, "error": "项目不存在或配置文件已损坏。"}

        root_string_fields = {
            "mode", "base_type", "base_model", "raw_dir", "trigger", "reg_dir",
            "style_preset", "style_caption", "at_sub_mode", "concept_type", "fast_tier",
            "global_pos", "global_neg", "train_env",
        }
        root_bool_fields = {"unet_only"}
        param_fields = {
            "rank", "alpha", "unet_lr", "te_lr", "repeats", "max_epochs", "resolution",
            "save_every", "sample_interval", "video_steps", "video_frames", "optimizer",
            "strong_bind", "clean_concept", "sample_preview", "compile", "crop_ratio",
            "sample_prompt", "noise_offset", "min_snr_gamma", "quant_mode", "blocks_to_swap",
            "wd14_model", "overwrite", "amd_mode",
        }
        allowed_root_fields = root_string_fields | root_bool_fields | {"params"}
        unknown_root_fields = set(patch) - allowed_root_fields
        if unknown_root_fields:
            return {"ok": False, "error": "未知的项目配置字段：%s" % ", ".join(sorted(unknown_root_fields))}
        next_mode = patch.get("mode", config.get("mode", "style"))
        if "mode" in patch and next_mode not in getattr(self.core, "MODE_KEYS", ()):
            return {"ok": False, "error": "训练模式无效。"}
        if "base_type" in patch and next_mode in ("style", "character", "concept"):
            if patch["base_type"] not in ("sd15", "sdxl", "flux", "anima"):
                return {"ok": False, "error": "第一引擎底模类型无效。"}
        for key in root_string_fields:
            if key not in patch:
                continue
            value = patch[key]
            if not isinstance(value, str) or len(value) > 32768:
                return {"ok": False, "error": "字段「%s」的格式无效。" % key}
            config[key] = value
        for key in root_bool_fields:
            if key not in patch:
                continue
            value = patch[key]
            if not isinstance(value, bool):
                return {"ok": False, "error": "字段「%s」必须为开关值。" % key}
            config[key] = value

        params = config.get("params")
        if not isinstance(params, dict):
            params = {}
        incoming_params = patch.get("params", {})
        if not isinstance(incoming_params, dict):
            return {"ok": False, "error": "训练参数格式无效。"}
        for key, value in incoming_params.items():
            if key not in param_fields:
                return {"ok": False, "error": "新版训练页尚未接入训练参数「%s」。" % key}
            if key == "sample_preview" and value is None:
                params.pop(key, None)
                continue
            if key in {"strong_bind", "clean_concept", "sample_preview", "compile", "overwrite", "amd_mode"}:
                if not isinstance(value, bool):
                    return {"ok": False, "error": "训练参数「%s」必须为开关值。" % key}
            elif not isinstance(value, (str, int, float)) or len(str(value)) > 128:
                return {"ok": False, "error": "训练参数「%s」的格式无效。" % key}
            params[key] = value
        config["params"] = params

        if not self.core.save_project(name, config):
            return {"ok": False, "error": "项目保存失败，请检查磁盘空间和写入权限。"}
        self._log("[项目] 已保存「%s」的训练配置。" % name)
        return {"ok": True, "project": next((p for p in self.list_projects() if p["name"] == name), None)}

    def choose_path(self, kind="folder"):
        if self._window is None:
            return {"ok": False, "error": "文件选择器尚未就绪。"}
        try:
            import webview

            if kind == "image":
                selected = self._window.create_file_dialog(
                    webview.FileDialog.OPEN,
                    file_types=("Image files (*.png;*.jpg;*.jpeg;*.webp;*.bmp)",),
                )
            elif kind == "model":
                selected = self._window.create_file_dialog(
                    webview.FileDialog.OPEN,
                    file_types=("Model files (*.safetensors;*.ckpt;*.pt;*.pth)", "All files (*.*)"),
                )
            else:
                selected = self._window.create_file_dialog(webview.FileDialog.FOLDER)
            if not selected:
                return {"ok": True, "cancelled": True, "path": ""}
            path = selected[0] if isinstance(selected, (list, tuple)) else selected
            return {"ok": True, "path": str(path or "")}
        except Exception as exc:
            return {"ok": False, "error": "无法打开文件选择器：%s" % exc}

    @staticmethod
    def _appearance_settings_from_core(core):
        settings = core._load_app_settings() or {}
        if not isinstance(settings, dict):
            settings = {}
        theme = str(settings.get("modern_ui_theme") or "dark")
        if theme not in ("dark", "light", "system"):
            theme = "dark"
        background = str(settings.get("modern_ui_background") or "").strip()
        if background:
            # Keep missing paths so removable drives can be reconnected later.
            background = os.path.abspath(background)
        opacity = settings.get("modern_ui_background_opacity", 18)
        try:
            opacity = max(0, min(100, int(opacity)))
        except (TypeError, ValueError):
            opacity = 18
        component_opacity = settings.get("modern_ui_component_opacity", 100)
        try:
            component_opacity = max(0, min(100, int(component_opacity)))
        except (TypeError, ValueError):
            component_opacity = 100
        idle_fade_enabled = settings.get("modern_ui_idle_fade_enabled", False)
        background_history = settings.get("modern_ui_background_history", [])
        history_paths = ModernUIBridge._normalize_appearance_background_history(background_history, background)
        return {
            "theme": theme,
            "background_path": background,
            "background_opacity": opacity,
            "background_available": bool(background and os.path.isfile(background)),
            "background_history": [
                {"path": path, "available": os.path.isfile(path)} for path in history_paths
            ],
            "component_opacity": component_opacity,
            "idle_fade_enabled": bool(idle_fade_enabled),
        }

    @staticmethod
    def _normalize_appearance_background_history(paths, selected=""):
        if not isinstance(paths, (list, tuple)):
            paths = []
        normalized = []
        seen = set()
        for raw_path in ([selected] if selected else []) + list(paths):
            if not isinstance(raw_path, (str, os.PathLike)):
                continue
            path = str(raw_path).strip()
            if not path:
                continue
            path = os.path.abspath(path)
            key = os.path.normcase(path)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(path)
            if len(normalized) >= _APPEARANCE_BACKGROUND_HISTORY_LIMIT:
                break
        return normalized

    def get_appearance_settings(self):
        return {"ok": True, "settings": self._appearance_settings_from_core(self.core)}

    def set_appearance_settings(
        self,
        theme="dark",
        background_path="",
        background_opacity=18,
        component_opacity=None,
        idle_fade_enabled=None,
        background_history=None,
    ):
        theme = str(theme or "dark")
        if theme not in ("dark", "light", "system"):
            return {"ok": False, "error": "颜色主题选项无效。"}
        background_path = str(background_path or "").strip()
        if background_path:
            background_path = os.path.abspath(background_path)
            if not os.path.isfile(background_path):
                return {"ok": False, "error": "背景图片文件不存在，请重新选择。"}
            if os.path.splitext(background_path)[1].lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                return {"ok": False, "error": "背景图片需为 PNG、JPG、WebP 或 BMP 格式。"}
            try:
                if os.path.getsize(background_path) > 8 * 1024 * 1024:
                    return {"ok": False, "error": "背景图片不能超过 8 MB。"}
            except OSError:
                return {"ok": False, "error": "无法读取背景图片，请检查文件权限。"}
        try:
            opacity = max(0, min(100, int(background_opacity)))
        except (TypeError, ValueError):
            return {"ok": False, "error": "背景图片显现程度无效。"}
        current_settings = self.core._load_app_settings() or {}
        current_settings = current_settings if isinstance(current_settings, dict) else {}
        settings = dict(current_settings) if isinstance(current_settings, dict) else {}
        if component_opacity is None:
            component_opacity = current_settings.get("modern_ui_component_opacity", 100)
        try:
            component_opacity = max(0, min(100, int(component_opacity)))
        except (TypeError, ValueError):
            return {"ok": False, "error": "界面组件透明度无效。"}
        if idle_fade_enabled is None:
            idle_fade_enabled = current_settings.get("modern_ui_idle_fade_enabled", False)
        if background_history is None:
            background_history = current_settings.get("modern_ui_background_history", [])
        history_paths = self._normalize_appearance_background_history(background_history, background_path)
        settings["modern_ui_theme"] = theme
        settings["modern_ui_background"] = background_path
        settings["modern_ui_background_opacity"] = opacity
        settings["modern_ui_component_opacity"] = component_opacity
        settings["modern_ui_idle_fade_enabled"] = bool(idle_fade_enabled)
        settings["modern_ui_background_history"] = history_paths
        if not self.core._save_app_settings(settings):
            return {"ok": False, "error": "设置保存失败，请检查用户设置目录的写入权限。"}
        self._log("[外观] 已保存新版训练页显示设置。")
        return {"ok": True, "settings": self._appearance_settings_from_core(self.core)}

    def get_appearance_background(self):
        import base64
        path = self._appearance_settings_from_core(self.core).get("background_path", "")
        if not path or not os.path.isfile(path):
            return {"ok": False, "error": "背景图片文件不存在，请在外观设置中重新选择。"}
        try:
            with open(path, "rb") as handle:
                content = handle.read(8 * 1024 * 1024 + 1)
            if len(content) > 8 * 1024 * 1024:
                return {"ok": False, "error": "背景图片超过 8 MB，无法载入。"}
            mime = {
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".bmp": "image/bmp",
            }.get(os.path.splitext(path)[1].lower())
            if not mime:
                return {"ok": False, "error": "背景图片格式不支持。"}
            data_url = "data:%s;base64,%s" % (mime, base64.b64encode(content).decode("ascii"))
            return {"ok": True, "data_url": data_url}
        except OSError as exc:
            return {"ok": False, "error": "读取背景图片失败：%s" % exc}

    def inspect_base_model(self, path):
        path = str(path or "").strip()
        if not path or not os.path.isfile(path):
            return {"ok": False, "error": "请选择有效的底模文件。"}
        if not path.lower().endswith((".safetensors", ".ckpt")):
            return {"ok": False, "error": "底模文件需为 .safetensors 或 .ckpt 格式。"}
        try:
            base_type = self.core.detect_base_type(path)
        except Exception:
            base_type = ""
        return {"ok": True, "base_type": str(base_type or "")}

    def get_qwen_model_setup(self, mode="qwen_image"):
        mode = str(mode or "qwen_image")
        if mode not in ("qwen_image", "zimage"):
            return {"ok": False, "error": "该 AI Toolkit 模型模式暂不支持新版训练页设置。"}
        choices = self.core.at_image_model_choices(mode)
        custom = self.core.at_image_custom_get(mode)
        info = self.core.at_image_info(mode)
        if custom.get("local_dir"):
            selected = next((item for item in choices if item.get("arch") == custom.get("arch")), None)
            source = "local"
        elif custom.get("model_id"):
            selected = next((item for item in choices if item.get("model_id") == custom.get("model_id")), None)
            source = "download"
        else:
            selected = next((item for item in choices if item.get("default")), choices[0] if choices else None)
            source = "download"
        selected = selected or (choices[0] if choices else {})
        auto_components = {}
        local_dir = custom.get("local_dir") or ""
        if local_dir and custom.get("arch") == "qwen_image_2" and os.path.isfile(local_dir):
            try:
                auto_components = self.core.at_image_qwen21_local_components(local_dir)
            except Exception:
                auto_components = {}
        public_choices = [{
            key: item.get(key) for key in (
                "key", "label", "model_id", "arch", "size", "hint", "min_vram",
                "rec_vram", "resident_vram", "default",
            )
        } for item in choices]
        return {
            "ok": True,
            "choices": public_choices,
            "settings": custom,
            "active": {key: info.get(key) for key in ("model_id", "arch", "label", "size", "hint")},
            "selected_key": selected.get("key", ""),
            "source": source,
            "auto_components": auto_components,
            "gpu_vendor": self.core.detect_gpu_vendor() or "unknown",
        }

    def save_qwen_model_setup(self, selection):
        if not isinstance(selection, dict):
            return {"ok": False, "error": "模型设置格式无效。"}
        mode = str(selection.get("mode") or "qwen_image")
        if mode not in ("qwen_image", "zimage"):
            return {"ok": False, "error": "该 AI Toolkit 模型模式暂不支持新版训练页设置。"}
        choices = self.core.at_image_model_choices(mode)
        key = str(selection.get("key") or "")
        choice = next((item for item in choices if item.get("key") == key), None)
        if not choice:
            return {"ok": False, "error": "请选择列表中的训练模型。"}
        source = str(selection.get("source") or "download")
        if source not in ("local", "download"):
            return {"ok": False, "error": "模型来源无效。"}

        if source == "local":
            path = str(selection.get("local_dir") or "").strip()
            arch = choice.get("arch") or ""
            if not path or not self.core.at_image_model_dir_ready(path, arch=arch):
                extra = "或有效的 Qwen-Image-2.1 safetensors 权重文件" if arch == "qwen_image_2" else "完整的 Diffusers 模型目录"
                return {"ok": False, "error": "请选择%s。" % extra}
            settings = {
                "local_dir": path,
                "model_id": choice.get("model_id"),
                "arch": arch,
                "label": (choice.get("label") or "本地模型") + "（本地）",
                "size": choice.get("size"), "hint": choice.get("hint"),
                "min_vram": choice.get("min_vram"), "rec_vram": choice.get("rec_vram"),
                "resident_vram": choice.get("resident_vram"),
            }
            if arch == "qwen_image_2" and os.path.isfile(path):
                for key_name, label in (("text_encoder_path", "文本编码器"), ("vae_path", "VAE")):
                    component_path = str(selection.get(key_name) or "").strip()
                    if component_path and not self.core.at_image_qwen21_component_file_ready(component_path):
                        return {"ok": False, "error": "%s路径不是有效的 safetensors 文件（需大于 1 MB）：%s" % (label, component_path)}
                    if component_path:
                        settings[key_name] = component_path
        elif choice.get("default"):
            settings = {}
        else:
            settings = {key_name: choice.get(key_name) for key_name in (
                "model_id", "arch", "label", "size", "hint", "min_vram", "rec_vram", "resident_vram",
            ) if choice.get(key_name) not in (None, "")}

        if not self.core.at_image_custom_set(mode, settings):
            return {"ok": False, "error": "保存模型设置失败。"}
        self._log("[模型] 已保存 %s 模型设置：%s" % (mode, choice.get("model_id") or choice.get("label", key)))
        return self.get_qwen_model_setup(mode)

    def get_mode_workspace(self, mode, project_name=""):
        """Return UI metadata and read-only readiness checks for a classic training mode."""
        mode = str(mode or "")
        if mode not in getattr(self.core, "MODE_KEYS", ()):
            return {"ok": False, "error": "未知的训练模式。"}
        core = self.core
        status = core.system_status()
        engine_key = {
            "style": "kohya_ok", "character": "kohya_ok", "concept": "kohya_ok",
            "krea2": "musubi_ok", "flux2": "musubi_ok",
            "video": "at_ok", "krea2_at": "at_ok", "qwen_image": "at_ok", "zimage": "at_ok",
            "krea2_fz": "fizgig_ok", "flux2_fz": "fizgig_ok",
        }.get(mode)
        engine_ready = bool(status.get(engine_key)) if engine_key else False
        engine_update_available = False
        if mode in ("video", "krea2_at", "qwen_image", "zimage"):
            try:
                engine_update_available = bool(core.ai_toolkit_engine_update_status().get("update_available"))
            except Exception:
                engine_update_available = False
        missing = []
        asset_dir = ""
        try:
            if mode in ("krea2", "krea2_fz"):
                missing = list(core.krea2_missing_models())
                asset_dir = core.krea2_models_dir()
            elif mode == "krea2_at":
                missing = list(core.krea2_at_missing_models())
                asset_dir = core.krea2_at_models_dir()
            elif mode == "flux2":
                missing = list(core.flux2_missing_models())
                asset_dir = core.flux2_models_dir()
            elif mode == "flux2_fz":
                missing = list(core.flux2_fz_missing_models())
                asset_dir = core.flux2_models_dir()
            elif mode == "video":
                missing = list(core.h3_missing_models())
                asset_dir = core.h3_models_dir()
            elif mode in ("qwen_image", "zimage"):
                if not core.at_image_model_ready(mode):
                    missing = ["训练模型尚未准备（可选择已有本地模型或按需下载）"]
                asset_dir = core.at_image_local_dir(mode)
        except Exception as exc:
            missing = ["无法读取模型状态：%s" % exc]
        supports = {
            key: bool(core.param_supports(key, mode))
            for key in _WORKSPACE_PARAM_KEYS
        }
        try:
            preset = dict(core.preset_for(mode, "sdxl") or {})
        except Exception:
            preset = {}
        presets = {}
        base_types = tuple(getattr(core, "BASE_TYPE_KEYS", ("sd15", "sdxl", "flux", "anima")))
        for preset_mode in getattr(core, "MODE_KEYS", (mode,)):
            presets[preset_mode] = {}
            for base_type in base_types:
                try:
                    presets[preset_mode][base_type] = dict(core.preset_for(preset_mode, base_type) or {})
                except Exception:
                    presets[preset_mode][base_type] = {}
        interval_units = {}
        for key in ("save_every", "sample_interval"):
            try:
                interval_units[key] = str(core.interval_unit_for(mode, key))
            except Exception:
                interval_units[key] = "steps"
        labels = getattr(core, "MODE_LABELS", {})
        trigger_hints = {
            "style": getattr(core, "TRIGGER_HINT_STYLE", ""),
            "character": getattr(core, "TRIGGER_HINT_CHARACTER", ""),
            "concept": getattr(core, "TRIGGER_HINT_CONCEPT", ""),
            "krea2": getattr(core, "TRIGGER_HINT_KREA2", ""),
            "krea2_at": getattr(core, "TRIGGER_HINT_KREA2_AT", ""),
            "krea2_fz": getattr(core, "TRIGGER_HINT_KREA2", ""),
            "flux2": getattr(core, "TRIGGER_HINT_FLUX2", ""),
            "flux2_fz": getattr(core, "TRIGGER_HINT_FLUX2_FZ", ""),
            "video": getattr(core, "TRIGGER_HINT_VIDEO", ""),
            "qwen_image": getattr(core, "TRIGGER_HINT_AT", ""),
            "zimage": getattr(core, "TRIGGER_HINT_AT", ""),
        }
        dataset_hints = getattr(core, "DATASET_TIPS", {})
        project_config = core.load_project(str(project_name or "").strip()) if project_name else {}
        project_config = project_config if isinstance(project_config, dict) else {}
        guide_done_by_check = {
            "env": bool(status.get("git") and status.get("python")),
            "kohya": bool(status.get("kohya_ok")),
            "musubi": bool(status.get("musubi_ok")),
            "at": bool(status.get("at_ok")),
            "fizgig": bool(status.get("fizgig_ok")),
            "base": bool(project_config.get("base_model")),
            "raw": bool(project_config.get("raw_dir")),
        }
        model_checks = {
            "krea2_models", "krea2_at_models", "flux2_models", "flux2_fz_models", "h3_models", "at_model",
        }
        for step in getattr(core, "GUIDE_STEPS", {}).get(mode, ()):
            check = step.get("check")
            if check in model_checks:
                # `missing` is calculated with the same engine-specific readiness check
                # shown in the workspace status badges, avoiding divergent guide logic.
                guide_done_by_check[check] = not missing
        guide_steps = [
            {
                "id": str(step.get("id", "")),
                "label": self._plain_ui_text(step.get("label", "")),
                "button": self._plain_ui_text(step.get("btn", "")),
                "check": str(step.get("check", "")),
                "action": str(step.get("act", "")),
                "tip": self._plain_ui_text(step.get("tip", "")),
                "done": bool(guide_done_by_check.get(step.get("check"), False)),
            }
            for step in getattr(core, "GUIDE_STEPS", {}).get(mode, ())
        ]
        return {
            "ok": True,
            "mode": mode,
            "label": self._plain_mode_label(labels.get(mode, mode)),
            "dataset_hint": self._plain_ui_text(dataset_hints.get(mode, "")),
            "dataset_hints": {key: self._plain_ui_text(dataset_hints.get(key, "")) for key in ("style", "character", "concept")},
            "trigger_hint": self._plain_ui_text(trigger_hints.get(mode, "")),
            "trigger_hints": {key: self._plain_ui_text(trigger_hints.get(key, "")) for key in ("style", "character", "concept")},
            "concept_type_hints": {
                key: self._plain_ui_text(value)
                for key, value in getattr(core, "CONCEPT_TYPE_DATASET_HINT", {}).items()
            },
            "engine_ready": engine_ready,
            "engine_update_available": engine_update_available,
            "engine_key": engine_key,
            "gpu": status.get("gpu") or "?",
            "gpu_vendor": core.detect_gpu_vendor() or "unknown",
            "missing_models": [self._plain_ui_text(item) for item in missing],
            "asset_dir": str(asset_dir or ""),
            "supports": supports,
            "interval_units": interval_units,
            "defaults": preset,
            "presets": presets,
            "is_video": mode == "video",
            "is_step_based": mode in ("video", "qwen_image", "zimage"),
            "has_training_submode": mode in ("krea2", "krea2_at", "krea2_fz", "flux2", "flux2_fz"),
            "guide_steps": guide_steps,
        }

    @staticmethod
    def _plain_mode_label(label):
        """Keep the classic mode wording while avoiding colorful emoji in the modern UI."""
        return re.sub(r"^[\U0001f000-\U0001faff\u2600-\u27bf\ufe0e\ufe0f\u200d]+\s*", "", str(label)).strip()

    @staticmethod
    def _plain_ui_text(value):
        value = str(value or "")
        value = re.sub(r"[\U0001f000-\U0001faff\u2600-\u27bf\ufe0e\ufe0f\u200d]+", "", value)
        return value.replace("提示：提示：", "提示：").strip()

    def create_project(self, name, template_name="自定义", config_json=""):
        name = str(name or "").strip()
        if not name:
            return {"ok": False, "error": "请填写项目名称。"}
        if len(name) > 80 or name.endswith((".", " ")) or re.search(r'[\\/:*?"<>|\x00-\x1f]', name):
            return {"ok": False, "error": "项目名称不能超过 80 个字符，也不能包含 \\/:*?\"<>| 等特殊字符。"}
        if name.upper().split(".", 1)[0] in {
            "CON", "PRN", "AUX", "NUL",
            *("COM%d" % i for i in range(1, 10)),
            *("LPT%d" % i for i in range(1, 10)),
        }:
            return {"ok": False, "error": "这个名称是 Windows 保留名称，请换一个名称。"}

        if any(str(p.get("name", "")).casefold() == name.casefold() for p in self.core.list_projects()):
            return {"ok": False, "exists": True, "error": "已存在同名项目。"}

        imported_config = None
        import_summary = {"applied": 0, "ignored": 0}
        if config_json:
            if not isinstance(config_json, str) or len(config_json) > 2 * 1024 * 1024:
                return {"ok": False, "error": "导入配置无效或超过 2 MB。"}
            try:
                imported_config, import_summary = self.core.parse_config_json(config_json.lstrip("\ufeff"))
                import json as _json

                raw_config = _json.loads(config_json.lstrip("\ufeff"))
                raw_params = raw_config.get("params", {}) if isinstance(raw_config, dict) else {}
                if isinstance(raw_params, dict):
                    params = dict(imported_config.get("params") or {})
                    supplemented = 0
                    bool_params = {"overwrite", "amd_mode"}
                    int_params = {"video_frames"}
                    float_params = {"noise_offset", "min_snr_gamma"}
                    for key in _MODERN_IMPORT_EXTRA_PARAMS:
                        if key not in raw_params or key in params:
                            continue
                        value = raw_params[key]
                        try:
                            if key in bool_params:
                                value = value if isinstance(value, bool) else (
                                    str(value).strip().lower() in ("1", "true", "yes", "on", "开")
                                )
                            elif key in int_params:
                                value = int(float(value))
                            elif key in float_params:
                                value = float(value)
                            elif isinstance(value, (dict, list)) or value is None:
                                raise ValueError("参数格式无效")
                            else:
                                value = str(value)
                            params[key] = value
                            supplemented += 1
                        except (TypeError, ValueError, OverflowError):
                            pass
                    if supplemented:
                        imported_config["params"] = params
                        import_summary["applied"] = import_summary.get("applied", 0) + supplemented
                        import_summary["ignored"] = max(0, import_summary.get("ignored", 0) - supplemented)
            except Exception as exc:
                return {"ok": False, "error": "配置导入失败：%s" % exc}

        templates = getattr(self.core, "PROJECT_TEMPLATES", {})
        if template_name == "Qwen-Image":
            template = {"mode": "qwen_image", "base_type": "qwen_image"}
        elif template_name in _MODERN_PROJECT_TEMPLATES:
            template = _MODERN_PROJECT_TEMPLATES[template_name]
        else:
            template = templates.get(template_name, {})
        mode = template.get("mode", "style")
        base_type = template.get("base_type", "sd15")
        data = {
            "name": name,
            "template": template_name if template_name in templates or template_name in _MODERN_PROJECT_TEMPLATES or template_name == "Qwen-Image" else "自定义",
            "mode": mode,
            "base_type": base_type,
            "preset_version": int(self.core.PRESET_VERSION),
            "params": {},
        }
        if imported_config:
            mode = imported_config.get("mode", mode)
            base_type = imported_config.get("base_type", base_type)
            params = dict(imported_config.get("params") or {})
            if imported_config.get("sample_prompt"):
                params["sample_prompt"] = imported_config["sample_prompt"]
            model_name = imported_config.get("base_model") or ""
            try:
                base_model = self.core.find_model_by_filename(model_name, mode) if model_name else ""
            except Exception:
                base_model = ""
            if model_name and not base_model:
                self._log("[配置] 导入的底模「%s」未在本机找到；请打开项目后重新选择底模。" % model_name)
            data.update({
                "mode": mode,
                "base_type": base_type,
                "at_sub_mode": imported_config.get("at_sub_mode") or "character",
                "concept_type": imported_config.get("concept_type") or "form",
                "trigger": imported_config.get("trigger") or "",
                "global_pos": imported_config.get("global_pos") or "",
                "global_neg": imported_config.get("global_neg") or "",
                "style_caption": imported_config.get("style_caption") or "",
                "base_model": base_model or "",
                "unet_only": bool(imported_config.get("unet_only", False)),
                "params": params,
            })
            template_options = dict(templates)
            template_options.update(_MODERN_PROJECT_TEMPLATES)
            matching_template = next((
                label for label, value in template_options.items()
                if value.get("mode") == mode and value.get("base_type", base_type) == base_type
            ), None)
            if matching_template:
                data["template"] = matching_template
        if not self.core.save_project(name, data):
            return {"ok": False, "error": "保存项目失败，请检查磁盘空间和写入权限。"}
        if imported_config:
            self._log("[项目] 已新建项目「%s」并导入配置（应用 %d 项 / 忽略 %d 项）。" % (
                name, import_summary.get("applied", 0), import_summary.get("ignored", 0),
            ))
        else:
            self._log("[项目] 已新建项目「%s」（模板：%s）" % (name, template_name))
        return {"ok": True, "project": next((p for p in self.list_projects() if p["name"] == name), None)}

    def rename_project(self, old_name, new_name):
        old_name = str(old_name or "").strip()
        new_name = str(new_name or "").strip()
        if not old_name or not self.core.load_project(old_name):
            return {"ok": False, "error": "项目不存在或配置文件已损坏。"}
        if not self._valid_project_name(new_name):
            return {"ok": False, "error": "项目名称无效：请使用不超过 80 个字符的名称，且不要包含 Windows 文件名保留字符。"}
        if old_name.casefold() == new_name.casefold():
            return {"ok": True, "log": "项目名称没有变化。"}
        if any(str(p.get("name", "")).casefold() == new_name.casefold() for p in self.core.list_projects()):
            return {"ok": False, "error": "已存在同名项目。"}

        data = self.core.load_project(old_name)
        if not self.core.save_project(new_name, data):
            return {"ok": False, "error": "新名称保存失败，原项目保持不变。"}
        if not self.core.delete_project(old_name):
            self.core.delete_project(new_name)
            return {"ok": False, "error": "旧项目配置无法移除，已回滚重命名。"}

        dataset_message = ""
        try:
            old_dir = self.core.project_data_dir(old_name)
            new_dir = self.core.project_data_dir(new_name)
            if old_dir and new_dir and os.path.isdir(old_dir) and not os.path.exists(new_dir):
                os.rename(old_dir, new_dir)
                dataset_message = "；图集目录已同步改名"
        except Exception:
            dataset_message = "；图集目录未能同步改名"
        message = "[项目] 已重命名「%s」→「%s」%s" % (old_name, new_name, dataset_message)
        self._log(message)
        return {"ok": True, "log": message}

    def delete_project(self, name):
        name = str(name or "").strip()
        if not name or not self.core.delete_project(name):
            return {"ok": False, "error": "项目不存在或删除失败。"}
        message = "[项目] 已删除项目「%s」；图集数据和 output 中的训练产物保留。" % name
        self._log(message)
        return {"ok": True, "log": message}

    def suggest_project_name(self):
        """Return a fresh default name, avoiding existing and already suggested names."""
        base = str(self.core.default_project_name() or "新项目").strip() or "新项目"
        existing = {
            str(item.get("name", "")).casefold()
            for item in self.core.list_projects()
            if item.get("name")
        }
        existing.update(name.casefold() for name in self._project_name_reservations)
        candidate = base
        suffix = 2
        while candidate.casefold() in existing:
            candidate = "%s_%d" % (base, suffix)
            suffix += 1
        self._project_name_reservations.add(candidate)
        return {"ok": True, "name": candidate}

    def open_project(self, name):
        name = str(name or "").strip()
        if not name or not self.core.load_project(name):
            return {"ok": False, "error": "项目不存在或配置文件已损坏。"}
        self._log("[项目] 已载入「%s」；训练配置由新版训练页承接，训练时直调现有引擎函数。" % name)
        return {"ok": True}

    @staticmethod
    def _valid_project_name(name):
        if not name or len(name) > 80 or name.endswith((".", " ")) or re.search(r'[\\/:*?"<>|\x00-\x1f]', name):
            return False
        return name.upper().split(".", 1)[0] not in {
            "CON", "PRN", "AUX", "NUL",
            *("COM%d" % i for i in range(1, 10)),
            *("LPT%d" % i for i in range(1, 10)),
        }

    def _spawn_classic(self, *arguments):
        root = _app_root()
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--ui=classic", *arguments]
        else:
            entry = Path(sys.argv[0]).resolve()
            command = [sys.executable, str(entry), "--ui=classic", *arguments]
        return subprocess.Popen(command, cwd=str(root), close_fds=True)

    def run_action(self, action, project_name=None):
        """Open legacy secondary utilities as isolated popups; never fall back to its workspace."""
        action = str(action or "")
        if action.startswith("mode:") or action == "train":
            return {"ok": False, "error": "训练模式与训练任务由新版训练页直接承接。"}
        if action == "preprocess":
            # Keep every caller on the modern task/review workflow. The classic
            # command remains available for the classic UI, but must not be
            # launched from this bridge as a hidden workspace process.
            return self.start_preprocess_task(project_name)

        if action.startswith("open_models:"):
            mode = action.split(":", 1)[1]
            model_dirs = {
                "krea2": self.core.krea2_models_dir,
                "krea2_at": self.core.krea2_at_models_dir,
                "krea2_fz": self.core.krea2_models_dir,
                "flux2": self.core.flux2_models_dir,
                "flux2_fz": self.core.flux2_models_dir,
                "video": self.core.h3_models_dir,
            }
            get_dir = model_dirs.get(mode)
            if get_dir is None:
                return {"ok": False, "error": "此模式没有独立的模型目录。"}
            path = get_dir()
            try:
                os.makedirs(path, exist_ok=True)
                os.startfile(path)
            except Exception as exc:
                return {"ok": False, "error": "无法打开模型目录：%s" % exc}
            message = "[模型] 已打开 %s 模型目录：%s" % (mode, path)
            self._log(message)
            return {"ok": True, "message": "已打开模型目录。", "log": message}

        if action == "output_dir":
            path = self.core.data_sub("output")
            os.makedirs(path, exist_ok=True)
            try:
                os.startfile(path)
            except Exception as exc:
                return {"ok": False, "error": "无法打开输出目录：%s" % exc}
            message = "[目录] 已打开输出目录：%s" % path
            self._log(message)
            return {"ok": True, "message": "已打开输出目录。", "log": message}

        if action == "export_log":
            import datetime
            filename = "KohyaLoRA_运行日志_%s.txt" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            desktop = self._desktop_directory()
            dest = os.path.join(desktop, filename)
            try:
                os.makedirs(desktop, exist_ok=True)
                with open(dest, "w", encoding="utf-8") as handle:
                    handle.write("\n".join(self.logs) + "\n")
            except OSError:
                directory = self.core.data_sub("logs")
                os.makedirs(directory, exist_ok=True)
                dest = os.path.join(directory, filename)
                with open(dest, "w", encoding="utf-8") as handle:
                    handle.write("\n".join(self.logs) + "\n")
            self._log("[导出] 运行日志已导出：%s" % dest)
            return {"ok": True, "message": "运行日志已导出：%s" % dest}

        project_actions = {
            "label_editor", "export_config", "readme", "at_model_help",
            "at_engine_update", "anima_components", "krea2_guide", "flux2_guide",
            "h3_guide", "video_caption_stub", "video_caption", "amd_env",
        }
        if action in project_actions:
            project_name = str(project_name or "").strip()
            if not project_name or not self.core.load_project(project_name):
                return {"ok": False, "error": "项目不存在或配置文件已损坏。"}
            try:
                self._spawn_classic("--project", project_name, "--action", action, "--utility-only")
            except Exception as exc:
                return {"ok": False, "error": "无法打开该工具窗口：%s" % exc}
            tool_name = {
                "label_editor": "标签编辑器",
                "export_config": "配置导出",
                "readme": "使用说明",
                "at_model_help": "模型说明",
                "at_engine_update": "训练引擎更新",
                "anima_components": "Anima 组件",
                "krea2_guide": "Krea 2 使用引导",
                "flux2_guide": "FLUX.2 使用引导",
                "h3_guide": "H3 视频引导",
                "video_caption_stub": "视频字幕工具",
                "video_caption": "视频字幕工具",
                "amd_env": "AMD 环境检查",
            }.get(action, "工具")
            message = "已在单独窗口打开「%s」的%s；新版训练页和当前项目会保留，关闭此窗口即可继续操作。" % (
                project_name, tool_name)
            self._log("[工具] " + message)
            return {"ok": True, "message": message, "log": "[工具] " + message}

        utility_actions = {"tools", "check_update", "data_dir", "queue", "env_locations"}
        if action in utility_actions:
            try:
                self._spawn_classic("--action", action, "--utility-only")
            except Exception as exc:
                return {"ok": False, "error": "无法打开工具窗口：%s" % exc}
            tool_name = {
                "tools": "小工具",
                "check_update": "检查更新",
                "data_dir": "数据目录",
                "queue": "训练队列",
                "env_locations": "环境位置",
            }.get(action, "工具")
            message = "已在单独窗口打开「%s」；新版训练页保持打开，关闭工具窗口即可返回。" % tool_name
            self._log("[工具] " + message)
            return {"ok": True, "message": message, "log": "[工具] " + message}

        return {"ok": False, "error": "这个操作尚未接入新版训练页。"}


def launch(core, dev=False, debug=False, engine_groups=(), short_mode_labels=None):
    if sys.platform != "win32":
        raise RuntimeError("新版训练页目前仅支持 Windows。")
    if not _has_webview2_runtime():
        raise RuntimeError(
            "未检测到 Microsoft Edge WebView2 Runtime。请先安装 WebView2 Runtime 后再使用新版训练页；"
            "Windows 11 通常已内置，部分 Windows 10 需要单独安装。"
        )
    _ensure_web_asset_mimetypes()
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "新版训练页运行组件尚未安装。开发环境请运行 `python -m pip install -r requirements-ui.txt`。"
        ) from exc

    root = _app_root()
    index = root / "modern_ui" / "dist" / "index.html"
    if dev:
        url = os.environ.get("KOHYA_UI_DEV_URL", "http://127.0.0.1:5173")
    elif index.is_file():
        url = str(index)
    else:
        raise RuntimeError(
            "新版训练页资源尚未构建。请先在 modern_ui 目录运行 `npm install` 和 `npm run build`。"
        )

    bridge = ModernUIBridge(core, engine_groups, short_mode_labels)
    window = webview.create_window(
        title=getattr(core, "APP_NAME", "Kohya-LoRA") + " · 新版训练页",
        url=url,
        js_api=bridge,
        width=1360,
        height=860,
        min_size=(1060, 700),
        background_color="#1e2128",
        text_select=True,
    )
    bridge._window = window
    webview.start(gui="edgechromium", debug=debug, http_server=not dev, icon=str(root / "app.ico"))
    return 0
