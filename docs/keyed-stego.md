# 带密钥的随机间隔 LSB（KLS1 协议）

成员二的“必做扩展”实现说明。代码在 `lsb_lab/keyed_stego.py`，测试在 `tests/test_keyed_stego.py`。
本协议是为课程实验自行设计的，**不是标准算法**，也没有复现某篇论文；与顺序 LSB v1 相互独立，
不修改、不复用 v1 的标记与帧格式。界面接入由集成负责人后续完成。

## 1. 接口

通过 `from lsb_lab import keyed_stego` 调用，全部函数不读写文件、不弹窗。

```python
def capacity_for_keyed(image: BmpImage) -> Capacity
def embed_text(image: BmpImage, text: str, *, key: str,
               salt: bytes | None = None) -> BmpImage
def extract_text(image: BmpImage, *, key: str) -> ExtractionResult
def payload_positions(image: BmpImage, *, key: str) -> tuple[int, ...]
```

| 情况 | 结果 |
| --- | --- |
| key 不是非空 str；text 不是 str（含孤立代理码）；显式 salt 不是恰 16 字节 | `ValueError` |
| 图像放不下合法空消息，或正文超过 `max_payload_bytes` | `CapacityError` |
| 帧标记/版本/长度不合法、密钥错误、帧内容损坏、正文不是合法 UTF-8 | `InvalidPayloadError` |

- key 原样按 UTF-8 编码，不 strip、不归一化；明文密钥不写入载体。
- `salt=None` 时用 `secrets.token_bytes(16)` 生成；显式盐只用于可复现测试。
- 嵌入返回 `dataclasses.replace` 构造的新图，输入图与一切非占用字节保持不变。
- `extract_text` 返回的 `ExtractionResult.checksum` 是帧内已认证的正文 CRC32，语义与 v1 一致。

## 2. 协议（冻结）

### 2.1 帧与通道布局

“逻辑通道索引”是 `bmp.iter_carrier_offsets` 产生顺序中的序号（0 ～ 载体数−1）。
帧的每个字节按先 bit7 后 bit0 写入，每个位占用一个通道的 LSB，修改公式 `(old & 0xFE) | bit`。

| 帧内偏移 | 长度 | 含义 |
| --- | --- | --- |
| 0 | 4 | ASCII `KLS1`（与 v1 的 `LSB1` 无关） |
| 4 | 1 | 版本 1 |
| 5 | 16 | 盐 |
| 21 | 4 | 正文字节数，无符号小端 |
| 25 | 4 | 正文 CRC32，无符号小端 |
| 29 | 16 | 标签 tag = HMAC-SHA256 截断的前 16 字节 |
| 45 | N | UTF-8 正文，无终止符 |

前 45 字节称为 **bootstrap**，固定占用逻辑通道 0 ～ 359；之后是 N 字节正文，第 i 个正文位
（i = 0 ～ 8N−1）写入通道 `pos(i)`。bootstrap 与正文位置不可能重叠。

### 2.2 密钥派生与位置规则

记 `K = UTF8(key)`，`P = b"KLS1" + 0x01`（标记加版本，作域分隔）。

1. 流密钥 `K_pos = HMAC-SHA256(K, P + b"pos" + salt)`。
2. keystream 第 j 块 = `HMAC-SHA256(K_pos, j)`，其中 j 写成 8 字节无符号大端；各块首尾相接，
   第 i 字节 `ks[i]` 取第 `⌊i/32⌋` 块的第 `i mod 32` 字节。
3. `pos(i) = 360 + 8×i + (ks[i] mod 8)`。

正文位按固定分组散布：第 i 组是通道 `[360 + 8i, 360 + 8i + 7]`，每组由密钥流在其中选 1 个通道。
由此得到以下保证：

- **唯一、不重叠、不越界**：各组互不相交且都从通道 360 起，所以位置必然唯一、升序并与 bootstrap 无关；
  只要 `8N ≤ ⌊(载体数 − 360)/8⌋`，最大位置不超过 `360 + 8×8N − 1 ≤ 载体数 − 1`。
