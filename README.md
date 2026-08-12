# Kohya-LoRA 一键训练工具

> Windows 平台、小白向的本地 LoRA 训练桌面工具。基于 [kohya-ss](https://github.com/bmaltais/kohya_ss) / [sd-scripts](https://github.com/kohya-ss/sd-scripts)（Apache-2.0）二次封装，项目本体 **MIT 开源**。

在 Windows 上一键安装环境并训练 LoRA，无需手动配置 Python / CUDA / PyTorch。内置 **画风 / 人物** 两种训练模式，支持 **SD1.5 / SDXL / FLUX.1 / Anima** 四种基础架构。

> ⚠️ **免责提示：禁止训练版权画师作品、受版权保护的真人素材；请仅使用你拥有版权或已获授权的图片。**

## ✨ 功能亮点（v0.5.5）

- **双模式**：🎨 画风 LoRA（自动过滤强人物五官标签）/ 👤 人物角色 LoRA（完整保留标签 + trigger 触发词 + 可选正则数据集）
- **四架构**：SD1.5 / SDXL / FLUX.1 / Anima，自动识别底模类型并适配分辨率与参数
- **项目管理**：主页项目列表、新建/打开/重命名/删除、配置自动保存、预设模板
- **数据集按项目隔离**：每个项目独立数据集目录，互不混用；支持秋叶式 `repeats_名称` 子目录结构
- **标签编辑器**：逐张看图改标签、批量删除/替换、置顶 Trigger、标签频率统计、整理数据集
- **训练实时监控**：步数/总步数、loss + 趋势曲线、显存、预计剩余时间、训练速度
- **一键训练**：自动预处理（过滤模糊/过小/损坏/重复图 → 裁剪缩放 → WD14 打标）→ 校验 → 训练，支持断点续训
- **WD14 打标模型内置**：开箱即用，自动 GPU(CUDA) 推理，失败自动回退 CPU
- **AMD 兼容模式（实验性）**：一键开关 + 环境检查/安装引导（ROCm / ZLUDA）
- **kohya 环境重定向** 到 `%APPDATA%\KohyaLoraTool`：升级覆盖安装不重装环境
- **显存智能适配**：自动调整 batch / 精度 / 梯度检查点，低显存弹出通俗中文警告
- **第二训练引擎（实验性）**：独立安装 musubi-tuner（不碰 Kohya 环境），新增 **「🖼 Krea 2 图像LoRA」** 模式（Krea2 12.9B，预设 rank32/1024px，国内镜像下载模型引导）；视频 LoRA 训练开发中
- **Krea2 细化引导**：软件内「📖 Krea 2 使用引导」逐步教学（装引擎→下模型→选图→训练→出图）；Krea2 模式自动隐藏无关的 SD 底模下拉、隐藏无效的文本编码器学习率；参数按官方/社区校准（repeats2、RAW 训练→Turbo 出图）
- **网络自愈**：Pillow/numpy 离线 wheel 内置（预处理不依赖网络）；AMD ROCm/PyTorch 大文件断点续传下载；pip 全局重试/超时/备用镜像/系统代理
- **显存检测升级（DXGI）**：AMD 卡不再误报显存（16GB 卡正确识别），训练按真实显存自动适配
- **AMD 训练自愈**：训练前自动检查 AMD 环境依赖，缺失自动补装（修复 ModuleNotFoundError: toml）
- **训练环境自愈（统一）**：训练前检查 kohya venv / AMD venv 的完整运行时依赖（含 transformers/huggingface_hub），缺失自动补装

## 📦 下载安装

到 [Releases](https://github.com/l1934332574-maker/Kohya-LoRA-Tool/releases) 下载：

| 文件 | 说明 |
|---|---|
| `Setup.exe` | 安装包版（默认装到「文档\KohyaLoraTool」），**内置 WD14 打标模型**，双击安装即用 |
| `KohyaLoraTool_*_portable.zip` | 便携版，解压即用 |

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
