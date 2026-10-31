import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from kohya_core import moss_layout
from kohya_core.lr_schedule import command, resolve, yaml_config, guard_resume
from kohya_core.prompt_reverse import export_report, result_item
from kohya_core.captioning import CaptionError


def draft():
    return {'width':800,'height':600,'bbox_coord_space':'abs','bbox_format':'xyxy',
            'summary':{'caption':'anime style'},
            'items':[{'label':'character','caption':'girl','bbox':[200,100,600,500]}]}

class MossLayoutTests(unittest.TestCase):
    def test_transform_and_trigger(self):
        result=json.loads(moss_layout.transform(json.dumps(draft()),(800,600),(100,0,700,600),(512,512),'trigger'))
        self.assertEqual(result['items'][0]['bbox'],[-171,-171,171,171])
        self.assertTrue(result['summary']['caption'].startswith('trigger'))
        self.assertEqual(result['bbox_format'],'yxyx')
    def test_invalid_local_model_layout_reports_image_error(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from kohya_core.qwen_vl_caption import _caption_images
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); image = root / 'one.png'
            Image.new('RGB', (32, 32), 'white').save(image)
            selection = {'images':[image], 'root':root, 'language':'zh', 'length':'brief', 'output_format':'moss_layout'}
            report = {'total':1, 'items':[], 'generated':0, 'failed':0}
            core = SimpleNamespace(check_stop=lambda: None)
            process = SimpleNamespace(poll=lambda: None)
            with patch('kohya_core.qwen_vl_caption.describe_image', return_value='{not valid json'):
                _caption_images(core, selection, {}, process, report, lambda _: None, lambda *_: None, lambda _: None)
            self.assertEqual(report['failed'], 1)
            self.assertEqual(report['items'][0]['status'], 'failed')
            self.assertTrue(report['items'][0]['error'])

    def test_local_detailed_description_has_room_for_complex_images(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from kohya_core.qwen_vl_caption import _caption_images
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); image = root / 'complex.png'; Image.new('RGB', (32, 32)).save(image)
            selection = {'images':[image], 'root':root, 'language':'zh', 'length':'detailed', 'output_format':'text'}
            report = {'total':1,'items':[],'generated':0,'failed':0}
            limits = []
            def respond(url, payload, key, stop, timeout=90):
                limits.append(payload['max_tokens'])
                choice = {'finish_reason':'stop' if payload['max_tokens'] == -1 else 'length','message':{'content':'完整的复杂画面描述'}}
                return {'choices':[choice]}
            service = {'provider':'compatible','base_url':'http://127.0.0.1/v1','model':'test','api_key':''}
            with patch('kohya_core.captioning._post', side_effect=respond):
                _caption_images(SimpleNamespace(check_stop=lambda:None), selection, service, SimpleNamespace(poll=lambda:None), report, lambda _:None, lambda *_:None, lambda _:None)
            self.assertEqual(limits[0],-1)
            self.assertEqual(report['generated'],1)

    def test_local_moss_layout_has_no_artificial_generation_limit(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from kohya_core.qwen_vl_caption import _caption_images
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); image = root / 'complex.png'; Image.new('RGB',(800,600)).save(image)
            selection = {'images':[image], 'root':root, 'language':'zh', 'length':'brief', 'output_format':'moss_layout'}
            report = {'total':1,'items':[],'generated':0,'failed':0}; limits=[]
            def respond(url,payload,key,stop,timeout=90):
                limits.append(payload['max_tokens'])
                return {'choices':[{'finish_reason':'stop' if payload['max_tokens'] == -1 else 'length','message':{'content':json.dumps(draft())}}]}
            service = {'provider':'compatible','base_url':'http://127.0.0.1/v1','model':'test','api_key':''}
            with patch('kohya_core.captioning._post',side_effect=respond):
                _caption_images(SimpleNamespace(check_stop=lambda:None),selection,service,SimpleNamespace(poll=lambda:None),report,lambda _:None,lambda *_:None,lambda _:None)
            self.assertEqual(limits,[-1]); self.assertEqual(report['generated'],1)

    def test_local_context_exhaustion_is_reported_as_incomplete(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from kohya_core.qwen_vl_caption import _caption_images
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);image=root/'complex.png';Image.new('RGB',(32,32)).save(image)
            selection={'images':[image],'root':root,'language':'zh','length':'brief','output_format':'moss_layout'}
            report={'total':1,'items':[],'generated':0,'failed':0}
            service={'provider':'compatible','base_url':'http://127.0.0.1/v1','model':'test','api_key':''}
            response={'choices':[{'finish_reason':'length','message':{'content':'incomplete'}}]}
            with patch('kohya_core.captioning._post',return_value=response):
                _caption_images(SimpleNamespace(check_stop=lambda:None),selection,service,SimpleNamespace(poll=lambda:None),report,lambda _:None,lambda *_:None,lambda _:None)
            self.assertEqual(report['generated'],0); self.assertEqual(report['failed'],1)
            self.assertIn('上下文',report['items'][0]['error'])

    def test_local_moss_requests_constrained_layout_schema(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from kohya_core.qwen_vl_caption import _caption_images
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); image=root/'complex.png'; Image.new('RGB',(800,600)).save(image)
            selection={'images':[image],'root':root,'language':'en','length':'brief','output_format':'moss_layout'}
            report={'total':1,'items':[],'generated':0,'failed':0}; payloads=[]
            service={'provider':'compatible','base_url':'http://127.0.0.1/v1','model':'test','api_key':''}
            def respond(url,payload,key,stop,timeout=90):
                payloads.append(payload)
                return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(draft())}}]}
            with patch('kohya_core.captioning._post',side_effect=respond):
                _caption_images(SimpleNamespace(check_stop=lambda:None),selection,service,SimpleNamespace(poll=lambda:None),report,lambda _:None,lambda *_:None,lambda _:None)
            self.assertEqual(payloads[0]['response_format']['type'],'json_object')
            schema=payloads[0]['response_format']['schema']
            self.assertEqual(schema['properties']['width']['const'],800)
            self.assertEqual(schema['properties']['height']['const'],600)
            self.assertEqual(report['generated'],1)

    def test_layout_region_limit_is_disclosed(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from kohya_core.qwen_vl_caption import _caption_images
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);image=root/'complex.png';Image.new('RGB',(800,600)).save(image)
            value=draft();value['items']=value['items'] * 16
            selection={'images':[image],'root':root,'language':'en','length':'brief','output_format':'moss_layout'}
            report={'total':1,'items':[],'generated':0,'failed':0}
            with patch('kohya_core.qwen_vl_caption.describe_image',return_value=json.dumps(value)):
                _caption_images(SimpleNamespace(check_stop=lambda:None),selection,{},SimpleNamespace(poll=lambda:None),report,lambda _:None,lambda *_:None,lambda _:None)
            self.assertEqual(report['generated'],1)
            self.assertIn('16',report['items'][0]['warning'])

    def test_local_model_progress_reports_real_generation_activity(self):
        from kohya_core.qwen_vl_caption import _report_model_activity
        import threading
        events = []
        state = {'lock': threading.Lock(), 'callback': lambda msg: events.append(msg)}
        _report_model_activity(state, 'slot print_timing: prompt processing, n_tokens = 228, progress = 0.24, t = 5.87 s')
        _report_model_activity(state, 'slot print_timing: n_gen = 126, tg = 4.15 t/s, tg_3s = 4.25 t/s')
        self.assertTrue(any('24%' in message for message in events))
        self.assertTrue(any('126' in message for message in events))

    def test_model_activity_reaches_current_image_progress(self):
        import threading
        from unittest.mock import patch
        from types import SimpleNamespace
        from kohya_core.qwen_vl_caption import _caption_images, _report_model_activity
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); image = root / 'one.png'
            Image.new('RGB', (800,600), 'white').save(image)
            selection = {'images':[image], 'root':root, 'language':'zh', 'length':'brief', 'output_format':'moss_layout'}
            report = {'total':1,'items':[],'generated':0,'failed':0}
            activity = {'lock':threading.Lock(), 'callback':None}; events = []
            def generate(*args, **kwargs):
                _report_model_activity(activity, 'n_gen = 126, tg = 4.15 t/s')
                return json.dumps(draft())
            with patch('kohya_core.qwen_vl_caption.describe_image', side_effect=generate):
                _caption_images(SimpleNamespace(check_stop=lambda:None), selection, {'_activity':activity}, SimpleNamespace(poll=lambda:None), report, lambda _:None, lambda done,total,item:events.append((done,total,item['name'])), lambda _:None)
            self.assertTrue(any(done == 0 and '126' in name and 'one.png' in name for done,total,name in events))
            self.assertEqual(events[-1][:2], (1,1))
            self.assertIsNone(activity['callback'])

    def test_local_layout_retries_and_accepts_corrected_result(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from kohya_core.qwen_vl_caption import _caption_images
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); image = root / 'one.png'
            Image.new('RGB', (800, 600), 'white').save(image)
            selection = {'images':[image], 'root':root, 'language':'zh', 'length':'brief', 'output_format':'moss_layout'}
            report = {'total':1, 'items':[], 'generated':0, 'failed':0}
            core = SimpleNamespace(check_stop=lambda: None)
            process = SimpleNamespace(poll=lambda: None)
            with patch('kohya_core.qwen_vl_caption.describe_image', side_effect=['{bad json', json.dumps(draft())]) as model:
                _caption_images(core, selection, {}, process, report, lambda _: None, lambda *_: None, lambda _: None)
            self.assertEqual(model.call_count, 2)
            self.assertEqual(report['generated'], 1)
            self.assertEqual(report['items'][0]['layout']['items'][0]['bbox'], [200,100,600,500])

    def test_unreadable_text_preserves_box_and_warns_after_retry(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from kohya_core.qwen_vl_caption import _caption_images
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); image = root / 'one.png'; Image.new('RGB', (800,600), 'white').save(image)
            layout = draft(); layout['items'].append({'label':'text','caption':'unreadable text','bbox':[0,0,100,40]})
            selection = {'images':[image], 'root':root, 'language':'zh', 'length':'brief', 'output_format':'moss_layout'}
            report = {'total':1,'items':[],'generated':0,'failed':0}
            with patch('kohya_core.qwen_vl_caption.describe_image', return_value=json.dumps(layout)) as model:
                _caption_images(SimpleNamespace(check_stop=lambda:None), selection, {}, SimpleNamespace(poll=lambda:None), report, lambda _:None, lambda *_:None, lambda _:None)
            self.assertEqual(report['generated'],1)
            self.assertEqual(model.call_count, 1)
            self.assertEqual(report['items'][0]['layout']['items'][1]['label'],'object')
            self.assertEqual(report['items'][0]['layout']['items'][1]['bbox'],[0,0,100,40])
            self.assertIn('未识别',report['items'][0]['warning'])

    def test_partially_outside_model_box_is_clipped_and_warned_without_retry(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from kohya_core.qwen_vl_caption import _caption_images
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); image = root / 'one.png'; Image.new('RGB', (800,600), 'white').save(image)
            layout = draft(); layout['items'][0]['bbox'] = [-10, 100, 900, 500]
            selection = {'images':[image], 'root':root, 'language':'zh', 'length':'brief', 'output_format':'moss_layout'}
            report = {'total':1,'items':[],'generated':0,'failed':0}
            with patch('kohya_core.qwen_vl_caption.describe_image', return_value=json.dumps(layout)) as model:
                _caption_images(SimpleNamespace(check_stop=lambda:None), selection, {}, SimpleNamespace(poll=lambda:None), report, lambda _:None, lambda *_:None, lambda _:None)
            self.assertEqual(report['generated'],1)
            self.assertEqual(model.call_count,1)
            self.assertEqual(report['items'][0]['layout']['items'][0]['bbox'],[0,100,800,500])
            self.assertIn('边界',report['items'][0]['warning'])

    def test_unrepairable_model_box_reports_actual_error(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from kohya_core.qwen_vl_caption import _caption_images
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); image = root / 'one.png'; Image.new('RGB', (800,600), 'white').save(image)
            layout = draft(); layout['items'][0]['bbox'] = [900,100,1000,500]
            selection = {'images':[image], 'root':root, 'language':'zh', 'length':'brief', 'output_format':'moss_layout'}
            report = {'total':1,'items':[],'generated':0,'failed':0}; logs=[]
            with patch('kohya_core.qwen_vl_caption.describe_image', return_value=json.dumps(layout)) as model:
                _caption_images(SimpleNamespace(check_stop=lambda:None), selection, {}, SimpleNamespace(poll=lambda:None), report, logs.append, lambda *_:None, lambda _:None)
            self.assertEqual(model.call_count,2)
            self.assertEqual(report['failed'],1)
            self.assertIn('第 1 个框',report['items'][0]['error'])
            self.assertNotIn('空文字框',report['items'][0]['error'])
            self.assertTrue(any('重新识别' in line and '第 1 个框' in line for line in logs))

    def test_repair_centered_boxes_and_unreadable_text_together(self):
        value = draft(); value.update(bbox_coord_space='abs_centralized',bbox_format='yxyx')
        value['items'] = [{'label':'text','caption':'sign','bbox':[-350,-450,100,100]}]
        repaired, warning = moss_layout.repair_model_layout(json.dumps(value),(800,600))
        item = moss_layout.parse(repaired,(800,600))['items'][0]
        self.assertEqual(item['bbox'],[0,0,500,400])
        self.assertEqual(item['label'],'object')
        self.assertIn('边界',warning); self.assertIn('未识别',warning)

    def test_repair_rejects_ambiguous_or_inconsistent_geometry(self):
        for box in ([900,0,1000,200],[400,0,200,200],[0,0,0,200]):
            value=draft(); value['items'][0]['bbox']=box
            with self.assertRaises(ValueError): moss_layout.repair_model_layout(json.dumps(value),(800,600))
        value=draft();value['width']=700;value['items'][0]['bbox']=[0,0,900,200]
        with self.assertRaises(ValueError): moss_layout.repair_model_layout(json.dumps(value),(800,600))

    def test_bad_or_outside_box_is_rejected(self):
        value=draft();value['items'][0]['bbox']=[0,0,900,200]
        with self.assertRaises(ValueError): moss_layout.parse(json.dumps(value))
        with self.assertRaises(ValueError): moss_layout.parse('{"summary":{},"summary":{}}')
    def test_export_original_image_and_checked_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); src=root/'src'; dst=root/'dst';src.mkdir();dst.mkdir()
            image=src/'one.png'; Image.new('RGB',(800,600),'white').save(image)
            result=result_item({'output_format':'moss_layout'},image,json.dumps(draft()))
            result.update(name='one.png',image_signature=[image.stat().st_size,image.stat().st_mtime_ns])
            report={'directory':str(src),'items':[result]}
            files=export_report(report,[{'name':'one.png','caption':result['caption']}],str(dst),True)
            self.assertEqual(len(files),1);self.assertEqual(image.read_bytes(),(dst/'one.png').read_bytes())
            self.assertEqual(json.loads((dst/'one.txt').read_text(encoding='utf-8'))['items'][0]['bbox'],[200,100,600,500])
            self.assertTrue((dst/'one.layout.json').is_file())
            with self.assertRaises(CaptionError): export_report(report,[{'name':'one.png','caption':'{bad'}],str(dst),True)
    def test_multi_character_training_keeps_layout_json(self):
        from tests.test_multi_character_dataset import MultiCharacterDatasetTests
        case = MultiCharacterDatasetTests('test_validation_files_follow_custom_output_directory')
        case.setUp()
        try:
            for role in case.settings['roles']:
                annotation = draft()
                annotation.update(width=96, height=80)
                annotation['items'][0]['bbox'] = [10, 10, 80, 70]
                (Path(role['directory']) / 'one.txt').write_text(json.dumps(annotation), encoding='utf-8')
            case.prepare()
            captions = sorted(case.target.glob('*.txt'))
            self.assertEqual(len(captions), 2)
            for caption in captions:
                value = json.loads(caption.read_text(encoding='utf-8'))
                self.assertEqual(value['bbox_format'], 'yxyx')
                self.assertTrue(any(role['trigger'] in value['summary']['caption'] for role in case.settings['roles']))
        finally:
            case.doCleanups()

    def test_external_preprocess_crop_preserves_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); src=root/'src'; dst=root/'dst';src.mkdir()
            Image.new('RGB',(800,600),(190,110,70)).save(src/'one.png')
            (src/'one.txt').write_text('  '+json.dumps(draft()),encoding='utf-8')
            script=Path(__file__).resolve().parents[1]/'preprocess.py'
            args=[sys.executable,str(script),'--input',str(src),'--output',str(dst),'--size','512','--mode','character','--moss-layout','--trigger','tok','--crop-ratio','1:1','--no-remove-black-borders','--no-remove-watermark','--min-size','0','--blur-threshold','0','--no-write-dataset-config']
            result=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            actual=json.loads((dst/'one.txt').read_text(encoding='utf-8'))
            self.assertEqual(actual['items'][0]['bbox'],[-171,-171,171,171])
            self.assertTrue(actual['summary']['caption'].startswith('tok'))

