"""Shared discipline labels, keyword rules and new-admission checks."""
import re

DOMAINS = ("自然科学", "社会科学", "哲学与人文科学")

TERMS = {
    "自然科学": r"计算机|数学|物理|化学|生物|医学|人工智能|信息检索|语言模型|自然科学|computer|retriev|language model|transformer|attention|embedding|bert|splade|colbert|physics|biology|chemistry|mathematics|machine learning|neural",
    "社会科学": r"社会科学|社会学|经济|金融|法学|政治|教育|管理学|economics|sociology|finance|political|education|management",
    "哲学与人文科学": r"哲学|人文|历史|文学|艺术|伦理|宗教|philosophy|humanities|history|literature|arts|ethics|religion",
}


def rule_discipline(metadata):
    """Explicit tags win; otherwise accept exactly one keyword-domain match."""
    tags = metadata.get("topics", [])
    explicit = [domain for domain in DOMAINS if domain in tags]
    if explicit:
        return explicit[0] if len(explicit) == 1 else None
    text = " ".join([metadata.get("title") or "", *tags]).lower()
    matches = [domain for domain, pattern in TERMS.items() if re.search(pattern, text)]
    return matches[0] if len(matches) == 1 else None


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
