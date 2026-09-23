# -*- coding: utf-8 -*-
"""三引擎安装流程回归测试（不下载数 GB PyTorch，不修改真实训练环境）。

覆盖源码解压、venv 创建/损坏重建、pip 自愈调用、Torch 版本锁定、
依赖约束文件和最终验证分支。真实依赖导入仍由 smoke_test.py 与本机环境验证承担。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import Kohya一键工具 as core

ROOT = Path(__file__).resolve().parent

def result(code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)

def fake_python(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")

def common_patches(kdir: Path):
    cache = kdir.parent / "cache"
    return (
        patch.object(core, "get_kohya_dir", return_value=str(kdir)),
        patch.object(core, "data_sub", side_effect=lambda *parts: str(cache.joinpath(*parts))),
        patch.object(core, "find_git", return_value=(r"C:\Program Files\Git\cmd\git.exe")),
        patch.object(core, "find_python", return_value=(r"C:\Python312\python.exe", "3.12")),
        patch.object(core, "_acquire_kohya_install_lock", return_value=SimpleNamespace()),
        patch.object(core, "_release_kohya_install_lock", return_value=None),
        patch.object(core, "detect_gpu_vendor", return_value="nvidia"),
    )

def test_main_engine(base: Path):
    kdir = base / "main" / "kohya_ss"
    state = {"torch": False, "setup": False, "deps": False}
    logs = []

    def run_stream(cmd, cwd=None, env=None, logf=print, **kwargs):
        cmd = [str(x) for x in cmd]
        if len(cmd) >= 4 and cmd[1:3] == ["-m", "venv"]:
            target = Path(cwd) / cmd[3] if not os.path.isabs(cmd[3]) else Path(cmd[3])
            fake_python(target / "Scripts" / "python.exe")
            return 0
        if any("setup_windows.py" in x for x in cmd):
            state["setup"] = True
            state["deps"] = True
            return 0
        return 0

    def subrun(cmd, *args, **kwargs):
        cmd = [str(x) for x in cmd]
        code = cmd[2] if len(cmd) > 2 and cmd[1] == "-c" else ""
        if "print(torch.version.cuda" in code:
            return result(0, "2.7.0+cu128\n12.8\nTrue\n")
        if "assert torch.cuda.is_available" in code or "import torch" in code:
            return result(0 if state["torch"] else 1, "2.7.0+cu128\n" if state["torch"] else "")
        if "import PIL, numpy" in code:
            return result(0 if state["deps"] else 1)
        return result(0)

    def preinstall(*args, **kwargs):
        state["torch"] = True
        return True

    patches = common_patches(kdir) + (
        patch.object(core, "KOHYA_DIR_FILE", str(base / "main" / "kohya_dir.txt")),
        patch.object(core, "_bundled_kohya_zip", return_value=str(ROOT / "installers" / "kohya_ss" / "kohya_ss-master.zip")),
        patch.object(core, "_bundled_sd_zip", return_value=str(ROOT / "installers" / "kohya_ss" / "sd-scripts-main.zip")),
        patch.object(core, "run_stream", side_effect=run_stream),
        patch.object(core.subprocess, "run", side_effect=subrun),
        patch.object(core, "_upgrade_pip", return_value=True),
        patch.object(core, "_ensure_venv_pip", return_value=True),
        patch.object(core, "_preinstall_torch", side_effect=preinstall),
        patch.object(core, "_ensure_kohya_deps", side_effect=lambda *a, **k: state.__setitem__("deps", True) or True),
        patch.object(core, "venv_python_version", return_value="3.12"),
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patches[12], patches[13], patches[14], patches[15]:
        out = core.install_kohya(logs.append)
    assert Path(out) == kdir
    assert state["torch"] and state["setup"] and state["deps"]
    assert (kdir / "sd-scripts" / "sdxl_train_network.py").is_file()
    print("MAIN_ENGINE_FULL_FLOW_OK")

def test_kohya_coexist_with_other_engines(base: Path):
    """先装第二/三引擎（musubi/ai-toolkit 已在 kohya_ss 目录内）再装第一引擎：不再误报「目标目录非空且不是 kohya_ss」。"""
    kdir = base / "coexist" / "kohya_ss"
    # 模拟第二/三引擎已装进同一个 kdir（真实场景：musubi-venv / ai-toolkit 等子目录）
    (kdir / "musubi-tuner").mkdir(parents=True, exist_ok=True)
    (kdir / "musubi-venv").mkdir(parents=True, exist_ok=True)
    (kdir / "ai-toolkit").mkdir(parents=True, exist_ok=True)
    (kdir / "ai_toolkit_venv").mkdir(parents=True, exist_ok=True)
    assert core._kohya_dir_has_foreign_content(str(kdir)) is False, "共存子目录被误判为陌生内容"

    state = {"torch": False, "setup": False, "deps": False}
    logs = []

    def run_stream(cmd, cwd=None, env=None, logf=print, **kwargs):
        cmd = [str(x) for x in cmd]
        if len(cmd) >= 4 and cmd[1:3] == ["-m", "venv"]:
            target = Path(cwd) / cmd[3] if not os.path.isabs(cmd[3]) else Path(cmd[3])
            fake_python(target / "Scripts" / "python.exe")
            return 0
        if any("setup_windows.py" in x for x in cmd):
            state["setup"] = True
            state["deps"] = True
            return 0
        return 0

    def subrun(cmd, *args, **kwargs):
        cmd = [str(x) for x in cmd]
        code = cmd[2] if len(cmd) > 2 and cmd[1] == "-c" else ""
        if "print(torch.version.cuda" in code:
            return result(0, "2.7.0+cu128\n12.8\nTrue\n")
        if "assert torch.cuda.is_available" in code or "import torch" in code:
            return result(0 if state["torch"] else 1, "2.7.0+cu128\n" if state["torch"] else "")
        if "import PIL, numpy" in code:
            return result(0 if state["deps"] else 1)
        return result(0)

    def preinstall(*args, **kwargs):
        state["torch"] = True
        return True

    patches = common_patches(kdir) + (
        patch.object(core, "KOHYA_DIR_FILE", str(base / "coexist" / "kohya_dir.txt")),
        patch.object(core, "_bundled_kohya_zip", return_value=str(ROOT / "installers" / "kohya_ss" / "kohya_ss-master.zip")),
        patch.object(core, "_bundled_sd_zip", return_value=str(ROOT / "installers" / "kohya_ss" / "sd-scripts-main.zip")),
        patch.object(core, "run_stream", side_effect=run_stream),
        patch.object(core.subprocess, "run", side_effect=subrun),
        patch.object(core, "_upgrade_pip", return_value=True),
        patch.object(core, "_ensure_venv_pip", return_value=True),
        patch.object(core, "_preinstall_torch", side_effect=preinstall),
        patch.object(core, "_ensure_kohya_deps", side_effect=lambda *a, **k: state.__setitem__("deps", True) or True),
        patch.object(core, "venv_python_version", return_value="3.12"),
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patches[12], patches[13], patches[14], patches[15]:
        out = core.install_kohya(logs.append)
    assert Path(out) == kdir
    assert (kdir / "sd-scripts" / "sdxl_train_network.py").is_file()
    # 其它引擎子目录保留（未被误删）
    assert (kdir / "ai-toolkit").is_dir() and (kdir / "musubi-tuner").is_dir()
    print("KOHYA_COEXIST_WITH_OTHER_ENGINES_OK")

def test_kohya_foreign_content_still_blocks(base: Path):
    """kohya_ss 目录里有陌生文件（非 kohya 也非第二/三引擎）时仍应阻止安装（防呆保留）。"""
    kdir = base / "foreign" / "kohya_ss"
    kdir.mkdir(parents=True, exist_ok=True)
    (kdir / "unrelated_file.txt").write_text("x", encoding="utf-8")
    assert core._kohya_dir_has_foreign_content(str(kdir)) is True, "陌生文件未识别"
    # 空目录 / 不存在 → False（可安装）
    assert core._kohya_dir_has_foreign_content(str(base / "empty_dir")) is False
    print("KOHYA_FOREIGN_CONTENT_STILL_BLOCKS_OK")

def test_second_engine(base: Path):
    kdir = base / "second" / "kohya_ss"
    state = {"torch": False, "editable": False}
    logs = []

    def run_stream(cmd, cwd=None, env=None, logf=print, **kwargs):
        cmd = [str(x) for x in cmd]
        if len(cmd) >= 4 and cmd[1:3] == ["-m", "venv"]:
            fake_python(Path(cmd[3]) / "Scripts" / "python.exe")
            return 0
        if "-e" in cmd:
            ci = cmd.index("-c")
            constraints = Path(cmd[ci + 1]).read_text(encoding="utf-8")
            assert "torch==2.7.1" in constraints and "torchvision==0.22.1" in constraints
            state["editable"] = True
        return 0

    def pair_check(vpy):
        if state["torch"]:
            return True, "torch 2.7.1 + torchvision 0.22.1 + cu128 + CUDA 可用"
        return False, "torch 未安装"

    def subrun(cmd, *args, **kwargs):
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "print(torch.__version__)" in code and state["editable"]:
            return result(0, "2.7.1+cu128\nTrue\n")
        if "musubi_tuner" in code:
            return result(0 if state["editable"] else 1)
        return result(0)

    def preinstall(*args, **kwargs):
        assert kwargs.get("torch_ver") == "2.7.1"
        assert kwargs.get("tv_ver") == "0.22.1"
        assert kwargs.get("force") is True
        state["torch"] = True
        return True

    patches = common_patches(kdir) + (
        patch.object(core, "_bundled_musubi_zip", return_value=str(ROOT / "installers" / "musubi-tuner" / "musubi-tuner-main.zip")),
        patch.object(core, "run_stream", side_effect=run_stream),
        patch.object(core.subprocess, "run", side_effect=subrun),
        patch.object(core, "_upgrade_pip", return_value=True),
        patch.object(core, "_ensure_venv_pip", return_value=True),
        patch.object(core, "_musubi_torch_pair_check", side_effect=pair_check),
        patch.object(core, "_preinstall_torch", side_effect=preinstall),
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patches[12], patches[13]:
        out = core.install_musubi_engine(logs.append)
    assert Path(out) == kdir / "musubi-venv" / "Scripts" / "python.exe"
    assert state["torch"] and state["editable"]
    assert (kdir / "musubi-tuner" / "krea2_train_network.py").is_file()
    print("SECOND_ENGINE_FULL_FLOW_OK")

def test_second_engine_without_git(base: Path):
    """内置 musubi 源码存在时，Git 缺失不应阻塞安装。"""
    kdir = base / "second_no_git" / "kohya_ss"
    state = {"torch": False, "editable": False}

    def run_stream(cmd, cwd=None, env=None, logf=print, **kwargs):
        cmd = [str(x) for x in cmd]
        if len(cmd) >= 4 and cmd[1:3] == ["-m", "venv"]:
            fake_python(Path(cmd[3]) / "Scripts" / "python.exe")
        if "-e" in cmd:
            state["editable"] = True
        return 0

    def pair_check(vpy):
        return ((True, "ok") if state["torch"] else (False, "torch 未安装"))

    def subrun(cmd, *args, **kwargs):
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "print(torch.__version__)" in code and state["editable"]:
            return result(0, "2.7.1+cu128\nTrue\n")
        if "musubi_tuner" in code:
            return result(0 if state["editable"] else 1)
        return result(0)

    def preinstall(*args, **kwargs):
        state["torch"] = True
        return True

    patches = common_patches(kdir) + (
        patch.object(core, "find_git", return_value=None),
        patch.object(core, "_bundled_musubi_zip", return_value=str(ROOT / "installers" / "musubi-tuner" / "musubi-tuner-main.zip")),
        patch.object(core, "run_stream", side_effect=run_stream),
        patch.object(core.subprocess, "run", side_effect=subrun),
        patch.object(core, "_upgrade_pip", return_value=True),
        patch.object(core, "_ensure_venv_pip", return_value=True),
        patch.object(core, "_musubi_torch_pair_check", side_effect=pair_check),
        patch.object(core, "_preinstall_torch", side_effect=preinstall),
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patches[12], patches[13], patches[14]:
        core.install_musubi_engine(lambda _: None)
    assert state["torch"] and state["editable"]
    print("SECOND_ENGINE_BUNDLED_SOURCE_WITHOUT_GIT_OK")

def make_source_zip(path: Path, root: str, files: dict[str, str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(f"{root}/{name}", content)

def test_third_engine(base: Path):
    kdir = base / "third" / "kohya_ss"
    av = kdir / "ai_toolkit_venv"
    fake_python(av / "Scripts" / "python.exe")
    (av / "pyvenv.cfg").write_text("home = X:\\MissingPython\n", encoding="utf-8")

    src_zip = base / "sources" / "ai-toolkit.zip"
    diff_zip = base / "sources" / "diffusers.zip"
    make_source_zip(src_zip, "ai-toolkit-main", {
        "run.py": "print('ok')\n",
        "requirements.txt": "numpy\nscipy==1.12.0\ngit+https://github.com/huggingface/diffusers.git\ntransformers\n",
        "toolkit/config_modules.py": "class ModelConfig: pass\n",
        "extensions_built_in/diffusion_models/minimax_h3.py": "class MinimaxH3Model: pass\n",
    })
    make_source_zip(diff_zip, "diffusers-test", {"pyproject.toml": "[project]\nname='diffusers'\nversion='0.0.0'\n"})
    state = {"rebuilt": False, "torch": False, "deps": False, "diffusers": False}
    logs = []

    def run_stream(cmd, cwd=None, env=None, logf=print, **kwargs):
        cmd = [str(x) for x in cmd]
        if len(cmd) >= 4 and cmd[1:3] == ["-m", "venv"]:
            target = Path(cmd[3])
            fake_python(target / "Scripts" / "python.exe")
            state["rebuilt"] = True
            return 0
        if "--no-deps" in cmd:
            state["diffusers"] = True
            return 0
        if "-r" in cmd:
            req = Path(cmd[cmd.index("-r") + 1]).read_text(encoding="utf-8")
            constraints = Path(cmd[cmd.index("-c") + 1]).read_text(encoding="utf-8")
            assert "scipy==1.12.0" not in req and "git+https://" not in req
            assert "numpy==2.1.3" in req and "scipy==1.15.3" in req
            assert "2.5.2" not in req and "1.18.0" not in req  # numpy 2.5.x 只有 cp312 轮子
            assert "numpy==2.1.3" in constraints and "scipy==1.15.3" in constraints
            assert "2.5.2" not in constraints and "1.18.0" not in constraints
            for wanted in ("torch==2.13.0", "torchvision==0.28.0", "torchaudio==2.11.0", "numpy==2.1.3", "scipy==1.15.3"):
                assert wanted in constraints
            state["deps"] = True
            return 0
        return 0

    def subrun(cmd, *args, **kwargs):
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "MinimaxH3Model" in code:
            return result(0 if state["deps"] else 1, "2.13.0+cu130\n" if state["deps"] else "")
        if "toolkit.config_modules" in code:
            return result(0 if state["deps"] else 1)
        return result(0)

    def preinstall(*args, **kwargs):
        assert kwargs.get("torch_ver") == "2.13.0"
        assert kwargs.get("tv_ver") == "0.28.0"
        assert kwargs.get("ta_ver") == "2.11.0"
        assert kwargs.get("cu") == "cu130"
        state["torch"] = True
        return True

    patches = common_patches(kdir) + (
        patch.object(core, "at_custom_dir", return_value=""),
        patch.object(core, "nvidia_driver_version", return_value=999),
        patch.object(core, "_download_engine_source", side_effect=lambda name, logf=print: str(src_zip if name == "ai-toolkit" else diff_zip)),
        patch.object(core, "run_stream", side_effect=run_stream),
        patch.object(core.subprocess, "run", side_effect=subrun),
        patch.object(core, "_upgrade_pip", return_value=True),
        patch.object(core, "_ensure_venv_pip", return_value=True),
        patch.object(core, "_venv_python_ok", return_value=(False, "venv 指向的 Python 已不存在")),
        patch.object(core, "_preinstall_torch", side_effect=preinstall),
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patches[12], patches[13], patches[14], patches[15]:
        out = core.install_ai_toolkit_engine(logs.append)
    assert Path(out) == av / "Scripts" / "python.exe"
    assert state["rebuilt"] and state["torch"] and state["diffusers"] and state["deps"]
    assert any(kdir.glob("ai_toolkit_venv_broken_*"))
    assert any("已损坏" in line for line in logs)
    print("THIRD_ENGINE_FULL_FLOW_AND_BROKEN_VENV_RECOVERY_OK")

def test_third_engine_amd(base: Path):
    """AI Toolkit AMD install: separate Python 3.12 ROCm path, filtered BNB and GPU verification."""
    import contextlib
    kdir = base / "third_amd" / "kohya_ss"
    av = kdir / "ai_toolkit_venv"
    src_zip = base / "sources" / "ai-toolkit-amd.zip"
    diff_zip = base / "sources" / "diffusers-amd.zip"
    make_source_zip(src_zip, "ai-toolkit-main", {
        "run.py": "print('ok')\n",
        "requirements.txt": "numpy\nscipy==1.12.0\nbitsandbytes>=0.48\ntorchao==0.10.0\ntorchcodec==0.9.1\ntransformers\n",
        "toolkit/config_modules.py": "class ModelConfig: pass\n",
        "extensions_built_in/diffusion_models/minimax_h3.py": "class MinimaxH3Model: pass\n",
    })
    make_source_zip(diff_zip, "diffusers-test", {"pyproject.toml": "[project]\nname='diffusers'\nversion='0.0.0'\n"})
    state = {"venv": False, "runtime": False, "diffusers": False, "deps": False,
             "preinstall_torch": False, "constraints": "", "requirements": "", "cmd": []}
    logs = []

    def run_stream(cmd, cwd=None, env=None, logf=print, **kwargs):
        cmd = [str(x) for x in cmd]
        state["cmd"].append(cmd)
        if len(cmd) >= 4 and cmd[1:3] == ["-m", "venv"]:
            fake_python(Path(cmd[3]) / "Scripts" / "python.exe")
            state["venv"] = True
            return 0
        if "--no-deps" in cmd:
            state["diffusers"] = True
            return 0
        if "-r" in cmd:
            req = Path(cmd[cmd.index("-r") + 1]).read_text(encoding="utf-8")
            constraints = Path(cmd[cmd.index("-c") + 1]).read_text(encoding="utf-8")
            state["requirements"] = req
            state["constraints"] = constraints
            assert "bitsandbytes" not in req.lower(), req
            assert "torchcodec" not in req.lower(), req
            assert "torchao==0.17.0" in req and "torchao==0.10.0" not in req, req
            assert "torch==" + core.FIZGIG_ROCM_TORCH_PIN in constraints, constraints
            assert "torchvision==" + core.FIZGIG_ROCM_TORCHVISION_PIN in constraints, constraints
            assert "setuptools<82" in constraints, constraints
            assert core.FIZGIG_ROCM_INDEX in cmd, cmd
            state["deps"] = True
            return 0
        return 0

    def subrun(cmd, *args, **kwargs):
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "HIP=" in code:
            if not state["deps"]:
                return result(1, "", "torch unavailable")
            return result(0, "TORCH=2.12.0+rocm7.15.0a20260728\nHIP=7.15.0\nCUDA=\nAVAILABLE=True\nDEVICE=AMD Radeon Test\nKERNEL=ok\n")
        if "MinimaxH3Model" in code:
            return result(0 if state["deps"] else 1, "2.12.0+rocm7.15.0a20260728\n")
        if "toolkit.config_modules" in code:
            return result(0 if state["deps"] else 1, "ok\n")
        return result(0)

    def fake_rocm_install(vpy, at_dir, logf=print, label="训练引擎"):
        assert label == "第三引擎"
        assert Path(vpy) == av / "Scripts" / "python.exe"
        state["runtime"] = True
        return "gfx1100"

    def forbidden_cuda(*args, **kwargs):
        state["preinstall_torch"] = True
        raise AssertionError("AMD flow must not preinstall CUDA torch")

    patches = common_patches(kdir) + (
        patch.object(core, "detect_gpu_vendor", return_value="amd"),
        patch.object(core, "_engine_ensure_python312", return_value=r"C:\Python312\python.exe"),
        patch.object(core, "at_custom_dir", return_value=""),
        patch.object(core, "_download_engine_source", side_effect=lambda name, logf=print: str(src_zip if name == "ai-toolkit" else diff_zip)),
        patch.object(core, "run_stream", side_effect=run_stream),
        patch.object(core.subprocess, "run", side_effect=subrun),
        patch.object(core, "_upgrade_pip", return_value=True),
        patch.object(core, "_ensure_venv_pip", return_value=True),
        patch.object(core, "_install_windows_amd_rocm_runtime", side_effect=fake_rocm_install),
        patch.object(core, "_preinstall_torch", side_effect=forbidden_cuda),
        patch.object(core, "_ai_toolkit_rocm_env", return_value={"PATH": "C:\\rocm\\bin"}),
    )
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        out = core.install_ai_toolkit_engine(logs.append)
    assert Path(out) == av / "Scripts" / "python.exe"
    assert state["venv"] and state["runtime"] and state["diffusers"] and state["deps"]
    assert not state["preinstall_torch"]
    assert any("AI Toolkit 可用（AMD ROCm 实验通道）" in line for line in logs), logs
    print("THIRD_ENGINE_AMD_ROCM_INSTALL_AND_GPU_VERIFICATION_OK")

def test_third_engine_amd_torchvision_guard():
    """A missing ROCm torchvision must never trigger installation of a CUDA/cu128 wheel."""
    calls = []
    responses = [result(1, "", "torchvision missing"), result(0, "2.12.0+rocm7.15\n7.15.0\n")]
    with patch.object(core.subprocess, "run", side_effect=lambda *a, **k: responses.pop(0)), \
         patch.object(core, "run_stream", side_effect=lambda *a, **k: calls.append(a) or 0):
        ok = core._ensure_torchvision_deps(r"X:\ai_toolkit_venv\Scripts\python.exe", lambda _: None,
                                           label="第三引擎")
    assert ok is False
    assert not calls, calls
    print("THIRD_ENGINE_AMD_TORCHVISION_NEVER_INSTALLS_CUDA_OK")

def test_amd_gpu_arch_mapping():
    """AMD ROCm wheel selection must use the GPU's documented gfx target."""
    cases = {
        "AMD Radeon RX 7900 XTX": "gfx1100",
        "AMD Radeon RX 7800 XT": "gfx1101",
        "AMD Radeon RX 7700 XT": "gfx1101",
        "AMD Radeon RX 6950 XT": "gfx1030",
        "AMD Radeon RX 6750 XT": "gfx1031",
        "AMD Radeon RX 6650 XT": "gfx1032",
        "AMD Radeon RX 7650 GRE": "gfx1102",
        "AMD Radeon RX 7600 XT": "gfx1102",
        "AMD Radeon RX 9070 XT": "gfx1201",
        "AMD Radeon RX 9060 XT": "gfx1200",
        "AMD Radeon PRO W7800": "gfx1100",
        "AMD Ryzen AI Max+ 395": "gfx1151",
    }
    for name, expected in cases.items():
        with patch.object(core, "detect_gpu_name", return_value=name):
            assert core._amd_gpu_arch(r"X:\missing_engine", lambda _: None) == expected, name
    print("AMD_ROCM_GPU_ARCH_SELECTION_OK")

def test_amd_arch_probe_not_polluted_by_hsa_override():
    """★ 2026-09-23（RX 7800 XT 装错包的根因）：探测架构时必须绕开 HSA_OVERRIDE_GFX_VERSION ✗

    完整事故链（用户日志 KohyaLoRA_Frieren1_20260923，RX 7800 XT = gfx1101）：
      ① 用户照老教程设 HSA_OVERRIDE_GFX_VERSION=11.0.0（把 gfx1101 伪装成 gfx1100）
      ② 安装时 detect_gpu.py 去问 HIP → 得到**假的** gfx1100 ✗
      ③ pip 按 gfx1100 装包（site-packages 里确实是 rocm_sdk_device_gfx1100 ✓）
      ④ 训练第一步 VAE 卷积 → `hipErrorInvalidImage` ✗
         （而"装的时候验证是通过的" ✗ —— 那次只测了矩阵乘 ✗）

    判据：
      · 脚本被带偏（报 gfx1100）而显卡名是 7800 XT → 必须返回 **gfx1101** ✓
      · 跑脚本时**必须**把 HSA_OVERRIDE_GFX_VERSION 从子进程环境里去掉 ✓
      · 名字表里没有的卡（脚本是唯一线索）→ 仍以脚本为准 ✓
    """
    with tempfile.TemporaryDirectory(prefix="archprobe_") as td:
        eng = Path(td)
        (eng / "detect_gpu.py").write_text("print('gfx1100')\n", encoding="utf-8")
        seen = {}

        def _run(cmd, *a, **k):
            seen["env"] = dict(k.get("env") or {})
            return result(0, "gfx1100\n")

        with patch.object(core, "detect_gpu_name", return_value="AMD Radeon RX 7800 XT"), \
             patch.object(core.subprocess, "run", side_effect=_run), \
             patch.dict(os.environ, {"HSA_OVERRIDE_GFX_VERSION": "11.0.0"}):
            arch = core._amd_gpu_arch(str(eng), lambda _s: None)
        assert arch == "gfx1101", \
            "探测脚本被 override 带偏时必须**以显卡名为准** ✗（得到 %s）" % arch
        assert "HSA_OVERRIDE_GFX_VERSION" not in (seen.get("env") or {}), \
            "跑 detect_gpu.py 时必须屏蔽 HSA_OVERRIDE_GFX_VERSION ✗ 否则永远探测到假架构"

        # 名字表里没有的新卡：脚本是唯一线索 ✓
        with patch.object(core, "detect_gpu_name", return_value="AMD Radeon RX 9999 XT"), \
             patch.object(core.subprocess, "run", side_effect=_run):
            assert core._amd_gpu_arch(str(eng), lambda _s: None) == "gfx1100"
    print("AMD_ARCH_PROBE_NOT_POLLUTED_BY_OVERRIDE_OK")

def test_amd_mirror_only_for_gfx1100():
    """★ 2026-09-23 修：魔搭那套 wheel 是 gfx1100 构建 ✗ —— 非 gfx1100 的卡不许再用它 ✓

    背景：魔搭预存 wheel 文件名里没有架构后缀，元数据固定拉 `rocm_sdk_device_gfx1100` ✗
      → RX 7800 XT（gfx1101）装上去后 MIOpen 卷积 kernel 对不上
      → 训练第一步 VAE 编码 `hipErrorInvalidImage` ✗（白折腾一整晚 ✓）

    判据：gfx1101 → **不下载**魔搭 wheel ✓，pip 走 `torch[device-gfx1101]` ✓
          gfx1100 → 仍走魔搭（国内快速路径不能丢 ✓）
    """
    for _arch, _want_mirror in (("gfx1101", False), ("gfx1100", True)):
        with tempfile.TemporaryDirectory(prefix="amdflow_") as td:
            eng = Path(td) / "fizgig"
            eng.mkdir(parents=True)
            vpy = str(Path(td) / "fizgig_venv" / "Scripts" / "python.exe")
            fake_python(Path(vpy))
            downloads, pips, logs = [], [], []

            def _run_stream(cmd, cwd=None, env=None, logf=print, **kw):
                pips.append([str(x) for x in cmd])
                return 0

            def _dl(url, dest, *a, **k):
                downloads.append(os.path.basename(str(dest)))
                return True

            with patch.object(core, "_amd_gpu_arch", return_value=_arch), \
                 patch.object(core, "run_stream", side_effect=_run_stream), \
                 patch.object(core, "_download_with_resume", side_effect=_dl), \
                 patch.object(core, "_wheel_valid", return_value=True), \
                 patch.object(core, "_engine_source_cache_dir", return_value=os.path.join(td, "cache")), \
                 patch.object(core, "_domestic_pip_env", return_value={}), \
                 patch.object(core, "build_direct_env", return_value={}), \
                 patch.object(core, "_amd_device_pkgs", return_value=[]):
                core._install_windows_amd_rocm_runtime(vpy, str(eng), logs.append, "第四引擎")
            _flat = " ".join(" ".join(c) for c in pips)
            _txt = " ".join(logs)
            if _want_mirror:
                assert downloads, "gfx1100 应保留魔搭国内快速路径 ✗"
                assert "魔搭" in _txt, logs
            else:
                # ⚠️ bitsandbytes 是**单独**从各自来源取的（两边都要 ✓），
                #   这里只关心"魔搭那套 ROCm/torch wheel"有没有被误用 ✗
                _rocm_dl = [d for d in downloads if "bitsandbytes" not in d]
                assert not _rocm_dl, \
                    "非 gfx1100 不该下载魔搭那套 gfx1100 wheel ✗（下到了 %s）" % _rocm_dl
                assert ("torch[device-%s]" % _arch) in _flat, _flat
                assert "gfx1100 构建" in _txt, logs
    print("AMD_MIRROR_ONLY_FOR_GFX1100_OK")

def test_amd_device_pkg_and_override_checks():
    """device 包架构核对 + HSA_OVERRIDE_GFX_VERSION 解析（本轮两处新护栏）✓

    · `_hsa_override_arch`：`11.0.0`/`11.0`→gfx1100、`10.3.0`→gfx1030、`11.0.1`→gfx1101、
      `gfx1101`→gfx1101、未设置→None ✓（解析错会误报/漏报 ✓）
    · `_warn_amd_arch_mismatch`：真 venv 里放**假 dist-info** ✓
      - 只有 gfx1100 包、卡是 gfx1101 → 必须报警 ✓ 且提示含「安装第四引擎」✓
      - 有 `gfx110x` 通配包 → 视为覆盖 1101 ✓ 不报 ✓（否则 7700/7600 会被误伤 ✗）
    · `_warn_hsa_override`：架构不符时必须说清**怎么删**（上次用户就是忘了删持久变量 ✓）
    """
    def _sil(*a, **k):
        return None

    assert core._hsa_override_arch() is None, "未设变量时应返回 None"
    for _v, _want in (("11.0.0", "gfx1100"), ("11.0", "gfx1100"), ("10.3.0", "gfx1030"),
                      ("11.0.1", "gfx1101"), ("gfx1101", "gfx1101")):
        with patch.dict(os.environ, {"HSA_OVERRIDE_GFX_VERSION": _v}):
            assert core._hsa_override_arch() == _want, (_v, core._hsa_override_arch())

    with tempfile.TemporaryDirectory(prefix="devpkg_") as td:
        vpy = str(Path(td) / "venv" / "Scripts" / "python.exe")
        fake_python(Path(vpy))
        sp = Path(td) / "venv" / "Lib" / "site-packages"
        sp.mkdir(parents=True, exist_ok=True)
        (sp / "rocm_sdk_device_gfx1100-7.15.dist-info").mkdir()
        assert core._amd_device_pkgs(vpy) == ["rocm_sdk_device_gfx1100-7.15"], core._amd_device_pkgs(vpy)
        _logs = []
        _ok, _pkgs, _hint = core._warn_amd_arch_mismatch(vpy, "gfx1101", _logs.append)
        assert not _ok and "安装第四引擎" in _hint, _hint
        assert any("不一致" in _ln for _ln in _logs), _logs
        (sp / "amd_torch_device_gfx110x-2.12.dist-info").mkdir()
        assert core._warn_amd_arch_mismatch(vpy, "gfx1101", _sil)[0] is True, \
            "gfx110x 是通配包（覆盖 1100/1101/1102）✗ 不该误报 ✗"

    with patch.dict(os.environ, {"HSA_OVERRIDE_GFX_VERSION": "11.0.0"}):
        _l2 = []
        core._warn_hsa_override("gfx1101", _l2.append)
        _t2 = "".join(_l2)
        assert "Remove-Item" in _t2 and "SetEnvironmentVariable" in _t2, _t2
        _l3 = []
        core._warn_hsa_override("gfx1100", _l3.append)
        assert not _l3, "与本机架构一致时不该报警 ✗"
    print("AMD_DEVICE_PKG_AND_OVERRIDE_CHECKS_OK")

def test_amd_gpu_kernel_check_detects_broken_gpu():
    """卷积自检必须能**抓住"GPU 卷积不可用"** ✗ —— 这是本次事故的直接信号 ✓

    用**真 python** 跑一遍：本机没有可用 CUDA/ROCm 时 `device='cuda'` 必然失败 ✓
      · 必须返回 ok=False ✓（抓不住就等于白加 ✗）
      · detail 要说清"后果 + 怎么修"（VAE / 重装 / 换 musubi ✓）
      · 且**不能抛异常** ✗（它要在训练前安全调用 ✓）
    """
    _logs = []
    # ① 打桩成"卷积失败"（不依赖本机有没有 GPU ✓）→ 必须判定 False ✓ 且给出修法 ✓
    _fake = result(0, "INFO|archs=gfx1100,cap=11.0,dev=AMD Radeon RX 7800 XT\n"
                      "CONV|FAIL|AcceleratorError: CUDA error: device kernel image is invalid\n")
    with patch.object(core, "_amd_device_pkgs", return_value=["rocm_sdk_device_gfx1100-7.15"]), \
         patch.object(core.subprocess, "run", return_value=_fake):
        ok, detail = core._amd_gpu_kernel_check(r"X:\v\Scripts\python.exe", {}, _logs.append, "自检")
    assert ok is False, "卷积失败时必须判定 False ✗（否则等于没查 ✗）"
    assert "VAE" in detail and "安装第四引擎" in detail, detail[:300]
    assert "rocm_sdk_device_gfx1100" in detail, "应把已装的 device 包列出来（诊断用）✗：" + detail[:300]
    assert any("GPU" in _ln for _ln in _logs), _logs

    # ② 「自检自己没跑成」时**绝不能拦训练** ✗ —— v0.17.11 误伤事件的教训 ✓
    #    （打桩：python 跑起来了、也有输出，但没有 CONV 结论）
    _l3 = []
    with patch.object(core.subprocess, "run",
                      return_value=result(0, "2.12.0+rocm7.15.0a20260728\nok=True\n")):
        ok3, _d3 = core._amd_gpu_kernel_check(r"X:\v\Scripts\python.exe", {}, _l3.append, "自检")
    assert ok3 is True, \
        "自检没取得结论时必须**放行** ✗（防误伤 —— v0.17.11 就是误拦把正常用户卡住的 ✓）"

    # ③ 真跑一次（本机环境）：**不允许抛异常** ✗ —— 它要在训练前安全调用 ✓
    _logs2 = []
    try:
        core._amd_gpu_kernel_check(sys.executable, None, _logs2.append, "自检")
    except Exception as _e:
        raise AssertionError("GPU 卷积自检不允许抛异常 ✗：%r" % _e)
    print("AMD_GPU_KERNEL_CHECK_CATCHES_BROKEN_GPU_OK")

def test_fizgig_amd_preflight_blocks_early():
    """训练前的 AMD 体检：卷积不过时必须**拦下**（而不是白跑完缓存才炸 ✗）✓"""
    with patch.object(core, "_amd_gpu_kernel_check", return_value=(False, "GPU 卷积自检未通过 ✗")), \
         patch.object(core, "_warn_hsa_override") as _w1, \
         patch.object(core, "_warn_amd_arch_mismatch") as _w2:
        ok, detail = core._fizgig_amd_preflight(r"X:\v\Scripts\python.exe", r"X:\fz", {},
                                                lambda _s: None)
    assert ok is False and "卷积" in detail, detail
    assert not _w1.called and not _w2.called, "卷积都不通过时不必再做后续检查 ✓"
    print("FIZGIG_AMD_PREFLIGHT_BLOCKS_EARLY_OK")

