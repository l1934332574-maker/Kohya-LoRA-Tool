"""The v7 ordinary-LoRA adapter. Model checks, cache identity and CLI are shared."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from .fizgig_engine import VERSION, COMMIT, MIRROR, SUPPORTED_STANDARD as SUPPORTED_V7, MOSS_VERSION, SUPPORTED_MOSS, SUPPORTED_ZIMAGE, LATEST_VERSION, source_commit, source_version, _env, _sha, _write

FAMILIES = {"krea2_fz": "krea2", "flux2_fz": "klein", "qwen21_fz": "qwen_image21",
            "h3_fz": "minimax", "anima_fz": "anima", "sdxl_fz": "sdxl", "zimage_fz": "zimage", "moss_fz": "moss_image"}


def models_dir(core, family):
    if family == "moss_image":
        from .moss_models import models_dir as directory
        return directory(core)
    return str(Path(core.KIT_DIR) / "models" / ("base" if family == "sdxl" else "anima"))


def models(core, family, params=None):
    params = params or {}
    if family == "moss_image":
        from .moss_models import files, settings, quantized_encoder_supported
        return files(core, settings(params), allow_quant=quantized_encoder_supported(params))
    if family == "zimage":
        from .zimage_fizgig import files, settings
        return files(core, settings(params))
    if family == "krea2":
        from .krea2_models import settings, encoder_key
        selection = settings(params)
        f = core.krea2_fz_model_files(selection)
        f["te"] = f.get(encoder_key(f, selection))
        f.pop("te_fp8", None)
        return dict(f, dit=f.get("raw"), preview_checkpoint=f.get("turbo"))
    if family == "klein":
        f = core.flux2_fz_model_files()
        f["preview_checkpoint"] = str(Path(core.flux2_models_dir()) / "flux-2-klein-9b.safetensors")
        if not Path(f["preview_checkpoint"]).is_file(): f["preview_checkpoint"] = None
        return f
    if family == "qwen_image21": return core.qwen21_fz_model_files()
    if family == "minimax":
        f = core.h3_fz_model_files(params.get("h3_models"))
        return dict(f, vae=f.get("video_vae"), speed_lora=f.get("turbo_lora"))
    folder = Path(models_dir(core, family))
    if family == "sdxl":
        checkpoint = params.get("base_model")
        if not checkpoint:
            default = folder / "sd_xl_base_1.0.safetensors"
            checkpoint = str(default) if default.is_file() else None
        return {"dit": checkpoint, "te": checkpoint, "vae": checkpoint}
    checkpoint = params.get("base_model") or str(folder / "anima-base-v1.0.safetensors")
    te, _base = core._anima_find_qwen3_any()
    if te and Path(te).is_dir():
        single = Path(te) / "model.safetensors"
        te = str(single) if single.is_file() else None
    # Reuse the component dialog resolver, including Anima_vae in current/legacy data roots.
    # anima_get_component() only reads manual overrides; it does not discover installed files.
    vae = core.anima_component_status()["vae"]["path"]
    for base in [folder, Path(core.base_models_dir()), *map(Path, core._anima_bases())]:
        if not vae and (base / "qwen_image_vae.safetensors").is_file():
            vae = str(base / "qwen_image_vae.safetensors")
    if not te and (folder / "qwen_3_06b_base.safetensors").is_file():
        te = str(folder / "qwen_3_06b_base.safetensors")
    return {"dit": checkpoint if Path(checkpoint).is_file() else None, "te": te, "vae": vae}


def missing(core, family, params=None):
    files = models(core, family, params)
    if family == "moss_image":
        from .moss_models import missing as missing_moss, settings, quantized_encoder_supported
        return missing_moss(core, settings(params), allow_quant=quantized_encoder_supported(params))
    if family == "zimage":
        from .zimage_fizgig import missing as missing_zimage, settings
        return missing_zimage(core, settings(params))
    if family == "sdxl":
        # A complete SDXL checkpoint contains the UNet, both text encoders and VAE.
        checkpoint = files.get("dit")
        if not checkpoint:
            return ["请选择完整的 SDXL 底模文件"]
        if not Path(checkpoint).is_file():
            return ["SDXL 底模文件不存在，请重新选择"]
        return []
    return ["缺少%s" % title for key, title in (("dit", "训练底模"), ("te", "文本编码器"), ("vae", "VAE"))
            if not files.get(key) or not Path(files[key]).is_file()]


def _helper_configs(core, family, logf):
    # Public small tokenizer/config files only. Each file is pinned and hashed.
    manifest = json.loads(Path(__file__).with_name("fizgig_helpers.json").read_text(encoding="utf-8"))
    spec = manifest.get(family)
    if not spec: return None
    root = Path(core.data_sub("cache", "fizgig_helpers", family, spec["commit"]))
    root.mkdir(parents=True, exist_ok=True)
    for name, identity in spec["files"].items():
        core.check_stop()
        target = root / name
        if target.is_file() and target.stat().st_size == identity["bytes"] and _sha(target) == identity["sha256"]:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        urls = [(MIRROR + "helpers/" + family + "/" + spec["commit"] + "/" + name, True),
                ("https://hf-mirror.com/" + spec["repo"] + "/resolve/" + spec["commit"] + "/" + name, True),
                ("https://huggingface.co/" + spec["repo"] + "/resolve/" + spec["commit"] + "/" + name, False)]
        if spec.get("modelscope_repo"):
            urls.insert(0, ("https://modelscope.cn/models/" + spec["modelscope_repo"] + "/resolve/master/" + name, True))
        logf("[Fizgig] 准备本地分词器 / 配置：%s / %s（国内镜像优先）" % (family, name))
        for url, direct in urls:
            if core._download_with_resume(url, str(target), logf, direct=direct, quick_fail=True):
                if target.stat().st_size == identity["bytes"] and _sha(target) == identity["sha256"]:
                    break
                target.rename(target.with_name(target.name + ".invalid.%s" % time.time_ns()))
            part = Path(str(target) + ".part")
            if part.is_file(): part.unlink()
        else: raise RuntimeError("配置下载或校验失败：%s；请稍后重试。" % name)
    return str(root), spec["repo"]


def _validate(core, family, files, version=None):
    required = ("dit", "te", "vae")
    if family in ("qwen_image21", "zimage") or (family == "minimax" and files.get("training_adapter")):
        required += ("training_adapter",)
    for key in required:
        path = files.get(key)
        if not path or not Path(path).is_file(): raise RuntimeError("缺少 %s 的 %s 模型，请先准备模型文件。" % (family, key))
        if not core._safetensors_complete(path):
            raise RuntimeError("模型文件不完整或损坏：%s。请重新下载该文件。" % path)
    validate_base(core, family, files["dit"])
    if family in ("zimage", "moss_image"):
        if family == "moss_image":
            from .moss_models import validate
        else:
            from .zimage_fizgig import validate
        for key in required:
            if family == "moss_image":
                validate(files[key], key, allow_quant=version == LATEST_VERSION)
            else:
                validate(files[key], key)
    if family == "krea2" and core._safetensors_is_prequantized(files["dit"]):
        raise RuntimeError("Krea2 需要 bf16 RAW 底模；推理用预量化文件不能直接用于训练。")


def validate_base(core, family, checkpoint):
    if not core._safetensors_complete(checkpoint):
        raise RuntimeError("模型文件不完整或损坏，请重新下载。")
    if family == "zimage":
        from .zimage_fizgig import validate
        validate(checkpoint, "dit")
    if family == "moss_image":
        from .moss_models import validate
        validate(checkpoint, "dit")
    if family == "minimax":
        from .h3_models import validate
        validate(checkpoint, "dit")
    if family == "anima":
        if core.detect_base_type(checkpoint) != "anima":
            raise RuntimeError("所选文件不是可识别的 Anima 底模；文本编码器不能作为底模。")
        keys = core._safetensors_keys(checkpoint)
        blocks = {int(m.group(1)) for k in keys if (m := re.search(r"(?:^|\.)blocks\.(\d+)\.", k))}
        if blocks != set(range(28)):
            raise RuntimeError("Fizgig 仅支持标准 28 层 Anima；当前检测到 %s 层。2.9B / 40 层请选 Kohya 引擎。" % len(blocks))
    if family == "sdxl" and core.detect_base_type(checkpoint) != "sdxl":
        raise RuntimeError("Fizgig SDXL 需要包含 UNet、双 CLIP 和 VAE 的完整 SDXL safetensors 底模。")


def _cache_identity(core, family, files, subsets, resolution, commit=COMMIT, training_type=None):
    def stat(path):
        p = Path(path); st = p.stat()
        return [str(p.resolve()), st.st_size, st.st_mtime_ns]
    assets = {k: stat(v) for k, v in files.items() if v and k in ("dit", "vae", "te", "audio_vae")}
    if family == "moss_image" and files.get("te"):
        from .moss_models import component_files
        assets["te"] = [stat(path) for path in component_files(files["te"])]
    images = []
    for folder, _repeats, _count in subsets:
        for path in sorted(Path(folder).iterdir()):
            if path.is_file() and not path.stem.casefold().endswith("-masklabel") and path.suffix.lower() in core.FIZGIG_IMAGE_EXTS | {".mp4", ".wav", ".mp3", ".flac", ".m4a", ".txt"}:
                images.append(stat(path))
    signature = {"commit": commit, "family": family, "resolution": resolution, "models": assets, "files": images}
    if family == "minimax":
        signature["training_type"] = training_type or "character"
        signature["clip_still"] = training_type != "style"
    return hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:20], signature


def preview_prompts(params, subsets):
    """One stable, relevant caption for automatic previews; explicit prompts stay intact."""
    custom = str(params.get("sample_prompt") or "").strip()
    positive = str(params.get("global_pos") or "").strip()
    if params.get("mode") == "moss_fz":
        from .moss_multi_character import prompt_lines, preview_selection
        if custom:
            return prompt_lines(custom, positive), "custom"
        if params.get("training_kind") == "multi_character":
            from .multi_character import normalize, validation_prompts
            settings = normalize(params.get("multi_character", {}))
            prompts = validation_prompts(settings, mode="moss_fz", resolution=params.get("resolution", 512))
            selected = preview_selection(prompts)
            return [line for item in selected for line in prompt_lines(item["prompt"], positive)], "multi_character"
    if custom:
        lines, origin = [line.strip() for line in custom.splitlines() if line.strip()], "custom"
    else:
        from .project_config import read_caption
        trigger = str(params.get("trigger") or "").strip()
        caption = ""
        extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".avif",
                      ".mp4", ".mov", ".webm", ".mkv", ".wav", ".mp3", ".flac", ".m4a", ".ogg"}
        checked = 0
        for directory, _repeats, _count in subsets:
            if checked >= 100:
                break
            try:
                entries = sorted(Path(directory).iterdir(), key=lambda path: path.name.casefold())
            except OSError:
                continue
            for media in entries:
                if checked >= 100:
                    break
                if media.suffix.lower() not in extensions or media.is_symlink() or not media.is_file():
                    continue
                checked += 1
                try:
                    candidate = " ".join(read_caption(media).split()).lstrip("# ")
                except (OSError, ValueError):
                    continue
                if candidate and candidate.strip(" ,").casefold() != trigger.casefold():
                    caption = candidate[:1200]
                    break
            if caption:
                break
        origin = "dataset_caption" if caption else "fallback"
        if not caption:
            caption = "a detailed portrait, high quality" if params.get("at_sub_mode", "character") == "character" else "a detailed scene, high quality"
        if trigger and not re.search(r"(?<!\w)" + re.escape(trigger) + r"(?!\w)", caption, re.I):
            caption = trigger + ", " + caption
        style = str(params.get("style_caption") or "").strip()
        if style and style.casefold() not in caption.casefold():
            caption += ", " + style
        lines = [caption]
    return [", ".join(filter(None, (positive, line))) for line in lines], origin


def train_lora(core, record, logf, mode, params, vram_gb, resume_from, progress):
    from . import loss_masks
    mask_mode, mask_floor = loss_masks.settings(dict(params, mode=mode))
    version = record["version"]
    commit = source_commit(version)
    if source_version(record["source"]) != version or version not in SUPPORTED_V7 or not Path(record["python"]).is_file():
        raise RuntimeError("此项目选择 Fizgig %s，请先安装或更新引擎。" % version)
    from .fizgig_engine import ensure_preview_offloading
    ensure_preview_offloading(record, logf)
    family = FAMILIES[mode]
    if family == "moss_image" and version not in SUPPORTED_MOSS:
        raise RuntimeError("MOSS-Image 需要 Fizgig " + " / ".join(SUPPORTED_MOSS))
    if family == "zimage" and version not in SUPPORTED_ZIMAGE:
        raise RuntimeError("Z-Image Turbo 需要 Fizgig %s，请选择兼容版本。" % " / ".join(SUPPORTED_ZIMAGE))
    if family == "krea2":
        from .krea2_models import settings, validate_selected
        validate_selected(core, settings(params))
    if family == "minimax":
        from .h3_models import validate_selected
        validate_selected(core, params.get("h3_models"))
    files = models(core, family, params)
    _validate(core, family, files, version=version)
    if family == "moss_image":
        if params.get("moss_preview_base"):
            files["preview_checkpoint"] = None
        if core._sample_preview_enabled(params, vram_gb):
            from .moss_models import missing as missing_moss, settings, validate
            errors = missing_moss(core, settings(params), preview=True, base_preview=bool(params.get("moss_preview_base")), allow_quant=version == LATEST_VERSION)
            if errors: raise RuntimeError("；".join(errors))
            if files.get("preview_checkpoint"): validate(files["preview_checkpoint"], "preview_checkpoint")
    if family == "krea2":
        for key, label in (("dit", "RAW 底模"), ("vae", "VAE"), ("te", "文本编码器"), ("preview_checkpoint", "Turbo 预览底模")):
            logf("[Fizgig · Krea 2] %s：%s" % (label, files.get(key) or "未使用"))
    if family == "anima":
        from .anima_ckpt import resolve_train_base, checkpoint_kind
        files["dit"], _kind = resolve_train_base(files["dit"], logf=logf)
        if checkpoint_kind(files["dit"]) != "pure":
            raise RuntimeError("Anima 合并包未能生成纯 DiT 缓存；请准备标准 28 层的纯 DiT 底模。原底模没有被覆盖。")
    precision = str(params.get("quant_mode") or "auto").lower()
    if precision == "fp8" and family == "klein":
        # The file itself is fp8. bf16 means use the shipped base without requantization.
        precision = "bf16"
        logf("[Fizgig] Klein 的 fp8 保存在底模文件中；新版使用原底模精度，不二次量化。")
    allowed = ("auto", "int8", "nf4", "hqq") if family == "minimax" else ("auto", "bf16", "int8", "nf4")
    if family == "minimax":
        from .h3_models import training_precision
        precision = training_precision(files["dit"], precision)
    if precision not in allowed:
        raise ValueError("新版 %s 支持 %s；当前精度 %s 不受支持，请重新选择。" % (family, "/".join(allowed), precision))
    train_dir = (params.get("train_data_dir") or params.get("raw_dir")) if family == "minimax" else core.dataset_train_dir("character", params.get("project"))
    mask_report = None
    if mask_mode != "off":
        train_dir, mask_report = loss_masks.training_view(core, params, core.check_stop)
        logf("[学习区域] 使用检查后的训练副本：有效 %d，排除 %d，明确整图学习 %d。" % (mask_report["valid"], mask_report["excluded"], mask_report["unmasked"]))
    if family == "minimax":
        from .h3_dataset import validate_options
        h3_training_type, _caption_method = validate_options(params)
        dataset, subsets = core._scan_fizgig_h3_subsets(train_dir, params.get("repeats", 1))
        count, captions = dataset["total"], dataset["missing_captions"]
        if dataset["images"] and not files.get("training_adapter"):
            raise RuntimeError("H3 图片训练需要 Circlestone 图片训练适配器；请在 H3 训练组件中下载或选择本地文件。")
        logf("[Fizgig · H3] 图片训练适配器：%s" % (files.get("training_adapter") or "未使用（当前无图片素材）"))
        if dataset["audio"] and not files.get("audio_vae"):
            raise RuntimeError("音频素材需要 H3 音频 VAE，请先下载。")
        if dataset["videos"] and not files.get("audio_vae"):
            logf("[Fizgig] 未配置音频 VAE：视频只训练画面，不训练声音。")
    else:
        subsets, captions = core._fizgig_qwen_image_subsets(train_dir, params.get("repeats", 1))
        count = sum(n for _, _, n in subsets)
    minimum = core.MIN_IMAGES.get(mode, 15)
    if count < minimum: raise RuntimeError("至少需要 %s 个可训练素材；当前 %s 个。" % (minimum, count))
    if captions: raise RuntimeError("素材缺少同名非空 .txt 描述：" + ", ".join(captions[:12]))
    def numeric(key, default):
        value = params.get(key)
        return default if value in (None, "") else value
    resolution = int(numeric("resolution", 512))
    epochs = int(numeric("max_epochs", 50 if family == "moss_image" else 16))
    rank = int(numeric("rank", 16 if family == "moss_image" else 32))
    alpha = float(numeric("alpha", rank))
    lr = float(numeric("unet_lr", 1e-4))
    if min(resolution, epochs, rank, alpha, lr) <= 0 or not all(math.isfinite(v) for v in (alpha, lr)):
        raise ValueError("分辨率、轮数、rank、alpha、学习率需要为正数。")
    if int(numeric("batch_size", 1)) != 1:
        raise ValueError("当前 Fizgig 接入按每次一个素材训练；批大小请设为 1。")
    if family == "moss_image" and str(params.get("gc") or "auto").lower() in ("关闭", "off", "false", "0"):
        raise ValueError("MOSS-Image 由引擎管理梯度检查点，请选择自动或开启。")
    optimizer = str(params.get("optimizer") or "auto").lower()
    if optimizer == "auto": optimizer = "adamw8bit" if family == "qwen_image21" else "adamw"
    if optimizer not in ("adamw", "adamw8bit"):
        raise ValueError("Fizgig 普通 LoRA 当前支持 AdamW / AdamW8bit 优化器。")
    adaptive = None
    if family == "qwen_image21" and not params.get("initial_lora"):
        preset = str(params.get("fizgig_qwen_preset") or "auto")
        if preset == "auto": preset = "style" if params.get("at_sub_mode") == "style" else "fast"
        if preset not in ("fast", "standard", "style"): raise ValueError("未知 Qwen 训练预设。")
        rank = alpha = 8 if preset == "fast" else 16
        lr = 1.5e-4 if preset == "style" else 1e-4
        if preset != "style": adaptive = (2e-4, 4e-4) if preset == "fast" else (1e-4, 2e-4)
    from .lr_schedule import resolve as resolve_schedule
    lr_spec, custom_schedule = resolve_schedule(params)
    if custom_schedule:
        adaptive = None
        lr = float(numeric("unet_lr", 1e-4))
    proj = core._sanitize_dirname(params.get("project")) or mode
    output = Path(core.data_sub("output", proj)); output.mkdir(parents=True, exist_ok=True)
    output_name = core._sanitize_dirname(params.get("output_name")) or core.output_name_for(mode, params.get("style_preset"))
    model_path = Path(files["dit"])
    run_identity = {"version": version, "family": family, "commit": commit,
                    "model": str(model_path.resolve()), "model_bytes": model_path.stat().st_size,
                    "model_mtime_ns": model_path.stat().st_mtime_ns,
                    "rank": rank, "alpha": alpha, "optimizer": optimizer,
                    "learning_rate": lr, "adaptive_lr": list(adaptive) if adaptive else None}
    if custom_schedule:
        run_identity["lr_schedule"] = lr_spec
    if family == "zimage" or (family == "minimax" and files.get("training_adapter")):
        adapter_path = Path(files["training_adapter"])
        run_identity["training_adapter"] = [str(adapter_path.resolve()), adapter_path.stat().st_size, adapter_path.stat().st_mtime_ns]
    if family == "minimax":
        run_identity["training_type"] = h3_training_type
    if family == "moss_image" and version == LATEST_VERSION:
        run_identity["moss_clean_end"] = "60:7:30:15:2"
    if mask_report:
        run_identity["loss_masks"] = {"fingerprint": mask_report["fingerprint"], "mode": mask_mode, "floor": mask_floor}
    if params.get("initial_lora"):
        run_identity["initial_lora_sha256"] = params.get("training_origin", {}).get("sha256")
    marker = output / (output_name + ".fizgig-runtime.json")
    if resume_from:
        from kohya_core.training_resume import require_state
        resumed_step = require_state(resume_from, "fizgig")
        core._record_effective(resume_step=resumed_step, resume_snapshot=Path(resume_from).name)
        logf("[续训] 使用完整 Fizgig 状态：已完成 %d 步；权重、优化器和随机数状态由引擎恢复。" % resumed_step)
        state_file = Path(resume_from) / "training_state.json"
        previous = json.loads(state_file.read_text(encoding="utf-8")).get("kohya_runtime", {}) if state_file.is_file() else {}
        if family == "minimax" and previous.get("family") == "minimax" and "training_type" not in previous:
            # Old H3 runs always enabled clip stills, matching the character strategy.
            previous["training_type"] = "character"
        if previous != run_identity:
            raise RuntimeError("续训快照的引擎、底模、训练适配器、训练类型、rank、优化器、学习率计划或学习区域（遮罩内容 / 背景参与程度）与当前不同，或缺少版本记录。请使用原配置续训；改变这些设置后请从头训练。")
    swap_text = str(numeric("blocks_to_swap", "auto")).strip().lower()
    swap = -1 if swap_text in ("auto", "自动", "") else int(swap_text)
    if swap < -1: raise ValueError("块交换应为自动或非负整数。")
    if family in ("anima", "sdxl") and swap > 0:
        raise ValueError("新版 %s 不支持块交换，请使用自动 / 0 或 NF4。" % family)
    if precision in ("nf4", "hqq") or family in ("anima", "sdxl"): swap = 0
    frames = int(numeric("video_frames", 56)) if family == "minimax" and dataset["videos"] else 1
    if frames != 1 and (frames < 22 or (frames - 5) % 17):
        raise ValueError("H3 视频帧数需要为 22、39、56、73 等（17n + 5）。")
    env = _env(core, record)
    if record.get("backend") == "amd-rocm":
        ok, detail = core._fizgig_amd_preflight(record["python"], record["source"], env, logf, "Fizgig")
        if not ok: raise RuntimeError(detail)
    env["FIZGIG_KOHYA_RUNTIME"] = json.dumps(run_identity)
    env["FIZGIG_KOHYA_TARGET_EPOCHS"] = str(epochs)
    helper = _helper_configs(core, family, logf)
    if helper:
        folder, repo = helper
        env["FIZGIG_LOCAL_HELPERS"] = json.dumps({repo: folder})
        if family == "anima": env["FIZGIG_ANIMA_HELPER_DIR"] = folder
        if family == "sdxl": env["FIZGIG_SDXL_CONFIG_DIR"] = folder
    if family == "qwen_image21":
        env["FIZGIG_QWEN21_PROCESSOR_DIR"] = str(Path(core._ensure_at_image_qwen21_assets(logf)) / "processor")
    enabled = core._sample_preview_enabled(params, vram_gb)
    planned_preview = preview_prompts(dict(params, mode=mode), subsets) if enabled else None
    fingerprint, identity = _cache_identity(core, family, files, subsets, resolution, commit,
                                            training_type=h3_training_type if family == "minimax" else None)
    cache = Path(core.data_sub("dataset", proj, "fizgig_v7_cache", family, fingerprint))
    cache.mkdir(parents=True, exist_ok=True)
    _write(cache / "identity.json", identity)
    config = cache / "dataset.toml"
    core._write_fizgig_subset_config(subsets, str(cache), str(config), resolution)
    source, python = record["source"], record["python"]
    for stage, key in (("latents", "vae"), ("text", "te")):
        core.check_stop()
        logf("[Fizgig %s · %s] 缓存 %s；相同模型、分辨率和素材才复用缓存。" % (version, family, stage))
        cmd = [python, str(Path(source) / "src/fizgig/families/cache.py"), "--family", family,
               "--stage", stage, "--dataset_config", str(config), "--model", files[key],
               "--skip_existing", "--batch_size", "4096" if family == "moss_image" and stage == "text" else "1", "--num_workers", "2"]
        if family == "minimax" and stage == "latents":
            if files.get("audio_vae"): cmd += ["--aux", "audio_vae=" + files["audio_vae"]]
            if dataset["videos"] and h3_training_type != "style": cmd += ["--aux", "clip_still=1"]
        if core.run_stream(cmd, cwd=source, env=env, logf=logf): raise RuntimeError("%s %s 缓存失败，请查看日志。" % (family, stage))
    cmd = [python, str(Path(source) / "src/fizgig/families/train.py"), "--family", family,
           "--network_type", "lora", "--dit", files["dit"], "--dataset_config", str(config),
           "--output_dir", str(output), "--output_name", output_name,
           "--precision", precision, "--blocks_to_swap", str(swap),
           "--network_dim", str(rank), "--network_alpha", str(alpha), "--learning_rate", str(lr),
           "--max_train_epochs", str(epochs), "--save_every_n_epochs", str(core._save_every_note(params, epochs, logf, family)),
           "--seed", "42", "--optimizer_type", optimizer, "--ema_decay", "0.98",
           "--compile_blocks", "on" if params.get("compile") else "off",
           "--save_state", "--save_state_on_train_end", "--keep_last_n_states", "2",
           "--vae", files["vae"], "--text_encoder", files["te"]]
    if mask_report:
        cmd += ["--masked_training", "--mask_floor", str(mask_floor)]
        core._record_effective(loss_masks={k: v for k, v in mask_report.items() if k != "rows"})
        _write(output / (output_name + ".loss-masks.json"), mask_report)
    if family in ("anima", "sdxl"): cmd[cmd.index("--blocks_to_swap") + 1] = "0"
    if files.get("training_adapter"): cmd += ["--training_adapter", files["training_adapter"]]
    if adaptive: cmd += ["--adaptive_lr", "--adaptive_lr_min", str(adaptive[0]), "--adaptive_lr_max", str(adaptive[1])]
    if params.get("trigger"): cmd += ["--trigger_word", str(params["trigger"])]
    if family == "moss_image" and params.get("training_kind") == "multi_character":
        from .multi_character import normalize
        from .moss_multi_character import options as moss_options
        settings = normalize(params.get("multi_character", {}))
        roles = settings["roles"]
        if len(roles) < 2 or any(not r["trigger"] for r in roles):
            raise ValueError("MOSS 多角色训练请补齐至少两个角色及其触发词。")
        cmd += ["--metadata_trigger_phrase", ", ".join(r["trigger"] for r in roles)]
        dop = moss_options(settings)["dop"]
        if dop:
            cmd += ["--dop", "--dop_trigger", ",".join(r["trigger"] for r in roles),
                    "--dop_class", ",".join(r.get("class_word", "person") for r in roles),
                    "--dop_every", "2", "--dop_weight", "2"]
        core._record_effective(training_kind="multi_character", multi_character_dop=dop,
                               multi_character_triggers=[r["trigger"] for r in roles],
                               multi_character_layout=moss_options(settings)["layout"])
        logf("[MOSS 多角色] %d 个角色；保留原触发词；DOP %s。" % (len(roles), "开启：每 2 步、权重 2" if dop else "关闭"))
    if resume_from: cmd += ["--resume", str(resume_from)]
    options = []
    if family == "moss_image" and version == LATEST_VERSION:
        options += ["lownoise_pct=" + run_identity["moss_clean_end"]]
        core._record_effective(moss_clean_end=run_identity["moss_clean_end"])
        logf("[Fizgig · MOSS] Clean-end 使用新版渐变计划：60:7:30:15:2。")
    if family == "minimax":
        options += ["photo_blocks=20-49", "clip_blocks=20-49", "audio_blocks=20-49", "caption_dropout=0.05",
                    "tread=0.5@2-47", "shift=0.666667"]
        if dataset["videos"] and h3_training_type != "style": options += ["clip_still_as_photo=1"]
        logf("[Fizgig · H3] 训练类型：%s；视频静帧增强：%s。" % (h3_training_type, "开启" if dataset["videos"] and h3_training_type != "style" else "关闭"))
        core._record_effective(training_type=h3_training_type, caption_method=params.get("caption_method") or "wd14",
                               clip_still_as_photo=bool(dataset["videos"] and h3_training_type != "style"))
        if files.get("audio_vae"): options += ["audio_vae=" + files["audio_vae"]]
    if family == "sdxl": options += ["prediction=" + ("v" if core._looks_like_vpred(files["dit"]) else "epsilon")]
    total = sum(r * n for _, r, n in subsets) * epochs
    monitored = core._attach_train_monitor(logf, progress, lr=lr)
    if progress is not None:
        progress.set_total(total)
        if resume_from: progress.set_step(core.resume_step_from(resume_from))
    sample_epochs = core._fizgig_sample_epochs(params, sum(r * n for _, r, n in subsets), epochs)
    if enabled:
        prompt_lines, prompt_source = planned_preview
        prompts = cache / "sample_prompts.txt"; prompts.write_text("\n".join(prompt_lines) + "\n", encoding="utf-8")
        steps, cfg = ((30, 4.5) if family == "anima" else (30, 3.0) if family == "sdxl" else (8, 1.0) if family == "zimage" else (30, 4.0) if family == "moss_image" else (20, 3.5))
        cmd += ["--sample_prompts", str(prompts), "--sample_every_n_epochs", str(sample_epochs),
                "--sample_width", str(resolution), "--sample_height", str(resolution),
                "--sample_steps", str(steps), "--sample_cfg_scale", str(cfg),
                "--sample_seed", str(core._sample_seed(params)), "--sample_negative", str(params.get("global_neg") or "") if family != "zimage" else ""]
        if files.get("preview_checkpoint"): cmd += ["--preview_checkpoint", files["preview_checkpoint"]]
        if files.get("speed_lora"): cmd += ["--speed_lora", files["speed_lora"]]
        if family == "minimax":
            options += ["preview_frames=" + str(frames)]
            if files.get("audio_vae") and frames > 1: options += ["preview_audio=1"]
        preview_model = files.get("preview_checkpoint") or files["dit"]
        core._record_effective(sample_prompt="\n".join(prompt_lines), sample_prompt_source=prompt_source,
                               sample_prompt_file=str(prompts), sample_preview_checkpoint=preview_model,
                               sample_negative=str(params.get("global_neg") or "") if family != "zimage" else "")
        monitored("[Fizgig] 预览提示词（%s）：%s" % ("自定义" if prompt_source == "custom" else "多角色验证" if prompt_source == "multi_character" else "训练标签" if prompt_source == "dataset_caption" else "通用回退", " | ".join(prompt_lines)))
        monitored("[Fizgig] 预览底模：%s；使用引擎当前轮次 LoRA / EMA 权重，固定种子用于比较训练变化。" % preview_model)
        if (output / ".sample_override.json").is_file():
            monitored("[Fizgig] 注意：项目含外部引擎的 .sample_override.json，非空覆盖设置可能替代上述采样参数；请核对后续 [sample override] 日志。")
        monitored("[Fizgig] 预览：每 %s 轮，%spx，%s 步，CFG %s；开始时不额外采样；最后一轮仅在满足间隔时采样。文件在项目 output 中。" % (sample_epochs, resolution, steps, cfg))
    for option in options: cmd += ["--family_option", option]
    from .lr_schedule import command as schedule_command
    cmd, lr_spec = schedule_command(cmd, params, source=Path(source) / "src/fizgig/families/train.py")
    core._record_effective(**lr_spec)
    from .lora_continue import fizgig_command
    cmd = fizgig_command(cmd, source, output, params, resume_from)
    if params.get("initial_lora"):
        core._record_effective(initial_lora=params["initial_lora"], training_origin=params.get("training_origin"))
    _write(marker, run_identity)
    core._record_effective(engine="Fizgig", engine_version=version, family=family, network_type="lora",
        rank=rank, alpha=alpha, epochs=epochs, unet_lr=lr, resolution=resolution, total_steps=total,
        train_text_encoder=False, te_lr="不参与训练", optimizer=optimizer, quant_mode=precision,
        blocks_to_swap=swap, batch_size=1, cache_dir=str(cache), sample_enabled=enabled,
        sample_interval=sample_epochs, sample_interval_unit="epochs", sample_seed=core._sample_seed(params),
        sample_at_first=False, sample_width=resolution if enabled else None,
        sample_height=resolution if enabled else None, sample_steps=steps if enabled else None,
        sample_cfg_scale=cfg if enabled else None, sample_at_end=False)
    if family == "minimax":
        core._record_effective(training_adapter=files.get("training_adapter") or "未使用",
                               training_adapter_loaded=False)
    monitored("[Fizgig] %s · %s · 普通 LoRA；%s 个素材，%s 轮。" % (version, family, count, epochs))
    def runtime_log(line):
        text = str(line)
        planned = re.search(r"\[precision\] Auto plan: (bf16|int8|nf4|hqq), block swap (\d+)", text)
        if planned:
            core._record_effective(quant_mode=planned.group(1), blocks_to_swap=int(planned.group(2)))
        loaded = re.search(r"Loading .+ DiT \((bf16|int8|nf4|hqq)\)", text)
        if loaded:
            core._record_effective(quant_mode=loaded.group(1))
        if family == "minimax" and "[adapter] training adapter ON" in text:
            core._record_effective(training_adapter_loaded=True)
        monitored(line)
    if core.run_stream(cmd, cwd=source, env=env, logf=core._fizgig_warmup_log_filter(runtime_log)):
        raise RuntimeError("Fizgig %s LoRA 训练失败，请查看日志。" % family)
    return str(output)
