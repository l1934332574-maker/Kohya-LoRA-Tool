# -*- coding: utf-8 -*-
"""冒烟测试：每次改动/打包前运行，验证核心配置完整性与基本链路。

用法：python smoke_test.py
返回码 0=通过；1=失败（会打印具体问题）。
覆盖：
  1. 语法检查（Kohya一键工具.py / kohya_gui.py / preprocess.py / video_caption.py）
  2. 配置完整性：所有模式的 PRESETS / GUIDE_STEPS / OUTPUT_NAMES / MIN_IMAGES / DATASET_TIPS
  3. AI 图像模型配置（AT_IMAGE_MODELS：arch/模型/显存提示）
  4. yaml 生成可解析（Qwen/Z-Image/H3）
  5. 导入验证（Kohya一键工具）
"""
import io
import os
import sys
import traceback
from unittest.mock import patch

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
# Windows 控制台默认 GBK，打印 ✔/✘/中文会 UnicodeEncodeError，统一转 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAILED = []


def check(name, fn):
    try:
        fn()
        print("  [ok] %s" % name)
    except Exception as e:
        FAILED.append(name)
        print("  [FAIL] %s: %s" % (name, e))
        traceback.print_exc()


def test_syntax():
    import py_compile
    files = ["Kohya一键工具.py", "kohya_gui.py", "preprocess.py", "video_caption.py",
             "gui/__init__.py", "gui/tag_tools.py",
             "kohya_core/tagging/__init__.py", "kohya_core/tagging/dictionary.py",
             "kohya_core/tagging/normalize.py", "kohya_core/tagging/translate.py",
             "kohya_core/tagging/complete.py", "kohya_core/tagging/test_tagging.py",
             "kohya_core/anima_ckpt.py", "test_anima_ckpt.py"]
    for f in files:
        py_compile.compile(os.path.join(ROOT, f), doraise=True)


def test_import_core():
    import Kohya一键工具 as core
    if not hasattr(core, "MODE_KEYS"):
        raise AssertionError("MODE_KEYS 缺失")
    return core


def test_config_completeness():
    core = test_import_core()
    for mode in core.MODE_KEYS:
        # PRESETS 每个 base_type 齐全
        presets = core.PRESETS.get(mode)
        if not presets:
            raise AssertionError("PRESETS 缺 %s" % mode)
        for bt in ("sd15", "sdxl", "flux", "anima"):
            if bt not in presets:
                raise AssertionError("PRESETS[%s] 缺 %s" % (mode, bt))
        # GUIDE_STEPS
        if mode not in core.GUIDE_STEPS:
            raise AssertionError("GUIDE_STEPS 缺 %s" % mode)
        # OUTPUT_NAMES
        if mode not in core.OUTPUT_NAMES:
            raise AssertionError("OUTPUT_NAMES 缺 %s" % mode)
        # MIN_IMAGES
        if mode not in core.MIN_IMAGES:
            raise AssertionError("MIN_IMAGES 缺 %s" % mode)
        # DATASET_TIPS
        if mode not in core.DATASET_TIPS:
            raise AssertionError("DATASET_TIPS 缺 %s" % mode)
        # 引导步骤 id 唯一
        ids = [s["id"] for s in core.GUIDE_STEPS[mode]]
        if len(ids) != len(set(ids)):
            raise AssertionError("GUIDE_STEPS[%s] 步骤 id 重复" % mode)
        for s in core.GUIDE_STEPS[mode]:
            for k in ("id", "label", "btn", "check", "act", "tip"):
                if k not in s:
                    raise AssertionError("GUIDE_STEPS[%s] 步骤缺字段 %s" % (mode, k))


def test_at_image_models():
    core = test_import_core()
    for mode in ("qwen_image", "zimage"):
        info = core.AT_IMAGE_MODELS.get(mode)
        if not info:
            raise AssertionError("AT_IMAGE_MODELS 缺 %s" % mode)
        for k in ("label", "arch", "model_id", "min_vram", "rec_vram", "size", "hint"):
            if k not in info:
                raise AssertionError("AT_IMAGE_MODELS[%s] 缺 %s" % (mode, k))
    qwen = {c["model_id"]: c for c in core.at_image_model_choices("qwen_image")}
    if qwen.get("Qwen/Qwen-Image-2512", {}).get("arch") != "qwen_image":
        raise AssertionError("Qwen-Image-2512 没映射到 qwen_image 架构")
    if qwen.get("Qwen/Qwen-Image-2.1", {}).get("arch") != "qwen_image_2":
        raise AssertionError("Qwen-Image-2.1 没映射到 qwen_image_2 架构")


def test_download_models():
    core = test_import_core()
    # FLUX 四件套
    for k in ("dit", "clip_l", "t5xxl", "ae"):
        if k not in core.FLUX_MODEL_LINKS:
            raise AssertionError("FLUX_MODEL_LINKS 缺 %s" % k)
        v = core.FLUX_MODEL_LINKS[k]
        if len(v) != 3 or not str(v[2]).startswith("http"):
            raise AssertionError("FLUX_MODEL_LINKS[%s] 格式错误" % k)
    if not callable(core.flux_missing_models):
        raise AssertionError("flux_missing_models 缺失")
    # Anima DiT 底模可应用内下载
    anima = core.get_download_models("anima")
    if not anima or not str(anima[0].get("url", "")).startswith("http"):
        raise AssertionError("DOWNLOAD_MODELS 缺 anima 应用内下载")
    # Krea2 文件齐全（含可选 turbo）
    if len(core.KREA2_MODEL_LINKS) < 4:
        raise AssertionError("KREA2_MODEL_LINKS 不完整")
    # FLUX.2 三件套（DiT / Qwen3 文本编码器 / VAE）
    for k in ("dit", "te", "vae"):
        if k not in core.FLUX2_MODEL_LINKS:
            raise AssertionError("FLUX2_MODEL_LINKS 缺 %s" % k)
        v = core.FLUX2_MODEL_LINKS[k]
        if len(v) != 3 or not str(v[2]).startswith("http"):
            raise AssertionError("FLUX2_MODEL_LINKS[%s] 格式错误" % k)
    if not callable(core.flux2_missing_models):
        raise AssertionError("flux2_missing_models 缺失")


def test_yaml():
    import tempfile
    import yaml
    core = test_import_core()
    tmp = tempfile.mkdtemp()
    vd = os.path.join(tmp, "img")
    os.makedirs(vd, exist_ok=True)
    params = {"project": "冒烟", "rank": "16", "alpha": "16", "unet_lr": "1e-4",
              "video_steps": "2000", "trigger": "myoc", "resolution": "1024"}
    # AI 图像 yaml
    for mode in ("qwen_image", "zimage"):
        cfg = os.path.join(tmp, mode + ".yaml")
        core.write_at_image_yaml(params, core.AT_IMAGE_MODELS[mode], vd, tmp, cfg)
        d = yaml.safe_load(open(cfg, encoding="utf-8"))
        if d["config"]["process"][0]["model"]["arch"] != core.AT_IMAGE_MODELS[mode]["arch"]:
            raise AssertionError("%s yaml arch 不符" % mode)
    qwen21 = next(c for c in core.at_image_model_choices("qwen_image")
                  if c.get("model_id") == "Qwen/Qwen-Image-2.1")
    cfg = os.path.join(tmp, "qwen21.yaml")
    core.write_at_image_yaml(params, qwen21, vd, tmp, cfg, vram_gb=24)
    d = yaml.safe_load(open(cfg, encoding="utf-8"))
    p0 = d["config"]["process"][0]
    if p0["model"].get("arch") != "qwen_image_2":
        raise AssertionError("Qwen-Image-2.1 yaml arch 不符: %s" % p0["model"].get("arch"))
    if p0["model"].get("name_or_path") != "Qwen/Qwen-Image-2.1":
        raise AssertionError("Qwen-Image-2.1 yaml model_id 不符: %s" % p0["model"].get("name_or_path"))
    # Z-Image 8G 快跑档（2026-09-06）：分辨率钳到 512 + 关采样 + 量化 TE + weighted（官方 zimage 预设）
    cfg = os.path.join(tmp, "zimage_8g.yaml")
    core.write_at_image_yaml(dict(params, resolution="1024"), core.AT_IMAGE_MODELS["zimage"], vd, tmp, cfg, vram_gb=8)
    d = yaml.safe_load(open(cfg, encoding="utf-8"))
    p0 = d["config"]["process"][0]
    _ram8 = core.detect_ram_gb() or 0
    _exp8 = 384 if _ram8 < 32 else 512
    if p0["datasets"][0]["resolution"] != [_exp8, _exp8]:
        raise AssertionError("Z-Image 8G 分辨率钳制不符: %s (ram %sG)" % (p0["datasets"][0]["resolution"], _ram8))
    if p0["train"].get("disable_sampling") is not True:
        raise AssertionError("Z-Image 8G 未关闭采样")
    if p0["train"].get("timestep_type") != "weighted":
        raise AssertionError("Z-Image 8G timestep 非 weighted")
    if p0["model"].get("quantize_te") is not True or p0["model"].get("qtype_te") != "qfloat8":
        raise AssertionError("Z-Image 8G TE 未量化")
    if p0["model"].get("layer_offloading") is not True or p0["model"].get("layer_offloading_transformer_percent") != 0.6:
        raise AssertionError("Z-Image 8G 未开层交换")
    # 16G 不启用快跑档（保持原行为，避免误伤现有配置）
    cfg = os.path.join(tmp, "zimage_16g.yaml")
    core.write_at_image_yaml(dict(params, resolution="1024"), core.AT_IMAGE_MODELS["zimage"], vd, tmp, cfg, vram_gb=16)
    d = yaml.safe_load(open(cfg, encoding="utf-8"))
    p0 = d["config"]["process"][0]
    if p0["datasets"][0]["resolution"] != [1024, 1024] or p0["train"].get("disable_sampling") is True or p0["model"].get("layer_offloading") is True:
        raise AssertionError("Z-Image 16G 误启用快跑档")
    # 手动开关：16G 强制开（fast_tier=on）→ 快跑档生效；8G 强制关（fast_tier=off）→ 完全常规
    cfg = os.path.join(tmp, "zimage_16g_on.yaml")
    core.write_at_image_yaml(dict(params, resolution="1024", fast_tier="on"), core.AT_IMAGE_MODELS["zimage"], vd, tmp, cfg, vram_gb=16)
    d = yaml.safe_load(open(cfg, encoding="utf-8"))
    p0 = d["config"]["process"][0]
    if p0["train"].get("disable_sampling") is not True or p0["model"].get("layer_offloading") is not True:
        raise AssertionError("Z-Image 16G fast_tier=on 未生效")
    if p0["datasets"][0]["resolution"] != [_exp8, _exp8]:
        raise AssertionError("Z-Image 16G fast_tier=on 分辨率钳制不符")
    cfg = os.path.join(tmp, "zimage_8g_off.yaml")
    core.write_at_image_yaml(dict(params, resolution="1024", fast_tier="off"), core.AT_IMAGE_MODELS["zimage"], vd, tmp, cfg, vram_gb=8)
    d = yaml.safe_load(open(cfg, encoding="utf-8"))
    p0 = d["config"]["process"][0]
    if p0["train"].get("disable_sampling") is True or p0["model"].get("layer_offloading") is True:
        raise AssertionError("Z-Image 8G fast_tier=off 误启用快跑档")
    if p0["datasets"][0]["resolution"] != [1024, 1024]:
        raise AssertionError("Z-Image 8G fast_tier=off 分辨率被误钳制")
    # Qwen-Image fast_tier=on：强制快跑档生效 + 分辨率 512
    cfg = os.path.join(tmp, "qwen_16g_on.yaml")
    core.write_at_image_yaml(dict(params, resolution="1024", fast_tier="on"), core.AT_IMAGE_MODELS["qwen_image"], vd, tmp, cfg, vram_gb=16)
    d = yaml.safe_load(open(cfg, encoding="utf-8"))
    p0 = d["config"]["process"][0]
    if p0["train"].get("disable_sampling") is not True or p0["model"].get("layer_offloading") is not True:
        raise AssertionError("Qwen fast_tier=on 未生效")
    if p0["datasets"][0]["resolution"] != [512, 512]:
        raise AssertionError("Qwen fast_tier=on 分辨率钳制不符")
    # H3 yaml
    cfg = os.path.join(tmp, "h3.yaml")
    core.write_h3_train_yaml(params, vd, tmp, cfg)
    d = yaml.safe_load(open(cfg, encoding="utf-8"))
    if d["config"]["process"][0]["model"]["arch"] != "minimax_h3":
        raise AssertionError("H3 yaml arch 不符")
    # Krea2（AI-Toolkit 引擎）yaml：16G → qint8+768+low_vram+关采样；24G → qfloat8+1024
    import tempfile as _tf
    _td = _tf.mkdtemp(prefix="k2at_")
    try:
        _raw = os.path.join(_td, "raw.safetensors")
        open(_raw, "wb").write(b"x" * 1024)
        _old_files = core.krea2_model_files
        core.krea2_model_files = lambda: {"raw": _raw, "vae": None, "te": None, "turbo": None}
        _old_count = core.count_images
        core.count_images = lambda *a, **k: 3
        try:
            cfg = os.path.join(tmp, "krea2_at16.yaml")
            core.write_krea2_at_yaml(dict(params, resolution="1024", sample_preview=False), vd, tmp, cfg, vram_gb=16)
            d = yaml.safe_load(open(cfg, encoding="utf-8"))
            p0 = d["config"]["process"][0]
            if p0["model"]["arch"] != "krea2" or p0["model"]["qtype"] != "qint8":
                raise AssertionError("Krea2(AT) 16G yaml 档位不符")
            if p0["datasets"][0]["resolution"] != [512, 512]:
                raise AssertionError("Krea2(AT) 16G 未按快档压到 512")
            if p0["train"].get("disable_sampling") is not True or "sample" not in p0:
                raise AssertionError("Krea2(AT) 16G 需保留 sample 段 + disable_sampling（引擎 cache_sample_prompts 会崩）")
            if p0.get("sample", {}).get("negative_prompt") != "lowres, bad anatomy, worst quality, low quality, blurry, jpeg artifacts, signature, watermark":
                raise AssertionError("Krea2(AT) 负向提示词不应为空(空串会被引擎当 bool 崩)")

            if p0["model"].get("quantize_te") is not True:
                raise AssertionError("Krea2(AT) 16G 应量化文本编码器（0.13 快档配方）")
            # 死区回归：16.0x / 17~23G 也必须拿到省显存组合。
            # 历史 bug：判定写 vram_gb <= 16，16 卡若报成 16.01 就退化成
            # qfloat8 + 1024 + 无 layer_offloading（16G 必 OOM，且连重试兜底都拿不到）。
            for _v in (16.01, 16.6, 17, 18.9):
                cfg = os.path.join(tmp, "krea2_at_%s.yaml" % _v)
                core.write_krea2_at_yaml(dict(params, resolution="1024", sample_preview=False),
                                         vd, tmp, cfg, vram_gb=_v)
                d = yaml.safe_load(open(cfg, encoding="utf-8"))
                p0 = d["config"]["process"][0]
                if p0["model"]["qtype"] != "qint8" or p0["datasets"][0]["resolution"] != [512, 512]:
                    raise AssertionError("Krea2(AT) %sG 未走省显存档（阈值悬崖）" % _v)
                if p0["model"].get("layer_offloading") is not True:
                    raise AssertionError("Krea2(AT) %sG 缺少 layer_offloading（死区）" % _v)
                if p0["model"].get("layer_offloading_transformer_percent") is None:
                    raise AssertionError("Krea2(AT) %sG 分层交换比例缺失" % _v)
            cfg = os.path.join(tmp, "krea2_at24.yaml")
            core.write_krea2_at_yaml(dict(params, resolution="1024", sample_preview=True), vd, tmp, cfg, vram_gb=24)
            d = yaml.safe_load(open(cfg, encoding="utf-8"))
            p0 = d["config"]["process"][0]
            if p0["model"]["qtype"] != "qfloat8" or p0["datasets"][0]["resolution"] != [1024, 1024]:
                raise AssertionError("Krea2(AT) 24G yaml 档位不符")
            if p0["model"].get("quantize_te") is not True:
                raise AssertionError("Krea2(AT) 24G 应量化文本编码器")
        finally:
            core.krea2_model_files = _old_files
            core.count_images = _old_count
    finally:
        import shutil as _sh
        _sh.rmtree(_td, ignore_errors=True)

def test_tagging():
    """标签管理 v1 · 离线中英词典核心链路（加载/翻译/补全/中文反查/GUI 模块可导入）。"""
    from kohya_core.tagging import TagDict
    from kohya_core.tagging import normalize, translate
    d = TagDict()
    if not d.available():
        raise AssertionError("缺少离线词典文件: installers/tag_dict/danbooru_zh.tsv")
    if len(d) < 150000:
        raise AssertionError("离线词条过少: %d" % len(d))
    if d.to_zh("hatsune_miku") != "初音未来":
        raise AssertionError("英→中 翻译错误: hatsune_miku")
    if d.to_zh("blue hair") != d.to_zh("blue_hair"):
        raise AssertionError("空格写法未规范化命中")
    if normalize.norm_en("Blue Hair") != "blue_hair":
        raise AssertionError("normalize 错误")
    if not d.zh_candidates("初音") or d.zh_candidates("初音")[0][0] != "hatsune_miku":
        raise AssertionError("中→英 反查错误: 初音")
    if not any(r[0] == "blue_hair" for r in d.complete_en("blue", limit=50)):
        raise AssertionError("英文补全缺 blue_hair")
    import gui.tag_tools  # GUI 辅助模块可正常导入

def test_anima_ckpt():
    """Anima 合并包剥离工具：识别/剥离/缓存（合成 safetensors，零依赖）。"""
    import json, os, struct, tempfile
    from kohya_core import anima_ckpt as ac

    def _w(path, keys):
        h = {"__metadata__": {}}
        off, payload = 0, b""
        for i, k in enumerate(keys):
            h[k] = {"dtype": "F32", "shape": [1], "data_offsets": [off, off + 4]}
            payload += struct.pack("<f", float(i + 1))
            off += 4
        blob = json.dumps(h, separators=(",", ":")).encode("utf-8")
        with open(path, "wb") as f:
            f.write(struct.pack("<Q", len(blob)) + blob + payload)

    d = tempfile.mkdtemp()
    pure = os.path.join(d, "pure.safetensors")
    merged = os.path.join(d, "merged.safetensors")
    _w(pure, ["net.0.weight", "net.1.weight"])
    _w(merged, ["net.0.weight", "net.1.weight", "cond_stage_model.qwen3_06b.w"])
    assert ac.checkpoint_kind(pure) == "pure"
    assert ac.checkpoint_kind(merged) == "merged"
    out = os.path.join(d, "out.safetensors")
    nkeep, ndrop = ac.strip_to_dit(merged, out, ref_path=pure, logf=lambda *a: None)
    assert (nkeep, ndrop) == (2, 1), (nkeep, ndrop)
    assert ac.checkpoint_kind(out) == "pure"

