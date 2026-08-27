## v0.10.17（2026-08-27）

### 修复：Krea2/FLUX.2 16G 显存被误判成 12G 档，RTX 4080 SUPER 训练慢 4~5 倍
- **背景**：用户 RTX 4080 SUPER（16G）Krea2 人物 LoRA（768px，29 图 × 2 repeats × 16 epochs = 928 步）实测 11~17s/it、ETA 3~4 小时，手动停止。社区同档 16G 卡实测约 2~4s/it（如 5060 Ti 16G 在 OneTrainer 跑 Krea 为 2.x s/it）。
- **根因**：工具显存自适应用 `vram_gb < 16` 判断档位，而 Windows DXGI 检测 16G 卡常报告 15.6~15.9GB（4080 SUPER 实测 15.67GB）→ 被误判成 12G 档，Krea2 自动 `blocks_to_swap=12`（每步在 CPU↔GPU 搬运 12 个 DiT 块，瓶颈在 PCIe 搬运而非显卡算力）。
- **已修**：Krea2/FLUX.2 的 blocks_to_swap 档位改用**显存取整判断**（15.67→16），16G 卡走 16-24G 档——Krea2 swap 12→6、FLUX.2 swap 6→2；H2D-only 单向交换对 16G 档保持开启（LoRA 冻结底模，Fizgig 实测块交换快 ~6.4×）。量化维持 int8（社区确认更快）；8G/12G/20G/24G/未知档位行为不变。
- **验证**：新增 SWAP_TIER_RESOLUTION_OK 单元测试（15.67→Krea2 (6, True) / FLUX.2 (2, True)，并锁死 8/12/16/20/24/未知档位），engine_install_smoke_test + smoke_test 全过。

## v0.10.16（2026-08-27）

### 修复：Krea2/FLUX.2 开「训练中采样预览」后启动即崩（tokenizer 在线拉取 SSL 失败）
- **背景**：用户 Krea2 人物 LoRA 训练（29 图）一键训练，latents/文本编码器缓存都正常，但训练一启动就报：
  `HTTPSConnectionPool(host='huggingface.co' ... /Qwen/Qwen3-VL-4B-Instruct/resolve/main/tokenizer_config.json ... SSLCertVerificationError)`，训练直接退出码 1。
- **根因**：v0.10.11 加采样预览后，训练命令带 `--sample_every_n_steps=100 + --text_encoder`，训练子进程加载文本编码器做采样提示词编码时需要 tokenizer。`train_krea2`/`train_flux2` 的**缓存步骤**都传了 `env=_k2env`（含 `KREA2_TOKENIZER_DIR` 本地 tokenizer + `HF_ENDPOINT=hf-mirror`），但**训练步骤的 run_stream 漏传 env** → 子进程读不到本地 tokenizer，回退在线拉 `Qwen/Qwen3-VL-4B-Instruct`，国内直连 HF 必崩。采样预览默认开启，所以 v0.10.11 之后该问题必现。
- **已修**：`train_krea2`/`train_flux2` 训练命令补传 `env=_k2env`（与缓存步骤一致）；同时顺带修复 RDNA2 训练步骤漏传 `KREA2_FP16`（此前 fp16 只在缓存生效，训练仍是 bf16 → 潜在黑图）。
- **验证**：新增 KREA2_TRAINING_ENV_PROPAGATION_OK 回归测试（4 处 run_stream 均传 env=_k2env），engine_install_smoke_test + smoke_test 全过。

### 新增：一键导出日志（反馈/求助时把 txt 直接发给维护者）
- **背景**：用户反馈问题常只贴半截日志 / B 站有字数限制 / 截图超大小，维护者来回追问环境信息成本高。
- **已做**：
  - 日志面板标题栏新增「📤 导出日志」按钮（训练监控栏也有同款小按钮，训练中随时可导）；
  - 一键导出为 `KohyaLoRA_<项目>_<时间>.txt`（默认存桌面，桌面不可写自动落到数据目录 logs/），内容含：软件版本 / 项目 / 操作系统 / Python / Git / 显卡（厂商+显存）/ NVIDIA 驱动 / 安装目录 / 数据目录 / 三引擎安装状态 / 训练环境 torch 后端（cuda/rocm/cpu）+ 完整运行日志；
  - 导出完成弹窗：打开文件 / 打开所在文件夹（定位到文件）/ 复制路径；
  - 导出在后台线程执行（torch 后端检测不卡界面），失败不阻断。
- **验证**：新增 EXPORT_LOG_OK（纯函数组装 + GUI 接线断言），engine_install_smoke_test + smoke_test 全过。

### 修复：第三引擎（ai-toolkit）大模型下载走 Xet CDN 卡死（peer closed / read timed out）
- **背景**：用户第三引擎训练（Qwen-Image/Z-Image），模型下载卡在 `Fetching 30 files`（57%→87% 反复重试 20+ 分钟），日志大量 `us.aws.cdn.hf.co/xet-bridge-us/... peer closed connection without sending complete message body` / `The read operation timed out`。
- **根因**：huggingface_hub 的 `HF_HUB_DISABLE_XET` 是 **import 时读进常量**（constants.py）；ai-toolkit run.py 内部自己 spawn 的 snapshot_download 若没带上工具构造的 env，就会走 Xet CDN（AWS 海外），国内大文件下载极易断连/超时卡死。
- **已修（根治）**：新增 `_ensure_venv_hf_sitecustomize()`——向三个训练环境（kohya venv / musubi-venv / ai_toolkit_venv）的 site-packages 注入 `sitecustomize.py`（Python 启动时在任何 import 前自动执行），强制 `HF_ENDPOINT=https://hf-mirror.com` + `HF_HUB_DISABLE_XET=1`。任何用该 venv 启动的进程/线程/子进程都被覆盖，不再可能走 Xet；幂等（已注入跳过），已有自定义 sitecustomize 追加不覆盖。五个训练入口（kohya / Krea2 / FLUX.2 / Qwen-Image·Z-Image / H3 视频）+ AMD 自定义环境均已接线。
- **验证**：本地实测注入后 `constants.HF_HUB_DISABLE_XET = True`（Xet 关闭、走 hf-mirror）；新增 VENV_HF_SITECUSTOMIZE_OK（注入/幂等/追加不覆盖/5 入口接线），engine_install_smoke_test + smoke_test 全过。

## v0.10.15（2026-08-26）


### 修复：Krea2 Raw/Turbo 下载 403 根治——改走魔搭官方转存（免许可一键下载）
- **背景**：v0.10.14 加入门禁引导后，Krea-2-Raw / Krea-2-Turbo 仍是 HuggingFace 门禁模型，hf-mirror 匿名直连必 401/403，用户仍需手动接受许可或配 HF_TOKEN。
- **已修（根治）**：
  - Krea2 raw / turbo 下载源改走魔搭（ModelScope）官方转存直链：`krea/Krea-2-Raw`、`krea/Krea-2-Turbo`（`resolve/master/raw.safetensors` / `turbo.safetensors`），无需接受许可、无需代理、国内 CDN 直连；
  - 文件名不变（`raw.safetensors` / `turbo.safetensors`），模型识别 / 训练命令零改动；
  - 应用内下载器（model_downloader）本就对 modelscope.cn 直连（不套系统代理）+ 断点续传，可直接复用；
  - VAE / Qwen3-VL 文本编码器链接非门禁，继续走 hf-mirror（实测 206 正常）；
  - 下载前预检保留为兜底：仅当源仍返回 401/403 时弹窗提示（改为说明已内置魔搭直链）。
- **验证**：`_http_status` 四链接均 206；`get_remote_size` 正确解析 26.2GB；ModelDownloader 实测下载约 24MB/s、断点续传正常；engine_install_smoke_test（新增 KREA2_MODELSCOPE_MIRROR_OK）+ smoke_test 全过。

## v0.10.14（2026-08-26）


### 修复：Krea2 Raw/Turbo 下载 401/403（HF 门禁模型）+ 下载器支持 HF_TOKEN
- **背景**：用户应用内下载 Krea2 raw/turbo 报 `HTTP Error 403`。实测 Krea-2-Raw / Krea-2-Turbo 是 HuggingFace 门禁模型（需接受 Krea 许可 + token），hf-mirror 匿名下载必 401/403；VAE / 文本编码器链接正常。
- **已修**：
  - 下载器支持环境变量 `HF_TOKEN`（`Authorization: Bearer` 头），已接受许可的用户可设 token 后应用内下载；
  - 401/403 失败时给出明确门禁引导（浏览器手动下载 / 设 HF_TOKEN / 等国内镜像）；
  - Krea2 raw/turbo 下载前预检状态码，401/403 直接弹窗引导，不再无效下载。
- **验证**：GATED_DOWNLOAD_GUIDANCE_OK，engine_install_smoke_test + smoke_test 全过。

## v0.10.13（2026-08-26）

### 修复：Z-Image / Qwen-Image 预下载「HF 缓存存在但本地残缺」仍误判就绪（v0.10.12 漏网）
- **背景**：v0.10.12 发布后 D 盘用户 Z-Image 仍报 `no config.json found in .../models/at_image/zimage`。
- **根因**：`at_image_model_ready` 的「HF 缓存目录存在也算就绪」兜底，本地残缺时误判就绪、训练指向残缺目录。
- **已修**：去掉 HF 缓存兜底，仅本地预下载目录完整才算就绪；残缺时重新 snapshot_download（自动复用 HF 缓存文件，不重复下载 16GB）。
- **验证**：回归测试新增「HF 缓存存在但本地残缺→不得判就绪」，engine_install_smoke_test + smoke_test 全过。

## v0.10.12（2026-08-26）

### 修复：Krea2 采样预览开启后启动即崩溃（缺 --text_encoder）
- **背景**：用户 Krea2 训练开采样预览，启动崩：`AssertionError: --text_encoder is required for sample generation during training`。
- **根因**：train_krea2 训练命令原本不传 `--text_encoder`（TE 只用于缓存，训练脚本不需要）；加采样后 musubi 需要 TE 编码采样提示词 → assert。
- **已修**：采样开启时追加 `--text_encoder <路径>`（FLUX.2 本来就有，未受影响）。
- **验证**：SAMPLE_PREVIEW_OK 新增断言，engine_install_smoke_test + smoke_test 全过。

## v0.10.11（2026-08-26）

