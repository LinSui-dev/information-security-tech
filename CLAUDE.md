# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

信息安全课程实验：LSB 信息隐藏（BMP 载体隐写），三人协作开发骨架。Python 3.11+，运行阶段仅标准库 + Tkinter；自行解析 BMP 二进制，**禁止引入 Pillow/OpenCV 等图片库**。支持未压缩 8 位灰度与 24 位真彩 BMP，≤512×512，宽为 4 的倍数。

BMP、LSB、控制器和 Tkinter UI 已实现。集成修复与验证范围见 docs/validation.md；基础运行和测试仅需标准库，GUI 测试需要桌面。

所有设计约束在 `docs/`：`architecture.md`（契约主文档）、`integration.md`（联调细则与验收向量，**冲突时优先级与 architecture 相同**）、`development.md`（分工）、`data-design.md`。修改共享接口前先阅读；出现冲突时停止修改，由三人共同确认。models/errors/contracts/docs 的修改须三人确认。

## 命令

```bash
# 初始化环境（无第三方依赖）
python -m venv .venv

# 全部测试（在仓库根目录）
python -m unittest discover -s tests -v

# 单个测试模块（用 -p 按文件名过滤）
python -m unittest discover -s tests -p test_contracts.py -v
python -m unittest discover -s tests -p test_bmp.py -v
# 注意：不要用 `python -m unittest tests.test_xxx` 包式调用——部分机器 site-packages
# 存在同名 `tests` 包会遮蔽本地目录；tests/ 下的测试文件导入夹具也须遵循
# bmp_factory.py docstring 中的导入约定。

# GUI 启动入口（必须以模块方式运行；导入 lsb_lab.ui 不得自动创建窗口）
python -m lsb_lab.ui
```

`tests/test_contracts.py` 只验证已实现的共享契约，通过不代表功能完成。

## 架构

### 依赖方向（硬性约束）

`ui → controller → bmp / stego → models / contracts / errors`

- `stego` 可调用 `bmp.iter_carrier_offsets`；`bmp` 不得反向依赖算法或界面。
- 核心算法不创建窗口、不弹对话框、不写文件；数据库不参与运行链路（`docs/schema.sql` 仅是后续可选扩展）。
- UI 只调用 controller 方法；可读 `controller.state` 用于显示，禁止直接写字段，禁止直接导入 bmp/stego。

### 文件归属（三人分工）

- 成员一：`bmp.py` + `tests/test_bmp.py` — BMP 读取/校验/保存/像素偏移遍历/PPM 预览
- 成员二：`stego.py` + `tests/test_stego.py` — LSB 嵌入提取、帧与容量控制（并维护 `contracts.py`）
- 成员三：`controller.py`、`ui.py`、`tests/test_controller.py`（mock）、`tests/test_integration.py`（必须用真实 bmp/stego 和临时磁盘文件；mock 通过不代表磁盘联调完成）

建议分支 `feat/bmp`、`feat/stego`、`feat/ui`，评审后合入 `main`。

### v1 数据帧格式（成员二实现，勿改动语义）

`b"LSB1"` + 版本 1（1 字节）+ 小端 uint32 正文长度 + 小端 CRC32 = 13 字节帧头，后接 UTF-8 正文。整帧按字节序写入，每字节先 bit7 后 bit0，修改公式 `(old & 0xFE) | bit`；只改实际占用位置，其余字节原样。容量 = `max(0, floor(载体位数/8) − 13)`，载体位数 = W×H（8 位）或 W×H×3（24 位），按 UTF-8 字节数而非字符数。载体位 < 104 时正式模式必须拒绝嵌入（含空文本）；不得为小图教学示例（4×2/4×4）取消长度字段或 CRC、不得做无帧回退。嵌入返回新 `BmpImage`（`dataclasses.replace`），绝不修改输入对象。

### BMP 解析边界（成员一实现）

只接受：`BM` 签名、40 字节 BITMAPINFOHEADER、`biPlanes=1`、`BI_RGB`、位深 8/24；宽为正且为 4 的倍数，宽/高绝对值 1–512；高度为负表示 top-down。以 `bfOffBits` 为像素起点（不硬编码 54）；`row_stride = ((width*bit_count+31)//32)*4`。8 位要求完整 256 项调色板且逐项 B=G=R=索引值。`raw_bytes` 保留整个文件，`save_bmp` 原样写出、不重建头部。`iter_carrier_offsets` 必须恰好产生 `carrier_count` 个偏移（`pixel_offset + row_index*row_stride + byte_index`，文件行顺序，忽略行填充）。预览输出 P6 PPM 字节，按视觉行方向、BGR→RGB 或灰度 (i,i,i)，不含填充。字段级错误归类细则见 `docs/integration.md` 第四节。

### 错误语义

- 格式损坏/非 BMP → `InvalidBmpError`；有效但超支持范围 → `UnsupportedBmpError`；超容 → `CapacityError`；帧标记/版本/长度/CRC/UTF-8 解码失败 → `InvalidPayloadError`；控制器状态错误（无原图嵌入、无载体保存）→ `LabError`；系统 IO 保持 `OSError`。
- 类型标注以外的错误参数属于编程错误，不应静默吞掉。

### 控制器状态机

每个可能失败的方法先在局部变量中完成全部校验/IO，成功后一次性更新状态；失败不修改任何字段，不能先清空再尝试。`dirty` 仅表示"存在尚未保存的嵌入载体"。精确状态转换表见 `docs/integration.md` 第二节；UI 事件与文件操作边界（丢弃确认、`get('1.0', 'end-1c')`、禁止覆盖 source_path 等）见第三节。

### 测试基线

可交叉核验的验收向量见 `docs/integration.md` 第五节（如 24 位首两像素 [0,1,2],[3,4,5] 嵌入首字节 `L` 后前六字节变 `[0,1,2,2,5,5]`；512×512 灰度/真彩最大正文 32755/98291 字节）。测试夹具 `tests/bmp_factory.py` 由成员一提供、三人共享，必须含非均匀像素。

## 阶段范围

基础阶段不含噪声、JPEG、剪裁、带密钥扩展（后续课程必做）；无数据库依赖，不开发 SQLite 接口。UTF-8 编码原样处理（不 strip、不归一化、不加换行）；孤立代理码由 UI 提示编码错误，不视为 BMP 错误。
