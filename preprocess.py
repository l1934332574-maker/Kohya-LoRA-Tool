#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kohya-SS LoRA 数据集预处理脚本（Windows / 通用）

功能：
  1. 批量读取输入图片文件夹，统一缩放：长边缩放到 --size 像素（默认 768），
     宽高向下取整到 8 的倍数（符合 kohya 训练要求，配合 bucket 使用）。
  2. 自动去除黑边：检测并裁剪四周纯黑/近黑边框（例如视频帧上下黑边）。
  3. 自动去除角落水印：对右下角等常见水印区域做启发式检测 + 图像修复
     （inpaint），可用 --no-remove-watermark 关闭。
  4. 两种训练模式（--mode）：
     - style  画风模式（默认，兼容旧版）：每张图生成统一画风 caption（无角色词），
       并自动过滤强人物五官/角色特征标签（filter_character_tags）。
     - character 人物角色模式：完整保留全部标签。优先保留用户自带的 .txt；
       没有时调用 kohya 官方 WD14 打标脚本自动打标；支持 --trigger 触发词自动插入
       每张 txt 第一行；支持 --reg-dir 正则数据集（写进 dataset_config 的 is_reg）。
  5. 可选去重（--dedup，按文件 MD5 跳过重复图片）。
  6. 输出 PNG 与同名 .txt caption 到输出文件夹，并自动生成 kohya 使用的
     数据集配置文件 configs/dataset_config.toml（含 num_repeats / 正则子集）。

用法示例：
  python preprocess.py --input "dataset/raw" --output "dataset/train" --size 1024
  python preprocess.py --input "D:/style" --output "D:/train" --mode style --repeats 5
  python preprocess.py --input "D:/char" --output "D:/train_char" --mode character \
      --trigger "ohwx" --reg-dir "D:/reg" --repeats 15 --dedup
