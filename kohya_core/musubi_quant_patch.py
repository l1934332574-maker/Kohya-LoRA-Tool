# -*- coding: utf-8 -*-
"""musubi-tuner INT8/NF4 量化底模补丁（幂等，供 Kohya一键工具.py 训练前调用）。

原理：给用户已安装的 musubi-tuner 源码打幂等补丁，增加：
  - INT8（W8A8 对称量化）：fp8_optimization_utils 扩展 quantize_int8 + 加载线程化 int8 参数
  - NF4（bitsandbytes 4-bit）：krea2 加载路径新增 load_krea2_dit_nf4（uint8 打包权重 + QuantState）
结构变化时跳过补丁（不破坏训练），各文件独立幂等。
"""
import io
import os

_MARK = "# === KOHYA_TOOL_PATCH_BEGIN"


def _read(fp):
    return io.open(fp, encoding="utf-8").read()


def _write(fp, src):
    io.open(fp, "w", encoding="utf-8", newline="\n").write(src)


def _apply(fp, repls, marker, logf, label, feature=None):
    """repls: [(old, new, expected_count)]，全部命中才写入。
    已打补丁（marker 或 feature 代码已存在）则静默跳过；结构不匹配才告警。"""
    if not os.path.isfile(fp):
        return False
    src = _read(fp)
    if marker in src or (feature and feature in src):
        return False
    for old, new, cnt in repls:
        n = src.count(old)
        if n != cnt:
            logf(f"[量化] musubi {label} 结构变化，跳过补丁（anchor 命中 {n}/{cnt}：{old[:50]!r}）")
            return False
        src = src.replace(old, new)
    _write(fp, src)
    return True


# ---------------------------------------------------------------- fp8_optimization_utils
_FP8_UTILS = ("modules", "fp8_optimization_utils.py")
_INT8_Q8_FN = '''
def quantize_int8(tensor, scale, max_value=127.0, min_value=-127.0):
    """Symmetric int8 quantization (W8A8). Scale = absmax / 127, rounded to nearest."""
    tensor = tensor.to(torch.float32)  # ensure tensor is in float32 for division
    tensor = torch.div(tensor, scale).nan_to_num_(0.0)
    tensor = tensor.clamp_(min=min_value, max=max_value)
    return tensor.to(torch.int8)


# === KOHYA_TOOL_PATCH_END: int8 ===
'''


