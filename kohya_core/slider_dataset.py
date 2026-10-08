"""Matched pairs for sliders. Source files are never written or filtered individually."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageOps

EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _images(folder):
    root = Path(folder).resolve()
    if not folder or not root.is_dir(): raise ValueError("请选择两个有效的图片文件夹。")
    # Explicit leaf folders only: no traversal through junctions or symlinks.
    paths = sorted((p for p in root.iterdir() if p.is_file() and not p.is_symlink() and p.suffix.lower() in EXTS), key=lambda p: p.name.casefold())
    if len(paths) > 1000: raise ValueError("每边最多 1000 张图片，请选择具体的图片文件夹。")
    return root, paths


def scan(settings, check_stop=lambda: None):
    roots, files = {}, {}
    for side in ("positive", "negative"):
        roots[side], files[side] = _images(settings[side + "_dir"])
    if roots["positive"] == roots["negative"]: raise ValueError("两个方向不能选择同一文件夹。")
    mappings = {side: {p.name.casefold(): p for p in files[side]} for side in roots}
    warnings, rows = [], []
    candidates = settings["pairs"]
    if not candidates:
        def stems(paths):
            groups = {}
            for p in paths: groups.setdefault(p.stem.casefold(), []).append(p)
            return groups
        pos, neg = stems(files["positive"]), stems(files["negative"])
        for stem in sorted(pos.keys() & neg.keys()):
            if len(pos[stem]) != 1 or len(neg[stem]) != 1:
                raise ValueError("同名图片存在多个扩展名，无法自动配对：%s。请在配对表中手动指定。" % stem)
            rows.append({"positive": pos[stem][0].name, "negative": neg[stem][0].name})
        candidates, rows = rows, []
    used = {side: set() for side in roots}
    for pair in candidates:
        check_stop()
        selected = {}
        for side in roots:
            path = mappings[side].get(pair[side].casefold())
            if path is None: raise ValueError("图片对文件不存在或不在所选文件夹内：%s" % pair[side])
            if path.name.casefold() in used[side]: raise ValueError("一张图片不能重复配成多对：%s" % path.name)
            used[side].add(path.name.casefold())
            selected[side] = path
        sizes, identities = {}, {}
        for side, path in selected.items():
            try:
                with Image.open(path) as image:
                    image.load()
                    sizes[side] = ImageOps.exif_transpose(image).size
                identities[side] = _hash(path, check_stop)
            except (OSError, ValueError) as exc: raise ValueError("图片对无法读取：%s；请更换这一整对。" % path.name) from exc
        if identities["positive"] == identities["negative"]: raise ValueError("这对图片完全相同，无法学习变化：%s" % pair["positive"])
        ratios = [w / h for w, h in sizes.values()]
        if abs(ratios[0] / ratios[1] - 1) > .02:
            raise ValueError("图片对比例差异超过 2%%：%s。请先对齐构图，避免训练到裁剪变化。" % pair["positive"])
        if any(min(size) < 256 for size in sizes.values()): warnings.append("%s：图片尺寸较小，将保留并缩放，放大不会增加真实细节。" % pair["positive"])
        rows.append({**pair, "identity": identities})
    if not rows: raise ValueError("没有配对成功的图片；请让两边使用相同文件名，或手动指定配对。")
    unpaired = sum(len(files[side]) - len(used[side]) for side in roots)
    if unpaired: warnings.append("%d 张未配对图片不会参与本次训练；原文件保留。" % unpaired)
    # Keep exact byte duplicates / shared endpoints in the same split. Renamed copies are not new validation data.
    parents = list(range(len(rows)))
    def group(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index
    seen = {}
    for i, row in enumerate(rows):
        for identity in row["identity"].values():
            if identity in seen: parents[group(i)] = group(seen[identity])
            else: seen[identity] = i
    groups = {}
    for i, row in enumerate(rows): groups.setdefault(group(i), []).append(row)
    def order(items):
        identities = sorted(json.dumps(row["identity"], sort_keys=True) for row in items)
        return hashlib.sha256((str(settings["seed"]) + json.dumps(identities)).encode()).hexdigest()
    ordered = sorted(groups.values(), key=order)
    hold_count = max(1, len(ordered) // 5) if len(ordered) >= 6 else 0
    holdout = [row for items in ordered[:hold_count] for row in items]
    train = [row for items in ordered[hold_count:] for row in items]
    if len(groups) < len(rows): warnings.append("发现内容重复或共用端点的图片对：保留材料，但分配到同一集合，避免训练 / 验证重复。")
    if not holdout: warnings.append("少于 6 组独立图片对：本次不留出图片验证集；试训结果不足以判断泛化能力。")
    return dict(pairs=rows, train=train, holdout=holdout, independent_groups=len(groups), warnings=warnings,
                positive_files=[p.name for p in files["positive"]], negative_files=[p.name for p in files["negative"]])


def _hash(path, check_stop):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            check_stop(); value.update(chunk)
    return value.hexdigest()


def materialize(settings, scanned, cache, check_stop):
    # Hash both bytes, crop, caption and split. A new pair, caption or resolution gets a new immutable cache.
    identity = dict(pairs=scanned["pairs"], train=scanned["train"], resolution=settings["resolution"],
                    caption=settings["neutral"], crop="synchronized-center-v1")
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    root = Path(cache) / fingerprint
    pos, neg = root / "positive", root / "negative"
    for directory in (pos, neg): directory.mkdir(parents=True, exist_ok=True)
    for split, pairs in (("train", scanned["train"]), ("holdout", scanned["holdout"])):
        targets = {"positive": pos, "negative": neg} if split == "train" else {
            side: root / ("holdout_" + side) for side in ("positive", "negative")}
        for directory in targets.values(): directory.mkdir(parents=True, exist_ok=True)
        for i, pair in enumerate(pairs):
            check_stop()
            filename = "%05d.png" % i
            for side, dest in targets.items():
                source = Path(settings[side + "_dir"]) / pair[side]
                if _hash(source, check_stop) != pair["identity"][side]: raise ValueError("检查后图片已变化，请重新检查：" + source.name)
                with Image.open(source) as image:
                    image = ImageOps.exif_transpose(image).convert("RGB")
                    image = ImageOps.fit(image, (settings["resolution"], settings["resolution"]), Image.Resampling.LANCZOS, centering=(.5, .5))
                    target = dest / filename
                    staged = target.with_suffix(".tmp.png")
                    image.save(staged); staged.replace(target)
                (dest / ("%05d.txt" % i)).write_text(settings["neutral"] + "\n", encoding="utf-8")
    (root / "pairs.json").write_text(json.dumps(identity, ensure_ascii=False, indent=2), encoding="utf-8")
    return root, pos, neg