def test_optimizer_resolution(base: Path):
    """resolve_optimizer / _probe_adamw8bit / _probe_lion / _optimizer_yaml_name 单元测试（mock 子进程，不真实运行 CUDA）。"""
    logs = []
    vpy = str(base / "venv" / "Scripts" / "python.exe")

    def probe_result(out, rc):
        return subprocess.CompletedProcess([], rc, out, "")

    # 1) AdamW8bit 预检通过 -> AdamW8bit
    with patch.object(core.subprocess, "run", return_value=probe_result("OK\n", 0)):
        opt, _ = core.resolve_optimizer(vpy, logs.append, requested="auto")
    assert opt == "AdamW8bit", opt

    # 2) AdamW8bit 预检失败（DLL 缺失）+ Lion 真实 step 预检通过 -> Lion
    def subrun_lion_ok(cmd, *args, **kwargs):
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "import lion_pytorch" in code:
            return probe_result("OK\n", 0)  # Lion 真实 step 成功
        if "bitsandbytes" in code:
            return probe_result("Error: libbitsandbytes_cuda128.dll missing\n", 1)
        return probe_result("", 0)
    with patch.object(core.subprocess, "run", side_effect=subrun_lion_ok):
        opt, _ = core.resolve_optimizer(vpy, logs.append, requested="auto")
    assert opt == "Lion", opt

    # 3) AdamW8bit 预检失败 + Lion 预检失败（真实 step 崩）-> AdamW
    def subrun_lion_bad(cmd, *args, **kwargs):
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "import lion_pytorch" in code:
            return probe_result("AttributeError: ... incompatible\n", 1)  # Lion 真实 step 失败
        if "bitsandbytes" in code:
            return probe_result("str2optimizer8bit_blockwise is not defined\n", 1)
        return probe_result("", 0)
    with patch.object(core.subprocess, "run", side_effect=subrun_lion_bad):
        opt, _ = core.resolve_optimizer(vpy, logs.append, requested="auto")
    assert opt == "AdamW", opt
    assert any("Lion 预检失败" in ln for ln in logs), logs

    # 4) AMD 模式固定 AdamW（不调用子进程）
    with patch.object(core.subprocess, "run", side_effect=AssertionError("AMD 模式不应调用子进程")):
        opt, _ = core.resolve_optimizer(vpy, logs.append, requested="auto", amd_mode=True)
    assert opt == "AdamW", opt

    # 5) 用户明确指定 adamw -> AdamW（不调用子进程）
    with patch.object(core.subprocess, "run", side_effect=AssertionError("指定 adamw 不应调用子进程")):
        opt, _ = core.resolve_optimizer(vpy, logs.append, requested="adamw")
    assert opt == "AdamW", opt

    # 6) 指定 adamw8bit 但不可用 + Lion 不可用 -> 自动降级 AdamW
    with patch.object(core.subprocess, "run", side_effect=subrun_lion_bad):
        opt, _ = core.resolve_optimizer(vpy, logs.append, requested="adamw8bit")
    assert opt == "AdamW", opt
    assert any("降级" in ln for ln in logs), logs

    # 7) _optimizer_yaml_name 映射
    assert core._optimizer_yaml_name("AdamW8bit") == "adamw8bit"
    assert core._optimizer_yaml_name("Lion") == "lion"
    assert core._optimizer_yaml_name("AdamW") == "adamw"
    assert core._optimizer_yaml_name("???") == "adamw"

    # 8) _probe_adamw8bit 超时/异常兜底
    def subrun_timeout(cmd, *args, **kwargs):
        raise TimeoutError("timeout")
    with patch.object(core.subprocess, "run", side_effect=subrun_timeout):
        ok, detail = core._probe_adamw8bit(vpy, logs.append, timeout=1)
    assert not ok and "预检进程异常" in detail, detail

    # 9.5) 用户明确指定 lion 但真实 step 预检失败 -> 自动降级 AdamW
    #      （Anima 用户反馈：命令带 --optimizer_type=Lion，退出码 1；旧版只做 import 检查）
    def subrun_lion_req_bad(cmd, *args, **kwargs):
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "import lion_pytorch" in code:
            return probe_result("RuntimeError: lion step incompatible\n", 1)
        if "bitsandbytes" in code:
            return probe_result("libbitsandbytes_cuda128.dll missing\n", 1)
        return probe_result("", 0)
    with patch.object(core.subprocess, "run", side_effect=subrun_lion_req_bad):
        opt, _ = core.resolve_optimizer(vpy, logs.append, requested="lion")
    assert opt == "AdamW", opt
    assert any("Lion 不可用" in ln for ln in logs), logs

    # 9) musubi 第二引擎 allow_lion=False：即使 Lion 预检会通过也直接降级 AdamW，且不调用 Lion 预检
    lion_called = {"n": 0}
    def subrun_musubi(cmd, *args, **kwargs):
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "import lion_pytorch" in code:
            lion_called["n"] += 1
            return probe_result("OK\n", 0)
        if "bitsandbytes" in code:
            return probe_result("Error: libbitsandbytes_cuda128.dll missing\n", 1)
        return probe_result("", 0)
    with patch.object(core.subprocess, "run", side_effect=subrun_musubi):
        opt, _ = core.resolve_optimizer(vpy, logs.append, requested="auto", allow_lion=False)
    assert opt == "AdamW", opt
    assert lion_called["n"] == 0, "allow_lion=False 不应调用 Lion 预检"

    print("OPTIMIZER_RESOLUTION_UNIT_TESTS_OK")

def test_preprocess_deps(base: Path):
    """_ensure_preprocess_deps 单元测试（mock 子进程/补装，不真实修改 venv）。"""
    vpy = str(base / "deps" / "venv" / "Scripts" / "python.exe")
    kdir = str(base / "deps" / "kohya_ss")
    logs = []

    def probe(rc):
        return subprocess.CompletedProcess([], rc, "", "")

    # 1) 依赖本来就可用：不触发任何补装
    install_called = {"n": 0}
    def run_stream_ok(cmd, cwd=None, env=None, logf=print, **kwargs):
        install_called["n"] += 1
        return 0
    with patch.object(core.subprocess, "run", return_value=probe(0)), \
         patch.object(core, "run_stream", side_effect=run_stream_ok), \
         patch.object(core, "build_env", return_value={}):
        assert core._ensure_preprocess_deps(vpy, kdir, logs.append) is True
    assert install_called["n"] == 0, "依赖可用时不应调用补装"
    assert not logs, logs

    # 2) 首次 import 失败 -> 内置 wheel 为空走国内镜像 -> 补装成功 -> 复检通过
    state = {"import_ok": False}
    def subrun_probe(cmd, *args, **kwargs):
        # 2026-09-06 起 _ensure_preprocess_deps 多了一道「解释器级 ctypes 前置校验」
        # （Anaconda 建的 venv 脱离 conda 激活时 _ctypes 对不上，重装 numpy 永远修不好）。
        # 这里按真实调用返回 ctypes-ok，否则会在进入补装流程之前就被判 False（旧断言已过期）。
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "import ctypes" in code:
            return subprocess.CompletedProcess([], 0, "ctypes-ok\n", "")
        return probe(0 if state["import_ok"] else 1)
    install_cmd = {"seen": []}
    def run_stream_install(cmd, cwd=None, env=None, logf=print, **kwargs):
        install_cmd["seen"].append([str(x) for x in cmd])
        if any("pip" in x for x in install_cmd["seen"][-1]):
            state["import_ok"] = True  # 装完即复检通过
        return 0
    with patch.object(core.subprocess, "run", side_effect=subrun_probe), \
         patch.object(core, "run_stream", side_effect=run_stream_install), \
         patch.object(core, "build_env", return_value={}), \
         patch.object(core, "_bundled_pip_wheels", return_value=[]), \
         patch.object(core, "_wheels_for_python", return_value=[]):
        assert core._ensure_preprocess_deps(vpy, kdir, logs.append) is True
    # 2026-09-11：pip 主源由阿里云改为中科大（实测 2.84 vs 0.12 MB/s），断言改为对常量取。
    assert any(core.PIP_INDEX_PRIMARY in x for c in install_cmd["seen"] for x in c), install_cmd["seen"]

    # 2.5) force=True：即使快速校验通过（-c 可 import），也强制补装一轮
    force_install = {"n": 0}
    def subrun_ok_force(cmd, *args, **kwargs):
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "import ctypes" in code:
            return subprocess.CompletedProcess([], 0, "ctypes-ok\n", "")   # ctypes 前置校验先过
        return probe(0)  # 校验总是通过
    def run_stream_force(cmd, cwd=None, env=None, logf=print, **kwargs):
        force_install["n"] += 1
        return 0
    with patch.object(core.subprocess, "run", side_effect=subrun_ok_force), \
         patch.object(core, "run_stream", side_effect=run_stream_force), \
         patch.object(core, "build_env", return_value={}), \
         patch.object(core, "_bundled_pip_wheels", return_value=[]), \
         patch.object(core, "_wheels_for_python", return_value=[]):
        assert core._ensure_preprocess_deps(vpy, kdir, logs.append, force=True) is True
    assert force_install["n"] >= 1, "force=True 必须执行补装"
    # 非 force 且校验通过：不补装
    n0 = force_install["n"]
    with patch.object(core.subprocess, "run", side_effect=subrun_ok_force), \
         patch.object(core, "run_stream", side_effect=run_stream_force), \
         patch.object(core, "build_env", return_value={}):
        assert core._ensure_preprocess_deps(vpy, kdir, logs.append) is True
    assert force_install["n"] == n0, "非 force 且校验通过时不应补装"

    # 3) 补装也失败（离线+双镜像，两轮重试都失败） -> 返回 False
    def subrun_bad(cmd, *args, **kwargs):
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "import ctypes" in code:
            return subprocess.CompletedProcess([], 0, "ctypes-ok\n", "")   # ctypes 前置校验先过
        return probe(1)
    def run_stream_bad(cmd, cwd=None, env=None, logf=print, **kwargs):
        return 1
    with patch.object(core.subprocess, "run", side_effect=subrun_bad), \
         patch.object(core, "run_stream", side_effect=run_stream_bad), \
         patch.object(core, "build_env", return_value={}), \
         patch.object(core, "_bundled_pip_wheels", return_value=[]), \
         patch.object(core, "_wheels_for_python", return_value=[]):
        assert core._ensure_preprocess_deps(vpy, kdir, logs.append) is False
    assert any("重试" in ln or "失败" in ln for ln in logs), logs

    print("PREPROCESS_DEPS_UNIT_TESTS_OK")

