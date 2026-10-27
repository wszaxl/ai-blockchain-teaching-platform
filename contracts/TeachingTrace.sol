pragma solidity ^0.4.20;

/*
 * AI+区块链区域协同教研平台 · 教研可信存证与学分互认合约（teaching_platform_v1）
 * —— contracts/TeachingTrace.sol：面向通用 solc 编译、REST 通道部署的合约文件。
 *
 * 【本合约在方案中的位置】《docs/教研平台/01-产品设计与实现方案.md》：
 *   - 第 2 节  双层架构中「区块链联盟链层」的落点：成果确权存证 / 贡献留痕 / 学分互认 / 审计追溯
 *              四件事全部由本合约承载；
 *   - 第 4 节  四大区块链应用点的链上动作载体：registerArtifact 对应 4.1 教研成果上链存证与确权，
 *              recordActivity 对应 4.2 智能合约自动统计贡献、4.3 跨校教研学分互认，
 *              getCreditFor 对应 4.3 的查询侧（本地只读、不耗 gas）；
 *   - 第 5.3 节 上链数据分析图两张「业务记录卡片」的字段来源（miniappinfo lists 键名与取值）；
 *   - 第 6 节  上链数据设计的落地实现：6.1 Artifact → achievements 表，6.2 Record → records 表，
 *              6.3 学分表 → creditOf 表；
 *   - 第 7 节  冻结 ABI（7.1）、编译兼容性硬约束（7.3）、学分折算算法（7.4）、
 *              错误与回滚语义（7.5）的原样实现；
 *   - 第 9 节  落地映射第 3~6 行：deploy / register / activity / credit 四类链上调用。
 *
 * 【与 contracts/BabyTraceCompat.sol 的关系】
 *   风格与写法逐字沿用 BabyTraceCompat：同一套 strings 最小化拼接库（只保留 slice/memcpy/toSlice/concat
 *   四段实际用到的函数）、setJsonKV/setItem/tableLog 三件套、LOG_STRING(string) 事件、
 *   mapping(string => struct) 主键存储。BabyTraceCompat 已由通用 solc 0.4.26 编译通过并经 REST 通道
 *   真实部署、真实调用（miniappinfo 链上回执解码通过），本合约只替换业务字段与业务逻辑，写法风险不变。
 *
 * 【与 BabyTraceCompat 的有意差异】（全部由 01 方案第 7.3 节条款定死，勿改动）
 *   1) 冻结 ABI 没有 prevHash 入参位 → tableLog 输出里的 prevHash / nextHash 恒为空串 ""：
 *      教研业务的时序溯源不依赖哈希指针链，而依赖链上交易本体（txHash / 区块 / 时间戳天然有序）
 *      加上业务主键（artifactId、activityId|teacherId）查询；
 *   2) 去掉 utils 库（compare_string / bytesToHexString 本合约均无调用需求，按需最小化内嵌）；
 *   3) 新增两段自写算法（solc 0.4 无内建 string↔uint 转换）：strToUint、uintToStr；
 *   4) 全程无 require / assert 断言（01 方案 7.5 定版）：非法分钟数（空串 / 含非数字字符）
 *      折算 0 学分，但活动记录照常留痕，异常输入本身也留在链上供审计。
 *
 * 编译：solc 0.4.26（pragma ^0.4.20 范围内），全程不使用任何蚂蚁链扩展（tx.txhash 之类一律不用）。
 */

