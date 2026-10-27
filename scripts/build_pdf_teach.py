# -*- coding: utf-8 -*-
"""生成《基于AI+区块链的区域协同教研平台》PDF 技术文档（赛题提交用）。"""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, HRFlowable)

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(WS, 'docs', '教研平台', '教研平台-技术文档.pdf')
TA = os.path.join(WS, 'docs', '教研平台')

pdfmetrics.registerFont(TTFont('Sun', r'C:\Windows\Fonts\simsun.ttc', subfontIndex=0))
pdfmetrics.registerFont(TTFont('Hei', r'C:\Windows\Fonts\simhei.ttf'))
registerFontFamily('Sun', normal='Sun', bold='Hei', italic='Sun', boldItalic='Hei')

ACCENT = colors.HexColor('#0F4C81')
MUTED = colors.HexColor('#6B7280')
LINE = colors.HexColor('#D1D5DB')
CODE_BG = colors.HexColor('#F3F4F6')

S_H1 = ParagraphStyle('h1', fontName='Hei', fontSize=15, leading=20, spaceBefore=16, spaceAfter=8, textColor=ACCENT)
S_H2 = ParagraphStyle('h2', fontName='Hei', fontSize=11.5, leading=16, spaceBefore=10, spaceAfter=4)
S_B = ParagraphStyle('b', fontName='Sun', fontSize=9.5, leading=15, wordWrap='CJK')
S_CODE = ParagraphStyle('c', fontName='Sun', fontSize=7.2, leading=9.6, backColor=CODE_BG, borderPadding=6, wordWrap='CJK')
S_CELL = ParagraphStyle('cell', fontName='Sun', fontSize=8.5, leading=12, wordWrap='CJK')
S_CELLH = ParagraphStyle('cellh', fontName='Hei', fontSize=8.5, leading=12)
S_CAP = ParagraphStyle('cap', fontName='Sun', fontSize=8, leading=12, textColor=MUTED, wordWrap='CJK')

def h1(t): return Paragraph(t, S_H1)
def h2(t): return Paragraph(t, S_H2)
def b(t): return Paragraph(t, S_B)
def code(t): return Paragraph(t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br/>'), S_CODE)
def cap(t): return Paragraph(t, S_CAP)

def tbl(rows, widths):
    t = Table([[Paragraph(c, S_CELLH) if i == 0 else Paragraph(c, S_CELL) for c in r] for i, r in enumerate(rows)],
              colWidths=widths, hAlign='CENTER')
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), CODE_BG),
        ('GRID', (0, 0), (-1, -1), 0.5, LINE),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t

def fig(name, width):
    p = os.path.join(TA, 'assets', name)
    if os.path.exists(p):
        from PIL import Image as PILImage
        im = PILImage.open(p)
        w, h = im.size
        hgt = width * h / w
        return Image(p, width=width, height=hgt)
    return Paragraph('（缺图：%s）' % name, S_B)

def contract_lines():
    p = os.path.join(WS, 'contracts', 'TeachingTrace.sol')
    src = open(p, encoding='utf-8').read().split('\n')
    out = []
    grab = False
    for ln in src:
        if 'function registerArtifact' in ln: grab = True
        if grab:
            out.append(ln)
        if grab and 'emit LOG_STRING' in ln:
            out.append('        // ……（含 recordActivity / getCreditFor 与学分折算逻辑，全文见 contracts/TeachingTrace.sol）')
            break
    return '\n'.join(out[:46])