def test_preprocess_auto_retry(base: Path):
    """preprocess() 子进程缺依赖失败时：补装后自动重试一次；补装也失败则报明确错误。"""
    kdir = base / "pp" / "kohya_ss"
    kdir.mkdir(parents=True, exist_ok=True)
    vpy = kdir / "venv" / "Scripts" / "python.exe"
    fake_python(vpy)
    in_dir = base / "pp" / "images"
    in_dir.mkdir(parents=True, exist_ok=True)
    (in_dir / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    out_dir = base / "pp" / "out"

    # 场景 A：第一次跑 preprocess 失败 -> 补装成功 -> 自动重试一次成功
    logs = []
    calls = {"n": 0}
    def run_stream_a(cmd, cwd=None, env=None, logf=print, **kwargs):
        cmd = [str(x) for x in cmd]
        if any("preprocess.py" in x for x in cmd):
            calls["n"] += 1
            return 1 if calls["n"] == 1 else 0
        return 0
    with patch.object(core, "venv_python", return_value=str(vpy)), \
         patch.object(core, "_venv_python_ok", return_value=(True, "ok")), \
         patch.object(core, "_ensure_preprocess_deps", return_value=True), \
         patch.object(core, "get_kohya_dir", return_value=str(kdir)), \
         patch.object(core, "dataset_train_dir", return_value=str(out_dir)), \
         patch.object(core, "run_stream", side_effect=run_stream_a):
        core.preprocess(logs.append, input_dir=str(in_dir), mode="style")
    assert calls["n"] == 2, calls
    assert any("自动重试预处理" in ln for ln in logs), logs

    # 场景 B：子进程失败后补装也失败 -> 抛明确错误，不无限重试
    logs2 = []
    calls2 = {"n": 0}
    deps_n = {"n": 0}
    def ensure_deps(vpy, kdir, logf=print, force=False):
        deps_n["n"] += 1
        return deps_n["n"] == 1  # 开头自检通过；子进程失败后的补装失败
    def run_stream_b(cmd, cwd=None, env=None, logf=print, **kwargs):
        cmd = [str(x) for x in cmd]
        if any("preprocess.py" in x for x in cmd):
            calls2["n"] += 1
        return 1
    with patch.object(core, "venv_python", return_value=str(vpy)), \
         patch.object(core, "_venv_python_ok", return_value=(True, "ok")), \
         patch.object(core, "_ensure_preprocess_deps", side_effect=ensure_deps), \
         patch.object(core, "get_kohya_dir", return_value=str(kdir)), \
         patch.object(core, "dataset_train_dir", return_value=str(out_dir)), \
         patch.object(core, "run_stream", side_effect=run_stream_b):
        try:
            core.preprocess(logs2.append, input_dir=str(in_dir), mode="style")
            raise AssertionError("应抛出预处理失败错误")
        except RuntimeError as e:
            # 文案随 2026-09-06 的「训练环境自愈」改造更新（旧文案「强制补装后仍不可用」已不存在）
            assert "训练环境自愈后仍不可用" in str(e), e
    assert calls2["n"] == 1, "补装失败时不应重试 preprocess"
    assert deps_n["n"] == 2, deps_n
    print("PREPROCESS_AUTO_RETRY_OK")

def test_preprocess_crop_ratio(base: Path):
    """预处理裁切比例：默认保比例不传参；square_crop 旧接口等价 1:1；crop_ratio 支持任意 W:H。"""
    # normalize_crop_ratio 单测
    assert core.normalize_crop_ratio("") == ""
    assert core.normalize_crop_ratio("不裁切") == ""
    assert core.normalize_crop_ratio("3:4") == "3:4"
    assert core.normalize_crop_ratio("3：4") == "3:4"   # 全角冒号兼容
    assert core.normalize_crop_ratio("9:16") == "9:16"
    assert core.normalize_crop_ratio("2:3") == "2:3"
    assert core.normalize_crop_ratio("abc") == ""
    assert core.normalize_crop_ratio("1:9") == ""       # 超范围 1:2~2:1
    assert core.normalize_crop_ratio("9:1") == ""
    assert core.normalize_crop_ratio("0:4") == ""

    kdir = base / "ppc" / "kohya_ss"
    kdir.mkdir(parents=True, exist_ok=True)
    vpy = kdir / "venv" / "Scripts" / "python.exe"
    fake_python(vpy)
    in_dir = base / "ppc" / "images"
    in_dir.mkdir(parents=True, exist_ok=True)
    (in_dir / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    out_dir = base / "ppc" / "out"
    captured = []

    def run_stream(cmd, cwd=None, env=None, logf=print, **kwargs):
        captured.append([str(x) for x in cmd])
        return 0

    def _do(**kw):
        captured.clear()
        with patch.object(core, "venv_python", return_value=str(vpy)), \
             patch.object(core, "_venv_python_ok", return_value=(True, "ok")), \
             patch.object(core, "_ensure_preprocess_deps", return_value=True), \
             patch.object(core, "get_kohya_dir", return_value=str(kdir)), \
             patch.object(core, "dataset_train_dir", return_value=str(out_dir)), \
             patch.object(core, "run_stream", side_effect=run_stream):
            core.preprocess(lambda *a: None, input_dir=str(in_dir), mode="style", **kw)
        assert captured, "应调用一次 preprocess 子进程"
        return captured[0]

    cmd_def = _do()
    assert "--crop-ratio" not in cmd_def and "--square-crop" not in cmd_def, cmd_def
    cmd_sq = _do(square_crop=True)
    assert "--crop-ratio" in cmd_sq and cmd_sq[cmd_sq.index("--crop-ratio") + 1] == "1:1", cmd_sq
    cmd_34 = _do(crop_ratio="3:4")
    assert "--crop-ratio" in cmd_34 and cmd_34[cmd_34.index("--crop-ratio") + 1] == "3:4", cmd_34
    cmd_bad = _do(crop_ratio="abc")
    assert "--crop-ratio" not in cmd_bad, cmd_bad
    # 静态断言：GUI 有裁切比例下拉；流水线入口读 params.crop_ratio，不再写死 square_crop=True
    src = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8-sig")
    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8")
    assert "square_crop=True," not in src and "square_crop=True," not in g, "流水线不应再写死居中裁切"
    # 2026-09-12：旧 tkinter 界面（Kohya一键工具.py 里的 class App）已删除；
    # crop_ratio 的读取点现在在新界面 kohya_gui.py，core 侧保留入口参数与归一化函数。
    assert "normalize_crop_ratio" in src and "crop_ratio=None" in src, "Kohya一键工具.py 缺 crop_ratio 入口"
    assert 'crop_ratio=params.get("crop_ratio")' in g, "kohya_gui.py 预处理应读 crop_ratio"
    assert "crop_ratio_var" in g and "crop_ratio_combo" in g, "GUI 应有裁切比例下拉"
    print("PREPROCESS_CROP_RATIO_OK")

def test_next_features(base: Path):
    """下版本三条：musubi 国内源优先 / 采样提示词可编辑 / 保存间隔可设置。"""
    # ① musubi 国内源：jsDelivr 直链 + 国内优先、git 兜底
    assert "cdn.jsdelivr.net" in core.MUSUBI_CN_ZIP_URL
    assert hasattr(core, "_install_musubi_from_domestic")
    k = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8-sig")
    assert "从国内直链下载 musubi-tuner" in k
    assert "改用 git 克隆（GitHub，需联网）" in k, "git 应保留为最后兜底"
    # 国内下载失败 -> 返回 False（不抛）
    with patch.object(core, "_download", side_effect=RuntimeError("net down")):
        assert core._install_musubi_from_domestic(str(base / "mt"), lambda *a: None) is False

    # ② 采样预览提示词：自定义整句生效；留空=自动（带 trigger）
    with patch.object(core, "data_sub", side_effect=lambda *p: str(base.joinpath(*p))):
        p1 = core._write_sample_prompts("o1", {"sample_preview": True, "sample_prompt": "1girl, red hair", "trigger": "tg"}, "style", engine="musubi", resolution=512)
        t1 = open(p1, encoding="utf-8").read()
        assert "1girl, red hair" in t1 and "--w 512 --h 512 --s 20" in t1 and "tg" not in t1, t1
        p2 = core._write_sample_prompts("o2", {"sample_preview": True, "trigger": "tg"}, "style", engine="kohya")
        t2 = open(p2, encoding="utf-8").read()
        assert t2.startswith("tg, portrait") and "masterpiece" in t2, t2

    # ③ 保存间隔：musubi 按轮（默认 1、>=1），train() 读 params
    assert core._resolve_save_every_epochs({}) == 1
    assert core._resolve_save_every_epochs({"save_every": 5}) == 5
    assert core._resolve_save_every_epochs({"save_every": 0}) == 1
    assert 'params.get("save_every")' in k
    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8")
    assert "模型保存间隔" in g and "sample_prompt" in g and "save_every" in g
    # ④ Krea2/FLUX.2 断点续训：--save_state + --resume 已接线（此前完全没传）
    k2 = k[k.find("def train_krea2("):k.find("def train_video(")]
    assert k2.count("--save_state") >= 2, "krea2/flux2 都应带 --save_state"
    assert k.count('cmd.append(f"--resume={resume_from}")') >= 2, "krea2/flux2 都应接线 --resume"
    assert "断点续训：从" in k2
    # ⑤ 低内存降 swap 阈值 32→24：4080S 16G + 31G 不再被误伤（swap6 会慢 10 倍）；12G + 16G 仍生效
    assert core._resolve_krea2_swap(15.67, ram_gb=31) == (12, True), "4080S 31G 应保持 swap12"
    assert core._resolve_krea2_swap(12, ram_gb=16) == (6, True), "3060 12G + 16G 仍应降 swap6"
    assert core._resolve_flux2_swap(15.67, ram_gb=31) == (2, True), "4080S 31G FLUX.2 应保持 swap2"
    assert core._resolve_flux2_swap(12, ram_gb=16) == (4, True), "12G + 16G FLUX.2 仍应降 swap4"
    # ⑥ WD14 打标 huggingface_hub 自愈补装
    pp = (ROOT / "preprocess.py").read_text(encoding="utf-8")
    assert "def _ensure_hf_hub" in pp and "_ensure_hf_hub(cur, logf)" in pp
    print("NEXT_FEATURES_OK")

def test_tools_module(base: Path):
    """主页 🧰 小工具模块：核心函数存在且可调用、训练进程名规则、GUI 静态接线。"""
    # 核心函数
    for fn in ("gpu_status_text", "vram_residual_processes", "kill_processes",
               "clear_memory", "clear_temp_cache", "nvidia_vram_used_mb", "active_process_pids"):
        assert hasattr(core, fn), fn
    # 训练进程名规则
    assert core._is_training_proc_name("python.exe") is True
    assert core._is_training_proc_name("pythonw.exe") is True
    assert core._is_training_proc_name("accelerate.exe") is True
    assert core._is_training_proc_name("chrome.exe") is False
    assert core._is_training_proc_name("explorer.exe") is False
    # 查看：返回文本
    assert isinstance(core.gpu_status_text(), str) and len(core.gpu_status_text()) > 0
    # 残留进程：nvidia-smi 不可用时返回 []（不抛）
    from kohya_core import gpu as _gpu
    _gpu._NV_SMI_STATE["ok"] = None
    with patch.object(_gpu, "_nvidia_smi", return_value=None):
        assert core.vram_residual_processes() == []
    _gpu._NV_SMI_STATE["ok"] = None
    # 清理内存：返回 4 元组（本机可跑，EmptyWorkingSet 安全）
    r = core.clear_memory()
    assert isinstance(r, tuple) and len(r) == 4, r
    # 清理缓存：返回列表
    assert isinstance(core.clear_temp_cache(), list)
    # GUI 静态接线
    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8")
    assert 'text="🧰 小工具"' in g and "cmd_open_tools" in g
    for m in ("_tools_run", "_tools_scan_vram", "_tools_kill_vram", "_tools_oneclick", "_fmt_mem", "_fmt_cache"):
        assert m in g, m
    print("TOOLS_MODULE_OK")

def test_gui_resource_guard(base: Path):
    """GUI 资源防护：监控器用安全 nvidia-smi + 节流；日志框限行；缩略图缓存上限（防 Tk 内存/GDI 耗尽弹窗）。"""
    # safe_nvidia_smi 已从 core 导出（监控器用）
    assert hasattr(core, "safe_nvidia_smi")
    from kohya_core import gpu as _gpu
    _gpu._NV_SMI_STATE["ok"] = None
    calls = {"n": 0}
    def fake_run(cmd, *a, **kw):
        calls["n"] += 1
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
    with patch.object(_gpu.subprocess, "run", side_effect=fake_run):
        assert core.safe_nvidia_smi(["--query-gpu=name"]) is None
        assert core.safe_nvidia_smi(["--query-gpu=name"]) is None
        assert calls["n"] == 1, "失败后不应重复调用"
    _gpu._NV_SMI_STATE["ok"] = None

    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8")
    # 监控器显存改用安全封装 + 5s 节流
    assert "core.safe_nvidia_smi(" in g and "_mon_vram_last" in g
    assert 'subprocess.run(["nvidia-smi"' not in g, "GUI 不应再直接裸调 nvidia-smi"
    # 日志框限行（防 Tk 内存/GDI 耗尽）+ 完整日志独立保留（导出不受限行影响）+ 缩略图缓存上限
    assert "_MAX_LOG_LINES = 3000" in g and 'self.log.delete("1.0"' in g
    assert "self._full_log" in g and '"\\n".join(getattr(self, "_full_log", None) or [])' in g
    assert "len(self._thumbs) > 50" in g
    # 启动时抑制子进程错误弹窗（SetErrorMode）
    k = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8-sig")
    assert "SetErrorMode(0x8003)" in k
    print("GUI_RESOURCE_GUARD_OK")

def test_nvidia_smi_driver_safe(base: Path):
    """重装系统未装 NVIDIA 驱动（nvidia-smi 0xc0000142）时：不调用 nvidia-smi、不弹窗、不卡死，
    改用 DXGI/WMI 检测；驱动缺失时 gpu_ok=False。"""
    from kohya_core import gpu as _gpu
    _gpu._NV_SMI_STATE["ok"] = None

    # 场景 A：驱动缺失（DXGI 只剩基础显示适配器）→ 绝不调用 nvidia-smi，走 WMI 兜底
    def fake_run_a(cmd, *a, **kw):
        c = " ".join(str(x) for x in cmd)
        assert "nvidia-smi" not in c, "驱动缺失时不应调用 nvidia-smi: %s" % c
        out = "Microsoft Basic Display Adapter|Microsoft" if "AdapterCompatibility" in c else "Microsoft Basic Display Adapter"
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
    with patch.object(_gpu, "_dxgi_adapters", return_value=[("Microsoft Basic Display Adapter", 0)]), \
         patch.object(_gpu.subprocess, "run", side_effect=fake_run_a):
        assert _gpu.detect_nvidia_gpu() is False
        assert _gpu.detect_gpu_vendor() == "unknown"
        assert "Basic Display" in (_gpu.detect_gpu_name() or "")
        assert _gpu.detect_gpu_info()["gpu_ok"] is False
        assert _gpu.nvidia_smi_broken() is False, "未调用过 nvidia-smi，不应标记损坏"

    # 场景 B：NVIDIA 独显驱动正常（DXGI 可枚举）→ 名字走 nvidia-smi 权威来源（DXGI 可能报错名/重复枚举）
    def fake_run_b(cmd, *a, **kw):
        c = " ".join(str(x) for x in cmd)
        if "nvidia-smi" in c:
            return subprocess.CompletedProcess(cmd, 0, stdout="NVIDIA GeForce RTX 4070\n", stderr="")
        raise AssertionError("nvidia-smi 成功时不应再调其他子进程: %s" % c)
    with patch.object(_gpu, "_dxgi_adapters", return_value=[("NVIDIA GeForce RTX 5070", 8 * 1024 ** 3)]), \
         patch.object(_gpu.subprocess, "run", side_effect=fake_run_b):
        assert _gpu.detect_nvidia_gpu() is True
        # DXGI 名字是错的（5070），nvidia-smi 返回权威的 4070
        assert _gpu.detect_gpu_name() == "NVIDIA GeForce RTX 4070"
        assert _gpu.detect_gpu_vendor() == "nvidia"
        assert _gpu.detect_gpu_info()["gpu_ok"] is True

    # 场景 C：_nvidia_smi 失败后不再重复调用（缓存损坏状态，避免弹窗刷屏/卡死）
    _gpu._NV_SMI_STATE["ok"] = None
    calls = {"n": 0}
    def fake_run_c(cmd, *a, **kw):
        calls["n"] += 1
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
    with patch.object(_gpu.subprocess, "run", side_effect=fake_run_c):
        assert _gpu._nvidia_smi(["--query-gpu=name"]) is None
        assert _gpu.nvidia_smi_broken() is True
        assert _gpu._nvidia_smi(["--query-gpu=name"]) is None
        assert calls["n"] == 1, "失败后不应重复调用 nvidia-smi"
    _gpu._NV_SMI_STATE["ok"] = None

    # 静态断言：GUI 环境信息在驱动缺失时给出提示
    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8")
    assert "未检测到可用独立显卡驱动" in g
    print("NVIDIA_SMI_DRIVER_SAFE_OK")

def test_alloc_conf_expandable_stripped(base: Path):
    """Windows 不支持 expandable_segments：训练子进程环境自动剥离，避免"显存充足却 OOM"假性爆显存。"""
    import os as _os
    # build_direct_env 剥离 expandable_segments，保留 max_split_size_mb 等其他有效项
    with patch.dict(_os.environ, {"PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True,max_split_size_mb:128"}, clear=False):
        env = core.build_direct_env()
        val = env.get("PYTORCH_CUDA_ALLOC_CONF", "")
        assert "expandable_segments" not in val.lower(), val
        assert "max_split_size_mb:128" in val, val
    with patch.dict(_os.environ, {"PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"}, clear=False):
        env2 = core.build_direct_env()
        assert "PYTORCH_CUDA_ALLOC_CONF" not in env2, env2.get("PYTORCH_CUDA_ALLOC_CONF")
    # _warn_alloc_conf 在误设时给出删除提示
    logs = []
    with patch.dict(_os.environ, {"PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"}, clear=False):
        core._warn_alloc_conf(logs.append)
    assert any("expandable_segments" in ln and "setx" in ln for ln in logs), logs
    logs2 = []
    with patch.dict(_os.environ, {}, clear=False):
        core._warn_alloc_conf(logs2.append)
    assert logs2 == [], logs2
    print("ALLOC_CONF_EXPANDABLE_STRIPPED_OK")

def test_preprocess_mode_mapping(base: Path):
    """训练模式 -> 预处理模式映射：FLUX.2 等第二/三引擎不能再把 flux2 当 --mode 传（preprocess 只收 style/character）。"""
    # 单测 preprocess_mode
    assert core.preprocess_mode("style") == "style"
    assert core.preprocess_mode("character") == "character"
    assert core.preprocess_mode("flux2") == "character"          # 修复点：FLUX.2 默认人物
    assert core.preprocess_mode("flux2", "style") == "style"     # 画风子模式
    assert core.preprocess_mode("krea2") == "character"
    assert core.preprocess_mode("qwen_image", "style") == "style"
    assert core.preprocess_mode("zimage") == "character"
    assert core.preprocess_mode("video") == "character"          # 兜底不崩
    # 静态断言：GUI 两个预处理入口不再用缺 FLUX.2 的旧元组，统一走 core.preprocess_mode
    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8")
    assert 'core.preprocess_mode(params.get("mode"), params.get("at_sub_mode"))' in g
    assert 'params.get("mode") in ("krea2", "qwen_image", "zimage")' not in g, "旧元组漏了 flux2"
    # 旧界面删除后，调用点在新界面 kohya_gui.py（上面已断言）；core 侧只需保留映射函数本身。
    k = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8-sig")
    assert "def preprocess_mode(" in k, "Kohya一键工具.py 缺 preprocess_mode"
    print("PREPROCESS_MODE_MAPPING_OK")

def test_torch_import_hints_split_1114_vs_126(base: Path):
    """WinError **1114**（DLL 初始化失败）与 **126**（文件缺失）必须给**不同**的指引。

    2026-09-16 用户实证（NJFF / 第四引擎）真实报错原文：
        OSError: [WinError 1114] 动态链接库(DLL)初始化例程失败。
        Error loading "...\\torch\\lib\\c10.dll" or one of its dependencies.
    —— **1114 是「DLL 找到了但起不来」**（多为 VC++ 运行库太旧，缺 VS2019+ 的
       `vcruntime140_1.dll`），**126 才是「缺文件」**。
    混为一谈的代价：用户照"缺 VC++"的提示装了运行库、问题照旧，白跑一趟 ✗
    （而且他会以为自己已经装过了 ✗）。
    """
    _real1114 = ('Traceback (most recent call last):\n'
                 '  File "<string>", line 1, in <module>\n'
                 'OSError: [WinError 1114] 动态链接库(DLL)初始化例程失败。 Error loading '
                 '"C:\\Users\\vipuser\\Documents\\KohyaLoraTool_data\\kohya_ss\\fizgig_venv'
                 '\\Lib\\site-packages\\torch\\lib\\c10.dll" or one of its dependencies.')
    _t1 = "\n".join(core._torch_import_hints(_real1114))
    assert _t1, "1114 没有给出任何指引"
    assert "初始化失败" in _t1, _t1
    # 1114 的排查顺序（2026-09-16 实证修正：VC++ 已在、CPU 才是头号嫌疑）
    assert "AVX2" in _t1, "1114 未把 CPU AVX2 列为头号嫌疑（低配云主机最常见的 1114 原因）"
    # ⚠️ 这里**故意不再要求**提到 `vcruntime140_1.dll`：
    #    2026-09-16 就是让人查"那个文件在不在"、看到它在就**排除了运行库** ✗ ——
    #    而真因是**版本**（14.34 < torch 需要的 14.44）✗。所以指引的重点是**版本号**，
    #    "目录里有没有这个文件"是个会误导人的检查 ✗（留着它反而会复制那次错误判断）。
    assert "msvcp140.dll" in _t1, "1114 未给出运行库自检命令"
    assert "杀软" in _t1, "1114 未给出杀软这条"
    assert "wmic cpu get name" in _t1, "1114 未给出可直接复制的 CPU 自检命令"
    # 干净 PATH 复测必须写成**分两行执行**，并同时给 PowerShell 与 cmd 语法：
    # 2026-09-16 连踩两次 —— ① 只给 cmd 的 `set PATH=`，用户跑在 PowerShell 里
    # 直接 CommandNotFound ✗；② 给成一行 `set PATH=… python -c …` 却没加 `&&`，
    # cmd 把后面整串当成 PATH 的值，**等于什么都没执行** ✗（用户以为"试过了没输出"）
    assert "set " in _t1 and "$env:PATH" in _t1, "干净 PATH 指引未同时覆盖 cmd 与 PowerShell"
    assert "一行一条" in _t1, "干净 PATH 指引没强调「一行一条执行」（挤在一行需要连接符，抄漏就静默不执行）"
    # 精确断言：**没有任何一条命令**把「设置 PATH」和「import torch」写在同一行
    # （写成一行就必须用连接符，用户抄漏一个字符就静默不执行 ✗ —— 正是 2026-09-16 的事故）
    assert not [ln for ln in core._torch_import_hints(_real1114)
                if "PATH=" in ln and "import torch" in ln], \
        "指引里出现了「设置 PATH + import」的一行式命令"
    assert "pytorch_wheels" in _t1, "1114 未提示手动放置的轮子可能损坏、需重新下载校验"

    # 工具应主动把 **CPU 型号 + AVX2 支持情况**写进日志。
    # 只写型号是不够的（2026-09-16 我们拿到型号后还要自己查，还查错了方向 ✗），
    # 必须直接给出 AVX2 结论，日志才能一眼判断。
    _k = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8-sig")
    assert "def _cpu_desc(" in _k and "当前 CPU：" in _k, "导入失败时未记录 CPU 信息"
    assert "AVX2：" in _k, "CPU 信息里没带 AVX2 结论"
    assert "IsProcessorFeaturePresent(40)" in _k, "AVX2 探测未用 PF_AVX2_INSTRUCTIONS_AVAILABLE"
    # 实测本机探测可用（不依赖 numpy/torch）
    _d = str(core._cpu_desc())
    assert "AVX2：" in _d and _d.strip(), _d
    assert core._cpu_name(), "读不到 CPU 型号"

    # ---- 2026-09-16 拿到用户实测报告后的修正：1114 的真因是 **VC++ 运行库版本低** ----
    # 当时我们让他 `dir vcruntime140*.dll`，看到"文件在、日期 2022"就**排除了运行库** ✗，
    # 真因恰恰是它：文件是 14.34，而 torch 2.10 需要 14.44 ✗（注册表里还只记着 14.22 ✗）。
    # 教训：**"存在且不旧"≠"够新"**，必须取到**版本号**再下结论。
    assert "版本太低" in _t1, "1114 未把「VC++ 运行库版本低」放在头号位置（实测确认的真因）"
    assert "vc_redist.x64.exe" in _t1, "1114 未给出 VC++ 安装直链"
    assert "194" in _t1, "1114 未提醒「静默安装退出码 194 也可能成功」这个坑"
    assert "msvcp140.dll" in _t1, "1114 没说要复查 msvcp140.dll 的版本号"
    assert "winerror 127" in core._torch_import_hints("WinError 127")[0].lower(), "127 未分类"
    # ⚠️ 断言必须能识别"读出了垃圾"：写第一版时按 [0][1] 取结构体字段（signature/strucVersion ✗），
    #    结果是 `65536.4277077181.…` 这种值，而 `count(".") == 3` 这种弱断言**照样通过** ✗。
    #    VS2015-2022 运行库的版本号**一定以 14. 开头**（msvcp140 = v14.0）→ 用它兜底 ✓
    _v = str(core._vc_runtime_file_version())
    assert _v.startswith("14.") and _v.count(".") == 3, \
        "msvcp140.dll 版本读取异常（应为 14.x.y.z）：%r" % _v
    _src = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8-sig")
    assert "系统 VC++ 运行库" in _src, "导入失败时未把运行库版本写进日志"
    # 修正误判：RDP 下 nvidia-smi 报 NVML 错误 ≠ 没有显卡（用户实测：4090 正常可用）
    assert "不代表没有显卡" in _src, "RDP 下查不到显卡仍会被当成「没有显卡」"

    _t2 = "\n".join(core._torch_import_hints(
        "ImportError: DLL load failed while importing _C: 找不到指定的模块"))
    assert "缺 VC++ 运行库" in _t2, _t2
    assert "vcruntime140_1.dll" not in _t2, "126 被当成 1114 处理了（两者指引必须不同）"

    assert core._torch_import_hints("Access is denied 拒绝访问"), "杀软分支没命中"
    assert core._torch_import_hints("0xc000001d illegal instruction"), "CPU 指令集分支没命中"
    assert core._torch_import_hints("") == [], "空输入应返回空"
    assert core._torch_import_hints(None) == [], "None 应返回空"
    print("TORCH_IMPORT_HINTS_SPLIT_OK")

def test_fizgig_krea2_saves_state(base: Path):
    """第四引擎 Krea2 路径**必须**传 --save_state，否则断点永不产生、续训无从谈起。

    2026-09-17 用户实证（三角洲蝶妹）：跑满 6 个 epoch / 3 小时手动停止，工具报
    「本次没有产生可续训的快照」✗ 并归因「停在第一个存档点之前，至少跑完第一个
    epoch 再停」✗ —— 真因是命令行**漏了 `--save_state`**：
    Fizgig 只在带该参数时才写 `{output_name}-NNNNNN-state/training_state.json` ✗，
    否则只存 LoRA 权重 → 无论跑多久都没有断点 ✗。
    同引擎的 FLUX.2 路径一直带着 ✓，Krea2 这条是复制时漏的 ✗。
    （已核对本地缓存的 Fizgig v5.0.0 源码：`krea2_train.py` 支持这三个参数 ✓）
    """
    k = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8-sig")

    def _cmd_of(anchor):
        _i = k.index(anchor)
        return k[_i:k.index("if resume_from:", _i)]      # 只看构建命令那段

    _k2 = _cmd_of("def train_krea2_fizgig(")
    assert '"--save_every_n_epochs"' in _k2, "Krea2(Fizgig) 没传保存间隔"
    assert '"--save_state"' in _k2, \
        "Krea2(Fizgig) 漏了 --save_state → 断点永不产生，续训形同不存在（本次用户报的问题）"
    assert '"--keep_last_n_states"' in _k2, "缺 --keep_last_n_states：状态目录会无限堆积"
    # 同引擎的参考路径（一直是对的）——用它当"该有什么"的标尺。
    # 锚点选 FLUX.2 命令里独有的参数（用常量名当锚点会命中它的**定义**，切片会跨过整个文件 → 断言形同虚设 ✗）
    _fz = _cmd_of('"--model_version", FLUX2FZ_MODEL_VERSION')
    assert '"--save_state"' in _fz, "FLUX.2(Fizgig) 的 --save_state 丢了（回归）"
    print("FIZGIG_KREA2_SAVE_STATE_OK")

def test_fizgig_skip_reason_logged(base: Path):
    """已装环境匹配但当前会话看不到 GPU 时，明确停下，不要重装数 GB 依赖。"""
    import contextlib

    kdir = base / "fizgig_skip_guard" / "kohya_ss"
    fv = kdir / "fizgig_venv"
    vpy = fv / "Scripts" / "python.exe"
    fake_python(vpy)
    logs, stream_calls = [], []
    probe = result(0, "2.10.0+cu128\nhip=\ncuda=12.8\nok=False\n")
    patches = (
        patch.object(core, "get_kohya_dir", return_value=str(kdir)),
        patch.object(core, "_fizgig_ensure_python312", return_value=r"C:\Python312\python.exe"),
        patch.object(core, "_deploy_fizgig_source", return_value=str(kdir / "fizgig")),
        patch.object(core, "_venv_python_ok", return_value=(True, "Python 3.12")),
        patch.object(core, "_ensure_venv_pip", return_value=True),
        patch.object(core, "_acquire_kohya_install_lock", return_value=SimpleNamespace()),
        patch.object(core, "_release_kohya_install_lock", return_value=None),
        patch.object(core, "detect_gpu_vendor", return_value="nvidia"),
        patch.object(core.subprocess, "run", return_value=probe),
        patch.object(core, "run_stream", side_effect=lambda *a, **k: stream_calls.append((a, k)) or 0),
    )
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        try:
            core.install_fizgig_engine(logs.append)
        except RuntimeError as exc:
            detail = str(exc)
        else:
            raise AssertionError("GPU 不可用时应停止，而非继续安装")
    assert "没有识别到 GPU" in detail and "重复下载安装不会修复" in detail
    assert "远程桌面" in detail and "不代表没有显卡" in detail
    assert not stream_calls, "匹配的已安装环境在 GPU 不可见时不应启动 pip/重装"

    # 已安装后端和 GPU 都可用：快速跳过，无安装命令。
    stream_calls.clear()
    probe_ok = result(0, "2.10.0+cu128\nhip=\ncuda=12.8\nok=True\n")
    with contextlib.ExitStack() as stack:
        for p in patches[:-2]:
            stack.enter_context(p)
        stack.enter_context(patch.object(core.subprocess, "run", return_value=probe_ok))
        stack.enter_context(patch.object(core, "run_stream", side_effect=lambda *a, **k: stream_calls.append((a, k)) or 0))
        out = core.install_fizgig_engine(logs.append)
    assert Path(out) == vpy and not stream_calls
    assert any("跳过重复安装" in line for line in logs)
    print("FIZGIG_SKIP_REASON_LOGGED_OK")

def test_h3_amd_blocked_by_hardware():
    """H3 AMD 通道尚未开放：即使旧配置没有 amd_mode，也必须按实际 GPU 阻止。"""
    with patch.object(core, "detect_gpu_vendor", return_value="amd"):
        try:
            core.train_video(params={"amd_mode": False})
        except RuntimeError as exc:
            assert "H3 视频的 Windows AMD 训练通道尚未开放" in str(exc)
        else:
            raise AssertionError("AMD 设备不应进入尚未开放的 H3 训练路径")
    print("H3_AMD_HARDWARE_GUARD_OK")

def test_preinstall_torch_mirror_fallback(base: Path):
    """_preinstall_torch 本地安装多镜像回退：第一个失败 -> 第二个成功；全部失败才报明确错误。"""
    kdir = base / "pt" / "kohya_ss"
    cache = base / "pt" / "cache" / "pytorch_wheels"
    cache.mkdir(parents=True, exist_ok=True)
    # 稀疏文件：逻辑大小满足 minsize（torch 1GB / torchvision 5MB），避免真写 1GB
    for name, size in (
            ("torch-2.7.1+cu128-cp310-cp310-win_amd64.whl", 1_000_000_000),
            ("torchvision-0.22.1+cu128-cp310-cp310-win_amd64.whl", 5_000_000)):
        with open(cache / name, "wb") as f:
            f.truncate(size)
    vpy = str(base / "pt" / "venv" / "Scripts" / "python.exe")
    logs = []

    def subrun(cmd, *args, **kwargs):
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "sys.version_info" in code:
            return result(0, "cp310")
        if "import torch, torchvision" in code:
            return result(0, "2.7.1+cu128\nTrue\n")
        return result(0)

    def data_sub(*parts):
        return str(base.joinpath("pt", *parts))  # 与 cache 目录（base/pt/cache/pytorch_wheels）对齐

    # 场景 A：第一个镜像失败 -> 第二个镜像成功
    installs = {"n": 0, "indexes": []}
    def run_stream_a(cmd, cwd=None, env=None, logf=print, **kwargs):
        cmd = [str(x) for x in cmd]
        if "pip" in cmd and "install" in cmd:
            installs["n"] += 1
            installs["indexes"].append((env or {}).get("PIP_INDEX_URL"))
            return 1 if installs["n"] == 1 else 0  # 第一个镜像（清华）失败，第二个（阿里云）成功
        return 0
    with patch.object(core, "data_sub", side_effect=data_sub), \
         patch.object(core, "_wheel_valid", return_value=True), \
         patch.object(core.subprocess, "run", side_effect=subrun), \
         patch.object(core, "run_stream", side_effect=run_stream_a), \
         patch.object(core, "build_direct_env", return_value={}):
        ok = core._preinstall_torch(vpy, str(kdir), logs.append,
                                    torch_ver="2.7.1", tv_ver="0.22.1",
                                    cu="cu128", label="第二引擎", force=True)
    assert ok is True
    assert installs["n"] == 2, installs
    # 2026-09-11：pip 源改为 PIP_MIRRORS（中科大→华为云→清华→上海交大→阿里云），
    # 断言直接对常量取，避免以后再调优先级时又要同步改测试。
    _mirs = [u for _n, u in core.PIP_MIRRORS]
    assert installs["indexes"][0] == _mirs[0], installs
    assert installs["indexes"][1] == _mirs[1], installs
    assert any("自动切换下一镜像" in ln for ln in logs), logs

    # 场景 B：三个镜像全部失败 -> 抛明确错误（不再笼统报「国内双镜像下载失败」）
    installs2 = {"n": 0, "indexes": []}
    def run_stream_b(cmd, cwd=None, env=None, logf=print, **kwargs):
        cmd = [str(x) for x in cmd]
        if "pip" in cmd and "install" in cmd:
            installs2["n"] += 1
            installs2["indexes"].append((env or {}).get("PIP_INDEX_URL"))
        return 1
    with patch.object(core, "data_sub", side_effect=data_sub), \
         patch.object(core, "_wheel_valid", return_value=True), \
         patch.object(core.subprocess, "run", side_effect=subrun), \
         patch.object(core, "run_stream", side_effect=run_stream_b), \
         patch.object(core, "build_direct_env", return_value={}):
        try:
            core._preinstall_torch(vpy, str(kdir), logs.append,
                                   torch_ver="2.7.1", tv_ver="0.22.1",
                                   cu="cu128", label="第二引擎", force=True)
            raise AssertionError("应抛出本地安装失败错误")
        except RuntimeError as e:
            assert "本地安装 PyTorch 轮子失败" in str(e), e
    assert installs2["n"] == len(_mirs), installs2  # 所有国内镜像各试一次
    assert installs2["indexes"][0] == _mirs[0], installs2
    assert installs2["indexes"][-1] == _mirs[-1], installs2

    print("PREINSTALL_TORCH_MIRROR_FALLBACK_OK")

def test_preinstall_torch_force_reinstall_on_import_failure(base: Path):
    """torch「装上了但导入失败」时必须自动 --force-reinstall，而不是原样重试。

    2026-09-16 用户实证（NJFF / 第四引擎）日志原文：
        torch is already installed with the same version as the provided wheel.
        Use --force-reinstall to force an installation of the wheel.     ← pip 明说了解法
        [第四引擎] 验证：
        [第四引擎] PyTorch 预下载失败（第2/3 次）：torch 安装后导入失败
    —— pip 因「版本相同」**跳过了安装**：已装的 torch 若是残缺的（安装中断/被杀软清理），
    就永远修不好；外层 3 次重试跑的是**逐字相同**的命令，必然全部失败 ✗
    最后还报「下载/安装失败」，把用户引去重下 wheel、手动放缓存 —— 全都无用（wheel 明明被找到）。
    """
    kdir = base / "pf" / "kohya_ss"
    cache = base / "pf" / "cache" / "pytorch_wheels"
    cache.mkdir(parents=True, exist_ok=True)
    # 稀疏文件：逻辑大小满足 minsize，避免真写 3GB
    for _name, _size in (
            ("torch-2.10.0+cu128-cp312-cp312-win_amd64.whl", 1_000_000_000),
            ("torchvision-0.25.0+cu128-cp312-cp312-win_amd64.whl", 5_000_000)):
        with open(cache / _name, "wb") as _f:
            _f.truncate(_size)
    vpy = str(base / "pf" / "kohya_ss" / "fizgig_venv" / "Scripts" / "python.exe")

    def data_sub(*parts):
        return str(base.joinpath("pf", *parts))

    def make_subrun(fail_first_n):
        st = {"n": 0}

        def _sub(cmd, *a, **k):
            code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
            if "sys.version_info" in code:
                return result(0, "cp312")
            if "import torch, torchvision" in code:
                st["n"] += 1
                if st["n"] <= fail_first_n:
                    return result(1, "", "ImportError: DLL load failed while importing _C")
                return result(0, "2.10.0+cu128\nTrue\n")
            return result(0)
        return _sub, st

    streams = []

    def run_stream_ok(cmd, cwd=None, env=None, logf=print, **k):
        streams.append([str(x) for x in cmd])
        return 0

    # ---- 场景 A：普通安装后导入失败 → 自动强制重装 → 成功 ----
    sub_a, _ = make_subrun(1)          # 只失败第一次（= 普通安装之后那次）
    logs_a = []
    with patch.object(core, "data_sub", side_effect=data_sub), \
         patch.object(core, "_wheel_valid", return_value=True), \
         patch.object(core.subprocess, "run", side_effect=sub_a), \
         patch.object(core, "run_stream", side_effect=run_stream_ok), \
         patch.object(core, "build_direct_env", return_value={}):
        ok = core._preinstall_torch(vpy, str(kdir), logs_a.append,
                                    torch_ver="2.10.0", tv_ver="0.25.0",
                                    cu="cu128", label="第四引擎")
    assert ok is True, "强制重装后应当成功"
    _force = [c for c in streams if "--force-reinstall" in c]
    assert _force, "导入失败后没发起 --force-reinstall（等于原样重试，必然再次失败）"
    assert sum(1 for x in _force[0] if x.endswith(".whl")) == 2, _force[0]
    assert any("强制重装" in ln for ln in logs_a), logs_a

    # ---- 场景 B：强制重装后仍失败 → 报错必须说清「导入失败」而非「下载失败」 ----
    #（旧文案把环境问题说成下载问题，用户于是反复重下 wheel / 手动放缓存 —— 全都无用）
    sub_b, _ = make_subrun(99)
    logs_b = []
    with patch.object(core, "data_sub", side_effect=data_sub), \
         patch.object(core, "_wheel_valid", return_value=True), \
         patch.object(core.subprocess, "run", side_effect=sub_b), \
         patch.object(core, "run_stream", side_effect=run_stream_ok), \
         patch.object(core, "build_direct_env", return_value={}):
        try:
            core._preinstall_torch(vpy, str(kdir), logs_b.append,
                                   torch_ver="2.10.0", tv_ver="0.25.0",
                                   cu="cu128", label="第四引擎")
            raise AssertionError("强制重装后仍失败时应当报错")
        except RuntimeError as e:
            _m = str(e)
            assert "导入失败" in _m, _m
            assert "下载失败" not in _m, "又把环境问题说成下载问题：" + _m
            assert "fizgig_venv" in _m, "没给出可删除重建的环境目录"
            assert "不要反复重下" in _m, _m
    # 关键盲点：旧代码只打 stdout，导入失败时日志里只有一行「验证：」，
    # 真正的 stderr（ImportError/traceback）被丢掉 → 用户重跑三遍、我们也只能猜 ✗
    assert any("原始报错" in ln for ln in logs_b), "未把导入失败的原始报错打进日志"
    assert any("DLL load failed" in ln for ln in logs_b), "未把报错原文（traceback）打出来"
    assert any("VC++" in ln for ln in logs_b), "未识别「DLL load failed」→ 缺 VC++ 运行库"

    print("PREINSTALL_TORCH_FORCE_REINSTALL_OK")

class _FakeResp:
    def __init__(self, data=b"{}"):
        self._data = data
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def read(self):
        return self._data

def test_tokenizer_cache(base: Path):
    """_ensure_tokenizer_cached：内置离线复制 / 文件级多源下载 / auto 完整性 / transformers 兜底。"""
    kdir = base / "kit"
    builtin = kdir / "installers" / "tokenizers"
    cache = base / "tok_cache"
    logs = []
    vpy = str(base / "venv" / "Scripts" / "python.exe")
    fake_python(Path(vpy))
    clip_files = ("vocab.json", "merges.txt", "tokenizer_config.json", "special_tokens_map.json")

    # 场景 A：内置包完整 -> 直接复制，零联网
    a_src = builtin / "openai_clip-vit-large-patch14"
    a_src.mkdir(parents=True)
    for f in clip_files:
        (a_src / f).write_text("{}", encoding="utf-8")
    with patch.object(core, "KIT_DIR", str(kdir)):
        ok = core._ensure_tokenizer_cached(str(cache), "openai/clip-vit-large-patch14", logs.append, "clip", vpy)
    assert ok is True, logs
    dst = cache / "openai_clip-vit-large-patch14"
    assert all((dst / f).is_file() for f in clip_files)
    assert any("无需联网" in ln for ln in logs), logs

    # 场景 B：内置缺失 + 文件级多源下载成功（hf-mirror/魔搭，直连）
    logs.clear()
    def fake_opener(*a, **k):
        return SimpleNamespace(open=lambda url, timeout=30: _FakeResp(b"tok"))
    with patch.object(core, "KIT_DIR", str(kdir)), \
         patch.object(core.urllib.request, "build_opener", side_effect=fake_opener):
        ok = core._ensure_tokenizer_cached(str(cache), "some/other-tokenizer", logs.append, "clip", vpy)
    assert ok is True, logs
    dst2 = cache / "some_other-tokenizer"
    assert all((dst2 / f).is_file() for f in clip_files), logs
    assert any("下载" in ln for ln in logs), logs

    # 场景 C：auto 类型只有 spiece.model（无 tokenizer.json）也应判定完整（内置 T5）
    logs.clear()
    t5 = builtin / "google_t5-v1_1-xxl"
    t5.mkdir(parents=True)
    (t5 / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    (t5 / "special_tokens_map.json").write_text("{}", encoding="utf-8")
    (t5 / "spiece.model").write_bytes(b"sp")
    with patch.object(core, "KIT_DIR", str(kdir)):
        ok = core._ensure_tokenizer_cached(str(cache), "google/t5-v1_1-xxl", logs.append, "auto", vpy)
    assert ok is True, logs
    t5dst = cache / "google_t5-v1_1-xxl"
    assert (t5dst / "spiece.model").is_file(), logs

    # 场景 D：内置/下载全失败 -> transformers from_pretrained 兜底
    logs.clear()
    def subrun_ok(cmd, *args, **kwargs):
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "from_pretrained" in code:
            return result(0, "tok_ok\n")
        return result(0)
    def fake_opener_fail(*a, **k):
        raise OSError("network down")
    with patch.object(core, "KIT_DIR", str(kdir)), \
         patch.object(core.urllib.request, "build_opener", side_effect=fake_opener_fail), \
         patch.object(core.subprocess, "run", side_effect=subrun_ok):
        ok = core._ensure_tokenizer_cached(str(cache), "nope/missing-tok", logs.append, "auto", vpy)
    assert ok is True, logs
    assert any("预缓存分词器" in ln for ln in logs), logs

    print("TOKENIZER_CACHE_UNIT_TESTS_OK")

def test_external_python_safe_cwd(base: Path):
    """_external_python_safe_cwd：当前 cwd 含 python312.dll（打包版应用目录）时必须切走，
    避免 Windows DLL 搜索命中打包版 DLL 导致 venv 的 _ctypes/numpy 崩溃。"""
    venv_python = r"E:\Lora-Tool\KohyaLoraTool_data\kohya_ss\venv\Scripts\python.exe"
    argv = [venv_python, "-c", "import numpy"]
    tmp = str(base / "TEMP")
    (base / "TEMP").mkdir(parents=True, exist_ok=True)

    # 场景 A：cwd 是打包版应用目录（含 python312.dll）-> 切到系统临时目录
    dirty = str(base / "KohyaTool")
    (base / "KohyaTool").mkdir(parents=True, exist_ok=True)
    def _glob(patt):
        patt = os.path.normpath(patt)
        if patt.startswith(os.path.normpath(dirty)):
            return [os.path.join(os.path.dirname(patt), "python312.dll")]
        return []

    with patch.object(core.os, "getcwd", return_value=dirty), \
         patch.object(core.glob, "glob", side_effect=_glob), \
         patch.object(core.tempfile, "gettempdir", return_value=tmp), \
         patch.object(core.os.path, "isdir", return_value=True):
        got = core._external_python_safe_cwd(argv)
    assert got == tmp, f"A: expect tempdir, got {got!r}"

    # 场景 B：cwd 干净 -> 用解释器自己的 Scripts 目录
    clean = str(base / "home")
    (base / "home").mkdir(parents=True, exist_ok=True)
    with patch.object(core.os, "getcwd", return_value=clean), \
         patch.object(core.glob, "glob", return_value=[]), \
         patch.object(core.os.path, "isdir", return_value=True):
        got = core._external_python_safe_cwd(argv)
    assert got == os.path.dirname(venv_python), f"B: expect Scripts dir, got {got!r}"

    # 场景 C：调用方显式传 cwd -> 保持不变（训练脚本 cwd 不能被篡改）
    with patch.object(core.glob, "glob", return_value=[os.path.join(clean, "python312.dll")]):
        got = core._external_python_safe_cwd(argv, current_cwd=clean)
    assert got == clean, f"C: expect explicit cwd unchanged, got {got!r}"

    # 场景 D：非 python 可执行（git）-> 不干预
    got = core._external_python_safe_cwd([r"C:\Program Files\Git\cmd\git.exe", "status"])
    assert got is None, f"D: expect None for non-python, got {got!r}"

    print("EXTERNAL_PYTHON_SAFE_CWD_UNIT_TESTS_OK")

def test_amd_download_progress(base: Path):
    """AMD 大文件阶段会向调用方上报下载进度，且不触发真实网络/安装。"""
    events = []
    logs = []
    rocm_urls = [
        "https://repo.radeon.com/test/rocm_a-1.0-py3-none-win_amd64.whl",
        "https://repo.radeon.com/test/rocm_b-1.0-py3-none-win_amd64.whl",
    ]
    torch_urls = ["https://repo.radeon.com/test/torch-1.0-cp312-win_amd64.whl"]

    def fake_download(url, dest, logf=print, progress_cb=None, **kwargs):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"test-wheel-data")
        if progress_cb:
            progress_cb(4, 16)
            progress_cb(16, 16)
        return True

    def progress(stage, filename, done, total, index, count):
        events.append((stage, filename, done, total, index, count))

    patches = (
        patch.object(core, "data_dir", return_value=str(base / "data")),
        patch.object(core, "AMD_ROC_WHEELS", rocm_urls),
        patch.object(core, "_amd_torch_wheels", return_value=torch_urls),
        patch.object(core, "_wheel_valid", return_value=False),
        patch.object(core, "_download_with_resume", side_effect=fake_download),
        patch.object(core, "run_pip_in_venv", return_value=0),
    )
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        core.install_amd_rocm("fake-venv", logs.append, progress)
        core.install_amd_torch("fake-venv", logs.append, progress)
    assert events[0][:2] == ("ROCm", "rocm_a-1.0-py3-none-win_amd64.whl"), events
    assert events[0][2:6] == (4, 16, 1, 2), events
    assert any(e[0] == "ROCm" and e[4] == 2 and e[5] == 2 for e in events), events
    assert any(e[0] == "PyTorch" and e[2:6] == (16, 16, 1, 1) for e in events), events
    print("AMD_DOWNLOAD_PROGRESS_UNIT_TEST_OK")

def test_amd_torch_verification(base: Path):
    """AMD 最终验证保留真实错误，并区分正常 ROCm 与 GPU 不可用。"""
    venv = base / "amd_verify" / "venv_amd"
    fake_python(venv / "Scripts" / "python.exe")

    ok_result = result(0, (
        "TORCH_VERSION=2.9.1+rocm7.2.1\n"
        "HIP_VERSION=7.2.1\n"
        "CUDA_VERSION=\n"
        "GPU_AVAILABLE=True\n"
        "GPU_NAME=AMD Radeon RX 7900 XTX\n"
    ))
    with patch.object(core.subprocess, "run", return_value=ok_result):
        ok, info, avail = core.verify_amd_torch(str(venv))
    assert ok and avail, (ok, info, avail)
    assert "2.9.1+rocm7.2.1" in info and "HIP 7.2.1" in info, info

    import_error = result(1, "", "OSError: [WinError 126] 找不到指定的模块。\nError loading amdhip64_7.dll")
    with patch.object(core.subprocess, "run", return_value=import_error):
        ok, info, avail = core.verify_amd_torch(str(venv))
    assert not ok and not avail, (ok, info, avail)
    assert "amdhip64_7.dll" in info and info != "?", info

    cpu_result = result(0, (
        "TORCH_VERSION=2.9.1+rocm7.2.1\n"
        "HIP_VERSION=7.2.1\n"
        "CUDA_VERSION=\n"
        "GPU_AVAILABLE=False\n"
        "GPU_NAME=\n"
    ))
    with patch.object(core.subprocess, "run", return_value=cpu_result):
        ok, info, avail = core.verify_amd_torch(str(venv))
    assert not ok and not avail, (ok, info, avail)
    assert "GPU 不可用" in info and "HIP 7.2.1" in info, info

    print("AMD_TORCH_VERIFICATION_UNIT_TEST_OK")

def test_accelerate_module_launcher(base: Path):
    """训练启动器必须使用当前 venv 的 Python 模块，而不是系统 accelerate.exe。"""
    venv = base / "launcher" / "venv"
    py = venv / "Scripts" / "python.exe"
    fake_python(py)
    good = result(0, "1.14.0\nF:/venv/Lib/site-packages/accelerate/__init__.py\n" + str(py) + "\n")
    with patch.object(core.subprocess, "run", return_value=good), patch.object(core, "build_env", return_value={}):
        cmd = core._accelerate_launch_cmd(str(py))
    assert cmd[:3] == [str(py), "-m", "accelerate.commands.launch"], cmd

    mismatch = result(0, "1.14.0\nC:/Python312/Lib/site-packages/accelerate/__init__.py\nC:/Python312/python.exe\n")
    with patch.object(core.subprocess, "run", return_value=mismatch), patch.object(core, "build_env", return_value={}):
        try:
            core._accelerate_launch_cmd(str(py))
        except RuntimeError as e:
            assert "不属于同一环境" in str(e), e
        else:
            raise AssertionError("system accelerate mismatch should be rejected")
    print("ACCELERATE_MODULE_LAUNCHER_UNIT_TEST_OK")

def test_main_engine_accel_always_defined(base: Path):
    """v0.9.18 回归：accel 只在 AMD 自定义环境分支赋值，普通 NVIDIA 用户训练启动即
    UnboundLocalError（cannot access local variable 'accel'）。现在主引擎 train()
    必须无条件调用 _accelerate_launch_cmd(vpy)，任何模式都能拿到启动器。"""
    src = Path(core.__file__).read_text(encoding="utf-8-sig")
    bad = ('if amd_mode and (params.get("train_env") or "").strip():\n'
           '        accel = _accelerate_launch_cmd(vpy)')
    assert bad not in src, "accel 仍只在 AMD 分支赋值（v0.9.18 回归未修复）"
    m = re.search(r"^    accel = _accelerate_launch_cmd\(vpy(?:, logf=logf)?\)$", src, re.M)
    assert m, "主引擎 train() 未找到无条件 accel 赋值"
    print("MAIN_ENGINE_ACCEL_ALWAYS_DEFINED_UNIT_TEST_OK")

def test_sample_preview_16g_default_off(base):
    """16G 档采样预览默认关（Krea2/FLUX.2 显存紧，采样残留显存导致越跑越慢）；20G+ 默认开；显式开启被尊重。"""
    assert core._sample_preview_enabled({}, 16) is False, "16G 默认关"
    assert core._sample_preview_enabled({}, 15.67) is False, "4080S 16G 默认关"
    assert core._sample_preview_enabled({}, 24) is True, "24G 默认开"
    assert core._sample_preview_enabled({}, None) is True, "未知显存默认开（兼容旧行为）"
    assert core._sample_preview_enabled({"sample_preview": True}, 16) is True, "用户显式开启被尊重"
    assert core._sample_preview_enabled({"sample_preview": False}, 24) is False, "用户显式关闭被尊重"
    print("SAMPLE_PREVIEW_16G_DEFAULT_OFF_OK")

def test_preset_for_fallback(base):
    """preset_for：底模类型与模式不匹配（style+flux2）时回退默认档，不抛 KeyError（UI 卡死 bug 修复）。"""
    import io as _io
    assert core.preset_for("style", "sd15").get("rank"), "正常档"
    p = core.preset_for("style", "flux2")     # style 无 flux2 档 → 回退 sd15，不崩
    assert p.get("rank") and p == core.preset_for("style", "sd15"), p
    assert core.preset_for("krea2", "flux2").get("rank"), "krea2 也无 flux2 档应回退"
    assert core.preset_for("nope", "x") == {}, "未知模式返回空"
    # 引擎导航覆盖全部 MODE_KEYS（GUI 常量，从源文件断言）
    gsrc = _io.open(ROOT / "kohya_gui.py", encoding="utf-8").read()
    assert "ENGINE_GROUPS" in gsrc and "SHORT_MODE_LABELS" in gsrc
    for mk in core.MODE_KEYS:
        assert ('"%s"' % mk) in gsrc, "引擎导航缺少模式 " + mk
    print("PRESET_FOR_FALLBACK_OK")

def test_at_image_ms_parse_skips_dirs(base):
    """_parse_at_image_ms_files：只取文件（Type=blob），跳过目录（Type=tree）与非必要文件。"""
    d = {"Data": {"Files": [
        {"Path": "vae", "Type": "tree", "Size": 0},
        {"Path": "transformer", "Type": "tree", "Size": 0},
        {"Path": "vae/config.json", "Type": "blob", "Size": 820},
        {"Path": "vae/diffusion_pytorch_model.safetensors", "Type": "blob", "Size": 167666902},
        {"Path": "transformer/config.json", "Type": "blob", "Size": 500},
        {"Path": ".gitattributes", "Type": "blob", "Size": 3027},
        {"Path": "README.md", "Type": "blob", "Size": 6015},
    ]}}
    files = core._parse_at_image_ms_files(d)
    assert "vae" not in files and "transformer" not in files, files      # 目录必须跳过
    assert "vae/config.json" in files and "vae/diffusion_pytorch_model.safetensors" in files, files
    assert ".gitattributes" not in files and "README.md" not in files, files  # 非必要文件跳过
    print("AT_IMAGE_MS_PARSE_SKIPS_DIRS_OK")

def test_safetensors_complete_check(base):
    """_safetensors_complete：截断/损坏的 safetensors 能被识别（训练前拦截，避免 reshape 英文错）。"""
    import struct
    import json as _json
    # 完整文件：header 声明 4 元素 + 16 字节数据
    p = base / "ok.safetensors"
    header = {"t": {"dtype": "F32", "shape": [4], "data_offsets": [0, 16]}}
    hb = _json.dumps(header, separators=(",", ":")).encode("utf-8")
    p.write_bytes(struct.pack("<Q", len(hb)) + hb + b"\x00" * 16)
    assert core._safetensors_complete(str(p)) is True
    # 截断：头部声明 3981312 元素（15925248 字节）但实际只有 8 字节 → 不完整
    p2 = base / "trunc.safetensors"
    header2 = {"t": {"dtype": "F32", "shape": [384, 384, 3, 3, 3], "data_offsets": [0, 15925248]}}
    hb2 = _json.dumps(header2, separators=(",", ":")).encode("utf-8")
    p2.write_bytes(struct.pack("<Q", len(hb2)) + hb2 + b"\x00" * 8)
    assert core._safetensors_complete(str(p2)) is False
    assert core._safetensors_complete(str(base / "nonexistent.safetensors")) is False
    print("SAFETENSORS_COMPLETE_CHECK_OK")

def test_modelscope_mirror_urls(base):
    """Krea2/FLUX.2 模型链接与 AT_IMAGE 下载全部魔搭化（hf-mirror 故障/被污染后不再依赖）。"""
    for key in ("vae", "te"):
        _f, _d, u = core.KREA2_MODEL_LINKS[key]
        assert "modelscope.cn" in u and "hf-mirror.com" not in u, (key, u)
    for key in ("dit", "te", "vae"):
        _f, _d, u = core.FLUX2_MODEL_LINKS[key]
        assert "modelscope.cn" in u and "hf-mirror.com" not in u, (key, u)
    # AT_IMAGE 魔搭仓库覆盖全部模式
    for mode in core.AT_IMAGE_MODELS:
        assert mode in core.AT_IMAGE_MS_REPOS, mode
    # 文件清单函数对非法仓库返回 None（不抛异常）
    assert core._at_image_ms_file_list("NoSuch/Repo_0000") is None
    print("MODELSCOPE_MIRROR_URLS_OK")

def test_train_monitor_krea2_parsing(base):
    """TrainMonitor 解析 Krea2 tqdm（avr_loss=）与缓存→训练阶段切换（监控面板数据来源）。"""
    mon = core.TrainMonitor()
    mon.start(total=696)
    # 缓存阶段：不应更新训练步数
    mon.on_line("INFO:musubi_tuner.dataset.cache_io:caching latents...")
    assert mon.snapshot().get("phase") == "cache", mon.snapshot()
    # Krea2 训练 tqdm：1/696 [.., 30.88s/it, avr_loss=0.0582]
    mon.on_line("steps:   1%|\u258f         | 4/696 [02:03<5:56:05, 30.88s/it, avr_loss=0.0582]")
    s = mon.snapshot()
    assert s.get("phase") == "train", s
    assert s.get("step") == 4, s
    assert s.get("total") == 696, s
    assert abs(s.get("loss") - 0.0582) < 1e-6, s
    assert abs(s.get("speed") - 1.0 / 30.88) < 1e-6, s
    # 包装函数：日志行喂给 monitor
    calls = []
    def _lf(x): calls.append(x)
    m2 = core.TrainMonitor()
    wrapped = core._attach_train_monitor(_lf, m2, lr=1e-4)
    m2.set_total(696)   # 真实流程：接线后训练函数会 set_total
    wrapped("steps:   2%|\u258e | 8/696 [.., 10.0s/it, avr_loss=0.05]")
    assert m2.snapshot().get("step") == 8 and calls == ["steps:   2%|\u258e | 8/696 [.., 10.0s/it, avr_loss=0.05]"]
    assert abs(m2.snapshot().get("lr") - 1e-4) < 1e-12, m2.snapshot()
    print("TRAIN_MONITOR_KREA2_PARSING_OK")

def test_prequantized_krea2_raw_detected(base):
    """Krea2 预量化 fp8/int8 底模必须被识别（训练前拦截，musubi 0.3.4 不支持预量化 Krea2 训练）。"""
    import struct
    import json as _json
    p = base / "prequant_raw.safetensors"
    header = {"__metadata__": {}, "blocks.0.attn.wq.weight": {"dtype": "F8_E4M3", "shape": [4, 4], "data_offsets": [0, 16]}}
    hb = _json.dumps(header, separators=(",", ":")).encode("utf-8")
    p.write_bytes(struct.pack("<Q", len(hb)) + hb + b"\x00" * 16)
    assert core._safetensors_is_prequantized(str(p)) is True, "fp8 预量化底模应判为 prequantized"
    p2 = base / "bf16_raw.safetensors"
    header2 = {"__metadata__": {}, "blocks.0.attn.wq.weight": {"dtype": "BF16", "shape": [4, 4], "data_offsets": [0, 32]}}
    hb2 = _json.dumps(header2, separators=(",", ":")).encode("utf-8")
    p2.write_bytes(struct.pack("<Q", len(hb2)) + hb2 + b"\x00" * 32)
    assert core._safetensors_is_prequantized(str(p2)) is False, "bf16 原版底模不应判为 prequantized"
    print("PREQUANTIZED_KREA2_RAW_DETECTED_OK")

def test_low_ram_swap(base):
    """低内存（<32G）自动降 swap：Krea2 12/16G 档 12→6、FLUX.2 12G 档 6→4；
    ≥32G / 8G 档 / 高显存档不受影响（2026-08-29 3060 12G + 16G 内存卡第一步待办）。"""
    # Krea2
    assert core._resolve_krea2_swap(12, ram_gb=16) == (6, True)
    assert core._resolve_krea2_swap(16, ram_gb=16) == (6, True)
    assert core._resolve_krea2_swap(20, ram_gb=16) == (6, False)   # 本已是 6
    assert core._resolve_krea2_swap(24, ram_gb=16) == (2, False)   # 本已是 2
    assert core._resolve_krea2_swap(12, ram_gb=32) == (12, True)   # >=32G 不降
    assert core._resolve_krea2_swap(12) == (12, True)              # ram_gb 缺省不降
    assert core._resolve_krea2_swap(8, ram_gb=16) == (24, True)    # 8G 档不降（显存受限）
    # FLUX.2
    assert core._resolve_flux2_swap(12, ram_gb=16) == (4, True)
    assert core._resolve_flux2_swap(12, ram_gb=32) == (6, True)
    assert core._resolve_flux2_swap(8, ram_gb=16) == (10, True)    # 8G 档不降
    assert core._resolve_flux2_swap(16, ram_gb=16) == (2, True)
    # _warn_low_ram：<32G 打印警告；>=32G / None 静默
    out = []
    core._warn_low_ram(out.append, 16, "Krea2")
    assert any("建议 32G" in x for x in out), "低内存应警告"
    out2 = []
    core._warn_low_ram(out2.append, 32, "Krea2")
    core._warn_low_ram(out2.append, None, "Krea2")
    assert out2 == [], ">=32G / None 不应警告"
    print("LOW_RAM_SWAP_AUTO_OK")

def test_flux2_first_engine_guard(base):
    """FLUX.2 底模不能在第一引擎训练：_looks_like_flux2 识别 + train() 拦截。"""
    # 文件名识别
    assert core._looks_like_flux2(r"I:\models\flux2\flux-2-klein-base-4b.safetensors") is True
    assert core._looks_like_flux2(r"I:\models\krea2\raw.safetensors") is False
    assert core._looks_like_flux2(r"I:\models\base\flux1-dev.safetensors") is False
    # 第一引擎 train() 拦截（Krea2 同款逻辑，直接用 _looks_like_flux2 短路验证）
    import unittest.mock as _m
    with _m.patch.object(core, "_looks_like_flux2", return_value=True):
        try:
            core.train(logf=lambda *a: None, base_model=r"I:\models\flux2\flux-2-klein-base-4b.safetensors",
                       mode="character", params={"base_model": r"I:\models\flux2\flux-2-klein-base-4b.safetensors"})
            raise AssertionError("应拦截 FLUX.2 底模在第一引擎训练")
        except RuntimeError as e:
            assert "FLUX.2" in str(e) and "第二引擎" in str(e), "拦截文案应引导去第二引擎"
    print("FLUX2_FIRST_ENGINE_GUARD_OK")

def test_igpu_filter(base):
    """AMD 平台优先识别到核显的回归测试：核显名称必须被过滤，独显名称不能误杀。

    背景：AMD 核显在 DXGI/WMI 里常排第一，且设备管理器禁用核显后 WMI 仍会列出，
    detect_gpu_name() 之前用 `Select-Object -First 1` 会优先取到核显（2026-08-29 用户反馈）。
    """
    from kohya_core import gpu as _gpu
    igpu = [
        "AMD Radeon(TM) Graphics", "AMD Radeon Graphics", "AMD Radeon(TM) Radeon Graphics",
        "AMD Radeon 780M", "AMD Radeon(TM) 680M", "AMD Radeon 610M", "AMD Radeon(TM) 890M",
        "AMD Radeon(TM) Vega 8 Graphics",
        "Intel(R) UHD Graphics", "Intel(R) Iris(R) Xe Graphics",
        "Microsoft Basic Display Adapter", "Microsoft Basic Render Driver",
    ]
    dgpu = [
        "AMD Radeon RX 6800 XT", "AMD Radeon RX 6600", "AMD Radeon RX Vega 56",
        "AMD Radeon PRO W6800", "AMD Radeon RX 6800M", "AMD Radeon RX 6600M", "AMD Radeon VII",
        "NVIDIA GeForce RTX 4070", "NVIDIA GeForce GTX 1080",
        "Intel(R) Arc(TM) A770 Graphics", "Intel(R) Arc(TM) A750",
    ]
    for n in igpu:
        assert _gpu._is_igpu_name(n), "核显应判为 iGPU: %s" % n
    for n in dgpu:
        assert not _gpu._is_igpu_name(n), "独显不应判为 iGPU: %s" % n
    # detect_gpu_name / detect_vram_gb 在本机可正常调用（不抛异常）
    try:
        core.detect_gpu_name()
        core.detect_vram_gb()
    except Exception as e:
        raise AssertionError("detect_gpu_name/detect_vram_gb 调用异常: %s" % e)
    print("GPU_IGPU_FILTER_OK")

def test_swap_tier_resolution(base):
    """Krea2/FLUX.2 块交换档位：16G 卡（DXGI 报告 15.6~15.9）取整后走 16-24G 档，不再误判 12G 档。

    2026-08-27 4080S 用户实测：15.67GB 被误判 <16 → swap=12（每步搬 12 个块）→ 11~17s/it。
    修复后 15.67 → 取整 16 → Krea2 swap=6 / FLUX.2 swap=2，H2D-only 保持开启。
    """
    # Krea2
    assert core._resolve_krea2_swap(8) == (24, True)
    assert core._resolve_krea2_swap(12) == (12, True)
    assert core._resolve_krea2_swap(15.67) == (12, True)    # 4080S 16G：int8+swap12 实测 7s/it 最快最稳
    assert core._resolve_krea2_swap(16) == (12, True)
    assert core._resolve_krea2_swap(18) == (12, False)   # 18G>16，H2D-only 关闭（与旧行为一致）
    assert core._resolve_krea2_swap(20) == (6, False)       # 20G 档 swap=6，H2D-only 关闭（与旧行为一致）
    assert core._resolve_krea2_swap(24) == (2, False)
    assert core._resolve_krea2_swap(None) == (24, True)
    assert core._resolve_krea2_swap(15.67, gc_on=False) == (12, False)
    # FLUX.2
    assert core._resolve_flux2_swap(8) == (10, True)
    assert core._resolve_flux2_swap(12) == (6, True)
    assert core._resolve_flux2_swap(15.67) == (2, True)     # 4080S 16G
    assert core._resolve_flux2_swap(16) == (2, True)
    assert core._resolve_flux2_swap(20) == (2, False)   # 20G 与旧行为一致，H2D-only 关闭
    assert core._resolve_flux2_swap(24) == (0, False)   # 24G 全驻留，无需交换（原逻辑）
    assert core._resolve_flux2_swap(None) == (10, True)
    print("SWAP_TIER_RESOLUTION_OK")

def test_quant_mode_resolution(base):
    """_resolve_quant_mode：档位默认 / 显式指定 / NF4 回退。"""
    fake_vpy = object()
    real_ensure = core._ensure_musubi_bnb
    real_probe = core._probe_nf4
    try:
        core._ensure_musubi_bnb = lambda mvpy, logf=print, label="X": True
        core._probe_nf4 = lambda vpy, logf=print, timeout=180: (True, "ok")
        # ★ 2026-09-17 变更：auto 档**一律 int8**（原先是 (None/24,"auto") 期望 fp8 ✗）。
        # 用户汇总实测（512px）：4090 24G fp8 7s/步 → int8 **1s/步**；
        # 16G 卡 fp8 50~100s/步 → int8 **2.2s/步**。
        # 根因：K2 的 fp8 没用上 scaled_mm（per-channel 与它不兼容），每步要反量化回 bf16；
        # 与块交换叠加后代价放大 —— 详见 Kohya一键工具.py 里 _resolve_quant_mode 的注释。
        # 显式 fp8 / int8 / nf4 的选择仍然照旧尊重 ✓（下面几条没动）。
        cases = [
            ((None, "auto"), "int8"), ((8, "auto"), "int8"), ((12, "auto"), "int8"),
            ((14, "auto"), "int8"), ((15.67, "auto"), "int8"),  # 4080S 16G：实测 int8+swap12=7s/it，fp8 反而慢
            ((16, "auto"), "int8"), ((24, "auto"), "int8"), ((47.48, "auto"), "int8"),
            ((8, "fp8"), "fp8"), ((8, "int8"), "int8"),
            ((8, "nf4"), "nf4"), ((24, "nf4"), "nf4"),
        ]
        for (vram, req), expect in cases:
            q, _ = core._resolve_quant_mode(fake_vpy, print, vram, label="T", requested=req)
            assert q == expect, (vram, req, q, expect)
        core._probe_nf4 = lambda vpy, logf=print, timeout=180: (False, "kernel fail")
        q, _ = core._resolve_quant_mode(fake_vpy, print, 8, label="T", requested="nf4")
        assert q == "fp8", "NF4 预检失败应回退 fp8"
    finally:
        core._ensure_musubi_bnb = real_ensure
        core._probe_nf4 = real_probe
    print("QUANT_MODE_RESOLUTION_UNIT_TESTS_OK")

def test_musubi_offload_device_patch(base: Path):
    """musubi custom_offloading_utils.py 块交换设备兼容补丁：AMD ROCm 不硬调 torch.cuda.current_device()。"""
    mdir = base / "kohya_ss" / "musubi-tuner" / "src" / "musubi_tuner" / "modules"
    mdir.mkdir(parents=True, exist_ok=True)
    fp = mdir / "custom_offloading_utils.py"
    old_line = "            dev = self.device.index if self.device.index is not None else torch.cuda.current_device()"
    fp.write_text("def move_blocks(...):\n" + old_line + "\n            torch.cuda.set_device(dev)\n", encoding="utf-8")
    logs = []
    core._patch_musubi_offload_device(str(base / "kohya_ss"), logs.append)
    src = fp.read_text(encoding="utf-8")
    assert "elif torch.cuda.is_available():" in src, src
    assert old_line not in src, src
    # 幂等：再打一次不重复插入
    core._patch_musubi_offload_device(str(base / "kohya_ss"), logs.append)
    src2 = fp.read_text(encoding="utf-8")
    assert src2.count("elif torch.cuda.is_available():") == 1, src2
    # 结构变化（找不到原行）→ 不崩、跳过
    fp.write_text("def move_blocks(...):\n    pass\n", encoding="utf-8")
    core._patch_musubi_offload_device(str(base / "kohya_ss"), logs.append)
    # 已接入 Krea2/FLUX.2 聚合路径与 Anima 路径
    main_src = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8")
    assert main_src.count("_patch_musubi_offload_device(_kdir, logf)") >= 1, main_src
    assert main_src.count("_patch_musubi_offload_device(kdir, logf)") >= 1, main_src
    print("MUSUBI_OFFLOAD_DEVICE_PATCH_OK")

def test_musubi_quant_patch(base):
    """musubi INT8/NF4 补丁：对随包 musubi-tuner-main.zip 应用全部成功且幂等。"""
    import zipfile
    from kohya_core.musubi_quant_patch import patch_musubi_quant_base, _patch_fp8_utils,         _patch_lora_utils, _patch_krea2_utils, _patch_krea2_train, _patch_flux2_utils, _patch_flux2_train
    zip_path = ROOT / "installers" / "musubi-tuner" / "musubi-tuner-main.zip"
    assert zip_path.is_file(), f"缺少随包 musubi 源码: {zip_path}"
    dst = base / "musubi_patch_test"
    with zipfile.ZipFile(str(zip_path)) as z:
        z.extractall(str(dst))
    mt = dst / "musubi-tuner-main" / "src" / "musubi_tuner"
    rs = [
        _patch_fp8_utils(mt, print), _patch_lora_utils(mt, print),
        _patch_krea2_utils(mt, print), _patch_krea2_train(mt, print),
        _patch_flux2_utils(mt, print), _patch_flux2_train(mt, print),
    ]
    assert all(rs), f"补丁应全部首次应用成功: {rs}"
    # 幂等：第二次全部跳过
    rs2 = [
        _patch_fp8_utils(mt, print), _patch_lora_utils(mt, print),
        _patch_krea2_utils(mt, print), _patch_krea2_train(mt, print),
        _patch_flux2_utils(mt, print), _patch_flux2_train(mt, print),
    ]
    assert not any(rs2), f"补丁应幂等（第二次全跳过）: {rs2}"
    print("MUSUBI_QUANT_PATCH_UNIT_TESTS_OK")

def test_accelerate_cpu_config_self_heal(base):
    """残留 accelerate use_cpu=true 自愈：检测→修复→复核；launch 显式单进程、配置干净零探测。"""
    cfg = base / "accelerate" / "default_config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('{\n  "use_cpu": true,\n  "num_processes": 2\n}\n', encoding="utf-8")

    real_path = core._accelerate_config_path
    real_run = core.subprocess.run
    real_probe = core._probe_accelerate_device
    try:
        core._accelerate_config_path = lambda: str(cfg)
        # 1) 检测 + 修复
        assert core._accelerate_config_use_cpu() is True
        assert core._neutralize_accelerate_cpu_config(print) is True
        raw = cfg.read_text(encoding="utf-8")
        assert '"use_cpu": false' in raw and '"use_cpu": true' not in raw
        assert core._accelerate_config_use_cpu() is False

        # 2) 配置干净时 launch 零探测，且 argv 带显式单进程
        calls = []
        def fake_run(cmd, **kw):
            calls.append(cmd)
            return result(0, stdout="accelerate 1.0.0\nC:\\x\\accelerate\\__init__.py\n" + str(cmd[0]))
        core.subprocess.run = fake_run
        core._probe_accelerate_device = lambda *a, **k: (_ for _ in ()).throw(AssertionError("干净配置不应触发探测"))
        argv = core._accelerate_launch_cmd(str(cfg))   # vpy 用存在的配置文件路径占位，fake_run 不真执行
        assert argv[1:3] == ["-m", "accelerate.commands.launch"]
        assert "--num_processes" in argv and "--num_machines" in argv

        # 3) use_cpu=true 时 launch 内自动修复 + 复核（探测返回 cuda）
        cfg.write_text('{"use_cpu": true}', encoding="utf-8")
        core._probe_accelerate_device = lambda *a, **k: "cuda:0"
        argv2 = core._accelerate_launch_cmd(str(cfg))
        assert '"use_cpu": false' in cfg.read_text(encoding="utf-8")
        assert "--num_processes" in argv2
    finally:
        core._accelerate_config_path = real_path
        core.subprocess.run = real_run
        core._probe_accelerate_device = real_probe
    print("ACCELERATE_CPU_CONFIG_SELF_HEAL_OK")

def test_anima_vae_fp32_patch(base: Path):
    """Anima VAE fp32 补丁：对随包 sd-scripts anima_train_network.py 首次应用成功 + 幂等。"""
    import zipfile
    zip_path = ROOT / "installers" / "kohya_ss" / "sd-scripts-main.zip"
    assert zip_path.is_file(), f"缺少随包 sd-scripts 源码: {zip_path}"
    kdir = base / "kohya_ss"
    target = kdir / "sd-scripts" / "anima_train_network.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(zip_path)) as z:
        target.write_bytes(z.read("sd-scripts-main/anima_train_network.py"))
    core._patch_anima_vae_fp32(str(kdir), print)
    src = target.read_text(encoding="utf-8")
    assert "ANIMA_VAE_FP32" in src and "KOHYA_TOOL_PATCH_BEGIN" in src, "补丁未应用"
    assert "vae.to(torch.float32)" in src, "fp32 分支缺失"
    core._patch_anima_vae_fp32(str(kdir), print)   # 幂等
    cnt = src.count("KOHYA_TOOL_PATCH_BEGIN: anima VAE fp32")
    assert cnt == 1, f"补丁应只出现一次，实际 {cnt}"
    print("ANIMA_VAE_FP32_PATCH_OK")

def test_dataset_config_is_reg_subset(base: Path):
    """is_reg 必须写在 [[datasets.subsets]] 子集层，不能写在 [[datasets]] 层（issue #3）。"""
    import preprocess
    train = base / "train"; reg = base / "reg"
    train.mkdir(parents=True, exist_ok=True); reg.mkdir(parents=True, exist_ok=True)
    cfg = base / "dataset_config.toml"
    preprocess.write_dataset_config(str(train), str(cfg), resolution=1024, num_repeats=5, reg_dir=str(reg))
    txt = cfg.read_text(encoding="utf-8")
    blocks = txt.split("[[datasets]]")
    assert len(blocks) == 3, f"应含训练+正则两个数据集块: {len(blocks)-1}"
    for b in blocks[1:]:
        ds = [l for l in b.splitlines() if l.strip() and not l.startswith("  ")]
        assert not any("is_reg" in l for l in ds), f"datasets 层不应有 is_reg: {ds}"
    assert "  is_reg = true" in blocks[2], "正则子集应含 is_reg=true"
    print("DATASET_CONFIG_IS_REG_SUBSET_OK")

def test_diagnose_optimizer_failure_scenarios(base: Path):
    """_diagnose_optimizer_failure：配置校验错误优先、bnb 命中、OOM/命令重印不误报。"""
    def run(txt):
        buf = []
        ok = core._diagnose_optimizer_failure(None, txt, buf.append)
        return ok, "\n".join(buf)
    # 1) voluptuous 配置校验失败（issue #3 主场景）
    ok, out = run(
        "voluptuous.error.MultipleInvalid: extra keys not allowed @ data['datasets'][1]['is_reg']\n"
        "subprocess.CalledProcessError: Command '[... --optimizer_type=AdamW8bit ...]' returned non-zero exit status 1."
    )
    assert ok and "数据集配置" in out and "is_reg" in out and "bitsandbytes" not in out, out
    # 2) 真实 bitsandbytes 崩溃仍命中（日志含命令行回显，opt_k 可解析）
    ok, out = run(
        "$ C:\\x\\python.exe -m accelerate.commands.launch ... --optimizer_type=AdamW8bit ...\n"
        "Traceback: NameError: name 'str2optimizer8bit_blockwise' is not defined\n"
        "bitsandbytes CUDA binary not found ... libbitsandbytes_cuda128.dll"
    )
    assert ok and "bitsandbytes" in out, out
    # 3) CalledProcessError 重印命令 + OOM 不误报
    ok, out = run(
        "subprocess.CalledProcessError: Command '[... --optimizer_type=AdamW8bit ...]' returned non-zero exit status 1.\n"
        "CUDA out of memory."
    )
    assert not ok, "OOM 不应误报 bnb"
    # 4) 正常日志不触发
    ok, out = run("steps: 1/100, avr_loss=0.07")
    assert not ok
    print("DIAGNOSE_OPTIMIZER_FAILURE_SCENARIOS_OK")

def test_anima_rdna2_no_half_vae(base: Path):
    """RDNA2 + Anima 必须传官方 --no_half_vae（cache_latents 阶段 vae_dtype 会覆盖 load 补丁）。"""
    src = Path(core.__file__).read_text(encoding="utf-8-sig")
    # anima 分支内 RDNA2 自动加 --no_half_vae
    assert "--no_half_vae" in src, "train() 应含 --no_half_vae"
    m = re.search(r'if _amd_is_gfx103x\(\):\n\s+cmd \+= \["--no_half_vae"\]', src)
    assert m, "anima 分支 RDNA2 未自动加 --no_half_vae"
    # 官方参数确实存在于随包 sd-scripts（不是自造参数）
    import zipfile
    zp = ROOT / "installers" / "kohya_ss" / "sd-scripts-main.zip"
    with zipfile.ZipFile(str(zp)) as z:
        tn = z.read("sd-scripts-main/train_network.py").decode("utf-8", errors="replace")
    assert '"--no_half_vae"' in tn, "sd-scripts 无 --no_half_vae 参数"
    print("ANIMA_RDNA2_NO_HALF_VAE_OK")

def test_h3_vram_adapt(base: Path):
    """H3 训练 yaml 按显存自动启用 low_vram / layer_offloading（照搬 ai-toolkit 官方/RunComfy 社区配置）。

    - low_vram: true 对所有 H3 训练默认开启（DiT≈19.5G + TE≈14.6G 无法同时常驻显存，24G 卡也一样）
    - layer_offloading: <24G 自动开（int8 DiT 对 12/16G 仍太大，分层交换兜底），24G+/未知保持关闭
    """
    import io as _io
    out = base / "h3_cfg"
    out.mkdir(exist_ok=True)
    params = {"project": "t", "rank": 32, "alpha": 32,
              "video_steps": 100, "video_frames": 73, "unet_lr": 2e-4}

    def gen(vram):
        cfg = out / ("cfg_%s.yaml" % ("none" if vram is None else vram))
        core.write_h3_train_yaml(params, str(base / "videos"), str(base / "out"),
                                 str(cfg), vpy=None, logf=lambda *a: None, vram_gb=vram)
        return _io.open(str(cfg), encoding="utf-8").read()

    t12 = gen(12)
    assert "low_vram: true" in t12 and "layer_offloading: true" in t12, t12
    assert "layer_offloading_transformer_percent: 0.6" in t12, t12
    assert "layer_offloading_text_encoder_percent: 1.0" in t12, t12
    t20 = gen(20)
    assert "layer_offloading: true" in t20, t20
    assert "layer_offloading_transformer_percent: 0.3" in t20, t20
    assert "layer_offloading_text_encoder_percent: 0.8" in t20, t20
    t24 = gen(24)
    assert "low_vram: true" in t24 and "layer_offloading: true" not in t24, t24
    tn = gen(None)
    assert "low_vram: true" in tn and "layer_offloading: true" not in tn, tn
    # 缩进：low_vram 与 name_or_path 同级（8 空格）
    assert "        low_vram: true\n" in t12, "low_vram 缩进错误"

    # nvfp4 主模型：12~16G 传 dit_nvfp4_path → yaml 生成 dit_fl2va_pruned_path 覆盖
    nvfp4_file = base / "h3_cfg" / "MiniMax_H3_FL2VA_pruned_nvfp4.safetensors"
    nvfp4_file.write_bytes(b"fake")
    cfg = out / "cfg_nvfp4.yaml"
    core.write_h3_train_yaml(params, str(base / "videos"), str(base / "out"), str(cfg),
                             vpy=None, logf=lambda *a: None, vram_gb=12, dit_nvfp4_path=str(nvfp4_file))
    tn4 = _io.open(str(cfg), encoding="utf-8").read()
    assert "dit_fl2va_pruned_path: " in tn4, tn4
    assert nvfp4_file.name in tn4, tn4

    # h3_model_files：nvfp4 文件名能被检测到（fake 文件很小，需把完整性阈值降到 1 字节）
    tiny_sizes = {k: 1 for k in core.H3_MIN_SIZES}
    with patch.object(core, "H3_MIN_SIZES", tiny_sizes), \
         patch.object(core, "h3_models_dir", return_value=str(base / "h3_cfg")):
        files = core.h3_model_files()
    assert files["dit_nvfp4"] and not files["dit"], files
    # h3_missing_models：<16G 且两者都缺时推荐 nvfp4（11.7GB）+ int8 可选项；>=24G 只要求 int8
    empty_dir = base / "h3_empty"
    empty_dir.mkdir(exist_ok=True)
    with patch.object(core, "h3_models_dir", return_value=str(empty_dir)):
        miss12 = core.h3_missing_models(12)
    assert any("11.7GB" in m for m in miss12), miss12
    assert any("19.5GB" in m for m in miss12), miss12
    with patch.object(core, "h3_models_dir", return_value=str(empty_dir)):
        miss24 = core.h3_missing_models(24)
    assert not any("11.7GB" in m for m in miss24), miss24
    assert any("19.5GB" in m for m in miss24), miss24
    print("H3_VRAM_ADAPT_OK")

def test_h3_resolution_frames(base: Path):
    """H3 训练 yaml 必须采用用户的分辨率/帧数，并吸附到引擎的硬约束网格。

    背景（2026-09-15 用户反馈）：yaml 里 `resolution: [1280, 1280]` 与采样 `width/height`
    曾是**硬编码字面量**，`video_frames` 又从未被 GUI 写入 params → 用户改这两项都不生效；
    而手改 yaml 会被下次生成覆盖，表现为「改了还是会变回配置里的 1280 和 73」。
    （test_h3_vram_adapt 显式传了 video_frames=73，正好绕过这个缺口，所以没被早期测试发现。）

    两条约束来自 ai-toolkit
    （extensions_built_in/diffusion_models/minimax_h3/minimax_h3.py）：
      - 帧数须为 17n+5（5/22/39/56/73/90…），否则引擎**静默向下裁帧**（:750-755）
      - 分辨率须为 32 的倍数（16x VAE 空间压缩 × 2x2 patch，:207）
    """
    import io as _io
    out = base / "h3_rf"
    out.mkdir(exist_ok=True)
    p = {"project": "t", "rank": 32, "alpha": 32, "unet_lr": 2e-4,
         "video_steps": 100, "trigger": "x"}

    def gen(extra, tag):
        cfg = out / ("rf_%s.yaml" % tag)
        core.write_h3_train_yaml(dict(p, **extra), str(base / "videos"), str(base / "out"),
                                 str(cfg), vpy=None, logf=lambda *a: None, vram_gb=8)
        return _io.open(str(cfg), encoding="utf-8").read()

    # 用户给的值必须被采用（不再写死 1280 / 恒 73）
    t = gen({"resolution": 768, "video_frames": 56}, "user")
    assert "resolution: [768, 768]" in t, t
    assert "num_frames: 56" in t, t
    assert "width: 768" in t, t
    assert "height: 416" in t, t          # 768*9//16=432，再向下对齐到 32 的倍数 = 416

    # 不在网格上的值要被吸附（而不是原样透传、再被引擎静默裁掉）
    assert "num_frames: 73" in gen({"video_frames": 70}, "snap_f"), "帧数未吸附到 17n+5"
    assert "resolution: [704, 704]" in gen({"resolution": 720}, "snap_r"), "分辨率未吸附到 32 倍数"

    # 未提供时回落默认
    t3 = gen({}, "default")
    assert "resolution: [1280, 1280]" in t3, t3
    assert "num_frames: 73" in t3, t3
    assert "height: 704" in t3, t3        # 720 不是 32 的倍数

    # 吸附纯函数
    for src, exp in ((73, 73), (70, 73), (60, 56), (5, 5), (1, 5)):
        assert core.h3_align_frames(src) == exp, (src, core.h3_align_frames(src))
    for src, exp in ((1280, 1280), (768, 768), (720, 704), (100, 96), (10, 32)):
        assert core.h3_align_resolution(src) == exp, (src, core.h3_align_resolution(src))

    # GUI 侧接线（源码断言，避免 import customtkinter）：帧数控件、项目存档、视频分辨率默认值
    _g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8-sig")
    assert '("帧数（17n+5）", "video_frames")' in _g, "高级参数缺「帧数」控件"
    assert '"video_frames": int(float(_getv("video_frames"' in _g, "未收集 video_frames"
    assert '"resolution": params.get("resolution"),' in _g, "项目存档未保存 resolution"
    assert 'return str(core.H3_RESOLUTION)' in _g, "视频分辨率默认值未单独分支"
    assert core.H3_RESOLUTION == 1280
    print("H3_RESOLUTION_FRAMES_OK")

def test_video_caption_args(base: Path):
    """video_caption.py 的 args 引用必须全部有定义（修复 args.model 未定义导致视频自动打标必崩）。"""
    vc = (ROOT / "video_caption.py").read_text(encoding="utf-8")
    defined = set(re.findall(r'add_argument\("--([a-z_]+)"', vc))
    used = set(re.findall(r"args\.([a-z_]+)", vc))
    assert not (used - defined), f"video_caption.py 未定义参数: {used - defined}"
    # 必须显式指定 utf-8：中文系统默认按 gbk 解码子进程输出，而 video_caption.py 的中文
    # --help 文本会让读取线程抛 UnicodeDecodeError → r.stdout 变成 None。
    # （生产代码里 run_stream 本来就是强制 utf-8 + errors=replace，测试这里要对齐。）
    r = subprocess.run([sys.executable, str(ROOT / "video_caption.py"), "--help"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    assert r.returncode == 0, (r.returncode, r.stderr)
    assert "--model" in r.stdout and "Qwen/Qwen2.5-VL-3B-Instruct" in r.stdout, r.stdout
    print("VIDEO_CAPTION_ARGS_OK")

def test_preprocess_python_fallback(base: Path):
    """Krea2/FLUX.2 只装第二引擎时，预处理用 musubi venv 而非误报「Kohya 尚未安装」。"""
    kdir = base / "kohya_ss"
    mv = kdir / "musubi-venv" / "Scripts" / "python.exe"
    fake_python(mv)
    with patch.object(core, "get_kohya_dir", return_value=str(kdir)):
        py = core._pick_preprocess_python()
    assert py == str(mv), py
    av = kdir / "ai_toolkit_venv" / "Scripts" / "python.exe"
    fake_python(av)
    with patch.object(core, "get_kohya_dir", return_value=str(kdir)):
        py2 = core._pick_preprocess_python()
    assert py2 == str(mv), py2  # musubi 优先于 ai_toolkit
    kv = kdir / "venv" / "Scripts" / "python.exe"
    fake_python(kv)
    with patch.object(core, "get_kohya_dir", return_value=str(kdir)):
        py3 = core._pick_preprocess_python()
    assert py3 == str(kv), py3  # kohya venv 最优先
    with patch.object(core, "get_kohya_dir", return_value=str(base / "empty")):
        py4 = core._pick_preprocess_python()
    assert py4 == "", py4
    # preprocess 入口改用多引擎 fallback，不再硬报「Kohya 尚未安装」
    _src_all = Path(core.__file__).read_text(encoding="utf-8-sig")
    assert "vpy = _pick_preprocess_python()" in _src_all, "preprocess 未使用 fallback"
    assert "尚未安装任何训练引擎" in _src_all, "preprocess 报错文案未更新"
    print("PREPROCESS_PYTHON_FALLBACK_OK")

def test_h3_integrity_and_nvfp4_required(base: Path):
    """H3 模型完整性校验（防 SafetensorError）+ 12~16G 必须 nvfp4 强提示。"""
    # 1) 不完整文件：目录里有小体积 nvfp4 → 视为缺失 + h3_missing_models 提示
    d = base / "h3_partial"
    d.mkdir(exist_ok=True)
    (d / "MiniMax_H3_FL2VA_pruned_nvfp4.safetensors").write_bytes(b"x" * 1024)
    with patch.object(core, "h3_models_dir", return_value=str(d)):
        files = core.h3_model_files()
        inc = core.h3_incomplete_files()
        miss = core.h3_missing_models(12)
    assert not files.get("dit_nvfp4"), files
    assert len(inc) == 1 and "nvfp4" in inc[0][0], inc
    assert any("不完整" in m for m in miss), miss
    # 2) 完整文件（超过阈值→这里用 mock 大小不行，直接验证阈值逻辑存在）
    src_all = Path(core.__file__).read_text(encoding="utf-8-sig")
    assert "H3_MIN_SIZES" in src_all and "h3_incomplete_files" in src_all
    # 3) 12~16G 必须 nvfp4：train_h3 含强提示（int8 物理放不下）
    assert "12~16G 显存训练 MiniMax H3 必须用 nvfp4 主模型" in src_all, "train_h3 缺 nvfp4 强提示"
    print("H3_INTEGRITY_AND_NVFP4_REQUIRED_OK")

def test_video_preprocess_no_auto_train(base: Path):
    """视频模式「数据预处理」只检查提示，不再自动进入训练（避免误触发训练）。"""
    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8")
    i = g.find("if params.get(\"mode\") == \"video\":")
    assert i != -1, "视频分支未找到"
    seg = g[i:g.find("def ", i + 10)]
    assert "视频无需图片预处理" in seg, "视频分支未改为提示"
    # 视频分支不再 q.put AUTO_CONFIRM
    assert 'q.put(("AUTO_CONFIRM"' not in seg, "视频分支仍会自动进入训练流程"
    print("VIDEO_PREPROCESS_NO_AUTO_TRAIN_OK")

def test_build_env_utf8_output(base: Path):
    """训练子进程强制 UTF-8 输出：英文系统（cp1252）下打印中文不再 UnicodeEncodeError。"""
    import os as _os
    # 1) 复现崩溃：子进程 PYTHONIOENCODING=cp1252 打印中文 → 非零退出
    bad_env = dict(_os.environ)
    bad_env["PYTHONIOENCODING"] = "cp1252"
    r1 = subprocess.run([sys.executable, "-c", "print('中文测试')"],
                        capture_output=True, text=True, timeout=60, env=bad_env)
    assert r1.returncode != 0, f"cp1252 打印中文应失败，实际 rc={r1.returncode} stdout={r1.stdout!r}"
    # 2) 修复：build_env 必须带 PYTHONIOENCODING=utf-8
    env = core.build_env()
    assert env.get("PYTHONIOENCODING") == "utf-8", env
    assert env.get("HF_HUB_DISABLE_XET") == "1", env  # huggingface_hub Xet 401（直连 xethub 绕过镜像）禁用
    # 3) 用 build_env 跑同样的打印 → 成功
    r2 = subprocess.run([sys.executable, "-c", "print('中文测试')"],
                        capture_output=True, text=True, encoding="utf-8", timeout=60, env=env)
    assert r2.returncode == 0, (r2.returncode, r2.stderr)
    assert "中文测试" in r2.stdout
    print("BUILD_ENV_UTF8_OUTPUT_OK")

def test_build_env_unbuffered_output(base: Path):
    """子进程「零输出就失败」的根因：管道下 Python 用块缓冲，硬崩时缓冲整块丢失。

    2026-09-15 qionglora 用户实测：preprocess.py 连续两轮「零输出 + 非零退出」，
    日志只剩一句「请查看上方日志」，用户和作者都无从下手（连报错都收不到）。
    修法：build_env 强制 PYTHONUNBUFFERED=1，让崩溃前已打印的内容一定先落进父进程日志。
    """
    import os as _os
    # 子进程打印一行后走 os._exit —— 跳过 flush，模拟「硬崩/被杀」
    code = "import os, sys; sys.stdout.write('BEFORE-CRASH\\n'); os._exit(3)"
    # 1) 复现：不带 PYTHONUNBUFFERED 时，父进程一个字都收不到（测试前提）
    bad_env = dict(_os.environ)
    bad_env.pop("PYTHONUNBUFFERED", None)
    got = []
    rc = core.run_stream([sys.executable, "-c", code], env=bad_env, logf=got.append)
    assert rc == 3, f"退出码应为 3，实际 {rc}"
    # 注意：用「整行相等」判定 —— run_stream 会把命令本身回显一行（以 "$ " 开头），
    # 而命令里就含 BEFORE-CRASH 字面量，用子串匹配会误判。
    assert not any(x.strip() == "BEFORE-CRASH" for x in got), \
        f"前提不成立（竟然收到了输出，说明未走块缓冲）：{got}"
    # 2) 修复：build_env 必须带 PYTHONUNBUFFERED=1，同样场景能拿到崩溃前日志
    env = core.build_env()
    assert env.get("PYTHONUNBUFFERED") == "1", ("build_env 缺 PYTHONUNBUFFERED", env.get("PYTHONUNBUFFERED"))
    got2 = []
    rc2 = core.run_stream([sys.executable, "-c", code], env=env, logf=got2.append)
    assert rc2 == 3, f"退出码应为 3，实际 {rc2}"
    assert any(x.strip() == "BEFORE-CRASH" for x in got2), f"PYTHONUNBUFFERED 未生效，仍收不到输出：{got2}"
    print("BUILD_ENV_UNBUFFERED_OK")

def test_preprocess_silent_failure_diagnosed(base: Path):
    """预处理失败必须自带诊断：主动自检 + 可复现命令，不能只说「请查看上方日志」。

    背景同上：上方日志为空时，「请查看上方日志」是零信息量报错。
    """
    src = Path(core.__file__).read_text(encoding="utf-8-sig")
    # 1) 零信息量的老文案必须消失
    assert 'raise RuntimeError("预处理失败，请查看上方日志")' not in src, "仍残留零信息量报错"
    # 2) 失败路径必须接上主动自检
    assert "_diagnose_preprocess_failure(vpy, cmd, logf)" in src, "预处理失败路径未接自检"
    # 3) 自检内容：逐项探测 + 导入污染检查 + 给出可复现命令
    i = src.find("def _diagnose_preprocess_failure(")
    assert i != -1, "缺 _diagnose_preprocess_failure"
    d = src[i:src.find("\ndef ", i + 10)]
    for k in ("from PIL import Image", "import numpy", "import ctypes",
              '" ".join(str(x) for x in cmd)',          # 复现命令
              "argparse.py", "subprocess.py"):           # 标准库同名污染检查
        assert k in d, f"自检缺内容：{k}"
    # 4) 误报修正：force 兜底模式下不得再断言「Pillow/numpy 不可用」
    j = src.find("def _ensure_preprocess_deps(")
    seg = src[j:src.find("\ndef ", j + 10)]
    assert "首次失败原因未明" in seg, "force 模式仍会误报缺依赖"
    print("PREPROCESS_SILENT_FAILURE_DIAGNOSED_OK")

def test_wd14_onnx_isolated(base: Path):
    """内置打标必须隔离到子进程：native 硬崩不得带走整个预处理。

    2026-09-15 qionglora 用户实测：onnxruntime 加载阶段 native 崩溃（**无 traceback**，
    try/except 拦不住）把整个 preprocess.py 一起带走 → 报「预处理失败」，
    而 18 张图片其实**已经处理好了，只差标签**。
    修法：打标放进子进程（崩了只丢标签、走既有兜底 caption），并在 native 风险步骤前留面包屑。
    """
    src = (ROOT / "preprocess.py").read_text(encoding="utf-8")
    # 1) 隔离实现存在，且总入口已改用它
    assert "def _run_wd14_onnx_isolated(" in src, "缺子进程隔离实现"
    # ⚠️ 用**结构化**判断，别绑死完整调用串：2026-09-17 给该调用加了 model_key 参数，
    # 原先写成 "return _run_wd14_onnx_isolated(output_dir, logf=logf)" 的断言立刻失效 ✗
    # （这个项目已经因为「断言太字面」误报过好几次了，统一改成看函数体内是否存在该调用）
    _ai = src.index("def _run_wd14_auto(")
    _abody = src[_ai:_ai + src[_ai:].index("\n\n\n")]
    assert "_run_wd14_onnx_isolated(" in _abody, "总入口未接隔离版"
    # 2) native 崩溃没有 traceback，必须有面包屑才能定位
    assert "正在加载 onnxruntime…" in src, "缺崩溃定位面包屑"
    # 3) 行为：外层子进程必须「正常收尾并拿到 bool」，而不是被内层一起带走
    out_dir = base / "wd14iso" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    code = ("import sys; sys.path.insert(0, sys.argv[2]);"
            "import preprocess as P;"
            "sys.exit(0 if P._run_wd14_onnx_isolated(sys.argv[1], logf=print) else 3)")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)          # 双保险（生产代码已改为不依赖它）
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, "-c", code, str(out_dir), str(ROOT)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900, env=env)
    blob = (r.stdout or "") + (r.stderr or "")
    # 0 = 打标成功；3 = 打标失败但**外层存活**。两者都合法（取决于本机有无 onnxruntime），
    # 但不能是被 native 崩溃带走的异常码。
    assert r.returncode in (0, 3), f"外层进程异常收尾 rc={r.returncode}：{blob[-900:]}"
    assert "独立子进程中运行" in blob, f"未走隔离路径：{blob[-900:]}"
    if r.returncode == 3:
        # 失败必须是「可读诊断」，不能又变成静默
        assert ("异常退出" in blob) or ("未找到" in blob) or ("缺 onnxruntime" in blob), \
            f"打标失败时缺可读诊断：{blob[-900:]}"
    print("WD14_ONNX_ISOLATED_OK")

def test_probe_onnxruntime_import(base: Path):
    """onnxruntime 探测必须区分「native 崩溃」与「未安装 / 加载失败」。

    2026-09-15 qionglora 用户 cmd 实测（本测试据此固化）：
        python -c "import onnxruntime; ..."  → 闪退、零输出、直接回提示符（DLL 级 native 崩溃）
        python -c "import cv2; ..."          → ModuleNotFoundError（普通缺包，代码本就有处理）
    两者修法完全不同（崩溃要重装/重建环境，缺包只要装上），诊断必须分开，否则给出的
    修复指引就是错的。
    """
    code = ("import sys; sys.path.insert(0, sys.argv[1]);"
            "import preprocess as P;"
            "cases = ["
            "  (3, ''),"                                              # native 崩溃：零输出
            "  (1, \"ModuleNotFoundError: No module named 'onnxruntime'\"),"   # 没装
            "  (0, 'ORT_OK 1.20.0'),"                                 # 正常
            "  (1, 'ImportError: DLL load failed'),"                  # 装坏了
            "];"
            "print('CASES', [P._classify_ort_probe(rc, out) for rc, out in cases])")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, "-c", code, str(ROOT)],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300, env=env)
    blob = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, f"探测脚本异常 rc={r.returncode}：{blob[-600:]}"
    got = [l for l in blob.splitlines() if l.startswith("CASES")]
    assert got, f"未拿到分类结果：{blob[-600:]}"
    # 顺序断言：四类必须被分开，且「崩溃」要排在「未安装」之前（对应用例顺序）
    i_crash = got[0].find("import 阶段直接崩溃")
    i_miss = got[0].find("未安装")
    i_ok = got[0].find("(True, '')")
    i_fail = got[0].find("加载失败")
    assert -1 not in (i_crash, i_miss, i_ok, i_fail), f"有一类没被识别：{got[0]}"
    assert i_crash < i_miss < i_ok < i_fail, f"分类顺序/归属不对：{got[0]}"
    # 源码须保留可执行的修复指引（重装命令 + 重建训练环境）
    src = (ROOT / "preprocess.py").read_text(encoding="utf-8")
    assert "--force-reinstall onnxruntime" in src, "缺重装指引"
    assert "② 安装训练内核" in src, "缺重建训练环境指引"
    print("PROBE_ONNXRUNTIME_IMPORT_OK")

