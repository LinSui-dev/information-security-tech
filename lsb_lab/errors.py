"""预期业务错误由界面捕获并显示；编程错误不应静默吞掉。"""


class LabError(Exception):
    """业务错误基类。"""


class InvalidBmpError(LabError):
    """文件结构损坏或不是 BMP。"""


class UnsupportedBmpError(LabError):
    """有效 BMP，但格式超出课程支持范围。"""


class CapacityError(LabError):
    """载体空间不足。"""


class InvalidPayloadError(LabError):
    """帧标记、版本、长度、校验或文本编码不正确。"""
