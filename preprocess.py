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

# ★ 2026-09-27 关键修复：剔除「本脚本所在目录」在 sys.path 中的条目 ✗
#   打包版（PyInstaller onedir）把 python312.dll / _socket.pyd 等 **3.12 的 C 扩展**
#   与这些辅助脚本**平铺在同一个目录**（F:\KohyaLoraTool\）✗
#   而 Python 会把「脚本所在目录」放进 sys.path[0] ✗
#   → 于是 `import urllib.request`（内部 import _socket）会命中那份 3.12 的 _socket.pyd ✗
#   → 报 `ImportError: Module use of python312.dll conflicts with this version of Python`
#     （venv 是 3.11，两边对不上 ✗；同类风险还有 _ctypes.pyd 等）
#   用户实测（KohyaLoRA_运行日志_20260927_220239）：预处理跑完图片，走到
#   「下载 WD14 打标模型」时整脚本崩溃，且换任何引擎都一样（预处理共用第一引擎 venv ✓）
#
#   为什么以前不报 ✗：`urllib` 是**惰性 import**（只在下模型时走到）✓
#   而 2026-09-17 起 WD14 模型改为「首次使用时下载」✗ → 第一次走到 urllib → 才引爆 ✓
#
#   ⚠️ 本段必须是**所有 import 之前的第一件事**（只用 os/sys，纯标准库，安全 ✓）
import glob as _glob2
import os as _os
import sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
# ⚠️ 必须**条件成立才剔除** ✗：仅当本目录确实含打包版 C 扩展时才动手 ✓
#   （开发环境下本目录就是项目根，还放着 kohya_core 等本地包 ——
#    无条件剔除会把它们也屏蔽掉，直接 import 失败 ✓）
if any(_glob2.glob(_os.path.join(_HERE, _p))
       for _p in ("python3*.dll", "_socket.pyd", "_ctypes.pyd")):
    _sys.path[:] = [p for p in _sys.path
                    if _os.path.normcase(_os.path.abspath(p or _os.getcwd())) != _os.path.normcase(_HERE)]

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback

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

# 写实版兜底 caption（--style-target realistic）：
#   旧版把动漫文案写死，于是"想训写实画风"的用户只要走到任何一条兜底路径
#   （WD14 打标失败 / 勾了跳过 WD14 / 最终兜底），整批标签都会被写成 anime cel-shading，
#   等于亲手把模型教成动漫 —— 这是"选了写实却出动漫味"最直接的一条原因。
DEFAULT_CAPTION_REALISTIC = (
    "photorealistic, realistic photograph, natural lighting, detailed skin texture, "
    "sharp focus, high detail, professional photography"
)

STYLE_TARGET_LABELS = {"anime": "动漫", "realistic": "写实"}


def default_style_caption(style_target):
    """画风模式的兜底 caption：按出图风格（anime / realistic）选文案。"""
    return DEFAULT_CAPTION_REALISTIC if style_target == "realistic" else DEFAULT_CAPTION


# 人物模式兜底 caption（仅在无法运行 WD14 打标、且原图没有自带 .txt 时使用）
DEFAULT_CHARACTER_CAPTION = "1girl, solo"

# ---- WD14 打标模型（2026-09-17 改为「可选 + 首次使用时下载」）----
# 背景：模型原先内置在安装包里（onnx 311MB），导致 Setup.exe 488MB、
# 发布包解压后 562MB —— 分发/更新都吃力（用户反馈「安装包太大了，分发也不方便」）。
# 现在改为**首次使用时下载**：发布包 562MB → 251MB，安装包约 488MB → 200MB 左右。
# 下载源策略与工具其他资源一致：**魔搭优先 → hf-mirror 兜底**
# （hf-mirror 在国内不稳；模型已上传到魔搭 wd14_models/<repo>/ 下，并做过回读校验）。
WD14_MODELS = {
    "swinv2-v3": "SmilingWolf/wd-swinv2-tagger-v3",
    "moat-v2": "SmilingWolf/wd-v1-4-moat-tagger-v2",
}
WD14_MODEL_LABELS = {
    "swinv2-v3": "WD14 swinv2-v3（推荐，标签库更新到 2024）",
    "moat-v2": "WD14 moat-v2（旧版，2022 标签库）",
}
# 默认模型：社区主流（月下载 ~70 万，是旧版的数千倍），标签库更新到 2024-02
WD14_DEFAULT_MODEL = "swinv2-v3"
WD14_REPO_ID = WD14_MODELS[WD14_DEFAULT_MODEL]      # 兼容旧引用，见 resolve_wd14_model

# 魔搭仓库（与 release.py 的 ms_repo 一致）—— 模型文件放在 wd14_models/<repo 名>/ 下
WD14_MS_REPO = "FGtiancai/Kohya-LoRA-Tool"
WD14_MS_BASE = "https://modelscope.cn/models/%s/resolve/master/wd14_models" % WD14_MS_REPO
WD14_HF_BASE = "https://hf-mirror.com"


def resolve_wd14_model(key=None):
    """把「打标模型选项」解析成 (key, repo)。

    ★★ 这是「老用户无缝衔接、新用户无感」的关键所在：

       **任何缺失 / 未知 / 空值，都静默回退到默认模型，绝不抛异常、绝不弹错误。**
       · 老用户升级后：设置/项目里没有这个键 → 直接拿到默认模型 ✓ 什么都不用做 ✓
       · 新用户：从没设过 → 走同一条路径 ✓ 装完即用 ✓
       · 用户显式选过（含选旧模型）→ 按他选的走 ✓

    之所以能这么简单，是因为**不做迁移**：旧项目不去动它，新建/之后的项目一律用默认；
    这样也不会出现「有的项目新、有的项目旧」的混乱 ✓
    """
    k = (key or "").strip()
    if k not in WD14_MODELS:
        k = WD14_DEFAULT_MODEL
    return k, WD14_MODELS[k]


def _wd14_repo_dirname(repo):
    """模型目录名：repo 里的 '/' 换成 '_'（内置目录与下载缓存都用它，天然支持多模型共存）。"""
    return repo.replace("/", "_")


