"""Managed image loss masks. Originals are read only; edits apply to training copies."""
from __future__ import annotations
import base64
import hashlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import time

SUFFIX = '-masklabel'
MODES = frozenset(('flux2_fz', 'krea2_fz', 'qwen21_fz', 'moss_fz', 'zimage_fz', 'sdxl_fz', 'anima_fz'))
KINDS = ('off', 'person', 'head', 'existing', 'body_clothes', 'not_faces')
EXTS = {'.png', '.webp', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.avif', '.jfif', '.jpe', '.gif'}
MODEL_NAME = 'selfie_multiclass_256x256.tflite'
MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/' + MODEL_NAME
MODEL_SHA256 = 'c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0'
ANIME_MODEL_NAME = 'anime-isnetis.onnx'
ANIME_MODEL_SHA256 = 'f15622d853e8260172812b657053460e20806f04b9e05147d49af7bed31a6e99'
ANIME_MODEL_URL = 'https://huggingface.co/skytnt/anime-seg/resolve/493cb60893f47441b26ec4fb9a306bce9e342982/isnetis.onnx'
MANIFEST = '.loss_masks.json'

def model_spec(source='photo'):
    if source == 'anime':
        return {'name': ANIME_MODEL_NAME, 'sha256': ANIME_MODEL_SHA256, 'url': ANIME_MODEL_URL,
                'generator': ANIME_MODEL_SHA256 + ':isnetis-1024-v1', 'dependency': 'onnxruntime', 'package': 'onnxruntime>=1.20,<2', 'size': '168 MiB', 'label': '二次元人物'}
    if source != 'photo': raise ValueError('图片类型需要选择二次元或真人。')
    return {'name': MODEL_NAME, 'sha256': MODEL_SHA256, 'url': MODEL_URL,
            'generator': MODEL_SHA256 + ':input-minus-one-v1', 'dependency': 'ai_edge_litert.interpreter', 'package': 'ai-edge-litert>=2.2,<3', 'size': '16 MB', 'label': '真人多类别'}

def source_type(params):
    source = str(params.get('mask_source') or 'photo')
    model_spec(source)
    return source


def is_mask_file(path):
    return Path(path).stem.casefold().endswith(SUFFIX)

def settings(params):
    mode = str(params.get('mask_mode') or 'off')
    source_type(params)
    if mode not in KINDS: raise ValueError('学习重点选项无效。')
    try: floor = float(params.get('mask_floor', .1))
    except (ValueError, TypeError): raise ValueError('背景参与程度需要为 0 到 1。') from None
    if not math.isfinite(floor) or not 0 <= floor <= 1: raise ValueError('背景参与程度需要为 0 到 1。')
    if mode != 'off' and (params.get('mode') not in MODES or params.get('fizgig_version') != 'v8.9.6' or params.get('training_kind') == 'slider'):
        raise ValueError('学习区域需要 Fizgig v8.9.6 普通图片 LoRA；请切换兼容版本，或把学习重点设为整张图片。')
    return mode, floor

def images(root):
    root = Path(root).resolve()
    result = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(n for n in dirs if not n.startswith('.') and not linked(Path(folder) / n))
        result.extend(Path(folder) / n for n in sorted(files) if Path(n).suffix.lower() in EXTS and not is_mask_file(n) and not linked(Path(folder) / n))
    return result

def linked(path):
    p = Path(path)
    return p.is_symlink() or getattr(p, 'is_junction', lambda: False)()

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''): h.update(chunk)
    return h.hexdigest()

def mask_for(image):
    image = Path(image)
    stem = (image.stem + SUFFIX).casefold()
    found = [p for p in image.parent.iterdir() if p.stem.casefold() == stem and p.suffix.lower() in EXTS and p.is_file() and not linked(p)]
    if len(found) > 1: raise ValueError('同一图片有多个遮罩，请只保留一个：' + image.name)
    return found[0] if found else None

def read_mask(path):
    from PIL import Image
    with Image.open(path) as image:
        image.load()
        if image.mode.startswith('I') or image.mode == 'F':
            import numpy as np
            a = np.asarray(image, dtype='float32')
            if float(a.max()) > 255: a = a / 257
            return Image.fromarray(np.clip(a, 0, 255).astype('uint8'), 'L')
        if 'A' in image.getbands() or 'transparency' in image.info:
            rgba = image.convert('RGBA')
            background = Image.new('RGBA', rgba.size, (0, 0, 0, 255))
            return Image.alpha_composite(background, rgba).convert('L')
        return image.convert('L')

