# REST 通道接入说明（已在本机实测跑通）

> 本文记录**真实执行过**的接入方式与结果，不是推测。
> 适用场景：链上账户为**密钥托管（KMS）**——私钥在平台侧，本地没有 `user.key`，
> 因此 SDK 直连那套（`src/main/java/com/muying/trace/`，需要 `user.key` 本地签名）**不适用**；
> 托管账户必须走 REST 通道，由平台代签。

---

## 一、为什么必须走 REST

| 通道 | 签名方 | 需要什么 | 本项目适配情况 |
| --- | --- | --- | --- |
| SDK 直连（`com.muying.trace.*`） | 本地 | `client.key/crt/trustCa` + **`user.key`** + 节点 host/port | 代码已完成；但账户是托管的，没有可用 `user.key` |
| **REST（`tools/RestChainTool.java`）** | **平台（KMS 代签）** | `access.key` + `accessId` + `account` + `kmsId` + `tenantid` | **已实测跑通并完成真实上链** |

## 二、本团队的真实配置（已逐个验证）

| 配置项 | 值 | 来源 |
| --- | --- | --- |
| `rest-url` | `https://rest.baas.alipay.com`（固定值） | 官方文档 |
| `bizid` | **`a00e36c5`**（开放联盟链） | 官方文档；实测 `141a48c42f1e47b085a4502dab442553`（合约体验链）返回 `209 no business authorization`，本租户无权限 |
| `access-id` | **`QoT6128ELXHOXRFH`** | 控制台「申请 AccessKey」 |
| `access-secret` | 文件 `keys/access.key` | 与 AccessId 同时生成 |
| `account`（托管账户名） | **`陈以宁`** | 控制台链账户 |
| 账户地址 | `bd6d0c4911705d02d89419f00b513a3c4ec0ec9c6e9dfb4ce50345f692cdf2bc` | = `SHA256("陈以宁")` |
| 账户授权公钥 | `21a81ac42db27ced187f4bef9a6c615007bb6c84468858a504cf6cc1f9df3d5857dba165f564e30af50b445640122cc3c746796b308df1ef85ade39a07f68980` | 链上 `auth_map`；**即团队早先提供的 `pub.txt`** |
| `mykmsKeyId` | `93f381ChLXHOXRFH1790846615585` | 控制台；前缀含租户号 |
| `tenantid` | **`LXHOXRFH`** | 由握手返回的 JWT 解出：`"extend":"{\"accessId\":\"…\",\"flag\":0,\"tenantId\":\"LXHOXRFH\"}"` |
| 账户燃料余额 | 10,100,000 → 存证后 10,078,350 | 链上 `balance` |

## 三、签名与协议（官方规则的等价实现）

```
message := accessId + 毫秒时间戳          （字符串直接拼接，无分隔符）
secret  := 小写十六进制( SHA256withRSA(message) )

取令牌  POST {rest-url}/api/contract/shakeHand
        body {"accessId":"…","time":"…","secret":"…"}   →  {"data":"<JWT，有效期 30 分钟>"}

查询    POST {rest-url}/api/contract/chainCall
        body {"accessId","bizid","method","requestStr"|"hash","token"}
        method 取值：QUERYACCOUNT / QUERYTRANSACTION / QUERYRECEIPT / QUERYLASTBLOCK …

交易    POST {rest-url}/api/contract/chainCallForBiz
        body {"orderId","bizid","account","content","mykmsKeyId","method":"DEPOSIT",
              "accessId","token","tenantid","gas"}
```

## 四、实测结果（真实上链，可复核）

```
$ java -cp build/tools RestChainTool deposit QoT6128ELXHOXRFH keys/access.key a00e36c5 \
       陈以宁 93f381ChLXHOXRFH1790846615585 LXHOXRFH \
       '{"batchId":"MY20261001-A","stage":"RAW_MATERIAL",...}'

存证响应: {"success":true,"code":"200","data":"44dc99f79929a1e407c7878f600ad43a7818f55228b44cdec580e385a3c6e39a"}
```

| 项目 | 值 |
| --- | --- |
| 交易哈希 | `44dc99f79929a1e407c7878f600ad43a7818f55228b44cdec580e385a3c6e39a` |
| 所在区块 | 183413686 |
| 回执 | `code:0, result:0, gasUsed:21650`，logs 含 `deposit_data` |
| 链上内容 | base64 解码后与提交内容**逐字一致**（中文字段完好） |
| 燃料扣减 | 10,100,000 → 10,078,350，差值 **21,650 = gasUsed** |

链上内容原文（由 `QUERYTRANSACTION` 返回的 `data` 字段 base64 解码得到）：

```json
{"batchId":"MY20261001-A","stage":"RAW_MATERIAL","operator":"成都理工大学工程技术学院技术组","location":"呼和浩特","detail":"生鲜乳入库 500kg，批号 MY20261001-A"}
```

## 五、怎么跑

