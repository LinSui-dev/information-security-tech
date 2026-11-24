# 成员二启动提示词

复制下方内容发送给成员二的 AI 编程助手：

```text
请完成本项目“必做扩展”成员二的工作：查阅文献、自行设计并实现带密钥的随机间隔 LSB。你与成员一完全并行开发，不等待其代码，不依赖 noise 或 analysis 模块。

开始前检查 Git 状态并保留已有修改，确认起点包含基础集成提交 b3ac91d。若远程 main 尚无该提交，请明确报告基线缺失，不从旧骨架开始，也不自行覆盖工作区。

阅读 README.md、docs/architecture.md、docs/integration.md、docs/validation.md、docs/extensions-assignment.md 及共享模型和现有实现。以 extensions-assignment.md 中本轮接口和职责为准；不得改变基础 v1 的格式、位序、异常和返回类型。

从共同基线创建 feat/keyed-stego，使用独立克隆目录或 worktree。
只修改或新增：
- lsb_lab/keyed_stego.py
- tests/test_keyed_stego.py
- docs/keyed-stego.md

按分工文档实现 capacity_for_keyed、embed_text、extract_text、payload_positions，复用真实 BmpImage、Capacity、ExtractionResult 和既有异常，不创建与生产模型不兼容的替身。

先形成并记录完整独立协议：magic/版本、bootstrap、salt、长度、CRC/MAC、字节序、位序、密钥派生及随机间隔生成规则，再按该协议编码。不需要等待成员一或逐步请求确认；文档明确的约束内自行完成设计选择。

必须有真正跳过的随机间隔，而非只打乱连续位置。保证位置唯一、不越界、与固定前缀不重叠；容量必须对所有合法密钥和盐成立。salt 默认由 secrets 产生，显式盐支持确定性测试；使用稳定的 hashlib/hmac 派生规则。HMAC 验证密钥和关键帧内容，空消息也验证密钥，使用 compare_digest。payload_positions 的逻辑索引和失败语义按分工文档执行。

仅使用标准库，不使用图片处理库；不改 BMP、顺序 stego、contracts、models、errors、UI、控制器、成员一文件或已有测试。嵌入返回新图，不修改输入或非占用字节。随机位置不是加密，不作抗压缩或抗剪裁承诺。

查阅实际文献/原始资料，在自己的文档中列出可核查的作者、题名、年份、链接和借鉴点，区分文献方法与自己的设计，不捏造来源。

使用 unittest 完成文档列出的测试，采用共享 BMP 夹具和真实模型，至少有真实磁盘及独立进程正确密钥往返。用独立已知向量检验帧和位置规则，不能只依靠自身嵌入提取互相验证。覆盖空文本、Unicode、边界、错误密钥、损坏帧、盐、容量和位置规则。不要只运行自己的测试而遗漏基础回归。

提交并推送 feat/keyed-stego，不合并或推送 main。回复提交 SHA、文件清单、协议和接口摘要、实际测试命令/结果及限制。界面接入与双方联调由集成负责人后续统一完成。
```
