"""Isolated application-settings storage for bridge test doubles."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
from gui.modern_host import ModernUIBridge as ApplicationBridge


class ModernUIBridge(ApplicationBridge):
    def __init__(self, core, *args, **kwargs):
        settings = None
        if not callable(getattr(core, 'data_sub', None)):
            settings = tempfile.TemporaryDirectory(prefix='kohya-bridge-test-')
            if type(core) is object:
                core = SimpleNamespace()
            def data_sub(*parts):
                path = Path(settings.name).joinpath(*parts)
                path.mkdir(parents=True, exist_ok=True)
                return str(path)
            core.data_sub = data_sub
        super().__init__(core, *args, **kwargs)
        self._test_settings_directory = settings
