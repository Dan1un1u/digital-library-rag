"""Validate question-facet accounting; this is not an independent semantic fact checker."""
from .validation import invalid, nonempty


def validate_coverage(value, requirements):
    if value['status'] != 'answered' or not requirements:
        return
    coverage = value.get('coverage')
    if not isinstance(coverage, list) or len(coverage) != len(requirements):
        invalid('回答必须逐项说明问题要点的覆盖与缺口')
    seen, used = set(), set()
    for row in coverage:
        if not isinstance(row, dict) or row.get('requirement') not in requirements or row['requirement'] in seen:
            invalid('回答要点缺失或重复')
        seen.add(row['requirement'])
        indices, gap = row.get('claim_indices'), row.get('gap')
        if (not isinstance(indices, list) or any(type(i) is not int or not 1 <= i <= len(value['claims']) for i in indices)
                or len(set(indices)) != len(indices) or not isinstance(gap, str)):
            invalid('要点引用非法')
        if not indices and not nonempty(gap):
            invalid('未回答的要点必须解释具体证据缺口')
        used.update(indices)
    if used != set(range(1,len(value['claims'])+1)):
        invalid('存在未回应任何问题要点的结论')
