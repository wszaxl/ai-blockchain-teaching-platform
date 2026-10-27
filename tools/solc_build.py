#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 Solidity 源码编译成"部署用的 creation bytecode"（纯十六进制）。

用法:
    <python路径> tools/solc_build.py <输入.sol> <输出.bin> [选项]

选项:
    --contract NAME   文件里有多个可部署合约时，显式指定要输出的合约名
    --optimize        打开优化器（默认关闭，与蚂蚁链控制台默认一致）
    --runs N          优化器 runs（隐含 --optimize，默认 200）
    --solc PATH       强制使用指定的 solc 可执行文件
    --runtime         输出 runtime bytecode（链上运行时代码）而不是 creation code
    --show-warnings   把编译器警告也打到 stderr（默认只在成功时提示条数）
    --evm-version V   传给 solc --evm-version（homestead/tangerineWhistle/spuriousDragon/byzantium）
    --libraries SPEC  传给 solc --libraries，形如 "Lib:0x1234...,Lib2:0xabcd..."（只影响外部库占位符）

退出码:
    0  编译成功，输出文件已写入纯十六进制
    1  编译失败（编译器诊断已打到 stderr）
    2  本机找不到/装不上可用的 solc
    3  命令行用法错误

solc 查找顺序:
    1. --solc 指定
    2. 本脚本同目录（tools/）下的 solc*.exe
    3. py-solc-x 已安装的版本（C:\\Users\\<user>\\.solcx\\）
    4. PATH 里的 solc
    版本会按源码里的 pragma solidity 约束挑"满足约束的最高版本"。
