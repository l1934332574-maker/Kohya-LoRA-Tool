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

VERSION = "v7.3.1"
LEGACY_V7 = "v7.0.1"
LATEST_VERSION = "v8.9.6"
LATEST_COMMIT = "a62e644e0bd954240a26b619cf307db4ac64a390"
LATEST_ARCHIVE_SHA256 = "676d734f272c508e7df1009fff0b3f016c68f0bb58b82cfad79b27ed7d6017ae"
LATEST_ARCHIVE_BYTES = 21379445
# VERSION / COMMIT retain the v7 source identity for legacy callers and caches.
SUPPORTED_V7 = (LEGACY_V7, VERSION, LATEST_VERSION)
MOSS_VERSION = "v8.5.0"
SUPPORTED_STANDARD = (LEGACY_V7, VERSION, MOSS_VERSION, LATEST_VERSION)
SUPPORTED_MOSS = (MOSS_VERSION, LATEST_VERSION)
SUPPORTED_ZIMAGE = (VERSION, LATEST_VERSION)
MOSS_COMMIT = "75d54881e466c9b7f436e2e397437a8bdc38f2e1"
MOSS_ARCHIVE_SHA256 = "71c9af3781c19e74ce8fe02bf04bc2561a13ea6cad8b43b3d5d0cdd1e1596ba5"
MOSS_ARCHIVE_BYTES = 20678733
OLD_COMMIT = "1c8ec88edc1a4f99f73585aeae00fec740b12ea6"
COMMIT = "7ee4986dae28fe35cc4ef636b984729624b32b42"
ARCHIVE_SHA256 = "ed0dfe599006492d5dfb04ddbc66aae0a4237b257d05eab0424aa4280de1b3bc"
ARCHIVE_BYTES = 12666311
MIRROR = "https://modelscope.cn/models/FGtiancai/Kohya-LoRA-Tool/resolve/master/engine_sources/"
SOURCES = (
    ("魔搭国内镜像", MIRROR + "fizgig-" + VERSION + ".zip", True),
    ("GitHub 加速镜像", "https://ghfast.top/https://github.com/shootthesound/Fizgig/archive/" + COMMIT + ".zip", False),
    ("GitHub 备用加速镜像", "https://gh-proxy.com/https://github.com/shootthesound/Fizgig/archive/" + COMMIT + ".zip", False),
    ("GitHub 官方源", "https://codeload.github.com/shootthesound/Fizgig/zip/" + COMMIT, False),
)
REQUIRED = ("requirements.txt", "src/fizgig/families/train.py", "src/fizgig/families/cache.py",
            "src/fizgig/families/registry.py", "src/fizgig/klein/driver.py", "src/fizgig/krea2/driver.py",
            "src/fizgig/qwen_image21/driver.py", "src/fizgig/minimax/driver.py",
            "src/fizgig/anima/driver.py", "src/fizgig/sdxl/driver.py",
            "src/fizgig/qwen_image21/embedder.py", "src/fizgig/utils/hf_cache.py")
OLD_REQUIRED = REQUIRED
REQUIRED = (*OLD_REQUIRED, "src/fizgig/families/zimage.py", "src/fizgig/zimage/driver.py",
            "src/fizgig/zimage/model.py", "src/fizgig/zimage/pipeline.py")

MOSS_REQUIRED = ("requirements.txt", "src/fizgig/families/train.py", "src/fizgig/families/cache.py",
                 "src/fizgig/families/registry.py", "src/fizgig/families/moss_image.py",
                 "src/fizgig/moss_image/driver.py", "src/fizgig/moss_image/model.py",
                 "src/fizgig/moss_image/embedder.py", "src/fizgig/moss_image/sampling.py",
                 "src/fizgig/utils/hf_cache.py", "src/fizgig/modules/offloading.py")


LATEST_REQUIRED = tuple(dict.fromkeys((*REQUIRED, *MOSS_REQUIRED,
    "src/fizgig/dataset/masks.py", "src/fizgig/dataset/automask.py")))


def target_version(mode):
    return LATEST_VERSION