class ScheduleTests(unittest.TestCase):
    def test_default_keeps_existing_command(self):
        cmd=['train','--lr_scheduler=cosine','--lr_warmup_steps=120']
        self.assertEqual(command(cmd,{'mode':'character'},'cosine',120)[0],cmd)
    def test_custom_schedule_replaces_both_flags(self):
        params={'mode':'character','lr_scheduler':'linear','lr_warmup_steps':'10'}
        cmd,spec=command(['train','--lr_scheduler=cosine','--lr_warmup_steps','120'],params,'cosine',120)
        self.assertEqual(cmd,['train','--lr_scheduler','linear','--lr_warmup_steps','10'])
        self.assertEqual(spec['lr_warmup_steps'],10)
    def test_resume_rejects_changed_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            params={'mode':'character','lr_scheduler':'linear','lr_warmup_steps':'10'}
            guard_resume(params,tmp,None,'cosine',120)
            guard_resume(params,tmp,'snapshot','cosine',120)
            with self.assertRaises(ValueError):
                guard_resume({'mode':'character','lr_scheduler':'constant'},tmp,'snapshot','cosine',120)

    def test_toolkit_yaml_and_conflict_checks(self):
        params={'mode':'qwen_image','lr_scheduler':'constant_with_warmup','lr_warmup_steps':'17'}
        text,spec=yaml_config('      train:\n        steps: 200\n',params)
        self.assertIn('lr_scheduler: constant_with_warmup',text)
        self.assertIn('"num_warmup_steps": 17',text)
        with self.assertRaises(ValueError): resolve({'mode':'qwen_image','lr_scheduler':'cosine','lr_warmup_steps':'4'})
        with self.assertRaises(ValueError): resolve({'mode':'character','lr_scheduler':'linear','optimizer':'prodigy'})

if __name__=='__main__': unittest.main()
