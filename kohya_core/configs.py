# -*- coding: utf-8 -*-
"""模式注册表配置（纯数据）：MODE_LABELS / ARCH_INFO / PRESETS / GUIDE_STEPS 等。
从 Kohya一键工具.py 渐进式拆分而来，原文件通过 `from kohya_core.configs import *` 使用。
"""

# ---------- 双模式预设 ----------

MODE_LABELS = {
    "style": "🎨 画风LoRA模式",
    "character": "👤 人物角色LoRA模式",
    "concept": "🦄 概念LoRA模式（形态/种族）",
    "krea2": "🖼 Krea 2 图像LoRA",
    "krea2_at": "🖼 Krea2 图像LoRA（AI-Toolkit 引擎）",
    "krea2_fz": "🖼 Krea2 图像LoRA（Fizgig 引擎）",
    "flux2": "🖼 FLUX.2 图像LoRA",
    "video": "🎬 视频LoRA（MiniMax H3）",
    "qwen_image": "🖼 Qwen-Image LoRA",
    "zimage": "🖼 Z-Image LoRA",
}
MODE_KEYS = ["style", "character", "concept", "krea2", "krea2_at", "krea2_fz", "flux2", "video", "qwen_image", "zimage"]

# Qwen-Image / Z-Image 的画风/人物子模式（训练类型切换）
AT_SUB_LABELS = {
    "character": "人物（保留全部标签）",
    "style": "画风（过滤人物标签）",
    "concept": "概念（形态/种族）",
}

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