def test_fizgig_preview_swap(base: Path):
    """Krea2 训练中「采样预览」必须分块换出 Turbo，别让它额外常驻整模型拖慢训练。

    2026-09-15 用户实测（RTX 4080 SUPER 15.67G，Krea2 512px，每 2 epoch 预览一次）：
      引擎自报每 epoch 步速：2.02 / 2.18（还没预览过）→ **12.74 / 9.95 / 7.56** → 3.55 / 2.49 / 2.63
      全程平均 6.22 s/it，而没预览过的前两个 epoch 只有 2.0 s/it。
      单次预览直接耗时 107/68/55/45/48/44 秒（其中约 74s 是重复加载+量化 Turbo）。
      → 预览本身只占约 7% 的总时间，**超过一半的额外耗时来自它把显存压爆之后的换页**。

    修法：给预览传 --preview_blocks_to_swap（CLI 默认 0 = 整个 ~13GB 常驻显存）。
    引擎的 sample_previews 本就为小显存卡设计了该组合：blocks_to_swap>0 时以 CPU 为加载设备、
    走 forward-only 分块换入，--preview_int8 的量化也刻意在 CPU 上做。
    """
    # 1) 档位表（含边界）
    assert core._fizgig_preview_swap(None) == 0, "拿不到显存时不该硬塞分块换出"
    assert core._fizgig_preview_swap(32) == 0
    assert core._fizgig_preview_swap(24) == 0
    assert core._fizgig_preview_swap(20) == 12          # 18~23G
    assert core._fizgig_preview_swap(18) == 12
    assert core._fizgig_preview_swap(16) == 20          # 12~17G ← 用户那台 15.67 取整 16
    assert core._fizgig_preview_swap(15.67) == 20
    assert core._fizgig_preview_swap(12) == 20
    assert core._fizgig_preview_swap(10) == 26
    assert core._fizgig_preview_swap(8) == 26
    # 2) 接线：预览参数块里必须真的用上它
    # 注意：用传参处 `"--preview_blocks_to_swap"` 当锚点 —— 不能用 `--preview_int8`，
    # 因为那个字面量也出现在 _fizgig_preview_swap 的 docstring 里（位于调用点之前）。
    src = Path(core.__file__).read_text(encoding="utf-8-sig")
    j = src.find('"--preview_blocks_to_swap"')
    assert j != -1, "预览参数块未传 --preview_blocks_to_swap"
    seg = src[max(0, j - 900):j + 200]
    assert "_fizgig_preview_swap(vram_gb)" in seg, "预览未按显存档位算分块换出"
    print("FIZGIG_PREVIEW_SWAP_OK")

