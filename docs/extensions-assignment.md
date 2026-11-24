# 必做扩展：两人并行分工

## 范围与共同起点

本轮只开发随机噪声/分析工具及带密钥的随机间隔 LSB。两人从最新远程 main 的同一提交开始（必须包含基础功能集成提交 `b3ac91d` 和本轮分工文档），在各自克隆目录或独立 worktree 开发，不等待对方提交。开始前执行 fetch 并记录共同基线 SHA，不能从旧骨架开发。

不得改变原有顺序 LSB v1 协议，不重写 BMP 解析，不使用图片处理库。Python 3.11+，标准库实现；沿用 BmpImage、Capacity、ExtractionResult 和既有异常。

| 人员 | 分支 | 独占文件 |
| --- | --- | --- |
| 成员一 | feat/noise-analysis | lsb_lab/noise.py、lsb_lab/analysis.py、tests/test_noise.py、tests/test_analysis.py、docs/noise-experiment.md |
| 成员二 | feat/keyed-stego | lsb_lab/keyed_stego.py、tests/test_keyed_stego.py、docs/keyed-stego.md |
| 集成负责人 | 后续统一集成 | controller.py、ui.py、共享文件、README、跨模块测试 |

两位成员本轮不编辑 UI、控制器、共享模型/异常/协议、其他人的文件或已有测试。不增加运行依赖。模块新增数据类定义在各自独占模块内；发现共同契约问题记录并交集成负责人，不自行修改。双方先完成独立算法和测试，界面接入属于后续统一集成工作。

## 成员一：随机噪声与分析

### 公共接口

```python
# noise.py
@dataclass(frozen=True)
class NoiseResult:
    image: BmpImage
    selected_channels: int
    changed_channels: int

def add_random_noise(image: BmpImage, *, ratio: float,
                     amplitude: int = 1, seed: int = 0) -> NoiseResult: ...

# analysis.py
@dataclass(frozen=True)
class ComparisonMetrics:
    channel_count: int
    changed_channels: int
    mse: float
    psnr_db: float | None
    lsb_error_count: int
    lsb_error_rate: float

def compare_images(before: BmpImage, after: BmpImage) -> ComparisonMetrics: ...

def compare_lsb_positions(before: BmpImage, after: BmpImage,
                          positions: Iterable[int]) -> tuple[int, int, float]: ...

def export_metrics(path: str | Path, records: Sequence[dict]) -> None: ...
```

### 确定的语义

- 噪声按有效像素通道字节选择位置：使用局部 `random.Random(seed)`，无放回抽样 `floor(carrier_count × ratio)` 个；ratio 必须是有限数且在 [0,1]，amplitude 为 1～255 整数（bool 不算整数）。非法配置抛 ValueError。
- 每个选中通道独立生成 [-amplitude, amplitude] 范围内、不含 0 的均匀整数扰动，再裁剪到 [0,255]；边界裁剪可能使实际改变数少于选中数，分别报告。不得只翻 LSB 来冒充一般噪声。
- 返回新图，不修改输入；头部、调色板、填充、间隔、尾部保持不变。随机种子用于复现实验，不代表密码学安全。
- compare_images 要求宽、高、位深及 top_down 相同；不相同抛 ValueError，不自动裁剪、对齐或转换。允许 pixel_offset 不同，各按自己的偏移读取。只比较有效通道，MSE 的分母是通道数，PSNR 为 10×log10(255²/MSE)。MSE=0 时 psnr_db=None，文档说明表示正无穷；便于严格 JSON 导出。
- lsb_error_rate 是全图有效通道 LSB 不同数量/通道数，不能标为正文位错误率。
- compare_lsb_positions 额外支持正文/帧特定位置统计。positions 是逻辑通道索引（0～carrier_count-1），不是文件偏移；索引须唯一且合法，空集合返回 (0,0,0.0)，其他返回 (错误位数,比较位数,错误率)。图像兼容条件同上。
- export_metrics 写 UTF-8 JSON，ensure_ascii=False、allow_nan=False；不建父目录、不添加扩展名。记录由调用者提供，注明模式、种子、ratio、amplitude、图像类型、正文长度及提取是否成功。数据库和隐藏明文无需写入。
- analysis 不依赖 keyed_stego；算法成功率由实验脚本/测试调用现有 stego.extract_text，捕获 InvalidPayloadError 得出。新增模块本身不弹窗。

### 验收

两类图、正负高度；同种子结果一致，不污染全局随机状态；ratio=0、ratio=1、边界像素、非法参数；输入与非像素区不变；MSE/PSNR/LSB 指标用手算小例验证；选定位置统计和 JSON 导出可重读验证。

