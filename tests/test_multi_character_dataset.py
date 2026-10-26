"""Exercise actual multi-character dataset/mask replacement, with no models or GPU."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from kohya_core import paths
from PIL import Image, PngImagePlugin
from kohya_core import loss_masks, multi_character
from kohya_core.image_io import ImageDecodeError


class MultiCharacterDatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config={'params':{'mask_mode':'existing','fizgig_version':'v8.9.6'}}
        self.custom_output=self.root/'custom-results'
        for target, value in [('data_dir', str(self.root/'data')), ('project_output_dir', str(self.custom_output))]:
            patcher=patch.object(paths,target,return_value=value);patcher.start();self.addCleanup(patcher.stop)
        self.core=SimpleNamespace(check_stop=lambda:None,
            data_sub=paths.data_sub,
            load_project=lambda _:self.config,
            project_output_dir=lambda _:str(self.custom_output))
        roles=[]
        for role in ('alice','betty'):
            directory=self.root/role;directory.mkdir()
            Image.new('RGB',(96,80),'red' if role=='alice' else 'blue').save(directory/'one.png')
            roles.append({'id':role,'name':role,'trigger':role+'_person','directory':str(directory),
                          'description':'a person in a white shirt'})
        self.settings={'roles':roles,'groups':[],'targets':[],'balance':True}
        self.target=Path(self.core.data_sub('dataset','project'))/'train_character'

    def prepare(self):
        return multi_character.prepare(self.core,'project',self.settings,128,lambda _:None,mode='moss_fz')

    def test_validation_files_follow_custom_output_directory(self):
        self.prepare()
        self.assertTrue((self.custom_output/'MOSS_多角色验证.jsonl').is_file())
        self.assertEqual(Path(self.core.data_sub('output','project')),self.custom_output)
        self.assertFalse((self.root/'data'/'output'/'project').exists())

    def test_recaption_preserves_manual_masks_and_review_decisions(self):
        self.prepare()
        manifest=json.loads((self.target/'multi_manifest.json').read_text(encoding='utf-8'))
        row=next(r for r in manifest['images'] if r['group_id']=='alice')
        image=self.target/row['name']
        mask=image.with_name(image.stem+loss_masks.SUFFIX+'.png')
        Image.new('L',(96,80),200).save(mask)
        loss_masks.remember(self.target,image,origin='manual',decision='default')
        expected=mask.read_bytes()
        source=self.root/'alice'/'one.png'
        source.with_suffix('.txt').write_text('alice_person, changed caption',encoding='utf-8')
        self.prepare()
        after=json.loads((self.target/'multi_manifest.json').read_text(encoding='utf-8'))
        name=next(r['name'] for r in after['images'] if r['group_id']=='alice')
        new=self.target/name
        self.assertNotEqual(new.name,image.name)
        self.assertEqual(loss_masks.mask_for(new).read_bytes(),expected)
        self.assertEqual(loss_masks.inspect_one(new,loss_masks.manifest(self.target)['images'][name])['status'],'valid')

    def test_failed_reprepare_keeps_existing_dataset_and_reports_all_bad_files(self):
        self.prepare()
        before={p.name:p.read_bytes() for p in self.target.iterdir() if p.is_file()}
        for role in ('alice','betty'):(self.root/role/'one.png').write_bytes(b'bad pixels')
        with self.assertRaises(ImageDecodeError):self.prepare()
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.target.iterdir() if p.is_file()})
        report=json.loads((self.target.parent/'image_normalization.json').read_text(encoding='utf-8'))
        self.assertEqual(len(report['errors']),2)
        self.assertFalse(list(self.target.parent.glob('.multi_prepare_*')))

    def test_imported_exif_mask_has_same_geometry_as_clean_training_image(self):
        path=self.root/'alice'/'rotated.jpg';exif=Image.Exif();exif[274]=6
        Image.new('RGB',(96,80),'green').save(path,exif=exif)
        mask=Image.new('L',(96,80),0);mask.paste(255,(0,0,48,80))
        mask.save(path.with_name(path.stem+loss_masks.SUFFIX+'.png'))
        self.prepare()
        manifest=json.loads((self.target/'multi_manifest.json').read_text(encoding='utf-8'))
        row=next(r for r in manifest['images'] if r['original_size']==[80,96])
        target=self.target/row['name']
        with Image.open(loss_masks.mask_for(target)) as result:
            self.assertEqual(result.size,(80,96))
            self.assertEqual(result.getpixel((40,20)),255)
            self.assertEqual(result.getpixel((40,75)),0)


if __name__=='__main__':unittest.main()
