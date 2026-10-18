"""Strict JSON, request and generated-answer validation."""
import json
from .errors import ProjectError


def invalid(message):
    raise ProjectError("OUTPUT_VALIDATION_FAILED", message)


def parse_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    try:
        value = json.loads(text, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, RecursionError):
        invalid("模型未返回合法 JSON 对象")
    if not isinstance(value, dict):
        invalid("模型输出必须为 JSON 对象")
    return value


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def strings(value, allow_empty=True):
    return isinstance(value, list) and (allow_empty or bool(value)) and all(nonempty(x) for x in value)


def validate_request(request):
    def bad():
        raise ProjectError("INVALID_REQUEST", "问题、过滤条件或 history 格式非法")
    if not isinstance(request, dict) or set(request) - {"question", "filters", "history"}:
        bad()
    q = request.get("question")
    if not nonempty(q) or len(q.strip()) > 2000:
        bad()
    history = request.get("history", [])
    if not isinstance(history, list):
        bad()
    if history:
        raise ProjectError("UNSUPPORTED_HISTORY", "第一版只支持单轮，请将澄清选择与原问题组成新请求")
    f = request.get("filters", {"year_from": None, "year_to": None, "topics": []})
    if not isinstance(f, dict) or set(f) - {"year_from", "year_to", "topics"}:
        bad()
    for k in ("year_from", "year_to"):
        if f.get(k) is not None and (type(f[k]) is not int or not 1 <= f[k] <= 9999):
            bad()
    if not strings(f.get("topics", [])):
        bad()
    if f.get("year_from") is not None and f.get("year_to") is not None and f["year_from"] > f["year_to"]:
        bad()
    return q.strip(), f


def validate_answer(value, selected, require_sentence_refs=False):
    if not isinstance(value, dict) or value.get("status") not in ("answered", "insufficient_evidence"):
        invalid("回答状态非法")
    claims, limitations = value.get("claims"), value.get("limitations")
    if not isinstance(claims, list) or not strings(limitations):
        invalid("回答结构非法")
    if value["status"] == "insufficient_evidence":
        if claims or not limitations or value.get("sections", []):
            invalid("证据不足必须无结论并说明原因")
        return value
    if not claims:
        invalid("回答结论为空")
    ids = {c["chunk_id"] for c in selected}
    from .sentences import sentence_spans
    sentences = {c["chunk_id"]: {s["sentence_id"] for s in sentence_spans(c["text"])} for c in selected}
    for claim in claims:
        if not isinstance(claim, dict) or not nonempty(claim.get("text")):
            invalid("结论文本为空")
        refs = claim.get("evidence_chunk_ids")
        if not strings(refs, False) or any(cid not in ids for cid in refs):
            invalid("结论包含缺失或不属于本次选中证据的引用")
        if require_sentence_refs and "evidence_sentences" not in claim:
            invalid("每条结论必须选择支持它的原文句子")
        if "evidence_sentences" in claim:
            positions = claim["evidence_sentences"]
            if (not isinstance(positions, dict) or set(positions) != set(refs)
                    or any(not strings(sids, False) or len(sids) > 6
                           or any(sid not in sentences[cid] for sid in sids) for cid, sids in positions.items())):
                invalid("引用句子必须属于对应的本次证据，且覆盖所有引用")
    if "sections" in value:
        sections = value["sections"]
        if not isinstance(sections, list) or not 1 <= len(sections) <= 6:
            invalid("回答段落结构非法")
        used = []
        for section in sections:
            if (not isinstance(section, dict) or not isinstance(section.get("heading"), str)
                    or len(section["heading"]) > 80 or not isinstance(section.get("claim_indices"), list)
                    or not section["claim_indices"] or any(type(i) is not int for i in section["claim_indices"])):
                invalid("回答段落引用非法")
            used.extend(section["claim_indices"])
        if sorted(used) != list(range(1, len(claims) + 1)):
            invalid("回答段落必须完整且不重复地引用本次结论")
    return value
