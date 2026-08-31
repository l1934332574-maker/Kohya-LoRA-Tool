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
    for f in ("Kohya一键工具.py", "kohya_gui.py", "preprocess.py", "video_caption.py"):
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
            if p0["datasets"][0]["resolution"] != [768, 768]:
                raise AssertionError("Krea2(AT) 16G 未压到 768")
            if "sample" in p0 or p0["train"].get("disable_sampling") is not True:
                raise AssertionError("Krea2(AT) 16G 采样未关闭")
            cfg = os.path.join(tmp, "krea2_at24.yaml")
            core.write_krea2_at_yaml(dict(params, resolution="1024", sample_preview=True), vd, tmp, cfg, vram_gb=24)
            d = yaml.safe_load(open(cfg, encoding="utf-8"))
            p0 = d["config"]["process"][0]
            if p0["model"]["qtype"] != "qfloat8" or p0["datasets"][0]["resolution"] != [1024, 1024]:
                raise AssertionError("Krea2(AT) 24G yaml 档位不符")
        finally:
            core.krea2_model_files = _old_files
            core.count_images = _old_count
    finally:
        import shutil as _sh
        _sh.rmtree(_td, ignore_errors=True)


def main():
    print("== Kohya-LoRA 工具 · 冒烟测试 ==")
    check("语法检查", test_syntax)
    check("导入 + 配置完整性（全部模式）", test_config_completeness)
    check("AI 图像模型配置", test_at_image_models)
    check("yaml 生成可解析", test_yaml)
    check("下载模型配置（FLUX/Anima/Krea2）", test_download_models)
    print("-" * 40)
    if FAILED:
        print("✘ 失败 %d 项: %s" % (len(FAILED), "、".join(FAILED)))
        return 1
    print("✔ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
