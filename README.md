# Kohya-LoRA 一键训练工具

> Windows 平台、小白向的本地 LoRA 训练桌面工具。基于 [kohya-ss](https://github.com/bmaltais/kohya_ss) / [sd-scripts](https://github.com/kohya-ss/sd-scripts)（Apache-2.0）二次封装，项目本体 **MIT 开源**。

在 Windows 上一键安装环境并训练 LoRA，无需手动配置 Python / CUDA / PyTorch。内置 **画风 / 人物** 等多种训练模式，支持 **SD1.5 / SDXL / FLUX.1 / FLUX.2 / Anima** 等基础架构。

> ⚠️ **免责提示：禁止训练版权画师作品、受版权保护的真人素材；请仅使用你拥有版权或已获授权的图片。**

## ✨ 功能亮点（v0.9.6）

### 🎨 训练模式与架构
- **双模式**：🎨 画风 LoRA（自动过滤强人物五官标签）/ 👤 人物角色 LoRA（完整保留标签 + trigger 触发词 + 可选正则数据集）
- **多架构自动识别**：SD1.5 / SDXL / FLUX.1 / FLUX.2 / Anima，自动识别底模类型并适配分辨率与参数
- **🖼 FLUX.2 图像 LoRA**（第二引擎）：2026 最新架构（4B DiT + Qwen3 文本编码器），8G 显存可跑（自动开 fp8 + blocks_to_swap 省显存），模型应用内下载（约 16GB，国内镜像）
- **🖼 Krea 2 图像 LoRA**（第二引擎）：12.9B 模型，独立 musubi-tuner 环境，预设 rank32/1024px
- **🎬 视频 LoRA（MiniMax H3）**（第三引擎）：33.1B 全模态视频模型 T2V LoRA；视频数据集自动抽帧 + Qwen2.5-VL 自动打标；推荐 24G NVIDIA 显存
- **🖼 Qwen-Image / Z-Image LoRA**（第三引擎）：20B / 8B 轻量模型，首次训练自动下载（国内镜像）

### 🗂 数据与预处理
- **数据集按项目隔离**：每个项目独立数据集目录，互不混用；支持秋叶式 `repeats_名称` 子目录结构
- **一键训练**：自动预处理（过滤模糊/过小/损坏/重复图 → 裁剪缩放 → WD14 打标）→ 校验 → 训练，支持断点续训
- **WD14 打标模型内置**：开箱即用，自动 GPU(CUDA) 推理，失败自动回退 CPU
- **标签编辑器**：逐张看图改标签、批量删除/替换、置顶 Trigger、标签频率统计、整理数据集

### 🚀 训练体验
- **项目管理**：主页项目列表、新建/打开/重命名/删除、配置自动保存、预设模板
- **智能新手引导**：左侧引导按所选模式动态生成（只显示该模式需要的步骤），每步完成自动高亮，全部完成才点亮一键训练
- **训练实时监控**：步数/总步数、loss + 趋势曲线、显存、预计剩余时间、训练速度
- **显存智能适配**：自动调整 batch / 精度 / 梯度检查点，低显存弹出通俗中文警告
- **训练分辨率可调**：高级参数面板可改（512/768/1024），16G 显存跑 Krea 2 / SDXL 可降到 768/512 防爆显存

### 📦 模型与更新
- **应用内下载全覆盖**：SD1.5 / SDXL / Anima 底模 + FLUX 四件套 + FLUX.2 + Krea2 + H3 全部支持应用内下载（国内镜像、断点续传、下完自动识别）
- **应用内自动更新**：启动自动检查新版本（魔搭 / raw / jsDelivr / GitHub 四源取最高版本），断点续传下载 + 实时进度 + 静默覆盖安装，发现新版一键升级
- **三引擎 PyTorch 安装稳定**：阿里镜像断点续传预下载 + 本地安装（自动重试 3 次），不再卡死在官方源下载 / ResolutionImpossible
- **第三引擎支持「导入已装环境」**：手动装好 AI Toolkit 一键导入复用，无需重新部署；装完立即刷新检测
- **kohya 环境重定向** 到 `%APPDATA%\KohyaLoraTool`：升级覆盖安装不重装环境
- **AMD 兼容模式（实验性）**：一键开关 + 环境检查/安装引导（ROCm / ZLUDA）

## 📦 下载安装

到 [Releases](https://github.com/l1934332574-maker/Kohya-LoRA-Tool/releases) 下载：

| 文件 | 说明 |
|---|---|
| `Setup.exe` | 安装包版（默认装到「文档\KohyaLoraTool」），**内置 WD14 打标模型**，双击安装即用 |
| `KohyaLoraTool_*_portable.zip` | 便携版，解压即用 |

> 🇨🇳 **国内镜像（Gitee 代码仓库）**：https://gitee.com/FGtiancai/Kohya-LoRA-Tool
> 🇨🇳 **国内安装包下载（魔搭）**：https://modelscope.cn/models/FGtiancai/Kohya-LoRA-Tool（Setup.exe 国内直连，应用自动更新优先走它）
>
> 程序**不内置 SD 基础底模**（体积太大）：首次使用按软件内引导下载底模，或把 `.safetensors` 放进 `models/base/` 自动识别。
> 首次使用需在软件内点「② 安装训练内核」安装 kohya + torch（离线安装包 + 国内镜像，约 10~30 分钟；之后升级不会重装）。

## 🚀 快速开始

1. 下载安装（或解压便携版），双击 `Kohya一键工具.exe`
2. 左侧新手引导按 ①②③④ 顺序：环境准备 → 安装训练内核 → 选底模 + 模式 → 选图片
3. 全部就绪后点「🚀 一键开始训练」
4. 训练产物在 `%APPDATA%\KohyaLoraTool\output\<项目名>\`

## 🗂️ 主要文件

| 文件 | 作用 |
|---|---|
| `kohya_gui.py` | 新版桌面主程序（CustomTkinter 界面） |
| `Kohya一键工具.py` | 业务逻辑核心（训练/预处理/环境/识别） |
| `preprocess.py` | 预处理 / WD14 打标 / trigger 插入 / 数据集配置 |
| `model_downloader.py` | 底模应用内下载（断点续传） |
| `installers/` | 内置离线安装包（Git / Python / kohya_ss / sd-scripts / musubi-tuner） |
| `wd14_tagger_model/` | 内置 WD14 打标模型 |
| `README_使用说明.md` | 完整使用说明（数据集准备、参数说明、打包、FAQ） |

## 📖 文档

完整使用说明见 [README_使用说明.md](README_使用说明.md)：数据集准备指南、参数说明、标签编辑器、`repeats_名称` 结构、打包与安装、常见问题。

## 🛠️ 从源码运行

需要 Python 3.10~3.12 与 customtkinter/Pillow（也可以直接用打包版）：

```bat
pip install customtkinter pillow
python kohya_gui.py
```

## 📄 许可

- 项目本体：**MIT**（见 `LICENSE`）
- 底层内核 [kohya-ss](https://github.com/bmaltais/kohya_ss) / [sd-scripts](https://github.com/kohya-ss/sd-scripts)：**Apache-2.0**（见 `THIRD_PARTY_NOTICES.md`）