def test_monitor_sampling_and_fizgig_resume():
    """采样预览进度不污染训练监控（防看门狗误杀）+ Fizgig 断点查找。"""
    import Kohya一键工具 as core
    mon = core.TrainMonitor()
    mon.start(total=3800)
    mon.on_line("steps:   8%| | 304/3800 [00:10<02:00, 4.17s/it, avr_loss=0.1]")
    s1 = mon.snapshot()
    assert s1.get("step") == 304 and s1.get("total") == 3800, s1
    mon.on_line("sampling:  62%| | 5/8 [01:25<00:59, 19.67s/it]")
    s2 = mon.snapshot()
    assert s2.get("step") == 304 and s2.get("total") == 3800, "采样行污染了监控: %s" % s2
    mon.on_line("rendering previews (epoch 2) on the fp8 Turbo...")
    s3 = mon.snapshot()
    assert s3.get("step") == 304, s3
    # 基线/收尾采样（Generating Samples: 0/1 …）同样不能污染步数，且必须推进 last_activity
    #（否则训练 100% 后的收尾采样超过 grace 会被"卡死看门狗"误杀，2026-09 AMD 用户复现）
    import time as _t
    t0 = s3.get("last_activity") or 0
    _t.sleep(0.05)
    mon.on_line("Generating baseline samples before training (step 304)")
    mon.on_line("Generating Samples:   0%|          | 0/1 [00:00<?, ?it/s]")
    s4 = mon.snapshot()
    assert s4.get("step") == 304 and s4.get("total") == 3800, "Generating Samples 污染监控: %s" % s4
    assert (s4.get("last_activity") or 0) > t0, "采样行未记为进程活动（看门狗会误杀）"
    # 断点续训：引擎按“剩余步数”从 0 重数（sd-scripts: range(max-initial)）→ 映射回绝对步
    mon2 = core.TrainMonitor()
    mon2.start(total=2000)
    mon2.set_step(800)
    mon2.on_line("steps:   6%| | 120/1200 [00:20<04:00, 4.17s/it, loss=0.12]")
    s5 = mon2.snapshot()
    assert s5.get("step") == 920 and s5.get("total") == 2000, "续训监控未映射回绝对步: %s" % s5
    mon2.on_line("steps:  50%| | 600/1200 [00:20<04:00, 4.17s/it, loss=0.11]")
    s6 = mon2.snapshot()
    assert s6.get("step") == 1400 and s6.get("total") == 2000, s6
    # Fizgig 断点查找：{name}-NNNNNN-state；有最终 LoRA 视为跑完不提示
    import tempfile, os as _os, json
    d = tempfile.mkdtemp()
    for ep in ("000001", "000002"):
        st = _os.path.join(d, "krea2_fizgig_lora-%s-state" % ep)
        _os.makedirs(st, exist_ok=True)
        with open(_os.path.join(st, "training_state.json"), "w", encoding="utf-8") as f:
            json.dump({"epoch": int(ep), "global_step": int(ep) * 152}, f)
    found = core.find_fizgig_state(d, "krea2_fizgig_lora")
    assert found and found.endswith("krea2_fizgig_lora-000002-state"), found
    open(_os.path.join(d, "krea2_fizgig_lora.safetensors"), "wb").write(b"x")
    assert core.find_fizgig_state(d, "krea2_fizgig_lora") is None, "跑完仍提示续训"
    # 旧成品 + 更新的新断点 → 仍应提示（修 find_fizgig_state 一刀切 bug，2026-09-08）
    st3 = _os.path.join(d, "krea2_fizgig_lora-000003-state")
    _os.makedirs(st3, exist_ok=True)
    with open(_os.path.join(st3, "training_state.json"), "w", encoding="utf-8") as f:
        json.dump({"epoch": 3, "global_step": 456}, f)
    _os.utime(st3, (9000, 9000))
    _os.utime(_os.path.join(d, "krea2_fizgig_lora.safetensors"), (1000, 1000))
    assert core.find_fizgig_state(d, "krea2_fizgig_lora") is not None, "旧成品+新断点未提示续训"
    # kohya/musubi 断点：有 -step…-state 且无成品 → 提示续训；成品已生成 → 不提示
    import tempfile as _tf2, os as _os2
    d2 = _tf2.mkdtemp()
    st2 = _os2.path.join(d2, "character_lora-step00000400-state")
    _os2.makedirs(st2, exist_ok=True)
    assert core.find_latest_state(d2, "character_lora") is not None, "中断点应提示续训"
    _os2.utime(st2, (2000, 2000))
    with open(_os2.path.join(d2, "character_lora.safetensors"), "wb") as f:
        f.write(b"x")
    _os2.utime(_os2.path.join(d2, "character_lora.safetensors"), (3000, 3000))
    assert core.find_latest_state(d2, "character_lora") is None, "跑完仍提示续训(kohya)"
    # 旧成品 + 更新的新中断 → 仍应提示（只看最终成品 vs 断点 mtime）
    _os2.utime(st2, (9000, 9000))
    assert core.find_latest_state(d2, "character_lora") is not None, "旧成品+新中断未提示续训(kohya)"


def test_lora_naming():
    """训练完成按项目名导出成品：挑最新成品、复制为 <项目名>.safetensors、原文件保留。"""
    import tempfile
    from kohya_core import lora_naming as ln

    d = tempfile.mkdtemp()
    for name, m in (("krea2_lora-000006.safetensors", 1000), ("krea2_lora-000008.safetensors", 2000)):
        p = os.path.join(d, name)
        with open(p, "wb") as f:
            f.write(b"\0" * 16)
        os.utime(p, (m, m))
    logs = []
    got = ln.export_project_named_lora("krea2", "测试项目", logf=logs.append, out_dir=d)
    assert got == os.path.join(d, "测试项目.safetensors") and os.path.isfile(got), logs
    assert os.path.isfile(os.path.join(d, "krea2_lora-000008.safetensors"))  # 原文件保留（续训/已完成检测仍认它）


def test_project_data_cleanup():
    """删除项目要能一并清掉图集数据（含打标文件），并能清理已经遗留的孤儿数据。

    2026-09-15 用户反馈：删了项目，打标好的文件还留在磁盘上一直占空间。
    根因：delete_project() 只删 projects/<名>.json，data/dataset/<项目名>/
    （预处理图片 + .txt 打标 + 各引擎缓存）原样留下 —— 而项目一删，
    这批数据再没有任何界面入口能找到它。
    """
    import tempfile
    import shutil
    import Kohya一键工具 as core
    from kohya_core import paths as _P

    tmp = tempfile.mkdtemp()
    _real_data_dir = _P.data_dir
    # ⚠️ 必须改 kohya_core.paths 里的引用：data_sub/projects_dir 等查的是
    # 本模块 globals，改 Kohya一键工具.data_dir 对它们无效（会写进真实数据目录）。
    _P.data_dir = lambda: tmp
    try:
        core.save_project("测试项目", {"name": "测试项目", "mode": "style"})
        ds = core.project_data_dir("测试项目")
        os.makedirs(os.path.join(ds, "train_character"), exist_ok=True)
        for i in range(3):
            open(os.path.join(ds, "train_character", "a%d.png" % i), "wb").write(b"x" * 100)
            open(os.path.join(ds, "train_character", "a%d.txt" % i), "w", encoding="utf-8").write("1girl")
        os.makedirs(os.path.join(ds, "krea2_cache"), exist_ok=True)
        open(os.path.join(ds, "krea2_cache", "c.bin"), "wb").write(b"y" * 50)
        assert core.dir_stats(ds) == (7, 365), core.dir_stats(ds)

        # 复现原问题：删项目后图集数据仍在（既有行为，正是用户踩到的）
        core.delete_project("测试项目")
        assert os.path.isdir(ds), "前置条件不符：删项目后图集数据应仍在"

        # 新函数：清图集数据；output 训练产物不归它管，必须原样保留
        out_d = core.project_output_dir("测试项目")
        os.makedirs(out_d, exist_ok=True)
        open(os.path.join(out_d, "成品.safetensors"), "wb").write(b"z")
        ok, n, b = core.delete_project_data("测试项目")
        assert ok and (n, b) == (7, 365), (ok, n, b)
        assert not os.path.isdir(ds), "图集数据未删净"
        assert os.path.isdir(out_d), "delete_project_data 不该动训练产物目录"
        assert core.delete_project_data("测试项目")[0] is True, "重复删除应幂等"
        assert core.delete_project_data("")[0] is True, "空项目名必须安全返回"

        # ---- 孤儿（已删项目遗留）检测 ----
        os.makedirs(os.path.join(tmp, "dataset", "train_character"), exist_ok=True)   # 旧版共享目录
        os.makedirs(os.path.join(tmp, "dataset", "已删项目", "train"), exist_ok=True)
        open(os.path.join(tmp, "dataset", "已删项目", "train", "x.txt"), "w", encoding="utf-8").write("t")
        core.save_project("活项目", {"name": "活项目"})
        os.makedirs(os.path.join(tmp, "dataset", "活项目", "train_character"), exist_ok=True)
        names = [x[0] for x in core.find_orphan_project_dirs()]
        assert "已删项目" in names, names
        assert "活项目" not in names, "有对应项目的目录被误判成孤儿：%s" % names
        assert "train_character" not in names, "旧版共享目录被误判成孤儿：%s" % names

        ok_n, files, size, failed = core.delete_orphan_project_dirs()
        assert (ok_n, files, size, failed) == (1, 1, 1, []), (ok_n, files, size, failed)
        assert not os.path.isdir(os.path.join(tmp, "dataset", "已删项目"))
        assert os.path.isdir(os.path.join(tmp, "dataset", "活项目")), "误删了活项目的数据"
        assert os.path.isdir(os.path.join(tmp, "dataset", "train_character")), "误删了旧版共享目录"
    finally:
        _P.data_dir = _real_data_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_label_editor_safety():
    """标签批量操作的两道闸：预演（绝不写盘）+ 快照/撤销（字节级还原）。

    2026-09-15 用户反馈：多选标签时忘了按 Ctrl，把前面选择要删的标签也删了。
    根因是批量删除/替换直接覆写全部 .txt，既无确认也无撤销。
    """
    import tempfile
    import shutil
    from pathlib import Path
    import Kohya一键工具 as core
    from kohya_core import paths as _P

    tmp = tempfile.mkdtemp()
    _real_data_dir = _P.data_dir
    _P.data_dir = lambda: tmp          # 与 paths 内部保持一致，别写进真实数据目录
    try:
        ds = os.path.join(tmp, "dataset", "proj", "train_character")
        os.makedirs(ds)
        # ⚠️ list_dataset_images **以图片为驱动**（只遍历图片再配对同名 .txt），
        # 所以只有 .txt 没有配对图片的文件根本不会被列出 —— 每个用例都要有同名图片。
        raw = {                                   # stem -> 原始内容
            "a": "1girl, solo, blue_hair\n",      # 带换行
            "b": "1girl, solo",                   # 无换行
            "c": "solo, blue_hair \n",            # 带尾随空格
        }
        for stem, txt in raw.items():
            open(os.path.join(ds, stem + ".txt"), "w", encoding="utf-8", newline="").write(txt)
            open(os.path.join(ds, stem + ".png"), "wb").write(b"x")
        open(os.path.join(ds, "d.png"), "wb").write(b"x")   # 没有 txt 的图不该被算进去

        def _tp(stem):
            return os.path.join(ds, stem + ".txt")

        def _read(stem):
            return open(_tp(stem), encoding="utf-8", newline="").read()

        # ---- ① dry_run 只统计，绝不写盘 ----
        assert core.batch_remove_tags(ds, "solo", dry_run=True) == (3, 3)
        for stem, txt in raw.items():
            assert _read(stem) == txt, "dry_run 改写了文件 %s" % stem
        assert core.batch_remove_tags(ds, "不存在的标签", dry_run=True) == (0, 0)

        # ---- ② snapshot 记的是原始内容，同时正常写盘 ----
        snap = {}
        assert core.batch_remove_tags(ds, "solo", snapshot=snap) == (3, 3)
        for stem, txt in raw.items():
            assert snap[_tp(stem)] == txt, "快照不是原始内容：%r" % snap.get(_tp(stem))
            assert "solo" not in _read(stem), "没删干净 %s" % stem

        # ---- ③ 撤销：字节级还原（含无换行 / 尾随空格两种形态）----
        assert core.restore_captions(snap) == 3
        for stem, txt in raw.items():
            assert _read(stem) == txt, "撤销未还原 %s -> %r（应为 %r）" % (stem, _read(stem), txt)

        # ---- ④ 替换同样支持预演 + 快照 + 撤销 ----
        assert core.batch_replace_tags(ds, "blue_hair", "aqua_hair", dry_run=True) == 2
        assert _read("a") == raw["a"], "替换的 dry_run 改写了文件"
        snap2 = {}
        assert core.batch_replace_tags(ds, "blue_hair", "aqua_hair", snapshot=snap2) == 2
        assert "aqua_hair" in _read("a")
        assert core.restore_captions(snap2) == 2
        assert _read("a") == raw["a"], "替换的撤销未还原"

        # ---- ⑤ 工具自己写的文件（Windows 上 save_caption 写 CRLF）也必须字节级还原 ----
        # 这条是防回归：_read_caption_raw 若用默认 newline 读，CRLF 会被归一成 LF，
        # 撤销就把整个数据集的行尾悄悄改掉了。
        open(os.path.join(ds, "e.png"), "wb").write(b"x")
        p_e = os.path.join(ds, "e.txt")
        core.save_caption(p_e, "1girl, crlfmarker")
        e_raw = open(p_e, encoding="utf-8", newline="").read()
        snap3 = {}
        assert core.batch_remove_tags(ds, "crlfmarker", snapshot=snap3) == (1, 1)
        assert core.restore_captions(snap3) == 1
        assert open(p_e, encoding="utf-8", newline="").read() == e_raw, \
            "工具自写文件未字节级还原（行尾被改写）"

        # ---- ⑥ 源码接线：GUI 必须真的用了这两道闸 ----
        gsrc = Path(os.path.join(os.path.dirname(core.__file__), "kohya_gui.py")).read_text(encoding="utf-8-sig")
        csrc = Path(core.__file__).read_text(encoding="utf-8-sig")
        assert "dry_run=True" in gsrc, "批量删除/替换没有预演步骤"
        assert gsrc.count("snapshot=snapshot") >= 3, "不是所有不可逆批量操作都留了撤销快照"
        assert "def _push_undo" in gsrc and "def _do_undo" in gsrc, "缺少撤销实现"
        assert "def restore_captions" in csrc, "缺少还原实现"
        # 缩略图不再写死尺寸（用户反馈「太小、下面明明有不少空间」）
        assert "im.thumbnail((220, 140))" not in gsrc, "缩略图仍是硬编码 220x140"
        assert "def _on_right_resize" in gsrc, "缩略图未接自适应"
        # 多选开关：图片列表与标签统计窗都要有，且偏好持久化
        assert "label_editor_multi" in gsrc, "多选偏好未持久化"
        # 两处开关的文案都是纯「多选模式」（用户要求不要多余的括号说明）
        assert gsrc.count('text="多选模式"') >= 2, "图片列表/标签统计窗未都加多选开关"

        # ---- ⑦ 缩略图自适应的三条防回归（2026-09-15 实测踩过的坑，都很隐蔽）----
        import re as _re
        # ① 绑定必须 add="+"：CTkFrame 内部用 <Configure> 维护自己的 canvas/圆角，
        #    直接 bind 会把它顶掉，控件自身就画不出来。
        assert 'self._on_right_resize, add="+"' in gsrc, \
            "自适应绑定没用 add='+'，会覆盖 CTk 控件的内部 <Configure> 处理器"
        # ② _on_right_resize 里绝不许量其它控件的高度 —— 那会成环：
        #    缩略图高度 → body 的请求高度 → 底部工具条能否分到 pack 空间 → 工具条高度
        #    → 预留量 → 缩略图高度…… 实测 40 轮 update 触发回调 566 次（死循环），
        #    布局整体崩坏、工具条 unmapped，表现为「标签编辑器功能组件全没了」。
        _m = _re.search(r"    def _on_right_resize\(self.*?\n(?=    def )", gsrc, _re.S)
        assert _m, "找不到 _on_right_resize 实现"
        _body = _m.group(0)
        # 唯一允许的输入是**窗口自身**的尺寸；把窗口测量摘掉后，不应再有别的尺寸测量
        _stripped = (_body.replace("self.win.winfo_width()", "")
                          .replace("self.win.winfo_height()", ""))
        for _bad in ("winfo_width()", "winfo_height()", "winfo_reqheight()"):
            assert _bad not in _stripped, \
                "_on_right_resize 里量了其它控件的 %s —— 会形成布局死循环，绝不能加回来" % _bad
        # ③ 缩略图容器必须是原生 tk.Frame：CTkFrame 是复合控件，
        #    pack_propagate(False) 转发不到内部 canvas，实测设 1236x700 仍被撑到 1248x1017。
        assert "self.prev_box = tk.Frame(" in gsrc, "缩略图容器不是原生 tk.Frame（propgate 不生效）"
        assert "self.prev_box.pack_propagate(False)" in gsrc, "缩略图容器未禁止尺寸传播"
    finally:
        _P.data_dir = _real_data_dir
        shutil.rmtree(tmp, ignore_errors=True)


def test_home_output_button():
    """主页要有直达「输出目录」的入口，且打开目录的路径必须健壮。

    2026-09-16 用户反馈：想看训练出来的 LoRA，必须先打开某个项目，
    或者自己去 %APPDATA%\\KohyaLoraTool\\output 里翻，很费劲。

    两个关键点：
      ① 主页入口给的是**输出根目录**（不是某个项目）—— 一次看到全部项目，
         这才真正免除「先点开之前的项目」；
      ② 打开目录不能裸调 os.startfile —— 从没训练过时目录根本不存在，会静默失手。
    """
    from pathlib import Path
    import Kohya一键工具 as core
    gsrc = Path(os.path.join(os.path.dirname(core.__file__), "kohya_gui.py")).read_text(encoding="utf-8-sig")

    # 1) 主页头部有这个按钮，绑到输出根目录入口，并登记进 _home_widgets（否则切页会残留）
    i = gsrc.find("def _build_home(self)")
    j = gsrc.find("def _show_home(self)")
    assert i != -1 and j > i, "找不到 _build_home / _show_home"
    head = gsrc[i:j]
    assert "self.btn_output_dir = ctk.CTkButton(" in head, "主页头部缺少「输出目录」按钮"
    assert "command=self.cmd_open_output_root" in head, "主页按钮未绑定到输出根目录入口"
    assert "self._home_widgets.append(self.btn_output_dir)" in head, "按钮未登记进主页组件"

    # 2) 打开目录必须「先建目录 + 失败有提示」
    k = gsrc.find("def _open_dir_or_warn(self")
    assert k != -1, "缺少健壮的打开目录封装 _open_dir_or_warn"
    body = gsrc[k:k + 900]
    assert "os.makedirs(d, exist_ok=True)" in body, "打开前未确保目录存在（从没训练过会失手）"
    assert "messagebox.showerror(" in body, "打开失败未提示用户"

    # 3) 两个入口语义必须不同：主页 = 输出根目录；工作区 = 当前项目
    a = gsrc.find("def cmd_open_output_root(self")
    assert a != -1, "缺少 cmd_open_output_root"
    assert 'core.data_sub("output")' in gsrc[a:a + 800], "主页入口未指向输出根目录"
    b = gsrc.find("def cmd_open_output(self")
    assert b != -1, "缺少 cmd_open_output"
    assert 'core.data_sub("output", self.current_project)' in gsrc[b:b + 800], \
        "工作区入口未指向当前项目"

    # 4) 旧的裸 startfile 必须已消除（没 try/except，失败就静默）
    assert 'os.startfile(core.data_sub("output"))' not in gsrc, "仍残留裸 startfile"
    print("HOME_OUTPUT_BUTTON_OK")


def test_preprocess_progress():
    """预处理要有真实进度可看（WD14 打标是预处理里最长的一段）。

    2026-09-16 用户反馈：预处理期间界面没有进度反馈，总怀疑「是不是卡住了」。
    预处理跑在**子进程**（`preprocess.py`）里，父进程拿不到任何回调 ——
    唯一的信息通道是它的 stdout，所以解析 `[WD14] 内置打标进度：done/total`。

    三条必须守住的边界（写错了比不做更糟）：
      ① 别的阶段的日志（训练步数 / 下载字节 / 缓存 tqdm）**绝不能被当成预处理进度**
         —— 否则进度条会乱跳；
      ② 官方打标脚本走 tqdm（`\\r` 原地刷新、行里没有 N/M）时**不能假装 0% 进度**，
         只能报「阶段已开始 + 已运行多久」；
      ③ 两处调用点都要接 —— 单独「数据预处理」和「一键开始训练」里的自动预处理，
         不接的话「一键」反而更让人干等。
    """
    from pathlib import Path
    import Kohya一键工具 as core

    # ---- ① 解析真实进度行（preprocess.py 逐字） ----
    m = core.PreprocessMonitor()
    assert m.feed("[WD14] 内置打标进度：120/450（已写 120 张）") is True
    s = m.snapshot()
    assert (s["done"], s["total"]) == (120, 450), s
    assert s["stage"] == "内置打标", s["stage"]
    assert s["running"] is True
    m2 = core.PreprocessMonitor()          # 半角冒号也要认
    assert m2.feed("[WD14] 内置打标进度: 7/9") is True
    assert m2.snapshot()["total"] == 9
    m2b = core.PreprocessMonitor()          # 整块传入（兼容 chunk）
    assert m2b.feed("[预处理] x\n[WD14] 内置打标进度：5/80（已写 5 张）") is True
    assert m2b.snapshot()["total"] == 80

    # ---- ② 无关日志绝不能驱动（否则进度条乱跳） ----
    m3 = core.PreprocessMonitor()
    for junk in ("[训练] steps: 5%| 51/1024 [01:00<19:00, 2.10s/it]",
                 "[下载] 12.3 MB / 45.6 MB",
                 "caching latents: 20/20",
                 "[OK] 预处理完成"):
        assert m3.feed(junk) is False, "无关日志被当成预处理进度：%s" % junk
    s3 = m3.snapshot()
    assert s3["running"] is False and (s3["done"], s3["total"]) == (0, 0), s3
    assert m3.feed("") is False and m3.feed(None) is False

    # ---- ③ 官方脚本路径：在动、但无数字（不许假装 0%） ----
    m4 = core.PreprocessMonitor()
    assert m4.feed("[WD14] 使用官方打标脚本: /a/b/wd14.py") is True
    s4 = m4.snapshot()
    assert s4["running"] is True and s4["total"] == 0, s4

    # ---- ④ 完成行把进度补满（末批不足 5 张时不会打最后一条进度行） ----
    m5 = core.PreprocessMonitor()
    m5.feed("[WD14] 内置打标进度：9/12（已写 9 张）")
    m5.feed("[WD14] 内置打标完成：为 12 张图片生成标签")
    assert m5.snapshot()["done"] == 12, m5.snapshot()

    # ---- ⑤ GUI 接线 ----
    g = Path(os.path.join(os.path.dirname(core.__file__), "kohya_gui.py")).read_text(encoding="utf-8-sig")
    assert "def _begin_preprocess_progress" in g and "def _end_preprocess_progress" in g, "缺少预处理进度开关"
    assert "def _render_preprocess_progress" in g, "界面没有渲染预处理进度"
    assert g.count("_pp_log = self._begin_preprocess_progress()") >= 2, \
        "预处理进度只接了一处（单独预处理 / 一键训练里的自动预处理都要有）"
    assert g.count("self._end_preprocess_progress()") >= 2, "预处理结束后没有撤掉进度监控"
    tw = g[g.find("def _train_worker"):]
    assert "self._pp_mon = None" in tw[:700], "训练开始未清掉预处理监控（会闪旧进度）"
    assert 'text="📊 训练监控"' in tw[:1000], "训练开始未把面板标题拨回训练语义"
    print("PREPROCESS_PROGRESS_OK")


