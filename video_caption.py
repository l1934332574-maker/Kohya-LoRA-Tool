# -*- coding: utf-8 -*-
"""视频自动打标：用 Qwen2.5-VL 给视频生成英文描述（写入同名 .txt）。

独立脚本，使用已安装且兼容的训练引擎 Python 环境运行：
  python video_caption.py --video_dir <视频文件夹> [--trigger <触发词>] [--frames 6] [--overwrite]

模型：Qwen/Qwen2.5-VL-3B-Instruct（约 6~7GB，首次使用自动下载，走 hf-mirror 国内镜像）。
已有非空同名 .txt 默认保留，空白文本会补齐；改写前备份原文本。--overwrite 可强制重写。
"""
# ★ 2026-09-27 关键修复：剔除「本脚本所在目录」在 sys.path 中的条目 ✗
#   打包版把 python312.dll / _socket.pyd 等 3.12 的 C 扩展与本脚本平铺在同一目录 ✗
#   而 Python 会把脚本目录放进 sys.path[0] → import 会命中那份 3.12 扩展 ✗
#   → `ImportError: Module use of python312.dll conflicts with this version of Python`
#   本脚本还会联网下载 Qwen2.5-VL 权重（走 urllib）✗ → 必踩 ✓
#   （细节见 preprocess.py 同段注释 ✓）
#   ⚠️ 必须是所有 import 之前的第一件事 ✓
import glob as _glob2
import os as _os
import sys as _sys
_HERE = _os.path.dirname(_os.path.abspath(__file__))
# ⚠️ 必须**条件成立才剔除** ✗：仅当本目录确实含打包版 C 扩展时才动手 ✓
#   （开发环境下本目录就是项目根，还放着 kohya_core 等本地包 ——
#    无条件剔除会把它们也屏蔽掉，直接 import 失败 ✓）
# The GUI imports this module while scanning project images. Keep the frozen
# bundle root on sys.path so PyInstaller can load later modules from PYZ.
# Only an external Python worker must avoid this directory's bundled DLLs.
if not getattr(_sys, "frozen", False) and any(
        _glob2.glob(_os.path.join(_HERE, _p))
        for _p in ("python3*.dll", "_socket.pyd", "_ctypes.pyd")):
    _sys.path[:] = [p for p in _sys.path
                    if _os.path.normcase(_os.path.abspath(p or _os.getcwd())) != _os.path.normcase(_HERE)]

import argparse
import os
import sys
from pathlib import Path
import re
import tempfile
import time
import uuid

# 默认模型：Qwen2.5-VL-3B-Instruct（约 6~7GB，首次使用自动下载，走 hf-mirror 国内镜像）
MODEL_ID = "Qwen/Qwen2.5-VL-3B-Instruct"


def find_videos(folder, recursive=False, mp4_only=False):
    folder = str(Path(folder).resolve())
    exts = (".mp4", ".avi", ".mov", ".webm", ".mkv", ".wmv", ".m4v", ".flv")
    if mp4_only:
        exts = (".mp4",)
    out = []
    folders = os.walk(folder) if recursive else [(folder, [], os.listdir(folder))]
    for root, dirs, files in folders:
        dirs[:] = sorted(name for name in dirs if not name.startswith(".")
                          and not _linked(Path(root) / name))
        for f in sorted(files):
            p = os.path.join(root, f)
            if os.path.isfile(p) and not _linked(Path(p)) and f.lower().endswith(exts):
                out.append(p)
    return out


