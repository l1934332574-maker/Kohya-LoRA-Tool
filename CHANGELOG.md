# 更新日志（Changelog）

# 更新日志（Changelog）

# 更新日志（Changelog）

# 更新日志（Changelog）

# 更新日志（Changelog）

# 更新日志（Changelog）

# 更新日志（Changelog）

## v0.9.2（2026-08-16）

### 新增
- **FLUX.2 图像 LoRA 训练模式**：基于第二引擎 musubi-tuner（官方已支持 FLUX.2 训练）。训练用 **FLUX.2 klein base 4B**（DiT 约 7.2GB + Qwen3 4B 文本编码器约 7.5GB + FLUX.2 VAE 约 320MB，共约 16GB），应用内一键下载（国内 hf-mirror 镜像、断点续传、下完自动识别）。**8G 显存可跑**（自动开 fp8 + blocks_to_swap 省显存），推荐 12G+。含 FLUX.2 与 FLUX.1 的底模自动区分识别、新手引导（①②③④）、使用模板。

### 修复
- **自动更新误判"已是最新"（jsDelivr 等 CDN 缓存滞后导致）**：之前检查更新是"第一个能连上的源就返回结果"，一旦 jsDelivr 这类 CDN 缓存还没刷新（仍指向旧版本号 v0.9.0），旧版本就会误判没有新版本、永远提示已是最新。现在改为**多源全部拉取、取版本号最高的结果**（魔搭 / raw.githubusercontent / jsDelivr / GitHub API 四个源），只要任何一个源返回更高版本就能检测到更新，不再被单个源卡住。
- **更新包下载时界面"没反应"（无任何进度显示）**：下载用 curl -sS 静默模式，445MB 下载期间日志区完全无输出，用户以为卡死。现在下载时**实时显示进度**（每 10% 一行：『正在下载 v0.9.1：123.4MB / 445.6MB（27%）…』，走魔搭国内直链时还会标明下载源），并把 curl 连接超时从 60s 缩到 20s，失败更快给出提示。

---

## v0.9.1（2026-08-16）

### 修复
- **第二引擎（Krea2）/ 第三引擎（H3·Qwen·Z-Image）安装卡在下载 PyTorch（IncompleteRead/卡死）**：
  三个引擎装 torch 都是 pip 直连下载 2~3GB 大轮子（无断点续传），国内网络一断就失败。
  现在统一改为先 **curl 断点续传**从阿里 pytorch 镜像预下载轮子（torch/torchvision[/xformers][/torchaudio]）
  再本地 pip 安装，官方 pip 检测到已装即跳过；kohya / musubi（cu128）/ ai-toolkit（cu130）全覆盖。

---

## v0.9.0（2026-08-15）

### 新增
- **应用内自动更新**：主页新增「🔄 检查更新」按钮 + 启动后台自动检查。发现新版时提示下载并
  静默覆盖安装（约 445MB，curl 断点续传，装完自动重启，训练数据在 %APPDATA% 不受影响）。
  更新源为 GitHub Releases（需要每个版本的 Release 都附上 Setup.exe）。

---

## v0.8.3（2026-08-15）

### 修复
- **安装第二/三引擎误用 ComfyUI 精简 Python（No module named venv）**：`find_python()` 之前只查
  版本号、不校验能否建虚拟环境，会把 ComfyUI 便携版自带的嵌入式 python（无 venv 模块）当正经
  Python 用，导致 `-m venv` 建环境失败。现在会跳过不能 `import venv` 的精简 python，并补充扫描
  LOCALAPPDATA / Program Files 下 3.10~3.12 标准安装路径。

---

## v0.8.2（2026-08-15）

### 修复
- **AMD 流程误判 Python 3.12「已安装」跳过**：`detect_system_pythons()` 之前只认注册表 / py launcher
  的版本号、不校验 python.exe 是否存在，装失败或卸载残留会导致误报“已安装”而跳过安装；
  现在每个候选版本都会校验 exe 真实存在且能运行，误报不再发生。
- **画风模式 WD14 打标实际未生效（标签全一样）**：`preprocess.py` 的 `--caption` 默认值是写死的
  画风描述，导致「画风描述词留空 → 自动 WD14 打标」的判断永远为假，画风模式一直回退到统一写死标签
  （且与图片内容可能不符，如黑白线稿被标成彩色赛璐璐）。已改为默认空值，留空时真正走 WD14 打标并
  过滤人物标签；WD14 不可用时的画风兜底也改为画风描述而不是人物兜底。