def test_python_env_source_guard():
    """建训练环境必须校验 Python 来源；状态徽章必须如实显示实际版本。

    2026-09-16 qiansui 用户实测链条：
      · 机器上只有 Anaconda 自带的 Python 3.11.7；
      · 工具用它建了训练环境（版本在允许范围内 → 直接采用，从不看来源）；
      · 打标 / 训练里的原生库接连 0xC0000005（conda 的 native DLL 污染）；
      · 他按别的建议「屏蔽 Anaconda」→ 训练环境立刻报「损坏、找不到 python 路径」
        （因为 venv 的基座就是 conda）；
      · 最后装官方 Python + 重下训练内核才好 —— 正是工具日志里早就写着的那条路。
    """
    from pathlib import Path
    import Kohya一键工具 as core

    # ① 来源识别
    for p in (r"C:\Software\anaconda3\python.EXE", r"D:\miniconda3\python.exe",
              r"C:\Users\a\Miniforge3\python.exe", r"C:\ProgramData\Anaconda3\python.exe"):
        assert core._python_is_conda(p) is True, "没认出 conda 来源：%s" % p
    for p in (r"C:\Python312\python.exe",
              r"C:\Users\a\AppData\Local\Programs\Python\Python312\python.exe"):
        assert core._python_is_conda(p) is False, "误判为 conda：%s" % p
    assert core._python_is_conda(None) is False
    assert core._python_is_conda("") is False

    # ② 建环境时不能「默默采用」conda 的解释器
    _src = Path(core.__file__).read_text(encoding="utf-8-sig")
    _k = _src.index("def install_python(")
    _body = _src[_k:_src.index("\ndef ", _k + 10)]
    assert "_python_is_conda(py)" in _body, "install_python 未校验 Python 来源"
    assert "and not _conda" in _body, "install_python 仍会直接采用 conda 的解释器"
    assert "Anaconda" in _body, "缺少对 Anaconda 的说明文案"

    # ③ 徽章必须显示**实际**版本，不能写死 3.12
    st = core.system_status(force=True)
    assert "python_conda" in st, "system_status 未暴露 python 来源"
    assert "python_path" in st, "system_status 未暴露 python 路径"
    _g = Path(os.path.join(os.path.dirname(core.__file__), "kohya_gui.py")).read_text(encoding="utf-8-sig")
    assert '"● Python 3.12"' not in _g, \
        "徽章又写死成 Python 3.12 了（用户会误以为自己环境符合要求）"
    assert "python_conda" in _g and "Anaconda ⚠" in _g, "徽章未如实显示 conda 来源"
    print("PYTHON_ENV_SOURCE_GUARD_OK")


def test_native_crash_diagnosis():
    """训练侧必须能识别 native 崩溃（0xC0000005），并给出可执行的排查步骤。

    2026-09-16 qiansui 用户的训练失败：`anima_train_network.py` 原生崩溃、**零输出**，
    accelerate 把它转成退出码 1 → 工具只报「训练结束，退出码 1，请查看上方日志」。
    而 `3221225477` 在全代码库 **0 命中** —— 工具根本不认识这个错误码。
    """
    from pathlib import Path
    import Kohya一键工具 as core

    # ① 真实的失败文本（accelerate traceback 片段）必须命中
    tail = ["The following values were not passed to `accelerate launch` and had defaults used instead:",
            "\t`--mixed_precision` was set to a value of 'no'",
            "Traceback (most recent call last):",
            "subprocess.CalledProcessError: Command '[...anima_train_network.py...]'"
            " returned non-zero exit status 3221225477."]
    out = []
    assert core._diagnose_native_crash("\n".join(tail), logf=out.append) is True, "未识别 native 崩溃"
    blob = "\n".join(out)
    for kw in ("0xC0000005", "Anaconda", "vc_redist", "重复训练不会变好"):
        assert kw in blob, "诊断缺少关键信息 %s：%s" % (kw, blob)
    assert core._diagnose_native_crash("exit code 0xC0000005", logf=lambda s: None) is True

    # ② 无关日志不得误报（OOM/普通报错不是 native 崩溃，修法完全不同）
    for junk in ("[训练] steps: 5%| 51/1024 [01:00<19:00, 2.10s/it]",
                 "RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB",
                 "ImportError: No module named 'cv2'", ""):
        assert core._diagnose_native_crash(junk, logf=lambda s: None) is False, \
            "无关日志被误判为 native 崩溃：%r" % junk

    # ③ 必须接在所有训练失败点的公共入口上（否则六条路径里只有一条有诊断）
    _src = Path(core.__file__).read_text(encoding="utf-8-sig")
    _k = _src.index("def _diagnose_optimizer_failure(")
    assert "_diagnose_native_crash(log_text, logf)" in _src[_k:_k + 900], \
        "native 崩溃诊断没接在 _diagnose_optimizer_failure 上"

    # ④ 换源重试不能用「失败」二字（用户会以为整体失败了），且结束要有结论
    assert "当前镜像下载失败" not in _src, "换源提示仍写「失败」（会误导用户以为整体失败）"
    assert "[Anima] ✓ 文本编码器已就绪" in _src, "Anima 下载完没有明确结论"
    print("NATIVE_CRASH_DIAGNOSIS_OK")


def test_high_coverage_tag_lock():
    """标签统计：高覆盖率特征要能提醒 + 手动锁进固定前缀。

    2026-09-16 用户实测：他的角色特征 `green hair` 是 20/21（95%）、`witch hat` 是
    17/21（81%），全都够不着强绑定的 **100%** 门槛 → 自动锁定永远拿不到它们 →
    单写触发词唤不出角色（他自己手动补上 `green hair` 就"非常像"）。

    所以标签统计里要有两样：**覆盖率提醒** + 一个把选中标签**锁进固定前缀**的入口。
    """
    from pathlib import Path
    import Kohya一键工具 as core

    _base = os.path.dirname(core.__file__)
    g = Path(os.path.join(_base, "kohya_gui.py")).read_text(encoding="utf-8-sig")
    # ① 覆盖率：必须真的去数图片总数
    assert "core.count_images(self.train_dir)" in g, "统计窗未取图片总数（算不出覆盖率）"
    assert "未锁定" in g, "统计窗未标出「高覆盖但未锁定」的标签"
    assert "def _stats_lock_to_prefix" in g, "缺手动锁定入口"
    assert "_btn_lock" in g, "锁定按钮未挂到窗口上（不便验证与扩展）"
    # ② 必须说清代价：锁了以后固定出现 + 要重跑预处理才生效
    _k = g.index("def _stats_lock_to_prefix")
    _body = g[_k:_k + 2600]
    assert "固定出现" in _body, "确认框没说「锁进去的特征会固定出现」（锁了帽子就脱不掉）"
    assert "重跑" in _body, "确认框没说要重跑预处理才生效"
    assert "_push_undo" in _body, "手动锁定没有留撤销快照（写坏了没法还原）"

    # ③ 核心函数：走 ||| 手动固定区（复用已有且已有测试覆盖的机制）
    _c = Path(core.__file__).read_text(encoding="utf-8-sig")
    assert "def lock_tags_to_prefix(" in _c, "缺核心锁定函数"
    assert "_FIXED_SEP" in _c, "未使用 ||| 手动固定区分隔符"

    # ④ 强绑定没锁到特征时不能静默（否则用户只能猜"是不是不生效"）
    _p = Path(os.path.join(_base, "preprocess.py")).read_text(encoding="utf-8")
    assert "没有可锁定的特征" in _p, "强绑定没锁到特征时又静默了（用户无从查证）"
    assert "★ 锁进固定前缀" in _p, "强绑定的提示没有指向界面入口"
    # ⑤ 覆盖率不足的告警不能说成"数据集不一致" —— 真实原因常是**视角遮挡让自动打标漏标**
    #    （2026-09-16 用户实测：21 张里有背面/侧身图，双马尾 twintails 只有 20/21，
    #     而它确实是角色的固定特征。旧文案"人物一致性不足，建议统一训练集特征"
    #     会把人引去改数据集甚至删掉侧身图，而且根本修不了"打标器看不到"这件事。）
    #    注：这里用**正向断言** —— 代码注释里会引用旧文案做历史说明，负向断言会误报。
    assert "视角遮挡" in _p and "打标漏标" in _p, "缺「视角遮挡导致自动打标漏标」的说明"
    assert "打开「标签统计」" in _p, "告警没有给出可执行的下一步"
    # 统计窗文案用的是「侧身 / 背面图容易让自动打标漏标」——断言跟着实际用词走
    assert "漏标" in g and "侧身" in g, "统计窗说明未解释「侧身/背面图会被漏标」"
    print("HIGH_COVERAGE_TAG_LOCK_OK")


def test_anima_component_picker():
    """Anima 的文本编码器 / VAE 要能「指定已有文件」，且查找优先用它。

    2026-09-16 用户反馈：他本机已经有 Anima 的模型，但工具只在 3 个固定 APPDATA 目录里
    按**精确目录名**找（Qwen3-0.6B / Anima_vae），找不到就直接下载
    （Qwen3 1.2GB + VAE 0.3GB，国内约 1.3MB/s ≈ 20 分钟）。
    日志实证确实走了下载（`[Anima] 从魔搭下载 Qwen3-0.6B/…`）——
    文件他早就有了，白等一场。
    """
    import tempfile
    from pathlib import Path
    import Kohya一键工具 as core

    td = tempfile.mkdtemp(prefix="kk_anima_t_")
    q3 = os.path.join(td, "Qwen3-0.6B")
    os.makedirs(q3, exist_ok=True)
    # ⚠️ 2026-09-20：config.json 必须写成**真实的 Qwen3 配置**（含 model_type）✗
    #    以前写 "{}" 也能过，但那正是用户踩的坑：
    #      ComfyUI models 大目录里恰有个缺 model_type 的 config.json →
    #      旧校验只数权重个数 → 放行 → 训练时报
    #      「Unrecognized model … Should have a model_type key in its config.json」✗
    with open(os.path.join(q3, "config.json"), "w", encoding="utf-8") as _f:
        _f.write('{"model_type": "qwen3", "architectures": ["Qwen3ForCausalLM"]}')
    open(os.path.join(q3, "model.safetensors"), "wb").write(b"\x00" * 16)
    bad = os.path.join(td, "model.safetensors (1).safetensors")
    open(bad, "wb").write(b"\x00" * 16)
    nodir = os.path.join(td, "empty")
    os.makedirs(nodir, exist_ok=True)
    vae = os.path.join(td, "qwen_image_vae.pth")
    open(vae, "wb").write(b"\x00" * 16)

    # ① 校验必须前置（选的时候就拦住，而不是等训练时炸）
    assert core._anima_component_ok("qwen3", q3)[0] is True
    ok, why = core._anima_component_ok("qwen3", bad)
    assert ok is False and "标准名" in why, why
    assert core._anima_component_ok("qwen3", nodir)[0] is False
    assert core._anima_component_ok("vae", td)[0] is False        # VAE 必须是文件
    assert core._anima_component_ok("vae", vae)[0] is True       # .pth 合法
    assert core._anima_component_ok("vae", os.path.join(td, "没有这个文件"))[0] is False

    # ② 查找优先级：手动指定 > 目录扫描（这是整件事的关键，写反了等于没做）
    _src = Path(core.__file__).read_text(encoding="utf-8-sig")
    _k = _src.index("def _anima_find_qwen3_any(")
    assert '_manual = anima_get_component("qwen3")' in _src[_k:_k + 700], \
        "Qwen3 查找未优先用手动指定的路径"
    _v = _src.index("vae_dir = os.path.join(base, \"Anima_vae\")")
    assert 'vae_file = anima_get_component("vae")' in _src[_v:_v + 500], \
        "VAE 查找未优先用手动指定的路径"

    # ③ 顺带修的：VAE 完整性校验必须限定 .safetensors（否则合法 .pth 被误报"损坏"）
    assert 'if vae_file.lower().endswith(".safetensors") and not _safetensors_complete(vae_file):' in _src, \
        "VAE 完整性校验未限定 .safetensors（.pth 会被误报成损坏）"

    # ④ 界面：Anima 分支要开真对话框（messagebox 放不下按钮），且带选择入口
    g = Path(os.path.join(os.path.dirname(core.__file__), "kohya_gui.py")).read_text(encoding="utf-8-sig")
    assert 'if bt == "anima":' in g and "self._show_anima_components()" in g, \
        "Anima 指引未改走组件对话框"
    # 注意：不能写 "def _show_anima_components(self)"（带右括号）——
    # 该方法现在签名是 (self, wait=False)，带括号的串根本不存在。
    assert "def _show_anima_components(self" in g, "缺少 Anima 组件对话框"
    _d = g[g.index("def _show_anima_components(self"):]
    _d = _d[:_d.index("\n    def ", 10)]
    assert "core.anima_set_component" in _d, "对话框未写回指定的路径"
    assert "选文件夹" in _d and "选文件" in _d, "对话框缺少选择入口"
    assert "_refresh_anima" in _d, "对话框没有状态刷新（指定后看不到变化）"

    # ⑤ 入口必须够得着：原先只挂在「没有模型？点这里下载」里，
    #    已有底模的用户**根本不会点那里** ✗ —— 所以要在训练前拦一道。
    assert "def _anima_components_preflight(self" in g, "缺少训练前预检"
    _p = g[g.index("def _anima_components_preflight(self"):]
    _p = _p[:_p.index("\n    def ", 10)]
    assert "if _q and _v:" in _p and "_modal(" in _p, \
        "预检未做到「两个都齐时静默通过、否则先问一句」"
    # 训练必须先等用户选完再开跑（少这一句 = 用户还没选，训练已经开始下载了）
    assert "_show_anima_components(wait=True)" in _p, "预检未阻塞等待用户选择"
    assert "w.wait_window()" in g, "对话框不支持阻塞等待"
    assert g.count("self._anima_components_preflight(params)") >= 2, \
        "预检只接了一处（一键开始训练 / 开始训练 都要有）"
    print("ANIMA_COMPONENT_PICKER_OK")


def test_label_undo_stack():
    """撤销必须能**连退多步**。

    2026-09-16 用户反馈：「这个撤销只能按一次啊，锁定两个之后第一个就改不了了」——
    原实现是**单槽快照**（self._undo = None）：第二次批量操作直接把第一次的快照覆盖掉，
    于是只能退一步，用户连锁两个特征后第一个再也回不去 ✗

    栈语义：每项存的是「**该次操作前**这些 .txt 的原文」，从栈顶往回退即可逐步还原。
    这里既查实现（必须是栈 + 退完一步还留着按钮可用），也在核心层跑一遍逆序还原，
    确认「连撤两步 == 回到原文」这个真正被用户感知的性质成立。
    """
    import tempfile
    import shutil
    from pathlib import Path
    import Kohya一键工具 as core
    from kohya_core import paths as _P

    g = Path(os.path.join(os.path.dirname(core.__file__), "kohya_gui.py")).read_text(encoding="utf-8-sig")
    assert "self._undo = []" in g, "撤销仍是单槽（第二次操作会覆盖第一次）"
    assert "_UNDO_MAX" in g, "撤销栈没有上限（连续大批量操作会一直堆积）"
    _p = g[g.index("def _push_undo(self"):]
    _p = _p[:_p.index("\n    def ", 10)]
    assert "self._undo.append(" in _p, "新快照没有入栈"
    assert "del self._undo[0]" in _p, "超上限时没有丢最旧的"
    _u = g[g.index("def _do_undo(self"):]
    _u = _u[:_u.index("\n    def ", 10)]
    assert "self._undo[-1]" in _u and "self._undo.pop()" in _u, "撤销没按栈顶弹出"
    assert 'state=("normal" if self._undo else "disabled")' in _u, \
        "撤销后一律禁用按钮（退一步就点不动了 —— 正是用户报的现象）"

    # 行为：两次操作各留快照，按逆序还原必须回到原文
    tmp = tempfile.mkdtemp()
    _real = _P.data_dir
    _P.data_dir = lambda: tmp
    try:
        ds = os.path.join(tmp, "dataset", "proj", "train_character")
        os.makedirs(ds)
        orig = {"a": "1girl, solo, blue_hair\n", "b": "1girl, solo, blue_hair\n"}
        for s, t in orig.items():
            open(os.path.join(ds, s + ".txt"), "w", encoding="utf-8", newline="").write(t)
            open(os.path.join(ds, s + ".png"), "wb").write(b"x")   # 列表以图片为驱动
        s1 = {}
        core.batch_remove_tags(ds, "solo", snapshot=s1)            # 第 1 步
        s2 = {}
        core.batch_remove_tags(ds, "blue_hair", snapshot=s2)       # 第 2 步
        _p1 = os.path.join(ds, "a.txt")
        assert open(_p1, encoding="utf-8").read().strip() == "1girl"
        core.restore_captions(s2)                                  # 撤销第 2 步
        assert open(_p1, encoding="utf-8").read().strip() == "1girl, blue_hair"
        core.restore_captions(s1)                                  # 撤销第 1 步
        got = open(_p1, encoding="utf-8").read()
        assert got == orig["a"], repr(got)
    finally:
        _P.data_dir = _real
        shutil.rmtree(tmp, ignore_errors=True)
    print("LABEL_UNDO_STACK_OK")


