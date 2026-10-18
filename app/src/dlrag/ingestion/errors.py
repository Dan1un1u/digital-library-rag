class ProjectError(Exception):
    def __init__(self, code, message):
        self.code, self.message = str(code), str(message)
        super().__init__(self.message)
