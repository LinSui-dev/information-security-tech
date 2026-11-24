# 三人联调细则（v1 的补充约束）

本文与 architecture、代码签名一起构成开发契约；出现冲突时先停止修改共享接口，由三人共同确认。本次补充后的接口作为基础阶段基线。

## 一、接口前置条件与所有权

- 成员一负责 `load_bmp` 的全部二进制校验；只有经它成功返回的对象或严格按同样规则生成的测试对象才能传给生产算法。数据类构造函数本身不验证文件，算法无需再实现一套 BMP 解析器。
- `save_bmp` 原样写出 `raw_bytes`，不重建 BMP 头；算法保证仅替换有效载体位。保存函数不增加扩展名、不弹覆盖确认、不自动创建父目录。路径问题交给 `OSError`。
- `iter_carrier_offsets` 必须产生恰好 `carrier_count` 个偏移：`pixel_offset + row_index * row_stride + byte_index`，`row_index=0..height-1`，`byte_index=0..width*channel_count-1`。
- `embed_text` 按 UTF-8 原样编码，不 strip、不归一化、不额外加换行；`extract_text` 返回的 payload 是正文，checksum 是已校验的帧头 CRC 整数。
- `encode_text` 只计算/校验正文；`pack_header` 只构造帧头；算法成员负责拼接二者和 CRC 校验。提取时捕获 UTF-8 解码失败并转换成 InvalidPayloadError。
- 类型标注以外的错误参数属于编程错误。GUI 正常输入的 Unicode 文本应可编码；出现孤立代理码时在 UI 提示编码错误，不将其视为 BMP 错误。
- UI 可以读取 `controller.state` 用于显示，但禁止直接写字段。所有变更通过控制器方法；UI 不直接导入 bmp/stego。
- `contracts.py` 的协议实现已提供，成员二负责维护它；models/errors 的修改须三人确认。不需要开发 SQLite 接口，schema 只用于可选扩展。

## 二、控制器精确状态转换

每个可能失败的方法先在局部变量中完成全部校验/IO，成功后一次性更新状态；失败不修改任何字段。state 中的 image 均不被原地修改。

| 方法 | 成功后的状态 | 失败/前置条件 |
| --- | --- | --- |
| open_source(path) | 设置 source/source_path；清空 stego、input_text、extracted_text、extracted_image、extracted_path；dirty=False；返回容量 | 读取失败全部保留 |
| set_input_text(text) | 与旧草稿相同则不变；不同则更新 input_text、清空 stego、dirty=False；保留提取结果 | UI 处理未保存载体的丢弃确认后才调用 |
| embed(text) | 基于 source 创建新 stego；input_text=text；dirty=True；清空 extracted_text/extracted_image/extracted_path | 无 source 抛 LabError；容量失败保留全部状态 |
| save_stego(path) | 写出 stego；dirty=False；不修改 source 和输入 | 无 stego 抛 LabError；IO 失败保留 dirty |
| extract_from(path) | 读取并校验正文后设置 extracted_image/path/text；清空 stego；dirty=False；保留 source/source_path/input_text；返回 ExtractionResult | 读取或解码失败全部保留；不要求已打开 source |
| get_source_preview() | 返回 source 的预览或 None，无状态变化 | 转换失败不修改状态 |
| get_result_preview() | stego 存在时返回其预览，否则返回 extracted_image 的预览，无图返回 None | 同上 |

`dirty` 只表示“存在尚未保存的嵌入载体”，不表示草稿或提取文本被编辑。本阶段不恢复草稿、不自动保存。

## 三、UI 事件与文件操作边界

- 输入区和提取区使用两个独立文本框；提取区只读。读取 Tk Text 输入使用 `get('1.0', 'end-1c')`，避免控件自动追加的末尾换行。
- 输入变更调用 set_input_text；若 dirty=True，先询问是否丢弃未保存载体。取消则还原控件文本，不调用控制器。刷新控件时屏蔽变更回调，避免递归。
- 打开原图、从文件提取、再次嵌入和退出之前若 dirty=True，UI 先做同样的丢弃确认；取消不执行操作。第一版只需“丢弃/取消”，用户可先取消并自行保存。
- 文件对话框取消时不调用控制器。保存对话框默认 `.bmp`，已有目标由 UI 确认覆盖；若目标解析后等于 source_path，拒绝保存并要求另存，避免覆盖原图。
- “嵌入”传入当前草稿；“提取”始终选择磁盘 BMP 并调用 extract_from，不读取内存 stego 或输入框。新进程无需打开原图即可提取。
- 右侧标题区分“嵌入结果”和“提取载体”；容量标签始终对应左侧 source，无 source 时显示“未加载”。提取成功不自动将载体当成新原图。
- 输入允许暂时超容，显示 UTF-8 已用字节/最大字节，超容时禁用嵌入按钮；算法仍必须二次检查。无 source 或帧头放不下也禁用嵌入；无 stego 禁用保存。
- 图像最大 512×512，可直接 1:1 预览，不做图像缩放。`PhotoImage(data=preview.ppm_bytes, format='PPM')`；保留 PhotoImage 引用以避免被回收。视觉摆放可调整，数据行为不能自行更改。
- 启动入口约定 `python -m lsb_lab.ui`，导入模块不得自动创建窗口。