def test_fizgig_sample_off_warned(base: Path):
    """Fizgig 采样被引擎自动关闭时必须告知用户（旧告警已失效，必须更正）。

    2026-09-15 逐字核对 Fizgig v5.0.0 源码（魔搭镜像与 GitHub v5.0.0 的 trainer.py
    sha256 一致）后更正：

      · 旧文案说「采样循环没有 try/except（trainer.py:1581），异常会跳过
        switch_block_swap_for_training() → 每步全量换块 → 1.78→8s/it」——
        **该机制在 v5.0.0 不存在**：两个采样调用点都已有 try/except/finally，
        finally 会还原训练 DiT 的块交换状态；且 `trainer.py:1581` 现在是
        `train_krea2()` 的签名参数注释（行号早已失效）。
      · 旧的触发条件也失效：引擎 except 只打印**异常类型名**、不打完整异常消息，
        所以 mark "unsupported operand type(s) for *" 根本不会进日志 → 死代码。

    真正该告知用户的是引擎的另一个行为：一次预览失败后 `do_previews = False`，
    **本轮后续 epoch 不再出预览图** —— 用户勾了预览却"跑着跑着没了"，日志里只有一行英文。
    """
    # 1) 新 mark：命中真实引擎日志，并解析出失败的 epoch
    line = ("[preview] epoch 3 preview failed (CUDA OOM - this card is too small for the Turbo preview); "
            "disabling previews for the rest of the run. Training continues and LoRAs still save normally.")
    out = []
    assert core._warn_fizgig_sample_failure(line, logf=out.append) is True, "未命中「引擎已自动关闭预览」的日志"
    blob = "\n".join(out)
    assert "已自动关闭本轮后续预览" in blob, blob
    assert "第 3 个 epoch" in blob, "未解析出失败的 epoch：%s" % blob
    assert "只影响预览图" in blob, "未说明影响范围（用户最关心训练受不受影响）"
    # 2) 旧引擎 mark 仍要兼容（别删）
    assert core._warn_fizgig_sample_failure(
        "unsupported operand type(s) for *", logf=lambda s: None) is True, "旧引擎 mark 不再兼容"
    # 3) 无关日志不得误报
    assert core._warn_fizgig_sample_failure(
        "steps: 5%| 51/1024 [01:00<19:00, 2.10s/it]", logf=lambda s: None) is False, "无关日志被误报"
    assert core._warn_fizgig_sample_failure("", logf=lambda s: None) is False
    # 4) 源码层面：已失效的旧结论必须清掉
    src = Path(core.__file__).read_text(encoding="utf-8-sig")
    assert "disabling previews for the rest of the run" in src, "缺新的引擎日志 mark"
    assert "块交换没还原" not in src, "仍残留已失效的旧结论文案"
    print("FIZGIG_SAMPLE_OFF_WARNED_OK")

def test_preprocess_skip_is_visible(base: Path):
    """预处理重跑时的「静默跳过」必须可见，且必须在打标阶段之前打印。

    2026-09-15 qionglora 用户：先单独点「数据预处理」（图片写好但打标已失败、降级成兜底
    caption），再点「一键开始训练」——后者自带预处理会重跑一遍，此时 18 张图全部
    「已存在 → 静默跳过」，屏幕上一个字都没有；接着打标阶段 native 崩溃，
    整个预处理被判失败。运行汇总在文件**末尾**，崩了就永远看不到，用户无从判断发生了什么。
    """
    src = (ROOT / "preprocess.py").read_text(encoding="utf-8")
    # 1) 跳过必须被记录并汇总（不再纯静默 continue）
    assert "skip_names.append(name)" in src, "跳过仍是静默 continue"
    assert "本次跳过未重新处理" in src, "缺跳过汇总提示"
    assert "[跳过]" in src, "缺逐张跳过明细"
    # 2) 顺序断言：汇总必须在打标阶段之前 —— 打标是当前最脆的一环，
    #    崩在后面就看不到汇总（旧版汇总在文件末尾，正是被这个吃掉）
    i_skip = src.find("本次跳过未重新处理")
    i_tag = src.find("# ---- 人物模式：WD14")
    assert i_skip != -1 and i_tag != -1, "锚点缺失"
    assert i_skip < i_tag, "跳过汇总打在了打标阶段之后，打标一崩仍然看不到"
    # 3) 全部跳过时要明说「等价于没重新处理」，避免用户误以为在跑
    assert "没有重新处理图片" in src, "缺「等价于没重新处理」提示"
    print("PREPROCESS_SKIP_VISIBLE_OK")

def test_krea2_style_subdir_consistency(base: Path):
    """Krea2/Qwen-Image 画风子模式：预处理输出 train_character，训练必须读 train_character（防「缺少预处理数据」）。"""
    src_all = Path(core.__file__).read_text(encoding="utf-8-sig")
    # train_krea2 / train_at_image 不再按 at_sub_mode 切换 train/train_character
    assert src_all.count('train_dir = dataset_train_dir("character", params.get("project"))') >= 2, "训练目录未统一为 train_character"
    # 不再存在按子模式切换 train/train_character 的旧写法
    assert 'dataset_train_dir("style" if _sub_mode == "style"' not in src_all, "仍存在按子模式切换目录"
    print("KREA2_STYLE_SUBDIR_CONSISTENCY_OK")

def test_project_open_robust(base: Path):
    """手动改坏项目 json（base_model/params 类型异常）后点「打开」不能静默无反应。"""
    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8")
    # cmd_open_project 内 _apply_project_data 必须被 try/except 包裹（失败按默认配置打开 + 日志提示）
    i = g.find("def cmd_open_project")
    assert i != -1, "cmd_open_project 未找到"
    seg = g[i:g.find("def ", i + 10)]
    assert "try:" in seg and "_apply_project_data(data)" in seg, "cmd_open_project 缺容错"
    assert "已按默认配置打开" in seg, "缺失败提示文案"
    # _apply_project_data 对关键字段做类型校验
    a = g[g.find("def _apply_project_data"):g.find("def _schedule_autosave")]
    assert "isinstance(bm, str)" in a, "base_model 缺类型校验"
    assert "isinstance(p, dict)" in a, "params 缺类型校验"
    print("PROJECT_OPEN_ROBUST_OK")

def test_run_stream_default_utf8(base: Path):
    """run_stream 默认 env 强制 UTF-8：繁体(cp950)/英文(cp1252)系统打印中文不再崩（krea2_cache_latents 漏传 env 根因）。"""
    u = (ROOT / "kohya_core" / "utils.py").read_text(encoding="utf-8")
    # run_stream env=None 时默认 build_env()
    i = u.find("def run_stream")
    assert i != -1
    seg = u[i:u.find("def ", i + 10)]
    assert "if env is None:" in seg and "env = build_env()" in seg, "run_stream 缺默认 build_env"
    # 实测：run_stream 跑 python 打印中文（含项目名「项目_」）应成功
    logs = []
    rc = core.run_stream([sys.executable, "-c", "print('\u9879\u76ee_\u6d4b\u8bd5')"], logf=logs.append)
    assert rc == 0, (rc, logs)
    assert any("\u9879\u76ee_\u6d4b\u8bd5" in l for l in logs), logs
    print("RUN_STREAM_DEFAULT_UTF8_OK")

def test_musubi_int8_weight_dtype_patch(base: Path):
    """FLUX.2 <16G int8 量化：musubi 断言不再崩溃（int8_base 时 dit_weight_dtype 应为 None）。"""
    import types as _types
    # 1) 模拟 musubi trainer_base.py，调用补丁应正确替换
    mt = base / "musubi-tuner" / "src" / "musubi_tuner" / "training"
    mt.mkdir(parents=True, exist_ok=True)
    tb = mt / "trainer_base.py"
    tb.write_text('dit_weight_dtype = (None if args.fp8_scaled else torch.float8_e4m3fn) if args.fp8_base else dit_dtype\n',
                  encoding="utf-8")
    logs = []
    with patch.object(core, "get_kohya_dir", return_value=str(base)):
        core._patch_musubi_int8_weight_dtype(str(base), logs.append)
    s = tb.read_text(encoding="utf-8")
    assert "args.int8_base" in s and "KOHYA_TOOL_PATCH" in s, s
    # 2) 验证替换后逻辑：int8_base=True / fp8_scaled=True / fp8_base=False → dit_weight_dtype=None（断言通过）
    args = _types.SimpleNamespace(fp8_scaled=True, int8_base=True, fp8_base=False)
    dit_dtype = "bf16"
    ns = {"args": args, "dit_dtype": dit_dtype, "torch": None}
    # 提取替换后的表达式（去掉注释）
    expr = s.split("KOHYA_TOOL_PATCH")[0].strip()
    exec("dit_weight_dtype = " + expr.replace("torch.float8_e4m3fn", "None"), ns)
    assert ns["dit_weight_dtype"] is None, ns
    # 3) 普通模式（int8=False, fp8=False）→ dit_weight_dtype=dit_dtype（不受影响）
    args2 = _types.SimpleNamespace(fp8_scaled=False, int8_base=False, fp8_base=False)
    ns2 = {"args": args2, "dit_dtype": "bf16", "torch": None}
    exec("dit_weight_dtype = " + expr.replace("torch.float8_e4m3fn", "None"), ns2)
    assert ns2["dit_weight_dtype"] == "bf16", ns2
    print("MUSUBI_INT8_WEIGHT_DTYPE_PATCH_OK")

def test_prequantized_base_detect(base: Path):
    """Krea2/FLUX.2 底模已预量化（fp8/int8）时跳过工具侧量化（防 musubi 'already in fp8 format' 报错）。"""
    import struct as _st, json as _json
    def fake(p, dtype):
        hdr = {"blocks.0.attn.q_proj.weight": {"dtype": dtype, "shape": [1, 1], "data_offsets": [0, 2]}}
        raw = _json.dumps(hdr).encode()
        with open(p, "wb") as f:
            f.write(_st.pack("<Q", len(raw))); f.write(raw)
    p_fp8 = base / "fp8.safetensors"; fake(p_fp8, "F8_E4M3FN")
    p_int8 = base / "int8.safetensors"; fake(p_int8, "I8")
    p_bf16 = base / "bf16.safetensors"; fake(p_bf16, "BF16")
    assert core._safetensors_is_prequantized(str(p_fp8)) is True, "fp8 未识别"
    assert core._safetensors_is_prequantized(str(p_int8)) is True, "int8 未识别"
    assert core._safetensors_is_prequantized(str(p_bf16)) is False, "bf16 误判"
    assert core._safetensors_is_prequantized(str(base / "missing.safetensors")) is False
    # _resolve_quant_mode prequantized=True → none
    q, d = core._resolve_quant_mode(None, lambda *a: None, 8, prequantized=True)
    assert q == "none", (q, d)
    # 静态断言：train_krea2 / train_flux2 都接入预量化检测
    src_all = Path(core.__file__).read_text(encoding="utf-8-sig")
    assert src_all.count('_safetensors_is_prequantized(files["raw"])') >= 1, "train_krea2 未接入"
    assert src_all.count('_safetensors_is_prequantized(files["dit"])') >= 1, "train_flux2 未接入"
    print("PREQUANTIZED_BASE_DETECT_OK")

def test_strong_binding(base: Path):
    """人物强绑定：trigger + 100% 一致特征词自动固定前缀 + keep_tokens + 一致性警告 + ||| 分隔符。"""
    import preprocess as pp

    # ---- 自动模式：3 张标签含 2 个 100% 一致特征 ----
    td = base / "bind_auto"
    td.mkdir(parents=True, exist_ok=True)
    caps = [
        'bannai11, blue hair, blue eyes, 1girl, solo, smile',
        'bannai11, blue eyes, blue hair, long hair, 1girl, smile',
        'blue hair, bannai11, blue eyes, school uniform, 1girl, solo',
    ]
    for i, c in enumerate(caps):
        (td / f"{i}.txt").write_text(c, encoding="utf-8")

    info = pp.analyze_caption_features(str(td), 'bannai11')
    assert info["total"] == 3, info
    assert info["consistent"] == ["blue hair", "blue eyes"], info["consistent"]
    assert any(t == "smile" for t, _ in info["near"]), info["near"]

    logs = []
    kt, warns = pp.apply_strong_binding(str(td), 'bannai11', logs.append)
    assert kt == 3, (kt, logs)          # trigger + 2 特征
    assert warns, "应有 smile 一致性警告"
    assert "bannai11, blue hair, blue eyes" in (td / "0.txt").read_text(encoding="utf-8"), "前缀未置顶"
    # 幂等：二次运行不再重写
    kt2, _ = pp.apply_strong_binding(str(td), 'bannai11', lambda *a: None)
    assert kt2 == kt, (kt2, kt)

    # ---- 手动 ||| 分隔符 ----
    td2 = base / "bind_sep"
    td2.mkdir(parents=True, exist_ok=True)
    (td2 / "0.txt").write_text("bannai11, blue hair, blue eyes ||| 1girl, solo", encoding="utf-8")
    (td2 / "1.txt").write_text("bannai11, blue hair, blue eyes ||| 1girl, long hair", encoding="utf-8")
    kt3, _ = pp.apply_strong_binding(str(td2), 'bannai11', lambda *a: None)
    assert kt3 == 3, (kt3,)
    s = (td2 / "0.txt").read_text(encoding="utf-8")
    assert "|||" not in s and s.startswith("bannai11, blue hair, blue eyes"), s

    # ---- 接入点静态断言 ----
    src_all = Path(core.__file__).read_text(encoding="utf-8-sig")
    assert "apply_strong_binding(train_dir" in src_all, "train()/krea2/flux2 未接入强绑定"
    assert "def preprocess(" in src_all and "strong_bind=True" in src_all[src_all.find("def preprocess("):src_all.find("def preprocess(") + 600], "preprocess() 未接 strong_bind"
    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8")
    assert "strong_bind_var" in g, "GUI 未定义 strong_bind_var"
    i = g.find("def _collect_params")
    assert i != -1 and "strong_bind" in g[i:i + 1200], "GUI _collect_params 未接 strong_bind"
    print("STRONG_BINDING_OK")

def test_at_image_model_ready_local(base: Path):
    """at_image_model_ready：完整本地仓库→就绪；半截（缺 config.json/分片）→未就绪（不依赖真实 HF 缓存）。"""
    local = base / "models" / "at_image" / "zimage"
    (local / "transformer").mkdir(parents=True, exist_ok=True)
    (local / "text_encoder").mkdir(parents=True, exist_ok=True)
    open(local / "model_index.json", "w", encoding="utf-8").write("{}")
    open(local / "transformer" / "config.json", "w", encoding="utf-8").write("{}")
    open(local / "text_encoder" / "config.json", "w", encoding="utf-8").write("{}")
    # 分片：transformer 用 index + 分片；text_encoder 用单文件
    (local / "transformer" / "diffusion_pytorch_model.safetensors.index.json").write_text(
        '{"weight_map": {"a": "diffusion_pytorch_model-00001-of-00002.safetensors", "b": "diffusion_pytorch_model-00002-of-00002.safetensors"}}',
        encoding="utf-8")
    (local / "transformer" / "diffusion_pytorch_model-00001-of-00002.safetensors").write_bytes(b"x" * (1024 * 1024 + 1))
    (local / "transformer" / "diffusion_pytorch_model-00002-of-00002.safetensors").write_bytes(b"x" * (1024 * 1024 + 1))
    (local / "text_encoder" / "diffusion_pytorch_model.safetensors").write_bytes(b"x" * (1024 * 1024 + 1))
    with patch.object(core, "data_sub", side_effect=lambda *p: str(base.joinpath(*p))):
        assert core._at_image_download_complete(str(local)) is True
        assert core.at_image_model_ready("zimage") is True
        # 半截场景：删掉一个 transformer 分片 → 未就绪（旧逻辑只看目录会误判就绪）
        os.remove(local / "transformer" / "diffusion_pytorch_model-00002-of-00002.safetensors")
        # 关键回归：即使 HF 缓存目录存在，本地残缺也绝不能判就绪（v0.10.12 漏网：训练指向残缺目录报 no config.json）
        hf_cache = base / "fakehome" / ".cache" / "huggingface" / "hub" / "models--Tongyi-MAI--Z-Image"
        hf_cache.mkdir(parents=True, exist_ok=True)
        with patch.object(core.os.path, "expanduser", return_value=str(base / "fakehome")):
            assert core.at_image_model_ready("zimage") is False, "HF 缓存存在但本地残缺不得判就绪"
        # 缺 config.json → 未就绪
        os.remove(local / "transformer" / "config.json")
        with patch.object(core.os.path, "expanduser", return_value=str(base / "fakehome")):
            assert core.at_image_model_ready("zimage") is False
    print("AT_IMAGE_MODEL_READY_LOCAL_OK")

def test_at_image_pre_download(base: Path):
    """Z-Image/Qwen-Image 底模预下载：未下载→自动魔搭直链下载（_at_image_ms_download）→yaml 指向本地目录。"""
    import contextlib
    state = {"downloaded": False, "ms_call": None, "yaml_info": None, "launched": False,
             "local_model": "", "train_env": None}
    vpy = str(base / "third" / "kohya_ss" / "ai_toolkit_venv" / "Scripts" / "python.exe")
    at_dir = str(base / "third" / "kohya_ss" / "ai-toolkit")
    os.makedirs(at_dir, exist_ok=True)
    open(os.path.join(at_dir, "run.py"), "w", encoding="utf-8").write("print('ok')\n")

    def fake_ready(mode):
        return state["downloaded"] or bool(state["local_model"])

    def fake_custom_get(mode):
        if mode == "qwen_image":
            if state["local_model"]:
                custom = {"local_dir": state["local_model"], "model_id": "Qwen/Qwen-Image-2.1",
                          "arch": "qwen_image_2"}
                custom.update(state.get("manual_components") or {})
                return custom
            return {"model_id": "Qwen/Qwen-Image-2.1", "arch": "qwen_image_2"}
        return {}

    def fake_ms_download(mode, logf=print):
        state["ms_call"] = mode
        state["downloaded"] = True
        return True

    def fake_status():
        return True, "ok", vpy

    def fake_write_yaml(params, info, train_dir, out_dir, cfg_path, vpy=None, logf=print, vram_gb=None):
        state["yaml_info"] = dict(info)

    def fake_run_stream(cmd, cwd=None, env=None, logf=print, collect=None, **kwargs):
        state["launched"] = True
        state["train_env"] = dict(env or {})
        return 0

    def fake_find_latest(out_dir):
        return os.path.join(out_dir, "lora.safetensors")

    patches = (
        patch.object(core, "data_sub", side_effect=lambda *p: str(base.joinpath(*p))),
        patch.object(core, "at_image_custom_get", side_effect=fake_custom_get),
        patch.object(core, "at_image_model_ready", side_effect=fake_ready),
        patch.object(core, "_at_image_ms_download", side_effect=fake_ms_download),
        patch.object(core, "ai_toolkit_engine_status", side_effect=fake_status),
        patch.object(core, "write_at_image_yaml", side_effect=fake_write_yaml),
        patch.object(core, "run_stream", side_effect=fake_run_stream),
        patch.object(core, "_at_dirs", return_value=(vpy, at_dir)),
        patch.object(core, "count_images", return_value=1),
        patch.object(core, "_ensure_torchvision_deps", return_value=True),
        patch.object(core, "_find_latest_safetensors", side_effect=fake_find_latest),
        patch.object(core, "_write_at_image_template", return_value=None),
        patch.object(core, "write_params_report", return_value=None),
        patch.object(core, "_patch_ai_toolkit_qwen21_local_components", return_value=True),
        patch.object(core, "_ensure_at_image_qwen21_assets", return_value=str(base / "processor_cache")),
        patch.object(core, "ai_toolkit_amd_status", return_value=(True, "rocm", "ROCm/HIP 7.15 · GPU AMD Radeon Test")),
        patch.object(core, "_ai_toolkit_rocm_env", return_value={"PATH": "C:\\rocm\\bin", "ROCM_PATH": "C:\\rocm"}),
        patch.object(core, "_ensure_ai_toolkit_triton", return_value=True),
    )
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        out = core.train_at_image(lambda _: None, mode="zimage", params={"project": "at_t1"})
        assert state["ms_call"] == "zimage", "未触发魔搭底模预下载"
        assert state["yaml_info"]["model_id"].replace("\\", "/").endswith("models/at_image/zimage"), state["yaml_info"]
        assert state["launched"], "未启动训练"
        assert str(out).endswith("lora.safetensors"), out

        # Qwen-Image-2.1: 模拟下载完成后确认训练 YAML 收到正确架构和独立缓存目录。
        state.update(downloaded=False, ms_call=None, yaml_info=None, launched=False)
        out = core.train_at_image(lambda _: None, mode="qwen_image", params={"project": "at_qwen21"})
        expected = core.at_image_local_dir("qwen_image").replace("\\", "/")
        assert state["ms_call"] == "qwen_image", "Qwen-Image-2.1 没走模型下载阶段"
        assert state["yaml_info"].get("arch") == "qwen_image_2", state["yaml_info"]
        assert state["train_env"].get("AI_TOOLKIT_QWEN21_ASSETS_PATH") == str(base / "processor_cache"), state["train_env"]
        assert state["yaml_info"]["model_id"].replace("\\", "/") == expected, state["yaml_info"]
        assert state["launched"], "Qwen-Image-2.1 没启动 AI Toolkit 训练入口"
        assert str(out).endswith("lora.safetensors"), out

        # 本地 ComfyUI checkpoint 同时有 clip/TE 与 VAE 时，训练进程必须收到两条本地路径，
        # 且不应触发底模下载。
        comfy_models = base / "ComfyUI" / "models"
        checkpoint = comfy_models / "unet" / "qwen_image_2.1_bf16.safetensors"
        te_file = comfy_models / "clip" / "qwen3vl_8b_bf16.safetensors"
        vae_file = comfy_models / "vae" / "qwen_image_2.1_vae_bf16.safetensors"
        for path in (checkpoint, te_file, vae_file):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as f:
                f.truncate(2 * 1024 * 1024)
        qwen_src = Path(at_dir) / "extensions_built_in" / "diffusion_models" / "qwen_image_2" / "qwen_image_2.py"
        qwen_src.parent.mkdir(parents=True, exist_ok=True)
        qwen_src.write_text(
            "import os\n"
            "class QwenImage2Model:\n"
            "    arch = 'qwen_image_2'\n"
            "    def load_model(self):\n"
            "        self.print_and_status_update(\"Loading transformer\")\n"
            "        transformer = QwenImage21Transformer2DModel.load(\n"
            "            model_path, config_path=base_model_path, **self.component_load_kwargs(\"transformer\")\n"
            "        )\n"
            "        processor = QwenImage21TextEncoder.load_processor(base_model_path)\n"
            "        self.print_and_status_update(\"Loading text encoder\")\n"
            "        text_encoder = QwenImage21TextEncoder.load_model(\n"
            "            base_model_path, dtype=dtype, subfolder=\"text_encoder\"\n"
            "        )\n"
            "        self.print_and_status_update(\"Loading VAE\")\n"
            "        vae = AutoencoderKLQwenImage21.load(\n"
            "            base_model_path, **self.component_load_kwargs(\"vae\")\n"
            "        )\n", encoding="utf-8")
        state.update(downloaded=False, ms_call=None, yaml_info=None, launched=False,
                     local_model=str(checkpoint), train_env=None)
        out = core.train_at_image(lambda _: None, mode="qwen_image", params={"project": "at_qwen21_local"})
        assert state["ms_call"] is None, "本地模型已指定时不应触发底模下载"
        assert state["train_env"].get("AI_TOOLKIT_QWEN21_TEXT_ENCODER_PATH") == str(te_file), state["train_env"]
        assert state["train_env"].get("AI_TOOLKIT_QWEN21_VAE_PATH") == str(vae_file), state["train_env"]
        assert state["train_env"].get("AI_TOOLKIT_QWEN21_ASSETS_PATH") == str(base / "processor_cache"), state["train_env"]
        assert str(out).endswith("lora.safetensors"), out

        # Manual paths override auto-discovery and are handed through to the AI Toolkit process.
        manual_te = base / "manual_components" / "text_encoder.safetensors"
        manual_vae = base / "manual_components" / "vae.safetensors"
        manual_te.parent.mkdir(parents=True, exist_ok=True)
        for path in (manual_te, manual_vae):
            with path.open("wb") as f:
                f.truncate(2 * 1024 * 1024)
        state.update(downloaded=False, ms_call=None, yaml_info=None, launched=False,
                     manual_components={"text_encoder_path": str(manual_te),
                                       "vae_path": str(manual_vae)})
        out = core.train_at_image(lambda _: None, mode="qwen_image",
                                  params={"project": "at_qwen21_manual_components"})
        assert state["ms_call"] is None, "手动指定组件时，本地底模不应触发下载"
        assert state["train_env"].get("AI_TOOLKIT_QWEN21_TEXT_ENCODER_PATH") == str(manual_te), state["train_env"]
        assert state["train_env"].get("AI_TOOLKIT_QWEN21_VAE_PATH") == str(manual_vae), state["train_env"]
        assert state["train_env"].get("AI_TOOLKIT_QWEN21_ASSETS_PATH") == str(base / "processor_cache"), state["train_env"]
        assert str(out).endswith("lora.safetensors"), out

        # AMD image training must both pass the ROCm runtime DLL environment and require a live ROCm GPU probe.
        state.update(downloaded=False, ms_call=None, yaml_info=None, launched=False,
                     local_model="", manual_components={})
        out = core.train_at_image(lambda _: None, mode="zimage",
                                  params={"project": "at_zimage_amd", "amd_mode": True})
        assert state["launched"] and state["ms_call"] == "zimage", state
        assert state["train_env"].get("ROCM_PATH") == "C:\\rocm", state["train_env"]
        assert state["train_env"].get("PATH") == "C:\\rocm\\bin", state["train_env"]
        assert state["train_env"].get("HF_ENDPOINT") == "https://hf-mirror.com", state["train_env"]
        assert str(out).endswith("lora.safetensors"), out
    print("AT_IMAGE_PRE_DOWNLOAD_OK")

def test_qwen21_processor_cache(base: Path):
    """Fetch only processor/config assets, verify hashes, and reuse an offline cache."""
    import hashlib
    import json as _json

    root = base / "qwen21_processor_cache"
    payloads = {
        path: _json.dumps({"file": Path(path).name}).encode("utf-8")
        for path in core.AT_IMAGE_QWEN21_ASSET_FILES
    }
    metadata = {
        path: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for path, data in payloads.items()
    }
    downloads = []

    def fake_download(url, dest, logf=print, progress_cb=None, direct=False):
        rel_path = next(path for path in payloads if url.endswith("/" + path))
        downloads.append(rel_path)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(payloads[rel_path])
        return True

    with patch.object(core, "data_sub", side_effect=lambda *parts: str(root)), \
         patch.object(core, "_at_image_qwen21_assets_metadata", return_value=metadata), \
         patch.object(core, "_download_with_resume", side_effect=fake_download):
        cache = core._ensure_at_image_qwen21_assets(lambda *_a: None)
        assert Path(cache) == root
        assert core._at_image_qwen21_assets_ready(cache)
        assert set(downloads) == set(core.AT_IMAGE_QWEN21_ASSET_FILES)
        assert len([path for path in downloads if path.startswith("processor/")]) == 9
        assert {"text_encoder/config.json", "vae/config.json", "transformer/config.json"}.issubset(downloads)
        with patch.object(core, "_at_image_qwen21_assets_metadata", side_effect=AssertionError("valid cache should work offline")), \
             patch.object(core, "_download_with_resume", side_effect=AssertionError("valid cache should not redownload")):
            assert core._ensure_at_image_qwen21_assets(lambda *_a: None) == cache
        tokenizer = Path(cache) / "processor" / "tokenizer.json"
        damaged = bytearray(tokenizer.read_bytes())
        damaged[0] ^= 1
        tokenizer.write_bytes(damaged)
        assert not core._at_image_qwen21_assets_ready(cache)
        assert core._ensure_at_image_qwen21_assets(lambda *_a: None) == cache
        assert downloads.count("processor/tokenizer.json") == 2
        assert downloads.count("processor/vocab.json") == 1
        assert core._at_image_qwen21_assets_ready(cache)
        model_root = base / "full_model_with_assets"
        for rel_path in core.AT_IMAGE_QWEN21_ASSET_FILES:
            local_file = model_root / rel_path.replace("/", os.sep)
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_bytes(b"available")
        assert core._at_image_qwen21_assets_folder_ready(str(model_root))
        (model_root / "vae" / "config.json").unlink()
        assert not core._at_image_qwen21_assets_folder_ready(str(model_root))
    print("QWEN21_PROCESSOR_CACHE_OK")