def test_krea2_warmup_notice():
    """Krea2(Fizgig) 必须提前说明「前 2 个 epoch 是预热期」。

    2026-09-17 多用户反馈「Krea2 训练速度降低」（4090：一秒多/步 → 3 秒；5070 Ti：5s → 8.8s）。
    复盘两份用户日志后确认的机制：**引擎自己就打印了预热说明** ——
      INFO:fizgig.krea2.trainer:[warm-up] Warm-up phase — the first two epochs start slowly
      while the GPU plans kernels and fills its caches.
    实测步速在预热期是 7.38 → 7.74 → 7.87 → 7.95 → 8.00 → 8.06 **逐步爬升**；
    而工具此前只写「5s/it 左右步速正常」✗ → 用户在预热期看到 7~8s/it，必然误判成「变慢了」✗；
    且日志显示用户两次都在 33 步（第一个存档点之前）就停 → **重开又回到预热** ✗，
    怎么试看到的都是慢的那一段 ✓ 必须提前说清楚。
    """
    from pathlib import Path
    import Kohya一键工具 as core      # noqa: E402
    src = Path(core.__file__).read_text(encoding="utf-8-sig")
    assert "前 2 个 epoch" in src and "预热阶段" in src, "缺少 Krea2 预热期说明"
    _i = src.index("前 2 个 epoch 是**预热阶段**")
    assert "warm-up" in src[max(0, _i - 700):_i + 700].lower(), \
        "预热说明没有引用引擎原文 —— 属于凭猜，不是证据"
    assert "重新预热" in src, "没说明「中途停止重开会重新预热」（用户就是栽在这里）"
    # ★ 不得写"未经证实的应然速度"（例如「稳态 5s/it 正常」）——
    # 工具里原有的「5s/it 左右步速正常」就是这么来的 ✗，而它**当初怎么测出来的已不可考** ✗，
    # 结果用户拿它当标尺、看到 7~8s 就以为坏了 ✗ 这种数字没验证过就不该写进日志。
    _seg = src[src.index("[Krea2(Fizgig)] ⚠ 前 2 个 epoch"):]
    _seg = _seg[:_seg.index('")')]
    assert "s/it" not in _seg, "预热提示里写了具体 s/it 数字 —— 未经验证的应然速度会误导用户"
    # 内存提示不能再说「已自动降低块交换数」：该函数体里**只有这条日志、没有任何调整动作** ✗
    # 注意只看**函数体**：注释里为了说明来龙去脉仍会引用这句旧文案，
    # 直接对全文断言会误判（本轮就又踩了一次「断言太字面」✗）。
    _w = src.index("def _warn_low_ram(")
    _body = src[_w:_w + src[_w:].index("\n\n\n")]
    # 只看**代码行**（去掉注释行）：注释里会引用旧文案来说明来龙去脉 ✓
    _code = "\n".join(_l for _l in _body.splitlines() if not _l.strip().startswith("#"))
    assert "已自动降低块交换数" not in _code, \
        "内存提示又在说假动作（并未真的调整参数）—— 会让人把变慢归因到没发生的事"
    assert "请把「块交换(blocks_to_swap)」调小" in _body, "内存提示没给出可执行建议"
    print("KREA2_WARMUP_NOTICE_OK")


def test_krea2_auto_quant_is_int8():
    """Krea2 的 auto 档必须走 int8 —— fp8 在 K2 上是**灾难档** ✗。

    2026-09-17 用户汇总实测（512px）：
        · 4090 24G：fp8 7 s/步 → int8 **1 s/步**（7×）
        · 16G 卡  ：fp8 50~100 s/步 → int8 **2.2 s/步**（25~45×）
    根因：K2 的 fp8 路径**没用上 scaled_mm**（per-channel 量化与它不兼容，强开会 raise，
    见 `_patch_musubi_fp8_scaled_mm`），每次前向要反量化回 bf16；块交换越多越惨。
    官方数据同向：3090 上 fp8 7.1 vs convrot_int8 5.3；Blackwell 上 bf16 2.0 快过 fp8 2.3。
    """
    import Kohya一键工具 as core      # noqa: E402

    # ① 两个引擎的 auto 档，只要不是低显存，都必须走 int8
    for _v in (12, 16, 24, 47.48):
        _q, _d = core._resolve_quant_mode(None, lambda s: None, _v, requested="auto")
        assert _q == "int8", "%.0fG 的 auto 档没走 int8（得到 %s）" % (_v, _q)
        _f, _s, _dd = core._fizgig_quant_swap(_v, "auto")
        assert _f == ["--quant_int8", "bf16"], \
            "Fizgig %.0fG 的 auto 档没走 int8（得到 %s）" % (_v, _f)
        # ⚠️ swap 必须**沿用该档位原值**，不能顺手改 0：16G 档靠块交换才跑得起来，
        # 改成 0 会 OOM。这里就是最初写错、被 engine 套件拦下的地方 ✓
        _expect_swap = 0 if _v >= 32 else (12 if _v >= 24 else (20 if _v >= 16 else 26))
        assert _s == _expect_swap, \
            "%.0fG 的 swap 应保持档位原值 %s，得到 %s" % (_v, _expect_swap, _s)

    # ② 低显存仍以显存优先：<10G 走 NF4（不能因为提速把兜底弄丢）
    assert core._fizgig_quant_swap(8, "auto")[0] == ["--quantize_4bit"], "8G 档的 NF4 兜底被破坏"

    # ③ 显式选择必须仍被尊重 —— 老项目存档里可能就存着 fp8，不能静默改掉
    assert core._fizgig_quant_swap(24, "fp8")[0] == [], "显式 fp8 被静默改成了别的档"
    assert core._resolve_quant_mode(None, lambda s: None, 24, requested="fp8")[0] == "fp8", \
        "musubi 的显式 fp8 被静默改掉"
    assert core._resolve_quant_mode(None, lambda s: None, 24, requested="int8")[0] == "int8"

    # ④ 显式 fp8 必须带实测代价 —— 否则老用户不知道自己还踩在慢档上
    assert "慢" in core._fizgig_quant_swap(24, "fp8")[2], "Fizgig 显式 fp8 没给出实测代价"
    assert "慢" in core._resolve_quant_mode(None, lambda s: None, 24, requested="fp8")[1], \
        "musubi 显式 fp8 没给出实测代价"

    # ⑤ 底模已预量化时不做工具侧量化（原有行为不能丢）
    assert core._resolve_quant_mode(None, lambda s: None, 24, requested="auto",
                                    prequantized=True)[0] == "none", "预量化底模被重复量化"
    print("KREA2_AUTO_QUANT_OK")


def test_wd14_model_selectable():
    """WD14 打标模型必须「可选 + 缺失时静默回默认」—— 这就是老用户无缝、新用户无感的关键。

    2026-09-17 变更：模型不再内置（内含 311MB onnx，发布包 562MB / 安装包 488MB，
    分发吃力）→ 改为首次使用时下载（魔搭优先 → hf-mirror 兜底）。
    社区主流是 swinv2-v3（月下载约 70 万，是旧版 moat-v2 的数千倍，标签库更新到 2024-02）。
    """
    import preprocess as P      # noqa: E402

    # ① 缺失 / 空 / 垃圾值 → 一律静默落默认，**绝不抛异常**
    #    （老用户升级后项目里没有这个键，走的就是这条路 ✓）
    for _bad in (None, "", "   ", "不存在的模型", "Auto"):
        _k, _r = P.resolve_wd14_model(_bad)
        assert _k == P.WD14_DEFAULT_MODEL, "%r 没落到默认模型（得到 %s）" % (_bad, _k)
        assert _r == P.WD14_MODELS[P.WD14_DEFAULT_MODEL], "默认模型 repo 不对"
    # ② 用户显式选择必须被尊重（含切回旧模型）
    assert P.resolve_wd14_model("moat-v2")[0] == "moat-v2", "显式选旧模型被改掉"
    assert P.resolve_wd14_model("swinv2-v3")[0] == "swinv2-v3"
    # ③ 默认必须是社区主流的 swinv2-v3
    assert P.WD14_DEFAULT_MODEL == "swinv2-v3", "默认模型被改动"
    # ④ 两个模型的目录名互不相同 → 天然共存，互不覆盖
    _dirs = {P._wd14_repo_dirname(r) for r in P.WD14_MODELS.values()}
    assert len(_dirs) == len(P.WD14_MODELS), "两个模型的目录名冲突，会互相覆盖"
    # ⑤ 下载源策略：魔搭优先（hf 作兜底）—— 魔搭 URL 必须指向本项目仓库
    assert P.WD14_MS_REPO in P.WD14_MS_BASE, "魔搭下载源没指向本项目仓库"
    assert "wd14_models" in P.WD14_MS_BASE, "魔搭路径与上传位置不一致"
    # ⑥ 命令行参数必须存在且**不用 choices**（未知值要静默回默认，而不是 argparse 报错退出）
    _src = open(os.path.join(ROOT, "preprocess.py"), encoding="utf-8").read()
    assert '"--wd14-model"' in _src, "缺少 --wd14-model 参数"
    _line = [l for l in _src.splitlines() if '"--wd14-model"' in l][0]
    assert "choices=" not in _line, "用了 choices → 未知值会让 argparse 直接报错退出（破坏无缝）"
    print("WD14_MODEL_SELECTABLE_OK")


def test_close_confirm_while_running():
    """训练/安装进行中关闭窗口必须**先确认**——误点关闭会直接终止任务、白跑几小时。

    2026-09-17 用户反馈：「软件没有关闭提醒，如果在训练不小心误关，会直接停掉」。
    以前 `_on_close` 是「保存配置 → 直接 destroy()」✗，训练在跑也照关不误。

    这里**真跑行为**（用假 self 直接调 `_on_close`），而不是查源码里有没有某句文案 ✗。
    """
    import kohya_gui as G      # noqa: E402
    import Kohya一键工具 as core      # noqa: E402
    from tkinter import messagebox as MB

    class _Root:
        def __init__(self):
            self.destroyed = False

        def destroy(self):
            self.destroyed = True

    def _make(busy):
        class _Fake:
            def __init__(self):
                self.busy = busy
                self._task_title = "一键开始训练" if busy else ""
                self.current_project = None
                self.ui_proc = None
                self.root = _Root()

            def _autosave(self):
                pass

            def _task_running(self):
                # 直接用真实实现的语义（busy 或底层有活跃子进程），但底层探测在本测试里
                # 不依赖真实进程 —— 单测不该去问系统
                return bool(self.busy)

        return _Fake()

    _real_ask = MB.askyesno
    _real_stop = core.stop_active_process
    _stops = []
    try:
        # ⚠️ 必须把 stop_active_process 打桩：它会 set 全局 _STOP_EVENT，
        # 真跑一次会把**同一个测试进程里后续的 run_stream 全部带停** ✗
        core.stop_active_process = lambda: _stops.append(1)
        # ① 有任务 + 用户选「否（继续跑）」→ **窗口不能关**，也不能停任务
        _f = _make(True)
        MB.askyesno = lambda *a, **k: False
        G.App._on_close(_f)
        assert _f.root.destroyed is False, "选了「不关」，窗口却关了"
        assert not _stops, "选了「不关」，任务却被停了"
        # ② 有任务 + 用户选「是（仍要关）」→ 关窗 **且主动停任务**
        _f2 = _make(True)
        MB.askyesno = lambda *a, **k: True
        G.App._on_close(_f2)
        assert _f2.root.destroyed is True, "确认关闭后窗口没关"
        assert _stops, "确认关闭时没有主动停止任务（只 destroy 会让子进程管道断裂）"
        # ③ 没有任务 → **不打扰**，直接关（不能给每次正常退出都弹框）
        _called = {"n": 0}

        def _count(*a, **k):
            _called["n"] += 1
            return True

        _f3 = _make(False)
        MB.askyesno = _count
        G.App._on_close(_f3)
        assert _f3.root.destroyed is True, "空闲时关不掉"
        assert _called["n"] == 0, "空闲退出也弹了确认框（打扰）"
    finally:
        MB.askyesno = _real_ask
        core.stop_active_process = _real_stop
        try:
            core.reset_stop()          # 保险：清掉可能被置位的停止事件
        except Exception:
            pass

    # ④ 源码层确认：确认框必须**默认选中「否」**（误点的代价是继续跑，不是白跑）
    _gsrc = open(os.path.join(ROOT, "kohya_gui.py"), encoding="utf-8").read()
    _i = _gsrc.index("def _on_close(self)")
    _seg = _gsrc[_i:_i + 2000]
    assert "default=" in _seg and "no" in _seg.lower(), "关闭确认框没设默认值为「否」"
    print("CLOSE_CONFIRM_WHILE_RUNNING_OK")


def test_wd14_selector_visible():
    """打标模型的选择必须**在折叠区之外**——用户要能直接看到，而不是去翻高级参数。

    2026-09-17 教训：我第一版把它放进了「高级参数」折叠区（`adv_collapsed = True` 默认收起），
    用户反馈「打标模型选择组件在哪里？我没有看到啊」✗ —— 位置选错了：
    它是常规选择，不是"老手参数" ✓

    这里**真构造界面**并断言控件确实 mapped（折叠区里的子控件 `winfo_ismapped()` 为 False，
    所以这条断言正好能抓住"又被塞进折叠区"的回归 ✓）。
    """
    import kohya_gui as G      # noqa: E402

    _app = G.App()
    try:
        _app._build_main_cards()
        _app.root.update_idletasks()
        _m = getattr(_app, "wd14_model_menu", None)
        assert _m is not None, "打标模型下拉不存在"
        # ⚠️ 判据不能用 winfo_ismapped()：_build_main_cards() 之后界面可能还停在主页，
        # 祖先不可见 → 所有子控件都是 not mapped，那会误报（第一次就踩了 ✗）。
        # 真正要保证的是语义：**它不在折叠容器 adv_body 里**（那才是"用户看不到"的原因）。
        _adv = getattr(_app, "adv_body", None)
        _p, _in_adv = _m, False
        while _p is not None:
            if _p is _adv:
                _in_adv = True
                break
            _p = getattr(_p, "master", None)
        assert not _in_adv, "打标模型控件在「高级参数」折叠区里 —— 用户翻不到 ✗"
        # 也不该藏在"高级参数"卡片里（哪怕折叠区之外）—— 它属于「① 准备图片数据」
        _p2, _in_card3 = _m, False
        while _p2 is not None:
            if _p2 is getattr(_app, "btn_toggle_adv", None):
                _in_card3 = True
            _p2 = getattr(_p2, "master", None)
        assert not _in_card3, "打标模型还在「高级参数」卡片里，应放在①准备图片数据 ✓"
        assert _app.wd14_model_var.get().startswith("swinv2-v3"), \
            "默认值不是新模型（%s）" % _app.wd14_model_var.get()
    finally:
        try:
            _app.root.destroy()
        except Exception:
            pass
    print("WD14_SELECTOR_VISIBLE_OK")