def _patch_fp8_utils(base, logf):
    fp = os.path.join(base, *_FP8_UTILS)
    repls = [
        ("def optimize_state_dict_with_fp8(",
         "# === KOHYA_TOOL_PATCH_BEGIN: int8 ===\n" + _INT8_Q8_FN + "def optimize_state_dict_with_fp8(", 1),
        ("def optimize_state_dict_with_fp8(\n    state_dict: dict,\n    calc_device: Union[str, torch.device],\n    target_layer_keys: Optional[list[str]] = None,\n    exclude_layer_keys: Optional[list[str]] = None,\n    exp_bits: int = 4,\n    mantissa_bits: int = 3,\n    move_to_device: bool = False,\n    quantization_mode: str = \"block\",\n    block_size: Optional[int] = 64,\n):",
         "def optimize_state_dict_with_fp8(\n    state_dict: dict,\n    calc_device: Union[str, torch.device],\n    target_layer_keys: Optional[list[str]] = None,\n    exclude_layer_keys: Optional[list[str]] = None,\n    exp_bits: int = 4,\n    mantissa_bits: int = 3,\n    move_to_device: bool = False,\n    quantization_mode: str = \"block\",\n    block_size: Optional[int] = 64,\n    int8: bool = False,\n):", 1),
        ("    allow_prequantized_fp8: bool = False,\n) -> dict:",
         "    allow_prequantized_fp8: bool = False,\n    int8: bool = False,\n) -> dict:", 1),
        ("    if exp_bits == 4 and mantissa_bits == 3:\n        fp8_dtype = torch.float8_e4m3fn\n    elif exp_bits == 5 and mantissa_bits == 2:\n        fp8_dtype = torch.float8_e5m2\n    else:\n        raise ValueError(f\"Unsupported FP8 format: E{exp_bits}M{mantissa_bits}\")",
         "    if int8:\n        fp8_dtype = torch.int8\n    elif exp_bits == 4 and mantissa_bits == 3:\n        fp8_dtype = torch.float8_e4m3fn\n    elif exp_bits == 5 and mantissa_bits == 2:\n        fp8_dtype = torch.float8_e5m2\n    else:\n        raise ValueError(f\"Unsupported FP8 format: E{exp_bits}M{mantissa_bits}\")", 2),
        ("    # Calculate FP8 max value\n    max_value = calculate_fp8_maxval(exp_bits, mantissa_bits)\n    min_value = -max_value  # this function supports only signed FP8",
         "    if int8:\n        max_value = 127.0\n        min_value = -127.0\n    else:\n        # Calculate FP8 max value\n        max_value = calculate_fp8_maxval(exp_bits, mantissa_bits)\n        min_value = -max_value  # this function supports only signed FP8", 2),
        ("    # Quantize weight to FP8 (scale can be scalar or [out,1], broadcasting works)\n    quantized_weight = quantize_fp8(tensor, scale, fp8_dtype, max_value, min_value)",
         "    # Quantize weight to FP8/INT8 (scale can be scalar or [out,1], broadcasting works)\n    if fp8_dtype == torch.int8:\n        quantized_weight = quantize_int8(tensor, scale, max_value, min_value)\n    else:\n        quantized_weight = quantize_fp8(tensor, scale, fp8_dtype, max_value, min_value)", 1),
        ('module.register_buffer("scale_weight", torch.ones(scale_shape, dtype=module.weight.dtype))',
         'module.register_buffer("scale_weight", torch.ones(scale_shape, dtype=torch.float32))', 1),
    ]
    return _apply(fp, repls, "# === KOHYA_TOOL_PATCH_BEGIN: int8 ===", logf, "fp8_optimization_utils(int8)", feature="quantize_int8")


# ---------------------------------------------------------------- lora_utils
_LORA_UTILS = ("utils", "lora_utils.py")


def _patch_lora_utils(base, logf):
    fp = os.path.join(base, *_LORA_UTILS)
    repls = [
        ("    weight_transform_hooks: Optional[WeightTransformHooks] = None,\n    allow_prequantized_fp8: bool = False,\n) -> dict[str, torch.Tensor]:",
         "    weight_transform_hooks: Optional[WeightTransformHooks] = None,\n    allow_prequantized_fp8: bool = False,\n    int8_optimization: bool = False,\n) -> dict[str, torch.Tensor]:", 2),
        ("        weight_transform_hooks=weight_transform_hooks,\n        allow_prequantized_fp8=allow_prequantized_fp8,\n    )",
         "        weight_transform_hooks=weight_transform_hooks,\n        allow_prequantized_fp8=allow_prequantized_fp8,\n        int8_optimization=int8_optimization,\n    )", 1),
        ("    if fp8_optimization:\n        logger.info(\n            f\"Loading state dict with FP8 optimization. Dtype of weight: {dit_weight_dtype}, hook enabled: {weight_hook is not None}\"\n        )",
         "    if fp8_optimization or int8_optimization:\n        logger.info(\n            f\"Loading state dict with {'INT8' if int8_optimization else 'FP8'} optimization. Dtype of weight: {dit_weight_dtype}, hook enabled: {weight_hook is not None}\"\n        )", 1),
        ("            weight_transform_hooks=weight_transform_hooks,\n            allow_prequantized_fp8=allow_prequantized_fp8,\n        )",
         "            weight_transform_hooks=weight_transform_hooks,\n            allow_prequantized_fp8=allow_prequantized_fp8,\n            int8=int8_optimization,\n        )", 1),
    ]
    return _apply(fp, repls, "# === KOHYA_TOOL_PATCH_BEGIN: int8 ===", logf, "lora_utils(int8)", feature="int8_optimization")