"""
from __future__ import print_function

import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 固定按 UTF-8 往外写，避免在 GBK 代码页的 Windows 控制台里因为编码不了中文而崩掉。
# （若控制台显示乱码，执行 chcp 65001 即可正常显示。）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

EXIT_OK = 0
EXIT_COMPILE = 1
EXIT_NO_SOLC = 2
EXIT_USAGE = 3


def die(msg, code):
    sys.stderr.write(msg.rstrip() + "\n")
    sys.exit(code)


# ---------------------------------------------------------------- 版本约束
def parse_version(s):
    """'0.4.26' -> (0, 4, 26)"""
    nums = re.findall(r"\d+", s)
    if not nums:
        return None
    while len(nums) < 3:
        nums.append("0")
    return tuple(int(x) for x in nums[:3])


def read_pragma_constraints(text):
    """返回 [ (op, version_tuple), ... ]，多个 pragma 时全部保留（都需满足）。"""
    clauses = []
    for m in re.finditer(r"pragma\s+solidity\s+([^;]+);", text):
        expr = m.group(1)
        for part in expr.replace(",", " ").split():
            op = "^"
            ver = part
            for cand in ("^", ">=", "<=", "==", "=", "~", ">", "<"):
                if part.startswith(cand):
                    op = "=" if cand == "==" else cand
                    ver = part[len(cand):]
                    break
            v = parse_version(ver)
            if v is None:
                continue
            clauses.append((op, v))
    return clauses


def satisfies(version, clauses):
    if not clauses:
        return True
    for op, v in clauses:
        if op == "^":
            # ^0.4.20 -> >=0.4.20 且同一主版本; 若写了 ^0.4.20 只允许 0.4.x
            if not (version >= v and version[0] == v[0]):
                return False
            if v[0] == 0 and v[1] is not None and version[1] != v[1]:
                return False
        elif op == "=":
            if version != v:
                return False
        elif op == ">=":
            if version < v:
                return False
        elif op == "<=":
            if version > v:
                return False
        elif op == ">":
            if version <= v:
                return False
        elif op == "<":
            if version >= v:
                return False
        elif op == "~":
            if not (version >= v and version[0] == v[0] and version[1] == v[1]):
                return False
    return True


# ---------------------------------------------------------------- solc 查找
def _version_of_exe(path):
    try:
        p = subprocess.Popen([path, "--version"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        out = p.communicate()[0].decode("utf-8", "replace")
    except Exception:
        return None
    m = re.search(r"Version:\s*(\d+\.\d+\.\d+)", out)
    return m.group(1) if m else None


def collect_candidates():
    """-> list of (version_str, path, kind)"""
    found = []

    # 1) tools/ 下的 solc*.exe 或 solc（含 solc-v0.4.26.exe 这种命名）
    if os.path.isdir(HERE):
        for name in sorted(os.listdir(HERE)):
            if not re.match(r"^solc.*(\.exe)?$", name, re.I):
                continue
            path = os.path.join(HERE, name)
            if not os.path.isfile(path):
                continue
            v = _version_of_exe(path)
            if v:
                found.append((v, path, "tools"))

    # 2) py-solc-x 已安装
    try:
        import solcx
        for vobj in solcx.get_installed_solc_versions():
            v = str(vobj)
            try:
                path = str(solcx.install.get_executable(v))
            except Exception:
                continue
            if os.path.isfile(path):
                found.append((v, path, "py-solc-x"))
    except Exception:
        pass

    # 3) PATH
    path_solc = shutil.which("solc") or shutil.which("solc.exe")
    if path_solc:
        v = _version_of_exe(path_solc)
        if v:
            found.append((v, path_solc, "PATH"))

    # 去重（同版本保留先出现的）
    seen, out = set(), []
    for v, p, k in found:
        if v in seen:
            continue
        seen.add(v)
        out.append((v, p, k))
    return out


def try_install(version):
    """用 py-solc-x 现下 solc（网络可用时）。"""
    try:
        import solcx
        solcx.install_solc(version)
        return str(solcx.install.get_executable(version))
    except Exception as e:
        sys.stderr.write("py-solc-x 安装 solc %s 失败: %s\n" % (version, e))
        return None


def pick_solc(clauses, forced=None):
    if forced:
        if not os.path.isfile(forced):
            die("--solc 指定的文件不存在: %s" % forced, EXIT_NO_SOLC)
        v = _version_of_exe(forced)
        return (v or "unknown"), forced

    cands = collect_candidates()
    ok = [(parse_version(v), v, p) for (v, p, k) in cands if satisfies(parse_version(v), clauses)]
    if ok:
        ok.sort()
        return ok[-1][1], ok[-1][2]

    # 已安装的都不满足 pragma —— 尝试按 pragma 让 py-solc-x 下载一个
    try:
        import solcx
        avail = [str(v) for v in solcx.get_available_solc_versions()]
    except Exception as e:
        avail = []
        sys.stderr.write("查询可下载 solc 版本失败（可能无网络）: %s\n" % e)

    want = sorted([v for v in avail if satisfies(parse_version(v), clauses)])
    if want:
        target = want[-1]
        sys.stderr.write("本机没有满足 pragma 的 solc，尝试用 py-solc-x 下载 %s ...\n" % target)
        p = try_install(target)
        if p:
            return target, p

    have = ", ".join("%s(%s)" % (v, k) for v, p, k in cands) or "无"
    die("找不到满足 pragma %s 的 solc。\n本机已有: %s\n"
        "可执行 pip install py-solc-x 后重试（脚本会自动下载对应版本）。"
        % (" ".join("%s%s" % (op, ".".join(map(str, v))) for op, v in clauses) or "(无约束)", have),
        EXIT_NO_SOLC)


# ---------------------------------------------------------------- 编译输出解析
def grab_hex(section_text, marker):
    """返回 (hex or None, cut)。

    cut 非 None 表示这段 hex 被一个非十六进制字符打断 —— 字节码因此不完整。
    典型场景：合约引用了外部库（public 库函数）却没给库地址，solc 会在代码里留下
    链接占位符（0.4.x 形如 __<file>:<lib>__<hash>）。这种情况下绝不能把截断的结果
    当成功产物写出去。
    """
    i = section_text.find(marker)
    if i < 0:
        return None, None
    buf = []
    for ch in section_text[i + len(marker):]:
        if ch in "0123456789abcdefABCDEF":
            buf.append(ch)
        elif ch.isspace() or ch == ":":
            continue
        else:
            return ("".join(buf) or None), ch
    return ("".join(buf) or None), None


def parse_output(text):
    """-> {contract_name: {'bin':..., 'runtime':...}}"""
    result = {}
    # 逐段切分，避免"Binary:"跨段串味
    chunks = re.split(r"^=+\s*.+:([A-Za-z_$][A-Za-z0-9_$]*)\s*=+\s*$", text, flags=re.M)
    # chunks = [前言, name1, body1, name2, body2, ...]
    for i in range(1, len(chunks) - 1, 2):
        name, body = chunks[i], chunks[i + 1]
        d = result.setdefault(name, {})
        # 先按 runtime 标记切开，否则找 "Binary:" 时会把 runtime 段的标题当成截断点
        body_bin, body_rt = body, ""
        j = body.find("Binary of the runtime part:")
        if j >= 0:
            body_bin, body_rt = body[:j], body[j:]
        b, cut = grab_hex(body_rt, "Binary of the runtime part:")
        if b:
            d.setdefault("runtime", b)
        if cut:
            d.setdefault("runtime_cut", cut)
        b, cut = grab_hex(body_bin, "Binary:")
        if b:
            d.setdefault("bin", b)
        if cut:
            d["bin_cut"] = cut
    return result


DECL = re.compile(r"\b(contract|library|interface)\s+([A-Za-z_$][A-Za-z0-9_$]*)")


# 蚂蚁链 BaaS 控制台的编译器是官方 solc 的改造版，多出一些官方 solc 没有的东西。
# 这些不是"编译器装错了"，命中时要把话说清楚，免得下游以为是工具链问题。
FORK_EXTENSIONS = [
    (r"\btx\s*\.\s*txhash\b", "tx.txhash —— 蚂蚁链 tx 扩展变量（官方 solc 无 tx.txhash）"),
    (r"(?<![\w$.])identity\s+[A-Za-z_$][A-Za-z0-9_$]*\s*[,;)]",
     "identity —— 蚂蚁链 ABI 类型名（256 位，官方 solc 无此类型）"),
]


def strip_comments(text):
    """去掉 // 与 /* */ 注释，只在真代码里找扩展特征。"""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def detect_fork_extensions(text):
    code = strip_comments(text)
    hits = []
    for pat, label in FORK_EXTENSIONS:
        if re.search(pat, code):
            hits.append(label)
    return hits


