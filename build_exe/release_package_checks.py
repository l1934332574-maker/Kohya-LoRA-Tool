"""Release checks for files consumed by standalone Python workers."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def verify_external_image_io(source_root, package_root, worker_python=None):
    """Run the packaged entry point, including its bundled-DLL path sanitization."""
    source_root = Path(source_root).resolve()
    package_root = Path(package_root).resolve()
    for relative in ("preprocess.py", "kohya_core/image_io.py"):
        source, packaged = source_root / relative, package_root / relative
        if not packaged.is_file():
            raise RuntimeError("发布包缺少独立预处理文件：" + relative)
        if not source.is_file() or source.read_bytes() != packaged.read_bytes():
            raise RuntimeError("发布包中的文件与仓库源文件不一致：" + relative)
    if not any(package_root.glob("python3*.dll")):
        raise RuntimeError("发布验证必须使用包含 Python 动态库的完整安装包目录")

    from PIL import Image
    with tempfile.TemporaryDirectory(prefix="kohya-package-images-") as temporary:
        work = Path(temporary)
        inputs, outputs = work / "input", work / "output"
        inputs.mkdir()
        exif = Image.Exif()
        exif[274] = 6
        Image.new("RGB", (160, 128), (90, 140, 190)).save(inputs / "portrait.jpg", exif=exif)
        Image.new("RGBA", (160, 128), (90, 140, 190, 0)).save(inputs / "alpha.png")
        palette = Image.new("P", (160, 128), 0)
        palette.putpalette([90, 140, 190] + [0] * 765)
        palette.save(inputs / "palette.png", transparency=0)
        for image in inputs.iterdir():
            image.with_suffix(".txt").write_bytes(b"character, blue hair\n")
        originals = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in inputs.iterdir()}
        report = work / "report.json"
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        for name in ("PYTHONPATH", "PYTHONHOME"):
            env.pop(name, None)
        result = subprocess.run(
            [str(worker_python or sys.executable), "-B", str(package_root / "preprocess.py"),
             "--input", str(inputs), "--output", str(outputs), "--size", "160",
             "--mode", "character", "--no-wd14", "--keep-user-captions",
             "--no-remove-watermark", "--no-remove-black-borders",
             "--no-write-dataset-config", "--report", str(report)],
            cwd=work, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        )
        if result.returncode != 0:
            detail = (result.stdout + "\n" + result.stderr).strip()[-2400:]
            raise RuntimeError("安装包的独立预处理入口运行失败：\n" + detail)
        if not report.is_file():
            raise RuntimeError("安装包预处理未生成完成报告")
        summary = json.loads(report.read_text(encoding="utf-8"))
        if summary.get("ok") != 3 or summary.get("corrupt") != 0 or summary.get("failed") != 0:
            raise RuntimeError("安装包预处理未正确读取全部 JPG/PNG 图片：" + str(summary))
        after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in inputs.iterdir()}
        if after != originals or inputs.with_name("input_corrupt").exists():
            raise RuntimeError("安装包预处理改动了正常输入图片或标签")
        for name in ("portrait", "alpha", "palette"):
            output = outputs / (name + ".png")
            with Image.open(output) as image:
                image.load()
                if image.mode != "RGB":
                    raise RuntimeError("安装包预处理未将图片规范为 RGB：" + name)
                if name == "portrait" and image.size != (128, 160):
                    raise RuntimeError("安装包预处理未正确校正 EXIF 方向")
                if name != "portrait" and image.getpixel((0, 0)) != (255, 255, 255):
                    raise RuntimeError("安装包预处理未正确处理透明背景：" + name)
            if (outputs / (name + ".txt")).read_bytes() != (inputs / (name + ".txt")).read_bytes():
                raise RuntimeError("安装包预处理未保留原标签：" + name)
    print("独立预处理入口已核对：JPG/EXIF、透明 PNG、调色板 PNG；原图和标签均保留。", flush=True)
