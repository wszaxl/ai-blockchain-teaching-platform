# -*- coding: utf-8 -*-
"""
三张图生成脚本（依据 docs/教研平台/01-产品设计与实现方案.md 第 5.1/5.2/5.3 节节点表与连线表）。

输出：docs/教研平台/assets/fig1_网络拓扑图.png / fig2_业务流程图.png / fig3_上链数据分析图.png
要求：白底、浅色填充+深色边框（低饱和度）、连线不穿节点（脚本内置几何自检）、
     中文字体 C:\\Windows\\Fonts\\simhei.ttf、200dpi、字号保证缩放到 A4 宽度仍可读。
用法：python tools\\make_charts.py   （成功退出码 0；几何自检有违规则退出码 2）
"""
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "docs", "教研平台", "assets")
FONT_PATH = r"C:\Windows\Fonts\simhei.ttf"
DPI = 200

if not os.path.exists(FONT_PATH):
    sys.exit("找不到中文字体 %s" % FONT_PATH)
font_manager.fontManager.addfont(FONT_PATH)
plt.rcParams["font.family"] = "SimHei"
plt.rcParams["axes.unicode_minus"] = False
os.makedirs(OUT_DIR, exist_ok=True)

# ---------------------------------------------------------------- 配色（低饱和度）
C_SOLID = "#37474F"   # 实线
C_DASH = "#5A6472"    # 虚线
C_BOLD = "#2E4D6E"    # 粗实线（REST 通道 / 链通道）
C_DOT = "#6E7680"     # 点线
C_TXT = "#111111"
C_SUB = "#4A4A4A"

F_CLIENT = "#EAE3F2"  # 从网络
E_CLIENT = "#4B3869"
F_APP = "#FFF1CC"     # 应用层
E_APP = "#7F6000"
F_ID = "#E4EFDA"      # 身份/接入层
E_ID = "#4C6937"
F_CHAIN = "#DCE6F1"   # 链层
E_CHAIN = "#2E4D6E"
F_VERIFY = "#FCE8DB"  # 验证侧
E_VERIFY = "#833C00"
F_BAND = "#F7F8FA"    # 层带
E_BAND = "#D6DADE"

# ---------------------------------------------------------------- 几何基础件
def px(pts):
    xs, ys = zip(*pts)
    return xs, ys


def box(ax, cx, cy, w, h, fc, ec, lw=1.4, r=0.14, zorder=5, ls="-"):
    p = FancyBboxPatch((cx - w / 2, cy - h / 2), w, h,
                       boxstyle="round,pad=0,rounding_size=%.3f" % r,
                       fc=fc, ec=ec, lw=lw, linestyle=ls, zorder=zorder)
    ax.add_patch(p)
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def rect(ax, x0, y0, w, h, fc, ec, lw=1.2, r=0.10, zorder=5, ls="-"):
    p = FancyBboxPatch((x0, y0), w, h,
                       boxstyle="round,pad=0,rounding_size=%.3f" % r,
                       fc=fc, ec=ec, lw=lw, linestyle=ls, zorder=zorder)
    ax.add_patch(p)
    return (x0, y0, x0 + w, y0 + h)


def _pt_along(p0, p1, frac):
    p0 = np.asarray(p0, float)
    p1 = np.asarray(p1, float)
    return p0 + (p1 - p0) * frac


def _head(ax, a, b, color, lw=1.2, ls="-"):
    ax.annotate("", xy=tuple(b), xytext=tuple(a),
                arrowprops=dict(arrowstyle="-|>", color=color, lw=lw,
                                linestyle=ls, shrinkA=0, shrinkB=0),
                zorder=6)


