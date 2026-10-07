"""Pinned Fizgig installs, with source/environment pairs and an atomic active pointer.

No GPU work or network request runs at import time. Existing v6 installs remain
available for old projects; dependency changes never modify their environment.
"""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

VERSION = "v7.0.1"
COMMIT = "1c8ec88edc1a4f99f73585aeae00fec740b12ea6"
ARCHIVE_SHA256 = "526b6dcac6e0f470031c98249b3bf10dea74df6a73a4d2e4f52f5a419c7178e4"
ARCHIVE_BYTES = 11098816
MIRROR = "https://modelscope.cn/models/FGtiancai/Kohya-LoRA-Tool/resolve/master/engine_sources/"
SOURCES = (
    ("魔搭国内镜像", MIRROR + "fizgig-v7.0.1.zip", True),
    ("GitHub 加速镜像", "https://ghfast.top/https://github.com/shootthesound/Fizgig/archive/" + COMMIT + ".zip", False),
    ("GitHub 备用加速镜像", "https://gh-proxy.com/https://github.com/shootthesound/Fizgig/archive/" + COMMIT + ".zip", False),
    ("GitHub 官方源", "https://codeload.github.com/shootthesound/Fizgig/zip/" + COMMIT, False),
)
REQUIRED = ("requirements.txt", "src/fizgig/families/train.py", "src/fizgig/families/cache.py",
            "src/fizgig/families/registry.py", "src/fizgig/klein/driver.py", "src/fizgig/krea2/driver.py",
            "src/fizgig/qwen_image21/driver.py", "src/fizgig/minimax/driver.py",
            "src/fizgig/anima/driver.py", "src/fizgig/sdxl/driver.py",
            "src/fizgig/qwen_image21/embedder.py", "src/fizgig/utils/hf_cache.py")
_CONTEXT = contextvars.ContextVar("kohya_fizgig_runtime", default=None)


def _read(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(path.name + ".tmp.%s" % os.getpid())
    staged.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(staged, path)


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def source_version(source):
    source = Path(source)
    record = _read(source / ".kohya-fizgig-source.json")
    if record.get("version") == VERSION and record.get("commit") == COMMIT and record.get("adapter") == 2:
        hashes = record.get("files") or {}
        try:
            if all((source / name).is_file() and hashes.get(name) == _sha(source / name) for name in REQUIRED):
                return VERSION
        except OSError:
            return ""
        return ""
    if (source / "src/fizgig/scripts/krea2_train.py").is_file():
        return "v6.5.0" if (source / "docs/RELEASE_NOTES_v6.5.0.md").is_file() else "legacy"
    return ""


def _registry(core):
    return _read(Path(core.get_kohya_dir()) / "fizgig_installs.json")


def runtime(core, version=None):
    bound = _CONTEXT.get()
    if bound and version is None:
        return dict(bound)
    registry = _registry(core)
    wanted = version or registry.get("active")
    installs = registry.get("installs") or {}
    if wanted in installs:
        record = dict(installs[wanted])
        record["version"] = wanted
        return record
    root = Path(core.get_kohya_dir())
    legacy = {"version": source_version(root / "fizgig"), "source": str(root / "fizgig"),
              "python": str(root / "fizgig_venv/Scripts/python.exe")}
    if version in (None, "v6.5.0", "legacy"):
        return legacy
    if version == VERSION:
        return {"version": VERSION, "source": str(root / "fizgig_versions" / VERSION / "source"),
                "python": str(root / "fizgig_versions" / VERSION / ("venv-rocm" if core.detect_gpu_vendor() == "amd" else "venv-cuda") / "Scripts/python.exe")}
    raise ValueError("未安装或不支持的 Fizgig 版本：%s" % version)


@contextlib.contextmanager
def use_runtime(core, params):
    wanted = (params or {}).get("fizgig_version")
    record = runtime(core, wanted or None)
    token = _CONTEXT.set(record)
    try:
        yield record
    finally:
        _CONTEXT.reset(token)


def update_status(core):
    record = runtime(core)
    installed = Path(record["python"]).is_file() and bool(source_version(record["source"]))
    current = installed and source_version(record["source"]) == VERSION
    versions = list((_registry(core).get("installs") or {}).keys())
    old = runtime(core, "v6.5.0")
    if Path(old["python"]).is_file() and source_version(old["source"]) and "v6.5.0" not in versions:
        versions.append("v6.5.0")
    return {"installed": installed, "update_available": installed and not current,
            "target_version": VERSION, "current_version": record.get("version") or "待识别",
            "engine_dir": record["source"], "h3_supported": installed, "qwen_image_2_supported": installed,
            "new_families_supported": current, "versions": versions}


def download(core, logf):
    path = Path(core._engine_source_cache_dir()) / ("fizgig-%s.zip" % VERSION)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.stat().st_size == ARCHIVE_BYTES and _sha(path) == ARCHIVE_SHA256:
        logf("[Fizgig] 复用已校验源码缓存：%s" % VERSION)
        return path
    for label, url, direct in SOURCES:
        core.check_stop()
        logf("[Fizgig] 下载 %s（%.1f MB），来源：%s" % (VERSION, ARCHIVE_BYTES / 1048576, label))
        if core._download_with_resume(url, str(path), logf, direct=direct, quick_fail=True):
            if path.stat().st_size == ARCHIVE_BYTES and _sha(path) == ARCHIVE_SHA256:
                return path
            logf("[Fizgig] 源码校验不匹配，已隔离该文件并切换来源。")
            path.rename(path.with_name(path.name + ".invalid.%s" % time.time_ns()))
        # Archive sources must have identical bytes. A failed request may have
        # returned an HTML body; never splice that body into the next source.
        part = Path(str(path) + ".part")
        if part.is_file():
            part.rename(part.with_name(part.name + ".retry.%s" % time.time_ns()))
    raise RuntimeError("Fizgig 国内镜像及备用源码均下载失败；原引擎仍保留，可稍后重试。")


def _deploy(core, archive, source):
    source.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise RuntimeError("Fizgig 源码归档损坏。")
        prefix = z.namelist()[0].split("/")[0] + "/"
        for entry in z.infolist():
            relative = entry.filename.removeprefix(prefix)
            if not relative or entry.is_dir():
                continue
            target = (source / relative).resolve()
            if not target.is_relative_to(source.resolve()):
                raise RuntimeError("Fizgig 归档包含越界路径。")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(entry))
    if not all((source / name).is_file() for name in REQUIRED):
        raise RuntimeError("Fizgig 源码缺少新版模型家族入口。")
    _patch_helpers(source)
    _write(source / ".kohya-fizgig-source.json", {"version": VERSION, "commit": COMMIT,
            "archive_sha256": ARCHIVE_SHA256, "adapter": 2,
            "files": {name: _sha(source / name) for name in REQUIRED}})


