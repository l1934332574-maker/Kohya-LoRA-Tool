"""Public Windows build entry point. Produces artifacts; never publishes/signs."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def run(args):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    if sys.platform != "win32":
        raise RuntimeError("The public desktop build requires Windows")
    source = (ROOT / "Kohya一键工具.py").read_text(encoding="utf-8-sig")
    version = re.search(r'APP_VERSION\s*=\s*"(\d+\.\d+\.\d+)"', source).group(1)
    installer = ROOT / "build_exe/installer/installer.iss"
    if '#define MyAppVersion "' + version + '"' not in installer.read_text(encoding="utf-8-sig"):
        raise RuntimeError("Application and installer versions differ")
    run(["npm.cmd", "--prefix", "modern_ui", "ci"])
    run(["npm.cmd", "--prefix", "modern_ui", "run", "build"])
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", "build_exe/dist", "--workpath", "build_exe/work",
         "build_exe/Kohya一键工具.spec"])
    package = ROOT / "build_exe/dist/Kohya一键工具"
    for name in ("preprocess.py", "video_caption.py", "model_downloader.py",
                 "README_使用说明.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, package / name)
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--", "installers", "configs"], cwd=ROOT)
    for name in tracked.decode("utf-8").split("\0"):
        if name:
            destination = package / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
    required = ("_tcl_data/init.tcl", "_tk_data/tk.tcl", "kohya_core/image_io.py",
                "kohya_core/loss_masks.py", "kohya_core/loss_mask_worker.py", "preprocess.py")
    for name in required:
        if not (package / name).is_file():
            raise RuntimeError("Missing package component: " + name)
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(package / "Kohya一键工具.exe"))
    pyz = archive.open_embedded_archive(next(name for name in archive.toc if name.endswith(".pyz")))
    for name in ("kohya_bundled_ui", "kohya_bundled_workers", "kohya_core.worker_files", "kohya_core.lora_continue", "fractions"):
        if name not in pyz.toc:
            raise RuntimeError("Missing EXE component: " + name)
    # The maintained installer may use this value to confirm replacement.
    (package / "installation-exe.sha256").write_text(sha256(package / "Kohya一键工具.exe"), encoding="ascii")
    (package / "kohya_dir.txt").write_text("", encoding="utf-8")
    from release_package_checks import verify_frozen_project_scan
    verify_frozen_project_scan(ROOT, package)
    output = ROOT / "build_exe/unsigned"
    output.mkdir(parents=True, exist_ok=True)
    compiler = Path(os.environ.get("ISCC_PATH", r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"))
    if not compiler.is_file():
        raise RuntimeError("Inno Setup compiler not found: " + str(compiler))
    # Hosted Windows runners do not include community language files.
    language = compiler.parent / "Languages/ChineseSimplified.isl"
    if not language.is_file():
        shutil.copy2(ROOT / "build_exe/installer/languages/ChineseSimplified.isl", language)
    run([compiler, "/O" + str(output), "/FSetup-unsigned", installer])
    portable = output / ("KohyaLoraTool_v" + version + "_unsigned_portable.zip")
    with zipfile.ZipFile(portable, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(package).as_posix())
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    files = [output / "Setup-unsigned.exe", portable]
    report = {"version": version, "source_commit": commit, "signed": False,
              "files": {p.name: {"size": p.stat().st_size, "sha256": sha256(p)} for p in files}}
    (output / "build-provenance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
    (output / "pip-freeze.txt").write_text(freeze, encoding="utf-8")
    print("Unsigned build complete; no release, upload or signing request was made.")


if __name__ == "__main__":
    main()
