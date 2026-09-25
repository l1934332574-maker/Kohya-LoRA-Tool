# -*- coding: utf-8 -*-
"""路径与项目管理（渐进式拆分，从 Kohya一键工具.py 迁出）。"""
import os
import re
import sys
import json
import datetime

from kohya_core import KIT_DIR, KOHYA_DIR_FILE

__all__ = [
    "get_kohya_dir", "base_models_dir", "data_dir", "data_sub", "_sanitize_dirname",
    "_settings_path", "save_data_setting",
    "dataset_train_dir", "projects_dir", "_project_path", "list_projects",
    "load_project", "save_project", "delete_project", "default_project_name",
    "project_data_dir", "project_output_dir", "dir_stats", "delete_project_data",
    "find_orphan_project_dirs", "delete_orphan_project_dirs",
]

def get_kohya_dir():
    """定位 kohya_ss 训练内核目录。

    优先级：
    1) kohya_dir.txt 记录及其中的有效训练源码
    2) 当前数据目录、历史 AppData 数据目录、安装目录旁数据目录里的 kohya_ss
    3) 安装目录 / 用户主目录下的旧位置
    4) 都不存在 -> 返回当前数据目录下的 kohya_ss，供首次安装使用
    """
    pinned = ""
    if os.path.isfile(KOHYA_DIR_FILE):
        with open(KOHYA_DIR_FILE, "r", encoding="utf-8") as f:
            p = f.read().strip().lstrip("\ufeff").strip()
        if p and os.path.isdir(p):
            pinned = os.path.abspath(p)

    # 数据根目录可能因安装位置变化而切换；训练内核始终留在原目录。
    # 在当前根、历史 AppData 根和安装目录旁的旧根中找现存源码，防止 UI 将其误报为未安装。
    candidates = [pinned]
    for root in (data_dir(), _appdata_data_dir(), _install_data_dir()):
        if root:
            candidates.append(os.path.join(root, "kohya_ss"))
    candidates.extend((
        os.path.join(KIT_DIR, "kohya_ss"),
        os.path.join(os.path.expanduser("~"), "kohya_ss"),
    ))

    seen = set()
    existing_dirs = []
    for candidate in candidates:
        if not candidate:
            continue
        candidate = os.path.abspath(candidate)
        key = os.path.normcase(candidate)
        if key in seen:
            continue
        seen.add(key)
        if not os.path.isdir(candidate):
            continue
        existing_dirs.append(candidate)
        if (os.path.isdir(os.path.join(candidate, ".git"))
                or os.path.isfile(os.path.join(candidate, "kohya_gui.py"))
                or os.path.isfile(os.path.join(candidate, "setup", "setup_windows.py"))
                or os.path.isdir(os.path.join(candidate, "sd-scripts"))):
            return candidate

    # 保留已记录的部分安装目录，允许原有安装器继续修复；新安装仍落在当前数据根。
    if pinned and os.path.isdir(pinned):
        return pinned
    if existing_dirs:
        return existing_dirs[0]
    return os.path.join(data_dir(), "kohya_ss")

def base_models_dir():
    """默认基础底模存放目录（项目内 models/base，软件不内置底模）。"""
    return os.path.join(KIT_DIR, "models", "base")

def _settings_path():
    """设置文件固定存 %APPDATA%\\KohyaLoraTool（小文件，不随数据目录移动），
    避免 data_dir 依赖设置、设置又依赖 data_dir 的循环。"""
    ap = os.environ.get("APPDATA", os.path.expanduser("~"))
    d = os.path.join(ap, "KohyaLoraTool")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return os.path.join(d, "settings.json")


def _read_data_setting():
    """读用户设置里指定的数据目录（未设置/不存在返回空）。"""
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            d = json.load(f)
        v = (d.get("data_dir") or "").strip()
        return v if v and os.path.isdir(v) else ""
    except Exception:
        return ""


def _appdata_data_dir():
    ap = os.environ.get("APPDATA", os.path.expanduser("~"))
    return os.path.abspath(os.path.join(ap, "KohyaLoraTool"))


def _install_data_dir():
    """Return the packaged app's adjacent data path without creating it."""
    if not getattr(sys, "frozen", False):
        return ""
    parent = os.path.dirname(os.path.abspath(KIT_DIR))
    return os.path.abspath(os.path.join(parent, "KohyaLoraTool_data"))


