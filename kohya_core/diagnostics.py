"""Bounded, local diagnostics shared by the classic and modern interfaces."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile


def redact(text):
    text = str(text)
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{12,}|hf_[A-Za-z0-9]{12,})\b", "<REDACTED>", text)
    text = re.sub(r'(?i)((?:api[_-]?key|access[_-]?token|password|secret|authorization|hf_token)[\s"\x27]*[:=][\s"\x27]*(?:bearer\s+)?)[^\s,;"\x27]+', r'\1<REDACTED>', text)
    text = re.sub(r'(?i)(https?://)[^/\s:@]+:[^/\s@]+@', r'\1<REDACTED>@', text)
    text = re.sub(r'(?i)([?&](?:token|key|signature|access_token)=)[^&\s"\x27]+', r'\1<REDACTED>', text)
    text = re.sub(r"(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\r\n\"']+", "%USERPROFILE%", text)
    home = str(Path.home())
    return text.replace(home, "%USERPROFILE%") if len(home) > 3 else text


def _json(value):
    def clean(item):
        if isinstance(item, dict):
            return {str(key): ("<REDACTED>" if str(key).lower().replace("-", "_") in
                              ("api_key", "token", "hf_token", "access_token", "huggingface_token", "password", "secret", "authorization")
                              else clean(value)) for key, value in item.items()}
        if isinstance(item, (list, tuple)):
            return [clean(value) for value in item]
        return redact(item) if isinstance(item, str) else item
    return json.dumps(clean(value), ensure_ascii=False, indent=2, default=str)


def _call(core, name, *args):
    try:
        return getattr(core, name)(*args)
    except Exception as exc:
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


def collect_summary(core):
    data = {"software_version": getattr(core, "APP_VERSION", "unknown"),
            "os": platform.platform(), "architecture": platform.machine(),
            "launcher_python": sys.executable, "launcher_version": sys.version,
            "frozen": bool(getattr(sys, "frozen", False)),
            "gpu": _call(core, "detect_gpu_info"), "ram_gb": _call(core, "detect_ram_gb"),
            "data_dir": _call(core, "data_dir"), "engine_dir": _call(core, "get_kohya_dir"),
            "selected_programs": _call(core, "get_env_paths"),
            "python": _call(core, "find_python"), "git": _call(core, "find_git")}
    return data


def summary_lines(core):
    summary = collect_summary(core)
    return [redact("操作系统: %s" % summary["os"]),
            "CPU: %s（%s 核）" % (platform.processor() or "未知", os.cpu_count()),
            redact("显卡: %s" % summary["gpu"]),
            redact("系统内存: %sGB" % summary["ram_gb"]), _json(summary)]


class SessionLog:
    """Keep every line on disk while the UI retains a bounded tail."""
    def __init__(self, directory):
        self.path = Path(directory) / ("session_%s.log" % datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        self.lock = threading.RLock()
        self.error = None

    def append(self, text):
        with self.lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write("[%s] %s\n" % (datetime.now().isoformat(timespec="seconds"), redact(text)))
            except OSError as exc:
                self.error = str(exc)

    def snapshot(self):
        with self.lock:
            try:
                return self.path.read_text(encoding="utf-8")
            except OSError as exc:
                self.error = str(exc)
                return "[会话日志读取失败] %s" % exc


def _run(command, timeout=20, env=None):
    started = time.monotonic()
    result = {"command": command, "timeout_seconds": timeout}
    try:
        process = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace",
                                 timeout=timeout, env=env,
                                 **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
        result.update(status="ok" if process.returncode == 0 else "failed",
                      returncode=process.returncode, stdout=process.stdout, stderr=process.stderr)
    except subprocess.TimeoutExpired as exc:
        def decode(value):
            return value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""
        result.update(status="timeout", stdout=decode(exc.stdout), stderr=decode(exc.stderr))
    except Exception as exc:
        result.update(status="error", error="%s: %s" % (type(exc).__name__, exc))
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    for key in ("stdout", "stderr"):
        if len(result.get(key, "")) > 100000:
            result[key] = result[key][:100000] + "\n[诊断输出超过 100000 字符，已截断]"
    return result


_PROBE = r'''
import importlib, importlib.metadata as metadata, json, os, sys, traceback
RUN_GPU_TEST = True
out = {"python": sys.executable, "version": sys.version, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
       "packages": {}, "imports": {}, "gpu": {"status": "not_tested"}}
for dist in metadata.distributions():
    name = dist.metadata.get("Name", "").lower().replace("_", "-")
    if name in ("torch", "torchvision", "torchaudio", "accelerate", "diffusers", "transformers", "numpy", "scipy", "pillow", "safetensors", "bitsandbytes", "xformers", "pip") or name.startswith(("rocm", "amd-torch")):
        out["packages"][name] = dist.version
for name in ("torch", "torchvision", "accelerate", "diffusers", "transformers"):
    try:
        importlib.import_module(name)
        out["imports"][name] = {"status": "ok"}
    except Exception:
        out["imports"][name] = {"status": "failed", "traceback": traceback.format_exc()}
try:
    import torch
    out["gpu"] = {"status": "unavailable", "hip": torch.version.hip, "cuda_build": torch.version.cuda,
                  "available": torch.cuda.is_available(), "device_count": torch.cuda.device_count()}
    if not RUN_GPU_TEST:
        out["gpu"]["status"] = "skipped_active_task"
    elif torch.cuda.is_available():
        out["gpu"].update(name=torch.cuda.get_device_name(0), architecture=getattr(torch.cuda.get_device_properties(0), "gcnArchName", ""))
        x = torch.randn(1, 4, 16, 16, device="cuda", dtype=torch.float16, requires_grad=True)
        w = torch.randn(8, 4, 3, 3, device="cuda", dtype=torch.float16, requires_grad=True)
        y = torch.nn.functional.conv2d(x, w)
        y.float().square().mean().backward()
        torch.cuda.synchronize()
        if not (torch.isfinite(y).all().item() and torch.isfinite(x.grad).all().item() and torch.isfinite(w.grad).all().item()):
            raise RuntimeError("GPU output or gradients contain NaN/Inf")
        out["gpu"].update(status="forward_backward_ok", dtype="float16")
except Exception:
    out["gpu"].update(status="failed", traceback=traceback.format_exc())
print("KLT_DIAGNOSTIC=" + json.dumps(out, ensure_ascii=False))
'''


def _runtime_probe(label, path, env, check_gpu=True):
    python = Path(path)
    report = {"label": label, "python": str(python)}
    if not python.is_file():
        return {**report, "status": "missing", "reason": "该环境的 python.exe 不存在"}
    cfg = python.parent.parent / "pyvenv.cfg"
    if cfg.is_file():
        try:
            report["pyvenv.cfg"] = cfg.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            report["pyvenv.cfg_error"] = str(exc)
    code = _PROBE if check_gpu else _PROBE.replace("RUN_GPU_TEST = True", "RUN_GPU_TEST = False")
    report["probe"] = _run([str(python), "-I", "-c", code], timeout=35, env=env)
    for line in report["probe"].get("stdout", "").splitlines():
        if line.startswith("KLT_DIAGNOSTIC="):
            try:
                report["runtime"] = json.loads(line.split("=", 1)[1])
            except ValueError as exc:
                report["parse_error"] = str(exc)
    report["pip_check"] = _run([str(python), "-I", "-m", "pip", "check"], timeout=10, env=env)
    return report


def write_bundle(core, destination, logs, task=None, project=None, session=None):
    """Local ZIP only: no uploads, installs, model files or dataset contents."""
    summary = collect_summary(core)
    env = _call(core, "build_env")
    if not isinstance(env, dict) or "error" in env:
        env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    kdir = summary["engine_dir"]
    profiles = {}
    if isinstance(kdir, str):
        for label, folder in (("kohya", "venv"), ("musubi", "musubi-venv"),
                              ("ai_toolkit", "ai_toolkit_venv"), ("fizgig", "fizgig_venv")):
            profiles[label] = str(Path(kdir) / folder / "Scripts" / "python.exe")
    data_dir = summary["data_dir"]
    if isinstance(data_dir, str):
        profiles["amd"] = str(Path(data_dir) / "venv_amd" / "Scripts" / "python.exe")
    for label, method in (("ai_toolkit", "_at_dirs"), ("fizgig", "_fizgig_dirs")):
        if hasattr(core, method):
            locations = _call(core, method)
            if isinstance(locations, (list, tuple)) and locations and isinstance(locations[0], str):
                profiles[label] = locations[0]
    project = project or {}
    train_env = project.get("train_env") or (project.get("params") or {}).get("train_env")
    if train_env:
        candidate = Path(train_env)
        profiles["custom"] = str(candidate if candidate.suffix.lower() == ".exe" else candidate / "Scripts" / "python.exe")
    ps = shutil.which("powershell")
    hardware = _run([ps, "-NoProfile", "-NonInteractive", "-Command",
                     "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
                     "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,PNPDeviceID,Status | ConvertTo-Json -Compress"], timeout=10) if ps else {"status": "unavailable", "reason": "未找到 Windows PowerShell"}
    with ThreadPoolExecutor(max_workers=3) as pool:
        check_gpu = not ((task or {}).get("busy") or (task or {}).get("status") == "running")
        futures = {label: pool.submit(_runtime_probe, label, path, env, check_gpu) for label, path in profiles.items()}
        reports = {}
        for label, future in futures.items():
            try:
                reports[label] = future.result()
            except Exception as exc:
                reports[label] = {"status": "error", "error": "%s: %s" % (type(exc).__name__, exc)}
    safe_project = {key: project[key] for key in ("mode", "base_type", "train_env") if key in project}
    safe_project["params"] = {key: value for key, value in (project.get("params") or {}).items()
                              if key in ("amd_mode", "train_env", "mixed_precision", "rank", "alpha", "resolution", "optimizer", "blocks_to_swap", "quant_mode", "compile")}
    cache = []
    if isinstance(data_dir, str):
        for stage in ("amd_rocm", "amd_torch"):
            directory = Path(data_dir) / "installer_cache" / stage
            try:
                for path in directory.iterdir():
                    if path.is_file():
                        cache.append({"stage": stage, "filename": path.name, "bytes": path.stat().st_size,
                                      "partial": path.name.endswith(".part"), "url_encoded_filename": "%2b" in path.name.lower()})
            except OSError as exc:
                cache.append({"stage": stage, "error": str(exc)})
    selected_env = {key: env.get(key) for key in ("HSA_OVERRIDE_GFX_VERSION", "AMD_SERIALIZE_KERNEL", "HIP_VISIBLE_DEVICES", "CUDA_VISIBLE_DEVICES", "ACCELERATE_USE_CPU", "VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH") if key in env}
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix.lower() == ".txt":
        def readable(value, indent=0):
            prefix = " " * indent
            if isinstance(value, dict):
                lines = []
                for key, item in value.items():
                    if isinstance(item, (dict, list)):
                        lines.append(prefix + str(key) + ":")
                        lines.extend(readable(item, indent + 2))
                    else:
                        lines.append(prefix + str(key) + ": " + str(item).replace("\n", "\n" + prefix + "  "))
                return lines
            if isinstance(value, list):
                lines = []
                for index, item in enumerate(value):
                    lines.append(prefix + "[%d]" % index)
                    lines.extend(readable(item, indent + 2))
                return lines
            return [prefix + str(value)]

        def section(title, value):
            # Reuse JSON cleaning to mask sensitive dictionary keys as well as text.
            return "\n【%s】\n%s\n" % (title, "\n".join(readable(json.loads(_json(value)))))

        text = "Kohya-LoRA 一键训练工具 · 运行日志与环境诊断\n"
        text += "软件版本: v%s\n导出时间: %s\n" % (getattr(core, "APP_VERSION", "未知"), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        text += "本文件在本地生成，可直接发送用于排查。failed=失败，missing=未安装，timeout=超时。\n正在训练时跳过额外 GPU 计算；基础计算通过不代表完整训练通过。\n"
        text += section("环境信息", {**summary, "display_drivers": hardware, "selected_environment_variables": selected_env})
        text += section("最近任务", {key: value for key, value in (task or {}).items() if key not in ("logs", "startup_logs")})
        text += section("训练配置摘要", safe_project)
        for label, report in reports.items():
            text += section("训练环境 / " + label, report)
        text += section("下载缓存", cache)
        text += "\n【运行日志】\n" + redact(logs) + "\n"
        if session:
            text += "\n【完整会话日志】\n" + session.snapshot()
            text += section("会话日志状态", {"write_error": session.error})
        else:
            text += section("会话日志状态", {"status": "未创建，请参考运行日志", "error": (task or {}).get("session_log_error")})
        destination.write_text(redact(text), encoding="utf-8-sig")
        return str(destination)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("environment.json", _json({**summary, "display_drivers": hardware, "selected_environment_variables": selected_env}))
        archive.writestr("task.json", _json({key: value for key, value in (task or {}).items() if key not in ("logs", "startup_logs")}))
        archive.writestr("project.json", _json(safe_project))
        archive.writestr("runtime_log.txt", redact(logs))
        archive.writestr("download_cache.json", _json(cache))
        if session:
            archive.writestr("session_log.txt", session.snapshot())
            archive.writestr("session_status.json", _json({"write_error": session.error}))
        for label, report in reports.items():
            archive.writestr("runtimes/%s.json" % label, _json(report))
        archive.writestr("说明.txt", "诊断包在本地生成，没有上传。包含日志、设备驱动、各 Python 环境、依赖检查和小型 GPU 前向/反向算子结果。\n不包含模型、数据集、图片或完整环境变量。常见密钥和用户目录已脱敏。\n算子自检通过不代表完整 LoRA 训练通过；missing、failed、timeout 必须分别判断。\n")
    return str(destination)


def write_training_feedback(directory, task, gallery):
    """Export this run's configuration and logs only; no model/data files or hardware probes."""
    path = Path(directory) / ("KohyaLoRA_训练反馈_%s_%s.zip" % (
        datetime.now().strftime("%Y%m%d_%H%M%S_%f"), str(task.get("id", "run"))[:8]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("项目配置.json", _json(task.get("project_config", {})))
        bundle.writestr("提交参数.json", _json(task.get("normalized_params", {})))
        bundle.writestr("启动计划.json", _json(task.get("plan", {})))
        bundle.writestr("引擎生效参数.json", _json(task.get("effective_params", {})))
        bundle.writestr("采样状态.json", _json(task.get("sampling_status", {})))
        bundle.writestr("采样文件清单.json", _json(gallery))
        bundle.writestr("启动日志.txt", "\n".join(redact(line) for line in task.get("startup_logs", [])))
        bundle.writestr("最近日志.txt", "\n".join(redact(line) for line in task.get("logs", [])))
        bundle.writestr("说明.txt", "本资料仅包含当前任务的设置、状态和日志。未包含训练图片、采样图片或模型文件；未进行硬件实测，也不会自动上传。\n生效参数只记录工具已确认的值，缺失项不代表零或关闭。\n采样比较需确认底模、提示词、种子、尺寸与采样条件一致；Loss 不是画质评分。\n")
    return str(path)
