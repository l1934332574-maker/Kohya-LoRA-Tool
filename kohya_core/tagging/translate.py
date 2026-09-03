# -*- coding: utf-8 -*-
"""标签翻译（中英互译）：基于离线词典的单条翻译与整段标签文本翻译。"""
from .normalize import has_cjk, split_tags, join_tags


def to_zh(d, name):
    """英→中：单个英文标签的翻译；未收录返回原名（不返回 None，方便界面直接展示）。"""
    zh = d.to_zh(name)
    return zh if zh else name


def to_en(d, text, limit=20):
    """中→英：输入中文，返回联想英文标签 [(name, cn, category, post_count)]。

    text 为英文时等价于英文前缀补全（方便一个入口统一处理）。
    """
    if not text:
        return []
    if has_cjk(text):
        return d.zh_candidates(text, limit=limit)
    return d.complete_en(text, limit=limit)


def translate_tags(d, caption):
    """翻译整段标签文本（按逗号拆词，逐个查词典）。

    返回 [(tag, zh)]：zh 与 tag 相同表示词典未收录（保留原名）。
    """
    out = []
    for tag in split_tags(caption):
        zh = d.to_zh(tag)
        out.append((tag, zh if zh else tag))
    return out


def summarize(d, tags):
    """给一组标签批量加中文，返回 [(tag, cn)]，未收录的 cn 留空串。"""
    res = []
    for t in tags or []:
        t = str(t or "").strip()
        if not t:
            continue
        zh = d.to_zh(t)
        res.append((t, zh if zh else ""))
    return res
