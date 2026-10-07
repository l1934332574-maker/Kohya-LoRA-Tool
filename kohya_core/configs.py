# -*- coding: utf-8 -*-
"""模式注册表配置（纯数据）：MODE_LABELS / ARCH_INFO / PRESETS / GUIDE_STEPS 等。
从 Kohya一键工具.py 渐进式拆分而来，原文件通过 `from kohya_core.configs import *` 使用。
"""

# ---------- 双模式预设 ----------

MODE_LABELS = {
    "style": "🎨 画风LoRA模式",
    "character": "👤 人物角色LoRA模式",
    "concept": "🦄 概念LoRA模式",
    "krea2": "🖼 Krea 2 图像LoRA",
    "krea2_at": "🖼 Krea2 图像LoRA（AI-Toolkit 引擎）",
    "anima_fz": "Anima LoRA（Fizgig）",
    "sdxl_fz": "SDXL LoRA（Fizgig）",
    "krea2_fz": "🖼 Krea2 图像LoRA（Fizgig 引擎）",
    "qwen21_fz": "🖼 Fizgig Qwen-Image-2.1",
    "h3_fz": "🎬 MiniMax H3 全模态（Fizgig 引擎）",
    "flux2": "🖼 FLUX.2 图像LoRA",
    "flux2_fz": "🖼 FLUX.2 Klein 9B（Fizgig 引擎）",
    "video": "🎬 视频LoRA（MiniMax H3）",
    "qwen_image": "🖼 Qwen-Image LoRA",
    "zimage": "🖼 Z-Image LoRA",
}
MODE_KEYS = ["style", "character", "concept", "krea2", "krea2_at", "krea2_fz", "qwen21_fz", "h3_fz", "flux2", "flux2_fz", "video", "qwen_image", "zimage", "anima_fz", "sdxl_fz"]

# Qwen-Image / Z-Image 的画风/人物子模式（训练类型切换）
AT_SUB_LABELS = {
    "character": "人物（保留全部标签）",
    "style": "画风（过滤人物标签）",
    "concept": "概念（形态/种族）",
}

# 概念模式的「概念类型」：决定【概念标签清洗依据】+【数据集提示 + 采样预览提示词】。
# · 形态/种族、服装：按词表删掉「描述概念本身」的标签；
# · 物品、身体部位：词表穷举不了，改删训练集里 100% 一致的标签。
# 清洗只在概念模式执行（人物/画风模式绝不删标签）；训练超参（yaml/toml）对所有类型一致。
CONCEPT_TYPE_LABELS = {
    "form": "🧜 形态/种族（美人鱼·半人马）",
    "outfit": "👗 服装（同款衣服）",
    "object": "🗿 物品（道具/武器）",
    "bodypart": "👁 身体部位（异色瞳/翅膀）",
}
CONCEPT_TYPE_KEYS = ["form", "outfit", "object", "bodypart"]

# 每种概念类型的数据集准备提示
CONCEPT_TYPE_DATASET_HINT = {
    "form": "15~30 张同一形态/种族（美人鱼/半人马/木偶人）：混不同画风/3D/实拍，只有形态保持一致",
    "outfit": "15~40 张同一款服装：务必换不同人脸/发色/画风/姿势/背景，只让这件衣服保持一致",
    "object": "15~40 张同一物品：换不同角度/光照/背景/画风，只让这个物品保持一致",
    "bodypart": "15~40 张同一身体部位（异色瞳/翅膀/尾巴等）：混不同脸型/发型/画风，只让该部位一致",
}

# 每种概念类型的采样预览提示词策略
#   subject=True  -> 按训练集标签自动补 1girl/1boy 主体
#   extra        -> 额外补词（人物系补 full body，部位系补 close-up，纯物品不加主体）
CONCEPT_TYPE_SAMPLE = {
    "form":     {"subject": True,  "extra": ["full body"]},
    "outfit":   {"subject": True,  "extra": ["full body"]},
    "bodypart": {"subject": True,  "extra": ["close-up"]},
    "object":   {"subject": False, "extra": []},
}


def concept_type_code(text):
    """界面文本 / 旧值 -> key；未知回退 form（兼容 key 直接传入）。"""
    t = (text or "").strip()
    if t in CONCEPT_TYPE_KEYS:
        return t
    for k, v in CONCEPT_TYPE_LABELS.items():
        if t == v:
            return k
    return "form"


def concept_type_sample(text):
    """取该概念类型的采样预览策略（未知回退 form）。"""
    return dict(CONCEPT_TYPE_SAMPLE.get(concept_type_code(text), CONCEPT_TYPE_SAMPLE["form"]))


# Z-Image 8G 快跑档开关（自动/开/关；仅 Z-Image 训练生效，见 write_at_image_yaml）
FAST_TIER_LABELS = {
    "auto": "自动（8G）",
    "on": "开（强制）",
    "off": "关",
}

def fast_tier_code(text):
    """界面文本 -> 档位 key（auto/on/off）。未知回退 auto。"""
    for _k, _v in FAST_TIER_LABELS.items():
        if _v == text:
            return _k
    return "auto"

