"""CPU mask generation in the selected Fizgig environment (no GPU imports)."""
import argparse
import importlib.util
import os
import shutil
import time
from pathlib import Path
import sys

# Load pure Python helpers directly: the frozen app directory can contain DLLs
# from a different Python ABI and must never be added to the worker search path.
HERE = Path(__file__).resolve().parent
app_root = HERE.parent
if any(app_root.glob('python3*.dll')):
    sys.path[:] = [p for p in sys.path if os.path.normcase(os.path.abspath(p or os.getcwd())) != os.path.normcase(str(app_root))]
spec = importlib.util.spec_from_file_location('_kohya_loss_masks', HERE / 'loss_masks.py')
masks = importlib.util.module_from_spec(spec); spec.loader.exec_module(masks)

class PhotoSegmenter:
    """Pinned MediaPipe model: its embedded metadata specifies mean=std=127.5."""
    def __init__(self, path):
        from ai_edge_litert.interpreter import Interpreter
        self.it = Interpreter(model_path=str(path), num_threads=2)
        self.it.allocate_tensors()
        self.inp, self.out = self.it.get_input_details()[0], self.it.get_output_details()[0]
        self.h, self.w = int(self.inp['shape'][1]), int(self.inp['shape'][2])

    def mask(self, image, kind):
        import numpy as np
        from PIL import Image
        x = (np.asarray(image.resize((self.w, self.h), Image.Resampling.BILINEAR), dtype=np.float32) - 127.5) / 127.5
        self.it.set_tensor(self.inp['index'], x[None])
        self.it.invoke()
        y = self.it.get_tensor(self.out['index'])[0].astype(np.float32)
        if y.ndim != 3 or y.shape[-1] != 6: raise ValueError('真人分割模型输出形状不符。')
        if y.min() < 0 or y.max() > 1.0001:
            y = np.exp(y - y.max(-1, keepdims=True)); y /= y.sum(-1, keepdims=True)
        if kind == 'person': result = 1 - y[..., 0]
        elif kind == 'head': result = y[..., 1] + y[..., 3]
        elif kind == 'body_clothes': result = y[..., 2] + y[..., 4] + y[..., 5]
        elif kind == 'not_faces': result = 1 - y[..., 1] - y[..., 3]
        else: raise ValueError('真人自动识别区域无效。')
        return np.asarray(Image.fromarray(np.clip(result, 0, 1)).resize(image.size, Image.Resampling.BILINEAR))


class AnimeSegmenter:
    """SkyTNT ISNet ONNX: RGB/255, aspect-preserving central padding to 1024."""
    def __init__(self, path):
        import onnxruntime as ort
        options = ort.SessionOptions(); options.intra_op_num_threads = min(4, os.cpu_count() or 2)
        self.session = ort.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider'])
        self.input = self.session.get_inputs()[0]
        if self.input.shape != [1, 3, 1024, 1024]: raise ValueError('二次元分割模型输入形状不符。')

    def mask(self, image, kind):
        if kind != 'person': raise ValueError('二次元自动模型只支持人物整体；局部区域请手绘。')
        import numpy as np
        from PIL import Image
        width, height = image.size; size = 1024
        h, w = (size, max(1, int(size * width / height))) if height > width else (max(1, int(size * height / width)), size)
        top, left = (size-h)//2, (size-w)//2
        x = np.zeros((size, size, 3), dtype=np.float32)
        x[top:top+h, left:left+w] = np.asarray(image.resize((w,h), Image.Resampling.BILINEAR), dtype=np.float32) / 255
        y = self.session.run(None, {self.input.name: np.transpose(x, (2,0,1))[None]})[0]
        if y.shape != (1,1,size,size) or not np.isfinite(y).all(): raise ValueError('二次元分割输出无效。')
        y = np.clip(y[0,0,top:top+h,left:left+w], 0, 1)
        return np.asarray(Image.fromarray(y).resize(image.size, Image.Resampling.BILINEAR))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--kind', choices=masks.KINDS[1:], required=True)
    parser.add_argument('--mask-source', choices=('photo', 'anime'), default='photo')
    parser.add_argument('--overwrite-auto', action='store_true')
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if masks.linked(root): raise ValueError('训练目录不能是链接')
    items = masks.images(root)
    segmenter = None
    if args.kind != 'existing':
        model = Path(args.model)
        specification = masks.model_spec(args.mask_source)
        if not model.is_file() or masks.digest(model) != specification['sha256']: raise ValueError('分割模型校验失败，请重新下载。')
        segmenter = AnimeSegmenter(model) if args.mask_source == 'anime' else PhotoSegmenter(model)
    from PIL import Image, ImageOps
    generated = 0
    for index, image in enumerate(items):
        records = masks.manifest(root)['images']
        key = image.relative_to(root).as_posix(); record = records.get(key, {})
        info = masks.inspect_one(image, record)
        if info.get('decision') in ('exclude', 'unmasked'): continue
        path = masks.mask_for(image)
        untouched_auto = bool(path and record.get('origin') == 'auto' and masks.digest(path) == record.get('mask_sha256'))
        regenerate = untouched_auto and (args.overwrite_auto or record.get('kind') != args.kind or record.get('generator') != masks.model_spec(args.mask_source)['generator'] or info['status'] != 'valid')
        if path and not regenerate:
            print('[学习区域] %d/%d 保留已有遮罩：%s' % (index + 1, len(items), key), flush=True)
            continue
        if segmenter is None: continue
        try:
            with Image.open(image) as src: rgb = ImageOps.exif_transpose(src).convert('RGB')
            import numpy as np
            mask = segmenter.mask(rgb, args.kind)
            if not np.isfinite(mask).all(): raise ValueError('模型返回了无效的区域权重。')
            # Preserve an invalid/stale mask until there is a replacement to inspect.
            if float(np.asarray(mask).mean()) < .01:
                print('[学习区域] %s 未识别到足够人物区域，请检查或手绘。' % key, flush=True)
                continue
            result = Image.fromarray(np.clip(np.asarray(mask) * 255, 0, 255).astype('uint8'), 'L').resize(rgb.size, Image.Resampling.BILINEAR)
            destination = image.with_name(image.stem + masks.SUFFIX + '.png')
            if path and path != destination: raise ValueError('自动遮罩扩展名不一致，请检查现有文件。')
            if path:
                backup = root / '.mask_backups' / ('auto_' + str(time.time_ns())) / path.relative_to(root)
                if any(masks.linked(p) for p in (backup, *backup.parents) if p.is_relative_to(root)):
                    raise ValueError('遮罩备份目录不能是链接。')
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup)
            masks.atomic_mask(destination, result)
            masks.remember(root, image, origin='auto', kind=args.kind, source=args.mask_source)
            generated += 1
            print('[学习区域] %d/%d 已生成：%s' % (index + 1, len(items), key), flush=True)
        except Exception as exc:
            raise RuntimeError('生成失败：%s：%s；已完成的遮罩保留。' % (key, exc)) from exc
    result = masks.report(root, kind=args.kind, source=args.mask_source)
    print('[学习区域] 已生成 %d；格式检查通过 %d/%d，%d 张需要检查。自动分割结果请查看覆盖图确认。' % (generated, result['valid'], result['total'], result['issues']), flush=True)

if __name__ == '__main__': main()