### 新增：训练中采样出图预览（三个引擎全覆盖）
- **kohya（SD1.5/SDXL/FLUX/Anima）**：训练命令加 `--sample_every_n_steps=100` + `--sample_prompts`（提示词文件自动生成：trigger + 质量词）。
- **musubi（Krea2 / FLUX.2）**：同样加 `--sample_every_n_steps=100` + `--sample_prompts`（musubi 原生支持）。
- **ai-toolkit（H3 视频 / Qwen-Image / Z-Image）**：yaml 原生 `sample:` 块已有，无需改动。
- **预览展示**：训练监控面板新增「采样预览」区，每 2 秒轮询输出目录最新的 `*sample*.png` 并显示；不解析训练日志、不写文件、不影响训练进程。
- **显存门控**：默认开启；显存 <10G 不再硬关，改为打印 OOM 警告（8G 卡 512/768 + block swap 通常能扛住采样）；GUI 提供「训练中采样预览」勾选，取消勾选即完全关闭。


### 修复：Z-Image / Qwen-Image 预下载半截缓存误判就绪（用户报 no config.json found）
- **背景**：用户 Z-Image 训练报 `Error no file named config.json found in directory .../models/at_image/zimage`——预下载中断留下半截目录，旧就绪判定只查"目录存在"就误判下载完成，训练指向不完整本地目录。
- **已修**：新增 `_at_image_download_complete()` 严格校验（必需 config.json + 按 `.safetensors.index.json` 校验全部分片/单文件权重齐全）；不完整自动续传，仍不完整则提示删除半截缓存并回退在线加载。

### 验证
- 新增 SAMPLE_PREVIEW_OK 回归测试（提示词文件生成 / 显存门控 / 三引擎命令接线 / GUI 预览组件断言），engine_install_smoke_test + smoke_test 全过。

## v0.10.10（2026-08-26）

### 修复：训练时 huggingface_hub Xet 下载 401 / 卡 0.00B（第三引擎 H3、Z-Image、Qwen-Image）
- **背景**：用户第三引擎训练启动时在线下载模型（H3 ~12.3GB、Z-Image ~16GB）失败：`CAS Client Error: HTTP 401 Unauthorized (cas-server.xethub.hf.co)`，或卡在 `Downloading bytes: 0.00B / Fetching 2 files: 0/2`。
- **根因**：huggingface_hub 1.x 对 Xet 存储仓库默认走 Xet 协议，直连 `cas-server.xethub.hf.co`，绕过 `HF_ENDPOINT=hf-mirror.com` 镜像；该通道对部分国内网络返回 401 / 卡死。
- **已修**：`kohya_core/utils.py` 的 `build_env()`（所有子进程统一环境）新增 `HF_HUB_DISABLE_XET=1`，全局禁用 Xet，回退经典 HTTP 走 hf-mirror 镜像。

### 新增：第三引擎 Z-Image / Qwen-Image 底模国内直链预下载
- 训练前自动用 snapshot_download（hf-mirror + 断点续传 + 可手动停止）把 diffusers 整仓预下载到数据目录 `models/at_image/<mode>`，训练 yaml 的 `name_or_path` 指向本地目录离线加载，不再训练时在线拉 16~40GB。
- 下载失败自动回退原在线加载路径，不阻断。

### 修复 / 优化（小件批量）
- **WD14 无 Triton 告警降噪**：打标输出里 `No module named triton` / `Detected no triton` 等整段 traceback 折叠成一行友好提示，不再误认打标失败。
- **Krea2/FLUX.2 float32 自愈防线补全**：musubi 版本检查泛化（Krea2 + FLUX.2 双标记），并补上 train_flux2 的接入——旧版 musubi 会以 float32 训练（300s/步）时直接阻止并提示重装第二引擎。
- **预处理损坏图片提前隔离**：`load_image` 立即 `im.load()` 校验像素；主流程前扫描输入图，损坏图（含同名 .txt）提前移到 `<输入目录>_corrupt` 并明确提示是哪张图，避免裸 PIL traceback。
- **FLUX.2 缺文本编码器提示优化**：检测到 Anima 的 Qwen3-0.6B 时明确说明「FLUX.2 需要 4B 的 qwen_3_4b.safetensors，0.6B 不适用」。


### 修复：Z-Image / Qwen-Image 预下载半截缓存误判就绪（用户报 no config.json found）
- **背景**：用户 Z-Image 训练报 `Error no file named config.json found in directory .../models/at_image/zimage`——预下载中断留下半截目录，旧就绪判定只查"目录存在"就误判下载完成，训练指向不完整本地目录。
- **已修**：新增 `_at_image_download_complete()` 严格校验（必需 config.json + 按 `.safetensors.index.json` 校验全部分片/单文件权重齐全）；不完整自动续传，仍不完整则提示删除半截缓存并回退在线加载。

### 验证
- 新增 6 条回归测试（预下载流程 / 本地就绪判定 / Triton 降噪 / musubi 版本检查 / 坏图隔离 / 0.6B 提示），engine_install_smoke_test + smoke_test 全过。

## v0.10.9（2026-08-26）

### 修复：第三引擎（ai-toolkit）依赖安装报 ResolutionImpossible（numpy 2.5.x 无 cp310/cp311 轮子）
- **背景**：用户（Python 3.10 venv）第三引擎装到「ai-toolkit 依赖」步骤报 `ERROR: Cannot install numpy==2.5.2 ... ResolutionImpossible`，日志提示 `no matching distributions available for your environment: numpy`。
- **根因**：安装器在生成的 requirements 与约束文件里硬编码 `numpy==2.5.2 + scipy==1.18.0`，但 numpy 2.3/2.4/2.5 只有 cp312 轮子（cp310 最高 2.2.6、cp311 最高 2.4.6）→ Python 3.10/3.11 下 pip 找不到匹配版本 → 解析失败。
- **已修**：两处硬编码改为 `numpy==2.1.3 + scipy==1.15.3`（cp310/311/312 三版本均有轮子，与 kohya 训练环境同一配对），并加注释防止回退到 2.5.x。
- **验证**：Python 3.10 venv 完整复现用户报错 → 修复后解析成功（cp310 / cp312 双版本实测）；engine_install_smoke_test 的 test_third_engine 断言同步更新（含「不得含 2.5.2/1.18.0」反向断言），全过。

## v0.10.8（2026-08-26）

### 修复：先装第二/三引擎再装第一引擎报「目标目录非空且不是 kohya_ss」
- **背景**：用户先装第三引擎（ai-toolkit/H3 视频），再装角色/画风（第一引擎 kohya）时报 `目标目录非空且不是 kohya_ss: .../kohya_ss`。
- **根因**：第二/三引擎默认装在 `get_kohya_dir()` 同一个目录下（`musubi-tuner/musubi-venv/ai-toolkit/ai_toolkit_venv` 子目录）。先装其它引擎后 `kohya_ss` 目录非空但无 kohya 标记（无 kohya_gui.py / .git），`install_kohya` 一律判为"被占用" → 拒绝安装。
- **已修**：新增 `_kohya_dir_has_foreign_content()`——仅当目录含"非 kohya 也非第二/三引擎"的陌生内容时才阻止；只含 musubi/ai-toolkit 等共存子目录时放行，kohya 与其它引擎共存安装到同一目录（引擎安装目录本就同源，不冲突）。
- **验证**：新增 `KOHYA_COEXIST_WITH_OTHER_ENGINES_OK`（预置 musubi/ai-toolkit 子目录后完整跑 install_kohya 成功且其它引擎目录保留）+ `KOHYA_FOREIGN_CONTENT_STILL_BLOCKS_OK`（陌生文件仍阻止，防呆保留），engine_install_smoke_test + smoke_test 全过。

## v0.10.7（2026-08-26）

### 新增：人物 LoRA 自动强绑定（一个触发词绑定一个人物）
- **背景**：用户反馈训练出的人物 LoRA 只写 trigger 生图时"完全不相干"——因为人物身份特征（发色/瞳色/发型等）散落在标签里，kohya 打乱/丢弃标签时特征被拆散，trigger 与人物特征绑定弱。
- **原理**：市面所有工具（kohya/秋叶/OneTrainer）做法一致：trigger 固定写在每张 caption 第一行 + keep_tokens 保护 + 特征词尽量 100% 一致。本工具已有 trigger 自动插入 + keep_tokens 保护，本次补上"自动提取 100% 一致特征词并固定前缀"。
- **已做**：
  - preprocess.py 新增 analyze_caption_features() / apply_strong_binding()：统计训练集全部 caption，找出 **100% 出现**的身份特征词（自动排除 trigger 本身与 1girl/solo/构图/画质等通用标签），把 trigger + 特征词 拼成固定前缀写到每张标签开头，并返回建议 keep_tokens（覆盖整组前缀，打乱/丢弃标签时不动它）。
  - 人物模式下默认开启（GUI 触发词卡片新增「人物强绑定」勾选，默认勾选，可取消）：预处理后标签即为 trigger, blue hair, blue eyes, ... 固定前缀，训练前也会自动同步重写。
  - **特征一致性检查**：某特征只出现在部分图（如 white hair 只有 22/24）→ 训练前警告"特征只在 x/y 张出现，人物一致性不足"，提醒用户补图/统一特征。
  - **手动固定区**：标签里可写 ||| 分隔符，||| 前为固定区（用户自定义，保持原顺序）、后为可动区；工具识别后去掉 ||| 并按固定区标签数设 keep_tokens（进阶用法，普通用户无需理会）。
  - 接入 kohya 引擎（SD1.5/SDXL/FLUX/Anima）、第二引擎（Krea2/FLUX.2）、第三引擎（Qwen-Image/Z-Image）人物/子模式；Krea2/FLUX.2 的 musubi 不吃 keep_tokens，但固定前缀置顶同样增强绑定。
- **验证**：新增 STRONG_BINDING_OK 冒烟测试（100% 特征提取 + 前缀置顶 + keep_tokens + 一致性警告 + ||| 手动固定区 + 幂等 + 三引擎/GUI 接入断言），engine_install_smoke_test + smoke_test 全过。

## v0.10.6（2026-08-25）

### 修复：FLUX.2 低显存 int8 训练启动即断言崩溃（musubi 只处理 fp8 不处理 int8）
- **背景**：用户 8G（FLUX.2 自动 int8）训练启动崩：`flux2_utils.load_flow_model` 断言 `(fp8_scaled or int8_base) and dit_weight_dtype is None` 不成立 → `AssertionError`。
- **根因**：musubi `trainer_base.py` 的 `dit_weight_dtype = ... if args.fp8_base else dit_dtype` 只处理 `fp8_base`，`--int8_base` 时仍取 `dit_dtype`(bf16) → 与断言冲突（int8 时 dit 权重 dtype 应为 None）。
- **已修**：新增 `_patch_musubi_int8_weight_dtype()` 幂等补丁（随 Krea2/FLUX.2 共用补丁链自动打）：`fp8_base 或 int8_base` 时 `dit_weight_dtype=None`；普通 bf16/fp16 训练不受影响。
- **验证**：新增 `MUSUBI_INT8_WEIGHT_DTYPE_PATCH_OK` 冒烟测试（模拟 musubi 文件替换 + int8/普通两场景断言），engine_install_smoke_test + smoke_test 全过。