def _linked(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def caption_snapshot(video):
    path = Path(video).with_suffix(".txt")
    if _linked(path):
        raise ValueError("字幕文件是链接，请先改为本地文本：%s" % path.name)
    if not path.exists():
        return None, ""
    if path.stat().st_size > 65536:
        raise ValueError("字幕文件过大，请先检查：%s" % path.name)
    content = path.read_bytes()
    encoding = "utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    return content, content.decode(encoding, errors="replace").strip()


def write_caption(video, text, previous, backup_root, dataset_root):
    path = Path(video).with_suffix(".txt")
    if caption_snapshot(video)[0] != previous:
        raise RuntimeError("描述期间字幕已修改，保留最新文本，请重新检查")
    data = (text.rstrip() + "\n").encode("utf-8")
    if previous is None:
        # Exclusive creation protects a newly added user caption.
        with path.open("xb") as handle:
            handle.write(data)
        return
    if _linked(backup_root.parent):
        raise RuntimeError("字幕备份目录是链接，请先检查 .caption_backups")
    backup = backup_root / path.relative_to(dataset_root)
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(previous)
    fd, temporary = tempfile.mkstemp(prefix=".caption_", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        if caption_snapshot(video)[0] != previous:
            raise RuntimeError("描述期间字幕已修改，保留最新文本，请重新检查")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def extract_frames(video_path, n=6, short=448):
    """用 cv2 均匀抽 n 帧，resize 短边到 short，返回 PIL 图列表。"""
    import cv2
    from PIL import Image
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total <= 0:
        cap.release()
        return []
    idxs = sorted({int(i * total / n) for i in range(n) if int(i * total / n) < total})
    frames = []
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        h, w = frame.shape[:2]
        scale = short / float(min(h, w))
        if scale < 1:
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
        frames.append(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
    cap.release()
    return frames


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--video_dir", required=True)
    ap.add_argument("--trigger", default="")
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--recursive", action="store_true", help="包含数据集子文件夹")
    ap.add_argument("--mp4-only", action="store_true", help="H3 混合媒体只描述可训练的 MP4")
    ap.add_argument("--model", default=MODEL_ID, help="Qwen2.5-VL 模型 ID（默认 %s）" % MODEL_ID)
    args = ap.parse_args()

    if args.frames < 1:
        ap.error("--frames 必须大于 0")
    videos = find_videos(args.video_dir, recursive=args.recursive, mp4_only=args.mp4_only)
    if not videos:
        print(f"[打标] 视频文件夹里没有找到视频：{args.video_dir}")
        return 1

    dataset_root = Path(args.video_dir).resolve()
    snapshots = {vp: caption_snapshot(vp) for vp in videos}
    pending = [vp for vp in videos if args.overwrite or not snapshots[vp][1]]
    backup_root = dataset_root / ".caption_backups" / ("video_" + time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8])
    n_ok, n_skip, n_fail = 0, len(videos) - len(pending), 0
    print(f"[打标] 找到 {len(videos)} 个视频，待描述 {len(pending)} 个，已有字幕跳过 {n_skip} 个。")
    if not pending:
        print(f"[打标] 完成：成功 0 | 跳过(已有txt) {n_skip} | 失败 0；无需加载模型。")
        return 0

    # 加载 Qwen2.5-VL（按需下载，走 HF_ENDPOINT 镜像）
    import torch
    from transformers import Qwen2_5_VLProcessor, Qwen2_5_VLForConditionalGeneration
    print("[打标] 加载 Qwen2.5-VL-3B（首次会自动下载模型，约 6~7GB，请耐心等待）…")
    proc = Qwen2_5_VLProcessor.from_pretrained(args.model)
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        args.model, torch_dtype="auto", device_map="auto")
    print("[打标] 模型加载完成，开始处理视频…")

    trig = (args.trigger or "").strip()
    prefix = f"<{trig}> " if trig else ""
    for index, vp in enumerate(pending, 1):
        try:
            if caption_snapshot(vp)[1] and not args.overwrite:
                print(f"[打标] 跳过（已有 txt）：{os.path.basename(vp)}")
                n_skip += 1
                continue
            print(f"[打标] 正在抽帧并描述：{os.path.basename(vp)}")
            frames = extract_frames(vp, args.frames)
            if not frames:
                raise RuntimeError("抽帧失败，视频可能无法读取")
            prompt = (f"{prefix}Describe this video clip in one concise English sentence: "
                      "who or what, the action, the scene, the style. No extra words.")
            msgs = [{"role": "user",
                     "content": [{"type": "image"}] * len(frames) +
                                [{"type": "text", "text": prompt}]}]
            text = proc.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
            inputs = proc(text=[text], images=[frames], return_tensors="pt").to(model.device)
            with torch.inference_mode():
                gen = model.generate(**inputs, max_new_tokens=160, do_sample=False,
                                     num_beams=1, use_cache=True)
            out = proc.batch_decode(gen[:, inputs["input_ids"].shape[1]:],
                                    skip_special_tokens=True)[0].strip()
            if not out:
                raise RuntimeError("模型没有生成描述，未写入占位字幕")
            if trig and not re.search(r"(^|[\s,，])" + re.escape(trig) + r"([\s,，.!?。！？]|$)", out, re.IGNORECASE):
                out = trig + ", " + out
            write_caption(vp, out, snapshots[vp][0], backup_root, dataset_root)
            print(f"[打标] OK {os.path.basename(vp)} -> {out[:90]}")
            n_ok += 1
        except FileExistsError:
            print(f"[打标] 跳过（已有 txt）：{os.path.basename(vp)}")
            n_skip += 1
        except Exception as e:
            print(f"[打标] 失败 {os.path.basename(vp)}: {e}")
            n_fail += 1
        finally:
            print(f"[视频描述进度] {index}/{len(pending)}")

    print(f"[打标] 完成：成功 {n_ok} | 跳过(已有txt) {n_skip} | 失败 {n_fail}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