## 四、BMP 字段与错误归类补充

文件头从 0 开始：签名 2 字节、bfSize（4）、保留字段（2+2）、bfOffBits（4）；DIB 从 14 开始，按 `<IiiHHIIiiII` 读取 40 字节。宽高有符号，其他按该格式解析。

先检查最少 18 字节以读取 DIB 长度；不是 BM/头部截断属于 InvalidBmpError，非 40 字节 DIB 属于 UnsupportedBmpError。40 字节 DIB 则要求文件至少 54 字节。检查 `bfSize == len(raw_bytes)`、像素区不越界；偏移至少 54（24 位）或 1078（8 位）。偏移前的额外间隔允许存在并保留。8 位调色板固定从 54 起读取 1024 字节。保留字段、调色板第四字节、分辨率和 biClrImportant 不参与支持判定，保持原样。

宽高为 0、像素区截断、偏移落入头或调色板、bfSize 不匹配、biSizeImage 非 0 且不等于 row_stride×height 属于 InvalidBmpError。其余超出支持范围的位深、planes、压缩、负宽、过大尺寸、宽非 4 倍数、调色板类型/数量属于 UnsupportedBmpError。无需对未知压缩算法继续按 BI_RGB 推导像素结构。

预览必须按真实行方向输出：top_down=True 时按原行顺序，否则反转行顺序；24 位每组三字节 BGR 转 RGB；灰度索引 i 输出 (i,i,i)。不含行填充。头部尺寸用 ASCII 十进制，固定格式 `b'P6\n' + f'{width} {height}\n255\n'.encode('ascii')`。

## 五、可交叉核验的测试基线

成员一维护标准库生成的测试夹具 `tests/bmp_factory.py`（仅测试用途）。并行开发时各自使用符合契约的测试桩，集成后共享真实夹具，不各自维护不同格式的生产解析器。夹具必须含非均匀像素，不能只用全零图验证方向。

| 测试输入 | 明确预期 |
| --- | --- |
| 16×8 灰度 | 128 位，16 总字节，3 正文字节；“中”成功，“中a”失败 |
| 8×8 真彩 | 192 位，24 总字节，11 正文字节 |
| 512×512 灰度/真彩 | 最大正文分别 32755/98291 字节 |
| 4×2 和 4×4 灰度，正式模式 | 容量不足；不能偷偷改为无帧模式 |
| 24 位首两个 BGR 像素 [0,1,2],[3,4,5] | 嵌入首字节 L（01001100）后，前六字节变成 [0,1,2,2,5,5] |
| UTF-8 往返 | 空串、中文、emoji、换行和末尾空格完全一致 |
| 嵌入再保存再重新读取 | 可正确提取；输入图 raw_bytes 保持原值 |
| 修改帧头魔数或版本 | InvalidPayloadError |
| 修改正文一个 LSB | CRC 校验失败，InvalidPayloadError |
| 保持正确 CRC 但正文非法 UTF-8 | InvalidPayloadError |
| 普通未嵌入图 | 测试夹具确保魔数不匹配，明确失败；不要声称所有随机图都不可能偶然匹配 |

教学小图的逐位测试由成员二写在 tests/test_stego.py 中，不增加 GUI 模式和公共 API：使用内部位写入辅助函数分别写 `b'?'`、`b'?S'`，由测试给定提取字节数 1/2，检查结果。辅助函数签名属于成员二内部实现，可自行决定，正式 embed_text/extract_text 不得调用无帧自动回退。

成员三负责 tests/test_controller.py 和 tests/test_integration.py，前者用 mock 覆盖全部状态转换及失败原子性，后者必须使用真实 bmp/stego 函数和临时磁盘文件。mock 测试通过不代表磁盘联调完成。GUI 截图和人工操作记录由成员三另存 output，不以单元测试代替。
