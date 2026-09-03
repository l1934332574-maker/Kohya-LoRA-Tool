# -*- coding: utf-8 -*-
"""补全建议：离线词典 + 当前数据集已有标签（频率）混合排序。

排序策略：
  1) 数据集里真实出现过的标签优先（按数据集出现次数），贴近当前训练集；
  2) 其余按词典热度（Danbooru post_count）补充。
"""
from .normalize import norm_en, split_tags


def _user_prefix_matches(user_tags, prefix):
    """user_tags: dict 标签名->次数。返回 [{name, count}] 按次数降序。"""
    p = norm_en(prefix)
    out = []
    if not p:
        return out
    for name, cnt in user_tags.items():
        if norm_en(name).startswith(p):
            out.append((name, cnt))
    out.sort(key=lambda kv: (-kv[1], kv[0]))
    return out


def suggest_en(d, prefix, user_tags=None, limit=30):
    """英文补全：user_tags 命中的放前面（按数据集频率），再用词典热度补充。

    user_tags 形如 {标签名: 出现次数}，来自数据集统计；可为 None。
    """
    if not prefix:
        return []
    user_tags = user_tags or {}
    hits = _user_prefix_matches(user_tags, prefix)
    if hits:
        out = []
        seen = set()
        for name, cnt in hits:
            r0 = d.lookup(name)
            if r0:
                cn, cat, cnt0 = r0
                cntv = cnt0 if cnt0 else cnt
            else:
                cn, cat, cntv = "", 0, cnt
            out.append((name, cn if cn else "", cat, cntv))
            seen.add(name.lower())
            if len(out) >= limit:
                return out
        rest = [r for r in d.complete_en(prefix, limit=limit)
                if r[0].lower() not in seen]
        return out + rest[: max(0, limit - len(out))]
    return d.complete_en(prefix, limit=limit)


def freq_of(records):
    """从数据集记录（[{caption}]）统计标签频率，返回 {标签名: 次数}（大小写不敏感合并）。"""
    cnt = {}
    for it in records or []:
        for tag in split_tags(it.get("caption", "")):
            low = tag.lower()
            cnt[low] = cnt.get(low, 0) + 1
    return cnt
