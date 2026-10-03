"""Atomic JSON persistence for local user settings and task records."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading

STORAGE_LOCK = threading.RLock()


def atomic_json_write(path, data, backup=False):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    with STORAGE_LOCK:
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                             dir=target.parent, prefix='.' + target.name,
                                             suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            if backup and target.is_file():
                # Only replace the last good backup with a readable configuration.
                try:
                    with target.open(encoding='utf-8-sig') as handle:
                        json.load(handle)
                except (OSError, ValueError):
                    pass
                else:
                    backup_tmp = Path(str(temporary) + '.bak')
                    try:
                        shutil.copy2(target, backup_tmp)
                        os.replace(backup_tmp, str(target) + '.bak')
                    finally:
                        backup_tmp.unlink(missing_ok=True)
            os.replace(temporary, target)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
