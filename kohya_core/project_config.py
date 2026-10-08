"""Saved project parameter contract shared by the desktop UI and training queue."""
from pathlib import Path


WORKSPACE_PARAM_KEYS = (
    'fizgig_version', 'rank', 'alpha', 'unet_lr', 'te_lr', 'repeats', 'max_epochs', 'resolution',
    'save_every', 'sample_interval', 'sample_seed', 'video_steps', 'video_frames', 'optimizer',
    'strong_bind', 'clean_concept', 'sample_preview', 'compile', 'crop_ratio',
    'sample_prompt', 'noise_offset', 'min_snr_gamma', 'quant_mode', 'blocks_to_swap',
    'fizgig_qwen_preset', 'wd14_model', 'overwrite', 'keep_user_captions', 'amd_mode',
    'batch_size', 'gc', 'global_pos', 'global_neg',
    'caption_method', 'caption_language', 'caption_length',
)
BOOL_PARAM_KEYS = frozenset(('strong_bind', 'clean_concept', 'sample_preview',
                            'compile', 'overwrite', 'keep_user_captions', 'amd_mode'))


def training_params(core, config, project_name):
    if config.get('training_kind') == 'slider':
        from .slider_project import parameters
        return parameters(config, project_name)
    mode = str(config.get('mode') or 'character')
    base_type = str(config.get('base_type') or 'sdxl')
    stored = config.get('params') if isinstance(config.get('params'), dict) else {}
    preset = dict(core.preset_for(mode, base_type) or {})

    def value(key, default=None):
        candidate = stored.get(key)
        return preset.get(key, default) if candidate in (None, '') else candidate

    def integer(key, default):
        try:
            return int(float(value(key, default)))
        except (TypeError, ValueError, OverflowError):
            return default

    if mode.endswith('_fz'):
        params_version = str(stored.get('fizgig_version') or ('v7.0.1' if mode in ('anima_fz', 'sdxl_fz') else 'v6.5.0'))
    else:
        params_version = ''
    kohya = mode in ('character', 'style', 'concept')
    ai_image = mode in ('qwen_image', 'zimage')
    small_rank = mode in ('qwen21_fz', 'h3_fz')
    rank_default = 12 if kohya else 16 if ai_image else 8 if small_rank else 32
    epoch_default = 8 if kohya else 20 if ai_image else 50 if mode == 'h3_fz' else 30 if mode == 'qwen21_fz' else 16
    params = {
        'fizgig_version': params_version,
        'mode': mode, 'base_type': base_type, 'project': project_name,
        'at_sub_mode': str(config.get('at_sub_mode') or 'character'),
        'concept_type': str(config.get('concept_type') or 'form'),
        'fast_tier': str(config.get('fast_tier') or 'auto'),
        'trigger': str(config.get('trigger') or '').strip(),
        'raw_dir': str(config.get('raw_dir') or '').strip(),
        'reg_dir': str(config.get('reg_dir') or '').strip() or None,
        'base_model': str(config.get('base_model') or '').strip() or None,
        'style_preset': str(config.get('style_preset') or '自定义'),
        'style_caption': str(config.get('style_caption') or '').strip(),
        'train_env': str(config.get('train_env') or '').strip() or None,
        'train_text_encoder': not bool(config.get('unet_only', False)),
        'rank': integer('rank', rank_default),
        'alpha': integer('alpha', 6 if kohya else rank_default),
        'repeats': integer('repeats', 5 if kohya else 1),
        'max_epochs': integer('max_epochs', epoch_default),
        'resolution': integer('resolution', 512),
        'video_steps': integer('video_steps', 2000),
        'video_frames': integer('video_frames', getattr(core, 'H3_FRAMES', 73)),
        'batch_size': integer('batch_size', 1),
        'sample_interval': integer('sample_interval', 0),
        'sample_seed': str(value('sample_seed', 1234)),
        'unet_lr': str(value('unet_lr', '3e-4' if kohya else '1e-4')),
        'te_lr': str(value('te_lr', '1.5e-4' if kohya else '1e-4')),
        'crop_ratio': core.normalize_crop_ratio(value('crop_ratio', '')),
    }
    for key in ('optimizer', 'quant_mode', 'gc', 'fizgig_qwen_preset'):
        params[key] = str(value(key, 'auto') or 'auto')
    for key in ('sample_prompt', 'blocks_to_swap', 'noise_offset', 'min_snr_gamma'):
        params[key] = value(key, '')
    params['caption_method'] = str(value('caption_method', 'wd14'))
    params['caption_language'] = str(value('caption_language', 'zh'))
    params['caption_length'] = str(value('caption_length', 'brief'))
    params['wd14_model'] = str(value('wd14_model', 'swinv2-v3') or 'swinv2-v3')
    for key in BOOL_PARAM_KEYS - {'sample_preview'}:
        params[key] = bool(value(key, key in ('strong_bind', 'clean_concept')))
    if params['caption_method'] == 'natural':
        params['strong_bind'] = False
        params['clean_concept'] = False
        params['keep_user_captions'] = True
    elif params['caption_method'] == 'existing':
        params['keep_user_captions'] = True
        params['strong_bind'] = False
        params['clean_concept'] = False
    # An absent sampling choice must retain the engine's automatic policy.
    if stored.get('sample_preview') is not None:
        params['sample_preview'] = bool(stored['sample_preview'])
    save_every = integer('save_every', 0)
    params['save_every'] = save_every if save_every > 0 else None
    for key in ('global_pos', 'global_neg'):
        params[key] = str(config.get(key) or stored.get(key) or '').strip()
    return params


def dataset_images(directory):
    """Match the preprocessor's root-first scan without following image or directory links."""
    from preprocess import IMAGE_EXTS
    root = Path(directory)
    if not root.is_dir():
        raise OSError("图片文件夹不存在。")
    images = [path for path in root.iterdir() if path.is_file() and not path.is_symlink() and path.suffix.lower() in IMAGE_EXTS]
    if not images:
        import os
        errors = []
        for folder, dirs, files in os.walk(root, onerror=errors.append):
            parent = Path(folder)
            dirs[:] = [name for name in dirs if not name.startswith('.') and not (parent / name).is_symlink()]
            images.extend(parent / name for name in files if (parent / name).is_file() and not (parent / name).is_symlink() and Path(name).suffix.lower() in IMAGE_EXTS)
        if errors:
            raise errors[0]
    return sorted(images, key=lambda path: path.relative_to(root).as_posix().casefold())


def read_caption(image):
    caption = Path(image).with_suffix('.txt')
    if caption.is_symlink():
        return ''
    with caption.open('rb') as handle:
        content = handle.read(65536)
    encoding = 'utf-16' if content.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    return content.decode(encoding, errors='replace').strip()


def caption_summary(directory, images=None):
    """Read sidecar availability without changing images or caption files."""
    try:
        images = dataset_images(directory) if images is None else images
    except OSError as exc:
        return {'ok': False, 'error': '无法检查图片文件夹：%s' % exc}
    nonempty = empty = 0
    for image in images:
        try:
            content = read_caption(image)
        except OSError:
            continue
        if content:
            nonempty += 1
        else:
            empty += 1
    count = len(images)
    return {'ok': True, 'images': count, 'captioned': nonempty,
            'empty_captions': empty, 'missing_captions': count - nonempty - empty,
            'keep_user_captions': count >= 2 and nonempty / count >= .6}
