# Kohya-SS LoRA 一键训练套件（Windows，画风 / 人物角色 双模式）

本套件用于在 Windows 上**一键安装 Kohya-SS 并训练 LoRA**，内置两种模式：

| 模式 | 用途 | 标签策略 |
|---|---|---|
| 🎨 画风 LoRA | 只学习绘画美术风格（笔触/色彩/光影/构图），**不学习角色** | 自动过滤强人物五官/角色标签，无 trigger |
| 👤 人物角色 LoRA | 学习某一个人物的脸部、服饰、角色特征 | 完整保留全部标签 + trigger 触发词 + 可选正则数据集 |

> 本项目基于 [kohya-ss](https://github.com/bmaltais/kohya_ss) / [sd-scripts](https://github.com/kohya-ss/sd-scripts)（Apache-2.0）二次封装，项目本体 MIT 开源，详见 `LICENSE` 与 `THIRD_PARTY_NOTICES.md`。
>
> ⚠️ **免责提示：禁止训练版权画师作品、受版权保护的真人素材；请仅使用你拥有版权或已获授权的图片。**

---

## 1. 文件清单

| 文件 | 作用 |
|---|---|
| `01_一键安装_Setup.bat` | 自动拉取 kohya_ss 官方仓库 + 建 venv + 安装全部依赖 + 配置 accelerate |
| `02_数据预处理_Preprocess.bat` | 命令行版画风模式预处理（1024px 缩放、去黑边/水印、统一画风标签、repeats=5） |
| `preprocess.py` | 预处理核心脚本（支持 `--mode style/character`，可单独命令行运行） |
| `03_启动UI_StartUI.bat` | 双击直接打开 kohya-ss 网页 UI（http://127.0.0.1:7860） |
| `04_一键训练_TrainCLI.bat` | 可选：不打开 UI，命令行一键训练画风 LoRA（已更新为最新预设） |
| `Kohya一键工具.py` | **桌面主程序**：双模式切换、高级参数、预处理、一键训练、使用模板导出 |
| `installers/` | **内置离线安装包**（Git、Python 3.10.11、kohya_ss + sd-scripts 源码 zip），安装不再依赖 GitHub/代理 |
| `configs/style_lora_gui.toml` | GUI 训练配置（画风 LoRA，可在 kohya 网页 UI 中 Import） |
| `configs/dataset_config.toml` | 数据集配置（预处理/训练时按当前模式自动重新生成，一般无需手改） |
| `dataset/raw/` | **把你的原始图片放这里** |
| `dataset/train/` | 画风模式预处理输出（PNG + 同名 .txt caption）；**实际写入 `%APPDATA%\KohyaLoraTool\dataset`** |
| `dataset/train_character/` | 人物模式预处理输出（自动创建，位于 `%APPDATA%\KohyaLoraTool\dataset`） |
| `output/` | 训练完成的 .safetensors、**txt 使用模板**、**参数报告 txt**、中间快照（自动创建，位于 `%APPDATA%\KohyaLoraTool\output`） |
| `logs/` | 训练日志目录（自动创建，位于 `%APPDATA%\KohyaLoraTool\logs`） |
| `LICENSE` / `THIRD_PARTY_NOTICES.md` | MIT 许可与第三方开源声明 |

---

## 2. 环境要求

- Windows 10 / 11（64 位）
- **NVIDIA 独立显卡**；**显存低于 12GB 时训练前会弹窗警告**（可继续，但可能 OOM/较慢）
- 显存建议：SD1.5 8G+、SDXL 16G+、**FLUX.1 16G+（8G 基本跑不动）**、**Anima 8G 可跑 / 推荐 12G+**
- 较新的 NVIDIA 驱动（PyTorch cu128 需要支持 CUDA 12.8 的驱动，一般 2024 年后驱动即可）
- Git 与 Python：**通常无需手动安装**，项目内置安装包（`installers/`），环境准备/01 脚本会自动静默安装
- 一个底模（.safetensors）：画风模式建议 SD1.5/SDXL 动漫模型；人物模式建议质量较高的写实/动漫底模

> ⚠️ **路径不要有空格**：kohya_ss 官方不支持含空格路径。套件会自动把 kohya_ss 装到无空格目录（如 `C:\Users\<你>\kohya_ss`），其余脚本自动跟随。套件自身路径**可以包含中文/空格**（已做兼容）。

---

## 3. 安装（第一次使用）

> 本项目**内置离线安装包**（`installers/`），全程**不需要代理、不需要访问 GitHub**：
> - Git / Python：用内置安装包静默安装；
> - kohya_ss + sd-scripts：用内置源码 zip 本地解压；
> - Python 依赖：走**清华 pypi 镜像 + 阿里 pytorch cu128 镜像**（国内直连）。

1. 双击 **`01_一键安装_Setup.bat`**，或打开桌面主程序后点 **② 一键安装 Kohya-SS**。
2. 脚本会自动：检查/安装 Git、Python → 解压内置 kohya_ss + sd-scripts 源码 → 建 `venv` → 装全部依赖（torch + CUDA、sd-scripts、onnxruntime 等）→ 配置 accelerate。
3. 看到 **Setup finished!** 以及 `cuda available: True` 即安装成功。
4. 安装耗时约 10~30 分钟（主要是 pip 从镜像拉取依赖）。完成后根目录生成 `kohya_dir.txt` 记录 kohya_ss 位置。
5. 重复运行会自动检测「已安装则跳过」，秒过。

---

## 4. 桌面主程序（推荐）

双击 `Kohya一键工具.py`（或打包后的 exe）启动主界面：

1. **顶部下拉框选择训练模式**：`🎨 画风LoRA模式` / `👤 人物角色LoRA模式`。
   - 切换模式时自动填充整套预设参数；
   - 你在「高级参数」面板里**手动修改过的参数，之后切换模式不再被自动重置**（点「↺ 恢复预设」可重新套用当前模式预设）。
2. **👤 人物模式专属控件**（画风模式下自动隐藏）：Trigger 触发词输入框、正则数据集文件夹选择。
3. **③ 数据预处理**：选择原始图片文件夹，自动完成 缩放/去黑边/去水印/去重/打标签。
4. **⑥ 一键训练**：选择底模 → 弹窗确认当前模式与生效参数 → 开始训练。
5. 训练前如果显存 <12GB 会弹警告；训练中日志实时输出；完成后自动生成 **txt 使用模板**。
6. **⑨ 关于**：查看开源协议与免责提示。

### 4.1 内置预设参数

| 参数 | 🎨 画风 LoRA | 👤 人物角色 LoRA |
|---|---|---|
| rank（LoRA 秩） | **12** | **24** |
| alpha（缩放） | **6** | **12** |
| 学习率（UNet） | **3e-4** | **1.5e-4** |
| 文本编码器学习率 | **1.5e-4** | **8e-5** |
| repeats（图片重复次数） | **5** | **3**（见「6.5 总步数与防过拟合」） |
| 最大训练 epoch | **8** | **6**（见「6.5 总步数与防过拟合」） |
| 标签处理 | 过滤强人物五官/角色标签 | 完整保留全部标签 |
| Trigger 触发词 | 无（不显示输入框） | 有（插入每张标签第一行） |
| 正则数据集 | 不需要（不传递正则参数） | 可选（写入 is_reg 数据集） |
| 数据集建议 | 20~60 张，尽量多不同人物/姿态 | 15~30 张同一人物，多角度、不同服装 |
| 输出模型 | `output/anime_style_lora.safetensors` | `output/character_lora.safetensors` |
| 使用模板 | `anime_style_lora_使用模板.txt` | `character_lora_使用模板.txt` |

> 高级面板还提供：「只训练 UNet（不训练文本编码器）」勾选框（默认两个模式都训练 UNet+文本编码器）与「梯度检查点」下拉（自动/开启/关闭；自动模式按显存自动判定：<16GB 或未知时开启）。

> 🏗 **新架构（2026）**：「底模」下拉新增 **FLUX.1** 与 **Anima**。FLUX.1 是 12B 大模型、画质新但非常吃显存（需 flux1-dev + clip_l + t5xxl + ae 四个文件放同一文件夹）；Anima 是最新 2B DiT 架构、显存友好（Qwen3 文本编码器与 VAE 训练时自动下载）。选完底模文件会自动识别架构；FLUX/Anima 默认「只训练 UNet/DiT」。

### 4.2 底模选择（SD1.5 / SDXL 联动）

主界面顶部「底模」下拉可选择 **SD1.5（512px）** 或 **SDXL 1.0（1024px）**，旁边「选择底模文件…」选择本地 `.safetensors / .ckpt`。

- 选底模类型会自动填充对应预设（分辨率 / rank / 学习率），**你手动改过的高级参数不会被覆盖**，只有点「↺ 恢复预设」才重写。
- 点「选择底模文件…」选完**自动识别**是 SD1.5 还是 SDXL（safetensors 秒级识别；认不出时手动在下拉里选）。
- **界面所有输入框/按钮鼠标悬停都有通俗中文说明**，看不懂专业词就把鼠标放上去。
- SD1.5：分辨率 512×512，沿用两套模式预设（rank 12/24，lr 3e-4/1.5e-4）。
- SDXL：分辨率 1024×1024，自动缩放 rank 与学习率：画风 rank→16、lr→1.5e-4；人物 rank→32、lr→7e-5。**SDXL 推荐 16G 及以上显存**。
- 训练时按底模类型自动选择脚本：SD1.5 → `train_network.py`（fp16），SDXL → `sdxl_train_network.py`（bf16），并自动切换 bucket 分辨率范围。

### 4.3 训练前确认弹窗

每次点击「⑥ 一键训练」选择底模后，会弹窗列出：当前模式、rank、alpha、学习率、文本编码器学习率、repeats、最大 epoch、训练目标、梯度检查点，人物模式还会显示 Trigger 与正则数据集，确认后才会真正开始。

---

### 4.4 附加全局提示词（正向 / 负向）

- **附加全局正向提示词**：两种模式都可见。训练时自动加到每张标签最前面（不修改图片的 .txt 文件），可留空。
- **附加全局负向提示词**：两种模式都可见。写入使用模板与参数报告；kohya 训练本身不使用负向提示词。
- 切换底模不会清空已填写的提示词。

### 4.5 一键开始训练（小白自动流水线）

主界面「原始图片文件夹」选择图片目录后，点 **🚀 一键开始训练**：

1. 自动预处理：**过滤模糊 / 过小 / 损坏图片**（弹窗提示过滤数量）→ 按底模分辨率**居中正方形裁剪缩放** → MD5 去重 → 复用 WD14 打标 / 画风标签过滤 / trigger 插入。
2. 前置校验：画风模式可用图片 **≥20 张**、人物模式 **≥15 张**，不足则友好中文提示并阻止训练。
3. 硬件智能适配：按显存自动调整 batch_size、fp16/bf16、xformers/sdpa、梯度检查点，OOM 前用通俗中文弹窗提醒。
4. 自动约束最大 epoch（按总步数上限防过拟合）；训练中断后再次运行时**自动检测快照、支持断点续训**。
5. 输出：最终 LoRA + 中间快照 + **完整参数报告 txt** + **使用模板**。

## 4.6 基础底模（软件不附带，需自备）

- **软件不打包任何 SD 底模**，保持安装包体积可控；训练必须要有基础底模。
- 底模默认存放目录：项目内 `models\base`（主界面「打开模型文件夹」可直接打开）。
- 主界面底模旁边有 **「没有模型？点这里下载」** 按钮，点开后**推荐「应用内下载」**：
  - **应用内下载**：直接在软件里下载（SD1.5：`v1-5-pruned-emaonly.safetensors` 约 4.3GB；SDXL：`sd_xl_base_1.0.safetensors` 约 6.9GB），走**阿里魔搭（ModelScope）极速直链**（国内快约 6 倍），带进度条、**断点续传**（中断后重下从断点继续）、可取消，下完**自动放进 `models\base` 并自动识别**加入底模列表，全程不用开浏览器。
  - 也可以选「浏览器极速下载（魔搭）」或「备用下载（hf-mirror）」在浏览器里下载，再把文件放进 `models\base` 点「↻ 刷新」。
- 程序启动会自动扫描该目录下的 `.safetensors / .ckpt`，把找到的模型自动列进「底模」下拉，并自动识别是 SD1.5 还是 SDXL。
- 如果选了「SD1.5 / SDXL 1.0」但目录里没有对应模型，会弹窗引导你跳转下载或打开模型文件夹。

## 5. 数据集准备指南

### 5.1 🎨 画风 LoRA 数据集（dataset/raw）

- **数量**：建议 20~60 张。
- **内容**：所有图片必须是**同一种画风**（同一部番/同一位画师/同一类上色方式）；**尽量多不同人物、不同姿态、不同构图**，避免大量重复同一张脸/同一个角色，防止「记住角色」。
- **标签**：自动使用统一画风 caption（anime cel-shading、flat color、clean thin black outlines 等），并自动过滤强人物五官/角色特征标签；不需要写 trigger，不需要正则图。
- 提前裁掉无用边框/字幕条；只使用你拥有版权或已获授权的图片。

### 5.2 👤 人物角色 LoRA 数据集（dataset/raw）

- **数量**：建议 15~30 张**同一人物**。
- **内容**：多角度（正面/侧面/背面）、不同服装、不同表情；图片越清晰越好，避免低分辨率大头照。
- **Trigger 触发词**：推荐设置**唯一**的 trigger（例如 `ohwx`、`mychar1`），预处理时自动插入每张标签第一行；推理时用 `trigger, 1girl, ...` 开头即可调用该角色。
- **正则数据集（可选）**：选择一个人物（或同角色）的补充图片文件夹作为正则数据集，写入 kohya 的 `is_reg = true` 数据集，用于防过拟合。
- **标签**：自动调用 kohya 官方 WD14 打标脚本生成完整标签（人脸/五官/服饰/角色特征全部保留）；如果原图目录里**已有同名 .txt**，则完整保留你自带的标签，不覆盖。

> WD14 打标需要联网下载模型（首次）。若网络不可用或未找到打标脚本，会自动回退为兜底标签并在日志中提示，不影响预处理完成。

### 5.3 预处理做了什么

| 处理 | 说明 |
|---|---|
| 统一缩放 1024px | 长边缩放到 1024，宽高向下取整到 8 的倍数（配合 bucket） |
| 去黑边 | 自动裁剪四周纯黑/近黑边框 |
| 去水印 | 右下角等常见水印区域启发式检测 + 图像修复 |
| 去重 | 人物模式默认按 MD5 跳过完全重复图片 |
| 打标签 | 画风=统一画风标签（过滤人物词）；人物=WD14 打标（完整保留）+ trigger |

预处理完成后自动生成 `configs/dataset_config.toml`（含 `num_repeats`；人物模式含 `keep_tokens=1` 与可选的 `is_reg` 正则数据集）。

### 5.4 命令行用法

```bat
:: 画风模式（默认）
"%PYTHON%" preprocess.py --input "D:\style_raw" --output "D:\train" --size 1024 --mode style --repeats 5

:: 人物模式
"%PYTHON%" preprocess.py --input "D:\char_raw" --output "D:\train_char" --size 1024 ^
    --mode character --trigger "ohwx" --reg-dir "D:\reg" --repeats 3 --dedup

:: 不自动 WD14 打标
"%PYTHON%" preprocess.py --input "D:\char_raw" --output "D:\train_char" --mode character --no-wd14
```

主要参数：`--size`、`--mode style/character`、`--trigger`、`--reg-dir`、`--repeats`、`--keep-tokens`、
`--dedup`、`--no-wd14`、`--wm-corner`、`--wm-force`、`--no-remove-watermark`、`--overwrite`。

---

## 6. 训练

### 方式 A：桌面主程序（推荐）

顶部选模式 → ③ 数据预处理 → ⑥ 一键训练（选底模 → 确认参数 → 开始）。训练参数按当前模式预设 + 你手动修改的高级参数自动组装，**底层仍然调用 sd-scripts 的 `sdxl_train_network.py`，未改动 kohya 调用**。

### 方式 B：网页 UI（Kohya-SS）

1. 双击 **`03_启动UI_StartUI.bat`**（或主程序 ④），浏览器打开 `http://127.0.0.1:7860`。
2. 点 **LoRA** 标签页 → `Import config` 选 `configs/style_lora_gui.toml`，把里面 3 个路径改成你机器上的实际路径即可训练画风 LoRA。
3. 人物模式可在网页 UI 里手动填参数（数据集配置已在预处理时生成）。

### 方式 C：命令行一键训练（画风）

双击 **`04_一键训练_TrainCLI.bat`**（可把底模路径作为第 1 个参数传入）。

---

## 6.5 总步数与防过拟合（重要）

**总步数计算公式：**

> 总步数 ≈ 图片张数 × repeats × max_train_epochs

**目标安全区间：1200 ~ 1800 步**（SDXL 人物 LoRA 训练）。步数过高模型会"死记硬背"训练图片，只能复刻原图，无法生成新姿势/新构图；步数太低则学不够。

**当前人物模式内置预设：repeats=3、max_train_epochs=6**（按当前数据集实测 73 张 → 73×3×6 ≈ 1314 步，落在安全区间）。

**手动调整方法（程序不会自动适配图片数量）：**
先用公式反推：`repeats × max_train_epochs ≈ 1200~1800 ÷ 图片张数`，再取整数组合。例如：

- 73 张：repeats×epochs ≈ 16~25 → 取 repeats=3、epochs=6（=18，得 1314 步）
- 30 张：repeats×epochs ≈ 40~60 → 取 repeats=4、epochs=12（=48，得 1440 步）
- 150 张：repeats×epochs ≈ 8~12 → 取 repeats=2、epochs=5（=10，得 1500 步）

原则：**repeats 控制在 2~4**（太高会反复记忆同一张图，是过拟合的主因）；步数不够就调大 epoch，步数超了先降 repeats。

> 说明：总步数还受 batch_size、bucketing（不同分辨率分批）影响，以训练开始时的日志为准。
> 训练会每 200 步保存一次 checkpoint，训练结束后全部快照整理到 `output\snapshots\`，方便挑选效果最好的中间权重（规避过拟合）。

## 7. 训练产物与使用模板

- **画风模式**：`output/anime_style_lora.safetensors` + `output/anime_style_lora_使用模板.txt`
- **人物模式**：`output/character_lora.safetensors` + `output/character_lora_使用模板.txt`
- `output/` 里还会按 `-000xxx.safetensors` 保存中间检查点（每 300 步）。

把 `.safetensors` 放进 WebUI 的 `models/Lora/`（或 ComfyUI 的 `models/loras/`）即可使用。

---

## 8. 推理提示

- **画风 LoRA**：无 trigger，直接写画风标签；推荐权重 **0.5~0.7**。示例：
  `anime cel-shading, clean thin black outlines, flat color, simple soft cel shading, tv anime screenshot, limited color palette, 1girl, cherry blossoms`
- **人物角色 LoRA**：以 trigger 开头，推荐权重 **0.6~0.9**。示例：
  `ohwx, 1girl, solo, masterpiece, best quality`
- 负面提示词建议：`lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, jpeg artifacts, signature, watermark, username, blurry, bad quality`

---

## 9. 常见问题（FAQ）

**Q1：训练时显存不足（OOM）**
确保梯度检查点为「自动/开启」；把 resolution 降到 512 重跑预处理；或改用 AdamW8bit（已是默认）。

**Q2：画风模式“记住角色”了**
数据集里是否大量重复同一个人 → 换成内容多样的图；确认 caption 保持统一画风（本工具会自动过滤人物标签）。

**Q3：人物模式效果不像 / 特征不突出**
确认 trigger 唯一且每张标签第一行都有；增加同人物不同角度图片；可适当提高 repeats/epoch，或把 rank 调高。

**Q4：WD14 打标失败 / 没打上标签**
首次需要联网下载模型；网络不可用时请配置系统代理后重试，或先自行给图片配好 .txt（会完整保留）。日志里会提示回退为兜底标签。

**Q5：`cuda available: False`**
更新 NVIDIA 驱动；确认在安装完成时 torch 检测到 GPU。

**Q8：底模怎么选？**
SD1.5 动漫模型（如 anything-v5、MeinaMix）选「SD1.5（512px）」；SDXL 模型（如 AniShadow V5）选「SDXL 1.0（1024px）」，注意 SDXL 推荐 16G+ 显存。

**Q9：一键开始训练提示图片太少？**
会自动过滤模糊/过小/损坏/重复图，过滤后画风至少 20 张、人物至少 15 张。补充清晰有效图片即可。

**Q5b：需要代理 / 访问 GitHub 吗？**
不需要。Git、Python、kohya_ss 源码都已内置；依赖走国内镜像（清华 pypi + 阿里 pytorch）。

**Q6：安装失败 / pip 报错**
把安装窗口往上翻找第一条红色错误；网络问题重试即可。

**Q7：为什么配置是 .toml？**
sd-scripts 官方支持 `.json` / `.toml` 配置（不支持 yaml）。本套件已自动生成。

---

## 10. 打包与安装

- **便携版**：运行 `build_portable.bat` 生成 `build_exe\dist\Kohya一键工具\`（并自动压缩为 `Kohya一键工具_便携版.zip`），整个文件夹解压即用。
- **安装包版**：运行 `build_installer.bat`（需先安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php)），生成 `build_exe\installer\Setup.exe`，默认安装到 `文档\KohyaLoraTool`（避开 Program Files 权限问题），自动创建桌面/开始菜单快捷方式与卸载入口，可勾选安装后直接启动。
- 打包时 `kohya_dir.txt` 会被清空，首次运行自动检测 kohya 源码；**不打包 torch / 大模型 / 用户数据**，仅代码、脚本、配置与离线安装包。
- **运行数据目录**：`output / dataset / logs / tokenizers` 会重定向到 `%APPDATA%\KohyaLoraTool`（避免权限报错）；`models\base`、`configs` 保留在程序目录。
- **显卡检测**：训练启动前自动检测 NVIDIA 显卡，非 N 卡会提示兼容性风险并询问是否继续。

## 11. 常见坑提醒

- kohya_ss 安装路径**不能有空格**（套件已自动规避）。
- 训练期间保持显卡驱动稳定，不要同时跑其他吃显存的应用。
- 遵守版权：不要训练版权画师作品与受版权保护的真人素材。
