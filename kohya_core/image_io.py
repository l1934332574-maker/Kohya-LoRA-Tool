"""Shared, non-destructive image decoding and diagnostics for dataset workflows."""
from pathlib import Path
import sys


class ImageEnvironmentError(ValueError):
    """The Python image runtime is incomplete; the source image is not implicated."""


class ImageDecodeError(ValueError):
    """A specific source image could not be fully decoded."""


def _sniff_format(path):
    try:
        with Path(path).open("rb") as stream:
            head = stream.read(64)
    except OSError:
        return ""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "GIF"
    if head.startswith(b"BM"):
        return "BMP"
    if head.startswith((b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")):
        return "TIFF"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "WEBP"
    if len(head) >= 12 and head[4:8] == b"ftyp" and any(
            brand in head[8:32] for brand in (b"avif", b"avis")):
        return "AVIF"
    return ""


def _extension_formats(suffix):
    return {
        ".jpg": {"JPEG"}, ".jpeg": {"JPEG"}, ".jpe": {"JPEG"}, ".jfif": {"JPEG"},
        ".png": {"PNG"}, ".apng": {"PNG"}, ".webp": {"WEBP"},
        ".bmp": {"BMP"}, ".tif": {"TIFF"}, ".tiff": {"TIFF"},
        ".gif": {"GIF"}, ".avif": {"AVIF"}, ".avifs": {"AVIF"},
    }.get(str(suffix or "").lower(), set())


def image_error(path, exc):
    """Return a user-facing diagnosis without mistaking Python failures for bad files."""
    path = Path(path)
    name = path.name or "图片"
    if isinstance(exc, ModuleNotFoundError):
        missing = str(getattr(exc, "name", "") or "").strip()
        if missing == "fractions":
            hint = ("请完整重新安装或覆盖更新软件包后重试。"
                    if getattr(sys, "frozen", False)
                    else "请修复本次处理实际使用的 Python 环境后重试。")
            return ImageEnvironmentError(
                "图片解码所需的 Python 标准库 fractions 在当前运行环境中缺失；"
                "这不是图片损坏。" + hint)
        if missing:
            return ImageEnvironmentError(
                "读取图片所需的 Python 模块「%s」缺失；这是运行环境问题，不是图片损坏。" % missing)
        return ImageEnvironmentError("读取图片时 Python 环境缺少模块；请修复软件运行环境后重试。")
    if isinstance(exc, ImportError):
        return ImageEnvironmentError("图片解码组件无法加载；请修复软件运行环境后重试。")
    if isinstance(exc, MemoryError):
        return ImageDecodeError("图片「%s」解码时内存不足；请先缩小图片尺寸后重试。" % name)

    if not path.exists():
        return ImageDecodeError("图片「%s」已不存在或已移动，请重新选择图集。" % name)
    if not path.is_file():
        return ImageDecodeError("图片「%s」不是普通文件，请检查图集目录。" % name)
    detected = _sniff_format(path)
    expected = _extension_formats(path.suffix)
    if detected and expected and detected not in expected:
        return ImageDecodeError(
            "图片「%s」的扩展名是 %s，实际内容是 %s；请用图片软件“另存为 %s”，不要只改扩展名。"
            % (name, path.suffix or "无扩展名", detected,
               "JPEG" if detected == "JPEG" else "PNG"))
    if not detected:
        return ImageDecodeError(
            "无法识别图片「%s」的文件内容（扩展名 %s）；文件可能损坏或只是改了扩展名。"
            "请用图片软件打开后另存为 PNG/JPEG；原图不会被修改。"
            % (name, path.suffix or "无扩展名"))
    detail = str(exc).replace("\r", " ").replace("\n", " ").strip()
    if len(detail) > 180:
        detail = detail[:177] + "..."
    return ImageDecodeError(
        "图片「%s」（%s）无法完整解码；请打开后另存为新的 PNG/JPEG。%s"
        % (name, detected, (" 解码器信息：" + detail) if detail else ""))


def read_image(path, *, preserve_alpha=False, alpha_background=None, max_pixels=None):
    """Fully decode, apply EXIF orientation and return an independent normalized image.

    By default this preserves Pillow's RGB conversion behavior. Callers that need the
    training preprocessor's white matte can pass ``alpha_background=(255,255,255)``;
    preview callers can preserve transparency with ``preserve_alpha=True``.
    """
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as source:
            width, height = source.size
            if width <= 0 or height <= 0:
                raise ImageDecodeError("图片「%s」尺寸无效。" % Path(path).name)
            if max_pixels is not None and width * height > int(max_pixels):
                raise ImageDecodeError("图片「%s」尺寸过大：%d × %d。" % (Path(path).name, width, height))
            source.load()
            image = ImageOps.exif_transpose(source)
            bands = image.getbands()
            has_alpha = "A" in bands or "transparency" in image.info
            if preserve_alpha and has_alpha:
                image = image.convert("RGBA")
            elif alpha_background is not None and has_alpha:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, tuple(alpha_background))
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            return image.copy()
    except (ImageEnvironmentError, ImageDecodeError):
        raise
    except Exception as exc:
        if exc.__class__.__name__ == "DecompressionBombError":
            raise ImageDecodeError("图片「%s」像素数量超过安全上限。" % Path(path).name) from exc
        if isinstance(exc, (OSError, ValueError, SyntaxError, ImportError, MemoryError)):
            diagnosed = image_error(path, exc)
            raise diagnosed from exc
        raise
