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
import shutil
import sys
import traceback
import subprocess

# 全局隐藏子进程窗口：GUI 宿主无控制台，直接 subprocess 会弹黑色 cmd 窗口，
# 这里统一加 CREATE_NO_WINDOW（0x08000000），WD14 打标等子进程全部后台静默运行。
if os.name == "nt":
    _orig_popen = subprocess.Popen

    def _popen_no_window(*args, **kwargs):
        kwargs.setdefault("creationflags", 0x08000000)
        return _orig_popen(*args, **kwargs)

    subprocess.Popen = _popen_no_window

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


# ============================================================
# 人物 LoRA 自动强绑定（trigger + 100% 一致特征 → 固定前缀）
# 2026-08-25：让「一个触发词绑定一个人物」。
# 原理：统计训练集全部 caption，找出 100% 出现的身份特征词（发色/瞳色/发型等），
#       把 trigger + 这些特征拼成固定前缀写到每张标签开头，并让 keep_tokens 覆盖整组，
#       kohya 打乱/丢弃标签时不会动到前缀 → 模型把 trigger 与人物特征强绑定。
# 支持 ||| 手动分隔符：||| 前为固定区（用户自定义），||| 后为可动区。
# ============================================================

# 通用/构图/画质类标签：出现在 100% 也不算人物身份特征，不参与自动前缀
BIND_GENERIC_TAGS = frozenset({
    "1girl", "1boy", "1other", "2girls", "2boys", "3girls", "solo",
    "multiple girls", "multiple boys", "no humans", "no human",
    "character", "original character", "fan art",
    "looking at viewer", "looking away", "looking back", "looking to the side",
    "upper body", "lower body", "full body", "portrait", "close-up",
    "cowboy shot", "medium shot", "long shot", "from above", "from below",
    "from side", "from behind", "profile", "pov",
    "masterpiece", "best quality", "high quality", "highres", "absurdres",
    "new", "newest", "old", "oldest", "very aesthetic",
    "white background", "simple background", "blurry background",
    "outdoors", "indoors", "depth of field",
})


def _split_caption_tags(text):
    """拆 caption 为标签列表（兼容中英文逗号、换行）。"""
    if not text:
        return []
    return [t.strip() for t in re.split(r"[,，\n]", text) if t.strip()]


def analyze_caption_features(train_dir, trigger=""):
    """分析训练集标签：统计每个标签的出现率。

    返回 dict:
      total        : 有效 caption 数量
      consistent   : 100% 出现的标签（排除 trigger 与通用标签，按首次出现顺序）
      near         : [(原标签, 出现次数)] 出现率 50%~99% 的标签（用于一致性警告）
      has_separator: 是否存在 ||| 手动固定区
    """
    from collections import Counter
    cnt = Counter()
    first_seen = {}
    trig = set(_norm_tag(t) for t in _split_caption_tags(trigger))
    total = 0
    has_sep = False
    if not os.path.isdir(train_dir):
        return {"total": 0, "consistent": [], "near": [], "has_separator": False}
    for root, _dirs, files in os.walk(train_dir):
        for fn in files:
            if not fn.lower().endswith(".txt"):
                continue
            fp = os.path.join(root, fn)
            try:
                with open(fp, "r", encoding="utf-8-sig") as f:
                    text = f.read()
            except Exception:
                continue
            if "|||" in text:
                has_sep = True
            tags = _split_caption_tags(text)
            if not tags:
                continue
            total += 1
            for t in tags:
                n = _norm_tag(t)
                if not n:
                    continue
                if n not in first_seen:
                    first_seen[n] = t.strip()
                cnt[n] += 1
    consistent = []
    for n, orig in first_seen.items():
        if n in trig or n in BIND_GENERIC_TAGS:
            continue
        if cnt[n] == total:
            consistent.append(orig)
    near = [(first_seen[n], cnt[n]) for n in first_seen
            if n not in trig and n not in BIND_GENERIC_TAGS
            and total > 0 and total * 0.5 <= cnt[n] < total]
    near.sort(key=lambda x: -x[1])
    return {"total": total, "consistent": consistent, "near": near[:10],
            "has_separator": has_sep}