def legacy_project_version(mode):
    """An omitted version in an existing project must retain its original runtime."""
    return (MOSS_VERSION if mode == "moss_fz" else VERSION if mode == "zimage_fz"
            else LEGACY_V7 if mode in ("anima_fz", "sdxl_fz") else "v6.5.0")


def compatible_versions(mode, multi=False):
    if mode == "moss_fz":
        return SUPPORTED_MOSS
    if mode == "zimage_fz":
        return SUPPORTED_ZIMAGE
    if multi or mode in ("anima_fz", "sdxl_fz"):
        return SUPPORTED_V7
    return ("v6.5.0", *SUPPORTED_V7)


def required_files(version):
    return (LATEST_REQUIRED if version == LATEST_VERSION else MOSS_REQUIRED if version == MOSS_VERSION
            else OLD_REQUIRED if version == LEGACY_V7 else REQUIRED)


def source_commit(version):
    return (LATEST_COMMIT if version == LATEST_VERSION else MOSS_COMMIT if version == MOSS_VERSION
            else OLD_COMMIT if version == LEGACY_V7 else COMMIT)


def _adapter_revision(version):
    return 5 if version == LATEST_VERSION else 4 if version == MOSS_VERSION else 2 if version == LEGACY_V7 else 3


def _archive_identity(version):
    if version == LATEST_VERSION:
        return LATEST_ARCHIVE_BYTES, LATEST_ARCHIVE_SHA256
    if version == MOSS_VERSION:
        return MOSS_ARCHIVE_BYTES, MOSS_ARCHIVE_SHA256
    return ARCHIVE_BYTES, ARCHIVE_SHA256


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
    version = record.get("version")
    if version in SUPPORTED_STANDARD and record.get("commit") == source_commit(version) and record.get("adapter") == _adapter_revision(version):
        hashes = record.get("files") or {}
        try:
            if all((source / name).is_file() and hashes.get(name) == _sha(source / name) for name in required_files(version)):
                return version
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
    if version in SUPPORTED_STANDARD:
        return {"version": version, "source": str(root / "fizgig_versions" / version / "source"),
                "python": str(root / "fizgig_versions" / version / ("venv-rocm" if core.detect_gpu_vendor() == "amd" else "venv-cuda") / "Scripts/python.exe")}
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
    current = installed and source_version(record["source"]) == LATEST_VERSION
    candidates = dict.fromkeys([*(_registry(core).get("installs") or {}), "v6.5.0", *SUPPORTED_STANDARD])
    versions = []
    for version in candidates:
        if version not in ("v6.5.0", *SUPPORTED_STANDARD):
            continue
        candidate = runtime(core, version)
        if Path(candidate["python"]).is_file() and source_version(candidate["source"]) == version:
            versions.append(version)
    return {"installed": installed, "update_available": installed and not current,
            "target_version": LATEST_VERSION, "current_version": record.get("version") or "待识别",
            "engine_dir": record["source"], "h3_supported": installed, "qwen_image_2_supported": installed,
            "new_families_supported": installed and source_version(record["source"]) in (VERSION, MOSS_VERSION, LATEST_VERSION), "versions": versions, "standard_versions": list(SUPPORTED_STANDARD)}


def download(core, logf, version=LATEST_VERSION):
    if version not in (VERSION, MOSS_VERSION, LATEST_VERSION):
        raise ValueError("此版本没有自动安装通道：" + version)
    size, digest = _archive_identity(version)
    sources = SOURCES if version == VERSION else (
        ("魔搭国内镜像", MIRROR + "fizgig-" + version + ".zip", True),
        ("GitHub 加速镜像", "https://ghfast.top/https://github.com/shootthesound/Fizgig/archive/" + source_commit(version) + ".zip", False),
        ("GitHub 官方源", "https://codeload.github.com/shootthesound/Fizgig/zip/" + source_commit(version), False),
    )
    if version == LATEST_VERSION:
        sources = tuple(item for item in sources if not item[2])
    path = Path(core._engine_source_cache_dir()) / ("fizgig-%s.zip" % version)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.stat().st_size == size and _sha(path) == digest:
        logf("[Fizgig] 复用已校验源码缓存：%s" % version)
        return path
    for label, url, direct in sources:
        core.check_stop()
        logf("[Fizgig] 下载 %s（%.1f MB），来源：%s" % (version, size / 1048576, label))
        if core._download_with_resume(url, str(path), logf, direct=direct, quick_fail=True):
            if path.stat().st_size == size and _sha(path) == digest:
                return path
            logf("[Fizgig] 源码校验不匹配，已隔离该文件并切换来源。")
            path.rename(path.with_name(path.name + ".invalid.%s" % time.time_ns()))
        # Archive sources must have identical bytes. A failed request may have
        # returned an HTML body; never splice that body into the next source.
        part = Path(str(path) + ".part")
        if part.is_file():
            part.rename(part.with_name(part.name + ".retry.%s" % time.time_ns()))
    raise RuntimeError("Fizgig 国内镜像及备用源码均下载失败；原引擎仍保留，可稍后重试。")


