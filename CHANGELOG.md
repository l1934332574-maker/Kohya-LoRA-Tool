# 更新日志（Changelog）

# 更新日志（Changelog）

# 更新日志（Changelog）

# 更新日志（Changelog）

# 更新日志（Changelog）

# 更新日志（Changelog）

# 更新日志（Changelog）

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