def apply_strong_binding(train_dir, trigger, logf=print):
    """人物 LoRA 自动强绑定：把 trigger + 100% 一致身份特征拼成固定前缀。

    - 无 trigger / 无标签 -> 返回 (0, [])（不强绑）。
    - 存在 ||| 分隔符 -> 手动模式：||| 前为固定区（保持用户顺序），||| 后为可动区；
      keep_tokens = 固定区标签数；写回时去掉 |||。
    - 否则自动模式：前缀 = trigger + 100% 一致特征；重写每张 caption 使前缀在开头；
      keep_tokens = 前缀标签数（幂等：已以完整前缀开头则跳过）。
    - 返回 (keep_tokens, warnings)。
    """
    trigger = (trigger or "").strip()
    if not trigger or not os.path.isdir(train_dir):
        return 0, []
    info = analyze_caption_features(train_dir, trigger)
    total = info["total"]
    if total == 0:
        return 0, []
    warnings = []
    for tag, c in info["near"]:
        warnings.append(f"特征「{tag}」只在 {c}/{total} 张出现（{c/total:.0%}），"
                        "人物一致性不足，建议统一训练集特征或补齐图片后再训")
    trig_tags = _split_caption_tags(trigger)
    trig_norm = [_norm_tag(t) for t in trig_tags]

    if info["has_separator"]:
        # ---- 手动固定区模式（|||）----
        max_keep = 0
        for root, _dirs, files in os.walk(train_dir):
            for fn in files:
                if not fn.lower().endswith(".txt"):
                    continue
                fp = os.path.join(root, fn)
                try:
                    with open(fp, "r", encoding="utf-8-sig") as f:
                        text = f.read()
                except Exception:
                    continue
                if "|||" not in text:
                    continue
                fixed, _, flex = text.partition("|||")
                fixed_tags = _split_caption_tags(fixed)
                flex_tags = _split_caption_tags(flex)
                # 保证 trigger 在固定区最前
                trig_keep = [t for t in trig_tags if _norm_tag(t) not in
                             {_norm_tag(x) for x in fixed_tags}]
                fixed_tags = trig_keep + fixed_tags
                max_keep = max(max_keep, len(fixed_tags))
                new = ", ".join(fixed_tags + flex_tags)
                try:
                    with open(fp, "w", encoding="utf-8") as f:
                        f.write(new)
                except Exception:
                    pass
        if max_keep:
            logf(f"[强绑定] 检测到 ||| 手动固定区，keep_tokens={max_keep}"
                 f"（固定区：{', '.join(trig_tags)} + 自定义特征）")
        return max_keep, warnings

    # ---- 自动模式 ----
    prefix = trig_tags + list(info["consistent"])
    if len(prefix) <= len(trig_tags):
        return max(1, len(trig_tags)), warnings
    prefix_norm = [_norm_tag(t) for t in prefix]
    keep = len(prefix)
    n = 0
    for root, _dirs, files in os.walk(train_dir):
        for fn in files:
            if not fn.lower().endswith(".txt"):
                continue
            fp = os.path.join(root, fn)
            try:
                with open(fp, "r", encoding="utf-8-sig") as f:
                    text = f.read()
            except Exception:
                continue
            tags = _split_caption_tags(text)
            if not tags:
                continue
            head = [_norm_tag(t) for t in tags[:len(prefix)]]
            if head == prefix_norm:          # 已绑定 -> 跳过（幂等）
                continue
            seen = set(prefix_norm)
            rest = []
            for t in tags:
                nrm = _norm_tag(t)
                if nrm in seen:
                    continue
                seen.add(nrm)
                rest.append(t.strip())
            new = ", ".join(prefix + rest)
            try:
                with open(fp, "w", encoding="utf-8") as f:
                    f.write(new)
                n += 1
            except Exception:
                pass
    logf(f"[强绑定] 已把 trigger + {len(info['consistent'])} 个 100% 一致特征拼成固定前缀"
         f"（keep_tokens={keep}）：{', '.join(prefix)}")
    if n:
        logf(f"[强绑定] 已重写 {n} 张标签，固定前缀置顶")
    return keep, warnings