library strings {
    // 字符串切片：记录一段字符串的长度与内存起始地址，让内存拼接按指针进行、无需反复新建拷逐字节拷。
    struct slice {
        uint _len;   // 切片长度（字节数）
        uint _ptr;   // 切片指向的内存起始地址
    }

    // 功能：把 src 起始的 len 字节拷贝到 dest（solc 0.4 无内建 memcpy，需 assembly 自写）。
    // 算法：先按 32 字节整块拷贝（每个 EVM word 一次 mload + mstore），
    //       不足 32 字节的尾巴用掩码按位合并，避免覆盖 dest 该位置上的原有字节。
    function memcpy(uint dest, uint src, uint len) private pure {
        for (; len >= 32; len -= 32) {       // 整字循环：每轮处理 32 字节，len 递减
            assembly {
                mstore(dest, mload(src))     // 读出 src 一个字，原样写入 dest
            }
            dest += 32;                      // 目标指针后移一个 word
            src += 32;                       // 源指针后移一个 word
        }
        uint mask = 256 ** (32 - len) - 1;   // 掩码：低 (32-len) 个字节为 0，其余字节为 1
        assembly {
            let srcpart := and(mload(src), not(mask))  // 取源字里要拷的高位部分
            let destpart := and(mload(dest), mask)     // 保留目标字里不被覆盖的低位部分
            mstore(dest, or(destpart, srcpart))        // 两部分按位或合并后写回
        }
    }

    // 功能：把 string 转成 slice（string 变量本身不暴露内容指针，需 assembly 取地址）。
    // 核心逻辑：string 的内存布局 = [长度槽][内容字节…]，内容首地址 = 变量地址 + 0x20。
    function toSlice(string self) internal pure returns (slice) {
        uint ptr;
        assembly {
            ptr := add(self, 0x20)           // 跳过 [长度] 槽，指向内容首字节
        }
        return slice(bytes(self).length, ptr); // 长度取 bytes(self).length，指针取刚算出的地址
    }

    // 功能：把两个切片首尾拼接成一个新 string（本合约 JSON 拼接的唯一底层操作）。
    // 核心逻辑：按两段总长 new 一块内存，先拷前段 self、再紧接其尾拷后段 other。
    function concat(slice self, slice other) internal pure returns (string) {
        string memory ret = new string(self._len + other._len); // 按两段总长分配新字符串
        uint retptr;
        assembly { retptr := add(ret, 32) }  // 取 ret 的 [长度] 槽之后的实际内容地址
        memcpy(retptr, self._ptr, self._len);               // 拷贝第一段（self）
        memcpy(retptr + self._len, other._ptr, other._len); // 紧接其后拷贝第二段（other）
        return ret;
    }
}