def _patch_helpers(source):
    """Use prepared local configs; patches are pinned, narrow, and fail closed."""
    patches = {
        "src/fizgig/anima/driver.py": [
            ('AutoTokenizer.from_pretrained(HELPER, subfolder="tokenizer")',
             'AutoTokenizer.from_pretrained(os.environ["FIZGIG_ANIMA_HELPER_DIR"], subfolder="tokenizer", local_files_only=True)'),
            ('hf_hub_download(HELPER, "t5_tokenizer/tokenizer.json")',
             'os.path.join(os.environ["FIZGIG_ANIMA_HELPER_DIR"], "t5_tokenizer", "tokenizer.json")')],
        "src/fizgig/sdxl/driver.py": [
            ('config=CONFIG_REPO', 'config=os.environ["FIZGIG_SDXL_CONFIG_DIR"], local_files_only=True')],
    }
    for relative, changes in patches.items():
        path = source / relative
        text = path.read_text(encoding="utf-8")
        for old, new in changes:
            if old not in text:
                raise RuntimeError("Fizgig 国内配置适配入口变化：%s" % relative)
            text = text.replace(old, new)
        if "import os\n" not in text:
            # The upstream modules have no future imports. Insert after their
            # docstring rather than ahead of any future import.
            import ast
            first = ast.parse(text).body[0]
            lines = text.splitlines(keepends=True)
            lines.insert(first.end_lineno if isinstance(first, ast.Expr) else 0, "\nimport os\n")
            text = "".join(lines)
        path.write_text(text, encoding="utf-8")
    path = source / "src/fizgig/utils/hf_cache.py"
    text = path.read_text(encoding="utf-8")
    anchor = "    local = cached_snapshot_dir(repo_id)"
    if text.count(anchor) != 1:
        raise RuntimeError("Fizgig 本地分词器接口变化。")
    text = text.replace(anchor, "    import json\n    paths = json.loads(os.environ.get('FIZGIG_LOCAL_HELPERS', '{}'))\n    if repo_id in paths:\n        return cls.from_pretrained(paths[repo_id], local_files_only=True, **kwargs)\n" + anchor)
    path.write_text(text, encoding="utf-8")
    path = source / "src/fizgig/qwen_image21/embedder.py"
    text = path.read_text(encoding="utf-8")
    marker = 'tokenizer_dir = tokenizer_dir or os.environ.get("FIZGIG_QWEN21_PROCESSOR_DIR")'
    if marker not in text:
        anchor = "        self.tokenizer = (AutoTokenizer.from_pretrained(tokenizer_dir) if tokenizer_dir else\n"
        if text.count(anchor) != 1:
            raise RuntimeError("Fizgig Qwen processor 接口变化，已保留旧引擎。")
        text = text.replace(anchor, "        " + marker + "\n" + anchor)
        path.write_text(text, encoding="utf-8")


    # Bind metadata to each snapshot, rather than a mutable output-level marker.
    path = source / "src/fizgig/families/train.py"
    text = path.read_text(encoding="utf-8")
    anchor = '"architecture": arch_id, **(extra or {})'
    if text.count(anchor) != 1:
        raise RuntimeError("Fizgig 续训快照接口变化。")
    text = text.replace(anchor, '"architecture": arch_id, **(extra or {}), "kohya_runtime": json.loads(os.environ.get("FIZGIG_KOHYA_RUNTIME", "{}")), "kohya_complete": epoch >= int(os.environ.get("FIZGIG_KOHYA_TARGET_EPOCHS", "2147483647"))')
    state_anchor = 'state_dir = os.path.join(output_dir, f"{output_name}-{epoch:06d}-state")'
    if text.count(state_anchor) != 1 or text.count("prune_state_dirs(output_dir, output_name, keep_last_n_states)") != 1:
        raise RuntimeError("Fizgig 快照目录接口变化。")
    text = text.replace(state_anchor, 'state_dir = os.path.join(output_dir, "snapshots", "fizgig-v7.0.1", f"{output_name}-{epoch:06d}-state")')
    text = text.replace("prune_state_dirs(output_dir, output_name, keep_last_n_states)",
                        'prune_state_dirs(os.path.join(output_dir, "snapshots", "fizgig-v7.0.1"), output_name, keep_last_n_states)')
    path.write_text(text, encoding="utf-8")