---## v0.10.5（2026-08-25）

### 修复：繁体/英文系统下 Krea2 缓存 latents 打印中文崩溃（cp950/cp1252 UnicodeEncodeError）
- **背景**：用户（繁体中文系统，cp950）Krea2 一键训练，`krea2_cache_latents.py` 打印含项目名「项目_」的路径时崩溃：`UnicodeEncodeError: 'cp950' codec can't encode character '\u9879'`。
- **根因**：`train_krea2` 调用 `krea2_cache_latents.py` 时**漏传 env**，子进程 stdout 跟随系统 locale（cp950 繁体 / cp1252 英文）→ 打印中文崩；上一轮只在 `build_env()` 加了 `PYTHONIOENCODING=utf-8`，但只对显式传 env 的调用生效，漏掉了这个入口。
- **已修**：`run_stream()`（所有子进程统一入口）`env=None` 时默认用 `build_env()`（含 `PYTHONIOENCODING=utf-8`），全局防线——任何调用漏传 env 都不会再出现编码崩溃。
- **验证**：新增 `RUN_STREAM_DEFAULT_UTF8_OK` 冒烟测试（静态断言 + 实测 run_stream 打印中文成功），engine_install_smoke_test + smoke_test 全过。

---## v0.10.4（2026-08-25）

### 修复：手动修改项目 json 后点「打开」无反应（静默失败）
- **背景**：用户手动编辑项目 json（改 base_model 等字段）后，软件里点「打开」没反应、打不开项目。
- **根因**：`cmd_open_project` 未包裹异常；手动改过的 json 字段类型/结构异常（如 base_model 非字符串、params 非 dict）→ `_apply_project_data` 抛异常 → 冒泡到按钮回调，GUI 静默失败（无提示）。
- **已修**：
  - `cmd_open_project` 用 try/except 包裹配置恢复，失败时日志提示「已按默认配置打开」并继续打开（不再静默无反应）。
  - `_apply_project_data` 对 `mode` / `base_type` / `base_model` / `params` 做类型校验（非字符串/dict 自动忽略/回退），手动改坏字段也能安全打开。
- **验证**：新增 `PROJECT_OPEN_ROBUST_OK` 冒烟测试，engine_install_smoke_test + smoke_test 全过。

### 优化：FLUX 模型下载全部改走魔搭（ModelScope）国内直链
- **背景**：用户反馈 FLUX 模型直连 HuggingFace 下载 SSL 失败（`CERTIFICATE_VERIFY_FAILED`）；hf-mirror 偶发不稳。
- **已做**：`FLUX_MODEL_LINKS` 4 个文件（DiT 22.2G / CLIP-L / T5-XXL / AE）全部改为魔搭国内直链（已验证 `Comfy-Org/flux1-dev`、`comfyanonymous/flux_text_encoders`、`Kijai/flux-fp8` 魔搭镜像，支持断点续传、国内 CDN）。
- 验证：链接检查 + smoke_test + engine_install_smoke_test 全过。

---## v0.10.3（2026-08-25）

### 修复：英文系统（cp1252）下训练打印中文崩溃（UnicodeEncodeError）
- **背景**：用户（Administrator，英文 Windows）Anima 训练时 `accelerator.print()` 打印含中文的内容（trigger/项目名/caption）→ 子进程 stdout 编码为 cp1252（英文系统默认）→ `UnicodeEncodeError: 'charmap' codec can't encode characters` → 训练直接崩溃。
- **根因**：`build_env()` / `build_direct_env()` 未设置 `PYTHONIOENCODING`，训练/预处理子进程 stdout 跟随系统 locale（英文=cp1252），无法编码中文。
- **已修**：`build_env()` 全局 `env.setdefault("PYTHONIOENCODING", "utf-8")`（不覆盖用户已有设置），所有训练/预处理/安装子进程 stdout 强制 UTF-8；`run_stream` 父进程本就按 UTF-8 解码，天然一致。
- **验证**：新增 `BUILD_ENV_UTF8_OUTPUT_OK` 冒烟测试（cp1252 打印中文复现崩溃 → build_env 强制 utf-8 后正常），engine_install_smoke_test + smoke_test 全过。

### 修复：Krea2 / Qwen-Image / Z-Image 画风子模式训练报「缺少预处理数据」
- **背景**：用户 Krea2 画风子模式一键训练，预处理"可用图片 29 张"成功，但训练报 `缺少预处理数据：...dataset\<项目>\train`。
- **根因**：预处理对 Krea2/Qwen-Image/Z-Image 统一输出到 `train_character`（`dataset_mode="character"`），但 `train_krea2` / `train_at_image` 按画风子模式（`at_sub_mode=style`）读 `train` 目录 → 目录不一致。
- **已修**：`train_krea2` / `train_at_image` 统一读 `train_character`（与预处理一致），画风子模式不再切到 `train`。
- **验证**：新增 `KREA2_STYLE_SUBDIR_CONSISTENCY_OK` 冒烟测试，engine_install_smoke_test + smoke_test 全过。

---## v0.10.2（2026-08-24）

### 修复：Krea2 / FLUX.2 / Qwen-Image / Z-Image 只装第二/第三引擎时，一键训练误报「Kohya 尚未安装」
- **根因**：`preprocess()`（数据预处理）固定用第一引擎（Kohya）venv 的 Python（`venv_python()`），Krea2/FLUX.2/Qwen-Image 用户只装第二/第三引擎、没装 Kohya → 一键训练预处理阶段报「Kohya 尚未安装」。该 bug 自 Krea2 模式加入以来一直存在。
- **已修**：新增 `_pick_preprocess_python()` 多引擎 fallback：Kohya venv → musubi-venv（第二引擎）→ ai_toolkit_venv（第三引擎）；预处理只需要 PIL/numpy（缺失自动补装），任何引擎 venv 都能跑。
- **验证**：新增 `PREPROCESS_PYTHON_FALLBACK_OK` 冒烟测试（kohya/musubi/ai_toolkit 优先序 + 全缺失），engine_install_smoke_test + smoke_test 全过。

### 新增：MiniMax H3 模型完整性校验（防 SafetensorError）
- **背景**：用户 nvfp4 下载中断残留损坏文件，工具只按文件名判定「模型齐全」，训练加载时 `SafetensorError: incomplete metadata, file not fully covered`。
- **已做**：`h3_model_files()` 增加文件大小校验（nvfp4 ≈11.7GB / int8 ≈19.5GB / TE ≈15GB / video_vae ≈5GB），明显偏小的文件视为缺失；新增 `h3_incomplete_files()`，`h3_missing_models()` 会提示「文件疑似下载不完整，请删除后重新下载」。

### 新增：12~16G 显存 H3 训练前强提示必须用 nvfp4
- **背景**：12G + int8（19.5G）物理放不下，训练准备阶段 `unet.to(device)` 必 OOM（实测）。
- **已做**：`train_h3` 检测 `vram_gb<16 且无 nvfp4` 时直接阻止并给出魔搭直链（int8 仅 24G+ 放行）。

### 修复：视频模式「数据预处理」不再自动跳训练
- **背景**：视频模式点「数据预处理」→ 扫描后 AUTO_CONFIRM 自动进入训练确认（含重装 torch 弹窗）→ 误触发训练。
- **已做**：视频模式点「数据预处理」只扫描并提示「视频数据已就绪，请直接点【一键训练】」，不再自动进入训练流程。


### 修复：Z-Image / Qwen-Image 预下载半截缓存误判就绪（用户报 no config.json found）
- **背景**：用户 Z-Image 训练报 `Error no file named config.json found in directory .../models/at_image/zimage`——预下载中断留下半截目录，旧就绪判定只查"目录存在"就误判下载完成，训练指向不完整本地目录。
- **已修**：新增 `_at_image_download_complete()` 严格校验（必需 config.json + 按 `.safetensors.index.json` 校验全部分片/单文件权重齐全）；不完整自动续传，仍不完整则提示删除半截缓存并回退在线加载。

### 验证
- 新增 `H3_INTEGRITY_AND_NVFP4_REQUIRED_OK`、`VIDEO_PREPROCESS_NO_AUTO_TRAIN_OK`、`PREPROCESS_PYTHON_FALLBACK_OK` 冒烟测试；engine_install_smoke_test + smoke_test 全过。

---## v0.10.1（2026-08-24）

### 修复：H3 模型下载全部改走魔搭（ModelScope）国内直链
- **背景**：用户反馈 nvfp4 量化模型走 hf-mirror 下载巨慢（部分文件慢/不稳定）。
- **已修**：`H3_MODEL_LINKS` 5 个文件（int8 主模型、nvfp4 主模型、Qwen3-VL-32B TE、视频 VAE、音频 VAE）全部改为魔搭国内直链（`cdn-lfs-cn-1.modelscope.cn`，已验证支持断点续传、国内直连快）。
  - int8/TE/VAE 用 `Comfy-Org/minimax-H3`；nvfp4 用 `Abiray/MiniMax-H3-nvfp4-INT4-INT8-Convrot`（魔搭同名镜像）。
- 冒烟测试全过。

---
## v0.10.0（2026-08-24）

### 新增：MiniMax H3（视频 LoRA）低显存自动适配（照搬 ai-toolkit 官方 / RunComfy 社区配置）
- **背景**：用户 12G 显卡训练 H3 在加载阶段 OOM（`text_encoder.to(device)` 时 `CUDA out of memory`）。H3 为 33B 全模态模型，DiT int8 约 19.5G + Qwen3-VL-32B TE 约 14.6G，无法同时常驻显存（24G 卡也一样）。
- **已做**（`write_h3_train_yaml`）：
  - **`low_vram: true` 对所有 H3 训练默认开启**（ai-toolkit GUI 默认值、RunComfy 官方指南建议）：DiT/TE 初始放 CPU、训练按需搬显存，根治「加载即 OOM」。
  - **`layer_offloading` <24G 自动开启**（分层交换兜底）：12~16G → DiT 交换 60% / TE 交换 100%；16~24G → DiT 30% / TE 80%；24G+ / 显存未知 → 关闭保速度（RunComfy 建议仅作最后兜底）。
  - 配合已有的 `cache_text_embeddings: true`（缓存文本嵌入后自动卸载 TE）。

