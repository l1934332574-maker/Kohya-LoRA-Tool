# -*- coding: utf-8 -*-
"""kohya_core：核心逻辑模块包（渐进式拆分）。"""
import os
import sys

def _kit_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KIT_DIR = _kit_dir()
KOHYA_DIR_FILE = os.path.join(KIT_DIR, "kohya_dir.txt")