def poly(ax, pts, color=C_SOLID, lw=1.6, ls="-", both=False, zorder=3):
    """画折线；both=True 在两端加相向箭头（双向），否则末端单箭头。"""
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, lw=lw, ls=ls, zorder=zorder,
            solid_capstyle="round", solid_joinstyle="round")
    p0, p1 = np.asarray(pts[-2], float), np.asarray(pts[-1], float)
    L = np.linalg.norm(p1 - p0)
    f = min(0.12, max(0.25 / L, 0.02))
    _head(ax, _pt_along(p0, p1, 1 - f), p1, color=color, lw=max(1.1, lw - 0.4), ls=ls)
    if both:
        q0, q1 = np.asarray(pts[0], float), np.asarray(pts[1], float)
        LL = np.linalg.norm(q1 - q0)
        ff = min(0.12, max(0.25 / LL, 0.02))
        _head(ax, _pt_along(q0, q1, ff), q0, color=color, lw=max(1.1, lw - 0.4), ls=ls)


def node(ax, cx, cy, w, h, fill, edge, t1, t2=None, s1=9.4, s2=7.9, tcol=None):
    r = box(ax, cx, cy, w, h, fill, edge)
    c1 = tcol if tcol else edge
    if t2:
        ax.text(cx, cy + 0.15, t1, ha="center", va="center", fontsize=s1,
                fontweight="bold", color=c1, zorder=6)
        ax.text(cx, cy - 0.22, t2, ha="center", va="center", fontsize=s2,
                color=C_SUB, zorder=6)
    else:
        ax.text(cx, cy, t1, ha="center", va="center", fontsize=s1,
                fontweight="bold", color=c1, zorder=6)
    return r


# ---------------------------------------------------------------- 几何自检（连线不穿节点）
def check_overlap(nodes, edges, allowed):
    """edges: {eid: [path, ...]}；nodes: [(nid, x0, y0, x1, y1)]；
    逐段采样，点落入节点内部（边界内缩 0.02）即违规；allowed 中的 (eid,nid) 为
    文档明确要求"穿经"的通道（图1 独立验证虚线穿经 N5、N2），予以豁免。"""
    viol = []
    n_seg = 0
    for eid, paths in edges.items():
        for path in paths:
            for i in range(len(path) - 1):
                n_seg += 1
                p0 = np.asarray(path[i], float)
                p1 = np.asarray(path[i + 1], float)
                ts = np.linspace(0.0, 1.0, 300)
                pts = p0[None, :] * (1 - ts[:, None]) + p1[None, :] * ts[:, None]
                for nid, nx0, ny0, nx1, ny1 in nodes:
                    if (eid, nid) in allowed:
                        continue
                    eps = 0.02
                    m = ((pts[:, 0] > nx0 + eps) & (pts[:, 0] < nx1 - eps) &
                         (pts[:, 1] > ny0 + eps) & (pts[:, 1] < ny1 - eps))
                    if m.any():
                        viol.append((eid, nid))
    return viol, n_seg


def finish(fig, path, name, n_nodes, n_edges, viol, n_seg):
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)
    size = os.path.getsize(path)
    status = ("自检通过" if len(viol) == 0 else "自检违规=" + str(viol))
    print("[%s] %s  节点 %d · 连线 %d · 抽查线段 %d · %s · %.0f KB"
          % (name, os.path.basename(path), n_nodes, n_edges, n_seg, status, size / 1024))
    return viol


def summary(name, n_nodes, n_edges, desc):
    print("    报告口径：%s -> 节点数 %d，连线数 %d（%s）" % (name, n_nodes, n_edges, desc))


