/*
 * RestDeployTool：走蚂蚁链 BaaS REST 通道部署 / 调用 Solidity 合约（KMS 托管账户由平台代签；纯 JDK 实现，不依赖 Spring 与 lib/ 下任何 jar）。
 *
 * 用法示例（命令行用法）：
 *   java -cp build\tools RestDeployTool deploy <accessId> <access.key路径> <bizid> <account> <kmsId> <tenantid> <合约字节码文件> <contractName>
 *   java -cp build\tools RestDeployTool call   <accessId> <access.key路径> <bizid> <account> <kmsId> <tenantid> <contractName> <methodSignature> <inputParamListStr> <outTypesJson> [--local]
 */

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.KeyFactory;
import java.security.PrivateKey;
import java.security.Signature;
import java.security.spec.PKCS8EncodedKeySpec;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;

/**
 * 参数说明：
 *   accessId    控制台「申请 AccessKey」得到的 AccessId（必须与 access.key 配套）
 *   access.key  私钥文件（PKCS#8，PEM 文本）；REST 通道只用它做 SHA256withRSA 握手签名
 *   bizid       链 ID；本租户只有开放联盟链 a00e36c5 有权限
 *   account     链账户名（KMS 托管账户，例如链账户（打码））
 *   kmsId       mykmsKeyId，控制台里形如 93f381ChLXHOXRFH1790846615585
 *   tenantid    租户号，握手返回的 JWT 里可解出，例如 LXHOXRFH
 *   contractName 合约名：部署时用它派生合约地址，之后调用必须用同一个名字
 *   --local     只对 call 有效：本地执行（isLocalTransaction=true），不打包、不耗 gas，用于只读查询
 *
 * 通道约定（依 docs/REST通道接入说明.md 的实测结论，勿改）：
 *   部署     POST /api/contract/chainCallForBiz + method=DEPLOYCONTRACTFORBIZASYNC
 *   写调用   POST /api/contract/chainCallForBiz + method=CALLCONTRACTBIZASYNC（上链打包）
 *   本地只读 POST /api/contract/chainCallForBiz + method=CALLCONTRACTBIZ + "isLocalTransaction":true
 *
 * 合约参数怎么传（踩过的坑）：
 *   - inputParamListStr 是「JSON 数组的字符串」，例如 ["a","b","c"]，由本工具原样转发；
 *   - 合约方法的 bytes32 参数必须写成 **32 个十进制字节值的嵌套数组**，例如
 *     [[114,111,115,101,0,0,...]]（rose 补零到 32 字节）；写成 "0x726f7365..."、
 *     裸 hex、或补空格到 32 字符的字符串，服务端都会拒：405 value length must be 32；
 *   - 其余类型按 JSON 直接写：string 写 "中文或文本"，int32 写数字（如 [2,3]）；
 *   - outTypesJson 写返回类型数组，例如 [] 或 ["uint8"]（本地查询用）。
 *   - 本项目的 BabyTraceCompat 对外方法全部是 string 参数，不需要 bytes32：
 *     insertTrace(traceId,batchId,stage,operatorName,location,date,detail,preTxHash) 共 8 个，首环节 preTxHash 传 "";
 *     updateDetail(traceId,detail,preTxHash) 共 3 个。
 *
 * 输出约定：
 *   两个子命令都会打印服务端原始响应；拿到交易哈希时单独打印一行
 *       >>> txHash = <64位hex>
 *   便于脚本抓取。本地查询（--local）没有上链交易，改为打印结果行
 *       >>> outRes = [...]
 *   （本地查询服务端会把业务结果转义后塞在 data 字符串里，形如
 *    {"success":true,"code":"200","data":"{\"outRes\":[1],...}"}，
 *    其中的 txHash 只是本地执行出来的哈希、并未打包，故本工具单独标成
 *    >>> localTxHash = ... ，不会混进 >>> txHash 行）。
 *
 * 编译运行（Windows cmd）：
 *   javac -encoding UTF-8 -nowarn -d build\tools tools\RestDeployTool.java
 *   java -cp build\tools RestDeployTool deploy QoT6128ELXHOXRFH keys\access.key a00e36c5 <链账户名> 93f381ChLXHOXRFH1790846615585 LXHOXRFH build\contracts\BabyTraceCompat.bin muying_trace_v1
 *
 * gas 默认值可用环境变量 REST_GAS 覆盖（例如 set REST_GAS=5000000）。
 * 说明：链上只按实际消耗扣 gas，gas 设大不会多扣，但设小了交易会失败且不退还已消耗的 gas。
 */
public class RestDeployTool {

