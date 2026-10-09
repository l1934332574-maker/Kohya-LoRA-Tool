"""Windows WebView host and narrow bridge for the modern training UI."""

from __future__ import annotations

import base64
import io
import json
import copy
import os
import re
import math
import mimetypes
import subprocess
import sys
import threading
import time
import uuid
import traceback
from pathlib import Path

from kohya_core.diagnostics import SessionLog, summary_lines, redact, write_bundle
from kohya_core.training_history import TrainingHistory
from kohya_core.training_media import sample_files, image_preview, is_sample
from kohya_core.model_catalog import catalog as model_catalog, resolve_choice
from kohya_core.fizgig_engine import runtime as fizgig_runtime, source_version as fizgig_source_version, VERSION as FIZGIG_TARGET
from kohya_core.fizgig_adapter import FAMILIES as FIZGIG_FAMILIES, models as fizgig_models, missing as fizgig_missing, _validate as validate_fizgig_models
from kohya_core.project_config import WORKSPACE_PARAM_KEYS, BOOL_PARAM_KEYS, training_params, caption_summary, dataset_images, read_caption

try:
    from model_downloader import ModelDownloader
except Exception:  # pragma: no cover - desktop package may omit the optional helper
    ModelDownloader = None


_MODERN_PROJECT_TEMPLATES = {
    "Anima LoRA（Fizgig）": {"mode": "anima_fz", "base_type": "anima", "note": "Fizgig v7.0.1 标准 28 层 Anima，普通 LoRA；上游实验性入口。"},
    "SDXL LoRA（Fizgig）": {"mode": "sdxl_fz", "base_type": "sdxl", "note": "Fizgig v7.0.1 完整 SDXL 底模，冻结文本编码器；上游实验性入口。"},
    "概念 LoRA（SDXL）": {"mode": "concept", "base_type": "sdxl", "note": "旧版兼容模板：SDXL 概念训练。", "visible": False},
    "Krea 2 图像 LoRA": {"mode": "krea2", "base_type": "sdxl", "note": "第二引擎 musubi；模型文件放在 models/krea2。"},
    "H3 视频 LoRA": {"mode": "video", "base_type": "sdxl", "note": "第三引擎 AI Toolkit；使用视频文件和同名字幕。"},
    "Krea2 图像 LoRA（AI Toolkit）": {"mode": "krea2_at", "base_type": "sdxl", "note": "第三引擎 AI Toolkit；Krea2 RAW 模型放在 models/krea2。"},
    "Z-Image LoRA": {"mode": "zimage", "base_type": "sdxl", "note": "第三引擎 AI Toolkit；轻量图像模型，按步训练。"},
    "Krea2 图像 LoRA（Fizgig）": {"mode": "krea2_fz", "base_type": "sdxl", "note": "第四引擎 Fizgig；NVIDIA / AMD 通道，复用 models/krea2。"},
    "Klein 9B LoRA（Fizgig）": {"mode": "flux2_fz", "base_type": "sdxl", "note": "第四引擎 Fizgig；Klein 9B 图像 LoRA，模型放在 models/flux2。"},
    "Qwen-Image-2.1 LoRA（Fizgig）": {"mode": "qwen21_fz", "base_type": "sdxl", "note": "第四引擎 Fizgig；Qwen-Image-2.1 官方训练预设，模型放在 models/qwen_image21。"},
    "MiniMax H3 全模态 LoRA（Fizgig）": {"mode": "h3_fz", "base_type": "sdxl", "note": "第四引擎 Fizgig；图片、视频、音频与同名字幕可放在同一原始目录或其子目录。"},
}

_WORKSPACE_PARAM_KEYS = WORKSPACE_PARAM_KEYS

