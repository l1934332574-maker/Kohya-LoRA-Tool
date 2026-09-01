# 第四引擎（Fizgig · AMD ROCm）接入计划

> 状态：计划（未开工）。目标：让 AMD 用户能稳定跑 Krea2 图像 LoRA，替代第二引擎 musubi 在 AMD 上 fallback CPU 的现状。
> 依据：Fizgig v5.0.0（2026-08-29 发布，Apache-2.0，GitHub 319 stars，更新活跃）。

## 一、结论：可以做，且比预期顺

> 补充（2026-09-01）：**N 卡也能用，而且 NVIDIA 是 Fizgig 的主场/主推平台**——标准安装
> （install_fizgig.bat → install_fizgig.py）就是 NVIDIA CUDA 路径（torch 2.10.0+cu128，驱动 555+，
> Win/Linux 都支持）；AMD ROCm 是 v4.3 才后加的。所以第四引擎应设计成**按显卡厂商自适应**
> （NVIDIA→CUDA 安装路径，AMD→ROCm 安装路径），而不是「仅 AMD」。优先级仍先做 AMD（当前最痛的缺口），
> NVIDIA 路径等 AMD 试点成功后再开。

1. **Fizgig 官方支持 AMD Windows ROCm**（v4.3.0，2026-08-22 上线）：RDNA1~RDNA4 / Strix Point / Instinct，Windows 是官方主推路径（Linux 反而实验性）。安装器自动检测显卡架构并拉对应 wheel。
2. **有完整 CLI**（`docs/CLI.md`）：`krea2_cache_latents.py` → `krea2_cache_text.py` → `krea2_train.py` 三件套，GUI 只是拼命令的壳。可以像 musubi/ai-toolkit 一样被我们驱动。
3. **模型文件 100% 复用现有 models/krea2/**，无需重新下载：
   | Fizgig 需要 | 现有文件 | 大小 |
   |---|---|---|
   | krea2_raw_bf16.safetensors | models/krea2/raw.safetensors | 25 GB（已有）|
   | qwen_image_vae.safetensors | models/krea2/qwen_image_vae.safetensors | 242 MB（已有）|
   | qwen3vl_4b_bf16.safetensors | models/krea2/qwen3vl_4b_bf16.safetensors | 8.4 GB（已有）|
   | krea2_turbo_fp8_scaled.safetensors（仅采样预览用）| 无（可选下载 ~13GB）| 不训练也可不装 |
4. **Python 3.12 直接复用**：工具已内置 python-3.12.10-amd64.exe（第二引擎 musubi 也用 3.12）；Fizgig ROCm 的 bitsandbytes wheel 是 cp312-only，正好匹配。
5. **许可证可再分发**：Fizgig 本体 Apache-2.0；其中 `detect_gpu.py` 是 comfyui-rocm 的 GPL-3.0 文件（随包带，需保留 THIRD_PARTY_NOTICES）。

## 二、内核安装大小（实测/核实数字）

来源：AMD 官方 nightly 索引 `https://rocm.nightlies.amd.com/whl-multi-arch/`（已 HEAD 实测 wheel 大小）。

| 组件 | 版本 | 下载量 | 说明 |
|---|---|---|---|
| Fizgig 源码 | v5.0.0 tag（钉死） | ~14 MB | 仓库源码 zip（GitHub size 14,334 KB）|
| torch (ROCm win) | 2.12.0+rocm7.15.0a20260728 | ~112 MB | AMD nightly，win_amd64 |
| torchvision (ROCm win) | 0.27.0+rocm7.15.0a20260728 | ~1 MB | |
| rocm-sdk-devel | 7.15.0a20260728 | ~655 MB | 随 pip 装，无需系统级 HIP SDK |
| rocm-sdk-core（依赖）| 同系列 | ~759 MB | devel 的依赖 |
| rocm-sdk-libraries（依赖）| 同系列 | ~116 MB | devel 的依赖 |
| bitsandbytes (ROCm win) | 0.50.2.dev0-cp312（0xDELUXA 社区轮子）| ~19 MB | |
| 共享依赖（transformers/diffusers/accelerate 等）| 钉死版本 | ~0.5~1 GB | requirements.txt 过滤 CUDA 行后安装 |
| InsightFace 模型 | — | ~300 MB | 仅 GUI 人脸预处理用；headless 可跳过 |
| **合计新增下载** | | **≈ 2.2 ~ 2.7 GB** | |
| **装完磁盘占用** | | **≈ 4 ~ 5 GB**（venv + pip 缓存）| pip 缓存可清理 |

对比：第二引擎 musubi 的 torch cu128 wheel 本身就 3.1 GB（3121 MB）——第四引擎整体下载量 ≈ 第二引擎一个 torch 包的量级，可接受。

## 三、前置工作（全部）

### P0（硬门槛，先做）：AMD 真机试点
- 目标：在真实 AMD 机器上，用 Fizgig CLI 跑通一次最小 Krea2 训练（10~20 张图、512~768、低步数）。
- 优先机：群友 7800 XT（RDNA3，Windows ROCm 官方支持最稳）。
- 备选：6800 XT 用户（RDNA2，gfx1030，索引里有对应 wheel，但历史上这位用户蓝屏/掉驱动过，风险最高）。
- 成功标准：日志显示 HIP/ROCm 设备不 fallback CPU；单步速度合理；不蓝屏不掉驱动；LoRA 出图正常。
- **试点不过，第四引擎不做**（避免重蹈第二引擎在 AMD 上翻车的覆辙）。

### P1：版本钉死 + 国内镜像缓存（解决国内网络）
- Fizgig 源码 zip 上传魔搭 `engine_sources/fizgig-main.zip`（沿用 ai-toolkit 的做法）。
- 把试点验证过的 5 个 ROCm wheel（torch/torchvision/rocm-sdk-devel/core/libraries）+ bnb wheel 一起上传魔搭，安装优先走魔搭直链，失败再走 AMD nightly（curl 断点续传）。总上传 ≈ 1.5~2 GB。
- **原因**：AMD nightly 索引没有国内镜像，且 nightly 会滚动清理——不缓存，用户装不了/以后装不上。

### P2：Python 3.12 复用
- 复用内置 python-3.12.10-amd64.exe（musubi 已依赖）；安装前确保 Tkinter 勾选（Fizgig GUI 需要，但我们只用 CLI，仅作防御）。

### P3：GPU 架构探测
- 复用 Fizgig 自带 `detect_gpu.py`（comfyui-rocm，输出 gfxXXXX），或参照现有 `kohya_core/gpu.py` 实现 AMD gfx 检测。
- 映射表：RX 7900 XTX/XT=1100，7800 XT=1100，7700 XT=1101，6800/6900=1030，6700 XT=1031，7600 XT=1150/1151，9070=1201 等。

### P4：许可证/第三方声明
- THIRD_PARTY_NOTICES.md 增加：Fizgig（Apache-2.0）+ comfyui-rocm detect_gpu.py（GPL-3.0）+ 0xDELUXA bitsandbytes win ROCm（MIT?）。

### P5：冒烟测试
- `engine_install_smoke_test.py` 增加第四引擎控制流测试：命令构造、状态判定、模型路径映射（不真装 GPU 环境）。
- 两套既有冒烟测试继续全绿。

## 四、技术方案（代码层）

### 4.1 安装 `install_fizgig_engine()`（复用第三引擎模式）
- 目录：`<kdir>/fizgig`（源码）+ `<kdir>/fizgig_venv`（venv）——与 musubi/ai-toolkit 并存风格一致，加入 `KOHYA_COEXIST_SUBDIRS`。
- 流程：源码部署（内置/魔搭 zip，缺 run 文件自清理重部署）→ 用 Python 3.12 建 venv（损坏自愈同现逻辑）→ 装 ROCm 栈（魔搭缓存优先，AMD nightly 兜底，断点续传）→ 装共享依赖（过滤后 requirements）→ 装 bnb wheel → 验证 `import torch; torch.cuda.is_available(); torch.version.rocm`。
- 幂等：已装可用则跳过。
- 不装 InsightFace（headless 训练用不到）。

### 4.2 状态 `fizgig_engine_status()` / `_fizgig_marker_ok()`
- marker：venv python 存在 + `fizgig/src/fizgig/scripts/krea2_train.py` 存在。
- 权威：`import torch; print(torch.version.rocm, torch.cuda.is_available(), torch.cuda.get_device_name(0))`，要求 HIP 可用。

### 4.3 训练管线（Krea2）
```
写数据集 TOML（[general] resolution/caption_extension/batch_size/num_repeats/enable_bucket + [[datasets]] image_directory/cache_directory）
→ <fizgig_venv>\python.exe <fizgig>/src/fizgig/scripts/krea2_cache_latents.py --dataset_config ... --vae models/krea2/qwen_image_vae.safetensors
→ krea2_cache_text.py --dataset_config ... --text_encoder models/krea2/qwen3vl_4b_bf16.safetensors
→ krea2_train.py --dataset_config ... --dit models/krea2/raw.safetensors --vae ... --text_encoder ...
    --output_dir <项目输出> --output_name <名称>
    --network_dim/--network_alpha --learning_rate --max_train_epochs --save_every_n_epochs
    --lr_scheduler cosine --lr_warmup_steps --seed
    [--quantize_4bit] 或 [--quant_int8 bf16] 或默认动态 fp8 + [--blocks_to_swap N]
    [--sample_prompts ... --sample_every_n_epochs 1 --turbo_dit ...]（可选预览）
```
- 显存策略（16G AMD 卡）：默认动态 fp8 + blocks_to_swap；10~12G 用 `--quantize_4bit`（NF4 底模驻留 ~5.6GB，社区实测可跑）；不碰 bf16 底模直训。
- 断点续训：Fizgig 原生 pause/resume（sentinel 文件）——先不接，二期再做，避免范围膨胀。
- 输出：标准 LoRA safetensors（ComfyUI 可直接用），沿用项目输出目录。

### 4.4 模型检查
- 复用 `krea2_missing_models` 逻辑（raw/vae/te 三个文件已覆盖）；turbo 只作可选下载。

## 五、UI 方案
- `kohya_gui.py`：
  - `ENGINE_GROUPS` 增加 `("第四引擎 · fizgig", ("krea2_fz",))`；`SHORT_MODE_LABELS["krea2_fz"]="Krea2AMD"`。
  - 侧边栏新增安装按钮「⚙ 安装第四引擎」+ 状态点（沿用 2×2 网格布局，1 个模式走单行）。
  - 模式页：与 Krea2（第二引擎）同款参数（rank/alpha/lr/epochs/分辨率/量化档），多一个「显存档位」下拉（自动 fp8 / NF4 4bit / INT8）。
  - 新手引导补第 4 步（仅 AMD 显示）。
- 仅在检测到 AMD 显卡时展示第四引擎入口（NVIDIA 用户默认隐藏，减少噪音；可在设置里手动显示）。

## 六、风险与对策
| 风险 | 对策 |
|---|---|
| AMD nightly 无国内镜像 + 滚动清理 | P1 魔搭缓存钉死 wheel（试点验证过的那套）|
| RDNA2（6800 XT）稳定性历史差 | 试点先 7800 XT；6800 XT 标注 best-effort；工具内检测 gfx1030 给提示 |
| nightly 轮子版本漂移导致装不上 | 安装时严格用缓存版本 + 校验 sha256 |
| torch.compile（triton）在 ROCm Windows 不可用 | Fizgig 会自动 graceful 降级 eager；默认不开 compile |
| Fizgig 更新节奏快（周更）| 钉死 tag（v5.0.0），不追 master；镜像缓存与软件同发 |
| 与现有引擎冲突 | 独立 venv + 独立源码目录，加入共存白名单；跑两套冒烟测试 |
| 采样预览引入问题 | 一期仅训练，预览二期再说 |

## 七、里程碑

> 进度（2026-09-01）：第 1 步骨架 ✅ → 第 2 步 NVIDIA 本机实装 ✅ → 第 3 步 GUI 入口 ✅ → 第 4 步训练管线 ✅ → 魔搭缓存 ✅
> （源码 + 6 个 ROCm wheel 已上传魔搭，AMD 安装改为魔搭优先 + nightly 兜底，双冒烟全绿）。
> AMD 真机试点仍需要群友 7800 XT / 6800 XT 机器（P0 硬门槛保留）。

- M0 AMD 真机试点（P0）——外部依赖：群友/用户机器
- M1 资源缓存上传魔搭（源码 + 5 wheel + bnb）——需确认魔搭上传权限/空间
- M2 引擎安装 + 状态 + 冒烟
- M3 训练管线（TOML/cache/train）+ 模型复用
- M4 UI（导航/安装按钮/参数页/引导）
- M5 双冒烟全绿 + 打包发版（提示手动传 Setup.exe）
- M6（二期）NVIDIA CUDA 路径：torch cu128（约 3GB，国内阿里云 pytorch-wheels 有镜像，比 ROCm 好办），
  验证 12G/16G 卡速度后再全量放开

## 八、待确认
1. 试点机器和群友（谁跑 7800 XT？）
2. 魔搭仓库上传权限（1.5~2GB wheel 缓存）
3. 是否一期就做采样预览（建议二期）
4. 第四引擎入口：建议 NVIDIA/AMD 都显示（安装时自动选 CUDA/ROCm 路径），NVIDIA 侧二期再做
