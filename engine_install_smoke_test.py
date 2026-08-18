# -*- coding: utf-8 -*-
"""三引擎安装流程回归测试（不下载数 GB PyTorch，不修改真实训练环境）。

覆盖源码解压、venv 创建/损坏重建、pip 自愈调用、Torch 版本锁定、
依赖约束文件和最终验证分支。真实依赖导入仍由 smoke_test.py 与本机环境验证承担。
"""
from __future__ import annotations

import os
import subprocess
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
            assert "numpy==2.5.2" in req and "scipy==1.18.0" in req
            for wanted in ("torch==2.13.0", "torchvision==0.28.0", "torchaudio==2.11.0", "numpy==2.5.2", "scipy==1.18.0"):
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


def test_optimizer_resolution(base: Path):
    """resolve_optimizer / _probe_adamw8bit / _optimizer_yaml_name 单元测试（mock 子进程，不真实运行 CUDA）。"""
    logs = []
    vpy = str(base / "venv" / "Scripts" / "python.exe")

    def probe_result(out, rc):
        return subprocess.CompletedProcess([], rc, out, "")

    # 1) 预检通过 -> AdamW8bit
    with patch.object(core.subprocess, "run", return_value=probe_result("OK\n", 0)):
        opt, _ = core.resolve_optimizer(vpy, logs.append, requested="auto")
    assert opt == "AdamW8bit", opt

    # 2) 预检失败（DLL 缺失）+ lion 可用 -> Lion
    def subrun_fail(cmd, *args, **kwargs):
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "import lion_pytorch" in code:
            return probe_result("", 0)
        if "bitsandbytes" in code:
            return probe_result("Error: libbitsandbytes_cuda128.dll missing\n", 1)
        return probe_result("", 0)
    with patch.object(core.subprocess, "run", side_effect=subrun_fail):
        opt, _ = core.resolve_optimizer(vpy, logs.append, requested="auto")
    assert opt == "Lion", opt

    # 3) 预检失败 + lion 不可用 -> AdamW
    def subrun_no_lion(cmd, *args, **kwargs):
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "import lion_pytorch" in code:
            return probe_result("", 1)
        if "bitsandbytes" in code:
            return probe_result("str2optimizer8bit_blockwise is not defined\n", 1)
        return probe_result("", 0)
    with patch.object(core.subprocess, "run", side_effect=subrun_no_lion):
        opt, _ = core.resolve_optimizer(vpy, logs.append, requested="auto")
    assert opt == "AdamW", opt

    # 4) AMD 模式固定 AdamW（不调用子进程）
    with patch.object(core.subprocess, "run", side_effect=AssertionError("AMD 模式不应调用子进程")):
        opt, _ = core.resolve_optimizer(vpy, logs.append, requested="auto", amd_mode=True)
    assert opt == "AdamW", opt

    # 5) 用户明确指定 adamw -> AdamW（不调用子进程）
    with patch.object(core.subprocess, "run", side_effect=AssertionError("指定 adamw 不应调用子进程")):
        opt, _ = core.resolve_optimizer(vpy, logs.append, requested="adamw")
    assert opt == "AdamW", opt

    # 6) 指定 adamw8bit 但不可用 -> 自动降级 AdamW
    def subrun_no_lion2(cmd, *args, **kwargs):
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "import lion_pytorch" in code:
            return probe_result("", 1)
        if "bitsandbytes" in code:
            return probe_result("compiled without GPU support\n", 1)
        return probe_result("", 0)
    with patch.object(core.subprocess, "run", side_effect=subrun_no_lion2):
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

    # 9) musubi 第二引擎 allow_lion=False：预检失败时即使 lion 可用也直接降级 AdamW
    def subrun_musubi(cmd, *args, **kwargs):
        code = str(cmd[2]) if len(cmd) > 2 and str(cmd[1]) == "-c" else ""
        if "import lion_pytorch" in code:
            return probe_result("", 0)  # lion 可用，但 musubi 不支持
        if "bitsandbytes" in code:
            return probe_result("Error: libbitsandbytes_cuda128.dll missing\n", 1)
        return probe_result("", 0)
    with patch.object(core.subprocess, "run", side_effect=subrun_musubi):
        opt, _ = core.resolve_optimizer(vpy, logs.append, requested="auto", allow_lion=False)
    assert opt == "AdamW", opt

    print("OPTIMIZER_RESOLUTION_UNIT_TESTS_OK")


def main():
    with tempfile.TemporaryDirectory(prefix="kohya_engine_flow_") as td:
        base = Path(td)
        test_main_engine(base)
        test_second_engine(base)
        test_second_engine_without_git(base)
        test_third_engine(base)
        test_optimizer_resolution(base)
    print("ALL_ENGINE_CONTROL_FLOW_TESTS_OK")


if __name__ == "__main__":
    main()