def save_data_setting(dir):
    """保存用户指定的数据目录（保留已有设置项）。返回是否成功。"""
    try:
        d = {}
        try:
            with open(_settings_path(), "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
        d["data_dir"] = (dir or "").strip()
        with open(_settings_path(), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _follow_install_dir():
    """新打包安装默认在安装目录同级放 KohyaLoraTool_data；源码运行使用 APPDATA。
    仅打包运行启用；无写权限（如 Program Files）返回 None。"""
    if not getattr(sys, "frozen", False):
        return None
    try:
        parent = os.path.dirname(os.path.abspath(KIT_DIR))
        cand = os.path.join(parent, "KohyaLoraTool_data")
        os.makedirs(cand, exist_ok=True)
        t = os.path.join(cand, ".write_test")
        with open(t, "w") as f:
            f.write("1")
        os.remove(t)
        return cand
    except Exception:
        return None


def data_dir():
    """运行期可写数据目录。

    优先级：
    1) 用户设置的数据目录（settings.json 的 data_dir，任意盘）
    2) 打包版默认 <安装目录同级>/KohyaLoraTool_data（沿用 0.17.x 路径规则）
    3) 源码运行/安装目录不可写时使用 %APPDATA%\\KohyaLoraTool

    output / dataset / logs / tokenizers / cache / anima / kohya_ss 等全部跟随此目录。
    """
    v = _read_data_setting()
    if v:
        return v
    v = _follow_install_dir()
    if v:
        return v
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "KohyaLoraTool")


def _known_data_roots():
    """Return the selected and legacy data roots, preserving their current on-disk contents."""
    roots = [data_dir(), _appdata_data_dir(), _install_data_dir()]
    try:
        with open(KOHYA_DIR_FILE, "r", encoding="utf-8") as handle:
            kernel_dir = handle.read().strip().lstrip("\ufeff").strip()
        if kernel_dir:
            kernel_dir = os.path.abspath(kernel_dir)
            if os.path.basename(os.path.normpath(kernel_dir)).casefold() == "kohya_ss":
                roots.append(os.path.dirname(kernel_dir))
            elif any(os.path.isdir(os.path.join(kernel_dir, child))
                     for child in ("kohya_ss", "projects", "dataset")):
                # Older builds also accepted the data root itself in kohya_dir.txt.
                roots.append(kernel_dir)
    except (OSError, UnicodeError):
        pass

    unique = []
    seen = set()
    for root in roots:
        if not root:
            continue
        root = os.path.abspath(root)
        key = os.path.normcase(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


_DATASET_IMAGE_EXTS = {
    ".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".webp", ".bmp",
    ".tif", ".tiff", ".gif", ".avif",
}


def _has_dataset_images(directory):
    if not directory or not os.path.isdir(directory):
        return False
    for root, dirs, files in os.walk(directory):
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        if any(os.path.splitext(name)[1].lower() in _DATASET_IMAGE_EXTS for name in files):
            return True
    return False


def _directory_has_files(directory):
    if not directory or not os.path.isdir(directory):
        return False
    for _root, dirs, files in os.walk(directory):
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        if files:
            return True
    return False

def data_sub(*parts):
    d = os.path.join(data_dir(), *parts)
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d

def _sanitize_dirname(name):
    """把项目名清洗成可用的文件夹名（兼容中文，去掉路径非法字符）。"""
    return re.sub(r'[\\/:*?"<>|\r\n]', "_", (name or "").strip()).strip(" .")

def dataset_train_dir(mode="style", project=None):
    """当前模式对应的训练数据集目录（人物=train_character，画风=train）。

    - project 为空：旧版共享目录 dataset/train_character（兼容历史数据）；
    - project 非空：项目独立目录 dataset/<项目名>/train_character，
      每个项目的数据互不混用（标签编辑器/预处理/训练都按项目隔离）。
    """
    proj = _sanitize_dirname(project)
    sub = "train" if mode == "style" else "train_character"
    if proj:
        current_root = data_dir()
        current = os.path.join(current_root, "dataset", proj, sub)
        if not _has_dataset_images(current):
            for root in _known_data_roots():
                if os.path.normcase(root) == os.path.normcase(os.path.abspath(current_root)):
                    continue
                legacy = os.path.join(root, "dataset", proj, sub)
                if _has_dataset_images(legacy):
                    return legacy
        return current
    current_root = data_dir()
    current = os.path.join(current_root, "dataset", sub)
    if not _has_dataset_images(current):
        for root in _known_data_roots():
            if os.path.normcase(root) == os.path.normcase(os.path.abspath(current_root)):
                continue
            legacy = os.path.join(root, "dataset", sub)
            if _has_dataset_images(legacy):
                return legacy
    return current

def projects_dir():
    """项目保存目录（数据目录下，随软件重装保留）。"""
    return data_sub("projects")

def _project_path(name):
    filename = (name or "").strip() + ".json"
    current = os.path.join(projects_dir(), filename)
    if os.path.isfile(current):
        return current
    current_root = data_dir()
    for root in _known_data_roots():
        if os.path.normcase(root) == os.path.normcase(os.path.abspath(current_root)):
            continue
        legacy = os.path.join(root, "projects", filename)
        if os.path.isfile(legacy):
            return legacy
    return current

def list_projects():
    """列出所有项目，按修改时间倒序。返回 [{name, updated, mode, base_type, raw_dir, base_model}]。"""
    out = []
    seen = set()
    roots = _known_data_roots()
    for root in roots:
        d = os.path.join(root, "projects")
        try:
            filenames = os.listdir(d)
        except OSError:
            continue
        for fn in filenames:
            if not fn.lower().endswith(".json"):
                continue
            fp = os.path.join(d, fn)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            name = str(data.get("name") or os.path.splitext(fn)[0])
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "name": name,
                "updated": data.get("updated", ""),
                "mode": data.get("mode", "style"),
                "base_type": data.get("base_type", "sd15"),
                "raw_dir": data.get("raw_dir", ""),
                "base_model": data.get("base_model", ""),
            })
    out.sort(key=lambda x: x.get("updated", ""), reverse=True)
    return out