    /** REST 固定网关（官方文档固定值） */
    static final String REST = "https://rest.baas.alipay.com";

    /** 默认 gas：部署按字节码 6409 字节、实测约 80 gas/字节的存码成本估算，留足余量 */
    static final long DEFAULT_DEPLOY_GAS = 3000000L;
    /** 默认 gas：写调用（BabyTraceCompat.insertTrace 要写 8 个字符串 + 拼 JSON，比纯 deposit 贵） */
    static final long DEFAULT_CALL_GAS = 1000000L;

    /** 命令行入口：按子命令 deploy / call 分发。 */
    public static void main(String[] args) {
        try {
            if (args.length == 0) {
                usage();
                System.exit(2);
            }
            // 收集位置参数；--local 可以出现在任意位置
            boolean local = false;
            List<String> pos = new ArrayList<String>();
            for (int i = 1; i < args.length; i++) {
                if ("--local".equals(args[i])) {
                    local = true;
                } else {
                    pos.add(args[i]);
                }
            }
            String cmd = args[0];
            if ("deploy".equals(cmd)) {
                if (pos.size() != 8) {
                    usage();
                    System.exit(2);
                }
                deploy(pos.get(0), pos.get(1), pos.get(2), pos.get(3), pos.get(4),
                        pos.get(5), pos.get(6), pos.get(7));
            } else if ("call".equals(cmd)) {
                if (pos.size() != 10) {
                    usage();
                    System.exit(2);
                }
                call(pos.get(0), pos.get(1), pos.get(2), pos.get(3), pos.get(4),
                        pos.get(5), pos.get(6), pos.get(7), pos.get(8), pos.get(9), local);
            } else {
                System.out.println("!!! 未知子命令: " + cmd);
                usage();
                System.exit(2);
            }
        } catch (Exception e) {
            System.out.println("!!! 执行失败: " + e);
            System.exit(1);
        }
    }

    static void usage() {
        System.out.println("用法:");
        System.out.println("  deploy <accessId> <access.key路径> <bizid> <account> <kmsId> <tenantid> <合约字节码文件> <contractName>");
        System.out.println("  call   <accessId> <access.key路径> <bizid> <account> <kmsId> <tenantid> <contractName> <methodSignature> <inputParamListStr> <outTypesJson> [--local]");
        System.out.println();
        System.out.println("  合约字节码文件须是纯十六进制（solc -o 生成的 .bin，或控制台合约二进制串），");
        System.out.println("  可带 0x 前缀与换行，本工具会去掉。");
        System.out.println("  bytes32 参数须写成 32 个十进制字节值的嵌套数组，如 [[114,111,115,101,0,...]]；");
        System.out.println("  写成 hex 或补空格字符串会被服务端拒（405 value length must be 32）。");
        System.out.println("  --local 仅用于 call：本地只读查询，不打包、不耗 gas。");
        System.out.println("  环境变量 REST_GAS 可覆盖默认 gas。");
    }

    // ---------------- 部署 ----------------

    static void deploy(String accessId, String keyPath, String bizid, String account, String kmsId,
                       String tenantid, String codeFile, String contractName) throws Exception {
        // 先校验字节码文件，避免文件有问题还白跑一次握手
        String code = sanitizeCode(readText(codeFile), codeFile);
        System.out.println(">>> 合约字节码: " + code.length() + " 字符 = " + (code.length() / 2)
                + " 字节（来自 " + codeFile + "）");

        PrivateKey key = loadKey(keyPath);
        String token = getToken(accessId, key);
        System.out.println(">>> 握手成功，已取得 token（有效期 30 分钟）");

        System.out.println(">>> contractName = " + contractName + "（合约地址由它派生，之后调用必须同名）");
        long gas = gasLimit(DEFAULT_DEPLOY_GAS);
        System.out.println(">>> gas = " + gas + "（链上只扣实际消耗；可用环境变量 REST_GAS 覆盖）");

        String orderId = "order_" + System.currentTimeMillis();
        String json = "{"
                + "\"orderId\":" + esc(orderId) + ","
                + "\"bizid\":" + esc(bizid) + ","
                + "\"account\":" + esc(account) + ","
                + "\"contractName\":" + esc(contractName) + ","
                + "\"contractCode\":" + esc(code) + ","
                + "\"mykmsKeyId\":" + esc(kmsId) + ","
                + "\"tenantid\":" + esc(tenantid) + ","
                + "\"method\":\"DEPLOYCONTRACTFORBIZASYNC\","
                + "\"accessId\":" + esc(accessId) + ","
                + "\"token\":" + esc(token) + ","
                + "\"gas\":" + gas + "}";

        System.out.println("=== 发起部署（DEPLOYCONTRACTFORBIZASYNC）orderId = " + orderId + " ===");
        String resp = post(REST + "/api/contract/chainCallForBiz", json);
        System.out.println("=== 服务端原始响应 ===");
        System.out.println(resp);

        String txHash = extractTxHash(resp);
        if (txHash == null) {
            System.out.println("!!! 未取得交易哈希，部署可能未提交");
            String q = "{\"accessId\":" + esc(accessId) + ",\"bizid\":" + esc(bizid)
                    + ",\"method\":\"QUERYTRANSACTIONBIZ\",\"orderId\":" + esc(orderId)
                    + ",\"tenantid\":" + esc(tenantid) + ",\"token\":" + esc(token) + "}";
            System.out.println("=== 按 orderId 查询（服务端原始响应）===");
            System.out.println(post(REST + "/api/contract/chainCall", q));
            System.exit(1);
        }
        System.out.println(">>> txHash = " + txHash);
        System.out.println("（合约地址由 contractName 派生，调用时用同一个 contractName）");
        pollReceipt(accessId, bizid, token, txHash, 6, 5);
    }

