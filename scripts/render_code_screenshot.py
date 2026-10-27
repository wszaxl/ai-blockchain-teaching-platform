# -*- coding: utf-8 -*-
"""Render the project's REAL core source code as dark-themed (VS Code Dark+)
syntax-highlighted screenshot PNGs, mirroring the reference PDF's code-shot style.

Code is extracted VERBATIM from the repository so the screenshot always matches
the actual implementation:
  - contracts/TeachingTrace.sol  (Solidity, on-chain data structures + frozen-ABI entries)
"""
import os
import re
from PIL import Image, ImageDraw, ImageFont

ROOT = "E:/HuaweiMoveData/Users/HUAWEI/Desktop/基于AL+区域协同教研"
SOL = os.path.join(ROOT, "contracts", "TeachingTrace.sol")
OUTDIR = os.path.join(ROOT, "docs", "教研平台", "assets")

MONO = "C:/Windows/Fonts/consola.ttf"
CJK = "C:/Windows/Fonts/msyh.ttc"

FONT_SIZE = 20
LINE_H = 28
PAD_X = 30
PAD_Y = 22

BG = (30, 30, 30)
C_COMMENT = (106, 153, 85)
C_STRING = (206, 145, 120)
C_KEYWORD = (86, 156, 214)
C_TYPE = (78, 201, 176)
C_NUM = (181, 206, 168)
C_FUNC = (220, 220, 170)
C_PLAIN = (212, 212, 212)
C_CTRL = (197, 134, 192)

KEYWORDS = {
    "pragma", "solidity", "contract", "library", "struct", "function", "event",
    "emit", "using", "for", "mapping", "memory", "storage", "public", "private",
    "internal", "pure", "view", "returns", "return", "new", "if", "else",
    "require", "assert", "assembly", "let", "while", "import", "is",
}
TYPES = {"string", "uint", "uint8", "int", "bytes", "byte", "bool", "address",
         "Artifact", "Record", "slice", "strings"}
CTRL = {"if", "else", "for", "while", "return", "returns"}

TOKEN_RE = re.compile(
    r'(?P<comment>//[^\n]*|/\*.*?\*/)'
    r'|(?P<string>"(?:[^"\\]|\\.)*")'
    r'|(?P<num>\b\d+\b)'
    r'|(?P<ident>[A-Za-z_][A-Za-z0-9_]*)'
    r'|(?P<other>.)',
    re.S,
)

_f_mono = ImageFont.truetype(MONO, FONT_SIZE)
_f_cjk = ImageFont.truetype(CJK, FONT_SIZE)
COL_W = _f_mono.getlength("0")


def is_cjk(ch):
    o = ord(ch)
    return (0x4E00 <= o <= 0x9FFF) or (0x3000 <= o <= 0x303F) or \
           (0xFF00 <= o <= 0xFFEF) or (0x2018 <= o <= 0x201D)


def classify(ident, next_ch):
    if ident in CTRL:
        return C_CTRL
    if ident in KEYWORDS:
        return C_KEYWORD
    if ident in TYPES:
        return C_TYPE
    if next_ch == "(":
        return C_FUNC
    return C_PLAIN


def tokenize_line(line):
    spans = []
    for m in TOKEN_RE.finditer(line):
        kind = m.lastgroup
        text = m.group()
        if kind == "comment":
            color = C_COMMENT
        elif kind == "string":
            color = C_STRING
        elif kind == "num":
            color = C_NUM
        elif kind == "ident":
            color = classify(text, line[m.end():m.end() + 1])
        else:
            color = C_PLAIN
        spans.append((text, color))
    return spans


def line_cols(line):
    return sum(2 if is_cjk(ch) else 1 for ch in line)


def render(lines, out_path):
    max_cols = max((line_cols(l) for l in lines), default=1)
    width = int(PAD_X * 2 + max_cols * COL_W) + 16
    height = int(PAD_Y * 2 + len(lines) * LINE_H)
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    y = PAD_Y
    for line in lines:
        x = PAD_X
        for text, color in tokenize_line(line):
            for ch in text:
                f = _f_cjk if is_cjk(ch) else _f_mono
                d.text((x, y), ch, font=f, fill=color)
                x += COL_W * (2 if is_cjk(ch) else 1)
        y += LINE_H
    img.save(out_path)
    return out_path


def slice_lines(path, ranges):
    with open(path, encoding="utf-8") as fh:
        src = fh.read().split("\n")
    out = []
    for a, b in ranges:
        out.extend(src[a - 1:b])
        out.append("")
    while out and out[-1] == "":
        out.pop()
    return out


if __name__ == "__main__":
    os.makedirs(OUTDIR, exist_ok=True)
    # 图 1：链上数据结构（contract 声明 / 事件 / struct / mapping），逐字取自 TeachingTrace.sol
    structs = slice_lines(SOL, [(86, 122)])
    p1 = render(structs, os.path.join(OUTDIR, "fig4_代码核心截图_1.png"))
    # 图 2：三个冻结 ABI 入口（registerArtifact / recordActivity / getCreditFor），逐字取自 TeachingTrace.sol
    entries = slice_lines(SOL, [(253, 268), (283, 302), (311, 314)])
    p2 = render(entries, os.path.join(OUTDIR, "fig4_代码核心截图_2.png"))
    print("saved:", p1)
    print("saved:", p2)
    print("img1 lines:", len(structs), " img2 lines:", len(entries))
