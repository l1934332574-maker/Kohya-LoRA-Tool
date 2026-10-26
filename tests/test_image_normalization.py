"""Real pixels and CLI regressions; fixtures never touch installed/user datasets."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin
from kohya_core import image_io
import preprocess

ROOT = Path(__file__).resolve().parents[1]


class ImageNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_clean_png_strips_metadata_and_preserves_pixels(self):
        source = self.root / 'source.png'
        meta = PngImagePlugin.PngInfo()
        meta.add_text('untrusted', 'metadata fixture')
        Image.new('RGBA', (96, 80), (20, 80, 140, 128)).save(source, pnginfo=meta)
        before = source.read_bytes()
        output = self.root / 'normalized.png'
        with image_io.read_image(source, alpha_background=(255, 255, 255)) as pixels:
            expected = pixels.tobytes()
            image_io.save_normalized_png(pixels, output)
        with Image.open(output) as result:
            result.load()
            self.assertEqual(result.mode, 'RGB')
            self.assertEqual(result.tobytes(), expected)
            self.assertNotIn('untrusted', result.info)
            self.assertFalse(result.getexif())
        self.assertEqual(source.read_bytes(), before)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows WIC codec')
    def test_real_windows_codec_preserves_alpha_and_exif_geometry(self):
        for kind in ('alpha', 'exif'):
            with self.subTest(kind=kind):
                path = self.root / (kind + ('.png' if kind == 'alpha' else '.jpg'))
                if kind == 'alpha':
                    Image.new('RGBA', (96, 80), (20, 80, 140, 0)).save(path)
                else:
                    exif = Image.Exif(); exif[274] = 6
                    Image.new('RGB', (96, 80), (20, 80, 140)).save(path, exif=exif)
                before = path.read_bytes()
                with image_io._windows_decode(path, pixel_limit=10000) as recovered:
                    with image_io._normalize_pixels(recovered, preserve_alpha=False,
                            alpha_background=(255,255,255), max_pixels=10000) as output:
                        self.assertEqual(output.size, (96,80) if kind == 'alpha' else (80,96))
                        if kind == 'alpha': self.assertEqual(output.getpixel((0,0)), (255,255,255))
                self.assertEqual(path.read_bytes(), before)

    def test_environment_failure_never_attempts_recovery(self):
        path = self.root / 'source.png'; Image.new('RGB',(96,80)).save(path)
        with patch('PIL.Image.open', side_effect=ModuleNotFoundError("missing", name='fractions')), \
                patch.object(image_io, '_windows_decode') as recovery:
            with self.assertRaises(image_io.ImageEnvironmentError): image_io.read_image(path)
        recovery.assert_not_called()

    def test_pixel_limit_does_not_attempt_recovery(self):
        path = self.root / 'source.png'; Image.new('RGB',(96,80)).save(path)
        with patch.object(image_io, '_windows_decode') as recovery:
            with self.assertRaises(image_io.ImageDecodeError): image_io.read_image(path, max_pixels=100)
        recovery.assert_not_called()

    def cli(self, inputs, outputs, *extra):
        return subprocess.run([sys.executable,'-B',str(ROOT/'preprocess.py'),
            '--input',str(inputs),'--output',str(outputs),'--size','160','--mode','character',
            '--no-wd14','--keep-user-captions','--no-remove-watermark','--no-remove-black-borders',
            '--no-write-dataset-config',*extra], cwd=self.root,
            env=dict(os.environ, PYTHONIOENCODING='utf-8'), capture_output=True,
            text=True, encoding='utf-8',errors='replace',timeout=60)

    def test_cli_converts_formats_keeps_captions_and_collision_outputs(self):
        inputs=self.root/'input';inputs.mkdir();outputs=self.root/'output'
        for name,mode,color in [('same.jpg','RGB','red'),('same.png','RGBA',(0,0,255,0)),
                                ('palette.png','P',0),('wrong_extension.png','RGB','green')]:
            image=Image.new(mode,(160,128),color)
            if mode=='P':image.putpalette([0,0,255]+[0]*765)
            image.save(inputs/name,format='JPEG' if name=='wrong_extension.png' else None)
            (inputs/Path(name).with_suffix('.txt')).write_text('kept caption\n',encoding='utf-8')
        hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()}
        result=self.cli(inputs,outputs)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        generated=list(outputs.glob('*.png'))
        self.assertEqual(len(generated),4,[p.name for p in outputs.iterdir()])
        for path in generated:
            with Image.open(path) as image:
                image.load();self.assertEqual(image.mode,'RGB');self.assertEqual(image.format,'PNG')
            self.assertEqual(path.with_suffix('.txt').read_text(encoding='utf-8'),'kept caption\n')
        self.assertEqual(hashes,{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs.iterdir()})

    def test_cli_reports_all_bad_files_without_moving_sources_or_outputs(self):
        inputs=self.root/'input';inputs.mkdir();outputs=self.root/'output';outputs.mkdir()
        (outputs/'existing.txt').write_text('keep')
        for index in range(3): (inputs/f'bad{index}.png').write_bytes(b'not image')
        result=self.cli(inputs,outputs)
        self.assertNotEqual(result.returncode,0)
        report=json.loads((outputs/'image_normalization.json').read_text(encoding='utf-8'))
        self.assertEqual(len(report['errors']),3)
        self.assertEqual(len(list(inputs.glob('*.png'))),3)
        self.assertEqual((outputs/'existing.txt').read_text(),'keep')
        self.assertFalse(inputs.with_name('input_corrupt').exists())

    def test_same_directory_is_rejected_before_modifying_source(self):
        Image.new('RGB',(160,128)).save(self.root/'source.png')
        before=(self.root/'source.png').read_bytes()
        result=self.cli(self.root,self.root)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((self.root/'source.png').read_bytes(),before)


if __name__=='__main__': unittest.main()
