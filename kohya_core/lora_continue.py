"""Independent LoRA warm starts; optimizer-state resume remains a separate operation."""
import copy
import hashlib
import json
import math
import re
import shutil
import struct
import time
import uuid
from .project_config import WORKSPACE_PARAM_KEYS
from pathlib import Path

SUPPORTED = {"character", "style", "concept", "krea2", "flux2", "krea2_at", "qwen_image", "zimage"}


def check_mode(config):
    mode = config.get("mode", "")
    if config.get("training_kind") == "slider" or mode == "video":
        raise ValueError("此入口暂不支持滑块和视频任务，请使用原训练流程。")
    if mode.endswith("_fz"):
        version = str((config.get("params") or {}).get("fizgig_version", ""))
        if version not in ("v8.5.0", "v8.9.6"):
            raise ValueError("Fizgig 追加训练需要项目选择 v8.5.0 或 v8.9.6；不会自动更换原项目引擎。")
    elif mode not in SUPPORTED:
        raise ValueError("当前模式尚未接入可训练 LoRA 初始权重。")


def inspect(path):
    """Read bounded safetensors metadata and scalar alphas without importing torch."""
    path = Path(path)
    if path.suffix.lower() != ".safetensors" or not path.is_file():
        raise ValueError("请选择已有 LoRA 的 .safetensors 文件。")
    size = path.stat().st_size
    with path.open("rb") as f:
        raw = f.read(8)
        if len(raw) != 8:
            raise ValueError("LoRA 文件不完整。")
        length = struct.unpack("<Q", raw)[0]
        if not 2 <= length <= min(32 * 1024 * 1024, size - 8):
            raise ValueError("不是有效的 safetensors 文件。")
        header = json.loads(f.read(length))
        if not isinstance(header, dict):
            raise ValueError("LoRA 文件头无效。")
        tensors = {k: v for k, v in header.items() if k != "__metadata__"}
        downs = {k: v for k, v in tensors.items() if k.endswith((".lora_down.weight", ".lora_A.weight"))}
        if not downs or any("lokr_" in k or "hada_" in k or "dora_scale" in k for k in tensors):
            raise ValueError("目前只支持带 alpha 的普通 LoRA；不支持 LoKr、DoRA 或全量模型。")
        dtype_bytes = {"F64": 8, "F32": 4, "F16": 2, "BF16": 2}
        intervals = []
        for key, v in tensors.items():
            if not isinstance(key, str) or not isinstance(v, dict):
                raise ValueError("LoRA 张量头无效。")
            if not key.endswith((".lora_down.weight", ".lora_up.weight", ".lora_A.weight", ".lora_B.weight", ".alpha")):
                raise ValueError("此文件包含普通 LoRA 之外的权重，暂不支持追加训练。")
            shape, offsets = v.get("shape"), v.get("data_offsets")
            width = dtype_bytes.get(v.get("dtype"))
            if not width or not isinstance(shape, list) or not all(isinstance(x, int) and x >= 0 for x in shape):
                raise ValueError("LoRA 张量类型或形状不受支持。")
            if not isinstance(offsets, list) or len(offsets) != 2 or not all(isinstance(x, int) for x in offsets):
                raise ValueError("LoRA 张量偏移无效。")
            a, b = offsets
            if a < 0 or b < a or b - a != math.prod(shape) * width or b > size - 8 - length:
                raise ValueError("LoRA 张量数据不完整。")
            intervals.append((a, b))
        intervals.sort()
        if any(left[1] > right[0] for left, right in zip(intervals, intervals[1:])):
            raise ValueError("LoRA 张量数据重叠。")
        ranks, alphas = set(), set()
        for key, down in downs.items():
            suffix = ".lora_A.weight" if key.endswith(".lora_A.weight") else ".lora_down.weight"
            stem = key[:-len(suffix)]
            up = tensors.get(stem + (".lora_B.weight" if suffix == ".lora_A.weight" else ".lora_up.weight"))
            rank = down["shape"][0] if len(down["shape"]) >= 2 else 0
            if not rank or not up or len(up["shape"]) < 2 or up["shape"][1] != rank:
                raise ValueError("LoRA 上下投影不成对或 rank 不一致。")
            ranks.add(rank)
            alpha = tensors.get(stem + ".alpha")
            if not alpha:
                raise ValueError("LoRA 缺少 alpha，无法保证继承权重的实际强度。")
            a, b = alpha["data_offsets"]
            if math.prod(alpha["shape"]) != 1:
                raise ValueError("LoRA alpha 应为标量。")
            f.seek(8 + length + a)
            raw = f.read(b - a)
            kind = alpha["dtype"]
            value = struct.unpack({"F32": "<f", "F64": "<d", "F16": "<e", "BF16": "<f"}[kind], raw if kind != "BF16" else b"\x00\x00" + raw)[0]
            if not math.isfinite(value) or value <= 0:
                raise ValueError("LoRA alpha 无效。")
            alphas.add(value)
        if len(ranks) != 1 or len(alphas) != 1:
            raise ValueError("当前训练器要求各层 rank / alpha 一致；此文件包含不同层配置。")
        if next(iter(alphas)) != int(next(iter(alphas))):
            raise ValueError("当前训练配置只支持整数 alpha。")
        metadata = header.get("__metadata__", {})
        return {"path": str(path.resolve()), "rank": ranks.pop(), "alpha": alphas.pop(),
                "modules": len(downs), "bytes": size, "metadata": metadata,
                "keys": list(tensors)}