def test_wd14_download_http_path():
    """打标模型下载必须真的能下 —— 走**完整正常路径**（URL 正常 + 目录正常）。

    ★ 2026-09-17 事故（用户 RTX 2060 实测日志 L81/L84/L146/L149 原文）：
        [WD14] 下载异常：name 'time' is not defined
      `preprocess.py` **没有 `import time`** ✗，而 `_http_download()` 里第一处
      `time.time()` 在 `urlopen` **成功之后**才执行 ✗ →
        · 我发布前测的两条"失败路径"（坏域名 / 不存在的目录）**都在那一行之前就挂了** ✗，
          所以这个问题**完全没被暴露** ✓；
        · 真实用户 URL 正常、目录正常 → 正好走到那一行 → NameError ✗✓
          → 魔搭 / hf-mirror **两个源全废** → 模型永远下不来 →
          打标静默降级成兜底 caption（只剩 `1girl, solo`），训练效果白瞎 ✗
    ★ 同一次真机验证还抓到第二个 bug：`download_wd14_model()` 原本 `return dst`
      （**模型目录**），而就绪路径返回的是**根目录** ✗ → 下载"成功"后调用方再拼一次
      目录名就嵌套两层 ✗ → 内置打标照样找不到 model.onnx ✗
      （此 bug 因下载从未成功过而一直潜伏 ✓ 修好下载才发作 ✓）

    这里用**本机 HTTP 服务**跑完整下载路径（不依赖外网）：上面两条 bug 都会被抓到 ✓
    """
    import http.server
    import shutil as _sh
    import tempfile as _tf
    import threading as _th
    import preprocess as P      # noqa: E402

    srv_dir = _tf.mkdtemp(prefix="wd14_srv_")
    cache_dir = _tf.mkdtemp(prefix="wd14_cache_")
    try:
        # 按魔搭的路径结构（<base>/<repo 目录名>/<文件>）提供两个文件
        _r = P._wd14_repo_dirname(P.WD14_MODELS[P.WD14_DEFAULT_MODEL])
        os.makedirs(os.path.join(srv_dir, _r), exist_ok=True)
        body = b"WD14FAKE" * 1400000                      # ≈10.7MB（必须 >10MB 才算"完整"）
        with open(os.path.join(srv_dir, _r, "model.onnx"), "wb") as f:
            f.write(body)
        with open(os.path.join(srv_dir, _r, "selected_tags.csv"), "w", encoding="utf-8") as f:
            # ⚠️ 必须 >1024 字节：download_wd14_model 对 csv 有**大小校验**
            #    （`min_sz=1024` ✓ 挡掉"下到了但只有半截/是错误页"的情况 ✓）
            f.write("tag_id,name,category,count\n")
            f.write("".join("%d,tag_%d,0,0\n" % (i, i) for i in range(200)))

        class _H(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def __init__(self, *a, **kw):
                super().__init__(*a, directory=srv_dir, **kw)

        class _Srv(http.server.ThreadingHTTPServer):
            daemon_threads = True

        srv = _Srv(("127.0.0.1", 0), _H)
        port = srv.server_address[1]
        _th.Thread(target=srv.serve_forever, daemon=True).start()

        _ms, _hf, _root = P.WD14_MS_BASE, P.WD14_HF_BASE, P._wd14_cache_root
        P.WD14_MS_BASE = "http://127.0.0.1:%d" % port
        P.WD14_HF_BASE = "http://127.0.0.1:%d" % port
        P._wd14_cache_root = lambda: cache_dir
        try:
            logs = []
            _k, _repo, d = P.pick_wd14_model(P.WD14_DEFAULT_MODEL, logs.append)
            assert d, "下载失败（完整正常路径都下不来）：%s" % " / ".join(logs)
            # 返回的必须是**根目录**：与就绪路径同形，调用方要拿它拼 repo 目录名、
            # 也要当 `--model_dir` 传给官方脚本 ✗ 返回模型目录会让这两处全错
            assert d == cache_dir, "返回的不是根目录（调用方拼目录名会嵌套）：%s" % d
            onnx_p, csv_p = P._wd14_onnx_files(P.WD14_DEFAULT_MODEL)
            assert onnx_p and csv_p, "下载完成后仍定位不到模型：%s" % onnx_p
            assert os.path.getsize(onnx_p) == len(body), "落盘内容不完整"
            # 已就绪 → 秒回、不重复下载
            logs2 = []
            assert P.pick_wd14_model(P.WD14_DEFAULT_MODEL, logs2.append)[2] == cache_dir
            assert not any("下载" in s for s in logs2), "已就绪却仍在下载"
        finally:
            P.WD14_MS_BASE, P.WD14_HF_BASE, P._wd14_cache_root = _ms, _hf, _root
            srv.shutdown()
    finally:
        _sh.rmtree(srv_dir, ignore_errors=True)
        _sh.rmtree(cache_dir, ignore_errors=True)
    print("WD14_DOWNLOAD_HTTP_OK")


def test_wd14_model_fallback():
    """指定模型下不到、但机器上**已有另一个模型** → 必须回退用它，不能掉到兜底 caption。

    ★ 2026-09-17 事故：老安装包（自 2026-08-15 起）**内置**的是 `moat-v2` ✓，
      而 v0.17.0 把默认模型换成了 `swinv2-v3` ✗ —— 两者目录名不同，
      于是**老用户本地明明有一份能用的模型，代码却从不看它** ✗（只找指定模型）→
      直接判定「未下载」→ 触发下载 → 撞上缺 import time 的 bug → 失败 →
      **一路掉到兜底 caption（只剩 `1girl, solo`）** ✗✓
      本地有模型却不用，是纯粹的浪费 ✓

    判据：① 指定模型已就绪 → 就用它（不因回退而改）；② 指定模型缺失 + 下载失败 →
    必须回退到已就绪的那个，并明确说明 ✓
    """
    import shutil as _sh
    import tempfile as _tf
    import preprocess as P      # noqa: E402

    tmp = _tf.mkdtemp(prefix="wd14_fb_")
    _orig_roots, _orig_dl = P._wd14_model_roots, P.download_wd14_model
    try:
        _mr = os.path.join(tmp, P._wd14_repo_dirname(P.WD14_MODELS["moat-v2"]))
        os.makedirs(_mr, exist_ok=True)
        with open(os.path.join(_mr, "model.onnx"), "wb") as f:
            f.write(b"0" * (11 * 1024 * 1024))
        P._wd14_model_roots = lambda: [tmp]          # 隔离出确定的环境

        def _has(root, k):
            return bool(root) and os.path.isfile(
                os.path.join(root, P._wd14_repo_dirname(P.WD14_MODELS[k]), "model.onnx"))

        # ② 指定模型缺失 + 下载失败 → 回退，且**不能返回 None**（None = 用户吃兜底 caption ✗）
        P.download_wd14_model = lambda k=None, logf=print: None
        logs = []
        k, repo, d = P.pick_wd14_model("swinv2-v3", logs.append)
        assert k == "moat-v2" and _has(d, "moat-v2"), \
            "没有回退到机器上已有的模型（得到 %s @ %s）" % (k, d)
        assert any("改用机器上已有的" in s for s in logs), "回退时没有明确说明"
        assert repo == P.WD14_MODELS["moat-v2"], "回退后 repo 仍是旧值 → 目录拼错"

        # ① 指定模型已就绪时 → 必须仍用它，别被回退逻辑改掉
        _sr = os.path.join(tmp, P._wd14_repo_dirname(P.WD14_MODELS["swinv2-v3"]))
        os.makedirs(_sr, exist_ok=True)
        with open(os.path.join(_sr, "model.onnx"), "wb") as f:
            f.write(b"0" * (11 * 1024 * 1024))
        k2, repo2, d2 = P.pick_wd14_model("swinv2-v3", lambda s: None)
        assert k2 == "swinv2-v3" and _has(d2, "swinv2-v3"), "指定模型就绪时却没有用它"
    finally:
        P._wd14_model_roots, P.download_wd14_model = _orig_roots, _orig_dl
        _sh.rmtree(tmp, ignore_errors=True)
    print("WD14_MODEL_FALLBACK_OK")


def test_env_paths_custom():
    """「自带 Python / Git」：自己选文件夹 → 识别 → 校验 → 采用（失效则回落自动）。

    需求来源（2026-09-17 用户反馈原话）：
      「环境文件可以增加一个自己选择环境文件所在的文件夹然后识别这些环境文件的功能吗?
        我之前用的秋叶绘图，里面的 Python 和 Git 都不在系统盘，而在秋叶的文件夹里
        （重装系统它也能识别，很方便）」

    这里守住四条**最容易做错**的：
      ① 校验不过的**绝不采用** ✗（否则要到建训练环境时才炸，更晚更难查 ✗）
      ② 原因必须**具体** —— 尤其「版本对但没有 venv」这种整合包常见情况 ✗
      ③ 指定路径失效 → **回落自动**，不阻断用户 ✓
      ④ 保存时**不能覆盖其它设置项**（data_dir / 各种开关 ✗）
    """
    import json as _json
    import shutil as _sh
    import tempfile as _tf
    import types as _types
    from kohya_core import utils as U      # noqa: E402
    from kohya_core import paths as _P

    sp_dir = _tf.mkdtemp(prefix="envset_")
    sp = os.path.join(sp_dir, "settings.json")
    _orig_sp = _P._settings_path
    _P._settings_path = lambda: sp          # 用临时设置文件，不碰用户真实设置 ✓
    try:
        # ① 校验：真 Python 通过；假 exe 必须被拒绝
        ok, ver, why = U.check_python_exe(sys.executable)
        assert ok and ver, "本机 Python 没通过校验：%s" % why
        _fd = _tf.mkdtemp(prefix="envfake_")
        _fake = os.path.join(_fd, "python.exe")
        with open(_fake, "wb") as f:
            f.write(b"MZ" + b"\x00" * 64)
        ok2, _v2, why2 = U.check_python_exe(_fake)
        assert not ok2 and why2, "假 python.exe 没被拒绝"
        _sh.rmtree(_fd, ignore_errors=True)

        # ② 「没有 venv」的整合包精简版必须**单独**说清（不能笼统一句"不行"）
        _h = U._py_has_venv
        U._py_has_venv = lambda p: False
        try:
            ok3, ver3, why3 = U.check_python_exe(sys.executable)
        finally:
            U._py_has_venv = _h
        assert not ok3 and ver3 and "venv" in why3, \
            "没区分「版本可用但没有 venv」这种情况：%s" % why3

        # ③ 存取往返 + 失效回落 + 只给目录也能识别
        assert U.set_env_paths(python_dir="", python_exe=sys.executable, git_exe="")
        assert U.get_env_paths()["python_exe"] == sys.executable
        assert U.custom_python_exe() == sys.executable
        assert U.set_env_paths(python_exe=r"D:\不存在的\python.exe")
        assert U.custom_python_exe() == "", "失效的指定 Python 没回落（会拿坏路径建环境 ✗）"
        assert U.explain_custom_python_problem(), "失效时没有说明原因"
        assert U.set_env_paths(python_dir=os.path.dirname(sys.executable), python_exe="")
        assert U.custom_python_exe() == sys.executable, "只指定文件夹时没识别出 Python"
        assert U.clear_env_paths()
        assert U.get_env_paths() == {"python_dir": "", "python_exe": "", "git_exe": ""}

        # ④ 保存环境路径不能覆盖其它设置项
        with open(sp, "w", encoding="utf-8") as f:
            _json.dump({"data_dir": r"D:\keep", "download_official_first": True}, f)
        assert U.set_env_paths(git_exe="")
        with open(sp, encoding="utf-8") as f:
            _d = _json.load(f)
        assert _d.get("data_dir") == r"D:\keep", "保存环境路径时覆盖了 data_dir ✗"
        assert _d.get("download_official_first") is True, "覆盖了其它开关 ✗"

        # ⑤ 应用层：建训练环境必须用**指定的解释器**（真建已在端到端单独验过 ✓）
        import Kohya一键工具 as core      # noqa: E402
        U.set_env_paths(python_dir=os.path.dirname(sys.executable), python_exe=sys.executable)
        assert core.find_python()[0] == sys.executable, "find_python 没用指定的解释器"

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        _calls = []
        _orig_sub = core.subprocess                       # 只替换 core 里的引用，不动全局模块 ✓
        core.subprocess = _types.SimpleNamespace(
            run=lambda cmd, *a, **k: (_calls.append(cmd), _R())[1])
        _td = _tf.mkdtemp(prefix="venvcmd_")
        try:
            core.create_python_venv("3.12", os.path.join(_td, "v"))
        finally:
            core.subprocess = _orig_sub
            _sh.rmtree(_td, ignore_errors=True)
        assert _calls and _calls[0][0] == sys.executable, \
            "建训练环境没用指定的解释器（用的是 %s）" % (_calls[0][0] if _calls else "?")
        assert "-m" in _calls[0] and "venv" in _calls[0], "命令不是 `python -m venv`：%s" % _calls[0]
        U.clear_env_paths()
    finally:
        _P._settings_path = _orig_sp
        _sh.rmtree(sp_dir, ignore_errors=True)
    print("ENV_PATHS_CUSTOM_OK")


def test_env_locations_ui():
    """「环境位置（自带 Python / Git）」入口必须存在、不在折叠区、且点得开。

    避免做完功能却没有入口（用户根本找不到 ✗）—— 这与 WD14 模型选择那次
    「做在折叠区里、用户看不见」是同一类问题 ✓
    """
    import kohya_gui as G      # noqa: E402

    _app = G.App()
    try:
        _app.root.update_idletasks()
        _b = getattr(_app, "btn_env_locations", None)
        assert _b is not None, "「环境位置」按钮不存在 —— 用户找不到入口 ✗"
        _adv = getattr(_app, "adv_body", None)
        _p, _in_adv = _b, False
        while _p is not None:
            if _p is _adv:
                _in_adv = True
                break
            _p = getattr(_p, "master", None)
        assert not _in_adv, "「环境位置」被放进高级参数折叠区 —— 用户翻不到 ✗"
        _app.cmd_env_locations()          # 必须能打开且不抛异常
        _app.root.update_idletasks()
    finally:
        try:
            _app.root.destroy()
        except Exception:
            pass
    print("ENV_LOCATIONS_UI_OK")


def test_fizgig_quant_swap_vram_table():
    """Krea2 量化档 + 块交换：**任何量化方式都必须按显存配块交换**。

    ★ 2026-09-18 事故（用户 5060 Ti 16G 实测日志，v0.17.2）：
      「手动选 int8」那条分支把 `swap` **写死为 0** ✗（文案还写着"~18G 显存常驻，最快" ✗），
      而 16G 卡**装不下** int8 的 ~18G 常驻 ✗ → 溢出到系统内存 / 页面文件 →
      日志里的步速**逐 epoch 单调恶化**：
        epoch1 末 3.80s/it ✓ → epoch2 末 7.07 → epoch3 9.46 → epoch4 11.37 → epoch5 12.73
        → epoch6 末 13.86s/it ✗（4 倍），**且每轮起点都比上轮终点更慢** ✗
      而同一张卡的实测基准（int8 + swap12 + pinned）= **2.5s/it** ✓✓
      —— 用户只会以为"这卡就这水平" ✗，完全看不出是配置被写死造成的 ✗

    这里锁两件事：
      ① 手动 int8 / fp8 在**任何显存**下都要配块交换（<10G 只能 NF4 除外 ✓）
      ② **auto 档取值表逐项不变** ✓ —— 改这里绝不能顺手动到 auto ✗（它才是绝大多数用户的路径 ✓）
    """
    import Kohya一键工具 as core      # noqa: E402

    # ② auto 的历史取值表（锁死，改这里必须是**有实测依据**的改动 ✓）
    #    值 = (块交换, 是否 int8)
    _AUTO = {None: (0, True), 8: (0, False), 10: (26, True), 15.67: (20, True),
             16: (20, True), 20: (20, True), 23.5: (12, True), 24: (12, True),
             32: (0, True), 48: (0, True)}
    for v, (sw, is_int8) in _AUTO.items():
        f, s, d = core._fizgig_quant_swap(v, "auto", backend="nvidia")
        assert s == sw, "auto 档在 %sG 下的块交换变了：%s（应为 %s）" % (v, s, sw)
        assert ("--quant_int8" in f) == is_int8, "auto 档在 %sG 下的量化变了：%s" % (v, f)
        assert d, "auto 档没有给出说明文案"

    # ① 手动选择的量化也必须配块交换
    for v in (10, 16, 24, 32):
        for q in ("int8", "fp8"):
            f, s, d = core._fizgig_quant_swap(v, q, backend="nvidia")
            if v >= 32:
                assert s == 0, "%sG + %s：显存足够大，应当不交换（得到 %s）" % (v, q, s)
            else:
                assert s > 0, ("%sG + %s：块交换为 0 ✗ —— 显存装不下常驻模型，"
                               "会溢出到内存/页面文件、越训越慢 ✗（2026-09-18 的 bug）" % (v, q))
        assert core._fizgig_quant_swap(v, "int8", "nvidia")[:2] == \
               core._fizgig_quant_swap(v, "auto", "nvidia")[:2], \
               "%sG：手动 int8 与自动档结果不一致（指定 int8 不该引入劣化 ✗）" % v

    # <10G：int8 装不下 → 必须自动改用 NF4，而不是给个跑不动的组合 ✗
    f, s, d = core._fizgig_quant_swap(8, "int8", backend="nvidia")
    assert "--quantize_4bit" in f and s == 0 and d, "小显存手动 int8 没自动改用 NF4"

    # AMD ROCm ≥18G 的实测档位（int8 + 0）必须保留 ✓ —— 它有 7900 XT 实测依据 ✓
    f, s, d = core._fizgig_quant_swap(20, "auto", backend="amd-rocm")
    assert "--quant_int8" in f and s == 0, "AMD ROCm ≥18G 的实测档位被改掉了：%s %s" % (f, s)
    print("FIZGIG_QUANT_SWAP_VRAM_OK")


def test_adv_rows_mode_gating():
    """高级参数里「量化 / 块交换 / torch.compile」必须**按模式显隐**。

    ★ 2026-09-18 用户反馈：「高级参数的选项会错误显示别的模式的选项」✗
      实测确认：这三行是直接 pack 进 adv_body 的，**全代码没有任何隐藏逻辑** ✗ →
      画风/人物/视频/Qwen/Z-Image 都会看到「量化方式（Krea2/FLUX.2）」这类与自己无关的项 ✗

    判据（用真实控件断言，不写"看起来对"✗）：
      · 量化 / 块交换：只在 **Krea2×3 / FLUX.2×2** 显示 ✓
      · torch.compile：再加 **画风/人物/概念** ✓（不含 视频/Qwen/Z-Image ✗ —— 它们的配置里没这项）
    """
    import kohya_gui as G          # noqa: E402
    import kohya_core.configs as C  # noqa: E402

    _app = G.App()
    try:
        _app._build_main_cards()
        if not _app.adv_body.winfo_children():
            _app._build_adv_body()
        _rows = getattr(_app, "_adv_rows", {})
        assert _rows, "三行没有登记进 _adv_rows（无法按模式显隐）"
        # ⚠️ 2026-09-19 更正：这里原先硬编码成 ("krea2","krea2_at","krea2_fz","flux2","flux2_fz") ✗
        #    但 `train_krea2_at` **根本不读** quant_mode / blocks_to_swap ✗ →
        #    Krea2(AI-Toolkit) 下这两行**显示了却不生效** ✗（与「提示跟实际不符」同一类问题 ✓）
        #    改为统一查 C.PARAM_SCOPE（唯一事实来源 ✓ 由 test_param_scope_matches_code 校验 ✓）
        _K2F2 = C.PARAM_SCOPE["quant_mode"]

        def _shown(name):
            r = _rows.get(name)
            return bool(r is not None and r.winfo_manager())

        for m in C.MODE_KEYS:
            _app.mode_combo.set(C.MODE_LABELS[m])
            _app._on_mode_change()
            _app.root.update_idletasks()
            for name in ("quant", "swap"):
                want = m in _K2F2
                assert _shown(name) == want, \
                    "%s（%s）：%s 可见性 = %s，应为 %s" % (C.MODE_LABELS[m], m, name, _shown(name), want)
            want_c = C.param_supports("compile", m)
            assert _shown("compile") == want_c, \
                "%s（%s）：compile 可见性 = %s，应为 %s" % (C.MODE_LABELS[m], m, _shown("compile"), want_c)
        # 顺序不能被重排打乱 ⚠️：pack 会把控件移到末位 ✗ 所以显隐用 `before=global_frame` 固定落点 ✓
        # 这里断言：量化 < 块交换 < compile < 附加全局提示词（否则界面顺序会跳 ✗）
        _app.mode_combo.set(C.MODE_LABELS["krea2"])
        _app._on_mode_change()
        _app.root.update_idletasks()
        kids = list(_app.adv_body.winfo_children())
        idx = {n: kids.index(_rows[n]) for n in ("quant", "swap", "compile") if _rows.get(n) in kids}
        assert len(idx) == 3, "三行没有全部挂回 adv_body：%s" % idx
        assert idx["quant"] < idx["swap"] < idx["compile"], \
            "三行顺序被打乱：%s" % idx
        _gf = getattr(_app, "global_frame", None)
        if _gf in kids:
            assert idx["compile"] < kids.index(_gf), \
                "compile 跑到「附加全局提示词」后面去了 ✗（重排副作用）"
    finally:
        try:
            _app.root.destroy()
        except Exception:
            pass
    print("ADV_ROWS_MODE_GATING_OK")


def test_steps_summary_and_intervals():
    """① 摘要行的「训练步数」必须跟随**界面输入框** ✗ 不是预设值；
       ② 「模型保存间隔 / 采样预览间隔」必须真的写进 视频 / Qwen / Z-Image 的配置。

    ★ 2026-09-18 用户反馈：「训练步数选项不生效」✗ 实测两件事：
      · 摘要行读的是 `pre.get('video_steps')`（预设 2000 ✗）→ 用户改成 1234，那行仍写 2000 ✗
        （看起来就是"没生效" ✗✓）
      · 两个 yaml 里 `save_every: 200` / `sample_every: 250` 是**硬编码** ✗ 而它们在全部 11 个
        模式都显示 ✓ → 填了完全没反应 ✗

    判据：填了就生效 ✓、**留空时默认行为一点不变** ✓（200 / 250 ✓）
    """
    import shutil as _sh
    import tempfile as _tf
    import kohya_gui as G          # noqa: E402
    import Kohya一键工具 as core    # noqa: E402

    # ① 摘要行
    _app = G.App()
    try:
        _app._build_main_cards()
        if not _app.adv_body.winfo_children():
            _app._build_adv_body()
        for m, label in (("video", "视频"), ("qwen_image", "Qwen-Image"), ("zimage", "Z-Image")):
            _app.mode_combo.set(core.MODE_LABELS[m])
            _app._on_mode_change()
            _app.root.update_idletasks()
            _app.param_vars["video_steps"].set("1234")
            _app._refresh_preset_summary()
            _txt = _app.preset_summary.cget("text")
            assert "1234" in _txt, "%s：摘要行没跟着输入框走 → %s" % (label, _txt)
            assert "2000" not in _txt, "%s：摘要行还显示预设值 2000 ✗ → %s" % (label, _txt)
    finally:
        try:
            _app.root.destroy()
        except Exception:
            pass

    # ② 两个 yaml
    td = _tf.mkdtemp(prefix="advfix_")
    imgs = os.path.join(td, "imgs")
    os.makedirs(imgs, exist_ok=True)
    open(os.path.join(imgs, "a.txt"), "w", encoding="utf-8").write("x")
    base = {"project": "p", "trigger": "t", "rank": 16, "alpha": 16, "unet_lr": 1e-4,
            "te_lr": 1e-4, "repeats": 5, "max_epochs": 8, "resolution": 512,
            "video_steps": 500, "video_frames": 22, "optimizer": "auto",
            "sample_preview": False, "sample_prompt": "", "at_sub_mode": "character"}
    try:
        def _gen(params):
            """生成两份配置，返回 (视频 yaml, AI 图像 yaml) 的文本。"""
            p1 = os.path.join(td, "v.yaml")
            core.write_h3_train_yaml(dict(params), imgs, os.path.join(td, "o"), p1,
                                     logf=lambda s: None, vram_gb=24)
            info = dict(core.AT_IMAGE_MODELS.get("zimage") or {})
            info.update({"arch": "zimage", "label": "Z-Image", "model_id": "x/y",
                         "resident_vram": 26})
            p2 = os.path.join(td, "a.yaml")
            core.write_at_image_yaml(dict(params), info, imgs, os.path.join(td, "o"), p2,
                                     logf=lambda s: None, vram_gb=24)
            return (open(p1, encoding="utf-8").read(), open(p2, encoding="utf-8").read())

        # 留空 / 0 → 默认行为必须完全不变（200 / 250）✓
        v, a = _gen(dict(base, save_every="", sample_interval=0))
        for tag, txt in (("视频", v), ("AI 图像", a)):
            assert "save_every: 200" in txt, "%s：留空时保存间隔不再是 200 ✗（默认行为被改了）" % tag
            assert "sample_every: 250" in txt, "%s：留空时采样间隔不再是 250 ✗（默认行为被改了）" % tag
        # 填了就必须生效 ✓
        v, a = _gen(dict(base, save_every=50, sample_interval=30))
        for tag, txt in (("视频", v), ("AI 图像", a)):
            assert "save_every: 50" in txt, "%s：填了 50 但 yaml 里不是 50 ✗" % tag
            assert "sample_every: 30" in txt, "%s：填了 30 但 yaml 里不是 30 ✗" % tag
    finally:
        _sh.rmtree(td, ignore_errors=True)
    print("STEPS_SUMMARY_AND_INTERVALS_OK")


def test_no_undefined_names():
    """所有发布脚本里**用到的名字都必须真的可见**（静态审计，兜住整类问题）。

    ★ 2026-09-17 一天之内**三次**同类事故，全都是"名字看不见"：
      · `preprocess.py` 用了 `time.time()` 却**没 `import time`** ✗
        → 打标模型下载 100% 失败 → 静默降级成 `1girl, solo` 兜底标签 ✗✓
      · `Kohya一键工具.py` 用了 `io.open()` 却**没 `import io`** ✗
        → 被 `except Exception: pass` 吞掉 → 模板示例 caption **一直静默为空** ✗
      · `Kohya一键工具.py` 用了 `_py_has_venv`，而它**不在 `utils.__all__` 里** ✗
        → `from kohya_core.utils import *` 取不到 → NameError ✗ →
        被 `except Exception: pass` 吞掉 → 「装完 Python 却识别不到」的兜底扫描静默失效 ✗

    这类错误只在**运行时、且只在那条具体分支上**才炸 ✗，而且常被 except 吞掉、连日志都没有 ✗
    → 靠"多测几条路径"防不住 ✓ 用静态审计一次兜住整类 ✓
    """
    import ast as _ast
    import builtins as _bi
    import importlib as _il

    # 模块级 dunder（`__file__` / `__name__` …）任何函数里都可见 ✓ 不能算未定义 ✗
    BUI = set(dir(_bi)) | {
        "__file__", "__name__", "__doc__", "__package__", "__spec__", "__loader__",
        "__builtins__", "__path__", "__dict__", "__class__", "__annotations__",
    }

    def _star_names(mod_name):
        """`from M import *` 到底带来哪些名字 —— 按**运行时真实行为**取（`__all__` 优先）✓"""
        try:
            m = _il.import_module(mod_name)
        except Exception:
            return None                      # 导不进来 → 该文件放弃检查（不做误报）
        al = getattr(m, "__all__", None)
        return set(al) if al is not None else {n for n in dir(m) if not n.startswith("_")}
    # 随包发布的脚本 + 核心包（注意本文件里 ROOT 是 **str**，不是 Path ✗）
    targets = [os.path.join(ROOT, _n) for _n in
               ("preprocess.py", "video_caption.py", "model_downloader.py",
                "Kohya一键工具.py", "kohya_gui.py")]
    _core = os.path.join(ROOT, "kohya_core")
    if os.path.isdir(_core):
        targets += [os.path.join(_core, _f) for _f in sorted(os.listdir(_core))
                    if _f.endswith(".py")]
    bad = []
    checked = 0
    for p in targets:
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8-sig") as _fh:
            tree = _ast.parse(_fh.read())
        # 模块级可见的名字
        top = set(BUI)
        star_ok = True
        for n in _ast.walk(tree):
            if isinstance(n, _ast.Import):
                for a in n.names:
                    top.add(a.asname or a.name.split(".")[0])
            elif isinstance(n, _ast.ImportFrom):
                if any(a.name == "*" for a in n.names):
                    names = _star_names(n.module or "")
                    if names is None:
                        star_ok = False          # 导不进来 → 该文件跳过（宁可不查，不误报 ✓）
                    else:
                        top |= names
                else:
                    for a in n.names:
                        top.add(a.asname or a.name)
            elif isinstance(n, _ast.Name) and isinstance(n.ctx, (_ast.Store, _ast.Del)):
                top.add(n.id)                    # 模块级赋值 / for 目标 / with-as / 推导式
            elif isinstance(n, _ast.arg):
                top.add(n.arg)
            elif isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                top.add(n.name)
            elif isinstance(n, _ast.alias):
                top.add(n.asname or n.name.split(".")[0])
            elif isinstance(n, _ast.ExceptHandler) and n.name:
                top.add(n.name)
            elif isinstance(n, (_ast.Global, _ast.Nonlocal)):
                top.update(n.names)
        if not star_ok:
            continue
        checked += 1
        for fn in [x for x in _ast.walk(tree)
                   if isinstance(x, (_ast.FunctionDef, _ast.AsyncFunctionDef))]:
            vis = set(top)
            for a in (fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs):
                vis.add(a.arg)
            if fn.args.vararg:
                vis.add(fn.args.vararg.arg)
            if fn.args.kwarg:
                vis.add(fn.args.kwarg.arg)
            # 函数体内所有绑定的名字（含嵌套函数 / 推导式 / with-as / except-as / 局部 import）
            for sub in _ast.walk(fn):
                if isinstance(sub, _ast.Name) and isinstance(sub.ctx, (_ast.Store, _ast.Del)):
                    vis.add(sub.id)
                elif isinstance(sub, (_ast.arg,)):
                    vis.add(sub.arg)
                elif isinstance(sub, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                    vis.add(sub.name)
                elif isinstance(sub, _ast.alias):
                    vis.add(sub.asname or sub.name.split(".")[0])
                elif isinstance(sub, _ast.ExceptHandler) and sub.name:
                    vis.add(sub.name)
                elif isinstance(sub, (_ast.Global, _ast.Nonlocal)):
                    vis.update(sub.names)
            for sub in _ast.walk(fn):
                if isinstance(sub, _ast.Name) and isinstance(sub.ctx, _ast.Load) \
                        and sub.id not in vis:
                    bad.append("%s L%d: %s() 里用了看不见的名字 `%s`"
                               % (os.path.basename(p), sub.lineno, fn.name, sub.id))
    assert checked, "一个文件都没检查到，测试本身失效了"
    assert not bad, "发现「用了但看不见」的名字：\n    " + "\n    ".join(sorted(set(bad)))
    print("NO_UNDEFINED_NAMES_OK")


def test_param_scope_matches_code():
    """界面提示的「适用范围」必须与**代码实际读取**一致 —— 由 `core.PARAM_SCOPE` 兜住。

    ★ 2026-09-19 用户反馈：「软件界面很多 UI 旁边的提示，其实跟实际都不符」✓ 核对**属实** ✗
      根因：界面控件从不按模式隐藏，而好几个参数**只被第一引擎读取** ✗ 最典型的一条：
        `global_pos` 的提示写「训练时自动加到每张图片标签最前面（例如 masterpiece）」，
        而 8 个训练入口里**只有 train() 会处理它** —— Krea2 / FLUX.2 / 两个 Fizgig /
        视频 / AI图像 **完全不读** ✗ 且在那些模式下**静默失效**（不报错、不提示）✗
      同类还有：te_lr / 只训UNet / AMD 兼容模式 / optimizer / 采样间隔（Fizgig 按轮换算）✗

    判据（避免两边各说各话）：
      ① 表里登记的 key **必须**是界面真实存在的参数（防止登记了不存在的东西）✓
      ② 登记的 key 必须**真的有训练入口读它**（空 = 表在撒谎 ✗）
      ③ 代码实际读取的模式 ⊆ 表声明的模式（表声明得比实际窄 = 会误置灰 ✗）
      ④ 公认通用的参数（rank/alpha/unet_lr/trigger）必须被绝大多数入口读到 ✓
    """
    import ast as _ast
    import kohya_core.configs as C      # noqa: E402

    # 训练入口 -> 它负责的模式（与 Kohya一键工具.py 的入口函数一一对应）
    ENTRY_MODES = {
        "train": ("style", "character", "concept"),
        "train_krea2": ("krea2",),
        "train_flux2": ("flux2",),
        "train_krea2_fizgig": ("krea2_fz",),
        "train_flux2_fizgig": ("flux2_fz",),
        "train_video": ("video",),
        "train_krea2_at": ("krea2_at",),
        "train_at_image": ("qwen_image", "zimage"),
        # ⚠️ 这些**配置生成函数**也算生效路径 ✓：有些参数不被 train_* 直接读，
        #    而是先交给它们写进 yaml（例：`video_frames` 只被 write_h3_train_yaml 读）✗
        #    只统计 train_* 会漏掉这类参数、把"确实生效"误判成"没人读" ✗
        "write_h3_train_yaml": ("video",),
        "write_at_image_yaml": ("qwen_image", "zimage"),
        "write_krea2_at_yaml": ("krea2_at",),
        "_fizgig_sample_epochs": ("krea2_fz", "flux2_fz"),
    }

    src = os.path.join(ROOT, "Kohya一键工具.py")
    lines = open(src, encoding="utf-8-sig").read().splitlines()
    tree = _ast.parse("\n".join(lines))
    spans = [(n.name, n.lineno, n.end_lineno) for n in tree.body
             if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))]

    def owner(ln):
        for nm, a, b in spans:
            if a <= ln <= b:
                return nm
        return None

    # 界面真实存在的参数（与 _collect_params 的返回字典一致）
    gui_keys = set()
    gtree = _ast.parse(open(os.path.join(ROOT, "kohya_gui.py"), encoding="utf-8-sig").read())
    for n in _ast.walk(gtree):
        if isinstance(n, _ast.FunctionDef) and n.name == "_collect_params":
            for c in _ast.walk(n):
                if isinstance(c, _ast.Dict):
                    for k in c.keys:
                        if isinstance(k, _ast.Constant) and isinstance(k.value, str):
                            gui_keys.add(k.value)

    # 每个参数：实际读取它的训练入口（统计**全部**界面参数，不只 PARAM_SCOPE 里的 ——
    #   否则通用参数（rank/alpha…）会被当成"没人读" ✗）
    actual = {}
    for i, ln in enumerate(lines, start=1):
        norm = ln.replace("'", '"')
        for k in gui_keys:
            if ('params.get("' + k + '"') in norm or ('params["' + k + '"]') in norm:
                f = owner(i)
                if f in ENTRY_MODES:
                    actual.setdefault(k, set()).update(ENTRY_MODES[f])

    bad = []
    for k, modes in C.PARAM_SCOPE.items():
        # ① key 必须是界面真实参数
        if k not in gui_keys:
            bad.append("%s：表里登记了，但界面根本没有这个参数" % k)
            continue
        got = actual.get(k, set())
        # ② 必须真有入口读
        if not got:
            bad.append("%s：表声称「%s」，但**没有任何训练入口读它**" % (k, C.param_scope_text(k)))
            continue
        # ③ 实际读取 ⊆ 表声明
        extra = got - set(modes)
        if extra:
            bad.append("%s：代码在 %s 下也读它，但表只声明了 %s（会**误置灰**）"
                       % (k, sorted(extra), sorted(modes)))
    assert not bad, "PARAM_SCOPE 与代码实际不符：" + " ｜ ".join(sorted(bad))

    # ④ 公认通用的参数：必须几乎所有入口都读
    for k in ("rank", "alpha", "unet_lr", "trigger"):
        assert k not in C.PARAM_SCOPE, "%s 是通用参数，不该登记进 PARAM_SCOPE" % k
        got = actual.get(k, set())
        assert len(got) >= 7, "%s 只被 %d 个入口读取（应近乎全模式通用）" % (k, len(got))

    # 文案能生成（给界面用）
    assert "仅" in C.param_scope_text("global_pos"), "适用范围文案没生成"
    print("PARAM_SCOPE_MATCHES_CODE_OK")


