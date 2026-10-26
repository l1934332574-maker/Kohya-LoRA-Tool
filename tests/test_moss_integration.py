"""MOSS project integration and version-preserving contracts (no GPU/network)."""
import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from kohya_core import configs, moss_models as models, fizgig_engine as engine, fizgig_adapter as adapter
from kohya_core.project_config import training_params
from kohya_core.model_catalog import resolve_choice
from gui.modern_host import ModernUIBridge
from model_downloader import ModelDownloader, DownloadError


def core_for(root):
    core = MagicMock()
    core.data_sub.side_effect = lambda *parts: str(Path(root).joinpath(*parts))
    core.get_kohya_dir.return_value = str(Path(root) / 'engine')
    core.preset_for.side_effect = lambda mode, arch: configs.PRESETS[mode][arch]
    core.normalize_crop_ratio.side_effect = lambda value: value
    core.detect_gpu_vendor.return_value = 'nvidia'
    core.MODE_KEYS = configs.MODE_KEYS
    core.PROJECT_TEMPLATES = configs.PROJECT_TEMPLATES
    core.PRESET_VERSION = configs.PRESET_VERSION
    core.BASE_TYPE_LABELS = {'sdxl':'SDXL'}
    core.MOSS_MODEL_LINKS = models.LINKS
    core.moss_models_dir.side_effect = lambda: models.models_dir(core)
    core.model_url_list.side_effect = lambda entry: entry[2]
    core.QUANT_MODE_OPTIONS = configs.QUANT_MODE_OPTIONS
    core.load_project.return_value = {'mode':'moss_fz','base_type':'sdxl','params':{},'moss_models':{}}
    core.save_project.return_value = True
    return core