- **安装训练内核卡在下载 torch（3.3GB）**：kohya 官方 setup 用 pip 直连下载 torch 大轮子
  （无断点续传，网络一抖就卡在 `Downloading torch-...whl`）。现在装 kohya 前先用 curl 断点续传
  预下载 torch/torchvision/xformers 轮子（阿里 pytorch 镜像）并 pip 装进 venv，官方 setup 检测到
  torch 已装即跳过下载；中断可续传、可重试。
- **使用模板读取真实训练标签**：训练完成生成的使用模板会读取当前项目训练集里实际写入的 caption
  填入「你的训练标签示例」（每个用户对应各自真实标签），并提示画风 LoRA 建议「触发词 + 画风标签」
  一起输入、单独一个触发词召唤效果较弱。

---

## v0.8.1（2026-08-15）

### 新增
- **应用内下载覆盖全部模型**（原来只有 SD1.5/SDXL 底模能在应用内下载，现在补齐）：
  - **FLUX.1 四件套**：DiT + CLIP-L + T5-XXL + AE，逐个应用内下载（断点续传）到 `models/base/`，下完自动扫描；
  - **Anima DiT 底模**：加入底模下载列表，应用内直接下载（约 4GB）；Qwen3-0.6B 文本编码器 + Qwen-Image VAE 首次训练自动下载；
  - **Krea 2 模型**：RAW / VAE / 文本编码器（+ 可选 Turbo）新增应用内下载对话框（断点续传），训练前缺模型时直接弹出；
  - 统一 H3 / FLUX / Krea2 的多文件下载对话框（每文件「⬇ 应用内 / 🌐 浏览器」+ 状态打勾）。
- **底模自动识别支持全部架构**：选择底模 / 打开项目恢复底模时，FLUX / Anima 也能自动识别并切换到对应预设（旧版只认 SD1.5/SDXL，新 GUI 3 处 + 旧 GUI 4 处一并修复）。

### 修复
- **一键预处理 / 一键训练卡死、停止报错**：`kohya_core/utils.py` 重构迁移时丢失进程管理的
  3 个全局变量（`_STOP_EVENT` / `_ACTIVE_LOCK` / `_ACTIVE_PROC`）和 `get_kohya_dir` 导入，
  导致子进程任务一启动就 NameError 静默崩溃、点「⏹ 停止当前任务」报错；已补回并验证停止流程正常。
- **AMD 自动安装失败时错误提示崩溃**：`except` 变量放进延迟执行的 lambda，Python 3 在 except
  结束后删除该变量导致 NameError；已改为先取值再传参。
- **Anima 训练在 8G 显存上极慢（约 110 秒/步、720 步 20+ 小时）**：1024px 下 Anima 超出 8G 显存、
  系统换页。现在 Anima 也按显存自动加 `--blocks_to_swap`（<12G=16 / <16G=8）并缓存冻结的
  Qwen3 文本编码器输出（`--cache_text_encoder_outputs`），大幅降低每步耗时。
- Anima 提示文案更新：明确 8G 能跑但 1024px 很慢，建议降到 512/768。
- Anima 提示文案更新：明确 8G 能跑但 1024px 很慢，建议降到 512/768。
- **AMD 流程误判 Python 3.12「已安装」跳过**：`detect_system_pythons()` 之前只认注册表 / py launcher
  的版本号、不校验 python.exe 是否存在，装失败或卸载残留会导致误报“已安装”而跳过安装；
  现在每个候选版本都会校验 exe 真实存在且能运行，误报不再发生。
- **画风模式 WD14 打标实际未生效（标签全一样）**：`preprocess.py` 的 `--caption` 默认值是写死的
  画风描述，导致「画风描述词留空 → 自动 WD14 打标」的判断永远为假，画风模式一直回退到统一写死标签
  （且与图片内容可能不符，如黑白线稿被标成彩色赛璐璐）。已改为默认空值，留空时真正走 WD14 打标并
  过滤人物标签；WD14 不可用时的画风兜底也改为画风描述而不是人物兜底。