# 架构注册表（标签中的 1024px 指架构规格；resolution 是新项目的训练默认值）
# family: sd=U-Net 架构；flux=DiT；anima=DiT+Qwen3
# tokenizers: [(model_id, kind)] kind='clip'=CLIPTokenizer, 'auto'=AutoTokenizer
ARCH_INFO = {
    "sd15": {
        "label": "SD1.5（512px）", "resolution": 512, "script": "train_network.py",
        "network_module": "networks.lora", "mixed": "fp16", "save_precision": "fp16",
        "min_bucket": 256, "max_bucket": 1024, "family": "sd",
        "min_vram": 8, "recommend_vram": 12, "hint": "",
        "tokenizers": [("openai/clip-vit-large-patch14", "clip")],
    },
    "sdxl": {
        "label": "SDXL 1.0（1024px 架构）", "resolution": 512, "script": "sdxl_train_network.py",
        "network_module": "networks.lora", "mixed": "bf16", "save_precision": "bf16",
        "min_bucket": 512, "max_bucket": 2048, "family": "sd",
        "min_vram": 12, "recommend_vram": 16,
        "hint": "⚠ SDXL 底模推荐 16G 及以上显存，否则容易显存不足。",
        "tokenizers": [("openai/clip-vit-large-patch14", "clip"), ("laion/CLIP-ViT-bigG-14-laion2B-39B-b160k", "clip")],
    },
    "flux": {
        "label": "FLUX.1（1024px 架构）", "resolution": 512, "script": "flux_train_network.py",
        "network_module": "networks.lora_flux", "mixed": "fp16", "save_precision": "bf16",
        "min_bucket": 256, "max_bucket": 1024, "family": "flux",
        "min_vram": 12, "recommend_vram": 16,
        "hint": "⚠ FLUX.1 是 12B 大模型，官方建议 16G 显存；8G 显存基本跑不动，请谨慎选择。",
        "tokenizers": [("openai/clip-vit-large-patch14", "clip"), ("google/t5-v1_1-xxl", "auto")],
    },
    "anima": {
        "label": "Anima（1024px 架构）", "resolution": 512, "script": "anima_train_network.py",
        "network_module": "networks.lora_anima", "mixed": "bf16", "save_precision": "bf16",
        "min_bucket": 512, "max_bucket": 2048, "family": "anima",
        "min_vram": 8, "recommend_vram": 12,
        "hint": "⚠ Anima 是 2026 最新架构（2B DiT + Qwen3 文本编码器）。8G 显存能跑但 1024px 会很慢（约 100 秒/步），建议降到 512/768，程序会自动开 block swap 省显存；推荐 12G+。",
        "tokenizers": [("Qwen/Qwen3-0.6B", "auto"), ("google/t5-v1_1-xxl", "auto")],
    },
    "flux2": {
        "label": "FLUX.2 klein（1024px 架构）", "resolution": 512, "script": "flux_2_train_network.py",
        "network_module": "networks.lora_flux_2", "mixed": "bf16", "save_precision": "bf16",
        "min_bucket": 256, "max_bucket": 1024, "family": "flux2",
        "min_vram": 8, "recommend_vram": 12,
        "hint": "⚠ FLUX.2 klein 4B 是 2026 新架构（4B DiT + Qwen3 文本编码器）：8G 显存可跑（需开省显存），推荐 12G+。训练用第二引擎 musubi，模型放 models/flux2/。",
        "tokenizers": [],
    },
}

BASE_TYPE_KEYS = list(ARCH_INFO.keys())
BASE_TYPE_LABELS = {k: v["label"] for k, v in ARCH_INFO.items()}
BASE_TYPE_HINTS = {k: v["hint"] for k, v in ARCH_INFO.items()}

# 内置预设参数（按 模式 × 底模类型；切换自动填充；手动改过的不再被覆盖，只有「恢复预设」重写）
#
# 结构 = 基线 + 架构覆盖（2026-09-12 收敛）：
#   旧版把 11 模式 × 4 架构 = 44 行平铺，其中 8 个模式（krea2 / krea2_fz / krea2_at / flux2 /
#   flux2_fz / video / qwen_image / zimage）的 4 行是逐字相同的，等于把同一份数据抄了 4 遍，
#   改一个数要动 4 处。现在只写一份基线 `_PRESET_BASE`，架构之间真正有差异时才用
#   `_PRESET_ARCH_DIFF` 覆盖。
#   运行期 `PRESETS` 的形状与旧版完全一致（mode -> arch -> 参数行），所以 preset_for 与界面的
#   「base_type not in PRESETS[mode]」判断、冒烟测试的完整性检查都不需要改。
_PRESET_ARCHS = ("sd15", "sdxl", "flux", "anima")

_PRESET_BASE = {
    "style": {"rank": "12", "alpha": "6", "unet_lr": "3e-4", "te_lr": "1.5e-4", "repeats": "5", "max_epochs": "8", "resolution": "512"},
    "character": {"rank": "24", "alpha": "12", "unet_lr": "1.5e-4", "te_lr": "8e-5", "repeats": "3", "max_epochs": "6", "resolution": "512"},
    "concept": {"rank": "32", "alpha": "16", "unet_lr": "1e-4", "te_lr": "5e-5", "repeats": "3", "max_epochs": "8", "resolution": "512"},
    "krea2": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4", "repeats": "2", "max_epochs": "16", "resolution": "512"},
    "anima_fz": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "0", "repeats": "2", "max_epochs": "16", "resolution": "512"},
    "sdxl_fz": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "0", "repeats": "2", "max_epochs": "16", "resolution": "512"},
    "krea2_fz": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4", "repeats": "2", "max_epochs": "16", "resolution": "512"},
    "qwen21_fz": {"rank": "8", "alpha": "8", "unet_lr": "1e-4", "te_lr": "1e-4", "repeats": "1", "max_epochs": "30", "resolution": "512", "fizgig_qwen_preset": "auto"},
    "h3_fz": {"rank": "8", "alpha": "8", "unet_lr": "2e-4", "te_lr": "1e-4", "repeats": "1", "max_epochs": "50", "resolution": "512", "video_frames": "56", "sample_interval": "5"},
    "krea2_at": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4", "repeats": "2", "max_epochs": "8", "resolution": "512"},
    "flux2": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4", "repeats": "2", "max_epochs": "16", "resolution": "512"},
    "flux2_fz": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4", "repeats": "2", "max_epochs": "16", "resolution": "512"},
    "video": {"rank": "32", "alpha": "32", "unet_lr": "2e-4", "te_lr": "1e-4", "repeats": "1", "max_epochs": "20", "resolution": "512", "video_steps": "2000", "video_frames": "73"},
    "qwen_image": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "1e-4", "repeats": "1", "max_epochs": "20", "resolution": "512", "video_steps": "2000"},
    "zimage": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "1e-4", "repeats": "1", "max_epochs": "20", "resolution": "512", "video_steps": "2000"},
}

# SD1.5 / SDXL 专用的「训练质量」增强（2026-09-12 新增，v3）：
#   noise_offset 改善暗部与对比度（训练集明暗差大时尤其明显），
#   min_snr_gamma 抑制高噪声步的过拟合。
#   两者只对 SD 系（epsilon / v-pred）有意义；FLUX / Anima 是 flow matching，
#   min_snr_gamma 会扭曲训练目标、noise_offset 也无意义，而且 sd-scripts 的
#   flux_train_network / anima_train_network 本身就不吃这两个参数 —— 所以只挂 sd15 / sdxl。
#   （第二~四引擎 musubi / AI-Toolkit / Fizgig 也不走 kohya 这条路，同样不挂。）
_PRESET_SD_EXTRA = {"noise_offset": "0.05", "min_snr_gamma": "5"}
_PRESET_SD_ARCHS = ("sd15", "sdxl")
_PRESET_SD_MODES = ("style", "character", "concept")

