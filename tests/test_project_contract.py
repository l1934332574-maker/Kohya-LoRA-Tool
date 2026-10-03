import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui.modern_host import ModernUIBridge
from kohya_core import paths, queue
from kohya_core.project_config import caption_summary
from kohya_core.training_history import TrainingHistory


def contract_core():
    return SimpleNamespace(preset_for=lambda *_: {}, normalize_crop_ratio=lambda value: value,
                           H3_FRAMES=73, ARCH_INFO={'sdxl': {}})


class ProjectContractTests(unittest.TestCase):
    def project(self, mode='krea2_fz'):
        return {'name': 'example', 'mode': mode, 'base_type': 'sdxl', 'params': {
            'keep_user_captions': True, 'sample_preview': False, 'quant_mode': 'nf4',
            'amd_mode': True, 'batch_size': '2', 'gc': 'on', 'wd14_model': 'moat-v2',
            'overwrite': True, 'compile': False, 'blocks_to_swap': '12'}}

    def test_queue_keeps_saved_training_and_caption_choices(self):
        with patch.object(paths, 'load_project', return_value=self.project()), \
                patch.dict(sys.modules, {'Kohya一键工具': contract_core()}):
            result = queue.params_from_project('example')
        for key, value in self.project()['params'].items():
            expected = 2 if key == 'batch_size' else value
            self.assertEqual(result.get(key), expected, key)

    def test_all_modern_training_paths_preserve_user_captions(self):
        bridge = ModernUIBridge(contract_core())
        for mode in ('character', 'qwen_image', 'krea2_fz'):
            with self.subTest(mode=mode):
                result = bridge._classic_training_params(self.project(mode), 'example')
                self.assertTrue(result.get('keep_user_captions'))

    def test_failed_save_does_not_truncate_existing_project(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'example.json'
            original = '{"name":"example","params":{"rank":8}}'
            target.write_text(original, encoding='utf-8')
            with patch.object(paths, 'projects_dir', return_value=directory), \
                    patch.object(paths, '_project_path', return_value=str(target)), \
                    patch.object(json, 'dump', side_effect=OSError('simulated full disk')):
                self.assertFalse(paths.save_project('example', {'params': {'rank': 16}}))
            self.assertEqual(target.read_text(encoding='utf-8'), original)


    def test_gc_manual_choices_reach_existing_engine_policy(self):
        source = Path(__file__).resolve().parents[1] / 'Kohya一键工具.py'
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        definition = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'decide_gradient_checkpointing')
        namespace = {}
        exec(compile(ast.Module(body=[definition], type_ignores=[]), str(source), 'exec'), namespace)
        choose = namespace['decide_gradient_checkpointing']
        for on in ('on', '开启', 'true'):
            self.assertTrue(choose(on, 24))
        for off in ('off', '关闭', 'false'):
            self.assertFalse(choose(off, 4))
        self.assertTrue(choose('auto', 4))
        self.assertFalse(choose('自动', 24))

    def test_saved_backup_recovers_corrupt_primary(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'example.json'
            with patch.object(paths, '_project_path', return_value=str(target)):
                self.assertTrue(paths.save_project('example', {'params': {'rank': 8}}))
                self.assertTrue(paths.save_project('example', {'params': {'rank': 16}}))
                target.write_text('{corrupt', encoding='utf-8')
                self.assertEqual(paths.load_project('example')['params']['rank'], 8)
                self.assertTrue(paths.delete_project('example'))
                self.assertIsNone(paths.load_project('example'))

    def test_rename_rolls_back_data_when_saving_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for parent in ('dataset', 'output'):
                (root / parent / 'old').mkdir(parents=True)
                (root / parent / 'old' / 'user.txt').write_text('keep')
            with patch.object(paths, 'load_project', return_value={'name': 'old'}), \
                    patch.object(paths, '_project_path', side_effect=lambda name: str(root / (name + '.json'))), \
                    patch.object(paths, 'project_data_dir', side_effect=lambda name: str(root / 'dataset' / name)), \
                    patch.object(paths, 'project_output_dir', side_effect=lambda name: str(root / 'output' / name)), \
                    patch.object(paths, 'save_project', return_value=False):
                ok, message = paths.rename_project('old', 'new')
            self.assertFalse(ok, message)
            for parent in ('dataset', 'output'):
                self.assertTrue((root / parent / 'old' / 'user.txt').exists())
                self.assertFalse((root / parent / 'new').exists())

    def test_dataset_summary_handles_missing_empty_and_unicode_captions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('a', 'b', 'c'):
                (root / (name + '.png')).write_bytes(b'fixture')
            (root / 'a.txt').write_text('subject', encoding='utf-8-sig')
            (root / 'b.txt').write_text('  ', encoding='utf-16')
            summary = caption_summary(directory)
            self.assertEqual((summary['images'], summary['captioned'], summary['empty_captions'], summary['missing_captions']), (3, 1, 1, 1))

    def test_metrics_are_finite_bounded_and_without_duplicate_steps(self):
        bridge = ModernUIBridge(contract_core())
        task = bridge._begin_task('test', 'training')
        for step in range(1, 1300):
            bridge._record_training_metrics(task, {'step': step, 'total': 2000, 'loss': .5 / step, 'speed': 2})
        bridge._record_training_metrics(task, {'step': 1300, 'total': 2000, 'loss': float('nan'), 'speed': float('inf')})
        status = bridge.get_task_status(task)
        self.assertLessEqual(len(status['loss_history']), 600)
        steps = [point['step'] for point in status['loss_history']]
        self.assertEqual(steps, sorted(set(steps)))
        self.assertIsNone(status['metrics']['loss'])
        self.assertEqual(status['metrics']['speed'], 0)

    def test_training_history_is_persistent_filtered_and_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as directory:
            history = TrainingHistory(directory)
            run = {'id': 'a' * 32, 'project_name': 'example', 'started': 100, 'status': 'completed',
                   'config': {'params': {'rank': 8}}, 'logs': ['done']}
            history.save(run)
            self.assertEqual(TrainingHistory(directory).get(run['id'])['config'], run['config'])
            self.assertEqual(len(history.list('example')), 1)
            self.assertEqual(history.list('other'), [])
            with self.assertRaises(ValueError):
                history.get('../outside')
            (Path(directory) / ('b' * 32 + '.json')).write_text('{bad')
            self.assertEqual(len(history.list()), 1)

    def test_history_restore_clears_new_overrides_and_preserves_current_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = ModernUIBridge(contract_core())
            bridge.core.data_sub = lambda _: directory
            bridge.core.load_project = lambda _: {'mode': 'krea2_fz', 'base_type': 'sdxl'}
            history = TrainingHistory(directory)
            history.save({'id': 'a' * 32, 'project_name': 'example', 'started': 100,
                          'config': {'mode': 'krea2_fz', 'base_type': 'sdxl', 'raw_dir': 'old', 'params': {'rank': 8}}})
            with patch.object(bridge, 'save_project_config', return_value={'ok': True}) as save:
                self.assertTrue(bridge.restore_training_run('a' * 32, 'example')['ok'])
                patch_config = save.call_args.args[1]
            self.assertNotIn('raw_dir', patch_config)
            self.assertEqual(patch_config['params']['rank'], 8)
            self.assertIsNone(patch_config['params']['quant_mode'])
            bridge._begin_task('running', 'training')
            self.assertFalse(bridge.restore_training_run('a' * 32, 'example')['ok'])


if __name__ == '__main__':
    unittest.main()
