# 第三方组件声明 / Third-Party Notices

本项目基于以下开源项目二次封装：

| 组件 | 说明 | 协议 |
|---|---|---|
| [kohya_ss](https://github.com/bmaltais/kohya_ss) | Kohya-SS GUI（启动 Web UI / 环境安装） | Apache-2.0 |
| [sd-scripts](https://github.com/kohya-ss/sd-scripts) | 底层训练脚本（sdxl_train_network.py 等） | Apache-2.0 |
| [WD14 tagger](https://huggingface.co/SmilingWolf) | 人物模式自动打标（tag_images_by_wd14_tagger.py + wd-v1-4-moat-tagger-v2 模型） | 模型遵循其各自许可 |
| [Fizgig](https://github.com/shootthesound/Fizgig) | 第四引擎（Krea2 图像 LoRA 训练，NVIDIA/AMD 双平台）| Apache-2.0 |
| [comfyui-rocm](https://github.com/patientx/comfyui-rocm) | Fizgig 随包的 detect_gpu.py（AMD GPU 架构探测）| GPL-3.0 |
| [ffdkj/Danbooru_Tag-Chinese-English-Translation-Table](https://github.com/ffdkj/ffdkj-Danbooru_Tag-Chinese-English-Translation-Table) | 内置离线中英词典主数据（每日更新 32.5 万条；收录 post_count≥30 词条） | 仓库未附明确开源许可证，仅内置离线查询 |
| [byzod/a1111-sd-webui-tagcomplete-CN](https://github.com/byzod/a1111-sd-webui-tagcomplete-CN) | 离线词典常见词覆盖/补充（Tags-zh-full-pack.csv，整合自多个社区翻译） | MIT（沿用上游） |
| [bitsandbytes_win_rocm](https://github.com/0xDELUXA/bitsandbytes_win_rocm) | AMD ROCm Windows 用 bitsandbytes 社区轮子 | 随组件其各自许可 |

## 免责与合规

- 请仅使用你**拥有版权或已获授权**的图片进行训练。
- **禁止训练受版权保护的画师作品**；**禁止训练受版权保护的真人素材**（肖像权）。
- 本项目仅提供训练工具，使用者须自行确保训练素材的合法性与合规性。

## 本项目许可

本项目本体（GUI、预处理封装、配置、文档）以 **MIT License** 开源，见 `LICENSE`。