# 只在「该架构与基线不同」时才写；未列出的架构 = 直接用基线
_PRESET_ARCH_DIFF = {
    "style": {
        "sdxl": {"rank": "16", "alpha": "8", "unet_lr": "1.5e-4", "te_lr": "7.5e-5"},
        "flux": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "1e-4"},
        "anima": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "1e-4"},
    },
    "character": {
        "sdxl": {"rank": "32", "alpha": "16", "unet_lr": "7e-5", "te_lr": "4e-5"},
        "flux": {"rank": "16", "alpha": "16", "unet_lr": "8e-5", "te_lr": "8e-5"},
        "anima": {"rank": "16", "alpha": "16", "unet_lr": "8e-5", "te_lr": "8e-5"},
    },
}


def _build_presets():
    """基线 + 架构覆盖 -> 运行期 PRESETS（形状与旧版一致：mode -> arch -> 参数行）。"""
    out = {}
    for mode, base in _PRESET_BASE.items():
        out[mode] = {}
        for arch in _PRESET_ARCHS:
            row = dict(base)
            row.update(_PRESET_ARCH_DIFF.get(mode, {}).get(arch, {}))
            if mode in _PRESET_SD_MODES and arch in _PRESET_SD_ARCHS:
                row.update(_PRESET_SD_EXTRA)
            out[mode][arch] = row
    return out


PRESETS = _build_presets()

# 预设表版本：语义性改动（改数值 / 改口径）时 +1。
# 项目 json 里会存这个值；打开旧项目时若不一致，就列出差异问一次是否按新版重算，
# 避免"用户正在跑 / 要复现结果的项目被悄悄换掉参数"。
#   v1 -> v2（2026-09-12）：预设表改「基线 + 架构覆盖」；风格预设由"绝对覆盖 6 个框"改为
#                          "学习率乘数（动漫 ×0.85 / 写实 ×1.15）"。
#   v2 -> v3（2026-09-12）：SD1.5 / SDXL 新增 noise_offset 与 min_snr_gamma 两项质量增强。
#                          这两项旧项目里根本不存在，所以打开旧项目时会单独提示一次，
#                          选「否」就明确关掉它们，保证老项目训练口径一字不变。
#   v3 -> v4（2026-09-29）：所有模式的新项目默认训练分辨率统一为 512。
PRESET_VERSION = 4

RESOLUTIONS = {k: v["resolution"] for k, v in ARCH_INFO.items()}
QUANT_MODE_OPTIONS = {
    "anima_fz": ("auto", "bf16", "int8", "nf4"),
    "sdxl_fz": ("auto", "bf16", "int8", "nf4"),
    "krea2": ("auto", "fp8", "int8", "nf4"),
    "flux2": ("auto", "fp8", "int8", "nf4"),
    "krea2_fz": ("auto", "fp8", "int8", "nf4", "bf16"),
    "flux2_fz": ("auto", "fp8", "nf4", "bf16"),
    "qwen21_fz": ("auto", "bf16", "int8", "nf4"),
    "h3_fz": ("auto", "int8", "nf4", "hqq"),
}
MIN_IMAGES = {"anima_fz": 15, "sdxl_fz": 15, "style": 20, "character": 15, "concept": 15, "krea2": 15, "krea2_at": 15, "krea2_fz": 15, "qwen21_fz": 5, "h3_fz": 1, "flux2": 15, "flux2_fz": 15, "video": 3, "qwen_image": 15, "zimage": 15}   # 一键训练最少可用图片/视频数
MAX_AUTO_STEPS = 12000                          # 一键训练自动约束的最大总步数（防过拟合）

PARAM_LABELS = {
    "rank": "LoRA rank：决定可训练参数容量。增大通常增加显存和文件大小，不保证更像或更清晰；需结合数据和训练量选择。",
    "alpha": "LoRA alpha：与 rank 一起影响训练更新的缩放。模式预设各有不同，不等同于出图时的 LoRA 加载权重。",
    "unet_lr": "UNet 学习率：控制参数更新幅度，不代表每步运行速度。适合的数值取决于底模、优化器和数据；实际学习率还受预热与调度影响。",
    "te_lr": "文本编码器学习率：仅在文本编码器参与训练时生效。通常采用较低起始值；不同优化器不能直接比较数值。",
    "repeats": "图片重复次数：增加每轮中同一图片的出现次数。与样本数、轮数和批大小共同决定训练量；增加不保证效果更好。",
    "max_epochs": "最大epoch",
    "resolution": "训练分辨率",
    "video_steps": "训练步数",
    "fizgig_qwen_preset": "Fizgig Qwen 预设",
}

# 高级参数通俗中文提示（鼠标悬停显示）
PARAM_TIPS = {
    "rank": "LoRA rank：决定可训练参数容量。增大通常增加显存和文件大小，不保证更像或更清晰；需结合数据和训练量选择。",
    "alpha": "LoRA alpha：与 rank 一起影响训练更新的缩放。模式预设各有不同，不等同于出图时的 LoRA 加载权重。",
    "unet_lr": "UNet 学习率：控制参数更新幅度，不代表每步运行速度。适合的数值取决于底模、优化器和数据；实际学习率还受预热与调度影响。",
    "te_lr": "文本编码器学习率：仅在文本编码器参与训练时生效。通常采用较低起始值；不同优化器不能直接比较数值。",
    "repeats": "图片重复次数：增加每轮中同一图片的出现次数。与样本数、轮数和批大小共同决定训练量；增加不保证效果更好。",
    "max_epochs": "最大训练轮数：轮数越多学得越久，够用就好。",
    "resolution": "训练分辨率：512 最省显存最快，768 平衡，1024 画质最好。16G 显存跑 Krea2/SDXL 建议降到 768 或 512，防止爆显存。",
    "video_steps": "视频 LoRA 总训练步数：2000 左右较稳；步数过高会死记视频内容（过拟合）。上限 3000。",
    "video_frames": "视频 H3 按 17n+5 取帧（如 73）；H3 Fizgig 将此值用于预览采样，不会裁剪训练视频长度。",
    "fizgig_qwen_preset": "Fizgig 官方 Qwen-Image-2.1 训练预设；自动会按人物/画风/概念训练类型选择 Fast 或 Style。Fast 学习率由引擎在 2e-4~4e-4 内自适应。预设固定 rank、alpha 和学习率，轮数可调。",
}

