"""MOSS-Image component paths and CPU-only structural validation for pinned Fizgig runtimes."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re

PROJECT_KEY = "moss_models"
KEYS = ("dit", "te", "vae", "preview_checkpoint")
REQUIRED = ("dit", "te", "vae")
REPO = "Comfy-Org/MOSS-Image"
REVISION = "f28da8f93449c16cfa7efa07dcd1303a1c0c44d1"


def _entry(filename, label, repo, path):
    return filename, label, (
        "https://modelscope.cn/models/" + repo + "/resolve/master/" + path,
        "https://hf-mirror.com/" + repo + "/resolve/main/" + path,
        "https://huggingface.co/" + repo + "/resolve/main/" + path,
    )


LINKS = {
    "dit": _entry("moss_image_base_bf16.safetensors", "MOSS-Image Base 训练底模（10.2 GB）", REPO,
                  "diffusion_models/moss_image_base_bf16.safetensors"),
    "te": _entry("qwen3.5_9b_bf16.safetensors", "Qwen3.5-9B BF16 文本编码器（19.3 GB）", "Comfy-Org/Qwen3.5",
                 "text_encoders/qwen3.5_9b_bf16.safetensors"),
    "vae": _entry("flux2-vae_small.safetensors", "FLUX.2 小型 VAE（0.25 GB）", REPO,
                  "vae/flux2-vae_small.safetensors"),
    "preview_checkpoint": _entry("moss_image_sft_int8_convrot.safetensors", "MOSS-Image SFT 预览底模（5.4 GB）", REPO,
                                 "diffusion_models/moss_image_sft_int8_convrot.safetensors"),
}


def settings(config=None):
    value = (config or {}).get(PROJECT_KEY) or {}
    return {k: v.strip() for k, v in value.items() if k in KEYS and isinstance(v, str) and v.strip()} if isinstance(value, dict) else {}


def models_dir(core):
    return str(Path(core.data_sub("models", "moss_image")))


def component_files(path):
    p = Path(path)
    match = re.fullmatch(r"(.+)-(\d{5})-of-(\d{5})\.safetensors", p.name)
    if not match:
        return [p]
    stem, _part, total = match.groups()
    if not 1 <= int(total) <= 100:
        raise ValueError("模型分片数量无效。")
    return [p.with_name(f"{stem}-{i:05d}-of-{int(total):05d}.safetensors") for i in range(1, int(total) + 1)]


@lru_cache(maxsize=32)
def _validated(identities, kind, allow_quant=False):
    # The shared H3 reader checks every byte span and quantization descriptor without loading tensors.
    from .h3_models import _header
    tensors, formats = {}, {}
    for path, size, modified, changed in identities:
        header, quant = _header(path, size, modified, changed)
        current = {k: v for k, v in header.items() if k != "__metadata__"}
        if tensors.keys() & current.keys():
            raise ValueError("模型分片含重复权重。")
        tensors.update(current)
        formats.update(quant)
    def normalize(key):
        return key.removeprefix("model.diffusion_model.").removeprefix("diffusion_model.").removeprefix("model.")
    tensors = {normalize(k): v for k, v in tensors.items()}
    formats = {normalize(k): v for k, v in formats.items()}
    def shape(key):
        return tensors.get(key, {}).get("shape")
    if kind in ("dit", "preview_checkpoint"):
        if shape("video_embedder.weight") != [3072, 128] or shape("final_linear_video.weight") != [128, 3072] or shape("text_embedder.proj.weight") != [3072, 4096]:
            raise ValueError("请选择 MOSS-Image 5B DiT，文本编码器或其他模型不能作为底模。")
        for i in range(42):
            if shape(f"layers.{i}.proj.qkv.weight") != [9216, 3072] and not all(shape(f"layers.{i}.proj.{part}.weight") == [3072, 3072] for part in ("q", "k", "v")):
                raise ValueError("MOSS-Image 底模需要完整的 42 层权重。")
        if kind == "dit":
            if any("sft" in Path(item[0]).stem.lower() for item in identities):
                raise ValueError("SFT 用于预览和出图；训练请选择 MOSS-Image Base。")
            if formats or any(v.get("dtype") not in ("BF16", "F16", "F32") for k, v in tensors.items() if k.endswith("weight") and len(v.get("shape", [])) >= 2):
                raise ValueError("训练底模请选择 BF16 / FP16 Base，训练精度由引擎设置。")
        elif any(v.get("format") not in ("int8_tensorwise",) for v in formats.values()):
            raise ValueError("SFT 预览仅支持浮点或 int8 ConvRot 权重。")
    elif kind == "te":
        if shape("language_model.embed_tokens.weight") != [248320, 4096] or not all(shape(f"language_model.layers.{i}.input_layernorm.weight") == [4096] for i in range(32)):
            raise ValueError("MOSS-Image 需要完整 Qwen3.5-9B 文本编码器；选择任一分片时其余分片须在同一目录。")
        quantized = bool(formats) or any(v.get("dtype") not in ("BF16", "F16", "F32")
            for k, v in tensors.items() if k.startswith("language_model.") and k.endswith("weight"))
        if quantized and not allow_quant:
            raise ValueError("量化文本编码器需要 Fizgig v8.9.6；当前版本请选择 BF16 / FP16。")
        for key, item in tensors.items():
            if not key.startswith("language_model.") or not key.endswith(".weight"):
                continue
            base, dims = key[:-7], item["shape"]
            descriptor = formats.get(base)
            if descriptor is None:
                if item["dtype"] not in ("BF16", "F16", "F32"):
                    raise ValueError("量化权重缺少对应的格式信息：" + key)
                continue
            fmt = descriptor.get("format")
            if len(dims) != 2 or min(dims) <= 0:
                raise ValueError("量化文本编码器的权重维度无效：" + key)
            rows, columns = dims
            if fmt == "int8_tensorwise":
                scale = tensors.get(base + ".weight_scale", {})
                if item["dtype"] != "I8" or scale.get("shape") not in ([rows], [rows, 1]) or scale.get("dtype") not in ("BF16", "F16", "F32"):
                    raise ValueError("INT8 文本编码器缺少有效的逐行缩放：" + base)
            elif fmt == "asym_w4a8_int8":
                group = descriptor.get("group_size", 16)
                rotation = descriptor.get("convrot_groupsize", 256)
                relative = tensors.get(base + ".weight_s_rel", {})
                channel = tensors.get(base + ".weight_s_channel", {})
                if (type(group) is not int or group < 4 or columns * 2 % group
                        or (16 % group != 0 and group % 16 != 0)
                        or type(rotation) is not int or rotation <= 0 or columns * 2 % rotation
                        or columns * 2 % 16 or item["dtype"] != "I8"
                        or relative.get("shape") != [rows, columns * 2 // group]
                        or relative.get("dtype") not in ("U8", "F8_E4M3", "F8_E4M3FN")
                        or channel.get("shape") != [rows]
                        or channel.get("dtype") not in ("BF16", "F16", "F32")):
                    raise ValueError("4-bit GPTQ 文本编码器的打包权重或缩放不完整：" + base)
                book = tensors.get(base + ".weight_codebook")
                if book is not None and (book.get("shape") != [16] or book.get("dtype") not in ("BF16", "F16", "F32")):
                    raise ValueError("4-bit GPTQ 文本编码器的码本无效：" + base)
            else:
                raise ValueError("文本编码器量化格式不受支持：" + str(fmt))
        if any(base + ".weight" not in tensors for base in formats):
            raise ValueError("文本编码器量化信息缺少对应的权重。")
        if quantized:
            return "Qwen3.5-9B · 量化结构检查通过（载入后还原 BF16）"
    elif kind == "vae":
        if shape("encoder.conv_in.weight") != [128, 3, 3, 3] or shape("decoder.conv_in.weight") not in ([512, 32, 3, 3], [384, 32, 3, 3]) or shape("bn.running_mean") != [128]:
            raise ValueError("请选择 FLUX.2 VAE（优先小型版本），FLUX.1 / SDXL VAE 不兼容。")
    else:
        raise ValueError("未知 MOSS-Image 组件。")
    return "结构检查通过"


def validate(path, kind, allow_quant=False):
    if kind not in KEYS:
        raise ValueError("未知 MOSS-Image 组件。")
    identities = []
    for p in component_files(path):
        if not p.is_file() or p.suffix.lower() != ".safetensors":
            raise ValueError("文件不存在或模型分片不完整：" + str(p))
        st = p.stat()
        identities.append((str(p.resolve()), st.st_size, st.st_mtime_ns, st.st_ctime_ns))
    return _validated(tuple(identities), kind, allow_quant)


def rows(core, selection=None, allow_quant=False):
    selection = selection or {}
    root = Path(models_dir(core))
    result = {}
    for key, entry in LINKS.items():
        path = selection.get(key) or str(root / entry[0])
        present, error, detail = False, "", "未准备"
        try:
            detail = validate(path, key, allow_quant=allow_quant)
            present = True
        except (OSError, ValueError) as exc:
            if key in selection or Path(path).exists():
                error = str(exc)
        result[key] = dict(path=path, present=present, error=error, detail=detail, manual=key in selection,
                           selected=True, in_use=present, disabled=False)
    return result


def files(core, selection=None, allow_quant=False):
    return {key: row["path"] if row["present"] else None for key, row in rows(core, selection, allow_quant=allow_quant).items()}


def missing(core, selection=None, preview=False, base_preview=False, allow_quant=False):
    required = (*REQUIRED, "preview_checkpoint") if preview and not base_preview else REQUIRED
    return [row["error"] or "缺少 " + LINKS[key][1] for key, row in rows(core, selection, allow_quant=allow_quant).items()
            if key in required and not row["present"]]


def quantized_encoder_supported(config=None):
    from .fizgig_engine import LATEST_VERSION
    config = config or {}
    return (config.get("fizgig_version") or (config.get("params") or {}).get("fizgig_version")) == LATEST_VERSION
