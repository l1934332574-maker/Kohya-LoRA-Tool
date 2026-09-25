# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 便携目录包（onedir）配置：dist\Kohya一键工具\ 即整个便携包。
# contents_directory='.' 让所有文件直接放在 exe 旁边，用户解压即可运行。
# 说明：不打包 torch / 大模型 / numpy / cv2 等；新界面依赖 Vue 构建产物与 pywebview。
# 经典 CustomTkinter 界面仍打入同一程序，作为兼容回退入口。

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# customtkinter 运行时需要主题 json 等资源；darkdetect 是其跨平台依赖
ctk_datas = collect_data_files("customtkinter")
ctk_hidden = collect_submodules("customtkinter")
dd_datas = collect_data_files("darkdetect")
modern_ui_root = os.path.normpath(os.path.join(os.path.dirname(SPEC), "..", "modern_ui"))
modern_ui_dist = os.path.join(modern_ui_root, "dist")
if not os.path.isfile(os.path.join(modern_ui_dist, "index.html")):
    raise RuntimeError("现代 UI 尚未构建。请先运行 npm --prefix modern_ui ci && npm --prefix modern_ui run build。")
modern_ui_datas = [(modern_ui_dist, "modern_ui/dist")]
try:
    import webview as _webview  # noqa: F401
    webview_hidden = collect_submodules(
        "webview",
        filter=lambda name: not name.startswith("webview.platforms.") or name in {
            "webview.platforms.winforms",
            "webview.platforms.edgechromium",
            "webview.platforms.win32",
        },
    )
    webview_datas = collect_data_files("webview")
except Exception as exc:
    raise RuntimeError("打包新版界面前，请运行 python -m pip install -r requirements-ui.txt。") from exc

# 程序图标：存在 app.ico 才设置（项目根或 build_exe 下）
_icon_path = os.path.join(os.path.dirname(SPEC), "app.ico")
if not os.path.isfile(_icon_path):
    _icon_path = os.path.join(os.path.dirname(os.path.dirname(SPEC)), "app.ico")
_icon = _icon_path if os.path.isfile(_icon_path) else None

a = Analysis(
    ['..\\kohya_gui.py'],
    pathex=['..'],
    binaries=[],
    datas=[
        ('..\\preprocess.py', '.'),
        ('..\\video_caption.py', '.'),
        ('..\\model_downloader.py', '.'),
        ('..\\README_使用说明.md', '.'),
        ('..\\LICENSE', '.'),
        ('..\\THIRD_PARTY_NOTICES.md', '.'),
        # WD14 打标模型内置：开箱即用，无需联网下载（约 311MB）
        ('..\\wd14_tagger_model', 'wd14_tagger_model'),
    ] + ctk_datas + dd_datas + modern_ui_datas + webview_datas,
    hiddenimports=ctk_hidden + webview_hidden + [
        # 标签管理 v1：中英词典/翻译/补全（kohya_gui 内惰性 import，显式声明防漏收集）
        'gui.tag_tools',
        'kohya_core.tagging', 'kohya_core.tagging.dictionary',
        'kohya_core.tagging.normalize', 'kohya_core.tagging.translate',
        'kohya_core.tagging.complete',
        'kohya_core.anima_ckpt',
        'kohya_core.lora_naming',
        'kohya_core.queue',
        'gui.queue_window',
        'gui.modern_host',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 'numpy', 'cv2', 'tensorflow', 'keras',
        'gradio', 'transformers', 'diffusers', 'onnxruntime', 'scipy',
        'pandas', 'matplotlib', 'sklearn', 'scikit_learn', 'wandb',
        'psutil', 'yaml', 'tensorboard', 'librosa',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Kohya一键工具',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
    contents_directory='.',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name='Kohya一键工具',
)
