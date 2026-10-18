"""C module boundary errors; messages never contain upstream response bodies."""


class ProjectError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)
