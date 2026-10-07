"""Shared model/version/engine choices; no network and no GPU imports."""
import copy
import json
from pathlib import Path


def catalog(core):
    rows = json.loads(Path(__file__).with_name('model_catalog.json').read_text(encoding='utf-8'))
    status = core.system_status()
    vendor = core.detect_gpu_vendor() or 'unknown'
    keys = {'kohya': 'kohya_ok', 'musubi': 'musubi_ok', 'ai_toolkit': 'at_ok', 'fizgig': 'fizgig_ok'}
    fz = core.fizgig_engine_update_status()
    for model in rows:
        for variant in model['variants']:
            engines = variant['engines']
            supported = [e for e in engines if vendor in e['vendors']]
            preferred = variant['preferred'].get(vendor)
            chosen = next((e for e in supported if e['key'] == preferred), supported[0] if supported else None)
            for engine in engines:
                engine['supported'] = vendor == 'unknown' or vendor in engine['vendors']
                engine['recommended'] = bool(chosen and engine['key'] == chosen['key'])
                engine['installed'] = bool(status.get(keys[engine['key']])) and (engine['key'] != 'fizgig' or fz.get('new_families_supported', False))
                engine['status'] = ('显卡路径未接入' if not engine['supported'] else '已安装' if engine['installed'] else '需安装 / 更新')
    return {'models': rows, 'gpu_vendor': vendor, 'gpu': status.get('gpu') or '未识别显卡'}


def resolve_choice(selection):
    if not isinstance(selection, dict): raise ValueError('模型选择格式无效。')
    rows = json.loads(Path(__file__).with_name('model_catalog.json').read_text(encoding='utf-8'))
    for model in rows:
        if model['key'] != selection.get('model'): continue
        for variant in model['variants']:
            if variant['key'] != selection.get('variant'): continue
            for engine in variant['engines']:
                if engine['key'] == selection.get('engine'):
                    return copy.deepcopy(engine)
    raise ValueError('这个模型版本没有所选引擎的训练入口。')
