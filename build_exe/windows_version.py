"""Generate Windows PE metadata required for code signing restrictions."""
from pathlib import Path
import re

PRODUCT_NAME = "Kohya-LoRA Tool"


def write_version_resource(root, output):
    source = (Path(root) / "Kohya一键工具.py").read_text(encoding="utf-8-sig")
    match = re.search(r'APP_VERSION\s*=\s*"(\d+\.\d+\.\d+)"', source)
    if not match:
        raise ValueError("Cannot determine the application version")
    version = match.group(1)
    numbers = tuple(int(part) for part in version.split(".")) + (0,)
    fields = {"CompanyName": "Kohya-LoRA Tool contributors",
              "FileDescription": PRODUCT_NAME, "FileVersion": version,
              "InternalName": "KohyaLoraTool", "OriginalFilename": "Kohya一键工具.exe",
              "ProductName": PRODUCT_NAME, "ProductVersion": version}
    strings = ",\n".join("StringStruct(%r, %r)" % item for item in fields.items())
    text = ("VSVersionInfo(ffi=FixedFileInfo(filevers=%r, prodvers=%r, mask=0x3f, "
            "flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)), "
            "kids=[StringFileInfo([StringTable('040904B0', [%s])]), "
            "VarFileInfo([VarStruct('Translation', [1033, 1200])])])" % (numbers, numbers, strings))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return version
