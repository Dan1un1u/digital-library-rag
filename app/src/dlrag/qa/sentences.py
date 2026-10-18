"""Deterministic sentence spans into unmodified chunk text (Python character offsets)."""
import re


def sentence_spans(text):
    boundaries = [m.end() for m in re.finditer(r'[。！？!?]+[”’"\']*|\.(?=\s+[A-Z“"\[]|\s*$)', text)]
    result, start = [], 0
    for end in boundaries + [len(text)]:
        left, right = start, end
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            result.append(dict(sentence_id=f"s{len(result) + 1}", start=left, end=right, text=text[left:right]))
        start = end
    return result


def annotated_text(text):
    result, start = [], 0
    for span in sentence_spans(text):
        result.extend([text[start:span['start']], f"[{span['sentence_id']}] ", span['text']])
        start = span['end']
    result.append(text[start:])
    return ''.join(result)
