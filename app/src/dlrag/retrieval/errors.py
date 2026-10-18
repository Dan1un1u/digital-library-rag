"""可被 D 按 code/message 识别的模块异常。"""


class ProjectError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)
