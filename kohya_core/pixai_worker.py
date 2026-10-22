"""Isolated PixAI v1.0 inference. Only verified local upstream code is loaded."""
from __future__ import annotations

from contextlib import nullcontext
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import tempfile


def emit(value):
    print('[PIXAI_RESULT] ' + json.dumps(value, ensure_ascii=False), flush=True)


def atomic_caption(path, caption):
    if path.is_symlink():
        raise ValueError('标签路径为链接，拒绝写入。')
    fd, temporary = tempfile.mkstemp(prefix='.pixai-', suffix='.part', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(caption)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def run(job):
    root = Path(job['model']).resolve()
    print('[PixAI] 校验模型与官方推理组件…', flush=True)
    for name, meta in job['files'].items():
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != meta['size']:
            raise ValueError('模型文件缺失或发生变化：' + name)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != meta['sha256']:
            raise ValueError('模型文件校验失败：' + name + '，请重新下载修复。')
    import torch
    from PIL import Image, ImageOps
    spec = importlib.util.spec_from_file_location('pixai_verified_pipeline', root / 'tagger_pipeline.py')
    upstream = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = upstream
    spec.loader.exec_module(upstream)
    device = 'cuda' if job.get('device', 'auto') == 'auto' and torch.cuda.is_available() else 'cpu'
    use_bf16 = device == 'cuda' and torch.cuda.is_bf16_supported()
    print('[PixAI] 加载 v1.0；设备 %s；精度 %s；逐张处理…' % (device, 'BF16 自动混合精度' if use_bf16 else 'FP32'), flush=True)
    config = upstream.ViTDetClsConfig.from_pretrained(str(root), local_files_only=True)
    model, loading = upstream.ViTDetCls.from_pretrained(str(root), config=config,
        local_files_only=True, use_safetensors=True, torch_dtype=torch.float32, output_loading_info=True)
    if loading.get('missing_keys') or loading.get('mismatched_keys') or loading.get('error_msgs'):
        raise RuntimeError('PixAI 权重与架构不匹配，停止打标。')
    model.eval()
    try:
        model.to(device)
    except RuntimeError:
        if device == 'cpu':
            raise
        print('[PixAI] GPU 加载失败，改用 CPU（速度较慢）。', flush=True)
        device = 'cpu'
        model.to(device='cpu')
        torch.cuda.empty_cache()
    processor = upstream.RescalePadProcessor.from_pretrained(str(root), local_files_only=True)
    settings = job['options']
    thresholds = {'general': float(settings['threshold']), 'character': .27, 'style': .15, 'copyright': .24}
    categories = ['general'] + [key for key in ('character', 'copyright', 'style') if settings[key]]
    print('[PixAI] 输出类别：' + ', '.join(categories), flush=True)
    failed = 0
    for index, filename in enumerate(job['images']):
        path = Path(filename)
        signature = None
        try:
            if path.is_symlink():
                raise ValueError('图片路径为链接。')
            signature = [path.stat().st_size, path.stat().st_mtime_ns]
            with Image.open(path) as original:
                original.load()
                image = ImageOps.exif_transpose(original).convert('RGBA')
                canvas = Image.new('RGBA', image.size, (255, 255, 255, 255))
                canvas.alpha_composite(image)
                image = canvas.convert('RGB')
            def infer():
                pixels = processor(image, return_tensors='pt')['pixel_values'].to(device=device, dtype=model.dtype)
                # Keep complex rotary buffers intact; casting the whole module loses their imaginary part.
                autocast = torch.autocast('cuda', dtype=torch.bfloat16) if device == 'cuda' and use_bf16 else nullcontext()
                with torch.inference_mode(), autocast:
                    logits = model(pixels)
                return logits.float().sigmoid()[0].cpu().tolist()
            try:
                scores = infer()
            except RuntimeError:
                if device == 'cpu':
                    raise
                print('[PixAI] GPU 推理失败，改用 CPU 重试本张图片。', flush=True)
                device = 'cpu'
                model.to(device='cpu')
                torch.cuda.empty_cache()
                scores = infer()
            if len(scores) != len(config.tags) or any(not math.isfinite(score) for score in scores):
                raise ValueError('模型输出无效。')
            groups, offset = {}, 0
            for category, count in config.tags_split:
                count = int(count)
                if category in categories:
                    groups[category] = sorted(((config.tags[i].replace('_', ' '), scores[i])
                        for i in range(offset, offset + count) if scores[i] > thresholds[category]),
                        key=lambda pair: (-pair[1], pair[0]))
                offset += count
            if offset != len(scores):
                raise ValueError('模型标签类别不匹配。')
            tags = list(dict.fromkeys(tag for category in categories for tag, _ in groups.get(category, [])))
            caption = ', '.join(tags)
            if not caption or len(caption) > 8192:
                raise ValueError('未识别出有效关键词，请调整阈值或检查图片。')
            if signature != [path.stat().st_size, path.stat().st_mtime_ns]:
                raise ValueError('打标期间图片已修改，请重新生成。')
            if job.get('write_sidecars'):
                target = path.with_suffix('.txt')
                # Training only fills absent or empty captions; never overwrite existing text.
                if target.is_file() and target.read_text(encoding='utf-8-sig').strip():
                    raise ValueError('打标期间标签已被修改，请重新处理。')
                atomic_caption(target, caption)
            emit({'index': index, 'status': 'generated', 'caption': caption, 'image_signature': signature})
        except ModuleNotFoundError as exc:
            failed += 1
            missing = str(getattr(exc, 'name', '') or '')
            message = ('当前 Python 运行环境缺少标准库 fractions；这是环境问题，不是图片损坏。'
                       if missing == 'fractions' else '图片解码环境缺少模块：' + (missing or '未知模块'))
            emit({'index': index, 'status': 'failed', 'error': message, 'image_signature': signature})
        except ImportError as exc:
            failed += 1
            emit({'index': index, 'status': 'failed', 'error': '图片解码环境无法加载依赖：' + str(exc)[:220], 'image_signature': signature})
        except (OSError, ValueError) as exc:
            failed += 1
            emit({'index': index, 'status': 'failed', 'error': str(exc)[:300], 'image_signature': signature})
        print('[PixAI] 内置打标进度：%s/%s' % (index + 1, len(job['images'])), flush=True)
    print('[PixAI] 打标完成，失败 %s 张；模型进程退出后释放显存。' % failed, flush=True)
    return 2 if failed and job.get('write_sidecars') else 0


if __name__ == '__main__':
    try:
        job = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        sys.exit(run(job))
    except Exception as exc:
        print('[PixAI] ERROR: %s: %s' % (type(exc).__name__, str(exc)[:500]), flush=True)
        sys.exit(1)
