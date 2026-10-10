"""Project-scoped H3 component paths and header-only Fizgig compatibility checks.

No tensor framework is imported and no model weights are copied or loaded into RAM.
Shape contracts come from the official Comfy checkpoints and the v7.0.1 loader.
"""
from __future__ import annotations

from functools import lru_cache
import json
import math
import os
from pathlib import Path
import struct

KEYS = ("dit", "te", "video_vae", "audio_vae", "training_adapter", "turbo_lora")
REQUIRED = ("dit", "te", "video_vae")
TITLES = dict(dit="H3 主模型", te="Qwen3-VL-32B 文本编码器", video_vae="H3 视频 VAE",
              audio_vae="H3 音频 VAE", training_adapter="H3 训练适配器", turbo_lora="H3 Turbo 预览 LoRA")
_FLOATS = {"BF16", "F16", "F32", "F64"}
_BYTES = {"BOOL": 1, "U8": 1, "I8": 1, "F8_E4M3": 1, "F8_E5M2": 1,
          "F8_E4M3FN": 1, "F8_E8M0": 1, "I16": 2, "U16": 2, "BF16": 2,
          "F16": 2, "F32": 4, "I32": 4, "U32": 4, "I64": 8, "U64": 8, "F64": 8}


def settings(config=None):
    value = (config or {}).get("h3_models", {})
    return {key: str(path) for key, path in value.items() if key in KEYS and isinstance(path, str)} if isinstance(value, dict) else {}


@lru_cache(maxsize=1)
def _schemas():
    return json.loads(Path(__file__).with_name("h3_model_shapes.json").read_text(encoding="utf-8"))["schemas"]


@lru_cache(maxsize=32)
def _header(path, size, modified, changed):
    with open(path, "rb") as stream:
        first = stream.read(8)
        if len(first) != 8:
            raise ValueError("文件不完整，无法读取 safetensors 文件头。")
        length = struct.unpack("<Q", first)[0]
        if not 2 <= length <= 32 * 1024 * 1024 or length + 8 > size:
            raise ValueError("safetensors 文件头无效或下载未完成。")
        try:
            header = json.loads(stream.read(length))
        except (ValueError, UnicodeError) as exc:
            raise ValueError("safetensors 文件头损坏。") from exc
        if not isinstance(header, dict):
            raise ValueError("safetensors 文件头格式无效。")
        data_size = size - 8 - length
        spans = []
        for key, entry in header.items():
            if key == "__metadata__":
                if not isinstance(entry, dict) or any(not isinstance(v, str) for v in entry.values()):
                    raise ValueError("safetensors 元信息格式无效。")
                continue
            if not isinstance(entry, dict):
                raise ValueError("权重描述无效：" + key)
            shape, offsets, dtype = entry.get("shape"), entry.get("data_offsets"), entry.get("dtype")
            if (not isinstance(shape, list) or any(type(n) is not int or n < 0 for n in shape)
                    or not isinstance(offsets, list) or len(offsets) != 2
                    or any(type(n) is not int for n in offsets) or not isinstance(dtype, str) or dtype not in _BYTES):
                raise ValueError("权重格式不受支持：" + key)
            start, end = offsets
            if not 0 <= start <= end <= data_size or end - start != math.prod(shape) * _BYTES[dtype]:
                raise ValueError("文件不完整或权重大小无效：" + key)
            if end > start:
                spans.append((start, end))
        cursor = 0
        for start, end in sorted(spans):
            if start != cursor:
                raise ValueError("权重数据存在重叠或缺口，文件无效。")
            cursor = end
        if not spans or cursor != data_size:
            raise ValueError("文件不完整或包含未覆盖的数据。")
        # Quantization descriptors are tiny JSON tensors, not weight payloads.
        formats = {}
        for key, entry in header.items():
            if not key.endswith(".comfy_quant"):
                continue
            a, b = entry["data_offsets"]
            if entry["dtype"] != "U8" or b - a > 16384:
                raise ValueError("量化信息无效：" + key)
            stream.seek(8 + length + a)
            try:
                descriptor = json.loads(stream.read(b - a))
                fmt = descriptor["format"]
                if not isinstance(fmt, str):
                    raise ValueError("量化格式无效。")
                formats[key[:-12]] = fmt
            except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                raise ValueError("量化信息无法识别：" + key) from exc
        return header, formats


def _check_shapes(header, expected, packed=False):
    for key, wanted in expected.items():
        item = header.get(key)
        actual = list(item.get("shape", [])) if isinstance(item, dict) else []
        if packed and key.endswith(".weight") and key[:-7] + ".weight_scale_2" in header and actual:
            actual[-1] *= 2
        if item is None or actual != wanted:
            raise ValueError("模型结构不兼容或缺少权重：" + key)


def _lora(header):
    linear = {k[:-7]: v for k, v in _schemas()["full"].items() if k.endswith(".weight") and len(v) == 2}
    names = {"lora_unet_" + k.replace(".", "_"): k for k in linear}
    pairs = {}
    for key, item in header.items():
        for suffix, side in ((".lora_A.weight", "down"), (".lora_B.weight", "up"),
                             (".lora_down.weight", "down"), (".lora_up.weight", "up")):
            if not key.endswith(suffix):
                continue
            stem = key[:-len(suffix)]
            module = names.get(stem, stem.removeprefix("diffusion_model."))
            if module not in linear or item.get("dtype") not in _FLOATS:
                raise ValueError("LoRA 包含不兼容的 H3 权重：" + key)
            pairs.setdefault(module, {})[side] = item["shape"]
            break
    if not pairs:
        raise ValueError("请选择 H3 LoRA 文件，不能使用主模型或其他模型的 LoRA。")
    for module, pair in pairs.items():
        out_size, in_size = linear[module]
        down, up = pair.get("down", []), pair.get("up", [])
        valid_in = {in_size}
        if ".adaln_proj.linear" in module:
            valid_in.add(8)
        if (len(down) != 2 or len(up) != 2 or down[0] <= 0 or down[1] not in valid_in
                or up != [out_size, down[0]]):
            raise ValueError("LoRA 维度不兼容或缺少成对权重：" + module)
    return "H3 LoRA · 结构兼容"