- **安装训练内核卡在下载 torch（3.3GB）**：kohya 官方 setup 用 pip 直连下载 torch 大轮子
  （无断点续传，网络一抖就卡在 `Downloading torch-...whl`）。现在装 kohya 前先用 curl 断点续传
  预下载 torch/torchvision/xformers 轮子（阿里 pytorch 镜像）并 pip 装进 venv，官方 setup 检测到
  torch 已装即跳过下载；中断可续传、可重试。

---

## v0.7.3（2026-08-15）

### 修复
- **画风模式触发词机制**：画风模式支持「画风触发词」，训练时 keep_tokens 保护并同步进标签，
  生图输入一个词即可激活画风（与人物模式一致），不再需要复制整段标签。
- **画风模式打标改造**：不再默认使用写死的动漫 caption；新增「画风描述词」输入框（推荐，最准），
  留空则自动 WD14 打标并过滤人物/五官标签（黑白手绘等画风会保留 monochrome/sketch 等真实标签）。

---

## v0.7.2（2026-08-14）

### 修复
- **第三引擎安装蓝屏防护**：PyTorch cu130 需要 NVIDIA 驱动 570+。安装前自动检测驱动版本，
  过低则阻止并提示先更新驱动（否则首次运行 CUDA 可能驱动崩溃蓝屏）；安装后的验证不再初始化 CUDA，
  避免触发驱动崩溃。
- （承接 v0.7.1）第三引擎安装遇残留目录先清理再克隆。

---

## v0.7.1（2026-08-14）

### 修复
- **第三引擎安装失败修复**：ai-toolkit 目录若存在但不完整（clone 中断残留、缺 run.py），
  安装时先清理再重新克隆，不再报 "destination path already exists and is not an empty directory"。
- （承接 v0.7.0）Z-Image / Qwen-Image 模型步骤不阻塞一键训练。

---

## v0.7.0（2026-08-14）

### 新增
- **🖼 Qwen-Image / Z-Image LoRA（实验性）**：新增两个图像 LoRA 模式，走 AI Toolkit 第三引擎。
  - Qwen-Image（20B，Qwen/Qwen-Image-2512）：**16G 显存起步、24G 舒服（推荐）**，模型约 40GB。
  - Z-Image（8B，Tongyi-MAI/Z-Image）：**12G 显存起步、16G 舒服**，模型约 16GB。
  - 首次训练自动下载模型（国内镜像 hf-mirror），无需手动下载；训练用基础版，出图可配 Turbo 加速。
  - 模型/显存说明已写入软件引导与提示（DATASET_TIPS/引导步骤/确认弹窗/显存警告）。

---

## v0.6.4（2026-08-13）

### 修复
- **AMD 训练收尾崩溃自动兼容**：AMD 版 PyTorch 的 torch.distributed 可能是残缺构建
  （缺 is_initialized 等），训练全程正常但收尾时 accelerate 崩、最终模型保存失败。
  现在 AMD 模式训练前自动检测，残缺则写入条件生效的 sitecustomize 兼容层
  （仅训练进程补默认接口，不拖慢 pip/普通 python），幂等可重复。
- （承接 v0.6.3）分词器缓存完整性自愈 + 依赖补 protobuf。

---

## v0.6.3（2026-08-13）

### 修复
- **分词器缓存完整性修复**：训练前预缓存改为用训练环境（kohya/AMD venv）的 python 执行下载，
  并做完整性校验（clip 需 vocab/merges/config/special_tokens，其他需 tokenizer_config/tokenizer.json）；
  缓存不完整自动清理重建，避免训练时 from_pretrained 因缺文件崩（vocab_file=None）。
- **训练依赖自愈补 protobuf**：transformers 4.54 加载 tokenizer 的路径需要 protobuf，缺失会报
  "requires the protobuf library"，现加入检查与补装。

---

## v0.6.2（2026-08-13）

### 新增
- **H3 模型应用内下载器**：视频模式顶部「⬇ 下载 H3 模型」可直接下载 DiT/文本编码器/VAE
  （复用底模下载器，带进度/断点续传/取消/下完自动识别）；引导第③步直接进入下载对话框。
- **视频自动打标（Qwen2.5-VL）**：顶部「✨ AI 自动描述」用 Qwen2.5-VL-3B 自动给每段视频
  生成英文描述写进同名 txt（首次下载模型约 6~7GB，走 hf-mirror；已有 txt 跳过不覆盖）。

