# 图集扫描后的内置模块导入失败 · 2026-10-26

## 原因

用户提供的新版堆栈包含 `worker_files.py:18` 的 `ModuleNotFoundError: kohya_bundled_workers`，随后在第 22 行转换为恢复组件缺失提示。此前仅凭旧堆栈判断旧程序或更新不完整不适用于这份新证据。

`preprocess.py` 在导入时遇到安装目录的 Python DLL 会移除该目录的 `sys.path` 条目。GUI 的 `project_config.dataset_images` 和 `ModernBridge._count_preprocessable_images` 会先导入该脚本，再启动预处理。移除目录后，PyInstaller 的 PYZ finder 无法发现后续尚未导入的模块。`video_caption.py` 有相同逻辑。

## 复现与检查盲区

使用独立 PyInstaller onedir 探针，先导入真实的 `project_config.dataset_images` 执行扫描，再调用真实的 `ensure_worker_files`。修复前稳定产生用户提供的同一异常及转换后的 RuntimeError；PYZ 中的内置恢复模块实际存在。证据位于 `work/worker-import-20261026/before-exact.json`。

旧安装自检直接预加载内置恢复模块，没有执行前置图集扫描，因而检查通过仍可能在 GUI 操作后失败。开发源码目录没有打包 DLL，普通源码测试同样绕开了触发条件。

## 修复

- `preprocess.py` 与 `video_caption.py` 只在独立 Python 进程中清理带打包 DLL 的脚本目录；frozen 主程序保留搜索路径。
- 独立 Python 运行时继续执行原有清理，避免加载不同 ABI 的应用 DLL。
- 安装自检先创建临时 PNG 并通过真实项目扫描函数读取，再加载恢复模块；不预加载该模块来掩盖路径破坏。
- 本地发布的独立图片检查和公共 Windows 构建均增加扫描顺序检查，要求实际 EXE 报告 `project_scan=true`。旧自检格式被拒绝。
- 增加隔离子进程回归测试，覆盖三个辅助模块在 frozen、外部 Python 和无打包 DLL 的源码环境中的导入行为。

## 验证范围

- 修复前：精简打包程序复现同一缺模块异常；回归测试的预处理和视频导入分支失败。
- 修复后：244 项单元测试完成，243 通过、1 跳过；基础 smoke 测试全部通过。
- 完整隔离打包 EXE：图集扫描后加载恢复模块通过；删除 `kohya_core/image_io.py` 后，同一路径恢复成功且字节一致。
- 完整隔离包的独立 Python 预处理：JPG/EXIF、透明 PNG、调色板 PNG 通过，原图与标签不变。
- 本轮未运行 GPU 训练，未覆盖用户安装，也未发布新版本。隔离 EXE 保留工作区版本号 0.19.20，仅用于验证，不作为新的正式安装包。
