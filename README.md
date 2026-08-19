# Kohya-LoRA 一键训练工具

> Windows 平台、小白向的本地 LoRA 训练桌面工具。基于 [kohya-ss](https://github.com/bmaltais/kohya_ss) / [sd-scripts](https://github.com/kohya-ss/sd-scripts)（Apache-2.0）二次封装，项目本体采用 **MIT License**。

无需手动配置复杂的 Python、CUDA 和训练命令：按照应用内新手引导选择模式、安装对应训练引擎、导入图片并选择模型，即可完成数据预处理与 LoRA 训练。

**当前版本：v0.9.17** · [GitHub Releases](https://github.com/l1934332574-maker/Kohya-LoRA-Tool/releases) · [国内安装包（魔搭）](https://modelscope.cn/models/FGtiancai/Kohya-LoRA-Tool)

> ⚠️ **免责提示：禁止训练版权画师作品或未经授权的真人素材；请仅使用你拥有版权或已获授权的图片。**

---

## 🆕 v0.9.17 更新重点

### 预处理「缺少 numpy」彻底修复（DLL 污染根因）

- **根因已定位**：打包版应用目录自带的 `python312.dll` 会污染从该目录启动的 venv Python（Windows DLL 搜索优先命中打包版 DLL，与 venv 基座 Python 版本不匹配 → `_ctypes` 崩溃 → 误报「缺少 numpy」）。已改为外部 Python 子进程自动避开污染目录，全部引擎生效。
- **内置 numpy 2.1.3 + pillow 12.3.0 三套离线 wheel（cp310/311/312）**：预处理缺依赖时零联网补装，不再依赖网络镜像。
- **预处理失败自动补装并重试一次**：子进程失败后强制补装一轮再重试，不再卡死在原始报错。
- **分词器预缓存离线化**：内置 openai/clip-vit-large-patch14、laion/CLIP-ViT-bigG-14、google/t5-v1_1-xxl 三套常用分词器（约 8MB），SD1.5 / SDXL / FLUX / Anima 训练所需分词器完全离线，不再因 hf-mirror 超时而卡死。

## 🆕 v0.9.16 更新重点

### 安装与预处理稳定性修复

- **torch 本地安装不再卡清华源**：torch 大轮子下载完成后，本地 `pip install` 的依赖解析（filelock 等）原来只走清华源，部分网络下清华源不可达会无限失败（`Could not find a version that satisfies the requirement filelock (from versions: none)`）。现在自动按 **清华 → 阿里云 → 上海交大** 顺序回退，任一镜像成功即完成；错误日志明确区分「下载失败」与「本地依赖安装失败」。
- **预处理报「缺少 numpy」自愈**：预处理自检与 preprocess.py 实际用法完全对齐（`from PIL import Image; import numpy`），半损坏的 Pillow 也会被识别；子进程预处理失败后会自动补装依赖并**自动重试一次**，不再卡死在原始报错。
- **Lion 优化器降级真实预检**：AdamW8bit 不可用时降级 Lion 改为真实 `backward + step` 预检，旧版 lion-pytorch 与 torch 2.7 不兼容也能识别，自动继续降级为 AdamW，不再训练到 `optimizer.step()` 才崩溃。

## 🆕 v0.9.15 更新重点

### 训练稳定性：AdamW8bit 崩溃自动降级

Windows + CUDA 12.8 下 bitsandbytes 可能能 import 但 8-bit CUDA 内核不可用（`libbitsandbytes_cuda128.dll` 缺失 / `compiled without GPU support` / `str2optimizer8bit_blockwise is not defined`），之前会在训练 `optimizer.step()` 阶段崩溃。

- 训练开始前先做一次**真实 8-bit 优化器 step 预检**，通过才用 AdamW8bit。
- 失败自动降级：**Lion**（显存更低）→ **AdamW**（纯 PyTorch，兼容性最好），不会再在训练中途崩溃。
- 覆盖全部引擎：第一引擎（SD/SDXL/FLUX/Anima）、第二引擎（Krea2/FLUX.2）、第三引擎（Qwen-Image / Z-Image / MiniMax H3 视频）；第二引擎 musubi-tuner 不支持 Lion 会直接降级 AdamW；AMD 兼容模式固定 AdamW。

### 下载不再“看起来卡死”

PyTorch 大轮子（2~3GB）下载改为：

- 下载到 `.part` 文件断点续传，中断后自动从断点继续，不再删掉重下 3GB。
- 每 5 秒输出一条下载进度（`下载进度：xxx / xxx MB（xx%）`），用户能实时看到在下载。
- 新增限速看门狗：120 秒平均低于 20KB/s 自动切换备用国内镜像，避免无限挂起。

## 🆕 v0.9.14 更新重点

### 三套训练引擎安装稳定性修复

- **第一引擎**：修复安装流程中的 `git is not defined`；已有环境重跑安装时会校正 NumPy/SciPy/Protobuf，解决 Anima 导入 `numpy.Inf` 报错。
- **第二引擎**：严格锁定 `torch 2.7.1+cu128 + torchvision 0.22.1+cu128`，自动识别并修复旧版错误配对或被依赖升级的环境；缺 pip 时自动自愈/重建。
- **第三引擎**：补齐 venv 健康检查，迁盘、换用户或跨 Python DLL 冲突时会保留旧环境并自动重建；修复 NumPy/SciPy 解析冲突。
- 三个引擎的大型 PyTorch 轮子继续使用阿里云/上海交大国内镜像断点续传，不需要代理；下载失败会干净停止，不再留下半安装环境。
- 新增三引擎安装回归测试，覆盖源码解压、venv 创建与损坏恢复、pip 自愈、Torch 版本锁定和最终验证流程。

### v0.9.12 更新重点

### v0.9.12 环境与安装修复

- **修复打包版污染外部 Python venv 的 DLL 问题**：解决 Python 3.10/3.11 Kohya 环境被软件自带 Python 3.12 DLL 误加载，导致 `python312.dll conflicts`、`DLL load failed`、Qwen/T5 分词器预缓存失败以及训练退出码 1。
- **Torch 验证信息更完整**：安装后显示 Torch 版本、CUDA 构建版本和 CUDA 可用状态；导入失败会输出真实错误，不再出现 `torch ? / CUDA ?` 后仍显示安装成功。
- **修复失效代理下的 Git 克隆命令**：修正 `git -c ... git clone` 重复拼接 `git` 的问题；主引擎、第二引擎、第三引擎均使用正确的 Git 参数顺序。
- **v0.9.12 可直接覆盖旧版本**：一般不需要删除已有 venv，也不需要重新下载已经安装的 Torch。

### Qwen-Image / Z-Image 支持画风与人物训练

这两个模式不再固定按人物数据处理，现在可以在软件中直接选择：

- **🎨 画风 LoRA**：按画风逻辑预处理和过滤人物、五官及角色类标签。
- **👤 人物 LoRA**：保留人物特征标签，支持 Trigger 触发词。
- 训练类型会随项目配置自动保存和恢复。
- 修复一键训练时 Qwen-Image / Z-Image 预处理模式传递错误的问题。

### 数据目录可迁移，减少 C 盘占用

- 新安装的打包版默认将训练引擎、数据集、模型缓存和输出放在**安装目录同级的 `KohyaLoraTool_data`**。
- 软件主页新增 **「💾 数据目录」**，可查看当前位置与占用空间。
- 支持一键迁移到安装盘，也可手动选择 D 盘、E 盘等任意位置。
- 老用户可以直接迁移原 `%APPDATA%\KohyaLoraTool` 数据，无需重新安装训练环境。
- 迁移过程会先检查空间、复制并校验，成功后才清理旧数据；失败时保留原文件。
- 少量全局设置仍保存在 `%APPDATA%\KohyaLoraTool\settings.json`，属于正常现象。

---

## ✨ 功能分布

### 1. 训练模式与模型架构

| 类型 | 支持内容 | 训练引擎 |
|---|---|---|
| 经典图像 LoRA | SD1.5、SDXL、FLUX.1、Anima | 第一引擎（kohya / sd-scripts） |
| 新架构图像 LoRA | Krea 2、FLUX.2 | 第二引擎（musubi-tuner） |
| AI Toolkit 图像 LoRA | Qwen-Image、Z-Image | 第三引擎（AI Toolkit） |
| 视频 LoRA | MiniMax H3 | 独立视频训练流程 |

主要能力：

- **底模自动识别**：选择模型后自动判断 SD1.5、SDXL、FLUX、Anima 等架构，并切换合适的分辨率与参数预设。
- **画风 / 人物双模式**：画风模式过滤人物干扰标签；人物模式保留角色特征并支持 Trigger。
- **Qwen-Image / Z-Image 子模式**：两种架构都可单独选择画风或人物训练。
- **低显存适配**：根据显存自动调整精度、梯度检查点、block swap 等省显存参数，并给出中文提示。
- **高级参数可调**：支持修改分辨率、批次、Epoch、学习率、Rank 等常用训练参数。

> 不同架构的显存要求差异较大。8G 显存可以尝试部分省显存预设，但 SDXL、FLUX、Krea 2、Qwen-Image 等模型仍可能需要降低分辨率或使用更大显存。

### 2. 数据预处理与标签

- **一键预处理**：自动过滤损坏、模糊、过小和重复图片，再完成裁剪、缩放与打标。
- **内置 WD14 打标模型**：开箱即用，优先使用 GPU，失败时自动尝试可用环境或回退方案。
- **坏图自动隔离**：无法读取的图片会移入 `<输出目录>_corrupt`，避免一张坏图中断整批任务。
- **画风标签过滤**：保留真实画风特征，过滤人物身份、五官和角色类干扰标签。
- **人物 Trigger**：可将自定义触发词置于标签开头，并在训练时保护对应 token。
- **标签编辑器**：支持逐图查看、批量删除/替换、Trigger 置顶和标签频率统计。
- **秋叶式数据集兼容**：支持 `repeats_名称` 子目录结构。

### 3. 项目管理与一键训练

- 新建、打开、重命名和删除多个训练项目。
- 每个项目独立保存模型、模式、图片目录、Trigger 和高级参数。
- 每个项目使用独立数据集与输出目录，不同项目不会混用图片和标签。
- 左侧新手引导会按当前架构动态显示所需步骤。
- 一键执行：**预处理 → 数据校验 → 生成配置 → 启动训练**。
- 支持停止当前任务和断点续训。
- 实时显示训练阶段、步数、Loss、速度、显存与预计剩余时间。
- 缓存进度和正式训练进度分开显示，避免把 `20/20 100%` 缓存误认为训练卡死。

### 4. 模型下载与环境安装

- SD1.5、SDXL、Anima、FLUX.1 组件、FLUX.2、Krea 2、MiniMax H3 等支持应用内下载或自动下载所需组件。
- 国内网络优先使用魔搭、阿里、清华和 Hugging Face 镜像，并支持大文件断点续传与自动重试。
- 第二、第三引擎使用独立虚拟环境，不影响第一引擎。
- 修复 PyTorch 大轮子下载中断、`%2B` 文件名导致 wheel 无效、Python 版本错配和 CPU 版 torch 误判为安装成功等问题。
- 第三引擎支持 **「导入已装环境」**，已有 AI Toolkit 的用户无需重复部署。
- 第三引擎源码采用**首次使用按需下载**：优先魔搭、再切换国内加速源，并缓存到数据目录；源码不内置在安装包内。
- 第一、第二、第三引擎的 PyTorch 大轮子统一使用阿里云/上海交大国内镜像断点续传，避免无代理用户被迫访问海外源。
- NVIDIA 为主要支持平台；AMD 提供实验性兼容模式和环境检查提示。

### 5. 自动更新与国内下载

- 启动时可自动检查更新。
- 从魔搭、GitHub Raw、jsDelivr、GitHub Release 多源获取版本信息。
- 安装包支持断点续传、下载进度提示和覆盖安装。
- 国内用户可直接从魔搭下载安装包，无需必须连接 GitHub。

---

## 📦 下载安装

### GitHub

前往 [GitHub Releases](https://github.com/l1934332574-maker/Kohya-LoRA-Tool/releases) 下载最新版：

| 文件 | 说明 |
|---|---|
| `Setup.exe` | 推荐使用。双击安装，内置主程序、离线安装资源和 WD14 打标模型；当前最新版为 v0.9.16 |
| `KohyaLoraTool_*_portable.zip` | 便携版，解压后运行；若该版本未上传 ZIP，请使用 `Setup.exe` |

### 国内镜像

- **魔搭安装包**：[FGtiancai/Kohya-LoRA-Tool](https://modelscope.cn/models/FGtiancai/Kohya-LoRA-Tool)
- **Gitee 代码仓库**：[FGtiancai/Kohya-LoRA-Tool](https://gitee.com/FGtiancai/Kohya-LoRA-Tool)

> 程序不会把所有基础模型直接塞进安装包，否则体积会非常大。请根据软件内引导下载所需底模或模型组件。

---

## 🚀 快速开始

1. 下载并运行 `Setup.exe`，覆盖安装旧版本不会删除原有项目和训练数据。
2. 启动 `Kohya一键工具.exe`，在主页新建或打开一个项目。
3. 选择训练架构；Qwen-Image / Z-Image 还需选择「画风」或「人物」。
4. 按左侧引导安装对应训练引擎并下载模型。
5. 选择原始图片目录，填写 Trigger 或画风描述词（可选）。
6. 点击 **「🚀 一键开始训练」**。
7. 在主页 **「💾 数据目录」** 中可查看实际输出位置和占用空间。

### 数据保存位置

| 使用情况 | 默认位置 |
|---|---|
| v0.9.7 及之后新安装的打包版 | 安装目录同级的 `KohyaLoraTool_data` |
| 无法写入安装盘时 | `%APPDATA%\KohyaLoraTool` |
| 老用户升级但尚未迁移 | 继续使用原数据目录，可在主页手动迁移 |
| 用户手动指定 | 用户选择的任意目录 |

训练结果位于当前数据目录的：

```text
output\<项目名>\
```

---

## 🗂️ 仓库主要文件

| 文件 | 作用 |
|---|---|
| `kohya_gui.py` | CustomTkinter 桌面主界面 |
| `Kohya一键工具.py` | 训练、环境、下载、模型识别和数据迁移等核心逻辑 |
| `preprocess.py` | 图片清理、裁剪缩放、WD14 打标和标签处理 |
| `model_downloader.py` | 底模与组件下载 |
| `kohya_core/` | 路径、配置、运行控制等公共模块 |
| `installers/` | Git、Python 和训练引擎等离线安装资源 |
| `wd14_tagger_model/` | 内置 WD14 模型文件 |
| `README_使用说明.md` | 完整使用说明与常见问题 |
| `CHANGELOG.md` | 各版本更新记录 |

## 📖 使用文档

详细的数据集准备、标签、参数、打包和常见问题请查看：

- [完整使用说明](README_使用说明.md)
- [更新日志](CHANGELOG.md)

## 🛠️ 从源码运行

源码界面需要 Python 3.10～3.12，并安装 CustomTkinter 与 Pillow：

```bat
pip install customtkinter pillow
python kohya_gui.py
```

训练引擎依赖建议仍通过软件内安装流程部署。

## 📄 开源许可

- 本项目桌面工具：**MIT License**（见 [LICENSE](LICENSE)）
- [kohya-ss](https://github.com/bmaltais/kohya_ss) / [sd-scripts](https://github.com/kohya-ss/sd-scripts)：**Apache-2.0**
- 其他第三方组件许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
