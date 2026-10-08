# 第三方组件声明 / Third-Party Notices

本项目基于以下开源项目二次封装：

| 组件 | 说明 | 协议 |
|---|---|---|
| [kohya_ss](https://github.com/bmaltais/kohya_ss) | Kohya-SS GUI（启动 Web UI / 环境安装） | Apache-2.0 |
| [sd-scripts](https://github.com/kohya-ss/sd-scripts) | 底层训练脚本（sdxl_train_network.py 等） | Apache-2.0 |
| [WD14 tagger](https://huggingface.co/SmilingWolf) | 人物模式自动打标（tag_images_by_wd14_tagger.py + wd-v1-4-moat-tagger-v2 模型） | 模型遵循其各自许可 |
| [Fizgig](https://github.com/shootthesound/Fizgig) | 第四引擎（固定 v7.0.1；Krea2、Klein 9B、Qwen-Image-2.1、H3、实验性 Anima / SDXL 普通 LoRA 与概念滑块）| Apache-2.0 |
| [comfyui-rocm](https://github.com/patientx/comfyui-rocm) | Fizgig 随包的 detect_gpu.py（AMD GPU 架构探测）| GPL-3.0 |
| [ffdkj/Danbooru_Tag-Chinese-English-Translation-Table](https://github.com/ffdkj/ffdkj-Danbooru_Tag-Chinese-English-Translation-Table) | 内置离线中英词典主数据（每日更新 32.5 万条；收录 post_count≥30 词条） | 仓库未附明确开源许可证，仅内置离线查询 |
| [byzod/a1111-sd-webui-tagcomplete-CN](https://github.com/byzod/a1111-sd-webui-tagcomplete-CN) | 离线词典常见词覆盖/补充（Tags-zh-full-pack.csv，整合自多个社区翻译） | MIT（沿用上游） |
| [bitsandbytes_win_rocm](https://github.com/0xDELUXA/bitsandbytes_win_rocm) | AMD ROCm Windows 用 bitsandbytes 社区轮子 | 随组件其各自许可 |

## Fizgig 本地配置适配

Fizgig 的国内源码镜像保留固定提交的原始归档、许可证与声明。工具安装时单独应用本地适配：使用已校验的分词器 / 配置目录，给续训快照增加版本记录并隔离目录；这些修改不代表上游原始代码。

分词器与配置来自 `circlestone-labs/Anima-Base-v1.0-Diffusers`、`stabilityai/stable-diffusion-xl-base-1.0`、`Qwen/Qwen3-8B` 和 `Qwen/Qwen3-VL-4B-Instruct` 的固定公开提交；来源、提交与文件 hash 记录在 `kohya_core/fizgig_helpers.json`。这些文件以及用户自行下载的模型分别遵循原仓库许可；镜像保留可获取的原仓库许可证。

概念滑块复用 Fizgig v7.0.1 的文字 / 图片对正负倍率目标与原生 LoRA 导出；工具的独立子进程扩展增加固定条件权重对照、留出验证及方向元数据，不改写用户安装的上游训练源码。

## 免责与合规

- 请仅使用你**拥有版权或已获授权**的图片进行训练。
- **禁止训练受版权保护的画师作品**；**禁止训练受版权保护的真人素材**（肖像权）。
- 本项目仅提供训练工具，使用者须自行确保训练素材的合法性与合规性。

## 本项目许可

本项目本体（GUI、预处理封装、配置、文档）以 **MIT License** 开源，见 `LICENSE`。