def _deploy(core, archive, source, version=LATEST_VERSION):
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
    if not all((source / name).is_file() for name in required_files(version)):
        raise RuntimeError("Fizgig 源码缺少新版模型家族入口。")
    _patch_helpers(source, version)
    _write(source / ".kohya-fizgig-source.json", {"version": version, "commit": source_commit(version),
            "archive_sha256": _archive_identity(version)[1], "adapter": _adapter_revision(version),
            "files": {name: _sha(source / name) for name in required_files(version)}})


def _patch_helpers(source, version=VERSION):
    """Use prepared local configs; patches are pinned, narrow, and fail closed."""
    if version == MOSS_VERSION:
        return _patch_moss_source(source)
    if version == LATEST_VERSION:
        _patch_latest_offloading(source)
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
    path = source / "src/fizgig/zimage/pipeline.py"
    text = path.read_text(encoding="utf-8")
    anchor = "    local = cached_snapshot_dir(config)"
    if text.count(anchor) != 1:
        raise RuntimeError("Fizgig Z-Image VAE 配置接口变化。")
    text = text.replace(anchor, "    import json, os\n    local = json.loads(os.environ.get('FIZGIG_LOCAL_HELPERS', '{}')).get(config) or cached_snapshot_dir(config)")
    # Prepared config failures must be reported instead of silently contacting the Hub.
    text = text.replace("        except Exception:\n            pass", "        except Exception:\n            raise")
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
    text = text.replace(state_anchor, 'state_dir = os.path.join(output_dir, "snapshots", "fizgig-%s", f"{output_name}-{epoch:06d}-state")' % version)
    text = text.replace("prune_state_dirs(output_dir, output_name, keep_last_n_states)",
                        'prune_state_dirs(os.path.join(output_dir, "snapshots", "fizgig-%s"), output_name, keep_last_n_states)' % version)
    path.write_text(text, encoding="utf-8")