# These fields are accepted by the modern workspace save bridge, but were added
# after the classic JSON importer whitelist was defined. Preserve them when a
# modern project is created from a compatible JSON file.
_MODERN_IMPORT_EXTRA_PARAMS = {
    "fizgig_version",
    "sample_interval", "video_frames", "noise_offset", "min_snr_gamma",
    "wd14_model", "overwrite", "keep_user_captions", "amd_mode", "fizgig_qwen_preset",
    "batch_size", "gc", "sample_prompt", "sample_seed", "global_pos", "global_neg",
    "caption_method", "caption_language", "caption_length",
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
        self._startup = None
        self.logs = [
            "欢迎使用 Kohya-LoRA 一键训练工具",
            "按左侧新手引导顺序操作；打开项目后进入新版训练页。",
        ]
        self._task_lock = threading.RLock()
        self._task = None
        self._task_downloader = None
        self._project_name_reservations = set()
        self._picker_dirs = {}
        self._dataset_previews = {}
        self._caption_reports = {}
        self._prompt_reports = {}
        from kohya_core.captioning import CaptionSettings
        self._caption_settings = CaptionSettings(self.core.data_sub("settings"))
        from kohya_core.assistant import AssistantSettings
        self._assistant_settings = AssistantSettings(self.core.data_sub("settings"))
        self._assistant_lock = threading.RLock()
        self._assistant_request = None
        self._log_lock = threading.RLock()
        self._diagnostics_thread = None
        self._log_export = {}
        self._session_log = None
        self._session_log_error = None
        try:
            self._session_log = SessionLog(self.core.data_sub("logs"))
            for line in self.logs:
                self._session_log.append(line)
        except Exception as exc:
            self._session_log_error = str(exc)

        from kohya_core.training_agent import TrainingAgent
        self._agent = TrainingAgent(self)

    def _agent_guard(self):
        if not self._agent.mutation_allowed():
            return {"ok": False, "error": "助手正在执行操作。你可以继续查看界面；需要手动修改时，请在助手里点击“我来操作”。"}
        return None

    def get_agent_environment(self):
        try:
            return {"ok": True, "environment": self._agent.environment()}
        except Exception:
            return {"ok": False, "error": "无法读取完整环境，可启动 Agent 后查看具体步骤。"}

    def start_agent(self, project_name, options):
        return self._agent.start(str(project_name or ""), options)

    def get_agent_state(self, project_name=None):
        return self._agent.snapshot(None if project_name is None else str(project_name))

    def reply_agent(self, run_id, answer, question_id=""):
        return self._agent.reply(str(run_id or ""), answer, str(question_id or ""))

    def send_agent_message(self, run_id, text):
        return self._agent.message(str(run_id or ""), text)

    def control_agent(self, run_id, action):
        return self._agent.control(str(run_id or ""), str(action or ""))

    def pick_agent_path(self, run_id, kind, path=""):
        if kind not in ("folder", "model"):
            return {"ok": False, "error": "请选择文件夹或模型文件。"}
        current = self._agent.snapshot().get("run") or {}
        if current.get("id") != str(run_id or ""):
            return {"ok": False, "error": "当前对话已变化，请刷新后重新选择。"}
        if not path:
            selection = self.choose_path(kind, memory_key="agent_chat_" + kind)
            if not selection.get("ok") or selection.get("cancelled"):
                return selection
            path = selection.get("path", "")
        return self._agent.provide_path(str(run_id or ""), kind, path)

    def stop_agent(self, run_id, stop_task=False):
        return self._agent.stop(str(run_id or ""), stop_task)

    def _agent_computer_context(self):
        if not self._agent.owns_thread():
            raise ValueError("电脑工具只能由当前助手任务调用。")
        roots = [str(_app_root()), self.core.data_sub("")]
        config = self.core.load_project(self._agent.state.get("project", "")) or {}
        dataset = str(config.get("raw_dir") or "")
        if dataset and os.path.isdir(dataset):
            roots.append(dataset)
        with self._agent.lock:
            authorized_paths = list(getattr(self._agent, "authorized_paths", ()))
        for path in authorized_paths:
            candidate = Path(path)
            roots.append(str(candidate))
        aliases = {"application": str(_app_root()), "data": self.core.data_sub(""),
                   "project": dataset if dataset and os.path.isdir(dataset) else self.core.data_sub("")}
        return roots, aliases

    def inspect_agent_computer(self, options):
        from kohya_core.agent_computer import inspect_files
        try:
            roots, aliases = self._agent_computer_context()
            return inspect_files(options, aliases, roots)
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:500]}

    def run_agent_computer_command(self, options):
        from kohya_core.agent_computer import run_command
        if not self._agent.owns_thread() or not isinstance(options, dict):
            return {"ok": False, "error": "电脑命令只能由当前助手任务调用。"}
        command = options.get("command")
        if not self._agent.consume_command_approval(command):
            return {"ok": False, "error": "这条电脑命令尚未获得用户明确确认。"}
        try:
            self._agent._check_stop()
            result = run_command(command, str(_app_root()), self._agent._check_stop)
            self._log("[助手电脑操作] 已执行用户确认的命令，返回码：%s" % result.get("returncode"))
            return result
        except Exception as exc:
            return {"ok": False, "error": "电脑命令未完成：%s" % type(exc).__name__}

    def open_agent_browser(self, url):
        from kohya_core.agent_computer import open_browser
        if not self._agent.owns_thread():
            return {"ok": False, "error": "请通过当前助手对话打开网页。"}
        try:
            self._agent._check_stop()
            return open_browser(url)
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:500]}

    def search_agent_models(self, query, provider="huggingface"):
        from kohya_core.agent_models import search_models
        if not self._agent.owns_thread():
            return {"ok": False, "error": "请通过助手对话查找模型。"}
        return search_models(query, provider, stop=self._agent._transport_stop)

    def get_agent_model_repository(self, provider, repository):
        from kohya_core.agent_models import model_repository
        if not self._agent.owns_thread():
            return {"ok": False, "error": "请通过助手对话查看模型文件。"}
        return model_repository(provider, repository, stop=self._agent._transport_stop)

    def _agent_model_directory(self, project_name, requested=""):
        config = self.core.load_project(project_name) or {}
        mode = str(config.get("mode") or "character")
        if requested:
            destination = Path(str(requested)).expanduser().resolve()
            with self._agent.lock:
                granted_paths = list(getattr(self._agent, "authorized_paths", ()))
            authorized = [Path(path).resolve() for path in granted_paths if Path(path).is_dir()]
            if not any(destination == folder or folder in destination.parents for folder in authorized):
                raise ValueError("下载目录需要用户在当前对话中明确选择。")
            return str(destination)
        directories = {"krea2": "krea2_models_dir", "krea2_at": "krea2_at_models_dir", "krea2_fz": "krea2_models_dir",
                       "flux2": "flux2_models_dir", "flux2_fz": "flux2_models_dir", "qwen21_fz": "qwen21_fz_models_dir",
                       "h3_fz": "h3_fz_models_dir", "video": "h3_models_dir"}
        if mode in directories:
            return str(getattr(self.core, directories[mode])())
        if mode in ("qwen_image", "zimage"):
            return str(self.core.at_image_local_dir(mode))
        architecture = str(config.get("base_type") or "sdxl")
        if architecture not in ("sd15", "sdxl", "flux", "anima"):
            architecture = "sdxl"
        return self.core.data_sub("models", architecture)

    def start_agent_model_download(self, project_name, options):
        from kohya_core.agent_models import download_file
        if not self._agent.owns_thread() or not isinstance(options, dict):
            return {"ok": False, "error": "模型下载只能由当前助手任务调用。"}
        if not (self._agent.state.get("policy") or {}).get("allow_download"):
            return {"ok": False, "error": "下载还没有获得本次授权。"}
        if str(project_name or "") != self._agent.state.get("project") or not project_name:
            return {"ok": False, "error": "请先绑定项目，再选择模型下载位置。"}
        try:
            destination = self._agent_model_directory(project_name, options.get("destination", ""))
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:500]}
        task_id = self._begin_task("助手模型下载", "agent_model_download", key=project_name)
        if not task_id:
            return {"ok": False, "error": "其他任务正在运行，请等它结束。"}
        run_id = self._agent.state["id"]
        cancel_event = threading.Event()
        with self._task_lock:
            self._task["cancel_event"] = cancel_event
        self._task_log(task_id, "[助手下载] 目标目录：%s" % destination)

        def stop():
            if cancel_event.is_set():
                raise RuntimeError("下载已取消；已下载的分段保留，可再次下载继续。")

        def progress(value):
            fraction = value.get("progress") if isinstance(value, dict) else value
            detail = value.get("message", "正在下载模型…") if isinstance(value, dict) else "正在下载模型…"
            with self._task_lock:
                if self._task and self._task.get("id") == task_id:
                    self._task.update(progress=fraction, message=detail)

        def worker():
            try:
                result = download_file(options.get("provider", "huggingface"), options.get("repository", ""),
                                       options.get("file", ""), destination, stop, progress)
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task["download_result"] = result
                if result.get("ok"):
                    with self._agent.lock:
                        if self._agent.state and self._agent.state.get("id") == run_id:
                            self._agent.authorized_paths.add(result["path"])
                    self._task_log(task_id, "[助手下载] 文件已保存：%s；结构检查不代表此模式支持该模型。" % result.get("path"))
                    self._finish_agent_download(task_id, "completed", "模型已下载并检查，请确认架构与当前训练模式兼容。")
                else:
                    self._finish_agent_download(task_id, "failed", result.get("error", "模型下载未完成。"))
            except Exception as exc:
                status = "cancelled" if cancel_event.is_set() else "failed"
                self._finish_agent_download(task_id, status, "下载已取消，可再次选择同一文件续传。" if status == "cancelled" else "模型下载失败：%s" % str(exc)[:400])

        threading.Thread(target=worker, daemon=True, name="AgentModelDownload").start()
        return {"ok": True, "task_id": task_id, "destination": destination}

    def _release_agent_model_for_task(self, task_id):
        # Manual training uses the same release step as Agent-started training.
        if not self._agent.state or not self._agent.state.get("messages"):
            return
        try:
            connection = self._assistant_settings.connection()
        except Exception:
            return
        if connection.get("provider") == "ollama":
            from kohya_core.agent_transport import release_model
            self._task_log(task_id, "[助手] GPU 任务前请求释放本地文字模型显存…")
            released = release_model(connection, getattr(self.core, "check_stop", lambda: None))
            self._task_log(task_id, "[助手] 本地文字模型已请求卸载。" if released.get("ok") else "[WARN] " + released.get("error", "文字模型卸载未确认，请检查显存。"))
        elif connection.get("local"):
            self._task_log(task_id, "[WARN] 本地兼容文字服务没有统一卸载接口，请在模型服务中释放文字模型显存后继续。")

    def _finish_agent_download(self, task_id, status, message):
        with self._task_lock:
            if self._task and self._task.get("id") == task_id:
                self._task.update(status=status, message=message, progress=1.0 if status == "completed" else self._task.get("progress"))
        self._task_log(task_id, message)
        self.core.clear_status_cache()

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
        with self._log_lock:
            self.logs.append(str(message))
            if self._session_log:
                self._session_log.append(message)
            if len(self.logs) > 3000:
                del self.logs[:-3000]

    def _task_log(self, task_id, message):
        message = str(message)
        with self._task_lock:
            task = self._task
            if task and task.get("id") == task_id:
                task["logs"].append(message)
                if task.get("kind") == "training":
                    task.setdefault("effective_params", {}).update(getattr(self.core, "get_effective", lambda: {})())
                if task.get("kind") == "training" and re.search(r"preview failed|sampling failed|disabling previews|采样(?:预览)?(?:生成)?失败|停用后续预览|(?:采样|预览).*(?:Error:|Exception:)|No prompt file", message, re.I):
                    task["sampling_status"] = {"status": "failed", "reason": message[:600],
                                               "disabled": "disabling previews" in message.lower() or "关闭本轮后续预览" in message or "停用后续预览" in message}
                if len(task["startup_logs"]) < 500:
                    task["startup_logs"].append(message)
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
                "kind": task.get("kind", ""),
                "project_name": task.get("key", ""),
                "plan": dict(task.get("plan") or {}),
                "status": task["status"],
                "message": task.get("message", ""),
                "progress": task.get("progress"),
                "eta_seconds": task.get("eta_seconds"),
                "detail": task.get("detail", ""),
                "metrics": task.get("metrics"),
                "loss_history": list(task.get("loss_history", [])),
                "sampling_status": dict(task.get("sampling_status") or {}),
                "effective_params": dict(task.get("effective_params") or {}),
                "download_result": dict(task.get("download_result") or {}),
                "logs": logs[max(0, offset - log_offset):],
                "next_offset": log_offset + len(logs),
            }

    @staticmethod
    def _is_training_sample(filename, parent):
        return is_sample(filename, parent)

    def _sample_context(self, task_id):
        with self._task_lock:
            task = self._task
            if not task or task.get("id") != str(task_id or "") or task.get("kind") != "training":
                raise ValueError("训练任务已不存在，请重新打开训练窗口。")
            return self.core.data_sub("output", task.get("key") or ""), float(task.get("started") or 0), dict(task.get("sample_baseline") or {})

    def list_task_samples(self, task_id, offset=0):
        """Only list images written during this task, with bounded page sizes."""
        try:
            directory, started, baseline = self._sample_context(task_id)
            images = [item for item in sample_files(directory, started) if baseline.get(item["name"]) != item["version"]]
            offset = max(0, int(offset or 0))
            return {"ok": True, "samples": images[offset:offset + 100], "total": len(images),
                    "next_offset": offset + 100 if offset + 100 < len(images) else None}
        except (OSError, ValueError, TypeError) as exc:
            return {"ok": False, "error": "无法读取本次采样历史：%s" % exc}

    def get_task_sample(self, task_id, after="", full=False, name=""):
        """Read the latest or a catalogued current-run image; never accept arbitrary file paths."""
        try:
            directory, started, baseline = self._sample_context(task_id)
            images = [item for item in sample_files(directory, started) if baseline.get(item["name"]) != item["version"]]
            entry = next((item for item in images if item["name"] == name), None) if name else (images[0] if images else None)
            if not entry:
                return {"ok": True, "available": False,
                        "warning": "这张采样图已不存在，请刷新历史列表。" if name else ""}
            result = {"ok": True, "available": True, **entry}
            if str(after or "") != entry["version"] or full:
                result.update(image_preview(directory, entry["name"], full))
            return result
        except (OSError, ValueError) as exc:
            # An image may still be being written. Do not mark its version as consumed.
            return {"ok": False, "available": False,
                    "error": "采样图暂时无法读取，稍后重试：%s" % str(exc)[:160]}

    def _record_training_metrics(self, task_id, snapshot):
        with self._task_lock:
            task = self._task
            if not task or task.get("id") != task_id:
                return
            step = int(snapshot.get("step") or 0)
            loss = snapshot.get("loss")
            loss = float(loss) if isinstance(loss, (int, float)) and math.isfinite(loss) else None
            speed = snapshot.get("speed")
            speed = float(speed) if isinstance(speed, (int, float)) and math.isfinite(speed) else 0.0
            task["metrics"] = {"step": step, "total": int(snapshot.get("total") or 0), "loss": loss, "speed": speed}
            if step > 0 and loss is not None:
                points = task.setdefault("loss_history", [])
                point = {"step": step, "loss": loss}
                if points and points[-1]["step"] == step:
                    points[-1] = point
                elif not points or step > points[-1]["step"]:
                    points.append(point)
                    if len(points) > 600:
                        task["loss_history"] = points[:-1:2] + [points[-1]]

    def _begin_task(self, title, kind, mode="", key=""):
        with self._task_lock:
            if not self._agent.mutation_allowed():
                return None
            if self._assistant_request and self._assistant_request.get("status") == "running":
                return None
            if self._task and self._task.get("status") in ("running", "awaiting_review"):
                return None
            task_id = uuid.uuid4().hex
            self._task = {
                "id": task_id, "title": str(title), "kind": kind, "mode": mode,
                "key": key, "status": "running", "message": "正在启动…",
                "progress": None, "eta_seconds": None, "detail": "", "logs": [], "startup_logs": [], "log_offset": 0,
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
            "cmd_install_fizgig": ("安装 Fizgig v7.0.1", self.core.install_fizgig_engine),
            "fizgig_engine_update": ("更新 Fizgig v7.0.1", self.core.update_fizgig_engine),
            "fizgig_engine_rollback": ("回退 Fizgig 活动版本", self.core.rollback_fizgig_engine),
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
                self._task_log(task_id, traceback.format_exc())

        threading.Thread(target=worker, name="ModernSetupTask", daemon=True).start()
        return {"ok": True, "task_id": task_id}

    def _model_download_spec(self, mode):
        mode = str(mode or "")
        specs = {
            "anima_fz": ("Anima 模型", "Fizgig 标准 28 层 Anima 组件", "ANIMA_FZ_MODEL_LINKS", "anima_fz_models_dir", "anima_fz_model_files", {"dit", "te", "vae"}),
            "sdxl_fz": ("SDXL 模型", "完整 SDXL 底模；已有第三方底模可直接选择", "SDXL_FZ_MODEL_LINKS", "sdxl_fz_models_dir", "sdxl_fz_model_files", {"dit"}),
            "krea2": ("Krea 2 模型", "Krea2 训练文件", "KREA2_MODEL_LINKS", "krea2_models_dir", "krea2_model_files", {"raw", "vae", "te"}),
            "krea2_at": ("Krea2 模型", "Krea2 AI Toolkit 训练文件", "KREA2_MODEL_LINKS", "krea2_models_dir", "krea2_model_files", {"raw", "vae"}),
            "krea2_fz": ("Krea2 模型", "Krea2 Fizgig 训练文件", "KREA2_MODEL_LINKS", "krea2_models_dir", "krea2_model_files", {"raw", "vae", "te"}),
            "flux2": ("FLUX.2 模型", "FLUX.2 4B 训练文件", "FLUX2_MODEL_LINKS", "flux2_models_dir", "flux2_model_files", {"dit", "te", "vae"}),
            "flux2_fz": ("Klein 9B 模型", "FLUX.2 Klein 9B 训练文件", "FLUX2FZ_MODEL_LINKS", "flux2_models_dir", "flux2_fz_model_files", {"dit", "te", "vae"}),
            "qwen21_fz": ("Qwen-Image-2.1 模型", "Qwen-Image-2.1 Fizgig 训练文件", "QWEN21_FZ_MODEL_LINKS", "qwen21_fz_models_dir", "qwen21_fz_model_files", {"dit", "vae", "te", "training_adapter"}),
            "h3_fz": ("H3 Fizgig 模型", "MiniMax H3 图片 / 视频 / 音频混合训练文件", "H3_FZ_MODEL_LINKS", "h3_fz_models_dir", "h3_fz_model_files", {"dit", "te", "video_vae"}),
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
            filename, label = value[0], value[1]
            urls = self.core.model_url_list(value)
            url = urls[0] if urls else ""
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
        elif mode == "qwen21_fz":
            note = "DiT、VAE、文本编码器和训练适配器为训练必需；speed LoRA 仅供预览，可选。"
        elif mode == "h3_fz":
            note = "官方 int8 DiT、文本编码器和视频 VAE 为必需；音频 VAE 在训练音频或带声音视频时必需，训练适配器和 Turbo LoRA 可选。"
        else:
            note = "下载支持断点续传；取消或中断后再次点击同一文件即可接着下载。"
        params = {
            "ok": True, "mode": mode, "title": title, "description": description,
            "asset_dir": asset_dir, "note": note, "items": items,
        }
        return params

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
        entry = links[key]
        filename, label = entry[0], entry[1]
        urls = self.core.model_url_list(entry)
        if not urls:
            return {"ok": False, "error": "当前模型没有可用的下载源，请手动获取。"}
        url = urls[0]
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
            cancel_event = self._task.get("cancel_event")
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
        if kind == "agent_model_download" and cancel_event is not None:
            cancel_event.set()
        elif downloader is not None:
            downloader.cancel()
        elif kind in ("setup", "training", "preprocess", "caption", "prompt_reverse"):
            self.core.stop_active_process()
        return {"ok": True}

    def continue_training(self, task_id, source="user"):
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
        self._task_log(str(task_id), "[训练] Agent 已按授权执行完整性检查并继续；尚未验证图文语义。" if source == "agent" and self._agent.owns_thread() else "[训练] 用户已检查标签并确认继续。")
        return {"ok": True}

    def get_caption_service(self):
        try:
            with self._task_lock:
                task = self._task
                active = {"id": task["id"], "status": task["status"], "project_name": task["key"]} if task and task["kind"] == "caption" else None
            return {"ok": True, "settings": self._caption_settings.public(), "task": active}
        except Exception:
            return {"ok": False, "error": "无法读取图片描述服务设置，请重新配置。"}

    def save_caption_service(self, settings):
        guard = self._agent_guard()
        if guard:
            return guard
        from kohya_core.captioning import CaptionError
        try:
            if not isinstance(settings, dict):
                raise CaptionError("服务设置格式无效。")
            with self._task_lock:
                if self._task and self._task.get("status") in ("running", "awaiting_review"):
                    raise CaptionError("请先完成或停止当前任务，再修改描述服务。")
                return {"ok": True, "settings": self._caption_settings.save(settings)}
        except CaptionError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception:
            return {"ok": False, "error": "无法保存描述服务设置或加密密钥。"}

    def get_caption_report(self, task_id):
        with self._task_lock:
            report = self._caption_reports.get(str(task_id or ""))
            return {"ok": True, "report": report} if report else {"ok": False, "error": "描述结果尚未生成或已过期。"}

    def get_prompt_reverse(self, task_id=""):
        with self._task_lock:
            key = str(task_id or "") or next(reversed(self._prompt_reports), "")
            report = self._prompt_reports.get(key)
            task = self._task if self._task and self._task.get("kind") == "prompt_reverse" and self._task.get("id") == key else None
            return {"ok": True, "task_id": key, "report": copy.deepcopy(report),
                    "task": {field: task.get(field) for field in ("id", "status", "message", "detail", "progress")} if task else None}

    def start_prompt_reverse(self, options):
        from kohya_core.captioning import CaptionError, _atomic_bytes
        from kohya_core.prompt_reverse import prepare, generate
        try:
            selection = prepare(options)
            service = self._caption_settings.connection() if selection["method"] == "natural" else None
            if service and not service["local"] and options.get("allow_remote") is not True:
                raise CaptionError("请确认允许将所选图片发送到在线视觉服务。")
        except CaptionError as exc:
            return {"ok": False, "error": str(exc)}
        except (OSError, ValueError):
            return {"ok": False, "error": "无法读取图片或服务设置，请检查选择的文件。"}
        task_id = self._begin_task("反推图片提示词", "prompt_reverse")
        if not task_id:
            return {"ok": False, "error": "已有训练、助手或准备任务正在运行，请先完成或停止。"}
        self.core.reset_stop()
        report = {"task_id": task_id, "directory": str(selection["root"]), "path": selection["path"],
                  "method": selection["method"], "language": selection["language"], "length": selection["length"],
                  "status": "running", "total": len(selection["images"]), "generated": 0, "failed": 0, "items": []}
        report_path = self.core.data_sub("logs", "prompt_reverse_%s.json" % task_id)

        def publish(value):
            with self._task_lock:
                self._prompt_reports[task_id] = copy.deepcopy(value)
                while len(self._prompt_reports) > 8:
                    self._prompt_reports.pop(next(iter(self._prompt_reports)))

        def progress(done, total, item):
            with self._task_lock:
                if self._task and self._task.get("id") == task_id:
                    self._task.update(progress=done / max(total, 1), detail="%s / %s · %s" % (done, total, item["name"]),
                                      message="正在反推图片提示词…")

        def worker():
            message = "反推任务已结束。"
            try:
                generate(self.core, selection, service, report, lambda line: self._task_log(task_id, line), progress, publish)
                report["status"] = "failed" if report["failed"] or report.get("error") else "completed"
                message = report.get("error") or "反推完成：生成 %d 张，失败 %d 张。结果可以编辑、复制或导出。" % (report["generated"], report["failed"])
            except self.core.StopRequested:
                report["status"], message = "cancelled", "已停止反推，已生成的结果保留；已发出的在线请求可能仍在执行。"
            except Exception as exc:
                report["status"] = "failed"
                message = str(exc) if isinstance(exc, CaptionError) else "反推失败，请检查图片、模型和运行日志。"
                report["error"] = message
            finally:
                publish(report)
                try:
                    _atomic_bytes(Path(report_path), json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"))
                except OSError:
                    self._task_log(task_id, "[反推] 无法保存本地结果记录；仍可在本次会话复制和导出。")
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task.update(status=report["status"], message=message, progress=None if report["status"] == "cancelled" else 1.0)
        publish(report)
        threading.Thread(target=worker, daemon=True, name="prompt-reverse").start()
        return {"ok": True, "task_id": task_id}

    def get_prompt_reverse_image(self, task_id, name):
        with self._task_lock:
            report = self._prompt_reports.get(str(task_id or ""))
            root = report.get("directory") if report and any(item["name"] == name for item in report["items"]) else None
        if not root:
            return {"ok": False, "error": "图片不属于本次反推结果。"}
        try:
            return {"ok": True, **image_preview(root, name)}
        except (OSError, ValueError):
            return {"ok": False, "error": "无法读取这张图片。"}

    def export_prompt_reverse(self, task_id, items, directory):
        guard = self._agent_guard()
        if guard:
            return guard
        from kohya_core.captioning import CaptionError
        from kohya_core.prompt_reverse import export_report
        with self._task_lock:
            report = copy.deepcopy(self._prompt_reports.get(str(task_id or "")))
        if not report:
            return {"ok": False, "error": "反推结果已过期，请重新生成。"}
        try:
            files = export_report(report, items, directory)
            return {"ok": True, "directory": str(Path(directory).resolve()), "written": len(files), "files": files}
        except CaptionError as exc:
            return {"ok": False, "error": str(exc)}
        except OSError:
            return {"ok": False, "error": "无法写入输出文件夹；请检查权限，部分文本可能已导出。"}

    def start_caption_task(self, project_name, options):
        from kohya_core.captioning import CaptionError, caption_options, generate_captions, service_identity
        if (self.core.load_project(str(project_name or "")) or {}).get("training_kind") == "slider":
            return {"ok": False, "error": "滑块使用共有描述与图片配对；请在滑块页操作，不做普通逐图打标。"}
        project_name = str(project_name or "").strip()
        config = self.core.load_project(project_name)
        if not isinstance(config, dict) or not isinstance(options, dict):
            return {"ok": False, "error": "项目或描述选项无效。"}
        try:
            language, length = caption_options(options.get("language", "zh"), options.get("length", "brief"))
            directory = str(options.get("directory") or config.get("raw_dir") or "").strip()
            if not os.path.isdir(directory):
                raise CaptionError("请先选择有效的原始图片文件夹。")
            service = self._caption_settings.connection()
            preview, replace = bool(options.get("preview", True)), bool(options.get("replace", False))
            names = None
            preview_cache = {}
            with self._task_lock:
                for old in reversed(list(self._caption_reports.values())):
                    if (old.get("preview") and old.get("project_name") == project_name
                            and old.get("directory") == directory and old.get("language") == language
                            and old.get("length") == length and old.get("service_identity") == service_identity(service)):
                        preview_cache = {item["name"]: item for item in old["items"] if item.get("status") == "preview"}
                        break
            retry_id = str(options.get("retry_task_id") or "")
            if retry_id:
                with self._task_lock:
                    previous = self._caption_reports.get(retry_id)
                if not previous or previous.get("project_name") != project_name or previous.get("directory") != directory:
                    raise CaptionError("重试任务与当前项目或图片目录不一致。")
                names = [item["name"] for item in previous["items"] if item.get("status") == "failed"]
                if not names:
                    raise CaptionError("没有需要重试的失败图片。")
                preview, replace = previous["preview"], previous.get("replace", False)
            if not service["local"] and options.get("allow_remote") is not True:
                raise CaptionError("请确认允许把图片发送到所选在线描述服务。")
        except CaptionError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception:
            return {"ok": False, "error": "无法准备描述任务，请检查服务和数据目录。"}
        task_id = self._begin_task("图片描述预览" if preview else "批量生成图片描述", "caption", key=project_name)
        if not task_id:
            return {"ok": False, "error": "已有任务运行中，请先完成或停止。"}
        self.core.reset_stop()

        def progress(done, total, item):
            with self._task_lock:
                if self._task and self._task.get("id") == task_id:
                    self._task.update(progress=done / total, detail="%d / %d · %s" % (done, total, item["name"]),
                                      message="正在生成图片描述…")

        def worker():
            try:
                report = generate_captions(service, directory, language, length, replace=replace,
                                           preview=preview, names=names, preview_cache=preview_cache, stop=self.core.check_stop,
                                           log=lambda line: self._task_log(task_id, line), progress=progress,
                                           report_path=self.core.data_sub("logs", "caption_%s.json" % task_id))
                report.update(project_name=project_name, directory=directory, replace=replace)
                with self._task_lock:
                    self._caption_reports[task_id] = report
                    while len(self._caption_reports) > 8:
                        self._caption_reports.pop(next(iter(self._caption_reports)))
                    if self._task and self._task.get("id") == task_id:
                        self._task.update(status="failed" if report["failed"] else "completed", progress=1.0,
                                          message=("预览完成（未写文件）：写入 %d，保留 %d，失败 %d。" if preview else "描述完成：写入 %d，保留 %d，失败 %d。") %
                                                  (report["written"], report["skipped"], report["failed"]))
            except self.core.StopRequested:
                try:
                    with open(self.core.data_sub("logs", "caption_%s.json" % task_id), encoding="utf-8") as handle:
                        partial = json.load(handle)
                    partial.update(project_name=project_name, directory=directory, replace=replace)
                    with self._task_lock:
                        self._caption_reports[task_id] = partial
                        while len(self._caption_reports) > 8:
                            self._caption_reports.pop(next(iter(self._caption_reports)))
                except (OSError, ValueError):
                    pass
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task.update(status="cancelled", message="描述已停止，已写入的文本保留；服务中已发出的请求可能仍在执行。")
            except Exception as exc:
                message = str(exc) if isinstance(exc, CaptionError) else "描述任务失败，请检查图片与服务状态。"
                self._task_log(task_id, "[描述失败] " + message)
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task.update(status="failed", message=message)

        threading.Thread(target=worker, daemon=True, name="caption-batch").start()
        return {"ok": True, "task_id": task_id}

    def start_preprocess_task(self, project_name):
        """Run the existing image/video preparation path in the modern task dialog."""
        project_name = str(project_name or "").strip()
        config = self.core.load_project(project_name) if project_name else None
        if not isinstance(config, dict):
            return {"ok": False, "error": "项目不存在或配置文件已损坏。"}
        if config.get("training_kind") == "slider":
            return {"ok": False, "error": "滑块训练会自动准备文字练习画面或同步处理图片对；无需普通预处理。"}
        raw_dir = str(config.get("raw_dir") or "").strip()
        if not raw_dir or not os.path.isdir(raw_dir):
            return {"ok": False, "error": "请先在新版训练页选择有效的数据文件夹。"}

        mode = str(config.get("mode") or "character")
        if mode == "video":
            has_videos = bool(self.core.scan_video_dataset(raw_dir)[0])
            if not has_videos:
                return {"ok": False, "error": "当前文件夹没有找到可用的视频文件。"}
        elif mode != "h3_fz" and self._count_preprocessable_images(raw_dir) <= 0:
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
        task_id = self._begin_task("%s 数据预处理" % self.core.MODE_LABELS.get(mode, mode), "preprocess", mode=mode, key=project_name)
        if not task_id:
            return {"ok": False, "error": "已有安装、预处理或训练任务正在运行，请等它完成后再试。"}
        self.core.reset_stop()

        def worker():
            import tempfile

            report_path = os.path.join(tempfile.gettempdir(), "kohya_modern_manual_preprocess_%s.json" % task_id)
            try:
                self._release_agent_model_for_task(task_id)
                if mode == "video":
                    videos, duration, no_caption = self.core.scan_video_dataset(raw_dir)
                    self._task_log(task_id, "[预处理] 视频数据已就绪：%d 个视频，%.1f 秒，%d 个缺字幕。视频无需图片预处理。" % (
                        len(videos), duration, no_caption
                    ))
                    message = "视频数据检查完成。"
                elif mode == "h3_fz":
                    summary = self.core.scan_fizgig_h3_dataset(raw_dir)
                    total = int(summary.get("total", 0) or 0)
                    missing = summary.get("missing_captions", 0)
                    missing = len(missing) if isinstance(missing, (list, tuple, set)) else int(missing or 0)
                    self._task_log(task_id, "[预处理] H3 混合媒体扫描：图片 %d，视频 %d，音频 %d，总计 %d，缺字幕 %d。" % (
                        int(summary.get("images", 0) or 0), int(summary.get("videos", 0) or 0),
                        int(summary.get("audio", 0) or 0), total, missing,
                    ))
                    if total <= 0:
                        raise RuntimeError("目录中没有可训练的图片、视频或音频样本。")
                    if missing:
                        raise RuntimeError("有 %d 个媒体文件缺少同名 .txt 字幕；请补齐字幕后重新扫描。" % missing)
                    message = "H3 混合媒体扫描完成；未移动或转码文件。"
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
                        "keep_user_captions": bool(stored.get("keep_user_captions", False)),
                        "caption_method": str(stored.get("caption_method") or "wd14"),
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
                self._task_log(task_id, traceback.format_exc())
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
        return training_params(self.core, config, project_name)

    def inspect_slider_pairs(self, project_name, settings):
        if not isinstance(self.core.load_project(str(project_name or "")), dict):
            return {"ok": False, "error": "项目不存在。"}
        try:
            from kohya_core.slider_project import normalize
            from kohya_core.slider_dataset import scan
            report = scan(normalize(settings))
            return {"ok": True, "pairs": [{k: row[k] for k in ("positive", "negative")} for row in report["pairs"]],
                    "positive_files": report["positive_files"], "negative_files": report["negative_files"],
                    "train_count": len(report["train"]), "holdout_count": len(report["holdout"]), "warnings": report["warnings"]}
        except (ValueError, OSError) as exc:
            files = {}
            try:
                from kohya_core.slider_dataset import _images
                for side in ("positive", "negative"):
                    _, paths = _images(str(settings.get(side + "_dir") or ""))
                    files[side + "_files"] = [path.name for path in paths]
            except (ValueError, OSError, AttributeError):
                pass
            return {"ok": False, "error": str(exc), **files}

    def _slider_run_dir(self, project_name, run_id):
        if not self._valid_project_name(str(project_name or "")):
            raise ValueError("项目名称无效。")
        if not isinstance(self.core.load_project(str(project_name or "")), dict):
            raise ValueError("项目不存在。")
        if not isinstance(run_id, str) or not re.fullmatch(r"\d{8}_\d{6}_[a-f0-9]{8}", run_id):
            raise ValueError("滑块训练记录无效。")
        root = Path(self.core.data_sub("output", str(project_name), "slider_runs"))
        target = root / run_id
        if root.is_symlink() or target.is_symlink() or not target.is_dir():
            raise ValueError("滑块训练记录不存在。")
        return target

    def get_slider_results(self, project_name, run_id=""):
        try:
            if not self._valid_project_name(str(project_name or "")): raise ValueError("项目名称无效。")
            if not isinstance(self.core.load_project(str(project_name or "")), dict):
                raise ValueError("项目不存在。")
            root = Path(self.core.data_sub("output", str(project_name), "slider_runs"))
            runs = sorted((p.name for p in root.iterdir() if p.is_dir() and not p.is_symlink()
                           and re.fullmatch(r"\d{8}_\d{6}_[a-f0-9]{8}", p.name)), reverse=True)[:50] if root.is_dir() else []
            if not runs: return {"ok": True, "runs": [], "result": None}
            chosen = str(run_id or runs[0])
            folder = self._slider_run_dir(project_name, chosen)
            path = folder / "result.json"
            result = json.loads(path.read_text(encoding="utf-8")) if path.is_file() and path.stat().st_size <= 2_000_000 else None
            checkpoints = [p.name for p in sorted(folder.glob("*.safetensors")) if p.is_file() and not p.is_symlink()]
            review = folder / "user_review.json"
            return {"ok": True, "runs": runs, "run_id": chosen, "result": result, "checkpoints": checkpoints,
                    "review": json.loads(review.read_text(encoding="utf-8")) if review.is_file() and review.stat().st_size < 10_000 else None}
        except (ValueError, OSError) as exc:
            return {"ok": False, "error": str(exc)}

    def get_slider_sample(self, project_name, run_id, name):
        try:
            folder = self._slider_run_dir(project_name, run_id)
            report = self.get_slider_results(project_name, run_id)
            allowed = {row["name"] for row in (report.get("result") or {}).get("comparisons", [])}
            if name not in allowed: raise ValueError("该图片不在本次权重对照清单中。")
            return {"ok": True, **image_preview(folder, name, full=True, max_size=(6000, 1600))}
        except (ValueError, OSError) as exc:
            return {"ok": False, "error": str(exc)}

    def review_slider_result(self, project_name, run_id, review):
        guard = self._agent_guard()
        if guard: return guard
        try:
            folder = self._slider_run_dir(project_name, run_id)
            keys = {"checkpoint", "direction_ok", "preservation_ok", "generalization_ok"}
            if not isinstance(review, dict) or set(review) != keys or any(not isinstance(review[k], bool) for k in keys - {"checkpoint"}):
                raise ValueError("效果核对内容无效。")
            report = self.get_slider_results(project_name, run_id)
            if review["checkpoint"] not in report.get("checkpoints", []) or not self.core._safetensors_complete(str(folder / review["checkpoint"])):
                raise ValueError("所选检查点不存在或文件不完整。")
            from kohya_core.fizgig_engine import _write
            _write(folder / "user_review.json", {**review, "reviewed": time.time(), "quality": "user_confirmed" if all(review[k] for k in keys - {"checkpoint"}) else "needs_review"})
            return {"ok": True}
        except (ValueError, OSError) as exc:
            return {"ok": False, "error": str(exc)}

    def export_slider_checkpoint(self, project_name, run_id, checkpoint):
        guard = self._agent_guard()
        if guard: return guard
        staged = None
        try:
            folder = self._slider_run_dir(project_name, run_id)
            report = self.get_slider_results(project_name, run_id)
            if not isinstance(checkpoint, str) or checkpoint not in report.get("checkpoints", []):
                raise ValueError("所选检查点不在本次训练记录中。")
            source = folder / checkpoint
            if not self.core._safetensors_complete(str(source)):
                raise ValueError("所选检查点尚未写完或文件不完整，请稍后再导出。")
            if self._window is None: raise ValueError("请在桌面程序中导出 LoRA。")
            import webview
            selected = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=checkpoint,
                                                      file_types=("LoRA (*.safetensors)",))
            if not selected: return {"ok": True, "message": "已取消 LoRA 导出。"}
            target = Path(selected[0] if isinstance(selected, (list, tuple)) else selected)
            if target.suffix.lower() != ".safetensors": target = target.with_name(target.name + ".safetensors")
            if target.resolve() == source.resolve(): return {"ok": True, "message": "所选位置就是原始检查点。"}
            import shutil
            import tempfile
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".slider_export_", suffix=".tmp", delete=False) as stream:
                staged = Path(stream.name)
            shutil.copyfile(source, staged)
            staged.replace(target)
            staged = None
            return {"ok": True, "message": "所选滑块 LoRA 已导出；原始检查点保留。"}
        except (ValueError, OSError, RuntimeError) as exc:
            return {"ok": False, "error": "滑块 LoRA 导出失败：%s" % exc}
        finally:
            if staged is not None:
                try: staged.unlink(missing_ok=True)
                except OSError: pass

    def prepare_training(self, project_name):
        """Run read-only preflight for a modern workspace's directly supported path."""
        guard = self._agent_guard()
        if guard:
            return guard
        with self._task_lock:
            if self._assistant_request and self._assistant_request.get("status") == "running":
                return {"ok": False, "error": "助手正在处理请求，请等待回复或先停止助手，再开始训练。"}
        project_name = str(project_name or "").strip()
        config = self.core.load_project(project_name) if project_name else None
        if not isinstance(config, dict):
            return {"ok": False, "error": "项目不存在或配置文件已损坏。"}
        if config.get("training_kind") == "slider":
            try:
                from kohya_core.slider_training import prepare
                return prepare(self.core, config, project_name)
            except (ValueError, RuntimeError, OSError) as exc:
                return {"ok": False, "error": str(exc)}
        mode = str(config.get("mode") or "")
        if mode in ("qwen_image", "zimage"):
            result = self._prepare_qwen_training(project_name)
        elif mode in ("character", "style", "concept"):
            result = self._prepare_anima_training(project_name, config)
        else:
            result = self._prepare_engine_training(project_name, config)
        if result.get("ok") and result.get("plan"):
            result["plan"]["config_summary"] = self._classic_training_params(config, project_name)
            supports = getattr(self.core, "param_supports", lambda *_: False)
            result["plan"]["config_supports"] = {key: bool(supports(key, mode)) for key in ("quant_mode", "batch_size", "gc")}
            interval_unit = getattr(self.core, "interval_unit_for", lambda *_: "steps")
            save_unit = interval_unit(mode, "save_every")
            result["plan"]["save_interval_unit"] = save_unit
            try:
                requested_save = int(result["plan"]["config_summary"].get("save_every") or 0)
            except (TypeError, ValueError):
                requested_save = 0
            effective_save = requested_save if requested_save > 0 else (1 if save_unit == "epochs" else 200)
            if mode in ("style", "character", "concept"):
                effective_save = max(50, effective_save)
            result["plan"]["save_interval_effective"] = effective_save
            result["plan"]["sampling_rule"] = self._sampling_rule(mode, result["plan"]["config_summary"], result["plan"])
            params = result["plan"]["config_summary"]
            try:
                getattr(self.core, "_sample_seed", lambda p: int(p.get("sample_seed") or 1234))(params)
            except (ValueError, TypeError) as exc:
                return {"ok": False, "error": str(exc)}
            result["plan"]["execution_summary"] = self._execution_summary(mode, params, result["plan"])
        return result

    def _execution_summary(self, mode, params, plan):
        """Describe settings actually specified by our entry points without inventing engine defaults."""
        kohya = mode in ("style", "character", "concept")
        train_te = kohya and params.get("train_text_encoder", True) and params.get("base_type") != "anima"
        rows = [{"label": "文本编码器训练", "value": "参与训练；起始学习率 %s" % params.get("te_lr") if train_te else "不参与训练；其学习率不生效"}]
        if mode in FIZGIG_FAMILIES and params.get("fizgig_version") == FIZGIG_TARGET:
            rows += [{"label": "引擎版本", "value": "Fizgig v7.0.1 · 普通 LoRA"},
                     {"label": "学习率计划", "value": "Qwen 官方预设接管" if mode == "qwen21_fz" else "constant；无学习率预热"}]
        elif kohya or mode in ("krea2_fz", "flux2_fz"):
            rows += [{"label": "学习率计划", "value": "cosine（余弦衰减）；输入的是起始学习率"},
                     {"label": "学习率预热", "value": "120 步；与模型加载、缓存及编译预热不同"}]
        elif mode == "qwen21_fz":
            rows.append({"label": "学习率计划", "value": "官方预设接管；Fast / Standard 自适应，Style 固定"})
        else:
            rows.append({"label": "学习率计划", "value": "工具未指定调度 / 学习率预热，使用当前引擎默认"})
        if mode in ("video", "qwen_image", "zimage"):
            steps = max(100, min(3000 if mode == "video" else 6000, int(params.get("video_steps") or 2000)))
            rows.append({"label": "实际步数限制", "value": "%d 步（入口范围 %d–%d）" % (steps, 100, 3000 if mode == "video" else 6000)})
        else:
            rows.append({"label": "训练量口径", "value": "轮数 × 每轮批次数；重复目录、过滤及分桶会改变总步数。启动后的生效参数和进度为准"})
        if kohya and params.get("base_type") == "sdxl":
            rows.append({"label": "SDXL 分辨率", "value": "默认 512 是资源起点；请查看处理后图片细节，再按显存自行调高"})
        rows.append({"label": "采样失败边界", "value": "Fizgig 部分入口可停用后续预览；其他入口的采样异常仍可能中断训练，不能保证隔离"})
        return rows

    def _sampling_rule(self, mode, params, plan):
        """开训前展示有效的采样开关和间隔，不猜测预处理后的精确步数。"""
        vram = plan.get("vram_gb")
        enabled = bool(getattr(self.core, "_sample_preview_enabled", lambda p, v: p.get("sample_preview") if p.get("sample_preview") is not None else v is None or v >= 20)(params, vram))
        reason = "手动开启" if params.get("sample_preview") is True else "手动关闭" if params.get("sample_preview") is False else "按显存自动开启" if enabled else "按显存自动关闭（低于 20GB）"
        fast = str(params.get("fast_tier") or "auto").lower()
        fast_arch = mode
        if mode in ("qwen_image", "zimage"):
            try:
                fast_arch = getattr(self.core, "at_image_info", lambda m: {"arch": m})(mode).get("arch", mode)
            except Exception:
                pass
        if params.get("sample_preview") is not True and fast_arch in ("qwen_image", "zimage") and (fast == "on" or (fast == "auto" and mode == "zimage" and vram is not None and vram < 10)):
            enabled, reason = False, "额外省显存档的自动策略关闭采样（可手动开启，需额外显存）"
        if enabled and mode == "krea2_fz" and params.get("fizgig_version") != FIZGIG_TARGET and not getattr(self.core, "krea2_model_files", lambda: {"turbo": True})().get("turbo"):
            enabled, reason = False, "缺少 Turbo 预览模型，本次不采样"
        try:
            interval = int(params.get("sample_interval") or 0)
        except (TypeError, ValueError):
            interval = 0
        unit = getattr(self.core, "interval_unit_for", lambda *_: "steps")(mode, "sample_interval")
        if interval > 0:
            cadence = "每 %d %s" % (interval, "轮" if unit == "epochs" else "步")
        elif unit == "epochs":
            cadence = "按图集大小估算约每 100 步一次，至少每 1 轮"
        elif mode in ("style", "character", "concept", "krea2", "flux2"):
            cadence = "跟随模型保存节奏（实际步数在训练启动后确定）"
        else:
            cadence = "每 250 步"
        if interval > 0 and unit == "steps" and interval < 10:
            cadence += "；间隔很短，可能显著增加耗时或显存占用"
        if interval > 0 and unit == "epochs" and interval > int(params.get("max_epochs") or 1):
            cadence += "；超过总轮数，训练中可能没有定期采样"
        if mode == "h3_fz":
            cadence += "；视频/音频请到输出目录查看，预览窗口只显示图片"
        if mode in FIZGIG_FAMILIES and params.get("fizgig_version") == FIZGIG_TARGET:
            cadence += "；开始时不额外采样，最后一轮只有满足间隔才采样"
        return {"enabled": enabled, "reason": reason, "cadence": cadence, "unit": unit}

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

        if mode in FIZGIG_FAMILIES and params.get("fizgig_version") == FIZGIG_TARGET:
            try:
                validate_fizgig_models(self.core, FIZGIG_FAMILIES[mode], fizgig_models(self.core, FIZGIG_FAMILIES[mode], params))
            except (ValueError, RuntimeError, OSError) as exc:
                return {"ok": False, "error": str(exc)}
        warnings = []
        if mode in ("anima_fz", "sdxl_fz"):
            warnings.append("当前为上游实验性普通 LoRA 入口；文本编码器冻结，具体训练效果需自行观察采样。")
        min_count = int(getattr(self.core, "MIN_IMAGES", {}).get(mode, 15))
        media_summary = None
        if mode == "h3_fz":
            try:
                media_summary = self.core.scan_fizgig_h3_dataset(raw_dir)
            except Exception as exc:
                return {"ok": False, "error": "H3 混合媒体数据集预检失败：%s" % exc}
            image_count = int(media_summary.get("total", 0) or 0)
            missing_captions = media_summary.get("missing_captions", 0)
            missing_captions = len(missing_captions) if isinstance(missing_captions, (list, tuple, set)) else int(missing_captions or 0)
            if image_count < min_count:
                return {"ok": False, "error": "H3 混合媒体目录只有 %d 个样本；至少需要 %d 个。" % (image_count, min_count)}
            if missing_captions:
                return {"ok": False, "error": "有 %d 个 H3 媒体文件缺少同名 .txt 字幕；请补齐后再训练。" % missing_captions}
            has_audio = int(media_summary.get("audio", 0) or 0) > 0
            has_video = int(media_summary.get("videos", 0) or 0) > 0
            if has_audio:
                try:
                    audio_missing = list(self.core.h3_fz_missing_models(require_audio=True))
                except Exception as exc:
                    return {"ok": False, "error": "无法检查 H3 音频模型：%s" % exc}
                if audio_missing:
                    return {"ok": False, "error": "当前数据集含音频，训练前还需准备音频 VAE：\n%s\n\n模型目录：%s" % (
                        "\n".join(str(item) for item in audio_missing), details.get("asset_dir") or "未指定")}
            elif has_video:
                try:
                    audio_vae_ready = bool(self.core.h3_fz_model_files().get("audio_vae"))
                except Exception:
                    audio_vae_ready = False
                if not audio_vae_ready:
                    warnings.append("视频含音轨但未准备音频 VAE；引擎会忽略声音，仅训练视频画面。")
            model_label = "MiniMax H3（Fizgig，全模态）"
            schedule_value = "%d 轮 · 预览 %d 帧" % (params.get("max_epochs") or 50, params.get("video_frames") or 56)
            steps = 0
        elif mode == "video":
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
            model_label = "MiniMax H3（AI Toolkit 视频）"
            aligned_frames = getattr(self.core, "h3_align_frames", lambda value: value)(params.get("video_frames") or 73)
            steps = max(100, min(getattr(self.core, "H3_MAX_STEPS", 3000), int(params.get("video_steps") or 2000)))
            schedule_value = "%d 步 · %d 帧" % (steps, aligned_frames)
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
        if vendor == "amd" and mode in ("qwen21_fz", "h3_fz"):
            warnings.append("Fizgig AMD ROCm 通道为实验性兼容路径；此模式的训练兼容性尚未验证。")
        if vendor != "amd":
            try:
                if not self.core.detect_nvidia_gpu():
                    warnings.append("没有检测到 NVIDIA GPU；请确认训练环境支持当前显卡。")
            except Exception:
                pass
        plan_rank = params["rank"]
        plan_alpha = params["alpha"]
        plan_learning_rate = str(params["unet_lr"])
        if mode == "qwen21_fz":
            qwen_preset = str(params.get("fizgig_qwen_preset") or "auto").lower()
            if qwen_preset == "auto":
                qwen_preset = "style" if str(params.get("at_sub_mode") or "character") == "style" else "fast"
            qwen_plan = {
                "fast": (8, 8, "Adaptive 2e-4~4e-4"),
                "standard": (16, 16, "Adaptive 1e-4~2e-4"),
                "style": (16, 16, "Flat 1.5e-4"),
            }
            plan_rank, plan_alpha, plan_learning_rate = qwen_plan.get(qwen_preset, qwen_plan["fast"])
            model_label = "Qwen-Image-2.1（Fizgig %s 预设）" % qwen_preset.title()
        resume_path = self._resume_path(project_name, mode, params)
        plan = {
            "project_name": project_name, "mode": mode,
            "mode_label": self.core.MODE_LABELS.get(mode, mode),
            "training_engine": self._engine_kind_for_mode(mode),
            "engine_label": ("Fizgig · " + params.get("fizgig_version", "")) if mode in FIZGIG_FAMILIES else self._engine_label_for_mode(mode),
            "model_label": model_label,
            "model_path": str(params.get("base_model") or details.get("asset_dir") or "由引擎管理"),
            "model_download_required": False, "model_size": "",
            "raw_dir": raw_dir, "image_count": image_count, "min_images": min_count,
            "data_count": image_count,
            "data_label": "混合媒体样本" if mode == "h3_fz" else ("视频" if mode == "video" else "图片"),
            "data_unit": "个" if mode == "h3_fz" else ("段" if mode == "video" else "张"),
            "media_summary": media_summary,
            "training_type": params.get("at_sub_mode") or mode,
            "training_target": "冻结底模和文本编码器，只训练普通 LoRA" if mode in FIZGIG_FAMILIES else "按当前模式调用已有训练引擎入口",
            "schedule_label": "训练计划", "schedule_value": schedule_value,
            "rank": plan_rank, "alpha": plan_alpha,
            "learning_rate": plan_learning_rate, "resolution": getattr(self.core, "h3_align_resolution", lambda value: value)(params["resolution"]) if mode == "video" else params["resolution"],
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
                "qwen21_fz": "fizgig", "h3_fz": "fizgig", "anima_fz": "fizgig", "sdxl_fz": "fizgig",
                "video": "ai_toolkit", "krea2_at": "ai_toolkit", "qwen_image": "ai_toolkit", "zimage": "ai_toolkit"}.get(mode, "unknown")

    @staticmethod
    def _engine_label_for_mode(mode):
        return {"style": "Kohya / sd-scripts", "character": "Kohya / sd-scripts", "concept": "Kohya / sd-scripts",
                "krea2": "musubi-tuner", "flux2": "musubi-tuner", "krea2_fz": "Fizgig", "flux2_fz": "Fizgig",
                "qwen21_fz": "Fizgig", "h3_fz": "Fizgig", "anima_fz": "Fizgig", "sdxl_fz": "Fizgig",
                "video": "AI Toolkit", "krea2_at": "AI Toolkit", "qwen_image": "AI Toolkit", "zimage": "AI Toolkit"}.get(mode, "训练引擎")

    def _resume_path(self, project_name, mode, params):
        if mode in ("video", "krea2_at", "qwen_image", "zimage"):
            return None  # AI Toolkit trainers do not consume resume_from.
        try:
            output_dir = self.core.data_sub("output", project_name)
            output_name = self.core.output_name_for(mode, params.get("style_preset"))
            if mode in FIZGIG_FAMILIES:
                return self.core.find_fizgig_state(output_dir, output_name, params.get("fizgig_version"), FIZGIG_FAMILIES[mode], params.get("max_epochs"))
            if mode in ("krea2", "flux2"):
                return self.core.find_musubi_state(output_dir, output_name)
            return self.core.find_latest_state(output_dir, output_name)
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
                return {"ok": False, "error": "检测到 AMD 显卡；请先在训练页顶部开启 AMD 兼容模式，再开始训练。"}
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

        resume_path = self._resume_path(project_name, params["mode"], params)
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
        return training_params(self.core, config, project_name)

    def _classic_training_params(self, config, project_name):
        """Normalize an engine project's saved fields to the legacy trainer contract."""
        mode = str(config.get("mode") or "")
        if mode in ("character", "style", "concept"):
            return self._anima_training_params(config, project_name)
        if mode in ("qwen_image", "zimage"):
            return self._qwen_training_params(config, project_name)
        return training_params(self.core, config, project_name)

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
        if params["base_model"].lower().endswith(".safetensors"):
            try:
                from kohya_core.anima_ckpt import validate_safetensors_layout
                validate_safetensors_layout(params["base_model"])
            except (ValueError, OSError, UnicodeError) as exc:
                return {"ok": False, "error": "底模文件检查未通过：%s" % exc}
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

        resume_path = self._resume_path(project_name, params["mode"], params)
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

    def _history_store(self):
        return TrainingHistory(self.core.data_sub("training_runs"))

    def list_training_runs(self, project_name=""):
        try:
            records = self._history_store().list(str(project_name or ""))
            with self._task_lock:
                active_id = (self._task or {}).get("id")
            for record in records:
                if record.get("status") in ("running", "awaiting_review") and record["id"] != active_id:
                    record.update(status="interrupted", message="上次任务没有正常结束；可检查输出目录中的快照。")
            return {"ok": True, "runs": records}
        except Exception as exc:
            return {"ok": False, "error": "读取训练记录失败：%s" % exc}

    def get_training_run(self, run_id):
        try:
            return {"ok": True, "run": self._history_store().get(str(run_id))}
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": "读取训练记录失败：%s" % exc}

    def restore_training_run(self, run_id, project_name):
        guard = self._agent_guard()
        if guard:
            return guard
        with self._task_lock:
            if self._task and self._task.get("status") in ("running", "awaiting_review"):
                return {"ok": False, "error": "请等当前任务结束后再恢复设置。"}
            result = self.get_training_run(run_id)
            if not result.get("ok"):
                return result
            record = result["run"]
            project_name = str(project_name or "")
            current = self.core.load_project(project_name)
            if not current or record.get("project_name") != project_name:
                return {"ok": False, "error": "请在原项目内恢复设置；项目已改名或删除时请手动参考记录。"}
            patch = dict(record.get("config") or {})
            saved_params = patch.get("params") if isinstance(patch.get("params"), dict) else {}
            patch["params"] = {key: saved_params.get(key) for key in WORKSPACE_PARAM_KEYS}
            for key, default in {"trigger": "", "style_preset": "自定义", "style_caption": "",
                                 "at_sub_mode": "character", "concept_type": "form", "fast_tier": "auto",
                                 "global_pos": "", "global_neg": "", "unet_only": False}.items():
                patch.setdefault(key, default)
            # Preserve current media and model locations; historical settings
            # are reused without silently selecting another dataset or engine.
            if patch.get("mode") != current.get("mode") or patch.get("base_type") != current.get("base_type"):
                return {"ok": False, "error": "当前模式或底模类型已变化，不能直接恢复这条记录。"}
            for key in ("raw_dir", "reg_dir", "base_model", "train_env"):
                patch.pop(key, None)
            if current.get("training_kind") == "slider":
                if patch.get("training_kind") != "slider":
                    return {"ok": False, "error": "这条记录不是滑块训练，不能替换当前滑块目标。"}
                from kohya_core.slider_project import normalize
                restored = normalize(patch.get("slider"))
                present = normalize(current.get("slider"))
                for key in ("positive_dir", "negative_dir", "pairs"):
                    restored[key] = present[key]
                patch["slider"] = restored
            return self.save_project_config(project_name, patch)

    def start_training(self, project_name, use_resume=False):
        """Run an existing engine pipeline without opening the classic Tk workspace."""
        project_name = str(project_name or "").strip()
        if (self.core.load_project(project_name) or {}).get("training_kind") == "slider":
            from kohya_core.slider_task import start
            return start(self, project_name, use_resume)
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
        task_id = self._begin_task("%s 训练" % plan["mode_label"], "training", mode=plan["mode"], key=project_name)
        if not task_id:
            return {"ok": False, "error": "已有环境、模型或训练任务正在运行，请等它完成后再试。"}
        review_event = threading.Event()
        try:
            baseline = {item["name"]: item["version"] for item in sample_files(self.core.data_sub("output", project_name), 0)}
        except OSError:
            baseline = {}
        with self._task_lock:
            if self._task and self._task.get("id") == task_id:
                self._task["review_event"] = review_event
                self._task["plan"] = plan
                self._task["sample_baseline"] = baseline
                self._task["normalized_params"] = dict(params)
        self.core.reset_stop()
        getattr(self.core, "reset_effective", lambda: None)()
        root_keys = ("mode", "base_type", "at_sub_mode", "concept_type", "fast_tier", "trigger",
                     "raw_dir", "reg_dir", "base_model", "style_preset", "style_caption",
                     "train_env", "unet_only", "global_pos", "global_neg")
        record_config = {key: config[key] for key in root_keys if key in config}
        stored_params = config.get("params") if isinstance(config.get("params"), dict) else {}
        record_config["params"] = {key: value for key, value in stored_params.items() if key in WORKSPACE_PARAM_KEYS}
        with self._task_lock:
            if self._task and self._task.get("id") == task_id:
                self._task["project_config"] = record_config
        with self._task_lock:
            task_state = self._task
            started = task_state["started"]
        run_record = {"id": task_id, "project_name": project_name, "mode": params["mode"],
                      "mode_label": plan["mode_label"], "started": started, "ended": None,
                      "status": "running", "message": "准备训练", "config": record_config,
                      "normalized_params": dict(params), "resume_path": str(resume_path or "")}
        try:
            self._history_store().save(run_record)
        except Exception as exc:
            self._task_log(task_id, "[WARN] 训练记录暂时无法保存：%s" % exc)

        def worker():
            import tempfile

            report_path = os.path.join(tempfile.gettempdir(), "kohya_modern_preprocess_%s.json" % task_id)
            monitor = None
            monitor_stop = threading.Event()
            monitor_thread = None
            try:
                self._release_agent_model_for_task(task_id)
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
                elif params["mode"] == "h3_fz":
                    media_summary = self.core.scan_fizgig_h3_dataset(params["raw_dir"])
                    processed_count = int(media_summary.get("total", 0) or 0)
                    missing_captions = media_summary.get("missing_captions", 0)
                    missing_captions = len(missing_captions) if isinstance(missing_captions, (list, tuple, set)) else int(missing_captions or 0)
                    self._task_log(task_id, "[预处理] H3 混合媒体扫描：图片 %d，视频 %d，音频 %d，总计 %d，缺字幕 %d；不移动、不转码。" % (
                        int(media_summary.get("images", 0) or 0), int(media_summary.get("videos", 0) or 0),
                        int(media_summary.get("audio", 0) or 0), processed_count, missing_captions,
                    ))
                    if missing_captions:
                        raise RuntimeError("有 %d 个媒体文件缺少同名 .txt 字幕；请补齐后再训练。" % missing_captions)
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
                        "keep_user_captions": params["keep_user_captions"],
                        "caption_method": params.get("caption_method", "wd14"),
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
                    label = "可用视频" if params["mode"] == "video" else "可用混合媒体样本" if params["mode"] == "h3_fz" else "可用图片"
                    raise RuntimeError("预处理后只有 %d 个%s；%s 至少需要 %d。" % (
                        processed_count, label, plan["mode_label"], plan["min_images"]))
                engine_name = plan.get("engine_label") or self._engine_label_for_mode(params["mode"])
                review_message = ("视频字幕检查完成；确认后启动 %s。" % engine_name if params["mode"] == "video"
                                  else "混合媒体扫描完成；确认字幕与样本后启动 %s。" % engine_name if params["mode"] == "h3_fz"
                                  else "可以打开标签编辑器查看或修改标签；确认后才会启动 %s。" % engine_name)
                with self._task_lock:
                    task = self._task
                    tagger_incomplete = bool(task and task.get("id") == task_id and any(
                        "[WARN] WD14 打标后仍有" in line for line in task.get("logs", ())))
                if tagger_incomplete:
                    review_message = "自动打标有缺失，部分图片使用了简短兜底标签。请打开标签编辑器核对并补齐，再决定是否继续训练。"
                self._task_log(task_id, "[预处理] 已完成，可用数据 %d 个。请检查数据后确认是否继续训练。" % processed_count)
                with self._task_lock:
                    if self._task and self._task.get("id") == task_id:
                        self._task["dataset_directory"] = params["raw_dir"] if params["mode"] in ("video", "h3_fz") else self.core.dataset_train_dir(params["mode"], project_name)
                        self._task.update(
                            status="awaiting_review",
                            message=("自动打标有缺失，请核对标签。" if tagger_incomplete else
                                     "数据检查已完成，请确认后继续训练。" if params["mode"] in ("video", "h3_fz") else
                                     "预处理已完成，请检查图片和标签。"),
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
                        effective = getattr(self.core, "get_effective", lambda: {})()
                        with self._task_lock:
                            if self._task and self._task.get("id") == task_id:
                                self._task.setdefault("effective_params", {}).update(effective)
                        self._record_training_metrics(task_id, snapshot)
                        total = int(snapshot.get("total") or 0)
                        step = int(snapshot.get("step") or 0)
                        speed = float(snapshot.get("speed") or 0)
                        eta = snapshot.get("eta")
                        eta_seconds = (max(0, int(eta)) if isinstance(eta, (int, float))
                                       and math.isfinite(eta) and total > 0 and step < total else None)
                        loss = snapshot.get("loss")
                        detail = ("Step %d / %d" % (step, total)) if total else (snapshot.get("phase_label") or "正在加载 / 缓存模型")
                        if speed > 0:
                            detail += " · %.2f step/s" % speed
                        if loss is not None:
                            detail += " · loss %s" % loss
                        with self._task_lock:
                            if self._task and self._task.get("id") == task_id and self._task.get("status") == "running":
                                self._task.update(
                                    message="训练中",
                                    progress=(min(1.0, max(0.0, step / total)) if total else None),
                                    eta_seconds=eta_seconds,
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
                elif mode == "qwen21_fz":
                    self.core.train_qwen21_fizgig(
                        lambda line: self._task_log(task_id, line), mode=mode, params=params,
                        vram_gb=plan.get("vram_gb"), resume_from=resume_path, progress=monitor,
                    )
                elif mode in ("anima_fz", "sdxl_fz"):
                    self.core.train_fizgig_lora(lambda line: self._task_log(task_id, line), mode=mode, params=params,
                        vram_gb=plan.get("vram_gb"), resume_from=resume_path, progress=monitor)
                elif mode == "h3_fz":
                    params["train_data_dir"] = params.get("raw_dir") or ""
                    self.core.train_h3_fizgig(
                        lambda line: self._task_log(task_id, line), mode=mode, params=params,
                        vram_gb=plan.get("vram_gb"), resume_from=resume_path, progress=monitor,
                    )
                else:
                    raise RuntimeError("新版训练页尚未注册「%s」训练模式。" % mode)
                self._record_training_metrics(task_id, monitor.snapshot())
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
                latest = self._resume_path(project_name, params.get("mode"), params)
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
                self._task_log(task_id, traceback.format_exc())
            finally:
                monitor_stop.set()
                if monitor is not None:
                    try:
                        monitor.finish()
                    except Exception:
                        pass
                if monitor_thread is not None:
                    monitor_thread.join(timeout=1)
                if monitor is not None:
                    self._record_training_metrics(task_id, monitor.snapshot())
                with self._task_lock:
                    task_state.setdefault("effective_params", {}).update(getattr(self.core, "get_effective", lambda: {})())
                    final_task = dict(task_state)
                run_record.update(ended=time.time(), status=final_task.get("status", "interrupted"),
                                  message=redact(final_task.get("message", "")),
                                  metrics=final_task.get("metrics"),
                                  loss_history=list(final_task.get("loss_history", [])),
                                  logs=[redact(line) for line in final_task.get("logs", [])[-300:]],
                                  effective_params=final_task.get("effective_params", {}),
                                  sampling_rule=plan.get("sampling_rule"),
                                  sampling_status=final_task.get("sampling_status", {}))
                try:
                    self._history_store().save(run_record)
                except Exception as exc:
                    self._task_log(task_id, "[WARN] 本次训练记录保存失败：%s" % exc)
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
        guard = self._agent_guard()
        if guard:
            return guard
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
        guard = self._agent_guard()
        if guard:
            return guard
        if not self.core.clear_env_paths():
            return {"ok": False, "error": "恢复自动检测失败。"}
        self._log("[环境] 已恢复自动查找 Python / Git。")
        return self.get_env_locations()

    def report_ui_startup(self, stage, detail=""):
        return self._startup.frontend_report(str(stage), str(detail)) if self._startup else {"ok": False}

    def open_ui_startup_report(self):
        return self._startup.open_report() if self._startup else {"ok": False}

    def use_classic_ui(self):
        with self._task_lock:
            if self._task and self._task.get("status") in ("running", "starting"):
                return {"ok": False, "error": "当前有任务运行，请先正常停止任务。"}
        if self._agent_guard():
            return {"ok": False, "error": "助手正在执行任务，请先停止助手。"}
        return self._startup.request_classic() if self._startup else {"ok": False}

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
            if template.get("visible", True)
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
            if not template.get("visible", True) or name in existing_template_names:
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
            "model_catalog": model_catalog(self.core),
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
                "training_kind": item.get("training_kind", "standard"),
                "mode_label": "概念滑块 LoRA" if item.get("training_kind") == "slider" else self._plain_mode_label(labels.get(mode, mode)),
                "base_type": str(item.get("base_type", "")),
                "base_type_label": base_labels.get(item.get("base_type", ""), str(item.get("base_type", ""))),
                "raw_dir": str(item.get("raw_dir", "")),
                "base_model": str(item.get("base_model", "")),
            })
        return projects

    def get_assistant_service(self):
        try:
            with self._assistant_lock:
                request = self._assistant_request
                active = {key: request.get(key) for key in ("id", "project", "status")} if request else None
                return {"ok": True, "settings": self._assistant_settings.public(), "request": active}
        except Exception:
            return {"ok": False, "error": "无法读取助手设置。"}

    def save_assistant_service(self, settings):
        guard = self._agent_guard()
        if guard:
            return guard
        from kohya_core.captioning import CaptionError
        try:
            if not isinstance(settings, dict):
                return {"ok": False, "error": "助手设置格式无效。"}
            with self._assistant_lock:
                if self._assistant_request and self._assistant_request["status"] == "running":
                    return {"ok": False, "error": "请先停止助手请求。"}
                return {"ok": True, "settings": self._assistant_settings.save(settings)}
        except CaptionError as exc:
            return {"ok": False, "error": str(exc).replace("描述", "助手").replace("视觉模型", "文字模型")}
        except Exception:
            return {"ok": False, "error": "无法保存助手设置。"}

    def start_assistant_request(self, project_name, options):
        guard = self._agent_guard()
        if guard:
            return guard
        from kohya_core.assistant import LABELS, BOUNDS, ask, validate_patch
        from kohya_core.captioning import CaptionError
        try:
            if not isinstance(options, dict):
                raise CaptionError("请求格式无效。")
            question = str(options.get("question") or "").strip()
            if not question or len(question) > 6000:
                raise CaptionError("请输入问题，长度不超过 6000 字。")
            project_name = str(project_name or "")
            config = self.core.load_project(project_name) if project_name else {}
            if not isinstance(config, dict):
                raise CaptionError("项目不存在。")
            with self._task_lock:
                task = self._task or {}
                if task.get("status") in ("running", "awaiting_review"):
                    raise CaptionError("当前有任务正在运行；请在任务结束后使用助手，避免争用资源。")
                task_key = str(task.get("key") or "")
                context_fields = ("kind", "mode", "status", "message") if task_key == project_name and project_name else ("kind", "status")
                task_context = {key: task.get(key) for key in context_fields}
                log_lines = list(task.get("logs", []))[-100:] if options.get("include_logs") and task_key == project_name and project_name else []
            service = self._assistant_settings.connection()
            if not service["local"] and options.get("allow_remote") is not True:
                raise CaptionError("在线助手需要允许发送本次问题、配置和所选日志。")
            mode = str(config.get("mode") or "character")
            effective = training_params(self.core, config, project_name) if project_name else {}
            allowed = {key: LABELS[key] for key in LABELS if project_name and self.core.param_supports(key, mode)}
            quant = list(getattr(self.core, "QUANT_MODE_OPTIONS", {}).get(mode, ()))
            if not quant:
                allowed.pop("quant_mode", None)
            if config.get("unet_only") or config.get("base_type") in ("flux", "anima"):
                allowed.pop("te_lr", None)
            if mode == "qwen21_fz":
                for key in ("rank", "alpha", "unet_lr"):
                    allowed.pop(key, None)
            context = {"project": project_name, "mode": config.get("mode"), "base_type": config.get("base_type"),
                       "saved_params": {key: (config.get("params") or {}).get(key) for key in LABELS},
                       "effective_params": {key: effective.get(key) for key in LABELS}, "allowed": allowed,
                       "engine_note": "Qwen 2.1 Fizgig 的 rank、alpha 和学习率由引擎预设决定，本版助手不修改。" if mode == "qwen21_fz" else "",
                       "numeric_ranges": {key: value for key, value in BOUNDS.items() if key in allowed},
                       "quant_modes": quant, "gc_options": ["auto", "开启", "关闭"],
                       "task": task_context, "logs": [redact(line) for line in log_lines],
                       "log_note": "仅同项目最近任务尾部，可能不完整" if log_lines else "未附加日志"}
            context = json.loads(redact(json.dumps(context, ensure_ascii=False)))
            with self._task_lock, self._assistant_lock:
                if not self._agent.mutation_allowed():
                    raise CaptionError("Agent 已经开始执行，请等待或先停止。")
                if (self._task or {}).get("status") in ("running", "awaiting_review"):
                    raise CaptionError("任务已经启动，请结束后再使用助手。")
                if self._assistant_request and self._assistant_request["status"] == "running":
                    raise CaptionError("助手已有请求正在处理。")
                request = {"id": uuid.uuid4().hex, "project": project_name, "status": "running", "answer": "",
                           "changes": [], "original": copy.deepcopy(config), "stop": threading.Event()}
                self._assistant_request = request

            def worker():
                def stop():
                    if request["stop"].is_set():
                        raise CaptionError("助手请求已停止；服务端可能仍在处理。")
                try:
                    result = ask(service, redact(question), context, stop)
                    patch = validate_patch(result["patch"], allowed, quant)
                    changes = [{"key": key, "label": LABELS[key], "before": effective.get(key), "after": value}
                               for key, value in patch.items() if effective.get(key) != value]
                    patch = {item["key"]: item["after"] for item in changes}
                    with self._assistant_lock:
                        stop()
                        request.update(status="completed", answer=result["answer"], patch=patch, changes=changes)
                except Exception as exc:
                    with self._assistant_lock:
                        request.update(status="cancelled" if request["stop"].is_set() else "failed",
                                       error=str(exc) if isinstance(exc, CaptionError) else "助手请求失败，未修改参数。")
            threading.Thread(target=worker, daemon=True, name="training-assistant").start()
            return {"ok": True, "id": request["id"]}
        except CaptionError as exc:
            return {"ok": False, "error": str(exc).replace("视觉模型", "文字模型")}
        except Exception:
            return {"ok": False, "error": "无法准备助手上下文，请检查项目和服务设置。"}

    def get_assistant_result(self, request_id):
        with self._assistant_lock:
            request = self._assistant_request
            if not request or request["id"] != request_id:
                return {"ok": False, "error": "助手请求已不存在。"}
            return {"ok": True, **{key: request.get(key) for key in ("id", "project", "status", "answer", "changes", "error", "applied", "undone")}}

    def stop_assistant_request(self, request_id):
        with self._assistant_lock:
            if not self._assistant_request or self._assistant_request["id"] != request_id:
                return {"ok": False, "error": "助手请求已不存在。"}
            self._assistant_request["stop"].set()
            return {"ok": True}

    def apply_assistant_proposal(self, request_id, undo=False):
        guard = self._agent_guard()
        if guard:
            return guard
        from kohya_core.captioning import _atomic_bytes
        if not isinstance(undo, bool):
            return {"ok": False, "error": "撤销选项格式无效。"}
        with self._task_lock, self._assistant_lock:
            request = self._assistant_request
            if not request or request["id"] != request_id or request["status"] != "completed":
                return {"ok": False, "error": "没有可应用的助手方案。"}
            if (self._task or {}).get("status") in ("running", "awaiting_review"):
                return {"ok": False, "error": "任务运行期间不能应用或撤销配置。"}
            if request.get("undone") or (not undo and request.get("applied")):
                return {"ok": False, "error": "此方案已经处理，请重新提问。"}
            if undo and not request.get("applied"):
                return {"ok": False, "error": "此方案尚未应用。"}
            name = request["project"]
            current = self.core.load_project(name)
            expected = request.get("after_config") if undo else request["original"]
            if current != expected:
                return {"ok": False, "error": "项目在提问后已有变化，为避免覆盖手动修改，请重新提问。"}
            patch = request.get("patch", {})
            if not patch:
                return {"ok": False, "error": "此回复没有参数修改。"}
            previous = request["original"].get("params") or {}
            values = {key: previous.get(key) for key in patch} if undo else patch
            path = Path(self.core.data_sub("logs")) / ("assistant_change_" + request_id + ("_undo" if undo else "") + ".json")
            try:
                _atomic_bytes(path, json.dumps({"status": "pending", "project": name, "undo": bool(undo),
                                               "params_before": {key: (current.get("params") or {}).get(key) for key in patch}, "patch": values},
                                              ensure_ascii=False, indent=2).encode("utf-8"))
            except OSError:
                return {"ok": False, "error": "无法保存配置修改记录，未应用方案。"}
            result = self.save_project_config(name, {"params": values})
            if not result.get("ok"):
                return result
            if undo:
                request["undone"] = True
            else:
                request["applied"] = True
                request["after_config"] = copy.deepcopy(self.core.load_project(name))
            try:
                _atomic_bytes(path, json.dumps({"status": "applied", "project": name, "undo": bool(undo),
                                               "params_before": {key: (current.get("params") or {}).get(key) for key in patch}, "patch": values},
                                              ensure_ascii=False, indent=2).encode("utf-8"))
            except OSError:
                self._log("[助手] 配置已保存，但修改记录状态写入失败。")
            return {"ok": True}

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
        guard = self._agent_guard()
        if guard:
            return guard
        name = str(name or "").strip()
        if not name or not isinstance(patch, dict):
            return {"ok": False, "error": "项目名称或配置内容无效。"}
        config = self.core.load_project(name)
        if not isinstance(config, dict):
            return {"ok": False, "error": "项目不存在或配置文件已损坏。"}

        config = dict(config)
        if patch.get("training_kind", config.get("training_kind", "standard")) not in ("standard", "slider"):
            return {"ok": False, "error": "训练任务类型无效。"}
        if "slider" in patch:
            try:
                from kohya_core.slider_project import normalize
                config["slider"] = normalize(patch["slider"])
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
        root_string_fields = {
            "mode", "base_type", "base_model", "raw_dir", "trigger", "reg_dir",
            "style_preset", "style_caption", "at_sub_mode", "concept_type", "fast_tier",
            "global_pos", "global_neg", "train_env", "training_kind",
        }
        root_bool_fields = {"unet_only"}
        param_fields = set(WORKSPACE_PARAM_KEYS)
        allowed_root_fields = root_string_fields | root_bool_fields | {"params", "slider"}
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

        if next_mode in ("anima_fz", "sdxl_fz") and patch.get("base_model"):
            try:
                from kohya_core.fizgig_adapter import validate_base
                validate_base(self.core, FIZGIG_FAMILIES[next_mode], config["base_model"])
            except (OSError, ValueError, RuntimeError) as exc:
                return {"ok": False, "error": str(exc)}
        params = dict(config.get("params")) if isinstance(config.get("params"), dict) else {}
        incoming_params = patch.get("params", {})
        if not isinstance(incoming_params, dict):
            return {"ok": False, "error": "训练参数格式无效。"}
        for key, value in incoming_params.items():
            if key not in param_fields:
                return {"ok": False, "error": "新版训练页尚未接入训练参数「%s」。" % key}
            if value is None:
                params.pop(key, None)
                continue
            if key == "fizgig_version" and value not in ("v6.5.0", FIZGIG_TARGET):
                return {"ok": False, "error": "未接入这个 Fizgig 版本。"}
            if key == "fizgig_version" and next_mode in ("anima_fz", "sdxl_fz") and value != FIZGIG_TARGET:
                return {"ok": False, "error": "Anima / SDXL Fizgig 项目需要 v7.0.1。"}
            allowed_quant = getattr(self.core, "QUANT_MODE_OPTIONS", {}).get(next_mode, ())
            if next_mode in FIZGIG_FAMILIES and (incoming_params.get("fizgig_version") or params.get("fizgig_version") or (FIZGIG_TARGET if next_mode in ("anima_fz", "sdxl_fz") else "v6.5.0")) == FIZGIG_TARGET:
                allowed_quant = (("auto", "int8", "nf4", "hqq") if next_mode == "h3_fz" else ("auto", "bf16", "int8", "nf4"))
            if key == "quant_mode" and value not in allowed_quant:
                return {"ok": False, "error": "当前训练模式不支持量化精度「%s」。" % value}
            if key == "sample_preview" and value is None:
                params.pop(key, None)
                continue
            caption_choices = {"caption_method": ("wd14", "natural", "existing"),
                               "caption_language": ("zh", "en"), "caption_length": ("brief", "detailed")}
            if key in caption_choices and value not in caption_choices[key]:
                return {"ok": False, "error": "图片描述选项无效。"}
            if key == "fizgig_qwen_preset" and value not in ("auto", "fast", "standard", "style"):
                return {"ok": False, "error": "Qwen-Image-2.1 训练预设无效。"}
            if key in BOOL_PARAM_KEYS:
                if not isinstance(value, bool):
                    return {"ok": False, "error": "训练参数「%s」必须为开关值。" % key}
            elif (not isinstance(value, (str, int, float))
                  or len(str(value)) > (32768 if key in ("sample_prompt", "global_pos", "global_neg") else 128)):
                return {"ok": False, "error": "训练参数「%s」的格式无效。" % key}
            params[key] = value
        if next_mode in FIZGIG_FAMILIES:
            version = params.get("fizgig_version") or (FIZGIG_TARGET if next_mode in ("anima_fz", "sdxl_fz") else "v6.5.0")
            allowed_quant = ((("auto", "int8", "nf4", "hqq") if next_mode == "h3_fz" else ("auto", "bf16", "int8", "nf4"))) if version == FIZGIG_TARGET else self.core.QUANT_MODE_OPTIONS.get(next_mode, ())
            if (params.get("quant_mode") or "auto") not in allowed_quant:
                return {"ok": False, "error": "所选引擎版本不支持已保存的量化精度，请同时改为自动或此版本支持的精度。"}
        config["params"] = params
        if config.get("training_kind") == "slider":
            try:
                from kohya_core.slider_project import parameters
                parameters(config, name)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}

        if not self.core.save_project(name, config):
            return {"ok": False, "error": "项目保存失败，请检查磁盘空间和写入权限。"}
        self._log("[项目] 已保存「%s」的训练配置。" % name)
        return {"ok": True, "project": next((p for p in self.list_projects() if p["name"] == name), None)}

    def inspect_dataset(self, directory):
        """Provide a read-only catalog; image reads require membership in this selected directory."""
        if not str(directory or "").strip():
            return {"ok": False, "error": "请先选择图片文件夹。"}
        try:
            root = Path(str(directory or "")).resolve()
            images = dataset_images(root)
            summary = caption_summary(root, images)
            names = [image.relative_to(root).as_posix() for image in images]
            token = uuid.uuid4().hex
            with self._task_lock:
                self._dataset_previews[token] = {"root": root, "names": set(names), "ordered": names}
                while len(self._dataset_previews) > 16:
                    self._dataset_previews.pop(next(iter(self._dataset_previews)))
            return {**summary, "preview_token": token, "preview_images": names[:100],
                    "next_offset": 100 if len(names) > 100 else None}
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": "无法检查图片文件夹：%s" % exc}

    def list_dataset_preview(self, token, offset=0):
        with self._task_lock:
            catalog = self._dataset_previews.get(str(token or ""))
        if not catalog:
            return {"ok": False, "error": "图集检查已过期，请重新检查。"}
        try:
            offset = max(0, int(offset or 0))
        except (TypeError, ValueError):
            offset = 0
        names = catalog["ordered"]
        return {"ok": True, "images": names[offset:offset + 100],
                "next_offset": offset + 100 if offset + 100 < len(names) else None}

    def get_dataset_preview(self, token, name):
        with self._task_lock:
            catalog = self._dataset_previews.get(str(token or ""))
        if not catalog or str(name or "") not in catalog["names"]:
            return {"ok": False, "error": "图片不在本次检查的图集中，请重新检查。"}
        try:
            image = image_preview(catalog["root"], name, full=True)
            try:
                caption = read_caption(catalog["root"] / name)
            except OSError:
                caption = ""
            return {"ok": True, "name": name, "caption": caption, **image}
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": "无法读取图片：%s" % exc}

    def inspect_task_dataset(self, task_id):
        with self._task_lock:
            task = self._task
            if not task or task.get("id") != str(task_id or "") or task.get("kind") != "training":
                return {"ok": False, "error": "训练任务已不存在。"}
            directory = task.get("dataset_directory")
            is_raw = task.get("mode") in ("video", "h3_fz")
        if not directory:
            return {"ok": False, "error": "图片预处理尚未完成。"}
        return {**self.inspect_dataset(directory), "source_kind": "raw_media" if is_raw else "processed"}

    @staticmethod
    def _picker_initial_directory(path):
        path = str(path or "").strip()
        if not path:
            return ""
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.isdir(path):
            return path
        parent = os.path.dirname(path)
        return parent if os.path.isdir(parent) else ""

    def choose_path(self, kind="folder", current_path="", memory_key=""):
        if self._window is None:
            return {"ok": False, "error": "文件选择器尚未就绪。"}
        try:
            import webview

            key = str(memory_key or kind or "folder")
            loader = getattr(self.core, "_load_app_settings", None)
            settings = loader() if callable(loader) else {}
            settings = settings if isinstance(settings, dict) else {}
            saved_dirs = settings.get("modern_ui_picker_dirs", {})
            saved_dirs = saved_dirs if isinstance(saved_dirs, dict) else {}
            directory = self._picker_initial_directory(current_path)
            if not directory:
                directory = self._picker_initial_directory(
                    self._picker_dirs.get("__last__") or settings.get("modern_ui_last_browse_dir")
                )
            if not directory:
                directory = self._picker_initial_directory(self._picker_dirs.get(key) or saved_dirs.get(key))

            if kind == "image":
                selected = self._window.create_file_dialog(
                    webview.FileDialog.OPEN,
                    directory=directory,
                    file_types=("Image files (*.png;*.jpg;*.jpeg;*.webp;*.bmp)",),
                )
            elif kind == "model":
                selected = self._window.create_file_dialog(
                    webview.FileDialog.OPEN,
                    directory=directory,
                    file_types=("Model files (*.safetensors;*.ckpt;*.pt;*.pth)", "All files (*.*)"),
                )
            else:
                selected = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=directory)
            if not selected:
                return {"ok": True, "cancelled": True, "path": ""}
            path = selected[0] if isinstance(selected, (list, tuple)) else selected
            path = str(path or "")
            chosen_dir = self._picker_initial_directory(path)
            if chosen_dir:
                self._picker_dirs["__last__"] = chosen_dir
                self._picker_dirs[key] = chosen_dir
                saver = getattr(self.core, "_save_app_settings", None)
                if callable(saver):
                    settings["modern_ui_last_browse_dir"] = chosen_dir
                    settings["modern_ui_picker_dirs"] = {**saved_dirs, key: chosen_dir}
                    saver(settings)
            return {"ok": True, "path": path}
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
        background_source = str(settings.get("modern_ui_background_source") or background).strip()
        if background_source:
            background_source = os.path.abspath(background_source)
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
        history_paths = ModernUIBridge._normalize_appearance_background_history(
            background_history, background, background_source
        )
        return {
            "theme": theme,
            "background_path": background,
            "background_source_path": background_source,
            "background_opacity": opacity,
            "background_available": bool(background and os.path.isfile(background)),
            "background_history": [
                {"path": path, "available": os.path.isfile(path)} for path in history_paths
            ],
            "component_opacity": component_opacity,
            "idle_fade_enabled": bool(idle_fade_enabled),
        }

    @staticmethod
    def _normalize_appearance_background_history(paths, selected="", selected_source=""):
        if not isinstance(paths, (list, tuple)):
            paths = []
        normalized = []
        seen = set()
        preferred = selected_source or selected
        for raw_path in ([preferred] if preferred else []) + list(paths):
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

    @staticmethod
    def _bundled_appearance_presets():
        root = _app_root() / "modern_ui" / "dist" / "themes"
        if not root.is_dir() and not getattr(sys, "frozen", False):
            root = _app_root() / "modern_ui" / "public" / "themes"
        return [
            {"id": "builtin-dark", "name": "深色示例", "built_in": True, "theme": "dark",
             "background_path": str(root / "dark.png"), "background_opacity": 90,
             "component_opacity": 80, "idle_fade_enabled": True},
            {"id": "builtin-light", "name": "浅色示例", "built_in": True, "theme": "light",
             "background_path": str(root / "light.png"), "background_opacity": 90,
             "component_opacity": 80, "idle_fade_enabled": True},
        ]

    def get_appearance_presets(self):
        settings = self.core._load_app_settings() or {}
        settings = settings if isinstance(settings, dict) else {}
        custom = settings.get("modern_ui_custom_presets", [])
        hidden = settings.get("modern_ui_hidden_builtin_presets", [])
        builtin_ids = {item["id"] for item in self._bundled_appearance_presets()}
        hidden_ids = [item for item in hidden if isinstance(item, str) and item in builtin_ids] if isinstance(hidden, list) else []
        presets = [item for item in self._bundled_appearance_presets() if item["id"] not in hidden_ids]
        if isinstance(custom, list):
            presets += [item for item in custom if isinstance(item, dict)]
        return {"ok": True, "hidden_builtin_ids": hidden_ids, "presets": [
            {**item, "available": not item.get("background_path") or not self._validate_appearance_image_path(item["background_path"])}
            for item in presets
        ]}

    def save_appearance_preset(self, name):
        name = str(name or "").strip()
        if not name or len(name) > 30:
            return {"ok": False, "error": "主题名称请填写 1–30 个字符。"}
        settings = self.core._load_app_settings() or {}
        if not isinstance(settings, dict):
            settings = {}
        custom = settings.get("modern_ui_custom_presets", [])
        custom = list(custom) if isinstance(custom, list) else []
        if len(custom) >= 20:
            return {"ok": False, "error": "最多保存 20 个自定义主题。"}
        if any(str(item.get("name", "")).casefold() == name.casefold() for item in self._bundled_appearance_presets() + custom if isinstance(item, dict)):
            return {"ok": False, "error": "已有同名主题，请换一个名称。"}
        current = self._appearance_settings_from_core(self.core)
        custom.append({
            "id": uuid.uuid4().hex, "name": name, "built_in": False,
            "theme": current["theme"], "background_path": current["background_path"],
            "background_source_path": current["background_source_path"],
            "background_opacity": current["background_opacity"],
            "component_opacity": current["component_opacity"],
            "idle_fade_enabled": current["idle_fade_enabled"],
        })
        settings["modern_ui_custom_presets"] = custom
        if not self.core._save_app_settings(settings):
            return {"ok": False, "error": "保存主题失败，请检查用户设置目录。"}
        return self.get_appearance_presets()

    def delete_appearance_preset(self, preset_id):
        settings = self.core._load_app_settings() or {}
        if not isinstance(settings, dict):
            settings = {}
        builtin_ids = {item["id"] for item in self._bundled_appearance_presets()}
        if preset_id in builtin_ids:
            hidden = settings.get("modern_ui_hidden_builtin_presets", [])
            hidden = [item for item in hidden if isinstance(item, str) and item in builtin_ids] if isinstance(hidden, list) else []
            settings["modern_ui_hidden_builtin_presets"] = list(dict.fromkeys(hidden + [preset_id]))
            if not self.core._save_app_settings(settings):
                return {"ok": False, "error": "隐藏内置主题失败，请检查用户设置目录。"}
            return self.get_appearance_presets()
        custom = settings.get("modern_ui_custom_presets", [])
        custom = list(custom) if isinstance(custom, list) else []
        removed = next((item for item in custom if isinstance(item, dict) and item.get("id") == preset_id), None)
        if not removed:
            return {"ok": False, "error": "找不到可删除的自定义主题。"}
        settings["modern_ui_custom_presets"] = [item for item in custom if item is not removed]
        if not self.core._save_app_settings(settings):
            return {"ok": False, "error": "删除主题失败，请检查用户设置目录。"}
        if removed.get("background_path"):
            self._remove_owned_appearance_crop(removed["background_path"])
        return self.get_appearance_presets()

    def restore_appearance_builtin_presets(self):
        settings = self.core._load_app_settings() or {}
        if not isinstance(settings, dict):
            settings = {}
        settings["modern_ui_hidden_builtin_presets"] = []
        if not self.core._save_app_settings(settings):
            return {"ok": False, "error": "恢复内置主题失败，请检查用户设置目录。"}
        return self.get_appearance_presets()

    def set_appearance_settings(
        self,
        theme="dark",
        background_path="",
        background_opacity=18,
        component_opacity=None,
        idle_fade_enabled=None,
        background_history=None,
        background_source_path=None,
        background_data_url=None,
    ):
        theme = str(theme or "dark")
        if theme not in ("dark", "light", "system"):
            return {"ok": False, "error": "颜色主题选项无效。"}
        background_path = str(background_path or "").strip()
        if background_path:
            background_path = os.path.abspath(background_path)
            error = self._validate_appearance_image_path(background_path)
            if error:
                return {"ok": False, "error": error}
        if background_source_path is None:
            background_source_path = background_path
        background_source_path = str(background_source_path or "").strip()
        if background_source_path:
            background_source_path = os.path.abspath(background_source_path)
        try:
            opacity = max(0, min(100, int(background_opacity)))
        except (TypeError, ValueError):
            return {"ok": False, "error": "背景图片显现程度无效。"}
        current_settings = self.core._load_app_settings() or {}
        current_settings = current_settings if isinstance(current_settings, dict) else {}
        old_background_path = str(current_settings.get("modern_ui_background") or "")
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
        history_paths = self._normalize_appearance_background_history(
            background_history, background_path, background_source_path
        )
        created_background_path = ""
        if background_data_url:
            if not background_source_path:
                return {"ok": False, "error": "裁切图片的原图路径无效，请重新选择。"}
            source_error = self._validate_appearance_image_path(background_source_path)
            if source_error:
                return {"ok": False, "error": source_error}
            try:
                crop_bytes, crop_extension = self._decode_appearance_crop_data_url(background_data_url)
                created_background_path = self._write_appearance_crop(crop_bytes, crop_extension)
                background_path = created_background_path
            except (OSError, ValueError) as exc:
                return {"ok": False, "error": str(exc) or "保存裁切图片失败。"}
        settings["modern_ui_theme"] = theme
        settings["modern_ui_background"] = background_path
        settings["modern_ui_background_source"] = background_source_path
        settings["modern_ui_background_opacity"] = opacity
        settings["modern_ui_component_opacity"] = component_opacity
        settings["modern_ui_idle_fade_enabled"] = bool(idle_fade_enabled)
        settings["modern_ui_background_history"] = history_paths
        if not self.core._save_app_settings(settings):
            if created_background_path:
                try:
                    os.remove(created_background_path)
                except OSError:
                    pass
            return {"ok": False, "error": "设置保存失败，请检查用户设置目录的写入权限。"}
        if old_background_path and os.path.normcase(os.path.abspath(old_background_path)) != os.path.normcase(os.path.abspath(background_path)):
            self._remove_owned_appearance_crop(old_background_path)
        self._log("[外观] 已保存新版训练页显示设置。")
        return {"ok": True, "settings": self._appearance_settings_from_core(self.core)}

    @staticmethod
    def _validate_appearance_image_path(path):
        if not path or not os.path.isfile(path):
            return "背景图片文件不存在，请重新选择。"
        if os.path.splitext(path)[1].lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            return "背景图片需为 PNG、JPG、WebP 或 BMP 格式。"
        try:
            if os.path.getsize(path) > 8 * 1024 * 1024:
                return "背景图片不能超过 8 MB。"
        except OSError:
            return "无法读取背景图片，请检查文件权限。"
        return ""

    @staticmethod
    def _appearance_assets_dir():
        from kohya_core.paths import _settings_path

        return os.path.join(os.path.dirname(os.path.abspath(_settings_path())), "modern_ui_backgrounds")

    @staticmethod
    def _decode_appearance_crop_data_url(data_url):
        import base64
        import binascii
        import re

        match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=]+)", str(data_url or ""))
        if not match:
            raise ValueError("裁切图片格式无效，请重新裁切。")
        if len(match.group(2)) > 11_184_812:
            raise ValueError("裁切后的图片不能超过 8 MB。")
        try:
            content = base64.b64decode(match.group(2), validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("裁切图片数据无效，请重新裁切。")
        if not content or len(content) > 8 * 1024 * 1024:
            raise ValueError("裁切后的图片不能超过 8 MB。")
        try:
            from io import BytesIO
            from PIL import Image

            with Image.open(BytesIO(content)) as image:
                expected_format = {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}[match.group(1)]
                if image.format != expected_format:
                    raise ValueError("裁切图片的文件格式与标记不一致。")
                image.verify()
        except Exception as exc:
            raise ValueError("无法读取裁切后的图片，请重新裁切。") from exc
        return content, {"png": ".png", "jpeg": ".jpg", "webp": ".webp"}[match.group(1)]

    def _write_appearance_crop(self, content, extension):
        import uuid

        directory = self._appearance_assets_dir()
        os.makedirs(directory, exist_ok=True)
        path = os.path.abspath(os.path.join(directory, "background-%s%s" % (uuid.uuid4().hex, extension)))
        with open(path, "xb") as handle:
            handle.write(content)
        return path

    def _remove_owned_appearance_crop(self, path):
        try:
            root = os.path.normcase(os.path.abspath(self._appearance_assets_dir()))
            candidate = os.path.normcase(os.path.abspath(path))
            if os.path.commonpath((root, candidate)) != root:
                return
            settings = self.core._load_app_settings() or {}
            if isinstance(settings, dict):
                current = settings.get("modern_ui_background")
                custom = settings.get("modern_ui_custom_presets", [])
                references = [current]
                if isinstance(custom, list):
                    references.extend(item.get("background_path") for item in custom if isinstance(item, dict))
                if any(ref and os.path.normcase(os.path.abspath(ref)) == candidate for ref in references):
                    return
            os.remove(candidate)
        except (OSError, ValueError):
            pass

    @staticmethod
    def _appearance_display_data_url(path):
        """Send a compact display image through pywebview, not a multi-MB source PNG."""
        import base64
        from io import BytesIO
        from PIL import Image, ImageOps

        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source)
            resampling = getattr(Image, "Resampling", Image)
            image.thumbnail((3840, 3840), resampling.LANCZOS)
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            image = image.convert("RGBA" if has_alpha else "RGB")
            buffer = BytesIO()
            image.save(buffer, format="WEBP", quality=84, method=4)
        return "data:image/webp;base64,%s" % base64.b64encode(buffer.getvalue()).decode("ascii")

    def get_appearance_background(self):
        path = self._appearance_settings_from_core(self.core).get("background_path", "")
        error = self._validate_appearance_image_path(path)
        if error:
            return {"ok": False, "error": error}
        try:
            return {"ok": True, "data_url": self._appearance_display_data_url(path)}
        except Exception as exc:
            return {"ok": False, "error": "读取背景图片失败：%s" % exc}

    def get_appearance_image_preview(self, path, thumbnail=False):
        import base64
        from io import BytesIO

        path = os.path.abspath(str(path or "").strip()) if str(path or "").strip() else ""
        error = self._validate_appearance_image_path(path)
        if error:
            return {"ok": False, "error": error}
        try:
            if thumbnail:
                from PIL import Image, ImageOps

                with Image.open(path) as source:
                    source.load()
                    resampling = getattr(Image, "Resampling", Image)
                    image = ImageOps.fit(source.convert("RGB"), (144, 144), method=resampling.LANCZOS)
                    buffer = BytesIO()
                    image.save(buffer, format="WEBP", quality=74, method=4)
                    content = buffer.getvalue()
                data_url = "data:image/webp;base64,%s" % base64.b64encode(content).decode("ascii")
            else:
                data_url = self._appearance_display_data_url(path)
            return {
                "ok": True,
                "data_url": data_url,
            }
        except Exception as exc:
            return {"ok": False, "error": "读取图片预览失败：%s" % exc}

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
        guard = self._agent_guard()
        if guard:
            return guard
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

    def get_model_catalog(self):
        return model_catalog(self.core)

    def get_mode_workspace(self, mode, project_name=""):
        """Return UI metadata and read-only readiness checks for a classic training mode."""
        mode = str(mode or "")
        if mode not in getattr(self.core, "MODE_KEYS", ()):
            return {"ok": False, "error": "未知的训练模式。"}
        core = self.core
        project_config = core.load_project(str(project_name or "").strip()) if project_name else {}
        project_config = project_config if isinstance(project_config, dict) else {}
        status = core.system_status()
        engine_key = {
            "style": "kohya_ok", "character": "kohya_ok", "concept": "kohya_ok",
            "krea2": "musubi_ok", "flux2": "musubi_ok",
            "video": "at_ok", "krea2_at": "at_ok", "qwen_image": "at_ok", "zimage": "at_ok",
            "krea2_fz": "fizgig_ok", "flux2_fz": "fizgig_ok",
            "qwen21_fz": "fizgig_ok", "h3_fz": "fizgig_ok", "anima_fz": "fizgig_ok", "sdxl_fz": "fizgig_ok",
        }.get(mode)
        engine_ready = bool(status.get(engine_key)) if engine_key else False
        engine_update_available = False
        if mode in ("video", "krea2_at", "qwen_image", "zimage"):
            try:
                engine_update_available = bool(core.ai_toolkit_engine_update_status().get("update_available"))
            except Exception:
                engine_update_available = False
        elif mode in FIZGIG_FAMILIES:
            try:
                engine_update_available = bool(core.fizgig_engine_update_status().get("update_available"))
            except Exception:
                engine_update_available = False
        missing = []
        asset_dir = ""
        try:
            if mode in ("anima_fz", "sdxl_fz"):
                missing = fizgig_missing(core, FIZGIG_FAMILIES[mode], project_config)
                asset_dir = core.anima_fz_models_dir() if mode == "anima_fz" else core.sdxl_fz_models_dir()
            elif mode in ("krea2", "krea2_fz"):
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
            elif mode == "qwen21_fz":
                missing = list(core.qwen21_fz_missing_models())
                asset_dir = core.qwen21_fz_models_dir()
            elif mode == "h3_fz":
                missing = list(core.h3_fz_missing_models())
                asset_dir = core.h3_fz_models_dir()
            elif mode == "video":
                missing = list(core.h3_missing_models())
                asset_dir = core.h3_models_dir()
            elif mode in ("qwen_image", "zimage"):
                if not core.at_image_model_ready(mode):
                    missing = ["训练模型尚未准备（可选择已有本地模型或按需下载）"]
                asset_dir = core.at_image_local_dir(mode)
        except Exception as exc:
            missing = ["无法读取模型状态：%s" % exc]
        version_info = core.fizgig_engine_update_status() if mode in FIZGIG_FAMILIES else {}
        version = str((project_config.get("params") or {}).get("fizgig_version") or (FIZGIG_TARGET if mode in ("anima_fz", "sdxl_fz") or not project_name else "v6.5.0"))
        if mode in FIZGIG_FAMILIES:
            record = fizgig_runtime(core, version)
            engine_ready = Path(record["python"]).is_file() and bool(fizgig_source_version(record["source"]))
        supports = {
            key: bool(core.param_supports(key, mode))
            # base_model is stored on the project root, but also controls the model picker UI.
            for key in (*_WORKSPACE_PARAM_KEYS, "base_model")
        }
        if mode in FIZGIG_FAMILIES and version == FIZGIG_TARGET:
            for key in ("optimizer", "compile", "global_pos", "global_neg"):
                supports[key] = True
            supports["blocks_to_swap"] = mode in ("krea2_fz", "flux2_fz", "qwen21_fz", "h3_fz")
        quant_modes = list(getattr(core, "QUANT_MODE_OPTIONS", {}).get(mode, ()))
        if mode in FIZGIG_FAMILIES and version == FIZGIG_TARGET:
            quant_modes = ["auto", "int8", "nf4", "hqq"] if mode == "h3_fz" else ["auto", "bf16", "int8", "nf4"]
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
        interval_hints = {}
        for key in ("save_every", "sample_interval"):
            try:
                interval_units[key] = str(core.interval_unit_for(mode, key))
                interval_hints[key] = str(core.interval_help_for(mode, key))
            except Exception:
                interval_units[key] = "steps"
                interval_hints[key] = ""
        labels = getattr(core, "MODE_LABELS", {})
        trigger_hints = {
            "style": getattr(core, "TRIGGER_HINT_STYLE", ""),
            "character": getattr(core, "TRIGGER_HINT_CHARACTER", ""),
            "concept": getattr(core, "TRIGGER_HINT_CONCEPT", ""),
            "krea2": getattr(core, "TRIGGER_HINT_KREA2", ""),
            "krea2_at": getattr(core, "TRIGGER_HINT_KREA2_AT", ""),
            "krea2_fz": getattr(core, "TRIGGER_HINT_KREA2", ""),
            "qwen21_fz": getattr(core, "TRIGGER_HINT_QWEN21_FZ", getattr(core, "TRIGGER_HINT_AT", "")),
            "h3_fz": getattr(core, "TRIGGER_HINT_H3_FZ", getattr(core, "TRIGGER_HINT_VIDEO", "")),
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
            "fizgig": engine_ready if mode in FIZGIG_FAMILIES else bool(status.get("fizgig_ok")),
            "base": bool(project_config.get("base_model")),
            "raw": bool(project_config.get("raw_dir")),
        }
        model_checks = {
            "krea2_models", "krea2_at_models", "flux2_models", "flux2_fz_models", "h3_models", "qwen21_fz_models", "h3_fz_models", "at_model", "fizgig_new_models",
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
            "quant_modes": quant_modes,
            "fizgig_version": version if mode in FIZGIG_FAMILIES else "",
            "fizgig_versions": version_info.get("versions", []),
            "fizgig_target_version": FIZGIG_TARGET,
            "model_choice": project_config.get("model_choice"),
            "interval_units": interval_units,
            "interval_hints": interval_hints,
            "defaults": preset,
            "presets": presets,
            "is_video": mode in ("video", "h3_fz"),
            "is_step_based": mode in ("video", "qwen_image", "zimage"),
            "has_training_submode": mode in ("krea2", "krea2_at", "krea2_fz", "qwen21_fz", "flux2", "flux2_fz", "anima_fz", "sdxl_fz"),
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

    def create_project(self, name, template_name="自定义", config_json="", mode_override=None, model_choice=None, training_type="character"):
        guard = self._agent_guard()
        if guard:
            return guard
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
                if raw_config.get("training_kind") == "slider":
                    from kohya_core.slider_project import normalize
                    settings = normalize(raw_config.get("slider"))
                    settings.update(positive_dir="", negative_dir="", pairs=[])
                    imported_config.update(training_kind="slider", slider=settings)
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

        if model_choice and not imported_config:
            try:
                choice = resolve_choice(model_choice)
                template_name = choice["template"]
                if training_type not in ("character", "style", "concept", "slider"):
                    raise ValueError("训练目的无效。")
                if training_type == "slider" and choice["mode"] not in ("anima_fz", "sdxl_fz"):
                    raise ValueError("滑块请选择 SDXL / 标准 28 层 Anima 的 Fizgig v7.0.1 入口。")
                if choice["mode"] == "character": mode_override = training_type
                vendor = self.core.detect_gpu_vendor()
                if vendor and vendor != "unknown" and vendor not in choice["vendors"]:
                    raise ValueError("这个模型版本尚未接入当前显卡的训练路径。")
            except (TypeError, ValueError) as exc:
                return {"ok": False, "error": str(exc)}
        templates = getattr(self.core, "PROJECT_TEMPLATES", {})
        mode_override = str(mode_override or "").strip()
        if template_name == "Qwen-Image":
            template = {"mode": "qwen_image", "base_type": "qwen_image"}
        elif template_name in _MODERN_PROJECT_TEMPLATES:
            template = _MODERN_PROJECT_TEMPLATES[template_name]
        else:
            template = templates.get(template_name) or templates.get("自定义", {"mode": "character", "base_type": "sdxl"})
        first_engine_modes = ("style", "character", "concept")
        is_first_engine_template = (
            template_name in templates or template_name in _MODERN_PROJECT_TEMPLATES
        ) and template.get("mode") in first_engine_modes
        if mode_override and not imported_config and is_first_engine_template and mode_override not in first_engine_modes:
            return {"ok": False, "error": "第一引擎训练模式无效。"}
        mode = mode_override if (mode_override and not imported_config and is_first_engine_template) else template.get("mode", "character")
        base_type = template.get("base_type", "sdxl")
        data = {
            "name": name,
            "template": template_name if template_name in templates or template_name in _MODERN_PROJECT_TEMPLATES or template_name == "Qwen-Image" else "自定义",
            "mode": mode,
            "base_type": base_type,
            "preset_version": int(self.core.PRESET_VERSION),
            "params": {},
        }
        if not imported_config:
            if training_type == "slider":
                if mode not in ("anima_fz", "sdxl_fz"):
                    return {"ok": False, "error": "滑块入口尚未接入所选模型。"}
                from kohya_core.slider_project import normalize
                data.update(training_kind="slider", slider=normalize({}), unet_only=True)
            data["at_sub_mode"] = training_type
            if model_choice: data["model_choice"] = {k: model_choice[k] for k in ("model", "variant", "engine")}
            if mode in FIZGIG_FAMILIES: data["params"]["fizgig_version"] = FIZGIG_TARGET
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
            if imported_config.get("training_kind") == "slider":
                from kohya_core.slider_project import parameters
                data.update(training_kind="slider", slider=imported_config["slider"], unet_only=True)
                try:
                    parameters(data, name)
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}
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
        guard = self._agent_guard()
        if guard:
            return guard
        with self._task_lock:
            if (self._task and self._task.get("status") in ("running", "awaiting_review")
                    and self._task.get("key") == str(old_name or "").strip()):
                return {"ok": False, "error": "该项目的任务尚未结束，请结束后再改名。"}
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

        ok, detail = self.core.rename_project(old_name, new_name)
        if not ok:
            return {"ok": False, "error": detail}
        message = "[项目] 已重命名「%s」→「%s」；%s" % (old_name, new_name, detail)
        self._log(message)
        return {"ok": True, "log": message}

    def delete_project(self, name):
        guard = self._agent_guard()
        if guard:
            return guard
        with self._task_lock:
            if (self._task and self._task.get("status") in ("running", "awaiting_review")
                    and self._task.get("key") == str(name or "").strip()):
                return {"ok": False, "error": "该项目的任务尚未结束，请结束后再删除配置。"}
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

    def get_log_export_status(self, export_id):
        """Report completion separately from the background export request."""
        with self._log_lock:
            if not export_id or self._log_export.get("id") != str(export_id):
                return {"ok": False, "error": "此日志导出任务已不存在，请重新导出。"}
            return {"ok": True, **self._log_export}

    def open_log_export(self, export_id, target="file"):
        """Only open the file produced by this session's completed export."""
        with self._log_lock:
            export = dict(self._log_export)
        if not export_id or export.get("id") != str(export_id) or export.get("status") != "completed":
            return {"ok": False, "error": "日志尚未导出成功，请稍候或重新导出。"}
        if target not in ("file", "folder"):
            return {"ok": False, "error": "打开方式无效。"}
        path = Path(export["path"]).resolve()
        try:
            if not path.is_file():
                return {"ok": False, "error": "日志文件已被移动或删除，请重新导出。"}
            if target == "folder":
                subprocess.Popen(["explorer.exe", "/select,", str(path)])
            else:
                os.startfile(str(path))
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": "无法打开日志%s：%s" % (
                "所在文件夹" if target == "folder" else "文件", redact(str(exc)))}

    def run_action(self, action, project_name=None):
        """Open legacy secondary utilities as isolated popups; never fall back to its workspace."""
        action = str(action or "")
        view_action = action in ("output_dir", "export_training_feedback", "export_log", "export_diagnostics")
        with self._task_lock:
            task = self._task or {}
            reviewing_labels = (action == "label_editor" and task.get("kind") == "training"
                                and task.get("status") == "awaiting_review"
                                and task.get("key") == str(project_name or ""))
        if not view_action and not reviewing_labels:
            guard = self._agent_guard()
            if guard:
                return guard
        if action.startswith("mode:") or action == "train":
            return {"ok": False, "error": "训练模式与训练任务由新版训练页直接承接。"}
        if action == "export_config" and (self.core.load_project(str(project_name or "")) or {}).get("training_kind") == "slider":
            if self._window is None: return {"ok": False, "error": "文件选择器尚未就绪。"}
            try:
                import webview
                config = self.core.load_project(project_name)
                payload = self.core.export_config_json(training_params(self.core, config, project_name), include_prompts=True)
                selected = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=project_name + "_滑块配置.json", file_types=("JSON (*.json)",))
                if not selected: return {"ok": True, "message": "已取消配置导出。"}
                path = selected[0] if isinstance(selected, (list, tuple)) else selected
                from kohya_core.fizgig_engine import _write
                _write(Path(path), payload)
                return {"ok": True, "message": "滑块配置已导出；不包含图片目录、配对路径或 API 设置。"}
            except Exception as exc:
                return {"ok": False, "error": "滑块配置导出失败：%s" % exc}
        if action == "preprocess":
            # Keep every caller on the modern task/review workflow. The classic
            # command remains available for the classic UI, but must not be
            # launched from this bridge as a hidden workspace process.
            return self.start_preprocess_task(project_name)

        if action.startswith("open_models:"):
            mode = action.split(":", 1)[1]
            model_dirs = {
                "sdxl_fz": self.core.sdxl_fz_models_dir,
                "anima_fz": self.core.anima_fz_models_dir,
                "krea2": self.core.krea2_models_dir,
                "krea2_at": self.core.krea2_at_models_dir,
                "krea2_fz": self.core.krea2_models_dir,
                "flux2": self.core.flux2_models_dir,
                "flux2_fz": self.core.flux2_models_dir,
                "qwen21_fz": self.core.qwen21_fz_models_dir,
                "h3_fz": self.core.h3_fz_models_dir,
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
            path = self.core.data_sub("output", project_name) if project_name else self.core.data_sub("output")
            os.makedirs(path, exist_ok=True)
            try:
                os.startfile(path)
            except Exception as exc:
                return {"ok": False, "error": "无法打开输出目录：%s" % exc}
            message = "[目录] 已打开输出目录：%s" % path
            self._log(message)
            return {"ok": True, "message": "已打开输出目录。", "log": message}

        if action == "export_training_feedback":
            from kohya_core.diagnostics import write_training_feedback
            with self._task_lock:
                task = dict(self._task or {})
                task["logs"] = list(task.get("logs", []))
                task["startup_logs"] = list(task.get("startup_logs", []))
            if task.get("kind") != "training" or task.get("key") != str(project_name or ""):
                return {"ok": False, "error": "当前任务不属于这个项目，请在对应的训练窗口导出。"}
            try:
                gallery = self.list_task_samples(task["id"])
                try:
                    path = write_training_feedback(self._desktop_directory(), task, gallery)
                except OSError:
                    path = write_training_feedback(self.core.data_sub("logs"), task, gallery)
                self._log("[导出] 本次训练反馈资料：%s" % path)
                return {"ok": True, "message": "反馈资料已导出：%s（包含设置和日志，不包含训练图片或模型，也不会上传）" % path}
            except Exception as exc:
                return {"ok": False, "error": "反馈资料导出失败：%s" % exc}

        if action in ("export_log", "export_diagnostics"):
            import datetime
            with self._log_lock:
                if self._diagnostics_thread and self._diagnostics_thread.is_alive():
                    return {"ok": False, "error": "日志正在导出，请稍候。"}
                logs = "\n".join(self.logs)
                with self._task_lock:
                    task = dict(self._task or {})
                task["session_log_error"] = self._session_log_error
                project = self.core.load_project(project_name) if project_name else {}
                filename = "KohyaLoRA_运行日志_%s.txt" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                dest = os.path.join(self._desktop_directory(), filename)
                export_id = uuid.uuid4().hex
                self._log_export = {"id": export_id, "status": "running", "path": "", "error": ""}

                def collect():
                    try:
                        try:
                            path = write_bundle(self.core, dest, logs, task, project, self._session_log)
                        except OSError:
                            fallback = os.path.join(self.core.data_sub("logs"), filename)
                            path = write_bundle(self.core, fallback, logs, task, project, self._session_log)
                        self._log("[诊断] 运行日志已导出：%s" % path)
                        with self._log_lock:
                            self._log_export.update(status="completed", path=str(path))
                    except Exception as exc:
                        self._log("[诊断] 导出失败：\n%s" % traceback.format_exc())
                        with self._log_lock:
                            self._log_export.update(status="failed", error="日志导出失败：%s" % redact(str(exc)))

                self._diagnostics_thread = threading.Thread(target=collect, name="KohyaDiagnostics", daemon=True)
                try:
                    self._diagnostics_thread.start()
                except Exception as exc:
                    self._log_export.update(status="failed", error="无法开始日志导出：%s" % redact(str(exc)))
                    return {"ok": False, "error": self._log_export["error"]}
            return {"ok": True, "export_id": export_id, "message": "正在收集运行日志与环境信息。"}

        project_actions = {
            "label_editor", "export_config", "readme", "at_model_help",
            "at_engine_update", "fizgig_engine_update", "anima_components", "krea2_guide", "flux2_guide",
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
                "fizgig_engine_update": "Fizgig 引擎更新",
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

        # ★ 2026-10-02（用户反馈：点了「下载底模」没看到窗口）：
        #   底模下载对话框要看 **当前项目的 base_type** 才知道该列哪批模型 ✗ ——
        #   `_download_choice_dialog` 第一行就是 `bt = bt or self.base_type` ✓
        #   若不带 --project，经典侧 base_type 是空的 ⇒
        #     get_download_models("") 返回空 ⇒ 走「架构下载帮助」分支直接 return ✗
        #   表现就是：日志说"已打开「底模下载」"，但**一个窗口都不弹** ✗（实测确认 ✓）
        #   ⇒ 必须带上项目 ✓；同时**不要求**项目必须存在（下载底模本身是全局操作 ✓）
        if action == "download_base":
            project_name = str(project_name or "").strip()
            args = []
            if project_name and self.core.load_project(project_name):
                args += ["--project", project_name]
            try:
                self._spawn_classic(*args, "--action", action, "--utility-only")
            except Exception as exc:
                return {"ok": False, "error": "无法打开底模下载窗口：%s" % exc}
            message = "已打开「底模下载」窗口；选择要下载的底模即可（新版训练页保持打开）。"
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

    from gui.ui_startup import StartupMonitor, check_page_assets

    startup = StartupMonitor(core)
    root = _app_root()
    index = root / "modern_ui" / "dist" / "index.html"
    if dev:
        url = os.environ.get("KOHYA_UI_DEV_URL", "http://127.0.0.1:5173")
    else:
        try:
            check_page_assets(index, startup._log)
        except Exception as exc:
            startup.record("asset_check_failed", exc)
            raise RuntimeError("%s\n\n启动诊断：%s" % (exc, startup.path)) from exc
        url = str(index)

    try:
        bridge = ModernUIBridge(core, engine_groups, short_mode_labels)
    except Exception as exc:
        startup.record("bridge_initialization_failed", exc)
        raise RuntimeError("工作区初始化失败：%s\n\n启动诊断：%s" % (redact(str(exc)), startup.path)) from exc
    bridge._startup = startup
    app_name = getattr(core, "APP_NAME", "Kohya-LoRA")
    app_version = getattr(core, "APP_VERSION", "0.0.0")
    window = webview.create_window(
        title="%s · v%s · 新版训练页" % (app_name, app_version),
        url=url,
        js_api=bridge,
        width=1360,
        height=860,
        min_size=(1060, 700),
        background_color="#1e2128",
        text_select=True,
    )
    bridge._window = window
    startup.attach(window)
    try:
        webview.start(startup.watch, gui="edgechromium", debug=debug, http_server=not dev,
                      user_agent="KohyaLoRA-Desktop/%s" % app_version, icon=str(root / "app.ico"))
    except Exception as exc:
        startup.record("host_failed", exc)
        raise RuntimeError("新版页面启动失败：%s\n\n启动诊断：%s" % (redact(str(exc)), startup.path)) from exc
    finally:
        startup.detach()
    # Reuse the launcher's existing classic fallback in this process.
    return "classic" if startup.classic_requested else 0
