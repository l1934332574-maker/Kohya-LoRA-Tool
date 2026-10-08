"""Bounded, read-only image access for dataset inspection and run sample galleries."""
import base64
import io
import os
import re
from pathlib import Path


def is_sample(filename, parent):
    low = filename.lower()
    return (low.endswith((".png", ".jpg", ".jpeg", ".webp")) and
            ("sample" in low or parent.lower() in ("sample", "samples") or
             re.search(r"_\d{4,}_|-\d+\.", low) is not None))


def sample_files(output_dir, started):
    root_path = Path(output_dir)
    files = []
    if not root_path.is_dir():
        return files
    scan_errors = []
    for root, dirs, names in os.walk(root_path, onerror=scan_errors.append):
        parent = Path(root)
        depth = len(parent.relative_to(root_path).parts)
        dirs[:] = [name for name in dirs if depth < 4 and not name.startswith(".") and
                   not (parent / name).is_symlink()]
        for name in names:
            path = parent / name
            if path.is_symlink() or not is_sample(name, parent.name):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_mtime < started - 2 or stat.st_size <= 0:
                continue
            relative = path.relative_to(root_path).as_posix()
            files.append({"name": relative, "version": "%s:%s:%s" % (stat.st_mtime_ns, stat.st_size, relative),
                          "modified": stat.st_mtime, "bytes": stat.st_size})
    if scan_errors:
        raise scan_errors[0]
    return sorted(files, key=lambda item: (item["modified"], item["name"]), reverse=True)


def image_preview(root, name, full=False, max_size=None):
    root = Path(root).resolve()
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("图片路径无效")
    path = root / relative
    if any((root / Path(*relative.parts[:n])).is_symlink() for n in range(1, len(relative.parts) + 1)):
        raise ValueError("不读取链接指向的图片")
    if not path.resolve().is_relative_to(root):
        raise ValueError("图片不在当前目录中")
    from PIL import Image
    with Image.open(path) as source:
        width, height = source.size
        if width * height > 80_000_000:
            raise ValueError("图片尺寸过大")
        source.thumbnail(max_size or ((1400, 1400) if full else (520, 520)))
        image = source.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=86, method=4)
    return {"data_url": "data:image/webp;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
            "width": width, "height": height}
