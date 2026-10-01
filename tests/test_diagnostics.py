import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from kohya_core import diagnostics as diag


class Core:
    APP_VERSION = "test"

    def __init__(self, directory):
        self.directory = str(directory)

    def data_dir(self):
        return self.directory

    def get_kohya_dir(self):
        return str(Path(self.directory) / "kohya_ss")

    def build_env(self):
        return {"PATH": "fixture", "HF_TOKEN": "DO_NOT_EXPORT", "HSA_OVERRIDE_GFX_VERSION": "10.3.0"}


class DiagnosticsTests(unittest.TestCase):
    def test_redacts_common_secrets_and_profile(self):
        text = 'api_key="sensitive" Authorization: Bearer abcdef hf_token=private https://a:pass@example.test/?token=private C:\\Users\\Alice\\data'
        result = diag.redact(text)
        for secret in ("sensitive", "abcdef", "private", "Alice", "a:pass"):
            self.assertNotIn(secret, result)

    def test_summary_records_failed_collection(self):
        report = diag.collect_summary(Core("fixture"))
        self.assertIn("error", report["gpu"])
        self.assertIn("error", report["python"])

    def test_timeout_keeps_partial_output(self):
        with patch.object(diag.subprocess, "run", side_effect=subprocess.TimeoutExpired(["python"], 1, output=b"before-timeout", stderr=b"error-detail")):
            report = diag._run(["python"], timeout=1)
        self.assertEqual(report["status"], "timeout")
        self.assertEqual(report["stdout"], "before-timeout")
        self.assertEqual(report["stderr"], "error-detail")

    def test_session_keeps_middle_after_ui_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            session = diag.SessionLog(directory)
            for index in range(3100):
                session.append("line-%d" % index)
            text = session.snapshot()
            self.assertIn("line-0\n", text)
            self.assertIn("line-1550\n", text)
            self.assertIn("line-3099\n", text)

    def test_bundle_contains_independent_reports_and_omits_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            core = Core(directory)
            path = Path(directory) / "diagnosis.zip"
            cache = Path(directory) / "installer_cache" / "amd_torch"
            cache.mkdir(parents=True)
            (cache / "torch-2.9.1%2Btest.whl.part").write_bytes(b"fixture")
            with patch.object(diag, "_run", return_value={"status": "failed", "stderr": "fixture driver error"}):
                diag.write_bundle(core, path, "traceback fixture\napi_key=hidden", {"status": "failed"},
                                  {"mode": "style", "hf_token": "DO_NOT_EXPORT", "params": {"rank": 8, "sample_prompt": "private text"}})
            import zipfile
            with zipfile.ZipFile(path) as archive:
                joined = "\n".join(archive.read(name).decode("utf-8") for name in archive.namelist())
                self.assertNotIn("DO_NOT_EXPORT", joined)
                self.assertNotIn("private text", joined)
                self.assertNotIn("hidden", joined)
                self.assertIn("traceback fixture", joined)
                self.assertEqual(json.loads(archive.read("runtimes/amd.json"))["status"], "missing")
                cache_entries = json.loads(archive.read("download_cache.json"))
                self.assertTrue(next(entry for entry in cache_entries if "filename" in entry)["url_encoded_filename"])

    def test_text_export_contains_diagnostics_full_session_and_readable_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            session = diag.SessionLog(directory)
            session.append("early session line")
            path = Path(directory) / "out.txt"
            failure = {"status": "failed", "traceback": "Traceback:\n  DLL load failed", "token": "private-secret"}
            with patch.object(diag, "_run", return_value={"status": "fixture"}), \
                 patch.object(diag, "_runtime_probe", return_value=failure):
                diag.write_bundle(Core(directory), path, "recent log\napi_key=private-key", {"status": "failed"}, session=session)
            text = path.read_text(encoding="utf-8-sig")
            for expected in ("【环境信息】", "【训练环境 / amd】", "【下载缓存】", "recent log", "early session line", "Traceback:\n    DLL load failed"):
                self.assertIn(expected, text)
            self.assertNotIn("private-secret", text)
            self.assertNotIn("private-key", text)
            self.assertNotIn("Traceback:\\n", text)

    def test_json_redacts_nested_secret_and_windows_path(self):
        report = json.loads(diag._json({"nested": {"token": "secret-value", "path": "C:\\Users\\Alice\\Python"}}))
        self.assertEqual(report["nested"]["token"], "<REDACTED>")
        self.assertEqual(report["nested"]["path"], "%USERPROFILE%\\Python")

    def test_busy_task_skips_gpu_test(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(diag, "_runtime_probe", return_value={"status": "fixture"}) as probe, \
                 patch.object(diag, "_run", return_value={"status": "fixture"}):
                diag.write_bundle(Core(directory), Path(directory) / "out.zip", "", {"status": "running"})
            self.assertTrue(probe.call_args_list)
            self.assertTrue(all(call.args[3] is False for call in probe.call_args_list))

    def test_real_probe_retains_module_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            python = Path(directory) / "Scripts" / "python.exe"
            python.parent.mkdir()
            python.touch()
            output = {"imports": {"torch": {"status": "failed", "traceback": "DLL load failed fixture"}}}
            with patch.object(diag, "_run", return_value={"status": "ok", "stdout": "noise\nKLT_DIAGNOSTIC=" + json.dumps(output)}):
                result = diag._runtime_probe("amd", python, {})
            self.assertIn("DLL load failed", result["runtime"]["imports"]["torch"]["traceback"])


if __name__ == "__main__":
    unittest.main()