def decl_kinds(text):
    """源码里每个顶层声明的种类：contract / library / interface。

    solc 给 library 也会输出非空的 Binary（库部署用的桩代码），必须区分，
    否则一个文件里有 library + contract 时会误判成"多个可部署合约"。
    """
    kinds = {}
    for m in DECL.finditer(text):
        kinds.setdefault(m.group(2), m.group(1))
    return kinds


def pick_contract(bins, src, src_text, want=None):
    """-> (合约名, 该合约的输出字典)；截断等情况交给调用方报错。"""
    info = dict((n, d) for n, d in bins.items() if d.get("bin") or d.get("bin_cut"))
    if not info:
        raise RuntimeError("编译输出里没有任何合约的 bytecode")
    if want:
        if want not in info:
            raise RuntimeError("找不到合约 %r；编译输出里有: %s"
                               % (want, ", ".join(sorted(info))))
        return want, info[want]

    kinds = decl_kinds(src_text)
    # 只认 contract（interface 不可部署；library 的 Binary 是库部署桩，不是我们要的部署码）
    usable = dict((n, d) for n, d in info.items() if kinds.get(n, "contract") == "contract")

    stem = os.path.splitext(os.path.basename(src))[0]
    for n in usable:
        if n == stem:
            return n, usable[n]
    for n in usable:
        if n.lower() == stem.lower():
            return n, usable[n]
    if len(usable) == 1:
        n = list(usable)[0]
        return n, usable[n]
    if not usable:
        raise RuntimeError("文件里没有可部署的 contract（只有 library/interface）: %s"
                           % ", ".join(sorted(info)))
    raise RuntimeError("文件里有多个可部署合约: %s；请用 --contract 指定"
                       % ", ".join(sorted(usable)))


LINK_HINT = (
    "原因通常是：源码里有外部库（public/external 库函数），本次编译没有提供库地址，\n"
    "solc 在字节码里留下了链接占位符（0.4.x 形如 __<file>:<lib>__<hash>）。\n"
    "处理办法二选一：\n"
    "  1) 用 --libraries \"<源码路径>:<库名>:<链上库地址>\" 提供地址。注意 solc 0.4.x\n"
    "     只认这种全限定名形式，只写库名（如 Ext:0x...）不会替换，占位符会留在代码里；\n"
    "  2) 把库函数改成 internal（会被内联，也就不需要链接了）——BabyTrace.sol 的\n"
    "     strings/utils 两个库就全是 internal，所以它不需要 --libraries。")