class MossIntegrationTests(unittest.TestCase):
    def test_catalog_resolves_standard_moss_project(self):
        row = resolve_choice({'model':'moss_image','variant':'moss_base','engine':'fizgig'})
        self.assertEqual((row['mode'], row['min_version']), ('moss_fz','v8.5.0'))

    def test_new_version_does_not_change_existing_targets(self):
        self.assertEqual(engine.VERSION, 'v7.3.1')
        self.assertEqual(engine.SUPPORTED_V7[:2], ('v7.0.1','v7.3.1'))
        self.assertIn(engine.LATEST_VERSION, engine.SUPPORTED_V7)
        self.assertEqual(engine.target_version('moss_fz'), engine.LATEST_VERSION)
        self.assertEqual(engine.target_version('krea2_fz'), engine.LATEST_VERSION)
        self.assertIn('v8.5.0', engine.SUPPORTED_STANDARD)

    def test_moss_source_marker_checks_all_deployed_files(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)
            for name in engine.MOSS_REQUIRED:
                file = source / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text('fixture', encoding='utf-8')
            marker = source / '.kohya-fizgig-source.json'
            marker.write_text(json.dumps({'version': engine.MOSS_VERSION,
                'commit': engine.MOSS_COMMIT, 'adapter': 4,
                'files': {name: engine._sha(source / name) for name in engine.MOSS_REQUIRED}}), encoding='utf-8')
            self.assertEqual(engine.source_version(source), engine.MOSS_VERSION)
            (source / 'src/fizgig/modules/offloading.py').write_text('changed', encoding='utf-8')
            self.assertEqual(engine.source_version(source), '')

    def test_params_keep_components_and_preview_choice(self):
        with tempfile.TemporaryDirectory() as root:
            core = core_for(root)
            config = {'mode':'moss_fz','params':{'moss_preview_base':True}, 'moss_models':{'dit':'local.safetensors'}}
            got = training_params(core, config, 'moss-test')
            self.assertEqual(got['fizgig_version'], 'v8.5.0')
            self.assertEqual((got['rank'],got['alpha'],got['max_epochs'],got['resolution']), (16,16,50,512))
            self.assertEqual(got['moss_models'], config['moss_models'])
            self.assertTrue(got['moss_preview_base'])
            self.assertNotIn('sample_preview', got)

    def test_old_project_versions_stay_explicit(self):
        with tempfile.TemporaryDirectory() as root:
            core = core_for(root)
            for version in ('v6.5.0','v7.0.1','v7.3.1'):
                got = training_params(core, {'mode':'krea2_fz','params':{'fizgig_version':version}}, 'old')
                self.assertEqual(got['fizgig_version'], version)

    def test_component_settings_ignore_unknown_fields(self):
        self.assertEqual(models.settings({'moss_models':{'dit':' x ', 'unknown':'bad', 'te':None}}), {'dit':'x'})
        self.assertEqual(models.settings({'moss_models':[]} ), {})

    def test_text_shards_enumerate_every_file(self):
        files = models.component_files('model-00003-of-00004.safetensors')
        self.assertEqual(len(files),4)
        self.assertEqual(files[0].name,'model-00001-of-00004.safetensors')
        with self.assertRaises(ValueError): models.component_files('model-00001-of-99999.safetensors')

    def test_missing_shards_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            p = Path(root)/'model-00001-of-00002.safetensors';p.write_bytes(b'x')
            with self.assertRaisesRegex(ValueError, '分片不完整'):
                models.validate(p, 'te')

    def test_preview_requirement_respects_explicit_base_choice(self):
        state = {k:{'present': k != 'preview_checkpoint', 'error':''} for k in models.KEYS}
        with patch.object(models,'rows',return_value=state):
            self.assertEqual(models.missing(None, preview=False), [])
            self.assertEqual(len(models.missing(None, preview=True)), 1)
            self.assertEqual(models.missing(None, preview=True,base_preview=True), [])

    def test_model_list_exposes_local_selection(self):
        with tempfile.TemporaryDirectory() as root:
            core = core_for(root)
            bridge = ModernUIBridge(core)
            got = bridge.get_model_downloads('moss_fz','test')
            self.assertTrue(got['ok'])
            self.assertEqual(len(got['items']),4)
            self.assertTrue(all(row['local_select'] for row in got['items']))
            self.assertIn('Base',got['note'])

    def test_picker_cancel_preserves_settings(self):
        with tempfile.TemporaryDirectory() as root:
            core = core_for(root); bridge = ModernUIBridge(core)
            with patch.object(bridge,'_agent_guard',return_value=None), patch.object(bridge,'choose_path',return_value={'ok':True,'cancelled':True}):
                self.assertTrue(bridge.select_moss_component('test','dit')['cancelled'])
            core.save_project.assert_not_called()

    def test_picker_validation_precedes_save(self):
        with tempfile.TemporaryDirectory() as root:
            core = core_for(root); bridge = ModernUIBridge(core)
            with patch.object(bridge,'_agent_guard',return_value=None), patch.object(bridge,'choose_path',return_value={'ok':True,'path':str(Path(root)/'wrong.safetensors')}):
                result = bridge.select_moss_component('test','dit')
            self.assertFalse(result['ok'])
            core.save_project.assert_not_called()

    def test_picker_preserves_other_project_fields(self):
        with tempfile.TemporaryDirectory() as root:
            core = core_for(root); core.load_project.return_value.update(trigger='keep',moss_models={'te':'keep-te'})
            bridge = ModernUIBridge(core)
            with patch.object(bridge,'_agent_guard',return_value=None), patch.object(bridge,'choose_path',return_value={'ok':True,'path':str(Path(root)/'base.safetensors')}), patch('gui.modern_host.validate_moss_component'):
                self.assertTrue(bridge.select_moss_component('test','dit')['ok'])
            saved = core.save_project.call_args.args[1]
            self.assertEqual(saved['trigger'],'keep'); self.assertEqual(saved['moss_models']['te'],'keep-te')

    def test_preview_choice_saved_as_boolean(self):
        with tempfile.TemporaryDirectory() as root:
            core = core_for(root);bridge = ModernUIBridge(core)
            with patch.object(bridge,'_agent_guard',return_value=None),patch.object(bridge,'list_projects',return_value=[]):
                result = bridge.save_project_config('test',{'params':{'moss_preview_base':True}})
            self.assertTrue(result['ok'], result)
            self.assertIs(core.save_project.call_args.args[1]['params']['moss_preview_base'],True)

    def test_wrong_moss_version_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            core = core_for(root);bridge=ModernUIBridge(core)
            with patch.object(bridge,'_agent_guard',return_value=None):
                result=bridge.save_project_config('test',{'params':{'fizgig_version':'v7.3.1'}})
            self.assertFalse(result['ok']);core.save_project.assert_not_called()

    def test_new_project_pins_moss_version(self):
        with tempfile.TemporaryDirectory() as root:
            core = core_for(root);core.list_projects.return_value=[];bridge=ModernUIBridge(core)
            with patch.object(bridge,'_agent_guard',return_value=None),patch.object(bridge,'list_projects',return_value=[]):
                result=bridge.create_project('new-moss',model_choice={'model':'moss_image','variant':'moss_base','engine':'fizgig'})
            self.assertTrue(result['ok'],result)
            saved=core.save_project.call_args.args[1]
            self.assertEqual((saved['mode'],saved['params']['fizgig_version']),('moss_fz',engine.LATEST_VERSION))

    def test_download_fallback_completes_once(self):
        done=[]
        with tempfile.TemporaryDirectory() as root:
            task=ModelDownloader('https://first', str(Path(root)/'model.bin'),fallback_urls=['https://second'], done_cb=lambda *a:done.append(a),logf=None)
            attempts=[]
            def download():
                attempts.append(task.url)
                if len(attempts)==1: raise DownloadError('mirror unavailable')
            with patch.object(task,'_download',side_effect=download):task.run()
        self.assertEqual(attempts,['https://first','https://second']);self.assertEqual(len(done),1);self.assertTrue(done[0][0])

    def test_cancel_does_not_try_next_source(self):
        done=[]
        with tempfile.TemporaryDirectory() as root:
            task=ModelDownloader('https://first',str(Path(root)/'model.bin'),fallback_urls=['https://second'],done_cb=lambda *a:done.append(a),logf=None)
            def download():task.cancel();raise DownloadError('cancelled')
            with patch.object(task,'_download',side_effect=download) as download_mock:task.run()
            self.assertEqual(download_mock.call_count,1)
        self.assertFalse(done[0][0])

    def run_adapter(self, base_preview=False):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);core=core_for(root);image=root/'image.png';image.write_bytes(b'fixture');image.with_suffix('.txt').write_text('a blue-haired woman',encoding='utf-8')
            file=root/'weight.safetensors';file.write_bytes(b'fixture')
            core.MIN_IMAGES={'moss_fz':1};core.FIZGIG_IMAGE_EXTS={'.png'}
            core._fizgig_qwen_image_subsets.return_value=([(str(root),1,1)],[])
            core._sanitize_dirname.side_effect=lambda s:s or ''
            core._sample_preview_enabled.return_value=True;core._save_every_note.return_value=1;core._sample_seed.return_value=42;core._fizgig_sample_epochs.return_value=1
            core._fizgig_warmup_log_filter.side_effect=lambda fn:fn
            commands=[];core.run_stream.side_effect=lambda cmd,**kw:commands.append(cmd) or 0
            files={k:str(file) for k in models.KEYS};params={'project':'moss','moss_preview_base':base_preview}
            record={'version':engine.MOSS_VERSION,'source':str(root/'source'),'python':sys.executable}
            with patch.object(adapter,'source_version',return_value=engine.MOSS_VERSION),patch.object(adapter,'models',return_value=files),patch.object(adapter,'_validate'),patch.object(adapter,'_env',return_value={}),patch.object(adapter,'_helper_configs',return_value=None),patch.object(models,'missing',return_value=[]),patch.object(models,'validate'):
                adapter.train_lora(core,record,lambda s:None,'moss_fz',params,8,None,None)
            return commands[-1]

    def test_moss_sampling_uses_sft_and_official_settings(self):
        cmd=self.run_adapter()
        self.assertEqual(cmd[cmd.index('--sample_steps')+1],'30')
        self.assertEqual(cmd[cmd.index('--sample_cfg_scale')+1],'4.0')
        self.assertIn('--preview_checkpoint',cmd)
        self.assertEqual(cmd[cmd.index('--family')+1],'moss_image')

    def test_explicit_base_preview_omits_sft_switch(self):
        self.assertNotIn('--preview_checkpoint',self.run_adapter(True))