def validate(config, params):
    if not params.get("initial_lora"):
        return
    check_mode(config)
    info = inspect(params["initial_lora"])
    if int(params["rank"]) != info["rank"] or float(params["alpha"]) != info["alpha"]:
        raise ValueError("追加训练的 rank / alpha 必须与来源 LoRA 相同。请重新创建追加训练项目。")
    expected = params.get("training_origin", {}).get("sha256")
    if expected and file_hash(info["path"]) != expected:
        raise ValueError("追加训练的来源权重已被修改，请重新选择 LoRA。")


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checkpoints(directory, sample=""):
    """Bound discovery to this output and its snapshot trees; never choose latest by time."""
    root = Path(directory).resolve()
    if not root.is_dir():
        return [], ""
    candidates = []
    paths = list(root.glob("*.safetensors"))
    snapshots = root / "snapshots"
    if snapshots.is_dir() and not snapshots.is_symlink():
        paths += list(snapshots.glob("*/*.safetensors")) + list(snapshots.glob("*/*/*.safetensors"))
    for path in sorted(paths):
        if path.is_symlink() or root not in path.resolve().parents:
            continue
        if len(candidates) >= 300:
            break
        candidates.append({"path": str(path.resolve()), "name": path.relative_to(root).as_posix()})
    # Fizgig sample = prefix-e000006_00_timestamp_seed.png; checkpoint = prefix-000006.
    match = re.match(r"(.+)-e(\d+)_", Path(sample).name) if sample else None
    selected = ""
    if match:
        prefix, epoch = match.groups()
        wanted = prefix + "-" + epoch
        hits = [row for row in candidates if Path(row["path"]).stem == wanted]
        if len(hits) == 1:
            selected = hits[0]["path"]
        else:
            hits = [row for row in candidates if Path(row["path"]).parent.name == wanted + "-state" and Path(row["path"]).name == "lora.safetensors"]
            if len(hits) == 1:
                selected = hits[0]["path"]
    return candidates, selected


