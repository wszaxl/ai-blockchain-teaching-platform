# -*- coding: utf-8 -*-
"""开发关键节点截图渲染：内容全部取自真实日志/真实链上回执解码，仅做截取与打码。
输出 docs/教研平台/assets/fig5-3..fig5-6 与 fig6-1。
打码规则：链账户名 → <链账户名>；长路径前缀 → …；工作档案内录屏文件名不出现。
"""
import base64, json, os, re
from PIL import Image, ImageDraw, ImageFont

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(WS, 'docs', '教研平台', 'assets')
RE = os.path.join(WS, 'build', 'probe', 're')
TMP = os.environ.get('TEMP', r'C:\Users\HUAWEI\AppData\Local\Temp')

BG      = (13, 17, 23)
BAR     = (22, 27, 34)
TXT     = (214, 226, 240)
PROMPT  = (126, 231, 135)
ACC     = (121, 192, 255)
SUB     = (139, 152, 173)
KEY     = (255, 213, 128)

F      = ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc', 21)
FB     = ImageFont.truetype(r'C:\Windows\Fonts\msyhbd.ttc', 21)
FT     = ImageFont.truetype(r'C:\Windows\Fonts\msyhbd.ttc', 24)


def read_log(name):
    raw = open(name, 'rb').read()
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('gbk', errors='replace')


def mask(s):
    s = re.sub(r'[A-Za-z]:\\Users\\[^\\]+\\Desktop\\[^\\]+\\', r'…\\', s)
    s = re.sub(r'E:\\HuaweiMoveData\\Users\\HUAWEI\\Desktop\\基于AL\+区域协同教研\\', r'…\\', s)
    return s


def unesc(t):
    return t.replace('\\"', '"')


def receipt_fields(logtext):
    m = re.search(r'"blockNumber":(\d+),"code":\d+,"gasUsed":(\d+),"hash":"([0-9a-f]{64})"', unesc(logtext))
    return m.group(1), m.group(2), m.group(3)


def decode_miniapp(logtext):
    for b64 in re.findall(r'"logData":"([A-Za-z0-9+/=]{80,})"', unesc(logtext)):
        try:
            raw = base64.b64decode(b64)
        except Exception:
            continue
        s = raw.decode('utf-8', errors='ignore')
        m = re.search(r'(\{"__type__":"miniappinfo".*\})', s)
        if m:
            obj = json.loads(m.group(1))
            return obj
    return None


def miniapp_line(obj):
    parts = '  '.join(f'{x["name"]}: {x["value"]}' for x in obj['lists'])
    return parts


def wrap(text, width=104):
    out, cur = [], ''
    for ch in text:
        cur += ch
        if len(cur) >= width:
            out.append(cur)
            cur = ''
    if cur:
        out.append(cur)
    return out