@lru_cache(maxsize=32)
def _validate_cached(path, kind, size, modified, changed):
    header, formats = _header(path, size, modified, changed)
    schemas = _schemas()
    if kind in ("training_adapter", "turbo_lora"):
        return _lora(header)
    if kind == "dit":
        pruned = "adaln_t_table" in header
        _check_shapes(header, schemas["dit" if pruned else "full"])
        if pruned:
            if not formats or any(v != "int8_convrot" for v in formats.values()):
                raise ValueError("当前支持 pruned int8 ConvRot 或完整 BF16 H3；此主模型量化格式不受支持。")
            for module in formats:
                if header.get(module + ".weight", {}).get("dtype") != "I8" or module + ".weight_scale" not in header:
                    raise ValueError("H3 int8 量化权重不完整：" + module)
            # All 50 blocks carry these four quantized matmuls in the supported pruned file.
            for block in range(50):
                for suffix in ("attn.qkv_proj", "attn.out_proj", "mlp.fc1", "mlp.fc2"):
                    if formats.get(f"blocks.{block}.{suffix}") != "int8_convrot":
                        raise ValueError("H3 int8 主模型缺少量化信息。")
            return "H3 pruned int8 ConvRot"
        if formats or any(header[key]["dtype"] not in _FLOATS for key in schemas["full"]):
            raise ValueError("完整 H3 主模型需要浮点权重；此预量化格式不受支持。")
        return "H3 完整浮点主模型 · 训练时使用 NF4"
    if kind == "te":
        _check_shapes(header, schemas["te"], packed=True)
        for module, fmt in formats.items():
            weight = header.get(module + ".weight", {})
            if module + ".weight_scale" not in header:
                raise ValueError("文本编码器量化信息缺少 scale：" + module)
            if fmt == "nvfp4" and (module + ".weight_scale_2" not in header or weight.get("dtype") != "U8"):
                raise ValueError("文本编码器 nvfp4 权重不完整：" + module)
            if fmt == "int8_tensorwise" and weight.get("dtype") != "I8":
                raise ValueError("文本编码器 int8 权重不完整：" + module)
        if any(v not in ("nvfp4", "int8_tensorwise") for v in formats.values()):
            raise ValueError("H3 文本编码器支持 nvfp4 AWQ 或完整浮点版本，不支持 int8 ConvRot 版本。")
        for key in schemas["te"]:
            item = header[key]
            if item["dtype"] not in _FLOATS and not (key.endswith(".weight") and key[:-7] in formats):
                raise ValueError("文本编码器包含无法识别的量化权重：" + key)
        return "Qwen3-VL-32B · H3 兼容"
    _check_shapes(header, schemas[kind])
    if formats or any(header[k]["dtype"] not in _FLOATS for k in schemas[kind]):
        raise ValueError("请选择 H3 专用浮点 VAE。")
    return TITLES[kind] + " · 结构兼容"


def validate(path, kind):
    if kind not in KEYS:
        raise ValueError("未知的 H3 组件类型。")
    path = os.path.abspath(os.path.expanduser(str(path or "").strip().strip('"')))
    if not Path(path).is_file():
        raise ValueError("文件不存在，请重新选择：" + path)
    if Path(path).suffix.lower() != ".safetensors":
        raise ValueError("请选择单个 .safetensors 文件。")
    stat = Path(path).stat()
    return _validate_cached(path, kind, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def training_precision(path, requested="auto"):
    validate(path, "dit")
    stat = Path(path).stat()
    header, _formats = _header(str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    if "adaln_t_table" in header:
        return requested
    if requested not in ("auto", "nf4"):
        raise ValueError("完整浮点 H3 主模型请使用自动或 NF4；int8 / HQQ 请使用 pruned int8 ConvRot 主模型。")
    return "nf4"


def rows(core, selection=None):
    defaults = core.h3_model_files()
    folder = Path(core.h3_fz_models_dir())
    result = {}
    for key in KEYS:
        entry = core.H3_FZ_MODEL_LINKS[key]
        manual = isinstance(selection, dict) and key in selection
        path = str(selection[key]) if manual else str(defaults.get(key) or folder / entry[0])
        disabled = manual and not path and key not in REQUIRED
        error, detail = "", "不使用" if disabled else "未准备"
        present = False
        if not disabled:
            try:
                detail = validate(path, key)
                present = True
            except (ValueError, OSError) as exc:
                if manual or Path(path).exists():
                    error = str(exc)
        result[key] = dict(path=path, manual=manual, disabled=disabled, present=present, error=error, detail=detail)
    return result


def files(core, selection=None):
    return {key: row["path"] if row["present"] else None for key, row in rows(core, selection).items()}


def missing(core, selection=None, require_audio=False):
    state = rows(core, selection)
    required = (*REQUIRED, "audio_vae") if require_audio else REQUIRED
    return [state[k]["error"] or "缺少 " + TITLES[k] for k in required if not state[k]["present"]]


def validate_selected(core, selection=None):
    for key, row in rows(core, selection).items():
        if row["manual"] and row["error"]:
            raise ValueError(TITLES[key] + "：" + row["error"])
