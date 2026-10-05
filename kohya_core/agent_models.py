# -*- coding: utf-8 -*-
"""Safe public model search and single-file downloads for training projects.

This module intentionally supports public repositories only. It never reads tokens,
credentials, cookies, or private provider configuration from the environment.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import PurePosixPath

_AGENT = "KohyaLocalModelAgent/1.0"
_METADATA_LIMIT = 5 * 1024 * 1024
_SEARCH_LIMIT = 20
_FILE_LIMIT = 500
_BLOCK_SIZE = 1024 * 1024
_SAFE_EXTENSIONS = {
    ".safetensors", ".bin", ".pt", ".pth", ".ckpt", ".gguf",
    ".json", ".txt", ".model", ".tiktoken", ".vocab", ".merges",
    ".yaml", ".yml", ".tokenizer", ".spm", ".jinja",
}
_UNSAFE_UNICODE_PATH = frozenset("\u2044\u2215\u29f8\uff0f\uff3c")
_MODEL_ID_PART = re.compile(r"^[\w][\w.-]{0,127}$", re.UNICODE)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


class AgentModelError(Exception):
    """Expected, user-displayable model lookup or download error."""


def _provider(value):
    name = str(value or "").strip().casefold().replace("_", "-")
    if name in ("huggingface", "hugging-face", "hf"):
        return "huggingface"
    if name in ("modelscope", "model-scope", "ms", "魔搭"):
        return "modelscope"
    raise AgentModelError("暂不支持该模型来源；请选择 Hugging Face 或 ModelScope。")


def _validate_repository(repository):
    value = str(repository or "").strip()
    parts = value.split("/")
    if (len(parts) != 2 or any(not _MODEL_ID_PART.fullmatch(part) or part in (".", "..")
                               for part in parts)):
        raise AgentModelError("仓库 ID 格式无效，请输入 owner/name，例如 Qwen/Qwen-Image。")
    if any(ord(ch) < 32 or ch in "\\%?#:" for ch in value):
        raise AgentModelError("仓库 ID 含有不支持的字符。")
    return value


def _normalize_repository(provider, repository):
    """Accept an ID or a plain public repository URL from the selected provider."""
    value = str(repository or "").strip()
    if value.startswith(("https://", "http://")):
        try:
            parsed = urllib.parse.urlsplit(value)
            port = parsed.port
        except ValueError as exc:
            raise AgentModelError("仓库链接格式无效。") from exc
        host = (parsed.hostname or "").lower().rstrip(".")
        allowed = ((provider == "huggingface" and host in ("huggingface.co", "www.huggingface.co"))
                   or (provider == "modelscope" and host in ("modelscope.cn", "www.modelscope.cn")))
        if (parsed.scheme != "https" or not allowed or parsed.username or parsed.password
                or parsed.query or parsed.fragment or port not in (None, 443)):
            raise AgentModelError("请提供所选来源的公开仓库链接，不支持其他域名、短链接或带参数的 URL。")
        parts = [urllib.parse.unquote(item) for item in parsed.path.split("/") if item]
        if provider == "modelscope" and parts[:1] == ["models"]:
            parts = parts[1:]
        if provider == "huggingface" and parts[:1] == ["models"]:
            parts = parts[1:]
        value = "/".join(parts)
    return _validate_repository(value)


def _validate_repo_file(value):
    path = str(value or "")
    if (not path or path.startswith("/") or "\\" in path or "%" in path
            or any(ch in path for ch in _UNSAFE_UNICODE_PATH)
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in path)):
        raise AgentModelError("仓库文件路径无效。")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise AgentModelError("仓库文件路径不能包含空项或 ..。")
    for part in parts:
        reserved_base = os.path.splitext(part)[0].casefold()
        if (any(ch in part for ch in '<>:"|?*') or part.endswith((".", " "))
                or reserved_base in ("con", "prn", "aux", "nul")
                or re.fullmatch(r"(?:com|lpt)[1-9]", reserved_base, re.IGNORECASE)):
            raise AgentModelError("仓库文件名包含当前系统不允许的字符。")
    if PurePosixPath(path).is_absolute():
        raise AgentModelError("仓库文件路径必须是仓库内的相对路径。")
    if os.path.splitext(parts[-1])[1].casefold() not in _SAFE_EXTENSIONS:
        raise AgentModelError("此文件类型不允许下载；仅支持模型权重和常用模型配置/分词器文件。")
    return path


def _quote_parts(value):
    return "/".join(urllib.parse.quote(part, safe="") for part in value.split("/"))


def _allowed_host(provider, host):
    host = (host or "").lower().rstrip(".")
    if not host or host.startswith("[") or re.fullmatch(r"\d+(?:\.\d+){3}", host):
        return False
    if provider == "huggingface":
        return (host == "huggingface.co" or host.endswith(".huggingface.co")
                or host == "hf.co" or host == "cdn.hf.co" or host.endswith(".cdn.hf.co")
                or host.endswith(".xethub.hf.co"))
    if provider == "modelscope":
        if host == "modelscope.cn" or host.endswith(".modelscope.cn"):
            return True
        # ModelScope public object storage redirects. Internal Alibaba endpoints
        # are intentionally excluded; redirects must remain HTTPS.
        for region in ("beijing", "hangzhou", "shanghai", "shenzhen", "qingdao"):
            if host.endswith(".oss-cn-%s.aliyuncs.com" % region):
                return "-internal." not in host and not host.endswith("-internal.aliyuncs.com")
    return False


def _check_url(provider, url):
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        raise AgentModelError("来源返回了无效链接。")
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or parsed.fragment or port not in (None, 443)
            or not _allowed_host(provider, parsed.hostname)):
        raise AgentModelError("来源链接跳转到了不受信任的地址，已停止请求。")
    return parsed


class _ProviderRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 6
    max_repeats = 3

    def __init__(self, provider):
        super().__init__()
        self.provider = provider

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(self.provider, newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("Authorization")
            redirected.remove_header("Cookie")
        return redirected


def _open(provider, url, *, headers=None, timeout=30):
    _check_url(provider, url)
    request_headers = {"User-Agent": _AGENT, "Accept-Encoding": "identity"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    opener = urllib.request.build_opener(_ProviderRedirect(provider))
    try:
        response = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise AgentModelError("来源拒绝公开访问此仓库或文件（401/403）；可能需要接受许可。") from exc
        if exc.code == 404:
            raise AgentModelError("仓库或文件不存在，或该文件已从来源移除。") from exc
        raise AgentModelError("来源请求失败（HTTP %s）。" % exc.code) from exc
    except AgentModelError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise AgentModelError("连接模型来源失败：%s" % str(exc)[:240]) from exc
    try:
        _check_url(provider, response.geturl())
    except Exception:
        response.close()
        raise
    return response


def _read_json(provider, url, *, max_bytes=_METADATA_LIMIT, timeout=30, stop=None):
    _stop_requested(stop)
    with _open(provider, url, headers={"Accept": "application/json"}, timeout=timeout) as response:
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "json" not in content_type and "text/" not in content_type and "octet-stream" not in content_type:
            raise AgentModelError("来源没有返回可读取的 JSON 数据。")
        payload = response.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise AgentModelError("仓库清单超过安全读取上限，请缩小范围或选择单文件仓库。")
    _stop_requested(stop)
    try:
        return json.loads(payload.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise AgentModelError("来源返回的仓库清单格式无效。") from exc


def _search_huggingface(query, stop=None):
    params = urllib.parse.urlencode({"search": query, "limit": _SEARCH_LIMIT, "sort": "downloads", "direction": "-1"})
    payload = _read_json("huggingface", "https://huggingface.co/api/models?" + params, stop=stop)
    if not isinstance(payload, list):
        raise AgentModelError("Hugging Face 搜索返回了意外格式。")
    models = []
    for item in payload[:_SEARCH_LIMIT]:
        if not isinstance(item, dict):
            continue
        repo = item.get("modelId") or item.get("id")
        if not isinstance(repo, str):
            continue
        models.append({
            "id": repo,
            "name": repo.rsplit("/", 1)[-1],
            "description": str(item.get("description") or "")[:200],
            "pipeline_tag": str(item.get("pipeline_tag") or ""),
            "library": str(item.get("library_name") or ""),
            "downloads": item.get("downloads") if isinstance(item.get("downloads"), int) else None,
            "likes": item.get("likes") if isinstance(item.get("likes"), int) else None,
            "last_modified": item.get("lastModified") or item.get("last_modified") or "",
            "tags": [str(tag)[:100] for tag in (item.get("tags") or [])[:30] if isinstance(tag, str)],
            "url": "https://huggingface.co/" + _quote_parts(repo),
        })
    return {"ok": True, "provider": "huggingface", "query": query, "models": models,
            "count": len(models), "truncated": len(payload) >= _SEARCH_LIMIT}


def _search_modelscope(query, stop=None):
    params = urllib.parse.urlencode({"search": query, "page_size": _SEARCH_LIMIT})
    payload = _read_json("modelscope", "https://modelscope.cn/openapi/v1/models?" + params, stop=stop)
    if not isinstance(payload, dict) or payload.get("success") is False:
        raise AgentModelError("ModelScope 搜索暂不可用；可在 ModelScope 网页找到仓库后输入其 owner/name ID。")
    data = payload.get("data") or {}
    items = data.get("models") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise AgentModelError("ModelScope 搜索返回了意外格式；请粘贴仓库 ID（owner/name）继续。")
    models = []
    for item in items[:_SEARCH_LIMIT]:
        if not isinstance(item, dict):
            continue
        repo = item.get("id") or item.get("model_id")
        if not isinstance(repo, str):
            continue
        models.append({
            "id": repo,
            "name": item.get("display_name") or repo.rsplit("/", 1)[-1],
            "description": str(item.get("description") or "")[:300],
            "downloads": item.get("downloads") if isinstance(item.get("downloads"), int) else None,
            "likes": item.get("likes") if isinstance(item.get("likes"), int) else None,
            "last_modified": item.get("last_modified") or "",
            "tags": [str(tag)[:100] for tag in (item.get("tags") or [])[:30] if isinstance(tag, str)],
            "url": "https://modelscope.cn/models/" + _quote_parts(repo),
        })
    return {"ok": True, "provider": "modelscope", "query": query, "models": models,
            "count": len(models), "truncated": len(items) >= _SEARCH_LIMIT,
            "repository_id_hint": "可直接输入 ModelScope 仓库 ID，格式为 owner/name。"}


def search_models(query, provider, stop=None):
    """Search public model repositories. Returns a JSON-serializable result."""
    try:
        _stop_requested(stop)
        source = _provider(provider)
        text = str(query or "").strip()
        if not text:
            raise AgentModelError("请输入模型名称或关键词。")
        if len(text) > 200 or any(ord(ch) < 32 for ch in text):
            raise AgentModelError("搜索词过长或包含不支持的控制字符。")
        return (_search_huggingface(text, stop=stop) if source == "huggingface"
                else _search_modelscope(text, stop=stop))
    except AgentModelError as exc:
        result = {"ok": False, "provider": str(provider or ""), "query": str(query or ""),
                  "models": [], "error": str(exc)}
        if str(provider or "").strip().casefold() in ("modelscope", "model-scope", "ms", "魔搭"):
            result["repository_id_input"] = True
            result["message"] = "也可以粘贴 ModelScope 仓库 ID（owner/name）继续。"
        return result


def _modelscope_files(repository, stop=None):
    url = ("https://modelscope.cn/api/v1/models/%s/repo/files?"
           "Revision=master&Recursive=true" % _quote_parts(repository))
    payload = _read_json("modelscope", url, stop=stop)
    if not isinstance(payload, dict) or payload.get("Code") != 200:
        raise AgentModelError("无法读取 ModelScope 仓库文件清单；请确认仓库 ID 是公开的。")
    data = payload.get("Data") or {}
    raw = data.get("Files") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise AgentModelError("ModelScope 仓库清单格式无效。")
    files = []
    ignored = 0
    for item in raw:
        if not isinstance(item, dict) or str(item.get("Type") or "").casefold() == "tree":
            continue
        path = str(item.get("Path") or "").strip()
        if not path:
            continue
        try:
            path = _validate_repo_file(path)
        except AgentModelError:
            ignored += 1
            continue
        try:
            size = int(item.get("Size"))
            size = size if size > 0 else None
        except (TypeError, ValueError):
            size = None
        sha = str(item.get("Sha256") or "").lower()
        if not _SHA256.fullmatch(sha):
            sha = None
        revision = str(item.get("Revision") or "master")
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", revision):
            revision = "master"
        files.append({"path": path, "name": path.rsplit("/", 1)[-1], "size": size,
                      "sha256": sha, "revision": revision})
    files.sort(key=lambda row: row["path"].casefold())
    truncated = len(files) > _FILE_LIMIT
    return {"revision": "master", "files": files[:_FILE_LIMIT], "truncated": truncated,
            "ignored_files": ignored}


def _hf_repo_info(repository, stop=None):
    url = "https://huggingface.co/api/models/" + _quote_parts(repository)
    payload = _read_json("huggingface", url, stop=stop)
    if not isinstance(payload, dict):
        raise AgentModelError("Hugging Face 仓库信息格式无效。")
    commit = str(payload.get("sha") or "")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise AgentModelError("Hugging Face 仓库没有可用的固定版本号。")
    return payload, commit.lower()


def _next_link(headers):
    link = headers.get("Link") or ""
    for item in link.split(","):
        match = re.search(r"<([^>]+)>\s*;\s*rel\s*=\s*\"?next\"?", item, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _hf_files(repository, commit, stop=None):
    path = "/api/models/%s/tree/%s" % (_quote_parts(repository), urllib.parse.quote(commit, safe=""))
    params = urllib.parse.urlencode({"recursive": "true", "expand": "true", "limit": "100"})
    next_url = "https://huggingface.co" + path + "?" + params
    files = []
    seen_urls = set()
    ignored = 0
    truncated = False
    while next_url and len(files) < _FILE_LIMIT:
        _stop_requested(stop)
        parsed = _check_url("huggingface", next_url)
        if parsed.hostname != "huggingface.co" or not parsed.path.startswith(path):
            raise AgentModelError("Hugging Face 文件分页链接超出当前仓库，已停止读取。")
        if next_url in seen_urls:
            raise AgentModelError("Hugging Face 文件分页重复，已停止读取。")
        seen_urls.add(next_url)
        with _open("huggingface", next_url, headers={"Accept": "application/json"}) as response:
            payload_bytes = response.read(_METADATA_LIMIT + 1)
            if len(payload_bytes) > _METADATA_LIMIT:
                raise AgentModelError("仓库文件页超过安全读取上限。")
            try:
                rows = json.loads(payload_bytes.decode("utf-8-sig"))
            except (ValueError, UnicodeError) as exc:
                raise AgentModelError("Hugging Face 文件清单格式无效。") from exc
            following = _next_link(response.headers)
        _stop_requested(stop)
        if not isinstance(rows, list):
            raise AgentModelError("Hugging Face 文件清单格式无效。")
        for item in rows:
            if not isinstance(item, dict) or str(item.get("type") or "file").casefold() not in ("file", "regular"):
                continue
            raw_path = item.get("path")
            if not isinstance(raw_path, str):
                continue
            try:
                file_path = _validate_repo_file(raw_path)
            except AgentModelError:
                ignored += 1
                continue
            lfs = item.get("lfs") if isinstance(item.get("lfs"), dict) else {}
            raw_size = lfs.get("size", item.get("size"))
            try:
                size = int(raw_size)
                size = size if size > 0 else None
            except (TypeError, ValueError):
                size = None
            raw_sha = str(lfs.get("sha256") or item.get("sha256") or lfs.get("oid") or "").lower()
            if raw_sha.startswith("sha256:"):
                raw_sha = raw_sha[7:]
            sha = raw_sha if _SHA256.fullmatch(raw_sha) else None
            files.append({"path": file_path, "name": file_path.rsplit("/", 1)[-1],
                          "size": size, "sha256": sha, "revision": commit})
            if len(files) >= _FILE_LIMIT:
                truncated = bool(following)
                break
        next_url = following if len(files) < _FILE_LIMIT else None
    if next_url:
        truncated = True
    files.sort(key=lambda row: row["path"].casefold())
    return {"revision": commit, "files": files[:_FILE_LIMIT], "truncated": truncated,
            "ignored_files": ignored}


def model_repository(provider, repository, stop=None):
    """Return safe downloadable file metadata for one public model repository."""
    source = str(provider or "")
    repo = str(repository or "")
    try:
        _stop_requested(stop)
        source = _provider(provider)
        repo = _normalize_repository(source, repository)
        if source == "huggingface":
            info, revision = _hf_repo_info(repo, stop=stop)
            listing = _hf_files(repo, revision, stop=stop)
            title = str(info.get("id") or repo)
            license_tag = next((str(t).split(":", 1)[1] for t in (info.get("tags") or [])
                                if isinstance(t, str) and t.startswith("license:")), "")
        else:
            listing = _modelscope_files(repo, stop=stop)
            revision = listing["revision"]
            title = repo
            license_tag = ""
        return {"ok": True, "provider": source, "repository": repo, "name": title,
                "revision": revision, "license": license_tag, "files": listing["files"],
                "count": len(listing["files"]), "truncated": listing["truncated"],
                "ignored_files": listing["ignored_files"],
                "message": "仓库文件清单超过 %d 项且已截断；只能下载当前已显示并验证过的文件。" % _FILE_LIMIT
                           if listing["truncated"] else ""}
    except AgentModelError as exc:
        return {"ok": False, "provider": source, "repository": repo, "files": [], "error": str(exc)}


def _stop_requested(stop):
    if stop is None:
        return False
    if hasattr(stop, "is_set"):
        return bool(stop.is_set())
    if callable(stop):
        # In particular, let the root worker's RuntimeError cancellation signal through.
        return bool(stop())
    return bool(stop)


def _progress(callback, done, total, speed, file_path, message=""):
    if not callback:
        return
    fraction = (min(1.0, done / total) if total and total > 0 else 0.0)
    event = {"progress": fraction, "message": message or ("下载中：" + file_path),
             "bytes_done": int(done), "total_bytes": int(total) if total is not None else None,
             "speed_bps": round(float(speed), 1), "file": file_path}
    try:
        callback(event)
    except TypeError:
        try:
            callback(fraction)
        except Exception:
            pass
    except Exception:
        pass


def _guard_local_path(root, path):
    """Resolve a path beneath the selected root and reject file/parent symlink escapes."""
    root_real = os.path.realpath(root)
    absolute = os.path.abspath(path)
    parent_real = os.path.realpath(os.path.dirname(absolute))
    try:
        if os.path.commonpath((root_real, parent_real)) != root_real:
            raise AgentModelError("下载路径越出了所选文件夹。")
    except ValueError as exc:
        raise AgentModelError("下载路径无效。") from exc
    resolved = os.path.join(parent_real, os.path.basename(absolute))
    if os.path.islink(resolved):
        raise AgentModelError("下载路径包含符号链接；请改选普通文件夹。")
    return resolved


def _destination_path(destination, file_path):
    raw_root = str(destination or "").strip()
    if not raw_root:
        raise AgentModelError("请选择本地下载文件夹。")
    root = os.path.abspath(os.path.expanduser(raw_root))
    os.makedirs(root, exist_ok=True)
    root_real = os.path.realpath(root)
    target = os.path.abspath(os.path.join(root_real, *file_path.split("/")))
    return root_real, _guard_local_path(root_real, target)


def _download_url(provider, repository, file_info):
    repo = _quote_parts(repository)
    file_path = "/".join(urllib.parse.quote(part, safe="") for part in file_info["path"].split("/"))
    revision = urllib.parse.quote(str(file_info.get("revision") or "main"), safe="")
    if provider == "huggingface":
        return "https://huggingface.co/%s/resolve/%s/%s?download=true" % (repo, revision, file_path)
    return "https://modelscope.cn/models/%s/resolve/%s/%s" % (repo, revision, file_path)


def _validate_safetensors(path, size):
    with open(path, "rb") as handle:
        prefix = handle.read(8)
        if len(prefix) != 8:
            raise AgentModelError("safetensors 文件头不完整。")
        header_len = struct.unpack("<Q", prefix)[0]
        if header_len < 2 or header_len > min(64 * 1024 * 1024, size - 8):
            raise AgentModelError("safetensors 文件头长度无效。")
        try:
            header = json.loads(handle.read(header_len).decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise AgentModelError("safetensors 文件头格式无效。") from exc
    if not isinstance(header, dict):
        raise AgentModelError("safetensors 文件头格式无效。")
    payload_size = size - 8 - header_len
    offsets = []
    for name, item in header.items():
        if name == "__metadata__":
            continue
        if not isinstance(item, dict):
            raise AgentModelError("safetensors 张量描述无效。")
        pair = item.get("data_offsets")
        if (not isinstance(pair, list) or len(pair) != 2
                or any(type(value) is not int for value in pair)
                or pair[0] < 0 or pair[0] > pair[1] or pair[1] > payload_size):
            raise AgentModelError("safetensors 张量数据范围无效。")
        offsets.append((pair[0], pair[1]))
    offsets.sort()
    if not offsets or offsets[-1][1] != payload_size:
        raise AgentModelError("safetensors 张量数据不完整。")
    if any(left[1] > right[0] for left, right in zip(offsets, offsets[1:])):
        raise AgentModelError("safetensors 张量数据范围重叠。")
    return True


def _file_metadata(provider, repository, file_path, stop=None):
    inventory = model_repository(provider, repository, stop=stop)
    _stop_requested(stop)
    if not inventory.get("ok"):
        raise AgentModelError(inventory.get("error") or "无法验证仓库文件。")
    for item in inventory["files"]:
        if item["path"] == file_path:
            return inventory, item
    if inventory.get("truncated"):
        raise AgentModelError("仓库文件清单超过 %d 项且已截断，无法验证未显示的文件；请选择清单中已显示的文件。" % _FILE_LIMIT)
    raise AgentModelError("所选文件不在该仓库的公开文件清单中。")


def _mark_restart_required(root, metadata_path, metadata):
    """Keep the partial for diagnosis, but prevent appending it after validation failure."""
    try:
        safe_path = _guard_local_path(root, metadata_path)
        value = dict(metadata) if isinstance(metadata, dict) else {}
        value["restart_required"] = True
        with open(safe_path, "w", encoding="utf-8") as handle:
            json.dump(value, handle)
    except (OSError, AgentModelError):
        pass


def download_file(provider, repository, file, destination, stop=None, progress=None):
    """Download one listed public model file into a user-authorized local folder.

    ``destination`` is a destination folder. The repository-relative file path is
    preserved under it. Cancellation raises RuntimeError and leaves the .part file.
    Cancellation is checked between metadata requests and response reads; one
    metadata request can take up to 30 seconds to time out, and a stalled file read
    can take up to the 60-second request timeout to return.
    """
    source = str(provider or "")
    repo = str(repository or "")
    file_value = (file.get("path") or file.get("rfilename") or file.get("file")
                  if isinstance(file, dict) else file)
    target_file = str(file_value or "")
    part = metadata_path = ""
    try:
        source = _provider(provider)
        repo = _normalize_repository(source, repository)
        target_file = _validate_repo_file(file_value)
        if _stop_requested(stop):
            raise RuntimeError("已取消下载。")
        _progress(progress, 0, None, 0.0, target_file, "正在检查仓库文件信息…")
        _inventory, file_info = _file_metadata(source, repo, target_file, stop=stop)
        root, final_path = _destination_path(destination, target_file)
        os.makedirs(os.path.dirname(final_path), exist_ok=True)
        final_path = _guard_local_path(root, final_path)
        part = _guard_local_path(root, final_path + ".part")
        metadata_path = _guard_local_path(root, part + ".json")
        if os.path.lexists(final_path):
            raise AgentModelError("目标文件已存在，为避免覆盖，下载已停止：%s" % final_path)
        url = _download_url(source, repo, file_info)
        _check_url(source, url)
        expected_size = file_info.get("size")
        expected_sha = file_info.get("sha256")
        source_id = hashlib.sha256(url.encode("utf-8")).hexdigest()
        try:
            metadata_path = _guard_local_path(root, metadata_path)
            with open(metadata_path, "rb") as handle:
                raw_meta = handle.read(64 * 1024 + 1)
            if len(raw_meta) > 64 * 1024:
                raise ValueError("resume metadata too large")
            old_meta = json.loads(raw_meta.decode("utf-8"))
        except (OSError, ValueError, UnicodeError, AgentModelError):
            old_meta = {}
        if not isinstance(old_meta, dict):
            old_meta = {}
        try:
            part_size = os.path.getsize(part)
        except OSError:
            part_size = 0
        resumable = bool(part_size and old_meta.get("source") == source_id
                         and not old_meta.get("restart_required")
                         and (expected_size is None or part_size < expected_size)
                         and ((expected_sha and old_meta.get("expected_sha256") == expected_sha)
                              or old_meta.get("validator")))
        if not resumable:
            part_size = 0
            try:
                with open(part, "wb"):
                    pass
            except OSError as exc:
                raise AgentModelError("无法创建下载临时文件：%s" % str(exc)[:160]) from exc
        if expected_size is not None:
            try:
                free = shutil.disk_usage(root).free
            except OSError:
                free = None
            remaining = max(0, expected_size - part_size)
            if free is not None and remaining > free:
                raise AgentModelError("磁盘空间不足：还需约 %.2f GB，可用 %.2f GB。" %
                                      (remaining / (1024 ** 3), free / (1024 ** 3)))
        if _stop_requested(stop):
            raise RuntimeError("已取消下载；可重试并从已保留的临时文件继续。")
        headers = {"Accept": "application/octet-stream", "Accept-Encoding": "identity"}
        validator = old_meta.get("validator") if resumable else None
        if part_size:
            headers["Range"] = "bytes=%d-" % part_size
            if validator:
                headers["If-Range"] = str(validator)
        _progress(progress, part_size, expected_size, 0.0, target_file, "准备下载：" + target_file)
        try:
            response = _open(source, url, headers=headers, timeout=60)
        except AgentModelError as exc:
            if part_size and "416" in str(exc):
                _mark_restart_required(root, metadata_path, old_meta)
            raise
        with response:
            status = getattr(response, "status", None) or response.getcode()
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "text/html" in content_type:
                _mark_restart_required(root, metadata_path, old_meta)
                raise AgentModelError("来源返回了网页，未得到模型文件。")
            if part_size and status == 206:
                content_range = response.headers.get("Content-Range") or ""
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range.strip())
                if not match or int(match.group(1)) != part_size:
                    _mark_restart_required(root, metadata_path, old_meta)
                    raise AgentModelError("断点续传范围不匹配；下次重试会从头下载。")
                total = int(match.group(3))
                response_validator = response.headers.get("ETag") or response.headers.get("Last-Modified")
                if validator and response_validator and response_validator != validator:
                    _mark_restart_required(root, metadata_path, old_meta)
                    raise AgentModelError("来源文件版本已变化；下次重试会从头下载。")
                start = part_size
            elif status == 200:
                start = 0
                content_length = response.headers.get("Content-Length")
                try:
                    total = int(content_length) if content_length is not None else expected_size
                except (TypeError, ValueError):
                    total = expected_size
            else:
                raise AgentModelError("来源返回了不支持的下载状态（HTTP %s）。" % status)
            if expected_size is not None and total is not None and expected_size != total:
                _mark_restart_required(root, metadata_path, old_meta)
                raise AgentModelError("来源报告的文件大小与仓库清单不一致。")
            total = expected_size if expected_size is not None else total
            current_validator = response.headers.get("ETag") or response.headers.get("Last-Modified")
            metadata = {"source": source_id, "validator": current_validator,
                        "total": total, "expected_sha256": expected_sha}
            try:
                metadata_path = _guard_local_path(root, metadata_path)
                with open(metadata_path, "w", encoding="utf-8") as handle:
                    json.dump(metadata, handle)
            except OSError as exc:
                raise AgentModelError("无法保存断点续传信息：%s" % str(exc)[:160]) from exc
            digest = hashlib.sha256()
            if start:
                part = _guard_local_path(root, part)
                with open(part, "rb") as existing:
                    while True:
                        if _stop_requested(stop):
                            raise RuntimeError("已取消下载；临时文件已保留，可重试续传。")
                        chunk = existing.read(_BLOCK_SIZE)
                        if not chunk:
                            break
                        digest.update(chunk)
            mode = "ab" if start else "wb"
            done = start
            with open(part, mode) as handle:
                last_time = time.monotonic()
                last_done = done
                speed = 0.0
                while True:
                    if _stop_requested(stop):
                        handle.flush()
                        raise RuntimeError("已取消下载；临时文件已保留，可重试续传。")
                    chunk = response.read(_BLOCK_SIZE)
                    if not chunk:
                        break
                    if total is not None and done + len(chunk) > total:
                        _mark_restart_required(root, metadata_path, metadata)
                        raise AgentModelError("来源发送的数据超过了仓库清单所示大小。")
                    handle.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last_time >= 0.5:
                        speed = (done - last_done) / max(0.001, now - last_time)
                        last_time, last_done = now, done
                    _progress(progress, done, total, speed, target_file)
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
        if _stop_requested(stop):
            raise RuntimeError("已取消下载；临时文件已保留，可重试续传。")
        actual_size = os.path.getsize(part)
        if actual_size <= 0 or (total is not None and actual_size != total):
            raise AgentModelError("下载未完成（%s/%s 字节）；临时文件已保留，可重试。" %
                                  (actual_size, total if total is not None else "未知"))
        part = _guard_local_path(root, part)
        with open(part, "rb") as handle:
            prefix = handle.read(256).lstrip().lower()
        if prefix.startswith((b"<!doctype html", b"<html", b"<?xml")):
            _mark_restart_required(root, metadata_path, metadata)
            raise AgentModelError("来源返回了网页或错误页，已拒绝保存为模型文件。")
        actual_sha = digest.hexdigest()
        if expected_sha and actual_sha.lower() != expected_sha.lower():
            _mark_restart_required(root, metadata_path, metadata)
            raise AgentModelError("文件 SHA256 校验失败；临时文件已保留，下次重试会从头下载。")
        safetensors_checked = False
        if target_file.lower().endswith(".safetensors"):
            try:
                safetensors_checked = _validate_safetensors(part, actual_size)
            except AgentModelError:
                _mark_restart_required(root, metadata_path, metadata)
                raise
        final_path = _guard_local_path(root, final_path)
        part = _guard_local_path(root, part)
        metadata_path = _guard_local_path(root, metadata_path)
        if os.path.lexists(final_path):
            raise AgentModelError("下载期间目标文件已出现，为避免覆盖已停止。")
        os.replace(part, final_path)
        try:
            os.remove(metadata_path)
        except OSError:
            pass
        _progress(progress, actual_size, total, 0.0, target_file, "下载完成：" + target_file)
        return {"ok": True, "provider": source, "repository": repo, "file": target_file,
                "path": final_path, "bytes": actual_size, "sha256": actual_sha,
                "expected_sha256": expected_sha, "revision": file_info.get("revision"),
                "resumed": bool(part_size), "compatible": None,
                "validation": {"size_verified": total is not None and actual_size == total,
                               "sha256_verified": bool(expected_sha),
                               "safetensors_header_verified": safetensors_checked,
                               "source_revision": file_info.get("revision"),
                               "source_url": url, "content_type": content_type}}
    except RuntimeError:
        raise
    except AgentModelError as exc:
        return {"ok": False, "provider": source, "repository": repo, "file": target_file,
                "path": final_path if "final_path" in locals() else "", "error": str(exc),
                "partial_path": part if part and os.path.isfile(part) else ""}
    except (OSError, ValueError, TypeError, urllib.error.URLError) as exc:
        return {"ok": False, "provider": source, "repository": repo, "file": target_file,
                "path": final_path if "final_path" in locals() else "", "error": str(exc)[:300],
                "partial_path": part if part and os.path.isfile(part) else ""}