def atomic_json(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.mask_', suffix='.part', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

def atomic_mask(path, image):
    path = Path(path)
    if linked(path): raise ValueError('遮罩不能写入链接。')
    fd, name = tempfile.mkstemp(prefix='.mask_', suffix='.part', dir=path.parent)
    os.close(fd)
    try:
        image.convert('L').save(name, format='PNG')
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

def manifest(root):
    path = Path(root) / MANIFEST
    if not path.is_file(): return {'schema': 1, 'images': {}}
    if linked(path): raise ValueError('遮罩记录不能是链接。')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') != 1 or not isinstance(data.get('images'), dict): raise ValueError('学习区域记录损坏，请从备份恢复。')
    return data

def remember(root, image, *, origin, kind='', decision=None, source='photo'):
    root, image = Path(root), Path(image)
    data = manifest(root); key = image.relative_to(root).as_posix()
    previous = data['images'].get(key, {})
    mask = mask_for(image)
    data['images'][key] = {**previous, 'image_sha256': digest(image), 'mask_sha256': digest(mask) if mask else '', 'origin': origin, 'kind': kind, 'generator': model_spec(source)['generator'] if origin == 'auto' else '', 'updated': time.time_ns()}
    if decision is not None:
        data['images'][key]['decision'] = decision
        data['images'][key]['decision_image_sha256'] = data['images'][key]['image_sha256']
    atomic_json(root / MANIFEST, data)

def inspect_one(image, record=None):
    from PIL import Image, ImageOps, ImageStat
    image = Path(image); record = record or {}
    info = {'name': image.name, 'status': 'missing', 'problem': '缺少学习区域', 'coverage': None, 'decision': record.get('decision', 'default'), 'origin': record.get('origin', 'existing'), 'kind': record.get('kind', ''), 'generator': record.get('generator', '')}
    info['image_sha256'] = digest(image)
    if record.get('decision_image_sha256') and record['decision_image_sha256'] != info['image_sha256']:
        info.update(decision='default', warning='图片已变化，原处理选择需要重新确认')
    try:
        path = mask_for(image)
        if path is None: return info
        info['mask_sha256'] = digest(path)
        # External edits are manual; preserve them, but still require geometry validation.
        manual_edit = record.get('mask_sha256') and record['mask_sha256'] != info['mask_sha256']
        mask = read_mask(path)
        with Image.open(image) as src: w, h = ImageOps.exif_transpose(src).size
        if abs((mask.width / mask.height) / (w / h) - 1) > .02: raise ValueError('遮罩与图片比例不一致')
        coverage = ImageStat.Stat(mask).mean[0] / 255
        info['coverage'] = round(coverage, 4)
        if coverage < .01: raise ValueError('遮罩接近全黑，没有可学习区域')
        stale = record.get('image_sha256') and record['image_sha256'] != info['image_sha256']
        if stale: raise ValueError('图片已改变，请重新生成或检查遮罩后重新保存')
        info.update(status='valid', problem='', origin='manual' if manual_edit else info['origin'])
        if coverage < .08: info['warning'] = '学习区域权重偏低，请确认不是仅识别出淡轮廓或小块区域'
        if coverage > .98: info['warning'] = '几乎覆盖整张图片，请确认是否符合预期'
    except Exception as exc:
        info.update(status='invalid', problem=str(exc))
    return info

def report(root, check_stop=lambda: None, kind=None, source='photo'):
    root = Path(root); data = manifest(root); rows = []
    for image in images(root):
        check_stop()
        key = image.relative_to(root).as_posix()
        record = data['images'].get(key, {})
        row = inspect_one(image, record); row['name'] = key
        if kind not in (None, 'off', 'existing') and row['origin'] == 'auto' and (record.get('kind') != kind or record.get('generator') != model_spec(source)['generator']):
            row.update(status='invalid', problem='学习重点或自动生成器已改变，请重新生成学习区域')
        rows.append(row)
    active = [r for r in rows if r['decision'] != 'exclude']
    issues = [r for r in active if r['status'] != 'valid' and r['decision'] != 'unmasked']
    identity = [{k: r.get(k) for k in ('name', 'image_sha256', 'mask_sha256', 'status', 'decision')} for r in rows]
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {'total': len(rows), 'valid': sum(r['status'] == 'valid' for r in active), 'issues': len(issues), 'excluded': len(rows)-len(active), 'unmasked': sum(r['decision'] == 'unmasked' for r in active), 'rows': rows, 'fingerprint': fingerprint}

def validate_report(result):
    if result['issues']:
        names = ', '.join(r['name'] for r in result['rows'] if r['decision'] not in ('exclude', 'unmasked') and r['status'] != 'valid')
        raise ValueError('有 %d 张学习区域需要检查：%s。请补生成、手动修正，或明确选择排除 / 整图学习。' % (result['issues'], names[:300]))

def preview(image, record=None):
    from PIL import Image, ImageOps
    result = inspect_one(image, record)
    try: path = mask_for(image)
    except ValueError: return result
    if not path: return result
    try:
        mask = read_mask(path)
        with Image.open(image) as src: original = ImageOps.exif_transpose(src).convert('RGB')
        mask = mask.resize(original.size)
        def url(im):
            im.thumbnail((1200, 1200)); b = io.BytesIO(); im.save(b, format='PNG')
            return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()
        tint = Image.new('RGB', original.size, (64, 204, 150))
        overlay = Image.composite(Image.blend(original, tint, .5), original, mask)
        raw = io.BytesIO(); mask.save(raw, format='PNG')
        result.update(mask_data_url=url(mask.copy()), overlay_data_url=url(overlay), mask_edit_data_url='data:image/png;base64,' + base64.b64encode(raw.getvalue()).decode())
    except Exception: pass  # The diagnostic above is shown next to the original.
    return result

def import_mask(source_image, output_image, *, border_box=None, crop_ratio='', crop_function=None):
    """Replay photo geometry on a raw sidecar, then save beside the managed copy."""
    from PIL import Image
    source, output = Path(source_image), Path(output_image)
    candidate = mask_for(source)
    if candidate is None: return
    # Existing manually edited destination always wins.
    current = mask_for(output)
    old = manifest(output.parent)['images'].get(output.name, {})
    if current and (old.get('origin') != 'auto' or digest(current) != old.get('mask_sha256')): return
    mask = read_mask(candidate)
    with Image.open(source) as raw:
        raw_size = raw.size; orientation = raw.getexif().get(274, 1)
    upright_size = raw_size[::-1] if orientation in (5, 6, 7, 8) else raw_size
    transpose = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_90}
    # Mask editors normally save upright pixels without the photo's EXIF flag.
    # Prefer that convention when dimensions are ambiguous (square/180 degrees).
    if mask.size == upright_size:
        pass
    elif mask.size == raw_size:
        if orientation in transpose: mask = mask.transpose(transpose[orientation])
    else:
        raise ValueError('原始遮罩尺寸必须与原图或其转正尺寸相同：' + source.name)
    if border_box: mask = mask.crop(border_box)
    if crop_ratio and crop_function: mask = crop_function(mask, crop_ratio)
    with Image.open(output) as processed: size = processed.size
    mask = mask.resize(size, Image.Resampling.BILINEAR)
    destination = output.with_name(output.stem + SUFFIX + '.png')
    if current and current != destination: raise ValueError('已有不同扩展名的遮罩，请先检查：' + current.name)
    atomic_mask(destination, mask)
    remember(output.parent, output, origin='import', kind='existing')

