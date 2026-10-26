"""Restore standalone workers from this frozen build, without touching user data."""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time


def ensure_worker_files(kit_dir, log=print):
    if not getattr(sys, "frozen", False):
        return []
    try:
        import kohya_bundled_workers as bundle
    except ModuleNotFoundError as exc:
        if exc.name != "kohya_bundled_workers":
            raise
        raise RuntimeError(
            "当前程序缺少内置组件恢复模块，可能是更新不完整或仍在运行旧程序。"
            "请退出软件所有窗口，用完整安装包覆盖原目录后重新打开。"
            "若通过软件内更新，请保留数据目录 logs 中的 update_install 日志。"
        ) from exc
    root = Path(kit_dir).resolve()
    recovered = []
    for name, (expected, encoded) in bundle.FILES.items():
        path = root / name
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise RuntimeError("预处理组件路径不安全，请使用完整安装包恢复：" + name)
        try:
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
                continue
            data = base64.b64decode(encoded, validate=True)
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("程序内置组件校验失败")
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                backup = path.with_name(path.name + ".previous_" + str(time.time_ns()))
                shutil.copy2(path, backup)
            fd, temporary = tempfile.mkstemp(prefix=".worker_", suffix=".part", dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("组件恢复后内容校验失败")
        except (OSError, ValueError) as exc:
            raise RuntimeError("预处理组件无法恢复：" + name + "。请退出软件，使用当前版本完整安装包覆盖安装到 "
                               + str(root) + "。原图和训练数据未处理。原因：" + str(exc)) from exc
        recovered.append(name)
        log("[组件恢复] 已从当前程序的内置副本恢复：" + name)
    return recovered