# ---------- 参数适用范围（界面按当前模式置灰 + 提示 / 回归测试校验） ----------
# ★ 2026-09-19 用户反馈：「软件界面很多 UI 旁边的提示，其实跟实际都不符」✓ 核对后**属实** ✗
#
# 根因：界面控件**从不按模式隐藏**（高级参数区固定 8 格 + 全局提示词 + AMD + 只训UNet，
# 对 11 个模式一视同仁），但这些参数**很多只被第一引擎（train()）读取** ✗
#   例：`global_pos` 的提示写「训练时自动加到每张图片标签最前面」—— 而 8 个训练入口里
#       只有 train() 会处理它，Krea2 / FLUX.2 / 两个 Fizgig / 视频 / AI图像 **完全不读** ✗
#       且在那些模式下是**静默失效**（不报错、不提示），与打标掉兜底是同一类问题 ✗
#
# 本表是**唯一事实来源**：
#   · 界面按它 → 不适用的控件置灰，提示写明「本模式不支持（仅 …）」✓
#   · 回归测试按它 → 校验「代码实际读取该参数的训练入口」是否与之相符 ✓
#     （这样以后改引擎，提示会自动被校验，不会再漂 ✓ —— 与「用了没导入」的静态审计同思路）
#
# ⚠️ 只列**不是全模式通用**的参数；没列出的 = 所有模式都生效 ✓
#    填写依据：对 Kohya一键工具.py 做的「参数 × 训练入口」读取审计（2026-09-19）✓
PARAM_SCOPE = {
    # 第一引擎 kohya + 第三引擎 AI Toolkit AMD 后端会读取兼容模式开关。
    "te_lr": ("style", "character", "concept"),
    "train_text_encoder": ("style", "character", "concept"),
    "global_pos": ("anima_fz", "sdxl_fz", "style", "character", "concept"),
    "global_neg": ("anima_fz", "sdxl_fz", "style", "character", "concept"),
    "amd_mode": ("style", "character", "concept", "krea2_at", "qwen_image", "zimage"),
    "style_preset": ("style", "character", "concept"),
    "noise_offset": ("style", "character", "concept"),
    "min_snr_gamma": ("style", "character", "concept"),
    "reg_dir": ("style", "character", "concept"),
    "base_model": ("anima_fz", "sdxl_fz", "style", "character", "concept"),
    # 仅视频 / AI 图像（这两个引擎按「总步数」训练，不用 epoch）
    "fizgig_qwen_preset": ("qwen21_fz",),
    "video_steps": ("video", "qwen_image", "zimage"),
    "video_frames": ("video", "h3_fz"),
    # 量化适用于 Krea2 / FLUX.2 系及 Fizgig Qwen 2.1 / H3；块交换仅适用于前两系。
    "quant_mode": ("anima_fz", "sdxl_fz", "krea2", "krea2_fz", "flux2", "flux2_fz", "qwen21_fz", "h3_fz"),
    "blocks_to_swap": ("krea2", "krea2_fz", "flux2", "flux2_fz"),
    # ★ 2026-09-27 新增（用户诉求：训练器能改 bs 与梯度检查点）✗
    #   batch_size：留空 = 自动 1 ✓
    #     · 第一引擎(kohya) 画风/人物/概念：`train()` 里本就 `params.get("batch_size", 1)` ✓
    #     · 第二引擎(musubi) Krea2 / FLUX.2：写进 dataset_config.toml ✓
    #       （musubi 的训练批大小只认该配置 ✗，命令行没有 --batch_size ✓）
    "batch_size": ("style", "character", "concept", "krea2", "flux2"),
    #   gc（梯度检查点）：自动 = 显存未知或 <16G 时开启；可手动「开启 / 关闭」✓
    #     · 第一引擎(kohya) 与 第二引擎(musubi) 的 Krea2 / FLUX.2 都真读它 ✓
    #     · Fizgig（第四引擎）走 yaml 且固定开启 ✗ → 本参数对它不生效 ✓
    "gc": ("style", "character", "concept", "krea2", "flux2"),
    # 优化器：两个 Fizgig 引擎不读（用引擎自己的默认）
    "optimizer": ("anima_fz", "sdxl_fz", "style", "character", "concept", "krea2", "flux2",
                  "krea2_at", "video", "qwen_image", "zimage"),
    # compile：仅第一引擎 + Krea2 / FLUX.2 / Krea2(Fizgig)
    "compile": ("anima_fz", "sdxl_fz", "style", "character", "concept", "krea2", "flux2", "krea2_fz"),
    # repeats / max_epochs：视频与 AI 图像按步数训练，不用这两个
    "repeats": ("anima_fz", "sdxl_fz", "style", "character", "concept", "krea2", "krea2_at",
                "krea2_fz", "qwen21_fz", "h3_fz", "flux2", "flux2_fz"),
    "max_epochs": ("anima_fz", "sdxl_fz", "style", "character", "concept", "krea2", "krea2_at",
                   "krea2_fz", "qwen21_fz", "h3_fz", "flux2", "flux2_fz"),
}

# 模式短名（用于生成「仅 … 生效」这类人话提示）
MODE_SHORT = {
    "style": "画风", "character": "人物", "concept": "概念",
    "krea2": "Krea 2", "krea2_at": "Krea2(AI-Toolkit)", "krea2_fz": "Krea2(Fizgig)",
    "flux2": "FLUX.2", "flux2_fz": "FLUX.2(Fizgig)", "video": "视频",
    "qwen21_fz": "Qwen-Image-2.1(Fizgig)", "h3_fz": "H3(Fizgig)",
    "qwen_image": "Qwen-Image", "zimage": "Z-Image",
}


def param_supports(key, mode):
    """该参数在指定模式下是否真的生效（未登记 = 所有模式都生效 ✓）。"""
    scope = PARAM_SCOPE.get(key)
    return True if scope is None else (mode in scope)


def param_scope_text(key):
    """生成「仅 … 生效」的人话文案；全模式通用的返回 ""。"""
    scope = PARAM_SCOPE.get(key)
    if not scope:
        return ""
    return "仅 " + "、".join(MODE_SHORT.get(m, m) for m in scope if m in MODE_KEYS) + " 生效"

TRIGGER_HINT_CONCEPT = ("💡提示：填一个网上很少见到的英文单词（如 my_mer_01），出图时带上它，角色就会变成你训练的形态/种族（美人鱼/半人马/木偶人等）。\n"
                    "⚠ 训练集要混不同画风，否则 trigger 会把画风也绑进去。")

TRIGGER_HINT_CHARACTER = ("💡提示：填一个网上很少见到的英文单词，比如 my_oc01\n"
                          "不要用 girl 这种普通单词！\n"
                          "训练之后输入这个单词，就能画出这个人物。\n"
                          "不填也可以正常训练。")
