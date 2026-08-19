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
    assert any("tuna.tsinghua.edu.cn" in x for c in install_cmd["seen"] for x in c), install_cmd["seen"]

    # 2.5) force=True：即使快速校验通过（-c 可 import），也强制补装一轮
    force_install = {"n": 0}
    def subrun_ok_force(cmd, *args, **kwargs):
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
            assert "强制补装后仍不可用" in str(e), e
    assert calls2["n"] == 1, "补装失败时不应重试 preprocess"
    assert deps_n["n"] == 2, deps_n
    print("PREPROCESS_AUTO_RETRY_OK")



def test_preinstall_torch_mirror_fallback(base: Path):
    """_preinstall_torch 本地安装多镜像回退：清华失败 -> 阿里云成功；全部失败才报明确错误。"""
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

    # 场景 A：清华失败 -> 阿里云成功
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
    assert installs["indexes"][0] == "https://pypi.tuna.tsinghua.edu.cn/simple", installs
    assert installs["indexes"][1] == "https://mirrors.aliyun.com/pypi/simple/", installs
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
    assert installs2["n"] == 3, installs2  # 清华/阿里/上海交大各试一次
    assert installs2["indexes"][2] == "https://mirror.sjtu.edu.cn/pypi/web/simple", installs2
    assert installs2["indexes"][0] == "https://pypi.tuna.tsinghua.edu.cn/simple", installs2

    print("PREINSTALL_TORCH_MIRROR_FALLBACK_OK")



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


def main():
    with tempfile.TemporaryDirectory(prefix="kohya_engine_flow_") as td:
        base = Path(td)
        test_main_engine(base)
        test_second_engine(base)
        test_second_engine_without_git(base)
        test_third_engine(base)
        test_optimizer_resolution(base)
        test_preprocess_deps(base)
        test_preinstall_torch_mirror_fallback(base)
        test_tokenizer_cache(base)
        test_preprocess_auto_retry(base)
        test_external_python_safe_cwd(base)
        test_amd_download_progress(base)
        test_amd_torch_verification(base)
        test_accelerate_module_launcher(base)
    print("ALL_ENGINE_CONTROL_FLOW_TESTS_OK")


if __name__ == "__main__":
    main()