def _http_download(url, dst, logf=print):
    """下载 url 到 dst（先写 .part 再改名，避免半截文件被后续当成完整的）。

    每 3 秒报一次进度 —— 445MB 的 onnx 约 2~3 分钟，没有进度用户会以为卡死。
    """
    tmp = dst + ".part"
    try:
        import urllib.request
    except ImportError as _e:
        # ★ 2026-09-27：兜底 ✗ —— 打包版自带的 C 扩展（python312.dll / _socket.pyd 等）
        #   与 venv 的 Python 版本不一致时，这一句 import 会以
        #   `Module use of python312.dll conflicts with this version of Python` 抛出 ✗
        #   脚本头已剔除 sys.path[0]（治本 ✓）；这里再兜一层：
        #   让它**只跳过下载**，而不是把整个预处理脚本带崩 ✗
        #   用户实测（KohyaLoRA_运行日志_20260927_220239）：图片处理全跑完了，
        #   只因走到「下载 WD14 模型」而整脚本退出码 1 ✓ —— 非常冤 ✓
        logf("[WD14]   无法加载网络模块：%s" % _e)
        logf("[WD14]   原因：工具自带的组件与训练环境 Python 版本不一致（打包版 C 扩展混入）")
        logf("[WD14]   处理：① 把这条日志发给作者 ② 或手动下载打标模型，"
             "放进 models\\wd14_tagger_model\\ 后重跑（无需联网）")
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "KohyaLoraTool"})
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            t0 = last = time.time()
            while True:
                chunk = r.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if time.time() - last >= 3:
                    last = time.time()
                    _sp = got / 1024 / 1024 / max(0.001, time.time() - t0)
                    if total:
                        logf("[WD14]   进度 %d%%（%.1f / %.1f MB，%.1f MB/s）"
                             % (got * 100 // total, got / 1048576.0, total / 1048576.0, _sp))
                    else:
                        logf("[WD14]   已下载 %.1f MB（%.1f MB/s）" % (got / 1048576.0, _sp))
        os.replace(tmp, dst)
        return True
    except Exception as e:
        logf("[WD14]   下载异常：%s" % e)
        try:
            os.remove(tmp)
        except Exception:
            pass
        return False


def download_wd14_model(key=None, logf=print):
    """首次使用时下载打标模型。成功返回模型目录，失败返回 None。

    **魔搭优先 → hf-mirror 兜底**；两个源都失败则**明确报错 + 告知手动放置路径**。

    ⚠️ 绝不静默成功：2026-09-16 魔搭上传就因为「大文件传输中断、小文件没传上去、
    脚本却照样打印成功」而静默失败过 —— 所以这里每个文件都要**校验大小**再认。
    """
    key, repo = resolve_wd14_model(key)
    _r = _wd14_repo_dirname(repo)
    dst = os.path.join(_wd14_cache_root(), _r)
    try:
        os.makedirs(dst, exist_ok=True)
    except Exception as e:
        logf("[WD14] 无法创建模型目录：%s" % e)
        return None
    logf("[WD14] 打标模型尚未下载（%s），现在下载…" % WD14_MODEL_LABELS.get(key, key))
    # (文件名, 认它完整的最小字节数) —— onnx 至少几十 MB，csv 至少 1KB
    for fn, min_sz in (("model.onnx", 10 * 1024 * 1024), ("selected_tags.csv", 1024)):
        tgt = os.path.join(dst, fn)
        if os.path.isfile(tgt) and os.path.getsize(tgt) >= min_sz:
            continue                                   # 已有且大小合理 → 跳过，不重复下
        ok = False
        for name, url in (
            ("魔搭", "%s/%s/%s" % (WD14_MS_BASE, _r, fn)),
            ("hf-mirror", "%s/%s/resolve/main/%s" % (WD14_HF_BASE, repo, fn)),
        ):
            logf("[WD14] 下载 %s（%s 源）…" % (fn, name))
            if _http_download(url, tgt, logf) and os.path.getsize(tgt) >= min_sz:
                logf("[WD14] ✓ %s 已就绪（%.1f MB）" % (fn, os.path.getsize(tgt) / 1048576.0))
                ok = True
                break
            logf("[WD14] %s 源未成功，换下一个源…" % name)
        if not ok:
            logf("[WD14] ⚠ 打标模型下载失败：%s（魔搭与 hf-mirror 都不可用）" % fn)
            logf("[WD14]   ① 可稍后重试（重新点训练即可，已下好的文件不会重下）")
            logf("[WD14]   ② 或手动下载该文件放到：%s" % tgt)
            return None
    logf("[WD14] 打标模型已就绪：%s" % dst)
    # ⚠️ 必须返回**根目录**（`%APPDATA%\...\wd14_tagger_model`），不是上面这个模型目录 ✗
    # 2026-09-17 真机实测抓到：本函数原先 `return dst`（模型目录），而 `_wd14_ready_dir()`
    # 返回的是根目录，两者不一致 ✗ → 调用方再拼一次 `repo 目录名` 就变成嵌套两层
    # （`...\SmilingWolf_wd-swinv2-tagger-v3\SmilingWolf_wd-swinv2-tagger-v3\`）✗ →
    # 内置打标照样「找不到 model.onnx」，官方脚本的 `--model_dir` 也是错的 ✗。
    # 这个 bug 此前**一直没暴露**，正是因为 `_http_download` 缺 import time、下载从未成功过 ✓
    # —— "修好下载"之后它立刻就会发作，所以必须一起修 ✓
    return _wd14_cache_root()


def _wd14_cache_root():
    """下载缓存根目录：%APPDATA%\\KohyaLoraTool\\wd14_tagger_model。"""
    return os.path.join(
        os.environ.get("APPDATA", os.path.expanduser("~")),
        "KohyaLoraTool", "wd14_tagger_model")

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


# ============================================================
# 概念模式：清洗「描述概念本身」的标签（2026-09-11）
#
# 原理：概念 = 训练集里唯一不变的东西。
#   如果 WD14 把概念本身拆成了通用标签（黑夹克 / 长袖 / 有领子 / 有扣子…），
#   基础模型靠这些标签就能把衣服画出来 → trigger 被架空 → 单独写 trigger 出不来。
#   所以概念模式必须把这些标签删掉，让 trigger 独占概念。
#
# 策略分两类：
#   · 服装 / 形态  —— 概念词可枚举，用词表精准删；
#   · 物品 / 身体部位 —— 无法穷举，改删「训练集里 100% 一致」的标签
#     （调用前已排除通用/姿势/场景词，见 CONCEPT_KEEP_TAGS）。
# ============================================================

CONCEPT_FILTER_WORDS = {
    # 服装：衣服本体 + 穿着部位 + 服装配件（不含帽子/眼镜/包等可独立控制的配饰）
    "outfit": (
        r"dress|skirt|shirt|blouse|jacket|coat|hoodie|sweater|cardigan|vest|waistcoat|"
        r"pants|jeans|shorts|trousers|leggings|stockings|thighhighs|kneesocks|socks|"
        r"boots?|shoes?|sneakers?|sandals?|gloves?|mittens?|"
        r"tie|necktie|bowtie|belt|sash|apron|collar|sailor collar|"
        r"uniform|school uniform|armor|costume|cosplay|"
        r"swimsuit|bikini|underwear|bra|panties|lingerie|"
        r"one-piece|jumpsuit|overalls|kimono|yukata|qipao|hanfu|"
        r"cape|cloak|capelet|poncho|shawl|tunic|"
        r"sleeves?|sleeved|sleeveless|long sleeves|short sleeves|puffy sleeves|"
        r"buttons?|buttoned|zippers?|zippered|pockets?|frills?|frilled|lace|pleats?|pleated|"
        r"collars?|collared|necklines?|hem|lapels?"
    ),
    # 形态 / 种族：身体形态本身（尾巴/翅膀/角/獠牙…）
    "form": (
        r"mermaid|mermaid tail|fish tail|fins?|centaur|lamia|"
        r"monster girl|dragon|dragon girl|demon|demon girl|angel|"
        r"slime|slime girl|puppet|marionette|doll|ball-jointed doll|"
        r"cyborg|android|robot|mecha|tentacles?|"
        r"scales|feathers|fur|furry|"
        r"horns?|wings?|tails?|multiple tails|kitsune|"
        r"animal ears|cat ears|fox ears"
    ),
}

_CONCEPT_FILTER_RE = {
    k: re.compile(r"\b(" + v + r")\b", re.IGNORECASE) for k, v in CONCEPT_FILTER_WORDS.items()
}

# 「100% 一致标签」删除路径下，永不自动删除的标签（姿势 / 场景 / 视角 / 交互）
# —— 这些即使 100% 一致也不属于「概念本身」，删了会被 trigger 反吸收
CONCEPT_KEEP_TAGS = frozenset({
    "standing", "sitting", "kneeling", "lying", "lying on back", "lying on stomach",
    "squatting", "crouching", "crawling", "walking", "running", "jumping", "dancing",
    "posing", "pose", "arms up", "arms behind back", "crossed arms", "hand on hip",
    "hands on hips", "hand in pocket", "hands in pockets", "pointing", "thumbs up",
    "peace sign", "victory sign", "spread legs", "legs up", "on back", "on stomach",
    "all fours", "bent over", "straddling", "girl on top", "cowgirl position",
    "bed", "on bed", "bed sheet", "indoors", "outdoors", "water", "bathroom", "forest",
    "city", "street", "classroom", "window", "night", "day", "sunlight", "sky",
    "from above", "from below", "from side", "from behind", "profile", "pov",
    "upper body", "lower body", "full body", "portrait", "close-up",
})

# 概念类型 -> 中文名（日志用）
CONCEPT_TYPE_CN = {"form": "形态/种族", "outfit": "服装", "object": "物品", "bodypart": "身体部位"}


def filter_concept_tags(text, concept_type, extra_remove=None):
    """概念模式：删除「描述概念本身」的标签，让 trigger 独占这个概念。

    - 服装 / 形态：走 CONCEPT_FILTER_WORDS 词表；
    - 物品 / 身体部位：词表不可穷举，由 extra_remove 传入「100% 一致标签」集合；
    - 返回 (新 caption, 被删标签列表)。
    """
    if not text:
        return "", []
    ct = (concept_type or "").strip().lower()
    pattern = _CONCEPT_FILTER_RE.get(ct)
    extra = {_norm_tag(t) for t in (extra_remove or [])}
    kept, removed = [], []
    for raw in text.split(","):
        s = raw.strip()
        if not s:
            continue
        n = _norm_tag(s)
        if n in extra or (pattern is not None and pattern.search(n)):
            removed.append(n)
        else:
            kept.append(s)
    return ", ".join(kept), removed


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


def apply_strong_binding(train_dir, trigger, logf=print, trigger_only=False):
    """人物 LoRA 自动强绑定：把 trigger + 100% 一致身份特征拼成固定前缀。

    - 无 trigger / 无标签 -> 返回 (0, [])（不强绑）。
    - 存在 ||| 分隔符 -> 手动模式：||| 前为固定区（保持用户顺序），||| 后为可动区；
      keep_tokens = 固定区标签数；写回时去掉 |||。
    - 否则自动模式：前缀 = trigger + 100% 一致特征；重写每张 caption 使前缀在开头；
      keep_tokens = 前缀标签数（幂等：已以完整前缀开头则跳过）。
    - trigger_only=True（概念模式）：固定前缀【只放 trigger】，不把 100% 一致标签
      锁进前缀——服装/物品这类概念若把描述标签一起锁进去，trigger 会被架空；
      这些标签改为给用户「一致性警告」，让用户自己决定加多样性还是保留。
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
        # ⚠️ 措辞（2026-09-16 用户反馈）：原来说「人物一致性不足，建议统一训练集特征」
        # 是**把锅甩给用户的数据集** ✗ —— 而真实原因常常是**视角遮挡让自动打标漏标**
        # （侧身 / 背面 / 远景图上看不到该特征，WD14 这类打标器直接不输出它）。
        # 用户的数据集一致性没问题，也没法靠"统一训练集"修好一个打标器看不到的东西；
        # 那条建议会把人引去改数据集、甚至删掉侧身图。正确的下一步是**手动锁进固定前缀**。
        # 典型实测：某角色 21 张里有背面/侧身图，双马尾 twintails 只有 20/21（95%），
        # 而它确实是角色的固定特征。
        warnings.append(f"特征「{tag}」只在 {c}/{total} 张出现（{c/total:.0%}）—— "
                        "强绑定只锁「张张都有」的词，所以它不会被自动锁定。"
                        "常见原因不是你的数据集不一致，而是视角遮挡让自动打标漏标"
                        "（侧身 / 背面 / 远景图上看不到该特征）。"
                        "若它确实是这个角色的固定特征：打开「标签统计」→ 选中它 → "
                        "点「★ 锁进固定前缀」手动锁定。")
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
    if trigger_only:
        # 概念模式：前缀只放 trigger；100% 一致的标签只给警告，不锁进前缀
        prefix = list(trig_tags)
        for _t in info["consistent"]:
            warnings.append(
                f"标签「{_t}」在训练集里 100% 出现——会被 trigger 一起吸收（换场景/换人时可能跟着变）；"
                "建议增加该维度的多样性，或确认它就是要绑定的概念本身")
    else:
        prefix = trig_tags + list(info["consistent"])
    if len(prefix) <= len(trig_tags):
        if trigger_only and info["consistent"]:
            logf(f"[强绑定] 概念模式：固定前缀只放 trigger（keep_tokens={max(1, len(trig_tags))}）；"
                 f"另有 {len(info['consistent'])} 个 100% 一致标签未锁进前缀（已给一致性警告）")
        elif not trigger_only:
            # 自动模式 + 没有任何标签「张张都有」→ 前缀里只剩 trigger 本身，
            # **强绑定等于没生效**。旧实现在这里一个字都不打，用户只能猜。
            # 2026-09-16 用户实测：单写 trigger 唤不出角色，于是怀疑"强绑定不生效" ——
            # 他的判断是对的，但日志里没有任何东西能确认，只能去问别的 AI。
            _tot = info["total"]
            logf("[强绑定] ⚠ 没有可锁定的特征 —— %d 张图里没有任何标签是「张张都有」的，"
                 "所以固定前缀里只有 trigger 本身，强绑定等于没生效："
                 "单写 trigger 不会带出角色的固定特征。" % _tot)
            if info["near"]:
                _txt = "、".join("%s %d/%d" % (t, c, _tot) for t, c in info["near"][:6])
                logf("[强绑定]   覆盖率最高的一批（都不到 100%，因此未被锁定）：" + _txt)
            logf("[强绑定]   想让 trigger 单独就能唤出角色，二选一：")
            logf("[强绑定]     ① 统一训练集特征（例如这个角色都同一发色 / 都戴帽），重跑预处理；")
            logf("[强绑定]     ② 打开「标签统计」，选中上面这些特征 → 点「★ 锁进固定前缀」"
                 "手动锁定它们（下次预处理生效）。")
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
    if trigger_only:
        logf(f"[强绑定] 概念模式：固定前缀只放 trigger（keep_tokens={keep}）：{', '.join(prefix)}")
    else:
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


def _wd14_model_roots():
    """两个模型根目录（同一个模型可能躺在任一处）：

      ① **程序目录** `wd14_tagger_model/` —— 兼容**已装的老版本**（老安装包里内置过模型 ✓，
         自 2026-08-15 起随包分发；新安装包不再内置，见 release.py 注释）；
      ② `%APPDATA%\\KohyaLoraTool\\wd14_tagger_model\\` —— **首次使用时下载到这里** ✓

    顺序即优先级：程序目录里的先命中。
    """
    kit = os.path.dirname(os.path.abspath(__file__))
    return [os.path.join(kit, "wd14_tagger_model"), _wd14_cache_root()]


def _wd14_ready_dir(key):
    """找**指定模型**，返回 (根目录, 是否就绪)。就绪 = 该根下已有`对应模型`的 model.onnx。

    注意两个模型的目录名不同（`SmilingWolf_wd-swinv2-tagger-v3` / `…moat-tagger-v2`），
    所以它们**天然共存**、互不覆盖 ✓
    """
    _, repo = resolve_wd14_model(key)
    _r = _wd14_repo_dirname(repo)
    roots = _wd14_model_roots()
    for d in roots:
        if os.path.isfile(os.path.join(d, _r, "model.onnx")):
            return d, True
    return roots[-1], False


def _wd14_model_dir(key=None):
    """（兼容入口）查找**指定模型**目录，返回 (目录, 是否就绪)。见 `_wd14_ready_dir`。"""
    return _wd14_ready_dir(key)


def lookup_wd14_model(key=None):
    """**只看机器上已就绪的**模型（不下载、不联网），返回 (key, repo, 根目录或 None)。

    优先用指定的模型；指定模型不在时，**退而用机器上已有的另一个模型** ✓

    ⚠️ 为什么必须回退（2026-09-17 事故，用户 RTX 2060 实测）：
      老安装包内置的是 `moat-v2`，而 v0.17.0 把默认模型换成了 `swinv2-v3` ——
      两者目录名不同，于是**老用户本地明明有一份能用的模型，`_wd14_model_dir` 也从不看它** ✗，
      直接判定「未下载」→ 触发下载 → 当时下载代码有个 `import time` 缺失的 bug → 失败 →
      **一路掉到兜底 caption（只剩 `1girl, solo`），训练效果白瞎** ✗✓
      本地有模型却不用，是纯粹的浪费 ✓
    """
    k0, _ = resolve_wd14_model(key)
    d, ready = _wd14_ready_dir(k0)
    if ready:
        return k0, WD14_MODELS[k0], d
    for k in WD14_MODELS:                       # 字典顺序即优先级（新的在前）
        if k == k0:
            continue
        d, ready = _wd14_ready_dir(k)
        if ready:
            return k, WD14_MODELS[k], d
    return k0, WD14_MODELS[k0], None


def pick_wd14_model(key=None, logf=print):
    """选定**本次实际使用**的打标模型，返回 (key, repo, 根目录或 None)。

    顺序：
      ① 指定模型已就绪 → 直接用 ✓
      ② 指定模型没有、但机器上有别的 → **仍先尝试下载指定模型** ✓
         （默认模型标签库更新、效果更好，能下就下 ✓）
      ③ 下载失败 → **回退用机器上已有的那个** ✓（标签库旧一些，但远好于兜底 caption）
      ④ 一个都没有 → None（调用方走兜底 caption）
    """
    k0, repo0 = resolve_wd14_model(key)
    k, repo, d = lookup_wd14_model(k0)
    if d and k == k0:
        return k, repo, d
    if d:
        logf("[WD14] 未找到 %s，先尝试下载…" % WD14_MODEL_LABELS.get(k0, k0))
    got = download_wd14_model(k0, logf)
    if got:
        return k0, repo0, got
    if d:
        logf("[WD14] ⚠ 指定模型（%s）下载失败，**改用机器上已有的「%s」打标** ——"
             % (WD14_MODEL_LABELS.get(k0, k0), WD14_MODEL_LABELS.get(k, k)))
        logf("[WD14]   标签库比新版旧一些，但**远好于兜底 caption**（那种只有 1girl, solo）✓")
        logf("[WD14]   想用新模型：联网后重跑一次即可自动补下 ✓")
        return k, repo, d
    return k0, repo0, None


def ensure_wd14_model(key=None, logf=print):
    """（兼容入口）确保打标模型就绪，返回模型根目录；失败返回 None。内部走 `pick_wd14_model`。

    两条打标路径（kohya 官方脚本 / 内置 onnx）都用它 ——
    这样「首次使用下载 / 回退」只有一处逻辑，且两条路径行为一致 ✓
    """
    return pick_wd14_model(key, logf)[2]


def run_wd14_tagger(output_dir, logf=print, script=None, batch_size=4, thresh=0.35,
                    model_key=None):
    """调用 kohya 官方 WD14 打标脚本，为 output_dir 里每张图生成 .txt 标签。

    返回是否成功。失败时由调用方做兜底处理，不会中断整体预处理。
    模型**首次使用时下载**（魔搭优先 → hf-mirror 兜底），之后离线可用 ✓

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
        # ⚠️ 别再说「缺 torch/onnxruntime」（2026-09-16 修正）：onxxruntime 最常见的故障
        # 是「装了但一 import 就崩」，说"缺"会把用户引向"装一个就行"——而装错变体
        # （gpu/directml）反而让冲突更严重。这里如实报出真实状态。
        _ok0, _kind0, _why0 = _probe_wd14_deps(sys.executable)
        if _kind0 == "crash":
            logf("[WD14] 没有可用的打标解释器：onnxruntime **装了但一导入就崩**（DLL 级故障）")
            logf("[WD14]   修法见下方「内置打标」段的自动修复与手工步骤（不是「缺包」）")
        elif _kind0 == "missing":
            logf("[WD14] 没有可用的打标解释器：确实缺 torch/onnxruntime（未安装）")
        else:
            logf("[WD14] 没有可用的打标解释器：%s" % (_why0 or "原因未知"))
        return False
    # kohya 官方脚本会 import library.dataset -> cv2 / imagesize 等；缺失会整批失败
    # （2026-09 用户日志：ModuleNotFoundError: No module named 'cv2'，只剩 1girl, solo 兜底标签）
    if not _ensure_wd14_script_deps(py, logf):
        logf("[WD14] 打标依赖（cv2/imagesize/onnxruntime）补装失败，官方脚本不可用，改用内置打标")
        return False
    # 隔离损坏图片：避免一张坏图导致整批打标中断
    _quarantine_corrupt_images(output_dir, logf)
    # ★ 首次使用时下载模型（魔搭优先 → hf-mirror 兜底）；已下好则秒回，不重复下载 ✓
    # 注意 `_key/_repo` **必须取 pick 的返回值**：指定模型缺失时会回退到机器上已有的另一个
    # 模型，若这里仍用 resolve_wd14_model(model_key) 拿 repo，就会与 model_dir 对不上 ✗
    _key, _repo, model_dir = pick_wd14_model(model_key, logf)
    if not model_dir:
        logf("[WD14] 打标模型不可用，官方脚本跳过（会走内置打标或兜底 caption）")
        return False
    logf(f"[WD14] 使用官方打标脚本: {script}")
    # ★ 明确打印本次**实际使用**的模型（回退时会与用户选的不同 —— 必须说出来 ✓）
    logf("[WD14] 官方打标使用模型：%s" % WD14_MODEL_LABELS.get(_key, _key))
    logf(f"[WD14] 打标解释器: {py}")
    logf(f"[WD14] 打标模型: {WD14_MODEL_LABELS.get(_key, _key)}（{model_dir}）")
    cmd = [
        py, script, output_dir,
        "--onnx", "--repo_id", _repo,
        "--model_dir", model_dir,
        "--batch_size", str(batch_size), "--thresh", str(thresh),
        "--remove_underscore", "--caption_extension", ".txt",
    ]
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



def _imgs_no_txt(output_dir):
    """输出目录里没有同名 .txt 的图片文件名。"""
    out = []
    for f in sorted(os.listdir(output_dir)):
        if os.path.splitext(f)[1].lower() in IMAGE_EXTS and not os.path.isfile(
                os.path.join(output_dir, os.path.splitext(f)[0] + ".txt")):
            out.append(f)
    return out


def _is_placeholder_caption(text, trigger, fallback):
    """判断 caption 是否上次打标失败留下的兜底。

    fallback 可以是一个文案，也可以是多个（动漫 / 写实两版兜底都要认得，
    否则用户切换出图风格后，上一版留下的兜底标签不会被自愈清掉）。
    """
    if not isinstance(fallback, str):
        return any(_is_one_placeholder(text, trigger, _fb) for _fb in (fallback or []))
    return _is_one_placeholder(text, trigger, fallback)


def _is_one_placeholder(text, trigger, fallback):
    """单个兜底文案的判定（仅 fallback 那几个词 + 可选 trigger 前缀）。"""
    fb = re.sub(r"\s+", " ", (fallback or "").strip().lower())
    if not fb:
        return False
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not t:
        return False
    if t == fb:
        return True
    # 去掉开头 trigger（可能多 trigger 词，逐词尝试；兼容 "trigger, xxx" / "trigger\nxxx"）
    changed = True
    while changed:
        changed = False
        for tg in re.split(r"[,，]+", trigger or ""):
            tg = tg.strip().lower()
            if not tg:
                continue
            m = re.match(r"^" + re.escape(tg) + r"[\s,，:：]*", t)
            if m:
                t = t[m.end():].strip()
                changed = True
                break
        if t == fb:
            return True
    return False


def _purge_placeholder_captions(output_dir, fallback, trigger, logf=print):
    """自愈：删掉上次打标失败留下的兜底 caption（如 1girl, solo），让 WD14 重新打标。"""
    n = 0
    for f in sorted(os.listdir(output_dir)):
        if os.path.splitext(f)[1].lower() not in IMAGE_EXTS:
            continue
        txt = os.path.join(output_dir, os.path.splitext(f)[0] + ".txt")
        if not os.path.isfile(txt):
            continue
        try:
            with open(txt, "r", encoding="utf-8") as fh:
                content = fh.read()
        except Exception:
            continue
        if _is_placeholder_caption(content, trigger, fallback):
            try:
                os.remove(txt)
                n += 1
            except Exception:
                pass
    if n:
        logf(f"[INFO] 检测到 {n} 张图片是上次打标失败留下的兜底标签，先清掉重新自动打标")
    return n


def _has_pymod(py, mod):
    try:
        r = subprocess.run([py, "-c",
                            "import sys, importlib.util;"
                            "sys.exit(0 if importlib.util.find_spec('%s') else 1)" % mod],
                           capture_output=True, text=True, timeout=120)
        return r.returncode == 0
    except Exception:
        return False


def _pip_install(py, pkgs, logf=print, timeout=900):
    """给指定解释器用国内镜像补装依赖（清代理 + 忽略 pip.ini）。返回是否成功。"""
    try:
        _env = dict(os.environ)
        for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            _env.pop(_k, None)
        _env["PIP_CONFIG_FILE"] = ""
        _env["NO_PROXY"] = "*"
        _env["no_proxy"] = "*"
        r = subprocess.run([py, "-m", "pip", "install", "--no-input", "--retries", "10",
                            "--timeout", "120", "--index-url",
                            "https://mirrors.ustc.edu.cn/pypi/simple/",
                            "--extra-index-url", "https://repo.huaweicloud.com/repository/pypi/simple/"]
                           + list(pkgs), env=_env,
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0
    except Exception:
        return False


def _ensure_wd14_script_deps(py, logf=print):
    """官方打标脚本依赖自检（cv2 / imagesize / onnxruntime / onnx），缺失自动补装。"""
    ok = True
    for mod, pkg in (("cv2", "opencv-python"), ("imagesize", "imagesize"),
                     ("onnxruntime", "onnxruntime"), ("onnx", "onnx")):
        if _has_pymod(py, mod):
            continue
        logf(f"[WD14] 补装打标依赖 {pkg}（{py}）…")
        if _pip_install(py, [pkg], logf):
            logf(f"[WD14] 已自动补装 {pkg}（{py}）")
        else:
            logf(f"[WD14] 自动补装 {pkg} 失败（{py}）")
            ok = False
    return ok


def _wd14_onnx_files(key=None):
    """定位**指定** WD14 模型的 onnx + 标签表；缺任一返回 (None, None)。

    **只看已有、不下载** ✓ 且 **不回退** ✓ —— 「用哪个模型」由 `pick_wd14_model` 决定，
    这里只负责按给定的 key 精确取文件 ✓

    ⚠️ 2026-09-19 更正（用户反馈「明明选了新打标器，好像又用了旧的」✓ 核对属实 ✗）：
       这里原先调 `lookup_wd14_model`（它会回退）✗ 于是只要机器上**存在另一个**模型
       （老安装包内置的 moat-v2），本函数就会返回**那个旧模型** →
       调用方 `_run_wd14_onnx` 看到 onnx_p 非空 → **跳过 pick** →
       **从不尝试下载用户选的 swinv2-v3**，且**没有任何日志说明** ✗
       → 「选了新的、实际用旧的」，而且静默 ✗ 与官方脚本那条路（走 pick，会下载）还不一致 ✗
    """
    _, repo = resolve_wd14_model(key)
    # ⚠️ `_wd14_ready_dir` 未就绪时也会返回一个目录（下载落点 roots[-1]），
    #    所以必须看 **ready**，不能只看 model_dir 是否为空 ✗
    model_dir, ready = _wd14_ready_dir(key)
    if not ready:
        return None, None
    repo_dir = os.path.join(model_dir, _wd14_repo_dirname(repo))
    onnx_p = os.path.join(repo_dir, "model.onnx")
    csv_p = os.path.join(repo_dir, "selected_tags.csv")
    if os.path.isfile(onnx_p) and os.path.isfile(csv_p):
        return onnx_p, csv_p
    return None, None


def _run_wd14_onnx(output_dir, logf=print, threshold=0.35, model_key=None):
    """内置 WD14 打标：onnxruntime 直读 model.onnx（CPU/GPU 自动），不依赖 kohya sd-scripts。

    适用：没装第一引擎（找不到官方打标脚本）、或官方脚本环境损坏（缺 cv2 等）的机器。
    预处理 / 阈值 / 输出格式与 kohya 官方 tag_images_by_wd14_tagger 的 default_format 一致
    （pad 白边到正方形 -> resize 448 -> 只取 general/character，>threshold 的标签，下划线转空格）。
    """
    # ⚠️ 必须先「决定用哪个模型」再取文件 —— 不能先取文件再决定 ✗
    #   2026-09-19 修正：原先是 `_wd14_onnx_files(model_key)` 在前，而它会回退到机器上
    #   已有的旧模型 → 返回非空 → **下面的 pick 永远不执行** → 用户选的新模型（swinv2-v3）
    #   **从来不会被下载**，还静默用着旧模型 ✗（用户反馈「选了新的却用了旧的」✓ 属实）
    #   现在与官方脚本那条路一致：都由 pick_wd14_model 决定（会先尝试下载指定模型 ✓，
    #   下载失败才回退，且回退时会打印说明 ✓）
    _used_key, _used_repo, _used_dir = pick_wd14_model(model_key, logf)
    if not _used_dir:
        logf("[WD14] 内置打标：未找到 model.onnx/selected_tags.csv（模型未下载成功）")
        return False
    # ★ 明确打印本次**实际使用**的模型：以前用户只能靠猜（"好像又用了旧的"）✗
    logf("[WD14] 内置打标使用模型：%s" % WD14_MODEL_LABELS.get(_used_key, _used_key))
    onnx_p, csv_p = _wd14_onnx_files(_used_key)
    if not onnx_p:
        logf("[WD14] 内置打标：未找到 model.onnx/selected_tags.csv（模型未下载成功）")
        return False
    # 面包屑：onnxruntime / cv2 都是 native 代码，一旦硬崩（DLL 冲突 / AVX 不兼容 /
    # provider 初始化失败）**不是 Python 异常，try/except 拦不住，也没有 traceback** ——
    # 日志只会「停在某一行之后再无输出」。所以每个高风险步骤前都留一行，崩溃点一眼可见。
    # 2026-09-15 qionglora 用户实测：输出正好停在这条调用之后、下一行之前。
    logf("[WD14] 内置打标：正在加载 onnxruntime…")
    try:
        import onnxruntime as ort
    except Exception:
        logf("[WD14] 内置打标：当前解释器缺 onnxruntime，自动补装…")
        if not _ensure_onnx(sys.executable, logf):
            logf("[WD14] 内置打标：onnxruntime 补装失败，无法打标")
            return False
        try:
            import onnxruntime as ort
        except Exception:
            return False
    try:
        import numpy as np
        from PIL import Image
    except Exception as e:
        logf(f"[WD14] 内置打标：缺 numpy/PIL：{e}")
        return False
    try:
        import cv2
    except Exception:
        cv2 = None

    # 标签表：rating(前 4) + general + character（与官方 default_format 顺序一致）
    import csv
    try:
        with open(csv_p, "r", encoding="utf-8") as f:
            rows = [r for r in csv.reader(f)][1:]
        general = [r[1] for r in rows if r[2] == "0"]
        character = [r[1] for r in rows if r[2] == "4"]
    except Exception as e:
        logf(f"[WD14] 内置打标：读取标签表失败：{e}")
        return False

    targets = _imgs_no_txt(output_dir)
    if not targets:
        return True
    logf(f"[WD14] 内置打标（onnx）：{len(targets)} 张缺标签图片，模型 {os.path.basename(onnx_p)}")
    try:
        providers = [p for p in ("CUDAExecutionProvider", "ROCMExecutionProvider", "CPUExecutionProvider")
                     if p in ort.get_available_providers()]
        try:
            sess = ort.InferenceSession(onnx_p, providers=providers)
        except Exception:
            sess = ort.InferenceSession(onnx_p, providers=["CPUExecutionProvider"])
        iname = sess.get_inputs()[0].name
        ishp = sess.get_inputs()[0].shape
        H = int(ishp[1]) if len(ishp) >= 2 and ishp[1] else 448
        W = int(ishp[2]) if len(ishp) >= 3 and ishp[2] else 448
    except Exception as e:
        logf(f"[WD14] 内置打标：加载 onnx 模型失败：{e}")
        return False

    def _prep(path):
        image = Image.open(path)
        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
            image = image.convert("RGBA")
        elif image.mode != "RGB":
            image = image.convert("RGB")
        if image.mode == "RGBA":
            bg = Image.new("RGB", image.size, (255, 255, 255))
            bg.paste(image, mask=image.split()[3])
            image = bg
        arr = np.array(image)[:, :, ::-1].astype(np.float32)  # RGB->BGR
        size = max(arr.shape[0:2])
        pad_x, pad_y = size - arr.shape[1], size - arr.shape[0]
        pad_l, pad_t = pad_x // 2, pad_y // 2
        arr = np.pad(arr, ((pad_t, pad_y - pad_t), (pad_l, pad_x - pad_l), (0, 0)),
                     mode="constant", constant_values=255)
        h, w = arr.shape[0:2]
        if h >= H and w >= W:
            if cv2 is not None:
                arr = cv2.resize(arr, (W, H), interpolation=cv2.INTER_AREA)
            else:
                arr = np.asarray(Image.fromarray(arr[:, :, ::-1].astype(np.uint8)).resize(
                    (W, H), Image.LANCZOS))[:, :, ::-1].astype(np.float32)
        else:
            arr = np.asarray(Image.fromarray(arr[:, :, ::-1].astype(np.uint8)).resize(
                (W, H), Image.LANCZOS))[:, :, ::-1].astype(np.float32)
        return arr

    tagged = 0
    done = 0
    total = len(targets)
    for f in targets:
        done += 1
        stem = os.path.splitext(f)[0]
        txt = os.path.join(output_dir, stem + ".txt")
        try:
            img_arr = _prep(os.path.join(output_dir, f))
            probs = sess.run(None, {iname: img_arr[None, ...]})[0][0]
            names = []
            seen = set()
            for i, p in enumerate(probs[4:]):
                tag = None
                if i < len(general):
                    if p >= threshold:
                        tag = general[i]
                elif (i - len(general)) < len(character):
                    if p >= threshold:
                        tag = character[i - len(general)]
                if not tag:
                    continue
                tag = tag.replace("_", " ") if len(tag) > 3 else tag
                low = tag.lower()
                if low in seen:
                    continue
                seen.add(low)
                names.append(tag)
            if names:
                with open(txt, "w", encoding="utf-8") as fh:
                    fh.write(", ".join(names) + "\n")
                tagged += 1
            if done % 5 == 0 or done == total:
                logf(f"[WD14] 内置打标进度：{done}/{total}（已写 {tagged} 张）")
        except Exception as e:
            logf(f"[WD14] 内置打标失败（{f}）：{e}")
    logf(f"[WD14] 内置打标完成：为 {tagged}/{total} 张图片生成标签")
    return tagged > 0


def _classify_ort_probe(rc, out):
    """把「探测 onnxruntime」的结果分类成人类可读的原因（纯函数，便于单测）。

    返回 (ok, detail)：
      · ok=True  → 能正常 import
      · ok=False → detail 指出是「native 崩溃 / 未安装 / 加载失败」中的哪一种

    为什么必须分类：三种情况的**修法完全不同** ——
      · native 崩溃 → 重装 onnxruntime、不行就重建训练环境（DLL 级故障，`import` 就死）
      · 未安装     → pip 装上即可
      · 加载失败   → 看报错（版本不匹配等）
    混为一谈就会给出错的修复指引。
    """
    out = (out or "").strip()
    if rc == 0 and "ORT_OK" in out:
        return True, ""
    if not out:
        # 零输出 + 非零退出 = 进程被 native 崩溃直接带走（DLL 装载失败 / VC 运行库缺失 /
        # 包半损坏）。**没有 traceback**，最容易被误判成「缺包」——
        # 2026-09-15 qionglora 用户实测就是这一类（cmd 里闪退、直接回提示符）。
        return False, ("import 阶段直接崩溃（退出码 %s、零输出）→ DLL 级故障，没有 traceback"
                       % rc)
    _last = out.splitlines()[-1].strip()
    if "No module named" in out:
        return False, "未安装（%s）" % _last
    return False, "加载失败（退出码 %s）：%s" % (rc, _last)


def _probe_onnxruntime_import(vpy, logf=print, timeout=180):
    """探测 onnxruntime 能否正常 import，并区分「崩溃 / 未安装 / 加载失败」。

    为什么必须放子进程：`import onnxruntime` 若发生 native 崩溃（DLL 加载失败 / VC 运行库缺失 /
    包半损坏），**不是 Python 异常** —— 在进程内 import 会直接把当前整个进程带走，
    `try/except Exception` 一个字都拦不住，也不会留下 traceback。

    2026-09-15 qionglora 用户实证（cmd 手工验证）：
        venv\\Scripts\\python.exe -c "import onnxruntime; ..."   → 闪退、零输出、直接回提示符
        venv\\Scripts\\python.exe -c "import cv2; ..."           → ModuleNotFoundError（普通缺包）
    即：cv2 只是没装（代码本就有处理），**真正的杀手是 onnxruntime 的 import 崩溃**。

    返回 (ok, detail)。
    """
    if not vpy:
        return False, "拿不到解释器路径"
    code = "import onnxruntime; print('ORT_OK', onnxruntime.__version__)"
    try:
        r = subprocess.run([vpy, "-c", code], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except Exception as e:
        return False, "探测异常：%s" % e
    return _classify_ort_probe(r.returncode, (r.stdout or "") + (r.stderr or ""))


def _run_wd14_onnx_isolated(output_dir, logf=print, threshold=0.35, model_key=None):
    """在**独立子进程**里跑内置打标 —— 隔离 native 硬崩。

    背景（2026-09-15 qionglora 用户实测）：`_run_wd14_onnx` 里的 `import onnxruntime`
    / 模型加载都是 native 代码，一旦硬崩（DLL 冲突 / AVX 不兼容 / provider 初始化失败）
    **不是 Python 异常，try/except 拦不住、也没有 traceback**，会把整个 preprocess.py
    一起带走 —— 而此刻**图片其实已经处理好了，只差标签**。
    用户看到的是「预处理失败」，实际损失的是整批图片的成果（本次就是 18 张）。

    隔离后：崩了只损失标签（走既有的兜底 caption），预处理成果全部保留。

    子进程的 stdout/stderr **直接继承**父进程 —— 父进程已被工具接管成管道，
    输出自然流进日志；配合 build_env() 的 PYTHONUNBUFFERED=1，崩溃前的内容也不会丢。
    """
    if not sys.executable:
        logf("[WD14] 内置打标：拿不到解释器路径，回退进程内执行")
        return _run_wd14_onnx(output_dir, logf=logf, threshold=threshold, model_key=model_key)
    # 显式把脚本目录作为 argv 传进去并用 sys.path.insert，**不依赖 PYTHONPATH 传递** ——
    # 环境变量在某些宿主（测试框架 / 被清过 env 的调用链）里不保证生效，
    # 那样子进程会直接 ModuleNotFoundError 而对生产行为毫无帮助。
    _here = os.path.dirname(os.path.abspath(__file__))
    # argv[4] = 打标模型选项（空串 = 用默认模型，见 resolve_wd14_model）
    code = ("import sys; sys.path.insert(0, sys.argv[3]);"
            "import preprocess as P;"
            "sys.exit(0 if P._run_wd14_onnx(sys.argv[1], threshold=float(sys.argv[2]),"
            " model_key=(sys.argv[4] or None)) else 1)")
    env = dict(os.environ)
    env["PYTHONPATH"] = _here          # 双保险
    env["PYTHONUNBUFFERED"] = "1"
    logf("[WD14] 内置打标：在独立子进程中运行（隔离 onnxruntime 的 native 崩溃）…")
    try:
        rc = subprocess.run([sys.executable, "-c", code, output_dir, str(threshold), _here,
                             model_key or ""], env=env, timeout=1800).returncode
    except Exception as e:
        logf(f"[WD14] ⚠ 内置打标子进程启动失败：{e}；改用兜底标签继续")
        return False
    if rc != 0:
        logf(f"[WD14] ⚠ 内置打标子进程未完成（退出码 {rc}）。"
             "可能是依赖、模型、逐图推理失败或 native 崩溃；请查看上方 WD14 日志。"
             "图片处理结果不受影响，缺少的标签将使用兜底 caption。")
        # 主动定位 + 给出可执行修复步骤。对着空白日志发呆正是「零门槛」的反面。
        _ok_ort, _why_ort = _probe_onnxruntime_import(sys.executable)
        if _ok_ort:
            logf("[WD14] 定位：onnxruntime 可正常导入；请检查上方模型加载、逐图推理或写入错误。")
        else:
            logf(f"[WD14] 定位：onnxruntime 不可用 —— {_why_ort}")
            # ---- 自动修复一次并重试（2026-09-16 新增）----
            # 以前这里只**打印**让用户手打的 pip 命令。实测（qiansui 用户）：
            # 用户看不懂那句命令，去问了另一个 AI，在 cpu / gpu 两个变体之间来回折腾
            # 几小时 —— 而最后修好的动作正好就是这里原本给的那条。
            # 工具既然知道怎么修，就该自己修。
            logf("[WD14] 正在自动修复 onnxruntime 并重试一次打标…")
            _fixed = _ensure_onnx(sys.executable, logf)
            if _fixed:
                logf("[WD14] onnxruntime 已修复，自动重试内置打标…")
                try:
                    _rc2 = subprocess.run([sys.executable, "-c", code, output_dir,
                                           str(threshold), _here, model_key or ""],
                                          env=env, timeout=1800).returncode
                except Exception as _e2:
                    _rc2 = -1
                    logf(f"[WD14] ⚠ 重试启动失败：{_e2}")
                if _rc2 == 0:
                    logf("[WD14] ✓ 修复后重试成功，标签已正常生成")
                    return True
                logf(f"[WD14] ⚠ 修复后重试仍失败（退出码 {_rc2}）")
            logf("[WD14]   手工修复步骤（按顺序试，多数情况第 1 条即可）：")
            logf("[WD14]     1) 清干净重装 —— **只装 CPU 版**，不要装 onnxruntime-gpu / directml：")
            logf("[WD14]        三个变体装进同一个 onnxruntime 目录，混装/残留正是"
                 "import 就崩的主因：")
            logf(f'[WD14]          "{sys.executable}" -m pip uninstall -y onnxruntime onnxruntime-gpu')
            logf(f'[WD14]          "{sys.executable}" -m pip install --no-cache-dir onnxruntime')
            logf("[WD14]     2) 第 1 条无效 → 安装/修复 **Microsoft Visual C++ 运行库**")
            logf("[WD14]        （0xC0000005 的经典根因；搜 “vc_redist.x64” 装官方最新版），装完重启")
            logf("[WD14]     3) 仍无效 → 重跑【② 安装训练内核】重建训练环境（会装匹配的版本）")
            logf("[WD14]   验证命令（**注意看最后一行的退出码**；只有 A 没有 B 就是崩了）：")
            logf(f'[WD14]        "{sys.executable}" -c "print(\'A\'); '
                 'import onnxruntime; print(\'B\', onnxruntime.__version__)"')
            logf("[WD14]        echo 退出码=%ERRORLEVEL%")
        logf("[WD14]   影响：本次未生成精细标签，缺标签图片用兜底 caption —— "
             "流程不中断，但训练效果会变差，建议修好后再训。")
        return False
    return True

def _run_wd14_auto(output_dir, logf=print, script=None, model_key=None):
    """自动打标总入口：官方脚本（GPU/CPU 回退）优先，失败/缺失改用内置 onnx 打标。

    model_key：打标模型选项（`swinv2-v3` / `moat-v2` / None=默认）。
    **任何未知值都会静默回退到默认模型**（见 resolve_wd14_model）——
    老用户升级后设置里没有这个键时走的就是这条路，不该有任何报错或阻塞 ✓
    """
    script = script or find_wd14_tagger()
    if script:
        if run_wd14_tagger(output_dir, logf=logf, script=script, model_key=model_key):
            return True
        logf("[WD14] 官方打标脚本失败，自动改用内置打标（onnx）重试…")
    else:
        logf("[WD14] 未找到 kohya 官方打标脚本，改用内置打标（onnx，不依赖第一引擎）…")
    return _run_wd14_onnx_isolated(output_dir, logf=logf, model_key=model_key)


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

def _probe_wd14_deps(py):
    """**真实**探测 py 能否 import torch + onnxruntime，并区分四种情况。

    返回 (ok, kind, detail)，kind ∈ {"ok", "missing", "crash", "error"}。

    ⚠️ 为什么不能再用 `importlib.util.find_spec`（2026-09-16 修正）：
    find_spec 只回答「包在不在」，而 onnxruntime 最要命的故障形态恰恰是
    **「找得到、import 就死」**（DLL 级故障）。旧实现把这种状态判为「已就绪」，
    于是 `_ensure_onnx` 的自动补装**永远不会触发** —— 自愈能力形同虚设。

    实测（2026-09-16 qiansui 用户）：onnxruntime 装了但 import 即崩（0xC0000005、
    零输出），工具据此判「健康」→ 不修 → 只能靠日志里那句要用户手打的 pip 命令
    → 用户看不懂，去问了另一个 AI，在 cpu/gpu 两个变体之间来回折腾几小时，
    **最后修好的动作正好就是工具原本给的那条**。

    必须放子进程：native 崩溃不是 Python 异常，进程内 import 会把自己一起带走。
    """
    if not py:
        return False, "error", "拿不到解释器路径"
    code = ("import torch, onnxruntime;"
            "print('WD14_DEPS_OK', torch.__version__, onnxruntime.__version__)")
    try:
        r = subprocess.run([py, "-c", code], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
    except Exception as e:
        return False, "error", "探测异常：%s" % e
    return _classify_wd14_probe(r.returncode, (r.stdout or "") + (r.stderr or ""))


def _classify_wd14_probe(rc, out):
    """把探测结果分成「能用 / 装了但崩 / 没装 / 其它错误」四类。纯函数，便于单测。

    四类**修法完全不同**，混为一谈就会给出错的修复指引（2026-09-16 qiansui 用户的
    实际遭遇：明明只是"装了但导入就崩"，日志却说"缺 torch/onnxruntime"，
    把他引向了"再装一个"——而装错变体反而让冲突更严重）。
    """
    out = (out or "").strip()
    if rc == 0 and "WD14_DEPS_OK" in out:
        return True, "ok", (out.splitlines()[-1] if out else "")
    if not out:
        # 零输出 + 非零退出 = 被 native 崩溃直接带走（DLL 装载失败 / 变体混装残留 /
        # VC 运行库缺失）。**没有 traceback**，最容易被误判成「缺包」。
        return False, "crash", "import 阶段直接崩溃（退出码 %s、零输出）→ DLL 级故障" % rc
    _last = out.splitlines()[-1].strip()
    if "No module named" in out:
        return False, "missing", "未安装（%s）" % _last
    return False, "error", "导入失败（退出码 %s）：%s" % (rc, _last)


def _has_wd14_deps(py):
    """解释器是否真的能 import torch + onnxruntime（WD14 打标必需）。

    走真实 import 探测（见 `_probe_wd14_deps`），不用 find_spec 的乐观判断。
    """
    return _probe_wd14_deps(py)[0]


def _has_torch(py):
    """检查解释器是否有 torch（**只查存在性**，用于挑解释器，追求秒级）。

    这里保留 find_spec 是有意的权衡：它只用来"挑一个候选解释器"，
    真正决定能不能干活的是 `_probe_wd14_deps`（真实 import）。
    """
    try:
        r = subprocess.run([py, "-c", "import sys, importlib.util;" +
                            "sys.exit(0 if importlib.util.find_spec('torch') else 1)"],
                           capture_output=True, text=True, timeout=120)
        return r.returncode == 0
    except Exception:
        return False


# onnxruntime 的三个变体：它们装进**同一个 `onnxruntime` 模块目录**，
# 混装或残留旧变体的 capi/*.dll 正是「import 即崩」最常见的根因。
_ONNX_VARIANTS = ("onnxruntime", "onnxruntime-gpu", "onnxruntime-directml")


def _pip_install_onnx(py, logf=print, clean=False):
    """安装 onnxruntime；clean=True 时先清干净再装。返回是否真的可用。

    clean=True 的必要性（2026-09-16 修正）：`pip install --force-reinstall onnxruntime`
    只覆盖**自己这个包**的文件，装过 onnxruntime-gpu 时残留在 `onnxruntime/capi/`
    里的旧 DLL **不会被清掉** → import 继续崩。
    所以「清干净」= 卸载全部变体 → 删掉残留的 onnxruntime 目录 → 只装 CPU 版。

    为什么只装 CPU 版：WD14 打标用它做推理，CPU 版就够；而 gpu 版会引入
    CUDA/cuDNN 依赖，反而多一个崩点。**明确不建议用户装 gpu 变体。**
    """
    _env = dict(os.environ)
    for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        _env.pop(_k, None)
    _env["NO_PROXY"] = "*"
    try:
        if clean:
            for _v in _ONNX_VARIANTS:
                try:
                    subprocess.run([py, "-m", "pip", "uninstall", "-y", _v],
                                   env=_env, capture_output=True, text=True, timeout=600)
                except Exception:
                    pass
            # 卸载后目录里可能仍有残留（手工装过 / 中断过），直接抹掉
            try:
                r = subprocess.run(
                    [py, "-c", "import sys,os,site;"
                               "print(os.pathsep.join(p for p in site.getsitepackages() if p))"],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=120)
                for _d in (r.stdout or "").strip().split(os.pathsep):
                    _p = os.path.join(_d.strip(), "onnxruntime")
                    if _d.strip() and os.path.isdir(_p):
                        shutil.rmtree(_p, ignore_errors=True)
                        logf("[WD14]   已清除残留目录：%s" % _p)
            except Exception:
                pass
        try:
            r = subprocess.run([py, "-m", "pip", "install", "--no-input", "--retries", "10",
                                "--timeout", "120", "--index-url",
                                "https://mirrors.ustc.edu.cn/pypi/simple/",
                                "--extra-index-url", "https://repo.huaweicloud.com/repository/pypi/simple/",
                                "onnxruntime", "onnx"], env=_env,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=900)
            if r.returncode != 0:
                _tail = "\n".join(((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-3:])
                logf("[WD14]   pip 安装失败（退出码 %s）：%s" % (r.returncode, _tail))
                return False
        except Exception as e:
            logf("[WD14]   pip 安装异常：%s" % e)
            return False
    except Exception as e:
        logf("[WD14]   安装流程异常：%s" % e)
        return False
    # 装完必须**真的 import 一次**才算成功 —— 只信 pip 的退出码是不够的
    _ok, _kind, _why = _probe_wd14_deps(py)
    if _ok:
        logf("[WD14] ✓ onnxruntime 已就绪（%s）" % (_why or ""))
        return True
    logf("[WD14] ⚠ 安装后仍不可用：%s" % _why)
    return False


def _ensure_onnx(py, logf=print):
    """确保解释器真能 import torch + onnxruntime（中科大源；原阿里云实测仅 0.12 MB/s）。

    「装了但导入就崩」时走**清干净重装**（见 `_pip_install_onnx`）——
    这正是 2026-09-16 那位用户手打 pip 折腾几小时才解决的问题，现在工具自己做。
    返回是否可用。
    """
    _ok, _kind, _why = _probe_wd14_deps(py)
    if _ok:
        return True
    if _kind == "crash":
        logf("[WD14] ⚠ onnxruntime 装了但一 import 就崩（DLL 级故障，没有 traceback）")
        logf("[WD14]   常见原因：onnxruntime 与 onnxruntime-gpu 混装，或残留了不匹配的 DLL。")
        logf("[WD14]   正在自动清理并重装（卸载全部变体 → 删除残留目录 → 只装 CPU 版）…")
        return _pip_install_onnx(py, logf, clean=True)
    logf("[WD14] %s，正在自动补装 onnxruntime/onnx…" % _why)
    return _pip_install_onnx(py, logf, clean=False)


def _ensure_hf_hub(py, logf=print):
    """解释器缺 huggingface_hub 时自动补装（WD14 打标脚本 import 时强制需要，缺了直接崩
    ModuleNotFoundError，2026-08-31 4080S 用户复现）。返回是否就绪（尽力而为）。"""
    try:
        r = subprocess.run([py, "-c", "import huggingface_hub"], capture_output=True, timeout=60)
        if r.returncode == 0:
            return True
    except Exception:
        pass
    try:
        _env = dict(os.environ)
        for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            _env.pop(_k, None)
        _env["NO_PROXY"] = "*"
        r = subprocess.run([py, "-m", "pip", "install", "--no-input", "--retries", "10",
                            "--timeout", "120", "--index-url",
                            "https://mirrors.ustc.edu.cn/pypi/simple/",
                            "--extra-index-url", "https://repo.huaweicloud.com/repository/pypi/simple/",
                            "huggingface_hub"], env=_env,
                           capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            r2 = subprocess.run([py, "-c", "import huggingface_hub"], capture_output=True, timeout=60)
            if r2.returncode == 0:
                logf(f"[WD14] 已自动补装 huggingface_hub（{py}）")
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
            _ensure_hf_hub(cur, logf)
            return cur, _sd_scripts_root()
    cands = []
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (here, os.path.dirname(here)):
        for sub in ("venv_amd", "musubi-venv", "ai_toolkit_venv", "fizgig_venv", "venv"):
            p = os.path.join(base, sub, "Scripts", "python.exe")
            if os.path.isfile(p) and os.path.abspath(p) != os.path.abspath(cur):
                cands.append(p)
    ap = os.environ.get("APPDATA", "")
    if ap:
        for sub in (r"KohyaLoraTool\venv_amd",
                    r"KohyaLoraTool\kohya_ss\musubi-venv",
                    r"KohyaLoraTool\kohya_ss\ai_toolkit_venv",
                    r"KohyaLoraTool\kohya_ss\fizgig_venv"):
            p = os.path.join(ap, sub, "Scripts", "python.exe")
            if os.path.isfile(p) and os.path.abspath(p) != os.path.abspath(cur):
                cands.append(p)
    for p in cands:
        if _has_torch(p):
            logf(f"[WD14] 当前解释器缺 torch，改用 {p} 打标")
            if _ensure_onnx(p, logf):
                _ensure_hf_hub(p, logf)
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


def crop_to_ratio(img, ratio_str):
    """按 宽:高 比例居中裁切；非法/超范围（1:2~2:1）返回原图不裁。"""
    m = re.match(r"^\s*(\d{1,3})\s*[:：]\s*(\d{1,3})\s*$", ratio_str)
    if not m:
        return img
    rw, rh = int(m.group(1)), int(m.group(2))
    if rw <= 0 or rh <= 0:
        return img
    ratio = rw / float(rh)
    if not (0.5 <= ratio <= 2.0):
        return img
    w, h = img.size
    if w / float(h) > ratio:   # 太宽 → 裁左右
        new_w = max(1, min(w, int(round(h * ratio / 2.0) * 2)))
        left = (w - new_w) // 2
        box = (left, 0, left + new_w, h)
    else:                       # 太高 → 裁上下
        new_h = max(1, min(h, int(round(w / ratio / 2.0) * 2)))
        top = (h - new_h) // 2
        box = (0, top, w, top + new_h)
    return img.crop(box)


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


def write_dataset_config(output_dir, config_path, resolution=512, batch_size=1,
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
    parser.add_argument("--style-target", choices=["anime", "realistic"], default="anime",
                        dest="style_target",
                        help="出图风格（画风模式兜底 caption 用）：anime=动漫（默认）/ realistic=写实")
    parser.add_argument("--trigger", default="", help="人物模式 trigger 触发词（插入每张 txt 第一行）")
    parser.add_argument("--reg-dir", default=None, help="人物模式正则数据集文件夹（写进 dataset_config 的 is_reg）")
    parser.add_argument("--repeats", type=int, default=1, help="训练图片重复次数 num_repeats（默认 1）")
    parser.add_argument("--keep-tokens", type=int, default=0,
                        help="caption 开头保留 token 数（人物模式建议 1 以保护 trigger）")
    parser.add_argument("--no-strong-bind", action="store_true",
                        help="人物模式关闭自动强绑定（默认开：自动把 trigger + 100% 一致特征词固定到标签开头）")
    parser.add_argument("--concept-type", default="",
                        help="概念类型：form/outfit/object/bodypart（概念模式用于清洗概念标签）")
    parser.add_argument("--concept-mode", dest="concept_mode", action="store_true", default=None,
                        help="明确声明这是概念模式（只有概念模式才清洗概念标签）")
    parser.add_argument("--no-concept-mode", dest="concept_mode", action="store_false",
                        help="明确声明不是概念模式（人物/画风模式绝不删除任何标签）")
    parser.add_argument("--no-clean-concept", action="store_true",
                        help="概念模式关闭「自动清洗概念标签」（默认开：删掉描述概念本身的标签，让 trigger 独占）")
    parser.add_argument("--dedup", action="store_true", help="按 MD5 跳过重复图片")
    parser.add_argument("--no-wd14", action="store_true", help="人物模式不自动调用 WD14 打标")
    # 打标模型选项。★ 刻意**不用 choices**：未知/空值要走「静默回退默认」而不是 argparse 报错退出
    # （老用户升级后设置里没有这个键，传过来的可能是空串 ✓）
    parser.add_argument("--wd14-model", default="",
                        help="打标模型：swinv2-v3（默认）/ moat-v2；留空或未知值都按默认处理")
    parser.add_argument("--min-size", type=int, default=0,
                        help="过滤过小图片：长边小于该像素则跳过（0=不过滤）")
    parser.add_argument("--blur-threshold", type=float, default=0,
                        help="过滤模糊图片：拉普拉斯方差小于该值则跳过（0=不过滤）")
    parser.add_argument("--square-crop", action="store_true", help="居中正方形裁剪后再缩放（等价 --crop-ratio 1:1）")
    parser.add_argument("--crop-ratio", default="",
                        help="按 宽:高 比例居中裁切后再缩放，如 3:4 / 9:16 / 1:1（默认不裁切，长边缩放保比例；范围 1:2~2:1）")
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
    # 画风模式兜底文案：按出图风格选（动漫 / 写实），见 DEFAULT_CAPTION_REALISTIC 注释
    style_fb = default_style_caption(getattr(args, "style_target", "anime"))
    if mode == "style" and getattr(args, "style_target", "anime") == "realistic":
        print("[INFO] 出图风格 = 写实：缺标签时使用写实兜底描述（不再是 anime cel-shading…）")

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
    _crop_ratio = args.crop_ratio or ("1:1" if args.square_crop else "")
    if _crop_ratio:
        print(f"[INFO] 按比例裁切: 开（居中裁剪为 {_crop_ratio}）")
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
    skip_names = []     # 因「已存在同名输出」而跳过的图（原先完全静默，用户看不到做了什么）
    for name in files:
        # name 可能是相对路径（子文件夹递归时用 / 分隔）；输出名用 __ 扁平化，避免重名
        _rel = name.replace("/", os.sep)
        _flat = name.replace("/", "__").replace("\\", "__")
        stem = os.path.splitext(_flat)[0]
        raw_img = os.path.join(input_dir, _rel)
        out_img = os.path.join(output_dir, stem + ".png")
        out_txt = os.path.join(output_dir, stem + ".txt")
        if os.path.exists(out_img) and not args.overwrite:
            # 原先这里是**纯静默 continue**：重跑时（典型场景：先单独点了「数据预处理」，
            # 再点「一键开始训练」——后者自带预处理，会把同一批图重跑一遍）
            # 会「18 张全部跳过、屏幕上一个字都没有」，用户以为在跑，实际什么都没做。
            # 2026-09-15 qionglora 用户实测：控制台 INFO 段之后直接跳到 [WD14]，
            # 中间一条 [OK] 都没有 —— 排查时非常容易误判成「图片处理失败」。
            skipped += 1
            skip_names.append(name)
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

            if _crop_ratio:
                img = crop_to_ratio(img, _crop_ratio)
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

    # 跳过汇总：重跑（典型：先单独点「数据预处理」，再点「一键开始训练」——
    # 后者自带预处理会把同一批图重跑一遍）时全部图都会被跳过。
    # 原先屏幕上一个字都没有，用户完全无法判断到底做了什么，
    # 还容易把「静默跳过」误读成「图片处理失败」（2026-09-15 qionglora 用户实测）。
    if skipped:
        print(f"[INFO] 输出目录已有 {skipped} 张同名图片，本次跳过未重新处理"
              f"（需要重做请清空输出目录，或改用覆盖模式）")
        for _n in skip_names[:5]:
            print(f"  [跳过] {_n}")
        if len(skip_names) > 5:
            print(f"  … 另有 {len(skip_names) - 5} 张同样跳过")
        if skipped == len(files):
            print("[INFO] 提示：本次全部图片都已存在，等价于「没有重新处理图片」，"
                  "只会补做打标/标签环节。")

    # ---- 人物模式：WD14 / 内置打标 / 兜底 / 还原自带标签 / 插入 trigger ----
    if mode == "character" and not args.no_caption and (ok + skipped):
        imgs_no_txt = _imgs_no_txt(output_dir)
        if not args.no_wd14:
            if not imgs_no_txt:
                # 自愈：上次打标失败留下的兜底标签（1girl, solo 等）清掉重新自动打标
                if _purge_placeholder_captions(output_dir, DEFAULT_CHARACTER_CAPTION, trigger):
                    imgs_no_txt = _imgs_no_txt(output_dir)
            if imgs_no_txt:
                _run_wd14_auto(output_dir, model_key=getattr(args, "wd14_model", None))
                missing_after_wd14 = _imgs_no_txt(output_dir)
                if missing_after_wd14:
                    _fill_missing_captions(output_dir, DEFAULT_CHARACTER_CAPTION)
                    print(f"[WARN] WD14 打标后仍有 {len(missing_after_wd14)} 张图片缺标签，已使用兜底 caption"
                          "（只有 1girl, solo 等极简词，训练效果会差；请查看上方日志排查后重试）")
            else:
                print("[INFO] 图片标签已齐全，跳过 WD14 打标。")
        else:
            _fill_missing_captions(output_dir, DEFAULT_CHARACTER_CAPTION)
            print("[INFO] 已跳过 WD14 自动打标（按设置），缺标签图片使用兜底 caption")
        # 还原原图自带的 .txt（完整保留用户标签）
        for stem, cap in user_captions.items():
            if cap.strip():
                with open(os.path.join(output_dir, stem + ".txt"), "w", encoding="utf-8") as f:
                    f.write(cap)
        # ---- 概念模式：清洗「描述概念本身」的标签（让 trigger 独占概念）----
        # 必须先确认「确实是概念模式」才清洗（2026-09-12 修）：
        # 界面「概念类型」默认 form 且在人物模式也照传，若只按 concept_type 判断，
        # 人物 LoRA 里 horns / animal ears / wings 这类人物特征会被静默删掉。
        # 未显式传 --concept-mode / --no-concept-mode 时沿用旧行为（按 concept_type 推断），
        # 保证手动命令行调用不受影响。
        _concept_on = getattr(args, "concept_mode", None)
        if _concept_on is None:
            _concept_on = bool(getattr(args, "concept_type", ""))
        if _concept_on and getattr(args, "concept_type", "") and not getattr(args, "no_clean_concept", False):
            _ct = args.concept_type
            _extra = set()
            if _ct in ("object", "bodypart"):
                # 词表穷举不了：改删训练集里 100% 一致的标签（已排除通用/姿势/场景词）
                try:
                    _info = analyze_caption_features(output_dir, trigger)
                    _extra = {_norm_tag(t) for t in _info["consistent"]} - set(CONCEPT_KEEP_TAGS)
                except Exception as _e:
                    print(f"[概念清洗] 统计 100% 一致标签失败（忽略）: {_e}")
            _removed_cnt, _n_changed = {}, 0
            for _f in sorted(os.listdir(output_dir)):
                if os.path.splitext(_f)[1].lower() not in IMAGE_EXTS:
                    continue
                _t = os.path.join(output_dir, os.path.splitext(_f)[0] + ".txt")
                if not os.path.isfile(_t):
                    continue
                try:
                    with open(_t, "r", encoding="utf-8-sig") as _fh:
                        _cur = _fh.read()
                except Exception:
                    continue
                _new, _rm = filter_concept_tags(_cur, _ct, extra_remove=_extra)
                if _new != _cur:
                    try:
                        with open(_t, "w", encoding="utf-8") as _fh:
                            _fh.write(_new)
                        _n_changed += 1
                    except Exception:
                        pass
                for _r in _rm:
                    _removed_cnt[_r] = _removed_cnt.get(_r, 0) + 1
            _cn = CONCEPT_TYPE_CN.get(_ct, _ct)
            if _removed_cnt:
                _top = sorted(_removed_cnt.items(), key=lambda kv: -kv[1])[:15]
                print(f"[概念清洗] {_cn}模式：已改写 {_n_changed} 张标签，删除 {len(_removed_cnt)} 种"
                      f"「概念本身」的标签（让 trigger 独占它）")
                print("[概念清洗] 删除清单：" + ", ".join("%s×%d" % (k, v) for k, v in _top)
                      + (" …" if len(_removed_cnt) > 15 else ""))
                print("[概念清洗] 若清单里有你不想删的（如想要的配饰），可在界面关闭「自动清洗概念标签」。")
            else:
                print(f"[概念清洗] {_cn}模式：没有需要删除的概念标签（标签里本来就没描述它）。")
        elif getattr(args, "concept_type", "") and not _concept_on:
            print("[概念清洗] 已跳过：当前不是概念模式（人物/画风模式不删除任何标签）")

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

    # ---- 画风模式：无画风描述词时，用 WD14 / 内置打标 + 过滤人物标签 ----
    if mode == "style" and not args.no_caption and (ok + skipped) and not style_caption.strip():
        imgs_no_txt = _imgs_no_txt(output_dir)
        if not args.no_wd14:
            if not imgs_no_txt:
                # 两版兜底都认（用户切过出图风格时，上一版留下的兜底标签也要能被自愈清掉）
                if _purge_placeholder_captions(
                        output_dir, (DEFAULT_CAPTION, DEFAULT_CAPTION_REALISTIC), trigger):
                    imgs_no_txt = _imgs_no_txt(output_dir)
            if imgs_no_txt:
                _run_wd14_auto(output_dir, model_key=getattr(args, "wd14_model", None))
                missing_after_wd14 = _imgs_no_txt(output_dir)
                if missing_after_wd14:
                    _fill_missing_captions(output_dir, style_fb)
                    print(f"[WARN] WD14 打标后仍有 {len(missing_after_wd14)} 张图片缺标签，已使用兜底 caption"
                          "（训练效果会差；请查看上方日志排查后重试）")
            else:
                print("[INFO] 图片标签已齐全，跳过 WD14 打标。")
        else:
            _fill_missing_captions(output_dir, style_fb)
            print("[INFO] 已跳过 WD14 自动打标（按设置），缺标签图片使用兜底 caption")
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
        fb = style_fb if mode == "style" else DEFAULT_CHARACTER_CAPTION
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

    # 画风模式自检：没填画风描述词时，若整批标签高度一致（<=2 种）说明自动打标没生效/全走兜底，显眼提醒
    if mode == "style" and (ok + skipped) and not (style_caption or "").strip() and not args.no_caption:
        try:
            _caps = set()
            for _f in sorted(os.listdir(output_dir)):
                if os.path.splitext(_f)[1].lower() not in IMAGE_EXTS:
                    continue
                _t = os.path.join(output_dir, os.path.splitext(_f)[0] + ".txt")
                if os.path.isfile(_t):
                    try:
                        with open(_t, "r", encoding="utf-8") as _fh:
                            _c = _fh.read().strip()
                    except Exception:
                        _c = ""
                    if _c:
                        _caps.add(_c)
            if len(_caps) == 1 and list(_caps)[0] == style_fb:
                print("[WARN] 画风模式自动打标未生效：所有标签都是统一的兜底描述（%s…），"
                      "请检查上方 WD14/内置打标日志；否则学不到逐张画风特征，效果会差。"
                      % style_fb[:40])
            elif len(_caps) <= 2:
                print("[WARN] 画风模式标签高度一致（%d 种），疑似自动打标未逐张生效；建议确认 WD14 正常后再训。" % len(_caps))
        except Exception:
            pass

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