TRIGGER_HINT_KREA2 = ("💡提示：填一个网上很少见到的英文单词（如 my_k2_01）\n"
                      "训练后输入这个单词，就能召唤这个角色/风格。\n"
                      "⚠ Krea 2 模式需先把模型放进 models/krea2/ 并安装第二引擎。")
TRIGGER_HINT_KREA2_AT = ("💡提示：填一个网上很少见到的英文单词（如 my_k2at_01）\n"
                       "训练后输入这个单词，就能召唤这个角色/风格。\n"
                       "\u26a0 Krea2（AI-Toolkit 引擎）需先安装第三引擎；底模用 bf16 RAW（models/krea2/raw.safetensors），\n"
                       "文本编码器/VAE 首次训练自动下载（约 9GB，国内镜像）。新项目默认 512px，16G 显存自动启用省显存优化。\n"
                       "不填也可以正常训练。")

TRIGGER_HINT_FLUX2 = ("💡提示：填一个网上很少见到的英文单词（如 my_f2_01）\n"
                      "训练后输入这个单词，就能召唤这个角色/风格。\n"
                      "⚠ FLUX.2 模式需先把模型放进 models/flux2/（DiT+文本编码器+VAE）并安装第二引擎；8G 显存可跑但较慢，推荐 12G+。")
TRIGGER_HINT_FLUX2_FZ = ("💡提示：填一个网上很少见到的英文单词（如 my_k9b_01）\n"
                        "训练后输入这个单词，就能召唤这个角色/风格。\n"
                        "\u26a0 Klein 9B（Fizgig 引擎）需先安装第四引擎，并把 Klein 9B 模型放进 models/flux2/\n"
                        "（fp8 DiT 约 9GB + Qwen3-8B 文本编码器约 15GB + VAE 320MB，国内镜像应用内下载）。\n"
                        "新项目默认 512px，可自行调高；12G 自动 NF4 + 块交换。NVIDIA/AMD 双平台。")
TRIGGER_HINT_STYLE = ("💡提示：填一个网上很少见到的英文单词，比如 my_style01\n"
                      "不要用 sketch 这种普通单词！\n"
                      "⚠重要：你的训练图片不能全是同一个人，不然画风套不到别的东西上。\n"
                      "训练之后输入这个单词，就能一键套用这个画风。\n"
                      "不填也可以正常训练。")
TRIGGER_HINT_VIDEO = ("💡提示：填一个网上很少见到的英文单词（如 my_oc01）\n"
                      "训练后输入这个单词，就能在视频里召唤这个角色/风格。\n"
                      "⚠ 视频 LoRA 需要 24G+ 显存（NVIDIA 显卡），且模型文件很大（40GB+）。\n"
                      "不填也可以正常训练。")
TRIGGER_HINT_AT = ("💡提示：填一个网上很少见到的英文单词（如 my_oc01）\n"
                   "训练后输入这个单词，就能召唤这个角色/风格。\n"
                   "不填也可以正常训练（但召唤效果弱）。")
DATASET_TIPS = {
    "anima_fz": "建议 15~30 张多角度、不同背景的图片。Fizgig 只接标准 28 层 Anima；2.9B / 40 层请选 Kohya。新项目默认 512px。",
    "sdxl_fz": "建议 15~30 张图片。使用完整 SDXL safetensors 底模，支持同架构第三方底模；这里只训练 UNet LoRA，文本编码器冻结。新项目默认 512px。",
    "style": "📌 数据集提示：建议 20~60 张图片，尽量多不同人物、不同姿态，避免五官固化。画风模式自动过滤强人物五官标签；可填画风专属触发词，不需要正则图。",
    "character": "📌 数据集提示：建议 15~30 张同一人物，多角度、不同服装，推荐设置唯一 trigger 触发词；可配合正则数据集防过拟合。",
    "concept": "📌 数据集提示：15~40 张「同一个概念」的图——形态/种族、同款服装、同一物品、同一身体部位都算；刻意混不同画风/人脸/姿势/背景，只有这个概念保持一致；trigger 是唯一共同元素，描述只写每张的变体。",
    "krea2": "📌 数据集提示：建议 15~30 张同一人物/风格，多角度多服装；训练前先把 Krea 2 模型放进 models/krea2/（RAW+VAE+文本编码器）。推荐 12G+ 显存。",
    "krea2_at": "📌 数据集提示：建议 15~30 张同一人物/风格，多角度多服装；训练前把 Krea 2 RAW 底模放进 models/krea2/（26GB，bf16 原版），文本编码器/VAE 首次训练自动下载。推荐 16G+ 显存；新项目默认 512px。",
    "krea2_fz": "📌 数据集提示：建议 15~30 张同一人物/风格，多角度多服装；训练前先把 Krea 2 模型放进 models/krea2/（RAW+VAE+文本编码器）。NVIDIA/AMD 双平台，8G 显存自动 NF4、12G+ 用 fp8。",
    "qwen21_fz": "📌 Fizgig Qwen-Image-2.1：准备至少 5 张清晰图片，放在原始图片文件夹；选择人物、画风或概念子模式。使用官方 Fizgig 预设，默认 512px，可自行调高。",
    "h3_fz": "📌 MiniMax H3 全模态：图片、视频、音频可放在同一目录或其子目录，每个文件配同名 .txt。准备至少 1 个样本；预处理只扫描，不会移动、转码或生成字幕。",
    "flux2": "📌 数据集提示：建议 15~30 张同一人物/风格，多角度多服装；训练前先把 FLUX.2 模型放进 models/flux2/（DiT+Qwen3 文本编码器+VAE，约 16GB，国内镜像）。8G 显存可跑（自动开省显存），推荐 12G+。",
    "flux2_fz": "📌 数据集提示：建议 15~30 张同一人物/风格，多角度多服装；训练前先把 Klein 9B 模型放进 models/flux2/（fp8 DiT + Qwen3-8B 文本编码器 + VAE）。推荐 16G+ 显存（12G 自动 NF4）。",
    "video": "📌 视频数据集提示：准备 3~10 段 3~10 秒的同角色/同风格视频（mp4），每段配一个同名 .txt 字幕描述内容。H3 模型 40GB+，训练推荐 24G 显存（NVIDIA）。",
    "qwen_image": "📌 数据集提示：15~30 张同一人物/风格图片。Qwen-Image 是 20B 大模型：16G 显存起步、24G 舒服（推荐）；首次训练自动下载模型约 40GB（国内镜像）。",
    "zimage": "📌 数据集提示：15~30 张同一人物/风格图片。Z-Image 是 8B 轻量模型：8G 可用（自动开快跑档）、12G 起步、16G 舒服；首次训练自动下载模型约 16GB（国内镜像）。",
}

