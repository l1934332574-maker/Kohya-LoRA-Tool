"""Concept-slider project contract. CPU only; no model or network imports."""
from __future__ import annotations
import math

SCHEMA_VERSION = 1
PURPOSES = {"bidirectional": "双向变化", "reduce": "减弱效果", "enhance": "增强效果"}
PRESETS = {"trial": {"steps": 128, "bank": 4}, "formal": {"steps": 768, "bank": 8}}
DEFAULTS = dict(schema_version=1, purpose="bidirectional", source="text", name="", neutral="",
                positive="", negative="", effect="", positive_dir="", negative_dir="", pairs=[],
                preset="trial", steps=768, rank=8, alpha=8.0, learning_rate=0.00005,
                resolution=512, seed=42, guidance=1.0, diff_weight=0.75, precision="auto",
                validation_prompts="", sample_steps=25, cfg=4.5)


def normalize(value):
    if value is None: value = {}
    if not isinstance(value, dict): raise ValueError("滑块设置需要为对象。")
    unknown = set(value) - set(DEFAULTS)
    if unknown: raise ValueError("未知滑块设置：" + ", ".join(sorted(unknown)))
    result = {**DEFAULTS, **value}
    if type(result["schema_version"]) is not int or result["schema_version"] != SCHEMA_VERSION: raise ValueError("滑块配置版本不受支持。")
    choices = {"purpose": PURPOSES, "source": ("text", "pairs"), "preset": ("trial", "formal", "custom"),
               "precision": ("auto", "bf16", "int8", "nf4")}
    for key, allowed in choices.items():
        if not isinstance(result[key], str) or result[key] not in allowed: raise ValueError("滑块字段「%s」选项无效。" % key)
    for key in ("name", "neutral", "positive", "negative", "effect", "positive_dir", "negative_dir", "validation_prompts"):
        if not isinstance(result[key], str) or len(result[key]) > 8192: raise ValueError("滑块字段「%s」过长或格式无效。" % key)
        result[key] = result[key].strip()
    ranges = {"steps": (32, 10000, int), "rank": (1, 128, int), "alpha": (0.1, 128, float),
              "learning_rate": (1e-7, 0.001, float), "resolution": (256, 1024, int),
              "seed": (0, 2147483646, int), "guidance": (0.1, 5, float), "diff_weight": (0, 1, float),
              "sample_steps": (10, 60, int), "cfg": (1, 12, float)}
    for key, (lo, hi, cast) in ranges.items():
        try:
            n = float(result[key])
            if isinstance(result[key], bool) or not math.isfinite(n) or not lo <= n <= hi or (cast is int and not n.is_integer()): raise ValueError()
            result[key] = cast(n)
        except (ValueError, TypeError, OverflowError): raise ValueError("滑块「%s」需要在 %s–%s 范围内。" % (key, lo, hi)) from None
    if result["resolution"] % 64: raise ValueError("滑块分辨率需要为 64 的倍数。")
    pairs = result["pairs"]
    if not isinstance(pairs, list) or len(pairs) > 1000: raise ValueError("图片对清单格式无效，最多 1000 对。")
    for pair in pairs:
        if not isinstance(pair, dict) or set(pair) != {"positive", "negative"} or any(not isinstance(pair[k], str) or len(pair[k]) > 4096 for k in pair):
            raise ValueError("每个图片对需要 positive / negative 相对文件名。")
    result["pairs"] = [dict(pair) for pair in pairs]
    return result


def prompts(settings):
    neutral = settings["neutral"]
    if not neutral: raise ValueError("请填写画面共有描述，说明主体、构图或画风。")
    if settings["purpose"] == "bidirectional":
        positive, negative = settings["positive"], settings["negative"]
        if not positive or not negative: raise ValueError("请填写正值与负值对应的完整画面描述。")
    else:
        if not settings["effect"]: raise ValueError("请填写希望减少或增强的效果。")
        target = neutral + ", " + settings["effect"]
        positive, negative = (neutral, target) if settings["purpose"] == "reduce" else (target, neutral)
    if positive.casefold() == negative.casefold(): raise ValueError("两个方向的描述完全相同，无法学习变化。")
    return [neutral, positive, negative]


def validation_prompts(settings):
    training = {p.casefold() for p in prompts(settings)} if settings["source"] == "text" else {settings["neutral"].casefold()}
    values = [p.strip() for p in settings["validation_prompts"].splitlines() if p.strip()]
    if len(values) > 4: raise ValueError("验证描述最多四条，避免采样耗时过长。")
    if any(p.casefold() in training for p in values): raise ValueError("验证描述不能与训练描述完全相同，请换一个场景或构图。")
    return list(dict.fromkeys(values))


def multipliers(settings):
    return [-1.0, -0.5, 0.0, 0.5, 1.0] if settings["purpose"] == "bidirectional" else [0.0, 0.25, 0.5, 0.75, 1.0]


def schedule(settings, train_count=None):
    preset = PRESETS.get(settings["preset"], {})
    steps = preset.get("steps", settings["steps"])
    items = train_count if settings["source"] == "pairs" else preset.get("bank", 8)
    if not items: raise ValueError("没有可以训练的图片对。")
    epochs = math.ceil(steps / items)
    # Divisor cadence guarantees a final comparison and a matching numbered checkpoint.
    cadence = max(d for d in range(1, epochs + 1) if epochs % d == 0 and d <= max(1, epochs // 4))
    samples = epochs if settings["preset"] == "trial" else cadence
    return dict(requested_steps=steps, total_steps=epochs * items, epochs=epochs, items=items,
                save_every_epochs=cadence, sample_every_epochs=samples, sample_every_steps=samples * items)


def parameters(config, name):
    settings = normalize(config.get("slider"))
    family = str(config.get("base_type") or "sdxl")
    if family not in ("sdxl", "anima") or config.get("mode") != family + "_fz":
        raise ValueError("滑块首批入口为 SDXL / 标准 28 层 Anima（Fizgig v7.0.1）。")
    params = config.get("params") or {}
    if not isinstance(params, dict): raise ValueError("训练参数需要为对象。")
    if params.get("fizgig_version", "v7.0.1") != "v7.0.1":
        raise ValueError("滑块需要 Fizgig v7.0.1，不能使用旧版本入口。")
    return dict(training_kind="slider", slider=settings, project=name, mode=family + "_fz", base_type=family,
                fizgig_version="v7.0.1", base_model=str(config.get("base_model") or ""),
                raw_dir=settings["positive_dir"], rank=settings["rank"], alpha=settings["alpha"],
                unet_lr=settings["learning_rate"], te_lr="不参与训练", train_text_encoder=False,
                resolution=settings["resolution"], quant_mode=settings["precision"], sample_seed=settings["seed"],
                sample_preview=True, at_sub_mode="slider")