# ---------------------------------------------------------------- 图 1 网络拓扑图
def fig1():
    fig = plt.figure(figsize=(9, 7.4), facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 14.3)
    ax.set_ylim(0, 11.7)
    ax.axis("off")
    ax.text(0.15, 11.45, "图 1  区块链网络拓扑图（主网络 / 从网络 / 节点 / 通道）",
            fontsize=13.5, fontweight="bold", color=C_TXT, ha="left", va="center")

    # 层带
    bands = [((0.06, 9.55, 10.89, 1.4), "从网络", 10.25),
             ((0.06, 6.85, 10.89, 1.6), "应用层", 7.65),
             ((0.06, 4.25, 10.89, 1.6), "身份/接入层", 5.05),
             ((0.06, 1.95, 6.79, 1.8), "链层（主网络）", 2.65)]
    for (x0, y0, w, h), name, yc in bands:
        rect(ax, x0, y0, w, h, F_BAND, E_BAND, lw=0.7, r=0.04, zorder=1)
        ax.text(0.09, yc, name, rotation=90, ha="center", va="center",
                fontsize=8.8, color="#707070", fontweight="bold", zorder=2)

    # 节点
    nodes = [
        ("N1", 2.1, 2.15, 6.7, 3.15),
        ("N2", 2.95, 4.575, 5.85, 5.525),
        ("N3", 0.25, 4.575, 2.75, 5.525),
        ("N4", 6.75, 4.575, 9.45, 5.525),
        ("N5", 2.2, 7.15, 6.6, 8.15),
        ("N6", 0.55, 9.875, 2.45, 10.825),
        ("N7", 2.95, 9.875, 4.85, 10.825),
        ("N8", 5.35, 9.875, 7.25, 10.825),
        ("N9", 7.85, 9.875, 10.85, 10.825),
        ("N10", 7.9, 2.375, 10.9, 3.325),
    ]
    node(ax, 1.5, 10.35, 1.9, 0.95, F_CLIENT, E_CLIENT, "N6 学校 A", "教师 · 教研员端")
    node(ax, 3.9, 10.35, 1.9, 0.95, F_CLIENT, E_CLIENT, "N7 学校 B", "教师 · 教研员端")
    node(ax, 6.3, 10.35, 1.9, 0.95, F_CLIENT, E_CLIENT, "N8 学校 C", "教师 · 教研员端")
    node(ax, 9.35, 10.35, 3.0, 0.95, F_CLIENT, E_CLIENT, "N9 教育主管部门 / 教育局", "审计端 · 只读")
    node(ax, 4.4, 7.65, 4.4, 1.0, F_APP, E_APP, "N5 教研平台后端", "（AI 层 + 区块链接入层）")
    node(ax, 1.5, 5.05, 2.5, 0.95, F_ID, E_ID, "N3 链上账户（托管·名称打码）", "+ KMS 代签（托管）")
    node(ax, 4.4, 5.05, 2.9, 0.95, F_ID, E_ID, "N2 BaaS REST 网关", "rest.baas.alipay.com")
    node(ax, 8.1, 5.05, 2.7, 0.95, F_ID, E_ID, "N4 平台租户凭据", "accessId + access.key")
    node(ax, 4.4, 2.65, 4.6, 1.0, F_CHAIN, E_CHAIN, "N1 蚂蚁链开放联盟链", "a00e36c5（主网络）")
    node(ax, 9.4, 2.85, 3.0, 0.95, F_VERIFY, E_VERIFY, "N10 链上浏览器", "区块链小程序")
    ax.text(9.4, 3.52, "验证侧", ha="center", va="center", fontsize=8.2,
            color="#8A8A8A", zorder=6)

    # 连线
    E = {}
    E["E1"] = [[(1.5, 9.875), (1.5, 8.8), (2.55, 8.8), (2.55, 8.15)]]
    E["E2"] = [[(3.9, 9.875), (3.9, 8.15)]]
    E["E3"] = [[(6.3, 9.875), (6.3, 8.9), (5.5, 8.9), (5.5, 8.15)]]
    E["E4"] = [[(9.35, 9.875), (9.35, 8.55), (6.5, 8.55), (6.5, 8.15)]]
    E["E5"] = [[(3.4, 7.15), (3.4, 6.6), (1.4, 6.6), (1.4, 5.525)]]
    E["E6"] = [[(5.6, 7.15), (5.6, 6.6), (8.1, 6.6), (8.1, 5.525)]]
    E["E7"] = [[(4.4, 7.15), (4.4, 5.525)]]
    E["E8"] = [[(4.4, 4.575), (4.4, 3.15)]]
    E["E9"] = [[(6.7, 2.65), (7.9, 2.85)]]
    E["E10"] = [[(0.85, 9.875), (0.85, 8.3)], [(2.95, 9.875), (2.95, 8.3)],
                [(5.4, 9.875), (5.4, 8.3)], [(10.6, 9.875), (10.6, 8.3)],
                [(0.85, 8.3), (10.6, 8.3)], [(5.7, 8.3), (5.7, 3.15)]]
    for k in ("E1", "E2", "E3", "E4"):
        poly(ax, E[k][0], C_SOLID, 1.6, "-", both=True)
    poly(ax, E["E5"][0], C_DASH, 1.5, (0, (5, 3)))
    poly(ax, E["E6"][0], C_DASH, 1.5, (0, (5, 3)))
    poly(ax, E["E7"][0], C_BOLD, 3.0, "-", both=True)
    poly(ax, E["E8"][0], C_BOLD, 3.0, "-", both=True)
    poly(ax, E["E9"][0], C_DOT, 1.5, (0, (1, 2)))
    for pth in E["E10"]:
        poly(ax, pth, C_DOT, 1.5, (0, (1, 2)), both=False)

    # 连线标注
    ax.text(2.2, 8.97, "业务接口", ha="center", va="center", fontsize=8.0, color=C_SUB, zorder=4)
    ax.text(7.9, 8.68, "审计查询（双向）", ha="center", va="center", fontsize=8.0, color=C_SUB, zorder=4)
    ax.text(2.35, 6.75, "通道 A：应用→身份", ha="center", va="center", fontsize=8.0, color=C_SUB, zorder=4)
    ax.text(6.9, 6.75, "握手签名", ha="center", va="center", fontsize=8.0, color=C_SUB, zorder=4)
    ax.text(4.2, 6.10, "通道 B：REST 通道", ha="right", va="center", fontsize=8.0,
            color=C_BOLD, zorder=4)
    ax.text(4.2, 4.10, "通道 C：链通道", ha="right", va="center", fontsize=8.0,
            color=C_BOLD, zorder=4)
    ax.text(7.3, 3.38, "miniappinfo 渲染查看", ha="center", va="bottom",
            fontsize=8.0, color=C_SUB, zorder=4)
    ax.text(5.98, 4.05, "查询（txHash 独立验证）", ha="left", va="center",
            fontsize=8.4, color="#833C00", zorder=4)
    ax.text(5.98, 3.72, "各校同路径 · 不信任平台库", ha="left", va="center",
            fontsize=8.0, color="#833C00", zorder=4)

    # 要点标注框（图例说明列）
    def legend_box(cx, cy, w, h, t, lines, tcol):
        rect(ax, cx - w / 2, cy - h / 2, w, h, "white", "#9AA0A8", lw=0.9, r=0.06, zorder=5)
        ax.text(cx, cy + h / 2 - 0.32, t, ha="center", va="center", fontsize=8.8,
                fontweight="bold", color=tcol, zorder=6)
        for i, ln in enumerate(lines):
            ax.text(cx, cy + h / 2 - 0.62 - i * 0.34, ln, ha="center", va="center",
                    fontsize=7.9, color="#3A3A3A", zorder=6)

    legend_box(12.5, 9.1, 2.85, 2.55, "主网络",
               ["开放联盟链 a00e36c5（平台托管）", "共识/记账节点对内不公开",
                "团队不持有任何链节点", "体验链 4 节点不画入（无对应）"], E_CHAIN)
    legend_box(12.5, 5.3, 2.85, 1.85, "从网络",
               ["各校 + 教育局", "组成的应用接入网络", "各端均为验证客户端"], E_CLIENT)
    legend_box(12.5, 1.85, 2.85, 1.85, "通道（同网关不同 method）",
               ["① 业务 HTTPS", "② 存证 DEPOSIT", "③ 合约 DEPLOY / CALL"], E_ID)

    ax.text(0.3, 0.38, "注：图上仅画可验证实况——物理共识节点对租户不公开（不画假节点）；"
                       "历史体验链 4 节点与 a00e36c5 无可验证对应关系，不画入。",
            ha="left", va="center", fontsize=7.8, color="#777777", zorder=2)

    allowed = {("E10", "N5"), ("E10", "N2")}   # 文档明确要求穿经 N5/N2
    viol, nseg = check_overlap(nodes, E, allowed)
    path = os.path.join(OUT_DIR, "fig1_网络拓扑图.png")
    finish(fig, path, "图1", 10, 10, viol, nseg)
    summary("图1", 10, 10, "节点表 10 行；连线表展开：N6/N7/N8→N5 各 1 条、N9→N5、"
            "通道 A、握手、通道 B、通道 C、N1→N10 渲染、N6/N7/N8/N9⇢N1 独立验证径（含 stubs/总线）")
    return viol


