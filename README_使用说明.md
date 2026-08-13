# Kohya-SS LoRA 一键训练工具（Windows · 画风/人物 双模式 · 四架构）

在 Windows 上**一键安装 Kohya-SS 并训练 LoRA** 的小白向桌面工具。内置画风/人物两种训练模式，支持 **SD1.5 / SDXL / FLUX.1 / Anima** 四种基础架构。

| 模式 | 用途 | 标签策略 |
|---|---|---|
| 🎨 画风 LoRA | 只学绘画美术风格（笔触/色彩/光影/构图），不学角色 | 自动过滤强人物五官/角色标签，可填画风专属 trigger（可选） |
| 👤 人物角色 LoRA | 学某一个人物的脸部、服饰、角色特征 | 完整保留标签 + trigger 触发词 + 可选正则数据集 |

> 本项目基于 [kohya-ss](https://github.com/bmaltais/kohya_ss) / [sd-scripts](https://github.com/kohya-ss/sd-scripts)（Apache-2.0）二次封装，项目本体 **MIT 开源**，详见 `LICENSE` 与 `THIRD_PARTY_NOTICES.md`。
>
> ⚠️ **免责提示：禁止训练版权画师作品、受版权保护的真人素材；请仅使用你拥有版权或已获授权的图片。**

---

## 1. 文件清单

| 文件 | 作用 |
|---|---|
| **`kohya_gui.py`** | **新版桌面主程序（CustomTkinter 界面）**：新手引导、模式/架构切换、预处理、一键训练、停止、下载、教学。`python kohya_gui.py` 运行 |
| `Kohya一键工具.py` | 业务逻辑核心（训练/预处理/下载/环境/识别），被 kohya_gui.py 复用；老版 tkinter 界面保留为兜底入口 |
| `preprocess.py` | 预处理/去模糊去重/方形裁剪/WD14 打标/trigger 插入 |
| `model_downloader.py` | 底模应用内下载（断点续传） |
| `01_一键安装_Setup.bat` | 命令行一键装环境（Git/Python/kohya_ss + 依赖） |
| `02_数据预处理_Preprocess.bat` / `03_启动UI_StartUI.bat` / `04_一键训练_TrainCLI.bat` | 命令行备选流程 |
| `installers/` | 内置离线安装包（Git、Python、kohya_ss + sd-scripts、musubi-tuner 源码），无需代理 |
| `configs/` | 训练配置模板（运行时自动生成实际配置） |
| `models/base/` | **把你的底模放这里**（程序自动扫描识别） |
| `wd14_tagger_model/` | **内置 WD14 打标模型**（人物模式自动打标，开箱即用、自动走 GPU） |
| `LICENSE` / `THIRD_PARTY_NOTICES.md` | MIT 许可 + 第三方开源声明 |

> 运行数据（dataset / output / logs / tokenizers）自动写入 `%APPDATA%\KohyaLoraTool\`，程序目录只保留只读资源（models/base、configs）。

---

## 1.5 项目管理（v0.3.0 新增）

- 软件启动进入**项目主页**，右上角「➕ 新建项目」可创建多个训练项目。
- 每个项目自动保存一套完整配置：训练模式（画风/人物）、底模、图片文件夹、触发词、正则图、全部高级参数、全局提示词。
- 新建项目时可选预设模板：**动漫画风 / 写实人物 / SD1.5 动漫 / 自定义**。
- 项目配置**自动保存**（改参数/换路径即存），下次打开软件点项目卡片直接恢复，不用重填。
- 项目文件存 `%APPDATA%\KohyaLoraTool\projects\`，随软件重装保留。
- 训练产物按项目分组输出到 `%APPDATA%\KohyaLoraTool\output\<项目名>\`。
- **数据集按项目隔离**：每个项目有自己的数据集目录 `%APPDATA%\KohyaLoraTool\dataset\<项目名>\train_character`（人物）或 `train`（画风），预处理、标签编辑器、训练都只读当前项目的数据，**不同项目之间互不混用**。打开旧项目时若检测到旧版共享数据集，会询问是否一次性导入到当前项目。

---

## 2. 环境要求

- Windows 10 / 11（64 位）
- **NVIDIA 独立显卡**（默认）；训练前自动检测，非 N 卡会提示兼容性风险
- **AMD 显卡**：支持「AMD 兼容模式（实验性）」，见下方 2.1 节；不承诺稳定
- 较新 NVIDIA 驱动（支持 CUDA 12.8，一般 2024 年后驱动即可）；AMD 需 Adrenalin 26.2.2 及以上

**四种架构显存建议：**

| 架构 | 分辨率 | 最低显存 | 推荐显存 |
|---|---|---|---|
| SD1.5 | 512 | 8G | 12G |
| SDXL | 1024 | 12G | 16G |
| FLUX.1 | 1024 | 12G（8G 基本跑不动） | 16G |
| Anima | 1024 | 8G（需开省显存） | 12G |

> ⚠️ 底模路径不要有空格；kohya_ss 会自动装到无空格目录。套件自身路径可含中文/空格（已兼容）。

> 💡 **升级/重装软件不丢环境**：kohya_ss 训练内核（venv + 依赖）和训练数据（dataset/output/logs）一样，默认存放在 `%APPDATA%\KohyaLoraTool\` 数据目录。以后更新软件时**直接覆盖安装即可，不用删旧目录、不用重装 kohya 环境**（省 10~30 分钟）。只有第一次使用需要安装环境。

---

### 2.1 AMD 显卡兼容模式（实验性）

> ⚠️ **实验性功能，不承诺稳定。** 官方内核 kohya-ss 面向 NVIDIA CUDA 设计；AMD 卡需要额外配置训练环境，训练速度与稳定性均不如 NVIDIA，请自行评估风险后再使用。

- 检测到 AMD 显卡（Radeon）时，界面顶部会出现「**AMD 兼容模式（实验性）**」开关（N 卡不显示）
- 开启后训练会自动适配：
  - 强制 `--sdpa`（关闭 xformers，AMD 无 xformers 支持）
  - 混合精度统一 bf16（RDNA3 原生支持）
  - 改用纯 PyTorch 的 AdamW 优化器（AMD 下 bitsandbytes / AdamW8bit 不可用）
  - 按型号自动设置环境变量：RX 6000 系自动设 `HSA_OVERRIDE_GFX_VERSION=10.3.0`，并设 ZLUDA/ROCm 兼容变量
- 训练前自动检查训练环境是否就绪；未就绪会**阻止训练**并弹窗引导（点「环境检查 / 安装引导」可查看两条路线的完整步骤与下载链接）

**两种环境配置路线（任选其一）：**

**路线一 · ROCm 原生（较推荐，官方支持）**：AMD 官方支持 RDNA3（RX 7000 系，含 RX 7800 XT）
1. 更新显卡驱动到 Adrenalin 26.2.2 及以上
2. 安装 Python 3.12（AMD 官方 ROCm 版 PyTorch 只支持 Python 3.11 / 3.12，本工具内置的 kohya venv 是 Python 3.10，需要另建 Python 3.12 虚拟环境）
3. 在 Python 3.12 虚拟环境里安装 AMD 官方 ROCm SDK + ROCm 版 PyTorch（torch 2.9.1+rocm7.2.1，安装命令见界面弹窗）
4. 在该环境安装 sd-scripts 依赖（去掉 xformers / bitsandbytes 相关项）
5. 让训练切到这个 venv 后开启本开关

**路线二 · ZLUDA（进阶，更不稳定）**：让 CUDA 版 PyTorch 在 AMD 卡上直接运行，需要安装 HIP SDK + ZLUDA 预编译包，并把 ZLUDA 的 nvcuda.dll 等放置到 torch 对应目录、设置 HIP_PATH 等环境变量。

> AMD 官方 ROCm for Windows 文档：https://rocm.docs.amd.com/projects/radeon-ryzen/zh-cn/latest/index.html
> ZLUDA：https://github.com/lshqqytiger/ZLUDA

---

## 3. 安装（第一次使用）

> 项目内置离线安装包，全程**不需要代理、不需要访问 GitHub**；Python 依赖走国内镜像（清华 pypi + 阿里 pytorch）。

1. 打开程序 → 左侧新手引导 **① 环境准备（去准备）**、**② 安装训练内核（去安装）**（或双击 `01_一键安装_Setup.bat`）
2. 看到日志 `cuda available: True` 即安装成功；重复运行自动跳过
3. 安装耗时约 10~30 分钟（主要是 pip 拉依赖）

---

## 4. 桌面程序使用（新版界面）

启动：双击打包后的 `Kohya一键工具.exe`，或 `python kohya_gui.py`。

界面分四块：
- **左侧新手引导**：①环境准备 ②安装内核 ③选底模+模式 ④选图片；每项带红/绿点（未装/已装）
- **顶部**：模式切换（画风/人物）+ 架构/底模下拉 + 状态徽章 + 当前预设摘要
- **中间（可滚动）**：图片、触发词、高级参数卡片
- **底部**：独立运行日志

### 新手流程（从上到下）
1. **① 环境准备** → 自动装 Git/Python（绿点点亮）
2. **② 安装训练内核** → 装 kohya-ss（绿点点亮）
3. **③ 选择底模 + 模式**：顶部下拉选架构（SD1.5/SDXL/FLUX/Anima）或直接选底模文件；没有底模点「没有模型？点这里下载」（应用内下载带进度/断点续传）
4. **④ 选择图片文件夹** → 选好后红点变绿
5. 全部完成后，左侧「🚀 一键开始训练」按钮**自动点亮**，点击开始
6. 训练前会弹窗确认参数（可取消），可断点续训；任务中左下角出现「⏹ 停止当前任务」可中断

### 第二训练引擎（Krea 2 / 视频 LoRA，实验性）

- 左侧新手引导新增「②' 第二引擎(可选)」：安装独立 musubi-tuner 环境（不碰现有 Kohya 环境）。
- 模式下拉新增 **「🖼 Krea 2 图像LoRA」**：基于 Krea 2（12.9B MMDiT）训练，预设 rank32/alpha32/1024px。
- Krea2 训练前需把模型放进 `models/krea2/`（RAW 底模 13~26GB / Qwen-Image VAE / Qwen3-VL 文本编码器，软件内提供国内镜像直链）；推荐 16G 显存（最低 12G，自动 fp8 + block swap 省显存）。
### 第三训练引擎（MiniMax H3 视频 LoRA，实验性，v0.6.0 新增）

- 新增 **「🎬 视频LoRA（MiniMax H3）」** 模式：基于 MiniMax-H3（33.1B 全模态视频模型，24fps + 音频）训练 T2V LoRA。
- 训练内核为 **AI Toolkit（Ostris）**，独立 `ai_toolkit_venv`，完全不碰 Kohya / musubi 环境；安装入口在视频模式顶部的「⚙ 安装第三引擎」。
- 训练前需把模型放进 `models/minimax_h3/`（FL2VA pruned int8 DiT / Qwen3-VL-32B 文本编码器 / 视频VAE，共约 40GB，软件内提供国内镜像直链）。
- 数据集：一个文件夹放 3~10 段 3~10 秒的 `.mp4` + 同名 `.txt` 字幕（描述画面内容），训练时自动抽帧（默认 73 帧 ≈ 3 秒）。
- 预设：rank32 / alpha32 / lr 2e-4 / 训练步数 2000（上限 3000 防过拟合）。
- ⚠ 硬性要求：**NVIDIA 显卡 + 24GB 及以上显存**（训练走 CUDA/NVFP4）；AMD 显卡暂不支持该模式，请继续使用画风/人物/Krea2 模式。
- ⚠ 许可：MiniMax H3 为社区许可证（开放权重），商用请自行确认条款。

### 模式与预设
- 顶部切换 **画风/人物**，自动填充整套预设参数（rank/alpha/学习率/repeats/epochs）；手动改过的参数切换模式不会被覆盖，点「↺ 恢复预设」可重载
- **高级参数**（默认折叠，老手展开）：可直接填 rank/alpha/学习率等，还提供 **「风格预设：动漫 / 写实」** 一键填入常用数值
- **只训练 UNet（不训练文本编码器）**：省显存、更快；8G 显存跑 SDXL/Anima、以及 FLUX 默认建议勾选

### 触发词
- **人物模式**：必填唯一 trigger（如 `my_oc01`，别用 girl 这种常见词），预处理时自动插入每张标签开头
- **画风模式**：可选填画风专属触发词
- 附加全局正向/负向提示词（训练全局参数，不写入图片 txt）

---

## 5. 四种架构说明

| 架构 | 训练脚本 | 说明 |
|---|---|---|
| **SD1.5** | train_network.py | 最成熟、资源占用低；动漫建议用动漫系列底模（anything-v5、MeinaMix 等） |
| **SDXL** | sdxl_train_network.py | 效果更好；8G 显存建议勾「只训练 UNet」 |
| **FLUX.1** | flux_train_network.py | 12B 大模型，需同目录放 clip_l/t5xxl/ae 等配套文件；低显存自动 fp8 + blocks_to_swap |
| **Anima** | anima_train_network.py | 2026 新架构（2B DiT + Qwen3 文本编码器）；自动下载 Qwen3-0.6B + Qwen-Image VAE，默认只训 DiT |

> 程序自动识别底模类型（SD1.5/SDXL/FLUX/Anima），识别后按对应架构训练。**训练底模建议和你出图用的底模同一系列**，效果最稳；动漫 LoRA 建议直接用动漫系列底模训练。

---

## 6. 数据集与总步数（防过拟合）

- **人物模式**：建议 15~30 张同一人物，多角度、不同服装
- **画风模式**：建议 20~60 张不同人物，避免五官固化
- 图片越清晰越好（太小的缩略图效果差）；程序自动过滤模糊/过小/损坏/重复图

**总步数公式：** `总步数 ≈ 图片张数 × repeats × max_train_epochs`，目标安全区间 **1200~1800 步**。

手动调整方法：`repeats × max_train_epochs ≈ 1200~1800 ÷ 图片张数`，例如：
- 73 张 → repeats=3、epochs=6（=18，约 1314 步）
- 30 张 → repeats=4、epochs=12（=48，约 1440 步）
- 150 张 → repeats=2、epochs=5（=10，约 1500 步）

原则：**repeats 控制在 2~4**（太高会死记硬背训练图，是过拟合主因）；步数不够调大 epoch，超了先降 repeats。程序每 200 步保存一次 checkpoint，训练后快照整理到 `output\snapshots\`，可挑最优中间权重。

---

## 6.5 标签编辑器 与 repeats_名称 数据集结构（新增）

### 标签编辑器（主界面 → 「标签编辑器」按钮）

预处理（WD14 自动打标）后，可以用标签编辑器检查/修正每张图的标签——**打标偶尔会不准，改好后 LoRA 学得更准**。功能：

- **逐张浏览**：左侧图片列表（带子目录结构），右侧显示缩略图 + 标签内容，可直接修改并保存（写入同名 .txt，UTF-8）
- **批量删除标签**：输入 `1girl, solo`（逗号分隔），从全部标签里精确删除这些词
- **批量替换标签**：例如把 `1girl` 全部换成 `2girls`（精确匹配整个标签，不会误伤子串）
- **置顶 Trigger**：把当前填写的触发词插到每张标签第一行（已以触发词开头则跳过，不会重复叠加）
- **标签统计**：按出现频率列出全部标签，可一键删除某个高频/不要的词
- **整理为 repeats_名称**：见下方

### repeats_名称 子目录结构（秋叶式）

数据集目录支持秋叶 lora-scripts 式的子目录结构：**`数字_名称`** 子目录，`数字` 就是这组图片的 `repeats`（重复次数）。例如：

```
dataset/train_character/
├── 3_yanami_01/        ← 这组图训练时重复 3 次
│   ├── 01.png / 01.txt
│   └── 02.png / 02.txt
└── 5_pose/             ← 这组图训练时重复 5 次（比如姿势参考）
    ├── pose1.png / pose1.txt
    └── pose2.png / pose2.txt
```

- 在「标签编辑器」里点 **「📁 整理为 repeats_名称」**，输入概念名即可一键把根目录平铺的图片/标签移入 `数字_名称` 子目录（数字取高级参数里的 repeats）。
- 也可以自己在资源管理器里手动建 `数字_名称` 文件夹、把图片丢进去。
- 训练时程序自动识别：每个子目录独立重复次数，并按加权总步数做防过拟合约束；总步数仍按 `每张图 × 各自 repeats × epoch` 计算。
- 根目录直接放的图片仍然有效，repeats 取高级参数面板里的值。

---

## 7. 训练产物与使用模板

- **画风模式**：`output/anime_style_lora.safetensors` + 使用模板 + 参数报告
- **人物模式**：`output/character_lora.safetensors` + 使用模板 + 参数报告
- 中间快照/续训状态自动归拢到 `output/snapshots\`

把 `.safetensors` 放进 WebUI 的 `models/Lora/`（或 ComfyUI 的 `models/loras/`）即可使用；**LoRA 架构必须和出图底模一致**（SD1.5 的 LoRA 用 SD1.5 底模出图，以此类推）。

---

## 8. 推理提示

- **画风 LoRA**：无 trigger 直接写画风标签，推荐权重 0.5~0.7
- **人物角色 LoRA**：以 trigger 开头，推荐权重 0.6~0.9
- 负面提示词建议：`lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, jpeg artifacts, signature, watermark, username, blurry, bad quality`

---

## 9. 常见问题（FAQ）

- **Q：训练太慢 / 显存不够？** 高级参数勾「只训练 UNet」；8G 跑 SDXL/Anima、以及 FLUX 建议勾选
- **Q：模型没效果？** 检查出图底模和 LoRA 架构是否匹配（SD1.5↔SD1.5、SDXL↔SDXL…）
- **Q：图片太少被拦？** 过滤后人物至少 15 张、画风至少 20 张
- **Q：训练中断了？** 自动检测断点，下次训练询问是否续训；任务中可点「⏹ 停止当前任务」
- **Q：底模在哪下载？** 点「没有模型？点这里下载」→ 应用内下载（推荐，带进度/断点续传）或浏览器下载；下载后放进 `models/base` 自动识别
- **Q：怎么检查/修改每张图的标签？** 主界面点「标签编辑器」：逐张看图改标签、批量删除/替换、置顶 trigger、标签频率统计
- **Q：repeats_名称 子目录是什么？** 秋叶式结构：`数字_名称` 子目录的 repeats 取数字，根目录平铺图取高级参数里的 repeats；「标签编辑器 → 整理为 repeats_名称」可一键整理
- **Q：需要代理 / 访问 GitHub 吗？** 不需要；离线安装包 + 国内镜像
- **Q：为什么配置是 .toml？** sd-scripts 支持 json/toml，工具已自动生成
- **Q：FLUX / Anima 需要额外文件？** FLUX 需同目录 clip_l/t5xxl/ae；Anima 会自动下载 Qwen3 文本编码器 + VAE（首次联网）

> 程序内点「使用说明」可打开内置教学与 FAQ 弹窗。

---

## 10. 打包与安装

- **便携版**：`build_portable.bat` → `build_exe\dist\Kohya一键工具\`（自动压缩 zip），整个文件夹解压即用
- **安装包版**：`build_installer.bat`（需 Inno Setup 6）→ `build_exe\installer\Setup.exe`，默认装到 `文档\KohyaLoraTool`，带桌面/开始菜单快捷方式与卸载入口
- 打包不包含 torch/大模型/用户数据；`models\base`、`configs` 保留在程序目录
- 训练/日志等运行数据重定向到 `%APPDATA%\KohyaLoraTool\`

## 11. 常见坑提醒

- kohya_ss 安装路径不能有空格（工具已自动规避）
- 训练时别同时跑其他吃显存的应用
- 遵守版权：不训练版权画师作品与受版权保护的真人素材