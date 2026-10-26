"""Shared, non-destructive image decoding and diagnostics for dataset workflows."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile


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

    if isinstance(exc, PermissionError):
        return ImageDecodeError("图片「%s」无读取权限（PermissionError）：%s；请检查文件权限或占用情况。" % (name, exc))
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
            "请用图片软件打开后另存为 PNG/JPEG；原图不会被修改。解码器：%s。"
            % (name, path.suffix or "无扩展名", type(exc).__name__))
    detail = str(exc).replace("\r", " ").replace("\n", " ").strip()
    if len(detail) > 180:
        detail = detail[:177] + "..."
    return ImageDecodeError(
        "图片「%s」（%s）无法完整解码；请打开后另存为新的 PNG/JPEG。%s"
        % (name, detected, (" 解码器信息：" + detail) if detail else ""))


# Paths are passed through the environment, never interpolated into shell code.
# WIC runs out of process so a native codec failure cannot terminate the UI.
_WINDOWS_DECODE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
try { Add-Type -AssemblyName PresentationCore } catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 3
}
try {
    $inputStream = [System.IO.File]::OpenRead($env:KOHYA_IMAGE_INPUT)
    try {
        $decoder = [System.Windows.Media.Imaging.BitmapDecoder]::Create(
            $inputStream,
            [System.Windows.Media.Imaging.BitmapCreateOptions]::IgnoreColorProfile,
            [System.Windows.Media.Imaging.BitmapCacheOption]::None)
        $frame = $decoder.Frames[0]
        $pixels = [long]$frame.PixelWidth * [long]$frame.PixelHeight
        if ($pixels -le 0 -or $pixels -gt [long]$env:KOHYA_IMAGE_PIXEL_LIMIT) {
            [Console]::Error.WriteLine('Image exceeds the pixel limit')
            exit 4
        }
        $orientation = 1
        try {
            foreach ($query in @('/app1/ifd/{ushort=274}', '/ifd/{ushort=274}')) {
                if ($frame.Metadata -and $frame.Metadata.ContainsQuery($query)) {
                    $orientation = [int]$frame.Metadata.GetQuery($query)
                    break
                }
            }
        } catch { $orientation = 1 }
        $bitmap = [System.Windows.Media.Imaging.FormatConvertedBitmap]::new(
            $frame, [System.Windows.Media.PixelFormats]::Bgra32, $null, 0)
        $encoder = [System.Windows.Media.Imaging.PngBitmapEncoder]::new()
        $encoder.Frames.Add([System.Windows.Media.Imaging.BitmapFrame]::Create(
            $bitmap, $null, $null, $null))
        $outputStream = [System.IO.File]::Create($env:KOHYA_IMAGE_OUTPUT)
        try { $encoder.Save($outputStream) } finally { $outputStream.Dispose() }
        @{ orientation = $orientation } | ConvertTo-Json -Compress
    } finally { $inputStream.Dispose() }
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
"""