- **间隔**：相邻两位的间隔 `pos(i+1) − pos(i)` 在 1 ～ 15 之间（期望 8），即确实存在被跳过的通道，
  而不是把连续位置重新排序。约 1/8 的可用通道承载正文位。
- **均匀性**：把 HMAC 输出字节视为均匀，8 整除 256，所以 `ks[i] mod 8` 精确均匀。
- **最后不完整分组**：剩余通道数不是 8 的倍数时，末尾不足 8 个的通道直接不用。
- **可重现性**：只依赖 `hashlib`/`hmac`，不使用 `hash()` 或任何随机模块；跨进程、跨平台一致。
  位置由 key、盐、版本和位序号共同决定，与图像无关（只受容量约束）；短正文的位置是长正文位置的前缀。

### 2.3 标签

`K_mac = HMAC-SHA256(K, P + b"mac" + salt)`，
`tag = HMAC-SHA256(K_mac, 帧内偏移 0 ～ 28 的元数据 + 正文)[0:16]`。

标签覆盖盐、长度、CRC 和全部正文；验证使用 `hmac.compare_digest`。空正文同样计算和验证标签，
所以错误密钥对空消息也失败。错误密钥被接受的概率约为 2⁻¹²⁸，不声称数学上绝不碰撞。

### 2.4 容量

```text
剩余通道 spare = max(0, 载体数 − 360)
max_payload_bytes = spare // 8 // 8
can_store_header  = 载体数 ≥ 360          # 能否保存合法空消息
header_bytes      = 45                    # 完整帧的固定元数据字节总数
```

容量只由图像和协议参数决定，对任何合法 key/salt 都成立。与 v1 相比正文容量约为其 1/8：

| 图像 | 通道数 | v1 最大正文 | KLS1 最大正文 |
| --- | --- | --- | --- |
| 16×8 灰度 | 128 | 3 | 放不下（can_store_header=False） |
| 32×16 灰度 | 512 | 51 | 2 |
| 64×32 灰度 / 真彩 | 2048 / 6144 | 243 / 755 | 26 / 90 |
| 256×256 真彩（共享样例） | 196608 | 24563 | 3066 |
| 512×512 灰度 / 真彩 | 262144 / 786432 | 32755 / 98291 | 4090 / 12282 |

### 2.5 嵌入、提取与位置查询

嵌入：校验参数 → 按容量拒绝超容 → 生成盐、元数据、标签 → 把 `元数据 + 标签 + 正文` 的位依次写入
通道 `0..359` 与 `pos(0..8N−1)`。其余字节（含被跳过通道）逐字节不变。

提取按以下顺序，任一步失败抛 `InvalidPayloadError`，不修改任何状态：

1. 载体数 < 360 → 拒绝。
2. 读出 bootstrap，检查标记与版本。
3. 声明长度 > `max_payload_bytes` → 拒绝（**读取不可信长度之前先做边界检查**）。
4. 按 `pos(i)` 读出正文位。
5. 验证标签（`compare_digest`）。错误密钥会定位到错误的正文位，必然在此失败。
6. 核对 CRC32。标签已覆盖 CRC 字段与正文，这一步只是冗余核对，不提供安全保证。
   先验标签是因为先比 CRC 会把“密钥错误”误报成“CRC 校验失败”。
7. 严格 UTF-8 解码。

`payload_positions` 只执行第 1～3 步，然后按嵌入顺序返回正文位置的逻辑通道索引（升序元组，
不含 bootstrap）。它不读取正文、不验证标签，**不能单独证明密钥正确**：错误密钥同样返回一组
“结构合法”的位置而不报错。它的用途是让分析工具统计受损正文；完整鉴别由 `extract_text` 负责。

## 3. 设计依据

### 3.1 实际查阅的资料

以下条目均核对过题名、作者、年份和出处（Crossref / Semantic Scholar / 出版方页面），
并阅读了“阅读范围”一列注明的内容，日期为 2026-11-25。