# ---------------------------------------------------------------- krea2_utils
_K2_UTILS = ("krea2", "krea2_utils.py")
_NF4_BLOCK = '''

# === KOHYA_TOOL_PATCH_BEGIN: nf4 ===
import torch.nn.functional as _nf4_F


def _nf4_linear_forward(self, x):
    """NF4 dequant forward: packed uint8 weight + quant_state -> compute dtype -> F.linear."""
    import bitsandbytes as bnb
    data = self.weight.data.reshape(-1, 1)
    dq = bnb.functional.dequantize_nf4(data, self._quant_state)
    dq = dq.to(x.dtype)
    if self.bias is not None:
        return _nf4_F.linear(x, dq, self.bias)
    return _nf4_F.linear(x, dq)


def load_safetensors_with_nf4_optimization(
    model_files,
    calc_device,
    target_layer_keys=None,
    exclude_layer_keys=None,
    move_to_device=False,
    weight_hook=None,
    disable_numpy_memmap=False,
    weight_transform_hooks=None,
):
    """Load safetensors and NF4-quantize target Linear weights (bitsandbytes).

    Returns (state_dict, quant_state_map, target_paths):
    - state_dict: packed uint8 weight (shape [out, in//2]) under original key, bf16 for others
    - quant_state_map: module path -> QuantState (tensors on calc_device)
    - target_paths: set of module paths whose weight was NF4-quantized
    """
    from musubi_tuner.utils.safetensors_utils import MemoryEfficientSafeOpen, TensorWeightAdapter
    import bitsandbytes as bnb

    if isinstance(model_files, str):
        model_files = [model_files]

    def is_target(key):
        is_t = (target_layer_keys is None or any(p in key for p in target_layer_keys)) and key.endswith(".weight")
        is_e = exclude_layer_keys is not None and any(p in key for p in exclude_layer_keys)
        return is_t and not is_e

    state_dict = {}
    quant_state_map = {}
    target_paths = set()
    n_quant = 0
    for model_file in model_files:
        with MemoryEfficientSafeOpen(model_file, disable_numpy_memmap=disable_numpy_memmap) as original_f:
            f = TensorWeightAdapter(weight_transform_hooks, original_f) if weight_transform_hooks is not None else original_f
            for key in f.keys():
                value = f.get_tensor(key)
                orig_dev = value.device
                if weight_hook is not None:
                    value = weight_hook(key, value, keep_on_calc_device=(calc_device is not None))
                if not is_target(key):
                    target_dev = calc_device if (calc_device is not None and move_to_device) else orig_dev
                    state_dict[key] = value.to(target_dev)
                    continue
                t = value.to(device=calc_device, dtype=torch.bfloat16).contiguous()
                data, qs = bnb.functional.quantize_4bit(t, quant_type="nf4", compress_statistics=False)
                out_f, in_f = t.shape
                packed = data.view(out_f, in_f // 2).contiguous()
                if not move_to_device:
                    packed = packed.to(orig_dev)
                state_dict[key] = packed
                d = qs.as_dict()
                for _k in ("absmax", "quant_map"):
                    if _k in d and isinstance(d[_k], torch.Tensor):
                        d[_k] = d[_k].to(calc_device)
                qs_gpu = bnb.functional.QuantState.from_dict(d, device=torch.device(calc_device))
                mod_path = key.rsplit(".weight", 1)[0]
                quant_state_map[mod_path] = qs_gpu
                target_paths.add(mod_path)
                n_quant += 1
    logger.info(f"Number of NF4-optimized Linear layers: {n_quant}")
    return state_dict, quant_state_map, target_paths


def apply_nf4_monkey_patch(model, quant_state_map):
    patched = 0
    for name, mod in model.named_modules():
        if name in quant_state_map and mod.__class__.__name__.endswith("Linear"):
            mod._quant_state = quant_state_map[name]
            mod.forward = _nf4_linear_forward.__get__(mod, type(mod))
            patched += 1
    logger.info(f"Number of NF4 monkey-patched Linear layers: {patched}")
    return model


def load_krea2_dit_nf4(
    dit_path,
    device,
    dtype=torch.bfloat16,
    config=single_mmdit_large_wide,
    loading_device=None,
    attn_mode="torch",
    split_attn=False,
):
    """Build K2 DiT with NF4-quantized per-block Linears (bitsandbytes)."""
    device = torch.device(device)
    loading_device = device if loading_device is None else torch.device(loading_device)
    with torch.device("meta"):
        dit = SingleStreamDiT(config, attn_mode=attn_mode, split_attn=split_attn)
    logger.info(f"Loading Krea 2 DiT weights from {dit_path} (nf4 4-bit)")
    sd, qs_map, target_paths = load_safetensors_with_nf4_optimization(
        model_files=dit_path,
        calc_device=device,
        target_layer_keys=KREA2_FP8_OPTIMIZATION_TARGET_KEYS,
        exclude_layer_keys=KREA2_FP8_OPTIMIZATION_EXCLUDE_KEYS,
        move_to_device=(loading_device == device),
    )
    # int8/uint8 base weights cannot require grad; freeze before assign (LoRA-only anyway)
    for _p in dit.parameters():
        _p.requires_grad_(False)
    # non-target keys: shape-compatible load via load_state_dict
    non_target_sd = {k: v for k, v in sd.items() if not (k.endswith(".weight") and k.rsplit(".", 1)[0] in target_paths)}
    if non_target_sd:
        dit.load_state_dict(non_target_sd, strict=False, assign=True)
    # target keys: packed uint8 weights have a different shape ([out, in//2]) ->
    # must replace the Parameter object directly (load_state_dict enforces shape).
    for mod_path in target_paths:
        mod = dit.get_submodule(mod_path)
        packed = sd[mod_path + ".weight"].to(loading_device)
        mod.weight = torch.nn.Parameter(packed, requires_grad=False)
    apply_nf4_monkey_patch(dit, qs_map)
    return dit


# === KOHYA_TOOL_PATCH_END: nf4 ===
'''


