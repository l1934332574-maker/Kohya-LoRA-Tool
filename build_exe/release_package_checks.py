"""Release checks for files consumed by standalone Python workers."""
from pathlib import Path
import subprocess
import sys


def verify_external_image_io(source_root, package_root):
    source_root = Path(source_root).resolve()
    package_root = Path(package_root).resolve()
    source = source_root / "kohya_core" / "image_io.py"
    packaged = package_root / "kohya_core" / "image_io.py"
    preprocess = package_root / "preprocess.py"
    if not preprocess.is_file():
        raise RuntimeError("发布包缺少独立预处理脚本 preprocess.py")
    if not packaged.is_file():
        raise RuntimeError("发布包缺少独立预处理所需的 kohya_core/image_io.py")
    if not source.is_file() or source.read_bytes() != packaged.read_bytes():
        raise RuntimeError("发布包中的 kohya_core/image_io.py 与仓库源文件不一致")
    if "from kohya_core.image_io import read_image" not in preprocess.read_text(encoding="utf-8-sig"):
        raise RuntimeError("预处理脚本的图片读取依赖检查未匹配当前入口")
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from kohya_core.image_io import read_image; "
        "assert callable(read_image); print('external image_io import: ok')"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(package_root)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    if result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr).strip()[-1200:]
        raise RuntimeError("独立预处理运行时无法导入已打包的图片模块：\n" + detail)
    print("独立预处理依赖已核对：kohya_core/image_io.py；" + result.stdout.strip(), flush=True)