# ---------------------------------------------------------------- 图 2 业务流程图
def fig2():
    fig = plt.figure(figsize=(9, 8.2), facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 11.3)
    ax.set_ylim(0, 10.35)
    ax.axis("off")
    ax.text(0.6, 9.98, "图 2  创新业务流程图（多校教师 → 教研活动 → AI 处理 → 上链 → 学分 → 审计）",
            fontsize=13.5, fontweight="bold", color=C_TXT, ha="left", va="center")

    lanes = [((0.25, 7.1, 10.3, 2.2), "教师端", 8.95, "#F2EEFA", "#C9C0DC", E_CLIENT),
             ((0.25, 4.85, 10.3, 2.15), "AI 层", 6.62, "#FDF6E4", "#E0D5AE", E_APP),
             ((0.25, 1.95, 10.3, 2.8), "区块链层", 4.42, "#EDF3F9", "#B9CDE3", E_CHAIN),
             ((0.25, 0.35, 10.3, 1.55), "主管端", 1.60, "#FDF1E7", "#E2C8AA", E_VERIFY)]
    for (x0, y0, w, h), name, yl, fc, ec, tc in lanes:
        rect(ax, x0, y0, w, h, fc, ec, lw=0.8, r=0.05, zorder=1)
        ax.text(0.55, yl, name, ha="left", va="center", fontsize=10.5,
                fontweight="bold", color=tc, zorder=2)

    def step(cx, cy, w, h, fill, edge, t, sub, tag, s1=9.3, s2=8.0):
        r = box(ax, cx, cy, w, h, fill, edge, r=0.10, lw=1.4)
        ax.text(cx, cy + h / 2 - 0.34, t, ha="center", va="center", fontsize=s1,
                fontweight="bold", color=edge, zorder=6)
        lines = sub.split("\n")
        if len(lines) == 1:
            ax.text(cx, cy - 0.16, sub, ha="center", va="center", fontsize=s2,
                    color=C_SUB, zorder=6)
        else:
            for i, ln in enumerate(lines):
                ax.text(cx, cy - 0.08 - i * 0.30, ln, ha="center", va="center",
                        fontsize=s2, color=C_SUB, zorder=6)
        ax.text(cx + w / 2 - 0.12, cy + h / 2 - 0.18, tag, ha="right", va="center",
                fontsize=7.4, color="#8A8A8A", zorder=6)
        return r

    N = {}
    N["S1"] = step(3.45, 8.2, 5.4, 0.9, F_CLIENT, E_CLIENT,
                   "S1  多校教师/教研员/教育局发起教研",
                   "上传资源 · 发起活动 · 参会", "案例①")
    N["S2"] = step(3.45, 6.35, 5.4, 0.8, F_APP, E_APP,
                   "S2  AI 层处理（本机模拟件）",
                   "智能推荐 · 会议纪要生成 · 教学诊断 · 贡献统计", "案例②")
    N["S3"] = step(3.45, 5.35, 5.4, 0.8, F_APP, E_APP,
                   "S3  平台归约：SHA-256 摘要",
                   "纪要/诊断 → fileHash；发言时长 → effortMinutes", "案例②→③")
    N["S4"] = step(3.45, 4.05, 5.4, 0.95, F_CHAIN, E_CHAIN,
                   "S4  上链存证（两笔合约交易）",
                   "registerArtifact + recordActivity 两笔合约交易\n"
                   "加盖链上时间戳 · 取得 txHash · LOG_STRING(miniappinfo)", "案例③")
    N["S5"] = step(3.45, 3.15, 5.4, 0.8, F_CHAIN, E_CHAIN,
                   "S5  联盟链共识确认",
                   "KMS 代签打出 · 回执可查 · 各校节点/浏览器按 txHash 验证与渲染", "案例④")
    N["S6"] = step(3.45, 2.35, 5.4, 0.7, F_CHAIN, E_CHAIN,
                   "S6  学分计算与互认",
                   "合约内 minutes×2 折算累加 · getCreditFor 读同一学分", "案例⑤")
    N["S7"] = step(8.5, 1.1, 3.2, 1.0, F_VERIFY, E_VERIFY,
                   "S7  教育局审计追溯",
                   "按 txHash 查回执/原文 · 按教师查学分\n按活动查活动记录", "案例⑤")
    box(ax, 8.55, 6.35, 2.0, 0.8, "white", E_APP, lw=1.2, r=0.10, ls=(0, (5, 3)))
    ax.text(8.55, 6.55, "S2'  教师画像构建", ha="center", va="center", fontsize=8.8,
            fontweight="bold", color=E_APP, zorder=6)
    ax.text(8.55, 6.16, "回流：读链上数据", ha="center", va="center", fontsize=7.8,
            color=C_SUB, zorder=6)

    E = {}
    E["S1-S2"] = [[(3.45, 7.75), (3.45, 6.75)]]
    E["S2-S3"] = [[(3.45, 5.95), (3.45, 5.75)]]
    E["S3-S4"] = [[(3.45, 4.95), (3.45, 4.525)]]
    E["S4-S5"] = [[(3.45, 3.575), (3.45, 3.55)]]
    E["S5-S6"] = [[(3.45, 2.75), (3.45, 2.70)]]
    E["S5-S7"] = [[(6.15, 3.15), (6.6, 3.15), (6.6, 1.05), (6.9, 1.05)]]
    E["S6-S7"] = [[(6.15, 2.35), (6.6, 2.35), (6.6, 1.05), (6.9, 1.05)]]
    E["S6-S2'"] = [[(5.3, 2.0), (5.3, 0.5), (10.2, 0.5), (10.2, 6.35), (9.55, 6.35)]]
    E["S2'-S2"] = [[(7.55, 6.35), (6.15, 6.35)]]
    for k in ("S1-S2", "S2-S3", "S3-S4", "S4-S5", "S5-S6"):
        poly(ax, E[k][0], C_SOLID, 1.7, "-")
    poly(ax, E["S5-S7"][0], C_BOLD, 1.5, "-")
    poly(ax, E["S6-S7"][0], C_BOLD, 1.5, "-")
    poly(ax, E["S6-S2'"][0], E_VERIFY, 1.5, (0, (6, 3)))
    poly(ax, E["S2'-S2"][0], E_VERIFY, 1.5, (0, (6, 3)))

    ax.text(8.0, 2.78, "审计支路 S5/S6 → S7", ha="left", va="center", fontsize=8.4,
            color=C_BOLD, zorder=4)
    ax.text(8.0, 2.46, "查回执 · 查学分 · 查活动记录", ha="left", va="center", fontsize=7.9,
            color=C_SUB, zorder=4)
    ax.text(10.42, 3.5, "S6 → S2'  学分/画像回流（画像构建取链上数据）",
            rotation=90, ha="center", va="center", fontsize=8.2, color=E_VERIFY, zorder=4)

    nodes = [("S1", 0.75, 7.75, 6.15, 8.65), ("S2", 0.75, 5.95, 6.15, 6.75),
             ("S3", 0.75, 4.95, 6.15, 5.75), ("S4", 0.75, 3.575, 6.15, 4.525),
             ("S5", 0.75, 2.75, 6.15, 3.55), ("S6", 0.75, 2.0, 6.15, 2.7),
             ("S7", 6.9, 0.6, 10.1, 1.6), ("S2'", 7.55, 5.95, 9.55, 6.75)]
    viol, nseg = check_overlap(nodes, E, set())
    path = os.path.join(OUT_DIR, "fig2_业务流程图.png")
    finish(fig, path, "图2", 8, 8, viol, nseg)
    summary("图2", 8, 8, "S1~S7 + S2' 回流节点；串行链 5 条 + 审计支路 2 条 + 回流 1 条")
    return viol