contract teaching_platform_v1 {

    // 数据展示事件：miniappinfo JSON 通道，蚂蚁链浏览器 / 小程序按 __type__=miniappinfo 解析渲染。
    event LOG_STRING(string);

    // using-for 声明：让 string / slice 类型直接以成员语法调用 strings 库（.toSlice()/.concat()）。
    using strings for *;

    // ---------- 上链数据结构（对应 01 方案第 6 节上链数据设计） ----------

    // 教研成果记录：对应 01 方案 6.1 Artifact；五个字段全部为 string（冻结 ABI 决定）。
    struct Artifact {
        string artifactId; // 成果编号：平台业务主键，形如 ART-YYYY-序号，全链唯一
        string title;      // 标题：教案/课件/课例/纪要/诊断报告的标题
        string author;     // 作者：第一作者（署名权主体）
        string school;     // 学校：作者所属学校（确权归属校）
        string fileHash;   // 文件哈希：SHA-256(成果文件原文) 的 64 位十六进制小写
    }

    // 教研活动参与记录：对应 01 方案 6.2 Record；
    // effortMinutes 保存调用方传入的原始字符串（含异常输入也原样保留，审计可见原始输入本身）。
    struct Record {
        string activityId;    // 活动编号：教研活动主键，形如 ACT-YYYY-序号
        string teacherId;     // 教师：参与教师唯一标识（跨校通用）
        string school;        // 学校：教师本次活动所属学校
        string effortMinutes; // 贡献分钟：发言/参与贡献时长的原始字符串（不裁剪、不改写）
        uint   credit;        // 折算学分：= strToUint 结果 × 2（转换失败时为 0）
    }

    // 成果主表：键 = artifactId，同编号重复登记 = 覆盖更新（后登记者覆盖先登记内容）。
    mapping (string => Artifact) achievements;

    // 活动记录表：键 = activityId + "|" + teacherId 复合键（同一活动多名教师各存一条，互不覆盖）。
    mapping (string => Record) records;

    // 教师学分表：键 = teacherId，值为该教师跨校累计学分（每次记录只加不减）。
    mapping (string => uint) creditOf;

    // ---------- 内部工具：拼 miniappinfo JSON（setJsonKV/setItem 与 BabyTraceCompat 逐字同源） ----------

    // 功能：往 JSON 里追加一个 "key":"value" 键值对。
    // 核心逻辑：逐段 concat 出 左引号+键+右引号冒号左引号+值+右引号；isEnd=false 时结尾补项间逗号。
    function setJsonKV(string json, string key, string value, bool isEnd) private pure returns (string) {
        json = json.toSlice().concat("\"".toSlice());    // 追加左引号
        json = json.toSlice().concat(key.toSlice());     // 追加键名
        json = json.toSlice().concat("\":\"".toSlice()); // 追加 右引号+冒号+左引号
        json = json.toSlice().concat(value.toSlice());   // 追加键值
        json = json.toSlice().concat("\"".toSlice());    // 追加右引号
        if (!isEnd) {                                    // 非末项时补分隔符
            json = json.toSlice().concat(",".toSlice()); // 追加项间逗号
        }
        return json;
    }

    // 功能：往 lists 数组追加一个展示项 {"name":"..","value":"..","type":".."}。
    // 核心逻辑：花括号内按序拼 name/value/type 三个键值对，type 固定传 "text"（业务字段全部文本展示）。
    function setItem(string json, string key, string value, string itype, bool isEnd) private pure returns (string) {
        json = json.toSlice().concat("{".toSlice());            // 追加项起始花括号
        json = setJsonKV(json, "name", key, false);    // 拼 "name":"字段中文名"
        json = setJsonKV(json, "value", value, false); // 拼 "value":"字段值"
        json = setJsonKV(json, "type", itype, true);   // 拼 "type":"text"
        json = json.toSlice().concat("}".toSlice());            // 追加项结束花括号
        if (!isEnd) {                                            // 非末项时补分隔符
            json = json.toSlice().concat(",".toSlice());         // 追加项间逗号
        }
        return json;
    }

    /*
     * 成果日志：输出 registerArtifact 的 miniappinfo 展示 JSON。
     * 载荷结构固定：__type__/prevHash/nextHash 三键 + lists[成果编号/标题/作者/学校/文件哈希]。
     * prevHash/nextHash 恒为空串：冻结 ABI 无入参位（01 方案 7.3 条款 2），
     * 时序溯源依赖链上交易本体（txHash/区块/时间戳天然有序）与成果编号查询，不依赖哈希指针链。
     */
    function tableLogArtifact(string artifactId) private {
        string memory json = "{";                              // JSON 起始花括号
        Artifact storage a = achievements[artifactId];         // 读刚写入的状态（先写后日志，日志即最终态）
        json = setJsonKV(json, "__type__", "miniappinfo", false); // 展示格式标记（蚂蚁链渲染约定）
        json = setJsonKV(json, "prevHash", "", false);        // 恒为空串（无入参位）
        json = setJsonKV(json, "nextHash", "", false);        // 恒为空串（无入参位）
        json = json.toSlice().concat("\"lists\":[".toSlice()); // lists 数组开始
        json = setItem(json, "成果编号", a.artifactId, "text", false); // 键名顺序=01 方案 5.3 卡片 A
        json = setItem(json, "标题",   a.title,      "text", false);
        json = setItem(json, "作者",   a.author,     "text", false);
        json = setItem(json, "学校",   a.school,     "text", false);
        json = setItem(json, "文件哈希", a.fileHash,  "text", true);  // 末项不补逗号
        json = json.toSlice().concat("]}".toSlice());          // lists 数组与根对象收尾
        emit LOG_STRING(json);                                 // 发事件：浏览器/小程序据此渲染业务字段
    }

    /*
     * 活动日志：输出 recordActivity 的 miniappinfo 展示 JSON，入参 key = "activityId|teacherId" 复合键。
     * 载荷结构固定：__type__/prevHash/nextHash 三键 + lists[活动编号/教师/学校/贡献分钟/折算学分]。
     * 其中「折算学分」是 uint 类型字段，经 uintToStr 转成十进制字符串再拼入（lists 内全部文本展示）。
     */
    function tableLogActivity(string key) private {
        string memory json = "{";                              // JSON 起始花括号
        Record storage r = records[key];                       // 读刚写入的记录（先写后日志）
        json = setJsonKV(json, "__type__", "miniappinfo", false); // 展示格式标记（蚂蚁链渲染约定）
        json = setJsonKV(json, "prevHash", "", false);        // 恒为空串（无入参位）
        json = setJsonKV(json, "nextHash", "", false);        // 恒为空串（无入参位）
        json = json.toSlice().concat("\"lists\":[".toSlice()); // lists 数组开始
        json = setItem(json, "活动编号", r.activityId, "text", false); // 键名顺序=01 方案 5.3 卡片 B
        json = setItem(json, "教师",     r.teacherId,  "text", false);
        json = setItem(json, "学校",     r.school,     "text", false);
        json = setItem(json, "贡献分钟", r.effortMinutes, "text", false); // 展示原始分钟串（不隐藏异常输入）
        json = setItem(json, "折算学分", uintToStr(r.credit), "text", true); // uint→字符串，末项不补逗号
        json = json.toSlice().concat("]}".toSlice());          // lists 数组与根对象收尾
        emit LOG_STRING(json);                                 // 发事件：浏览器/小程序据此渲染业务字段
    }

    // ---------- 内部工具：string ↔ uint 手工转换（01 方案 7.3 条款 3：自写并逐行注明算法） ----------

    /*
     * 功能：把十进制数字字符串转成 uint。
     * 算法：从左到右逐字符累加——result = result × 10 + 当前位值（高位在前）。
     * 失败语义（01 方案 7.5 定版）：空串或出现任一非 '0'~'9' 字符 → 整体返回 0
     * （不 require、不抛错，由调用方 recordActivity 按 0 学分继续处理）。
     * 注意：0.4 版无溢出检查，数十位以上超长"数字串"会使 result×10 静默回绕；
     *       业务侧（贡献分钟）量级很小，走不进溢出区间，此处不做额外校验。
     */
    function strToUint(string s) private pure returns (uint result) {
        bytes memory b = bytes(s);             // 字符串的字节视图，b.length 即字符数
        for (uint i = 0; i < b.length; i++) {  // 逐字符校验并累加（空串时循环不执行，result 保持 0）
            byte c = b[i];                     // 当前字符字节
            if (c < 0x30 || c > 0x39) {        // 非 '0'(0x30)~'9'(0x39) 区间 = 非法输入
                return 0;                      // 立即取 m=0（整体失败，不保留已累加的部分值）
            }
            result = result * 10 + (uint(uint8(c)) - 0x30); // 高位在前：累加进位并加当前位值
        }
        // 空串：for 循环体一次都不执行，result 恒为初始 0，与失败语义一致（空串=0）
    }

    /*
     * 功能：把 uint 转成十进制字符串（供 getCreditFor 返回与 miniappinfo 展示；solc 0.4 无内建此转换）。
     * 算法：先反复除 10 数出位数，再分配同样长度的字节缓冲，
     *       从低位到高位逐位取 v%10 映射成 '0'~'9' 字符、从缓冲末尾向左回填。
     */
    function uintToStr(uint v) private pure returns (string) {
        if (v == 0) {                          // 特殊值：0 没有任何位数，直接返回固定结果
            return "0";                        // 未经任何活动的教师查到 "0"
        }
        uint len = 0;                          // 十进制位数计数器
        uint tmp = v;
        while (tmp > 0) {                      // 数位循环：直到除数归零
            tmp /= 10;                         // 去掉最低位
            len++;                             // 位数 +1
        }
        bytes memory b = new bytes(len);       // 分配恰好 len 字节的缓冲区
        uint i = len;                          // 写入游标：从缓冲区末尾向左填
        while (v > 0) {                        // 回填循环：共执行 len 次，游标不会为负
            i--;                               // 游标左移一位
            b[i] = byte(uint8(48 + v % 10));   // 取当前最低位(0~9) 映射到 ASCII '0'~'9' 写入
            v /= 10;                           // 丢弃已写出的最低位
        }
        return string(b);                      // bytes→string 显式转换（0.4 合法写法）
    }

    // ---------- 对外方法（冻结 ABI 三入口，参数顺序不得变动） ----------

    /*
     * 入口 A：教研成果确权存证（01 方案 4.1 / 7.1 ①）。
     * 功能：把成果五字段（编号/标题/作者/学校/文件哈希）落进链上状态 achievements，
     *       并 emit 一条 LOG_STRING(miniappinfo) 供浏览器/小程序展示与审计取数。
     * 核心逻辑：先组装完整结构体并写入 mapping，再执行 tableLogArtifact——严格
     *           「先写状态、后发日志」，保证事件载荷就是本次调用的最终链上状态。
     */
    function registerArtifact(
        string artifactId,   // 成果编号（业务主键，全链唯一）
        string title,        // 标题
        string author,       // 作者（署名权主体）
        string school,       // 学校（确权归属校）
        string fileHash      // 文件哈希：SHA-256(成果文件原文) 的 64 位十六进制小写
    ) public {
        Artifact memory a;               // 内存中组装新记录
        a.artifactId = artifactId;       // 成果编号
        a.title = title;                 // 标题
        a.author = author;               // 作者
        a.school = school;               // 学校
        a.fileHash = fileHash;           // 文件哈希
        achievements[artifactId] = a;    // 按编号落库；同编号重复登记=覆盖更新
        tableLogArtifact(artifactId);    // 先写后日志：日志内容即链上最终状态
    }

    /*
     * 入口 B：教研活动参与记录（01 方案 4.2 / 4.3 / 7.1 ②）。
     * 功能：按 activityId+teacherId 复合键留痕一条参与记录，并在同一次调用内
     *       完成"分钟→学分"折算（minutes×2）与累加进教师学分表 creditOf，
     *       最后 emit LOG_STRING(miniappinfo)。
     * 核心逻辑（执行顺序固定，勿改动）：
     *    1) strToUint(effortMinutes) 取 m：非法串折 0（不 require、不回滚，见 01 方案 7.5）；
     *    2) credit = m × 2：统一折算口径"贡献 1 分钟 = 2 学分"固化在合约里，
     *       任何学校调用同一公式即实现跨校互认；
     *    3) creditOf[teacherId] += credit：有累加先落账，保证日志里能看到最新累计口径的本次折算；
     *    4) 复合键 key = activityId + "|" + teacherId：同一活动多名教师各存一条，互不覆盖；
     *    5) 写记录、再日志：事件载荷 = 本次调用的最终链上状态。
     */
    function recordActivity(
        string activityId,     // 活动编号（教研活动主键）
        string teacherId,      // 教师（唯一标识，跨校通用）
        string school,         // 学校（教师本次活动所属学校）
        string effortMinutes   // 贡献分钟数（原始字符串；非法输入折算 0 学分但照常留痕）
    ) public {
        uint m = strToUint(effortMinutes);     // 第 1 步：字符串→uint，失败（空串/非数字）返回 0
        uint credit = m * 2;                   // 第 2 步：统一折算口径——贡献 1 分钟 = 2 学分
        creditOf[teacherId] += credit;         // 第 3 步：累加进教师学分表（仅增不减）
        string memory key = activityId.toSlice().concat("|".toSlice()); // 第 4 步：拼复合键前半段
        key = key.toSlice().concat(teacherId.toSlice());                //       续上教师 = "活动|教师"
        Record memory r;                       // 内存中组装参与记录
        r.activityId = activityId;             // 活动编号
        r.teacherId = teacherId;               // 教师
        r.school = school;                     // 学校
        r.effortMinutes = effortMinutes;       // 原始分钟串原样保存（异常输入审计可见）
        r.credit = credit;                     // 本次折算学分（m=0 时此处为 0）
        records[key] = r;                      // 第 5 步：复合键留痕（同键重复调用=覆盖并再次累加，见脚注 4）
        tableLogActivity(key);                 // 先写后日志：日志内容即本次调用的最终链上状态
    }

    /*
     * 入口 C：教师累计学分查询（01 方案 4.3 / 7.1 ③）。
     * 功能：返回某教师在 creditOf 中的跨校累计学分。
     * 核心逻辑：view 只读——不产生交易、不消耗 gas、不改变任何链上状态；
     *           累计值是 uint 类型，经 uintToStr 转成十进制字符串返回，
     *           方便 REST 本地只读通道以 outTypes ["string"] 直接取用。
     */
    function getCreditFor(string teacherId) public view returns (string) {
        // 缺省值语义：从未参与记录的教师 mapping 默认 0 → 返回 "0"
        return uintToStr(creditOf[teacherId]); // 取累计学分并转为十进制字符串（如 "180"）
    }
}

