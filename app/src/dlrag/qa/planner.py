"""No repair calls for query planning; malformed output falls back verbatim."""
from .validation import invalid, nonempty, strings


def original_plan(question):
    return dict(original_query=question, intent="explain", rewritten_query=question,
                keywords=[], needs_clarification=False, clarification_question=None,
                clarification_options=[])


def validate_plan(value, question):
    fields = set(original_plan(question))
    if not isinstance(value, dict) or not fields <= set(value) or set(value) - fields - {"english_query", "answer_requirements", "mechanism_query"}:
        invalid("规划字段不完整或包含额外字段")
    if value["original_query"] != question or value["intent"] not in {"find", "explain", "compare", "clarify"}:
        invalid("规划改变原问题或意图非法")
    if not nonempty(value["rewritten_query"]) or len(value["rewritten_query"]) > 2000 or not strings(value["keywords"]):
        invalid("改写或关键词非法")
    if type(value["needs_clarification"]) is not bool:
        invalid("澄清标记必须为布尔值")
    if value["needs_clarification"]:
        options = value["clarification_options"]
        if (value["intent"] != "clarify" or not nonempty(value["clarification_question"])
                or not strings(options) or not 2 <= len(options) <= 3 or len(set(options)) != len(options)):
            invalid("澄清必须有追问和 2–3 个不同选项")
    elif value["intent"] == "clarify" or value["clarification_question"] is not None or value["clarification_options"] != []:
        invalid("非澄清规划包含澄清内容")
    result = {k: value[k] for k in original_plan(question)}
    if value.get('mechanism_query') is not None:
        if not nonempty(value['mechanism_query']) or len(value['mechanism_query']) > 500:
            invalid('机制补充查询非法')
        result['mechanism_query'] = value['mechanism_query'].strip()
    if "answer_requirements" in value:
        requirements = value["answer_requirements"]
        if not strings(requirements) or len(requirements) > 4 or any(len(r) > 150 for r in requirements) or len(set(requirements)) != len(requirements):
            invalid("问题要点格式非法")
        result["answer_requirements"] = requirements
    if value.get("english_query") is not None:
        if not nonempty(value["english_query"]) or len(value["english_query"]) > 2000:
            invalid("英文检索表达非法")
        result["english_query"] = value["english_query"].strip()
    return result
