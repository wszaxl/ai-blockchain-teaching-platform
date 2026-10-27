# -*- coding: utf-8 -*-
"""从提交物视频抽取的真实平台页面帧中裁掉浏览器标签条，产出 4.3 操作图。"""
import os
from PIL import Image

SRC = os.path.join(os.environ["TEMP"], "frames")
DST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "docs", "教研平台", "assets")

JOBS = [
    ("v3_020.png", "fig4-3_操作图_管理控制台.png"),
    ("v2_004.png", "fig4-4_操作图_链浏览器洞察看板.png"),
]

for name, out in JOBS:
    im = Image.open(os.path.join(SRC, name))
    w, h = im.size
    top = int(h * 0.043)  # 去掉标签条，保留地址栏作为真实平台 URL 证据
    im.crop((0, top, w, h)).save(os.path.join(DST, out))
    print(out, im.size, "->", (w, h - top))
