/*
 * RestChainTool：蚂蚁链 BaaS REST 通道工具，对 KMS 托管账户执行账户查询、存证与交易查询（纯 JDK，不依赖 Spring / rest-client jar）。
 *
 * 用法示例（命令行用法）：
 *   java RestChainTool account <accessId> <access.key路径> <bizid> <账户名>
 *   java RestChainTool deposit <accessId> <access.key路径> <bizid> <账户名> <mykmsKeyId> <tenantid> <存证内容>
 *   java RestChainTool query   <accessId> <access.key路径> <bizid> <txHash>
 */

import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.security.spec.PKCS8EncodedKeySpec;
import java.util.Base64;

/**
 * 适用场景：链上账户是「密钥托管（KMS）」时，交易由平台代签、本地没有 user.key，
 * 无法用 SDK 直连那套（com.muying.trace.*）签名，只能走本工具。
 *
 * 签名规则（官方 CertUtil.sign 的等价实现）：
 *   secret = 小写十六进制（SHA256withRSA（accessId + 毫秒时间戳））
 *   取令牌：POST {rest-url}/api/contract/shakeHand，body {accessId,time,secret} → data 即 token（30 分钟有效）
 *   查询：  POST {rest-url}/api/contract/chainCall（method=QUERYACCOUNT / QUERYTRANSACTION / QUERYRECEIPT）
 *   交易：  POST {rest-url}/api/contract/chainCallForBiz（method=DEPOSIT / TENANTCREATEACCUNT / DEPLOYCONTRACTFORBIZASYNC …）
 */
public class RestChainTool {

    static final String REST_URL = "https://rest.baas.alipay.com";

    /** 命令行入口：按子命令 account / deposit / query 分发。 */
    public static void main(String[] args) throws Exception {
        String cmd = args.length > 0 ? args[0] : "";
        boolean known = "account".equals(cmd) || "deposit".equals(cmd) || "query".equals(cmd);
        if (!known) {
            if (!cmd.isEmpty()) {
                System.out.println("未知子命令：" + cmd);
            }
            usage();
            System.exit(2);
        }
        // 先按子命令核参数个数，再读 access.key / 握手：deposit 缺 5~7 参数时在这里
        // 给用法提示退出，而不是握手之后才抛 ArrayIndexOutOfBoundsException / NoSuchFileException
        if ("deposit".equals(cmd) ? args.length != 8 : args.length < 5) {
            usage();
            System.exit(2);
        }
        String accessId = args[1];
        String keyPath = args[2];
        String bizid = args[3];
        PrivateKey key = loadKey(keyPath);
        String token = getToken(accessId, key);
        System.out.println("token 获取成功（有效期 30 分钟）");

        if ("account".equals(cmd)) {
            String account = args[4];
            String r = chainCall(accessId, bizid, token, "QUERYACCOUNT",
                    "{\"queryAccount\":\"" + account + "\"}");
            System.out.println(r);
        } else if ("deposit".equals(cmd)) {
            String account = args[4];
            String kmsId = args[5];
            String tenantid = args[6];
            String content = args[7];
            String orderId = "order_" + System.currentTimeMillis();
            String json = "{"
                    + "\"orderId\":" + esc(orderId) + ","
                    + "\"bizid\":" + esc(bizid) + ","
                    + "\"account\":" + esc(account) + ","
                    + "\"content\":" + esc(content) + ","
                    + "\"mykmsKeyId\":" + esc(kmsId) + ","
                    + "\"method\":\"DEPOSIT\","
                    + "\"accessId\":" + esc(accessId) + ","
                    + "\"token\":" + esc(token) + ","
                    + "\"tenantid\":" + esc(tenantid) + ","
                    + "\"gas\":100000}";
            String r = post(REST_URL + "/api/contract/chainCallForBiz", json);
            System.out.println("存证响应: " + r);
            if (r.contains("\"success\":false")) {
                System.out.println("!!! 存证失败：服务端返回 success=false（原始响应见上）");
                System.exit(1);
            }
            String txHash = field(r, "data");
            if (txHash == null || !txHash.matches("[0-9a-fA-F]{64}")) {
                System.out.println("!!! 未取得交易哈希，存证可能未提交（服务端原始响应见上）");
                System.exit(1);
            }
            System.out.println(">>> txHash = " + txHash);
            System.out.println("用 `query " + accessId + " " + keyPath + " " + bizid + " " + txHash + "` 查回执与内容");
        } else {
            String txHash = args[4];
            System.out.println("--- 交易回执 ---");
            System.out.println(chainCall(accessId, bizid, token, "QUERYRECEIPT", null, txHash));
            System.out.println("--- 交易内容（data 为 base64，解码即存证原文）---");
            System.out.println(chainCall(accessId, bizid, token, "QUERYTRANSACTION", null, txHash));
        }
    }

