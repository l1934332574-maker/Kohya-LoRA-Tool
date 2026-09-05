# -*- coding: utf-8 -*-
"""kohya_core.anima_ckpt 单元测试（合成 safetensors，零依赖）。

用法：python test_anima_ckpt.py；返回码 0=通过。
"""
import io
import os
import sys
import json
import struct
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from kohya_core import anima_ckpt as ac

FAILED = []


def check(name, fn):
    try:
        fn()
        print("  [ok] %s" % name)
    except Exception as e:
        FAILED.append(name)
        print("  [FAIL] %s: %s" % (name, e))
        import traceback
        traceback.print_exc()


def _write_sf(path, keys):
    """写一个最小 safetensors：每个张量 4 字节，内容 = key 序号。"""
    header = {"__metadata__": {"k": "v"}}
    offset = 0
    payload = b""
    for i, k in enumerate(keys):
        header[k] = {"dtype": "F32", "shape": [1], "data_offsets": [offset, offset + 4]}
        payload += struct.pack("<f", float(i + 1))
        offset += 4
    blob = json.dumps(header, separators=(",", ":")).encode("utf-8")
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(blob)))
        f.write(blob)
        f.write(payload)


def _read_keys(path):
    h, _off = ac._read_header(path)
    return ac._tensor_keys(h)


def t_classify():
    d = tempfile.mkdtemp()
    pure = os.path.join(d, "pure.safetensors")
    merged = os.path.join(d, "merged.safetensors")
    _write_sf(pure, ["net.0.weight", "net.1.weight"])
    _write_sf(merged, ["net.0.weight", "cond_stage_model.qwen3_06b.logit_scale"])
    assert ac.checkpoint_kind(pure) == "pure"
    assert ac.checkpoint_kind(merged) == "merged"
    assert ac.checkpoint_kind(os.path.join(d, "nope.safetensors")) == "missing"
    bad = os.path.join(d, "bad.safetensors")
    with open(bad, "wb") as f:
        f.write(b"\x00\x00")
    assert ac.checkpoint_kind(bad) == "invalid"


def t_strip_with_ref():
    d = tempfile.mkdtemp()
    ref = os.path.join(d, "ref.safetensors")
    src = os.path.join(d, "src.safetensors")
    dst = os.path.join(d, "out.safetensors")
    _write_sf(ref, ["net.0.weight", "net.1.weight", "net.2.weight"])
    _write_sf(src, ["net.0.weight", "net.1.weight", "net.2.weight",
                    "cond_stage_model.qwen3_06b.logit_scale", "first_stage_model.w"])
    nkeep, ndrop = ac.strip_to_dit(src, dst, ref_path=ref, logf=lambda *a: None)
    assert (nkeep, ndrop) == (3, 2), (nkeep, ndrop)
    assert _read_keys(dst) == ["net.0.weight", "net.1.weight", "net.2.weight"]
    # 内容校验：out 张量字节 == src 对应切片
    sh, soff = ac._read_header(src)
    dh, doff = ac._read_header(dst)
    with open(src, "rb") as fs, open(dst, "rb") as fd:
        for k in ["net.0.weight", "net.2.weight"]:
            fs.seek(soff + sh[k]["data_offsets"][0]); a = fs.read(4)
            fd.seek(doff + dh[k]["data_offsets"][0]); b = fd.read(4)
            assert a == b, k
    assert ac.checkpoint_kind(dst) == "pure"


def t_strip_no_ref():
    d = tempfile.mkdtemp()
    src = os.path.join(d, "src.safetensors")
    dst = os.path.join(d, "out.safetensors")
    _write_sf(src, ["net.0.weight", "cond_stage_model.qwen3_06b.w", "first_stage_model.w"])
    nkeep, ndrop = ac.strip_to_dit(src, dst, logf=lambda *a: None)
    assert (nkeep, ndrop) == (1, 2)
    assert _read_keys(dst) == ["net.0.weight"]


def t_resolve():
    import kohya_core.anima_ckpt as m
    d = tempfile.mkdtemp()
    cache = os.path.join(d, "cache")
    os.makedirs(cache, exist_ok=True)
    _orig = m._cache_dir
    m._cache_dir = lambda: cache
    try:
        pure = os.path.join(d, "anima-base-v1.0.safetensors")
        _write_sf(pure, ["net.0.weight", "net.1.weight"])
        p, kind = ac.resolve_train_base(pure, logf=lambda *a: None)
        assert (p, kind) == (pure, "pure")
        merged = os.path.join(d, "BSSANIRLANIMASemi_v20.safetensors")
        _write_sf(merged, ["net.0.weight", "net.1.weight", "cond_stage_model.qwen3_06b.w"])
        p2, kind2 = ac.resolve_train_base(merged, logf=lambda *a: None)
        assert kind2 in ("merged_stripped", "merged_cached"), kind2
        assert os.path.isfile(p2) and ac.checkpoint_kind(p2) == "pure"
        assert _read_keys(p2) == ["net.0.weight", "net.1.weight"]  # 与参考同目录纯文件对齐
        # 第二次 -> 复用缓存
        p3, kind3 = ac.resolve_train_base(merged, logf=lambda *a: None)
        assert kind3 == "merged_cached" and p3 == p2
        # 缺失文件
        p4, kind4 = ac.resolve_train_base(os.path.join(d, "x.safetensors"), logf=lambda *a: None)
        assert kind4 == "missing"
    finally:
        m._cache_dir = _orig


def main():
    print("== Anima 合并包剥离工具测试 ==")
    check("识别 pure/merged/invalid/missing", t_classify)
    check("带参考剥离（交集 + 内容一致）", t_strip_with_ref)
    check("无参考剥离（前缀丢弃）", t_strip_no_ref)
    check("训练前 resolve（自动剥离/缓存复用）", t_resolve)
    print("-" * 40)
    if FAILED:
        print("FAIL %d: %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("OK 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
