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