def _windows_decode(path, *, pixel_limit):
    """Recover pixels with the installed Windows codec; never alter the source."""
    from PIL import Image
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    if not powershell.is_file():
        raise ImageEnvironmentError('Windows 备用图片解码器不可用；原图未修改。')
    with tempfile.TemporaryDirectory(prefix='kohya_image_') as directory:
        converted = Path(directory) / 'decoded.png'
        env = dict(os.environ, KOHYA_IMAGE_INPUT=str(Path(path).resolve()),
                   KOHYA_IMAGE_OUTPUT=str(converted), KOHYA_IMAGE_PIXEL_LIMIT=str(pixel_limit))
        try:
            result = subprocess.run(
                [str(powershell), '-NoProfile', '-NonInteractive', '-STA', '-Command', _WINDOWS_DECODE],
                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired as exc:
            raise OSError('Windows 备用解码超过 30 秒，已停止；原图未修改。') from exc
        except OSError as exc:
            raise ImageEnvironmentError('无法启动 Windows 备用图片解码器：' + str(exc)) from exc
        detail = result.stderr.decode('utf-8-sig', errors='replace').strip()[-400:]
        if result.returncode == 3:
            raise ImageEnvironmentError('Windows 图片组件无法加载：' + detail)
        if result.returncode or not converted.is_file():
            raise OSError(detail or 'Windows 备用解码未能恢复图片')
        metadata = json.loads(result.stdout.decode('utf-8-sig'))
        with Image.open(converted) as source:
            if source.width * source.height > pixel_limit:
                raise ImageDecodeError('备用解码图片的像素数量超过安全上限。')
            source.load()
            image = source.copy()
        orientation = int(metadata.get('orientation', 1))
        if 1 <= orientation <= 8:
            image.getexif()[274] = orientation
        return image


def _normalize_pixels(source, *, preserve_alpha, alpha_background, max_pixels):
    from PIL import Image, ImageOps
    width, height = source.size
    if width <= 0 or height <= 0:
        raise ImageDecodeError('图片尺寸无效。')
    if max_pixels is not None and width * height > int(max_pixels):
        raise ImageDecodeError('图片尺寸过大：%d × %d。' % (width, height))
    source.load()
    orientation = source.getexif().get(274, 1)
    image = ImageOps.exif_transpose(source)
    has_alpha = 'A' in image.getbands() or 'transparency' in image.info
    if preserve_alpha and has_alpha:
        image = image.convert('RGBA')
    elif alpha_background is not None and has_alpha:
        rgba = image.convert('RGBA')
        image = Image.new('RGB', rgba.size, tuple(alpha_background))
        image.paste(rgba, mask=rgba.getchannel('A'))
    else:
        image = image.convert('RGB')
    result = image.copy()
    result.info['kohya_source_size'] = (width, height)
    result.info['kohya_source_orientation'] = orientation
    return result


def read_image(path, *, preserve_alpha=False, alpha_background=None, max_pixels=None):
    """Fully decode and orient pixels, retrying failed Windows images with WIC.

    Environment failures and pixel limits are never treated as recoverable bad
    files. Neither decoder modifies originals or enables truncated-image loading.
    """
    options = dict(preserve_alpha=preserve_alpha, alpha_background=alpha_background, max_pixels=max_pixels)
    try:
        from PIL import Image
        # Image.open silently ignores ImportError from plugins. Import the known
        # decoder explicitly so a missing runtime module is reported correctly.
        plugin = {'PNG': 'Png', 'JPEG': 'Jpeg', 'GIF': 'Gif', 'BMP': 'Bmp',
                  'TIFF': 'Tiff', 'WEBP': 'WebP', 'AVIF': 'Avif'}.get(_sniff_format(path))
        if plugin:
            import importlib
            importlib.import_module('PIL.' + plugin + 'ImagePlugin')
        with Image.open(path) as source:
            return _normalize_pixels(source, **options)
    except (ImageEnvironmentError, ImageDecodeError):
        raise
    except Exception as exc:
        if exc.__class__.__name__ in ('DecompressionBombError', 'DecompressionBombWarning'):
            raise ImageDecodeError('图片「%s」像素数量超过安全上限。' % Path(path).name) from exc
        if not isinstance(exc, (OSError, ValueError, SyntaxError, ImportError, MemoryError)):
            raise
        diagnosed = image_error(path, exc)
        if isinstance(diagnosed, ImageEnvironmentError) or isinstance(exc, MemoryError):
            raise diagnosed from exc
        if (sys.platform != 'win32' or not Path(path).is_file()
                or isinstance(exc, PermissionError) or not _sniff_format(path)):
            raise diagnosed from exc
        from PIL import Image
        pixel_limit = min(int(max_pixels or Image.MAX_IMAGE_PIXELS or 89478485),
                          int(Image.MAX_IMAGE_PIXELS or 89478485))
        try:
            with _windows_decode(path, pixel_limit=pixel_limit) as recovered:
                image = _normalize_pixels(recovered, **options)
            image.info['kohya_decoder'] = 'windows'
            return image
        except ImageEnvironmentError:
            raise
        except (OSError, ValueError) as recovery_error:
            raise ImageDecodeError(str(diagnosed) + ' 自动另存也未成功：' + str(recovery_error)) from exc


def save_normalized_png(image, destination):
    """Atomically save clean RGB/RGBA pixels and validate the new PNG before use."""
    from PIL import Image
    destination = Path(destination)
    if destination.is_symlink():
        raise ValueError('标准图片输出不能覆盖符号链接。')
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.normalized_', suffix='.part', dir=destination.parent)
    try:
        os.close(fd)
        # Do not copy source EXIF, ICC, text chunks or decoder-specific metadata.
        with Image.new('RGBA' if image.mode == 'RGBA' else 'RGB', image.size) as clean:
            clean.paste(image)
            clean.save(temporary, format='PNG')
        with Image.open(temporary) as check:
            check.load()
            if check.format != 'PNG' or check.size != image.size:
                raise OSError('标准 PNG 保存校验失败。')
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def finish_image_batch(report_path, *, total, recovered, errors):
    """Keep the complete failure list; never silently drop training examples."""
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {'schema': 1, 'total': total, 'recovered': recovered, 'errors': errors,
              'originals_modified': False}
    fd, temporary = tempfile.mkstemp(prefix='.image_report_', suffix='.part', dir=report_path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, report_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    if errors:
        names = '、'.join(Path(row['source']).name for row in errors[:8])
        raise ImageDecodeError(
            f'已检查 {total} 张图片，自动转换后仍有 {len(errors)} 张无法读取：{names}。'
            f'完整清单：{report_path}。原图和标签均未移动或覆盖，请修复这些图片后重试。')
    return report
