# -*- coding: utf-8 -*-
"""标签管理核心模块单元测试。

用法：python kohya_core/tagging/test_tagging.py
返回码 0=通过；1=失败。依赖 installers/tag_dict/danbooru_zh.tsv（离线词典）。
"""
import io
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from kohya_core.tagging import TagDict, default_dict_path, cat_label
from kohya_core.tagging import normalize, translate, complete

FAILED = []


def check(name, fn):
    try:
        fn()
        print("  [ok] %s" % name)
    except Exception as e:
        FAILED.append(name)
        print("  [FAIL] %s: %s" % (name, e))
        import traceback
        traceback.print_exc()


def t_normalize():
    assert normalize.norm_en("Blue Hair") == "blue_hair"
    assert normalize.norm_en("blue-hair") == "blue_hair"
    assert normalize.norm_en("BLUE  HAIR") == "blue_hair"
    assert normalize.norm_en("cat_ears") == "cat_ears"
    assert normalize.has_cjk("蓝色头发") is True
    assert normalize.has_cjk("blue_hair") is False
    assert normalize.norm_en(" 蓝发 ") == "蓝发"
    assert normalize.split_tags("1girl, solo ， blue_hair") == ["1girl", "solo", "blue_hair"]
    assert normalize.split_tags("1girl, 1girl") == ["1girl"]
    assert normalize.join_tags(["a", " b ", ""]) == "a, b"


def t_dict_load():
    d = TagDict()
    assert d.available(), "离线词典文件不存在: %s" % d.path
    t0 = time.time()
    n = len(d)
    dt = time.time() - t0
    print("    载入 %d 条，耗时 %.2fs，路径: %s" % (n, dt, d.path))
    assert n > 150000, "词典词条过少: %d" % n
    assert d.to_zh("1girl") == "单人女性"
    assert d.to_zh("hatsune_miku") == "初音未来"
    assert d.to_zh("armpit") == "腋"
    assert d.to_zh("blue hair") == d.to_zh("blue_hair")  # 空格写法可命中
    row = d.lookup("blue_eyes")
    assert row and row[0] == "蓝瞳" and row[2] > 1000000
    assert cat_label(0) == "通用" and cat_label(4) == "角色"


def t_complete_en():
    d = TagDict()
    r = d.complete_en("blue", limit=30)
    assert r and r[0][0] in ("blue_eyes", "blue_hair"), "应按热度排序: %s" % (r[:3],)
    names = {x[0] for x in r}
    assert "blue_eyes" in names and "blue_sky" in names


def t_zh_reverse():
    d = TagDict()
    r = d.zh_candidates("初音", limit=20)
    assert r and r[0][0] == "hatsune_miku", r[:3]
    r2 = d.zh_candidates("蓝瞳", limit=10)
    assert r2 and r2[0][0] == "blue_eyes", r2[:3]
    r3 = d.zh_candidates("不存在的中文词xx", limit=5)
    assert r3 == []


def t_translate():
    d = TagDict()
    assert translate.to_zh(d, "solo") == "独奏" or translate.to_zh(d, "solo") != "solo"
    lst = translate.translate_tags(d, "1girl, blue_hair, some_unknown_tag_xyz")
    assert len(lst) == 3
    en2zh = dict(lst)
    assert en2zh["1girl"] == "单人女性"
    assert en2zh["blue_hair"] != "blue_hair"
    assert en2zh["some_unknown_tag_xyz"] == "some_unknown_tag_xyz"


def t_user_suggest():
    d = TagDict()
    freq = complete.freq_of([
        {"caption": "1girl, blue_hair"},
        {"caption": "1girl, blue_eyes, solo"},
        {"caption": "blue_hair, solo"},
    ])
    assert freq.get("blue_hair") == 2 and freq.get("1girl") == 2
    r = complete.suggest_en(d, "blue", user_tags=freq, limit=30)
    assert r and r[0][0] == "blue_hair"


def main():
    print("== 标签管理核心模块测试 ==")
    check("normalize 文本规范化", t_normalize)
    check("离线词典加载 + 精确翻译", t_dict_load)
    check("英文前缀补全", t_complete_en)
    check("中文反查联想", t_zh_reverse)
    check("整段标签翻译", t_translate)
    check("数据集频率 + 补全排序", t_user_suggest)
    print("-" * 40)
    if FAILED:
        print("FAIL %d: %s" % (len(FAILED), ", ".join(FAILED)))
        return 1
    print("OK 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
