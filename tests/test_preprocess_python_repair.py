import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import kohya_core.utils as core_utils


def _load_legacy_tool():
    """Load the classic app module without starting its UI."""
    source = ROOT / "Kohya一键工具.py"
    spec = importlib.util.spec_from_file_location("kohya_legacy_preprocess_test", source)
    module = importlib.util.module_from_spec(spec)
    previous_popen = subprocess.Popen
    try:
        spec.loader.exec_module(module)
    finally:
        # The Windows app wraps Popen at import time; keep the test runner isolated.
        subprocess.Popen = previous_popen
    return module


legacy = _load_legacy_tool()


class PreprocessPythonRepairTests(unittest.TestCase):
    def test_preprocess_reuses_packages_after_same_version_base_python_relocation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kernel = root / "kohya_ss"
            venv = kernel / "venv"
            scripts = venv / "Scripts"
            scripts.mkdir(parents=True)
            vpy = scripts / "python.exe"
            vpy.write_bytes(b"venv launcher fixture")

            missing_base = root / "old-python-310"
            installed_base = root / "current-python-310"
            installed_base.mkdir()
            candidate = installed_base / "python.exe"
            candidate.write_bytes(b"base interpreter fixture")
            cfg = venv / "pyvenv.cfg"
            cfg.write_text(
                "home = %s\ninclude-system-site-packages = false\nversion = 3.10.11\n"
                % missing_base,
                encoding="utf-8",
            )

            input_dir = root / "images"
            input_dir.mkdir()
            output_dir = root / "dataset"
            calls = []

            def venv_status(_vpy):
                current_home = next(
                    line.split("=", 1)[1].strip()
                    for line in cfg.read_text(encoding="utf-8").splitlines()
                    if line.lower().startswith("home")
                )
                if os.path.normcase(current_home) == os.path.normcase(str(installed_base)):
                    return True, "3.10.11"
                return False, "venv 指向的 Python 已不存在（No Python at ...），venv 已损坏"

            def available_python_version(path):
                return ("3.10.11", (3, 10, 11)) if os.path.normcase(path) == os.path.normcase(str(candidate)) else (None, None)

            def run_preprocess(cmd, logf=print, **_kwargs):
                calls.append(list(cmd))
                return 0

            with patch.object(legacy, "_pick_preprocess_python", return_value=str(vpy)), \
                    patch.object(legacy, "_venv_python_ok", side_effect=venv_status), \
                    patch.object(legacy, "_ensure_preprocess_deps", return_value=True) as ensure_deps, \
                    patch.object(core_utils, "_installed_python_candidates", return_value=[str(candidate)]), \
                    patch("kohya_core.utils._repair_candidate_python_version", side_effect=available_python_version), \
                    patch.object(core_utils.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")), \
                    patch.object(legacy, "get_kohya_dir", return_value=str(kernel)), \
                    patch.object(legacy, "dataset_train_dir", return_value=str(output_dir)), \
                    patch.object(legacy, "run_stream", side_effect=run_preprocess):
                legacy.preprocess(input_dir=str(input_dir), project="fixture", wd14=False, logf=lambda _line: None)

            self.assertEqual(len(calls), 1, "preprocess.py should start once after repairing the venv")
            self.assertEqual(calls[0][0], str(vpy))
            ensure_deps.assert_called_once_with(str(vpy), str(kernel), unittest.mock.ANY)
            self.assertEqual(
                next(line.split("=", 1)[1].strip() for line in cfg.read_text(encoding="utf-8").splitlines()
                     if line.lower().startswith("home")),
                str(installed_base),
            )
            backups = list(venv.glob("pyvenv.cfg.preprocess-repair-*.bak"))
            self.assertEqual(len(backups), 1, "the original venv config should be preserved")
            self.assertIn(str(missing_base), backups[0].read_text(encoding="utf-8"))

    def test_different_python_patch_version_is_never_used_to_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            venv = root / "venv"
            scripts = venv / "Scripts"
            scripts.mkdir(parents=True)
            vpy = scripts / "python.exe"
            vpy.write_bytes(b"venv launcher fixture")
            missing_base = root / "old-python-310"
            cfg = venv / "pyvenv.cfg"
            original = (
                "home = %s\ninclude-system-site-packages = false\nversion = 3.10.11\n"
                % missing_base
            ).encode("utf-8")
            cfg.write_bytes(original)
            other_python = root / "python310-patch.exe"
            other_python.write_bytes(b"different patch-version fixture")

            with patch("kohya_core.utils._repair_candidate_python_version", return_value=("3.10.12", (3, 10, 12))), \
                    patch.object(core_utils.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")):
                repaired, detail = core_utils.repair_relocated_venv(
                    str(vpy), validate=lambda _path: (True, "unexpected"),
                    candidates=[str(other_python)], logf=lambda _line: None,
                )

            self.assertFalse(repaired, detail)
            self.assertEqual(cfg.read_bytes(), original)
            self.assertEqual(list(venv.glob("pyvenv.cfg.preprocess-repair-*.bak")), [])

    def test_existing_wrong_version_home_is_repointed_to_exact_recorded_python(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            venv = root / "venv"
            scripts = venv / "Scripts"
            scripts.mkdir(parents=True)
            vpy = scripts / "python.exe"
            vpy.write_bytes(b"venv launcher fixture")
            wrong_base = root / "Python312"
            wrong_base.mkdir()
            (wrong_base / "python.exe").write_bytes(b"Python 3.12 fixture")
            right_base = root / "Python310"
            right_base.mkdir()
            candidate = right_base / "python.exe"
            candidate.write_bytes(b"Python 3.10 fixture")
            cfg = venv / "pyvenv.cfg"
            original = (
                "home = %s\ninclude-system-site-packages = false\nversion = 3.10.11\n"
                % wrong_base
            ).encode("utf-8")
            cfg.write_bytes(original)

            def probe(path):
                if os.path.normcase(path) == os.path.normcase(str(wrong_base / "python.exe")):
                    return "3.12.10", (3, 12, 10)
                if os.path.normcase(path) == os.path.normcase(str(candidate)):
                    return "3.10.11", (3, 10, 11)
                return None, None

            def validate(_vpy):
                current_home = next(
                    line.split("=", 1)[1].strip()
                    for line in cfg.read_text(encoding="utf-8").splitlines()
                    if line.lower().startswith("home")
                )
                return os.path.normcase(current_home) == os.path.normcase(str(right_base)), "3.10.11"

            with patch("kohya_core.utils._repair_candidate_python_version", side_effect=probe):
                repaired, detail = core_utils.repair_relocated_venv(
                    str(vpy), validate=validate, candidates=[str(candidate)], logf=lambda _line: None,
                )

            self.assertTrue(repaired, detail)
            current_home = next(
                line.split("=", 1)[1].strip()
                for line in cfg.read_text(encoding="utf-8").splitlines()
                if line.lower().startswith("home")
            )
            self.assertEqual(os.path.normcase(current_home), os.path.normcase(str(right_base)))
            self.assertIn(str(wrong_base), list(venv.glob("pyvenv.cfg.preprocess-repair-*.bak"))[0].read_text(encoding="utf-8"))

    def test_preprocess_repairs_existing_python312_home_after_ctypes_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kernel = root / "kohya_ss"
            venv = kernel / "venv"
            scripts = venv / "Scripts"
            scripts.mkdir(parents=True)
            vpy = scripts / "python.exe"
            vpy.write_bytes(b"venv launcher fixture")
            wrong_base = root / "Python312"
            wrong_base.mkdir()
            (wrong_base / "python.exe").write_bytes(b"Python 3.12 fixture")
            right_base = root / "Python310"
            right_base.mkdir()
            candidate = right_base / "python.exe"
            candidate.write_bytes(b"Python 3.10 fixture")
            cfg = venv / "pyvenv.cfg"
            cfg.write_text(
                "home = %s\ninclude-system-site-packages = false\nversion = 3.10.11\n"
                % wrong_base,
                encoding="utf-8",
            )
            input_dir = root / "images"
            input_dir.mkdir()
            output_dir = root / "dataset"
            started = []

            def venv_status(_vpy):
                current_home = next(
                    line.split("=", 1)[1].strip()
                    for line in cfg.read_text(encoding="utf-8").splitlines()
                    if line.lower().startswith("home")
                )
                if os.path.normcase(current_home) == os.path.normcase(str(right_base)):
                    return True, "3.10"
                return False, "AttributeError: class must define a '_type_' attribute"

            def available_python_version(path):
                if os.path.normcase(path) == os.path.normcase(str(wrong_base / "python.exe")):
                    return "3.12.10", (3, 12, 10)
                if os.path.normcase(path) == os.path.normcase(str(candidate)):
                    return "3.10.11", (3, 10, 11)
                return None, None

            def run_preprocess(cmd, logf=print, **_kwargs):
                started.append(list(cmd))
                return 0

            with patch.object(legacy, "_pick_preprocess_python", return_value=str(vpy)), \
                    patch.object(legacy, "_venv_python_ok", side_effect=venv_status), \
                    patch.object(legacy, "_ensure_preprocess_deps", return_value=True) as ensure_deps, \
                    patch.object(core_utils, "_installed_python_candidates", return_value=[str(candidate)]), \
                    patch("kohya_core.utils._repair_candidate_python_version", side_effect=available_python_version), \
                    patch.object(core_utils.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")), \
                    patch.object(legacy, "get_kohya_dir", return_value=str(kernel)), \
                    patch.object(legacy, "dataset_train_dir", return_value=str(output_dir)), \
                    patch.object(legacy, "run_stream", side_effect=run_preprocess):
                legacy.preprocess(input_dir=str(input_dir), project="fixture", wd14=False, logf=lambda _line: None)

            self.assertEqual(len(started), 1, "preprocess.py should start only after repairing the mixed base")
            self.assertEqual(started[0][0], str(vpy))
            ensure_deps.assert_called_once_with(str(vpy), str(kernel), unittest.mock.ANY)
            current_home = next(
                line.split("=", 1)[1].strip()
                for line in cfg.read_text(encoding="utf-8").splitlines()
                if line.lower().startswith("home")
            )
            self.assertEqual(os.path.normcase(current_home), os.path.normcase(str(right_base)))

    def test_existing_same_version_home_with_stdlib_failure_is_not_repointed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            venv = root / "venv"
            scripts = venv / "Scripts"
            scripts.mkdir(parents=True)
            vpy = scripts / "python.exe"
            vpy.write_bytes(b"venv launcher fixture")
            same_base = root / "Python310"
            same_base.mkdir()
            (same_base / "python.exe").write_bytes(b"Python 3.10 fixture")
            candidate_base = root / "Python310-copy"
            candidate_base.mkdir()
            candidate = candidate_base / "python.exe"
            candidate.write_bytes(b"Python 3.10 fixture")
            cfg = venv / "pyvenv.cfg"
            original = (
                "home = %s\ninclude-system-site-packages = false\nversion = 3.10.11\n"
                % same_base
            ).encode("utf-8")
            cfg.write_bytes(original)
            validate = unittest.mock.Mock(return_value=(True, "unexpected"))

            def probe(path):
                if os.path.normcase(path) == os.path.normcase(str(same_base / "python.exe")):
                    return None, None  # ctypes/stdlib smoke failed; do not guess from another install
                return "3.10.11", (3, 10, 11)

            with patch("kohya_core.utils._repair_candidate_python_version", side_effect=probe):
                repaired, detail = core_utils.repair_relocated_venv(
                    str(vpy), validate=validate, candidates=[str(candidate)], logf=lambda _line: None,
                )

            self.assertFalse(repaired, detail)
            self.assertEqual(cfg.read_bytes(), original)
            validate.assert_not_called()
            self.assertEqual(list(venv.glob("pyvenv.cfg.preprocess-repair-*.bak")), [])

    def test_venv_health_probe_cleans_pythonhome_and_pythonpath(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            venv = root / "venv"
            scripts = venv / "Scripts"
            scripts.mkdir(parents=True)
            vpy = scripts / "python.exe"
            vpy.write_bytes(b"venv launcher fixture")
            base = root / "Python310"
            base.mkdir()
            (base / "python.exe").write_bytes(b"base Python fixture")
            (venv / "pyvenv.cfg").write_text(
                "home = %s\nversion = 3.10.11\n" % base, encoding="utf-8",
            )
            completed = subprocess.CompletedProcess([], 0, "3.10\n", "")
            with patch.dict(os.environ, {
                "PYTHONHOME": r"C:\Users\XiaoHan\AppData\Local\Programs\Python\Python312",
                "PYTHONPATH": r"C:\Users\XiaoHan\AppData\Local\Programs\Python\Python312\Lib",
            }), patch.object(core_utils.subprocess, "run", return_value=completed) as run:
                ok, detail = legacy._venv_python_ok(str(vpy))

            self.assertTrue(ok, detail)
            child_env = run.call_args.kwargs["env"]
            self.assertNotIn("PYTHONHOME", child_env)
            self.assertNotIn("PYTHONPATH", child_env)

    def test_venv_health_probe_rejects_runtime_minor_mismatch_with_cfg(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            venv = root / "venv"
            scripts = venv / "Scripts"
            scripts.mkdir(parents=True)
            vpy = scripts / "python.exe"
            vpy.write_bytes(b"venv launcher fixture")
            base312 = root / "Python312"
            base312.mkdir()
            (base312 / "python.exe").write_bytes(b"Python 3.12 fixture")
            (venv / "pyvenv.cfg").write_text(
                "home = %s\nversion = 3.10.11\n" % base312, encoding="utf-8",
            )
            completed = subprocess.CompletedProcess([], 0, "3.12\n", "")
            with patch.object(core_utils.subprocess, "run", return_value=completed):
                ok, detail = legacy._venv_python_ok(str(vpy))

            self.assertFalse(ok)
            self.assertIn("3.12", detail)
            self.assertIn("3.10", detail)

    def test_preprocess_dependency_probe_cleans_pythonhome_and_pythonpath(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vpy = root / "python.exe"
            vpy.write_bytes(b"venv launcher fixture")
            completed = subprocess.CompletedProcess([], 0, "", "")
            with patch.dict(os.environ, {
                "PYTHONHOME": r"C:\Users\XiaoHan\AppData\Local\Programs\Python\Python312",
                "PYTHONPATH": r"C:\Users\XiaoHan\AppData\Local\Programs\Python\Python312\Lib",
            }), patch.object(core_utils.subprocess, "run", return_value=completed) as run:
                ready = legacy._ensure_preprocess_deps(str(vpy), str(root), logf=lambda _line: None)

            self.assertTrue(ready)
            child_env = run.call_args.kwargs["env"]
            self.assertNotIn("PYTHONHOME", child_env)
            self.assertNotIn("PYTHONPATH", child_env)

    def test_candidate_probe_uses_clean_environment_and_checks_stdlib(self):
        completed = subprocess.CompletedProcess([], 0, "3.10.11\n", "")
        with patch.dict(os.environ, {"PYTHONHOME": "stale-home", "PYTHONPATH": "stale-path"}), \
                patch.object(core_utils.subprocess, "run", return_value=completed) as run:
            version, parts = core_utils._repair_candidate_python_version("python.exe")

        self.assertEqual((version, parts), ("3.10.11", (3, 10, 11)))
        args, kwargs = run.call_args
        self.assertIn("import ctypes, socket, ssl, sqlite3", args[0][2])
        self.assertNotIn("PYTHONHOME", kwargs["env"])
        self.assertNotIn("PYTHONPATH", kwargs["env"])

    def test_failed_preprocess_dependency_check_restores_config_and_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            kernel = root / "kohya_ss"
            venv = kernel / "venv"
            scripts = venv / "Scripts"
            scripts.mkdir(parents=True)
            vpy = scripts / "python.exe"
            vpy.write_bytes(b"venv launcher fixture")
            missing_base = root / "old-python-310"
            installed_base = root / "current-python-310"
            installed_base.mkdir()
            candidate = installed_base / "python.exe"
            candidate.write_bytes(b"base interpreter fixture")
            cfg = venv / "pyvenv.cfg"
            original = (
                "home = %s\ninclude-system-site-packages = false\nversion = 3.10.11\n"
                % missing_base
            ).encode("utf-8")
            cfg.write_bytes(original)
            input_dir = root / "images"
            input_dir.mkdir()
            run_preprocess = unittest.mock.Mock(return_value=0)

            def venv_status(_vpy):
                current_home = next(
                    line.split("=", 1)[1].strip()
                    for line in cfg.read_text(encoding="utf-8").splitlines()
                    if line.lower().startswith("home")
                )
                if os.path.normcase(current_home) == os.path.normcase(str(installed_base)):
                    return True, "3.10.11"
                return False, "venv 指向的 Python 已不存在（No Python at ...），venv 已损坏"

            def available_python_version(path):
                return ("3.10.11", (3, 10, 11)) if os.path.normcase(path) == os.path.normcase(str(candidate)) else (None, None)

            ensure_deps = unittest.mock.Mock(return_value=False)
            with patch.object(legacy, "_pick_preprocess_python", return_value=str(vpy)), \
                    patch.object(legacy, "_venv_python_ok", side_effect=venv_status), \
                    patch.object(legacy, "_ensure_preprocess_deps", ensure_deps), \
                    patch.object(core_utils, "_installed_python_candidates", return_value=[str(candidate)]), \
                    patch("kohya_core.utils._repair_candidate_python_version", side_effect=available_python_version), \
                    patch.object(core_utils.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")), \
                    patch.object(legacy, "get_kohya_dir", return_value=str(kernel)), \
                    patch.object(legacy, "run_stream", run_preprocess):
                with self.assertRaisesRegex(RuntimeError, "训练环境已损坏"):
                    legacy.preprocess(
                        input_dir=str(input_dir), project="fixture", wd14=False,
                        logf=lambda _line: None,
                    )

            self.assertEqual(cfg.read_bytes(), original)
            ensure_deps.assert_called_once()
            run_preprocess.assert_not_called()


if __name__ == "__main__":
    unittest.main()