def _md5_file(path):
    import hashlib

    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_wd14_tagger():
    """在 kohya_ss（含 sd-scripts）里查找官方 WD14 打标脚本。

    兼容 kohya_dir.txt 指向 kohya_ss 根、或数据根（KohyaLoraTool_data）、或为空三种情况；
    找不到返回 None（调用方打印候选路径便于排查，2026-08-22 补全）。
    """
    cands = []
    kit = os.path.dirname(os.path.abspath(__file__))
    for base in (kit, os.path.expanduser("~")):
        cands.append(os.path.join(base, "kohya_ss", "finetune", "tag_images_by_wd14_tagger.py"))
        cands.append(os.path.join(base, "kohya_ss", "sd-scripts", "finetune", "tag_images_by_wd14_tagger.py"))
    kdf = os.path.join(kit, "kohya_dir.txt")
    kd = None
    if os.path.isfile(kdf):
        try:
            with open(kdf, "r", encoding="utf-8") as f:
                kd = f.read().strip().lstrip("\ufeff").strip() or None
        except Exception:
            kd = None
    # kd 可能是 kohya_ss 根（正常），也可能是数据根（KohyaLoraTool_data）——两种都试
    for base in ((kd, os.path.join(kd, "kohya_ss")) if kd else ()):
        cands.append(os.path.join(base, "finetune", "tag_images_by_wd14_tagger.py"))
        cands.append(os.path.join(base, "sd-scripts", "finetune", "tag_images_by_wd14_tagger.py"))
    # 兜底：跟随安装位置的数据目录 / APPDATA（打包版数据在安装目录同级 KohyaLoraTool_data）
    for root in (os.path.join(os.path.dirname(kit), "KohyaLoraTool_data"),
                 os.path.join(os.environ.get("APPDATA", ""), "KohyaLoraTool")):
        base = os.path.join(root, "kohya_ss")
        cands.append(os.path.join(base, "finetune", "tag_images_by_wd14_tagger.py"))
        cands.append(os.path.join(base, "sd-scripts", "finetune", "tag_images_by_wd14_tagger.py"))
    # 去重后返回第一个存在的
    seen = set()
    for p in cands:
        if not p or p in seen:
            continue
        seen.add(p)
        if os.path.isfile(p):
            return p
    return None


def _run_cmd(cmd, cwd=None, env=None, logf=print):
    """运行命令并把 stdout/stderr 实时交给 logf。返回退出码。

    WD14 打标子进程（onnxruntime）缺 Triton 时会打印大段非致命告警 /
    traceback（"No module named triton" 等），容易被用户误认成打标失败；
    这里把含 triton 的告警行（及紧邻的 traceback 头）折叠成一行友好提示。
    """
    import subprocess
    _triton_noise = re.compile(
        r"no module named ['\"]?triton|triton not found|detected no triton|without triton|"
        r"failed to import triton|import triton failed|cannot import name ['\"]?triton", re.I)
    _noted = [False]
    _tb = []  # 缓存可能的 traceback 头（最长 8 行），遇到 triton 行则整段吞掉

    logf("$ " + " ".join(str(x) for x in cmd))
    try:
        proc = subprocess.Popen(
            cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=0x08000000,
        )
    except Exception as e:
        logf(f"[ERROR] 无法启动进程: {e}")
        return 1

    def _flush_tb():
        if _tb:
            for _l in _tb:
                logf(_l)
            _tb.clear()

    for line in proc.stdout:
        raw = line.rstrip("\n").rstrip("\r")
        if _triton_noise.search(raw):
            if _tb:
                _tb.clear()
            if not _noted[0]:
                _noted[0] = True
                logf("[WD14] 提示：未检测到 Triton（仅可选加速不可用），不影响打标")
            continue
        if raw.strip() == "Traceback (most recent call last):" or (
                _tb and (raw.startswith("  File ") or raw.startswith("    ") or raw.strip() == "")):
            _tb.append(raw)
            if len(_tb) > 8:
                _flush_tb()
            continue
        _flush_tb()
        logf(raw)
    _flush_tb()
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


def _wd14_model_dir():
    """WD14 模型目录：优先用程序内置（wd14_tagger_model，随安装包分发），否则用 %APPDATA% 缓存。

    返回 (目录, 是否已就绪)。就绪 = 该目录里已有对应 repo 的 model.onnx。
    """
    repo = WD14_REPO_ID.replace("/", "_")
    candidates = []
    kit = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(kit, "wd14_tagger_model"))            # 内置（随安装包）
    candidates.append(os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")),
        "KohyaLoraTool", "wd14_tagger_model"))                           # 下载缓存
    for d in candidates:
        if os.path.isfile(os.path.join(d, repo, "model.onnx")):
            return d, True
    return candidates[-1], False