### 新增：MiniMax H3 支持 nvfp4 量化主模型（12~16G 显存推荐）
- **背景**：int8 DiT（19.5G）对 12/16G 显存仍偏大，社区（awesome-minimax-h3）12~16G 推荐 nvfp4 量化版（DiT 约 11.7G，更小更稳）。
- **已做**：
  - `H3_MODEL_LINKS` 新增 nvfp4 主模型下载项（国内镜像直链，约 11.7GB）。
  - `h3_model_files` 自动检测 nvfp4 文件；`h3_missing_models(vram_gb)` <16G 时优先推荐 nvfp4、int8 作为可选项。
  - `train_h3` <16G 且存在 nvfp4 文件时自动使用：通过 `model_kwargs.dit_fl2va_pruned_path` 覆盖加载路径（ai-toolkit 默认只认 int8 文件名），并输出日志。
  - GUI：H3 状态检测（dit 或 nvfp4 任一算齐全）、使用引导补充 nvfp4 下载说明。
- **验证**：`H3_VRAM_ADAPT_OK` 冒烟测试扩展 nvfp4 三场景（yaml 覆盖路径 / 文件检测 / 缺失推荐），engine_install_smoke_test + smoke_test 全过。
- 说明：低显存会变慢（层需反复交换）；nvfp4 为社区量化版，如加载异常请换回 int8。

### 修复：AI 视频自动打标必崩（args.model 未定义）
- **根因**：`video_caption.py` 加载 Qwen2.5-VL 时引用 `args.model`，但 argparse 从未定义 `--model` → 启动即 `AttributeError` → 退出码 1 → 工具报「视频自动打标失败」，所有用户视频打标永远打不上（与显存/网络无关）。
- **已修**：补 `--model` 参数（默认 `Qwen/Qwen2.5-VL-3B-Instruct`，与文档一致，也支持换模型）；新增 `VIDEO_CAPTION_ARGS_OK` 冒烟测试。

### 修复：视频（H3）模式打开「标签编辑器」空白
- **根因**：标签编辑器是图片专用（逐张看图改标签），读 `dataset/<project>/train_character`；视频模式数据在用户选的视频文件夹（同名 .txt 字幕），不写该目录 → 必然空白。
- **已修**：视频模式点「标签编辑器」直接提示说明（视频字幕=视频文件夹同名 txt / 占位字幕 / AI 打标），不再弹空白窗口。

---## v0.9.30（2026-08-24）

### 修复：老系统 curl 不兼容导致 torch 大轮子下载永远失败
- **根因**：_download_with_resume() 硬编码 --retry-all-errors（curl 8.0+ 才有）。Windows 10 及更老系统自带的 system32/curl.exe 多为 7.x，识别不了该参数会直接 curl: option --retry-all-errors: is unknown 拒绝执行 → 阿里云 / 上海交大双国内镜像都失败、进度 0%（用户反馈：Kohya 训练内核安装失败）。
- **已修**：新增 _curl_supports_retry_all_errors() 检测 curl 版本，**>=8.0 才加该参数**；旧版本自动省略（--retry 5 --retry-delay 5、断点续传 -C - 不受影响）。覆盖 Kohya / 第二引擎 / AMD 全部大文件下载场景。

### 修复：Accelerate 环境预检中文路径误报「不属于同一环境」
- **根因**：预检子进程按系统 ANSI（GBK）编码输出含中文的 sys.executable 路径，父进程按 UTF-8 解码 → 中文变乱码 → 字符串比较失败 → 误报；安装/数据目录含中文（如 C:\\ai绘画\...）时必现，实际环境完全正常。
- **已修**：子进程强制 -X utf8 + PYTHONIOENCODING=utf-8，中文路径正确回传；路径比较改用 
ealpath + normcase 容错；**真实环境不一致仍保留硬报错**（不掩盖 venv 损坏，引导重装内核）。


### 修复：Z-Image / Qwen-Image 预下载半截缓存误判就绪（用户报 no config.json found）
- **背景**：用户 Z-Image 训练报 `Error no file named config.json found in directory .../models/at_image/zimage`——预下载中断留下半截目录，旧就绪判定只查"目录存在"就误判下载完成，训练指向不完整本地目录。
- **已修**：新增 `_at_image_download_complete()` 严格校验（必需 config.json + 按 `.safetensors.index.json` 校验全部分片/单文件权重齐全）；不完整自动续传，仍不完整则提示删除半截缓存并回退在线加载。

### 验证
- 新增 curl 版本解析 7 场景 + 下载命令构造 3 场景（旧/新 curl × direct/代理）；engine_install_smoke_test（20+ 项）+ smoke_test（5 项）全过。

---## v0.9.29（2026-08-23）

### 修复：人物模式 + 正则数据集训练必崩（is_reg 写错 TOML 层级，GitHub issue #3）
- **根因**：`preprocess.write_dataset_config()` 把 `is_reg = true` 写在 `[[datasets]]` 层级，而 sd-scripts 的 schema 要求它写在 `[[datasets.subsets]]` 子集层级 → 任何「人物模式 + 正则数据集」组合 100% 触发 `voluptuous.error.MultipleInvalid: extra keys not allowed @ data['datasets'][1]['is_reg']`，训练启动即崩。
- **已修**：is_reg 从 `[[datasets]]` 块移除，改写到正则数据集的每个 `[[datasets.subsets]]` 子集块内。

### 修复：训练失败误诊为 bitsandbytes 8-bit 问题
- **根因**：`_diagnose_optimizer_failure()` 关键字含裸 `"8bit"`，且只过滤 `$ ` 开头命令行；`CalledProcessError` 会把含 `--optimizer_type=AdamW8bit` 的整条命令重印出来，未被过滤 → 配置校验错误、OOM 等都被误报成 bitsandbytes 问题。
- **已修**：优先识别数据集配置校验失败（`Invalid user config` / `extra keys not allowed` / `MultipleInvalid`）并报出非法键位置；关键字移除裸 `"8bit"`；过滤 `Command '[...]'` 重印行。真实 bnb 崩溃仍能正确命中。

### 修复：RDNA2（RX 6000）Anima latent 缓存仍 NaN（补 --no_half_vae 根治）
- **根因**：上一版只改了 `load_target_model` 的 `vae.to(weight_dtype)`，但 sd-scripts 的 `cache_latents` 阶段会 `vae.to(device, dtype=vae_dtype)`，`vae_dtype = torch.float32 if args.no_half_vae else weight_dtype` → VAE 被转回 fp16 编码 → latent 仍 NaN（用户实测：补丁生效但缓存阶段 watcher 仍报 10 个 npz NaN）。
- **已修**：RDNA2 + Anima 时训练命令自动加官方 **`--no_half_vae`**，VAE 在 load / cache_latents / 采样全流程保持 fp32；保留原有 load 补丁双保险。NVIDIA / RDNA3+ 不受影响。
- 说明：自动停止（loss=NaN 检测）只是保护动作，不是问题来源。


### 修复：Z-Image / Qwen-Image 预下载半截缓存误判就绪（用户报 no config.json found）
- **背景**：用户 Z-Image 训练报 `Error no file named config.json found in directory .../models/at_image/zimage`——预下载中断留下半截目录，旧就绪判定只查"目录存在"就误判下载完成，训练指向不完整本地目录。
- **已修**：新增 `_at_image_download_complete()` 严格校验（必需 config.json + 按 `.safetensors.index.json` 校验全部分片/单文件权重齐全）；不完整自动续传，仍不完整则提示删除半截缓存并回退在线加载。

### 验证
- 新增冒烟测试：`DATASET_CONFIG_IS_REG_SUBSET_OK`、`DIAGNOSE_OPTIMIZER_FAILURE_SCENARIOS_OK`（4 场景）、`ANIMA_RDNA2_NO_HALF_VAE_OK`；engine_install_smoke_test + smoke_test 全过。

---## v0.9.28（2026-08-23）

### 修复：AMD RDNA2（RX 6000）Anima 训练第一步 loss=NaN（VAE fp32）

- **根因**：训练脚本把 Qwen-Image VAE 用 `vae.to(weight_dtype)` 转成 fp16 编码 latent；RDNA2（RX 6000）上 fp16 的 VAE 编码**普遍数值溢出** → `*_anima.npz` 含 NaN/Inf → 训练第一步 `avr_loss=nan`。真实用户反馈：换任何图片、1024/768/512 三种分辨率都复现，连之前低轮次跑通的也报错 → 不是个别图片问题。
- **已修**：
  - 新增 `_patch_anima_vae_fp32` 幂等补丁：`anima_train_network.py` 读 `ANIMA_VAE_FP32` 环境变量，为 1 时 VAE 保持 **fp32** 编码 latent（缓存一次性，训练 DiT 仍走 fp16，速度不变），否则行为与官方一致。
  - `train()` 在 **RDNA2 + Anima** 时自动设 `ANIMA_VAE_FP32=1`；NVIDIA / RDNA3+ 完全不受影响。
  - 新增 `_scan_anima_nan_latents(delete=True)`：训练前自动扫描并删除旧 NaN 缓存，删后自动用 fp32 重新缓存，**用户无需手动删文件**。
- **验证**：补丁首次应用 + 幂等（`ANIMA_VAE_FP32_PATCH_OK`）+ engine_install_smoke_test 全过。

---## v0.9.27（2026-08-22）

### 新增：Krea2 / FLUX.2 8G 显存大幅提速（INT8 量化 + 可选 torch.compile / NF4）
- **INT8（W8A8 对称量化）**：8~16G 显存自动启用。本机 4070 8G 实测：fp8 ≈138s/步 → **int8 ≈53s/步（快约 2.6 倍）**，量化误差比 fp8 更小（0.0032 vs 0.0104），loss 与 fp8 基本一致；显存充足（≥16G）保持 fp8 不变。
- **NF4（4-bit，bitsandbytes）**：显式开启才用（bnb 自动补装 + CUDA 真实量化/反量化预检，失败自动回退 fp8）。
- **torch.compile 可选开关**：默认关（Windows triton 首次编译慢、偶发不稳）；开启后 fp8 ≈2 倍、int8 ≈2.8 倍。
- **H2D-only 单向块交换**：8G 低显存档自动开启（只 Host→Device 不再回传，避免 pin_memory OOM），比双向交换更快。
- 新增 `kohya_core/musubi_quant_patch.py` 幂等补丁（结构变化自动跳过，不影响原 fp8 流程）。

### 新增：主引擎 RDNA2（RX 6000）自动切 fp16
- 之前只在手动开启「AMD 兼容模式」时才切 fp16；现在自动检测 gfx103x → 直接 fp16（与第二引擎一致），修 AMD 6000 系第一步 loss=NaN / 黑图；NVIDIA 与 RDNA3+ 逻辑不变。