# 架构注册表（对标秋叶：SD1.5 / SDXL / FLUX.1 / Anima）
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
        "label": "SDXL 1.0（1024px）", "resolution": 1024, "script": "sdxl_train_network.py",
        "network_module": "networks.lora", "mixed": "bf16", "save_precision": "bf16",
        "min_bucket": 512, "max_bucket": 2048, "family": "sd",
        "min_vram": 12, "recommend_vram": 16,
        "hint": "⚠ SDXL 底模推荐 16G 及以上显存，否则容易显存不足。",
        "tokenizers": [("openai/clip-vit-large-patch14", "clip"), ("laion/CLIP-ViT-bigG-14-laion2B-39B-b160k", "clip")],
    },
    "flux": {
        "label": "FLUX.1（1024px）", "resolution": 1024, "script": "flux_train_network.py",
        "network_module": "networks.lora_flux", "mixed": "fp16", "save_precision": "bf16",
        "min_bucket": 256, "max_bucket": 1024, "family": "flux",
        "min_vram": 12, "recommend_vram": 16,
        "hint": "⚠ FLUX.1 是 12B 大模型，官方建议 16G 显存；8G 显存基本跑不动，请谨慎选择。",
        "tokenizers": [("openai/clip-vit-large-patch14", "clip"), ("google/t5-v1_1-xxl", "auto")],
    },
    "anima": {
        "label": "Anima（1024px）", "resolution": 1024, "script": "anima_train_network.py",
        "network_module": "networks.lora_anima", "mixed": "bf16", "save_precision": "bf16",
        "min_bucket": 512, "max_bucket": 2048, "family": "anima",
        "min_vram": 8, "recommend_vram": 12,
        "hint": "⚠ Anima 是 2026 最新架构（2B DiT + Qwen3 文本编码器）。8G 显存能跑但 1024px 会很慢（约 100 秒/步），建议降到 512/768，程序会自动开 block swap 省显存；推荐 12G+。",
        "tokenizers": [("Qwen/Qwen3-0.6B", "auto"), ("google/t5-v1_1-xxl", "auto")],
    },
    "flux2": {
        "label": "FLUX.2 klein（1024px）", "resolution": 1024, "script": "flux_2_train_network.py",
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
PRESETS = {
    "style": {
        "sd15": {"rank": "12", "alpha": "6", "unet_lr": "3e-4", "te_lr": "1.5e-4",
                 "repeats": "5", "max_epochs": "8", "resolution": "512"},
        "sdxl": {"rank": "16", "alpha": "8", "unet_lr": "1.5e-4", "te_lr": "7.5e-5",
                 "repeats": "5", "max_epochs": "8", "resolution": "1024"},
        "flux": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "5", "max_epochs": "8", "resolution": "1024"},
        "anima": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "1e-4",
                  "repeats": "5", "max_epochs": "8", "resolution": "1024"},
    },
    "character": {
        "sd15": {"rank": "24", "alpha": "12", "unet_lr": "1.5e-4", "te_lr": "8e-5",
                 "repeats": "3", "max_epochs": "6", "resolution": "512"},
        "sdxl": {"rank": "32", "alpha": "16", "unet_lr": "7e-5", "te_lr": "4e-5",
                 "repeats": "3", "max_epochs": "6", "resolution": "1024"},
        "flux": {"rank": "16", "alpha": "16", "unet_lr": "8e-5", "te_lr": "8e-5",
                 "repeats": "3", "max_epochs": "6", "resolution": "1024"},
        "anima": {"rank": "16", "alpha": "16", "unet_lr": "8e-5", "te_lr": "8e-5",
                  "repeats": "3", "max_epochs": "6", "resolution": "1024"},
    },
    "concept": {
        "sd15": {"rank": "32", "alpha": "16", "unet_lr": "1e-4", "te_lr": "5e-5",
                 "repeats": "3", "max_epochs": "8", "resolution": "512"},
        "sdxl": {"rank": "32", "alpha": "16", "unet_lr": "1e-4", "te_lr": "5e-5",
                 "repeats": "3", "max_epochs": "8", "resolution": "1024"},
        "flux": {"rank": "32", "alpha": "16", "unet_lr": "1e-4", "te_lr": "5e-5",
                 "repeats": "3", "max_epochs": "8", "resolution": "1024"},
        "anima": {"rank": "32", "alpha": "16", "unet_lr": "1e-4", "te_lr": "5e-5",
                  "repeats": "3", "max_epochs": "8", "resolution": "1024"},
    },
    "krea2": {
        "sd15": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "2", "max_epochs": "16", "resolution": "1024"},
        "sdxl": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "2", "max_epochs": "16", "resolution": "1024"},
        "flux": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "2", "max_epochs": "16", "resolution": "1024"},
        "anima": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                  "repeats": "2", "max_epochs": "16", "resolution": "1024"},
    },
    "krea2_fz": {
        "sd15": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "2", "max_epochs": "16", "resolution": "512"},
        "sdxl": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "2", "max_epochs": "16", "resolution": "512"},
        "flux": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "2", "max_epochs": "16", "resolution": "512"},
        "anima": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                  "repeats": "2", "max_epochs": "16", "resolution": "512"},
    },
    "krea2_at": {
        "sd15": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "2", "max_epochs": "8", "resolution": "1024"},
        "sdxl": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "2", "max_epochs": "8", "resolution": "1024"},
        "flux": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "2", "max_epochs": "8", "resolution": "1024"},
        "anima": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                  "repeats": "2", "max_epochs": "8", "resolution": "1024"},
    },
    "flux2": {
        "sd15": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "2", "max_epochs": "16", "resolution": "1024"},
        "sdxl": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "2", "max_epochs": "16", "resolution": "1024"},
        "flux": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "2", "max_epochs": "16", "resolution": "1024"},
        "anima": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                  "repeats": "2", "max_epochs": "16", "resolution": "1024"},
    },
    "video": {
        "sd15": {"rank": "32", "alpha": "32", "unet_lr": "2e-4", "te_lr": "1e-4",
                 "repeats": "1", "max_epochs": "20", "resolution": "1280", "video_steps": "2000"},
        "sdxl": {"rank": "32", "alpha": "32", "unet_lr": "2e-4", "te_lr": "1e-4",
                 "repeats": "1", "max_epochs": "20", "resolution": "1280", "video_steps": "2000"},
        "flux": {"rank": "32", "alpha": "32", "unet_lr": "2e-4", "te_lr": "1e-4",
                 "repeats": "1", "max_epochs": "20", "resolution": "1280", "video_steps": "2000"},
        "anima": {"rank": "32", "alpha": "32", "unet_lr": "2e-4", "te_lr": "1e-4",
                  "repeats": "1", "max_epochs": "20", "resolution": "1280", "video_steps": "2000"},
    },
    "qwen_image": {
        "sd15": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "1", "max_epochs": "20", "resolution": "1024", "video_steps": "2000"},
        "sdxl": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "1", "max_epochs": "20", "resolution": "1024", "video_steps": "2000"},
        "flux": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "1", "max_epochs": "20", "resolution": "1024", "video_steps": "2000"},
        "anima": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "1e-4",
                  "repeats": "1", "max_epochs": "20", "resolution": "1024", "video_steps": "2000"},
    },
    "zimage": {
        "sd15": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "1", "max_epochs": "20", "resolution": "1024", "video_steps": "2000"},
        "sdxl": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "1", "max_epochs": "20", "resolution": "1024", "video_steps": "2000"},
        "flux": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "1e-4",
                 "repeats": "1", "max_epochs": "20", "resolution": "1024", "video_steps": "2000"},
        "anima": {"rank": "16", "alpha": "16", "unet_lr": "1e-4", "te_lr": "1e-4",
                  "repeats": "1", "max_epochs": "20", "resolution": "1024", "video_steps": "2000"},
    },
}

