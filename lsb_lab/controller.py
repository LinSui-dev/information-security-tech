"""成员三实现。界面只调用控制器，不直接操作二进制数据。"""
from pathlib import Path
from .models import SessionState, Capacity, ExtractionResult, PreviewData


class LabController:
    def __init__(self) -> None:
        self.state = SessionState()

    def open_source(self, path: str | Path) -> Capacity:
        """成功后更新 source，清空旧 stego/提取结果；失败保留旧状态。"""
        raise NotImplementedError

    def embed(self, text: str) -> None:
        """基于 source 嵌入，成功后更新 stego 和 dirty。"""
        raise NotImplementedError

    def set_input_text(self, text: str) -> None:
        """更新草稿；变更后清除旧 stego 并将 dirty 置 False，详见联调契约。"""
        raise NotImplementedError

    def get_source_preview(self) -> PreviewData | None:
        """无 source 返回 None，否则委托 bmp.to_preview。"""
        raise NotImplementedError

    def get_result_preview(self) -> PreviewData | None:
        """优先显示 stego，其次 extracted_image，否则 None。"""
        raise NotImplementedError

    def save_stego(self, path: str | Path) -> None:
        """保存 stego，成功后清除 dirty；未嵌入时抛 LabError。"""
        raise NotImplementedError

    def extract_from(self, path: str | Path) -> ExtractionResult:
        """从磁盘重新读取载体并提取；不得直接返回缓存的输入文本。"""
        raise NotImplementedError