def test_preprocess_overwrite_picks_up_changed_captions():
    """改过的标签必须能真的生效 —— 否则外部/自定义打标的结果**进不了训练集** ✗

    ★ 2026-09-19（为「自定义本地打标模型」做前置调研时发现）：
      `preprocess()` 的输出目录 `out = dataset_train_dir(...)` **就是训练读取的那个目录** ✓
      而 preprocess.py 对「输出目录里已有同名图片」的处理是**整张跳过**（含打标）✗ ——
      偏偏 `--overwrite` **只有视频打标那条路有**，图片预处理界面从来不传 ✗
      → 于是：手动改的标签、或用别的打标模型重写过的标签，
        重跑一次预处理**一个字都不会变** ✗ 而且是**静默**的
        （日志只说「跳过 N 张」，很容易被当成成功 ✓）

      这直接卡死了「自定义打标模型」这条路：外面打好了标签却根本喂不进训练集 ✗

    ★ 为什么用**真跑一遍**来验（不旁路）✗：
      上次教训 —— 只测"失败路径"会恰好绕开出问题的那一行 ✓ 这里同一个道理：
      只有真的跑完两遍预处理、真的改了源 txt，才能看出标签到底有没有被采用 ✓

    判据：① 首次处理采用源标签 ✓ ② 改了源标签 + 不勾 → **不变**（复现现象）
          ③ 同样的改动 + 勾选 → **必须变**（修复生效）
    """
    import shutil as _sh
    import subprocess as _sp
    import tempfile as _tf
    from PIL import Image as _Img

    tmp = _tf.mkdtemp(prefix="pp_ovw_")
    try:
        src = os.path.join(tmp, "raw")
        out = os.path.join(tmp, "out")
        os.makedirs(src, exist_ok=True)
        _names = ["a.png", "b.png"]
        for _n in _names:
            _Img.new("RGB", (640, 640), (120, 80, 200)).save(os.path.join(src, _n))
            with open(os.path.join(src, _n.replace(".png", ".txt")), "w", encoding="utf-8") as f:
                f.write("moshu, first version")

        def _run(extra):
            _cmd = [sys.executable, "-u", os.path.join(ROOT, "preprocess.py"),
                    "--input", src, "--output", out, "--size", "512",
                    "--mode", "character", "--repeats", "1", "--trigger", "moshu"] + extra
            _r = _sp.run(_cmd, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=900,
                         env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            return (_r.stdout or "") + (_r.stderr or "")

        def _cap(n="a.png"):
            _p = os.path.join(out, n.replace(".png", ".txt"))
            return open(_p, encoding="utf-8").read().strip() if os.path.isfile(_p) else ""

        _run([])
        assert "first version" in _cap(), "① 首次处理没有采用源标签：%r" % _cap()

        with open(os.path.join(src, "a.txt"), "w", encoding="utf-8") as f:
            f.write("moshu, SECOND version")
        _run([])
        assert "first version" in _cap(), \
            "② 不勾「重新处理」时标签却变了 —— 跳过逻辑已不是预期行为，本测试的前提需更新"

        _run(["--overwrite"])
        assert "SECOND" in _cap(), \
            "③ 勾了「重新处理」标签仍未更新 ✗ 改过的标签照样进不了训练集：%r" % _cap()
    finally:
        _sh.rmtree(tmp, ignore_errors=True)
    print("PREPROCESS_OVERWRITE_OK")


def test_wd14_respects_selected_model():
    """选了哪个打标模型，就必须真的用哪个 —— 不能因为机器上有个旧模型就**悄悄**用旧的。

    ★ 2026-09-19 用户反馈：「他明明选的新的打标器，好像又用了旧的打标器」✓ 核对**属实** ✗

      当时 `_wd14_onnx_files()` 内部调 `lookup_wd14_model`（它会回退）✗ 于是：
        用户选 swinv2-v3（新），机器上只有老安装包内置的 moat-v2（旧）
        → 该函数返回**旧模型**的文件 → 调用方 `_run_wd14_onnx` 看到文件存在
        → **跳过 pick_wd14_model** → 新模型**从来不会被下载** → 一直静默用旧的 ✗
      而且全程**没有任何日志**说明"其实用的是旧模型"（回退提示只在 pick 里打印，
      而 pick 根本没被执行）✗ —— 用户只能靠猜 ✓
      另外：官方脚本那条路走的是 pick（**会**下载）→ 两条路行为还不一致 ✗

    判据：
      ① `_wd14_onnx_files(指定模型)` **不得**返回别的模型的文件（回退 = 上面的 bug）✓
      ② 指定已有模型时能正常取到（证明①不是环境没造好）✓
      ③ `_run_wd14_onnx` 里必须先「决定用哪个模型」再「取文件」（顺序反了就会旧病复发）✓
    """
    import ast as _ast
    import shutil as _sh
    import tempfile as _tf
    import preprocess as P      # noqa: E402

    tmp = _tf.mkdtemp(prefix="wd14_sel_")
    _orig_roots = P._wd14_model_roots
    try:
        # 机器上**只有**旧模型 moat-v2（模拟老用户：老安装包内置过它）
        _mr = os.path.join(tmp, P._wd14_repo_dirname(P.WD14_MODELS["moat-v2"]))
        os.makedirs(_mr, exist_ok=True)
        with open(os.path.join(_mr, "model.onnx"), "wb") as f:
            f.write(b"0" * (11 * 1024 * 1024))
        with open(os.path.join(_mr, "selected_tags.csv"), "w", encoding="utf-8") as f:
            f.write("tag_id,name,category,count\n" +
                    "".join("%d,tag_%d,0,0\n" % (i, i) for i in range(200)))
        P._wd14_model_roots = lambda: [tmp]

        # ① 选的是新模型 → 绝不能拿旧模型的顶上（否则调用方会跳过下载、永远用旧的 ✗）
        _r = P._wd14_onnx_files(P.WD14_DEFAULT_MODEL)
        assert _r == (None, None), \
            "_wd14_onnx_files 回退到了机器上已有的旧模型 ✗ —— 内置打标会据此跳过下载，" \
            "用户选的新模型永远下不来（得到 %s）" % (_r[0],)
        # ② 指定已有模型时必须能取到（证明①不是因为环境没造好）
        assert P._wd14_onnx_files("moat-v2")[0], "指定已有模型时反而取不到（测试环境问题）"

        # ③ 顺序契约：先 pick（决定模型，含下载/回退说明），再取文件
        _tree = _ast.parse(open(os.path.join(ROOT, "preprocess.py"),
                                encoding="utf-8-sig").read())
        _fn = next(n for n in _ast.walk(_tree)
                   if isinstance(n, _ast.FunctionDef) and n.name == "_run_wd14_onnx")
        _pick = _files = None
        for c in _ast.walk(_fn):
            if isinstance(c, _ast.Call) and isinstance(c.func, _ast.Name):
                if c.func.id == "pick_wd14_model" and _pick is None:
                    _pick = c.lineno
                elif c.func.id == "_wd14_onnx_files" and _files is None:
                    _files = c.lineno
        assert _pick is not None and _files is not None, \
            "_run_wd14_onnx 里没找到 pick_wd14_model / _wd14_onnx_files 的调用"
        assert _pick < _files, \
            "_run_wd14_onnx 里先取文件后决定模型（L%d < L%d？）✗ —— 先取文件会拿到旧模型" \
            "并跳过下载，用户选的新模型就永远用不上 ✗" % (_pick, _files)
    finally:
        P._wd14_model_roots = _orig_roots
        _sh.rmtree(tmp, ignore_errors=True)
    print("WD14_RESPECTS_SELECTED_MODEL_OK")


def test_anima_qwen3_pick_guards():
    """Anima「指定 Qwen3 路径」：选错目录必须拦下、能恢复默认、失效必须说出来。

    ★ 2026-09-20 用户反馈（群内转述，后经用户确认属实 ✓）：
      「训练器第一次用让选 qwen3 的路径位置或者下载，选了以后就识别不到 qwen3 了，
        就算那个路径有也不行，还问有啥办法恢复默认路径」

      复现后确认：他选的是 **ComfyUI 的 models 大目录** ✗
      原因：`_anima_component_ok()` 用 `os.walk` **递归**找任意 `model.safetensors`，
      于是「models 大目录」（下面全是别的模型）也**校验通过** ✗
      → 运行时把这个大目录当 Qwen3 交给 sd-scripts → 里面没有 Qwen3 的
        config.json/tokenizer → 加载不到 → 用户看到的就是「识别不到，路径明明有」✗
      而且校验当时还回了「就绪」→ 用户完全不知道自己选错了 ✗

    判据：
      ① 选「大目录」（本层无权重、只有子目录里有）→ **必须被拒** ✓
      ② 选合法 Qwen3 文件夹 → 必须通过，且运行时确实用它 ✓
      ③ 指定后路径失效 → status 必须 `stale=True` 并给出原因（不得静默回落 ✗）
      ④ `anima_clear_component` 能清除指定（用户要的「恢复默认」✗ 以前完全没有入口）
    """
    import shutil as _sh
    import tempfile as _tf
    import Kohya一键工具 as core        # noqa: E402

    # 会写真实 settings.json → 先备份，结束恢复（不能弄丢用户设置）
    _sp = core._settings_path()
    _bak = open(_sp, encoding="utf-8").read() if os.path.isfile(_sp) else None
    tmp = _tf.mkdtemp(prefix="anima_guard_")

    def _clear_manual():
        _s = dict(core._load_app_settings() or {})
        _s.pop("anima_qwen3_path", None)
        core._save_app_settings(_s)

    try:
        # ① 像 ComfyUI 的 models 大目录：本层没权重，全在子目录里
        big = os.path.join(tmp, "models")
        for sub in ("unet", "checkpoints", "loras"):
            d = os.path.join(big, sub)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "sd_xl_base.safetensors"), "wb") as f:
                f.write(b"0" * (3 * 1024 * 1024))
        _clear_manual()
        ok, why = core.anima_set_component("qwen3", big)
        assert not ok, "把 models 大目录当 Qwen3 接受了 ✗（用户选错却以为成功）"
        assert core.anima_get_component("qwen3") is None, "大目录竟然还生效 ✗"

        # ①b ★ 复刻用户 v0.17.7 日志里那次失败的确切形态：
        #     大目录**本层有个缺 model_type 的 config.json** + 一个权重文件 ✗
        #     训练时报：Unrecognized model … Should have a model_type key in its config.json
        #     上一版只数权重个数、没读 config 内容 → 放行 ✗ → 训练才炸 ✗
        big2 = os.path.join(tmp, "ComfyUI", "models")
        os.makedirs(os.path.join(big2, "unet"), exist_ok=True)
        with open(os.path.join(big2, "config.json"), "w", encoding="utf-8") as f:
            f.write('{"architectures": ["SomethingElse"]}')      # ← 缺 model_type ✗
        with open(os.path.join(big2, "some_model.safetensors"), "wb") as f:
            f.write(b"0" * (2 * 1024 * 1024))
        with open(os.path.join(big2, "unet", "sd_xl.safetensors"), "wb") as f:
            f.write(b"0" * (3 * 1024 * 1024))
        _clear_manual()
        ok_b, why_b = core.anima_set_component("qwen3", big2)
        assert not ok_b, "「本层有缺 model_type 的 config.json」的大目录仍被接受 ✗" \
                         "（这正是用户 v0.17.7 训练时报 Unrecognized model 的原因）"
        assert "model_type" in why_b, "拦下了但没说明是 model_type 的问题 ✗（用户不知道该改什么）"

        # ①c config.json 明确是别的模型 → 拒绝
        other = os.path.join(tmp, "other")
        os.makedirs(other, exist_ok=True)
        with open(os.path.join(other, "config.json"), "w", encoding="utf-8") as f:
            f.write('{"model_type": "clip"}')
        with open(os.path.join(other, "model.safetensors"), "wb") as f:
            f.write(b"0" * (2 * 1024 * 1024))
        _clear_manual()
        assert not core.anima_set_component("qwen3", other)[0], \
            "非 Qwen3 的 config.json 竟被接受 ✗"

        # ② 合法的 Qwen3 文件夹：必须通过且被使用
        okd = os.path.join(tmp, "good", "Qwen3-0.6B")
        os.makedirs(okd, exist_ok=True)
        with open(os.path.join(okd, "config.json"), "w", encoding="utf-8") as f:
            f.write('{"model_type": "qwen3", "architectures": ["Qwen3ForCausalLM"]}')
        with open(os.path.join(okd, "model.safetensors"), "wb") as f:
            f.write(b"0" * (2 * 1024 * 1024))
        _clear_manual()
        ok2, why2 = core.anima_set_component("qwen3", okd)
        assert ok2, "合法的 Qwen3 文件夹反被拒 ✗（会误伤正常用户）：%s" % why2
        _rp, _rb = core._anima_find_qwen3_any()
        assert os.path.normcase(_rp or "") == os.path.normcase(okd), \
            "运行时没用指定的路径（得到 %s）" % _rp

        # ②b ⚠️ 2026-09-22 **改口径**：**目录**里没有 config.json → **必须拒** ✗
        #     原来这里断言"必须通过"，理由是「sd-scripts 会用内置配置加载它」✗ ——
        #     但用户日志（KohyaLoRA_项目_0922_2215_20260922，RTX 3060 Laptop）**证伪了它** ✗：
        #        `--qwen3=D:/moxin/wenben`（自建目录、无 config.json）
        #          → anima_utils.load_qwen3_tokenizer(路径)
        #          → AutoTokenizer.from_pretrained(路径, local_files_only=True) ✗
        #          → ValueError: Unrecognized model in D:/moxin/wenben.
        #             Should have a `model_type` key in its config.json ✗
        #        —— 训练**一步都没进去** ✓
        #     即：`--qwen3=` 对**目录**用的是**纯 HuggingFace 目录语义** ✗
        #        「单文件模式 = 传目录也行」的假设**不成立** ✗
        #     → 宁可**选的时候就说清楚** ✓，也不要拖到训练才炸 ✗
        #       （真要只给权重文件：请选**文件**，见 ②c ✓）
        _only = os.path.join(tmp, "only", "qwen3_weights")
        os.makedirs(_only, exist_ok=True)
        with open(os.path.join(_only, "model.safetensors"), "wb") as f:
            f.write(b"0" * (2 * 1024 * 1024))
        _clear_manual()
        _ok_only, _why_only = core.anima_set_component("qwen3", _only)
        assert not _ok_only, \
            "无 config.json 的目录竟被判「就绪」✗ —— 训练到这一步必炸（本次修复点）"
        assert "config.json" in _why_only, \
            "拒绝时必须讲清是缺 config.json ✗：%s" % _why_only

        # ②c 但**直接选权重文件**（文件路径）这条路必须仍然可用 ✓（别收紧过头 ✗）
        assert core.anima_set_component(
            "qwen3", os.path.join(_only, "model.safetensors"))[0], \
            "「选文件」这条路被误伤 ✗ —— 收紧不能连它一起砍掉"

        # ③ 指定后失效 → 必须明确说明（不得静默回落）
        #    ⚠️ 要删**当前指定的那个**（②b 已把指定换成 _only）✗ 删错目录会测不出问题
        _sh.rmtree(os.path.join(tmp, "only"), ignore_errors=True)
        _st = (core.anima_component_status().get("qwen3") or {})
        assert _st.get("stale"), "指定的路径失效了却没有任何提示 ✗（用户会不明所以）"
        assert _st.get("stale_why"), "只说失效、不说原因 ✗"

        # ④ 恢复默认
        ok3, _msg = core.anima_clear_component("qwen3")
        assert ok3 and not core.anima_get_component_raw("qwen3"), "恢复默认没清掉指定 ✗"
        assert not (core.anima_component_status().get("qwen3") or {}).get("stale"), \
            "清除后仍报失效 ✗"

        # ⑤ ★ 必须有**常显入口**（2026-09-20 用户实测：「好像没有这个啊」✗）
        #    此前唯一入口在「底模下载」那条几乎走不到的分支里 ✗ 一旦指定错就再也进不去 ✗
        #    没有入口 = 上面的「恢复默认」用户根本点不到 = 等于没做 ✓
        _gsrc = open(os.path.join(ROOT, "kohya_gui.py"), encoding="utf-8-sig").read()
        assert "btn_anima_components" in _gsrc, "缺少 Anima 组件常显入口 ✗（用户无法自助恢复）"
        _i_fn = _gsrc.index("def _build_main_cards")
        _i_next = _gsrc.find("\n    def ", _i_fn + 10)
        _body = _gsrc[_i_fn:_i_next if _i_next > 0 else len(_gsrc)]
        assert "btn_anima_components" in _body, \
            "入口不在 `_build_main_cards` 里 → 可能随模式隐藏 ✗（被卡住时可能不在 Anima 模式）"
        assert "↩ 恢复默认" in _gsrc, "对话框里没有「恢复默认」按钮 ✗"
    finally:
        if _bak is not None:
            with open(_sp, "w", encoding="utf-8") as f:
                f.write(_bak)
        else:
            try:
                os.remove(_sp)
            except Exception:
                pass
        _sh.rmtree(tmp, ignore_errors=True)
    print("ANIMA_QWEN3_PICK_GUARD_OK")