OUTPUT_NAMES = {"anima_fz": "anima_fizgig_lora", "sdxl_fz": "sdxl_fizgig_lora", "style": "anime_style_lora", "character": "character_lora", "concept": "concept_lora", "krea2": "krea2_lora", "krea2_at": "krea2_at_lora", "krea2_fz": "krea2_fizgig_lora", "qwen21_fz": "qwen21_fizgig_lora", "h3_fz": "h3_fizgig_lora", "flux2": "flux2_lora", "flux2_fz": "flux2_fizgig_lora", "video": "h3_video_lora", "qwen_image": "qwen_image_lora", "zimage": "zimage_lora"}
# ---------- 新手引导步骤（数据驱动，按模式渲染） ----------
# 每步：id(唯一) / label(显示文案) / btn(按钮文字) / check(完成判定类型) / act(GUI 动作方法名) / tip(悬停提示)
# check 类型：
#   env=Git+Python 全局已装 | kohya/musubi/at=对应训练引擎全局已装
#   krea2_models/h3_models=对应模型文件齐全（全局，训练前必须）
#   base=当前项目已选底模 | raw=当前项目已选数据文件夹（图片/视频）
# 每种模式只列它真正需要的步骤：只训 H3 的小白不会看到 kohya/musubi。
GUIDE_STEPS = {
    "style": [
        {"id": "env", "label": "① 环境准备", "btn": "去准备", "check": "env", "act": "cmd_env",
         "tip": "安装 Git 和 Python（只需一次，全部项目通用）。"},
        {"id": "kohya", "label": "② 安装训练内核", "btn": "去安装", "check": "kohya", "act": "cmd_install",
         "tip": "安装 Kohya 训练内核（画风/人物模式需要，只需一次）。"},
        {"id": "base", "label": "③ 选择模型类型", "btn": "去设置", "check": "base", "act": "cmd_pick_model_type",
         "tip": "选择底模文件并确认模型类型（SD1.5 / SDXL / FLUX / Anima）；自动识别不准时可手动指定。"},
        {"id": "raw", "label": "④ 选择图片文件夹", "btn": "去选文件夹", "check": "raw", "act": "cmd_pick_raw",
         "tip": "选择原始图片文件夹（jpg/png/webp 等）。"},
    ],
    "character": [
        {"id": "env", "label": "① 环境准备", "btn": "去准备", "check": "env", "act": "cmd_env",
         "tip": "安装 Git 和 Python（只需一次，全部项目通用）。"},
        {"id": "kohya", "label": "② 安装训练内核", "btn": "去安装", "check": "kohya", "act": "cmd_install",
         "tip": "安装 Kohya 训练内核（画风/人物模式需要，只需一次）。"},
        {"id": "base", "label": "③ 选择模型类型", "btn": "去设置", "check": "base", "act": "cmd_pick_model_type",
         "tip": "选择底模文件并确认模型类型（SD1.5 / SDXL / FLUX / Anima）；建议和出图用的底模同系列。"},
        {"id": "raw", "label": "④ 选择图片文件夹", "btn": "去选文件夹", "check": "raw", "act": "cmd_pick_raw",
         "tip": "选择同一人物的图片文件夹（15~30 张）。"},
    ],
    "concept": [
        {"id": "env", "label": "① 环境准备", "btn": "去准备", "check": "env", "act": "cmd_env",
         "tip": "安装 Git 和 Python（只需一次，全部项目通用）。"},
        {"id": "kohya", "label": "② 安装训练内核", "btn": "去安装", "check": "kohya", "act": "cmd_install",
         "tip": "安装 Kohya 训练内核（概念模式需要，只需一次）。"},
        {"id": "base", "label": "③ 选择模型类型", "btn": "去设置", "check": "base", "act": "cmd_pick_model_type",
         "tip": "选择底模文件并确认模型类型（SD1.5 / SDXL / FLUX / Anima）；自动识别不准时可手动指定。"},
        {"id": "raw", "label": "④ 选择图片文件夹", "btn": "去选文件夹", "check": "raw", "act": "cmd_pick_raw",
         "tip": "15~30 张同一形态/种族（如美人鱼），刻意混不同画风，避免 trigger 把画风也吸进去。"},
    ],
    "krea2": [
        {"id": "env", "label": "① 环境准备", "btn": "去准备", "check": "env", "act": "cmd_env",
         "tip": "安装 Git 和 Python（只需一次，全部项目通用）。"},
        {"id": "musubi", "label": "② 安装第二引擎", "btn": "去安装", "check": "musubi", "act": "cmd_install_musubi",
         "tip": "安装第二引擎 musubi-tuner（Krea2 模式需要，只需一次）。"},
        {"id": "krea2_models", "label": "③ 下载 Krea2 模型", "btn": "去下载", "check": "krea2_models", "act": "cmd_dl_krea2_models",
         "tip": "应用内下载 Krea2 的 RAW/VAE/文本编码器 3 个文件（国内镜像，断点续传，下完自动识别）。"},
        {"id": "raw", "label": "④ 选择图片文件夹", "btn": "去选文件夹", "check": "raw", "act": "cmd_pick_raw",
         "tip": "选择图片文件夹（15~30 张同一人物/风格）。"},
    ],
    "krea2_fz": [
        {"id": "env", "label": "① 环境准备", "btn": "去准备", "check": "env", "act": "cmd_env",
         "tip": "安装 Git 和 Python（只需一次，全部项目通用）。"},
        {"id": "fizgig", "label": "② 安装第四引擎", "btn": "去安装", "check": "fizgig", "act": "cmd_install_fizgig",
         "tip": "安装第四引擎 Fizgig（Krea2 图像 LoRA，NVIDIA/AMD 双平台，只需一次）。"},
        {"id": "krea2_models", "label": "③ 下载 Krea2 模型", "btn": "去下载", "check": "krea2_models", "act": "cmd_dl_krea2_models",
         "tip": "应用内下载 Krea2 的 RAW/VAE/文本编码器 3 个文件（国内镜像，断点续传，下完自动识别）。"},
        {"id": "raw", "label": "④ 选择图片文件夹", "btn": "去选文件夹", "check": "raw", "act": "cmd_pick_raw",
         "tip": "选择图片文件夹（15~30 张同一人物/风格）。"},
    ],
    "krea2_at": [
        {"id": "env", "label": "① 环境准备", "btn": "去准备", "check": "env", "act": "cmd_env",
         "tip": "安装 Git 和 Python（只需一次，全部项目通用）。"},
        {"id": "at", "label": "② 安装第三引擎", "btn": "去安装", "check": "at", "act": "cmd_install_at",
         "tip": "安装第三引擎 AI Toolkit（Krea2 AT 模式需要，只需一次，需 NVIDIA 显卡）。"},
        {"id": "krea2_at_models", "label": "③ 下载 Krea2 模型", "btn": "去下载", "check": "krea2_at_models", "act": "cmd_dl_krea2_models",
         "tip": "应用内下载 Krea 2 RAW 底模（26GB，bf16 原版）；文本编码器/VAE 首次训练自动下载（约 9GB，国内镜像）。"},
        {"id": "raw", "label": "④ 选择图片文件夹", "btn": "去选文件夹", "check": "raw", "act": "cmd_pick_raw",
         "tip": "选择图片文件夹（15~30 张同一人物/风格）。"},
    ],
    "flux2": [
        {"id": "env", "label": "① 环境准备", "btn": "去准备", "check": "env", "act": "cmd_env",
         "tip": "安装 Git 和 Python（只需一次，全部项目通用）。"},
        {"id": "musubi", "label": "② 安装第二引擎", "btn": "去安装", "check": "musubi", "act": "cmd_install_musubi",
         "tip": "安装第二引擎 musubi-tuner（FLUX.2 模式需要，只需一次）。"},
        {"id": "flux2_models", "label": "③ 下载 FLUX.2 模型", "btn": "去下载", "check": "flux2_models", "act": "cmd_dl_flux2_models",
         "tip": "应用内下载 FLUX.2 的 DiT/文本编码器/VAE 3 个文件（约 16GB，国内镜像，断点续传，下完自动识别）。"},
        {"id": "raw", "label": "④ 选择图片文件夹", "btn": "去选文件夹", "check": "raw", "act": "cmd_pick_raw",
         "tip": "选择图片文件夹（15~30 张同一人物/风格）。"},
    ],
    "flux2_fz": [
        {"id": "env", "label": "① 环境准备", "btn": "去准备", "check": "env", "act": "cmd_env",
         "tip": "安装 Git 和 Python（只需一次，全部项目通用）。"},
        {"id": "fizgig", "label": "② 安装第四引擎", "btn": "去安装", "check": "fizgig", "act": "cmd_install_fizgig",
         "tip": "安装第四引擎 Fizgig（FLUX.2 Klein 9B 图像 LoRA，NVIDIA/AMD 双平台，只需一次）。"},
        {"id": "flux2_fz_models", "label": "③ 下载 Klein 9B 模型", "btn": "去下载", "check": "flux2_fz_models", "act": "cmd_dl_flux2_models",
         "tip": "应用内下载 Klein 9B 的 fp8 DiT/Qwen3-8B 文本编码器/VAE（约 25GB，国内镜像，断点续传，下完自动识别）。"},
        {"id": "raw", "label": "④ 选择图片文件夹", "btn": "去选文件夹", "check": "raw", "act": "cmd_pick_raw",
         "tip": "选择图片文件夹（15~30 张同一人物/风格）。"},
    ],
    "qwen21_fz": [
        {"id": "env", "label": "① 环境准备", "btn": "去准备", "check": "env", "act": "cmd_env",
         "tip": "安装 Git 和 Python（只需一次，全部项目通用）。"},
        {"id": "fizgig", "label": "② 安装第四引擎", "btn": "去安装", "check": "fizgig", "act": "cmd_install_fizgig",
         "tip": "安装第四引擎 Fizgig（Qwen-Image-2.1，支持 NVIDIA / AMD）。"},
        {"id": "qwen21_fz_models", "label": "③ 下载 Qwen-Image-2.1 模型", "btn": "去下载", "check": "qwen21_fz_models", "act": "cmd_dl_qwen21_fz_models",
         "tip": "下载 DiT、VAE、文本编码器和 Fizgig 训练适配器；speed LoRA 仅供预览，可选。"},
        {"id": "raw", "label": "④ 选择图片文件夹", "btn": "去选文件夹", "check": "raw", "act": "cmd_pick_raw",
         "tip": "选择至少 5 张图片；使用人物、画风或概念训练类型。"},
    ],
    "h3_fz": [
        {"id": "env", "label": "① 环境准备", "btn": "去准备", "check": "env", "act": "cmd_env",
         "tip": "安装 Git 和 Python（只需一次，全部项目通用）。"},
        {"id": "fizgig", "label": "② 安装第四引擎", "btn": "去安装", "check": "fizgig", "act": "cmd_install_fizgig",
         "tip": "安装第四引擎 Fizgig（MiniMax H3 图像/视频/音频混合 LoRA）。"},
        {"id": "h3_fz_models", "label": "③ 下载 H3 Fizgig 模型", "btn": "去下载", "check": "h3_fz_models", "act": "cmd_dl_h3_fz_models",
         "tip": "下载官方 int8 DiT、文本编码器和视频 VAE；音频 VAE 按数据集需要，可选适配器和 Turbo LoRA。"},
        {"id": "raw", "label": "④ 选择混合媒体文件夹", "btn": "去选文件夹", "check": "raw", "act": "cmd_pick_raw",
         "tip": "图片、视频和音频可混放；每个媒体文件需配同名 .txt，预处理按钮只扫描。"},
    ],
    "video": [
        {"id": "env", "label": "① 环境准备", "btn": "去准备", "check": "env", "act": "cmd_env",
         "tip": "安装 Git 和 Python（只需一次，全部项目通用）。"},
        {"id": "at", "label": "② 安装第三引擎", "btn": "去安装", "check": "at", "act": "cmd_install_at",
         "tip": "安装第三引擎 AI Toolkit（MiniMax H3 视频模式需要，只需一次，需 NVIDIA 显卡）。"},
        {"id": "h3_models", "label": "③ 下载 H3 模型", "btn": "去下载", "check": "h3_models", "act": "cmd_dl_h3_models",
         "tip": "应用内下载 MiniMax H3 的 DiT/文本编码器/VAE（约 40GB，断点续传），下完自动识别。"},
        {"id": "raw", "label": "④ 选择视频文件夹", "btn": "去选文件夹", "check": "raw", "act": "cmd_pick_raw",
         "tip": "选择视频数据集文件夹（3~10 段 mp4 + 同名 txt 字幕）。"},
    ],
    "qwen_image": [
        {"id": "env", "label": "① 环境准备", "btn": "去准备", "check": "env", "act": "cmd_env",
         "tip": "安装 Git 和 Python（只需一次，全部项目通用）。"},
        {"id": "at", "label": "② 安装第三引擎", "btn": "去安装", "check": "at", "act": "cmd_install_at",
         "tip": "安装第三引擎 AI Toolkit（Qwen-Image / Z-Image 模式需要，只需一次，需 NVIDIA 显卡）。"},
        {"id": "at_model", "label": "③ Qwen-Image 模型", "btn": "查看说明", "check": "at_model", "act": "cmd_at_model_help",
         "tip": "Qwen-Image 是 20B 大模型：16G 显存起步、24G 舒服（推荐）。首次训练自动下载约 40GB（国内镜像）。"},
        {"id": "raw", "label": "④ 选择图片文件夹", "btn": "去选文件夹", "check": "raw", "act": "cmd_pick_raw",
         "tip": "选择原始图片文件夹（15~30 张同一人物/风格）。"},
    ],
    "zimage": [
        {"id": "env", "label": "① 环境准备", "btn": "去准备", "check": "env", "act": "cmd_env",
         "tip": "安装 Git 和 Python（只需一次，全部项目通用）。"},
        {"id": "at", "label": "② 安装第三引擎", "btn": "去安装", "check": "at", "act": "cmd_install_at",
         "tip": "安装第三引擎 AI Toolkit（Qwen-Image / Z-Image 模式需要，只需一次，需 NVIDIA 显卡）。"},
        {"id": "at_model", "label": "③ Z-Image 模型", "btn": "查看说明", "check": "at_model", "act": "cmd_at_model_help",
         "tip": "Z-Image 是 8B 轻量模型：8G 可用（自动开快跑档）、12G 起步、16G 舒服。首次训练自动下载约 16GB（国内镜像）；训练用基础版，出图可配 Turbo。"},
        {"id": "raw", "label": "④ 选择图片文件夹", "btn": "去选文件夹", "check": "raw", "act": "cmd_pick_raw",
         "tip": "选择原始图片文件夹（15~30 张同一人物/风格）。"},
    ],
}