def _patch_krea2_utils(base, logf):
    fp = os.path.join(base, *_K2_UTILS)
    repls = [
        ("def load_krea2_dit(",
         _NF4_BLOCK + "\n\ndef load_krea2_dit(", 1),
        ("    fp8_scaled: bool = False,\n    loading_device: Optional[Union[str, torch.device]] = None,",
         "    fp8_scaled: bool = False,\n    int8_base: bool = False,\n    nf4_base: bool = False,\n    loading_device: Optional[Union[str, torch.device]] = None,", 1),
        ("    device = torch.device(device)\n    loading_device = device if loading_device is None else torch.device(loading_device)\n    has_lora = lora_weights is not None and len(lora_weights) > 0",
         "    device = torch.device(device)\n    loading_device = device if loading_device is None else torch.device(loading_device)\n    if nf4_base:\n        return load_krea2_dit_nf4(\n            dit_path, device=device, dtype=dtype, config=config,\n            loading_device=loading_device, attn_mode=attn_mode, split_attn=split_attn,\n        )\n    has_lora = lora_weights is not None and len(lora_weights) > 0", 1),
        ("    if fp8_scaled or has_lora:",
         "    if int8_base or fp8_scaled or has_lora:", 1),
        ("            fp8_optimization=fp8_scaled,\n            calc_device=device,",
         "            fp8_optimization=fp8_scaled,\n            int8_optimization=int8_base,\n            calc_device=device,", 1),
        ("        if fp8_scaled:\n            apply_fp8_monkey_patch(dit, sd, use_scaled_mm=False)",
         "        if fp8_scaled or int8_base:\n            apply_fp8_monkey_patch(dit, sd, use_scaled_mm=False)", 1),
        ('        + (" (fp8 scaled)" if fp8_scaled else "")',
         '        + (" (int8 scaled)" if int8_base else "") + (" (fp8 scaled)" if fp8_scaled else "")', 1),
        ("    fp8_scaled: bool = False,\n    calc_device: Union[str, torch.device] = \"cpu\",",
         "    fp8_scaled: bool = False,\n    int8_base: bool = False,\n    calc_device: Union[str, torch.device] = \"cpu\",", 1),
        ("    if fp8_scaled:\n        sd = load_safetensors_with_lora_and_fp8(",
         "    if int8_base or fp8_scaled:\n        sd = load_safetensors_with_lora_and_fp8(", 1),
        ("            fp8_optimization=True,\n            calc_device=calc_dev,",
         "            fp8_optimization=fp8_scaled,\n            int8_optimization=int8_base,\n            calc_device=calc_dev,", 1),
        ("        if loading_device.type != \"cpu\":\n            for key in sd.keys():\n                sd[key] = sd[key].to(loading_device)\n        dit.load_state_dict(sd, strict=True, assign=True)",
         "        if int8_base:\n            # int8 weights cannot require grad (torch: only float/complex tensors can).\n            # Base is frozen for LoRA training anyway; fp8 path does not need this.\n            for _p in dit.parameters():\n                _p.requires_grad_(False)\n        if loading_device.type != \"cpu\":\n            for key in sd.keys():\n                sd[key] = sd[key].to(loading_device)\n        dit.load_state_dict(sd, strict=True, assign=True)", 1),
    ]
    ok = _apply(fp, repls, "# === KOHYA_TOOL_PATCH_BEGIN: nf4 ===", logf, "krea2_utils(int8+nf4)", feature="load_krea2_dit_nf4")
    return ok


