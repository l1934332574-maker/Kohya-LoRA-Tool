"""Versioned slider extension, executed only by the selected Fizgig GPU environment.

Uses Fizgig v7.0.1's signed prompt/pair objectives and native LoRA serialization.
All extensions are scoped to this child; installed upstream sources are never edited.
"""
from __future__ import annotations
import argparse
import json
import logging
import math
from pathlib import Path
import sys
import time


def atomic_json(path, value):
    path = Path(path)
    staged = path.with_suffix(path.suffix + ".tmp")
    staged.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    staged.replace(path)


def run(args):
    recipe = json.loads(Path(args.recipe).read_text(encoding="utf-8"))
    if recipe.get("backend_version") != 1 or recipe.get("commit") != "1c8ec88edc1a4f99f73585aeae00fec740b12ea6":
        raise ValueError("Slider backend / upstream version mismatch")
    sys.path.insert(0, str(Path(args.source) / "src"))
    import torch
    from safetensors import safe_open
    from fizgig.families import train as trainer
    from fizgig.families.lora import FamilyLoRA
    from fizgig.families.registry import get as get_family
    settings, files, schedule = recipe["settings"], recipe["files"], recipe["schedule"]
    output = Path(recipe["output_dir"])
    desc = get_family(recipe["family"])
    if not desc or not desc.slider_training: raise ValueError("This family has no signed slider objective")
    if not torch.cuda.is_available(): raise RuntimeError("当前训练环境没有可用 GPU（NVIDIA / ROCm），请修复环境。")
    native_clip = torch.nn.utils.clip_grad_norm_
    def finite_clip(*values, **options):
        options['error_if_nonfinite'] = True
        return native_clip(*values, **options)
    torch.nn.utils.clip_grad_norm_ = finite_clip
    comparisons = []
    result = {"schema_version": 1, "status": "running", "quality": "pending_review", "comparisons": comparisons,
              "purpose": settings["purpose"], "multipliers": recipe["multipliers"], "family": recipe["family"],
              "holdout_pairs": len(recipe["holdout"]), "output_name": recipe["output_name"], "checkpoint": "",
              "base_model": Path(files["dit"]).name, "created": time.time()}
    result_path = output / "result.json"
    atomic_json(result_path, result)
    # Standard native LoRA tensors, with self-contained semantics and provenance.
    native_save = FamilyLoRA.save
    def save_with_direction(net, path, metadata=None, dtype=torch.bfloat16):
        if Path(path).name == recipe["output_name"] + ".safetensors":
            print("[滑块阶段] finish: 正在保存最终模型", flush=True)
        metadata = dict(metadata or {})
        metadata.update(kohya_training_kind="concept_slider", kohya_slider_schema="1", kohya_slider_purpose=settings["purpose"],
                        kohya_slider_name=settings["name"], kohya_slider_source=settings["source"], kohya_slider_zero="adapter_disabled", kohya_slider_backend="fizgig-v7.0.1",
                        kohya_slider_positive=(recipe.get("slider_prompts") or ["", settings["positive"], ""])[1],
                        kohya_slider_negative=(recipe.get("slider_prompts") or ["", "", settings["negative"]])[2],
                        kohya_slider_base=Path(files["dit"]).name)
        return native_save(net, path, metadata, dtype)
    FamilyLoRA.save = save_with_direction
    if settings["source"] == "text":
        native_step = trainer._prompt_slider_step
        def finite_prompt_step(*a, **kw):
            loss, timestep = native_step(*a, **kw)
            if not math.isfinite(loss): raise RuntimeError("滑块损失出现非有限值，停止训练；请降低学习率或检查精度。")
            return loss, timestep
        trainer._prompt_slider_step = finite_prompt_step
    trainer.SLIDER_PREVIEW_MULTIPLIERS = tuple(recipe["multipliers"])
    held_latents = []
    pair_validation = []
    result['pair_validation'] = pair_validation
    def validate_pairs(driver, dit, net, vae, cond, epoch):
        if not recipe['holdout']: return
        from fizgig.families import quant
        import numpy as np
        from PIL import Image
        device = next(dit.parameters()).device
        if not held_latents:
            # Holdout pairs are never in the training config. Cap numerical evaluation to two deterministic pairs.
            quant.move(dit, 'cpu')
            torch.cuda.empty_cache()
            try:
                for pair in recipe['holdout'][:2]:
                    images = []
                    for side in ('positive', 'negative'):
                        with Image.open(pair[side]) as image: images.append(np.array(image.convert('RGB')))
                    held_latents.append(driver.encode_images(vae, images))
            finally:
                quant.move(dit, device)
        baseline, adapted = [], []
        was_training = dit.training
        dit.eval()
        try:
            with torch.no_grad():
                for i, endpoints in enumerate(held_latents):
                    for j, endpoint in enumerate(endpoints):
                        latent = endpoint[None].to(device)
                        # Exact same noise/timestep for each endpoint's baseline and trained adapter.
                        for multiplier, losses in ((0., baseline), (1. if j == 0 else -1., adapted)):
                            net.set_trainable_multiplier(multiplier)
                            gen = torch.Generator(device='cpu').manual_seed(settings['seed'] + 777 + i * 2 + j)
                            loss, _ = driver.training_loss(dit, latent, cond, gen)
                            losses.append(float(loss))
            if not all(math.isfinite(loss) for loss in baseline + adapted): raise RuntimeError('留出验证出现非有限值')
            pair_validation.append(dict(epoch=epoch, pairs=len(held_latents), baseline_loss=sum(baseline)/len(baseline),
                                        slider_loss=sum(adapted)/len(adapted), note='数值参考，不能替代目标方向与画面保持的人工检查'))
        finally:
            net.set_trainable_multiplier(1.)
            dit.train(was_training)
    native_render = trainer._render_previews
    cached_validation = []
    validation = recipe["validation_prompts"] or [settings["neutral"] + ", full scene composition", settings["neutral"] + ", close-up framing"]
    # Never permit ordinary sample_override.json to change fixed slider comparison conditions.
    trainer._read_sample_override = lambda _output: None
    def compare(driver, dit, net, vae, encoded, out_dir, epoch, **kw):
        print("[滑块阶段] sample: 正在准备验证描述与权重对照", flush=True)
        native_generate = driver.generate
        frame = 0
        total_frames = 0
        def generate_with_progress(*values, **options):
            nonlocal frame
            frame += 1
            weight = recipe["multipliers"][(frame - 1) % len(recipe["multipliers"])]
            print("[滑块阶段] sample: 正在生成对照 %d / %d · 权重 %+.2g" %
                  (frame, total_frames, weight), flush=True)
            generated = native_generate(*values, **options)
            print("[滑块采样] 已生成 %d / %d 张对照画面" % (frame, total_frames), flush=True)
            return generated
        try:
            if not cached_validation:
                device = next(dit.parameters()).device
                for prompt in validation:
                    cached_validation.extend(trainer._encode_override(driver, files["te"], prompt, dit, device, parkable=True))
            all_encoded = [encoded[0], *cached_validation]
            descriptions = [settings["neutral"], *validation]
            # Explicit seed 0 remains fixed; the upstream CLI normally uses 0 for randomized previews.
            seeds = [settings["seed"]] if settings["preset"] == "trial" else [settings["seed"], settings["seed"] + 100000]
            total_frames = len(seeds) * len(all_encoded) * len(recipe["multipliers"])
            driver.generate = generate_with_progress
            all_paths = []
            for seed in seeds:
                for i, cond in enumerate(all_encoded):
                    call = {**kw, "seed": seed + i, "slider": True, "width": settings["resolution"], "height": settings["resolution"],
                            "steps": settings["sample_steps"], "cfg": settings["cfg"]}
                    # Save one complete strip at a time so the gallery need not wait for every validation scene.
                    paths = native_render(driver, dit, net, vae, [cond], out_dir, epoch, **call)
                    all_paths.extend(paths)
                    for path in paths:
                        relative = Path(path).relative_to(output).as_posix()
                        comparisons.append(dict(name=relative, epoch=epoch, seed=seed + i,
                            prompt=descriptions[i], role="training_context" if i == 0 else "held_out_prompt",
                            multipliers=recipe["multipliers"], resolution=settings["resolution"], steps=settings["sample_steps"],
                            cfg=settings["cfg"], checkpoint=recipe["output_name"] + "-%06d.safetensors" % epoch))
                    atomic_json(result_path, result)
                    print("[滑块采样] 已保存 %d / %d 组权重对照" %
                          (len(all_paths), len(seeds) * len(all_encoded)), flush=True)
            try:
                if recipe['holdout']:
                    print("[滑块阶段] sample: 正在验证留出图片对", flush=True)
                validate_pairs(driver, dit, net, vae, encoded[0], epoch)
            except Exception as exc:
                result['holdout_validation_error'] = str(exc)[:500]
                logging.warning('[WARN] 留出图片对数值验证未完成：%s；保留已生成对照，效果仍待检查。', exc)
            atomic_json(result_path, result)
            return all_paths
        finally:
            driver.generate = native_generate
            if epoch < schedule["epochs"]:
                print("[滑块阶段] train: 继续滑块训练", flush=True)
            else:
                print("[滑块阶段] finish: 正在保存模型与训练结果", flush=True)
    trainer._render_previews = compare
    if recipe["family"] == "sdxl": options = {"prediction": args.prediction}
    else: options = {}
    try:
        checkpoint = trainer.train_family(recipe["family"], files["dit"], recipe["dataset_config"], str(output), recipe["output_name"],
            network_dim=settings["rank"], network_alpha=settings["alpha"], learning_rate=settings["learning_rate"],
            max_train_epochs=schedule["epochs"], save_every_n_epochs=schedule["save_every_epochs"],
            seed=settings["seed"], precision=settings["precision"], blocks_to_swap=0, compile_blocks="off",
            gradient_checkpointing=True, gradient_accumulation_steps=1, optimizer_type="adamw", lr_scheduler="constant",
            max_grad_norm=1.0, ema_decay=0, save_state=True, save_state_on_train_end=True, keep_last_n_states=2,
            vae_path=files["vae"], te_path=files["te"], sample_prompts=[settings["neutral"]],
            sample_every_n_epochs=schedule["sample_every_epochs"], sample_width=settings["resolution"],
            sample_height=settings["resolution"], sample_steps=settings["sample_steps"], sample_cfg_scale=settings["cfg"],
            sample_negative="", sample_seed=settings["seed"] or 1,
            slider_pairs=settings["source"] == "pairs", slider_diff_weight=settings["diff_weight"],
            slider_prompts=recipe.get("slider_prompts"), slider_guidance=settings["guidance"],
            slider_bank=schedule["items"], slider_bank_res=settings["resolution"],
            metadata_title=settings["name"], family_options=options)
        # Verify tensors and metadata in the exported native file, not just child exit code.
        with safe_open(checkpoint, framework="pt", device="cpu") as handle:
            keys = list(handle.keys())
            factors = [key for key in keys if "lora_up" in key or "lora_B" in key]
            if not factors or (handle.metadata() or {}).get("kohya_training_kind") != "concept_slider":
                raise RuntimeError("导出文件不含可识别的滑块 LoRA 权重 / 元数据。")
            changed = False
            for key in keys:
                tensor = handle.get_tensor(key)
                if not bool(torch.isfinite(tensor).all()): raise RuntimeError("导出 LoRA 含非有限值，未标记为完成。")
                if key in factors and bool(torch.count_nonzero(tensor)): changed = True
            if not changed: raise RuntimeError("LoRA 权重没有发生更新，未标记为完成。")
        result.update(status="generated", checkpoint=Path(checkpoint).name, completed=time.time(),
                      export_checked=True, preview_status="available" if comparisons else "missing",
                      message="产物已生成，待查看效果" if comparisons else "产物已生成；权重对照未成功，请检查采样日志")
        atomic_json(result_path, result)
        print("[滑块] 导出权重检查完成；效果等待用户比较，不以 loss 判定合格。", flush=True)
    except BaseException as exc:
        result.update(status="failed", error=str(exc)[:1000], completed=time.time())
        atomic_json(result_path, result)
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--prediction", choices=("epsilon", "v"), default="epsilon")
    run(parser.parse_args())
