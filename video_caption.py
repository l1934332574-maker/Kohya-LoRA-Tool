# -*- coding: utf-8 -*-
"""视频自动打标：用 Qwen2.5-VL 给视频生成英文描述（写入同名 .txt）。

独立脚本，用 kohya venv 的 Python 运行（transformers 4.54 已支持 Qwen2.5-VL）：
  python video_caption.py --video_dir <视频文件夹> [--trigger <触发词>] [--frames 6] [--overwrite]

模型：Qwen/Qwen2.5-VL-3B-Instruct（约 6~7GB，首次使用自动下载，走 hf-mirror 国内镜像）。
已存在同名 .txt 的视频默认跳过（避免重复打标/覆盖手写描述），--overwrite 可强制重写。
"""
import argparse
import os
import sys


def find_videos(folder):
    exts = (".mp4", ".avi", ".mov", ".webm", ".mkv", ".wmv", ".m4v", ".flv")
    out = []
    for f in sorted(os.listdir(folder)):
        p = os.path.join(folder, f)
        if os.path.isfile(p) and f.lower().endswith(exts):
            out.append(p)
    return out


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--video_dir", required=True)
    ap.add_argument("--trigger", default="")
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    videos = find_videos(args.video_dir)
    if not videos:
        print(f"[打标] 视频文件夹里没有找到视频：{args.video_dir}")
        return 1

    # 加载 Qwen2.5-VL（按需下载，走 HF_ENDPOINT 镜像）
    from transformers import Qwen2_5_VLProcessor, Qwen2_5_VLForConditionalGeneration
    print("[打标] 加载 Qwen2.5-VL-3B（首次会自动下载模型，约 6~7GB，请耐心等待）…")
    proc = Qwen2_5_VLProcessor.from_pretrained(args.model)
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        args.model, torch_dtype="auto", device_map="auto")
    print("[打标] 模型加载完成，开始处理视频…")

    trig = (args.trigger or "").strip()
    prefix = f"<{trig}> " if trig else ""
    n_ok = n_skip = n_fail = 0
    for vp in videos:
        txt = os.path.splitext(vp)[0] + ".txt"
        if os.path.isfile(txt) and not args.overwrite:
            print(f"[打标] 跳过（已有 txt）：{os.path.basename(vp)}")
            n_skip += 1
            continue
        frames = extract_frames(vp, args.frames)
        if not frames:
            print(f"[打标] 抽帧失败：{os.path.basename(vp)}")
            n_fail += 1
            continue
        try:
            prompt = (f"{prefix}Describe this video clip in one concise English sentence: "
                      "who or what, the action, the scene, the style. No extra words.")
            msgs = [{"role": "user",
                     "content": [{"type": "image"}] * len(frames) +
                                [{"type": "text", "text": prompt}]}]
            text = proc.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
            inputs = proc(text=[text], images=[frames], return_tensors="pt")
            gen = model.generate(**inputs, max_new_tokens=160, do_sample=False,
                                 num_beams=1, use_cache=True)
            out = proc.batch_decode(gen[:, inputs["input_ids"].shape[1]:],
                                    skip_special_tokens=True)[0].strip()
            if not out:
                out = trig if trig else "a video"
            with open(txt, "w", encoding="utf-8") as f:
                f.write(out + "\n")
            print(f"[打标] OK {os.path.basename(vp)} -> {out[:90]}")
            n_ok += 1
        except Exception as e:
            print(f"[打标] 失败 {os.path.basename(vp)}: {e}")
            n_fail += 1

    print(f"[打标] 完成：成功 {n_ok} | 跳过(已有txt) {n_skip} | 失败 {n_fail}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
