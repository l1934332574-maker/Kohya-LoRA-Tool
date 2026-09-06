# -*- coding: utf-8 -*-
"""kohya_core.lora_naming 单元测试（纯文件操作，零第三方依赖）。

用法：python test_lora_naming.py；返回码 0=通过。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from kohya_core import lora_naming as ln

FAILED = []


def check(name, fn):
    try:
        fn()
        print("  [ok] %s" % name)
    except Exception as e:
        FAILED.append(name)
        print("  [FAIL] %s: %r" % (name, e))


def _touch(path, mtime=None, size=8):
    with open(path, "wb") as f:
        f.write(b"\0" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_find_final_picks_newest():
    d = tempfile.mkdtemp()
    _touch(os.path.join(d, "a.safetensors"), mtime=1000)
    _touch(os.path.join(d, "b.safetensors"), mtime=2000)
    os.makedirs(os.path.join(d, "snapshots"))
    _touch(os.path.join(d, "snapshots", "c.safetensors"), mtime=9000)  # 子目录不参与挑选
    _touch(os.path.join(d, "note.txt"), mtime=9000)                    # 非 safetensors 不参与
    assert ln.find_final_lora(d) == os.path.join(d, "b.safetensors")


def test_find_final_prefers_prefix():
    d = tempfile.mkdtemp()
    _touch(os.path.join(d, "anime_style_lora-000004.safetensors"), mtime=1000)
    _touch(os.path.join(d, "other_lora.safetensors"), mtime=9999)
    got = ln.find_final_lora(d, prefer_prefix="anime_style_lora")
    assert got == os.path.join(d, "anime_style_lora-000004.safetensors"), got


def test_export_copies_named_by_project():
    d = tempfile.mkdtemp()
    _touch(os.path.join(d, "krea2_lora-000006.safetensors"), mtime=1000, size=16)
    _touch(os.path.join(d, "krea2_lora-000008.safetensors"), mtime=2000, size=32)
    logs = []
    got = ln.export_project_named_lora("krea2", "我的项目", logf=logs.append, out_dir=d)
    target = os.path.join(d, "我的项目.safetensors")
    assert got == target and os.path.isfile(target), (got, logs)
    assert os.path.getsize(target) == 32                               # 取的是最新成品
    assert os.path.isfile(os.path.join(d, "krea2_lora-000008.safetensors"))  # 原文件保留
    assert any("已按项目名命名成品" in m for m in logs), logs
    # 收尾重复调用：同源不重复复制，结果一致
    got2 = ln.export_project_named_lora("krea2", "我的项目", logf=lambda *a: None, out_dir=d)
    assert got2 == target


def test_export_overwrites_on_retrain():
    d = tempfile.mkdtemp()
    _touch(os.path.join(d, "krea2_lora.safetensors"), mtime=1000, size=16)
    ln.export_project_named_lora("krea2", "proj", logf=lambda *a: None, out_dir=d)
    _touch(os.path.join(d, "krea2_lora.safetensors"), mtime=3000, size=64)  # 重训出新成品
    ln.export_project_named_lora("krea2", "proj", logf=lambda *a: None, out_dir=d)
    assert os.path.getsize(os.path.join(d, "proj.safetensors")) == 64


def test_export_skips_and_sanitizes_name():
    d = tempfile.mkdtemp()
    logs = []
    assert ln.export_project_named_lora("krea2", "", logf=logs.append, out_dir=d) is None
    assert ln.export_project_named_lora("krea2", "  ", logf=logs.append, out_dir=d) is None
    empty = tempfile.mkdtemp()
    assert ln.export_project_named_lora("krea2", "proj", logf=logs.append, out_dir=empty) is None
    assert any("没找到成品" in m for m in logs), logs
    # 项目名带文件名非法字符 → 清洗成下划线
    d2 = tempfile.mkdtemp()
    _touch(os.path.join(d2, "krea2_lora.safetensors"), mtime=100)
    got = ln.export_project_named_lora("krea2", "a:b*c?", logf=lambda *a: None, out_dir=d2)
    assert os.path.basename(got) == "a_b_c_.safetensors", got


def test_export_never_raises():
    # out_dir 是文件（异常路径）：只返回 None，不抛
    d = tempfile.mkdtemp()
    fp = os.path.join(d, "not_a_dir")
    with open(fp, "w") as f:
        f.write("x")
    assert ln.export_project_named_lora("krea2", "proj", logf=lambda *a: None, out_dir=fp) is None


def main():
    print("== kohya_core.lora_naming 单元测试 ==")
    check("找最新成品（只看顶层文件）", test_find_final_picks_newest)
    check("优先匹配模式 output_name 前缀", test_find_final_prefers_prefix)
    check("按项目名复制成品（原文件保留）", test_export_copies_named_by_project)
    check("重训后覆盖旧导出", test_export_overwrites_on_retrain)
    check("无项目/无成品跳过 + 文件名清洗", test_export_skips_and_sanitizes_name)
    check("异常路径不抛出", test_export_never_raises)
    print("-" * 40)
    if FAILED:
        print("✘ 失败 %d 项: %s" % (len(FAILED), "、".join(FAILED)))
        return 1
    print("✔ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
