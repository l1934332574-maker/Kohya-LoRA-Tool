# -*- coding: utf-8 -*-
"""标签管理中英词典 / 翻译 / 补全核心（纯 Python，无 UI 依赖）。

kohya_core.tagging
├─ dictionary : 离线词典加载与查询（en→zh / zh→en / 英文前缀补全 / 中文联想）
├─ translate  : 单条标签 / 整段标签文本翻译
├─ complete   : 补全建议（离线词典 + 数据集已有标签）
└─ normalize  : 标签文本规范化 / 拆分 / 拼接
"""
from .dictionary import TagDict, default_dict_path, cat_label
from . import normalize, translate, complete

__all__ = [
    "TagDict", "default_dict_path", "cat_label",
    "normalize", "translate", "complete",
]