def run_wd14_tagger(output_dir, logf=print, script=None, batch_size=4, thresh=0.35):
    """调用 kohya 官方 WD14 打标脚本，为 output_dir 里每张图生成 .txt 标签。

    返回是否成功。失败时由调用方做兜底处理，不会中断整体预处理。
    模型优先用内置 wd14_tagger_model（开箱即用，不联网）；缺失时才自动下载一次。

    增强（整合 2026-08-17 现场修复）：
    - 解释器自动选择：当前解释器缺 torch/onnxruntime 时自动改用带 torch 的 venv 并补装 onnx；
    - library 路径修复：把 sd-scripts 根目录加进 PYTHONPATH 并作为工作目录；
    - 坏图隔离：打标前校验输出图片，损坏的移走，避免一张坏图中断整批打标。
    """
    script = script or find_wd14_tagger()
    if not script:
        logf("[WD14] 未找到 kohya 官方打标脚本，跳过自动打标")
        return False
    # 打标环境准备：当前解释器缺 torch/onnxruntime 时自动选带 torch 的 venv 并补装
    py, sd_root = _prepare_wd14_env(logf)
    if not py:
        logf("[WD14] 没有可用的打标解释器（缺 torch/onnxruntime），跳过自动打标")
        return False
    # 隔离损坏图片：避免一张坏图导致整批打标中断
    _quarantine_corrupt_images(output_dir, logf)
    model_dir, ready = _wd14_model_dir()
    logf(f"[WD14] 使用官方打标脚本: {script}")
    logf(f"[WD14] 打标解释器: {py}")
    logf(f"[WD14] 打标模型目录: {model_dir}" + ("（内置，已就绪）" if ready else "（未就绪，将自动下载）"))
    cmd = [
        py, script, output_dir,
        "--onnx", "--repo_id", WD14_REPO_ID,
        "--model_dir", model_dir,
        "--batch_size", str(batch_size), "--thresh", str(thresh),
        "--remove_underscore", "--caption_extension", ".txt",
    ]
    if not ready:
        cmd.append("--force_download")
    env = dict(os.environ)
    env["HF_ENDPOINT"] = "https://hf-mirror.com"
    for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(_k, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    # library 模块路径：sd-scripts 根目录进 PYTHONPATH，并作为工作目录
    cwd = None
    if sd_root:
        old_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = sd_root + ((";" + old_pp) if old_pp else "")
        cwd = sd_root
    try:
        rc = _run_cmd(cmd, cwd=cwd, env=env, logf=logf)
        if rc == 0:
            logf("[WD14] 自动打标完成（GPU）")
            return True
        logf(f"[WD14] 打标脚本退出码 {rc}")
        # GPU 会话初始化失败（驱动/CUDA 版本不匹配）时，自动回退 CPU 重试一次
        if env.get("CUDA_VISIBLE_DEVICES") != "":
            logf("[WD14] GPU 打标失败，正在回退 CPU 重试一次（会慢一些）…")
            env["CUDA_VISIBLE_DEVICES"] = ""
            rc2 = _run_cmd(cmd, cwd=cwd, env=env, logf=logf)
            if rc2 == 0:
                logf("[WD14] 自动打标完成（CPU 回退）")
                return True
            logf(f"[WD14] CPU 回退也失败（退出码 {rc2}）")
    except Exception as e:
        logf(f"[WD14] 打标失败: {e}")
        try:
            if env.get("CUDA_VISIBLE_DEVICES") != "":
                logf("[WD14] 正在回退 CPU 重试一次…")
                env["CUDA_VISIBLE_DEVICES"] = ""
                rc3 = _run_cmd(cmd, cwd=cwd, env=env, logf=logf)
                if rc3 == 0:
                    logf("[WD14] 自动打标完成（CPU 回退）")
                    return True
        except Exception:
            pass
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


def _sd_scripts_root(script=None):
    """由 WD14 打标脚本路径推导 sd-scripts 根目录（library 包所在处）。

    官方脚本在 <sd-scripts>/finetune/tag_images_by_wd14_tagger.py，
    运行时会 import library.dataset，需要把 sd-scripts 根目录加进模块搜索路径。
    """
    p = script or find_wd14_tagger()
    if not p:
        return None
    cand = os.path.dirname(os.path.dirname(os.path.abspath(p)))
    return cand if os.path.isdir(os.path.join(cand, "library")) else None


def _quarantine_corrupt_images(output_dir, logf=print):
    """打标前校验输出图片完整性：损坏/截断的移到 <输出目录>_corrupt。

    避免一张坏图导致整批 WD14 打标中断；下次预处理会从原图自动重新生成。
    """
    moved = 0
    corrupt_dir = output_dir.rstrip("\\/") + "_corrupt"
    for f in sorted(os.listdir(output_dir)):
        if os.path.splitext(f)[1].lower() not in IMAGE_EXTS:
            continue
        p = os.path.join(output_dir, f)
        try:
            with load_image(p):
                pass
        except Exception:
            try:
                os.makedirs(corrupt_dir, exist_ok=True)
                shutil.move(p, os.path.join(corrupt_dir, f))
                t = os.path.join(output_dir, os.path.splitext(f)[0] + ".txt")
                if os.path.isfile(t):
                    shutil.move(t, os.path.join(corrupt_dir, os.path.basename(t)))
                moved += 1
                logf(f"[WD14] 隔离损坏图片: {f}")
            except Exception:
                pass
    if moved:
        logf(f"[WD14] 已隔离 {moved} 张损坏图片到 {corrupt_dir}（下次预处理会从原图重新生成）")
    return moved



def _quarantine_input_corrupt(input_dir, files, logf=print):
    """预处理前扫描输入图片，损坏/截断的提前隔离到 <输入目录>_corrupt。

    返回被隔离的文件名列表（相对路径）。避免坏图在打标/处理阶段才暴露裸 PIL
    traceback；同时让用户一眼看到是哪张图坏了（对应待办：预处理前提前扫描隔离）。
    """
    moved = []
    corrupt_dir = input_dir.rstrip("\\/") + "_corrupt"
    for name in files:
        p = os.path.join(input_dir, name.replace("/", os.sep))
        try:
            with load_image(p):
                pass
        except Exception as e:
            try:
                os.makedirs(corrupt_dir, exist_ok=True)
                _flat = name.replace("/", "__").replace("\\", "__")
                shutil.move(p, os.path.join(corrupt_dir, _flat))
                _t = os.path.join(input_dir, os.path.splitext(name.replace("/", os.sep))[0] + ".txt")
                if os.path.isfile(_t):
                    shutil.move(_t, os.path.join(corrupt_dir, os.path.splitext(_flat)[0] + ".txt"))
                moved.append(name)
                logf(f"[隔离损坏图片] {name}（{e}）→ {corrupt_dir}")
            except Exception:
                pass
    if moved:
        logf(f"[INFO] 已隔离 {len(moved)} 张损坏图片到 {corrupt_dir}（可从原图重新下载/修复后再放回）")
    return moved

def _has_wd14_deps(py):
    """检查解释器能否 import torch + onnxruntime（WD14 打标必需）。"""
    code = ("import sys, importlib.util;" +
            "sys.exit(0 if (importlib.util.find_spec('torch') and importlib.util.find_spec('onnxruntime')) else 1)")
    try:
        r = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=120)
        return r.returncode == 0
    except Exception:
        return False