    // ---------------- 调用 ----------------

    static void call(String accessId, String keyPath, String bizid, String account, String kmsId,
                     String tenantid, String contractName, String methodSignature,
                     String inputParamListStr, String outTypesJson, boolean local) throws Exception {
        PrivateKey key = loadKey(keyPath);
        String token = getToken(accessId, key);
        System.out.println(">>> 握手成功，已取得 token（有效期 30 分钟）");

        String method = local ? "CALLCONTRACTBIZ" : "CALLCONTRACTBIZASYNC";
        long gas = gasLimit(DEFAULT_CALL_GAS);
        String orderId = "order_" + System.currentTimeMillis();
        String json = "{"
                + "\"orderId\":" + esc(orderId) + ","
                + "\"bizid\":" + esc(bizid) + ","
                + "\"account\":" + esc(account) + ","
                + "\"contractName\":" + esc(contractName) + ","
                + "\"methodSignature\":" + esc(methodSignature) + ","
                + "\"inputParamListStr\":" + esc(inputParamListStr) + ","
                + "\"outTypes\":" + esc(outTypesJson) + ","
                + (local ? "\"isLocalTransaction\":true," : "")
                + "\"mykmsKeyId\":" + esc(kmsId) + ","
                + "\"tenantid\":" + esc(tenantid) + ","
                + "\"method\":\"" + method + "\","
                + "\"accessId\":" + esc(accessId) + ","
                + "\"token\":" + esc(token) + ","
                + "\"gas\":" + gas + "}";

        System.out.println("=== 调用合约 " + methodSignature + "  method=" + method
                + (local ? "（本地执行/只读，不打包、不耗 gas）" : "（异步上链）") + " ===");
        System.out.println("=== 参数 inputParamListStr = " + inputParamListStr + " ===");
        String resp = post(REST + "/api/contract/chainCallForBiz", json);
        System.out.println("=== 服务端原始响应 ===");
        System.out.println(resp);

        if (local) {
            // 本地查询：服务端把结果转义后放在 data 字符串里，先解开再取 outRes
            String inner = payload(resp);
            String outRes = jsonArrayField(inner, "outRes");
            if (outRes == null && inner != resp) {
                outRes = jsonArrayField(resp, "outRes");
            }
            if (outRes == null) {
                System.out.println("!!! 未取到 outRes，本地查询失败（服务端原始响应见上）");
                System.exit(1);
            }
            String result = jsonNumberField(inner, "result");
            String localHash = jsonStringField(inner, "txHash");
            System.out.println(">>> outRes = " + outRes);
            if (isTxHash(localHash)) {
                System.out.println(">>> localTxHash = " + localHash + "（本地执行，未打包上链）");
            }
            if (result != null && !"0".equals(result)) {
                System.out.println("!!! 本地执行 result=" + result + "：调用失败");
                System.exit(1);
            }
            System.out.println(">>> 本地执行成功（isLocalTransaction=true，未打包、不耗 gas）");
            return;
        }

        String txHash = extractTxHash(resp);
        if (txHash == null) {
            System.out.println("!!! 未取得交易哈希，调用可能未提交");
            System.exit(1);
        }
        System.out.println(">>> txHash = " + txHash);
        pollReceipt(accessId, bizid, token, txHash, 6, 5);
    }

    // ---------------- 回执轮询 ----------------

