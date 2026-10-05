# -*- coding: utf-8 -*-
"""Anima 底模「合并包」识别 + 剥离 + 缓存（纯 Python，零第三方依赖）。

背景：Anima 训练（sd-scripts anima_train_network.py）要求“纯 DiT”底模文件；
社区发布的 Semi/merge 推理包常把文本编码器(Qwen3-0.6B)一起塞进同一个
.safetensors（key 以 cond_stage_model.* / first_stage_model.* 开头），
训练脚本严格校验会报 `Unexpected keys in checkpoint` 直接退出。

本模块：
  1. checkpoint_kind()  —— 只读 safetensors 头判断 pure/merged；
  2. strip_to_dit()      —— 流式拷贝 DiT 权重到新文件（不加载权重进内存），
                           只删除非 DiT 前缀，不按其他模型的结构裁剪；
  3. resolve_train_base()—— merged 时自动剥离并缓存到数据目录，二次直接复用。
"""
import io
import os
import re
import json
import struct
import shutil
import tempfile

_DROP_PREFIXES = ("cond_stage_model.", "first_stage_model.", "vae.", "text_encoder.")


def _read_header(path):
    """返回 (header_dict, data_offset)。header_dict 不含 __metadata__ 的键为张量 key。

    只读前 8 字节 + 头部 JSON，不加载任何权重。
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    with open(path, "rb") as f:
        head = f.read(8)
        if len(head) < 8:
            raise ValueError("文件过小，不是 safetensors：%s" % path)
        (n,) = struct.unpack("<Q", head)
        if n <= 0 or n > min(64 << 20, os.path.getsize(path) - 8):  # Bounded header-only inspection
            raise ValueError("safetensors 头部长度异常：%s" % path)
        blob = f.read(n)
        if len(blob) != n:
            raise ValueError("safetensors 头部不完整：%s" % path)
    header = json.loads(blob.decode("utf-8"))
    return header, 8 + n


def validate_safetensors_layout(path):
    """Read the header only and require tensor offsets to cover the actual payload."""
    header, offset = _read_header(path)
    if not isinstance(header, dict):
        raise ValueError("模型头部不是有效的张量目录。")
    spans = []
    for name, tensor in header.items():
        if name == "__metadata__":
            continue
        values = tensor.get("data_offsets") if isinstance(tensor, dict) else None
        if not isinstance(values, list) or len(values) != 2 or any(type(v) is not int for v in values):
            raise ValueError("模型张量偏移格式无效。")
        start, end = values
        if start < 0 or end < start:
            raise ValueError("模型张量偏移无效。")
        spans.append((start, end))
    if not spans:
        raise ValueError("模型文件中没有可用张量。")
    cursor = 0
    for start, end in sorted(spans):
        if start != cursor:
            raise ValueError("模型张量数据有空隙或重叠，无法正常加载。")
        cursor = end
    actual = os.path.getsize(path) - offset
    if cursor != actual:
        extra = actual - cursor
        note = "实际数据比头部声明多 %d 字节" % extra if extra > 0 else "实际数据比头部声明少 %d 字节" % -extra
        raise ValueError("safetensors 文件布局异常：%s。请核对原始模型或重新准备文件；工具不会自动裁剪或覆盖底模。" % note)


def _tensor_keys(header):
    return [k for k in header.keys() if k != "__metadata__"]


def checkpoint_kind(path):
    """返回 "pure"/"merged"/"invalid"/"missing"。

    merged = 张量 key 里含文本编码器/VAE（cond_stage_model.*、first_stage_model.* 等）。
    """
    try:
        header, _off = _read_header(path)
    except FileNotFoundError:
        return "missing"
    except Exception:
        return "invalid"
    keys = _tensor_keys(header)
    if not keys:
        return "invalid"
    for k in keys:
        if k.startswith(_DROP_PREFIXES):
            return "merged"
    return "pure"


def _reference_keys(path):
    """参考纯 DiT 底模的张量 key 集合（用于保证剥离结果“零多余 key”）。"""
    try:
        header, _off = _read_header(path)
    except Exception:
        return None
    keys = _tensor_keys(header)
    return set(keys) if keys else None


def strip_to_dit(src, dst, ref_path=None, logf=print):
    """把合并包里的 DiT 权重流式拷到新文件；返回 (写入张量数, 丢弃张量数)。

    - 仅丢弃文本编码器/VAE 前缀，保留原模型的全部 DiT 层。
    - ref_path 仅作结构对照，不能用另一规格模型的 key 集合裁剪本模型。
    """
    header, data_off = _read_header(src)
    keys = _tensor_keys(header)
    if not keys:
        raise ValueError("没有张量可剥离：%s" % src)
    keep = [k for k in keys if not k.startswith(_DROP_PREFIXES)]
    drop = [k for k in keys if k.startswith(_DROP_PREFIXES)]
    if ref_path:
        ref = _reference_keys(ref_path)
        if ref and set(keep) != ref:
            logf("[Anima] 合并包与参考底模的结构不同；保留本模型所有 DiT 权重，不按参考模型删层。")
    if not keep:
        raise ValueError("剥离后没有保留任何 DiT 权重：%s" % src)

    # 新头部（保持原张量顺序）
    meta = dict(header.get("__metadata__") or {})
    meta["kohya_dit_only"] = "1"
    meta["kohya_dit_strip_schema"] = "2"
    new_header = {"__metadata__": meta}
    offset = 0
    for k in keep:
        spec = dict(header[k])
        length = spec["data_offsets"][1] - spec["data_offsets"][0]
        spec["data_offsets"] = [offset, offset + length]
        new_header[k] = spec
        offset += length
    blob = json.dumps(new_header, separators=(",", ":")).encode("utf-8")

    dst_tmp = None
    try:
        fd, dst_tmp = tempfile.mkstemp(prefix=os.path.basename(dst) + ".", suffix=".part",
                                       dir=os.path.dirname(dst) or ".")
        os.close(fd)
        with open(src, "rb") as fin, open(dst_tmp, "wb") as fout:
            fout.write(struct.pack("<Q", len(blob)))
            fout.write(blob)
            for k in keep:
                s0, s1 = header[k]["data_offsets"]
                length = s1 - s0
                fin.seek(data_off + s0)
                _copy_range(fin, fout, length)
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        os.replace(dst_tmp, dst)
        dst_tmp = None
    finally:
        if dst_tmp and os.path.isfile(dst_tmp):
            try:
                os.remove(dst_tmp)
            except Exception:
                pass
    logf("[Anima] 剥离完成：保留 %d 个 DiT 权重，丢弃 %d 个非 DiT key → %s"
         % (len(keep), len(drop), dst))
    return len(keep), len(drop)


def _copy_range(fin, fout, length):
    remaining = length
    chunk = 1 << 22  # 4MB
    while remaining > 0:
        buf = fin.read(min(chunk, remaining))
        if not buf:
            raise IOError("读取源文件失败（可能被截断）：偏移 %d" % fin.tell())
        fout.write(buf)
        remaining -= len(buf)


def _cache_dir():
    try:
        from kohya_core.paths import data_dir
        return os.path.join(data_dir(), "cache", "anima_dit")
    except Exception:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "_anima_dit_cache")


def _cache_meta_path(dst):
    return dst + ".json"


def _cache_valid(dst, src):
    try:
        with open(_cache_meta_path(dst), "r", encoding="utf-8") as f:
            m = json.load(f)
        st = os.stat(src)
        return (os.path.isfile(dst) and checkpoint_kind(dst) == "pure"
                and m.get("strip_schema") == 2
                and m.get("src") == src and m.get("size") == st.st_size
                and m.get("mtime_ns") == st.st_mtime_ns)
    except Exception:
        return False


def _write_cache_meta(dst, src):
    try:
        st = os.stat(src)
        with open(_cache_meta_path(dst), "w", encoding="utf-8") as f:
            json.dump({"src": src, "size": st.st_size, "mtime_ns": st.st_mtime_ns, "strip_schema": 2}, f)
    except Exception:
        pass


def _find_pure_reference(src):
    """在 src 同目录找“纯 DiT”参考文件（仅头读取，快）。找不到返回 None。"""
    d = os.path.dirname(src) or "."
    try:
        names = [f for f in os.listdir(d) if f.lower().endswith(".safetensors")]
    except Exception:
        return None
    for name in sorted(names):
        # 只认名字带 anima 的纯 DiT 文件当参考（models/base 里可能有 FLUX 等其他纯 DiT，结构不同）
        if "anima" not in name.lower():
            continue
        p = os.path.join(d, name)
        if os.path.abspath(p) == os.path.abspath(src):
            continue
        try:
            if checkpoint_kind(p) == "pure":
                return p
        except Exception:
            continue
    return None


def resolve_train_base(path, logf=print, force=False):
    """训练前调用：返回 (实际底模路径, kind)。

    kind: "pure" 直接用；"merged_stripped"/"merged_cached" 用剥离缓存；
          "invalid"/"missing" 原样返回（由调用方决定是否报错）。
    """
    kind = checkpoint_kind(path)
    if kind in ("pure", "invalid", "missing"):
        return path, kind
    if kind == "merged":
        stem = os.path.splitext(os.path.basename(path))[0]
        cache_dir = _cache_dir()
        os.makedirs(cache_dir, exist_ok=True)
        dst = os.path.join(cache_dir, stem + "_dit.safetensors")
        if not force and _cache_valid(dst, path):
            logf("[Anima] 复用剥离缓存（合并包 → DiT）：%s" % dst)
            return dst, "merged_cached"
        logf("[Anima] 检测到合并包底模（内含文本编码器 Qwen3，训练需要纯 DiT），"
             "正在剥离并缓存（大文件一次性，约 1~3 分钟）…\n       源: %s" % path)
        try:
            strip_to_dit(path, dst, logf=logf)
            _write_cache_meta(dst, path)
            return dst, "merged_stripped"
        except Exception as e:
            logf("[Anima] 剥离失败（%s），继续使用原文件——训练端若报 Unexpected keys 请换纯 DiT 底模" % e)
            return path, kind
    return path, kind
