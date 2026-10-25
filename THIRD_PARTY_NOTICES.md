# 第三方组件声明 / Third-Party Notices

本项目基于以下开源项目二次封装：

| 组件 | 说明 | 协议 |
|---|---|---|
| [kohya_ss](https://github.com/bmaltais/kohya_ss) | Kohya-SS GUI（启动 Web UI / 环境安装） | Apache-2.0 |
| [sd-scripts](https://github.com/kohya-ss/sd-scripts) | 底层训练脚本（sdxl_train_network.py 等） | Apache-2.0 |
| [Huihui Qwen3-VL 4B](https://huggingface.co/huihui-ai/Huihui-Qwen3-VL-4B-Instruct-abliterated) / [noctrex GGUF](https://huggingface.co/noctrex/Huihui-Qwen3-VL-4B-Instruct-abliterated-GGUF) | 可选下载的本地详细图片描述模型（Huihui 社区去拒答版本，noctrex Q4_K_M 与配套 FP16 视觉组件；固定提交与 SHA256）。原模型基于 Qwen3-VL-4B-Instruct；作者说明仅处理文本部分。去拒答不保证输出质量或所有输入均能生成描述。 | Apache-2.0（继承原模型许可） |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | Qwen3-VL 本地推理组件（固定 b11553 的 Windows x64 CPU / Vulkan 官方归档，独立进程） | MIT |
| [RAM++](https://github.com/xinyu1205/recognize-anything) / [官方权重](https://huggingface.co/xinyu1205/recognize-anything-plus-model) | 可选下载的本地真实照片关键词模型（固定模型权重、推理源码、标签列表和 BERT 词表，逐文件 SHA256 校验；独立环境运行） | Apache-2.0；内含 Salesforce BERT/ViT 代码 BSD-3-Clause、Microsoft Swin 代码 MIT；原版权头与许可随源码保留 |
| [PixAI Tagger v1.0](https://huggingface.co/pixai-labs/pixai-tagger-v1.0) | 可选二次元打标模型；训练与独立图片反推共用固定提交权重、配置及官方 tagger_pipeline.py，逐文件 SHA256 校验，独立环境运行。官方推理源码包含 SAM3 / ViTDet 与旋转位置编码来源说明，原文件保留这些说明。 | Apache-2.0（按模型仓库声明）；所含第三方实现遵循各自许可 |
| [WD14 tagger](https://huggingface.co/SmilingWolf) | 人物模式自动打标（tag_images_by_wd14_tagger.py + wd-v1-4-moat-tagger-v2 模型） | 模型遵循其各自许可 |
| [Fizgig](https://github.com/shootthesound/Fizgig) | 第四引擎（新项目固定 v8.9.6，保留 v7.3.1 / MOSS v8.5.0 及已有 v7.0.1；Krea2、Klein 9B、Qwen-Image-2.1、H3、Anima / SDXL / Z-Image Turbo 普通 LoRA 与概念滑块，MOSS-Image Base 普通 LoRA）| Apache-2.0；MiniMax 相关 ComfyUI 派生源码遵循 GPL-3.0，归档保留其版权头与许可 |
| [MediaPipe Selfie Multiclass](https://ai.google.dev/edge/mediapipe/solutions/vision/image_segmenter) / [LiteRT](https://github.com/google-ai-edge/LiteRT) | 可选 CPU 人物分割；首次生成学习区域时下载官方 256×256 TFLite 模型，并校验固定 SHA256；不随软件内置模型权重。 | Apache-2.0（按上游模型与运行时声明） |
| [comfyui-rocm](https://github.com/patientx/comfyui-rocm) | Fizgig 随包的 detect_gpu.py（AMD GPU 架构探测）| GPL-3.0 |
| [ffdkj/Danbooru_Tag-Chinese-English-Translation-Table](https://github.com/ffdkj/ffdkj-Danbooru_Tag-Chinese-English-Translation-Table) | 内置离线中英词典主数据（每日更新 32.5 万条；收录 post_count≥30 词条） | 仓库未附明确开源许可证，仅内置离线查询 |
| [byzod/a1111-sd-webui-tagcomplete-CN](https://github.com/byzod/a1111-sd-webui-tagcomplete-CN) | 离线词典常见词覆盖/补充（Tags-zh-full-pack.csv，整合自多个社区翻译） | MIT（沿用上游） |
| [bitsandbytes_win_rocm](https://github.com/0xDELUXA/bitsandbytes_win_rocm) | AMD ROCm Windows 用 bitsandbytes 社区轮子 | 随组件其各自许可 |

## Fizgig 本地配置适配

Fizgig 的国内源码镜像保留固定提交的原始归档、许可证与声明。工具安装时单独应用本地适配：使用已校验的分词器 / 配置目录，给续训快照增加版本记录并隔离目录；这些修改不代表上游原始代码。

分词器与配置来自 `circlestone-labs/Anima-Base-v1.0-Diffusers`、`stabilityai/stable-diffusion-xl-base-1.0`、`Qwen/Qwen3-8B` 、`Qwen/Qwen3-VL-4B-Instruct` 和 `OpenMOSS-Team/MOSS-Image-Base` 的固定公开提交；来源、提交与文件 hash 记录在 `kohya_core/fizgig_helpers.json`。这些文件以及用户自行下载的模型分别遵循原仓库许可；镜像保留可获取的原仓库许可证。

概念滑块复用项目选定 Fizgig 标准版本 的文字 / 图片对正负倍率目标与原生 LoRA 导出；工具的独立子进程扩展增加固定条件权重对照、留出验证及方向元数据，不改写用户安装的上游训练源码。

## 免责与合规

- 请仅使用你**拥有版权或已获授权**的图片进行训练。
- **禁止训练受版权保护的画师作品**；**禁止训练受版权保护的真人素材**（肖像权）。
- 本项目仅提供训练工具，使用者须自行确保训练素材的合法性与合规性。

## 本项目许可

本项目本体（GUI、预处理封装、配置、文档）以 **MIT License** 开源，见 `LICENSE`。

## Z-Image Turbo 组件

Fizgig 的 Z-Image 实现改编自 Tongyi-MAI 的 Apache-2.0 参考源码，原始版权头和许可随固定引擎归档保留。Turbo 权重与 Qwen3-4B、FLUX.1 VAE 的单文件分发来自 `Comfy-Org/z_image_turbo`；训练适配器来自 `ShootTheSound/Fizgig-Z-Image-Turbo-Training-Adapter` 的固定提交。分词器与 VAE 配置来自 `Tongyi-MAI/Z-Image-Turbo` 的固定提交，来源与逐文件 hash 记录在 `kohya_core/fizgig_helpers.json`。模型、适配器分别遵循其上游仓库的许可；本工具仅按需下载，不随安装包附带大型模型权重。

## 二次元学习区域

按需下载 SkyTNT 的 [Anime Segmentation](https://github.com/SkyTNT/anime-segmentation) 人物前景分割 ONNX，使用其 RGB 归一化、等比例缩放与居中补边推理流程。上游代码为 Apache-2.0；模型来源为作者的 `skytnt/anime-seg` 仓库，固定提交 `493cb60893f47441b26ec4fb9a306bce9e342982`、文件 `isnetis.onnx`，SHA256 `f15622d853e8260172812b657053460e20806f04b9e05147d49af7bed31a6e99`。模型只按需下载，不附带在安装包内。CPU 推理使用 ONNX Runtime。
