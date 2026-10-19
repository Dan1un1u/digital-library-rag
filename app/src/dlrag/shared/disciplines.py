"""One explicit broad-discipline selection for new catalogue admissions."""

DOMAINS = ("自然科学", "社会科学", "哲学与人文科学")


class DisciplineError(ValueError):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def require_discipline(metadata):
    topics = metadata.get("topics", []) if isinstance(metadata, dict) else None
    if not isinstance(topics, list) or any(not isinstance(tag, str) for tag in topics):
        raise DisciplineError("INVALID_REQUEST", "主题须为文本列表。")
    selected = [domain for domain in DOMAINS if domain in topics]
    if not selected:
        raise DisciplineError("DISCIPLINE_REQUIRED", "请选择所属学科：自然科学、社会科学或哲学与人文科学。")
    if len(selected) != 1:
        raise DisciplineError("DISCIPLINE_CONFLICT", "所属学科只能选择一项，请保留一个学科标签。")
    return selected[0]