# ---------------------------------------------------------------- krea2_train_network
_K2_TRAIN = ("krea2_train_network.py",)


def _patch_krea2_train(base, logf):
    fp = os.path.join(base, *_K2_TRAIN)
    repls = [
        ('    parser.add_argument(\n        "--fp8_scaled",',
         ('    parser.add_argument(\n'
          '        "--nf4_base",\n'
          '        action="store_true",\n'
          '        help="use NF4 4-bit (bitsandbytes) for the DiT base. Requires bitsandbytes installed; falls back to fp8 if unavailable.",\n'
          '    )\n'
          '    parser.add_argument(\n'
          '        "--int8_base",\n'
          '        action="store_true",\n'
          '        help="use int8 (W8A8) for the DiT base (requires --int8_scaled). Symmetric per-block quantization.",\n'
          '    )\n'
          '    parser.add_argument(\n'
          '        "--int8_scaled",\n'
          '        action="store_true",\n'
          '        help="use dynamic scaled int8 for the DiT (requires --int8_base).",\n'
          '    )\n'
          '    parser.add_argument(\n'
          '        "--fp8_scaled",'), 1),
        ("        model = krea2_utils.load_krea2_dit(\n            dit_path,\n            device=loading_device,\n            dtype=dtype,\n            fp8_scaled=args.fp8_scaled,\n            loading_device=loading_device,",
         "        model = krea2_utils.load_krea2_dit(\n            dit_path,\n            device=loading_device,\n            dtype=dtype,\n            fp8_scaled=args.fp8_scaled,\n            int8_base=args.int8_base,\n            nf4_base=args.nf4_base,\n            loading_device=loading_device,", 1),
        ('        if args.fp8_base and not args.fp8_scaled:\n            raise ValueError("Krea 2 fp8 supports only scaled fp8: pass --fp8_scaled together with --fp8_base.")',
         ('        if args.fp8_base and not args.fp8_scaled:\n'
          '            raise ValueError("Krea 2 fp8 supports only scaled fp8: pass --fp8_scaled together with --fp8_base.")\n'
          '        if args.int8_base and not args.int8_scaled:\n'
          '            raise ValueError("Krea 2 int8 supports only scaled int8: pass --int8_scaled together with --int8_base.")'), 1),
        ('                    args.turbo_dit, fp8_scaled=args.fp8_scaled, calc_device=accelerator.device, result_device="cpu"',
         '                    args.turbo_dit, fp8_scaled=args.fp8_scaled, int8_base=args.int8_base, calc_device=accelerator.device, result_device="cpu"', 1),
        ("                args.turbo_dit, fp8_scaled=args.fp8_scaled, calc_device=accelerator.device, result_device=accelerator.device",
         "                args.turbo_dit, fp8_scaled=args.fp8_scaled, int8_base=args.int8_base, calc_device=accelerator.device, result_device=accelerator.device", 1),
        ("                args.dit, fp8_scaled=args.fp8_scaled, calc_device=accelerator.device, result_device=accelerator.device",
         "                args.dit, fp8_scaled=args.fp8_scaled, int8_base=args.int8_base, calc_device=accelerator.device, result_device=accelerator.device", 1),
    ]
    return _apply(fp, repls, "# === KOHYA_TOOL_PATCH_BEGIN: int8 ===", logf, "krea2_train_network(int8+nf4)", feature="--nf4_base")


