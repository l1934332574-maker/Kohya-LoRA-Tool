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
]

def get_kohya_dir():
    """定位 kohya_ss 训练内核目录。

    优先级：
    1) kohya_dir.txt 记录（最优先，尊重用户/历史选择）
    2) APPDATA 数据目录下的 KohyaLoraTool 文件夹里的 kohya_ss（新默认：
       和 dataset/output 放一起，升级/重装软件不删 APPDATA，训练环境直接保留，不用每次重装）
    3) 安装目录内 kohya_ss（旧版位置，向后兼容：老用户覆盖升级不重装）
    4) 用户主目录下的 kohya_ss（更早版本的兜底位置）
    5) 都不存在 -> 返回 APPDATA 数据目录下的 kohya_ss（新装到这里）
    """
    if os.path.isfile(KOHYA_DIR_FILE):
        with open(KOHYA_DIR_FILE, "r", encoding="utf-8") as f:
            p = f.read().strip().lstrip("\ufeff").strip()
        if p and os.path.isdir(p):
            return p
    # 新默认：数据目录（升级/重装软件保留，不用重装环境）
    d = os.path.join(data_dir(), "kohya_ss")
    if os.path.isdir(d):
        return d
    # 向后兼容：安装目录内（旧版位置，覆盖升级不重装）
    d_old = os.path.join(KIT_DIR, "kohya_ss")
    if os.path.isdir(d_old):
        return d_old
    # 更早版本的兜底位置
    d_legacy = os.path.join(os.path.expanduser("~"), "kohya_ss")
    if os.path.isdir(d_legacy):
        return d_legacy
    return d

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
    """跟随安装位置：安装目录同级放 KohyaLoraTool_data（升级/重装不删）。
    仅打包运行启用；源码开发环境保持 APPDATA 稳定。无写权限（如 Program Files）返回 None。"""
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
    2) 跟随安装位置：打包版默认 <安装目录同级>/KohyaLoraTool_data（装 D 盘数据就在 D 盘）
    3) %APPDATA%\\KohyaLoraTool（兜底，现状）

    output / dataset / logs / tokenizers / cache / anima / kohya_ss 等全部跟随此目录。
    """
    v = _read_data_setting()
    if v:
        return v
    v = _follow_install_dir()
    if v:
        return v
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "KohyaLoraTool")

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
        return os.path.join(data_dir(), "dataset", proj, sub)
    return os.path.join(data_dir(), "dataset", sub)

def projects_dir():
    """项目保存目录（数据目录下，随软件重装保留）。"""
    return data_sub("projects")

def _project_path(name):
    return os.path.join(projects_dir(), (name or "").strip() + ".json")

def list_projects():
    """列出所有项目，按修改时间倒序。返回 [{name, updated, mode, base_type, raw_dir, base_model}]。"""
    d = projects_dir()
    out = []
    try:
        for fn in os.listdir(d):
            if not fn.lower().endswith(".json"):
                continue
            fp = os.path.join(d, fn)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            out.append({
                "name": data.get("name") or os.path.splitext(fn)[0],
                "updated": data.get("updated", ""),
                "mode": data.get("mode", "style"),
                "base_type": data.get("base_type", "sd15"),
                "raw_dir": data.get("raw_dir", ""),
                "base_model": data.get("base_model", ""),
            })
    except Exception:
        pass
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

def default_project_name():
    """生成默认项目名：项目_MMDD_HHMM。"""
    import datetime
    return "项目_" + datetime.datetime.now().strftime("%m%d_%H%M")
