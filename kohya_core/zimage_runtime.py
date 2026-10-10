"""Copied into the training engine; imports ML libraries only in that process."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct


def load_transformer(klass, *args, **kwargs):
    if not os.environ.get("KOHYA_ZIMAGE_ASSETS"):
        return klass.load_model(*args, **kwargs)
    # Comfy checkpoints sometimes wrap every tensor in diffusion_model.
    converter = klass.convert_state_dict_on_load
    original = klass.__dict__.get("convert_state_dict_on_load")
    klass.convert_state_dict_on_load = classmethod(
        lambda cls, sd: converter({key.removeprefix("diffusion_model."): value for key, value in sd.items()}))
    try:
        return klass.load_model(*args, **kwargs)
    finally:
        if original is None:
            delattr(klass, "convert_state_dict_on_load")
        else:
            klass.convert_state_dict_on_load = original


def _component_root(path, kind):
    root = Path(path)
    return root / kind if (root / kind / "config.json").is_file() else root


def _text_folder(path, assets):
    """HF index references original tensors: no copying or hardlinks across disks."""
    path = Path(path).resolve()
    if path.is_dir():
        return _component_root(path, "text_encoder")
    with path.open("rb") as stream:
        length = struct.unpack("<Q", stream.read(8))[0]
        if length > 32 * 1024 * 1024:
            raise ValueError("Invalid Qwen3 header")
        header = json.loads(stream.read(length))
    weights = {key: str(path) for key in header if key != "__metadata__"}
    identity = "%s:%s:%s" % (path, path.stat().st_size, path.stat().st_mtime_ns)
    stage = Path(assets) / "local_text_encoders" / hashlib.sha256(identity.encode()).hexdigest()[:24]
    stage.mkdir(parents=True, exist_ok=True)
    for name in ("config.json", "generation_config.json"):
        src = Path(assets) / "text_encoder" / name
        if src.is_file():
            (stage / name).write_bytes(src.read_bytes())
    index = {"metadata": {"total_size": path.stat().st_size - length - 8}, "weight_map": weights}
    dest = stage / "model.safetensors.index.json"
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(index), encoding="utf-8")
    os.replace(tmp, dest)
    return stage


def load_text_encoder(klass, base, **kwargs):
    path = os.environ.get("KOHYA_ZIMAGE_TEXT_ENCODER")
    if not path:
        if hasattr(klass, "load"):
            return klass.load(base, **kwargs)
        return klass.from_pretrained(base, **kwargs)
    from transformers import Qwen3Config
    assets = os.environ["KOHYA_ZIMAGE_ASSETS"]
    dtype = kwargs.get("dtype", kwargs.get("torch_dtype"))
    root = _text_folder(path, assets)
    config = Qwen3Config.from_pretrained(str(root), local_files_only=True)
    model, info = klass.from_pretrained(
        str(root), config=config, torch_dtype=dtype, local_files_only=True,
        low_cpu_mem_usage=True, output_loading_info=True)
    unexpected = [k for k in info.get("unexpected_keys", []) if not k.endswith(".rotary_emb.inv_freq")]
    if info.get("missing_keys") or info.get("mismatched_keys") or unexpected or info.get("error_msgs"):
        raise RuntimeError("Qwen3-4B checkpoint does not match its config: %s" % info)
    if hasattr(model, "aitk_post_load"):
        model.aitk_post_load(**kwargs)
    return model


def load_vae(klass, base, **kwargs):
    path = os.environ.get("KOHYA_ZIMAGE_VAE")
    if not path:
        if hasattr(klass, "load_model"):
            return klass.load_model(base, **kwargs)
        return klass.from_pretrained(base, **kwargs)
    import torch
    from accelerate import init_empty_weights
    from safetensors.torch import load_file
    from diffusers.loaders.single_file_utils import convert_ldm_vae_checkpoint
    assets = os.environ["KOHYA_ZIMAGE_ASSETS"]
    dtype = kwargs.get("dtype", kwargs.get("torch_dtype"))
    if Path(path).is_dir():
        model, info = klass.from_pretrained(str(_component_root(path, "vae")), torch_dtype=dtype, local_files_only=True, output_loading_info=True)
        if info.get("missing_keys") or info.get("unexpected_keys") or info.get("mismatched_keys") or info.get("error_msgs"):
            raise RuntimeError("Z-Image VAE checkpoint does not match its config: %s" % info)
    else:
        config = klass.load_config(str(Path(assets) / "vae"), local_files_only=True)
        state = load_file(path, device="cpu")
        if "encoder.down_blocks.0.resnets.0.conv1.weight" not in state:
            state = convert_ldm_vae_checkpoint(state, config)
        with init_empty_weights(include_buffers=False):
            model = klass.from_config(config)
        # Explicitly strict: never leave missing VAE tensors randomly initialized.
        model.load_state_dict(state, strict=True, assign=True)
        model.to(dtype=dtype or torch.bfloat16)
        del state
    return model