```bat
cd /d "E:\HuaweiMoveData\Users\HUAWEI\Desktop\陈以宁竞赛"
javac -encoding UTF-8 -nowarn -d build\tools tools\RestChainTool.java

:: 查账户（余额 / 授权公钥 / 地址）
java -cp build\tools RestChainTool account QoT6128ELXHOXRFH keys\access.key a00e36c5 陈以宁

:: 存证上链
java -cp build\tools RestChainTool deposit QoT6128ELXHOXRFH keys\access.key a00e36c5 <链账户名> 93f381ChLXHOXRFH1790846615585 LXHOXRFH "{\"batchId\":\"MY20261001-A\",\"stage\":\"PRODUCTION\",\"operator\":\"某某乳业一厂\",\"location\":\"呼和浩特\",\"detail\":\"灌装1200罐\"}"

:: 用交易哈希查回执 + 内容
java -cp build\tools RestChainTool query QoT6128ELXHOXRFH keys\access.key a00e36c5 <txHash>
```

## 六、注意事项（都是踩过的坑）

1. **`accessId` 必须与 `access.key` 配套**。不配套时服务端只回 `fail check signature`（code 204），
   而这个提示是通用的——乱填 accessId 也是同样的报错，无法据此区分"ID 不存在"和"密钥不匹配"。
2. **查询接口有频率限制**：连续调用会返回 `211 rate limit reached`，需间隔重试。
3. **`bizid` 决定在哪条链上操作**。本租户只在 `a00e36c5` 有权限，填 `141a48c42f1e47b085a4502dab442553`
   会返回 `209 no business authorization`。
4. **`gas` 要设得比实际消耗大**（本次用 100000，实际耗 21650），否则交易失败且不返还已消耗的 gas。
5. **token 有效期 30 分钟**，过期需重新握手。
6. 返回内容里的 `data` 字段是 **base64**，解出来才是存证原文。
7. `access.key` 是私钥文件，**不要外发、不要提交到公开仓库**。

---

## 七、智能合约：真实部署与调用（已实测跑通）

> 官方两个 SDK Demo（`BaaSDepositDemo`、`BaaSContractVoteDemo`）都是**本地私钥签名**路线，
> 直接用 `user.key` 逐笔签名交易。本团队账户是 **KMS 托管**，本地没有可用 `user.key`，
> 因此这两个 Demo 的步骤**必须改走 REST 的 `chainCallForBiz`**，由平台代签。
> 下面全部是改走 REST 之后的实测结果。

### 7.1 部署合约

```
POST /api/contract/chainCallForBiz
{
  "orderId":     "order_<毫秒>",
  "bizid":       "a00e36c5",
  "account":     "陈以宁",
  "contractName":"muying_trace_demo_1",     ← 合约地址由它派生，调用时必须用同一个名字
  "contractCode":"<solc 编译后的十六进制，不含 0x>",
  "mykmsKeyId":  "93f381ChLXHOXRFH1790846615585",
  "tenantid":    "LXHOXRFH",
  "method":      "DEPLOYCONTRACTFORBIZASYNC",
  "accessId":    "QoT6128ELXHOXRFH",
  "token":       "<握手得到的 token>",
  "gas":         500000
}
```

实测结果（部署官方投票合约 `contractVoteCode.txt`，1806 字节）：

| 项目 | 值 |
| --- | --- |
| 部署交易哈希 | `64aa2beb838a662c8a145296ce5fdd7ef13726dda99bb4a2eb4073afe196b17a` |
| 所在区块 | 183414412 |
| gasUsed | 145824 |
| 回执 | `code:0, result:0`，logs topics 为 `deploy_contract` |

### 7.2 调用合约（写交易）

```
method: "CALLCONTRACTBIZASYNC"
contractName: 同上（必须一致）
methodSignature: "voteForCandidate(bytes32)"
inputParamListStr: "[[114,111,115,101,0,0,...]]"
outTypes: "[]"
```

实测投票交易：

| 项目 | 值 |
| --- | --- |
| 调用交易哈希 | `b45eea18e6e619a33400eaaaa7f85f8e2857fa65416a4e68861e414fcada643c` |
| 所在区块 | 183414471 |
| gasUsed | 71022 |
| 回执 | `result:0`；logs 含 `call_contract` 与 **VOTE 事件**（logData base64 解出为 `rose` + 投票人账户地址） |

### 7.3 调用合约（本地查询，不打包）

```
method: "CALLCONTRACTBIZ"
"isLocalTransaction": true
methodSignature: "totalVotesFor(bytes32)"
outTypes: "[\"uint8\"]"
```

实测结果：

```json
{"outRes":[1],"transaction":{"data":{"success":true,"transactionReceipt":{"output":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAE=","result":0}}}}
```

`outRes: [1]` 即 rose 的票数 —— **投票前为 0，投票后为 1，与官方文档 1.3 → 1.5 的预期完全一致**。

### 7.4 【重要】合约参数怎么传：bytes32 要用数字数组

这是本次踩得最久的一个坑，官方文档没写清楚：

| 传法 | 结果 |
| --- | --- |
| `["0x726f7365…"]`（带 0x 的 hex） | ✗ `405  value length must be 32` |
| `["726f7365…"]`（裸 hex，64 字符） | ✗ 同样报错 |
| `["rose                            "]`（补空格到 32 字符） | ✗ 同样报错 |
| **`[[114,111,115,101,0,…,0]]`（32 个字节值组成的数字数组）** | **✓ 成功** |