| 资料 | 链接 | 阅读范围 | 借鉴点 |
| --- | --- | --- | --- |
| R. J. Anderson, F. A. P. Petitcolas. On the limits of steganography. IEEE JSAC 16(4):474–481, 1998 | [DOI](https://doi.org/10.1109/49.668971)、[作者版 PDF](https://www.cl.cam.ac.uk/archive/rja14/Papers/jsac98-limsteg.pdf) | 摘要、引言 | 隐写隐藏的是消息的存在；嵌入通常由密钥参数化；对手分被动观察和主动修改两类 |
| J. Fridrich, M. Goljan, R. Du. Reliable detection of LSB steganography in color and grayscale images. Proc. ACM Workshop on Multimedia and Security 2001, pp. 27–30 | [DOI](https://doi.org/10.1145/1232454.1232466)、[作者版 PDF](http://ws2.binghamton.edu/fridrich/Research/ACMwrkshp_version.pdf) | 全文 | RS 分析能检测随机散布的 LSB 嵌入（摘要称短至 0.03 bpp）；嵌入越少痕迹越小；针对“值对”的攻击对顺序嵌入有效，对随机散布要消息长度与像素数相当才可靠 |
| N. Provos, P. Honeyman. Detecting Steganographic Content on the Internet. CITI Technical Report 01-11, 2001 | [PDF](http://citi.umich.edu/u/provos/papers/detecting.pdf) | 摘要、引言 | 其检测框架包含字典攻击环节；启示是密钥（口令）强度直接决定嵌入位置是否保密 |
| T. Sharp. An Implementation of Key-Based Digital Signal Steganography. Information Hiding (IH 2001), LNCS 2137, Springer, pp. 13–26, 2001 | [DOI](https://doi.org/10.1007/3-540-45496-9_2) | 出版方摘要页 | 用隐写密钥生成伪随机样本序列；把被动看守者的攻击作为设计约束 |
| H. Krawczyk, M. Bellare, R. Canetti. HMAC: Keyed-Hashing for Message Authentication. RFC 2104, 1997 | [rfc-editor.org](https://www.rfc-editor.org/rfc/rfc2104) | 头部、摘要、引言 | 采用 HMAC 作为带密钥的派生与认证原语 |
| M. Nystrom. Identifiers and Test Vectors for HMAC-SHA-224/256/384/512. RFC 4231, 2005 | [rfc-editor.org](https://www.rfc-editor.org/rfc/rfc4231) | §4.2 测试向量 1 | HMAC-SHA-256 的外部已知答案，用于检验本模块的原语调用 |
| D. Eastlake 3rd, J. Schiller, S. Crocker. Randomness Requirements for Security. RFC 4086, 2005 | [rfc-editor.org](https://www.rfc-editor.org/rfc/rfc4086) | 摘要 | 安全用途的随机量应来自密码学安全的随机源；RFC 4086 全文没有讨论“盐”，盐在本协议中的用途属于下面的自研决定 |
| Python 3.11 标准库文档：`hmac.compare_digest`、`secrets` | [hmac](https://docs.python.org/3.11/library/hmac.html)、[secrets](https://docs.python.org/3.11/library/secrets.html) | 对应条目 | 验证时用 `compare_digest` 避免基于内容的短路比较；盐用 `secrets` 而非 `random` 生成 |

未采用的资料：van Schyndel 等（1994）、Bender 等（1996）、Chan 与 Cheng（2004）的题录经 Crossref 核对无误，
但没有读到摘要或全文，因此不引用其内容。中文文献常说的“随机间隔法”只检索到博客等二手描述，
没有找到可核实的原始出处，本文不把它归到任何一篇论文。

### 3.2 文献方法与本设计的区分

| 来源 | 属于文献中已有的做法 | 本设计自行决定的部分 |
| --- | --- | --- |
| 位置保密 | 用密钥驱动伪随机序列决定嵌入位置（Sharp 2001） | bootstrap 固定占前 360 通道；每 8 个通道一组、组内取 `ks[i] mod 8`；间隔界限 1～15 |
| 抗分析 | 散布并降低嵌入率能减少统计痕迹，但不保证不可检测（Fridrich 等 2001） | 选择 1/8 的嵌入率；不做任何不可检测性声明 |
| 认证 | HMAC（RFC 2104） | 子密钥派生的标签与盐拼接方式；标签截断为 16 字节；标签覆盖全部元数据 |
| 威胁模型 | 被动/主动看守者（Anderson 与 Petitcolas 1998） | 只把“无密钥者难以定位正文”作为目标；不承诺抵抗主动修改 |

组内选点而不是“每位之前累加一个随机间隔”，原因后者无法保证容量：间隔之和可能超出图像，
而容量必须对所有密钥和盐成立。分组规则以 8 倍的容量损失换取这一保证。

## 4. 安全边界与限制

- **随机位置不是加密。** 正文以 UTF-8 明文位写入；bootstrap 是明文结构，前 32 个通道的 LSB 就是 `KLS1`，
  任何人都能看出该图使用了带密钥模式并读出盐和正文长度。
- **不抗压缩、噪声和剪裁。** 帧内任何一位翻转都会导致提取失败（测试逐一翻转验证），没有纠错编码。
- **不抗统计分析。** 本协议修改约 1/8 的通道 LSB 加固定前缀 360 个通道；Fridrich 等的 RS 分析
  报告的检测下限远低于这一嵌入率，不应宣称肉眼不可察觉就等于不可检测。
- **依赖密钥强度，且未做口令拉伸。** 攻击者知道协议后可用猜测的密钥读 bootstrap、算标签来离线验证，
  每次猜测只需少量 HMAC 运算。应使用足够长的随机密钥。
- **盐不是秘密。** 它的作用是让同一密钥与正文在不同次嵌入中得到不同位置和标签；不用于提高口令强度。
- **错误密钥与载体损坏不可区分。** 两者都在标签验证处失败，提示文案应写“密钥错误或帧已损坏”。
- **`payload_positions` 不做鉴别**（见 2.5）。
- CRC32 只是冗余核对与结果字段来源，没有安全意义。

## 5. 测试与验证

环境：Windows 11，Python 3.13.12，仅标准库。在 `feat/keyed-stego` 分支的仓库根目录执行：

```bash
python -m unittest discover -s tests -p test_keyed_stego.py -v   # Ran 31 tests ... OK
python -m unittest discover -s tests -v                          # Ran 123 tests ... OK
```

123 = 基线 92 项 + 本模块 31 项，含基础 v1、BMP、控制器和 3 项 Tk 控件测试（本机有图形桌面，已执行）。
基线运行时出现的 `ResourceWarning` 在改动前即存在，与本模块无关。

| 类别 | 覆盖内容 |
| --- | --- |
| 独立已知向量 | HMAC 原语对照 RFC 4231；位置对照附录 A 的 V1/V2；完整帧对照 V3；全 0 像素图上的 bootstrap 原始位对照 V4 |
| 往返 | 灰度/真彩 × 正/负高度 × 空串、中文、emoji、换行、制表符、尾空格、100 字节 |
| 确定性与盐 | 同图/key/salt 载体逐字节相同；新盐改变载体；默认盐每次不同且可提取；`bytearray`/`memoryview` 盐等价 |
| 真实磁盘与独立进程 | 保存到磁盘后由子进程读取提取（含 gap 与尾部字节）；子进程错误密钥失败；共享样例 `samples/lsb-demo-256x256.bmp` |
| 密钥 | 7 种错误密钥（含空消息）全部 `InvalidPayloadError` |
| 容量 | 8 组手算值；恰好上限可写、多 1 字节拒绝；62 组不同 key/salt 在上限均可嵌入；小图拒绝 |
| 参数 | 空/非字符串 key、15/17 字节盐、非字节盐、非字符串文本、孤立代理码 → `ValueError` |
| 位置规则 | 升序唯一、不越界、不占 bootstrap、每组恰取一位、间隔 1～15 且确有跳过；组内偏移近似均匀；与视觉方向无关；依赖 key 与盐 |
| 占用范围 | 只有 bootstrap 与正文位置的 LSB 变化，其余字节逐字节不变 |
| 损坏 | bootstrap 360 位逐一翻转、正文每一位逐一翻转均失败；帧外 LSB 与次低位变化可容忍 |
| 互操作 | v1 与 KLS1 帧互不可读，v1 行为未变 |

限制：项目要求 Python 3.11+，本机只有 3.13，未在 3.11/3.12 上实际运行；代码没有使用 3.11 之后的语法或接口。
单次非正式计时：512×512 灰度嵌入并提取 4089 字节约 0.07 秒，真彩 12282 字节约 0.18 秒，未做系统性能测试。
本轮没有实验材料需要归档，测试均使用临时目录。

## 附录 A：独立参考实现与已知向量

下面的参考实现与 `keyed_stego.py` 分开编写，只用 `hashlib/hmac/struct/zlib`，不导入 `lsb_lab`。
测试中的向量由它生成并硬编码；`tests/test_keyed_stego.py` 的读位函数也不经过被测模块的内部代码。

```python
import hashlib, hmac, struct, zlib
MAGIC = b"KLS1"

def positions(key, salt, n):
    stream_key = hmac.new(key.encode("utf-8"), MAGIC + b"\x01pos" + salt, hashlib.sha256).digest()
    def byte(i):
        block = hmac.new(stream_key, (i // 32).to_bytes(8, "big"), hashlib.sha256).digest()
        return block[i % 32]
    return [360 + 8 * i + byte(i) % 8 for i in range(n)]

def tag(key, salt, payload):
    prk = hmac.new(key.encode("utf-8"), MAGIC + b"\x01mac" + salt, hashlib.sha256).digest()
    meta = struct.pack("<4sB16sII", MAGIC, 1, salt, len(payload), zlib.crc32(payload))
    return hmac.new(prk, meta + payload, hashlib.sha256).digest()[:16], meta
```

| 向量 | 输入 | 输出 |
| --- | --- | --- |
| V0 | HMAC-SHA256，key = `0b`×20，data = `"Hi There"` | `b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7`（RFC 4231） |
| V1 | key `vector-key-1`，盐 `00…0f`，前 64 位 | 360 372 379 386 392 404 410 419 424 437 445 454 458 468 474 480 494 496 508 513 525 531 543 550 553 560 573 578 586 593 602 613 619 624 633 647 648 658 665 674 687 688 703 707 717 720 733 738 751 758 763 772 783 786 796 800 812 822 829 837 843 852 860 868 |
| V2 | key `向量密钥🔑`，盐 `ff`×16，前 16 位 | 363 372 377 391 395 405 414 416 428 439 446 455 458 470 479 486 |
| V3a | `vector-key-1`，盐 `00…0f`，正文 `Hi` | 帧十六进制 `4b4c533101000102030405060708090a0b0c0d0e0f020000000e0e174d1378261a890222071b49ae00b42c3ba54869` |
| V3b | 同上，空正文 | `4b4c533101000102030405060708090a0b0c0d0e0f000000000000000076247c61d3b41b8f9d0c13d7599944f4` |
| V3c | `向量密钥🔑`，盐 `ff`×16，正文 `中\n` | `4b4c533101ffffffffffffffffffffffffffffffff04000000618d6848092bc7f51aabe208efb05dc75f88e6a7e4b8ad0a` |

## 附录 B：待集成事项

1. 控制器与界面尚未接入本模块（本轮约定不改）。界面需要密钥输入（不回显）和模式切换；
   容量显示在带密钥模式下应改用 `capacity_for_keyed`。
2. 错误密钥与载体损坏不可区分，建议界面提示统一为“密钥错误或帧已损坏”。
3. 成员一的分析工具若要统计正文位置，`payload_positions` 返回升序逻辑通道索引，可直接传给
   `compare_lsb_positions`；它不验证密钥，统计结果的解释需由调用方说明。
4. 测试只在 Python 3.13.12 上执行过，见第 5 节。
5. 未发现需要修改共享模型、异常或 v1 协议的契约问题。