# ---------------------------------------------------------------- 图 3 上链数据分析图
def fig3():
    fig = plt.figure(figsize=(9, 7.3), facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 9.75)
    ax.axis("off")
    ax.text(6.0, 9.5, "图 3  上链数据分析图（同一套 miniappinfo 格式的两种业务记录）",
            fontsize=13.5, fontweight="bold", color=C_TXT, ha="center", va="center")

    rect(ax, 2.9, 8.36, 6.2, 0.72, "white", "#8A8A8A", lw=0.9, r=0.12, ls=(0, (4, 2)), zorder=5)
    ax.text(6.0, 8.78, "两卡片：同一账户 · 同一链 · 同一套 miniappinfo 格式",
            ha="center", va="center", fontsize=8.6, color="#3A3A3A", zorder=6)
    ax.text(6.0, 8.5, "时序溯源靠链上交易本体（txHash / 区块号 / 时间戳） · prevHash 键恒为空串",
            ha="center", va="center", fontsize=8.6, color="#3A3A3A", zorder=6)

    def row(ax, x0, y, key, value, keyc, vc="#2B2B2B", w_inner=4.3):
        rect(ax, x0 + 0.22, y - 0.18, w_inner, 0.36, "#F7F8FA", "#D8DCE0", lw=0.6, r=0.07, zorder=5)
        ax.text(x0 + 0.45, y, key, ha="left", va="center", fontsize=8.3,
                fontweight="bold", color=keyc, zorder=6)
        ax.text(x0 + 1.95, y, value, ha="left", va="center", fontsize=8.2, color=vc, zorder=6)

    def band(ax, x0, y0, w, h, fill, edge, title, lines, tcol):
        rect(ax, x0, y0, w, h, fill, edge, lw=0.9, r=0.07, zorder=5)
        ax.text(x0 + 0.18, y0 + h - 0.21, title, ha="left", va="center", fontsize=8.3,
                fontweight="bold", color=tcol, zorder=6)
        for i, ln in enumerate(lines):
            ax.text(x0 + 0.20, y0 + h - 0.52 - i * 0.32, ln, ha="left", va="center",
                    fontsize=8.1, color="#333333", zorder=6)

    def card(x0, w, title, tag, hdr_fill, ec, keyc, section2_t, rows, band_kwargs):
        box(ax, x0 + w / 2, 4.35, w, 7.7, "white", ec, lw=1.5, r=0.12)
        rect(ax, x0 + 0.08, 7.62, w - 0.16, 0.49, hdr_fill, hdr_fill, lw=0.0, r=0.10, zorder=5)
        ax.text(x0 + 0.26, 7.865, title, ha="left", va="center", fontsize=10.0,
                fontweight="bold", color=ec, zorder=6)
        ax.text(x0 + w - 0.26, 7.865, tag, ha="right", va="center", fontsize=7.8,
                color="#5A6472", zorder=6)
        ax.text(x0 + 0.26, 7.33, "① 固定三键（合约 tableLog 常量）", ha="left",
                va="center", fontsize=8.1, color="#5A6472", zorder=6)
        row(ax, x0, 6.95, "「__type__」", "miniappinfo", keyc)
        row(ax, x0, 6.55, "「prevHash」", "“”  恒为空串（冻结 ABI 无入参位）", keyc)
        row(ax, x0, 6.15, "「nextHash」", "“”  恒为空串", keyc)
        ax.text(x0 + 0.26, 5.76, section2_t, ha="left", va="center", fontsize=8.1,
                color="#5A6472", zorder=6)
        for i, (k, v) in enumerate(rows):
            row(ax, x0, 5.32 - i * 0.40, k, v, keyc)
        band(ax, x0 + 0.2, band_kwargs["y0"], w - 0.4, band_kwargs["h"],
             band_kwargs["fill"], band_kwargs["edge"], band_kwargs["title"],
             band_kwargs["lines"], band_kwargs["tcol"])

    # 卡片 A
    card(0.7, 4.7, "卡片 A：教研成果存证记录", "触发：registerArtifact",
         F_CHAIN, E_CHAIN, "#1F3864",
         "② lists 业务键（registerArtifact 五参）",
         [("成果编号", "ART-2026-001"),
          ("标题", "跨校集体备课案例：二次函数教学设计"),
          ("作者", "周书"),
          ("学校", "成都理工大学工程技术学院"),
          ("文件哈希", "0a9999… （SHA-256 · 64 位十六进制）")],
         dict(y0=1.55, h=1.5, fill="#EFF4E9", edge="#7A9468",
              title="③ 链上元数据带（交易回执字段 · 证据 03 同款格式）",
              lines=["交易哈希 0x…（64 位） · 区块号 183651xxx",
                     "链上时间戳 tx.timestamp · gasUsed（数字）",
                     "存证主体：教师「陈以宁」 · 发送账户 bd6d0c49…"],
              tcol="#4C6937"))
    ax.text(0.95, 1.08, "校验：拿原文重算 SHA-256 与链上 fileHash 比对",
            ha="left", va="center", fontsize=7.8, color="#777777", zorder=6)

    # 卡片 B
    card(6.6, 4.7, "卡片 B：教研活动参与记录", "触发：recordActivity",
         F_VERIFY, E_VERIFY, "#7F3F00",
         "② lists 业务键（recordActivity 四参 + 合约计算）",
         [("活动编号", "ACT-2026-001"),
          ("教师", "陈以宁"),
          ("学校", "成都理工大学工程技术学院"),
          ("贡献分钟", "90"),
          ("折算学分", "180（=90×2，合约累加进 creditOf）")],
         dict(y0=2.5, h=1.02, fill="#FBF1E2", edge="#B08A55",
              title="③ 链上元数据带（同卡片 A · 交易回执字段）",
              lines=["交易哈希 0x…（64 位） · 区块号 183651xxx",
                     "tx.timestamp · gasUsed · 教师「陈以宁」· 发送账户 bd6d0c49…"],
              tcol="#8A5A22"))
    ax.text(6.86, 2.18, "脚注 · 该教师累计学分（链上查询）", ha="left", va="center",
            fontsize=8.1, fontweight="bold", color="#7F3F00", zorder=6)
    rect(ax, 6.8, 1.48, 4.32, 0.62, "#FCE8DB", "#D9A96A", lw=0.9, r=0.10, zorder=5)
    ax.text(6.97, 1.86, "getCreditFor( “陈以宁” ) → “180”", ha="left", va="center",
            fontsize=8.4, fontweight="bold", color="#7F3F00", zorder=6)
    ax.text(6.97, 1.60, "（该教师累计学分 · 本地只读 · 不耗 gas）", ha="left", va="center",
            fontsize=8.0, color="#5A4A3A", zorder=6)

    # 两卡片之间的虚线箭头
    E = {}
    E["AB"] = [[(5.4, 4.35), (6.6, 4.35)]]
    poly(ax, E["AB"][0], C_DASH, 1.4, (0, (4, 2)), both=True)
    ax.text(6.0, 4.62, "同构", ha="center", va="center", fontsize=8.2, color=C_SUB, zorder=6)

    nodes = [("A", 0.7, 0.5, 5.4, 8.2), ("B", 6.6, 0.5, 11.3, 8.2)]
    viol, nseg = check_overlap(nodes, E, set())
    path = os.path.join(OUT_DIR, "fig3_上链数据分析图.png")
    finish(fig, path, "图3", 2, 1, viol, nseg)
    summary("图3", 2, 1, "卡片 A / 卡片 B；两卡片间双虚线同构箭头 1 条")
    return viol


def main():
    total = []
    total += fig1()
    total += fig2()
    total += fig3()
    if total:
        print("!! 存在几何自检违规：%r" % total)
        sys.exit(2)
    print("三张图输出完成，几何自检全部通过，退出码 0")
    sys.exit(0)


if __name__ == "__main__":
    main()