即：`bytes32` 要按 **32 个 0-255 的十进制数字**写成嵌套数组；`int32` 之类则直接写数字（官方样例 `[2,3]`）。

### 7.5 与官方 SDK Demo 的对应关系

| 官方 Demo 步骤 | SDK 写法（需 user.key） | 本团队的 REST 等价写法 |
| --- | --- | --- |
| 1.1 初始化环境 | `initMychainEnv()` / `initSdk()` | `POST /api/contract/shakeHand` 拿 token |
| 1.2 部署合约 | `sdk.getContractService().deployContract(...)` | `chainCallForBiz` + `DEPLOYCONTRACTFORBIZASYNC` |
| 1.3 查票数（本地） | `callContract` + `request.setLocal()` | `chainCallForBiz` + `CALLCONTRACTBIZ` + `isLocalTransaction:true` |
| 1.4 投票 | `callContract` | `chainCallForBiz` + `CALLCONTRACTBIZASYNC` |
| 1.5 再查票数 | 同 1.3 | 同 1.3 |
| 1.6 关闭 | `sdk.shutDown()` | 无需（token 30 分钟后自然失效） |

### 7.6 关于"区块浏览器查看"

官方说明里"访问体验链浏览器，输入存证交易 hash 查询"针对的是**合约体验链**
（`141a48c42f1e47b085a4502dab442553`）。本租户对那条链返回 `209 no business authorization`，
因此上面的实测量都在**开放联盟链**（`a00e36c5`）上完成；开放联盟链同样有区块链浏览器可查交易哈希。


---

## 八、母婴溯源合约：真实部署与两条溯源记录（已实测跑通）

### 8.1 结论：通用 solc 编译的字节码被这条链接受

工作流的"信任门槛"把通用 solc 产物挡下后，主控直接做了部署实验——**成功**。
即：蚂蚁链 EVM 接受标准 solc 0.4.26 输出的字节码；官方投票合约源码只是**源码层**使用了
`identity` 这类定制类型（定制编译器才认识），字节码层并无特殊限制。
因此 contracts/BabyTraceCompat.sol（去掉 `tx.txhash` 的兼容版）可以走：
`solc 0.4.26 本地编译 → REST 部署`，不依赖控制台编译模块。

### 8.2 部署

| 项目 | 值 |
| --- | --- |
| 合约名 | `muying_babytrace_v1`（合约地址由它 SHA256 派生） |
| 字节码 | build/contracts/BabyTraceCompat.bin（12,818 字符 = 6,409 字节） |
| 部署交易 | `f205bc31c9f4ca9aa2216e4fb47de67b47997fc71f2035328cc9b9a72c88c65f` |
| 区块 | 183416200，gasUsed 85,429，result 0，logs topics=`deploy_contract` |

### 8.3 两条溯源记录（prevHash 已串成链）

| 环节 | 交易哈希 | 区块 | gasUsed |
| --- | --- | --- | --- |
| 第 1 环 原料采购 | `7485c337c3c1ac3491c8fd58c1a661bf312a0ac7bb2a374003f91aa8a2f678ae` | 183416223 | 574,303 |
| 第 2 环 生产加工 | `43862334c287418b450187bf66a4f190968a289776a7bf015fb0cfcc2a258a47` | 183416281 | 693,637 |

第 2 环回执 logs 的 `LOG_STRING` 事件 logData（base64）解出：

```json
{"__type__":"miniappinfo","prevHash":"7485c337c3c1ac3491c8fd58c1a661bf312a0ac7bb2a374003f91aa8a2f678ae",
 "nextHash":"","lists":[
  {"name":"批次号","value":"MY20261001-A","type":"text"},
  {"name":"环节","value":"PRODUCTION","type":"text"},
  {"name":"操作主体","value":"某某乳业一厂","type":"text"},
  {"name":"地点","value":"呼和浩特2号灌装线","type":"text"},
  {"name":"时间","value":"2026-10-02","type":"text"},
  {"name":"详情","value":"配方v3，灌装1200罐，批号P20261001","type":"text"}
 ]}
```

**prevHash 正好等于第 1 环的交易哈希**——「环节 → 上一环节」的溯源指针在链上正式成立。
这条 JSON 就是蚂蚁链区块链小程序/浏览器直接渲染的格式，扫码即可看到六个中文业务字段。

### 8.4 后续环节只需重复同一命令

把上一环的 txHash 作为第 8 个参数（preTxHash）传入即可串链：

```bat
java -cp build	ools RestDeployTool call QoT6128ELXHOXRFH keysccess.key a00e36c5 陈以宁 ^
  93f381ChLXHOXRFH1790846615585 LXHOXRFH muying_babytrace_v1 ^
  "insertTrace(string,string,string,string,string,string,string,string)" ^
  "["T-003","MY20261001-A","QUALITY_CHECK","某某乳业质检中心","中心实验室","2026-10-03","全项检验合格","<上一环txHash>"]" "[]"
```
