"""Standalone RAM++ keyword worker; one model load per image folder."""
from __future__ import annotations

import json
from pathlib import Path
import sys


def main():
    import torch
    from PIL import Image, ImageOps
    from torchvision.transforms import Compose, Normalize, Resize, ToTensor

    job = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    root = Path(job['model'])
    # Only the pinned inference modules are provided. Namespace packages avoid
    # importing upstream training, captioning and open-set CLIP dependencies.
    sys.path.insert(0, str(root / 'source'))
    from ram.models.ram_plus import RAM_plus

    torch.set_num_threads(max(1, min(torch.get_num_threads(), 8)))
    model = RAM_plus(image_size=384, vit='swin_l', text_encoder_type=str(root / 'tokenizer'), stage='eval')
    checkpoint = torch.load(root / job['checkpoint'], map_location='cpu', weights_only=True)
    state = checkpoint['model']
    for key in list(state):
        if 'relative_position_index' in key or 'attn_mask' in key:
            del state[key]
        elif 'vision_multi' in key:
            state[key.replace('vision_multi', 'tagging_head')] = state.pop(key)
    loaded = model.load_state_dict(state, strict=False)
    missing_parameters = set(loaded.missing_keys) & {name for name, _ in model.named_parameters()}
    # The SHA-verified official checkpoint omits this scalar. Upstream's
    # strict=False loader retains RAM_plus.__init__'s log(1 / 0.07), which
    # generate_tag uses for description reweighting. Keep that exact default;
    # all other missing inference parameters must still fail explicitly.
    if 'reweight_scale' in missing_parameters:
        missing_parameters.remove('reweight_scale')
        print('[RAM++] 官方权重未提供 reweight_scale，沿用模型自带默认值。', flush=True)
    if missing_parameters:
        raise RuntimeError('RAM++ checkpoint is missing inference parameters: ' + ', '.join(sorted(missing_parameters)[:5]))
    del checkpoint, state
    # Preserve official per-tag thresholds at the default 0.68 control value.
    delta = float(job['threshold']) - .68
    model.class_threshold = (model.class_threshold + delta).clamp(.01, .99)
    device = 'cuda' if job['device'] == 'auto' and torch.cuda.is_available() else 'cpu'
    try:
        model = model.to(device).eval()
    except RuntimeError:
        if device != 'cuda':
            raise
        model = model.to('cpu').eval()
        torch.cuda.empty_cache()
        device = 'cpu'
        print('[RAM++] GPU 加载失败，使用 CPU。', flush=True)
    print('[RAM++] 模型已加载（%s），输出%s关键词。' % (device.upper(), '中文' if job['language'] == 'zh' else '英文'), flush=True)
    transform = Compose([Resize((384, 384)), ToTensor(), Normalize([.485, .456, .406], [.229, .224, .225])])
    for index, name in enumerate(job['images']):
        path = Path(name)
        item = {'index': index}
        try:
            before = [path.stat().st_size, path.stat().st_mtime_ns]
            with Image.open(path) as original:
                original.load()
                frame = ImageOps.exif_transpose(original).convert('RGBA')
                background = Image.new('RGBA', frame.size, (255, 255, 255, 255))
                frame = Image.alpha_composite(background, frame).convert('RGB')
                inputs = transform(frame).unsqueeze(0)
            def infer():
                with torch.inference_mode():
                    return model.generate_tag(inputs.to(device))
            try:
                english, chinese = infer()
            except RuntimeError:
                if device != 'cuda':
                    raise
                model = model.to('cpu').eval()
                torch.cuda.empty_cache()
                device = 'cpu'
                print('[RAM++] GPU 推理失败，继续使用 CPU；模型保持加载。', flush=True)
                english, chinese = infer()
            tags = (chinese if job['language'] == 'zh' else english)[0]
            text = ', '.join(dict.fromkeys(tag.strip() for tag in tags.split('|') if tag.strip()))
            if before != [path.stat().st_size, path.stat().st_mtime_ns]:
                raise ValueError('打标期间图片已修改，请重新生成。')
            if not text:
                raise ValueError('未识别出关键词，请降低阈值后重试。')
            if len(text) > 8192:
                raise ValueError('关键词超过导出长度，请提高阈值后重试。')
            item.update(status='generated', caption=text, image_signature=before)
        except ModuleNotFoundError as exc:
            missing = str(getattr(exc, 'name', '') or '')
            message = ('当前 Python 运行环境缺少标准库 fractions；这是环境问题，不是图片损坏。'
                       if missing == 'fractions' else '图片解码环境缺少模块：' + (missing or '未知模块'))
            item.update(status='failed', error=message)
        except ImportError as exc:
            item.update(status='failed', error='图片解码环境无法加载依赖：' + str(exc)[:220])
        except (OSError, ValueError) as exc:
            item.update(status='failed', error=str(exc)[:300])
        print('[RAM_RESULT] ' + json.dumps(item, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
