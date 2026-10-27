/*
 * TeachFlowTool：AI+区块链区域协同教研平台的链上工具，走蚂蚁链 BaaS REST 通道完成
 * 教研合约 teaching_platform_v1 的部署 / 教研成果确权存证 / 教研活动留痕与学分折算 / 教师累计学分查询
 * （KMS 托管账户由平台代签；纯 JDK 实现，不依赖 Spring 与 lib/ 下任何 jar）。
 * 握手、签名、HTTP 与 JSON 解析代码与 tools/RestDeployTool.java 同源（该通道形态已实测跑通）。
 *
 * 子命令与案例功能对应（《docs/教研平台/01-产品设计与实现方案.md》第 9 节落地映射第 3~6 行）：
 *   deploy   → 部署教研平台合约 teaching_platform_v1（DEPLOYCONTRACTFORBIZASYNC / TX_DEPLOY_CONTRACT，
 *              合约地址 = SHA256(contractName) 派生）；编译产物 build\contracts\TeachingTrace.bin
 *   register → 4.1 教研成果上链存证与确权：registerArtifact(string×5) 写入 achievements 表并
 *              emit LOG_STRING(miniappinfo：成果编号/标题/作者/学校/文件哈希)，txHash 即成果唯一存证编号
 *   activity → 4.2 智能合约自动统计贡献 + 4.3 跨校教研学分互认：recordActivity(string×4) 按
 *              credit = 分钟×2 折算（贡献 1 分钟 = 2 学分）累加 creditOf[teacherId]、复合键留痕
 *              records[activityId|teacherId] 并 emit LOG_STRING(miniappinfo)
 *   credit   → 4.3 查询侧：getCreditFor(string) 本地只读（CALLCONTRACTBIZ + isLocalTransaction:true，
 *              outTypes ["string"]），返回教师跨校累计学分十进制串，不打包、不耗 gas
 *
 * 用法示例（命令行用法；6 个链参数与 RestDeployTool 完全一致）：
 *   java -cp build\tools TeachFlowTool deploy   <accessId> <access.key路径> <bizid> <account> <kmsId> <tenantid> <合约字节码文件> <contractName>
 *   java -cp build\tools TeachFlowTool register <accessId> <access.key路径> <bizid> <account> <kmsId> <tenantid> <contractName> <artifactId> <title> <author> <school> <fileHash>
 *   java -cp build\tools TeachFlowTool activity <accessId> <access.key路径> <bizid> <account> <kmsId> <tenantid> <contractName> <activityId> <teacherId> <school> <effortMinutes>
 *   java -cp build\tools TeachFlowTool credit   <accessId> <access.key路径> <bizid> <account> <kmsId> <tenantid> <contractName> <teacherId>
 *
 * 本租户链参数实测值：
 *   QoT6128ELXHOXRFH keys\access.key a00e36c5 <链账户名> 93f381ChLXHOXRFH1790846615585 LXHOXRFH
 *
 * 编译运行（Windows cmd）：
 *   javac -encoding UTF-8 -nowarn -d build\tools tools\TeachFlowTool.java
 *   java -cp build\tools TeachFlowTool deploy QoT6128ELXHOXRFH keys\access.key a00e36c5 <链账户名> 93f381ChLXHOXRFH1790846615585 LXHOXRFH build\contracts\TeachingTrace.bin teaching_platform_v1
 *   java -cp build\tools TeachFlowTool register QoT6128ELXHOXRFH keys\access.key a00e36c5 <链账户名> 93f381ChLXHOXRFH1790846615585 LXHOXRFH teaching_platform_v1 ART-2026-001 "跨校集体备课案例：二次函数教学设计" 周书 成都理工大学工程技术学院 <64位十六进制小写SHA-256>
 *   java -cp build\tools TeachFlowTool activity QoT6128ELXHOXRFH keys\access.key a00e36c5 <链账户名> 93f381ChLXHOXRFH1790846615585 LXHOXRFH teaching_platform_v1 ACT-2026-001 陈以宁 成都理工大学工程技术学院 90
 *   java -cp build\tools TeachFlowTool credit   QoT6128ELXHOXRFH keys\access.key a00e36c5 <链账户名> 93f381ChLXHOXRFH1790846615585 LXHOXRFH teaching_platform_v1 陈以宁
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
 *   account     链账户名（KMS 托管账户；名称按隐私要求打码，可在控制台「链账户管理」查看本租户唯一账户）
 *   kmsId       mykmsKeyId，控制台里形如 93f381ChLXHOXRFH1790846615585
 *   tenantid    租户号，握手返回的 JWT 里可解出，例如 LXHOXRFH
 *   contractName 合约名：部署时用它派生合约地址，之后调用必须用同一个名字（teaching_platform_v1）
 *
 * 通道约定（依 docs/REST通道接入说明.md 的实测结论，勿改）：
 *   部署     POST /api/contract/chainCallForBiz + method=DEPLOYCONTRACTFORBIZASYNC
 *   写调用   POST /api/contract/chainCallForBiz + method=CALLCONTRACTBIZASYNC（上链打包）
 *   本地只读 POST /api/contract/chainCallForBiz + method=CALLCONTRACTBIZ + "isLocalTransaction":true
 *
 * 合约参数怎么传（踩过的坑，冻结 ABI 全 string，勿改）：
 *   - 冻结 ABI 三个入口参数全部是 string，直接以「JSON 字符串数组」传参即可，例如 ["ART-2026-001","跨校备课案例","周书","成都理工大学工程技术学院","0a99…"]；
 *   - bytes32 才是「32 个十进制字节值的嵌套数组」（如 [[114,111,115,101,0,…]]）那个坑，
 *     本工具四个子命令不产生任何 bytes32 参数，正常字符串数组传参；
 *   - outTypes：register / activity 无返回值，写 "[]"；credit（getCreditFor）返回 string，写 ["string"]。
 *
 * 输出约定（便于脚本抓取）：
 *   - deploy / register / activity 拿到交易哈希时单独打印一行
 *       >>> txHash = <64位hex>
 *     随后轮询回执；回执 211 限流时按固定间隔重试（查询接口有频率限制，勿连续打）。
 *   - credit 是本地只读（isLocalTransaction=true），没有上链交易，不打印 >>> txHash 行；
 *     改为打印结果行 >>> outRes = [...] 与解出的学分 >>> credit = <值>。
 *
 * gas 默认值可用环境变量 REST_GAS 覆盖（例如 set REST_GAS=5000000）。
 * 说明：链上只按实际消耗扣 gas，gas 设大不会多扣，但设小了交易会失败且不退还已消耗的 gas。
 */