RESOLUTIONS = {k: v["resolution"] for k, v in ARCH_INFO.items()}
MIN_IMAGES = {"style": 20, "character": 15, "concept": 15, "krea2": 15, "krea2_at": 15, "krea2_fz": 15, "flux2": 15, "video": 3, "qwen_image": 15, "zimage": 15}   # 一键训练最少可用图片/视频数
MAX_AUTO_STEPS = 12000                          # 一键训练自动约束的最大总步数（防过拟合）

PARAM_LABELS = {
    "rank": "rank",
    "alpha": "alpha",
    "unet_lr": "学习率",
    "te_lr": "文本编码器学习率",
    "repeats": "repeats",
    "max_epochs": "最大epoch",
    "resolution": "训练分辨率",
    "video_steps": "训练步数",
}

# 高级参数通俗中文提示（鼠标悬停显示）
PARAM_TIPS = {
    "rank": "LoRA 秩：越大学得越细、越像，也越容易过拟合；一般 8~64。",
    "alpha": "缩放系数：一般取 rank 的一半，影响 LoRA 的强度。",
    "unet_lr": "UNet 学习率：越大学得越快，太大容易崩或过拟合。",
    "te_lr": "文本编码器学习率：控制提示词理解的学习速度，建议比 UNet 学习率低。",
    "repeats": "每张图片重复次数：越多学得越用力，小心过拟合。",
    "max_epochs": "最大训练轮数：轮数越多学得越久，够用就好。",
    "resolution": "训练分辨率：512 最省显存最快，768 平衡，1024 画质最好。16G 显存跑 Krea2/SDXL 建议降到 768 或 512，防止爆显存。",
    "video_steps": "视频 LoRA 总训练步数：2000 左右较稳；步数过高会死记视频内容（过拟合）。上限 3000。",
}

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
                       "文本编码器/VAE 首次训练自动下载（约 9GB，国内镜像）。16G 显存自动 768 + int8 + 分层交换优化。\n"
                       "不填也可以正常训练。")

TRIGGER_HINT_FLUX2 = ("💡提示：填一个网上很少见到的英文单词（如 my_f2_01）\n"
                      "训练后输入这个单词，就能召唤这个角色/风格。\n"
                      "⚠ FLUX.2 模式需先把模型放进 models/flux2/（DiT+文本编码器+VAE）并安装第二引擎；8G 显存可跑但较慢，推荐 12G+。")
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
    "style": "📌 数据集提示：建议 20~60 张图片，尽量多不同人物、不同姿态，避免五官固化。画风模式自动过滤强人物五官标签；可填画风专属触发词，不需要正则图。",
    "character": "📌 数据集提示：建议 15~30 张同一人物，多角度、不同服装，推荐设置唯一 trigger 触发词；可配合正则数据集防过拟合。",
    "concept": "📌 数据集提示：15~30 张同一形态/种族（如美人鱼/半人马/木偶人），刻意混不同画风/3D/实拍，避免 trigger 把画风一起吸进去；trigger 是唯一共同元素，描述只写每张的变体。",
    "krea2": "📌 数据集提示：建议 15~30 张同一人物/风格，多角度多服装；训练前先把 Krea 2 模型放进 models/krea2/（RAW+VAE+文本编码器）。推荐 12G+ 显存。",
    "krea2_at": "📌 数据集提示：建议 15~30 张同一人物/风格，多角度多服装；训练前把 Krea 2 RAW 底模放进 models/krea2/（26GB，bf16 原版），文本编码器/VAE 首次训练自动下载。推荐 16G+ 显存（16G 自动 768+int8+分层交换优化）。",
    "krea2_fz": "📌 数据集提示：建议 15~30 张同一人物/风格，多角度多服装；训练前先把 Krea 2 模型放进 models/krea2/（RAW+VAE+文本编码器）。NVIDIA/AMD 双平台，8G 显存自动 NF4、12G+ 用 fp8。",
    "flux2": "📌 数据集提示：建议 15~30 张同一人物/风格，多角度多服装；训练前先把 FLUX.2 模型放进 models/flux2/（DiT+Qwen3 文本编码器+VAE，约 16GB，国内镜像）。8G 显存可跑（自动开省显存），推荐 12G+。",
    "video": "📌 视频数据集提示：准备 3~10 段 3~10 秒的同角色/同风格视频（mp4），每段配一个同名 .txt 字幕描述内容。H3 模型 40GB+，训练推荐 24G 显存（NVIDIA）。",
    "qwen_image": "📌 数据集提示：15~30 张同一人物/风格图片。Qwen-Image 是 20B 大模型：16G 显存起步、24G 舒服（推荐）；首次训练自动下载模型约 40GB（国内镜像）。",
    "zimage": "📌 数据集提示：15~30 张同一人物/风格图片。Z-Image 是 8B 轻量模型：8G 可用（自动开快跑档）、12G 起步、16G 舒服；首次训练自动下载模型约 16GB（国内镜像）。",
}