def related_images(root, image):
    """A multi-character sampling copy represents the same photo and decision."""
    root, image = Path(root), Path(image)
    path = root / 'multi_manifest.json'
    if not path.is_file() or linked(path): return [image]
    data = json.loads(path.read_text(encoding='utf-8'))
    for row in data.get('images', []):
        first = str(row.get('name') or '')
        if not first or Path(first).name != first: continue
        prefix = Path(first).stem.rsplit('_', 1)[0] + '_'
        if not image.stem.startswith(prefix): continue
        count = int(row.get('sampling_copies', 1))
        if not 1 <= count <= 64: raise ValueError('多角色均衡副本记录无效，请重新预处理。')
        expected = digest(image); result = []
        for i in range(count):
            item = root / (prefix + str(i) + '.png')
            if not item.is_file() or linked(item) or digest(item) != expected:
                raise ValueError('同一图片的均衡副本已改变，请重新预处理后检查。')
            result.append(item)
        return result
    return [image]

def sync_activation(root, enabled):
    """Keep inactive sidecars recoverable and out of legacy trainers/taggers."""
    root = Path(root).resolve()
    stash = root / '.inactive_loss_masks'
    if linked(stash): raise ValueError('遮罩备份目录不能是链接。')
    if enabled:
        if not stash.is_dir(): return
        candidates = [p for p in stash.rglob('*') if p.is_file() and is_mask_file(p) and not linked(p)]
        for source in candidates:
            if any(linked(p) for p in source.parents if p.is_relative_to(stash)): raise ValueError('遮罩备份路径不能是链接。')
            destination = root / source.relative_to(stash)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if digest(source) != digest(destination): raise ValueError('存在不同的活动与备份遮罩，请先检查：' + destination.name)
                continue
            source.rename(destination)
    else:
        candidates = []
        for folder, dirs, files in os.walk(root):
            dirs[:] = [n for n in dirs if not n.startswith('.') and not linked(Path(folder) / n)]
            candidates.extend(Path(folder) / n for n in files if is_mask_file(n) and Path(n).suffix.lower() in EXTS and not linked(Path(folder) / n))
        for source in candidates:
            # Includes orphaned sidecars: an old trainer must never see them as photos.
            destination = stash / source.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                previous = destination.with_name(destination.name + '.previous_' + str(time.time_ns()))
                destination.rename(previous)
            source.rename(destination)

