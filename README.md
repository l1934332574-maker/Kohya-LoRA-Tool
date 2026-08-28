# Kohya-LoRA 一键训练工具

> Windows 平台、小白向的本地 LoRA 训练桌面工具。基于 [kohya-ss](https://github.com/bmaltais/kohya_ss) / [sd-scripts](https://github.com/kohya-ss/sd-scripts)（Apache-2.0）二次封装，项目本体采用 **MIT License**。

无需手动配置复杂的 Python、CUDA 和训练命令：按照应用内新手引导选择模式、安装对应训练引擎、导入图片并选择模型，即可完成数据预处理与 LoRA 训练。

**当前版本：v0.10.21** · [GitHub Releases](https://github.com/l1934332574-maker/Kohya-LoRA-Tool/releases) · [国内安装包（魔搭）](https://modelscope.cn/models/FGtiancai/Kohya-LoRA-Tool)

> ⚠️ **免责提示：禁止训练版权画师作品或未经授权的真人素材；请仅使用你拥有版权或已获授权的图片。**

---

- **Krea2 Raw/Turbo 下载 403 根治**：改走魔搭官方转存直链，免许可、免代理一键下载（原为 HuggingFace 门禁模型，hf-mirror 匿名必 401/403）。
- **修复 Krea2/FLUX.2 开采样预览训练秒崩**：训练子进程漏传本地 tokenizer/hf-mirror 环境，采样加载文本编码器时在线拉 HF tokenizer 失败；已与缓存步骤一致化，顺带修复 RDNA2 训练漏传 fp16。
- **修复「人物模式 + 正则数据集」训练必崩**：`is_reg` 写错 TOML 层级（应写在子集层），现按 sd-scripts schema 修正。
- **修复失败误诊**：训练失败不再被误报为 bitsandbytes 8-bit 问题，优先报告真实原因（配置校验 / OOM / 优化器）。
- **RDNA2（RX 6000）Anima 训练加官方 `--no_half_vae`**：VAE 全程 fp32（含缓存阶段），根治 latent NaN / 第一步 loss=nan。

- **修复老系统 curl 不兼容导致 torch 大轮子下载永远失败**：`--retry-all-errors` 需 curl 8.0+，Windows 自带旧版 curl 自动省略该参数，Kohya/第二引擎/AMD 大文件下载不再报错。
- **修复 Accelerate 中文路径误报「不属于同一环境」**：子进程强制 UTF-8 + realpath 容错比较，中文安装目录不再误报（真实环境不一致仍硬报错）。

- **MiniMax H3（视频 LoRA）低显存自动适配**：所有 H3 训练默认开 `low_vram`，<24G 自动开分层交换，12G 卡不再加载就 OOM。
- **MiniMax H3 支持 nvfp4 量化主模型**（12~16G 显存推荐，约 11.7GB 更小更稳），自动检测并优先使用。

- **MiniMax H3 模型下载全部改走魔搭国内直链**（ModelScope）：int8 / nvfp4 主模型、Qwen3-VL-32B 文本编码器、视频/音频 VAE 全部改为国内 CDN 直链，支持断点续传，再也不用苦等 hf-mirror。

- **MiniMax H3 模型完整性校验**：下载不完整的文件会被识别并提示重新下载，不再等训练时报 SafetensorError。
- **12~16G 显存 H3 训练前强提示**：必须用 nvfp4 主模型（int8 19.5GB 物理放不下），直接给魔搭下载链接。
- **视频模式「数据预处理」不再自动跳训练**：只检查提示，避免误触发训练。
- **修复 Krea2/FLUX.2 只装第二引擎时一键训练误报「Kohya 尚未安装」**：预处理自动多引擎 fallback。

- **修复英文系统（cp1252）下训练打印中文崩溃**：所有训练/预处理子进程强制 UTF-8 输出，不再 UnicodeEncodeError。
- **修复 Krea2/Qwen-Image/Z-Image 画风子模式训练报「缺少预处理数据」**：训练统一读 train_character（与预处理一致）。

- **修复手动修改项目 json 后点「打开」无反应**：配置恢复容错，失败时按默认配置打开并提示。
- **FLUX 模型下载改走魔搭国内直链**：DiT / CLIP-L / T5-XXL / AE 全部国内 CDN 直连、支持断点续传，不再直连 HuggingFace（避免 SSL 失败）。

- **修复繁体/英文系统下 Krea2 缓存 latents 打印中文崩溃**：所有子进程默认强制 UTF-8 输出，不再 UnicodeEncodeError。

## 🆕 v0.10.21 更新重点

- **修复 Z-Image/Qwen-Image 魔搭下载报 WinError 183**：魔搭文件清单里的目录项被误当文件下载导致中断；现只下载文件（跳过目录），16GB 模型可正常断点续传下载。

## 🆕 v0.10.20 更新重点

- **Z-Image / Qwen-Image 底模下载改走魔搭直链**：hf-mirror 故障/被污染后不再依赖，16GB 模型国内直连 + 断点续传；Krea2 VAE/文本编码器、FLUX.2 三件套下载也全部魔搭化。
- **Krea2 16G 卡默认配置调优**：默认 int8 + 块交换 12（4080S 实测 7s/it，比 fp8+swap10 的 30~40s/it 快 4~5 倍），不用再手动调高级参数。
- **修复训练监控面板"只有日志在动"**：Krea2/FLUX.2/AI-Image 训练现在正常显示步数/loss/速度/曲线。
- **Krea2 预量化底模拦截**：误放 ComfyUI 用的 fp8 raw 会提前明确提示换 bf16 原版。
- **Anima/Krea2 模型文件完整性校验**：损坏/截断的 VAE、底模、文本编码器训练前拦截并中文提示重下，不再爆 reshape 英文错。

## 🆕 v0.10.19 更新重点

- **修复 Krea2 16G 卡「换页卡死 / 越跑越慢」**：16G 档块交换 6→10（显存留足余量防换页）+ 16G 及以上自动开 pinned memory 加速块交换搬运（musubi 官方加速）。实测链路：swap=6 时显存 15.5/16 顶满、v0.10.17 卡死一下午、v0.10.18 64→176s/it 越跑越慢。
- **高级参数新增「块交换数」下拉**（Krea2/FLUX.2）：自动 / 2 / 4 / 6 / 8 / 10 / 12，跑稳后可手动往下调换速度，随项目保存。

## 🆕 v0.10.18 更新重点

- **Krea2/FLUX.2 16G 卡默认量化照搬社区改 fp8**：16G 卡带宽不是瓶颈，int8 的省带宽优势用不上反而算子低效（4080S 实测 100% 利用率功耗仅 80W）；现 16G+ 自动默认 fp8_scaled（musubi 官方 + 社区 16G 主流），int8 只留给 8~12G 带宽瓶颈档。
- **高级参数新增「量化方式」下拉**（Krea2/FLUX.2）：自动 / fp8 / int8 / nf4 可自行对比，选择随项目保存。

## 🆕 v0.10.17 更新重点

- **修复 16G 显卡（如 RTX 4080 SUPER）Krea2/FLUX.2 训练异常慢**：16G 卡被 Windows 检测为 15.6~15.9GB，之前会误判成 12G 档、每步搬运 12 个模型块（实测 11~17s/it、预计 3~4 小时）；现按显存档位取整，16G 走正确的 16-24G 档（Krea2 swap=6 / FLUX.2 swap=2），回到社区 16G 正常速度（同配置预计 2~4s/it、30~60 分钟）。

## 🆕 v0.10.16 更新重点

- **新增「一键导出日志」**：日志面板/训练监控一键导出 `KohyaLoRA_<项目>_<时间>.txt`（桌面），自动附带软件版本、操作系统、显卡/驱动、Python/Git、三引擎状态、torch 后端等环境信息 + 完整运行日志；出问题直接把 txt 发给维护者即可定位，不用再截图/手抄半截日志。
- **修复第三引擎模型下载卡死（Xet CDN）**：向三个训练环境注入 sitecustomize，强制走 hf-mirror + 禁用 HF Xet（大文件下载不再 peer closed / 超时卡在 Fetching files）。
- **修复 Krea2/FLUX.2 开「训练中采样预览」训练秒崩**：采样加载文本编码器时 tokenizer 走了在线拉取（国内直连 HF SSL 失败）；现训练子进程与缓存步骤一致使用本地 tokenizer + hf-mirror，顺带修复 RDNA2 训练步骤漏传 fp16。

## 🆕 v0.10.15 更新重点

- **Krea2 Raw/Turbo 下载 403 根治**：下载源改走魔搭（ModelScope）官方转存 `krea/Krea-2-Raw` / `krea/Krea-2-Turbo`，无需接受 Krea 许可、无需代理、国内 CDN 直连 + 断点续传，一键下载；文件名不变，训练零改动。

## 🆕 v0.10.7 更新重点

- **人物 LoRA 自动强绑定**：一个触发词绑定一个人物——自动提取训练集 100% 一致的身份特征并固定为标签前缀（keep_tokens 覆盖整组），特征不一致训练前警告，支持 ||| 手动固定区。
- **修复 Krea2/FLUX.2 预量化底模（fp8/int8）训练启动报错**：底模本身已量化时不再重复加量化参数。

## 🆕 v0.10.6 更新重点

- **修复 FLUX.2 低显存 int8 训练启动即断言崩溃**：musubi 只处理 fp8 不处理 int8 的 bug，已自动打补丁，8G 用户能正常训练。

> 完整更新记录见 [CHANGELOG.md](CHANGELOG.md)。

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
- **人物强绑定（默认开）**：自动提取训练集 100% 一致的身份特征（发色/瞳色/发型等），拼成 trigger + 特征 固定前缀并整体保护（keep_tokens 覆盖整组）——只写一个触发词也能稳定唤出同一个人物。特征不一致（如 white hair 只有 22/24 张）会在训练前提醒；进阶可用 ||| 手动划分固定区/可动区。
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
| `Setup.exe` | 推荐使用。双击安装，内置主程序、离线安装资源和 WD14 打标模型；当前最新版为 v0.9.29 |
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