def test_ai_toolkit_engine_update(base: Path):
    """AI Toolkit 一键源码更新：旧源码触发提示，更新校验注册，失败时恢复旧源码。"""
    roots = base / "at_engine_update"
    roots.mkdir(parents=True, exist_ok=True)
    source_zip = roots / "ai-toolkit-main.zip"
    source_zip.write_bytes(b"mock zip")
    calls = []

    def seed_engine(engine_dir: Path, python_path: Path):
        engine_dir.mkdir(parents=True, exist_ok=True)
        (engine_dir / "run.py").write_text("# old source\n", encoding="utf-8")
        python_path.parent.mkdir(parents=True, exist_ok=True)
        python_path.write_bytes(b"mock python")

    def extract_qwen21(_zip_path, stage_dir):
        stage = Path(stage_dir)
        (stage / "run.py").write_text("# updated source\n", encoding="utf-8")
        model_dir = stage / "extensions_built_in" / "diffusion_models"
        qwen_dir = model_dir / "qwen_image_2"
        qwen_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "__init__.py").write_text(
            "from .qwen_image_2 import QwenImage2Model\n", encoding="utf-8")
        (qwen_dir / "qwen_image_2.py").write_text(
            "import os\n"
            "class QwenImage2Model:\n"
            "    arch = 'qwen_image_2'\n"
            "    def load_model(self):\n"
            "        self.print_and_status_update(\"Loading transformer\")\n"
            "        transformer = QwenImage21Transformer2DModel.load(\n"
            "            model_path, config_path=base_model_path, **self.component_load_kwargs(\"transformer\")\n"
            "        )\n"
            "        processor = QwenImage21TextEncoder.load_processor(base_model_path)\n"
            "        self.print_and_status_update(\"Loading text encoder\")\n"
            "        text_encoder = QwenImage21TextEncoder.load_model(\n"
            "            base_model_path, dtype=dtype, subfolder=\"text_encoder\"\n"
            "        )\n"
            "        self.print_and_status_update(\"Loading VAE\")\n"
            "        vae = AutoencoderKLQwenImage21.load(\n"
            "            base_model_path, **self.component_load_kwargs(\"vae\")\n"
            "        )\n", encoding="utf-8")

    lock = SimpleNamespace()

    def downloaded(kind, logf=print, force_refresh=False, required_files=None):
        calls.append((kind, force_refresh, tuple(required_files or ())))
        return str(source_zip)

    # Successful update: source changes atomically; venv stays where it was; old source is backed up.
    good_engine = roots / "success" / "ai-toolkit"
    good_python = roots / "success" / "venv" / "Scripts" / "python.exe"
    seed_engine(good_engine, good_python)
    with patch.object(core, "_at_dirs", return_value=(str(good_python), str(good_engine))), \
         patch.object(core, "_download_engine_source", side_effect=downloaded), \
         patch.object(core, "_extract_zip", side_effect=extract_qwen21), \
         patch.object(core, "_acquire_kohya_install_lock", return_value=lock), \
         patch.object(core, "_release_kohya_install_lock", return_value=None), \
         patch.object(core.subprocess, "run", return_value=result(0, "QWEN_IMAGE_2_REGISTERED")), \
         patch.object(core, "clear_status_cache", return_value=None):
        assert core.ai_toolkit_engine_update_status()["update_available"] is True
        result_info = core.update_ai_toolkit_engine(lambda *_a: None)
        assert result_info.get("updated") is True, result_info
        assert core._ai_toolkit_qwen21_source_ready(str(good_engine)) is True
        patched_source = (good_engine / "extensions_built_in" / "diffusion_models" / "qwen_image_2" / "qwen_image_2.py").read_text(encoding="utf-8")
        assert "AI_TOOLKIT_QWEN21_TEXT_ENCODER_PATH" in patched_source, patched_source
        assert "AI_TOOLKIT_QWEN21_VAE_PATH" in patched_source, patched_source
        assert (good_engine / "run.py").read_text(encoding="utf-8") == "# updated source\n"
        assert good_python.is_file(), "更新引擎不应重建/移动独立 Python 环境"
        backup = Path(result_info["backup_dir"])
        assert (backup / "run.py").read_text(encoding="utf-8") == "# old source\n"
        assert core.ai_toolkit_engine_update_status()["update_available"] is False
    assert calls and calls[-1][0] == "ai-toolkit" and calls[-1][1] is True, calls
    assert any("qwen_image_2/qwen_image_2.py" in x.replace("\\", "/") for x in calls[-1][2]), calls

    # Failed runtime registration rolls the old engine source back into the active path.
    bad_engine = roots / "rollback" / "ai-toolkit"
    bad_python = roots / "rollback" / "venv" / "Scripts" / "python.exe"
    seed_engine(bad_engine, bad_python)
    with patch.object(core, "_at_dirs", return_value=(str(bad_python), str(bad_engine))), \
         patch.object(core, "_download_engine_source", side_effect=downloaded), \
         patch.object(core, "_extract_zip", side_effect=extract_qwen21), \
         patch.object(core, "_acquire_kohya_install_lock", return_value=lock), \
         patch.object(core, "_release_kohya_install_lock", return_value=None), \
         patch.object(core.subprocess, "run", return_value=result(1, stderr="mock import failure")), \
         patch.object(core, "clear_status_cache", return_value=None):
        try:
            core.update_ai_toolkit_engine(lambda *_a: None)
            raise AssertionError("更新后架构导入失败时必须报错")
        except RuntimeError as e:
            assert "更新后引擎检查失败" in str(e), e
        assert (bad_engine / "run.py").read_text(encoding="utf-8") == "# old source\n"
        assert core._ai_toolkit_qwen21_source_ready(str(bad_engine)) is False
    gui = (ROOT / "kohya_gui.py").read_text(encoding="utf-8")
    assert "_animate_at_engine_update_arrow" in gui and "一键更新" in gui
    assert '"AT_ENGINE_UPDATE_DONE"' in gui
    print("AI_TOOLKIT_ENGINE_UPDATE_OK")

def test_qwen21_reuses_comfy_components(base: Path):
    """Qwen-Image-2.1 自动复用 ComfyUI clip/vae 权重，并给 AI Toolkit 注入本地文件。"""
    models = base / "qwen21_comfy" / "ComfyUI" / "models"
    clip = models / "clip"
    vae = models / "vae"
    clip.mkdir(parents=True)
    vae.mkdir(parents=True)
    te_file = clip / "qwen3vl_8b_bf16.safetensors"
    vae_file = vae / "qwen_image_2.1_vae_bf16.safetensors"
    for path in (te_file, vae_file):
        with path.open("wb") as f:
            f.truncate(2 * 1024 * 1024)

    checkpoint = models / "unet" / "qwen_image_2.1_bf16.safetensors"
    checkpoint.parent.mkdir()
    with checkpoint.open("wb") as f:
        f.truncate(2 * 1024 * 1024)
    components = core.at_image_qwen21_local_components(str(checkpoint))
    assert components == {"text_encoder_path": str(te_file), "vae_path": str(vae_file)}, components

    # The extension patch accepts direct local safetensors paths and gives all
    # component configs plus the processor the same local cache root.
    engine = base / "qwen21_engine" / "ai-toolkit"
    qwen = engine / "extensions_built_in" / "diffusion_models" / "qwen_image_2"
    qwen.mkdir(parents=True)
    source = (
        "import os\n"
        "class QwenImage2Model:\n"
        "    def load_model(self):\n"
        "        self.print_and_status_update(\"Loading transformer\")\n"
        "        transformer = QwenImage21Transformer2DModel.load(\n"
        "            model_path, config_path=base_model_path, **self.component_load_kwargs(\"transformer\")\n"
        "        )\n"
        "        processor = QwenImage21TextEncoder.load_processor(base_model_path)\n"
        "        self.print_and_status_update(\"Loading text encoder\")\n"
        "        text_encoder = QwenImage21TextEncoder.load_model(\n"
        "            base_model_path, dtype=dtype, subfolder=\"text_encoder\"\n"
        "        )\n"
        "        self.print_and_status_update(\"Loading VAE\")\n"
        "        vae = AutoencoderKLQwenImage21.load(\n"
        "            base_model_path, **self.component_load_kwargs(\"vae\")\n"
        "        )\n"
    )
    model_file = qwen / "qwen_image_2.py"
    model_file.write_text(source, encoding="utf-8")
    assert core._patch_ai_toolkit_qwen21_local_components(str(engine), lambda *_a: None)
    patched = model_file.read_text(encoding="utf-8")
    assert "AI_TOOLKIT_QWEN21_TEXT_ENCODER_PATH" in patched, patched
    assert "AI_TOOLKIT_QWEN21_VAE_PATH" in patched, patched
    assert "local_text_encoder_path or base_model_path" in patched, patched
    assert "local_vae_path or base_model_path" in patched, patched
    assert "AI_TOOLKIT_QWEN21_ASSETS_PATH" in patched, patched
    assert "local_assets_path or base_model_path" in patched, patched
    assert "QwenImage21Transformer2DModel.load(\n            model_path, config_path=local_assets_path or base_model_path" in patched, patched
    assert "QwenImage21TextEncoder.load_processor(local_assets_path or base_model_path)" in patched, patched
    assert "dtype=dtype, config_path=local_assets_path or base_model_path" in patched, patched
    assert "config_path=local_assets_path or base_model_path," in patched, patched
    assert core._ai_toolkit_qwen21_local_components_patch_ready(str(engine))
    compile(patched, str(model_file), "exec")

    # Execute the generated loader with stub component classes. This verifies
    # that the environment paths reach the three weight loaders and that every
    # config/processor lookup uses the local assets root.
    assets_root = base / "qwen21_runtime_assets"
    for rel_path in core.AT_IMAGE_QWEN21_ASSET_FILES:
        asset = assets_root / rel_path.replace("/", os.sep)
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_text("{}", encoding="utf-8")
    manual_te = base / "runtime_text_encoder.safetensors"
    manual_vae = base / "runtime_vae.safetensors"
    manual_te.write_bytes(b"te")
    manual_vae.write_bytes(b"vae")
    calls = {}

    class FakeTransformer:
        @staticmethod
        def load(*args, **kwargs):
            calls["transformer"] = (args, kwargs)
            return "transformer"

    class FakeTextEncoder:
        @staticmethod
        def load_processor(*args, **kwargs):
            calls["processor"] = (args, kwargs)
            return "processor"

        @staticmethod
        def load_model(*args, **kwargs):
            calls["text_encoder"] = (args, kwargs)
            return "text_encoder"

    class FakeVae:
        @staticmethod
        def load(*args, **kwargs):
            calls["vae"] = (args, kwargs)
            return "vae"

    runtime = {
        "QwenImage21Transformer2DModel": FakeTransformer,
        "QwenImage21TextEncoder": FakeTextEncoder,
        "AutoencoderKLQwenImage21": FakeVae,
        "model_path": str(checkpoint),
        "base_model_path": "Qwen/Qwen-Image-2.1",
        "dtype": "bf16",
    }
    exec(compile(patched, str(model_file), "exec"), runtime)
    instance = runtime["QwenImage2Model"]()
    instance.print_and_status_update = lambda *_a: None
    instance.component_load_kwargs = lambda component: {"subfolder": component}
    with patch.dict(os.environ, {
        "AI_TOOLKIT_QWEN21_ASSETS_PATH": str(assets_root),
        "AI_TOOLKIT_QWEN21_TEXT_ENCODER_PATH": str(manual_te),
        "AI_TOOLKIT_QWEN21_VAE_PATH": str(manual_vae),
    }):
        instance.load_model()
    assert calls["transformer"][1].get("config_path") == str(assets_root), calls
    assert calls["processor"][0] == (str(assets_root),), calls
    assert calls["text_encoder"][0][0] == str(manual_te), calls
    assert calls["text_encoder"][1].get("config_path") == str(assets_root), calls
    assert calls["vae"][0][0] == str(manual_vae), calls
    assert calls["vae"][1].get("config_path") == str(assets_root), calls

    before = patched
    assert core._patch_ai_toolkit_qwen21_local_components(str(engine), lambda *_a: None)
    assert model_file.read_text(encoding="utf-8") == before, "引擎补丁必须幂等"

    # New ComfyUI layouts use text_encoders; keep that path working as well.
    (models / "text_encoders").mkdir()
    modern_te = models / "text_encoders" / "qwen3vl_8b_bf16.safetensors"
    modern_te.write_bytes(b"x" * (2 * 1024 * 1024))
    modern = core.at_image_qwen21_local_components(str(checkpoint))
    assert modern["text_encoder_path"] == str(modern_te), modern
    print("QWEN21_REUSES_COMFY_COMPONENTS_OK")

def test_wd14_triton_noise_collapse(base: Path):
    """WD14 无 Triton 告警/traceback 折叠成一行友好提示，不吞正常输出。"""
    import preprocess as pp
    seen = []
    code = (
        "import sys\n"
        "print('Traceback (most recent call last):')\n"
        "print('  File \"x.py\", line 1, in <module>')\n"
        "print(\"ModuleNotFoundError: No module named 'triton'\")\n"
        "print('WARNING:torchao.kernel.intmm: Detected no triton, certain kernels will not work')\n"
        "print('normal line 1')\n"
        "print('normal line 2')\n"
    )
    code_file = base / "triton_noise.py"
    code_file.write_text(code, encoding="utf-8")
    rc = pp._run_cmd([sys.executable, str(code_file)], logf=seen.append)
    assert rc == 0
    text = "\n".join(seen)
    assert "Traceback" not in text, text
    assert "ModuleNotFoundError" not in text, text
    assert "torchao" not in text, text
    assert "未检测到 Triton" in text, text
    assert "normal line 1" in text and "normal line 2" in text, text
    print("WD14_TRITON_NOISE_COLLAPSE_OK")

def test_musubi_version_check(base: Path):
    """_check_musubi_krea2_version：旧版 musubi（Krea2/FLUX.2 缺标记）阻止；新版通过。"""
    enc = base / "musubi" / "musubi-tuner" / "src" / "musubi_tuner"
    (enc / "flux_2").mkdir(parents=True, exist_ok=True)
    (enc / "krea2_train_network.py").write_text("print('old')\n", encoding="utf-8")
    (enc / "flux_2" / "flux2_utils.py").write_text("print('old')\n", encoding="utf-8")
    raised = False
    try:
        core._check_musubi_krea2_version(str(base / "musubi"), lambda *a: None)
    except RuntimeError as e:
        raised = True
        assert "musubi 版本过旧" in str(e) and "FLUX.2" in str(e), e
    assert raised, "旧版 musubi 应被阻止"
    (enc / "krea2_train_network.py").write_text("args.dit_dtype\nbfloat16\n", encoding="utf-8")
    (enc / "flux_2" / "flux2_utils.py").write_text("load_safetensors_with_lora_and_fp8\n", encoding="utf-8")
    core._check_musubi_krea2_version(str(base / "musubi"), lambda *a: None)
    print("MUSUBI_VERSION_CHECK_OK")

def test_quarantine_input_corrupt(base: Path):
    """预处理前损坏图片提前隔离：截断 PNG 移到 <输入目录>_corrupt，正常图保留。"""
    import preprocess as pp
    inp = base / "inp"
    inp.mkdir(parents=True, exist_ok=True)
    from PIL import Image as _PIL
    good = inp / "good.png"
    _PIL.new("RGB", (2, 2), (255, 0, 0)).save(str(good), format="PNG")
    bad = inp / "bad.png"
    bad.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)
    (inp / "bad.txt").write_text("tag", encoding="utf-8")
    removed = pp._quarantine_input_corrupt(str(inp), ["good.png", "bad.png"], print)
    assert removed == ["bad.png"], removed
    assert not bad.exists()
    corrupt_dir = Path(str(inp) + "_corrupt")
    assert corrupt_dir.is_dir() and (corrupt_dir / "bad.png").exists()
    assert (corrupt_dir / "bad.txt").exists()
    assert good.exists()
    print("QUARANTINE_INPUT_CORRUPT_OK")

def test_flux2_qwen3_06b_hint(base: Path):
    """FLUX.2 缺 4B 文本编码器且检测到 Anima 的 Qwen3-0.6B 时，缺失提示明确说明不适用。"""
    with patch.object(core, "flux2_model_files", return_value={}), \
            patch.object(core, "_anima_find_qwen3_any", return_value=("C:/fake/Qwen3-0.6B", "base")):
        missing = core.flux2_missing_models()
    joined = "\n".join(missing)
    assert "qwen_3_4b.safetensors" in joined, joined
    assert "Qwen3-0.6B" in joined and "不适用于 FLUX.2" in joined, joined
    print("FLUX2_QWEN3_06B_HINT_OK")

def test_sample_preview(base: Path):
    """训练中采样出图预览：提示词文件生成 + 显存门控 + 三引擎命令接线 + GUI 预览。"""
    with patch.object(core, "data_sub", side_effect=lambda *p: str(base.joinpath(*p))):
        p1 = core._write_sample_prompts("out1", {"sample_preview": True, "trigger": "bannai11"}, "character")
        assert p1 and os.path.isfile(p1)
        p1txt = open(p1, encoding="utf-8").read()
        assert "bannai11" in p1txt and "portrait" in p1txt and "1girl" not in p1txt, p1txt
        # kohya 引擎默认不带 musubi 的 --w/--h 后缀
        assert "--w " not in p1txt and "--h " not in p1txt, p1txt
        # musubi 引擎按训练分辨率出图，避免默认 256x256 出图又小又糊像"怪物"
        pm = core._write_sample_prompts("outm", {"sample_preview": True, "trigger": "bannai11"}, "style",
                                        resolution=512, engine="musubi")
        assert pm and os.path.isfile(pm)
        pmtxt = open(pm, encoding="utf-8").read()
        assert "--w 512 --h 512 --s 20" in pmtxt, pmtxt
        assert core._write_sample_prompts("out2", {"sample_preview": False}, "style") is None
    assert core._sample_preview_enabled({"sample_preview": True}, 12) is True
    assert core._sample_preview_enabled({"sample_preview": True}, 8) is True  # 勾选框说了算，低显存只警告不硬关
    assert core._sample_preview_enabled({"sample_preview": False}, 24) is False
    src = Path(core.__file__).read_text(encoding="utf-8-sig")
    # 2026-09-07（332c19e）起采样步数改为跟随「中间保存快照」，不再写死每 100 步；
    # 故按语义断言「三处都接线了采样」而不是抓字面量 "--sample_every_n_steps=100"。
    assert src.count("--sample_every_n_steps=") >= 3, "train/krea2/flux2 应都接线采样"
    assert "--sample_prompts=" in src
    assert '"--text_encoder", files["te"]' in src  # Krea2 采样必须带 text_encoder（musubi assert）
    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8")
    assert "sample_preview_var" in g and "_refresh_sample_preview" in g and "mon_sample_lbl" in g and "_is_sample_file" in g
    print("SAMPLE_PREVIEW_OK")

def test_gated_download_guidance(base: Path):
    """门禁模型下载兜底引导：_http_status 401 探测 + 下载器 HF_TOKEN/提示 + GUI 预检接线。"""
    import urllib.error
    def _raise_401(*a, **k):
        raise urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, None)
    with patch.object(core.urllib.request, "urlopen", side_effect=_raise_401):
        assert core._http_status("https://hf-mirror.com/x") == 401
    md = (ROOT / "model_downloader.py").read_text(encoding="utf-8")
    assert "HF_TOKEN" in md and "Authorization" in md and "401/403" in md
    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8")
    assert 'key in ("raw", "turbo")' in g and "魔搭（ModelScope）官方转存直链" in g
    print("GATED_DOWNLOAD_GUIDANCE_OK")

def test_at_image_low_vram_vram_aware(base: Path):
    """AI 图像 low_vram 显存感知（v0.11.3）：显存充足关掉提速（A6000 48G Qwen-Image 9.76s/it 主因），低显存/未知保持开。"""
    info = core.AT_IMAGE_MODELS["qwen_image"]
    out = base / "out"
    out.mkdir(parents=True, exist_ok=True)
    params = {"project": "t", "rank": 16, "alpha": 16, "unet_lr": 1e-4, "video_steps": 100,
              "trigger": "x", "resolution": 1024, "optimizer": "AdamW"}
    def _gen(vram):
        p = base / ("q_%s.yaml" % str(vram))
        core.write_at_image_yaml(params, info, str(base), str(out), str(p), vram_gb=vram)
        return p.read_text(encoding="utf-8")
    assert "low_vram: false" in _gen(44), "48G 高显存应关 low_vram（A6000 提速主因）"
    assert "low_vram: true" in _gen(8), "低显存应保持开"
    assert "low_vram: true" in _gen(None), "显存未知应保守开"
    print("AT_IMAGE_LOW_VRAM_VRAM_AWARE_OK")

def test_krea2_first_engine_guard(base: Path):
    """Krea2 底模不能在第一引擎（kohya）训练：识别 + 拦截 + 引导（否则按 FLUX 加载 OOM）。"""
    # 1) 键识别：txtfusion → krea2；不误判 FLUX/Anima
    assert core._classify_base_keys(["txtfusion.0.attn.wq.weight", "blocks.0.attn.wq.weight"]) == "krea2"
    assert core._classify_base_keys(["double_blocks.0.attn.qkv.weight"]) == "flux"
    assert core._classify_base_keys(["llm_adapter.0.weight", "adaln_modulation.0.weight", "x_embedder.weight"]) == "anima"
    # 2) 文件名兜底（用户把 Krea2raw.safetensors 放 models/base 的场景）
    assert core._looks_like_krea2(r"I:\Documents\KohyaLoraTool\models\base\Krea2raw.safetensors") is True
    assert core._looks_like_krea2(r"I:\models\base\flux1-dev.safetensors") is False
    # 3) train() 第一引擎入口有拦截 + 引导文案
    src = Path(core.__file__).read_text(encoding="utf-8-sig")
    i = src.find("def train(logf=print, base_model=None")
    j = src.find("\ndef ", i + 1)
    seg = src[i:j]
    assert "_looks_like_krea2(_k2base)" in seg, "train() 缺 Krea2 拦截"
    assert "Krea2 训练必须用「第二引擎(musubi)」的 Krea2 模式" in seg, "缺引导文案"
    # 4) GUI 选底模：识别到 Krea2 有明确提示（不再是笼统的「类型待确认」）
    # 2026-09-12：_on_base_change 现在在新界面 kohya_gui.py（旧 tkinter 界面已删），
    # 断言跟着改到当前 UI 文件，否则会一直指着已删除的死代码。
    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8-sig")
    i2 = g.find("def _on_base_change")
    assert i2 >= 0, "kohya_gui.py 缺 _on_base_change"
    j2 = g.find("\n    def ", i2 + 1)
    seg2 = g[i2:] if j2 < 0 else g[i2:j2]
    assert "core._looks_like_krea2(payload)" in seg2, "GUI 缺 Krea2 提示分支"
    assert "Krea2 训练请用第二引擎" in seg2, "GUI 缺 Krea2 提示文案"
    print("KREA2_FIRST_ENGINE_GUARD_OK")

def test_third_engine_triton_and_laptop_warning(base: Path):
    """v0.11.3：第三引擎缺 Triton 自动补装 + 笔记本低显存重型模型强警告。"""
    src = Path(core.__file__).read_text(encoding="utf-8-sig")
    assert "def _ensure_ai_toolkit_triton" in src, "缺第三引擎 triton 补装"
    assert "_ensure_ai_toolkit_triton(vpy, logf, amd_mode=" in src, "train_at_image 缺 triton 接线"
    assert "def _warn_laptop_heavy_load" in src, "缺笔记本强警告"
    for fn in ("train_krea2", "train_flux2", "train_at_image"):
        i = src.find("def %s(" % fn)
        j = src.find("\ndef ", i + 1)
        seg = src[i:j]
        assert "_warn_laptop_heavy_load(logf, vram_gb" in seg, "%s 缺笔记本警告接线" % fn
    # 行为验证：笔记本 + 低显存触发警告；台式机不触发
    logs = []
    with patch.object(core, "detect_gpu_name", return_value="NVIDIA GeForce RTX 4070 Laptop GPU"):
        core._warn_laptop_heavy_load(logs.append, 8, "Krea2")
    assert any("笔记本" in x for x in logs), logs
    logs.clear()
    with patch.object(core, "detect_gpu_name", return_value="NVIDIA GeForce RTX 4090"):
        core._warn_laptop_heavy_load(logs.append, 24, "Krea2")
    assert not logs, logs
    print("THIRD_ENGINE_TRITON_AND_LAPTOP_WARNING_OK")

def test_swap_zero_option(base: Path):
    """块交换数下拉应可选 0（全驻留显存不搬）：GUI 可选 + 后端手动分支正确生成无 swap 命令。"""
    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8-sig")
    # 1) 下拉值含 "0"
    assert '"自动", "0", "2", "4", "6", "8", "10", "12"' in g, "块交换数下拉缺 0（全驻留）选项"
    # 2) 保存/恢复：0 是纯数字，走 isdigit 分支（不回退成自动）
    assert 'str(self.swap_var.get()).isdigit()' in g, "保存逻辑缺 isdigit"
    assert 'str(_swap_gui).isdigit()' in g, "恢复逻辑缺 isdigit"
    # 3) 后端：手动 0 → swap=0 且不追加 --blocks_to_swap（全部驻留）
    c = Path(core.__file__).read_text(encoding="utf-8-sig")
    for fn in ("train_krea2", "train_flux2"):
        i = c.find("def %s" % fn)
        j = c.find("\ndef ", i + 1)
        seg = c[i:j]
        assert "_manual_swap.isdigit()" in seg, "%s 缺手动 swap 分支" % fn
        assert "swap = min(int(_manual_swap), " in seg, "%s 缺 swap 上限收敛" % fn
        assert "if swap > 0:" in seg, "%s 缺 swap>0 才追加参数" % fn
    print("SWAP_ZERO_OPTION_OK")

def test_torch_compile_safe_fallback(base: Path):
    """v0.11.1「勾选 torch.compile 直接 TritonMissing 崩溃」修复：自检/自动补装/失败自动回退，不再硬崩。"""
    src = Path(core.__file__).read_text(encoding="utf-8-sig")
    # 1) 自检函数 + 探针：必须真实 CUDA forward+backward（能暴露 TritonMissing）
    assert "def _ensure_compile_ready" in src, "缺 _ensure_compile_ready"
    assert "def _compile_probe_code" in src, "缺 _compile_probe_code"
    assert "def _log_mentions_compile_failure" in src, "缺 _log_mentions_compile_failure"
    assert "torch.compile(m)" in src and "backward()" in src and "COMPILE_PROBE_OK" in src, "探针必须真实 forward+backward"
    assert 'TRITON_WINDOWS_PIN = "3.3.0.post19"' in src, "缺 triton-windows 固定版本"
    assert "triton-windows==%s" in src, "应自动补装 triton-windows"
    # 2) 失败标记检测：TritonMissing/inductor 命中；正常日志与 OOM 不误报
    assert core._log_mentions_compile_failure(["torch._inductor.exc.TritonMissing: Cannot find a working triton installation"])
    assert core._log_mentions_compile_failure(["Traceback", "TritonError: abc"])
    assert not core._log_mentions_compile_failure(["steps: 1/696, avr_loss=0.07"])
    assert not core._log_mentions_compile_failure(["CUDA out of memory."])
    # 3) Krea2：--compile 仅在自检通过时追加；失败回退 SDPA 不中断；运行期崩溃自动去掉 --compile 重试
    i = src.find("def train_krea2")
    j = src.find("\ndef ", i + 1)
    k = src[i:j]
    assert "_compile_ok, _compile_note = _ensure_compile_ready(mvpy, logf)" in k, "Krea2 缺自检接线"
    assert "已自动禁用" in k, "Krea2 缺回退提示文案"
    assert "自动去掉 --compile" in k, "Krea2 缺运行期自动重试"
    # 4) FLUX.2 同样接线（GUI 勾选文案 Krea2/FLUX.2 现在名副其实）
    i2 = src.find("def train_flux2")
    j2 = src.find("\ndef ", i2 + 1)
    f = src[i2:j2]
    assert "_flux2_compile_ok, _flux2_compile_note = _ensure_compile_ready(mvpy, logf)" in f, "FLUX.2 缺自检接线"
    assert "已自动禁用" in f, "FLUX.2 缺回退提示文案"
    assert "自动去掉 --compile" in f, "FLUX.2 缺运行期自动重试"
    print("TORCH_COMPILE_SAFE_FALLBACK_OK")

def test_venv_hf_sitecustomize(base: Path):
    """训练环境注入 sitecustomize.py：强制 hf-mirror + 禁用 Xet（幂等、不覆盖用户自定义）。"""
    venv = base / "venv"
    sp = venv / "Lib" / "site-packages"
    sp.mkdir(parents=True, exist_ok=True)
    logs = []
    assert core._ensure_venv_hf_sitecustomize(str(venv), logs.append) is True
    t = sp / "sitecustomize.py"
    content = t.read_text(encoding="utf-8")
    assert "KohyaLoRA_HF_MIRROR" in content
    assert "HF_ENDPOINT" in content and "hf-mirror.com" in content
    assert "HF_HUB_DISABLE_XET" in content
    # 幂等：二次调用不重复写
    first = content
    core._ensure_venv_hf_sitecustomize(str(venv), logs.append)
    assert t.read_text(encoding="utf-8") == first
    # 已有自定义 sitecustomize → 追加不覆盖
    t.write_text("# user custom\nimport sys\n", encoding="utf-8")
    core._ensure_venv_hf_sitecustomize(str(venv), logs.append)
    merged = t.read_text(encoding="utf-8")
    assert "# user custom" in merged and "import sys" in merged and "KohyaLoRA_HF_MIRROR" in merged
    # 五个训练入口都接线了
    src_main = Path(core.__file__).read_text(encoding="utf-8-sig")
    assert src_main.count("_ensure_venv_hf_sitecustomize(") >= 7  # helper def + 5 train + amd 分支
    print("VENV_HF_SITECUSTOMIZE_OK")

def test_export_log(base: Path):
    """一键导出日志：纯函数组装含版本/环境/日志内容 + GUI 按钮/弹窗接线。"""
    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8")
    assert "cmd_export_log" in g and "_show_export_dialog" in g
    assert "_export_log_text" in g and "_collect_env_lines" in g
    assert "导出日志" in g and "explorer" in g
    import kohya_gui as gui
    env = ["操作系统: Windows-11", "显卡: NVIDIA RTX 4060（厂商 nvidia，显存 8GB）",
           "第一引擎(kohya): 已安装", "第二引擎(musubi): 已安装", "第三引擎(ai-toolkit): 未安装"]
    text = gui._export_log_text("step 1/10 loss=0.5", "testproj", env_lines=env)
    assert "Kohya-LoRA 一键训练工具" in text
    assert "软件版本: v" in text and "项目: testproj" in text
    assert "操作系统: Windows-11" in text and "NVIDIA RTX 4060" in text
    assert "step 1/10 loss=0.5" in text
    # 无日志时给占位提示
    text2 = gui._export_log_text("", "p2", env_lines=[])
    assert "（暂无日志）" in text2
    print("EXPORT_LOG_OK")

def test_krea2_training_env_propagation(base: Path):
    """Krea2/FLUX.2 训练命令必须带 KREA2_TOKENIZER_DIR 环境（采样加载文本编码器用本地 tokenizer）。

    背景：v0.10.11 加采样预览后，训练命令带 --sample_every_n_steps + --text_encoder，
    训练子进程加载文本编码器时 musubi 会拉 Qwen3-VL-4B tokenizer；若 KREA2_TOKENIZER_DIR
    只传给缓存步骤而漏传给训练步骤，国内直连 huggingface.co 会 SSL 失败 → 训练秒崩。
    """
    src = Path(core.__file__).read_text(encoding="utf-8-sig")
    # krea2 缓存 TE + 训练 + flux2 缓存 TE + 训练：4 处 run_stream 都要传 _k2env
    assert src.count("env=_k2env") >= 4, "krea2/flux2 缓存+训练（含 compile 自动重试）run_stream 都应传 env=_k2env"
    assert src.count('_k2env["KREA2_TOKENIZER_DIR"]') == 2
    assert src.count("run_stream(cmd, cwd=mt_dir, env=_k2env, logf=logf, collect=_log_tail)") == 2
    print("KREA2_TRAINING_ENV_PROPAGATION_OK")

def test_krea2_modelscope_mirror(base: Path):
    """Krea2 Raw/Turbo 已改走魔搭官方转存（免许可直链），文件名与识别逻辑不变。"""
    links = core.KREA2_MODEL_LINKS
    assert links["raw"][0] == "raw.safetensors"
    assert links["turbo"][0] == "turbo.safetensors"
    assert links["raw"][2].startswith("https://modelscope.cn/models/krea/Krea-2-Raw/resolve/master/raw.safetensors")
    assert links["turbo"][2].startswith("https://modelscope.cn/models/krea/Krea-2-Turbo/resolve/master/turbo.safetensors")
    assert "hf-mirror.com" not in links["raw"][2] and "hf-mirror.com" not in links["turbo"][2]
    # VAE / 文本编码器也已魔搭化（2026-08-28：hf-mirror 故障/被污染后不再依赖）
    assert "modelscope.cn" in links["vae"][2] and "modelscope.cn" in links["te"][2]
    # 下载器需把 modelscope.cn 当作国内直连域名（不套系统代理）
    md = (ROOT / "model_downloader.py").read_text(encoding="utf-8")
    assert "modelscope.cn" in md
    print("KREA2_MODELSCOPE_MIRROR_OK")