OUTPUT_NAMES = {"style": "anime_style_lora", "character": "character_lora", "concept": "concept_lora", "krea2": "krea2_lora", "krea2_at": "krea2_at_lora", "krea2_fz": "krea2_fizgig_lora", "flux2": "flux2_lora", "video": "h3_video_lora", "qwen_image": "qwen_image_lora", "zimage": "zimage_lora"}
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
        {"id": "base", "label": "③ 选择底模", "btn": "去选底模", "check": "base", "act": "cmd_pick_base",
         "tip": "选择基础底模（.safetensors），SD1.5/SDXL/FLUX/Anima 都可。"},
        {"id": "raw", "label": "④ 选择图片文件夹", "btn": "去选文件夹", "check": "raw", "act": "cmd_pick_raw",
         "tip": "选择原始图片文件夹（jpg/png/webp 等）。"},
    ],
    "character": [
        {"id": "env", "label": "① 环境准备", "btn": "去准备", "check": "env", "act": "cmd_env",
         "tip": "安装 Git 和 Python（只需一次，全部项目通用）。"},
        {"id": "kohya", "label": "② 安装训练内核", "btn": "去安装", "check": "kohya", "act": "cmd_install",
         "tip": "安装 Kohya 训练内核（画风/人物模式需要，只需一次）。"},
        {"id": "base", "label": "③ 选择底模", "btn": "去选底模", "check": "base", "act": "cmd_pick_base",
         "tip": "选择基础底模（.safetensors），建议和出图用的底模同系列。"},
        {"id": "raw", "label": "④ 选择图片文件夹", "btn": "去选文件夹", "check": "raw", "act": "cmd_pick_raw",
         "tip": "选择同一人物的图片文件夹（15~30 张）。"},
    ],
    "concept": [
        {"id": "env", "label": "① 环境准备", "btn": "去准备", "check": "env", "act": "cmd_env",
         "tip": "安装 Git 和 Python（只需一次，全部项目通用）。"},
        {"id": "kohya", "label": "② 安装训练内核", "btn": "去安装", "check": "kohya", "act": "cmd_install",
         "tip": "安装 Kohya 训练内核（概念模式需要，只需一次）。"},
        {"id": "base", "label": "③ 选择底模", "btn": "去选底模", "check": "base", "act": "cmd_pick_base",
         "tip": "选择基础底模（.safetensors），SD1.5/SDXL/FLUX/Anima 都可。"},
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


PROJECT_TEMPLATES = {
    "动漫画风": {
        "mode": "style",
        "base_type": "sdxl",
        "note": "适合动漫/插画风格 LoRA：默认 SDXL 分辨率 1024，rank 16，低学习率防过拟合。",
        "params": {"rank": "16", "alpha": "8", "unet_lr": "1.5e-4", "te_lr": "7.5e-5",
                   "repeats": "5", "max_epochs": "8"},
    },
    "写实人物": {
        "mode": "character",
        "base_type": "sdxl",
        "note": "适合真人/角色 LoRA：默认 SDXL 分辨率 1024，rank 32，配 trigger 触发词效果更好。",
        "params": {"rank": "32", "alpha": "16", "unet_lr": "7e-5", "te_lr": "4e-5",
                   "repeats": "3", "max_epochs": "6"},
    },
    "SD1.5 动漫": {
        "mode": "style",
        "base_type": "sd15",
        "note": "轻量底模（512 分辨率），显存要求低，适合老显卡快速出效果。",
        "params": {"rank": "12", "alpha": "6", "unet_lr": "3e-4", "te_lr": "1.5e-4",
                   "repeats": "5", "max_epochs": "8"},
    },
    "FLUX.2 人物": {
        "mode": "flux2",
        "base_type": "sdxl",
        "note": "FLUX.2 klein 4B 人物/风格 LoRA：需第二引擎 + models/flux2/ 模型（约 16GB，国内镜像）。8G 显存可跑（自动开省显存），推荐 12G+。",
        "params": {"rank": "32", "alpha": "32", "unet_lr": "1e-4", "te_lr": "1e-4",
                   "repeats": "2", "max_epochs": "16"},
    },
    "自定义": {
        "mode": "character",
        "base_type": "sdxl",
        "note": "全部参数自己调，程序按当前模式+底模填默认值。",
        "params": {},
    },
}
