"""Deploy a depth-aware Anima loader into existing sd-scripts environments."""
import ast
import os
from pathlib import Path
import re
import tempfile

_MARKER = "KOHYA_TOOL_ANIMA_DYNAMIC_DEPTH_V2"
_LEGACY_MARKER = "KOHYA_TOOL_ANIMA_DYNAMIC_DEPTH_V1"
_HELPER = r'''

# KOHYA_TOOL_ANIMA_DYNAMIC_DEPTH_V2
def _kohya_anima_checkpoint_depth(dit_path):
    # Inspect tensor names/shapes without loading model weights or allocating GPU memory.
    import re
    from safetensors import safe_open

    with safe_open(dit_path, framework="pt", device="cpu") as checkpoint:
        # Match load_anima_model.rename_hook exactly: community/aesthetics models
        # can use model.diffusion_model.* while original models use net.*.
        names = {}
        for key in checkpoint.keys():
            name = key
            for prefix in ("net.", "model.diffusion_model."):
                if key.startswith(prefix):
                    name = key[len(prefix):]
                    break
            names[name] = key
        indices = sorted({int(match.group(1)) for name in names
                          if (match := re.match(r"^blocks\.(\d+)\.", name))})
        if not indices:
            raise ValueError("Anima 层数探测未找到 DiT blocks.* 权重；支持无前缀、net.* 和 model.diffusion_model.* 命名，请核对模型结构。")
        depth = indices[-1] + 1
        if depth > 256:
            raise ValueError("Anima checkpoint has an unsupported DiT block count")
        missing = sorted(set(range(depth)) - set(indices))
        if missing:
            raise ValueError("Anima checkpoint has missing DiT block indices: %s" % missing[:10])
        embedding = names.get("x_embedder.proj.1.weight")
        if embedding is None:
            raise ValueError("Anima checkpoint is missing x_embedder.proj.1.weight")
        shape = checkpoint.get_slice(embedding).get_shape()
        if len(shape) != 2 or shape[0] != 2048:
            raise ValueError("This Anima loader supports model_channels=2048; checkpoint shape is %s" % (shape,))
    logger.info("Anima checkpoint: detected %d DiT blocks (model_channels=2048)", depth)
    return depth
'''


def patch_anima_loader(kdir, logf=print):
    """Patch only the known fixed-depth configuration; preserve custom/upstream implementations."""
    path = Path(kdir) / "sd-scripts" / "library" / "anima_utils.py"
    if not path.is_file():
        raise RuntimeError("Anima 加载器缺失，请先安装第一引擎。")
    original = path.read_bytes()
    source = original.decode("utf-8-sig")
    if _MARKER in source:
        return False
    upgrading = _LEGACY_MARKER in source
    if upgrading:
        # Replace only our injected helper. Keep the loader's rename hooks,
        # VAE fixes and any unrelated environment changes intact.
        tree = ast.parse(source, filename=str(path))
        helpers = [node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == "_kohya_anima_checkpoint_depth"]
        if len(helpers) != 1 or helpers[0].decorator_list or helpers[0].end_lineno is None:
            raise RuntimeError("旧版 Anima 层数探测补丁结构异常，请修复第一引擎后重试。")
        helper = helpers[0]
        lines = source.splitlines(keepends=True)
        source = "".join(lines[:helper.lineno - 1]) + _HELPER.lstrip("\n") + "".join(lines[helper.end_lineno:])
        source = source.replace("# " + _LEGACY_MARKER + "\r\n", "").replace("# " + _LEGACY_MARKER + "\n", "")
    else:
        pattern = r'(["\']num_blocks["\']\s*:\s*)28(?=\s*[,}])'
        matches = list(re.finditer(pattern, source))
        if len(matches) != 1:
            logf("[Anima] 当前加载器不是已知的固定28层实现，保留其现有结构识别逻辑。")
            return False
        source = re.sub(pattern, lambda match: match.group(1) + "_kohya_anima_checkpoint_depth(dit_path)", source, count=1)
        source += _HELPER
    ast.parse(source, filename=str(path))
    backup = path.with_name(path.name + (".kohya_depth_v2.bak" if upgrading else ".kohya_depth_v1.bak"))
    if not backup.exists():
        with backup.open("xb") as handle:
            handle.write(original)
    newline = "\r\n" if b"\r\n" in original else "\n"
    source = source.replace("\r\n", "\n").replace("\n", newline)
    payload = source.encode("utf-8-sig" if original.startswith(b"\xef\xbb\xbf") else "utf-8")
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    logf("[Anima] %s底模层数自动识别：兼容无前缀、net.*、model.diffusion_model.* 命名及28/40层同宽度结构；已保留加载器备份。"
         % ("已升级" if upgrading else "已启用"))
    return True
