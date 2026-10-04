"""Deploy a depth-aware Anima loader into existing sd-scripts environments."""
import ast
import os
from pathlib import Path
import re
import tempfile

_MARKER = "KOHYA_TOOL_ANIMA_DYNAMIC_DEPTH_V1"
_HELPER = r'''

# KOHYA_TOOL_ANIMA_DYNAMIC_DEPTH_V1
def _kohya_anima_checkpoint_depth(dit_path):
    # Inspect tensor names/shapes without loading model weights or allocating GPU memory.
    import re
    from safetensors import safe_open

    with safe_open(dit_path, framework="pt", device="cpu") as checkpoint:
        names = {key[4:] if key.startswith("net.") else key: key for key in checkpoint.keys()}
        indices = sorted({int(match.group(1)) for name in names
                          if (match := re.match(r"^blocks\.(\d+)\.", name))})
        if not indices or indices != list(range(indices[-1] + 1)):
            raise ValueError("Anima checkpoint has missing or non-contiguous DiT block indices")
        depth = len(indices)
        if depth > 256:
            raise ValueError("Anima checkpoint has an unsupported DiT block count")
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
    pattern = r'(["\']num_blocks["\']\s*:\s*)28(?=\s*[,}])'
    matches = list(re.finditer(pattern, source))
    if len(matches) != 1:
        logf("[Anima] 当前加载器不是已知的固定28层实现，保留其现有结构识别逻辑。")
        return False
    source = re.sub(pattern, lambda match: match.group(1) + "_kohya_anima_checkpoint_depth(dit_path)", source, count=1)
    source += _HELPER
    ast.parse(source, filename=str(path))
    backup = path.with_name(path.name + ".kohya_depth_v1.bak")
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
    logf("[Anima] 已启用底模层数自动识别：保留原加载器备份，兼容28层及40层同宽度结构。")
    return True
