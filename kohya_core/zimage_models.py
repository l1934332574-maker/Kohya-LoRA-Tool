"""Z-Image split weights, project settings and managed component assets."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import struct
from pathlib import Path

PROJECT_KEY = "at_model"
PATH_KEYS = ("local_dir", "text_encoder_path", "vae_path")
FIELD_KEYS = (*PATH_KEYS, "model_id", "arch", "label", "size", "hint",
              "min_vram", "rec_vram", "resident_vram")
_FLOAT_BYTES = {"F16": 2, "BF16": 2, "F32": 4, "F64": 8}


def settings(core, config=None):
    """An explicit project selection, including {}, overrides legacy defaults."""
    if isinstance(config, dict) and isinstance(config.get(PROJECT_KEY), dict):
        return {k: v for k, v in config[PROJECT_KEY].items() if k in FIELD_KEYS and v not in (None, "")}
    return core.at_image_custom_get("zimage")


def read_header(path):
    """Read tensor metadata only, rejecting truncated/quantized weights."""
    path = Path(path)
    if not path.is_file() or path.suffix.lower() != ".safetensors":
        raise ValueError("请选择 safetensors 权重文件。")
    size = path.stat().st_size
    with path.open("rb") as stream:
        raw = stream.read(8)
        if len(raw) != 8:
            raise ValueError("权重文件不完整。")
        length = struct.unpack("<Q", raw)[0]
        if not 2 <= length <= min(32 * 1024 * 1024, size - 8):
            raise ValueError("权重文件头无效或文件下载不完整。")
        try:
            header = json.loads(stream.read(length))
        except (UnicodeError, ValueError) as exc:
            raise ValueError("无法读取 safetensors 文件头。") from exc
    if not isinstance(header, dict):
        raise ValueError("权重文件头格式无效。")
    tensors = {k: v for k, v in header.items() if k != "__metadata__"}
    spans = []
    for name, tensor in tensors.items():
        if not isinstance(tensor, dict):
            raise ValueError("权重张量元数据无效。")
        dtype = tensor.get("dtype")
        if dtype not in _FLOAT_BYTES or any(s in name.lower() for s in ("weight_scale", ".qweight", ".absmax", "quant_state")):
            raise ValueError("拆分模式暂不支持预量化 FP8 / NF4 / GGUF 权重，请使用 BF16 / FP16 原始权重。")
        shape, offsets = tensor.get("shape"), tensor.get("data_offsets")
        if not isinstance(shape, list) or not all(type(n) is int and n >= 0 for n in shape):
            raise ValueError("权重张量形状无效。")
        if not isinstance(offsets, list) or len(offsets) != 2 or not all(type(n) is int for n in offsets):
            raise ValueError("权重张量偏移无效。")
        count = 1
        for n in shape:
            count *= n
        a, b = offsets
        if a < 0 or b - a != count * _FLOAT_BYTES[dtype]:
            raise ValueError("权重张量长度与数据类型不匹配。")
        spans.append((a, b))
    cursor = 0
    for a, b in sorted(spans):
        if a != cursor:
            raise ValueError("权重数据不连续，文件可能损坏。")
        cursor = b
    if not tensors or cursor != size - 8 - length:
        raise ValueError("权重文件已截断或包含多余数据，请重新下载。")
    return tensors


def component_files(path, kind):
    path = Path(path)
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise ValueError("模型路径不存在：%s" % path)
    root = path / kind if (path / kind / "config.json").is_file() else path
    if not (root / "config.json").is_file():
        raise ValueError("组件目录缺少 config.json：%s" % root)
    indexes = list(root.glob("*.safetensors.index.json"))
    if indexes:
        with indexes[0].open(encoding="utf-8") as stream:
            names = set((json.load(stream).get("weight_map") or {}).values())
        if not names:
            raise ValueError("组件分片索引为空。")
        files = []
        for name in names:
            # Keep index names inside the selected folder; HF snapshot symlinks
            # may legitimately point to the shared blob cache. No weights are written.
            p = Path(os.path.abspath(root / name))
            if not p.is_relative_to(Path(os.path.abspath(root))):
                raise ValueError("组件分片索引包含目录外路径。")
            files.append(p)
        return sorted(files)
    name = "model.safetensors" if kind == "text_encoder" else "diffusion_pytorch_model.safetensors"
    return [root / name]


def validate(path, kind):
    tensors = {}
    for file in component_files(path, kind):
        current = read_header(file)
        if set(tensors) & set(current):
            raise ValueError("组件分片包含重复张量。")
        tensors.update(current)
    keys = {k.removeprefix("diffusion_model.") for k in tensors}
    if kind == "transformer":
        required = ("cap_embedder.1.weight", "t_embedder.mlp.0.weight")
        if not all(k in keys for k in required) or not all(any(k.startswith("layers.%d." % i) for k in keys) for i in range(30)):
            raise ValueError("所选文件不是完整的标准 Z-Image 底模（30 层）。")
        cap = next(v for k, v in tensors.items() if k.removeprefix("diffusion_model.") == required[0])
        if cap["shape"] != [3840, 2560]:
            raise ValueError("该 Z-Image 底模架构与当前训练入口不兼容。")
        if any(v["dtype"] not in ("F16", "BF16") for k, v in tensors.items() if k.endswith("weight") and len(v["shape"]) >= 2):
            raise ValueError("Z-Image 底模请使用 BF16 / FP16 原始权重。")
    elif kind == "text_encoder":
        if tensors.get("model.embed_tokens.weight", {}).get("shape") != [151936, 2560] or not all("model.layers.%d.self_attn.q_proj.weight" % i in keys for i in range(36)):
            raise ValueError("Z-Image 需要完整 Qwen3-4B 文本编码器；不支持 Qwen3-VL 或其他规格。")
    elif kind == "vae":
        enc = tensors.get("encoder.conv_in.weight", {})
        dec = tensors.get("decoder.conv_in.weight", {})
        if enc.get("shape") != [128, 3, 3, 3] or dec.get("shape") != [512, 16, 3, 3]:
            raise ValueError("Z-Image 需要 FLUX.1 兼容的 16 通道 VAE，不能使用 SDXL 或 Qwen-Image VAE。")
    return tensors


def validate_selection(selection):
    path = str(selection.get("local_dir") or "").strip()
    if path and (Path(path).suffix.lower() == ".safetensors" or Path(path).is_file()):
        validate(path, "transformer")
        for key, kind in (("text_encoder_path", "text_encoder"), ("vae_path", "vae")):
            if selection.get(key):
                validate(selection[key], kind)
    return bool(path and Path(path).is_file())


def assets_root(core):
    return Path(core.data_sub("models", "at_image", "zimage_components"))


def discover(core, selection):
    """Search known model locations, with bounded depth and no network IO."""
    found = {}
    main = Path(str(selection.get("local_dir") or ""))
    roots = [assets_root(core), Path(core.at_image_local_dir("zimage", {}))]
    for parent in list(main.parents)[:4]:
        if parent.name.lower() == "models":
            roots.append(parent)
            break
    candidates = {
        "text_encoder_path": ("text_encoder", "text_encoders/qwen_3_4b.safetensors", "text_encoders/qwen3_4b.safetensors", "clip/qwen_3_4b.safetensors", "clip/qwen3_4b.safetensors"),
        "vae_path": ("vae", "vae/ae.safetensors", "vae/flux_vae.safetensors", "vae/diffusion_pytorch_model.safetensors"),
    }
    for key, kind in (("text_encoder_path", "text_encoder"), ("vae_path", "vae")):
        if selection.get(key):
            validate(selection[key], kind)
            found[key] = str(Path(selection[key]).resolve())
            continue
        for root in roots:
            for name in candidates[key]:
                p = root / name
                if not p.exists():
                    continue
                try:
                    validate(p, kind)
                except (OSError, ValueError, TypeError, KeyError):
                    continue
                found[key] = str(p.resolve())
                break
            if key in found:
                break
    return found


def missing(core, selection):
    try:
        validate_selection(selection)
        found = discover(core, selection)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return [str(exc)]
    items = [label for key, label in (("text_encoder_path", "缺少 Qwen3-4B 文本编码器"), ("vae_path", "缺少 16 通道 VAE")) if key not in found]
    if not assets_ready(core):
        items.append("缺少 tokenizer 与配套配置（约 16 MB）")
    return items


def _manifest():
    with Path(__file__).with_name("zimage_assets.json").open(encoding="utf-8") as stream:
        return json.load(stream)


def _sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def assets_ready(core):
    root = assets_root(core)
    try:
        return all((root / name).is_file() and (root / name).stat().st_size == meta["size"] and _sha(root / name) == meta["sha256"]
                   for name, meta in _manifest()["files"].items() if not name.endswith((".safetensors", ".index.json")))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def prepare(core, selection, logf):
    """Download only configs/tokenizer and missing TE/VAE; never the transformer."""
    validate_selection(selection)
    found = discover(core, selection)
    root = assets_root(core)
    manifest = _manifest()
    files = manifest["files"]
    required = [name for name in files if not name.endswith(".safetensors") and not name.endswith(".index.json")]
    for key, kind in (("text_encoder_path", "text_encoder"), ("vae_path", "vae")):
        if key not in found:
            names = [n for n in files if n.startswith(kind + "/")]
            required.extend(n for n in names if n not in required)
            logf("[Z-Image] 本机未找到%s，仅准备该组件（约 %.2f GB）" % ("Qwen3-4B 文本编码器" if kind == "text_encoder" else "VAE", sum(files[n]["size"] for n in names) / 1024**3))
    for name in required:
        meta = files[name]
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_file() and dest.stat().st_size == meta["size"]:
            if _sha(dest) == meta["sha256"]:
                continue
        if dest.is_symlink() or dest.is_file() and dest.stat().st_size >= meta["size"]:
            dest.unlink()
        logf("[Z-Image] 准备组件文件：%s" % name)
        success = False
        for host in ("https://modelscope.cn/models", "https://hf-mirror.com"):
            mid = "resolve/master" if "modelscope" in host else "resolve/main"
            url = "%s/%s/%s/%s" % (host, manifest["repo"], mid, name)
            if core._download_with_resume(url, str(dest), logf, direct=True) and dest.is_file() and dest.stat().st_size == meta["size"] and _sha(dest) == meta["sha256"]:
                success = True
                break
            if dest.is_file() and dest.stat().st_size >= meta["size"]:
                dest.unlink()
        if not success:
            raise RuntimeError("Z-Image 组件下载或校验失败：%s；请检查网络后重试。" % name)
    for key, kind in (("text_encoder_path", "text_encoder"), ("vae_path", "vae")):
        if key not in found:
            validate(root / kind, kind)
            found[key] = str(root / kind)
    return str(root), found


def patch_engine(at_dir, logf):
    """Patch recognized upstream load calls only; keep full-directory loading intact."""
    path = Path(at_dir) / "extensions_built_in/diffusion_models/z_image/z_image.py"
    if not path.is_file():
        raise RuntimeError("第三引擎没有 Z-Image 加载器，请更新第三引擎。")
    source = path.read_text(encoding="utf-8")
    marker = "# Kohya Z-Image split components v1"
    if marker not in source:
        tree = ast.parse(source)
        replacements = []
        calls = {
            "Qwen3ForCausalLM.from_pretrained": ("load_text_encoder", "Qwen3ForCausalLM"),
            "Qwen3TextEncoder.load": ("load_text_encoder", "Qwen3TextEncoder"),
            "AutoencoderKL.from_pretrained": ("load_vae", "AutoencoderKL"),
            "KLVAE.load_model": ("load_vae", "KLVAE"),
            "ZImageTransformer2DModel.load_model": ("load_transformer", "ZImageTransformer2DModel"),
        }
        counts = dict.fromkeys(("load_text_encoder", "load_vae", "load_transformer"), 0)
        lines = source.splitlines(keepends=True)
        offsets = [0]
        for line in lines:
            offsets.append(offsets[-1] + len(line))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            match = calls.get(ast.unparse(node.func))
            if not match:
                continue
            helper, klass = match
            counts[helper] += 1
            node.func = ast.Name(id=helper, ctx=ast.Load())
            node.args.insert(0, ast.Name(id=klass, ctx=ast.Load()))
            # AST offsets are UTF-8 byte offsets, not Python character offsets.
            start = offsets[node.lineno - 1] + len(lines[node.lineno - 1].encode()[:node.col_offset].decode())
            end = offsets[node.end_lineno - 1] + len(lines[node.end_lineno - 1].encode()[:node.end_col_offset].decode())
            replacements.append((start, end, ast.unparse(node)))
        if any(count != 1 for count in counts.values()):
            raise RuntimeError("第三引擎 Z-Image 加载器版本尚未兼容拆分模式，请先更新第三引擎；未修改引擎源码。")
        for start, end, replacement in sorted(replacements, reverse=True):
            source = source[:start] + replacement + source[end:]
        parsed = ast.parse(source)
        anchor = 0
        for node in parsed.body:
            if isinstance(node, ast.ImportFrom) and node.module == "__future__" or isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                anchor = node.end_lineno
            else:
                break
        lines = source.splitlines(keepends=True)
        lines.insert(anchor, marker + "\nfrom kohya_zimage_local import load_text_encoder, load_vae, load_transformer\n")
        source = "".join(lines)
        compile(source, str(path), "exec")
        backup = path.with_suffix(".py.kohya_split.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        temp = path.with_suffix(".py.tmp")
        temp.write_text(source, encoding="utf-8", newline="\n")
        # Install the helper before publishing the loader that imports it.
        runtime = Path(__file__).with_name("zimage_runtime.py")
        shutil.copy2(runtime, Path(at_dir) / "kohya_zimage_local.py")
        os.replace(temp, path)
    else:
        for helper in ("load_text_encoder", "load_vae", "load_transformer"):
            if helper + "(" not in source:
                raise RuntimeError("Z-Image 拆分加载补丁不完整，请更新第三引擎。")
        shutil.copy2(Path(__file__).with_name("zimage_runtime.py"), Path(at_dir) / "kohya_zimage_local.py")
    logf("[Z-Image] 第三引擎已接通独立底模、文本编码器与 VAE")
