"""The v7 ordinary-LoRA adapter. Model checks, cache identity and CLI are shared."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from .fizgig_engine import VERSION, COMMIT, MIRROR, source_version, _env, _sha, _write

FAMILIES = {"krea2_fz": "krea2", "flux2_fz": "klein", "qwen21_fz": "qwen_image21",
            "h3_fz": "minimax", "anima_fz": "anima", "sdxl_fz": "sdxl"}


def models_dir(core, family):
    return str(Path(core.KIT_DIR) / "models" / ("base" if family == "sdxl" else "anima"))


def models(core, family, params=None):
    params = params or {}
    if family == "krea2":
        f = core.krea2_model_files()
        return dict(f, dit=f.get("raw"), preview_checkpoint=f.get("turbo"))
    if family == "klein":
        f = core.flux2_fz_model_files()
        f["preview_checkpoint"] = str(Path(core.flux2_models_dir()) / "flux-2-klein-9b.safetensors")
        if not Path(f["preview_checkpoint"]).is_file(): f["preview_checkpoint"] = None
        return f
    if family == "qwen_image21": return core.qwen21_fz_model_files()
    if family == "minimax":
        f = core.h3_fz_model_files()
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


def _validate(core, family, files):
    required = ("dit", "te", "vae")
    if family == "qwen_image21": required += ("training_adapter",)
    for key in required:
        path = files.get(key)
        if not path or not Path(path).is_file(): raise RuntimeError("缺少 %s 的 %s 模型，请先准备模型文件。" % (family, key))
        if not core._safetensors_complete(path):
            raise RuntimeError("模型文件不完整或损坏：%s。请重新下载该文件。" % path)
    validate_base(core, family, files["dit"])
    if family == "krea2" and core._safetensors_is_prequantized(files["dit"]):
        raise RuntimeError("Krea2 需要 bf16 RAW 底模；推理用预量化文件不能直接用于训练。")


def validate_base(core, family, checkpoint):
    if not core._safetensors_complete(checkpoint):
        raise RuntimeError("模型文件不完整或损坏，请重新下载。")
    if family == "anima":
        if core.detect_base_type(checkpoint) != "anima":
            raise RuntimeError("所选文件不是可识别的 Anima 底模；文本编码器不能作为底模。")
        keys = core._safetensors_keys(checkpoint)
        blocks = {int(m.group(1)) for k in keys if (m := re.search(r"(?:^|\.)blocks\.(\d+)\.", k))}
        if blocks != set(range(28)):
            raise RuntimeError("Fizgig v7.0.1 仅支持标准 28 层 Anima；当前检测到 %s 层。2.9B / 40 层请选 Kohya 引擎。" % len(blocks))
    if family == "sdxl" and core.detect_base_type(checkpoint) != "sdxl":
        raise RuntimeError("Fizgig SDXL 需要包含 UNet、双 CLIP 和 VAE 的完整 SDXL safetensors 底模。")


def _cache_identity(core, family, files, subsets, resolution):
    def stat(path):
        p = Path(path); st = p.stat()
        return [str(p.resolve()), st.st_size, st.st_mtime_ns]
    assets = {k: stat(v) for k, v in files.items() if v and k in ("dit", "vae", "te", "audio_vae")}
    images = []
    for folder, _repeats, _count in subsets:
        for path in sorted(Path(folder).iterdir()):
            if path.is_file() and path.suffix.lower() in core.FIZGIG_IMAGE_EXTS | {".mp4", ".wav", ".mp3", ".flac", ".m4a", ".txt"}:
                images.append(stat(path))
    signature = {"commit": COMMIT, "family": family, "resolution": resolution, "models": assets, "files": images}
    return hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:20], signature


def train_lora(core, record, logf, mode, params, vram_gb, resume_from, progress):
    if source_version(record["source"]) != VERSION or not Path(record["python"]).is_file():
        raise RuntimeError("此项目选择 Fizgig v7.0.1，请先安装或更新引擎。")
    family = FAMILIES[mode]
    files = models(core, family, params)
    _validate(core, family, files)
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
    if precision not in allowed:
        raise ValueError("新版 %s 支持 %s；当前精度 %s 不受支持，请重新选择。" % (family, "/".join(allowed), precision))
    train_dir = (params.get("train_data_dir") or params.get("raw_dir")) if family == "minimax" else core.dataset_train_dir("character", params.get("project"))
    if family == "minimax":
        dataset, subsets = core._scan_fizgig_h3_subsets(train_dir, params.get("repeats", 1))
        count, captions = dataset["total"], dataset["missing_captions"]
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
    epochs = int(numeric("max_epochs", 16))
    rank = int(numeric("rank", 32))
    alpha = float(numeric("alpha", rank))
    lr = float(numeric("unet_lr", 1e-4))
    if min(resolution, epochs, rank, alpha, lr) <= 0 or not all(math.isfinite(v) for v in (alpha, lr)):
        raise ValueError("分辨率、轮数、rank、alpha、学习率需要为正数。")
    if int(numeric("batch_size", 1)) != 1:
        raise ValueError("当前 Fizgig 接入按每次一个素材训练；批大小请设为 1。")
    optimizer = str(params.get("optimizer") or "auto").lower()
    if optimizer == "auto": optimizer = "adamw8bit" if family == "qwen_image21" else "adamw"
    if optimizer not in ("adamw", "adamw8bit"):
        raise ValueError("Fizgig 普通 LoRA 当前支持 AdamW / AdamW8bit 优化器。")
    adaptive = None
    if family == "qwen_image21":
        preset = str(params.get("fizgig_qwen_preset") or "auto")
        if preset == "auto": preset = "style" if params.get("at_sub_mode") == "style" else "fast"
        if preset not in ("fast", "standard", "style"): raise ValueError("未知 Qwen 训练预设。")
        rank = alpha = 8 if preset == "fast" else 16
        lr = 1.5e-4 if preset == "style" else 1e-4
        if preset != "style": adaptive = (2e-4, 4e-4) if preset == "fast" else (1e-4, 2e-4)
    proj = core._sanitize_dirname(params.get("project")) or mode
    output = Path(core.data_sub("output", proj)); output.mkdir(parents=True, exist_ok=True)
    output_name = core._sanitize_dirname(params.get("output_name")) or core.output_name_for(mode, params.get("style_preset"))
    model_path = Path(files["dit"])
    run_identity = {"version": VERSION, "family": family, "commit": COMMIT,
                    "model": str(model_path.resolve()), "model_bytes": model_path.stat().st_size,
                    "model_mtime_ns": model_path.stat().st_mtime_ns,
                    "rank": rank, "alpha": alpha, "optimizer": optimizer,
                    "learning_rate": lr, "adaptive_lr": list(adaptive) if adaptive else None}
    marker = output / (output_name + ".fizgig-runtime.json")
    if resume_from:
        state_file = Path(resume_from) / "training_state.json"
        previous = json.loads(state_file.read_text(encoding="utf-8")).get("kohya_runtime", {}) if state_file.is_file() else {}
        if previous != run_identity:
            raise RuntimeError("续训快照的引擎、底模、rank、优化器或学习率计划与当前选择不同，或缺少版本记录。请用原配置续训；新版可从头训练。")
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
    fingerprint, identity = _cache_identity(core, family, files, subsets, resolution)
    cache = Path(core.data_sub("dataset", proj, "fizgig_v7_cache", family, fingerprint))
    cache.mkdir(parents=True, exist_ok=True)
    _write(cache / "identity.json", identity)
    config = cache / "dataset.toml"
    core._write_fizgig_subset_config(subsets, str(cache), str(config), resolution)
    source, python = record["source"], record["python"]
    for stage, key in (("latents", "vae"), ("text", "te")):
        core.check_stop()
        logf("[Fizgig %s · %s] 缓存 %s；相同模型、分辨率和素材才复用缓存。" % (VERSION, family, stage))
        cmd = [python, str(Path(source) / "src/fizgig/families/cache.py"), "--family", family,
               "--stage", stage, "--dataset_config", str(config), "--model", files[key],
               "--skip_existing", "--batch_size", "1", "--num_workers", "2"]
        if family == "minimax" and stage == "latents":
            if files.get("audio_vae"): cmd += ["--aux", "audio_vae=" + files["audio_vae"]]
            if dataset["videos"]: cmd += ["--aux", "clip_still=1"]
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
    if family in ("anima", "sdxl"): cmd[cmd.index("--blocks_to_swap") + 1] = "0"
    if files.get("training_adapter"): cmd += ["--training_adapter", files["training_adapter"]]
    if adaptive: cmd += ["--adaptive_lr", "--adaptive_lr_min", str(adaptive[0]), "--adaptive_lr_max", str(adaptive[1])]
    if params.get("trigger"): cmd += ["--trigger_word", str(params["trigger"])]
    if resume_from: cmd += ["--resume", str(resume_from)]
    options = []
    if family == "minimax":
        options += ["photo_blocks=20-49", "clip_blocks=20-49", "audio_blocks=20-49", "caption_dropout=0.05",
                    "tread=0.5@2-47", "shift=0.666667"]
        if dataset["videos"]: options += ["clip_still_as_photo=1"]
        if files.get("audio_vae"): options += ["audio_vae=" + files["audio_vae"]]
    if family == "sdxl": options += ["prediction=" + ("v" if core._looks_like_vpred(files["dit"]) else "epsilon")]
    total = sum(r * n for _, r, n in subsets) * epochs
    monitored = core._attach_train_monitor(logf, progress, lr=lr)
    if progress is not None:
        progress.set_total(total)
        if resume_from: progress.set_step(core.resume_step_from(resume_from))
    enabled = core._sample_preview_enabled(params, vram_gb)
    sample_epochs = core._fizgig_sample_epochs(params, sum(r * n for _, r, n in subsets), epochs)
    if enabled:
        prompt = str(params.get("sample_prompt") or params.get("trigger") or "a detailed portrait, high quality").strip()
        positive = str(params.get("global_pos") or "").strip()
        prompt_lines = [", ".join(filter(None, (positive, line.strip()))) for line in prompt.splitlines() if line.strip()]
        prompts = cache / "sample_prompts.txt"; prompts.write_text("\n".join(prompt_lines) + "\n", encoding="utf-8")
        steps, cfg = ((30, 4.5) if family == "anima" else (30, 3.0) if family == "sdxl" else (20, 3.5))
        cmd += ["--sample_prompts", str(prompts), "--sample_every_n_epochs", str(sample_epochs),
                "--sample_width", str(resolution), "--sample_height", str(resolution),
                "--sample_steps", str(steps), "--sample_cfg_scale", str(cfg),
                "--sample_seed", str(core._sample_seed(params)), "--sample_negative", str(params.get("global_neg") or "")]
        if files.get("preview_checkpoint"): cmd += ["--preview_checkpoint", files["preview_checkpoint"]]
        if files.get("speed_lora"): cmd += ["--speed_lora", files["speed_lora"]]
        if family == "minimax":
            options += ["preview_frames=" + str(frames)]
            if files.get("audio_vae") and frames > 1: options += ["preview_audio=1"]
        monitored("[Fizgig] 预览：每 %s 轮，%spx，%s 步，CFG %s；开始时不额外采样；最后一轮仅在满足间隔时采样。文件在项目 output 中。" % (sample_epochs, resolution, steps, cfg))
    for option in options: cmd += ["--family_option", option]
    _write(marker, run_identity)
    core._record_effective(engine="Fizgig", engine_version=VERSION, family=family, network_type="lora",
        rank=rank, alpha=alpha, epochs=epochs, unet_lr=lr, resolution=resolution, total_steps=total,
        train_text_encoder=False, te_lr="不参与训练", optimizer=optimizer, quant_mode=precision,
        blocks_to_swap=swap, batch_size=1, cache_dir=str(cache), sample_enabled=enabled,
        sample_interval=sample_epochs, sample_interval_unit="epochs", sample_seed=core._sample_seed(params),
        sample_at_first=False, sample_width=resolution if enabled else None,
        sample_height=resolution if enabled else None, sample_steps=steps if enabled else None,
        sample_cfg_scale=cfg if enabled else None, sample_at_end=False)
    monitored("[Fizgig] %s · %s · 普通 LoRA；%s 个素材，%s 轮。" % (VERSION, family, count, epochs))
    def runtime_log(line):
        text = str(line)
        planned = re.search(r"\[precision\] Auto plan: (bf16|int8|nf4|hqq), block swap (\d+)", text)
        if planned:
            core._record_effective(quant_mode=planned.group(1), blocks_to_swap=int(planned.group(2)))
        loaded = re.search(r"Loading .+ DiT \((bf16|int8|nf4|hqq)\)", text)
        if loaded:
            core._record_effective(quant_mode=loaded.group(1))
        monitored(line)
    if core.run_stream(cmd, cwd=source, env=env, logf=core._fizgig_warmup_log_filter(runtime_log)):
        raise RuntimeError("Fizgig %s LoRA 训练失败，请查看日志。" % family)
    return str(output)
