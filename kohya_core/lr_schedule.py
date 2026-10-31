"""Explicit learning-rate schedules shared by project persistence and engine adapters."""
import json

KINDS = ("auto", "constant", "constant_with_warmup", "cosine", "linear")
AI_MODES = ("qwen_image", "zimage", "krea2_at", "video")


def normalize(params):
    kind = str(params.get("lr_scheduler") or "auto")
    if kind not in KINDS:
        raise ValueError("学习率调度请选择自动、恒定、恒定预热、余弦或线性。")
    raw = params.get("lr_warmup_steps")
    if raw in (None, "", "auto"):
        warmup = None
    else:
        if isinstance(raw, bool) or not str(raw).isdigit() or not 0 <= int(raw) <= 100000:
            raise ValueError("学习率预热步数应为 0–100000 的整数。")
        warmup = int(raw)
    return kind, warmup


def resolve(params, default="constant", default_warmup=0):
    kind, warmup = normalize(params)
    mode = params.get("mode", "")
    custom = kind != "auto" or warmup is not None
    if custom and mode.endswith("_fz") and params.get("fizgig_version") not in ("v7.0.1", "v7.3.1", "v8.5.0", "v8.9.6"):
        raise ValueError("此 Fizgig 旧版本未接入自定义学习率调度，请选择自动或切换已支持的版本。")
    if custom and any(word in str(params.get("optimizer", "")).lower() for word in ("schedulefree", "prodigy", "dadapt", "adafactor")):
        raise ValueError("所选优化器接管学习率；调度器请设为自动并清空预热，或改用 AdamW。")
    effective = default if kind == "auto" else kind
    steps = default_warmup if warmup is None and kind == "auto" else (100 if effective == "constant_with_warmup" and warmup is None else warmup or 0)
    if effective == "constant" and steps:
        raise ValueError("恒定学习率不使用预热，请选择恒定＋预热。")
    if effective == "constant_with_warmup" and steps <= 0:
        raise ValueError("恒定＋预热需要大于 0 的预热步数。")
    if mode in AI_MODES and custom and effective not in ("constant_with_warmup",) and steps:
        raise ValueError("AI Toolkit 此调度方式不支持单独预热，请清空预热或选择恒定＋预热。")
    return {"lr_scheduler": effective, "lr_warmup_steps": steps}, custom


def command(cmd, params, default="constant", default_warmup=0, source=None):
    spec, custom = resolve(params, default, default_warmup)
    if not custom:
        return cmd, spec
    if source is not None and "--lr_scheduler" not in Path_text(source):
        raise ValueError("当前引擎源码未提供学习率调度参数，请更新此引擎或选择自动。")
    result, skip = [], False
    for arg in cmd:
        if skip:
            skip = False
            continue
        if arg in ("--lr_scheduler", "--lr_warmup_steps"):
            skip = True
        elif not arg.startswith(("--lr_scheduler=", "--lr_warmup_steps=")):
            result.append(arg)
    for key, value in spec.items():
        result += ["--" + key, str(value)]
    return result, spec


def Path_text(path):
    from pathlib import Path
    return Path(path).read_text(encoding="utf-8-sig")


def yaml_config(text, params):
    spec, custom = resolve(params)
    if not custom:
        return text, {"lr_scheduler": "engine_default", "lr_warmup_steps": "engine_default"}
    kwargs = ({"num_warmup_steps": spec["lr_warmup_steps"]} if spec["lr_scheduler"] == "constant_with_warmup" else
              {"start_factor": 1.0, "end_factor": 0.0} if spec["lr_scheduler"] == "linear" else {})
    block = "      train:\n        lr_scheduler: " + spec["lr_scheduler"] + "\n        lr_scheduler_params: " + json.dumps(kwargs) + "\n"
    if text.count("      train:\n") != 1:
        raise ValueError("无法确定训练配置中的学习率调度位置。")
    return text.replace("      train:\n", block), spec


def guard_resume(params, output, resume_from, default="constant", default_warmup=0):
    """Persist effective schedule and reject incompatible exact-state resumes."""
    from pathlib import Path
    import os
    import tempfile
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ".kohya_lr_schedule.json"
    spec, custom = resolve(params, default, default_warmup)
    if resume_from:
        if not path.is_file():
            if custom:
                raise ValueError("此旧断点没有学习率调度记录；请用自动调度续训，或从 LoRA 新建追加训练。")
            return spec
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("无法读取断点的学习率调度记录，请勿直接续训。") from exc
        if previous != spec:
            raise ValueError("断点的学习率调度与当前设置不同；请恢复原设置或从 LoRA 追加训练。")
        return spec
    fd, name = tempfile.mkstemp(prefix=".lr_schedule_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(spec, stream, ensure_ascii=False)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return spec