def _env(core, record):
    if record.get("backend") == "amd-rocm":
        return core._fizgig_rocm_env(record["source"], record["python"])
    return core.build_direct_env()


def _dependencies_match(record, env):
    # Read installed distributions, without importing torch or downloading.
    packages = {"torch": "2.12.0+rocm7.15.0a20260728" if record["backend"] == "amd-rocm" else "2.10.0+cu128",
                "accelerate": "1.6.0", "diffusers": "0.32.1", "safetensors": "0.5.3",
                "transformers": "4.57.6", "tokenizers": "0.22.2", "hqq": "0.2.8.post1",
                "comfy-kitchen": "0.2.31", "toml": "0.10.2", "voluptuous": "0.15.2", "omegaconf": "2.3.0",
                "torchvision": "0.27.0+rocm7.15.0a20260728" if record["backend"] == "amd-rocm" else "0.25.0+cu128",
                "bitsandbytes": "0.50.2.dev0" if record["backend"] == "amd-rocm" else "0.48.2"}
    code = "import importlib.metadata as m,json; wanted=%r; print(json.dumps({p:m.version(p) for p in wanted}))" % list(packages)
    try:
        result = subprocess.run([record["python"], "-c", code], env=env, capture_output=True, text=True, timeout=60)
        found = json.loads(result.stdout or "{}")
        return result.returncode == 0 and all(found.get(p) == v for p, v in packages.items())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def cli_ready(core, record):
    env = _env(core, record)
    for entry, flags in (("train.py", ("--precision", "--family_option", "--resume", "--sample_every_n_epochs")),
                         ("cache.py", ("--stage", "--model", "--aux"))):
        result = subprocess.run([record["python"], str(Path(record["source"]) / "src/fizgig/families" / entry),
                                 "--help"], cwd=record["source"], env=env,
                                capture_output=True, text=True, timeout=180)
        output = result.stdout or ""
        if result.returncode or any(flag not in output for flag in flags):
            raise RuntimeError("Fizgig %s 入口不可用：%s" % (entry, (result.stderr or output)[-600:]))