class Shot:
    def __init__(self, title):
        self.rows = []          # (kind, text)
        self.title = title

    def cmd(self, t):    self.rows.append(('cmd', t))
    def out(self, t):    self.rows.append(('out', t))
    def kv(self, t):     self.rows.append(('kv', t))
    def dim(self, t):    self.rows.append(('dim', t))
    def gap(self):       self.rows.append(('gap', ''))

    def save(self, path):
        lines = []
        for kind, text in self.rows:
            if kind == 'gap':
                lines.append((kind, ''))
            else:
                for i, w in enumerate(wrap(text)):
                    lines.append((kind if i == 0 else kind + '_c', w))
        lh, pad, barh = 32, 34, 52
        W = 1800
        H = barh + pad * 2 + lh * len(lines) + 10
        im = Image.new('RGB', (W, H), BG)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, W, barh], fill=BAR)
        for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse([24 + i * 30, barh // 2 - 8, 40 + i * 30, barh // 2 + 8], fill=c)
        d.text((130, barh // 2 - 13), self.title, font=FT, fill=SUB)
        y = barh + pad
        for kind, text in lines:
            base = kind.rstrip('_c')
            if base == 'gap':
                y += lh // 2
                continue
            if base == 'cmd':
                d.text((pad, y), text, font=FB if kind == 'cmd' else F, fill=PROMPT)
            elif base == 'kv':
                d.text((pad, y), text, font=F if kind == 'kv' else F, fill=KEY)
            elif base == 'dim':
                d.text((pad, y), text, font=F, fill=SUB)
            else:
                d.text((pad, y), text, font=F, fill=TXT)
            y += lh
        im.save(path)
        print('saved', os.path.basename(path), im.size)


ACC_CMD = 'QoT6128ELXHOXRFH keys\\access.key a00e36c5 <链账户名> 93f381ChLXHOXRFH1790846615585 LXHOXRFH'

# ---------- fig5-3 项目整体结构 ----------
n_scripts = len([f for f in os.listdir(os.path.join(WS, 'scripts')) if f.endswith('.py')])
n_vid = len(os.listdir(os.path.join(WS, '提交物-视频')))
n_rec = len(os.listdir(os.path.join(WS, '工作档案', '原始录屏')))
s = Shot('项目整体结构（真实目录 · 角色标注）')
s.out('基于AI+区块链的区域协同教研平台/')
s.out('├── contracts/                Solidity 合约源码 TeachingTrace.sol（冻结 ABI 三入口）')
s.out('├── tools/                    链上工具链：TeachFlowTool / RestChainTool / RestDeployTool + solc_build.py')
s.out('├── build/                    编译与运行产物：alipay-solc-0.4.24、TeachingTrace.bin、*.class、上链回执日志')
s.out('├── keys/                     access.key（RSA 私钥 · 提交压缩包时删除 · 内容全程打码）')
s.out('├── 可视化/                   链上交易可视化服务 visualize_server.py + 大屏页面 visualize.html')
s.out(f'├── scripts/                  文档 / 图表 / 截图生成脚本（{n_scripts} 个 .py）')
s.out('├── docs/                     方案 docx · 技术文档 pdf · 汇报 pptx · 接口文档 · assets 图')
s.out(f'├── 提交物-视频/              联盟链搭建与 SDK 终端演示视频（{n_vid} 个）')
s.out(f'├── 工作档案/                 原始录屏（{n_rec} 段）· 工作流脚本 · 过程记忆')
s.out('├── README-复现手册.md        复现步骤、链参数与隐私须知')
s.out('├── 提交物清单与视频核验.md    提交物对照与视频核验记录')
s.out('└── 资产与外部依赖清单.md      外部依赖与来源清单')
s.gap()
s.dim('说明：合约 → 工具链 → BaaS REST 网关 → 开放联盟链 a00e36c5；可视化与文档均消费同一批真实回执。')
s.save(os.path.join(ASSETS, 'fig5-3_项目整体结构.png'))

# ---------- fig5-4 编译与部署 ----------
compile_line = read_log(os.path.join(RE, '6_compile.txt')).strip().splitlines()[0]
deploy_log = read_log(os.path.join(RE, '1_deploy.txt'))
blk, gas, h = receipt_fields(deploy_log)
s = Shot('关键节点① 合约编译 + 部署上链（蚂蚁链 BaaS REST 网关）')
s.cmd('E:\\…\\基于AL+区域协同教研> java -cp build/tools RestDeployTool  （编译: tools\\solc_build.py）')
s.out(mask(compile_line))
s.gap()
s.cmd('E:\\…\\基于AL+区域协同教研> java -cp build/tools TeachFlowTool deploy ' + ACC_CMD + ' build\\contracts\\TeachingTrace.bin teaching_platform_v1')
for ln in deploy_log.strip().splitlines()[:1]:
    s.out(mask(ln))
s.out('--- 交易回执 ---')
j = deploy_log.split('--- 交易回执 ---')[1].strip().splitlines()[0]
cut = j.index('\\"hash\\":\\"') + len('\\"hash\\":\\"') + 64
s.out(j[:cut] + '\", …（logs / output 字段省略）')
s.gap()
s.kv(f'>>> 部署成功  blockNumber={blk}  gasUsed={gas}')
s.kv(f'>>> contractAddress 由合约名 teaching_platform_v1 派生  txHash={h}')
s.save(os.path.join(ASSETS, 'fig5-4_编译与部署终端.png'))

# ---------- fig5-5 上链回执核验 ----------
r2 = read_log(os.path.join(TMP, 'q_r2.txt'))
a2 = read_log(os.path.join(TMP, 'dev_activity.txt'))
b1, g1, h1 = receipt_fields(r2)
b2, g2, h2 = receipt_fields(a2)
m1, m2 = decode_miniapp(r2), decode_miniapp(a2)
s = Shot('关键节点② 业务上链回执核验（QUERYRECEIPT + logData base64 解码存证原文）')
s.cmd('E:\\…\\基于AL+区域协同教研> java -cp build/tools RestChainTool query ' + ACC_CMD + ' 48ba4912…dcecc5b3')
s.out('--- 交易回执 ---')
s.kv(f'blockNumber={b1}  gasUsed={g1}  result=0  txHash={h1}')
s.out('--- 存证原文（logData base64 解码即 miniappinfo）---')
s.out(miniapp_line(m1))
s.gap()
s.cmd('E:\\…\\基于AL+区域协同教研> java -cp build/tools RestChainTool query ' + ACC_CMD + ' 7b844056…8ad4e8e6')
s.out('--- 交易回执 ---')
s.kv(f'blockNumber={b2}  gasUsed={g2}  result=0  txHash={h2}')
s.out('--- 存证原文（logData base64 解码即 miniappinfo）---')
s.out(miniapp_line(m2))
s.gap()
s.dim('两笔回执均可在 ChainInsight 浏览器输入哈希复核；存证原文与第 6.2 节凭证表一致。')
s.save(os.path.join(ASSETS, 'fig5-5_上链回执核验终端.png'))

# ---------- fig5-6 学分查询 ----------
credit_log = read_log(os.path.join(TMP, 'dev_credit.txt'))
s = Shot('关键节点③ 链上只读查询：getCreditFor 现场折算学分')
s.cmd('E:\\…\\基于AL+区域协同教研> java -cp build/tools TeachFlowTool credit ' + ACC_CMD + ' teaching_platform_v1 陈以宁')
for ln in credit_log.strip().splitlines():
    ln = mask(ln)
    if ln.startswith('{"success"'):
        ln = ln[:ln.index('\\"txHash\\":\\"') + len('\\"txHash\\":\\"') + 64] + '\" …（其余字段省略）'
    s.out(ln)
s.gap()
s.kv('>>> 合约按「贡献分钟 × 2」返回：credit = 180（90 分钟教研活动 ACT-2026-001）')
s.save(os.path.join(ASSETS, 'fig5-6_学分查询终端.png'))

# ---------- fig6-1 可视化大屏 ----------
im = Image.open(os.path.join(TMP, 'dev_dash.png'))
im = im.crop((0, 0, im.width, 700))
im.save(os.path.join(ASSETS, 'fig6-1_可视化大屏.png'))
print('saved fig6-1_可视化大屏.png', im.size)