def load_project(name):
    """读取项目。返回 dict 或 None。"""
    fp = _project_path(name)
    if not os.path.isfile(fp):
        return None
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def save_project(name, data):
    """保存项目（自动写 updated 时间）。返回是否成功。"""
    name = (name or "").strip()
    if not name:
        return False
    import datetime
    data = dict(data or {})
    data["name"] = name
    data["updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not data.get("created"):
        data["created"] = data["updated"]
    try:
        os.makedirs(projects_dir(), exist_ok=True)
        with open(_project_path(name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def delete_project(name):
    """删除项目文件。"""
    fp = _project_path(name)
    try:
        if os.path.isfile(fp):
            os.remove(fp)
            return True
    except Exception:
        pass
    return False

def project_data_dir(name):
    """项目的图集目录（预处理后的图片 + 打标文件 + 各引擎缓存）。

    范围就是 data/dataset/<项目名>/ —— 底下装 train / train_character（图片与 .txt 打标）
    以及 krea2_cache / flux2_cache / fizgig_cache / fizgig_klein_cache 等派生产物。
    项目改名时 GUI 会整体 rename 这个目录（kohya_gui.cmd_rename_project），
    可见它就是「一个项目的数据边界」，删除项目时理应一并处理。
    """
    proj = _sanitize_dirname(name)
    if not proj:
        return ""
    current_root = data_dir()
    current = os.path.join(current_root, "dataset", proj)
    if not _directory_has_files(current):
        for root in _known_data_roots():
            if os.path.normcase(root) == os.path.normcase(os.path.abspath(current_root)):
                continue
            legacy = os.path.join(root, "dataset", proj)
            if _directory_has_files(legacy):
                return legacy
    return current


def project_output_dir(name):
    """项目的训练产物目录（LoRA 成品 / 采样图 / 训练日志）。

    ⚠️ **有意不随项目删除** —— 里面是用户训练出来的模型成品，删项目不等于不要模型。
    （也是删除确认框里一直写「训练产物仍在 output 文件夹」的原因。）
    """
    proj = _sanitize_dirname(name)
    if not proj:
        return ""
    current_root = data_dir()
    current = os.path.join(current_root, "output", proj)
    if not _directory_has_files(current):
        for root in _known_data_roots():
            if os.path.normcase(root) == os.path.normcase(os.path.abspath(current_root)):
                continue
            legacy = os.path.join(root, "output", proj)
            if _directory_has_files(legacy):
                return legacy
    return current


def dir_stats(d):
    """目录的 (文件数, 总字节)；不存在或读不到返回 (0, 0)。"""
    n = 0
    total = 0
    if not d or not os.path.isdir(d):
        return 0, 0
    try:
        for root, _dirs, files in os.walk(d):
            for f in files:
                n += 1
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except Exception:
        pass
    return n, total


def delete_project_data(name):
    """删除项目的图集目录（预处理图片 + 打标文件 + 引擎缓存）。

    返回 (ok, 文件数, 字节数)：n/bytes 是删除前测得的量，供调用方报「释放了多少」。
    **不含** output/<项目名> 的训练产物（见 project_output_dir），由调用方决定。

    背景（2026-09-15 用户反馈）：delete_project() 只删 projects/<名>.json，
    图集目录原封不动 —— 项目一旦删除，这批数据再没有任何界面入口，
    却一直占着磁盘（一个项目的预处理图集常有几百 MB 到数 GB）。
    """
    d = project_data_dir(name)
    if not d or not os.path.isdir(d):
        return True, 0, 0
    # 保险丝：只允许删 data/dataset/<单层>/ —— 项目名经 _sanitize_dirname 已去掉路径分隔符，
    # 这里再校验一次父目录，避免任何异常输入把 rmtree 指到 dataset 或数据根上。
    if os.path.basename(os.path.dirname(os.path.abspath(d))) != "dataset":
        return False, 0, 0
    n, size = dir_stats(d)
    import shutil
    try:
        shutil.rmtree(d)
        return True, n, size
    except Exception:
        return False, n, size


# 旧版共享数据集目录（不属于任何项目）：dataset_train_dir() 在 project 为空时就写这里，
# 清理「无主数据」时必须排除，否则会把「没开项目」模式的数据一起删掉。
_LEGACY_SHARED_DATASET_DIRS = ("train", "train_character")


def find_orphan_project_dirs():
    """找出没有对应项目文件的图集目录 —— 即删除项目时遗漏、之后无人认领的孤儿数据。

    返回 [(名称, 路径, 文件数, 字节数), ...]，按占用从大到小（大的先清，收益最直观）。

    判定方式：目录名（= 项目名，list_projects 用项目名存 json）在 projects/ 里找不到同名
    .json。已知的误判边界：项目名含路径非法字符时 json 名与目录名同为原始名，仍然一致；
    真正需要排除的是旧版共享目录（见上）。
    """
    root = os.path.join(data_dir(), "dataset")
    if not os.path.isdir(root):
        return []
    known = set()
    try:
        for fn in os.listdir(projects_dir()):
            if fn.lower().endswith(".json"):
                known.add(os.path.splitext(fn)[0])
    except Exception:
        pass
    out = []
    try:
        for name in os.listdir(root):
            if name in _LEGACY_SHARED_DATASET_DIRS or name.startswith("."):
                continue
            p = os.path.join(root, name)
            if not os.path.isdir(p) or name in known:
                continue
            n, b = dir_stats(p)
            out.append((name, p, n, b))
    except Exception:
        pass
    out.sort(key=lambda x: x[3], reverse=True)
    return out


def delete_orphan_project_dirs():
    """删除全部无主图集目录。返回 (成功项数, 文件数, 字节数, 失败项名称列表)。

    每次调用都重新扫一遍（而不是复用调用方手里的旧列表）—— 避免用户看到确认框之后
    又新建了同名项目，把新数据误删。
    """
    import shutil
    ok_n = files = size = 0
    failed = []
    for name, p, n, b in find_orphan_project_dirs():
        try:
            shutil.rmtree(p)
            ok_n += 1
            files += n
            size += b
        except Exception:
            failed.append(name)
    return ok_n, files, size, failed


def default_project_name():
    """生成默认项目名：项目_MMDD_HHMM。"""
    import datetime
    return "项目_" + datetime.datetime.now().strftime("%m%d_%H%M")
