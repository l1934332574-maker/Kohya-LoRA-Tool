# -*- coding: utf-8 -*-
"""训练队列（v1）：把已保存项目排成一队，逐项“预处理 → 训练”自动跑。

- 仅运行期有效、不持久化；可跨引擎混排（第 1~4 引擎项目都能进队列）；
- 视频（H3）模式 v1 不入队；
- 停止 = 安全停掉当前项并中止整队（由窗口层调 stop_active_process / StopRequested）；
- 失败项跳过、由队列窗口收集汇总并可重新入队。

运行期懒 import Kohya一键工具，避免模块加载期循环依赖。
"""
import os

__all__ = ["params_from_project", "run_queue_item"]


def params_from_project(name):
    """从已保存项目 json 重建训练参数（缺失的高级参数交给各引擎默认值兜底）。"""
    from kohya_core.paths import load_project
    data = load_project(name)
    if not data:
        raise ValueError("项目不存在或已损坏：%s" % name)
    mode = data.get("mode") or "character"
    bt = data.get("base_type") or "sdxl"
    sub = data.get("params") or {}
    p = {
        "mode": mode,
        "base_type": bt,
        "at_sub_mode": data.get("at_sub_mode") or "character",
        "base_model": data.get("base_model") or "",
        "raw_dir": data.get("raw_dir") or "",
        "trigger": data.get("trigger") or "",
        "reg_dir": data.get("reg_dir") or "",
        "global_pos": data.get("global_pos") or "",
        "global_neg": data.get("global_neg") or "",
        "style_caption": data.get("style_caption") or "",
        "train_text_encoder": not bool(data.get("unet_only", False)),
        "train_env": data.get("train_env") or "",
        "fast_tier": data.get("fast_tier") or "auto",
        "project": (data.get("name") or name),
        "sample_preview": True,
        "strong_bind": bool(sub.get("strong_bind", True)),
    }
    for k in ("rank", "alpha", "unet_lr", "te_lr", "repeats", "max_epochs", "save_every",
              "crop_ratio", "sample_prompt", "sample_interval", "optimizer",
              "resolution", "video_steps", "gc"):
        if sub.get(k) is not None:
            p[k] = sub[k]
    return p


def run_queue_item(name, logf=print):
    """跑单个项目：预处理 → 训练。返回 (ok, msg)。

    引擎层的中断（StopRequested / 异常）会向上抛，由队列窗口统一处理
    （StopRequested=停止整队；Exception=跳过该项记入失败）。
    """
    import Kohya一键工具 as K
    p = params_from_project(name)
    mode = p["mode"]
    if mode == "video":
        return False, "视频(H3)模式暂不支持入队"
    K.reset_stop()
    if not p.get("raw_dir") or not os.path.isdir(p["raw_dir"]):
        return False, "项目缺少原始图片文件夹（raw_dir）"
    vram = K.detect_vram_gb()
    # 预处理分辨率：与 GUI 一键训练一致
    try:
        size = int(p.get("resolution") or (K.FLUX2FZ_RESOLUTION if mode == "flux2_fz" else (K.KREA2_RESOLUTION if mode in ("krea2", "krea2_fz", "krea2_at")
                                           else K.RESOLUTIONS.get(p.get("base_type"), 512))))
    except Exception:
        size = 1024
    pp_mode = K.preprocess_mode(mode, p.get("at_sub_mode"))
    K.preprocess(logf, input_dir=p["raw_dir"], size=size, mode=pp_mode,
                 trigger=p.get("trigger"), reg_dir=p.get("reg_dir"),
                 repeats=int(p.get("repeats") or 5),
                 dedup=True, wd14=True, square_crop=False,
                 crop_ratio=p.get("crop_ratio") or "",
                 min_size=256, blur_threshold=30.0, report=None, keep_tokens=None,
                 project=name, style_caption=p.get("style_caption") or "",
                 dataset_mode="character" if mode != "style" else None,
                 strong_bind=p.get("strong_bind", True),
                 concept_type=p.get("concept_type") or "",
                 clean_concept=bool(p.get("clean_concept", True)))
    logf("[队列] 预处理完成，开始训练…")
    if mode in ("qwen_image", "zimage"):
        K.train_at_image(logf, mode=mode, params=p, vram_gb=vram, resume_from=None, progress=None)
    elif mode == "krea2":
        K.train_krea2(logf, mode="krea2", params=p, vram_gb=vram, resume_from=None, progress=None)
    elif mode == "krea2_at":
        K.train_krea2_at(logf, mode="krea2_at", params=p, vram_gb=vram, resume_from=None, progress=None)
    elif mode == "krea2_fz":
        K.train_krea2_fizgig(logf, mode="krea2_fz", params=p, vram_gb=vram, resume_from=None, progress=None)
    elif mode == "flux2":
        K.train_flux2(logf, mode="flux2", params=p, vram_gb=vram, resume_from=None, progress=None)
    elif mode == "flux2_fz":
        K.train_flux2_fizgig(logf, mode="flux2_fz", params=p, vram_gb=vram, resume_from=None, progress=None)
    else:
        if not p.get("base_model"):
            return False, "第一引擎项目缺底模（base_model）"
        K.train(logf, base_model=p["base_model"], mode=mode, params=p,
                vram_gb=vram, resume_from=None, progress=None)
    try:
        K.export_project_named_lora(mode, name, logf=logf)
    except Exception:
        pass
    return True, "完成"