def create(core, source_config, source_project, options, run=None):
    check_mode(source_config)
    info = inspect(options.get("source_path", ""))
    config = copy.deepcopy(source_config)
    params = dict(config.get("params") or {})
    original = (run or {}).get("normalized_params") or {}
    for key in params.keys() | original.keys():
        if key in original and key in WORKSPACE_PARAM_KEYS:
            params[key] = original[key]
    old_resolution = int(original.get("resolution") or params.get("resolution") or 512)
    resolution = int(options.get("resolution") or old_resolution)
    epochs = int(options.get("epochs") or 2)
    steps = int(options.get("steps") or 200)
    kind = str(options.get("kind") or "append")
    if kind not in ("append", "refine") or not 256 <= resolution <= 2048 or resolution % 64 or not 1 <= epochs <= 100 or not 100 <= steps <= 6000:
        raise ValueError("分辨率应为 256–2048 的 64 倍数，追加轮数 1–100，步数 100–6000。")
    if kind == "refine" and resolution <= old_resolution:
        raise ValueError("高清精修的目标分辨率必须高于原训练分辨率。")
    lr = str(options.get("learning_rate") or original.get("unet_lr") or params.get("unet_lr") or "1e-4")
    if not math.isfinite(float(lr)) or not 0 < float(lr) <= .1:
        raise ValueError("请填写有效的学习率。")
    name = source_project[:40] + ("_精修" if kind == "refine" else "_追加") + str(resolution) + "_" + time.strftime("%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    # Never inherit the parent's custom output directory or mutable source path.
    output = Path(core.data_sub("output")) / name
    initial = output / "inputs" / "source.safetensors"
    initial.parent.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copyfile(info["path"], initial)
        checksum = file_hash(initial)
        if checksum != file_hash(info["path"]):
            raise ValueError("复制过程中来源 LoRA 发生变化，请重试。")
        params.update(rank=info["rank"], alpha=info["alpha"], resolution=resolution, max_epochs=epochs,
                      video_steps=steps, unet_lr=lr, overwrite=True, keep_user_captions=True, mask_overwrite_auto=False)
        config.update(name=name, params=params, output_dir=str(output), initial_lora=str(initial),
                      training_origin={"kind": kind, "project": source_project, "run_id": (run or {}).get("id", ""),
                                       "source_path": info["path"], "source_sample": options.get("sample", ""),
                                       "sha256": checksum, "resolution": old_resolution,
                                       "target_resolution": resolution, "crop_ratio": params.get("crop_ratio", ""), "created": time.time()})
        for key in ("created", "updated", "resume_path"):
            config.pop(key, None)
        if config.get("training_kind") == "multi_character":
            snapshot_multi_inputs(core, config, source_project, output)
        else:
            snapshot_inputs(core, config, source_project, output)
        if not core.save_project(name, config):
            raise OSError("保存追加训练项目失败；原项目未修改。")
    except Exception:
        # Only this unique child directory was created by this call.
        expected_parent = Path(core.data_sub("output")).resolve()
        resolved = output.resolve()
        if resolved.parent == expected_parent and resolved.name == name and not output.is_symlink():
            shutil.rmtree(resolved)
        raise
    return name, config


FIZGIG_LAUNCHER = r'''import json, runpy, sys
from pathlib import Path
source, initial, script = sys.argv[1:4]
sys.argv = [script] + sys.argv[4:]
sys.path.insert(0, str(Path(source) / "src"))
from safetensors import safe_open
from fizgig.families.lora import FamilyLoRA, TRAINABLE
original = FamilyLoRA.add_trainable
loaded = False
def add_trainable(self, *args, **kwargs):
    global loaded
    result = original(self, *args, **kwargs)
    if loaded:
        raise RuntimeError("Initial LoRA was requested more than once")
    # Compare against the live network before copying; no second full state_dict on CPU.
    expected = {}
    count = 0
    for full, wrapper in self.wrapped.items():
        if TRAINABLE not in wrapper.adapters:
            continue
        down, up = wrapper.adapters[TRAINABLE]
        ka, kb, kalpha = self._keys(full)
        expected[ka] = tuple(down.weight.shape)
        expected[kb] = tuple(up.weight.shape)
        expected[kalpha] = ()
        count += 1
    with safe_open(initial, framework="pt", device="cpu") as f:
        if set(f.keys()) != set(expected):
            raise RuntimeError("Initial LoRA layers differ from the selected model/network; refusing partial loading")
        for key, shape in expected.items():
            actual = tuple(f.get_slice(key).get_shape())
            if key.endswith(".alpha"):
                if float(f.get_tensor(key).item()) != float(self.alpha):
                    raise RuntimeError("Initial LoRA alpha differs from the trainable network")
            elif actual != shape:
                raise RuntimeError("Initial LoRA shape mismatch: " + key)
    matched = self.load_trainable(initial)
    if not count or matched != count:
        raise RuntimeError("Initial LoRA was not completely loaded")
    loaded = True
    print("[追加训练] 已加载可训练初始 LoRA：%d 个模块；使用新的优化器与训练计数。" % matched, flush=True)
    return result
FamilyLoRA.add_trainable = add_trainable
import torch
optimizer_init = torch.optim.Optimizer.__init__
def require_initial_optimizer(self, *args, **kwargs):
    if not loaded:
        raise RuntimeError("Initial LoRA was not completely loaded before optimizer creation")
    return optimizer_init(self, *args, **kwargs)
torch.optim.Optimizer.__init__ = require_initial_optimizer
runpy.run_path(script, run_name="__main__")
if not loaded:
    raise RuntimeError("Initial LoRA hook did not execute")
'''


def fizgig_command(cmd, source, output, params, resume_from):
    if not params.get("initial_lora") or resume_from:
        return cmd
    launcher = Path(output) / "initial_lora_launcher.py"
    launcher.write_text(guarded(FIZGIG_LAUNCHER), encoding="utf-8")
    return [cmd[0], str(launcher), str(source), params["initial_lora"], cmd[1]] + cmd[2:]


def guarded(body):
    # Both Windows spawn and POSIX workers can import the launcher as __mp_main__.
    body = body.replace("global loaded", "nonlocal loaded")
    return "def main():\n" + "\n".join("    " + line for line in body.splitlines()) + "\n\nif __name__ == '__main__':\n    main()\n"


def snapshot_inputs(core, config, project, output):
    """Keep full-resolution originals and reuse the captions actually trained last time."""
    from .project_config import dataset_images
    if not str(config.get("raw_dir") or "").strip():
        raise ValueError("请先为来源项目选择原始图片目录。")
    root = Path(config["raw_dir"])
    images = dataset_images(root)
    if not images:
        raise ValueError("来源原图目录为空；高清精修需要原始图片。")
    names = [p.relative_to(root).as_posix() for p in images]
    # Same stable naming convention as preprocess._output_image_stems.
    stems = {name: str(Path(name.replace("/", "__")).with_suffix("")) for name in names}
    counts = {}
    for stem in stems.values():
        counts[stem.casefold()] = counts.get(stem.casefold(), 0) + 1
    occupied = {stem.casefold() for stem in stems.values()}
    for name, stem in list(stems.items()):
        if counts[stem.casefold()] > 1:
            candidate = stem + "_" + hashlib.sha256(name.encode("utf-8")).hexdigest()
            while candidate.casefold() in occupied:
                candidate += "_"
            stems[name] = candidate
            occupied.add(candidate.casefold())
    target = output / "inputs" / "images"
    target.mkdir()
    old_train = Path(core.dataset_train_dir(config["mode"], project))
    for image, name in zip(images, names):
        destination = target / (stems[name] + image.suffix.lower())
        caption = old_train / (stems[name] + ".txt")
        if not caption.is_file():
            caption = image.with_suffix(".txt")
        if caption.is_symlink() or not caption.is_file() or not caption.read_bytes().strip():
            raise ValueError("来源图片缺少训练标签：" + name + "；请先补齐原图同名文本。")
        shutil.copyfile(image, destination)
        shutil.copyfile(caption, destination.with_suffix(".txt"))
        from . import loss_masks
        previous_image = old_train / (stems[name] + ".png")
        if previous_image.is_file():
            mask = loss_masks.mask_for(previous_image)
            record = loss_masks.manifest(old_train)["images"].get(previous_image.name, {})
            if record or mask:
                saved = output / "inputs" / "reviewed_masks"
                saved.mkdir(exist_ok=True)
                if mask:
                    shutil.copyfile(mask, saved / (stems[name] + loss_masks.SUFFIX + mask.suffix))
                index = saved / "records.json"
                records = json.loads(index.read_text(encoding="utf-8")) if index.exists() else {}
                records[stems[name] + ".png"] = record
                index.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    config["raw_dir"] = str(target)
    config["training_origin"]["original_raw_dir"] = str(root)
    config["training_origin"]["caption_source"] = str(old_train)


NATIVE_LAUNCHER = r'''import importlib, runpy, sys
from pathlib import Path
source, initial, module, script = sys.argv[1:5]
sys.argv = [script] + sys.argv[5:]
sys.path[:0] = [str(Path(script).parent), source, str(Path(source) / "src")]
if module.startswith("networks.") and (Path(source) / "src/musubi_tuner").is_dir():
    module = "musubi_tuner." + module
owner = importlib.import_module(module)
if module == "toolkit.network_mixins":
    cls = owner.ToolkitNetworkMixin
else:
    cls = getattr(owner, "LoRANetwork", None)
    if cls is None:
        cls = owner.lora.LoRANetwork
original = cls.load_weights
loaded = False
def load_weights(self, file, *args, **kwargs):
    nonlocal loaded
    if not isinstance(file, str) or Path(file).resolve() != Path(initial).resolve():
        return original(self, file, *args, **kwargs)
    original_load = self.load_state_dict
    had_override = "load_state_dict" in self.__dict__
    previous = self.__dict__.get("load_state_dict")
    checked = False
    def strict_load(state, *a, **k):
        nonlocal checked
        info = original_load(state, *a, **k)
        relevant = lambda key: ".lora_down." in key or ".lora_up." in key or ".lora_A." in key or ".lora_B." in key or key.endswith(".alpha")
        missing = [key for key in info.missing_keys if relevant(key)]
        unexpected = [key for key in info.unexpected_keys if relevant(key)]
        if missing or unexpected or not any(relevant(key) for key in state):
            raise RuntimeError("Initial LoRA layers differ from the selected model/network; refusing partial loading: " + str((missing[:3], unexpected[:3])))
        checked = True
        return info
    self.load_state_dict = strict_load
    try:
        result = original(self, file, *args, **kwargs)
        if not checked:
            raise RuntimeError("Initial LoRA loading could not be verified")
        loaded = True
        print("[追加训练] 已完整加载可训练初始 LoRA；使用新的训练计数。", flush=True)
        return result
    finally:
        if had_override:
            self.load_state_dict = previous
        else:
            del self.load_state_dict
cls.load_weights = load_weights
import torch
optimizer_init = torch.optim.Optimizer.__init__
def require_initial_optimizer(self, *args, **kwargs):
    if not loaded:
        raise RuntimeError("Initial LoRA was not completely loaded before optimizer creation")
    return optimizer_init(self, *args, **kwargs)
torch.optim.Optimizer.__init__ = require_initial_optimizer
runpy.run_path(script, run_name="__main__")
if not loaded:
    raise RuntimeError("Initial LoRA was not loaded; refusing to report successful additional training")
'''


def native_command(cmd, source, output, params, resume_from=None, module=""):
    if not params.get("initial_lora") or resume_from:
        return cmd
    # Commands in these adapters invoke Python scripts directly.
    if not module:
        for i, arg in enumerate(cmd):
            if arg == "--network_module":
                module = cmd[i + 1]
            elif arg.startswith("--network_module="):
                module = arg.split("=", 1)[1]
    if not module:
        raise ValueError("当前引擎未声明可验证的 LoRA 加载模块。")
    script_index = next(i for i, arg in enumerate(cmd[1:], 1) if arg.endswith(".py"))
    launcher = Path(output) / "initial_lora_launcher.py"
    launcher.write_text(guarded(NATIVE_LAUNCHER), encoding="utf-8")
    return cmd[:script_index] + [str(launcher), str(source), str(params["initial_lora"]), module, cmd[script_index]] + cmd[script_index + 1:]


def inherit_masks(core, params, logf):
    """Resize reviewed single-image masks to the rebuilt training geometry."""
    if not params.get("initial_lora"):
        return
    from . import loss_masks
    origin = params.get("training_origin", {})
    saved = Path(params["initial_lora"]).parent / "reviewed_masks"
    if not saved.is_dir():
        return
    if str(params.get("crop_ratio") or "") != str(origin.get("crop_ratio") or ""):
        raise ValueError("追加训练已改变裁切比例；请重新创建项目并检查学习区域，避免旧遮罩错位。")
    from PIL import Image
    target = Path(core.dataset_train_dir(params["mode"], params["project"]))
    records = json.loads((saved / "records.json").read_text(encoding="utf-8"))
    count = 0
    current_records = loss_masks.manifest(target)["images"]
    for name, record in records.items():
        image = target / name
        if not image.is_file():
            continue
        # Keep edits made in the child project on subsequent preprocessing runs.
        if name in current_records or loss_masks.mask_for(image):
            continue
        previous = loss_masks.mask_for(saved / name)
        if previous:
            with Image.open(image) as pixels:
                size = pixels.size
            with loss_masks.read_mask(previous) as mask:
                resized = mask.resize(size, Image.Resampling.BILINEAR)
            loss_masks.atomic_mask(image.with_name(image.stem + loss_masks.SUFFIX + ".png"), resized)
            resized.close()
            count += 1
        loss_masks.remember(target, image, origin="import", kind=record.get("kind", "existing"), decision=record.get("decision"))
    logf("[追加训练] 已继承并缩放 %d 张已有学习区域；请在标签确认阶段检查边缘。" % count)


def multi_identity(row, resolution):
    path = row["path"]
    stat = path.stat()
    return hashlib.sha256(json.dumps([row["group_id"], str(path.resolve()), stat.st_size, stat.st_mtime_ns,
                                     row["caption"], resolution], ensure_ascii=False).encode()).hexdigest()[:24]


def snapshot_multi_inputs(core, config, project, output):
    from .multi_character import scan
    from . import loss_masks
    origin = config["training_origin"]
    mode = config["mode"]
    old = scan(config.get("multi_character", {}), mode=mode, resolution=origin["resolution"])
    settings = old["settings"]
    folders = {row["id"]: output / "inputs" / ("group_" + str(index))
               for index, row in enumerate(settings["roles"] + settings["groups"])}
    for folder in folders.values():
        folder.mkdir()
    old_train = Path(core.dataset_train_dir(mode, project))
    old_records = loss_masks.manifest(old_train)["images"]
    references = {}
    for index, row in enumerate(old["entries"]):
        path = row["path"]
        old_name = "multi_" + multi_identity(row, origin["resolution"]) + "_0.png"
        caption_path = old_train / Path(old_name).with_suffix(".txt")
        caption = caption_path.read_text(encoding="utf-8-sig").strip() if caption_path.is_file() else row["caption"]
        destination = folders[row["group_id"]] / (str(index) + path.suffix.lower())
        shutil.copy2(path, destination)
        destination.with_suffix(".txt").write_text(caption, encoding="utf-8")
        references[str(destination.resolve())] = old_name
    origin["original_multi_character"] = copy.deepcopy(settings)
    for row in settings["roles"] + settings["groups"]:
        row["directory"] = str(folders[row["id"]])
    config["multi_character"] = settings
    config["raw_dir"] = str(next(iter(folders.values())))
    new = scan(settings, mode=mode, resolution=origin["target_resolution"])
    factors = {row["id"]: row["sampling_copies"] for row in new["roles"]}
    saved = output / "inputs" / "reviewed_masks"
    records = {}
    for row in new["entries"]:
        previous_name = references[str(row["path"].resolve())]
        previous = old_train / previous_name
        if not previous.is_file():
            continue
        record = old_records.get(previous_name, {})
        mask = loss_masks.mask_for(previous)
        if not record and not mask:
            continue
        saved.mkdir(exist_ok=True)
        identity = multi_identity(row, origin["target_resolution"])
        for index in range(factors[row["group_id"]]):
            name = "multi_" + identity + "_" + str(index) + ".png"
            records[name] = record
            if mask:
                shutil.copyfile(mask, saved / (Path(name).stem + loss_masks.SUFFIX + mask.suffix))
    if records:
        (saved / "records.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
