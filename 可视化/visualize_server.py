# -*- coding: utf-8 -*-
"""链上交易可视化：本地服务 + 大屏页面。
启动：python visualize_server.py  →  浏览器打开 http://127.0.0.1:8765/
查询接口 /api/query?hash=<交易哈希> 调用 RestChainTool 真实查链。
"""
import json, os, subprocess, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))          # 可视化/（页面所在）
PROJECT = os.path.dirname(ROOT)                              # 项目根（build/ 与 keys/ 所在）
JAVA = r'C:\Program Files\Java\jdk-21\bin\java.exe'
CHAIN = ['QoT6128ELXHOXRFH', 'keys\\access.key', 'a00e36c5']

# 预置：已真实上链并解码过的记录（卡片展示用）
SHOWCASE = [
    {"tag": "母婴溯源 · 原料采购", "hash": "7485c337c3c1ac3491c8fd58c1a661bf312a0ac7bb2a374003f91aa8a2f678ae",
     "block": "183416223",
     "json": {"__type__": "miniappinfo", "prevHash": "", "lists": [
        {"name": "批次号", "value": "MY20261001-A"}, {"name": "环节", "value": "RAW_MATERIAL"},
        {"name": "操作主体", "value": "成都理工大学工程技术学院技术组"}, {"name": "地点", "value": "呼和浩特"},
        {"name": "时间", "value": "2026-10-01"}, {"name": "详情", "value": "生鲜乳入库500kg，检测合格"}]}},
    {"tag": "母婴溯源 · 生产加工", "hash": "43862334c287418b450187bf66a4f190968a289776a7bf015fb0cfcc2a258a47",
     "block": "183416281",
     "json": {"__type__": "miniappinfo", "prevHash": "7485c337c3c1ac3491c8fd58c1a661bf312a0ac7bb2a374003f91aa8a2f678ae", "lists": [
        {"name": "批次号", "value": "MY20261001-A"}, {"name": "环节", "value": "PRODUCTION"},
        {"name": "操作主体", "value": "某某乳业一厂"}, {"name": "地点", "value": "呼和浩特2号灌装线"},
        {"name": "时间", "value": "2026-10-02"}, {"name": "详情", "value": "配方v3，灌装1200罐，批号P20261001"}]}},
    {"tag": "教研平台 · 成果确权", "hash": "48ba4912c6af94f00007fb1b106503857e96b73acc37580eac23f71ddcecc5b3",
     "block": "链上可查",
     "json": {"__type__": "miniappinfo", "lists": [
        {"name": "成果编号", "value": "ART-2026-001"}, {"name": "标题", "value": "跨校集体备课案例：二次函数教学设计"},
        {"name": "作者", "value": "周书"}, {"name": "学校", "value": "成都理工大学工程技术学院"},
        {"name": "文件哈希", "value": "0a9999…（SHA-256）"}]}},
    {"tag": "教研平台 · 教研活动", "hash": "7b844056dbd173c64f25c507ec070e72ba8dca1fc56e49d716309b1a8ad4e8e6",
     "block": "链上可查",
     "json": {"__type__": "miniappinfo", "lists": [
        {"name": "活动编号", "value": "ACT-2026-001"}, {"name": "教师", "value": "陈以宁"},
        {"name": "学校", "value": "成都理工大学工程技术学院"}, {"name": "贡献分钟", "value": "90"},
        {"name": "折算学分", "value": "180"}]}},
]

HTML = open(os.path.join(ROOT, 'visualize.html'), encoding='utf-8').read()

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype='text/html; charset=utf-8'):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.end_headers()
        self.wfile.write(body.encode('utf-8'))
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/':
            self._send(200, HTML)
        elif parsed.path == '/api/showcase':
            self._send(200, json.dumps(SHOWCASE, ensure_ascii=False), 'application/json; charset=utf-8')
        elif parsed.path == '/api/query':
            qs = urllib.parse.parse_qs(parsed.query)
            h = (qs.get('hash', [''])[0]).strip()
            if len(h) != 64:
                self._send(200, json.dumps({"error": "请输入 64 位交易哈希"}, ensure_ascii=False), 'application/json; charset=utf-8')
                return
            out = subprocess.run([JAVA, '-Dfile.encoding=UTF-8', '-cp', os.path.join('build', 'tools'),
                                  'RestChainTool', 'query'] + CHAIN + [h],
                                 cwd=PROJECT, capture_output=True, text=True,
                                 encoding='utf-8', errors='ignore', timeout=90)
            self._send(200, json.dumps({"raw": out.stdout, "stderr": out.stderr[-500:], "exit": out.returncode}, ensure_ascii=False),
                       'application/json; charset=utf-8')
        else:
            self._send(404, 'not found')

print('可视化服务已启动: http://127.0.0.1:8765/  (Ctrl+C 停止)')
HTTPServer(('127.0.0.1', 8765), H).serve_forever()