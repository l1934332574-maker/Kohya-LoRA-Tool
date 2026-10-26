"""Runtime defaults for Windows MOSS encoders; preserve explicit overrides."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from kohya_core import fizgig_engine as engine


class FizgigRuntimeEnvironmentTests(unittest.TestCase):
    def make_env(self, platform='win32', version='v8.9.6', initial=None, backend='nvidia'):
        core = SimpleNamespace(build_direct_env=lambda: dict(initial or {}),
                               _fizgig_rocm_env=lambda source, python: dict(initial or {}, ROCM_READY='1'))
        record = dict(version=version, backend=backend, source='source', python='python')
        with patch.object(engine.sys, 'platform', platform):
            return engine._env(core, record)

    def test_windows_moss_uses_plain_file_reads(self):
        env = self.make_env()
        self.assertEqual(env['FIZGIG_TE_FROM_FILE'], '1')
        self.assertEqual(env['PYTHONFAULTHANDLER'], '1')
        self.assertEqual(env['PYTHONUTF8'], '1')

    def test_explicit_choices_are_preserved(self):
        env = self.make_env(initial={'FIZGIG_TE_FROM_FILE': '0', 'PYTHONFAULTHANDLER': '0'})
        self.assertEqual(env['FIZGIG_TE_FROM_FILE'], '0')
        self.assertEqual(env['PYTHONFAULTHANDLER'], '0')

    def test_linux_does_not_force_windows_workaround(self):
        self.assertNotIn('FIZGIG_TE_FROM_FILE', self.make_env(platform='linux'))

    def test_older_engine_does_not_receive_moss_workaround(self):
        self.assertNotIn('FIZGIG_TE_FROM_FILE', self.make_env(version='v7.3.1'))

    def test_rocm_environment_is_retained(self):
        env = self.make_env(backend='amd-rocm', initial={'USER_SETTING': 'kept'})
        self.assertEqual(env['ROCM_READY'], '1')
        self.assertEqual(env['USER_SETTING'], 'kept')
        self.assertEqual(env['FIZGIG_TE_FROM_FILE'], '1')


if __name__ == '__main__':
    unittest.main()