class MossStructureTests(unittest.TestCase):
    def check_header(self, header, kind, quant=None):
        with patch('kohya_core.h3_models._header', return_value=(header, quant or {})):
            return models._validated.__wrapped__((("base.safetensors", 1, 1, 1),), kind)

    def dit_header(self):
        shape = lambda x: {"shape": x, "dtype": "BF16"}
        result = {"video_embedder.weight": shape([3072,128]),
                  "final_linear_video.weight": shape([128,3072]),
                  "text_embedder.proj.weight": shape([3072,4096])}
        result.update({f"layers.{i}.proj.qkv.weight": shape([9216,3072]) for i in range(42)})
        return result

    def test_complete_dit_and_quantized_training_rejection(self):
        header = self.dit_header()
        self.check_header(header, 'dit')
        header['layers.10.proj.qkv.weight']['dtype'] = 'I8'
        with self.assertRaisesRegex(ValueError, 'BF16'): self.check_header(header, 'dit')
        del header['layers.10.proj.qkv.weight']
        with self.assertRaisesRegex(ValueError, '42'): self.check_header(header, 'dit')

    def test_sft_quant_descriptor_is_checked(self):
        header = self.dit_header()
        self.check_header(header, 'preview_checkpoint', {'x':{'format':'int8_tensorwise'}})
        with self.assertRaisesRegex(ValueError, 'int8 ConvRot'):
            self.check_header(header, 'preview_checkpoint', {'x':{'format':'nvfp4'}})

    def test_small_and_full_flux2_vae(self):
        for channels in (384,512):
            self.check_header({'encoder.conv_in.weight':{'shape':[128,3,3,3]},
                'decoder.conv_in.weight':{'shape':[channels,32,3,3]}, 'bn.running_mean':{'shape':[128]}}, 'vae')
        with self.assertRaisesRegex(ValueError, 'FLUX.2'): self.check_header({}, 'vae')

    def test_text_cache_changes_if_any_shard_changes(self):
        with tempfile.TemporaryDirectory() as root:
            core = core_for(root);core.FIZGIG_IMAGE_EXTS={'.png'}
            shards = [Path(root)/f'model-{i:05d}-of-00002.safetensors' for i in (1,2)]
            for shard in shards: shard.write_bytes(b'x')
            assets={'te':str(shards[0])}
            first = adapter._cache_identity(core,'moss_image',assets,[],512)[0]
            shards[1].write_bytes(b'xx')
            self.assertNotEqual(first, adapter._cache_identity(core,'moss_image',assets,[],512)[0])

    def test_preview_disabled_does_not_require_sft_download(self):
        with tempfile.TemporaryDirectory() as root:
            core=core_for(root);core._sample_preview_enabled.return_value=False
            bridge=ModernUIBridge(core)
            items=bridge.get_model_downloads('moss_fz','test')['items']
            self.assertFalse(next(i for i in items if i['key']=='preview_checkpoint')['required'])

    def test_preflight_reports_missing_sft_before_preprocessing(self):
        with tempfile.TemporaryDirectory() as root:
            core=core_for(root);bridge=ModernUIBridge(core)
            params={'raw_dir':root,'moss_models':{},'fizgig_version':'v8.5.0'}
            with patch.object(bridge,'_classic_training_params',return_value=params), patch.object(bridge,'get_mode_workspace',return_value={'engine_ready':True,'missing_models':[]}), patch('gui.modern_host.moss_missing',return_value=['missing SFT']):
                result=bridge._prepare_engine_training('test',{'mode':'moss_fz'})
            self.assertEqual(result, {'ok':False,'error':'missing SFT'})

    def test_finished_new_snapshot_does_not_offer_older_state(self):
        from tests.test_anima_component_integrity import legacy
        with tempfile.TemporaryDirectory() as root:
            out=Path(root);name='moss_image_lora'
            for epoch in (1,2):
                state=out/'snapshots/fizgig-v8.5.0'/f'{name}-{epoch:06d}-state';state.mkdir(parents=True)
                for f in ('lora.safetensors','optimizer.pt','rng.pt'): (state/f).write_bytes(b'fixture')
                meta={'epoch':epoch,'global_step':epoch*3,'kohya_complete':epoch==2,
                      'kohya_runtime':{'version':'v8.5.0','family':'moss_image'}}
                (state/'training_state.json').write_text(json.dumps(meta),encoding='utf-8')
                for f in state.iterdir(): os.utime(f,(100+epoch,100+epoch))
            self.assertIsNone(legacy.find_fizgig_state(root,name,'v8.5.0','moss_image',2))
            self.assertEqual(legacy.find_fizgig_state(root,name,'v8.5.0','moss_image',3),str(state))
            self.assertIsNone(legacy.find_fizgig_state(root,name,'v7.3.1','moss_image',3))


if __name__=='__main__':unittest.main()
