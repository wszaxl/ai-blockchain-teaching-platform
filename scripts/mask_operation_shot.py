# -*- coding: utf-8 -*-
"""对 4.3 操作图（管理控制台）中的链账户名称单元格打码遮挡。"""
import os
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PNG = os.path.join(ROOT, "docs", "教研平台", "assets", "fig4-3_操作图_管理控制台.png")

BOX = (470, 1130, 580, 1180)  # 账户名称列取值单元格（含复制图标）

im = Image.open(PNG).convert("RGB")
bg = im.getpixel((700, 1160))  # 表格行背景色
ImageDraw.Draw(im).rectangle(BOX, fill=bg)
im.save(PNG)
print("masked:", PNG, "bg=", bg)