    static void pollReceipt(String accessId, String bizid, String token, String txHash,
                            int rounds, int sleepSec) throws Exception {
        for (int i = 1; i <= rounds; i++) {
            Thread.sleep(sleepSec * 1000L);
            String q = "{\"accessId\":" + esc(accessId) + ",\"bizid\":" + esc(bizid)
                    + ",\"method\":\"QUERYRECEIPT\",\"hash\":" + esc(txHash) + ",\"token\":" + esc(token) + "}";
            String r = post(REST + "/api/contract/chainCall", q);
            System.out.println("--- 回执查询 " + i + "/" + rounds + "（服务端原始响应）---");
            System.out.println(abbrev(r, 1500));
            if (r.contains("txFinish\":true")) {
                if (r.contains("\"result\":0")) {
                    String gasUsed = jsonNumberField(r, "gasUsed");
                    System.out.println(">>> 回执 result=0 txFinish=true（已打包且执行成功）"
                            + (gasUsed == null ? "" : " gasUsed=" + gasUsed));
                    return;
                }
                System.out.println(">>> 回执 txFinish=true 但 result != 0：交易执行失败");
                System.exit(1);
            }
            if (r.contains("\"code\":\"211\"")) {
                System.out.println("（提示：211 rate limit reached，查询频率受限，稍后可用 txHash 自行重查）");
            }
        }
        System.out.println(">>> 回执在 " + rounds + " 次轮询内未返回 txFinish=true；交易可能仍在打包，");
        System.out.println("    可用交易哈希稍后查询：POST /api/contract/chainCall method=QUERYRECEIPT hash=" + txHash);
    }

    // ---------------- 签名 / HTTP ----------------

    /** 读 PEM 私钥（PKCS#8）：去掉 ----- 包裹行，剩余内容 base64 解码 */
    static PrivateKey loadKey(String p) throws Exception {
        String text = new String(Files.readAllBytes(Paths.get(p)), StandardCharsets.UTF_8);
        StringBuilder sb = new StringBuilder();
        for (String line : text.split("\\r?\\n")) {
            if (line.contains("---")) {
                continue;
            }
            sb.append(line.trim());
        }
        return KeyFactory.getInstance("RSA")
                .generatePrivate(new PKCS8EncodedKeySpec(Base64.getDecoder().decode(sb.toString())));
    }