def install(core, logf=print):
    root = Path(core.get_kohya_dir())
    root.mkdir(parents=True, exist_ok=True)
    lock = core._acquire_kohya_install_lock(str(root), logf)
    if lock is None:
        raise RuntimeError("另一个环境任务正在运行，请完成后再更新 Fizgig。")
    try:
        registry = _registry(core)
        previous = runtime(core)
        if previous.get("version") == VERSION and source_version(previous["source"]) == VERSION and Path(previous["python"]).is_file() and _dependencies_match(previous, _env(core, previous)):
            core.check_stop()
            core._fizgig_verify(previous["python"], previous["source"], logf, backend=previous.get("backend", "nvidia"))
            core.check_stop()
            logf("[Fizgig] 已安装 %s，环境检查通过；无需重复下载。" % VERSION)
            return previous["python"]
        vendor = core.detect_gpu_vendor()
        if vendor not in ("amd", "nvidia"):
            raise RuntimeError("Fizgig 当前接入支持 NVIDIA CUDA / AMD ROCm；未识别到支持的显卡，请检查驱动。")
        backend = "amd-rocm" if vendor == "amd" else "nvidia"
        folder = root / "fizgig_versions" / VERSION
        source = folder / "source"
        if source_version(source) != VERSION:
            _deploy(core, download(core, logf), source)
        record = {"version": VERSION, "source": str(source), "backend": backend}
        candidate = dict(previous, backend=backend)
        if Path(candidate["python"]).is_file() and _dependencies_match(candidate, _env(core, candidate)):
            record["python"] = candidate["python"]
            logf("[Fizgig] 复用匹配的 GPU 环境；不重新下载 torch / ROCm。")
        else:
            venv = folder / ("venv-rocm" if backend == "amd-rocm" else "venv-cuda")
            record["python"] = str(venv / "Scripts/python.exe")
            py = core._fizgig_ensure_python312(logf)
            if not Path(record["python"]).is_file():
                logf("[Fizgig] 创建新版独立环境；旧版本保持原路径。")
                if core.run_stream([py, "-m", "venv", str(venv)], cwd=str(root), logf=logf):
                    raise RuntimeError("Fizgig 新环境创建失败，原版本仍保留。")
            if not core._ensure_venv_pip(record["python"], str(venv), logf, label="Fizgig"):
                raise RuntimeError("Fizgig 新环境缺少 pip。")
            if not core._upgrade_pip(record["python"], str(root), logf, label="Fizgig"):
                raise RuntimeError("国内依赖源无法准备 pip，请稍后重试。")
            if backend == "amd-rocm":
                core._install_windows_amd_rocm_runtime(record["python"], str(source), logf, label="Fizgig")
            else:
                core._preinstall_torch(record["python"], str(root), logf,
                    torch_ver=core.FIZGIG_TORCH_VERSION, tv_ver=core.FIZGIG_TORCHVISION_VERSION,
                    cu=core.FIZGIG_TORCH_CU, label="Fizgig")
            dependencies = core.FIZGIG_SHARED_DEPS + " omegaconf==2.3.0 " + (core.FIZGIG_ROCM_EXTRA_DEPS if backend == "amd-rocm" else core.FIZGIG_NVIDIA_EXTRA_DEPS)
            requirements = folder / "requirements-domestic.txt"
            requirements.write_text("\n".join(dependencies.split()) + "\n", encoding="utf-8")
            env = core._domestic_pip_env()
            env["DISABLE_CUDA"] = "1"
            if core.run_stream([record["python"], "-m", "pip", "install", "--no-input", "--retries", "3", "--timeout", "60",
                                "--index-url", core.PIP_INDEX_PRIMARY, "--extra-index-url", core.PIP_INDEX_SECONDARY,
                                "-r", str(requirements)], cwd=str(source), env=env, logf=logf):
                raise RuntimeError("Fizgig 新版依赖安装失败，原版本仍可使用。")
        core.check_stop()
        logf("[Fizgig] 正在检查 GPU 环境和六个模型入口…")
        core._fizgig_verify(record["python"], str(source), logf, backend=backend)
        core.check_stop()
        installs = dict(registry.get("installs") or {})
        if previous.get("version") and Path(previous["python"]).is_file():
            installs.setdefault(previous["version"], previous)
        installs[VERSION] = record
        _write(root / "fizgig_installs.json", {"schema": 1, "active": VERSION,
               "previous": (previous.get("version") if previous.get("version") != VERSION else registry.get("previous")), "installs": installs})
        core.clear_status_cache()
        logf("[Fizgig] %s 已就绪。模型与项目不移动；旧项目可继续使用原引擎版本。" % VERSION)
        return record["python"]
    finally:
        core._release_kohya_install_lock(lock)


def rollback(core, logf=print):
    registry = _registry(core)
    previous = registry.get("previous")
    record = (registry.get("installs") or {}).get(previous)
    if not record or not Path(record["python"]).is_file() or not source_version(record["source"]):
        raise RuntimeError("没有可回退的完整 Fizgig 源码与环境。")
    lock = core._acquire_kohya_install_lock(core.get_kohya_dir(), logf)
    if lock is None:
        raise RuntimeError("另一个环境任务正在运行。")
    try:
        registry["active"], registry["previous"] = previous, registry.get("active")
        _write(Path(core.get_kohya_dir()) / "fizgig_installs.json", registry)
        core.clear_status_cache()
        logf("[Fizgig] 已切回 %s；模型和项目数据未移动。" % previous)
        return {"version": previous}
    finally:
        core._release_kohya_install_lock(lock)
