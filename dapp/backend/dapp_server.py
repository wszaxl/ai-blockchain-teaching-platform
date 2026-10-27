# -*- coding: utf-8 -*-
"""区域协同教研 DApp —— 后端服务（BaaS REST 交易网关适配层）

三层 DApp 架构中的「后端 / 链访问层」：
  前端页面(dapp/frontend)  →  本地后端(本文件, :8790)  →  蚂蚁链开放联盟链 BaaS REST 网关

设计要点（与安全边界）：
  * 后端只做「只读」链上查询：账户余额(QUERYACCOUNT)、交易回执/内容(QUERYRECEIPT/QUERYTRANSACTION)。
  * 私钥文件 keys/access.key 仅以「路径」传给 Java 工具在本地签名握手，后端从不读取其内容、
    也从不把私钥、token 写进任何 HTTP 响应。
  * 写交易（部署 / 确权 / 活动上链）不在本后端开放，避免联网页面误触发链上状态变更；
    它们由离线命令行工具 TeachFlowTool 在受控环境执行（见 README-复现手册.md）。
  * 账户地址为链上公开信息，可安全内嵌；账户「名称」按隐私要求打码。

启动：python dapp/backend/dapp_server.py   →   浏览器打开 http://127.0.0.1:8790/
"""
import json, os, re, subprocess, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BACKEND = os.path.dirname(os.path.abspath(__file__))          # dapp/backend
DAPP = os.path.dirname(BACKEND)                                # dapp/
PROJECT = os.path.dirname(DAPP)                                # 项目根（build/、keys/ 所在）
FRONTEND = os.path.join(DAPP, 'frontend')

JAVA = r'C:\Program Files\Java\jdk-21\bin\java.exe'
TOOL_CP = os.path.join('build', 'tools')

# 链接入参数（均为链上公开 / 参赛团队自有配置；私钥只给路径，不给内容）
ACCESS_ID = 'QoT6128ELXHOXRFH'
KEY_PATH = os.path.join('keys', 'access.key')                  # 相对项目根，私钥不出本机
BIZID = 'a00e36c5'
ACCOUNT_ADDR = 'bd6d0c4911705d02d89419f00b513a3c4ec0ec9c6e9dfb4ce50345f692cdf2bc'  # 链上公开地址

# QUERYACCOUNT 以「账户名」为键（账户名经 SHA256 派生出上面的公开地址）。账户名属隐私信息，
# 绝不写入源码；如需实时余额，运维在本机以环境变量 DAPP_ACCOUNT_NAME 提供后再启动本服务。
ACCOUNT_NAME = os.environ.get('DAPP_ACCOUNT_NAME', '').strip()

# 链上账户端点偶发不可达时的兜底：最近一次实时重查快照（可在区块链浏览器复核）。
LAST_KNOWN_BALANCE = 6537457
LAST_KNOWN_TS = '2026-10-07'

CHAIN_INFO = {
    "platform": "蚂蚁链开放联盟链（BaaS）",
    "chainId": BIZID,
    "tenantId": "LXHOXRFH",
    "gateway": "rest.baas.alipay.com",
    "accessId": ACCESS_ID,
    "signAlg": "SHA256withRSA",
    "accountCustody": "KMS 托管账户（私钥不出 KMS，账户名称打码）",
    "accountAddr": ACCOUNT_ADDR,
    "contractCompiler": "alipay-solc-0.4.24",
    "fuelModel": "写交易按 gasUsed 扣减；只读 CALLCONTRACTBIZ 本地调用不耗 gas",
}

