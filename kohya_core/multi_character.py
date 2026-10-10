"""Multi-character datasets: explicit identities, reviewed group captions and bounded sampling."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import uuid
from pathlib import Path

KIND = "multi_character"
IMAGE_MODES = {"character", "krea2", "krea2_at", "krea2_fz", "flux2", "flux2_fz",
               "qwen21_fz", "anima_fz", "sdxl_fz", "qwen_image", "zimage"}
_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_TRIGGER = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{2,63}$")


def _text(value, limit=4096):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise ValueError("多角色字段格式无效或过长。")
    return value.strip()


def normalize(value):
    """Allow incomplete drafts, reject ambiguous IDs and stale member references."""
    if not isinstance(value, dict):
        raise ValueError("多角色配置必须是对象。")
    roles, groups, targets = [], [], []
    for key in ("roles", "groups", "targets"):
        if not isinstance(value.get(key, []), list) or len(value.get(key, [])) > 128:
            raise ValueError("多角色列表格式无效或过长。")
    ids, triggers = set(), set()
    for row in value.get("roles", []):
        if not isinstance(row, dict): raise ValueError("角色配置无效。")
        rid = _text(row.get("id", ""), 64)
        trigger = _text(row.get("trigger", ""), 64)
        if not _ID.fullmatch(rid) or rid in ids: raise ValueError("角色 ID 无效或重复。")
        if trigger and (not _TRIGGER.fullmatch(trigger) or trigger.casefold() in triggers):
            raise ValueError("触发词应为独立的英文字母、数字或下划线，且不能重复。")
        ids.add(rid)
        if trigger: triggers.add(trigger.casefold())
        roles.append({"id": rid, "name": _text(row.get("name", ""), 100), "trigger": trigger,
                      "directory": _text(row.get("directory", "")),
                      "description": _text(row.get("description", ""))})
    group_ids = set()
    for row in value.get("groups", []):
        if not isinstance(row, dict): raise ValueError("同框素材配置无效。")
        gid = _text(row.get("id", ""), 64)
        if not _ID.fullmatch(gid) or gid in group_ids or gid in ids: raise ValueError("同框组 ID 无效或重复。")
        group_ids.add(gid)
        members = row.get("members", [])
        if not isinstance(members, list) or len(members) > len(roles): raise ValueError("同框角色列表无效。")
        selected, seen = [], set()
        for member in members:
            if not isinstance(member, dict): raise ValueError("同框角色配置无效。")
            rid = member.get("role_id")
            if not isinstance(rid, str) or rid not in ids or rid in seen: raise ValueError("同框素材引用了未知或重复角色。")
            seen.add(rid)
            selected.append({"role_id": rid, "position": _text(member.get("position", ""), 200)})
        if not isinstance(row.get("reviewed", False), bool): raise ValueError("同框标注确认必须是开关值。")
        groups.append({"id": gid, "name": _text(row.get("name", ""), 100),
                       "directory": _text(row.get("directory", "")), "members": selected,
                       "caption": _text(row.get("caption", "")), "reviewed": row.get("reviewed", False)})
    for row in value.get("targets", []):
        if not isinstance(row, dict): raise ValueError("目标组合无效。")
        members = row.get("role_ids", [])
        if not isinstance(members, list) or any(not isinstance(rid, str) or rid not in ids for rid in members) or len(set(members)) != len(members):
            raise ValueError("目标组合引用了未知或重复角色。")
        targets.append({"role_ids": list(members), "prompt": _text(row.get("prompt", ""))})
    if not isinstance(value.get("balance", True), bool): raise ValueError("采样均衡必须是开关值。")
    return {"roles": roles, "groups": groups, "targets": targets, "balance": value.get("balance", True)}


def _contains(text, trigger):
    return bool(re.search(r"(?<![\w])" + re.escape(trigger) + r"(?![\w])", text, re.I))


def validation_prompts(settings):
    roles = {r["id"]: r for r in settings["roles"]}
    prompts = [{"kind": "solo", "roles": [r["id"]], "prompt":
                f'{r["trigger"]}, {" ".join(r["description"].splitlines()) or "a person"}, medium shot, plain background'}
               for r in roles.values() if r["trigger"]]
    for target in settings["targets"]:
        selected = [roles[rid] for rid in target["role_ids"]]
        if len(selected) < 2: continue
        prompt = target["prompt"] or (f'{len(selected)} people standing together. ' + " ".join(
            f'{r["trigger"]} is at position {i + 1} from the left.' for i, r in enumerate(selected)))
        missing = [r["trigger"] for r in selected if r["trigger"] and not _contains(prompt, r["trigger"])]
        if missing: prompt = ", ".join(missing) + ". " + prompt
        prompts.append({"kind": "group", "roles": target["role_ids"], "prompt": prompt.replace("\n", " ")})
        if len(selected) == 2 and not target["prompt"]:
            prompts.append({"kind": "group_reversed", "roles": list(reversed(target["role_ids"])),
                            "prompt": f'2 people standing together. {selected[1]["trigger"]} is on the left. {selected[0]["trigger"]} is on the right.'})
    return prompts


def parameters(core, config, params):
    if config.get("mode") not in IMAGE_MODES: raise ValueError("多角色模式请选择图像人物 LoRA 训练入口。")
    if config.get("mode", "").endswith("_fz") and params.get("fizgig_version") != "v7.0.1":
        raise ValueError("多角色 Fizgig 入口请使用 v7.0.1；旧版本项目保留原训练方式。")
    settings = normalize(config.get("multi_character", {}))
    directories = [r["directory"] for r in settings["roles"]] + [g["directory"] for g in settings["groups"]]
    params.update(training_kind=KIND, multi_character=settings, at_sub_mode="character", trigger="",
                  strong_bind=False, clean_concept=False, keep_user_captions=True, caption_method="existing",
                  crop_ratio="", overwrite=True, raw_dir=next((d for d in directories if d), ""))
    if not params.get("sample_prompt"):
        prompts = validation_prompts(settings)
        # Bound automatic preview cost; the full validation set is exported separately.
        selected = [p for p in prompts if p["kind"] == "solo"][:2] + [p for p in prompts if p["kind"] != "solo"][:4]
        params["sample_prompt"] = "\n".join(p["prompt"] for p in selected)
    return params


def scan(value, check_stop=lambda: None):
    from .project_config import dataset_images, read_caption
    settings = normalize(value)
    if len(settings["roles"]) < 2: raise ValueError("请至少添加两个角色。")
    role_map = {r["id"]: r for r in settings["roles"]}
    for role in role_map.values():
        if not role["name"] or not role["trigger"] or not role["directory"]:
            raise ValueError("请补齐每个角色的名称、独立触发词和单人素材目录。")
    entries, summary, warnings, seen = [], [], [], {}
    for group, row in [(False, r) for r in settings["roles"]] + [(True, g) for g in settings["groups"]]:
        check_stop()
        label = row["name"] or row["id"]
        if not row["directory"]: raise ValueError(f"请选择「{label}」的图片目录。")
        images = dataset_images(row["directory"])
        if not images: raise ValueError(f"「{label}」目录没有可用图片。")
        if len(images) > 3000: raise ValueError("每组最多处理 3000 张图片，请选择具体素材目录。")
        if group:
            if len(row["members"]) < 2: raise ValueError(f"「{label}」至少需要选择两个同框角色。")
            if not row["reviewed"]: raise ValueError(f"请确认「{label}」每张图片的角色与标注位置一致。")
            member_ids = [m["role_id"] for m in row["members"]]
        else: member_ids = [row["id"]]
        generated = reused = 0
        for image in images:
            check_stop()
            key = str(image.resolve()).casefold()
            if key in seen: raise ValueError(f"同一图片被分配到多组：{image.name}（{seen[key]} / {label}）。")
            seen[key] = label
            try: caption = read_caption(image)
            except FileNotFoundError: caption = ""
            if caption:
                wrong = [r["trigger"] for rid, r in role_map.items() if rid not in member_ids and _contains(caption, r["trigger"])]
                if wrong: raise ValueError(f"{image.name} 的标签含未分配的角色触发词：{', '.join(wrong)}。")
                if group and any(not _contains(caption, role_map[rid]["trigger"]) for rid in member_ids):
                    raise ValueError(f"同框图片 {image.name} 的已有标签未包含所有指定角色的触发词。请补齐身份与位置描述。")
                if not group and not _contains(caption, row["trigger"]): caption = row["trigger"] + ", " + caption
                reused += 1
            elif group:
                if any(not m["position"] for m in row["members"]):
                    raise ValueError(f"{image.name} 没有标签，请填写同框组各角色的位置，或准备逐图标签。")
                caption = f'{len(member_ids)} people. ' + " ".join(
                    f'{role_map[m["role_id"]]["trigger"]} is {m["position"]}.' for m in row["members"])
                caption += " " + row["caption"]
                generated += 1
            else:
                if not row["description"]: raise ValueError(f"{image.name} 没有标签，请补充「{label}」的角色描述，或准备同名 .txt。")
                caption = row["trigger"] + ", " + row["description"]
                generated += 1
            wrong = [r["trigger"] for rid, r in role_map.items() if rid not in member_ids and _contains(caption, r["trigger"])]
            if wrong: raise ValueError(f"{image.name} 的描述包含未分配的角色触发词：{', '.join(wrong)}。")
            caption = " ".join(caption.splitlines())
            entries.append({"path": image, "caption": caption.strip(), "group_id": row["id"], "group": group, "roles": member_ids})
        if not group and len(images) < 10: warnings.append(f"「{label}」只有 {len(images)} 张单人图，身份学习需要重点验证。")
        if generated: warnings.append(f"「{label}」有 {generated} 张采用组描述；请检查动作、背景及服装是否准确。")
        summary.append({"id": row["id"], "name": label, "group": group, "images": len(images), "existing_captions": reused, "generated_captions": generated, "sampling_copies": 1})
    singles = [r for r in summary if not r["group"]]
    if settings["balance"] and singles:
        largest = max(r["images"] for r in singles)
        for row in singles: row["sampling_copies"] = min(3, max(1, round(largest / row["images"])))
        if max(r["images"] for r in singles) > 3 * min(r["images"] for r in singles):
            warnings.append("角色样本量差异超过 3 倍；采样最多补到 3 倍，建议补充少样本角色。")
    if not settings["groups"]: warnings.append("尚无同框素材；本次主要学习分别调用角色，同框效果需另行验证。")
    for target in settings["targets"]:
        if len(target["role_ids"]) < 2: raise ValueError("目标组合至少选择两个角色。")
        if not any(set(target["role_ids"]) <= set(m["role_id"] for m in g["members"]) for g in settings["groups"]):
            warnings.append("目标组合「%s」没有对应同框样本，属于待验证组合。" % " + ".join(role_map[rid]["name"] for rid in target["role_ids"]))
    factors = {r["id"]: r["sampling_copies"] for r in summary}
    return {"settings": settings, "entries": entries, "roles": summary, "images": len(entries),
            "training_images": sum(factors[e["group_id"]] for e in entries), "warnings": warnings,
            "validation": validation_prompts(settings)}


def public_scan(value):
    result = scan(value)
    return {k: v for k, v in result.items() if k not in ("entries", "settings")}


def prepare(core, project, settings, resolution, logf=print, report=None):
    """Build a complete new flat dataset, then replace only the managed project directory."""
    from PIL import Image, ImageOps
    check_stop = core.check_stop
    result = scan(settings, check_stop)
    resolution = int(resolution)
    if resolution < 64 or resolution > 4096: raise ValueError("训练分辨率应在 64～4096 范围内。")
    intended_root = Path(core.data_sub("dataset", project)).resolve()
    target = intended_root / "train_character"
    if target.is_symlink(): raise ValueError("项目训练数据目录不能是符号链接。")
    target = target.resolve()
    if not target.is_relative_to(intended_root) or target == intended_root or target.is_symlink():
        raise ValueError("多角色数据集输出目录无效。")
    for entry in result["entries"]:
        if entry["path"].resolve().is_relative_to(target): raise ValueError("原始素材不能选择项目的预处理输出目录。")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".multi_prepare_", dir=target.parent)).resolve()
    factors = {r["id"]: r["sampling_copies"] for r in result["roles"]}
    manifest, written = [], 0
    try:
        for row in result["entries"]:
            check_stop()
            path = row["path"]
            source_stat = path.stat()
            identity = hashlib.sha256(json.dumps([row["group_id"], str(path.resolve()), source_stat.st_size, source_stat.st_mtime_ns, row["caption"], resolution], ensure_ascii=False).encode()).hexdigest()[:24]
            with Image.open(path) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                width, height = image.size
                scale = min(1.0, resolution / max(width, height))
                size = (max(8, int(width * scale) // 8 * 8), max(8, int(height * scale) // 8 * 8))
                if min(width, height) < 64: raise ValueError(f"图片尺寸过小，请检查：{path.name}。")
                image = image.resize(size, Image.Resampling.LANCZOS)
                copies = factors[row["group_id"]]
                for index in range(copies):
                    check_stop()
                    filename = f"multi_{identity}_{index}.png"
                    image.save(stage / filename)
                    (stage / Path(filename).with_suffix(".txt")).write_text(row["caption"], encoding="utf-8")
                    written += 1
                if written % 10 == 0 or len(manifest) + 1 == len(result["entries"]):
                    logf(f"[多角色] 整理素材 {len(manifest) + 1}/{len(result['entries'])}，已写入 {written} 个样本。")
                manifest.append({"name": f"multi_{identity}_0.png", "group_id": row["group_id"],
                                 "roles": row["roles"], "sampling_copies": copies, "original_size": [width, height], "size": list(size)})
        check_stop()
        (stage / "multi_manifest.json").write_text(json.dumps({"images": manifest, "roles": result["roles"]}, ensure_ascii=False, indent=2), encoding="utf-8")
        backup = None
        if target.exists():
            if target.is_symlink() or not target.is_dir(): raise ValueError("项目输出目录不是普通文件夹。")
            backup = target.with_name(".multi_previous_" + uuid.uuid4().hex)
            if not backup.resolve().is_relative_to(intended_root): raise ValueError("数据备份目录无效。")
            target.rename(backup)
        try: stage.rename(target)
        except BaseException:
            if backup is not None: backup.rename(target)
            raise
        if backup:
            # Keep previous prepared labels recoverable; source directories are never modified.
            logf(f"[多角色] 旧预处理数据已保留：{backup}")
        output = Path(core.data_sub("output", project)); output.mkdir(parents=True, exist_ok=True)
        (output / "多角色验证提示词.txt").write_text("\n\n".join(p["prompt"] for p in result["validation"]), encoding="utf-8")
        (output / "多角色使用说明.txt").write_text(
            "多角色 LoRA\n请使用训练时相同底模验证。角色触发词：\n" +
            "\n".join(f'{r["name"]}: {r["trigger"]}' for r in result["settings"]["roles"]) +
            "\n\n先分别验证角色，再检查目标组合及位置互换。重点检查身份、人数、服装归属和位置。\n" +
            "组描述仅是人工提供的标签模板，不代表已检查图片。采样关闭时可在出图工具使用验证提示词。\n" +
            "\n".join(result["warnings"]), encoding="utf-8")
        stats = {"ok": written, "skipped_existing": 0, "unique_images": result["images"], "multi_character": {k: result[k] for k in ("roles", "warnings", "validation")}}
        if report: Path(report).write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        for warning in result["warnings"]: logf("[多角色] 提醒：" + warning)
        logf(f"[多角色] {len(result['settings']['roles'])} 个角色，{result['images']} 张原图，均衡后 {written} 个训练样本；保留完整构图。")
        return stats
    finally:
        if stage.exists():
            if not stage.is_relative_to(intended_root) or not stage.name.startswith(".multi_prepare_"):
                raise ValueError("临时目录清理范围无效。")
            shutil.rmtree(stage)


def export_settings(value):
    settings = normalize(value)
    for row in settings["roles"] + settings["groups"]: row["directory"] = ""
    for row in settings["groups"]: row["reviewed"] = False
    return settings
