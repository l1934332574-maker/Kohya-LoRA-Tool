"""Slider host: preflight, immutable run recipe and one cancellable child process."""
from __future__ import annotations
import json
import re
from pathlib import Path
import time
import uuid
from . import slider_project as schema
from . import slider_dataset as dataset
from .fizgig_engine import VERSION, COMMIT, runtime, source_version, _env, _write
from .fizgig_adapter import models, _validate, _helper_configs


def prepare(core, config, name):
    params = schema.parameters(config, name)
    settings = params["slider"]
    if not settings["name"]: raise ValueError("请给这个滑块取一个名字，说明你想改变什么。")
    if not settings["neutral"]: raise ValueError("请填写共有画面描述。")
    if settings["source"] == "text": schema.prompts(settings)
    validations = schema.validation_prompts(settings)
    record = runtime(core, VERSION)
    if not Path(record["python"]).is_file() or source_version(record["source"]) != VERSION:
        raise ValueError("滑块训练需要 Fizgig v7.0.1。请先安装 / 更新 Fizgig 引擎，原有项目仍使用原版本。")
    family = params["base_type"]
    files = models(core, family, params)
    _validate(core, family, files)
    vendor = core.detect_gpu_vendor()
    if vendor not in ("amd", "nvidia"): raise ValueError("尚未识别可用的 NVIDIA / AMD 显卡，请先检查训练环境。")
    scanned = dataset.scan(settings) if settings["source"] == "pairs" else None
    run_schedule = schema.schedule(settings, len(scanned["train"]) if scanned else None)
    warnings = ["实验性滑块入口：当前接入完成，尚未完成本机 GPU 端到端质量验收；请先试训。",
                "底模与文本编码器冻结。0 为停用 LoRA；训练结束不代表效果合格，需查看固定条件的权重对照。"]
    if family == "anima": warnings.append("当前只支持标准 28 层 Anima；40 层 / 2.9B 尚未接入滑块。")
    if vendor == "amd": warnings.append("AMD 的滑块训练与采样尚未单独实测；普通 LoRA 可用不代表滑块已经验收。")
    if settings["source"] == "text": warnings.append("文字模式学习底模已理解的效果；描述尽量只改变目标，不能保证学会底模不认识的新风格。")
    if not validations: warnings.append("未提供验证描述：会自动增加不同构图的验证画面；建议正式训练前填写自己的新场景。")
    if scanned: warnings += scanned["warnings"]
    if settings["preset"] != "trial" and scanned and len(scanned["train"]) < 4:
        warnings.append("正式训练的数据很少，请优先补充不同构图的对照；增加步数不能替代样本多样性。")
    return {"ok": True, "plan": dict(project_name=name, mode=params["mode"], mode_label="概念滑块 LoRA",
        training_kind="slider", training_engine="fizgig", engine_label="Fizgig v7.0.1 · 滑块训练",
        model_label=family.upper() if family == "sdxl" else "Anima · 标准 28 层", model_path=files["dit"],
        model_size="", model_download_required=False, raw_dir=settings["positive_dir"],
        image_count=len(scanned["train"]) if scanned else run_schedule["items"],
        data_count=len(scanned["train"]) if scanned else run_schedule["items"],
        data_label="训练图片对" if scanned else "底模自动生成的练习画面", data_unit="对" if scanned else "张",
        min_images=1 if scanned else 0, training_type="slider", training_target=schema.PURPOSES[settings["purpose"]],
        rank=settings["rank"], alpha=settings["alpha"], learning_rate=str(settings["learning_rate"]),
        resolution=settings["resolution"], steps=run_schedule["total_steps"], trigger="无需触发词",
        schedule_label="实际训练步数", schedule_value=str(run_schedule["total_steps"]), gpu_vendor=vendor,
        vram_gb=core.detect_vram_gb(), warnings=warnings, resume_path="", config_summary=params,
        save_interval_unit="epochs", save_interval_effective=run_schedule["save_every_epochs"],
        sampling_rule=dict(enabled=True, reason="滑块固定权重对照，不按显存静默关闭",
          cadence=("试训结束时生成一组对照" if settings["preset"] == "trial" else "每 %d 步生成对照，包含最后一轮" % run_schedule["sample_every_steps"]) + "；相同种子、描述与采样设置，仅改变 LoRA 权重", unit="steps"),
        execution_summary=[{"label": "变化目的", "value": schema.PURPOSES[settings["purpose"]]},
            {"label": "训练方式", "value": "文字指导（无需图片）" if not scanned else "配对图片（原图不变、同步裁剪）"},
            {"label": "文本编码器 / 底模", "value": "均冻结，只训练 LoRA；固定学习率、梯度检查点"},
            {"label": "验证", "value": "%d 对整对留出；%d 条另选的画面描述" % (len(scanned["holdout"]) if scanned else 0, len(validations) or 2)},
            {"label": "采样权重", "value": " / ".join("%g" % v for v in schema.multipliers(settings))},
            {"label": "训练步数", "value": "%d（目标 %d，按完整轮次向上取整）" % (run_schedule["total_steps"], run_schedule["requested_steps"])}],
        slider_schedule=run_schedule, slider_holdout=len(scanned["holdout"]) if scanned else 0)}