# ---------------------------------------------------------------- flux2
_FLUX2_UTILS = ("flux_2", "flux2_utils.py")
_FLUX2_TRAIN = ("flux_2_train_network.py",)


def _patch_flux2_utils(base, logf):
    fp = os.path.join(base, *_FLUX2_UTILS)
    repls = [
        ("    dit_weight_dtype: Optional[torch.dtype] = None,\n    fp8_scaled: bool = False,\n    lora_weights_list: Optional[dict[str, torch.Tensor]] = None,",
         "    dit_weight_dtype: Optional[torch.dtype] = None,\n    fp8_scaled: bool = False,\n    int8_base: bool = False,\n    lora_weights_list: Optional[dict[str, torch.Tensor]] = None,", 1),
        ("    assert (not fp8_scaled and dit_weight_dtype is not None) or (fp8_scaled and dit_weight_dtype is None)",
         "    assert (not (fp8_scaled or int8_base) and dit_weight_dtype is not None) or ((fp8_scaled or int8_base) and dit_weight_dtype is None)", 1),
        ("        fp8_optimization=fp8_scaled,\n        calc_device=device,",
         "        fp8_optimization=fp8_scaled,\n        int8_optimization=int8_base,\n        calc_device=device,", 1),
        ("    if fp8_scaled:\n        apply_fp8_monkey_patch(model, sd, use_scaled_mm=False)",
         "    if fp8_scaled or int8_base:\n        apply_fp8_monkey_patch(model, sd, use_scaled_mm=False)", 1),
        ("    info = model.load_state_dict(sd, strict=True, assign=True)",
         ("    if int8_base:\n"
          "        # int8 weights cannot require grad; base is frozen for LoRA anyway\n"
          "        for _p in model.parameters():\n"
          "            _p.requires_grad_(False)\n"
          "    info = model.load_state_dict(sd, strict=True, assign=True)"), 1),
    ]
    return _apply(fp, repls, "# === KOHYA_TOOL_PATCH_BEGIN: int8 ===", logf, "flux2_utils(int8)", feature="int8_base")


def _patch_flux2_train(base, logf):
    fp = os.path.join(base, *_FLUX2_TRAIN)
    repls = [
        ('    parser.add_argument("--fp8_scaled", action="store_true", help="use scaled fp8 for DiT / DiTにスケーリングされたfp8を使う")',
         ('    parser.add_argument("--int8_base", action="store_true",\n'
          '                        help="use int8 (W8A8) for the DiT base (requires --int8_scaled). Symmetric per-block quantization.")\n'
          '    parser.add_argument("--int8_scaled", action="store_true",\n'
          '                        help="use dynamic scaled int8 for the DiT (requires --int8_base).")\n'
          '    parser.add_argument("--fp8_scaled", action="store_true", help="use scaled fp8 for DiT / DiTにスケーリングされたfp8を使う")'), 1),
        ("            fp8_scaled=args.fp8_scaled,\n            disable_numpy_memmap=args.disable_numpy_memmap,",
         "            fp8_scaled=args.fp8_scaled,\n            int8_base=args.int8_base,\n            disable_numpy_memmap=args.disable_numpy_memmap,", 1),
    ]
    return _apply(fp, repls, "# === KOHYA_TOOL_PATCH_BEGIN: int8 ===", logf, "flux_2_train_network(int8)", feature="--int8_base")


def patch_musubi_quant_base(kdir, logf=print):
    """给 musubi-tuner 打 INT8 + NF4 量化底模补丁（幂等）。返回是否全部应用成功。"""
    base = os.path.join(kdir, "musubi-tuner", "src", "musubi_tuner")
    if not os.path.isdir(base):
        logf("[量化] 未找到 musubi-tuner 源码目录，跳过量化补丁")
        return False
    results = [
        _patch_fp8_utils(base, logf),
        _patch_lora_utils(base, logf),
        _patch_krea2_utils(base, logf),
        _patch_krea2_train(base, logf),
        _patch_flux2_utils(base, logf),
        _patch_flux2_train(base, logf),
    ]
    n_new = sum(1 for r in results if r)
    logf(f"[量化] musubi INT8/NF4 补丁检查完成（新应用 {n_new}/6，其余已存在或跳过）")
    return True