PY_MIN = (3, 10, 9)
PY_MAX = (3, 13, 0)


# 新建项目模板：只负责「模式 + 底模类型」，参数一律交给 PRESETS（三源合一，2026-09-12）。
#   旧版每个模板还带一份 `params`，而那 4 份 params 与 PRESETS 对应档「逐字相同」——
#   属于第二份事实来源，改预设表它不会跟着变，于是出现「动漫画风」模板 rank 16 与
#   风格预设「动漫」rank 32 互相打架。现在统一由 _apply_presets() 按模式+底模填。
#   （FLUX.2 人物 的 base_type 是占位值：flux2 模式的底模控件本就隐藏，取哪档结果相同。）
PROJECT_TEMPLATES = {
    "自定义": {
        "mode": "character",
        "base_type": "sdxl",
        "note": "从人物 + SDXL 起步；进入训练页后可切换训练模式、底模和参数。",
    },
    "SD1.5": {
        "mode": "character",
        "base_type": "sd15",
        "note": "使用 SD1.5 底模，默认人物训练；进入训练页后可切换人物、画风或概念模式。",
    },
    "SDXL": {
        "mode": "character",
        "base_type": "sdxl",
        "note": "使用 SDXL 底模，默认人物训练；进入训练页后可切换人物、画风或概念模式。",
    },
    "FLUX.1": {
        "mode": "character",
        "base_type": "flux",
        "note": "使用第一引擎 FLUX.1 底模，默认人物训练；进入训练页后可切换人物、画风或概念模式。",
    },
    "Anima": {
        "mode": "character",
        "base_type": "anima",
        "note": "使用 Anima 底模，默认人物训练；进入训练页后可切换人物、画风或概念模式。",
    },
    "FLUX.2 人物": {
        "mode": "flux2",
        "base_type": "sdxl",
        "note": "FLUX.2 klein 4B 人物/风格 LoRA：需第二引擎 + models/flux2/ 模型（约 16GB，国内镜像）。8G 显存可跑（自动开省显存），推荐 12G+。",
    },
    "Qwen-Image-2.1（Fizgig）": {
        "mode": "qwen21_fz",
        "base_type": "sdxl",
        "note": "第四引擎 Fizgig；使用 Qwen-Image-2.1 官方训练预设，模型放在 models/qwen_image21。",
    },
    "MiniMax H3 全模态（Fizgig）": {
        "mode": "h3_fz",
        "base_type": "sdxl",
        "note": "第四引擎 Fizgig；图片、视频、音频混合训练，媒体与同名 .txt 可放在同一原始目录或其子目录。",
    },
    # 保留旧名称供历史项目和旧调用方识别；新版下拉由现代 UI 隐藏这些细分模板。
    "画风 LoRA（SDXL）": {
        "mode": "style",
        "base_type": "sdxl",
        "note": "旧版兼容模板：SDXL 画风训练。",
        "visible": False,
    },
    "人物 LoRA（SDXL）": {
        "mode": "character",
        "base_type": "sdxl",
        "note": "旧版兼容模板：SDXL 人物训练。",
        "visible": False,
    },
    "画风 LoRA（SD1.5）": {
        "mode": "style",
        "base_type": "sd15",
        "note": "旧版兼容模板：SD1.5 画风训练。",
        "visible": False,
    },
}

# v7 ordinary-LoRA setup flow (shared by the modern workspace and Agent).
for _mode, _name in (("anima_fz", "Anima"), ("sdxl_fz", "SDXL")):
    GUIDE_STEPS[_mode] = [
        {"id": "env", "label": "① 环境准备", "btn": "去准备", "check": "env", "act": "cmd_env", "tip": "准备 Python / Git。"},
        {"id": "fizgig", "label": "② 安装 Fizgig v7", "btn": "去安装", "check": "fizgig", "act": "cmd_install_fizgig", "tip": "国内镜像优先；保留旧版本环境。"},
        {"id": "base", "label": "③ 选择底模 / 组件", "btn": "去设置", "check": "fizgig_new_models", "act": "cmd_pick_model_type", "tip": "选择已有底模；缺少的组件可在模型下载中准备。"},
        {"id": "raw", "label": "④ 选择图片文件夹", "btn": "去选择", "check": "raw", "act": "cmd_pick_raw", "tip": "选择训练图片文件夹。"},
    ]