---

## v0.6.1（2026-08-13）

### 新增
- **智能新手引导（数据驱动）**：左侧引导改为按所选模式动态生成——主页不显示；
  画风/人物=环境→kohya→底模→图片，Krea2=环境→第二引擎→Krea2模型→图片，
  视频H3=环境→第三引擎→H3模型→视频。只显示该模式真正需要的步骤，
  不会让只训 H3 的用户去装 kohya/musubi。
- 引导步骤按顺序推进：每步完成自动高亮（呼吸闪烁）下一步，全部完成才点亮「一键开始训练」；
  一键按钮会提示还差哪一步。环境/引擎为全局绿点（装一次通用），底模/数据按项目重新检测。

---

## v0.6.0（2026-08-13）

### 新增
- **🎬 视频 LoRA（MiniMax H3，实验性）**：新增第三训练引擎 AI Toolkit（Ostris），支持 MiniMax-H3
  （33.1B 全模态视频模型）T2V LoRA 训练。
- 新训练模式「视频LoRA（MiniMax H3）」：独立 ai_toolkit_venv，不碰 kohya/musubi 环境；
  视频数据集（mp4 + 同名 txt 字幕）自动扫描/时长统计/占位字幕生成；训练 yaml 自动生成；
  H3 模型国内镜像下载引导（models/minimax_h3，约 40GB）。
- 显存适配：视频模式按 24GB 推荐做警告；LoRA rank32 / lr 2e-4 / 默认 2000 步（上限 3000 防过拟合）。
- ⚠ 说明：H3 训练为 NVIDIA 专属（CUDA/NVFP4），需要 24G+ 显存；AMD 用户不受影响（继续用其他模式）。

### 修复
- （承接 v0.5.7）AMD 训练环境 transformers/diffusers 版本校正。

---

## v0.5.7（2026-08-13）

### 新增
- **训练分辨率可调**：高级参数面板新增「训练分辨率」输入（默认按模式/底模自动填：SD1.5=512、SDXL/FLUX/Anima/Krea2=1024）。
  16G 显存跑 Krea 2 / SDXL 可手动降到 768 或 512 防爆显存；预处理裁切与训练同时生效；
  手动修改后切换模式/底模不会被覆盖，点「恢复预设」才回到推荐值。
- 训练确认弹窗、预设摘要同步展示当前分辨率。

---

## v0.5.6（2026-08-12）

### 修复
- **AMD 训练依赖自愈扩展**：toml/voluptuous 补上后，venv_amd 还缺 `imagesize`（sd-scripts dataset.py
  模块加载必需）→ 自愈检查扩到 sd-scripts 核心依赖（imagesize/rich/ftfy/einops/opencv/sentencepiece 等），
  补装时安装全量训练依赖（含 lion-pytorch/schedulefree/prodigy 系可选优化器）
- 检查用 find_spec 秒级，健康机器不触发安装

---

## v0.5.5（2026-08-12）


### 修复
- **训练环境运行时依赖自愈**：训练前检查 kohya venv / AMD venv 是否具备完整依赖
  （PIL/numpy/transformers/huggingface_hub/toml/voluptuous/safetensors/diffusers/accelerate/omegaconf），
  缺失自动补装（内置 wheel + 国内镜像 + 重试），修复 Anima 分词器缓存 / VAE 下载报
  `No module named 'transformers'` / `'huggingface_hub'`
- 检查用 importlib.find_spec（秒级），不拖慢训练启动

---

## v0.5.4（2026-08-12）


### 修复
- **AMD 训练环境缺 toml/voluptuous**：训练走 venv_amd 跑 sd-scripts 时报
  `ModuleNotFoundError: No module named 'toml'`（AMD 依赖列表漏了这两个小包）
- AMD 依赖列表补 toml/voluptuous；训练前自动检查 venv_amd 关键依赖，缺失自动补装（国内镜像+重试/超时）

---

## v0.5.3（2026-08-12）


### 修复
- **显卡显存检测改用 DXGI**（DedicatedVideoMemory）：修复 AMD 卡显存误报
  （注册表 qwMemorySize 对部分 AMD 卡误报、双显卡会取到核显）；
  16GB 卡不再被当成 8GB，训练显存适配/低显存提示/监控按真实显存走
