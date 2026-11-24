"""会话控制器：失败时不提交状态变更。"""
from dataclasses import replace
from pathlib import Path
from . import bmp, stego
from .contracts import capacity_for
from .errors import LabError
from .models import SessionState, Capacity, ExtractionResult, PreviewData


class LabController:
    def __init__(self) -> None:
        self.state = SessionState()

    def open_source(self, path: str | Path) -> Capacity:
        image = bmp.load_bmp(path)
        capacity = capacity_for(image)
        self.state = SessionState(source=image, source_path=Path(path).resolve())
        return capacity

    def set_input_text(self, text: str) -> None:
        if text != self.state.input_text:
            self.state = replace(self.state, input_text=text, stego=None, dirty=False)

    def embed(self, text: str) -> None:
        if self.state.source is None:
            raise LabError("请先打开原图")
        image = stego.embed_text(self.state.source, text)
        self.state = replace(self.state, stego=image, input_text=text, dirty=True,
                             extracted_text="", extracted_image=None, extracted_path=None)

    def save_stego(self, path: str | Path) -> None:
        if self.state.stego is None:
            raise LabError("请先嵌入信息")
        target = Path(path).resolve()
        source = self.state.source_path
        if source is not None and (target == source or
                (target.exists() and source.exists() and target.samefile(source))):
            raise LabError("不能覆盖原图，请选择其他保存路径")
        bmp.save_bmp(self.state.stego, target)
        self.state = replace(self.state, dirty=False)

    def extract_from(self, path: str | Path) -> ExtractionResult:
        image = bmp.load_bmp(path)
        result = stego.extract_text(image)
        self.state = replace(self.state, extracted_image=image,
                             extracted_path=Path(path).resolve(), extracted_text=result.text,
                             stego=None, dirty=False)
        return result

    def get_source_preview(self) -> PreviewData | None:
        return bmp.to_preview(self.state.source) if self.state.source is not None else None

    def get_result_preview(self) -> PreviewData | None:
        image = self.state.stego or self.state.extracted_image
        return bmp.to_preview(image) if image is not None else None