def test_fourth_engine(base: Path):
    """第四引擎（Fizgig）安装控制流：NVIDIA CUDA + AMD ROCm 两条路径（mock 子进程）。"""
    import contextlib
    kdir = base / "fourth" / "kohya_ss"
    fz_dir = kdir / "fizgig"
    fv = kdir / "fizgig_venv"
    fake_python(fv / "Scripts" / "python.exe")
    (fv / "pyvenv.cfg").write_text("home = X:\\MissingPython\n", encoding="utf-8")

    src_zip = base / "sources" / "fizgig.zip"
    make_source_zip(src_zip, "Fizgig-master", {
        "requirements.txt": "torch==2.10.0\nbitsandbytes==0.48.2\nnumpy\naccelerate==1.6.0\ntransformers\n",
        "src/fizgig/scripts/krea2_train.py": "import sys\n",
        "detect_gpu.py": "print('gfx1100')\n",
    })

    def run_flow(vendor):
        state = {"rebuilt": False, "torch": False, "deps": False, "rocm": False, "bnb": False, "verify": False}
        logs = []

        def run_stream(cmd, cwd=None, env=None, logf=print, **kwargs):
            cmd = [str(x) for x in cmd]
            if len(cmd) >= 4 and cmd[1:3] == ["-m", "venv"]:
                target = Path(cmd[3])
                fake_python(target / "Scripts" / "python.exe")
                state["rebuilt"] = True
                return 0
            if "--no-deps" in cmd and any("rocm_sdk_devel" in x for x in cmd):
                # 魔搭缓存路径：本地 wheel --no-deps 安装（绕开 rocm 元包解析）
                assert any("rocm_sdk_core" in x for x in cmd)
                assert any("torch-2.12.0+rocm7.15.0a20260728" in x for x in cmd)
                state["rocm"] = True
                return 0
            if any("rocm.nightlies.amd.com" in x for x in cmd):
                assert "torch[device-gfx1100]==2.12.0+rocm7.15.0a20260728" in cmd
                assert "rocm-sdk-devel==7.15.0a20260728" in cmd
                state["rocm"] = True
                return 0
            if "bitsandbytes" in " ".join(cmd) and any(x.endswith(".whl") for x in cmd):
                state["bnb"] = True
                return 0
            if "-r" in cmd:
                req = Path(cmd[cmd.index("-r") + 1]).read_text(encoding="utf-8")
                assert "torch==" not in req and "torchvision==" not in req
                if vendor == "nvidia":
                    assert "triton-windows" in req and "bitsandbytes==0.48.2" in req
                else:
                    assert "triton-windows" not in req and "bitsandbytes" not in req
                    assert "setuptools<82" in req and "filelock" in req
                state["deps"] = True
                return 0
            return 0

        def subrun(cmd, *args, **kwargs):
            cmd = [str(x) for x in cmd]
            if len(cmd) > 1 and str(cmd[1]).endswith("detect_gpu.py"):
                return result(0, "gfx1100\n")
            code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
            if "import torch" in code:
                if vendor == "amd":
                    if not state["rocm"]:
                        return result(1, "")
                    if "rocm=" in code:
                        return result(0, "2.12.0+rocm7.15.0a20260728\nrocm=7.15.0\nhip=7.15.0\ncuda=\nok=True\n")
                    return result(0, "2.12.0+rocm7.15.0a20260728\nok=True\n")
                if not state["torch"]:
                    return result(1, "")
                return result(0, "2.10.0+cu128\ncuda=12.8\nok=True\n")
            if code and "print(sys.executable)" in code:
                return result(0, r"C:\Python312\python.exe")
            if len(cmd) > 1 and str(cmd[1]).endswith("krea2_train.py"):
                state["verify"] = True
                return result(0, "--help output")
            return result(0)

        def preinstall(*args, **kwargs):
            assert kwargs.get("torch_ver") == "2.10.0"
            assert kwargs.get("tv_ver") == "0.25.0"
            assert kwargs.get("cu") == "cu128"
            state["torch"] = True
            return True

        patches = common_patches(kdir) + (
            patch.object(core, "_find_python312_exe", return_value=r"C:\Python312\python.exe"),
            patch.object(core, "_download_fizgig_source", return_value=str(src_zip)),
            patch.object(core, "run_stream", side_effect=run_stream),
            patch.object(core.subprocess, "run", side_effect=subrun),
            patch.object(core, "_upgrade_pip", return_value=True),
            patch.object(core, "_ensure_venv_pip", return_value=True),
            patch.object(core, "_venv_python_ok", return_value=(False, "venv 指向的 Python 已不存在")),
            patch.object(core, "_preinstall_torch", side_effect=preinstall),
            patch.object(core, "detect_gpu_vendor", return_value=vendor),
            patch.object(core, "_download_with_resume", return_value=True),
            patch.object(core, "_wheel_valid", return_value=True),
        )
        with contextlib.ExitStack() as st:
            for p in patches:
                st.enter_context(p)
            out = core.install_fizgig_engine(logs.append)
        assert Path(out) == fv / "Scripts" / "python.exe"
        assert state["rebuilt"] and state["deps"] and state["verify"]
        assert any("已损坏" in line for line in logs)
        assert any(kdir.glob("fizgig_venv_broken_*"))
        return state, logs

    s1, l1 = run_flow("nvidia")
    assert s1["torch"] and not s1["rocm"]
    assert any("NVIDIA CUDA" in x for x in l1)

    # 魔搭路径：rocm sdist 下载后需真实文件存在（代码检查 os.path.isfile）
    _rdir = base / "fourth" / "cache" / "cache" / "engine_sources" / "rocm"
    _rdir.mkdir(parents=True, exist_ok=True)
    (_rdir / "rocm-7.15.0a20260728.tar.gz").write_bytes(b"dummy")
    s2, l2 = run_flow("amd")
    assert s2["rocm"] and s2["bnb"] and not s2["torch"]
    assert any("AMD ROCm" in x for x in l2) and any("gfx1100" in x for x in l2)
    print("FOURTH_ENGINE_NVIDIA_AND_AMD_CONTROL_FLOW_OK")

    # 兜底：魔搭缓存下载失败 → 自动回退 AMD nightly（rocm.nightlies 命令）
    kdir = base / "fourth" / "kohya_ss"
    fv = kdir / "fizgig_venv"
    fz_dir = kdir / "fizgig"
    state = {"rebuilt": False, "torch": False, "deps": False, "rocm": False, "bnb": False, "verify": False}
    logs = []
    def run_stream2(cmd, cwd=None, env=None, logf=print, **kwargs):
        cmd = [str(x) for x in cmd]
        if len(cmd) >= 4 and cmd[1:3] == ["-m", "venv"]:
            fake_python(Path(cmd[3]) / "Scripts" / "python.exe")
            state["rebuilt"] = True
            return 0
        if any("rocm.nightlies.amd.com" in x for x in cmd):
            assert "torch[device-gfx1100]==2.12.0+rocm7.15.0a20260728" in cmd
            state["rocm"] = True
            return 0
        if "bitsandbytes" in " ".join(cmd) and any(x.endswith(".whl") for x in cmd):
            state["bnb"] = True
            return 0
        if "-r" in cmd:
            state["deps"] = True
            return 0
        return 0
    def subrun2(cmd, *args, **kwargs):
        cmd = [str(x) for x in cmd]
        if len(cmd) > 1 and str(cmd[1]).endswith("detect_gpu.py"):
            return result(0, "gfx1100\n")
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "import torch" in code:
            if not state["rocm"]:
                return result(1, "")
            return result(0, "2.12.0+rocm7.15.0a20260728\nrocm=7.15.0\nhip=7.15.0\ncuda=\nok=True\n")
        if len(cmd) > 1 and str(cmd[1]).endswith("krea2_train.py"):
            state["verify"] = True
            return result(0, "--help")
        return result(0)
    patches2 = common_patches(kdir) + (
        patch.object(core, "_find_python312_exe", return_value=r"C:\Python312\python.exe"),
        patch.object(core, "_download_fizgig_source", return_value=str(base / "sources" / "fizgig.zip")),
        patch.object(core, "run_stream", side_effect=run_stream2),
        patch.object(core.subprocess, "run", side_effect=subrun2),
        patch.object(core, "_upgrade_pip", return_value=True),
        patch.object(core, "_ensure_venv_pip", return_value=True),
        patch.object(core, "_venv_python_ok", return_value=(False, "venv 指向的 Python 已不存在")),
        patch.object(core, "detect_gpu_vendor", return_value="amd"),
        patch.object(core, "_download_with_resume",
                     side_effect=lambda url, dest, logf=print, progress_cb=None, direct=False: "modelscope.cn" not in url),  # 魔搭失败→nightly；bnb(GitHub) 成功
        patch.object(core, "_wheel_valid", return_value=True),
    )
    with contextlib.ExitStack() as st2:
        for p in patches2:
            st2.enter_context(p)
        core.install_fizgig_engine(logs.append)
    assert state["rocm"] and state["bnb"] and state["verify"]
    assert any("回退 AMD nightly" in x for x in logs)
    print("FOURTH_ENGINE_AMD_NIGHTLY_FALLBACK_OK")

def test_fizgig_deps_self_heal(base: Path):
    """Fizgig 训练前依赖自愈：老版本装的 fizgig_venv 缺 toml 等包时按需补装（AMD 7900 XT 用户复现）。"""
    src = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8-sig")
    assert "def _ensure_fizgig_deps" in src, "缺 Fizgig 依赖自愈函数"
    assert "_ensure_fizgig_deps(vpy, fz_dir, logf)" in src, "缺训练前接线"
    assert "import importlib.util" in src, "探测必须显式引入 importlib.util（否则 find_spec 必崩、自愈静默失效）"
    # 功能：探测返回 MISSING=toml → run_stream 应收到 pip install toml（自愈真的生效）
    logs = []
    calls = []

    class _CP:
        returncode = 0
        stdout = "MISSING=toml\n"
        stderr = ""

    with patch.object(core.subprocess, "run", return_value=_CP()), \
         patch.object(core, "_fz_selftest", return_value=True), \
         patch.object(core, "run_stream", side_effect=lambda cmd, *a, **k: (calls.append([str(x) for x in cmd]), 0)[1]):
        # ⚠️ 本测试只管「缺依赖 → 补装」这条链 ✗ 所以把**深度自检**打桩成通过 ✓
        #   （2026-09-22）不打桩的话：它用一个假 python 路径、又 patch 了 subprocess.run ✗
        #   → 自检必然失败 ✗ 断言就测不到本来要测的补装了 ✓
        #   「环境坏时必须返回 False」由下面一段单独覆盖 ✓
        ok = core._ensure_fizgig_deps(r"X:\fizgig_venv\Scripts\python.exe", str(base), logs.append)
    assert ok is True, "缺 toml 时应补装成功"
    assert any("pip" in c and "install" in c and "toml" in c for c in calls), calls
    assert any("--no-cache-dir" in c for c in calls), "应绕过损坏的 pip 缓存（--no-cache-dir）"

    # ★ 2026-09-22 新增：依赖齐了、但**包里是坏的**（如 `transformers/models` 损坏 1392、
    #   或 `torch/_C` 缺失）时，必须返回 False 把训练拦下 ✓
    #   这正是三份用户日志的坏法 ✗ —— 以前 `find_spec` 看目录在不在，**完全看不见** ✗
    #   于是拖到「训练跑到一半」才炸 ✗（latents/文本编码器缓存全白跑 ✗）
    _logs2 = []
    with patch.object(core.subprocess, "run", return_value=_CP()), \
         patch.object(core, "_fz_selftest", return_value=False), \
         patch.object(core, "run_stream", side_effect=lambda cmd, *a, **k: (calls.append([str(x) for x in cmd]), 0)[1]):
        assert core._ensure_fizgig_deps(r"X:\fizgig_venv\Scripts\python.exe", str(base), _logs2.append) is False, \
            "包在但坏了（自检不过）时必须返回 False 拦下训练 ✗ —— 否则又会跑到一半才炸"
    print("FIZGIG_DEPS_SELF_HEAL_OK")
def test_fourth_engine_train_pipeline(base: Path):
    """train_krea2_fizgig：数据集 TOML + 缓存 + 训练命令构造（8G→NF4 / 16G→fp8+swap20）。"""
    import contextlib
    import Kohya一键工具 as core_mod
    proj = "fztest"
    train_dir = base / "data" / "train_character"
    train_dir.mkdir(parents=True, exist_ok=True)
    for k in range(1, 5):
        (train_dir / ("img%02d.png" % k)).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        (train_dir / ("img%02d.txt" % k)).write_text("fztest subject, portrait\n", encoding="utf-8")
    kdir = base / "trainpipe" / "kohya_ss"
    kdir.mkdir(parents=True, exist_ok=True)
    (kdir / "fizgig_venv" / "Scripts").mkdir(parents=True, exist_ok=True)
    fake_python(kdir / "fizgig_venv" / "Scripts" / "python.exe")
    (kdir / "fizgig" / "src" / "fizgig" / "scripts").mkdir(parents=True, exist_ok=True)
    (kdir / "fizgig" / "src" / "fizgig" / "scripts" / "krea2_train.py").write_text("import sys\n", encoding="utf-8")
    mods = base / "models" / "krea2"
    mods.mkdir(parents=True, exist_ok=True)
    for name in ("raw.safetensors", "qwen_image_vae.safetensors", "qwen3vl_4b_bf16.safetensors"):
        (mods / name).write_bytes(b"TENSOR" + b"\0" * 64)
    kit = base / "kit"
    (kit / "configs").mkdir(parents=True, exist_ok=True)

    def run_flow(vram_gb, quant_mode, expect_flags, expect_no_flags, backend="nvidia"):
        logs = []
        cmds = []
        envs = []

        def run_stream(cmd, cwd=None, env=None, logf=print, **kwargs):
            envs.append(env)
            cmds.append([str(x) for x in cmd])
            return 0

        patches = (
            patch.object(core, "get_kohya_dir", return_value=str(kdir)),
            patch.object(core, "data_sub", side_effect=lambda *parts: str(base / "out" / ".".join(parts))),
            patch.object(core, "data_dir", return_value=str(base / "appdata")),
            patch.object(core, "KIT_DIR", str(kit)),
            patch.object(core, "fizgig_engine_status", return_value=(True, "已就绪", str(kdir / "fizgig_venv" / "Scripts" / "python.exe"), backend)),
            patch.object(core, "krea2_model_files", return_value={
                "raw": str(mods / "raw.safetensors"),
                "vae": str(mods / "qwen_image_vae.safetensors"),
                "te": str(mods / "qwen3vl_4b_bf16.safetensors"),
            }),
            patch.object(core, "krea2_missing_models", return_value=[]),
            patch.object(core, "_safetensors_complete", return_value=True),
            patch.object(core, "_safetensors_is_prequantized", return_value=False),
            patch.object(core, "dataset_train_dir", return_value=str(train_dir)),
            patch.object(core, "detect_ram_gb", return_value=32),
            patch.object(core, "run_stream", side_effect=run_stream),
            patch.object(core, "_ensure_fizgig_deps", return_value=True),
        )
        params = {"project": proj, "rank": "16", "alpha": "8", "unet_lr": "1e-4",
                  "max_epochs": "2", "repeats": "2", "resolution": "512",
                  "trigger": "fztest", "quant_mode": quant_mode, "compile": "0"}
        with contextlib.ExitStack() as st:
            for p in patches:
                st.enter_context(p)
            core.train_krea2_fizgig(logs.append, mode="krea2_fz", params=params, vram_gb=vram_gb)
        assert len(cmds) == 3, "expected 3 subprocess calls, got %d" % len(cmds)
        lat, tex, trn = cmds
        assert lat[1].endswith("krea2_cache_latents.py") and "--vae" in lat and "--skip_existing" in lat
        assert tex[1].endswith("krea2_cache_text.py") and "--text_encoder" in tex and "--skip_existing" in tex
        assert trn[1].endswith("krea2_train.py")
        joined = " ".join(trn)
        assert "--dit" in joined and "--network_dim" in joined and "16" in joined
        assert "--compile_blocks" in joined and "off" in joined
        for f in expect_flags:
            assert f in joined, "missing %s in %s" % (f, joined[:300])
        for f in expect_no_flags:
            assert f not in joined, "unexpected %s in %s" % (f, joined[:300])
        # 数据集 TOML
        toml = (kit / "configs" / "fizgig_krea2_dataset_config.toml").read_text(encoding="utf-8")
        assert "resolution = [512, 512]" in toml
        assert "image_directory" in toml and train_dir.as_posix() in toml
        assert "num_repeats = 2" in toml
        # 训练输出日志
        assert any("Krea2(Fizgig)" in x for x in logs)
        return envs

    l1 = run_flow(8, "auto", expect_flags=["--quantize_4bit"], expect_no_flags=["--blocks_to_swap"])
    l2 = run_flow(16, "auto", expect_flags=["--blocks_to_swap", "20"], expect_no_flags=["--quantize_4bit"])
    l3 = run_flow(12, "nf4", expect_flags=["--quantize_4bit"], expect_no_flags=["--blocks_to_swap"])
    # AMD 后端：run_stream 必须收到 ROCm 运行时环境（BNB_ROCM_VERSION=715 等）
    l4_envs = run_flow(16, "auto", expect_flags=["--blocks_to_swap", "20"], expect_no_flags=["--quantize_4bit"], backend="amd-rocm")
    _train_env = l4_envs[-1] or {}
    assert _train_env.get("BNB_ROCM_VERSION") == "715"
    assert _train_env.get("FIZGIG_GPU_BACKEND") == "rocm"
    assert _train_env.get("ROCM_PATH", "").endswith("_rocm_sdk_core")
    assert "MIOPEN_FIND_MODE" in _train_env and "expandable_segments" in _train_env.get("PYTORCH_ALLOC_CONF", "")
    # v0.14.6 起 AMD ROCm 优化器回归 Fizgig 官方默认（不再强制 adamw），此处不再断言命令带 adamw
    print("FOURTH_ENGINE_AMD_ROCM_ENV_OK")
    print("FOURTH_ENGINE_TRAIN_PIPELINE_OK")
def test_resume_monitor_seed(base: Path):
    """断点续训监控续上：resume_step_from 解析 + TrainMonitor.set_step 预填 + 日志覆盖。"""
    assert core.resume_step_from(r"C:\out\proj\krea2_lora-step00000200-state") == 200
    assert core.resume_step_from(r"C:\out\proj\no_step_dir") == 0
    d = base / "state_dir"
    d.mkdir(parents=True, exist_ok=True)
    (d / "training_state.json").write_text('{"global_step": 321}', encoding="utf-8")
    assert core.resume_step_from(str(d)) == 321
    mon = core.TrainMonitor()
    mon.start(total=544)
    mon.set_step(200)
    snap = mon.snapshot()
    assert snap["step"] == 200 and snap["total"] == 544
    # 后续训练日志仍会覆盖为真实进度（续上后继续走）
    mon.on_line("steps: 210/544 [00:05<00:20, 1.00it/s, loss=0.5]")
    assert mon.snapshot()["step"] == 210
    print("RESUME_MONITOR_SEED_OK")

def test_resume_promise_is_truthful(base: Path):
    """停止训练时的「可续训」承诺必须与事实一致。

    2026-09-15 用户实证：Fizgig 停在第 10/1024 步（引擎每个 epoch 才写一次快照，
    第一个存档点在第 64 步）—— 一个快照都没有，却被**两处**无条件告知
    「进度快照已保留，下次可断点续训」；用户跑去续训发现没有，非常着急。

    注意：这是「承诺与事实不符」，**不是续训机制本身的缺陷** ——
    机制（步数映射 / 旧成品误吞 / 看门狗误杀 / --resume 接线）此前已修过多版且都是对的，
    但没能碰到用户真正的痛点。本测试守住「别再说做不到的承诺」。
    """
    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8")
    # 1) 旧的无条件承诺必须消失
    assert "进度快照已保留，下次可断点续训" not in g, "仍残留无条件承诺（日志/确认框）"
    assert "训练中断后进度快照会保留" not in g, "悬停提示仍无条件承诺"
    # 2) 快照查找必须是唯一口径：_ask_resume 与停止提示共用 _latest_resume_state
    assert "def _latest_resume_state(self, params):" in g, "缺统一快照查找"
    i = g.find("def _ask_resume(self, params):")
    assert i != -1, "_ask_resume 缺失"
    assert "_latest_resume_state(params)" in g[i:i + 600], "_ask_resume 未走统一口径"
    # 3) 停止分支按「是否真有快照」分流，并给出补救指引
    # 注意：文件里有多个 `except core.StopRequested:`（预处理也有一个），
    # 用 find 会命中错的那个 —— 所以直接拿「本次无快照」这句文案锚定训练停止分支。
    j = g.find("没有产生可续训的快照")
    assert j != -1, "没找到「本次无快照」的如实告知"
    seg = g[max(0, j - 1600):j + 900]
    assert "_latest_resume_state(params)" in seg, "停止分支未检查快照是否存在"
    assert "没有产生可续训的快照" in seg, "缺「本次无快照」的如实告知"
    assert "第一个存档点" in seg, "缺原因说明"
    assert "_steps_per_state" in seg and "还差 {_left} 步" in seg, "缺「还差多少步到存档点」引导"
    # 4) 停止确认框要提前说明限制，别等停了才发现
    k = g.find("确定要停止当前任务吗？")
    assert k != -1, "没找到停止确认框"
    assert "没到第一个存档点就停" in g[k:k + 400], "确认框未提前说明存档点限制"
    print("RESUME_PROMISE_TRUTHFUL_OK")
def test_stuck_100_watchdog(base: Path):
    """100% 卡住自动停止：进程还活着且无新步数超时 → stop_active_process。"""
    import time as _time
    clock = {"t": 1000.0}

    def fake_time():
        return clock["t"]

    class FakeMon:
        def __init__(self):
            self.n = 0
        def snapshot(self):
            if self.n < 2:
                self.n += 1
                return {"running": True, "phase": "train", "total": 100, "step": 50}
            return {"running": True, "phase": "train", "total": 100, "step": 100}

    mon = FakeMon()
    state = {"stopped": False}
    logs = []

    def fake_pids():
        return {123}          # 进程还活着（卡住）
    def fake_stop():
        state["stopped"] = True
    def fake_sleep(sec):
        clock["t"] += sec

    with patch.object(core, "active_process_pids", side_effect=fake_pids), \
         patch.object(core, "stop_active_process", side_effect=fake_stop), \
         patch.object(core.time, "sleep", side_effect=fake_sleep), \
         patch.object(core.time, "time", side_effect=fake_time):
        core._start_train_stuck_watchdog(mon, logs.append, grace=150)
        for _ in range(400):
            if state["stopped"]:
                break
            _time.sleep(0.05)
    assert state["stopped"], "watchdog should have auto-stopped"
    assert any("自动停止" in x for x in logs)
    print("STUCK_100_WATCHDOG_OK")
def test_concept_mode(base: Path):
    """概念模式（形态/种族）：预处理映射 + 训练目录 + 推理模板 + 采样提示词。"""
    # 预处理映射：concept → character（保留全部标签）
    assert core.preprocess_mode("concept", None) == "character"
    assert core.preprocess_mode("krea2", "concept") == "character"
    assert core.preprocess_mode("krea2", "style") == "style"
    # 训练目录：concept 走 train_character
    assert "train_character" in core.dataset_train_dir("concept", "proj_x").replace("\\", "/")
    # 触发词提示
    assert hasattr(core, "TRIGGER_HINT_CONCEPT")
    # 推理模板 concept 分支（trigger + 形态模板，不落画风模板）
    import tempfile as _tf
    out = _tf.mkdtemp()
    tpl = core.write_usage_template("concept", {"trigger": "my_mer_01", "base_type": "sdxl"}, "concept_test", out_dir=out)
    txt = open(tpl, encoding="utf-8").read()
    assert "概念（形态/种族）LoRA 使用模板" in txt and "my_mer_01" in txt
    # 采样提示词 concept 分支：trigger + 不带 portrait（避免偏向半身人脸）
    sp = core._write_sample_prompts("concept_test", {"trigger": "my_mer_01", "sample_preview": True}, "concept", resolution=1024)
    assert sp and "my_mer_01" in open(sp, encoding="utf-8").read()
    assert "portrait" not in open(sp, encoding="utf-8").read()
    print("CONCEPT_MODE_OK")

def test_official_source_option(base: Path):
    """下载太慢切官方源：设置开关持久化 + torch 轮子/GitHub 引擎源码/HuggingFace 底模接线（需代理）。"""
    src = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8-sig")
    assert "def _official_source_preferred" in src, "缺官方源设置读取函数"
    assert "download_official_first" in src, "缺设置键 download_official_first"
    assert "download.pytorch.org/whl" in src, "缺 PyTorch 官方轮子源"
    assert "https://github.com/" in src, "缺 GitHub 引擎源码源"
    gsrc = (ROOT / "kohya_gui.py").read_text(encoding="utf-8-sig")
    assert "⑥ 下载源" in gsrc and "download_official_first" in gsrc, "GUI 缺下载源开关"
    assert "https://huggingface.co/" in gsrc, "GUI 缺 HuggingFace 直连"
    assert "_download_qwen3_from_modelscope" in src, "缺 Qwen3 魔搭兜底函数"
    assert "modelscope.cn/models/Qwen/Qwen3-0.6B" in src, "缺 Qwen3 魔搭直链"
    # v0.15.11 后下载策略反转为「魔搭直链优先、hf-mirror 仅兜底」，文案随之改动；
    # 断言跟着改为匹配当前实现（原断言 "自动切换魔搭" 已过期，会中断整个测试套件）。
    #
    # 2026-09-16 再改一次措辞：这是**换源重试**、结果还没定，用「失败」会让用户以为
    # 整体失败了（用户原话：「也不知道到底成功还是失败，下载倒是有进行」）。
    assert "自动换 hf-mirror 重试" in src, "缺魔搭→hf-mirror 切换（魔搭优先、hf-mirror 兜底）"
    assert "[Anima] ✓ 文本编码器已就绪" in src, "下载完成后没有明确结论（用户无法判断成败）"
    print("OFFICIAL_SOURCE_OPTION_OK")


def test_modelscope_ptw_preferred(base: Path):
    """PyTorch 大轮子下载源：上海交大优先、阿里云末位兜底，且下载前按实测吞吐重排。"""
    src = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8-sig")
    assert "MODELSCOPE_PTW_MIRROR" in src, "缺魔搭轮子缓存常量"
    assert "download.pytorch.org/whl" in src, "缺官方源（PyTorch 官方，需代理）"
    assert 'modelscope.cn/models/FGtiancai/Kohya-LoRA-Tool/resolve/master/engine_sources/pytorch_wheels/' in src
    # 2026-09-11：源顺序改为「上海交大优先、阿里云末位」，并在下载前按实测吞吐重排
    # （同一文件实测：上海交大 2.37 / 魔搭 2.25 / 官方直连 0.21 / 阿里云 0.12 MB/s）。
    i_sjtu = src.find("mirror.sjtu.edu.cn/pytorch-wheels")
    i_mota = src.find("MODELSCOPE_PTW_MIRROR,")
    i_ali = src.find("mirrors.aliyun.com/pytorch-wheels")
    assert 0 <= i_sjtu < i_mota < i_ali, "下载源顺序应为 上海交大→魔搭→阿里云(末位兜底)"
    assert "_order_bases_by_speed" in src, "缺「下载前实测测速选源」"
    assert "PIP_INDEX_PRIMARY" in src, "缺国内 PyPI 主源常量（中科大）"
    print("MODELSCOPE_PTW_PREFERRED_OK")
def test_modal_dialogs_logged(base: Path):
    """训练前的阻塞弹窗必须先写日志 —— 否则用户看到的就是「卡死、没反应、也没报错」。

    2026-09-15 一位 4090 用户实证：导出日志停在「[OK] 可用图片 20 张」之后再无任何输出。
    实际是 _ask_fix_cpu_torch 弹了「检测到 CPU 版 PyTorch，是否重装 cu128」的确认框 ——
    而这些确认框**一行日志都不写**、又可能藏在主窗口后面，用户只能判断成卡死。

    守两件事：
      ① 统一入口 _modal 必须「先写日志、再弹窗」（顺序不能颠倒）；
      ② 训练流程里的确认函数不得再出现裸 messagebox（否则又回到不写日志的老问题）。
    """
    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8")
    # 1) 统一入口存在，且先写日志再弹窗
    i = g.find("def _modal(self")
    assert i != -1, "缺少统一弹窗入口 _modal"
    seg = g[i:i + 2200]
    assert "_log(" in seg, "_modal 没有写日志"
    assert seg.find("_log(") < seg.find("messagebox."), "_modal 必须先写日志再弹窗"
    # 2) 训练流程里的确认函数，不得再出现裸 messagebox
    for fn in ("def _ask_fix_cpu_torch(self", "def _warn_no_nvidia(self", "def _warn_low_vram(self",
               "def _ask_resume(self", "def _anima_merged_ok(self", "def _confirm_training(self",
               "def _handle_auto_confirm(self"):
        j = g.find(fn)
        assert j != -1, "找不到 %s" % fn
        k = g.find("\n    def ", j + 1)
        body = g[j:] if k < 0 else g[j:k]
        for bad in ("messagebox.askyesno", "messagebox.askokcancel", "messagebox.showwarning"):
            assert bad not in body, "%s 里还有裸 %s —— 弹窗前不写日志，用户会以为卡死" % (fn, bad)
    # 3) 日志要有可检索前缀：支持时一眼看出「不是卡死，是在等我点确认」
    assert "弹窗等待你操作" in g, "弹窗日志缺少可检索前缀"
    print("MODAL_DIALOGS_LOGGED_OK")


def test_multiselect_click_toggle(base: Path):
    """「多选模式」必须真正做到「点一下即切换」，且保留滑动选择。

    2026-09-16 用户反馈「多选按钮不是很顺手」——上一版只把 selectmode 换成 extended，
    而 **extended 本来就要求按 Ctrl**，所以开关打开后仍然得按 Ctrl，等于没生效
    （当时又按要求去掉了说明文字，这个"没生效"就一直没被发现）。

    实测四种 selectmode 的真实行为（Tk 原生互斥，2026-09-16）：
        browse / single : 单击即替换选择，多选不了
        multiple        : 单击即切换 ✓ 但**拖拽只选中起始那一行**，没有滑动选择 ✗
        extended        : 拖拽连续 ✓ 但**单击替换选择**（需 Ctrl）✗
    → 结论：必须自己接管鼠标事件（`_attach_multiselect`）。
    """
    g = (ROOT / "kohya_gui.py").read_text(encoding="utf-8")
    i = g.find("def _attach_multiselect(self")
    assert i != -1, "缺少自实现的多选逻辑 _attach_multiselect"
    seg = g[i:i + 3200]
    # 1) 三处鼠标事件都要接管
    for ev in ('"<ButtonPress-1>"', '"<B1-Motion>"', '"<ButtonRelease-1>"'):
        assert ("lb.bind(%s" % ev) in seg, "未接管 %s" % ev
    # 2) 三个关键实现点（少一个行为就不对）
    assert 'st["base"] = set(lb.curselection())' in seg, "按下时未记录按下前的选中集"
    assert 'st["base"] | set(range(lo, hi + 1))' in seg, "拖动未做区间叠加（滑动选择）"
    assert 'st["base"] ^ {st["anchor"]}' in seg, "未拖动时未切换该行（等价 Ctrl+单击）"
    assert 'return "break"' in seg, "未挡掉原生「替换选择」，单击仍会清掉已选项"
    # 3) 两个列表都要挂上（图片列表 + 标签统计窗）
    assert g.count("self._attach_multiselect(") >= 2, "没有同时挂到图片列表与标签统计窗"
    assert "self._attach_multiselect(self.listbox, on_change=self._on_select)" in g, \
        "图片列表未挂自实现多选"
    print("MULTISELECT_CLICK_TOGGLE_OK")


def test_vpred_base_parameterization(base: Path):
    """v-prediction 底模必须自动加 --v_parameterization，否则采样预览是纯噪点。

    2026-09-15 用户实证：底模 noobaiXLNAIXL_vPred10Version（v-pred 版），工具没传
    --v_parameterization → sd-scripts 按 epsilon 训练+采样。训练 loss 看着仍然正常
    （avr_loss=0.0965，最迷惑人），但预览图全是噪点。

    关键点：v-pred 与 eps 的**模型结构完全相同**，detect_base_type 靠架构键分类
    认不出来，只能按文件名判断 —— 所以这个测试同时守住「识别函数」和「接线」两处。
    """
    # 1) 识别函数：各种写法都要认，且不能误伤 eps / 普通模型
    assert core._looks_like_vpred("noobaiXLNAIXL_vPred10Version.safetensors"), "未识别 vPred（驼峰）"
    assert core._looks_like_vpred("my_model-v-pred.safetensors"), "未识别 v-pred（连字符）"
    assert core._looks_like_vpred("G:/models/sd_xl_vpred.safetensors"), "未识别 vpred（全小写 + 路径）"
    assert core._looks_like_vpred("foo_v_prediction.safetensors"), "未识别 v_prediction"
    assert not core._looks_like_vpred("noobaiXLNAIXL_epsilonPred11Version.safetensors"), "eps 版被误判为 v-pred"
    assert not core._looks_like_vpred("novaAnimeXL_ilV30HappyNewYear.safetensors"), "普通模型被误判"
    assert not core._looks_like_vpred(""), "空路径应为 False"
    assert not core._looks_like_vpred(None), "None 应为 False"
    # 2) 接线：train() 的 family == "sd" 分支必须加 --v_parameterization
    k = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8-sig")
    i = k.find('    if family == "sd":\n        cmd += [f"--unet_lr={unet_lr}"')
    assert i != -1, "找不到 train() 的 sd 分支"
    seg = k[i:i + 800]
    assert "_looks_like_vpred(base_model)" in seg, "sd 分支未判断 v-pred"
    assert '"--v_parameterization"' in seg, "sd 分支未加 --v_parameterization"
    # 3) 采样提示词：第一引擎也要写 --w/--h（不写会按 512 出图，1024 训练的图又小又糊）
    j = k.find("def _write_sample_prompts(")
    assert j != -1, "找不到 _write_sample_prompts"
    body = k[j:j + 3000]
    assert "elif resolution:" in body, "第一引擎采样提示词未写分辨率"
    print("VPRED_PARAMETERIZATION_OK")


def test_run_stream_pipe_held_by_grandchild(base: Path):
    """子进程退出、但孙进程仍持有 stdout 管道时，run_stream 必须立即返回。

    2026-09-16 qiansui 用户实测：下载训练内核**每次都在最后卡住** —— 活其实早就干完
    （手动结束任务后重点一次，工具检测完直接说「已安装」），但任务一直不结束。

    根因：Windows 上子进程的 stdout 管道句柄会被**孙进程**继承
    （git clone 的 git-remote-https、pip 的构建子进程、杀软扫描进程等）；
    只要还有孙进程握着它，管道就永不 EOF。旧实现 `for line in proc.stdout` 会
    **永久阻塞** → 任务永不结束 → 用户只能手动结束（一次不受控中断，
    半装的 venv / 半下的 wheel 都可能留下隐患）。

    这里直接复现该场景：子进程先拉起一个继承 stdout 的孙进程（睡很久），
    然后自己立刻退出。旧实现会一直等孙进程；新实现以「进程已退出」为判据，应立即返回。
    """
    import time as _t
    child = base / "pipe_grandchild.py"
    child.write_text(
        "import subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "print('CHILD_DONE', flush=True)\n"
        "sys.exit(0)\n",
        encoding="utf-8")
    got = []
    _t0 = _t.time()
    rc = core.run_stream([sys.executable, "-u", str(child)],
                         logf=got.append, env=dict(os.environ))
    _dt = _t.time() - _t0
    blob = "\n".join(got)
    assert rc == 0, (rc, blob[-400:])
    # 崩溃前/退出前的输出必须照样收到（不能为了不卡住而丢日志）
    assert "CHILD_DONE" in blob, "没收到子进程输出：%s" % blob[-400:]
    assert _dt < 10, ("子进程已退出却被孙进程拖住 %.1fs —— 仍在等管道 EOF" % _dt)
    # 高频输出下父进程吞吐不能退化成「等待与打日志串行」。
    # 2026-09-17 实测：主循环每轮固定 sleep(0.15) 时，父进程总耗时 4.01s，而边读边打的
    # 旧实现只要 1.86s ✗（子进程不受影响 ✓ 但界面日志会积压、进度看着卡 ✗）。
    # 这里只做**结构性**断言（计时断言会飘 ✗）：必须存在「有积压就不睡」的实现。
    _u = (ROOT / "kohya_core" / "utils.py").read_text(encoding="utf-8")
    assert "def _drain_counted()" in _u, "缺少带计数的排空（无法判断是否有积压）"
    assert "_last_drained" in _u and "if not _last_drained:" in _u, \
        "主循环又变成每轮无条件 sleep —— 高频输出下吞吐会掉一半"
    print("RUN_STREAM_NO_PIPE_HANG_OK")


def test_wd14_dep_probe_real_import(base: Path):
    """WD14 依赖判据必须是「能否真的 import」，不能是 find_spec。

    2026-09-16 修正。旧 `_has_wd14_deps` 用 `importlib.util.find_spec` 只回答
    「包在不在」，而 onnxruntime 最要命的故障形态恰恰是**「找得到、import 就死」**
    → 被判为「已就绪」→ `_ensure_onnx` 的自动补装**永远不触发**，自愈形同虚设。

    实测（2026-09-16 qiansui 用户）：onnxruntime 装了但 import 即崩（0xC0000005、
    零输出），工具判「健康」→ 不修 → 只剩日志里一句要用户手打的 pip 命令 →
    用户看不懂，去问另一个 AI，在 cpu/gpu 变体之间折腾几小时，
    **而最后修好的动作正好就是工具原本给的那条**。

    注：这里用**纯函数分类**做断言（照 `_classify_ort_probe` 的现成范式）。
    本想用「假模块 + PYTHONPATH」造真实崩溃场景，但实测本机 **PYTHONPATH 传不进
    子进程**（子进程 sys.path 里根本没有它）—— 代码库也早就写明「不依赖 PYTHONPATH
    传递，环境变量在某些宿主里不保证生效」。分类函数的输入正是 native 崩溃的真实形状。
    """
    import preprocess as P

    # ① 零输出 + 非零退出（native 崩溃的真实形状，3221225477 = 0xC0000005）
    #    → 必须判 crash，**绝不能判 missing**（这是本次修复的核心）
    ok, kind, why = P._classify_wd14_probe(3221225477, "")
    assert ok is False and kind == "crash", (ok, kind, why)
    assert "崩溃" in why, why

    # ② 真没装 → missing（与"崩"必须分开：一个要装、一个要清干净重装）
    ok2, kind2, why2 = P._classify_wd14_probe(
        1, "Traceback (most recent call last):\nModuleNotFoundError: No module named 'onnxruntime'")
    assert ok2 is False and kind2 == "missing", (ok2, kind2, why2)
    assert "未安装" in why2, why2

    # ③ DLL 装载失败（有输出但非"没装"）→ error，不能误判成 missing
    _ok3, kind3, why3 = P._classify_wd14_probe(
        1, "ImportError: DLL load failed while importing onnxruntime_pybind11_state")
    assert kind3 == "error", (kind3, why3)

    # ④ 正常 → ok
    ok4, kind4, _w4 = P._classify_wd14_probe(0, "WD14_DEPS_OK 2.7.0+cu128 1.20.0")
    assert ok4 is True and kind4 == "ok", (ok4, kind4)

    # ⑤ 端到端存活：对真实解释器探测必须返回四类之一且不抛异常
    _ok5, kind5, _w5 = P._probe_wd14_deps(sys.executable)
    assert kind5 in ("ok", "missing", "crash", "error"), (kind5, _w5)

    # ⑥ 源码断言：不能再用 find_spec 当 WD14 的可用性判据
    #    （只看该函数体本身；`find_spec(` 带括号 = 真的在调用，docstring 里提名字不算）
    _src = (ROOT / "preprocess.py").read_text(encoding="utf-8")
    _k = _src.index("def _has_wd14_deps(")
    _body = _src[_k:_src.index("\ndef ", _k + 10)]
    assert "find_spec(" not in _body, "_has_wd14_deps 又改回 find_spec 了（会把坏环境判成健康）"
    assert "_probe_wd14_deps(py)[0]" in _body, _body[:220]

    # ⑦ 崩溃路径必须触发「清干净重装」，不能只是再装一次
    _enc = _src.index("def _ensure_onnx(")
    _ebody = _src[_enc:_enc + 1500]
    assert 'clean=True' in _ebody, "_ensure_onnx 在崩溃路径未走清干净重装"
    assert '"crash"' in _ebody, "_ensure_onnx 未区分崩溃与未安装"
    print("WD14_DEP_PROBE_REAL_IMPORT_OK")


