"""Lock down software-side compatibility for pinned Fizgig offloading sources."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from kohya_core import fizgig_engine as engine, fizgig_adapter as adapter

FIXTURE='''
from types import SimpleNamespace
torch = SimpleNamespace(device=lambda name: name)
moves = []
def _streamed_linears(layer): return layer

def _synchronize_device(device): pass

def weighs_to_device(layer, device): moves.append((layer, device))

def swap_weight_devices_no_cuda(device, layer_to_cpu, layer_to_cuda):
    assert layer_to_cpu.__class__ == layer_to_cuda.__class__
    return 'fast'

class Offloader:
    def swap_weight_devices_cuda(self, device, layer_to_cpu, layer_to_cuda):
        assert layer_to_cpu.__class__ == layer_to_cuda.__class__
        return 'fast'
'''


class FizgigOffloadingCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.source=Path(self.temp.name)
        for relative in engine.required_files(engine.LATEST_VERSION):
            path=self.source/relative;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(FIXTURE if path.name=='offloading.py' else 'fixture',encoding='utf-8')
        self.file=self.source/'src/fizgig/modules/offloading.py'
        engine._write(self.source/'.kohya-fizgig-source.json',{
            'version':engine.LATEST_VERSION,'commit':engine.source_commit(engine.LATEST_VERSION),
            'adapter':engine._adapter_revision(engine.LATEST_VERSION),
            'files':{name:engine._sha(self.source/name) for name in engine.required_files(engine.LATEST_VERSION)}})
        self.record={'version':engine.LATEST_VERSION,'source':str(self.source),'python':sys.executable}

    def test_installed_patch_preserves_version_and_is_idempotent(self):
        self.assertTrue(engine.ensure_preview_offloading(self.record,lambda _:None))
        after=self.file.read_bytes()
        self.assertEqual(engine.source_version(self.source),engine.LATEST_VERSION)
        self.assertFalse(engine.ensure_preview_offloading(self.record,lambda _:None))
        self.assertEqual(after,self.file.read_bytes())
        self.assertEqual(self.file.with_name(self.file.name+'.kohya-mixed-storage.bak').read_text(encoding='utf-8'),FIXTURE)

    def test_changed_source_is_not_patched(self):
        self.file.write_text(FIXTURE+'\n# edited',encoding='utf-8');before=self.file.read_bytes()
        with self.assertRaises(RuntimeError):engine.ensure_preview_offloading(self.record)
        self.assertEqual(before,self.file.read_bytes())

    def test_marker_write_failure_rolls_back_source(self):
        before=self.file.read_bytes()
        with patch.object(engine,'_write',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):engine.ensure_preview_offloading(self.record)
        self.assertEqual(before,self.file.read_bytes())
        self.assertEqual(engine.source_version(self.source),engine.LATEST_VERSION)

    def test_both_transfer_paths_guard_dtype_shape_and_names(self):
        engine.ensure_preview_offloading(self.record,lambda _:None)
        namespace={};exec(self.file.read_text(encoding='utf-8'),namespace)
        def layer(dtype='BF16',shape=(4,4),name='linear'):
            return {name:SimpleNamespace(weight=SimpleNamespace(dtype=dtype,shape=shape))}
        calls=(namespace['swap_weight_devices_no_cuda'],namespace['Offloader']().swap_weight_devices_cuda)
        for call in calls:
            self.assertEqual(call('gpu',layer(),layer()),'fast')
            for other in (layer('INT8'),layer(shape=(8,4)),layer(name='other')):
                namespace['moves'].clear()
                self.assertIsNone(call('gpu',layer(),other))
                self.assertEqual([device for _,device in namespace['moves']],['cpu','gpu'])

    def test_training_applies_compatibility_before_model_loading(self):
        with patch.object(adapter,'source_version',return_value=engine.LATEST_VERSION), \
                patch.object(engine,'ensure_preview_offloading',side_effect=RuntimeError('compatibility probe')) as ensure, \
                patch.object(adapter,'models') as models:
            with self.assertRaisesRegex(RuntimeError,'compatibility probe'):
                adapter.train_lora(SimpleNamespace(),self.record,lambda _:None,'moss_fz',{},8,None,None)
        ensure.assert_called_once();models.assert_not_called()


if __name__=='__main__': unittest.main()
