"""Build a self-contained, versioned UI recovery copy inside the frozen EXE."""
from pathlib import Path
import base64
import hashlib
import io
import json
import zipfile


def write_bundle(dist, module_path):
    dist, module_path = Path(dist), Path(module_path)
    files = sorted(p for p in dist.rglob('*') if p.is_file() and p.name != 'ui-manifest.json')
    hashes = {p.relative_to(dist).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    manifest = json.dumps({'schema': 1, 'sha256': hashes}, sort_keys=True, ensure_ascii=False, indent=2).encode('utf-8')
    (dist / 'ui-manifest.json').write_bytes(manifest)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in [*files, dist / 'ui-manifest.json']:
            archive.writestr(path.relative_to(dist).as_posix(), path.read_bytes())
    raw = payload.getvalue()
    module_path.parent.mkdir(parents=True, exist_ok=True)
    module_path.write_text(
        '# Generated at package build; bundled into PYZ, not an external recovery file.\n'
        + 'BUILD_ID = ' + repr(hashlib.sha256(manifest).hexdigest()) + '\n'
        + 'ARCHIVE_SHA256 = ' + repr(hashlib.sha256(raw).hexdigest()) + '\n'
        + 'ARCHIVE_BASE64 = ' + repr(base64.b64encode(raw)) + '\n', encoding='utf-8')
    return module_path