def test_wd14_onnx_clean_reinstall(base: Path):
    """「装了但导入就崩」必须走「清干净重装」，而不是 `--force-reinstall`。

    2026-09-16 修正：onnxruntime / onnxruntime-gpu / onnxruntime-directml 三个包
    装进**同一个 `onnxruntime` 模块目录**；`--force-reinstall onnxruntime` 只覆盖
    自己这个包的文件，别的变体遗留在 capi/ 里的旧 DLL 不会被清掉 → import 继续崩。
    实测（qiansui 用户）：他在 cpu / gpu 变体之间来回装了三次才碰对。
    """
    import preprocess as P
    calls = []

    def fake_run(cmd, **kw):
        calls.append(" ".join(str(x) for x in cmd))
        out = str(base) if "getsitepackages" in " ".join(str(x) for x in cmd) else ""
        return subprocess.CompletedProcess([], 0, out, "")

    # clean=True：卸掉全部变体 + 只装 CPU 版
    with patch.object(P.subprocess, "run", side_effect=fake_run), \
         patch.object(P, "_probe_wd14_deps", return_value=(True, "ok", "ORT 1.2")):
        assert P._pip_install_onnx(sys.executable, lambda _s: None, clean=True) is True
    for _v in ("onnxruntime-gpu", "onnxruntime-directml"):
        assert any(("uninstall" in c and _v in c) for c in calls), \
            "未卸载变体 %s（只卸一个清不干净）：%s" % (_v, calls)
    _inst = [c for c in calls if " install " in (" " + c + " ")]
    assert _inst, calls
    assert not any(("onnxruntime-gpu" in c or "directml" in c) for c in _inst), \
        "仍在安装 gpu/directml 变体（会引入额外崩点）：%s" % _inst

    # clean=False（单纯缺包）：不该去卸，免得白折腾
    calls.clear()
    with patch.object(P.subprocess, "run", side_effect=fake_run), \
         patch.object(P, "_probe_wd14_deps", return_value=(True, "ok", "")):
        P._pip_install_onnx(sys.executable, lambda _s: None, clean=False)
    assert not any("uninstall" in c for c in calls), calls
    print("WD14_ONNX_CLEAN_REINSTALL_OK")


def test_manual_lock_tags_to_prefix(base: Path):
    """标签统计里「把高覆盖标签锁进固定前缀」：写入 ||| 后强绑定必须真的锁定它。

    2026-09-16 用户场景：某角色特征覆盖率 20/21（95%，差的那 1 张多半是色差/漏标），
    够不着强绑定的 **100%** 门槛 → 自动锁定拿不到它 → 单写 trigger 唤不出角色
    （他实测：手动补上 green hair 就"非常像"了）。
    解法：在「标签统计」里手动把它锁进固定前缀（写 `|||`）。

    这里验证**与 preprocess.apply_strong_binding 的完整往返**：写 → 消费 → keep_tokens。
    只验证"写进去了"是不够的 —— 真正的契约是预处理能把 `|||` 变成固定前缀。
    """
    import preprocess as pp
    td = base / "manual_lock"
    td.mkdir(parents=True, exist_ok=True)
    caps = {
        "a": "qiansui321, long hair, green hair, 1girl, solo, smile",
        "b": "qiansui321, long hair, green hair, 1girl, solo, hat",
        "c": "qiansui321, long hair, 1girl, solo",      # 这张没有 green hair → 就是 20/21 的那 1 张
    }
    for _stem, _c in caps.items():
        (td / (_stem + ".txt")).write_text(_c, encoding="utf-8")
        # list_dataset_images 以图片为驱动：没有配对图片的 txt 根本不会被列出
        (td / (_stem + ".png")).write_bytes(b"x")

    snap = {}
    files, locked = core.lock_tags_to_prefix(str(td), ["green hair", "witch hat"],
                                             trigger="qiansui321", snapshot=snap)
    assert files == 3, (files, locked)
    assert locked == ["green hair", "witch hat"], locked
    for _stem in caps:
        _s = (td / (_stem + ".txt")).read_text(encoding="utf-8")
        assert "|||" in _s, _s
        assert _s.startswith("qiansui321, green hair, witch hat ||| "), _s
    # 撤销快照必须记下原文（可整批还原）
    assert set(snap) == {str(td / (_s + ".txt")) for _s in caps}, snap

    # 幂等：再锁一次不该产生任何写入
    assert core.lock_tags_to_prefix(str(td), ["green hair"], trigger="qiansui321")[0] == 0

    # ★ 真正的契约：preprocess 的强绑定必须消费 `|||`
    #   keep_tokens = 前缀词数（qiansui321 + green hair + witch hat = 3），且 `|||` 消失
    kt, _warns = pp.apply_strong_binding(str(td), "qiansui321", lambda *_a: None)
    assert kt == 3, ("强绑定没有把手动固定区算进 keep_tokens", kt)
    for _stem in caps:
        _s = (td / (_stem + ".txt")).read_text(encoding="utf-8")
        assert "|||" not in _s, ("||| 未被消费", _s)
        assert _s.startswith("qiansui321, green hair, witch hat"), _s
    print("MANUAL_LOCK_TAGS_TO_PREFIX_OK")


def main():
    # 每条用例独立 try/except：任何一条失败（常见于「实现改了、断言没跟着改」）都不再中断整个套件。
    # 否则后面几十条用例会被一条过期断言全部吞掉 —— v0.15.11~v0.16.5 就踩过：
    # test_official_source_option 的过期断言让套件从 2026-09-08 起一直卡在第 2597 行，
    # 其后所有用例（含 preprocess_deps / sample_preview / krea2_at_support）从未被执行。
    _failures = []

    def _wrap(_fn):
        def _inner(*a, **k):
            try:
                return _fn(*a, **k)
            except Exception as _e:
                _failures.append((_fn.__name__, repr(_e)))
                print("[FAIL] %s: %r" % (_fn.__name__, _e), flush=True)
        _inner.__name__ = _fn.__name__
        return _inner

    for _n in [k for k in list(globals()) if k.startswith("test_") and callable(globals()[k])]:
        globals()[_n] = _wrap(globals()[_n])

    with tempfile.TemporaryDirectory(prefix="kohya_engine_flow_") as td:
        base = Path(td)
        test_main_engine(base)
        test_kohya_coexist_with_other_engines(base)
        test_kohya_foreign_content_still_blocks(base)
        test_second_engine(base)
        test_second_engine_without_git(base)
        test_third_engine(base)
        test_third_engine_amd(base)
        test_third_engine_amd_torchvision_guard()
        test_amd_gpu_arch_mapping()
        # ★ 2026-09-23（AMD Radeon RX 7800 XT 事故）：装错架构的 ROCm 包 → 训练第一步卷积炸 ✗
        test_amd_arch_probe_not_polluted_by_hsa_override()
        test_amd_mirror_only_for_gfx1100()
        test_amd_device_pkg_and_override_checks()
        test_amd_gpu_kernel_check_detects_broken_gpu()
        test_fizgig_amd_preflight_blocks_early()
        test_fourth_engine(base)
        test_fourth_engine_train_pipeline(base)
        test_fizgig_deps_self_heal(base)
        test_resume_monitor_seed(base)
        test_resume_promise_is_truthful(base)
        test_stuck_100_watchdog(base)
        test_concept_mode(base)
        test_modelscope_ptw_preferred(base)
        test_official_source_option(base)
        test_optimizer_resolution(base)
        test_preprocess_deps(base)
        test_fizgig_krea2_saves_state(base)
        test_torch_import_hints_split_1114_vs_126(base)
        test_fizgig_skip_reason_logged(base)
        test_h3_amd_blocked_by_hardware()
        test_preinstall_torch_mirror_fallback(base)
        test_preinstall_torch_force_reinstall_on_import_failure(base)
        test_tokenizer_cache(base)
        test_preprocess_auto_retry(base)
        test_preprocess_crop_ratio(base)
        test_preprocess_mode_mapping(base)
        test_alloc_conf_expandable_stripped(base)
        test_run_stream_pipe_held_by_grandchild(base)
        test_wd14_dep_probe_real_import(base)
        test_wd14_onnx_clean_reinstall(base)
        test_manual_lock_tags_to_prefix(base)
        test_nvidia_smi_driver_safe(base)
        test_gui_resource_guard(base)
        test_tools_module(base)
        test_next_features(base)
        test_external_python_safe_cwd(base)
        test_amd_download_progress(base)
        test_amd_torch_verification(base)
        test_accelerate_module_launcher(base)
        test_main_engine_accel_always_defined(base)
        test_quant_mode_resolution(base)
        test_swap_tier_resolution(base)
        test_igpu_filter(base)
        test_low_ram_swap(base)
        test_flux2_first_engine_guard(base)
        test_prequantized_krea2_raw_detected(base)
        test_train_monitor_krea2_parsing(base)
        test_modelscope_mirror_urls(base)
        test_safetensors_complete_check(base)
        test_at_image_ms_parse_skips_dirs(base)
        test_preset_for_fallback(base)
        test_sample_preview_16g_default_off(base)
        test_musubi_quant_patch(base)
        test_musubi_offload_device_patch(base)
        test_accelerate_cpu_config_self_heal(base)
        test_anima_vae_fp32_patch(base)
        test_dataset_config_is_reg_subset(base)
        test_diagnose_optimizer_failure_scenarios(base)
        test_anima_rdna2_no_half_vae(base)
        test_h3_vram_adapt(base)
        test_h3_resolution_frames(base)
        test_video_caption_args(base)
        test_preprocess_python_fallback(base)
        test_h3_integrity_and_nvfp4_required(base)
        test_video_preprocess_no_auto_train(base)
        test_build_env_utf8_output(base)
        test_build_env_unbuffered_output(base)
        test_preprocess_silent_failure_diagnosed(base)
        test_wd14_onnx_isolated(base)
        test_probe_onnxruntime_import(base)
        test_fizgig_preview_swap(base)
        test_fizgig_sample_off_warned(base)
        test_modal_dialogs_logged(base)
        test_vpred_base_parameterization(base)
        test_multiselect_click_toggle(base)
        test_preprocess_skip_is_visible(base)
        test_krea2_style_subdir_consistency(base)
        test_project_open_robust(base)
        test_run_stream_default_utf8(base)
        test_musubi_int8_weight_dtype_patch(base)
        test_prequantized_base_detect(base)
        test_strong_binding(base)
        test_at_image_model_ready_local(base)
        test_at_image_pre_download(base)
        test_qwen21_processor_cache(base)
        test_ai_toolkit_engine_update(base)
        test_qwen21_reuses_comfy_components(base)
        test_wd14_triton_noise_collapse(base)
        test_musubi_version_check(base)
        test_quarantine_input_corrupt(base)
        test_flux2_qwen3_06b_hint(base)
        test_sample_preview(base)
        test_gated_download_guidance(base)
        test_krea2_modelscope_mirror(base)
        test_krea2_training_env_propagation(base)
        test_export_log(base)
        test_venv_hf_sitecustomize(base)
        test_torch_compile_safe_fallback(base)
        test_swap_zero_option(base)
        test_at_image_low_vram_vram_aware(base)
        test_third_engine_triton_and_laptop_warning(base)
        test_krea2_first_engine_guard(base)
        test_at_train_driver_guard(base)
        test_krea2_at_truncated_te_self_heal(base)
        test_krea2_at_start_oom_retry(base)
        test_config_export_import(base)
        test_tokenizer_failure_self_heal(base)
        test_cpu_device_probe_warning(base)
        test_krea2_at_support(base)
        test_musubi_dataset_precheck(base)
    if _failures:
        print("=" * 64)
        print("ENGINE_CONTROL_FLOW_FAILURES: %d 条失败" % len(_failures))
        for _n, _e in _failures:
            print("  · %s: %s" % (_n, _e))
        raise SystemExit(1)
    print("ALL_ENGINE_CONTROL_FLOW_TESTS_OK")

def test_cpu_device_probe_warning(base: Path):
    """训练前始终探测加速设备：CPU 版 torch/坏 ROCm 命中 device: cpu 时醒目警告（防全程 CPU 傻跑）。"""
    src = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8")
    assert "_probe_accelerate_device(vpy, logf)" in src, "缺设备探测调用"
    assert "探测不到 GPU" in src and "device: cpu" in src, "缺 CPU 警告文案"
    assert "def _probe_accelerate_device" in src, "缺探测函数"
    print("CPU_DEVICE_PROBE_WARNING_OK")

def test_tokenizer_failure_self_heal(base: Path):
    """tokenizer 缓存损坏自愈：失败判定命中、_complete_dir 拒绝 0 字节、train() 已接线强制重建重试。"""
    assert core._log_mentions_tokenizer_failure(
        ["TypeError: expected str, bytes or os.PathLike object, not NoneType", "tokenization_clip.py", "vocab_file"]) is True
    assert core._log_mentions_tokenizer_failure(["spiece.model", "not NoneType"]) is True
    assert core._log_mentions_tokenizer_failure(["steps: 1/100, avr_loss=0.05"]) is False
    assert core._log_mentions_tokenizer_failure(["CUDA error: out of memory"]) is False
    src = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8")
    assert "os.path.getsize(_p) > 0" in src, "缺 0 字节拒绝"
    assert "强制重建分词器缓存后自动重试" in src, "缺失败重试接线"
    assert "def _force_rebuild_tokenizer_cache" in src, "缺强制重建函数"
    # SDXL 需要两个 tokenizer（tokenizer1=openai/clip-vit-large-patch14 + tokenizer2=laion）；
    # 漏配 tokenizer1 会导致自愈只重建 laion、vocab_file=None 重试仍崩（2026-09-01 4070S 用户 v0.14.0 日志）
    _sdxl_tk = [m for m, _k in core.ARCH_INFO.get("sdxl", {}).get("tokenizers", [])]
    assert "openai/clip-vit-large-patch14" in _sdxl_tk, "SDXL 缺 tokenizer1"
    assert "laion/CLIP-ViT-bigG-14-laion2B-39B-b160k" in _sdxl_tk, "SDXL 缺 tokenizer2"
    assert (ROOT / "installers" / "tokenizers" / "openai_clip-vit-large-patch14" / "vocab.json").is_file(), "内置 tokenizer1 缺失"
    print("TOKENIZER_FAILURE_SELF_HEAL_OK")

def test_config_export_import(base: Path):
    """配置导出/导入：默认排除提示词与本机路径、可选项保留、解析逐字段容错、底模只留文件名并可自动定位。"""
    import json as _json
    params = {
        "mode": "style", "base_type": "sdxl", "at_sub_mode": "画风（过滤人物标签）",
        "base_model": r"D:\models\anima-base-v1.0.safetensors",
        "rank": 16, "alpha": 8, "unet_lr": 1e-4, "te_lr": 5e-5, "repeats": 5,
        "max_epochs": 8, "resolution": 1024, "save_every": 200, "optimizer": "AdamW8bit",
        "quant_mode": "auto", "blocks_to_swap": "6", "strong_bind": True,
        "sample_preview": False, "crop_ratio": "3:4", "train_text_encoder": True,
        "trigger": "zzz", "style_caption": "水彩风", "raw_dir": r"D:\data", "train_env": r"D:\venv",
    }
    cfg = core.export_config_json(params)
    assert cfg["base_model"] == "anima-base-v1.0.safetensors", cfg
    assert cfg["at_sub_mode"] == "style", cfg
    assert "trigger" not in cfg and "style_caption" not in cfg and "raw_dir" not in cfg and "train_env" not in cfg, cfg
    cfg2 = core.export_config_json(params, include_prompts=True)
    assert cfg2.get("trigger") == "zzz" and cfg2.get("style_caption") == "水彩风", cfg2
    # 解析容错：未知模式回退、坏数值忽略、未知字段忽略、短标签画风识别、底模取文件名
    text = _json.dumps({"mode": "unknown_mode", "base_type": "nope", "at_sub_mode": "画风",
                        "base_model": "x/y/z.safetensors",
                        "params": {"rank": "abc", "unet_lr": "1e-4", "repeats": "5", "future_field": 1},
                        "trigger": "t1"})
    pcfg, summ = core.parse_config_json(text)
    assert pcfg["mode"] == "character" and pcfg["at_sub_mode"] == "style", pcfg
    assert "rank" not in pcfg["params"] and pcfg["params"]["unet_lr"] == 1e-4, pcfg
    assert pcfg["base_model"] == "z.safetensors" and pcfg["trigger"] == "t1", pcfg
    assert summ["ignored"] >= 3, summ  # mode/base_type/rank/future_field 被忽略
    # 底模自动定位：models/base 下同名文件能找全路径
    mdir = base / "models" / "base"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "anima-base-v1.0.safetensors").write_bytes(b"x")
    with patch.object(core, "data_sub", side_effect=lambda *pp: str(base.joinpath(*pp))):
        found = core.find_model_by_filename("anima-base-v1.0.safetensors", "style")
    assert found and str(found).replace("\\", "/").endswith("anima-base-v1.0.safetensors"), found
    assert core.find_model_by_filename("", None) is None
    print("CONFIG_EXPORT_IMPORT_OK")

def test_krea2_at_start_oom_retry(base: Path):
    """Krea2AT 16G 启动 OOM 自动重试判定：启动 OOM 命中、中途 OOM/正常不命中；16G yaml 保持 0.3 保速度。"""
    assert core._log_mentions_start_oom(["Error running job: CUDA error: out of memory"]) is True
    assert core._log_mentions_start_oom(["Traceback", "cudaErrorMemoryAllocation"]) is True
    assert core._log_mentions_start_oom(["steps: 5/464 [00:10<10:00, 0.5s/it, avr_loss=0.07]", "CUDA error: out of memory"]) is False
    assert core._log_mentions_start_oom(["Loading transformer", "Moving transformer to CPU"]) is False
    src = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8")
    assert "force_offload" in src and "else 0.3" in src, "16G 默认保持 0.3 保速度，支持兜底加大"
    assert "自动重试（" in src and "最后兜底" in src, "缺启动 OOM 多次自动重试 + 加大分层交换兜底"
    # force_offload=0.5 时 yaml 应写出 0.5（16G 最后兜底）
    _td = base / "at_oom_yaml"
    _td.mkdir(parents=True, exist_ok=True)
    with patch.object(core, "krea2_model_files", return_value={"raw": str(base / "raw.safetensors")}), \
         patch.object(core, "krea2_at_te_dir", return_value=str(_td)), \
         patch.object(core, "krea2_at_vae_dir", return_value=str(_td)), \
         patch.object(core, "dataset_train_dir", return_value=str(base)), \
         patch.object(core, "count_images", return_value=5):
        _cfg = str(_td / "t.yaml")
        core.write_krea2_at_yaml({"project": "p", "rank": "32", "alpha": "32"}, str(base), str(_td), _cfg, vram_gb=16, force_offload=0.5)
        _y = open(_cfg, encoding="utf-8").read()
        assert "layer_offloading_transformer_percent: 0.5" in _y, _y
    print("KREA2_AT_START_OOM_RETRY_OK")

def test_krea2_at_truncated_te_self_heal(base: Path):
    """Krea2AT 文本编码器：截断 safetensors 分片能被识别（>1MB 但头部声明超文件大小），下载时自动删除重下。"""
    import struct
    import json as _json
    td = base / "krea2_at_te"
    td.mkdir(parents=True, exist_ok=True)
    (td / "config.json").write_text("{}", encoding="utf-8")
    (td / "tokenizer.json").write_text("{}", encoding="utf-8")
    idx = {"weight_map": {"a": "model-00001-of-00002.safetensors", "b": "model-00002-of-00002.safetensors"}}
    (td / "model.safetensors.index.json").write_text(_json.dumps(idx), encoding="utf-8")
    # 截断分片：头部声明 100MB 数据，实际只有 2MB（>1MB，旧检查会误判为完整）
    hdr = {"t": {"dtype": "F32", "shape": [1], "data_offsets": [0, 100 * 1024 * 1024]}}
    hb = _json.dumps(hdr, separators=(",", ":")).encode("utf-8")
    shard1 = td / "model-00001-of-00002.safetensors"
    shard1.write_bytes(struct.pack("<Q", len(hb)) + hb + b"\x00" * (2 * 1024 * 1024))
    assert core._safetensors_complete(str(shard1)) is False, "截断分片应判为不完整"
    with patch.object(core, "krea2_at_te_dir", return_value=str(td)):
        assert core.krea2_at_text_encoder_ready() is False, "存在截断分片应判为未就绪"
        logs = []
        files = ["config.json", "tokenizer.json", "model.safetensors.index.json",
                 "model-00001-of-00002.safetensors", "model-00002-of-00002.safetensors"]
        def _dl(url, dest, logf, direct=False, **kw):
            hb2 = _json.dumps({"t": {"dtype": "F32", "shape": [4], "data_offsets": [0, 16]}},
                              separators=(",", ":")).encode("utf-8")
            with open(dest, "wb") as f:
                f.write(struct.pack("<Q", len(hb2)) + hb2 + b"\x00" * 16)
            return True
        with patch.object(core, "_at_image_ms_file_list", return_value=files), \
             patch.object(core, "_download_with_resume", side_effect=_dl):
            ok = core._krea2_at_download_te(logs.append)
        assert ok is True, logs
        assert core.krea2_at_text_encoder_ready() is True, "自愈后应就绪"
        assert core._safetensors_complete(str(shard1)) is True, "截断分片应被重下为完整"
        assert any("截断" in x for x in logs), logs
    print("KREA2_AT_TRUNCATED_TE_SELF_HEAL_OK")

def test_at_train_driver_guard(base: Path):
    """第三引擎训练前 NVIDIA 驱动预检：<570 拦截，>=570/未知放行（cu130 首次 CUDA 蓝屏护栏）。"""
    assert hasattr(core, "_check_at_train_driver"), "缺少 _check_at_train_driver"
    logs = []
    # <570 -> RuntimeError 拦截
    with patch.object(core, "nvidia_driver_version", return_value=550):
        try:
            core._check_at_train_driver(logs.append)
            raise AssertionError("550 应被拦截")
        except RuntimeError as e:
            assert "570" in str(e), str(e)
    # >=570 -> 放行并打印
    with patch.object(core, "nvidia_driver_version", return_value=572):
        core._check_at_train_driver(logs.append)
    assert any("572" in x for x in logs), logs
    # 检测失败(None) -> 放行不误伤
    with patch.object(core, "nvidia_driver_version", return_value=None):
        core._check_at_train_driver(logs.append)
    # 三个 ai-toolkit 训练入口都已接上护栏
    src = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8")
    for fn in ("def train_krea2_at", "def train_at_image", "def train_video"):
        i = src.find(fn)
        assert i >= 0, fn
        e = src.find("\ndef ", i + 10)
        seg = src[i:e if e >= 0 else len(src)]
        assert "_check_at_train_driver(logf)" in seg, fn + " 未接训练前驱动护栏"
    print("AT_TRAIN_DRIVER_GUARD_OK")

def test_krea2_at_support(base: Path):
    """第三引擎 Krea2（AI-Toolkit）接入：模型检测 / yaml 生成 / 训练控制流。"""
    # ---- 模型缺失提示：raw/vae 缺失时给国内直链 ----
    with patch.object(core, "krea2_model_files", return_value={"raw": None, "vae": None, "te": None, "turbo": None}):
        miss = core.krea2_at_missing_models()
        assert len(miss) >= 2 and "raw.safetensors" in miss[0] and "modelscope.cn" in miss[0]

    # ---- TE/VAE 本地目录完整性检测 ----
    local = base / "models" / "krea2_at"
    te = local / "te"
    vae = local / "vae" / "vae"
    (te).mkdir(parents=True, exist_ok=True)
    (vae).mkdir(parents=True, exist_ok=True)
    with patch.object(core, "data_sub", side_effect=lambda *pp: str(base.joinpath(*pp))):
        assert core.krea2_at_text_encoder_ready() is False   # 缺 config/tokenizer
        assert core.krea2_at_vae_ready() is False            # 缺 config/权重
        # 补全 TE（index + 分片）
        open(te / "config.json", "w", encoding="utf-8").write("{}")
        open(te / "tokenizer.json", "w", encoding="utf-8").write("{}")
        (te / "model.safetensors.index.json").write_text(
            '{"weight_map": {"a": "model-00001-of-00002.safetensors", "b": "model-00002-of-00002.safetensors"}}',
            encoding="utf-8")
        import struct as _st
        import json as _json
        def _mk_safe(pth):
            _h = {"t": {"dtype": "F32", "shape": [4], "data_offsets": [0, 16]}}
            _hb = _json.dumps(_h, separators=(",", ":")).encode("utf-8")
            pth.write_bytes(_st.pack("<Q", len(_hb)) + _hb + b"\x00" * 16)
        _mk_safe(te / "model-00001-of-00002.safetensors")
        _mk_safe(te / "model-00002-of-00002.safetensors")
        assert core.krea2_at_text_encoder_ready() is True
        # 补全 VAE
        open(vae / "config.json", "w", encoding="utf-8").write("{}")
        _mk_safe(vae / "diffusion_pytorch_model.safetensors")
        assert core.krea2_at_vae_ready() is True
        assert core.krea2_at_model_ready() is True
        # 半截：删一个 TE 分片 → 未就绪
        os.remove(te / "model-00002-of-00002.safetensors")
        assert core.krea2_at_text_encoder_ready() is False
        os.remove(te / "model-00001-of-00002.safetensors")
        # index 仍在但分片缺失 → 必须判未就绪（防下载中断残留误判）
        assert core.krea2_at_text_encoder_ready() is False
        # 走单文件回退：删掉 index，只留 model.safetensors
        os.remove(te / "model.safetensors.index.json")
        _mk_safe(te / "model.safetensors")
        assert core.krea2_at_text_encoder_ready() is True

    # ---- yaml 生成（16G / 24G 档）----
    train_dir = base / "train"
    train_dir.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (train_dir / ("i%d.png" % i)).write_bytes(b"x")
        (train_dir / ("i%d.txt" % i)).write_text("t, girl", encoding="utf-8")
    raw = base / "raw.safetensors"
    raw.write_bytes(b"x" * 1024)
    with patch.object(core, "data_sub", side_effect=lambda *pp: str(base.joinpath(*pp))), \
         patch.object(core, "krea2_model_files", return_value={"raw": str(raw), "vae": None, "te": None, "turbo": None}), \
         patch.object(core, "count_images", return_value=3):
        import yaml
        cfg = base / "krea2_at_16.yaml"
        core.write_krea2_at_yaml({"project": "p", "rank": 16, "alpha": 16, "unet_lr": 1e-4,
                                  "repeats": 2, "max_epochs": 3, "resolution": 1024,
                                  "sample_preview": False, "trigger": "t"}, str(train_dir), str(base), str(cfg), vram_gb=16)
        d = yaml.safe_load(open(cfg, encoding="utf-8"))
        proc = d["config"]["process"][0]
        assert proc["model"]["arch"] == "krea2"
        assert proc["model"]["qtype"] == "qint8"
        # 2026-09-08（a631a71）Krea2AT 16G 对齐回 0.13 快档配方：分辨率由 768 改为 512
        assert proc["datasets"][0]["resolution"] == [512, 512]      # 16G 压到 512
        assert proc["train"].get("disable_sampling") is True
        # sample 段现在是无条件写出（引擎缺该段时 cache_sample_prompts 会崩），
        # 关采样靠 disable_sampling 实现（smoke_test 里同样按「必须存在」断言）。
        assert "sample" in proc
        assert proc["model"]["low_vram"] is True
        assert "Qwen3-VL-4B-Instruct" in proc["model"]["model_kwargs"]["text_encoder_path"] or "te" in proc["model"]["model_kwargs"]["text_encoder_path"]
        cfg2 = base / "krea2_at_24.yaml"
        core.write_krea2_at_yaml({"project": "p", "rank": 16, "alpha": 16, "unet_lr": 1e-4,
                                  "repeats": 2, "max_epochs": 3, "resolution": 1024,
                                  "sample_preview": True, "trigger": "t"}, str(train_dir), str(base), str(cfg2), vram_gb=24)
        d2 = yaml.safe_load(open(cfg2, encoding="utf-8"))
        p2 = d2["config"]["process"][0]
        assert p2["model"]["qtype"] == "qfloat8"
        assert p2["datasets"][0]["resolution"] == [1024, 1024]
        assert p2["model"]["low_vram"] is False
        assert "sample" in p2

    # ---- train_krea2_at 控制流 ----
    vpy = str(base / "third" / "kohya_ss" / "ai_toolkit_venv" / "Scripts" / "python.exe")
    at_dir = str(base / "third" / "kohya_ss" / "ai-toolkit")
    os.makedirs(at_dir, exist_ok=True)
    open(os.path.join(at_dir, "run.py"), "w", encoding="utf-8").write("print('ok')\n")
    state = {"launched": None, "yaml_called": False}
    logs = []

    def fake_run_stream(cmd, cwd=None, env=None, logf=print, collect=None, **kwargs):
        state["launched"] = [str(x) for x in cmd]
        return 0

    def fake_yaml(params, train_dir, out_dir, cfg_path, vpy=None, logf=print, vram_gb=None):
        state["yaml_called"] = True
        return cfg_path

    def fake_latest(out_dir):
        return os.path.join(out_dir, "krea2_at_lora.safetensors")

    kwargs = {
        "data_sub": (lambda *pp: str(base.joinpath(*pp))),
        "get_kohya_dir": (lambda: str(base / "third" / "kohya_ss")),
        "ai_toolkit_engine_status": (lambda: (True, "ok", vpy)),
        "_at_dirs": (lambda: (vpy, at_dir)),
        "_ensure_venv_hf_sitecustomize": (lambda *a, **k: None),
        "_check_at_krea2_support": (lambda *a, **k: True),
        "_ensure_torchvision_deps": (lambda *a, **k: True),
        "_ensure_ai_toolkit_triton": (lambda *a, **k: True),
        "krea2_at_missing_models": (lambda: []),
        "krea2_model_files": (lambda: {"raw": str(raw), "vae": None, "te": None, "turbo": None}),
        "_safetensors_complete": (lambda *a, **k: True),
        "_safetensors_is_prequantized": (lambda *a, **k: False),
        "_ensure_krea2_at_models": (lambda *a, **k: (True, "")),
        "_warn_laptop_heavy_load": (lambda *a, **k: None),
        "detect_ram_gb": (lambda: 32),
        "_warn_low_ram": (lambda *a, **k: None),
        "dataset_train_dir": (lambda *a, **k: str(train_dir)),
        "count_images": (lambda *a, **k: 3),
        "write_krea2_at_yaml": fake_yaml,
        "build_direct_env": (lambda: {}),
        "run_stream": fake_run_stream,
        "_find_latest_safetensors": fake_latest,
        "_write_krea2_at_template": (lambda *a, **k: None),
        "write_params_report": (lambda *a, **k: None),
    }
    with patch.multiple(core, **kwargs):
        out = core.train_krea2_at(logf=logs.append, params={"project": "p", "at_sub_mode": "character",
                                                            "rank": 16, "alpha": 16, "unet_lr": 1e-4,
                                                            "repeats": 2, "max_epochs": 3, "trigger": ""},
                                  vram_gb=16)
        assert out and out.endswith("krea2_at_lora.safetensors")
        assert state["yaml_called"] is True
        assert state["launched"] and len(state["launched"]) >= 3 and state["launched"][1].endswith("run.py")
    print("KREA2_AT_SUPPORT_OK")


def test_musubi_dataset_precheck(base: Path):
    """musubi 训练前/缓存后校验：子文件夹、不支持扩展名、缺 .txt、缓存为空都要给明确报错，
    避免"缓存静默为空 → 训练 total batches: 0"的谜之失败。"""
    logs = []

    def fresh(name):
        d = base / "dataset" / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    # 1) 合法子集：a.png + a.txt，返回 1
    valid = fresh("valid")
    (valid / "a.png").write_bytes(b"x")
    (valid / "a.txt").write_text("1girl", encoding="utf-8")
    n = core._musubi_dataset_precheck(str(valid), "Krea2", logs.append)
    assert n == 1, n
    assert any("数据集校验通过" in x for x in logs)

    # 2) 缺 .txt 标签 → 明确报错
    missing = fresh("missing_cap")
    (missing / "b.png").write_bytes(b"x")
    try:
        core._musubi_dataset_precheck(str(missing), "Krea2", logs.append)
        raise AssertionError("missing caption should raise")
    except RuntimeError as e:
        assert ".txt" in str(e) and "b.png" in str(e), str(e)

    # 3) 只有子文件夹图片 → 报"子文件夹"
    only_sub = fresh("only_sub")
    (only_sub / "sub").mkdir(parents=True, exist_ok=True)
    (only_sub / "sub" / "x.png").write_bytes(b"x")
    (only_sub / "sub" / "x.txt").write_text("1girl", encoding="utf-8")
    try:
        core._musubi_dataset_precheck(str(only_sub), "Krea2", logs.append)
        raise AssertionError("subfolder should raise")
    except RuntimeError as e:
        assert "子文件夹" in str(e), str(e)

    # 4) 只有不支持扩展名 → 报"扩展名"
    only_gif = fresh("only_gif")
    (only_gif / "x.gif").write_bytes(b"x")
    (only_gif / "x.txt").write_text("1girl", encoding="utf-8")
    try:
        core._musubi_dataset_precheck(str(only_gif), "Krea2", logs.append)
        raise AssertionError("unsupported ext should raise")
    except RuntimeError as e:
        assert "扩展名" in str(e), str(e)

    # 5) 缓存校验：latents 为空 / te 缺失 / 通过
    cache = base / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    try:
        core._verify_musubi_cache(str(cache), "Krea2", logs.append, phase="latents")
        raise AssertionError("empty cache should raise")
    except RuntimeError as e:
        assert "latents 缓存为空" in str(e), str(e)
    (cache / "a_1024x1024_kr2.safetensors").write_bytes(b"x")
    core._verify_musubi_cache(str(cache), "Krea2", logs.append, phase="latents", expected=1)
    try:
        core._verify_musubi_cache(str(cache), "Krea2", logs.append, phase="te")
        raise AssertionError("missing te should raise")
    except RuntimeError as e:
        assert "文本编码器缓存为空" in str(e), str(e)
    (cache / "a_kr2_te.safetensors").write_bytes(b"x")
    core._verify_musubi_cache(str(cache), "Krea2", logs.append, phase="te", expected=1)
    print("MUSUBI_DATASET_PRE_CHECK_OK")

if __name__ == "__main__":
    main()