story = []
# 封面
story.append(Spacer(1, 70 * mm))
story.append(Paragraph('U 型区域协同教研 · 区块链 + AI 技术创新组', ParagraphStyle('k', fontName='Hei', fontSize=11, leading=15, textColor=MUTED, alignment=TA_CENTER, spaceAfter=8)))
story.append(Paragraph('基于 AI+区块链的区域协同教研平台', ParagraphStyle('hero', fontName='Hei', fontSize=26, leading=36, textColor=ACCENT, alignment=TA_CENTER, spaceAfter=6)))
story.append(Paragraph('———— 技术文档（PDF 提交版）————', ParagraphStyle('st', fontName='Sun', fontSize=13, leading=18, alignment=TA_CENTER, spaceAfter=36)))
story.append(HRFlowable(width='58%', thickness=1.1, color=ACCENT, spaceAfter=14))
story.append(Paragraph('院校名称：＿＿＿＿＿＿　　｜　　团队名称：＿＿＿＿＿＿　　｜　　2026 年 10 月', ParagraphStyle('mt', fontName='Sun', fontSize=10.5, leading=15, alignment=TA_CENTER, textColor=MUTED, spaceAfter=30)))
story.append(Paragraph('本平台面向区域内跨校协同教研场景：AI 层提供资源推荐、会议纪要、教学分析与教师画像；'
                      '区块链联盟链层提供教研成果确权、过程留痕、贡献统计与跨校学分互认。'
                      '全部链上能力已在蚂蚁链开放联盟链真实实现并留有可复验的交易凭证。',
                      ParagraphStyle('sm', fontName='Sun', fontSize=10, leading=17, alignment=TA_CENTER)))
story.append(PageBreak())

story.append(h1('1. 业务痛点与行业发展趋势'))
story.append(b('传统区域协同教研存在四大痛点：<b>①</b> 跨校教研资源孤岛、成果版权归属不明，优质资源易被盗用；'
              '<b>②</b> 教研活动过程记录依赖人工签到与纸质台账，打卡造假、代签难以杜绝，教师贡献无法量化；'
              '<b>③</b> 各校学分认定口径不一，跨校学分互认缺失；'
              '<b>④</b> 教研资料分散、缺乏智能分析工具，选题与质量评估依赖经验。'))
story.append(b('被广泛认可的行业趋势是"AI 提效 + 区块链可信"双轮驱动：AI 解决"找得到、理得清、评得准"，'
              '区块链解决"确得了权、留得了痕、认得了分"。本方案正是这一趋势在基础教育教研场景的落地。'))
story.append(h1('2. 解决方案：AI 层 + 区块链联盟链层双层架构'))
story.append(tbl([['层', '能力', '解决痛点', '实现与边界'],
                  ['AI 层', '资源智能推荐 / 会议纪要 / 教学数据分析 / 教师画像', '① 查找效率低；④ 分析手段落后',
                   '模拟实现 + 接口预留（本环境无 AI 服务），AI 摘要哈希后送链存证'],
                  ['区块链层', '成果上链确权 / 参与留痕与贡献统计 / 跨校学分互认 / 全流程审计追溯', '① 版权；② 真实性；③ 学分壁垒',
                   '真实实现并上链（Solidity 合约 + REST 通道），见第 5 节凭证']],
                 [52, 132, 120, 166]))
story.append(h2('2.1 关键技术'))
story.append(b('哈希指纹存证（SHA-256）、时间戳、联盟链共识、Solidity 0.4.x 智能合约、'
              'KMS 密钥托管与 REST 平台代签、miniappinfo 展示格式、交易哈希 prevHash 级联链。'))
story.append(h2('2.2 区块链应用点（逐条对应案例文档的四个痛点）'))
story.append(b('① 教研资源确权：成果文件哈希 + 署名主体 + 学校上链；② 活动过程留痕：参与与贡献分钟数上链、非法输入照常留痕；'
              '③ 学分互认：合约内统一 "分钟 × 2" 折算口径、按教师累计；④ 审计追溯：每一笔都有交易哈希、按活动/成果主键可查。'))