### 新增：高级参数「优化器」下拉框
- 自动 / AdamW / Lion / AdamW8bit，默认「自动」= 行为零变化；遇 bitsandbytes（AdamW8bit）崩溃可手动切换 AdamW/Lion。
- 训练失败自动诊断：命令用 AdamW8bit 且日志命中 bitsandbytes 8-bit 崩溃关键字时，明确提示改用 AdamW/Lion。

### 修复：训练「卡在训练前 / accelerator device: cpu」（残留 accelerate 配置）
- **根因**：`accelerate launch` 读 `%USERPROFILE%\.cache\huggingface\accelerate\default_config.yaml`，若 `use_cpu=true` → 训练（含 caching latents）全程 CPU，表现为「卡在训练前、无报错、CPU/GPU 无负荷」；而 torch/优化器预检（不走 accelerate）却正常。
- **已修**：训练前自动检测残留配置并改回 `use_cpu=false`，用与训练相同的 accelerate launch 路径复核设备；launch 显式 `--num_processes 1 --num_machines 1` 防残留多卡配置。

### 修复/增强
- 各引擎 venv 缺 torchvision 自动补装匹配版本（torch 2.7.x → torchvision 0.22.x，阿里云源+官方兜底），修 `ModuleNotFoundError: No module named 'torchvision'`。
- Anima 训练期间后台扫描 latent 缓存，发现 NaN/Inf 报出具体图片名并提示删除（只提示不自动删/停）。
- WD14 打标脚本查找增强：kohya_dir.txt 指向数据根、安装目录同级 KohyaLoraTool_data、%APPDATA% 等候选路径；找不到时 WARN 附已查路径便于排查。
- 验证：engine_install_smoke_test（18 项，含量化决策 / musubi 补丁幂等 / accelerate 配置自愈）+ smoke_test.py 全过。

---## v0.9.24（2026-08-22）

### 修复：AMD RDNA2（RX 6000）训练出的 LoRA 出黑图
- **根因**：软件 AMD 模式统一用 bf16 混合精度，但 **RDNA2（RX 6000）硬件不原生支持 bf16**（RDNA3 才支持）→ bf16 训练数值错误 → LoRA 权重损坏 → 出图全黑。同一个 LoRA 在 7800 XT（RDNA3）上正常。
- **已修**：
  - 主引擎：AMD 模式按架构选精度——**RDNA2（RX 6000/gfx103x）→ fp16**（RDNA2 原生支持，数值正确）；RDNA3+ → 保持 bf16；
  - Krea2/FLUX.2（musubi）：训练前自动给 musubi 打幂等补丁，RDNA2 时 `dit_dtype`/VAE 用 fp16（读 `KREA2_FP16` 环境变量），命令 `--mixed_precision` 同步改 fp16。
- **验证**：musubi 补丁幂等 + 主引擎精度分支 + 冒烟测试全过。

### 新增：训练 loss=NaN/Inf 自愈检测
- 训练过程中检测到 loss 为 NaN/Inf（数值异常，常见 AMD RDNA2 + bf16 / 模型或数据问题）→ **自动停止训练**，避免「跑完 100% 卡在保存 checkpoint」的假死。
- 日志明确提示原因与建议（更新到最新版 / 检查数据）。
- 验证：正常 loss 不触发、NaN/Inf 触发一次、冒烟测试全过。
### 修复：视频模式（H3）模型状态行被挤出窗口
- h3_row 一行 8 个按钮（模型/引擎/字幕操作）超宽被挤出窗口；拆成两行（模型操作行 + 引擎/字幕行），视频模式下正常显示。

### 新增：Krea2 / FLUX.2 支持「画风 / 人物」训练类型切换
- 第二引擎（Krea2 / FLUX.2）现在和 Qwen-Image/Z-Image 一样，可选择「画风（过滤人物标签）/ 人物（保留全部标签）」；
- 训练数据集目录按子模式自动选（画风=train，人物=train_character），与预处理一致；trigger 提示同步。
### 修复：Krea2/FLUX.2 训练回归（v0.9.23 引入，本机 4070 实测复现）
- **根因**：v0.9.23 给 musubi 打补丁自动开 fp8 `use_scaled_mm=True`（40/50 系），但 **Krea2/FLUX.2 的 fp8 量化是 per-channel，不兼容 scaled_mm** → 训练一进入 forward 就崩（`ValueError: scaled_mm only supports per-tensor scale_weight`）。这就是「v0.9.9 能跑、后续版本不行」的根因。
- **已修**：回退该补丁，恢复 `use_scaled_mm=False`（与 v0.9.9 一致，慢但能跑完）；已打补丁的用户升级后训练时自动撤销。
- **实测**：4070 复现崩溃 → 回退后训练正常进入 GPU 计算（不崩）；Krea2 12.9B 在 8GB 上 float32 计算极慢属预期（配 8GB 强提示 + loss=NaN 检测）。
### 调整：pip 国内镜像默认改用阿里云（清华保留兜底）
- 用户反馈清华源经常出问题；所有默认/首选 pip 镜像从清华改为**阿里云**（`mirrors.aliyun.com/pypi/simple/`），清华保留为兜底、上海交大第三；
- 涉及：主引擎/第二/第三引擎依赖安装、pip config 默认源、PyTorch 轮子依赖镜像、预处理补装、安装脚本 bat；
- 冒烟测试断言同步更新，全部通过。
### 修复：Krea2/FLUX.2 fp8 反量化成 float32 计算（DiT dtype: float32 根因）
- **根因**：musubi `fp8_optimization_utils.py` 在 `use_scaled_mm=False` 时 `original_dtype = self.scale_weight.dtype`（固定 float32）→ fp8 权重每次前向反量化成 **float32** 计算 → 8GB 爆显存、每步极慢（日志 `DiT dtype: torch.float32`）。
- **已修**：打幂等补丁改为 `original_dtype = x.dtype`（用输入计算 dtype，bf16/fp16 跟 mixed precision 走），scale 同步转 dtype；不再 float32 计算。
- **本机 4070 实测**：显存占用从 ~7800MiB 降至 ~7071MiB（约 -700MB），训练正常计算不崩。
### 修复：MiniMax-H3 视频训练 processor 联网加载失败
- AI Toolkit 训练时从 `MiniMaxAI/MiniMax-H3` 在线加载 tokenizer/processor，国内连不上报 `Can't load processor ... processor_config.json`。
- 已修：训练前自动下载 H3 的 `FL2VA/tokenizer`（4 文件）+ `FL2VA/processor`（7 文件）到本地（hf-mirror 直连+代理兜底），并给 `minimax_h3.py` 打幂等补丁读 `H3_REPO_DIR` 环境变量指向本地；不再在线拉 HF。
- 验证：补丁幂等 + ai_toolkit venv py_compile + 冒烟测试全过。
### 修复：Krea2/FLUX.2 左侧全绿仍提示「请先选择底模」
- 根因：`cmd_one_click_train` 只把 qwen_image/zimage/video 排除在底模检查外，Krea2/FLUX.2 走 else 分支强制检查 `base_model`（它们用 raw/dit，无底模）→ 误报。
- 已修：Krea2/FLUX.2 改为调用 `_ensure_krea2_ready` / 新增 `_ensure_flux2_ready`（检查第二引擎 + 模型齐全）；人物子模式 trigger 检查同步覆盖 Krea2/FLUX.2。
---

## v0.9.23（2026-08-22）

### 新增：训练前自动检测 CPU 版 torch + 一键确认自动重装 cu128（自愈）
- **背景**：部分用户训练时 `accelerator device: cpu`、300s/步，根因是 venv 里 torch 是 CPU 版（CUDA 不可用），软件只警告不修复。
- **已实现**：
  - 训练前（NVIDIA 卡）自动检测 `detect_torch_backend`；
  - 检测到 CPU 版 → **弹窗询问**「是否自动重装 cu128 版 PyTorch（约 3.3GB，国内镜像，断点续传，可停止）」；
  - 用户确认 → 自动调用 `_preinstall_torch` 重装 cu128 → 重装后重新验证，仍不可用则明确提示更新 NVIDIA 驱动；
  - 用户拒绝 → 仅警告，按 CPU 继续（不阻断）；AMD 卡 / CUDA 正常用户完全不受影响（增量）。
- **验证**：fix_cpu_torch 三场景（成功/重装失败/仍 CPU）、GUI 确认五场景（确认/拒绝/AMD/CUDA 正常/非 NVIDIA）、冒烟测试全过。

### 修复：Krea2/FLUX.2 fp8 退化成 float32 计算（300s/步根因）
- **根因**：musubi `krea2_utils.py` / `flux2_utils.py` 写死 `apply_fp8_monkey_patch(..., use_scaled_mm=False)`；`use_scaled_mm=False` 时每次前向把 fp8 权重**反量化成 float32** 计算 → fp8 只省存储、计算还是 float32 → 8GB 爆显存、300s/步（日志 `DiT dtype: torch.float32`）。与 musubi 版本/重装无关。
- **已修（方案 A）**：训练前自动给 musubi 打幂等补丁，`use_scaled_mm` 按 GPU 算力自动开启（**SM 8.9+ / RTX 40/50 系 → True**，硬件 fp8 加速）；30 系及以下仍走 float32 兜底。
- **已修（待办十一）**：训练前检查 musubi 版本，Krea2 源码没有 bf16 强制（旧版）→ 直接提示「musubi 版本过旧，请重装第二引擎/更新软件」并阻止训练。

### 提示：Krea2 8GB 强提示（方案 B）
- Krea2 是 12.9B 大模型，8G 显存训练会非常慢（每步数十秒以上）；训练前明确弹窗「强烈不建议在此显卡上训练 Krea 2」，可拒绝。---

## v0.9.22（2026-08-21）

### 修复：AMD RX 6000 检测在多显卡（核显+独显）机器上失效
- **现象**：RX 6800 XT 用户更新到 v0.9.21 后，AMD 安装仍走官方 7.2.1 源，下载损坏报 `BadZipFile`，没走社区 ROCm 7.1.1。
- **根因**：`_amd_is_gfx103x()` 依赖 `detect_gpu_name()`，而它用 WMI 时 `Select-Object -First 1` **只取第一个显卡**；核显+独显的机器上取到的是核显（Intel UHD / AMD Radeon Graphics），名字不匹配 RX 6xxx → 误判为「非 gfx103x」→ 走了官方源。
- **已修**：`_amd_is_gfx103x()` 改为**遍历 `Win32_VideoController` 全部显卡名称**，任一匹配 `RX 6xxx` / `gfx103x` 即判定为 gfx103x，自动切换社区源。
- **验证**：核显+RX6800XT / 核显+NVIDIA / 直接识别 / gfx1030 / WMI 空 共 5 场景全过；冒烟测试全过。

---

## v0.9.21（2026-08-21）

