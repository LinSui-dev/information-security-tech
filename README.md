# LSB 信息隐藏课程实验

三人协作开发骨架，仅覆盖基础功能的架构和接口，尚未实现 BMP 读写、嵌入提取和图形界面。

## 技术约定

- Python 3.11+，运行阶段仅使用标准库；图形界面使用 Tkinter。
- 自行解析 BMP 二进制，不使用 Pillow、OpenCV 等图片处理库。
- 支持未压缩的 8 位、256 级灰度 BMP 和 24 位真彩 BMP；尺寸不超过 512×512，宽度为 4 的倍数。
- 先阅读 [开发契约](docs/architecture.md) 和 [分工与联调](docs/development.md)。
- 开发前逐项确认 [三人联调细则](docs/integration.md)，其中明确状态转换、UI 事件及交叉验收样例。
- 数据库不是基础运行依赖；[数据设计](docs/data-design.md) 说明文件数据及可选实验记录库。

## 开发环境

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

无需安装第三方依赖。IDE 选择 `.venv` 中的 Python 解释器。

## 文件归属

| 成员 | 主要文件 | 任务 |
| --- | --- | --- |
| 一 | `lsb_lab/bmp.py`、`tests/test_bmp.py`（待创建） | BMP 读取、识别、校验、保存与显示数据转换 |
| 二 | `lsb_lab/stego.py`、`tests/test_stego.py`（待创建） | LSB 嵌入提取、帧头及容量控制 |
| 三 | `lsb_lab/controller.py`、`lsb_lab/ui.py`、集成测试 | 状态管理、界面与联调 |
| 共同维护 | `models.py`、`contracts.py`、`errors.py`、`docs/` | 接口、数据格式及实验记录 |

`tests/test_contracts.py` 验证已有共享契约，不代表功能已完成。各模块当前主动抛出 `NotImplementedError`，避免将空实现当成成功。