/*
 * 说明（与合约正文一一对应，供部署与调用方查阅）：
 * 1) 三个入口全部使用 string 参数：调用时按顺序传字符串即可，REST 通道直接以字符串数组传参，
 *    避开 bytes32 必须写成 32 个十进制数字嵌套数组的实测坑（01 方案 9 节"参数编码注意"）。
 * 2) 入参顺序（冻结 ABI，不得变动）：
 *    registerArtifact：artifactId, title, author, school, fileHash
 *    recordActivity   ：activityId, teacherId, school, effortMinutes
 *    getCreditFor     ：teacherId
 * 3) recordActivity 的复合键 = activityId + "|" + teacherId；同一教师在同一活动被再次调用时，
 *    记录被覆盖、学分再次累加（合约把"每次调用"视为一次参与事实，幂等去重由平台侧业务主键负责）。
 * 4) 错误与回滚语义（01 方案 7.5 定版）：本合约无 require/assert、无转账与扣款逻辑；
 *    effortMinutes 为空串或含非数字字符 → 折算 0 学分，记录照常留下（原始分钟串原样可见）；
 *    registerArtifact 对任意字符串（含空串）都原样存证——输入校验是平台侧职责，不是链上职责。
 * 5) gas 量级参考：BabyTraceCompat 的 insertTrace（8 个 string）实测 57~69 万 gas；
 *    本合约 registerArtifact（5 个 string）/recordActivity（4 个 string）同量级，
 *    调用 gas 上限沿用 1,000,000（01 方案 9 节）。
 * 6) getCreditFor 的 string 出参经 REST 本地只读（CALLCONTRACTBIZ + isLocalTransaction:true）
 *    为本交付序列的待实测项——本地只读通道本身已有 uint8 出参实测先例（01 方案 9 节第 6 行）。
 */