### 新增：AMD RX 6000/gfx103x 显卡支持（社区 ROCm 7.1.1 构建）
- **背景**：官方 Windows ROCm 6.4.4+（含 7.2.1）均不支持 RDNA2（RX 6000/gfx103x），此前软件检测到 RX 6000 会直接阻止 AMD 安装。
- **现已集成社区预编译的 ROCm 7.1.1（gfx103x target）构建**（guinmoon/rocm7_builds）：rocm_sdk + torch/torchvision 共约 2.6GB，已转存**魔搭国内镜像**（`amd_rocm_gfx103x/`，无需代理）。
- RX 6000 用户开启「AMD 兼容模式」后，软件**自动**从魔搭下载安装社区 ROCm 7.1.1 + PyTorch，全程无需手动操作；训练时自动设置 `HSA_OVERRIDE_GFX_VERSION=10.3.0` 兼容运行。
- 注意：社区构建非官方，稳定性/性能不保证；仅支持 Python 3.12（非 3.12 会明确提示重建 AMD 环境）。

### 修复：Krea2 / FLUX.2 训练「缓存文本编码器输出」阶段联网超时（用户反馈）
- **根因**：musubi-tuner 的 `krea2_encoder.py` 用 `AutoTokenizer.from_pretrained("Qwen/Qwen3-VL-4B-Instruct")` 在线拉 tokenizer，国内直连 huggingface.co 超时（`ConnectTimeoutError`），训练中断。
- **已修（自愈，用户零手动）**：
  - **内置 Qwen3-VL-4B tokenizer**（config/tokenizer_config/tokenizer.json/vocab/merges，约 11MB）随安装包离线分发；
  - 训练前自动确保本地 tokenizer 就绪（内置 → hf-mirror/魔搭镜像兜底）；
  - 自动给 musubi `krea2_encoder.py` 打幂等补丁：`KREA2_TOKENIZER_DIR` 环境变量指向本地目录 + `local_files_only=True`，不再联网；
  - 自动补装 `protobuf`（transformers fast tokenizer 依赖）；
  - `train_krea2` / `train_flux2` 均已接入。
- **验证**：补丁幂等、环境变量生效、本地 tokenizer 真实加载（AutoTokenizer + Qwen2TokenizerFast）、冒烟测试全过。

### 测试
- AMD gfx103x 检测（RX 6800/RTX 4070 mock）、社区源 URL、三引擎冒烟测试全部通过。

---

## v0.9.20（2026-08-21）

### 修复
- **Anima 训练 TensorBoard 日志目录中文路径崩溃**：安装目录含中文（如 `C:\Users\admin\Desktop\新建文件夹`）时，新版「跟随安装位置」使数据目录变成中文路径，TensorFlow 写 TensorBoard 日志报 `FailedPreconditionError: ... logs is not a directory`，训练全部准备完成后崩溃。现已自动把 `--logging_dir` 重定向到 ASCII 路径（`%APPDATA%\KohyaLoraTool\logs`），不影响训练本身。
- **Qwen3-0.6B 完整性误判**：旧判定只查 `config.json` 是否存在，下载中断残留的目录（只有配置、没有权重）以及手动放置的文件名不规范（如浏览器下载的 `model.safetensors (1).safetensors`）都会被误判为已就绪，训练加载 Qwen3 时报 `OSError: no file named pytorch_model.bin, model.safetensors...`。现已校验「config.json + transformers 标准权重名（model.safetensors / pytorch_model.bin / 分片）」，不完整自动触发重新下载。

### 自愈
- **Qwen3 残缺目录自动备份重下**：检测到不完整时自动改名备份为 `Qwen3-0.6B.incomplete_时间戳` 并重新下载，用户无需手动删文件夹。
- **训练前 torch 后端预警**：非 AMD 模式训练前检测，CPU 版 torch（CUDA 不可用）直接提示「训练会全程 CPU 且极慢，看起来像卡住」，不再干等。
- **监控无进展超时提示**：训练启动后超过 3 分钟无任何新日志/loss 且步数为 0，监控面板显示「训练可能卡住或已退出，请看上方日志」，不再一直挂着「等待训练数据」。

### 测试
- 三引擎安装流程、Qwen3 完整性 7 场景、TrainMonitor 超时字段、项目冒烟测试全部通过。

---

## v0.9.19（2026-08-20）

### 修复
- **v0.9.18 回归：训练启动即崩溃（cannot access local variable 'accel'）**：上一版把主引擎训练启动器 `accel` 的赋值错误地放进了「AMD 兼容模式且设置了自定义训练环境」分支，普通 NVIDIA 用户（SD1.5/SDXL/FLUX/Anima）走不到赋值语句，一点「一键开始训练」就直接报 `UnboundLocalError`。现已改为**无条件**通过当前训练环境解析 Accelerate 启动器，所有用户恢复正常训练。
- 新增回归测试 `MAIN_ENGINE_ACCEL_ALWAYS_DEFINED`，防止再次出现 accel 未定义。

---
## v0.9.18（2026-08-20）

### 修复
- **Windows Accelerate 启动器串环境导致训练立即退出**：主引擎、Krea2、FLUX.2 统一使用当前训练环境的 `python.exe -m accelerate.commands.launch`，启动前验证 Accelerate 与训练 Python 属于同一 venv。
- **AMD ROCm 安装与验证可见性**：保留实时下载进度；验证失败时显示 torch/HIP/GPU 状态及真实 traceback，不再只显示 `?`。
- **AMD Windows 兼容性提示**：检测 RX 6000/gfx1030 时，在下载前提示当前 ROCm Windows 官方支持限制，避免无效下载数 GB 依赖。
- **WD14 Triton 警告说明**：`No module named triton` 属于可选优化缺失，不影响 ONNX Runtime CUDA 打标。

### 测试
- 三引擎安装流程、AMD 下载/验证、Accelerate venv 一致性、项目冒烟测试全部通过。

---

# 更新日志（Changelog）

## v0.9.17（未发布）

### 修复
- **分词器预缓存失败导致训练联网卡死（用户反馈）**：训练前预缓存分词器（如 openai/clip-vit-large-patch14）只走 hf-mirror.com 单源，部分用户网络连 hf-mirror 也超时（`Connection to hf-mirror.com timed out`），失败后只提示「将尝试联网加载」，训练脚本再走默认 huggingface.co → 必然失败/卡死。现已：
  - **内置三个常用分词器到安装包**（openai/clip-vit-large-patch14、laion/CLIP-ViT-bigG-14-laion2B-39B-b160k、google/t5-v1_1-xxl，共约 8MB）：SD1.5 / SDXL / FLUX / Anima 训练所需分词器完全离线、零联网，首次使用自动从内置包复制。
  - **多级兜底**：内置包 → 本地已下载模型目录（Anima 的 Qwen3-0.6B）→ 文件级国内多镜像下载（hf-mirror / 魔搭，30s 短超时、直连绕代理）→ transformers from_pretrained。
  - **修复 auto 分词器完整性误判**：T5 等 sentencepiece 分词器只有 spiece.model 没有 tokenizer.json，旧检查要求 tokenizer.json 导致每次都判定不完整、反复联网重建；现改为 tokenizer.json 或 spiece.model 任一即可。
  - 失败提示明确（「训练时可能需联网加载」），不再误导。

- **预处理报「缺少 numpy」真正根因：打包版 python312.dll 污染（用户诊断铁证）**：用户反馈 v0.9.16 后「-c 校验通过、预处理仍报缺少 numpy」，其自测命令从工具目录 `E:\Lora-Tool\KohyaLoraTool` 运行 venv python `import numpy` 直接崩溃（`AttributeError: class must define a '_type_' attribute`），切到其他目录则正常。根因是打包版应用目录自带 `python312.dll`，GUI 从该目录启动后外部 venv Python 继承污染 cwd，Windows DLL 搜索优先命中打包版 DLL，与 venv 基座 Python 3.12 版本不匹配 → `_ctypes` 崩溃 → numpy 无法 import → 误报「缺少 numpy」。现已：
  - **外部 Python 子进程安全 cwd**：启动外部 Python（预处理 / 分词器预缓存 / pip 补装等）且未显式指定 cwd 时，检测当前目录是否含 `python312.dll`，含则自动切到系统临时目录，从源头避开 DLL 搜索污染；显式传入 cwd 的训练命令保持不变。
  - 对全部引擎（第一/第二/第三引擎）生效，源码运行（非打包）同样适用。

- **预处理报「缺少 numpy」且自动补装不生效（用户反馈，v0.9.16 补丁后仍复现）**：v0.9.16 已加自动补装+重试，但补装对大多数用户是空转——内置离线 wheel 只有 **cp312**，而工具默认 kohya venv 是 **Python 3.10**（`_wheels_for_python` 过滤后为空 → 只能走镜像，镜像不可达即失败）。现已：
  - **内置 numpy 2.1.3 + pillow 12.3.0 的 cp310/cp311/cp312 三套离线 wheel**（约 57MB），默认 py3.10 venv 也能零联网补装；numpy 版本与 kohya 训练环境锁定一致（不再补装到不兼容的最新 2.5.x）。
  - **失败后强制补装**：子进程预处理失败后不再依赖快速校验（`-c` 通过但脚本实际 import 失败会误判），改为 `force=True` 强制补装一轮再重试。
  - **preprocess.py 报错打印真实 traceback**：`import numpy` 失败时输出具体原因（ModuleNotFoundError / DLL load failed / 版本冲突），便于后续定位根因，不再笼统提示「缺少 numpy」。
  - **检测工具目录残留假 numpy 文件**（另一类污染，本地已复现并修复）：若工具目录里残留了假的 `numpy.py` / `numpy` 文件夹——脚本运行时 `sys.path[0]` 指向脚本目录，`import numpy` 会优先命中假文件而不是 venv 里的真 numpy。现已在 preprocess.py 里检测并打印「检测到干扰 numpy 导入的文件 + 具体路径」，指导用户删除后重试。

### 测试
- 新增 `_ensure_tokenizer_cached` 单测：内置离线复制 / 文件级多源下载 / auto（spiece.model）完整性 / transformers 兜底；真实调用三个内置分词器复制均成功。
- 新增 `_ensure_preprocess_deps` force 模式单测（校验通过也强制补装）；`_wheels_for_python` 对 cp310/311/312 过滤验证；真实空 venv 端到端离线补装 numpy 2.1.3 + pillow 12.3.0 成功。
- 新增 `_external_python_safe_cwd` 单测（cwd 含 python312.dll → 切临时目录 / cwd 干净 → 用解释器 Scripts 目录 / 显式 cwd 不变 / 非 Python 不干预）；真实打包目录验证含 python312.dll 时返回系统临时目录。

---

## v0.9.16（2026-08-19）