def test_fizgig_sample_interval_is_epochs():
    """Fizgig 的「采样预览间隔」必须**直接就是轮数** —— 填 10 = 每 10 轮一次。

    ★ 2026-09-21 用户实测纠正（原文：「那不是标的轮吗？所以填的 10 轮一次啊」）✗
      上一版把这个字段当**步数**、内部再换算：`round(N ÷ 每轮步数)` ✗
      于是他按"轮"理解填 10 → round(10÷100)=0 → 下限 1 → **实际每 1 轮** ✗
      → 期望「每 10 轮」却得到「每 1 轮」，**差 10 倍** ✗
      → 他反馈的现象：「还是 100 张预览一次」（1 轮 = 100 步 ✓）
      单位不一致是**设计的问题** ✓ 现在与引擎口径统一：填几就是几轮 ✓
      （Fizgig 按轮组织采样 —— epoch-0 的 Sample at Start + 每个 epoch 各一次，
        做不到「每 N 步」；要按步得用 Krea2（musubi）的 --sample_every_n_steps ✓）
    """
    import Kohya一键工具 as core        # noqa: E402

    # 用户这次的实况：每轮 100 步、共 40 轮、他填 10
    assert core._fizgig_sample_epochs({"sample_interval": 10}, 100, 40) == 10, \
        "填 10 应等于「每 10 轮」✗（又变回按步换算了？）"
    assert core._fizgig_sample_epochs({"sample_interval": 1}, 100, 40) == 1
    assert core._fizgig_sample_epochs({"sample_interval": 3}, 100, 40) == 3
    # 留空/0 → 沿用「约每 100 步」启发式（每轮 100 步 → 1 轮）
    assert core._fizgig_sample_epochs({}, 100, 40) == 1, "留空时应是每 1 轮"
    assert core._fizgig_sample_epochs({"sample_interval": 0}, 100, 40) == 1
    # 超过总轮数 → 限制在总轮数（避免一次都不出）
    assert core._fizgig_sample_epochs({"sample_interval": 100}, 100, 40) == 40
    # 每轮不是 100 步时，留空仍约每 100 步
    assert core._fizgig_sample_epochs({}, 25, 40) == 4

    # 日志文案要说人话（用户能否看懂"实际会怎样"）
    _n = core._fizgig_sample_note({"sample_interval": 10}, 100, 40,
                                 core._fizgig_sample_epochs({"sample_interval": 10}, 100, 40))
    assert "每 10 轮" in _n and "1000 步" in _n, "采样说明没写清轮数与对应步数：%s" % _n

    # 界面：这个字段的单位必须**随模式变**（Fizgig=轮、其它=步）✗ 不能一律写"(步)"
    _g = open(os.path.join(ROOT, "kohya_gui.py"), encoding="utf-8-sig").read()
    assert "采样预览间隔(轮)" in _g, "界面缺少「(轮)」的动态标签 ✗"
    assert 'core.interval_unit_for(self.mode, "sample_interval")' in _g, \
        "界面单位没有使用统一的模式映射 ✗（可能与训练参数不一致）"
    print("FIZGIG_SAMPLE_INTERVAL_IS_EPOCHS_OK")


def test_interval_values_are_scoped_by_unit():
    """Step-based and epoch-based modes must not reinterpret one shared interval value."""
    import Kohya一键工具 as core        # noqa: E402

    cache = core.capture_interval_values({}, "qwen_image", {
        "save_every": "200", "sample_interval": "200",
    })
    assert core.interval_values_for_mode(cache, "qwen_image") == {
        "save_every": "200", "sample_interval": "200",
    }
    assert core.interval_values_for_mode(cache, "krea2_fz") == {
        "save_every": "", "sample_interval": "",
    }, "从按步模式切到 Fizgig 时，200 不应悄悄变成 200 轮"

    cache = core.capture_interval_values(cache, "krea2_fz", {
        "save_every": "1", "sample_interval": "2",
    })
    assert core.interval_values_for_mode(cache, "krea2_fz") == {
        "save_every": "1", "sample_interval": "2",
    }
    assert core.interval_values_for_mode(cache, "qwen_image") == {
        "save_every": "200", "sample_interval": "200",
    }, "回到按步模式时应恢复该单位下原先的值"
    assert core.interval_unit_for("krea2", "save_every") == "epochs"
    assert core.interval_unit_for("krea2", "sample_interval") == "steps"
    assert core.interval_unit_for("krea2_fz", "sample_interval") == "epochs"
    assert core.interval_unit_for("krea2_at", "save_every") == "steps"

    # 直接跑 UI 的捕获/恢复方法，确保切换物理模式时输入框不会沿用另一单位的数值。
    import kohya_gui as gui        # noqa: E402

    class _Value:
        def __init__(self, value):
            self.value = str(value)

        def get(self):
            return self.value

        def set(self, value):
            self.value = str(value)

    app = object.__new__(gui.App)
    app.mode = "qwen_image"
    app._interval_values = {}
    app._applying_preset = False
    app.param_vars = {key: _Value("200") for key in ("save_every", "sample_interval")}
    app._capture_interval_values()
    app.mode = "krea2_fz"
    app._restore_interval_values()
    assert all(app.param_vars[key].get() == "" for key in ("save_every", "sample_interval")), \
        "切到 epoch 引擎后应使用默认值，不能把 200 步当成 200 轮"
    app.param_vars["save_every"].set("1")
    app.param_vars["sample_interval"].set("2")
    app._capture_interval_values()
    app.mode = "qwen_image"
    app._restore_interval_values()
    assert all(app.param_vars[key].get() == "200" for key in ("save_every", "sample_interval")), \
        "切回 step 引擎后应恢复原来的步数设置"

    # 项目 JSON 必须同时保存当前值和另一单位下的缓存值。
    app.current_project = None
    app.base_type = "sdxl"
    app._collect_params = lambda: {"mode": app.mode, "base_type": app.base_type}
    project_data = gui.App._collect_project_data(app)
    assert project_data["interval_values"]["steps"] == {
        "save_every": "200", "sample_interval": "200",
    }
    assert project_data["interval_values"]["epochs"] == {
        "save_every": "1", "sample_interval": "2",
    }, "自动保存项目时不能丢掉另一单位的间隔设置"
    print("INTERVAL_VALUES_SCOPED_BY_UNIT_OK")


def test_fizgig_int8_vram_guard():
    """16G 卡跑 Krea2(Fizgig)：必须把分辨率压到 512，并在引擎确认时告警。

    ★ 2026-09-21 用户实测（5060 Ti 16G / Krea2 Fizgig / 768px / int8，日志 v0.17.8）：
      「每次建新项目练，一样设置时间越来越长，好几次 11 小时；删项目重来几次才变 3 小时；
        而且步数越跑越慢」

      根因（引擎原文，日志 L175）：
        `[int8] W8A8 base is fully resident … block swap can't reduce its footprint;
         forcing blocks_to_swap=0` ✗
      → int8 底模**必须全驻留显存**，工具按显存配的 blocks_to_swap **被引擎强制改回 0** ✗
      → 需 ~18G，而 16G 卡装不下 → 溢出到系统内存 / 硬盘页面文件 ✗
      → 实测 8~19 s/it（2052 步 ≈ 11 小时 ✗）
      用户三个现象全部由此解释：
        · 时间越来越长 = 换页程度随内存/磁盘状态变 ✓
        · 删项目才变快 = 释放磁盘后页面文件有地方写 ✓
        · 越跑越慢     = 换页随时间恶化 ✓
      —— 与「新建项目」无关 ✓

    判据：
      ① **int8** + ≤19G（取整）+ >512 → 压到 512 ✓ 且**必须打印说明**（不许静默改 ✗）
         ⚠️ 2026-09-22 修：本保护**只对 int8 生效** ✗ —— NF4（底模仅 ~5.6G）/ FP8 档
            砍分辨率纯属白丢画质 ✗（由 test_fizgig_clamp_resolution_only_for_int8 覆盖 ✓）
      ② 显存够（≥20）或已是 512 / 显存未知 → **不动** ✓
      ③ 引擎那条原文出现时必须告警 ✓ 且要澄清「与新建项目无关」✓
      ④ 普通日志 / 空日志 → 不许误报 ✗
    """
    import Kohya一键工具 as core        # noqa: E402

    # ★ 2026-09-22 改：本函数现在**只对 int8 生效** ✗（NF4 底模仅 ~5.6G，768 放得下 ✓）
    #   → 这里显式传 int8 档位 ✓；「NF4 不该被降」由 test_fizgig_clamp_resolution_only_for_int8 覆盖 ✓
    _I8 = ("--quant_int8", "bf16")
    # ① 用户实况：DXGI 报 15.67G、分辨率 768
    _logs = []
    assert core._fizgig_clamp_resolution(15.673828125, 768, _I8, _logs.append) == 512, \
        "16G 卡 + int8 + 768px 必须降到 512 ✗（否则 int8 溢出 → 越跑越慢）"
    _t = "\n".join(_logs)
    assert "512" in _t, "降了但没打印说明 ✗（静默改用户设置）"
    assert "越跑越慢" in _t, "没说清后果 ✗"

    # ② 不该动的情况
    for _vram, _reso, _want, _desc in ((24.0, 768, 768, "24G 卡不动"),
                                       (19.9, 768, 768, "≈20G 档不动"),
                                       (16.0, 512, 512, "已是 512 不动"),
                                       (None, 768, 768, "显存未知不猜"),
                                       (19.0, 1024, 512, "19G 中间档 + 1024 → 512"),
                                       (12.0, 768, 512, "12G + 768 → 512")):
        assert core._fizgig_clamp_resolution(_vram, _reso, _I8, lambda s: None) == _want, \
            "%s ✗（得到 %s）" % (_desc, core._fizgig_clamp_resolution(_vram, _reso, _I8, lambda s: None))

    # ③ 用用户日志里的**逐字原文**
    _real = ("INFO:fizgig.krea2.trainer:[int8] W8A8 base is fully resident (staged quantise -> GPU) "
             "— block swap can't reduce its footprint; forcing blocks_to_swap=0.")
    _l2 = []
    assert core._warn_fizgig_int8_resident(_real, _l2.append), "真实日志原文没被识别 ✗"
    _t2 = "\n".join(_l2)
    assert "18G" in _t2, "没说明需要多少显存 ✗"
    assert "与「新建项目」无关" in _t2, "没澄清用户的核心困惑 ✗"

    # ④ 不许误报
    assert not core._warn_fizgig_int8_resident("普通日志", lambda s: None), "普通日志误报 ✗"
    assert not core._warn_fizgig_int8_resident("", lambda s: None), "空日志误报 ✗"
    print("FIZGIG_INT8_VRAM_GUARD_OK")


def test_save_interval_is_epochs_for_krea2():
    """Krea2/FLUX.2（含 Fizgig）的「模型保存间隔」按**轮** —— 填超总轮数必须警告。

    ★ 2026-09-21 用户反馈（欣欣 / Krea2 Fizgig，界面截图佐证）：
      「输出的 LoRA 快照好像也没了，以前都有很多个，新版就没了」
      他界面里填的是 **200** ✗ 而这条路用 `--save_every_n_epochs <save_every>` ✗
      → 200 轮存一次、训练只有 18~22 轮 → **一个中间快照都不会产生** ✗
      日志只留一句「本次没有产生可续训的快照」，用户读成"新版不存快照了"✗

    他为什么会填 200 ✗：原界面提示把「留空=默认 200 **步**」和「N **轮**」写在同一句里 ✗
      （与「采样预览间隔」是同一类单位混淆 ✓）

    判据：
      ① 值 > 总轮数 → 必须警告「不会保存任何中间快照」+ 给改法 ✓
      ② 正常值（1/2/留空）→ **不许**误报 ✓
      ③ 返回值**不能被改**（尊重用户填的值 ✓）
      ④ 界面标签按模式在「(轮) / (步)」之间切 ✓
    """
    import Kohya一键工具 as core        # noqa: E402

    # ① 用户实况：填 200、训练 18 轮
    _lg = []
    _v = core._save_every_note({"save_every": 200}, 18, _lg.append, "Krea2(Fizgig)")
    _t = "\n".join(_lg)
    assert _v == 200, "不该改变用户填的值（得到 %s）" % _v
    assert "不会保存任何中间快照" in _t, "没警告「一个快照都不会存」✗（用户的核心困惑）"
    assert "留空" in _t, "没给改法 ✗"

    # ② 正常值不许误报
    for _p, _e, _d in (({"save_every": 1}, 18, "填 1"), ({}, 18, "留空"),
                       ({"save_every": "2"}, 18, "填 2"), ({"save_every": 18}, 18, "正好等于轮数")):
        _l2 = []
        core._save_every_note(_p, _e, _l2.append, "Krea2")
        assert not any("不会保存任何中间快照" in s for s in _l2), "%s 被误报 ✗" % _d

    # ③ 界面标签按模式切
    _g = open(os.path.join(ROOT, "kohya_gui.py"), encoding="utf-8-sig").read()
    assert "模型保存间隔(轮)" in _g, "界面缺少「(轮)」的动态标签 ✗"
    assert 'core.interval_unit_for(self.mode, "save_every")' in _g, \
        "保存间隔单位没有使用统一的模式映射 ✗（可能与训练参数不一致）"
    print("SAVE_INTERVAL_IS_EPOCHS_OK")


