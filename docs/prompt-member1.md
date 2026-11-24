# 成员一启动提示词

复制下方内容发送给成员一的 AI 编程助手：

```text
请完成本项目“必做扩展”成员一的工作：随机噪声和实验分析工具。你与成员二完全并行开发，不等待其代码，不依赖其模块。

开始前检查 Git 状态并保留已有修改，确认起点包含基础集成提交 b3ac91d。若远程 main 尚无该提交，请明确报告基线缺失，不从旧骨架开始，也不自行覆盖工作区。

阅读 README.md、docs/architecture.md、docs/integration.md、docs/validation.md、docs/extensions-assignment.md 及现有 BMP/LSB 实现。以 extensions-assignment.md 中本轮接口和职责为准；原有 v1 协议保持不变。

从共同基线创建 feat/noise-analysis，使用独立克隆目录或 worktree。
只修改或新增：
- lsb_lab/noise.py
- lsb_lab/analysis.py
- tests/test_noise.py
- tests/test_analysis.py
- docs/noise-experiment.md

按分工文档实现 NoiseResult、ComparisonMetrics、add_random_noise、compare_images、compare_lsb_positions、export_metrics，严格遵循参数、返回值、噪声抽样/裁剪、指标分母、逻辑位置索引和 JSON 语义。

只使用标准库；图像解析和像素遍历复用 bmp 模块。不得使用图片处理库，不修改输入图片，不改变非像素区，不污染全局随机状态。不修改 UI、控制器、共享接口、v1 算法、成员二文件或已有测试；需要跨范围修改时先记录问题交集成负责人。

使用 unittest 完成文档列出的验收项。利用已完成的基础顺序 LSB 进行真实磁盘噪声实验，保留无噪声对照和多种子结果。导出材料放 output/noise/，在自己的文档中给出复现命令、具体方法、真实结果和限制，必要的标准库复现实验入口可放 analysis.py 的 __main__，导入模块不得执行实验。不要声称全图 LSB 错误率等于正文错误率，不伪造实验或画质结论。

完成后运行新增测试及现有测试，明确执行环境、失败或未执行的项目。提交并推送 feat/noise-analysis，不合并或推送 main。回复提交 SHA、文件清单、接口摘要、测试结果及实验材料位置。界面接入与双方联调由集成负责人后续统一完成。
```