"""Validate model-provided scope links and restore the planner's original wording."""
from .validation import invalid, nonempty


def validate_coverage(value, requirements):
    if value['status'] != 'answered' or not requirements:
        return []
    coverage = value.get('coverage')
    if not isinstance(coverage, list) or len(coverage) != len(requirements):
        invalid('回答必须逐项说明问题要点的覆盖与缺口')
    by_requirement, used = {}, set()
    for row in coverage:
        if not isinstance(row, dict):
            invalid('回答要点结构非法')
        requirement = row.get('requirement')
        if 'requirement_index' in row:
            index = row['requirement_index']
            if type(index) is not int or not 1 <= index <= len(requirements):
                invalid('回答要点序号非法')
            original = requirements[index - 1]
            if requirement is not None and requirement != original:
                invalid('回答要点序号与原文不符')
            requirement = original
        if requirement not in requirements or requirement in by_requirement:
            invalid('回答要点缺失或重复')
        indices, gap = row.get('claim_indices'), row.get('gap')
        if (not isinstance(indices, list) or any(type(i) is not int or not 1 <= i <= len(value['claims']) for i in indices)
                or len(set(indices)) != len(indices) or not isinstance(gap, str)):
            invalid('要点引用非法')
        if not indices and not nonempty(gap):
            invalid('未回答的要点必须解释具体证据缺口')
        by_requirement[requirement] = {'requirement': requirement, 'claim_indices': indices, 'gap': gap}
        used.update(indices)
    if used != set(range(1, len(value['claims']) + 1)):
        invalid('存在未回应任何问题要点的结论')
    return [by_requirement[requirement] for requirement in requirements]
