# 基础功能集成验证（2026-11-24）

## 合并来源

main 合并 origin/feat/bmp（30dd894）和 origin/feat/stego（76949a2），保留分支提交历史。基础集成提交为 b3ac91d，随后随界面及分工文档一并发布到远程 main。

## 集成时发现并修复

成员二分支使用 length+CRC+LSBv1、低位优先，并调用模型不存在的 copy/get_pixel_byte/set_pixel_byte，返回 str；也移除了共享容量函数。其测试使用自行定义的可变模型，未暴露真实模型不兼容，且 pytest 风格没有被项目 unittest 命令收集。

集成恢复既定 LSB1+version+length+CRC 协议和高位优先、不可变 BmpImage、ExtractionResult、CapacityError；重写算法测试为 unittest 和共享真实模型。未增加旧的错误协议兼容模式，旧分支协议生成的载体会被拒绝。

## 成员三交付

- 控制器按契约执行原子状态变更，预览通过 BMP 模块生成。
- Tkinter 双图预览、滚动条、独立输入和只读提取区、容量提示及按钮状态。
- 未保存结果丢弃确认、取消还原输入、覆盖原图保护（控制器也校验路径及同一文件）。
- 磁盘读取提取，不读取缓存输入；导入 UI 不创建窗口。

## 已执行验证

命令：`python -m unittest discover -s tests -v`。Python 3.12 / Windows：92 项测试通过。

- 69 项 BMP、6 项共享协议、5 项算法、7 项控制器、2 项真实文件集成、3 项 Tk 控件测试。
- 灰度和真彩、正负高度、间隔/尾部保留、中文/emoji/换行/尾空格、容量及损坏帧。
- 真实磁盘保存并在独立 Python 进程中重新提取；不依赖原图或会话。
- Tk 测试创建真实控件和 PhotoImage，触发修改事件和按钮回调；文件选择、确认与错误消息对话框使用 mock，未声称已逐项人工测试原生对话框。
- computer-use 查看了实际加载和提取完成的窗口：图像、文本和容量显示正常；已保存截图 output/ui-verified.png。

本地输出 output/ 中提供 gray.bmp、color.bmp、color-stego.bmp、界面截图及 test-results.txt（Git 忽略）。这些是确定性合成样例，不是课程提供图片。完整四项附加实验不在本次范围内。

## 窗口调整

默认客户区为 960×540，对应 1920×1080 屏幕的四分之一面积（标题栏和边框另计），居中打开；Windows 启用 DPI 感知。两列图片等宽，文本区增加滚动条，操作按钮增加步骤编号。已查看实际窗口，截图 output/ui-960x540.png；调整后完整 92 项测试再次通过。