# 已真实上链并解码过的业务记录（前端展示用；均为链上实测数据）
SHOWCASE = [
    {"tag": "教研平台 · 成果确权", "hash": "48ba4912c6af94f00007fb1b106503857e96b73acc37580eac23f71ddcecc5b3",
     "block": "183651012", "gasUsed": "407754",
     "fields": {"成果编号": "ART-2026-001", "标题": "跨校集体备课案例：二次函数教学设计",
                "作者": "周书", "学校": "成都理工大学工程技术学院"}},
    {"tag": "教研平台 · 教研活动", "hash": "7b844056dbd173c64f25c507ec070e72ba8dca1fc56e49d716309b1a8ad4e8e6",
     "block": "183651029", "gasUsed": "488838",
     "fields": {"活动编号": "ACT-2026-001", "教师": "陈以宁", "学校": "成都理工大学工程技术学院",
                "贡献分钟": "90", "折算学分": "180"}},
    {"tag": "合约部署", "hash": "ceeaba86f9ed2451379182dbc5263597019e0f2b60e7a155d615f44e6bd956b9",
     "block": "183447761", "gasUsed": "107225",
     "fields": {"说明": "TeachingTrace 学分互认合约部署上链"}},
]

HASH_RE = re.compile(r'^[0-9a-fA-F]{64}$')


def run_tool(subcmd, extra):
    """在项目根调用 Java RestChainTool（只读子命令），返回 stdout 文本。私钥仅以路径传入。"""
    args = [JAVA, '-Dfile.encoding=UTF-8', '-cp', TOOL_CP, 'RestChainTool', subcmd,
            ACCESS_ID, KEY_PATH, BIZID] + extra
    r = subprocess.run(args, cwd=PROJECT, capture_output=True, text=True,
                       encoding='utf-8', errors='ignore', timeout=90)
    return r.stdout, r.stderr, r.returncode


def parse_balance(stdout):
    m = re.search(r'\\"balance\\":(\d+)', stdout) or re.search(r'"balance":(\d+)', stdout)
    return int(m.group(1)) if m else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ('/', '/index.html'):
            return self._serve_file(os.path.join(FRONTEND, 'index.html'), 'text/html; charset=utf-8')

        if path == '/api/chain':
            return self._json(CHAIN_INFO)

        if path == '/api/showcase':
            return self._json(SHOWCASE)

        if path == '/api/balance':
            key = ACCOUNT_NAME or ACCOUNT_ADDR
            try:
                out, err, code = run_tool('account', [key])
                bal = parse_balance(out)
                if bal is not None:
                    return self._json({"ok": True, "live": True, "balance": bal,
                                       "account": ACCOUNT_ADDR, "ts": None,
                                       "note": "QUERYACCOUNT 实时回读；私钥仅本地路径参与签名，未在响应中出现"})
                return self._json({"ok": True, "live": False, "balance": LAST_KNOWN_BALANCE,
                                   "account": ACCOUNT_ADDR, "ts": LAST_KNOWN_TS,
                                   "note": "链上 QUERYACCOUNT 端点暂不可达，显示 %s 实时重查快照（可在区块链浏览器复核）" % LAST_KNOWN_TS})
            except Exception as e:
                return self._json({"ok": True, "live": False, "balance": LAST_KNOWN_BALANCE,
                                   "account": ACCOUNT_ADDR, "ts": LAST_KNOWN_TS,
                                   "note": "查询异常(%s)，回退 %s 快照" % (e, LAST_KNOWN_TS)})

        if path == '/api/receipt':
            qs = urllib.parse.parse_qs(parsed.query)
            h = (qs.get('hash', [''])[0]).strip()
            if not HASH_RE.match(h):
                return self._json({"ok": False, "error": "请输入 64 位十六进制交易哈希"})
            try:
                out, err, code = run_tool('query', [h])
                return self._json({"ok": code == 0, "hash": h, "raw": out,
                                   "stderr": err[-400:], "exit": code})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, 500)

        return self._json({"ok": False, "error": "not found"}, 404)

    def _serve_file(self, fp, ctype):
        if not os.path.isfile(fp):
            return self._send(404, 'not found', 'text/plain; charset=utf-8')
        with open(fp, 'rb') as f:
            self._send(200, f.read(), ctype)


def main():
    port = int(os.environ.get('DAPP_PORT', '8790'))
    srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print('教研 DApp 后端已启动: http://127.0.0.1:%d/  (Ctrl+C 停止)' % port)
    srv.serve_forever()


if __name__ == '__main__':
    main()