"""



import argparse
import json
import os
import re
import sys
import traceback

# 统一 caption：只描述画风，绝不描述画面中的人物 / 角色。
# 注意：这里没有 trigger word，这是纯风格 LoRA。
DEFAULT_CAPTION = (
    "anime cel-shading, clean thin black outlines, flat color, "
    "simple soft cel shading, tv anime screenshot, limited color palette"
)

# 人物模式兜底 caption（仅在无法运行 WD14 打标、且原图没有自带 .txt 时使用）
DEFAULT_CHARACTER_CAPTION = "1girl, solo"

# WD14 打标模型
WD14_REPO_ID = "SmilingWolf/wd-v1-4-moat-tagger-v2"

# 画风模式要过滤的“强人物特征”标签（精确匹配，下划线等价于空格）
STYLE_FILTERED_TAGS = {
    "1girl", "1boy", "1other", "solo", "2girls", "2boys", "multiple girls",
    "multiple boys", "no humans", "no human", "character", "original character",
    "fan art", "portrait", "face", "facial", "facial expression",
    "eyes", "eyebrows", "eyelashes", "iris", "pupil", "nose", "nostril",
    "mouth", "lips", "teeth", "tongue", "chin", "jaw", "cheeks", "forehead",
    "bangs", "hair", "hair bun", "hair between eyes", "hair ornament",
    "hairclip", "hairband", "hair tie", "hairpins", "hair flower",
    "head", "headgear", "hat", "cap", "beret", "hood", "crown", "tiara",
    "veil", "mask", "scarf", "necklace", "choker", "earrings", "ears",
    "cat ears", "animal ears", "wings", "horns", "halo", "tail",
    "blush", "smile", "grin", "pout", "frown", "expression", "expressions",
    "looking at viewer", "looking away", "looking back", "looking to the side",
    "looking up", "looking down", "closed eyes", "closed mouth", "open mouth",
    "parted lips", "wink", "winking", "tears", "crying", "sad", "angry",
    "happy", "surprised", "serious", "neutral", "scared", "embarrassed",
    "ahegao", "drooling", "sweat", "sweatdrop", "sweating", "drool",
    "glasses", "sunglasses", "eyepatch", "blindfold", "monocle",
    "beard", "mustache", "sideburns", "mole", "freckles", "scar", "tattoo",
    "dress", "skirt", "shirt", "blouse", "jacket", "coat", "hoodie",
    "sweater", "cardigan", "vest", "pants", "jeans", "shorts", "trousers",
    "leggings", "stockings", "thighhighs", "kneesocks", "socks", "boots",
    "shoes", "sneakers", "gloves", "mittens", "tie", "bowtie", "belt",
    "sash", "apron", "collar", "sailor collar", "school uniform", "uniform",
    "armor", "costume", "cosplay", "swimsuit", "bikini", "underwear", "bra",
    "panties", "lingerie", "one-piece", "jumpsuit", "overalls", "kimono",
    "yukata", "qipao", "cape", "cloak", "capelet", "ribbon", "bow",
    "hair ribbon", "hair bow", "headphones", "earbuds", "circlet", "brooch",
    "badge", "name tag", "waistcoat", "sleeves", "puffy sleeves",
    "bare shoulders", "bare arms", "barefoot", "navel", "midriff",
    "breasts", "cleavage", "chest", "abs", "muscles", "pecs",
    "crossed arms", "hand on hip", "hands on hips", "hand in pocket",
    "hands in pockets", "arms behind back", "pointing", "thumbs up",
    "peace sign", "victory sign", "cowboy shot", "upper body", "lower body",
    "full body", "close-up", "profile", "from side", "from behind",
    "from above", "from below", "standing", "sitting", "kneeling", "lying",
    "lying on back", "lying on stomach", "squatting", "crouching",
    "crawling", "walking", "running", "jumping", "dancing", "posing", "pose",
}

# 只要标签里含这些词，就视为“强人物特征标签”并过滤（下划线会先归一化为空格）
STYLE_FILTER_WORDS = (
    r"hair|eyes?|face|facial|eyebrows?|eyelashes?|iris|pupils?|nose|nostrils?|"
    r"lips?|mouth|teeth|tongue|chin|cheeks?|blush|smile|frown|pout|grin|tears?|"
    r"crying|sweat|drool|breasts?|cleavage|chest|muscles?|abs|outfit|costume|"
    r"uniform|dress|skirt|shirts?|blouse|jacket|coat|hoodie|sweater|pants|jeans|"
    r"shorts|trousers|leggings|stockings|thighhighs|socks|boots|shoes|gloves|"
    r"tie|necklace|choker|earrings|hat|cap|crown|tiara|veil|mask|glasses|"
    r"sunglasses|eyepatch|scarf|ribbon|wings|horns|tail|bangs|ponytail|"
    r"twintails|braid|hime cut|mole|freckles|scar|tattoo|beard|mustache"
)
_STYLE_FILTER_RE = re.compile(r"\b(" + STYLE_FILTER_WORDS + r")\b", re.IGNORECASE)


def _norm_tag(tag: str) -> str:
    """标签归一化：下划线/连字符转空格、去首尾空白、小写。"""
    return re.sub(r"[_\-]+", " ", tag.strip()).strip().lower()


def filter_character_tags(text: str) -> str:
    """画风模式：过滤 caption 中的强人物五官/角色特征标签，降低人物主体权重。

    - 精确命中的强人物标签（STYLE_FILTERED_TAGS）直接删除；
    - 标签里含五官/服装/身份词（STYLE_FILTER_WORDS）的也删除；
    - 保留笔触、色彩、光影、构图、画风相关描述。
    """
    if not text:
        return ""
    tags = [t for t in text.split(",") if t.strip()]
    kept = []
    for t in tags:
        n = _norm_tag(t)
        if not n:
            continue
        if n in STYLE_FILTERED_TAGS:
            continue
        if _STYLE_FILTER_RE.search(n):
            continue
        kept.append(t.strip())
    return ", ".join(kept)


def insert_trigger(caption: str, trigger: str) -> str:
    """人物模式：把 trigger 触发词插入 caption 第一行。

    - trigger 为空 -> 原样返回；
    - caption 单行 -> 拼成 "trigger, 原标签"；
    - caption 多行 -> 在文件最前面新增一行 trigger；
    - 第一行已包含 trigger（按词匹配）-> 不重复插入。
    """
    trigger = (trigger or "").strip()
    if not trigger:
        return caption
    text = (caption or "").strip()
    if not text:
        return trigger
    first = text.splitlines()[0].strip()
    if re.search(r"(^|[\s,])" + re.escape(trigger) + r"([\s,]|$)", first, re.IGNORECASE):
        return text
    if "\n" in text:
        return trigger + "\n" + text
    return trigger + ", " + text


def _md5_file(path):
    import hashlib

    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_wd14_tagger():
    """在 kohya_ss（含 sd-scripts）里查找官方 WD14 打标脚本。"""
    cands = []
    kit = os.path.dirname(os.path.abspath(__file__))
    for base in (kit, os.path.expanduser("~")):
        cands.append(os.path.join(base, "kohya_ss", "finetune", "tag_images_by_wd14_tagger.py"))
        cands.append(os.path.join(base, "kohya_ss", "sd-scripts", "finetune", "tag_images_by_wd14_tagger.py"))
    kdf = os.path.join(kit, "kohya_dir.txt")
    if os.path.isfile(kdf):
        try:
            with open(kdf, "r", encoding="utf-8") as f:
                kd = f.read().strip().lstrip("\ufeff").strip()
            cands.append(os.path.join(kd, "finetune", "tag_images_by_wd14_tagger.py"))
            cands.append(os.path.join(kd, "sd-scripts", "finetune", "tag_images_by_wd14_tagger.py"))
        except Exception:
            pass
    for p in cands:
        if os.path.isfile(p):
            return p
    return None


def _run_cmd(cmd, cwd=None, env=None, logf=print):
    """运行命令并把 stdout/stderr 实时交给 logf。返回退出码。"""
    import subprocess

    logf("$ " + " ".join(str(x) for x in cmd))
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
    except Exception as e:
        logf(f"[ERROR] 无法启动进程: {e}")
        return 1
    for line in proc.stdout:
        logf(line.rstrip("\n").rstrip("\r"))
    proc.wait()
    return proc.returncode


def _system_proxy():
    """读取 Windows 系统代理设置，返回代理地址或 None（供 WD14 模型下载使用）。"""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        try:
            enable, _ = winreg.QueryValueEx(k, "ProxyEnable")
            server, _ = winreg.QueryValueEx(k, "ProxyServer")
        finally:
            winreg.CloseKey(k)
        if enable and server:
            return server if "://" in server else "http://" + server
    except Exception:
        pass
    return None


def run_wd14_tagger(output_dir, logf=print, script=None, batch_size=4, thresh=0.35):
    """调用 kohya 官方 WD14 打标脚本，为 output_dir 里每张图生成 .txt 标签。

    返回是否成功。失败时由调用方做兜底处理，不会中断整体预处理。
    """
    script = script or find_wd14_tagger()
    if not script:
        logf("[WD14] 未找到 kohya 官方打标脚本，跳过自动打标")
        return False
    logf(f"[WD14] 使用官方打标脚本: {script}")
    cmd = [
        sys.executable, script, output_dir,
        "--onnx", "--repo_id", WD14_REPO_ID,
        "--batch_size", str(batch_size), "--thresh", str(thresh),
        "--remove_underscore", "--caption_extension", ".txt",
    ]
    env = dict(os.environ)
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    _px = _system_proxy()
    if _px:
        env.setdefault("HTTP_PROXY", _px)
        env.setdefault("HTTPS_PROXY", _px)
    try:
        rc = _run_cmd(cmd, env=env, logf=logf)
        if rc == 0:
            logf("[WD14] 自动打标完成")
            return True
        logf(f"[WD14] 打标脚本退出码 {rc}")
    except Exception as e:
        logf(f"[WD14] 打标失败: {e}")
    return False


def _fill_missing_captions(output_dir, fallback, logf=print):
    """给输出目录里没有 .txt 的图片补一份兜底 caption。"""
    n = 0
    for f in sorted(os.listdir(output_dir)):
        if os.path.splitext(f)[1].lower() not in IMAGE_EXTS:
            continue
        stem = os.path.splitext(f)[0]
        txt = os.path.join(output_dir, stem + ".txt")
        if not os.path.isfile(txt):
            with open(txt, "w", encoding="utf-8") as fh:
                fh.write(fallback)
            n += 1
    if n:
        logf(f"[INFO] 为 {n} 张没有标签的图片补写了兜底 caption（未找到 WD14 打标结果）")


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}



def normalize_caption(text: str) -> str:
    """把不常见连字符（如 U+2011）统一成普通连字符，压缩多余空白。"""
    text = text.replace("\u2011", "-").replace("\u2010", "-").replace("\u2012", "-")
    text = text.replace("\u2013", "-").replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_image(path):
    """读取图片：EXIF 方向校正，透明通道平铺到白底，转 RGB。"""
    from PIL import Image, ImageOps

    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "PA") or (
            im.mode == "P" and "transparency" in im.info
        ):
            rgba = im.convert("RGBA")
            bg = Image.new("RGB", rgba.size, (255, 255, 255))
            bg.paste(rgba, mask=rgba.split()[-1])
            im = bg
        else:
            im = im.convert("RGB")
        return im


def crop_black_borders(img, threshold=12, margin=2):
    """裁剪四周纯黑/近黑边框。返回 (新图, 是否裁剪)。"""
    import numpy as np

    gray = np.asarray(img.convert("L"))
    mask = gray > threshold
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not rows.any() or not cols.any():
        return img, False
    ys = np.where(rows)[0]
    xs = np.where(cols)[0]
    y0, y1 = int(ys[0]), int(ys[-1])
    x0, x1 = int(xs[0]), int(xs[-1])
    y0 = max(0, y0 - margin)
    x0 = max(0, x0 - margin)
    y1 = min(img.height - 1, y1 + margin)
    x1 = min(img.width - 1, x1 + margin)
    box = (x0, y0, x1 + 1, y1 + 1)
    return img.crop(box), True


def _corner_rects(width, height, corner, w_frac, h_frac):
    """按 corner 返回一个或多个候选水印区域 (x0,y0,x1,y1)。"""
    cw = max(24, int(width * w_frac))
    ch = max(24, int(height * h_frac))
    rects = []
    if corner in ("br", "all"):
        rects.append((width - cw, height - ch, width, height))
    if corner in ("bl", "all"):
        rects.append((0, height - ch, cw, height))
    if corner in ("tr", "all"):
        rects.append((width - cw, 0, width, ch))
    if corner in ("tl", "all"):
        rects.append((0, 0, cw, ch))
    return rects


def remove_corner_watermark(img, corner="br", w_frac=0.22, h_frac=0.12,
                            force=False, contrast_threshold=45):
    """启发式去除角落水印：检测到高对比文字则用 inpaint 修复。

    返回 (新图, 是否检测到并处理)。
    需要 opencv-python（kohya_ss 依赖中已包含）；缺失时自动跳过。
    """
    try:
        import cv2
        import numpy as np
    except Exception:
        return img, False

    w, h = img.size
    arr = np.array(img)  # copy: PIL arrays are read-only
    gray_all = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    global_std = float(gray_all.std())
    handled = False

    for (x0, y0, x1, y1) in _corner_rects(w, h, corner, w_frac, h_frac):
        region = arr[y0:y1, x0:x1]
        gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
        med = float(np.median(gray))
        diff = np.abs(gray.astype(np.int16) - int(med)).astype(np.uint8)
        mask = (diff > contrast_threshold).astype(np.uint8) * 255

        corner_std = float(gray.std())
        text_ratio = float(mask.sum()) / max(1, mask.size)
        detected = force or (
            corner_std > max(28.0, global_std * 1.6) and text_ratio > 0.004
        )
        if not detected:
            continue

        kernel = np.ones((3, 3), np.uint8)
        mask_d = cv2.dilate(mask, kernel, iterations=2)
        repaired = cv2.inpaint(region, mask_d, 3, cv2.INPAINT_TELEA)
        arr[y0:y1, x0:x1] = repaired
        handled = True

    if handled:
        from PIL import Image

        return Image.fromarray(arr), True
    return img, False


def resize_to_multiple(img, target=768, multiple=8, allow_upscale=True):
    """长边缩放到 target，宽高取整到 multiple 的倍数。"""
    w, h = img.size
    scale = target / float(max(w, h))
    if not allow_upscale and scale > 1.0:
        scale = 1.0
    nw = max(multiple, int(round(w * scale / multiple)) * multiple)
    nh = max(multiple, int(round(h * scale / multiple)) * multiple)
    return img.resize((nw, nh), resample=3)  # 3 = LANCZOS


def square_center_crop(img):
    """居中裁剪为正方形（小白自动流水线用）。"""
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def is_blurry(img, threshold):
    """用拉普拉斯方差判断是否模糊；方差 < threshold 视为模糊。"""
    try:
        import cv2
        import numpy as np
        gray = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2GRAY)
        var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        return var < threshold
    except Exception:
        return False


def write_dataset_config(output_dir, config_path, resolution=768, batch_size=1,
                         num_repeats=1, reg_dir=None, keep_tokens=0):
    """为 kohya sd-scripts 生成数据集配置 TOML（绝对路径）。

    - num_repeats：训练图片重复次数；
    - reg_dir：正则数据集文件夹（非空时额外写一个 is_reg = true 的 [[datasets]]）；
    - keep_tokens：保留在 caption 开头的 token 数（人物模式保护 trigger，通常=1）。
    """
    image_dir = os.path.abspath(output_dir).replace("\\", "/")
    min_bucket = 512 if resolution >= 1024 else 256
    max_bucket = 2048 if resolution >= 1024 else 1024
    lines = [
        "# Auto-generated by preprocess.py (LoRA dataset config).",
        "[general]",
        'caption_extension = ".txt"',
        "shuffle_caption = false",
        f"keep_tokens = {int(keep_tokens)}",
        "",
        "[[datasets]]",
        f"resolution = {resolution}",
        f"batch_size = {batch_size}",
        "enable_bucket = true",
        "bucket_no_upscale = true",
        "bucket_reso_steps = 64",
        f"min_bucket_reso = {min_bucket}",
        f"max_bucket_reso = {max_bucket}",
        "",
        "  [[datasets.subsets]]",
        f'  image_dir = "{image_dir}"',
        f"  num_repeats = {int(num_repeats)}",
    ]
    if reg_dir and os.path.isdir(reg_dir):
        reg = os.path.abspath(reg_dir).replace("\\", "/")
        lines += [
            "",
            "[[datasets]]",
            f"resolution = {resolution}",
            f"batch_size = {batch_size}",
            "is_reg = true",
            "enable_bucket = true",
            "bucket_no_upscale = true",
            "bucket_reso_steps = 64",
            f"min_bucket_reso = {min_bucket}",
            f"max_bucket_reso = {max_bucket}",
            "",
            "  [[datasets.subsets]]",
            f'  image_dir = "{reg}"',
            "  num_repeats = 1",
        ]
    toml_text = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(toml_text)
    return image_dir


def _force_utf8_stdio():
    """强制 stdout/stderr 使用 UTF-8，保证中文日志在 GUI/终端里不乱码。"""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main():
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(

        description="Kohya-SS LoRA 数据集预处理：缩放 + 去黑边/水印 + 画风过滤 / 人物WD14打标 + 触发词 + 正则数据集"
    )
    parser.add_argument("--input", required=True, help="原始图片文件夹")
    parser.add_argument("--output", default="./dataset/train", help="输出文件夹（默认 ./dataset/train）")
    parser.add_argument("--size", type=int, default=768, help="长边目标像素（默认 768）")
    parser.add_argument("--multiple", type=int, default=8, help="宽高取整倍数（默认 8）")
    parser.add_argument("--black-threshold", type=int, default=12, help="黑边判定亮度阈值（默认 12）")
    parser.add_argument("--margin", type=int, default=2, help="黑边裁剪后保留的外边距像素（默认 2）")
    parser.add_argument("--no-remove-black-borders", action="store_true", help="不去除黑边")
    parser.add_argument("--no-remove-watermark", action="store_true", help="不去除水印")
    parser.add_argument("--wm-corner", default="br",
                        choices=["br", "bl", "tr", "tl", "all"],
                        help="水印检测区域（默认 br=右下角）")
    parser.add_argument("--wm-w", type=float, default=0.22, help="水印区域宽度占比（默认 0.22）")
    parser.add_argument("--wm-h", type=float, default=0.12, help="水印区域高度占比（默认 0.12）")
    parser.add_argument("--wm-force", action="store_true",
                        help="强制修复水印区域（即使未检测到水印也执行）")
    parser.add_argument("--caption", default=DEFAULT_CAPTION, help="统一 caption 文本（画风模式）")
    parser.add_argument("--no-caption", action="store_true", help="不生成 caption 文件")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的输出图片")
    parser.add_argument("--no-upscale", action="store_true", help="小图不放大（只缩小）")
    parser.add_argument("--no-write-dataset-config", action="store_true",
                        help="不生成 dataset_config.toml")
    parser.add_argument("--config-path", default=None,
                        help="dataset_config.toml 输出路径（默认 <kit>/configs/dataset_config.toml）")
    parser.add_argument("--mode", choices=["style", "character"], default="style",
                        help="训练模式：style=画风（默认，过滤人物标签）/ character=人物（保留全部标签）")
    parser.add_argument("--trigger", default="", help="人物模式 trigger 触发词（插入每张 txt 第一行）")
    parser.add_argument("--reg-dir", default=None, help="人物模式正则数据集文件夹（写进 dataset_config 的 is_reg）")
    parser.add_argument("--repeats", type=int, default=1, help="训练图片重复次数 num_repeats（默认 1）")
    parser.add_argument("--keep-tokens", type=int, default=0,
                        help="caption 开头保留 token 数（人物模式建议 1 以保护 trigger）")
    parser.add_argument("--dedup", action="store_true", help="按 MD5 跳过重复图片")
    parser.add_argument("--no-wd14", action="store_true", help="人物模式不自动调用 WD14 打标")
    parser.add_argument("--min-size", type=int, default=0,
                        help="过滤过小图片：长边小于该像素则跳过（0=不过滤）")
    parser.add_argument("--blur-threshold", type=float, default=0,
                        help="过滤模糊图片：拉普拉斯方差小于该值则跳过（0=不过滤）")
    parser.add_argument("--square-crop", action="store_true", help="居中正方形裁剪后再缩放")
    parser.add_argument("--report", default=None,
                        help="JSON 报告输出路径（含 ok/重复/模糊/过小/损坏 计数）")
    args = parser.parse_args()

    # ---- 依赖检查 ----
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        print("[ERROR] 缺少 Pillow。请先运行 01_一键安装_Setup.bat，")
        print("        或用 kohya_ss 的 venv python 运行本脚本：")
        print('        "kohya_ss\\venv\\Scripts\\python.exe" preprocess.py ...')
        sys.exit(1)
    try:
        import numpy  # noqa: F401
    except Exception:
        print("[ERROR] 缺少 numpy。请先运行 01_一键安装_Setup.bat 安装依赖。")
        sys.exit(1)

    input_dir = os.path.abspath(args.input)
    output_dir = os.path.abspath(args.output)
    if not os.path.isdir(input_dir):
        print(f"[ERROR] 输入文件夹不存在: {input_dir}")
        sys.exit(1)
    os.makedirs(output_dir, exist_ok=True)
    if os.path.abspath(input_dir) == output_dir:
        print("[WARN] 输入与输出是同一文件夹，将在原位置覆盖处理。")

    mode = args.mode
    trigger = (args.trigger or "").strip()
    style_caption = normalize_caption(args.caption)

    files = sorted(
        f for f in os.listdir(input_dir)
        if os.path.splitext(f)[1].lower() in IMAGE_EXTS
    )
    if not files:
        print(f"[WARN] 输入文件夹里没有找到图片（支持 jpg/png/webp/bmp/tif/gif）。")
        print(f"       {input_dir}")
        return

    print(f"[INFO] 找到 {len(files)} 张图片")
    print(f"[INFO] 缩放目标: 长边 {args.size}px（取整到 {args.multiple} 的倍数）")
    print(f"[INFO] 去黑边: {'开' if not args.no_remove_black_borders else '关'}")
    print(f"[INFO] 去水印: {'开(' + args.wm_corner + ')' if not args.no_remove_watermark else '关'}")
    if args.dedup:
        print("[INFO] 去重: 开（MD5 完全相同视为重复）")
    if args.square_crop:
        print(f"[INFO] 正方形裁剪: 开（居中裁剪为正方形）")
    if args.min_size:
        print(f"[INFO] 过小过滤: 开（长边 < {args.min_size}px 跳过）")
    if args.blur_threshold:
        print(f"[INFO] 模糊过滤: 开（清晰度阈值 {args.blur_threshold}）")
    if mode == "style":
        print(f"[INFO] 模式: 画风 LoRA（过滤强人物五官/角色标签）")
        print(f"[INFO] 统一 caption: {style_caption}")
    else:
        print(f"[INFO] 模式: 人物角色 LoRA（完整保留标签）")
        print(f"[INFO] trigger 触发词: {trigger if trigger else '（未填写）'}")
        if args.reg_dir:
            print(f"[INFO] 正则数据集: {os.path.abspath(args.reg_dir)}")
        print(f"[INFO] 重复次数 num_repeats: {args.repeats}")
        if not args.no_wd14 and find_wd14_tagger():
            print(f"[INFO] WD14 自动打标: 开（找不到 .txt 的图片会自动打标）")
        else:
            print("[INFO] WD14 自动打标: 关（保留原图自带 .txt 或使用兜底 caption）")
    print()

    ok = skipped = failed = 0
    dups = corrupt = too_small = blurry = 0
    cropped = 0
    watermarked = 0
    seen_hashes = {}
    user_captions = {}  # stem -> 原图自带 .txt 内容（人物模式优先保留）
    for name in files:
        stem = os.path.splitext(name)[0]
        raw_img = os.path.join(input_dir, name)
        out_img = os.path.join(output_dir, stem + ".png")
        out_txt = os.path.join(output_dir, stem + ".txt")
        if os.path.exists(out_img) and not args.overwrite:
            skipped += 1
            continue
        if args.dedup:
            h = _md5_file(raw_img)
            if h in seen_hashes:
                dups += 1
                print(f"  [DUP] {name} 与 {seen_hashes[h]} 重复，已跳过")
                continue
            seen_hashes[h] = name
        try:
            img = load_image(raw_img)
        except Exception as e:
            corrupt += 1
            print(f"  [损坏] {name}: {e}")
            if os.environ.get("PREPROCESS_DEBUG"):
                traceback.print_exc()
            continue
        if args.min_size and max(img.size) < args.min_size:
            too_small += 1
            print(f"  [过小] {name}（{img.width}x{img.height}，长边 < {args.min_size}px）已跳过")
            continue
        if args.blur_threshold and args.blur_threshold > 0:
            if is_blurry(img, args.blur_threshold):
                blurry += 1
                print(f"  [模糊] {name} 清晰度不足，已跳过")
                continue
        try:
            if not args.no_remove_watermark:
                img, wm = remove_corner_watermark(
                    img,
                    corner=args.wm_corner,
                    w_frac=args.wm_w,
                    h_frac=args.wm_h,
                    force=args.wm_force,
                )
                if wm:
                    watermarked += 1

            if not args.no_remove_black_borders:
                img, c = crop_black_borders(img, threshold=args.black_threshold, margin=args.margin)
                if c:
                    cropped += 1

            if args.square_crop:
                img = square_center_crop(img)
            img = resize_to_multiple(
                img, target=args.size, multiple=args.multiple,
                allow_upscale=not args.no_upscale,
            )
            img.save(out_img, format="PNG", optimize=True)

            if not args.no_caption:
                raw_txt = os.path.join(input_dir, stem + ".txt")
                if mode == "style":
                    # 画风模式：优先用原图自带 .txt（过滤人物标签），否则统一画风 caption
                    cap = ""
                    if os.path.isfile(raw_txt):
                        try:
                            with open(raw_txt, "r", encoding="utf-8") as f:
                                cap = f.read()
                        except Exception:
                            cap = ""
                    cap = filter_character_tags(cap if cap.strip() else style_caption)
                    with open(out_txt, "w", encoding="utf-8") as f:
                        f.write(cap)
                else:
                    # 人物模式：先记录原图自带 .txt，打标/兜底之后统一写入
                    if os.path.isfile(raw_txt):
                        try:
                            with open(raw_txt, "r", encoding="utf-8") as f:
                                user_captions[stem] = f.read()
                        except Exception:
                            user_captions[stem] = ""

            ok += 1
            print(f"  [OK] {name} -> {os.path.basename(out_img)} ({img.width}x{img.height})")
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
            if os.environ.get("PREPROCESS_DEBUG"):
                traceback.print_exc()

    # ---- 人物模式：WD14 打标 / 兜底 / 还原自带标签 / 插入 trigger ----
    if mode == "character" and not args.no_caption and ok:
        tagger = find_wd14_tagger()
        use_wd14 = (not args.no_wd14) and bool(tagger)
        if use_wd14:
            wd14_ok = run_wd14_tagger(output_dir)
            if not wd14_ok:
                _fill_missing_captions(output_dir, DEFAULT_CHARACTER_CAPTION)
        else:
            _fill_missing_captions(output_dir, DEFAULT_CHARACTER_CAPTION)
            if not tagger:
                print("[WARN] 未找到 kohya 官方 WD14 打标脚本，缺少标签的图片使用了兜底 caption。")
        # 还原原图自带的 .txt（完整保留用户标签）
        for stem, cap in user_captions.items():
            if cap.strip():
                with open(os.path.join(output_dir, stem + ".txt"), "w", encoding="utf-8") as f:
                    f.write(cap)
        # 插入 trigger 到每张 txt 第一行
        if trigger:
            n_trig = 0
            for f in sorted(os.listdir(output_dir)):
                if os.path.splitext(f)[1].lower() not in IMAGE_EXTS:
                    continue
                t = os.path.join(output_dir, os.path.splitext(f)[0] + ".txt")
                if os.path.isfile(t):
                    with open(t, "r", encoding="utf-8") as fh:
                        cur = fh.read()
                    with open(t, "w", encoding="utf-8") as fh:
                        fh.write(insert_trigger(cur, trigger))
                    n_trig += 1
            print(f"[INFO] 已把 trigger「{trigger}」插入 {n_trig} 张图片的标签第一行")

    print()
    print("=" * 60)
    print(f"  处理成功: {ok}  |  跳过(已存在): {skipped}  |  重复: {dups}")
    print(f"  损坏: {corrupt}  |  过小: {too_small}  |  模糊: {blurry}  |  失败: {failed}")
    print(f"  去除黑边: {cropped}  |  去除水印: {watermarked}")
    print(f"  输出目录: {output_dir}")
    if ok and not args.no_caption:
        if mode == "style":
            print("  每张图已生成同名 .txt caption（画风描述，已过滤人物五官/角色标签）")
        else:
            print("  每张图已生成同名 .txt caption（人物标签完整保留" +
                  ("，trigger 已插入" if trigger else "") + "）")
    print("=" * 60)

    if args.report:
        try:
            report = {
                "input_dir": input_dir,
                "output_dir": output_dir,
                "mode": mode,
                "total": len(files),
                "ok": ok,
                "skipped_existing": skipped,
                "duplicates": dups,
                "corrupt": corrupt,
                "too_small": too_small,
                "blurry": blurry,
                "failed": failed,
            }
            with open(args.report, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(f"[INFO] 已生成过滤报告: {args.report}")
        except Exception as e:
            print(f"[WARN] 写报告失败: {e}")

    if ok and not args.no_write_dataset_config:
        config_path = args.config_path
        if config_path is None:
            kit_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(kit_dir, "configs", "dataset_config.toml")
        image_dir = write_dataset_config(
            output_dir, config_path, resolution=args.size,
            num_repeats=args.repeats, reg_dir=args.reg_dir,
            keep_tokens=args.keep_tokens,
        )
        print(f"[INFO] 已生成数据集配置: {config_path}")
        print(f"[INFO]  image_dir = {image_dir}")

if __name__ == "__main__":
    main()

