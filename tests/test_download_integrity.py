import hashlib
import io
import json
import os
import struct
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

import model_downloader as downloads


class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {'Content-Length': str(len(body))}


class DownloadIntegrityTests(unittest.TestCase):
    def test_token_only_sent_to_official_https_hosts(self):
        with patch.dict(os.environ, {'HF_TOKEN': 'private-token'}):
            for url in ('https://modelscope.cn/a', 'https://hf-mirror.com/a',
                        'http://huggingface.co/a', 'https://huggingface.co.evil/a'):
                self.assertNotIn('Authorization', downloads._base_headers(url))
            self.assertIn('Authorization', downloads._base_headers('https://huggingface.co/a'))
        request = urllib.request.Request('https://huggingface.co/a', headers={'Authorization': 'Bearer secret'})
        redirected = downloads._TokenSafeRedirect().redirect_request(request, None, 302, '', {}, 'https://cdn.example/a')
        self.assertFalse(redirected.has_header('Authorization'))

    def test_html_and_truncated_response_never_become_models(self):
        for body, headers in ((b'<html>error</html>', {}), (b'short', {'Content-Length': '10'})):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as directory:
                dest = Path(directory) / 'model.bin'
                task = downloads.ModelDownloader('https://example/a', str(dest), logf=None)
                with patch.object(downloads, '_opener_for') as opener:
                    opener.return_value.open.return_value = Response(body, headers=headers)
                    with self.assertRaises(downloads.DownloadError):
                        task._download()
                self.assertFalse(dest.exists())

    def test_safetensors_data_is_checked_not_just_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'model.safetensors'
            header = json.dumps({'weight': {'dtype': 'F32', 'shape': [1], 'data_offsets': [0, 4]}}).encode()
            dest.write_bytes(struct.pack('<Q', len(header)) + header + b'1234')
            task = downloads.ModelDownloader('https://example/a', str(dest))
            task._validate_file(dest)
            dest.write_bytes(dest.read_bytes()[:-1])
            with self.assertRaises(downloads.DownloadError):
                task._validate_file(dest)

    def test_matching_validated_range_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'model.bin'
            task = downloads.ModelDownloader('https://example/a', str(dest), logf=None)
            Path(task.part).write_bytes(b'abc')
            task._write_metadata({'source': hashlib.sha256(task.url.encode()).hexdigest(), 'validator': '"v1"', 'total': 6})
            with patch.object(downloads, '_opener_for') as opener:
                opener.return_value.open.return_value = Response(b'def', 206, {'Content-Range': 'bytes 3-5/6', 'ETag': '"v1"'})
                task._download()
                request = opener.return_value.open.call_args.args[0]
                self.assertEqual(request.get_header('Range'), 'bytes=3-')
                self.assertEqual(request.get_header('If-range'), '"v1"')
            self.assertEqual(dest.read_bytes(), b'abcdef')
            self.assertFalse(Path(task.metadata).exists())

    def test_wrong_range_or_changed_etag_does_not_append(self):
        for headers in ({'Content-Range': 'bytes 0-2/6'},
                        {'Content-Range': 'bytes 3-5/6', 'ETag': '"v2"'}):
            with self.subTest(headers=headers), tempfile.TemporaryDirectory() as directory:
                task = downloads.ModelDownloader('https://example/a', str(Path(directory) / 'model.bin'), logf=None)
                Path(task.part).write_bytes(b'abc')
                task._write_metadata({'source': hashlib.sha256(task.url.encode()).hexdigest(), 'validator': '"v1"', 'total': 6})
                with patch.object(downloads, '_opener_for') as opener:
                    opener.return_value.open.return_value = Response(b'xyz', 206, headers)
                    with self.assertRaises(downloads.DownloadError):
                        task._download()
                self.assertEqual(Path(task.part).read_bytes(), b'abc')
                self.assertEqual(json.loads(Path(task.metadata).read_text()), {})

    def test_invalid_existing_file_is_replaced_only_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory) / 'model.bin'
            dest.write_bytes(b'<html>bad</html>')
            task = downloads.ModelDownloader('https://example/a', str(dest), logf=None)
            Path(task.metadata).write_text('[]')
            with patch.object(downloads, '_opener_for') as opener:
                opener.return_value.open.return_value = Response(b'good')
                task._download()
            self.assertEqual(dest.read_bytes(), b'good')
