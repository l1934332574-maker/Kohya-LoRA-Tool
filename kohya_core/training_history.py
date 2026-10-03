"""Bounded, atomic records of modern desktop training attempts."""
import json
import math
import re
from pathlib import Path

from .storage import atomic_json_write


class TrainingHistory:
    def __init__(self, directory):
        self.directory = Path(directory)

    def _path(self, run_id):
        if not re.fullmatch(r'[0-9a-f]{32}', str(run_id)):
            raise ValueError('训练记录编号无效。')
        return self.directory / (run_id + '.json')

    def save(self, record):
        atomic_json_write(self._path(record['id']), record)

    def get(self, run_id):
        target = self._path(run_id)
        if target.stat().st_size > 4_000_000:
            raise ValueError('训练记录过大，无法读取。')
        with target.open(encoding='utf-8') as handle:
            record = json.load(handle)
        if not isinstance(record, dict) or record.get('id') != run_id:
            raise ValueError('训练记录损坏。')
        started = record.get('started')
        if not isinstance(started, (int, float)) or not math.isfinite(started):
            raise ValueError('训练记录的时间无效。')
        return record

    def list(self, project_name='', limit=100):
        records = []
        for path in self.directory.glob('*.json'):
            try:
                record = self.get(path.stem)
                if project_name and record.get('project_name') != project_name:
                    continue
                records.append({key: record.get(key) for key in (
                    'id', 'project_name', 'mode', 'mode_label', 'started', 'ended',
                    'status', 'message', 'metrics', 'resume_path',
                )})
            except (OSError, ValueError):
                continue
        records.sort(key=lambda record: float(record.get('started') or 0), reverse=True)
        return records[:max(1, min(int(limit), 100))]