    static void usage() {
        System.out.println("用法：");
        System.out.println("  account <accessId> <access.key路径> <bizid> <账户名>");
        System.out.println("  deposit <accessId> <access.key路径> <bizid> <账户名> <mykmsKeyId> <tenantid> <存证内容>");
        System.out.println("  query   <accessId> <access.key路径> <bizid> <txHash>");
    }

    // ---------- 基础设施 ----------

    static PrivateKey loadKey(String pemPath) throws Exception {
        String text = new String(Files.readAllBytes(Paths.get(pemPath)), StandardCharsets.UTF_8);
        StringBuilder sb = new StringBuilder();
        for (String line : text.split("\\r?\\n")) {
            if (line.contains("---")) continue;
            sb.append(line.trim());
        }
        return KeyFactory.getInstance("RSA").generatePrivate(
                new PKCS8EncodedKeySpec(Base64.getDecoder().decode(sb.toString())));
    }

    static String sign(String data, PrivateKey key) throws Exception {
        Signature sig = Signature.getInstance("SHA256withRSA");
        sig.initSign(key);
        sig.update(data.getBytes(StandardCharsets.UTF_8));
        StringBuilder sb = new StringBuilder();
        for (byte x : sig.sign()) sb.append(String.format("%02x", x));
        return sb.toString();
    }

    static String getToken(String accessId, PrivateKey key) throws Exception {
        long now = System.currentTimeMillis();
        String body = "{\"accessId\":\"" + accessId + "\",\"time\":\"" + now
                + "\",\"secret\":\"" + sign(accessId + now, key) + "\"}";
        String resp = post(REST_URL + "/api/contract/shakeHand", body);
        String token = field(resp, "data");
        if (token == null) throw new IllegalStateException("握手失败：" + resp);
        return token;
    }

    static String chainCall(String accessId, String bizid, String token, String method, String requestStr) throws Exception {
        return chainCall(accessId, bizid, token, method, requestStr, null);
    }

    static String chainCall(String accessId, String bizid, String token, String method, String requestStr, String hash) throws Exception {
        StringBuilder sb = new StringBuilder("{");
        sb.append("\"accessId\":").append(esc(accessId)).append(",");
        sb.append("\"bizid\":").append(esc(bizid)).append(",");
        sb.append("\"method\":").append(esc(method)).append(",");
        if (requestStr != null) sb.append("\"requestStr\":").append(esc(requestStr)).append(",");
        if (hash != null) sb.append("\"hash\":").append(esc(hash)).append(",");
        sb.append("\"token\":").append(esc(token)).append("}");
        return post(REST_URL + "/api/contract/chainCall", sb.toString());
    }

    static String post(String urlStr, String json) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(urlStr).openConnection();
        conn.setRequestMethod("POST");
        conn.setConnectTimeout(15000);
        conn.setReadTimeout(60000);
        conn.setDoOutput(true);
        conn.setRequestProperty("Content-Type", "application/json;charset=UTF-8");
        try (OutputStream os = conn.getOutputStream()) {
            os.write(json.getBytes(StandardCharsets.UTF_8));
        }
        int code = conn.getResponseCode();
        InputStream is = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
        StringBuilder body = new StringBuilder();
        if (is != null) {
            try (BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
                String line;
                while ((line = br.readLine()) != null) body.append(line);
            }
        }
        // 与 RestDeployTool.post 同口径：HTTP 非 200 当作失败返回，取不到 data 的调用方（getToken / deposit）
        // 会据此报错并以非 0 退出码结束，脚本可判错
        if (code != 200) {
            return "HTTP " + code + " " + body;
        }
        return body.toString();
    }

    static String field(String json, String name) {
        String key = "\"" + name + "\":\"";
        int i = json.indexOf(key);
        if (i < 0) return null;
        int start = i + key.length();
        int end = json.indexOf('"', start);
        return end < 0 ? null : json.substring(start, end);
    }

    static String esc(String s) {
        return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"")
                .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + "\"";
    }
}