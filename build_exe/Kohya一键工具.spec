# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 便携目录包（onedir）配置：dist\Kohya一键工具\ 即整个便携包。
# contents_directory='.' 让所有文件直接放在 exe 旁边，用户解压即可运行。
# 说明：不打包 torch / 大模型 / numpy-cv2-PIL 等，只打包代码与脚本（运行数据重定向到 %APPDATA%）。

import os

# 程序图标：存在 app.ico 才设置（项目根或 build_exe 下）
_icon_path = os.path.join(os.path.dirname(SPEC), "app.ico")
if not os.path.isfile(_icon_path):
    _icon_path = os.path.join(os.path.dirname(os.path.dirname(SPEC)), "app.ico")
_icon = _icon_path if os.path.isfile(_icon_path) else None

a = Analysis(
    ['..\\Kohya一键工具.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('..\\preprocess.py', '.'),
        ('..\\README_使用说明.md', '.'),
        ('..\\LICENSE', '.'),
        ('..\\THIRD_PARTY_NOTICES.md', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch', 'numpy', 'cv2', 'PIL', 'Pillow', 'tensorflow', 'keras',
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