def training_view(core, params, check_stop=lambda: None):
    """Freeze reviewed masks and explicit per-image choices into an isolated dataset."""
    mode, floor = settings(params)
    if mode == 'off': return None, None
    root = Path(core.dataset_train_dir('character', params['project'])).resolve()
    result = report(root, check_stop, kind=mode, source=source_type(params)); validate_report(result)
    parent = root.parent / 'mask_training'
    if linked(parent): raise ValueError('学习区域训练副本目录不能是链接。')
    parent.mkdir(exist_ok=True)
    captions = [(r['name'], digest((root / r['name']).with_suffix('.txt')) if (root / r['name']).with_suffix('.txt').is_file() else '') for r in result['rows'] if r['decision'] != 'exclude']
    key = hashlib.sha256(json.dumps([result['fingerprint'], captions], ensure_ascii=False).encode()).hexdigest()[:24]
    target = parent / ('reviewed_' + key)
    # Reuse only a complete snapshot whose copied files still match the reviewed sources.
    if target.is_dir() and not linked(target) and (target / '.reviewed_masks.json').is_file():
        expected_images = {r['name'] for r in result['rows'] if r['decision'] != 'exclude'}
        complete = {p.relative_to(target).as_posix() for p in images(target)} == expected_images
        for row in result['rows']:
            check_stop()
            if row['decision'] == 'exclude': continue
            dst = target / row['name']
            if not dst.is_file() or linked(dst) or digest(dst) != row['image_sha256']: complete = False; break
            if row['decision'] != 'unmasked' and row['status'] == 'valid':
                copied_mask = mask_for(dst)
                if not copied_mask or digest(copied_mask) != row.get('mask_sha256'): complete = False; break
            elif mask_for(dst): complete = False; break
            caption = dst.with_suffix('.txt'); original_caption = (root / row['name']).with_suffix('.txt')
            if original_caption.is_file() and (not caption.is_file() or linked(caption) or digest(caption) != digest(original_caption)): complete = False; break
        if complete: return str(target), {**result, 'mask_floor': floor, 'mask_mode': mode}
        target = parent / ('reviewed_' + key + '_' + str(time.time_ns()))
    stage = Path(tempfile.mkdtemp(prefix='.prepare_', dir=parent)).resolve()
    try:
        for row in result['rows']:
            check_stop()
            if row['decision'] == 'exclude': continue
            image = root / row['name']; dst = stage / row['name']; dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(image, dst)
            caption = image.with_suffix('.txt')
            if caption.is_file() and not linked(caption): shutil.copy2(caption, dst.with_suffix('.txt'))
            mask = mask_for(image)
            if row['decision'] != 'unmasked' and row['status'] == 'valid' and mask:
                shutil.copy2(mask, dst.with_name(dst.stem + SUFFIX + mask.suffix.lower()))
                if digest(dst.with_name(dst.stem + SUFFIX + mask.suffix.lower())) != row.get('mask_sha256'): raise ValueError('遮罩在准备训练时改变，请重新检查。')
            if digest(dst) != row['image_sha256']: raise ValueError('图片在准备训练时改变，请重新检查。')
        atomic_json(stage / '.reviewed_masks.json', {**result, 'mask_floor': floor, 'mask_mode': mode})
        check_stop(); stage.rename(target)
    finally:
        if stage.exists() and stage.parent == parent.resolve() and stage.name.startswith('.prepare_'): shutil.rmtree(stage)
    return str(target), {**result, 'mask_floor': floor, 'mask_mode': mode}