def test_env_selftest_catches_broken_env():
    """深度环境自检必须**抓得住「包装不全」** —— 而不是拖到训练中途才炸 ✗

    ★ 2026-09-22：三份用户日志、三台完全不同的机器、三种坏法，
      而工具**一个都没提前发现** ✗：
        · ① RTX 5070 12G：`torch/lib/c10.dll` 初始化失败（WinError 1114，VC++ 运行库 14.36 < 14.44）
        · ② RTX 5060 Ti 16G：`transformers/models` 目录损坏（WinError 1392）
        · ③ AMD RX 9060 XT 8G：`torch/_C/` 缺失 → `'torch._C' is not a package`
      根因：环境检查只用 `find_spec()`（看文件/目录在不在 ✗），
      或只 `import torch` —— 而 `import torch` **根本用不到** `_C._distributed_c10d` ✗
      → 三种坏法全部通过 ✗ → 全都拖到「训练跑到一半」才炸 ✗
        （①②③ 的数据检查、latents 缓存、文本编码器缓存、模型加载**全白跑** ✗）

    本测试用**真 venv** 复现第 ③ 种（这是最隐蔽的一种：`import torch` 会**成功** ✗）。
    判据：① 必须**点名** `torch._C._distributed_c10d` ✓
          ② 该项必须标「必需」✓（否则不会拦下训练，等于没修 ✗）
          ③ `torch` 本体**不能**被误报 ✓（它确实 import 得到 ✓）
          ④ 三份日志的三种坏法，建议文案都能识别 ✓

    ⚠️ 为什么必须**真跑一遍**（不旁路）✗：上次教训 —— 只测"看起来对"会绕开除问题那一步 ✓
      这里同理：只有真起一个 venv、真往里塞"半个包"，才能证明自检抓得住 ✓
    """
    import Kohya一键工具 as core     # noqa: E402
    import shutil as _sh
    import subprocess as _sp
    import tempfile as _tf

    _sil = lambda *a, **k: None       # noqa: E731
    tmp = _tf.mkdtemp(prefix="estest_")
    try:
        venv = os.path.join(tmp, "v")
        _sp.run([sys.executable, "-m", "venv", "--without-pip", venv],
                check=True, capture_output=True)
        vpy = os.path.join(venv, "Scripts", "python.exe")
        sp = os.path.join(venv, "Lib", "site-packages")

        # ① 空 venv：自检必须不通过
        _ok1, _f1, _r1 = core.env_selftest(vpy, _sil, quiet=True)
        assert not _ok1 and _f1, "空 venv 竟然通过了自检 —— 等于没查 ✗"

        # ② 塞「有 torch、无 _C」的假包 → 必须点名 _distributed_c10d
        os.makedirs(os.path.join(sp, "torch"))
        with open(os.path.join(sp, "torch", "__init__.py"), "w", encoding="utf-8") as f:
            f.write("__version__ = '0.0.0'\n")
        # ⚠️ 必须把**其余必需项**也塞上 ✓ —— 否则测的就变成"缺 torchvision/transformers"了 ✗
        #   （那些缺了本来就该拦 ✓ 与本测试要守的「只缺分布式扩展不许拦」是两回事 ✗）
        for _m in ("torchvision", "transformers"):
            os.makedirs(os.path.join(sp, _m), exist_ok=True)
            with open(os.path.join(sp, _m, "__init__.py"), "w", encoding="utf-8") as f:
                f.write("\n")
        _ok2, _f2, _r2 = core.env_selftest(vpy, _sil, quiet=True)
        _mods = [x[0] for x in _f2]
        _key = "torch._C._distributed_c10d"
        assert _key in _mods, \
            "没能抓到 torch._C 缺失 ✗ —— 这是日志 ③ 的坏法（只 import torch 是成功的 ✗）"
        assert "torch" not in _mods, "torch 本体被误报了 ✗ —— 它确实 import 得到，误报会让自检不可信"

        # ★★ 2026-09-22 二次修正（**必须守住这条，否则会再次误伤**）★★
        #   v0.17.11 把 `torch._C._distributed_c10d` 当成「必需」✗ → 弹出
        #   「AMD 依赖已安装，但环境验证失败」把用户**卡在安装界面** ✗
        #   而实测（用户日志 KohyaLoRA_055_20260922，AMD RX 7800 XT）：用户 0.17.10 训练一切正常 ✓
        #   → AMD ROCm 版 PyTorch **可能本来就不含** 它 ✓（只影响 distributed/DTensor 路径 ✓）
        assert not any(x[0] == _key and x[2] for x in _f2), \
            "%s 被标成「必需」✗ —— AMD ROCm 版可能本来就没有它，会误拦正常用户" % _key
        assert _ok2 is True, \
            "torch 本体可用、只是缺分布式扩展时**不该拦下训练** ✗（v0.17.11 就是这么误伤的）"
        _adv = core.env_selftest_advice(_f2)
        assert "不影响开始训练" in _adv, "非必需项失败时该说「不影响开始训练」✗：%s" % _adv[:220]
        assert "没白跑训练时间" not in _adv, \
            "非必需项失败却说「没白跑训练时间」✗ —— 那等于把用户卡住（v0.17.11 的错）"
        assert "不等于环境坏了" in _adv, "没澄清「这不算环境坏」✗ —— 用户会被误导去重装"

        # ③ 三份日志的原始报错，各自都要能识别
        _cases = (
            ("WinError 1392", "OSError: [WinError 1392] 文件或目录损坏且无法读取。: 'D:\\x\\transformers\\models'",
             "文件或目录损坏"),
            ("WinError 1114", "OSError: [WinError 1114] 动态链接库(DLL)初始化例程失败。Error loading \"c10.dll\"",
             "VC++ 运行库"),
            # ⚠️ 这里要的是「澄清」而不是「判定坏了」✗ —— 见上面二次修正的说明 ✓
            ("torch._C", "ModuleNotFoundError: No module named 'torch._C._distributed_c10d'; "
                         "'torch._C' is not a package", "不等于环境坏了"),
        )
        for _nm, _err, _want in _cases:
            _a = core.env_selftest_advice([("m", "M", True, _err)])
            assert _want in _a, "「%s」这类坏法没给出对应说明（缺「%s」）✗" % (_nm, _want)

        # ④ **必需项**失败时，必须说清「训练没开始、没白跑」（这跟上面正好相反 ✓）
        _a_req = core.env_selftest_advice(
            [("torch", "PyTorch", True, "OSError: [WinError 1114] 动态链接库(DLL)初始化例程失败")])
        assert "没白跑训练时间" in _a_req, \
            "必需项真失败时必须说清「训练没有开始、没白跑」✗"
    finally:
        _sh.rmtree(tmp, ignore_errors=True)
    print("ENV_SELFTEST_CATCHES_BROKEN_ENV_OK")


def test_fizgig_clamp_resolution_only_for_int8():
    """Krea2(Fizgig) 的分辨率钳制**只该对 int8 生效** ✗

    ★ 2026-09-22 修：原先不看量化方式，≤19G 一律把分辨率砍到 512 ✗ ——
      于是**连 NF4 用户也被砍** ✗。可 NF4 底模只 ~5.6GB ✓
      （`_fizgig_quant_swap` 的注释与本函数原来的提示都写着 ✓），
      16G 卡上 NF4 + 768px **完全放得下** ✓ → 砍到 512 纯属**白丢画质** ✗
      ★ 为什么该降的是 int8：它的底模必须**全驻留**（引擎强制 blocks_to_swap=0 ✗），
      需 ~18G 常驻 > 16G ✗ → 溢出换页 → 越跑越慢 ✗（实测 8~19 s/it）
    判据：int8 且 ≤19G → 降 512 ✓；**其余任何档位**（NF4 / fp8 / ≥20G / 本来 ≤512）→ **原样** ✓
    """
    import Kohya一键工具 as core     # noqa: E402

    _sil = lambda *a, **k: None       # noqa: E731
    _i8 = ["--quant_int8", "bf16"]
    _nf4 = ["--quantize_4bit"]
    assert core._fizgig_clamp_resolution(15.67, 768, _i8, _sil) == 512, "int8 + 16G 该降到 512"
    assert core._fizgig_clamp_resolution(15.67, 768, _nf4, _sil) == 768, \
        "NF4 + 16G 被误降到 512 ✗ —— NF4 底模只 ~5.6G，768 放得下（本次修复点）"
    assert core._fizgig_clamp_resolution(15.67, 768, [], _sil) == 768, "fp8 档不该被降"
    assert core._fizgig_clamp_resolution(24.0, 768, _i8, _sil) == 768, "24G 装得下 int8，不该降"
    assert core._fizgig_clamp_resolution(15.67, 512, _i8, _sil) == 512, "本来就是 512，保持"
    assert core._fizgig_clamp_resolution(None, 768, _i8, _sil) == 768, "显存未知时不猜"
    print("FIZGIG_CLAMP_ONLY_INT8_OK")


def test_at_image_custom_model():
    """第三引擎「自定义模型」：默认不变、自定义生效、能恢复、不覆盖官方模型、不破坏其它设置。

    ★ 2026-09-22 用户提出（原话）：
      「那想训练其他的 QwenImage 的模型呢，像最新出的 2.1，我看 AI toolkit 官方已经支持了」
      → ai-toolkit 的支持列表一直在加（Qwen-Image-2.1 / Qwen-Image-Edit 系列 …✗），
        而工具把 model_id / arch 写死在 AT_IMAGE_MODELS 里 ✗ → 用户**完全没有入口** ✗

    判据（**第 ① 条最重要** ✗）：
      ① 没设置过时，info 与本地目录**必须与以前完全一致** ✓
         （否则已下好的 34~40G 会被判成"未下载"→ 用户白重下 ✗）
      ② 自定义 model_id → info 被覆盖 ✓ 且用**独立目录** ✓（不覆盖官方那份 ✓）
      ③ 自定义本地目录 → 直接用它（跳过下载 ✓）
      ④ 恢复默认 → 一切回到官方 ✓
      ⑤ 读-改-写：**不许破坏 app_settings 里的其它键** ✗
      ⑥ 两个模式（qwen_image / zimage）互不干扰 ✓
    """
    import Kohya一键工具 as core      # noqa: E402
    import shutil as _sh
    import tempfile as _tf

    tmp = _tf.mkdtemp(prefix="atcustom_")
    _orig = core._settings_path
    _orig_data_sub = core.data_sub
    core._settings_path = lambda: os.path.join(tmp, "settings.json")   # 隔离，别动真实配置 ✓
    core.data_sub = lambda *parts: os.path.join(tmp, *parts)  # 下载路径也隔离，避免真实缓存污染测试 ✓
    try:
        M = "qwen_image"
        # ① 默认必须与以前一致
        i0 = core.at_image_info(M)
        d0 = core.at_image_local_dir(M)
        assert i0.get("model_id") == core.AT_IMAGE_MODELS[M]["model_id"], \
            "没设置过时 model_id 被改动了 ✗（会让已下载的模型判定失效）"
        assert os.path.basename(d0) == M, \
            "没设置过时本地目录变了 ✗（%s）—— 已下好的模型会被判成未下载、白重下" % d0

        # ② 自定义仓库名
        core.at_image_custom_set(M, {"model_id": "Qwen/Qwen-Image-2.1", "arch": "qwen_image_2",
                                     "min_vram": 12, "rec_vram": 16, "resident_vram": 20})
        i1 = core.at_image_info(M)
        d1 = core.at_image_local_dir(M)
        assert i1.get("model_id") == "Qwen/Qwen-Image-2.1" and i1.get("arch") == "qwen_image_2", \
            "自定义 model_id / arch 没生效 ✗：%s" % {k: i1.get(k) for k in ("model_id", "arch")}
        assert i1.get("min_vram") == 12, "自定义显存档位没生效 ✗"
        assert d1 != d0, "自定义后仍用官方目录 ✗ —— 会把官方那份 40G 覆盖掉"

        # ②b Qwen-Image-2.1 下载器请求对应的 ModelScope 仓库，而不是默认 2512。
        _urls = []
        def _fake_download(url, dest, *_args, **_kwargs):
            _urls.append(url)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            open(dest, "wb").write(b"metadata")
            return True
        with patch.object(core, "_at_image_ms_file_list", return_value=["model_index.json"]), \
             patch.object(core, "_download_with_resume", side_effect=_fake_download), \
             patch.object(core, "at_image_model_ready", return_value=True):
            assert core._at_image_ms_download(M, lambda *_a: None), "Qwen-Image-2.1 下载器没完成"
        assert _urls and "/models/Qwen/Qwen-Image-2.1/resolve/master/" in _urls[0], \
            "Qwen-Image-2.1 下载器请求了错误仓库: %s" % _urls

        # ③ 自定义本地目录
        loc = os.path.join(tmp, "my_model")
        os.makedirs(loc)
        core.at_image_custom_set(M, {"local_dir": loc})
        assert core.at_image_local_dir(M) == loc, "指定本地目录后没用它 ✗（会白下一遍）"
        assert core.at_image_info(M).get("model_id") == loc, \
            "未知架构的旧设置应显示本地路径，不要误显示默认底模"

        core.at_image_custom_set(M, {"local_dir": loc, "arch": "qwen_image_2"})
        assert core.at_image_info(M).get("model_id") == "Qwen/Qwen-Image-2.1", \
            "旧版只存本地目录和架构时，应识别为 Qwen-Image-2.1"

        core.at_image_custom_set(M, {
            "local_dir": loc, "arch": "qwen_image_2",
            "text_encoder_path": os.path.join(tmp, "custom_text_encoder.safetensors"),
            "vae_path": os.path.join(tmp, "custom_vae.safetensors"),
        })
        _saved_components = core.at_image_custom_get(M)
        assert _saved_components.get("text_encoder_path", "").endswith("custom_text_encoder.safetensors"), \
            "手动文本编码器路径没有保存"
        assert _saved_components.get("vae_path", "").endswith("custom_vae.safetensors"), \
            "手动 VAE 路径没有保存"

        # ④ 恢复默认
        core.at_image_custom_set(M, {})
        assert core.at_image_info(M).get("model_id") == i0.get("model_id"), "恢复默认后 model_id 没回来 ✗"
        assert core.at_image_local_dir(M) == d0, "恢复默认后本地目录没回来 ✗"
        assert core.at_image_custom_get(M) == {}, "恢复默认后自定义设置没清空 ✗"

        # ⑤ 不能破坏 app_settings 的其它键
        core._save_app_settings({"some_other_key": 123})
        core.at_image_custom_set(M, {"model_id": "Qwen/Qwen-Image-2.1"})
        _s = core._load_app_settings()
        assert _s.get("some_other_key") == 123, \
            "写自定义模型把别的设置弄丢了 ✗（读-改-写 没做对）"

        # ⑥ 两个模式互不干扰
        core.at_image_custom_set("zimage", {"model_id": "Tongyi-MAI/Z-Image-Turbo"})
        assert core.at_image_info("qwen_image").get("model_id") == "Qwen/Qwen-Image-2.1", \
            "改 zimage 影响到了 qwen_image ✗"
        assert core.at_image_info("zimage").get("model_id") == "Tongyi-MAI/Z-Image-Turbo", \
            "zimage 的自定义没生效 ✗"
        # 清掉 zimage 的自定义，避免影响同进程内其它用例
        core.at_image_custom_set("zimage", {})
    finally:
        core._settings_path = _orig
        core.data_sub = _orig_data_sub
        _sh.rmtree(tmp, ignore_errors=True)
    print("AT_IMAGE_CUSTOM_MODEL_OK")


def test_at_image_qwen21_single_file():
    """Qwen-Image-2.1 的 Comfy-Org 单文件权重可直接作为 AI Toolkit 底模。"""
    import tempfile
    import shutil
    import yaml
    import Kohya一键工具 as core

    tmp = tempfile.mkdtemp(prefix="qwen21_single_file_")
    try:
        checkpoint = os.path.join(tmp, "qwen_image_2.1_bf16.safetensors")
        with open(checkpoint, "wb") as f:
            f.write(b"0" * (2 * 1024 * 1024))

        assert core.at_image_model_dir_ready(checkpoint, arch="qwen_image_2"), \
            "AI Toolkit 可接受的 Qwen-Image-2.1 safetensors 文件被误判为不完整模型"
        assert not core.at_image_model_dir_ready(checkpoint, arch="qwen_image"), \
            "单文件 Qwen-Image-2.1 权重不应被其它架构当作可用模型"

        with patch.object(core, "_settings_path", return_value=os.path.join(tmp, "settings.json")), \
             patch.object(core, "data_sub", side_effect=lambda *parts: os.path.join(tmp, *parts)):
            core.at_image_custom_set("qwen_image", {
                "local_dir": checkpoint, "model_id": "Qwen/Qwen-Image-2.1", "arch": "qwen_image_2"})
            assert core.at_image_model_ready("qwen_image"), \
                "指定本地 2.1 权重后仍被训练前检查判成未下载"
            info = core.at_image_info("qwen_image")
            info["model_id"] = core.at_image_local_dir("qwen_image")
            params = {"project": "qwen21_local", "rank": 16, "alpha": 16,
                      "unet_lr": "1e-4", "video_steps": 2000}
            cfg = os.path.join(tmp, "train.yaml")
            core.write_at_image_yaml(params, info, tmp, tmp, cfg)
            data = yaml.safe_load(open(cfg, encoding="utf-8"))
            model = data["config"]["process"][0]["model"]
            assert model.get("arch") == "qwen_image_2", model
            assert model.get("name_or_path") == checkpoint, model

        gui = open(os.path.join(ROOT, "kohya_gui.py"), encoding="utf-8-sig").read()
        assert "askopenfilename" in gui and "选择 Qwen-Image-2.1 权重文件" in gui, \
            "模型选择窗口没有提供 Qwen-Image-2.1 单文件选择入口"
        assert "文本编码器" in gui and "手动指定组件" in gui and "at_image_qwen21_component_file_ready" in gui, \
            "模型选择窗口没有提供手动选择 Qwen-Image-2.1 文本编码器/VAE 的入口"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("AT_IMAGE_QWEN21_SINGLE_FILE_OK")


def main():
    print("== Kohya-LoRA 工具 · 冒烟测试 ==")
    check("语法检查", test_syntax)
    check("导入 + 配置完整性（全部模式）", test_config_completeness)
    check("AI 图像模型配置", test_at_image_models)
    check("yaml 生成可解析", test_yaml)
    check("下载模型配置（FLUX/Anima/Krea2）", test_download_models)
    check("标签管理 v1 · 离线词典核心链路", test_tagging)
    check("Anima 合并包识别/剥离/缓存", test_anima_ckpt)
    check("采样预览不污染监控 + Fizgig 断点查找", test_monitor_sampling_and_fizgig_resume)
    check("训练完成按项目名导出成品", test_lora_naming)
    check("删项目清理图集数据 + 遗留数据清理", test_project_data_cleanup)
    check("标签批量操作：预演 + 快照撤销", test_label_editor_safety)
    check("主页输出目录入口", test_home_output_button)
    check("预处理进度（WD14 打标）", test_preprocess_progress)
    check("Anima 组件指定已有文件", test_anima_component_picker)
    check("Krea2 预热期说明（防「更新后变慢」误判）", test_krea2_warmup_notice)
    check("Krea2 auto 量化必须是 int8（fp8 是灾难档）", test_krea2_auto_quant_is_int8)
    check("WD14 打标模型可选 + 缺失静默回默认", test_wd14_model_selectable)
    check("任务进行中关闭窗口必须先确认", test_close_confirm_while_running)
    check("打标模型选择必须可见（不在折叠区）", test_wd14_selector_visible)
    check("打标模型能真的下载（完整正常路径）", test_wd14_download_http_path)
    check("打标模型缺失时回退到已有模型", test_wd14_model_fallback)
    check("无「用了但看不见」的名字（防同名静默失效）", test_no_undefined_names)
    check("界面提示的适用范围与代码一致", test_param_scope_matches_code)
    check("改过的标签能通过「重新处理」生效", test_preprocess_overwrite_picks_up_changed_captions)
    check("环境自检能抓到「包装不全」", test_env_selftest_catches_broken_env)
    check("Fizgig 分辨率钳制只对 int8 生效", test_fizgig_clamp_resolution_only_for_int8)
    check("第三引擎可自定义模型（默认不变+能恢复）", test_at_image_custom_model)
    check("Qwen-Image-2.1 可选择现有 safetensors 权重文件", test_at_image_qwen21_single_file)
    check("选了新打标模型就不能偷偷用旧模型", test_wd14_respects_selected_model)
    check("Anima 指定 Qwen3：选错要拦、能恢复默认、失效要说", test_anima_qwen3_pick_guards)
    check("Fizgig 采样间隔按「轮」算（填 10 = 每 10 轮）", test_fizgig_sample_interval_is_epochs)
    check("步/轮间隔值分别记忆，切换模式不偷换单位", test_interval_values_are_scoped_by_unit)
    check("16G 档防 int8 溢出：降 512 + 告警", test_fizgig_int8_vram_guard)
    check("保存间隔按「轮」+ 超总轮数要警告", test_save_interval_is_epochs_for_krea2)
    check("自带 Python / Git：选文件夹 → 识别 → 校验 → 采用", test_env_paths_custom)
    check("自带环境入口可见且能打开", test_env_locations_ui)
    check("Krea2 量化档必须按显存配块交换", test_fizgig_quant_swap_vram_table)
    check("高级参数：量化/块交换/编译按模式显隐", test_adv_rows_mode_gating)
    check("训练步数摘要跟输入 + 保存/采样间隔生效", test_steps_summary_and_intervals)
    check("标签撤销可连退多步", test_label_undo_stack)
    check("Python 环境来源校验 + 徽章如实显示", test_python_env_source_guard)
    check("训练 native 崩溃诊断", test_native_crash_diagnosis)
    check("高覆盖特征锁进固定前缀", test_high_coverage_tag_lock)
    print("-" * 40)
    if FAILED:
        print("✘ 失败 %d 项: %s" % (len(FAILED), "、".join(FAILED)))
        return 1
    print("✔ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