### 修复
- **Lion 优化器降级后训练崩溃（v0.9.15 回归补漏）**：AdamW8bit 不可用时自动降级 Lion 只做了 `import lion_pytorch` 检查，未做真实 step 预检；部分机器上 lion-pytorch 能 import 但旧版与 torch 2.7 不兼容，训练到 `optimizer.step()` 才崩（Anima 报错命令含 `--optimizer_type=Lion`，退出码 1）。现已改为 `_probe_lion` 真实 step 预检（与 AdamW8bit 预检一致：创建参数 → backward → step），失败自动继续降级为纯 PyTorch AdamW，不再崩溃。

- **第二引擎/第三引擎 torch 本地安装报 `Could not find a version that satisfies the requirement filelock (from versions: none)`（用户反馈，无限失败）**：torch 大轮子已从阿里云/上海交大断点续传下载成功（日志「已存在缓存轮子，跳过下载」），但下一步本地 `pip install` 安装时，依赖解析（filelock/typing-extensions/sympy/networkx/jinja2/fsspec 等）只走清华源；部分用户网络下清华源不可达/超时 → pip 报「from versions: none」→ 外层又笼统包成「国内双镜像下载失败」，误导排查。现已改为**本地安装多镜像自动回退**：清华 → 阿里云 → 上海交大，任一镜像成功即完成；全部失败才报错，且错误日志明确区分「下载失败」与「本地依赖安装失败」。

- **预处理报「缺少 numpy」卡死（用户反馈）**：预处理开始前工具已有 Pillow/numpy 自检+自动补装，但旧检查只做 `import PIL, numpy`（顶层 import），preprocess.py 实际用 `from PIL import Image`，半损坏的 Pillow 顶层能过、子模块挂，导致父自检通过、子进程仍报「缺少 numpy」且不触发补装。现已改为 `_ensure_preprocess_deps`：用与 preprocess.py 完全一致的 `from PIL import Image; import numpy` 校验；子进程预处理失败后还会再次自检，确认缺依赖则自动补装（内置离线 wheel → 清华 → 阿里）并**自动重试一次**，不再卡死在原始报错。

### 测试
- `engine_install_smoke_test.py` 优化器单测更新为 mock `_probe_lion`：Lion 预检通过→Lion、Lion 预检失败→AdamW、用户明确选 Lion 但预检失败→自动降级 AdamW（Anima 反馈案例）、musubi `allow_lion=False` 不调用 Lion 预检。
- 新增 `_ensure_preprocess_deps` 单测（依赖可用不补装 / 缺失补装成功 / 补装失败返回 False）与 `preprocess` 自动重试单测（子进程失败→补装→重试成功；补装失败→明确报错且不无限重试）。
- 新增 `_preinstall_torch` 多镜像回退单测（清华失败→阿里云成功；三镜像全失败→抛「本地安装失败」明确错误）。

---

## v0.9.15（2026-08-18）

### 修复
- **Windows + CUDA 12.8 下 AdamW8bit 优化器训练崩溃**：bitsandbytes 在 Windows 下可能能 import 但 CUDA 8-bit 内核不可用（`libbitsandbytes_cuda128.dll` 缺失 / `compiled without GPU support` / `str2optimizer8bit_blockwise is not defined`），之前会在训练 `optimizer.step()` 阶段才崩溃。现在训练开始前会先在真实 venv 里做一次 8-bit 优化器 step 预检（创建真实参数 → `loss.backward()` → `optimizer.step()`），预检通过才用 AdamW8bit；失败自动降级为 Lion（显存更低），再失败降级为纯 PyTorch AdamW。**覆盖全部引擎**：第一引擎（SD/SDXL/FLUX/Anima）、第二引擎（Krea2/FLUX.2）、第三引擎（Qwen-Image/Z-Image/MiniMax H3 视频）。第二引擎 musubi-tuner 不支持 Lion，预检失败时直接降级 AdamW；AMD 兼容模式固定 AdamW。指定 `adamw8bit` 时同样自动降级，不再崩溃。
- **PyTorch 3.3GB 大轮子下载“看起来卡死”**：curl 静默模式下载 2~3GB torch 时界面上长时间无任何输出，用户误以为卡死。现在：
  - 下载到 `.part` 文件，断点续传，完整校验通过后才改名为正式 wheel；中断后重试自动从断点继续，不再删掉重下 3GB。
  - 每 5 秒输出一条进度日志：`[Kohya] 下载进度：xxx / xxx MB（xx%）`。
  - 新增限速看门狗：120 秒平均下载速度低于 20KB/s 时 curl 直接失败返回，自动切换备用国内镜像，避免无限挂起。

### 测试
- `engine_install_smoke_test.py` 新增优化器解析（`resolve_optimizer` / `_probe_adamw8bit` / `_optimizer_yaml_name`）单元测试，不真实运行 CUDA（mock 子进程）。
- 全模式冒烟测试、Python 编译、依赖检查与 Git 差异检查通过。

---

## v0.9.14（2026-08-18）

### 修复
- **第一引擎安装报 `name 'git' is not defined`**：恢复 Kohya 安装函数的 Git 检测变量，避免 PyTorch 预装完成后在官方依赖安装阶段直接退出。
- **Anima / Transformers 导入 `cannot import name 'Inf' from numpy`**：统一校正为 `numpy 2.1.3 + scipy 1.15.3 + protobuf 5.29.5`，兼容 Python 3.10–3.12、TensorFlow/W&B；已有环境重跑安装也会自动自愈。
- **第二引擎 Torch 被依赖升级或版本配错**：严格锁定 `torch 2.7.1+cu128 + torchvision 0.22.1+cu128`，旧版 `2.7.1 + 0.22.0`、CPU 版或其他版本会被识别并自动重装。
- **第二引擎缺 pip**：创建及复用 musubi-venv 时都会检查 pip，优先 `ensurepip` 自愈，失败则保留旧 venv 并重建。
- **第二引擎无意义强制要求 Git**：安装包内已有 musubi-tuner 源码时不再要求 Git；仅源码包缺失、需要克隆回退时才检查 Git。
- **第三引擎损坏环境无法恢复**：增加与第一/第二引擎一致的 venv 健康检查；迁盘、换用户、`No Python at ...` 或跨版本 DLL 冲突时自动保留旧环境并用当前 Python 重建。
- **第三引擎 NumPy/SciPy 依赖冲突**：移除 AI Toolkit 原始不兼容配对，锁定 `numpy 2.5.2 + scipy 1.18.0`，并锁定第三引擎 Torch 依赖，防止 pip 回溯或二次升级。
- **Torch 下载失败后留下半残环境**：国内双镜像预下载失败时立即停止并保留断点缓存，不再继续执行必然失败的后续安装。

### 测试
- 新增 `engine_install_smoke_test.py`，覆盖三引擎源码部署、venv 创建、pip 自愈、损坏环境重建、Torch 约束和最终验证控制流。
- 第一引擎已在真实 CUDA 环境验证；全模式冒烟测试、Python 编译、依赖检查与 Git 差异检查通过。

---

## v0.9.13（2026-08-18）

### 修复
- **第三引擎改为国内按需安装**：AI Toolkit 源码和固定版 Diffusers 不再随安装包内置，也不再通过 GitHub `git clone` 或 `git+https` 安装；首次使用时优先从魔搭下载，失败自动切换国内加速源，并缓存到数据目录。
- **第三引擎安装不再强制依赖 Git**：环境中只要有可用 Python，即可按需部署 AI Toolkit。
- **PyTorch 国内镜像统一**：第一、第二、第三引擎的 PyTorch 大轮子均使用阿里云/上海交大双国内镜像断点续传，普通依赖使用清华/阿里 PyPI；不再回退到 `download.pytorch.org`。
- **失效代理自动绕过**：国内镜像、模型组件和训练下载会清理已关闭的本地代理，避免用户必须开启代理才能安装。
- **打包版 Python DLL 隔离补强**：启动外部 Python 时自动设置安全工作目录，避免当前目录中的 Python 3.12 DLL 污染 Python 3.10/3.11 venv。

### 体积
- 第三引擎源码不进入 Setup.exe；本版安装包继续控制在 500MB 以内。

---

## v0.9.12（2026-08-18）

### 新增
- **界面字体更圆润清晰**：全局改用微软雅黑优先（比 Segoe UI 更圆润），字号整体放大一点点（标题 16 / 正文 13 / 提示 11 / 日志 12）；左侧新手引导侧栏加宽并对齐步骤按钮，放大字体后不再拥挤错位。

### 修复
- **打包版误报 venv 跨版本 DLL 冲突**：隔离 PyInstaller 自带的 Python 3.12 / OpenSSL DLL 与外部 Kohya venv，修正 PATH 清理未实际生效的问题；不再出现 `torch ? / CUDA ?` 后又误报“venv 已损坏”。
- **Torch 安装验证不再吞错**：现在显示 torch 版本、CUDA 构建版本和 CUDA 可用状态；导入失败会打印真实错误并判定安装未完成，不再错误显示 `[OK]`。
- **Git 失效代理绕过命令修复**：修正 `git -c ... git clone` 中重复拼入 `git` 导致的 `git is not a git command`；主引擎、第二引擎、第三引擎克隆均使用绝对 `git.exe` 和正确参数顺序。

---

## v0.9.11（2026-08-18）

### 修复
- **AMD 依赖下载完整性校验升级**：下载的 wheel / 压缩包现在做全量 CRC 校验（此前只查文件头魔数，会放行“头部完好但内部损坏”的文件，pip 装时报 BadZipFile 中断）；损坏缓存自动删除重新下载，覆盖 AMD ROCm、AMD PyTorch、NVIDIA torch 大轮子。
- **训练前依赖补装不再被网络中断卡死**：补装失败自动完整重试一轮；核心模块齐全时（如仅 scipy 版本升级失败、下载 IncompleteRead 中断），降级为“警告继续训练”，不再一刀切报“网络不稳”拦死训练。

---

## v0.9.10（2026-08-18）

### 修复
- **训练环境健康检查全面加强（针对“有 Python 却跑不了”的三类根因）**：
  - 新增 venv 深度检测：校验 pyvenv.cfg 指向的 Python 是否还在，并实际导入 socket/ssl/ctypes/sqlite3；
  - 自动识别“跨版本 DLL 混用”（No Python at ... / python312.dll conflicts / DLL load failed），命中即判定环境损坏，安装内核时自动把旧 venv 改名保留并用当前 Python 重建；
  - 训练 / 预处理 / 模型下载遇到损坏环境时给出明确原因和重跑②指引，不再误导为“网络不稳”。