用已有 v1 嵌入后的真实 BMP 做噪声实验。建议 ratio=1%、5%、10%，amplitude=1，每组至少 5 个种子；保留无噪声对照。导出真实数据，记录像素指标、全图及已知帧位置错误率、提取结果，不能保证每组必然提取失败或成功。核对预览，说明噪声数量和整体画质，不能只凭 PSNR 宣称肉眼不可察觉。

## 成员二：带密钥的随机间隔 LSB

### 公共接口

```python
def capacity_for_keyed(image: BmpImage) -> Capacity: ...
def embed_text(image: BmpImage, text: str, *, key: str,
               salt: bytes | None = None) -> BmpImage: ...
def extract_text(image: BmpImage, *, key: str) -> ExtractionResult: ...
def payload_positions(image: BmpImage, *, key: str) -> tuple[int, ...]: ...
```

通过 `from lsb_lab import keyed_stego` 调用，不覆盖基础 stego。salt=None 时使用标准库 secrets 生成 16 字节盐；显式 salt 必须恰为 16 字节，用于可复现测试。不记录或嵌入明文密钥；key 不能为空，原样 UTF-8 编码，不 strip。非法参数抛 ValueError，超容抛 CapacityError，帧/长度/校验/错误密钥抛 InvalidPayloadError。

### 算法必须说明的决策

成员二自行设计并在 docs/keyed-stego.md 中冻结完整新协议：独立 magic 和版本、固定长度 bootstrap、16 字节 salt、长度字段、校验/密钥验证开销、位置生成顺序及位序。不能修改 v1 或复用其标记。bootstrap 占据固定前缀通道，其余通道供随机间隔正文使用，二者不得重叠。

- 必须是真正有跳过位置的“随机间隔”方法，而非仅对连续全部位置重新排序。给出明确的最大/最小间隔、唯一位置和越界处理规则。
- 容量只由图像和协议参数决定，不依赖密钥或盐；任何有效 key/salt 在宣称容量以内均可嵌入。建议使用固定大小分组、组内由密钥选点等能保证容量的方法，并明确最后不完整分组如何处理。
- 位置生成由密钥、盐及协议版本确定；使用标准库 hashlib/hmac 等实现稳定的派生规则，不依赖 Python hash() 或未注明版本的随机行为。定义跨进程可重现的字节到整数映射和取样规则。
- 使用 HMAC-SHA256（可明确截断长度）验证密钥及帧内容，包含关键元数据；使用 hmac.compare_digest。可同时保留正文 CRC32，并填入 ExtractionResult.checksum。空正文也应验证密钥。错误密钥以极高概率失败，不声称数学上绝不碰撞。
- 不声称随机嵌入等于加密，也不声称自动抗 JPEG、噪声或剪裁。正文可保持 UTF-8 明文编码，本轮不另加加密功能。
- 返回不可变新图，只改占用 LSB。提取不需要原图；读取不可信长度前先做边界检查。
- payload_positions 解析 bootstrap 并验证其结构和声明长度，按嵌入顺序返回正文承载位置的逻辑通道索引，不含固定 bootstrap；不验证正文完整性，使实验工具可统计受损正文。文档明确它不能单独证明密钥正确；完整提取才负责鉴别。
- capacity_for_keyed 的 header_bytes 表示完整帧的固定元数据字节总数（含 salt、MAC、CRC 等），max_payload_bytes 必须考虑随机间隔造成的通道损耗，不能直接套用 v1 的减 13 公式；can_store_header 表示是否能保存合法空消息。

### 验收

两类图和正负高度；空串、中文、emoji、换行及尾空格；同图/key/salt 生成完全相同载体；新盐改变载体；正确密钥跨进程提取；错误密钥失败；容量恰好和超容；小图拒绝；bootstrap/正文/MAC 损坏失败；位置唯一、不越界、有跳过、与固定前缀不重叠；原图和非占用字节保持不变；旧 v1 基础测试继续通过。

按要求查阅并引用实际读过的文献/原始资料，区分文献方法与自己设计的部分。记录题名、作者、年份、链接及借鉴点，不捏造来源；课程没有规定必须复现某篇论文，不将自己的实现称为标准算法。

## 提交与统一验收

两人分别运行 `python -m unittest discover -s tests -v`；若无图形桌面，另运行 `python -m unittest discover -s tests -p test_noise.py -v` 等自己的测试，并明确 GUI 测试未执行。新增测试均采用 unittest，不引入 pytest 依赖。

提交并推送自己的分支，不合并或推送 main。最终回复包含提交 SHA、文件清单、接口和协议摘要、实际测试命令/结果、未完成项、实验材料位置。双方都完成后，由集成负责人统一合并，检查协议、接入界面并执行真实磁盘联调。

JPEG 转换仍按课程要求使用“画图”，无需开发 JPEG 编解码器；剪裁分析及实践验证另行安排，不混入本轮代码职责。