    /** secret = 小写十六进制( SHA256withRSA(accessId + 毫秒时间戳) ) */
    static String sign(String d, PrivateKey k) throws Exception {
        Signature s = Signature.getInstance("SHA256withRSA");
        s.initSign(k);
        s.update(d.getBytes(StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        for (byte b : s.sign()) {
            sb.append(String.format("%02x", b));
        }
        return sb.toString();
    }

    static String getToken(String accessId, PrivateKey k) throws Exception {
        long now = System.currentTimeMillis();
        String r = post(REST + "/api/contract/shakeHand",
                "{\"accessId\":\"" + accessId + "\",\"time\":\"" + now + "\",\"secret\":\"" + sign(accessId + now, k) + "\"}");
        String t = jsonStringField(r, "data");
        if (t == null || r.contains("\"success\":false")) {
            throw new IllegalStateException("握手失败（服务端原始响应: " + r
                    + "）——accessId 必须与 access.key 配套，不配套时服务端只回 fail check signature（code 204）");
        }
        return t;
    }

    static String post(String u, String json) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(u).openConnection();
        c.setRequestMethod("POST");
        c.setConnectTimeout(15000);
        c.setReadTimeout(90000);
        c.setDoOutput(true);
        c.setRequestProperty("Content-Type", "application/json;charset=UTF-8");
        try (OutputStream os = c.getOutputStream()) {
            os.write(json.getBytes(StandardCharsets.UTF_8));
        }
        int code = c.getResponseCode();
        InputStream is = code >= 400 ? c.getErrorStream() : c.getInputStream();
        StringBuilder b = new StringBuilder();
        if (is != null) {
            try (BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
                String l;
                while ((l = br.readLine()) != null) {
                    b.append(l);
                }
            }
        }
        if (code != 200) {
            return "HTTP " + code + " " + b;
        }
        return b.toString();
    }

    // ---------------- 小工具 ----------------

    static String readText(String p) throws Exception {
        return new String(Files.readAllBytes(Paths.get(p)), StandardCharsets.UTF_8);
    }

    /** 字节码文件 -> 纯小写十六进制：去掉空白、可选的 0x 前缀，并校验合法性 */
    static String sanitizeCode(String raw, String file) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < raw.length(); i++) {
            char ch = raw.charAt(i);
            if (!Character.isWhitespace(ch)) {
                sb.append(ch);
            }
        }
        String s = sb.toString();
        if (s.startsWith("0x") || s.startsWith("0X")) {
            s = s.substring(2);
        }
        if (s.length() == 0 || !s.matches("[0-9a-fA-F]+")) {
            throw new IllegalArgumentException("字节码文件不是纯十六进制（" + file
                    + "）：请用 solc --bin -o <目录> 生成的 .bin，或控制台的合约二进制串；"
                    + "若文件里带了 \"======= xxx ======= / Binary:\" 之类表头，请先去掉");
        }
        return s.toLowerCase();
    }

    static long gasLimit(long def) {
        String v = System.getenv("REST_GAS");
        if (v != null && v.trim().length() > 0) {
            try {
                return Long.parseLong(v.trim());
            } catch (NumberFormatException e) {
                System.out.println("!!! REST_GAS 不是数字，忽略: " + v);
            }
        }
        return def;
    }

    static boolean isTxHash(String s) {
        return s != null && s.matches("[0-9a-fA-F]{64}");
    }

    /** 取 "name":"value" 的字符串值，按 JSON 规则反转义（反斜杠转义序列与 U+XXXX 形式均支持） */
    static String jsonStringField(String j, String name) {
        String k = "\"" + name + "\":\"";
        int i = j.indexOf(k);
        if (i < 0) {
            return null;
        }
        StringBuilder sb = new StringBuilder();
        for (int p = i + k.length(); p < j.length(); p++) {
            char c = j.charAt(p);
            if (c == '"') {
                return sb.toString();
            }
            if (c != '\\') {
                sb.append(c);
                continue;
            }
            if (p + 1 >= j.length()) {
                return null;
            }
            char e = j.charAt(++p);
            if (e == 'u') {
                if (p + 4 >= j.length()) {
                    return null;
                }
                sb.append((char) Integer.parseInt(j.substring(p + 1, p + 5), 16));
                p += 4;
            } else if (e == 'n') {
                sb.append('\n');
            } else if (e == 'r') {
                sb.append('\r');
            } else if (e == 't') {
                sb.append('\t');
            } else if (e == 'b') {
                sb.append('\b');
            } else if (e == 'f') {
                sb.append('\f');
            } else {
                sb.append(e); // \" \\ \/
            }
        }
        return null;
    }

    /**
     * 服务端常把业务 JSON 转义后放在顶层 data 字符串里，例如
     * {"success":true,"code":"200","data":"{\"outRes\":[1],...}"}；
     * 这里把 data 解开取出业务 JSON，取不到就退回整段原始响应。
     */
    static String payload(String resp) {
        String data = jsonStringField(resp, "data");
        if (data != null) {
            String t = data.trim();
            if (t.startsWith("{") || t.startsWith("[")) {
                return t;
            }
        }
        return resp;
    }

    /** 取交易哈希：异步交易的 data 本身就是 64 位 hex；若 data 是转义 JSON 则取其中的 txHash */
    static String extractTxHash(String resp) {
        String data = jsonStringField(resp, "data");
        if (isTxHash(data)) {
            return data;
        }
        String h = jsonStringField(payload(resp), "txHash");
        return isTxHash(h) ? h : null;
    }

    /** 取 "name":<数字> 的数字文本 */
    static String jsonNumberField(String j, String name) {
        String k = "\"" + name + "\":";
        int i = j.indexOf(k);
        if (i < 0) {
            return null;
        }
        int s = i + k.length();
        int e = s;
        while (e < j.length() && "-0123456789".indexOf(j.charAt(e)) >= 0) {
            e++;
        }
        return e > s ? j.substring(s, e) : null;
    }

    /** 取 "name":[ ... ] 的数组文本（按括号配对截取，含字符串内的括号不计数） */
    static String jsonArrayField(String j, String name) {
        String k = "\"" + name + "\":";
        int i = j.indexOf(k);
        if (i < 0) {
            return null;
        }
        int s = i + k.length();
        int depth = 0;
        for (int p = s; p < j.length(); p++) {
            char c = j.charAt(p);
            if (c == '"') {
                p++;
                while (p < j.length() && j.charAt(p) != '"') {
                    if (j.charAt(p) == '\\') {
                        p++;
                    }
                    p++;
                }
                continue;
            }
            if (c == '[' || c == '{') {
                depth++;
            } else if (c == ']' || c == '}') {
                depth--;
                if (depth == 0) {
                    return j.substring(s, p + 1);
                }
            }
        }
        return null;
    }

    static String abbrev(String s, int max) {
        return s.length() > max ? s.substring(0, max) + "..." : s;
    }

    static String esc(String s) {
        return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"")
                .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + "\"";
    }
}