public class TeachFlowTool {

    /** REST 固定网关（官方文档固定值） */
    static final String REST = "https://rest.baas.alipay.com";

    /** 默认 gas：部署按字节码存码成本估算，留足余量（同 RestDeployTool） */
    static final long DEFAULT_DEPLOY_GAS = 3000000L;
    /** 默认 gas：写调用与同量级的 BabyTraceCompat.insertTrace（8 string）实测 57~69 万，沿用 100 万 */
    static final long DEFAULT_CALL_GAS = 1000000L;

    /** 查询接口 211 rate limit：连续调用会被限流，按固定间隔重试；连续重试上限与间隔时长 */
    static final int MAX_211_RETRY = 3;
    static final long RETRY_DELAY_MS = 10000L;

    /** 命令行入口：按子命令 deploy / register / activity / credit 分发。 */
    public static void main(String[] args) {
        try {
            if (args.length == 0) {
                usage();
                System.exit(2);
            }
            List<String> pos = new ArrayList<String>();
            for (int i = 1; i < args.length; i++) {
                pos.add(args[i]);
            }
            String cmd = args[0];
            if ("deploy".equals(cmd)) {
                need(pos, 8);
                deploy(pos.get(0), pos.get(1), pos.get(2), pos.get(3), pos.get(4),
                        pos.get(5), pos.get(6), pos.get(7));
            } else if ("register".equals(cmd)) {
                need(pos, 12);
                register(pos.get(0), pos.get(1), pos.get(2), pos.get(3), pos.get(4),
                        pos.get(5), pos.get(6), pos.get(7), pos.get(8), pos.get(9),
                        pos.get(10), pos.get(11));
            } else if ("activity".equals(cmd)) {
                need(pos, 11);
                activity(pos.get(0), pos.get(1), pos.get(2), pos.get(3), pos.get(4),
                        pos.get(5), pos.get(6), pos.get(7), pos.get(8), pos.get(9),
                        pos.get(10));
            } else if ("credit".equals(cmd)) {
                need(pos, 8);
                credit(pos.get(0), pos.get(1), pos.get(2), pos.get(3), pos.get(4),
                        pos.get(5), pos.get(6), pos.get(7));
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
        System.out.println("  deploy   <accessId> <access.key路径> <bizid> <account> <kmsId> <tenantid> <合约字节码文件> <contractName>");
        System.out.println("  register <accessId> <access.key路径> <bizid> <account> <kmsId> <tenantid> <contractName> <artifactId> <title> <author> <school> <fileHash>");
        System.out.println("  activity <accessId> <access.key路径> <bizid> <account> <kmsId> <tenantid> <contractName> <activityId> <teacherId> <school> <effortMinutes>");
        System.out.println("  credit   <accessId> <access.key路径> <bizid> <account> <kmsId> <tenantid> <contractName> <teacherId>");
        System.out.println();
        System.out.println("  6 个链参数与 RestDeployTool 完全一致，本租户实测值:");
        System.out.println("    QoT6128ELXHOXRFH keys\\access.key a00e36c5 <链账户名> 93f381ChLXHOXRFH1790846615585 LXHOXRFH");
        System.out.println("  contractName 须与部署时一致（合约地址由它派生），本包合约名为 teaching_platform_v1。");
        System.out.println("  合约字节码文件须是纯十六进制（solc -o 生成的 .bin），可带 0x 前缀与换行。");
        System.out.println("  register → registerArtifact(string,string,string,string,string)：");
        System.out.println("    参数序 = 命令行序：artifactId、title、author、school、fileHash（fileHash 为 SHA-256 的 64 位十六进制小写）。");
        System.out.println("  activity → recordActivity(string,string,string,string)：");
        System.out.println("    参数序 = 命令行序：activityId、teacherId、school、effortMinutes（合约按 分钟×2 折算学分）。");
        System.out.println("  credit   → getCreditFor(string) 本地只读（CALLCONTRACTBIZ + isLocalTransaction:true，outTypes [\"string\"]），不打包、不耗 gas。");
        System.out.println("  三个方法参数全部是 string，直接按字符串数组传参（bytes32 才需要 32 个十进制数字的嵌套数组）。");
        System.out.println("  环境变量 REST_GAS 可覆盖默认 gas。");
    }

    static void need(List<String> pos, int n) {
        if (pos.size() != n) {
            System.out.println("!!! 参数个数不对：期望 " + n + " 个，实际 " + pos.size() + " 个");
            usage();
            System.exit(2);
        }
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

    // ---------------- 教研成果存证（register → registerArtifact） ----------------

    static void register(String accessId, String keyPath, String bizid, String account, String kmsId,
                         String tenantid, String contractName, String artifactId, String title,
                         String author, String school, String fileHash) throws Exception {
        // 冻结 ABI：registerArtifact(string,string,string,string,string)，参数序 = artifactId,title,author,school,fileHash
        String params = strArray(artifactId, title, author, school, fileHash);
        callWrite(accessId, keyPath, bizid, account, kmsId, tenantid, contractName,
                "registerArtifact(string,string,string,string,string)", params, "教研成果确权存证");
    }

    // ---------------- 教研活动留痕与学分折算（activity → recordActivity） ----------------

    static void activity(String accessId, String keyPath, String bizid, String account, String kmsId,
                         String tenantid, String contractName, String activityId, String teacherId,
                         String school, String effortMinutes) throws Exception {
        // 冻结 ABI：recordActivity(string,string,string,string)，参数序 = activityId,teacherId,school,effortMinutes
        // 合约同一次调用内完成：credit = 分钟×2 → creditOf[teacherId] 累加 → records 复合键留痕 → emit
        String params = strArray(activityId, teacherId, school, effortMinutes);
        callWrite(accessId, keyPath, bizid, account, kmsId, tenantid, contractName,
                "recordActivity(string,string,string,string)", params, "教研活动留痕与学分折算");
    }

    // ---------------- 写调用公共通道（CALLCONTRACTBIZASYNC 上链打包） ----------------

    static void callWrite(String accessId, String keyPath, String bizid, String account, String kmsId,
                          String tenantid, String contractName, String methodSignature,
                          String inputParamListStr, String bizLabel) throws Exception {
        PrivateKey key = loadKey(keyPath);
        String token = getToken(accessId, key);
        System.out.println(">>> 握手成功，已取得 token（有效期 30 分钟）");

        long gas = gasLimit(DEFAULT_CALL_GAS);
        String orderId = "order_" + System.currentTimeMillis();
        String json = "{"
                + "\"orderId\":" + esc(orderId) + ","
                + "\"bizid\":" + esc(bizid) + ","
                + "\"account\":" + esc(account) + ","
                + "\"contractName\":" + esc(contractName) + ","
                + "\"methodSignature\":" + esc(methodSignature) + ","
                + "\"inputParamListStr\":" + esc(inputParamListStr) + ","
                + "\"outTypes\":\"[]\","
                + "\"mykmsKeyId\":" + esc(kmsId) + ","
                + "\"tenantid\":" + esc(tenantid) + ","
                + "\"method\":\"CALLCONTRACTBIZASYNC\","
                + "\"accessId\":" + esc(accessId) + ","
                + "\"token\":" + esc(token) + ","
                + "\"gas\":" + gas + "}";

        System.out.println("=== " + bizLabel + "：调用合约 " + methodSignature + "（CALLCONTRACTBIZASYNC 异步上链）===");
        System.out.println("=== 参数 inputParamListStr = " + inputParamListStr + " ===");
        String resp = post(REST + "/api/contract/chainCallForBiz", json);
        System.out.println("=== 服务端原始响应 ===");
        System.out.println(resp);

        String txHash = extractTxHash(resp);
        if (txHash == null) {
            System.out.println("!!! 未取得交易哈希，调用可能未提交");
            System.exit(1);
        }
        System.out.println(">>> txHash = " + txHash);
        pollReceipt(accessId, bizid, token, txHash, 6, 5);
    }

    // ---------------- 学分查询（credit → getCreditFor，本地只读） ----------------

    static void credit(String accessId, String keyPath, String bizid, String account, String kmsId,
                       String tenantid, String contractName, String teacherId) throws Exception {
        PrivateKey key = loadKey(keyPath);
        String token = getToken(accessId, key);
        System.out.println(">>> 握手成功，已取得 token（有效期 30 分钟）");

        // 冻结 ABI：getCreditFor(string) view，返回 string；outTypes ["string"]
        String methodSignature = "getCreditFor(string)";
        String inputParamListStr = strArray(teacherId);
        String outTypesJson = "[\"string\"]";
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
                + "\"isLocalTransaction\":true,"
                + "\"mykmsKeyId\":" + esc(kmsId) + ","
                + "\"tenantid\":" + esc(tenantid) + ","
                + "\"method\":\"CALLCONTRACTBIZ\","
                + "\"accessId\":" + esc(accessId) + ","
                + "\"token\":" + esc(token) + ","
                + "\"gas\":" + gas + "}";

        System.out.println("=== 查询教师累计学分：调用合约 " + methodSignature
                + " method=CALLCONTRACTBIZ（本地执行/只读，不打包、不耗 gas）===");
        System.out.println("=== 参数 inputParamListStr = " + inputParamListStr + "  outTypes = " + outTypesJson + " ===");

        // 查询接口有频率限制：211 rate limit reached 时按固定间隔重试，最多 MAX_211_RETRY 次
        String resp = post(REST + "/api/contract/chainCallForBiz", json);
        int attempt = 1;
        while (isRateLimited(resp) && attempt < MAX_211_RETRY) {
            System.out.println("（提示：211 rate limit reached，等待 " + (RETRY_DELAY_MS / 1000)
                    + " 秒后重试，第 " + attempt + "/" + (MAX_211_RETRY - 1) + " 次）");
            Thread.sleep(RETRY_DELAY_MS);
            attempt++;
            resp = post(REST + "/api/contract/chainCallForBiz", json);
        }
        System.out.println("=== 服务端原始响应 ===");
        System.out.println(resp);

        // 本地查询：服务端把结果转义后放在 data 字符串里，先解开再取 outRes
        String inner = payload(resp);
        String outRes = jsonArrayField(inner, "outRes");
        if (outRes == null && inner != resp) {
            outRes = jsonArrayField(resp, "outRes");
        }
        if (outRes == null) {
            System.out.println("!!! 未取到 outRes，学分查询失败（服务端原始响应见上）");
            System.exit(1);
        }
        String result = jsonNumberField(inner, "result");
        String localHash = jsonStringField(inner, "txHash");
        System.out.println(">>> outRes = " + outRes);
        if (isTxHash(localHash)) {
            System.out.println(">>> localTxHash = " + localHash + "（本地执行，未打包上链）");
        }
        String creditVal = unwrapFirstString(outRes);
        if (creditVal != null) {
            System.out.println(">>> credit = " + creditVal);
        }
        if (result != null && !"0".equals(result)) {
            System.out.println("!!! 本地执行 result=" + result + "：查询失败");
            System.exit(1);
        }
        System.out.println(">>> 本地查询成功（isLocalTransaction=true，未打包、不耗 gas）");
    }

    // ---------------- 回执轮询（211 限流间隔重试） ----------------

    static void pollReceipt(String accessId, String bizid, String token, String txHash,
                            int rounds, int sleepSec) throws Exception {
        int valid = 0;    // 有效查询轮数（命中 211 限流的查询不计入轮数，重试补足）
        int hit211 = 0;   // 连续限流计数：连续 MAX_211_RETRY 次后暂停，避免死循环
        while (valid < rounds) {
            Thread.sleep(sleepSec * 1000L);
            String q = "{\"accessId\":" + esc(accessId) + ",\"bizid\":" + esc(bizid)
                    + ",\"method\":\"QUERYRECEIPT\",\"hash\":" + esc(txHash) + ",\"token\":" + esc(token) + "}";
            String r = post(REST + "/api/contract/chainCall", q);
            if (isRateLimited(r)) {
                hit211++;
                System.out.println("（第 " + valid + "/" + rounds + " 轮查询命中 211 rate limit"
                        + "，等待 " + (RETRY_DELAY_MS / 1000) + " 秒后继续重试）");
                if (hit211 >= MAX_211_RETRY) {
                    System.out.println(">>> 连续 " + hit211 + " 次 211 限流，暂停轮询；交易可能仍在打包，");
                    System.out.println("    可用交易哈希稍后自行重查：POST /api/contract/chainCall method=QUERYRECEIPT hash=" + txHash);
                    return;
                }
                Thread.sleep(RETRY_DELAY_MS);
                continue;
            }
            hit211 = 0;
            valid++;
            System.out.println("--- 回执查询 " + valid + "/" + rounds + "（服务端原始响应）---");
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
        }
        System.out.println(">>> 回执在 " + rounds + " 轮有效查询内未返回 txFinish=true；交易可能仍在打包，");
        System.out.println("    可用交易哈希稍后查询：POST /api/contract/chainCall method=QUERYRECEIPT hash=" + txHash);
    }

    // ---------------- 签名 / HTTP（与 RestDeployTool 同源） ----------------

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

    // ---------------- 小工具（与 RestDeployTool 同源） ----------------

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

    /** 211 rate limit 判定：限流响应的关键是 211 状态码（rate limit reached），不依赖其余结构 */
    static boolean isRateLimited(String r) {
        return r != null && (r.contains("\"code\":\"211\"")
                || r.contains("\"code\": 211")
                || r.contains("211 rate limit")
                || r.contains("rate limit reached"));
    }

    /**
     * 把若干字符串拼成 REST inputParamListStr：JSON 字符串数组，如 ["a","b","c"]。
     * 冻结 ABI 三入口参数全部是 string，直接按字符串传参——bytes32 才必须写成
     * 32 个十进制字节值的嵌套数组（那是别的合约的坑，本工具不用）。
     */
    static String strArray(String... items) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < items.length; i++) {
            if (i > 0) {
                sb.append(",");
            }
            sb.append(esc(items[i]));
        }
        return sb.append("]").toString();
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

    /**
     * 从 ["180"] 这种单元素字符串数组中解出首个字符串（按 JSON 规则反转义），
     * 形状不匹配（多元素 / 数字 / 非数组）时返回 null，调用方只作为加分打印、不影响主流程。
     */
    static String unwrapFirstString(String outRes) {
        String t = outRes == null ? null : outRes.trim();
        if (t == null || t.length() < 4 || !t.startsWith("[") || !t.endsWith("]")) {
            return null;
        }
        String inner = t.substring(1, t.length() - 1).trim();
        if (!inner.startsWith("\"")) {
            return null;
        }
        // 复用 jsonStringField 的扫描与反转义逻辑：把字面量原样接在 "x": 后面解出值
        return jsonStringField("{\"x\":" + inner, "x");
    }

    static String abbrev(String s, int max) {
        return s.length() > max ? s.substring(0, max) + "..." : s;
    }

    static String esc(String s) {
        return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"")
                .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + "\"";
    }
}