story.append(h1('3. 区块链网络拓扑与业务流程（三种图）'))
story.append(fig('fig1_网络拓扑图.png', 400))
story.append(cap('图 1　区块链网络拓扑图：主网络（开放联盟链 a00e36c5，平台托管节点）+ 通道（租户 LXHOXRFH/AccessKey）+ 各校接入端。'))
story.append(Spacer(1, 8))
story.append(fig('fig2_业务流程图.png', 410))
story.append(cap('图 2　创新业务流程图：多方主体 → AI 处理 → 哈希存证 → 联盟链同步 → 学分自动计算与审计追溯。'))
story.append(Spacer(1, 8))
story.append(fig('fig3_上链数据分析图.png', 260))
story.append(cap('图 3　上链数据分析图：教研成果（Artifact）与教研活动（Activity）两套上链数据字段。'))
story.append(h1('4. 上链数据设计'))
story.append(tbl([['教研成果 Artifact', '类型', '含义'],
                  ['artifactId', 'string', '成果编号（业务主键，全链唯一）'],
                  ['title', 'string', '标题'],
                  ['author', 'string', '作者（署名权主体）'],
                  ['school', 'string', '确权归属校'],
                  ['fileHash', 'string', 'SHA-256(成果文件原文)']],
                 [120, 60, 290]))
story.append(Spacer(1, 4))
story.append(tbl([['教研活动 Activity', '类型', '含义'],
                  ['activityId', 'string', '活动编号'],
                  ['teacherId', 'string', '教师（跨校通用标识）'],
                  ['school', 'string', '所属学校'],
                  ['effortMinutes', 'string', '贡献分钟（×2 折算学分，非法输入折算 0 学分但照常留痕）']],
                 [120, 60, 290]))
story.append(h1('5. 智能合约（TeachingTrace.sol）'))
story.append(b('接口：<b>registerArtifact(5×string)</b> 成果确权、<b>recordActivity(4×string)</b> 活动留痕+学分折算、'
              '<b>getCreditFor(string)</b> 学分查询（本地只读）。每个写操作 emit LOG_STRING(miniappinfo JSON)，供浏览器与小程序展示。'
              '接口文档：docs/教研平台/02-智能合约接口文档.md。关键代码节选（注释与代码严格对应）：'))
story.append(code(contract_lines()))
story.append(h1('6. 真实运行凭证（SDK 调用，开放联盟链 a00e36c5）'))
story.append(tbl([['动作', '交易哈希'],
                  ['合约部署 teaching_platform_v1', 'ceeaba86f9ed2451379182dbc5263597019e0f2b60e7a155d615f44e6bd956b9'],
                  ['成果确权 registerArtifact', '48ba4912c6af94f00007fb1b106503857e96b73acc37580eac23f71ddcecc5b3'],
                  ['活动记录 recordActivity', '7b844056dbd173c64f25c507ec070e72ba8dca1fc56e49d716309b1a8ad4e8e6'],
                  ['学分查询 getCreditFor("陈以宁")', 'outRes = ["180"]（90 分钟 × 2 = 180，本地只读、不耗 gas）']],
                 [180, 290]))
story.append(b('调用工具：tools/TeachFlowTool.java（deploy / register / activity / credit 四子命令），'
              '全程原始输出见 docs/教研平台/07-过程实录与视频拍摄脚本.md 与 build/probe/re/。'))
story.append(h1('7. 提交资料说明'))
story.append(b('<b>方案 PPT</b>：随附《教研平台-方案汇报.pptx》提纲版，可在其中按节渲染本技术文档内容。'))
story.append(b('<b>PDF 技术文档</b>：即本文档，覆盖赛题全部要求（痛点/趋势/解决方案/三图/上链数据设计/智能合约与接口文档）。'))
story.append(b('<b>视频</b>：联盟链搭建过程、智能合约运行、SDK 运行三段视频的分镜脚本与口播稿见过程实录文档 2.1~2.3 节，'
              '由团队按脚本录屏（本机无录屏环境）。其中"搭建过程"以平台控制台配置 + 合约部署实录替代，解释口径见实录文档。'))
story.append(Spacer(1, 6))
story.append(HRFlowable(width='100%', thickness=0.7, color=LINE, spaceAfter=4))
story.append(cap('本文档全部交易哈希与数字来自真实链上查询（存证文件 build/probe/re/），未作任何加工。'))

doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=22 * mm, rightMargin=22 * mm,
                        topMargin=18 * mm, bottomMargin=18 * mm,
                        title='基于AI+区块链的区域协同教研平台·技术文档',
                        author='技术组')
doc.build(story)
print('PDF 已生成:', OUT, os.path.getsize(OUT), '字节')