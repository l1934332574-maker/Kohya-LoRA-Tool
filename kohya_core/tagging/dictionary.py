# -*- coding: utf-8 -*-
"""离线中英标签词典：懒加载 installers/tag_dict/danbooru_zh.tsv。

数据文件为 4 列 TSV（按英文名升序）：name<TAB>category<TAB>post_count<TAB>cn_name。
内存策略：
  - en2zh / counts / cats：首次查询时整表载入（约 17 万条，几十 ms 级）；
  - 中文反查索引 / 英文前缀有序表：按需构建并缓存，避免白占内存。

查询能力：
  to_zh(name)         英→中 精确翻译（自动规范化：空格/连字符→下划线）
  lookup(name)        返回 (cn, category, post_count) 或 None
  complete_en(prefix) 英文前缀补全（按 Danbooru 热度 post_count 排序）
  zh_candidates(text) 中文反查联想（前缀优先 + 包含匹配，按热度排序）
"""
import os
import sys
import bisect

try:
    from kohya_core import KIT_DIR
except Exception:  # 极早期导入兜底
    KIT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CAT_LABELS = {0: "通用", 1: "画师", 3: "作品", 4: "角色", 5: "元数据"}
_DATA_SUB = os.path.join("installers", "tag_dict", "danbooru_zh.tsv")


def default_dict_path():
    """定位离线词典文件（支持 KOHYA_TAG_DICT 环境变量覆盖，便于测试/自定义词典）。"""
    env = os.environ.get("KOHYA_TAG_DICT")
    if env and os.path.isfile(env):
        return env
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = KIT_DIR
    p = os.path.join(base, _DATA_SUB)
    if not os.path.isfile(p):  # 便携/开发目录运行兜底
        alt = os.path.join(os.getcwd(), _DATA_SUB)
        if os.path.isfile(alt):
            return alt
    return p


def cat_label(cat):
    return CAT_LABELS.get(cat, "标签")


class TagDict(object):
    """离线中英标签词典查询器（懒加载、只读）。"""

    def __init__(self, path=None):
        self.path = path or default_dict_path()
        self.en2zh = {}
        self.counts = {}
        self.cats = {}
        self._names = []
        self._zh_map = None      # cn -> [(post_count, name), ...]（按热度降序）
        self._zh_uniq = None     # 排序后的唯一中文列表（前缀 bisect）
        self._zh_cache = {}
        self._loaded = False

    # ---------- 载入 ----------
    def available(self):
        return os.path.isfile(self.path)

    def row_count(self):
        if not self._loaded:
            return 0
        return len(self.en2zh)

    def _ensure(self):
        if self._loaded:
            return
        if not os.path.isfile(self.path):
            self._loaded = True  # 缺文件时表现为空词典，界面提示由调用方处理
            return
        en2zh, counts, cats = {}, {}, {}
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < 4:
                    continue
                name = parts[0].strip()
                if not name:
                    continue
                cn = parts[3].strip()
                try:
                    cat = int(parts[1])
                except Exception:
                    cat = 0
                try:
                    cnt = int(parts[2])
                except Exception:
                    cnt = 0
                en2zh[name] = cn
                counts[name] = cnt
                cats[name] = cat
        self.en2zh = en2zh
        self.counts = counts
        self.cats = cats
        self._names = sorted(en2zh.keys())
        self._loaded = True

    def _ensure_zh(self):
        self._ensure()
        if self._zh_map is not None:
            return
        zmap = {}
        for name, cn in self.en2zh.items():
            if not cn:
                continue
            zmap.setdefault(cn, []).append((self.counts.get(name, 0), name))
        for cn in zmap:
            zmap[cn].sort(key=lambda kv: (-kv[0], kv[1]))
        self._zh_map = zmap
        self._zh_uniq = sorted(zmap.keys())

    # ---------- 英→中 ----------
    def to_zh(self, name):
        """英→中：精确翻译单个英文标签；未收录返回 None（调用方自行显示原名）。"""
        self._ensure()
        if not name:
            return None
        key = self._norm(name)
        if key in self.en2zh:
            return self.en2zh[key]
        if name in self.en2zh:
            return self.en2zh[name]
        return None

    def lookup(self, name):
        """返回 (cn, category, post_count)；未收录返回 None。"""
        self._ensure()
        if not name:
            return None
        key = self._norm(name)
        if key not in self.en2zh and name not in self.en2zh:
            return None
        k = key if key in self.en2zh else name
        return (self.en2zh[k], self.cats.get(k, 0), self.counts.get(k, 0))

    @staticmethod
    def _norm(name):
        from .normalize import norm_en
        return norm_en(name)

    # ---------- 英文前缀补全 ----------
    def complete_en(self, prefix, limit=30):
        """英文前缀补全：返回 [(name, cn, category, post_count)]，按热度排序，精确前缀最优先。"""
        self._ensure()
        if not self._names:
            return []
        p = self._norm(prefix)
        if not p:
            return []
        lo = bisect.bisect_left(self._names, p)
        cands = []
        exact = None
        n = len(self._names)
        while lo < n and self._names[lo].startswith(p):
            nm = self._names[lo]
            if nm == p:
                exact = nm
            else:
                cands.append(nm)
            lo += 1
            if len(cands) > 600:  # 命中过多时截断，避免卡顿
                break
        if exact is not None:
            cands.insert(0, exact)
        cands.sort(key=lambda nm: (-self.counts.get(nm, 0), nm))
        return [self._row(nm) for nm in cands[:limit]]

    def _row(self, name):
        return (name, self.en2zh.get(name, ""), self.cats.get(name, 0), self.counts.get(name, 0))

    # ---------- 中文反查 ----------
    def zh_candidates(self, text, limit=30, contains=True):
        """中文反查：输入中文，返回 [(name, cn, category, post_count)]。

        前缀命中优先；数量不足时再做包含匹配。结果整体按热度排序。
        """
        self._ensure_zh()
        if not text or not self._zh_map:
            return []
        t = text.strip()
        if not t:
            return []
        cached = self._zh_cache.get(t)
        if cached is not None:
            return cached[:limit]
        uniq = self._zh_uniq
        lo = bisect.bisect_left(uniq, t)
        matched = []          # (cn, count, name)
        seen_cn = set()
        # 1) 前缀命中（顺序天然按拼音? 中文按 Unicode 序，非拼音；仍需热度重排）
        while lo < len(uniq) and uniq[lo].startswith(t):
            cn = uniq[lo]
            seen_cn.add(cn)
            for cnt, nm in self._zh_map[cn]:
                matched.append((cnt, nm))
            lo += 1
            if len(matched) > 800:
                break
        # 2) 包含匹配（前缀不够时补充；单字不做全表包含扫描，避免输入卡顿）
        if contains and len(t) >= 2 and len(matched) < limit * 8:
            extra = []
            for cn in uniq:
                if cn in seen_cn or t not in cn:
                    continue
                seen_cn.add(cn)
                for cnt, nm in self._zh_map[cn][:3]:
                    extra.append((cnt, nm))
                if len(extra) > 800:
                    break
            matched.extend(extra)
        matched.sort(key=lambda kv: (-kv[0], kv[1]))
        out = [self._row(nm) for _, nm in matched[:limit]]
        if len(self._zh_cache) > 256:
            self._zh_cache.clear()
        self._zh_cache[t] = out
        return out

    def __len__(self):
        self._ensure()
        return len(self.en2zh)
