"""Escaped source HTML and per-claim citation links, independent of Streamlit state."""
from html import escape
from urllib.parse import quote, urlencode
from dlrag.shared.i18n import t, get_language


def source_url(base, evidence, highlights, version):
    params = [('index_version', version)] if version else []
    if get_language() == 'en':
        params.append(('lang', 'en'))
    params += [('span', f"{s['start']}:{s['end']}") for s in highlights]
    return base.rstrip('/') + '/sources/' + quote(evidence['chunk_id'], safe='') + '?' + urlencode(params) + '#source-text'


def marked_text(text, spans):
    # Recheck exact source spans at the rendering boundary; never highlight guessed matches.
    intervals = sorted((s['start'], s['end']) for s in spans
                       if type(s.get('start')) is int and type(s.get('end')) is int
                       and 0 <= s['start'] < s['end'] <= len(text) and text[s['start']:s['end']] == s.get('text'))
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    result, position = [], 0
    for start, end in merged:
        result.extend([escape(text[position:start]), '<mark style="background:#ffe082;color:#181818;padding:2px 0">', escape(text[start:end]), '</mark>'])
        position = end
    result.append(escape(text[position:]))
    return ''.join(result)


def claim_html(claim, evidence, numbers, base, version):
    by_id = {e['evidence_id']: e for e in evidence}
    positions = {c['evidence_id']: c['highlights'] for c in claim.get('citations', [])}
    refs = []
    for eid in claim['evidence_ids']:
        url = source_url(base, by_id[eid], positions.get(eid, []), version)
        label = escape(t('查看引用 {p0} 的原文', p0=numbers[eid]), quote=True)
        refs.append(f'<sup><a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer" aria-label="{label}">[{numbers[eid]}]</a></sup>')
    return escape(claim['text'].strip()) + ' ' + ' '.join(refs)