def _patch_latest_offloading(source):
    """Keep mixed BF16/INT8 blocks on separate storage in the v8.9.6 offloader."""
    import ast
    path = Path(source) / "src/fizgig/modules/offloading.py"
    text = path.read_text(encoding="utf-8")
    marker = "# KOHYA_TOOL_PATCH: mixed block storage v1"
    if marker in text:
        return False
    tree = ast.parse(text)
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
             and n.name in ("swap_weight_devices_no_cuda", "swap_weight_devices_cuda")]
    if (len(nodes) != 2 or text.count("def _streamed_linears(") != 1
            or text.count("class Offloader:") != 1):
        raise RuntimeError("Fizgig 块交换接口变化，已停止训练；引擎文件未改动。")
    lines = text.splitlines(keepends=True)
    for node in sorted(nodes, key=lambda n: n.lineno, reverse=True):
        first = next((n for n in node.body if isinstance(n, ast.Assert)), None)
        if first is None:
            raise RuntimeError("Fizgig 块交换入口变化，已停止训练。")
        indent = " " * first.col_offset
        guard = [
            "if not _kohya_swap_storage_compatible(layer_to_cpu, layer_to_cuda):",
            "    _synchronize_device(device)",
            '    weighs_to_device(layer_to_cpu, torch.device("cpu"))',
            "    weighs_to_device(layer_to_cuda, device)",
            "    _synchronize_device(device)",
            "    return None",
        ]
        lines[first.end_lineno:first.end_lineno] = [indent + line + "\n" for line in guard]
    helper = marker + "\n" + '''def _kohya_swap_storage_compatible(layer_a, layer_b):
    a, b = _streamed_linears(layer_a), _streamed_linears(layer_b)
    return a.keys() == b.keys() and all(
        a[name].weight.shape == module.weight.shape
        and a[name].weight.dtype == module.weight.dtype
        for name, module in b.items())


'''
    updated = "".join(lines).replace("class Offloader:", helper + "class Offloader:", 1)
    compile(updated, str(path), "exec")
    temporary = path.with_name(path.name + ".kohya-tmp-" + str(os.getpid()))
    try:
        temporary.write_text(updated, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists(): temporary.unlink()
    return True


def ensure_preview_offloading(record, log=print):
    """Apply the software compatibility fix to an already verified installed source."""
    if record.get("version") != LATEST_VERSION:
        return False
    source = Path(record["source"])
    if source_version(source) != LATEST_VERSION:
        raise RuntimeError("Fizgig 源码校验未通过；已停止处理预览兼容补丁。")
    path = source / "src/fizgig/modules/offloading.py"
    previous = path.read_bytes()
    if "# KOHYA_TOOL_PATCH: mixed block storage v1" in previous.decode("utf-8"):
        return False
    marker_path = source / ".kohya-fizgig-source.json"
    marker = _read(marker_path)
    backup = path.with_name(path.name + ".kohya-mixed-storage.bak")
    if not backup.exists(): backup.write_bytes(previous)
    try:
        _patch_latest_offloading(source)
        marker["files"]["src/fizgig/modules/offloading.py"] = _sha(path)
        _write(marker_path, marker)
    except BaseException:
        path.write_bytes(previous)
        raise
    log("[Fizgig] 已补齐混合精度块交换保护；保留原引擎版本，无需重新下载。")
    return True


def _patch_moss_offloading(source):
    # MOSS omits LoRA on block 22. Match the resident base Linears by their
    # logical name even when only one side has a LoRALinear wrapper.
    path = source / "src/fizgig/modules/offloading.py"
    text = path.read_text(encoding="utf-8")
    before = "            modules_to_cpu = {k: v for k, v in layer_to_cpu.named_modules()}\n            for module_to_cuda_name, module_to_cuda in layer_to_cuda.named_modules():"
    after = "            modules_to_cpu = dict(_kohya_swap_linears(layer_to_cpu))\n            for module_to_cuda_name, module_to_cuda in _kohya_swap_linears(layer_to_cuda):"
    if text.count(before) != 1:
        raise RuntimeError("Fizgig MOSS 预览块交换接口变化。")
    helper = '''def _kohya_swap_linears(layer):
    modules = dict(layer.named_modules())
    for name, module in modules.items():
        if not module.__class__.__name__.endswith("Linear") or not hasattr(module, "weight") or module.weight is None:
            continue
        parent, separator, child = name.rpartition(".")
        if child == "base" and separator and modules[parent].__class__.__name__ == "LoRALinear":
            name = parent
        yield name, module


'''
    # Block 22 remains BF16 while its neighbours can be INT8. Reusing their
    # storage would silently change Parameter.dtype and corrupt both blocks.
    guard = """        cpu_linears = dict(_kohya_swap_linears(layer_to_cpu))
        gpu_linears = dict(_kohya_swap_linears(layer_to_cuda))
        if cpu_linears.keys() != gpu_linears.keys() or any(
            cpu_linears[name].weight.shape != module.weight.shape
            or cpu_linears[name].weight.dtype != module.weight.dtype
            for name, module in gpu_linears.items()
        ):
            torch.cuda.current_stream().synchronize()
            weighs_to_device(layer_to_cpu, torch.device("cpu"))
            weighs_to_device(layer_to_cuda, device)
            torch.cuda.current_stream().synchronize()
            return None

"""
    anchor = "        debug_print = False\n"
    if text.count(anchor) != 1:
        raise RuntimeError("Fizgig MOSS 预览交换入口变化。")
    text = text.replace("class Offloader:", helper + "class Offloader:").replace(before, after)
    text = text.replace(anchor, guard + anchor)
    path.write_text(text, encoding="utf-8")


def _patch_moss_source(source):
    _patch_moss_offloading(source)
    path = source / "src/fizgig/utils/hf_cache.py"
    text = path.read_text(encoding="utf-8")
    anchor = "    local = cached_snapshot_dir(repo_id)"
    if text.count(anchor) != 1:
        raise RuntimeError("Fizgig MOSS 本地分词器接口变化。")
    text = text.replace(anchor, "    import json\n    paths = json.loads(os.environ.get('FIZGIG_LOCAL_HELPERS', '{}'))\n    if repo_id in paths:\n        return cls.from_pretrained(paths[repo_id], local_files_only=True, **kwargs)\n" + anchor)
    path.write_text(text, encoding="utf-8")
    path = source / "src/fizgig/families/train.py"
    text = path.read_text(encoding="utf-8")
    changes = [
        ('"architecture": arch_id, **(extra or {})', '"architecture": arch_id, **(extra or {}), "kohya_runtime": json.loads(os.environ.get("FIZGIG_KOHYA_RUNTIME", "{}")), "kohya_complete": epoch >= int(os.environ.get("FIZGIG_KOHYA_TARGET_EPOCHS", "2147483647"))'),
        ('state_dir = os.path.join(output_dir, f"{output_name}-{epoch:06d}-state")', 'state_dir = os.path.join(output_dir, "snapshots", "fizgig-v8.5.0", f"{output_name}-{epoch:06d}-state")'),
        ('prune_state_dirs(output_dir, output_name, keep_last_n_states)', 'prune_state_dirs(os.path.join(output_dir, "snapshots", "fizgig-v8.5.0"), output_name, keep_last_n_states)'),
    ]
    for before, after in changes:
        if text.count(before) != 1:
            raise RuntimeError("Fizgig MOSS 续训接口变化，已停止部署。")
        text = text.replace(before, after)
    path.write_text(text, encoding="utf-8")


def _env(core, record):
    env = (core._fizgig_rocm_env(record["source"], record["python"]) if record.get("backend") == "amd-rocm"
           else core.build_direct_env())
    if record.get("version") in SUPPORTED_MOSS:
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        if sys.platform == "win32":
            # Avoid mapping every BF16 Qwen shard at once on Windows. The
            # upstream file reader loads streamed layers only when needed.
            env.setdefault("FIZGIG_TE_FROM_FILE", "1")
            env.setdefault("PYTHONFAULTHANDLER", "1")
    return env


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
        matched = result.returncode == 0 and all(found.get(p) == v for p, v in packages.items())
        if matched and record["backend"] == "amd-rocm":
            from .amd_runtime import SELECTION_ERROR, require_device_packages
            arch = env.get("KOHYA_ROCM_DEVICE_ARCH")
            if env.get(SELECTION_ERROR) or not arch:
                return False
            require_device_packages(record["python"], arch, env)
        return matched
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
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


def ensure_selected_runtime(core, version, logf=print):
    """Prepare the selected runtime; an existing legacy choice never upgrades."""
    if version in (VERSION, MOSS_VERSION, LATEST_VERSION):
        return install(core, logf, version=version)
    if version not in ("v6.5.0", *SUPPORTED_STANDARD):
        raise ValueError("未接入这个 Fizgig 版本：%s" % version)
    record = runtime(core, version)
    if not Path(record["python"]).is_file() or source_version(record["source"]) != version:
        raise RuntimeError("未检测到完整的 Fizgig %s 安装，请检查原引擎目录；也可以在项目中选择 %s 后安装。" % (version, LATEST_VERSION))
    backend = record.get("backend") or ("amd-rocm" if core.detect_gpu_vendor() == "amd" else "nvidia")
    with use_runtime(core, {"fizgig_version": version}):
        core._fizgig_verify(record["python"], record["source"], logf, backend=backend)
    core.clear_status_cache()
    logf("[Fizgig] 已复用项目选定版本 %s；无需下载 %s。" % (version, LATEST_VERSION))
    return record["python"]


def install(core, logf=print, version=LATEST_VERSION):
    if version not in (VERSION, MOSS_VERSION, LATEST_VERSION):
        raise ValueError("没有此版本的安装通道：" + version)
    root = Path(core.get_kohya_dir())
    root.mkdir(parents=True, exist_ok=True)
    lock = core._acquire_kohya_install_lock(str(root), logf)
    if lock is None:
        raise RuntimeError("另一个环境任务正在运行，请完成后再更新 Fizgig。")
    try:
        registry = _registry(core)
        previous = runtime(core)
        if previous.get("version") == version and source_version(previous["source"]) == version and Path(previous["python"]).is_file() and core._python312_64bit(previous["python"]) and _dependencies_match(previous, _env(core, previous)):
            core.check_stop()
            core._fizgig_verify(previous["python"], previous["source"], logf, backend=previous.get("backend", "nvidia"))
            core.check_stop()
            logf("[Fizgig] 已安装 %s，环境检查通过；无需重复下载。" % version)
            return previous["python"]
        vendor = core.detect_gpu_vendor()
        if vendor not in ("amd", "nvidia"):
            raise RuntimeError("Fizgig 当前接入支持 NVIDIA CUDA / AMD ROCm；未识别到支持的显卡，请检查驱动。")
        backend = "amd-rocm" if vendor == "amd" else "nvidia"
        folder = root / "fizgig_versions" / version
        source = folder / "source"
        if source_version(source) != version:
            _deploy(core, download(core, logf, version), source, version)
        record = {"version": version, "source": str(source), "backend": backend}
        candidate = dict(previous, backend=backend)
        if Path(candidate["python"]).is_file() and core._python312_64bit(candidate["python"]) and _dependencies_match(candidate, _env(core, candidate)):
            record["python"] = candidate["python"]
            logf("[Fizgig] 复用匹配的 GPU 环境；不重新下载 torch / ROCm。")
        else:
            venv = folder / ("venv-rocm" if backend == "amd-rocm" else "venv-cuda")
            record["python"] = str(venv / "Scripts/python.exe")
            py = core._fizgig_ensure_python312(logf)
            if Path(record["python"]).is_file() and not core._python312_64bit(record["python"]):
                # Preserve incompatible venvs; never move an arbitrary registry path.
                resolved = venv.resolve()
                if resolved.parent != folder.resolve() or resolved.name not in ("venv-rocm", "venv-cuda"):
                    raise RuntimeError("训练环境路径超出当前引擎目录，无法自动备份。")
                backup = venv.with_name(venv.name + ".incompatible-" + str(time.time_ns()))
                if backup.resolve().parent != folder.resolve():
                    raise RuntimeError("训练环境备份路径超出当前引擎目录。")
                logf("[Fizgig] 现有环境不是可用的 64 位 Python 3.12；将备份后重建。")
                try:
                    venv.rename(backup)
                except OSError as exc:
                    raise RuntimeError("无法备份原训练环境，请关闭占用它的程序后重试：%s" % exc) from exc
                logf("[Fizgig] 原环境已保留到：%s" % backup)
            if not Path(record["python"]).is_file():
                logf("[Fizgig] 创建新版独立环境；旧版本保持原路径。")
                if core.run_stream([py, "-m", "venv", str(venv)], cwd=str(root), logf=logf):
                    raise RuntimeError("Fizgig 新环境创建失败，原版本仍保留。")
            if not core._python312_64bit(record["python"]):
                raise RuntimeError("Fizgig 环境需要 64 位 Python 3.12；当前环境架构不匹配，已停止安装 GPU 依赖。")
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
        logf("[Fizgig] 正在检查 GPU 环境和模型入口…")
        core._fizgig_verify(record["python"], str(source), logf, backend=backend)
        core.check_stop()
        installs = dict(registry.get("installs") or {})
        if previous.get("version") and Path(previous["python"]).is_file():
            installs.setdefault(previous["version"], previous)
        installs[version] = record
        _write(root / "fizgig_installs.json", {"schema": 1, "active": version,
               "previous": (previous.get("version") if previous.get("version") != version else registry.get("previous")), "installs": installs})
        core.clear_status_cache()
        logf("[Fizgig] %s 已就绪。模型与项目不移动；旧项目可继续使用原引擎版本。" % version)
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