- **缺 pip 自动修复（第二引擎 “No module named pip” 安装卡死）**：
  - 主引擎与第二引擎安装前都会检查 pip，缺失时先用 ensurepip 自愈；
  - 自愈失败自动重建虚拟环境（旧环境保留为 venv_broken_时间戳 / musubi-venv_broken_时间戳）。
- **主引擎强制校验 torch + torchvision（训练报 ModuleNotFoundError: No module named 'torchvision'）**：
  - 训练前完整性检查新增 torch / torchvision；
  - 缺 torchvision 时按已装 torch 版本自动配对补装（如 torch 2.7.1 → torchvision 0.22.1，走阿里镜像断点续传）；
  - 补装失败给出明确指引重跑②，不再等到训练脚本启动才崩。
- **pip 升级失败诊断与备用源**：
  - pip 升级主源（清华）失败自动切换阿里镜像重试；
  - 失败提示区分“网络 / 镜像故障”和“No module named pip 需重建”。
- **国内镜像强制生效（分词器缓存 / 训练 / 模型组件下载）**：
  - HF_ENDPOINT 由 setdefault 改为强制覆盖 huggingface.co（用户系统已有官方站环境变量时不再直连超时）；
  - 分词器预缓存、Qwen3 等模型组件下载统一走 hf-mirror。
- **外部 Python 子进程环境净化**：
  - 启动训练 / 下载 / 安装子进程时清除 PYTHONHOME / PYTHONPATH / PYTHONSTARTUP，并从 PATH 移除 PyInstaller 解包目录，避免错误版本 DLL 被塞进 venv 子进程。

---

## v0.9.9（2026-08-18）

### 修复
- **环境准备：内置 Python 静默安装失败却只报“仍未找到”，且优先装了旧版 3.10.11**：
  - 内置安装包改为优先 Python 3.12（与内置 cp312 wheel 匹配、安装器更新更稳），3.10 保留为兜底；
  - 静默安装后检查安装程序退出码，失败时明确提示退出码与重试/手动安装建议，不再一句“仍未找到”；
  - 安装后综合检测（常规路径 + 用户级安装目录），并列出已检测到的 Python 版本作为诊断；
  - 退出码 0 但未检测到时，提示重启软件再试 / 可能被安全软件拦截。

- **训练环境损坏自动重建（“No Python at ...”导致一键训练/预处理全失败）**：
  - 根因：venv 指向的 base Python 不存在（数据目录迁移到新盘 / 更换系统用户 / 原 Python 被卸载）时，venv 的 python.exe 启动直接报 “No Python at ...”，一键训练、预处理、安装内核全部失败；之前只提示“网络不稳或镜像不可达”，误导排查方向；
  - 新增 venv 健康检测：重跑【② 安装训练内核】时自动识别损坏 venv，把旧 venv 重命名为 venv_broken_时间戳 保留，用当前 Python 自动重建并重装依赖；
  - 训练 / 预处理遇到损坏 venv 时给出明确提示（原因 + 引导重跑②自动重建），不再报“网络不稳”。

---

## v0.9.8（2026-08-17）

### 修复
- **第二引擎（musubi-tuner）安装失败根因：PyTorch/torchvision 版本配对错误**：
  - 之前写死 torch 2.7.1+cu128 + torchvision 0.22.0+cu128（torch 2.7.1 应配 torchvision 0.22.1，而 0.22.0 要求 torch 2.7.0），pip 会因依赖冲突报 ResolutionImpossible / IncompleteRead，很多用户第二引擎装不上；现已全部改为 torch 2.7.1+cu128 + torchvision 0.22.1+cu128（阿里镜像预下载主路径与 pip 官方源回退路径同步修正）。
  - 新增第二引擎 torch/torchvision 配对校验：已装错误组合（2.7.1+0.22.0）不再被误判为“已安装”，会自动识别并强制重装修复。
  - 安装前/安装后都会校验 torch + torchvision + CUDA 12.8 + GPU 可用，全部达标才算安装成功。
  - 保留国内镜像断点续传预下载 + 本地 wheel 安装，v0.9.5 的 %2B 文件名解码修复不受影响。

---

## v0.9.7（2026-08-17）

### 新增
- **Qwen-Image / Z-Image 新增「画风 / 人物」训练类型切换**：这两个模式原来固定按人物处理，现在可选画风（统一 caption + 自动过滤人物五官/角色标签）或人物（保留全部标签 + WD14 打标 + trigger），切换自动保存到项目。
- **数据目录可迁移到安装盘（解决 C 盘占用）**：
  - 新增「💾 数据目录」入口：显示当前数据目录与占用大小；
  - 一键迁移：把训练引擎/数据集/缓存等（原在 C 盘 %APPDATA%）整体搬到安装盘或任意盘，先复制校验再删源，失败自动保留；
  - 打包版默认跟随安装位置（装 D 盘数据就在 D 盘，Program Files 无权限才回退 C 盘）；
  - 设置文件固定存 %APPDATA%（不随数据目录移动）。

### 修复
- **一键训练里 Qwen-Image/Z-Image 预处理 mode 传错**（之前会把 qwen_image 原样传给只接受 style/character 的预处理脚本），统一走画风/人物映射。

---

## v0.9.6（2026-08-17）

### 修复
- **WD14 打标失败导致"图有标签无"（画风模式漏标签）**：整合 2026-08-17 现场修复：
  - 画风模式 WD14 失败时立即补兜底 caption，并新增最终兜底段（处理后仍缺失/空标签一律补写，绝不漏标签）；
  - 打标解释器自动选择：当前环境缺 torch/onnxruntime 时自动改用带 torch 的 venv（venv_amd / musubi-venv / ai_toolkit_venv），并自动补装 onnxruntime/onnx；
  - library 模块路径修复：自动把 sd-scripts 根目录加进 PYTHONPATH 并作为工作目录，解决 import library 失败；
  - 坏图隔离：打标前校验输出图片，损坏/截断的自动移到 <输出目录>_corrupt，不再一张坏图中断整批打标。
- **一键安装脚本因 PATH 里的旧/新 Python 版本不符而粗暴退出（"建议删除本机旧 Python"）**：现在自动依次尝试 PATH python → py -3.12 → py -3.10 → 内置 Python 3.12 静默安装，全程无需手动删 Python，并用选定的解释器创建 venv。

---

## v0.9.5（2026-08-17）

### 修复
- **第二/三引擎安装 torch 本地轮子报 Invalid wheel filename (invalid version)（很多用户装不上第二引擎）**：预下载的 torch/torchvision/torchaudio 轮子文件名里 %2B 是 URL 编码的 +，之前下载到本地后文件名没解码，pip 本地安装按文件名解析版本失败。现在下载 URL 保持编码、本地文件名解码成 +（如 	orch-2.7.1+cu128-...whl），并自动把旧版本残留的 %2B 缓存改名复用，不用重新下载 3GB。

---

## v0.9.4（2026-08-17）

### 修复
- **训练监控把数据集缓存进度误当成训练步数（"假 20/20 100%"卡住错觉）**：latents / 文本编码器缓存阶段的 tqdm 是批次进度，不再计入训练步数；缓存阶段单独显示「正在缓存数据集…」，训练真正开始后才显示步数/loss/速度。
- **kohya venv 用 Python 3.10/3.11 建出、与内置 cp312 依赖错配导致 numpy/torch 装不上（训练退化成 CPU 版 torch → accelerator device: cpu 卡死）**：
  - 建 venv 优先用 Python 3.12（一键安装脚本与程序内），并校验 venv 实际版本，非 3.12 给出明确提示；
  - find_python 改为 3.12 优先（不再让 PATH 里任意版本的 python 抢跑建出错误版本 venv）；
  - 内置离线 wheel 安装前按 venv Python 版本过滤，避免 cp312 wheel 装进 3.10/3.11 报 not supported；
  - NVIDIA 卡上「已安装」判定要求 torch.cuda 可用，CPU 版 torch 不再被当成装好而跳过重装 cu128；
  - AMD 版 PyTorch wheel URL 的 Python 标签映射修正（3.10→cp310，不再错配 cp312）。
- **训练环境状态检测对第二/三引擎 venv python.exe 存在性硬校验**：musubi-venv / ai_toolkit_venv 的 python.exe 必须真实存在才算已安装，残缺 venv 不再显示为已安装。

- **Qwen3-0.6B / Anima VAE 手动放置不生效（"放到指定文件夹也没用"）**：兼容新旧安装目录（老版 %APPDATA%\\Kohya_ss 与新版 %APPDATA%\\KohyaLoraTool\\anima 都扫描），用户按旧提示把模型放到 Kohya_ss\\Qwen3-0.6B 也能被识别，不再强制走自动下载。
- **模型下载时报 python312.dll conflicts（venv 是 3.10/3.11 却混入 3.12 编译的扩展）**：下载前预检 huggingface_hub，版本错配时直接给出明确修复指引（用 Python 3.12 重建 venv / 手动放置模型），不再让用户面对晦涩的 dll 冲突报错。

---

## v0.9.3（2026-08-17）

### 新增
- **第三引擎（AI Toolkit）支持「导入已装环境」**：手动装好 AI Toolkit 的用户不用重新部署——点「📂 导入已装环境」选择已装目录（含 run.py 的源码目录，或含 ai-toolkit 子目录的根目录），程序自动探测源码 + venv 并复用，检测通过后直接训练。

### 修复
- **环境装好/导入后界面仍显示「未安装」（30 秒检测缓存）**：安装或导入完成后立即清空环境检测缓存并刷新，不再出现装好了还显示未装。
- **第三引擎检测支持自定义目录**：ai_toolkit_engine_status / 引导状态 / 训练（H3 视频、Qwen-Image、Z-Image）统一使用「用户导入目录优先、标准位置兜底」的路径解析。
- **第二/三引擎安装 torch 失败（ResolutionImpossible / No matching distribution）**：阿里 pytorch-wheels 是文件仓库（curl 可直链下载），但 pip 不能把它当 index 解析；之前回退/配置把阿里当 pip 源 + 混用官方 download.pytorch.org，国内网络下 pip 解析 torch 失败。现在：① 预下载走阿里 curl 断点续传（重试 3 次）→ 本地 wheel 安装（主路径，国内快）；② 彻底失败才回退官方 index（提示挂代理）；③ 移除无效的阿里 extra-index 配置。
- **Anima 训练 Qwen3-0.6B 自动下载失败后，手动放置模型不被识别**：之前只认完整目录里的 config.json，用户手动放单个 .safetensors 权重（或完整文件夹）都不被识别，仍强制走自动下载。现在支持两种手动放置（完整文件夹 或 单个 .safetensors 权重，sd-scripts 会自动用内置 config/tokenizer 加载），并给出明确的下载地址与放置路径提示。

---

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

