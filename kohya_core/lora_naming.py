# -*- coding: utf-8 -*-
"""训练完成后按项目名导出成品 LoRA（复制为 <项目名>.safetensors）。

背景：各引擎的成品文件名是写死的（anime_style_lora / krea2_lora / h3_video_lora…），
多项目训练后从 output 里拷文件时分不清谁是谁。训练正常结束后，把输出目录里
最新的成品 .safetensors 复制一份命名为 <项目名>.safetensors。

为什么是“复制”不是“改名”：断点续训与“已完成不再提示续训”的检测都按引擎原
文件名找文件（如 Fizgig find_fizgig_state 认 <output_name>.safetensors），
改名会把这套逻辑全打断；成品 LoRA 体积有限，多留一份可接受。

纯文件操作、零第三方依赖，可单测（test_lora_naming.py，smoke_test 已接入）。
"""
import os
import shutil

from kohya_core.configs import OUTPUT_NAMES
from kohya_core.paths import data_dir, _sanitize_dirname

__all__ = ["find_final_lora", "export_project_named_lora"]


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _probe_output_dir(name):
    """输出子目录探测路径（只拼不建；data_sub 会 makedirs，探测阶段不能产生空目录）。"""
    return os.path.join(data_dir(), "output", name)


def find_final_lora(out_dir, prefer_prefix=None, exclude_names=()):
    """在输出目录顶层找最新的成品 .safetensors；没有返回 None。

    只看顶层文件：snapshots/（中间快照）、sample/（采样预览）、checkpoints/ 等
    子目录不参与挑选。prefer_prefix 优先匹配该模式的默认 output_name（防止目录里
    混入无关文件时挑错）；没有 prefix 匹配时取整体最新的——“最后写出的
    .safetensors 就是本次成品”对各引擎通用（sd-scripts/musubi 的 epoch 序列文件、
    ai-toolkit/Fizgig 的覆盖式成品都满足）。
    """
    if not out_dir or not os.path.isdir(out_dir):
        return None
    excl = {str(n).lower() for n in (exclude_names or ()) if n}
    pref = (prefer_prefix or "").lower()
    try:
        names = os.listdir(out_dir)
    except OSError:
        return None
    pool = []
    for name in names:
        if not name.lower().endswith(".safetensors") or name.lower() in excl:
            continue
        p = os.path.join(out_dir, name)
        if os.path.isfile(p):
            pool.append(p)
    if not pool:
        return None
    if pref:
        with_pref = [p for p in pool if os.path.basename(p).lower().startswith(pref)]
        if with_pref:
            pool = with_pref
    return max(pool, key=lambda p: (_mtime(p), p))


def export_project_named_lora(mode, project, logf=print, out_dir=None, prefer_prefix=None):
    """训练正常结束后调用：把成品复制为 <项目名>.safetensors。

    返回目标路径；跳过/失败返回 None。本函数永不抛异常——收尾的锦上添花步骤，
    任何失败只记日志，不能把已经成功的训练标成失败。
    """
    try:
        return _export(mode, project, logf, out_dir=out_dir, prefer_prefix=prefer_prefix)
    except Exception as e:
        try:
            logf(f"[导出] 按项目名命名成品失败（忽略，不影响训练结果）：{e}")
        except Exception:
            pass
        return None


def _export(mode, project, logf, out_dir=None, prefer_prefix=None):
    raw = str(project or "").strip()
    proj = _sanitize_dirname(raw)
    if not proj:
        return None  # 没开项目（共享 output/），没有可用的项目名
    target_name = proj + ".safetensors"
    pref = prefer_prefix or OUTPUT_NAMES.get(mode, "")
    if out_dir is None:
        # 第二/三/四引擎的输出目录用清洗后的项目名；第一引擎用原始项目名拼（历史行为），两边都探一下
        dirs = [_probe_output_dir(proj)]
        if raw != proj:
            dirs.append(_probe_output_dir(raw))
        src, out_dir = None, None
        for d in dirs:
            if not os.path.isdir(d):
                continue
            found = find_final_lora(d, prefer_prefix=pref, exclude_names=[target_name])
            if found and (src is None or _mtime(found) > _mtime(src)):
                src, out_dir = found, d
    else:
        src = find_final_lora(out_dir, prefer_prefix=pref, exclude_names=[target_name])
    if not src:
        logf(f"[导出] 输出目录里没找到成品 .safetensors，跳过按项目名命名（{proj}）")
        return None
    target = os.path.join(out_dir, target_name)
    if os.path.abspath(src) == os.path.abspath(target):
        return target  # 成品本来就叫项目名，无需复制
    if os.path.isfile(target) and os.path.getsize(target) == os.path.getsize(src) \
            and abs(_mtime(target) - _mtime(src)) < 2:
        return target  # 已导出过且同源（收尾重复调用），不再复制
    tmp = target + ".part"
    shutil.copy2(src, tmp)
    os.replace(tmp, target)
    logf(f"[导出] 已按项目名命名成品：{target}（原 {os.path.basename(src)} 保留，断点续训不受影响）")
    return target
