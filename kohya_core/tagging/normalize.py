# -*- coding: utf-8 -*-
"""标签文本规范化 / 拆分 / 拼接（纯函数，无 IO）。"""
import re

_CJK_RE = re.compile(
    r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]"
)
_SPLIT_RE = re.compile(r"[,，;；]+")


def has_cjk(text):
    """是否包含中日韩文字（用于区分『输入英文补全』与『输入中文反查』）。"""
    return bool(_CJK_RE.search(text or ""))


def norm_en(text):
    """英文 Danbooru 标签规范化：小写、空白/连字符转下划线、去多余下划线。

    'Blue Hair' / 'blue-hair' / 'blue  hair' → 'blue_hair'。
    含 CJK 的输入原样去掉首尾空白返回（中文走反查，不做英文规整）。
    """
    if not text:
        return ""
    t = str(text).strip()
    if not t:
        return ""
    if has_cjk(t):
        return t
    t = t.lower()
    t = re.sub(r"[\s\-]+", "_", t)
    t = re.sub(r"_+", "_", t).strip("_")
    return t


def split_tags(caption):
    """把逗号分隔的标签拆成去空白列表（兼容中英文逗号；不区分大小写去重）。"""
    parts = [p.strip() for p in _SPLIT_RE.split(caption or "") if p and p.strip()]
    out, seen = [], set()
    for p in parts:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def join_tags(tags):
    """把标签列表拼成单行逗号分隔文本（自动跳过空值）。"""
    items = [str(t).strip() for t in tags or [] if str(t or "").strip()]
    return ", ".join(items)


def normalize_caption(caption):
    """整段标签规范化：拆词、去重、按原顺序拼接，末尾不带多余符号。"""
    return join_tags(split_tags(caption))