# ---------------------------------------------------------------- main
def main(argv):
    want = None
    forced_solc = None
    optimize = False
    runs = None
    want_runtime = False
    show_warnings = False
    evm_version = None
    libraries = None
    i = 0
    rest = argv[1:]
    while i < len(rest):
        a = rest[i]
        if a == "--contract" and i + 1 < len(rest):
            want = rest[i + 1]; i += 2; continue
        if a == "--solc" and i + 1 < len(rest):
            forced_solc = rest[i + 1]; i += 2; continue
        if a == "--runs" and i + 1 < len(rest):
            runs = rest[i + 1]; optimize = True; i += 2; continue
        if a == "--evm-version" and i + 1 < len(rest):
            evm_version = rest[i + 1]; i += 2; continue
        if a == "--libraries" and i + 1 < len(rest):
            libraries = rest[i + 1]; i += 2; continue
        if a in ("-h", "--help"):
            sys.stdout.write(__doc__)
            return EXIT_OK
        if a == "--optimize":
            optimize = True; i += 1; continue
        if a == "--runtime":
            want_runtime = True; i += 1; continue
        if a == "--show-warnings":
            show_warnings = True; i += 1; continue
        if a.startswith("--"):
            die("未知选项: %s" % a, EXIT_USAGE)
        i += 1

    # 收集"非选项及其值"之外的位置参数（选项值已在上面的循环里跳过）
    args = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("--contract", "--solc", "--runs", "--evm-version", "--libraries"):
            i += 2
            continue
        if not a.startswith("--"):
            args.append(a)
        i += 1

    if len(args) < 2:
        sys.stderr.write("用法: <python> tools/solc_build.py <输入.sol> <输出.bin> "
                         "[--contract NAME] [--optimize] [--runs N] [--solc PATH] [--runtime]\n")
        return EXIT_USAGE
    src, dst = args[0], args[1]
    if not os.path.isfile(src):
        die("输入文件不存在: %s" % src, EXIT_USAGE)

    raw = open(src, "rb").read()
    text = raw.decode("utf-8", "replace")
    clauses = read_pragma_constraints(text)
    fork_hits = detect_fork_extensions(text)

    version, solc = pick_solc(clauses, forced_solc)

    cmd = [solc, "--bin"]
    if want_runtime:
        cmd.append("--bin-runtime")
    if evm_version:
        cmd += ["--evm-version", evm_version]
    if libraries:
        cmd += ["--libraries", libraries]
    cmd.append(os.path.abspath(src))
    if optimize:
        cmd.append("--optimize")
        if runs:
            cmd += ["--optimize-runs", str(runs)]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out_b, err_b = p.communicate()
    out = out_b.decode("utf-8", "replace")
    err = err_b.decode("utf-8", "replace")

    if p.returncode != 0:
        # 编译失败：把编译器诊断（含警告）原样打到 stderr
        if out.strip():
            sys.stderr.write(out if out.endswith("\n") else out + "\n")
        if err.strip():
            sys.stderr.write(err if err.endswith("\n") else err + "\n")
        if fork_hits:
            sys.stderr.write(
                "提示: 源码用到蚂蚁链 BaaS 编译器扩展，官方 solc 没有这些：\n"
                + "".join("  - %s\n" % h for h in fork_hits)
                + "这不是 solc 版本/优化开关/库链接的问题；需要先由适配环节把这些扩展换成\n"
                  "官方 solc 能接受、且链上等价的写法。\n")
        die("编译失败 (solc %s, 退出码 %d): %s" % (version, p.returncode, src), EXIT_COMPILE)

    nwarn = len([l for l in err.splitlines() if "Warning" in l])
    if show_warnings and err.strip():
        sys.stderr.write(err if err.endswith("\n") else err + "\n")
    elif nwarn:
        sys.stderr.write("solc: %d 条警告已忽略（加 --show-warnings 查看）\n" % nwarn)

    bins = parse_output(out)
    try:
        name, entry = pick_contract(bins, src, text, want)
    except RuntimeError as e:
        # 有 Binary 段但没解析到时，把原始输出丢出去便于排查
        sys.stderr.write(out + ("\n" if out and not out.endswith("\n") else ""))
        die(str(e), EXIT_COMPILE)

    if entry.get("bin_cut"):
        # 绝不把截断的字节码当成功产物写出去
        sys.stderr.write(out + ("\n" if out and not out.endswith("\n") else ""))
        die("合约 %s 的 --bin 输出不是纯十六进制，在字符 %r 处被打断，产物不完整。\n%s"
            % (name, entry["bin_cut"], LINK_HINT), EXIT_COMPILE)

    if want_runtime:
        rt = entry.get("runtime")
        if not rt:
            die("合约 %s 没有 runtime bytecode" % name, EXIT_COMPILE)
        hexcode = rt
    else:
        hexcode = entry["bin"]

    hexcode = hexcode.lower()
    if hexcode.startswith("0x"):
        hexcode = hexcode[2:]

    dstdir = os.path.dirname(os.path.abspath(dst))
    if dstdir and not os.path.isdir(dstdir):
        os.makedirs(dstdir)
    with open(dst, "wb") as f:
        f.write(hexcode.encode("ascii"))   # 纯十六进制，无 0x、无空白

    sys.stdout.write("OK: %s <- %s | solc %s (%s) | %s | %d bytes -> %s\n"
                     % (name, src, version, solc, "runtime" if want_runtime else "creation",
                        len(hexcode) // 2, dst))
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except SystemExit:
        raise
    except Exception as e:
        die("内部错误: %r" % (e,), EXIT_COMPILE)