def _has_torch(py):
    """检查解释器能否 import torch。"""
    try:
        r = subprocess.run([py, "-c", "import sys, importlib.util;" +
                            "sys.exit(0 if importlib.util.find_spec('torch') else 1)"],
                           capture_output=True, text=True, timeout=120)
        return r.returncode == 0
    except Exception:
        return False


def _ensure_onnx(py, logf=print):
    """解释器缺 onnxruntime/onnx 时自动补装（清华源）。返回是否就绪。"""
    if _has_wd14_deps(py):
        return True
    try:
        _env = dict(os.environ)
        for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            _env.pop(_k, None)
        _env["NO_PROXY"] = "*"
        r = subprocess.run([py, "-m", "pip", "install", "--no-input", "--retries", "10",
                            "--timeout", "120", "--index-url",
                            "https://mirrors.aliyun.com/pypi/simple/",
                            "--extra-index-url", "https://pypi.tuna.tsinghua.edu.cn/simple",
                            "onnxruntime", "onnx"], env=_env,
                           capture_output=True, text=True, timeout=600)
        if r.returncode == 0 and _has_wd14_deps(py):
            logf(f"[WD14] 已自动补装 onnxruntime/onnx（{py}）")
            return True
    except Exception:
        pass
    return False


def _prepare_wd14_env(logf=print):
    """准备 WD14 打标解释器环境。返回 (python 路径, sd_scripts_root 或 None)。

    策略：
    1. 当前解释器有 torch+onnxruntime → 直接用；
    2. 有 torch 但缺 onnxruntime → 自动补装；
    3. 当前解释器缺 torch → 探测其他引擎 venv（venv_amd / musubi-venv / ai_toolkit_venv），
       找到带 torch 的并补装 onnxruntime；
    4. 都不可用 → 返回 (None, None)。
    """
    cur = sys.executable
    if _has_torch(cur):
        if _ensure_onnx(cur, logf):
            return cur, _sd_scripts_root()
    cands = []
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (here, os.path.dirname(here)):
        for sub in ("venv_amd", "musubi-venv", "ai_toolkit_venv", "venv"):
            p = os.path.join(base, sub, "Scripts", "python.exe")
            if os.path.isfile(p) and os.path.abspath(p) != os.path.abspath(cur):
                cands.append(p)
    ap = os.environ.get("APPDATA", "")
    if ap:
        for sub in (r"KohyaLoraTool\venv_amd",
                    r"KohyaLoraTool\kohya_ss\musubi-venv",
                    r"KohyaLoraTool\kohya_ss\ai_toolkit_venv"):
            p = os.path.join(ap, sub, "Scripts", "python.exe")
            if os.path.isfile(p) and os.path.abspath(p) != os.path.abspath(cur):
                cands.append(p)
    for p in cands:
        if _has_torch(p):
            logf(f"[WD14] 当前解释器缺 torch，改用 {p} 打标")
            if _ensure_onnx(p, logf):
                return p, _sd_scripts_root()
    return None, None


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".jfif", ".jpe", ".avif"}



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
        im.load()  # 立即校验像素完整性（PIL 懒加载，损坏/截断的 PNG 在此刻抛错）
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
                         num_repeats=1, reg_dir=None, keep_tokens=0,
                         subsets=None, reg_subsets=None):
    """为 kohya sd-scripts 生成数据集配置 TOML（绝对路径）。

    - num_repeats：训练图片重复次数（平铺数据集时生效）；
    - subsets：[(image_dir, num_repeats), ...]，支持秋叶式 repeats_名称 子目录结构，
      每个子目录独立重复次数；传入时按多个 [[datasets.subsets]] 输出，忽略单一 num_repeats；
    - reg_dir：正则数据集文件夹（非空时额外写一个 [[datasets]]，is_reg=true 写在子集层）；
    - reg_subsets：正则数据集子集列表（同 subsets 语义，默认为 [(reg_dir, 1)]）；
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
    ]
    if subsets:
        for _item in subsets:
            _d = _item[0]
            _nr = _item[1]
            _abs = os.path.abspath(_d).replace("\\", "/")
            lines += [
                "",
                "  [[datasets.subsets]]",
                f'  image_dir = "{_abs}"',
                f"  num_repeats = {int(_nr)}",
            ]
    else:
        lines += [
            "",
            "  [[datasets.subsets]]",
            f'  image_dir = "{image_dir}"',
            f"  num_repeats = {int(num_repeats)}",
        ]
    if reg_dir and os.path.isdir(reg_dir):
        reg_subsets = reg_subsets or [(reg_dir, 1)]
        lines += [
            "",
            "[[datasets]]",
            f"resolution = {resolution}",
            f"batch_size = {batch_size}",
            "enable_bucket = true",
            "bucket_no_upscale = true",
            "bucket_reso_steps = 64",
            f"min_bucket_reso = {min_bucket}",
            f"max_bucket_reso = {max_bucket}",
        ]
        for _item in reg_subsets:
            _d = _item[0]
            _nr = _item[1]
            _abs = os.path.abspath(_d).replace("\\", "/")
            lines += [
                "",
                "  [[datasets.subsets]]",
                f'  image_dir = "{_abs}"',
                f"  num_repeats = {int(_nr)}",
                "  is_reg = true",
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
    parser.add_argument("--caption", default="", help="统一 caption 文本（画风模式；留空则自动 WD14 打标并过滤人物标签）")
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
    parser.add_argument("--no-strong-bind", action="store_true",
                        help="人物模式关闭自动强绑定（默认开：自动把 trigger + 100% 一致特征词固定到标签开头）")
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

    def _print_import_pollution_hint(mod):
        # 常见根因：工具目录被残留的 numpy.py / numpy / PIL.py / PIL 文件夹污染。
        # 脚本运行时 sys.path[0] 指向脚本所在目录，import 会优先命中这些假文件，
        # 而不是 venv 里的真包，导致「-c 校验通过、脚本却报缺少依赖」的矛盾现象。
        try:
            _here = os.path.dirname(os.path.abspath(__file__))
            _cands = {mod + ".py", mod}
            for _d in (_here, os.getcwd()):
                _bad = [os.path.join(_d, _n) for _n in _cands
                        if os.path.exists(os.path.join(_d, _n))]
                if _bad:
                    print("[ERROR] 检测到干扰 %s 导入的文件（残留/误放，会被当成真包加载），请删除后重试：" % mod)
                    for _b in _bad:
                        print("        " + _b)
        except Exception:
            pass

    # ---- 依赖检查 ----
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        print("[ERROR] import Pillow 失败，真实错误如下（用于定位根因）：")
        traceback.print_exc()
        _print_import_pollution_hint("PIL")
        print("[ERROR] 缺少 Pillow。请先运行 01_一键安装_Setup.bat，")
        print("        或用 kohya_ss 的 venv python 运行本脚本：")
        print('        "kohya_ss\\venv\\Scripts\\python.exe" preprocess.py ...')
        sys.exit(1)
    try:
        import numpy  # noqa: F401
    except Exception:
        # 打印真实 traceback：可能是未安装（ModuleNotFoundError）、DLL 冲突（DLL load failed）、
        # 版本不兼容等；只笼统提示「缺少 numpy」会让用户/开发者无法定位根因。
        print("[ERROR] import numpy 失败，真实错误如下（用于定位根因）：")
        traceback.print_exc()
        _print_import_pollution_hint("numpy")
        print("[ERROR] 缺少 numpy。请先运行 01_一键安装_Setup.bat 安装依赖，")
        print("        或重跑【② 安装训练内核】自动重建环境。")
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

    # 收集输入文件：优先直接扫描根目录；根目录没有图时自动递归子文件夹
    # （用户常把图按角色/风格分在子目录里，选中"上层图集文件夹"也能直接处理）
    files = sorted(
        f for f in os.listdir(input_dir)
        if os.path.splitext(f)[1].lower() in IMAGE_EXTS
    )
    if not files:
        files = []
        for _root, _dirs, _fs in os.walk(input_dir):
            _dirs[:] = [d for d in _dirs if not d.startswith(".")]
            for _f in _fs:
                if os.path.splitext(_f)[1].lower() in IMAGE_EXTS:
                    files.append(os.path.relpath(os.path.join(_root, _f), input_dir).replace(os.sep, "/"))
        files.sort()
        if files:
            print(f"[INFO] 根目录没有图片，自动扫描子文件夹，共找到 {len(files)} 张图片。")
    if not files:
        print(f"[WARN] 输入文件夹里没有找到图片（支持 jpg/png/webp/bmp/tif/gif/jfif/jpe/avif）。")
        print(f"       {input_dir}")
        return

    print(f"[INFO] 找到 {len(files)} 张图片")
    # 预处理前提前扫描隔离损坏图片（待办四十八）：明确提示是哪张图坏，避免裸 PIL traceback
    _removed = _quarantine_input_corrupt(input_dir, files, print)
    if _removed:
        _rs = set(_removed)
        files = [f for f in files if f not in _rs]
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
        # name 可能是相对路径（子文件夹递归时用 / 分隔）；输出名用 __ 扁平化，避免重名
        _rel = name.replace("/", os.sep)
        _flat = name.replace("/", "__").replace("\\", "__")
        stem = os.path.splitext(_flat)[0]
        raw_img = os.path.join(input_dir, _rel)
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
                raw_txt = os.path.join(input_dir, os.path.splitext(_rel)[0] + ".txt")
                if mode == "style":
                    # 画风模式：优先画风描述词（用户提供）；否则记录原图自带 txt，
                    # 稍后统一 WD14 打标 + 过滤人物标签（不再默认写死动漫 caption）
                    if style_caption.strip():
                        with open(out_txt, "w", encoding="utf-8") as f:
                            f.write(style_caption)
                    elif os.path.isfile(raw_txt):
                        try:
                            with open(raw_txt, "r", encoding="utf-8") as f:
                                user_captions[stem] = f.read()
                        except Exception:
                            user_captions[stem] = ""
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
    if mode == "character" and not args.no_caption and (ok + skipped):
        tagger = find_wd14_tagger()
        use_wd14 = (not args.no_wd14) and bool(tagger)
        imgs_no_txt = [f for f in os.listdir(output_dir)
                       if os.path.splitext(f)[1].lower() in IMAGE_EXTS
                       and not os.path.isfile(os.path.join(output_dir, os.path.splitext(f)[0] + ".txt"))]
        if use_wd14:
            if imgs_no_txt:
                wd14_ok = run_wd14_tagger(output_dir)
                if not wd14_ok:
                    _fill_missing_captions(output_dir, DEFAULT_CHARACTER_CAPTION)
            else:
                print("[INFO] 图片标签已齐全，跳过 WD14 打标。")
        else:
            _fill_missing_captions(output_dir, DEFAULT_CHARACTER_CAPTION)
            if not tagger:
                print("[WARN] 未找到 kohya 官方 WD14 打标脚本，缺少标签的图片使用了兜底 caption。/n       （已检查：安装目录/用户目录 kohya_ss、kohya_dir.txt 指向目录、安装目录同级 KohyaLoraTool_data/kohya_ss、%APPDATA%/KohyaLoraTool/kohya_ss 下的 finetune 与 sd-scripts/finetune；若确认脚本存在，请检查 kohya_dir.txt 路径）")
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
        # 人物强绑定：自动把 trigger + 100% 一致身份特征拼成固定前缀（keep_tokens 覆盖整组）
        if not args.no_strong_bind and trigger:
            try:
                _kt, _warns = apply_strong_binding(output_dir, trigger, logf=print)
                for _w in _warns:
                    print(f"[WARN] {_w}")
                if _kt and _kt > args.keep_tokens:
                    args.keep_tokens = _kt
            except Exception as _e:
                print(f"[WARN] 人物强绑定失败（忽略）: {_e}")

    # ---- 画风模式：无画风描述词时，用 WD14 打标 + 过滤人物标签（替代写死的动漫 caption） ----
    if mode == "style" and not args.no_caption and (ok + skipped) and not style_caption.strip():
        tagger = find_wd14_tagger()
        use_wd14 = (not args.no_wd14) and bool(tagger)
        imgs_no_txt = [f for f in os.listdir(output_dir)
                       if os.path.splitext(f)[1].lower() in IMAGE_EXTS
                       and not os.path.isfile(os.path.join(output_dir, os.path.splitext(f)[0] + ".txt"))]
        if use_wd14:
            if imgs_no_txt:
                wd14_ok = run_wd14_tagger(output_dir)
                if not wd14_ok:
                    _fill_missing_captions(output_dir, DEFAULT_CAPTION)
            else:
                print("[INFO] 图片标签已齐全，跳过 WD14 打标。")
        else:
            _fill_missing_captions(output_dir, DEFAULT_CAPTION)
            if not tagger:
                print("[WARN] 未找到 kohya 官方 WD14 打标脚本，缺少标签的图片使用了兜底 caption。/n       （已检查：安装目录/用户目录 kohya_ss、kohya_dir.txt 指向目录、安装目录同级 KohyaLoraTool_data/kohya_ss、%APPDATA%/KohyaLoraTool/kohya_ss 下的 finetune 与 sd-scripts/finetune；若确认脚本存在，请检查 kohya_dir.txt 路径）")
        # 还原原图自带 txt（过滤人物标签）
        for stem, cap in user_captions.items():
            if cap.strip():
                with open(os.path.join(output_dir, stem + ".txt"), "w", encoding="utf-8") as f:
                    f.write(filter_character_tags(cap))
        # 对全部 txt 过滤人物/五官标签（WD14 打的也过滤，保留画风/内容标签）
        n_f = 0
        for f in sorted(os.listdir(output_dir)):
            if os.path.splitext(f)[1].lower() not in IMAGE_EXTS:
                continue
            t = os.path.join(output_dir, os.path.splitext(f)[0] + ".txt")
            if os.path.isfile(t):
                with open(t, "r", encoding="utf-8") as fh:
                    cur = fh.read()
                ncur = filter_character_tags(cur)
                if ncur != cur:
                    with open(t, "w", encoding="utf-8") as fh:
                        fh.write(ncur)
                    n_f += 1
        print(f"[INFO] 画风模式：已用 WD14 打标并过滤人物/五官标签 {n_f} 张（保留画风/内容标签）")

    # ---- 画风模式：同样支持画风专属触发词（插入每张 txt 第一行，不动 WD14 打标逻辑） ----
    if mode == "style" and not args.no_caption and (ok + skipped) and trigger:
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
        print(f"[INFO] 已把画风专属触发词「{trigger}」插入 {n_trig} 张图片的标签第一行")

    # ---- 最终兜底：确保每张图都有非空标签（任何环节失败都不漏标签） ----
    if not args.no_caption and (ok + skipped):
        fb = DEFAULT_CAPTION if mode == "style" else DEFAULT_CHARACTER_CAPTION
        n_fill = 0
        for f in sorted(os.listdir(output_dir)):
            if os.path.splitext(f)[1].lower() not in IMAGE_EXTS:
                continue
            t = os.path.join(output_dir, os.path.splitext(f)[0] + ".txt")
            need = False
            if not os.path.isfile(t):
                need = True
            else:
                try:
                    with open(t, "r", encoding="utf-8") as fh:
                        if not fh.read().strip():
                            need = True
                except Exception:
                    need = True
            if need:
                with open(t, "w", encoding="utf-8") as fh:
                    fh.write(fb)
                n_fill += 1
        if n_fill:
            print(f"[INFO] 最终兜底：为 {n_fill} 张缺失/空标签的图片补写了 caption")

    print()
    print("=" * 60)
    print(f"  处理成功: {ok}  |  跳过(已存在): {skipped}  |  重复: {dups}")
    print(f"  损坏: {corrupt}  |  过小: {too_small}  |  模糊: {blurry}  |  失败: {failed}")
    print(f"  去除黑边: {cropped}  |  去除水印: {watermarked}")
    print(f"  输出目录: {output_dir}")
    if (ok + skipped) and not args.no_caption:
        if mode == "style":
            print("  每张图已生成同名 .txt caption（画风描述，已过滤人物五官/角色标签" +
                  ("，trigger 已插入" if trigger else "") + "）")
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