def train(core, config, name, logf=print, progress=None):
    plan = prepare(core, config, name)["plan"]
    params = schema.parameters(config, name)
    settings = params["slider"]
    family = params["base_type"]
    record = runtime(core, VERSION)
    files = models(core, family, params)
    if family == "anima":
        from .anima_ckpt import resolve_train_base
        files["dit"], _ = resolve_train_base(files["dit"], logf=logf)
    core.check_stop()
    recipe = dict(settings=settings, family=family, files=files, schedule=plan["slider_schedule"],
                  multipliers=schema.multipliers(settings), commit=COMMIT, backend_version=1,
                  validation_prompts=schema.validation_prompts(settings), holdout=[])
    run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    output = Path(core.data_sub("output", name, "slider_runs", run_id)); output.mkdir(parents=True, exist_ok=True)
    recipe["output_dir"] = str(output)
    recipe["output_name"] = (core._sanitize_dirname(name) or "concept") + "_slider"
    dataset_config = None
    if settings["source"] == "pairs":
        logf("[滑块] 正在检查图片对、同步裁剪并缓存；不做普通图集打标或单边过滤。")
        scanned = dataset.scan(settings, core.check_stop)
        # The plan is informational. Always recompute the split and schedule on the exact material being cached.
        recipe["schedule"] = schema.schedule(settings, len(scanned["train"]))
        root, positive, negative = dataset.materialize(settings, scanned, core.data_sub("dataset", name, "slider_pairs"), core.check_stop)
        recipe["holdout"] = [{side: str(root / ("holdout_" + side) / ("%05d.png" % i))
                              for side in ("positive", "negative")} for i in range(len(scanned["holdout"]))]
        dataset_config = root / ("dataset_" + family + ".toml")
        # Model identities are part of the latent/text cache location, so a new base cannot reuse old tensors.
        identities = {key: [str(Path(path).resolve()), Path(path).stat().st_size, Path(path).stat().st_mtime_ns] for key, path in files.items() if path}
        import hashlib
        model_id = hashlib.sha256(json.dumps(identities, sort_keys=True).encode()).hexdigest()[:16]
        cache = root / ("cache_" + family + "_" + model_id)
        lines = ['[general]', 'resolution = [%d, %d]' % (settings["resolution"], settings["resolution"]),
                 'caption_extension = ".txt"', 'batch_size = 1', 'num_repeats = 1', 'enable_bucket = false',
                 '[[datasets]]', 'image_directory = ' + json.dumps(str(positive)),
                 'control_directory = ' + json.dumps(str(negative)), 'cache_directory = ' + json.dumps(str(cache))]
        dataset_config.write_text("\n".join(lines) + "\n", encoding="utf-8")
        for warning in scanned["warnings"]: logf("[WARN] " + warning)
    recipe["dataset_config"] = str(dataset_config) if dataset_config else None
    if settings["source"] == "text": recipe["slider_prompts"] = schema.prompts(settings)
    recipe_path = output / "recipe.json"
    _write(recipe_path, recipe)
    env = _env(core, record)
    helper = _helper_configs(core, family, logf)
    if helper:
        folder, repo = helper
        env["FIZGIG_LOCAL_HELPERS"] = json.dumps({repo: folder})
        env["FIZGIG_ANIMA_HELPER_DIR" if family == "anima" else "FIZGIG_SDXL_CONFIG_DIR"] = folder
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    monitored = core._attach_train_monitor(logf, progress, lr=settings["learning_rate"])
    if progress: progress.set_total(recipe["schedule"]["total_steps"])
    if dataset_config:
        for stage, model_key in (("latents", "vae"), ("text", "te")):
            core.check_stop(); monitored("[滑块] 正在缓存配对%s…" % ("图像" if stage == "latents" else "共有描述"))
            cmd = [record["python"], str(Path(record["source"]) / "src/fizgig/families/cache.py"), "--family", family,
                   "--stage", stage, "--dataset_config", str(dataset_config), "--model", files[model_key],
                   "--slider", "--skip_existing", "--batch_size", "1", "--num_workers", "0"]
            if core.run_stream(cmd, cwd=record["source"], env=env, logf=monitored): raise RuntimeError("滑块图片对缓存失败，请查看训练日志。")
    runner = Path(core.KIT_DIR) / "training_backends/sliders/run.py"
    if not runner.is_file(): raise RuntimeError("安装包缺少滑块训练脚本，请使用完整安装包。")
    core._record_effective(training_kind="slider", engine="Fizgig", engine_version=VERSION, family=family,
        total_steps=recipe["schedule"]["total_steps"], epochs=recipe["schedule"]["epochs"], rank=settings["rank"],
        alpha=settings["alpha"], optimizer="adamw", batch_size=1, unet_lr=settings["learning_rate"],
        train_text_encoder=False, resolution=settings["resolution"], quant_mode=settings["precision"],
        sample_enabled=True, sample_seed=settings["seed"], sample_width=settings["resolution"],
        sample_height=settings["resolution"], sample_steps=settings["sample_steps"], sample_cfg_scale=settings["cfg"],
        sample_interval=recipe["schedule"]["sample_every_steps"], sample_interval_unit="steps", sample_at_end=True,
        slider_multipliers=recipe["multipliers"], slider_output=str(output))
    prediction = "v" if family == "sdxl" and core._looks_like_vpred(files["dit"]) else "epsilon"
    cmd = [record["python"], str(runner), "--source", record["source"], "--recipe", str(recipe_path), "--prediction", prediction]
    monitored("[滑块] 正在生成练习画面 / 加载模型；这段准备时间不计入训练步数。")
    def runtime_log(line):
        text = str(line)
        planned = re.search(r"\[precision\] Auto plan: (bf16|int8|nf4|hqq), block swap (\d+)", text)
        if planned: core._record_effective(quant_mode=planned.group(1), blocks_to_swap=int(planned.group(2)))
        loaded = re.search(r"Loading .+ DiT \((bf16|int8|nf4|hqq)\)", text)
        if loaded: core._record_effective(quant_mode=loaded.group(1))
        monitored(line)
    if core.run_stream(cmd, cwd=record["source"], env=env, logf=core._fizgig_warmup_log_filter(runtime_log)):
        raise RuntimeError("滑块训练失败；日志与已完成的检查点已保留。")
    core.check_stop()
    result = json.loads((output / "result.json").read_text(encoding="utf-8"))
    if result.get("status") != "generated" or not (output / result.get("checkpoint", "missing")).is_file():
        raise RuntimeError("进程结束但未确认滑块产物，不能标记为完成。")
    # No automatic project-name copy: distinct runs/checkpoints and their comparisons stay together.
    monitored("[完成] 滑块产物已生成，待查看效果：%s" % output)
    return result