- 检测优先级：DXGI → nvidia-smi → 注册表；排除核显/基础显示适配器取最大

---

## v0.5.2（2026-08-12）


### 新增 / 调整
- **Krea2 使用引导**：软件内新增「📖 Krea 2 使用引导」窗口，第 1~6 步逐步教学（装第二引擎→下载模型→选图→预处理→训练→出图），含模型国内镜像直链与常见问题
- **Krea2 参数校准**：预设 repeats 5→2（官方/社区量级，防过拟合）；隐藏无效的「文本编码器学习率」字段（Krea2 文本编码器预缓存、不训练）
- **Krea2 状态栏独立一行**：RAW→Turbo 提示 + 打开模型文件夹 + 使用引导按钮
- 桌面新增「Krea2参数数据库.md」参考文档（Musubi/AI Toolkit/OneTrainer/LoRAlab 交叉对照）

---

## v0.5.1（2026-08-12）


### 修复 / 增强
- **预处理自愈**：kohya venv 缺 Pillow/numpy 时自动补装，安装验证加强（修复中断安装导致的预处理永久失败）
- **Pillow/numpy 内置离线 wheel**：自动补装优先装本地包，彻底绕开网络不稳（`IncompleteRead`）
- **AMD 断点续传下载**：ROCm/PyTorch 大文件用 curl `-C -` 续传 + 重试；缓存文件加完整性校验，损坏自动重下
- **pip 下载**：全局重试/超时（`PIP_RETRIES=10`、`PIP_TIMEOUT=120`）+ 备用镜像 + 系统代理
- **Krea2 模式 UI**：隐藏 SD/SDXL/FLUX/Anima 底模下拉（Krea2 不用这些底模），改为显示 Krea2 模型状态 + 打开模型文件夹

---

## v0.5.0（2026-08-12）


### 新增
- **第二训练引擎（musubi-tuner，实验性）**：左侧新增「②' 第二引擎(可选)」独立环境安装入口，与现有 Kohya 环境完全隔离，可随时安装/跳过
- **「🖼 Krea 2 图像LoRA」模式**：基于 Krea 2（12.9B MMDiT）训练，预设 rank32/alpha32/1024px
  - `models/krea2` 模型解析 + 国内镜像下载引导（RAW 13~26GB / Qwen-Image VAE / Qwen3-VL 8GB）
  - 训练流程：缓存 latents/文本编码器 → accelerate 训练，显存自动 `fp8 + blocks_to_swap` 省显存
  - 缺模型/缺引擎引导弹窗、显存与确认弹窗适配、一键按钮状态适配
- `installers/` 内置 musubi-tuner 离线源码包

### 修复
- musubi 数据集配置 schema 兼容（移除 `keep_tokens`/`shuffle_caption` 等不被接受的 key）
- Krea2 VAE 下载链接指向正确仓库（`Comfy-Org/Qwen-Image_ComfyUI`）
- 缓存/训练脚本 `num_workers` 传参修正（musubi 线程池不接受 0）

### 说明
- Krea2 训练需 12G+ 显存（推荐 16G）；本机 8G 仅可做预处理与查看界面
- 视频 LoRA（Wan 等）训练开发中

---

## v0.4.0（2026-08-12）

### 新增
- 项目管理：主页项目列表、新建/打开/重命名/删除、配置自动保存、预设模板
- 数据集按项目隔离 `dataset/<项目名>/`，旧共享数据一次性迁移，重命名同步改目录
- 标签编辑器：逐张改标签、批量删除/替换、置顶 Trigger、标签频率统计、整理 `repeats_名称`
- 训练实时监控：步数/总步数、loss + 趋势曲线、显存、预计剩余时间、训练速度
- `repeats_名称` 子目录结构；预处理自动递归子文件夹；新建项目清空旧配置
- WD14 打标模型内置，自动 GPU(CUDA) 推理，失败回退 CPU
- 启动性能优化（主卡片延迟构建、阴影防抖、底模扫描后台化）

### 修复
- 训练写 dataset_config 时三元组解包崩溃
- 断点续训、训练前自动同步 Trigger、停止按钮

### 说明
- AMD 兼容模式（实验性）：sdpa + bf16 + AdamW 自动适配
- kohya 环境重定向 `%APPDATA%`，升级覆盖不重装环境
