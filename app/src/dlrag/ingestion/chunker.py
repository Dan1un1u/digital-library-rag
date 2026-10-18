"""Page-bounded exact substring chunking with explicit counting units."""
import re
from importlib.metadata import version, PackageNotFoundError
from .errors import ProjectError

DEFAULT_CONFIG = dict(count_mode='token', tokenizer_name=None, tokenizer_revision=None,
                      max_tokens=400, overlap_tokens=50, max_chars=1200, overlap_chars=150)


def normalize_config(options):
    if not isinstance(options, dict) or set(options) - set(DEFAULT_CONFIG):
        raise ProjectError('INVALID_REQUEST', 'Unknown chunking configuration fields')
    config = {**DEFAULT_CONFIG, **options}
    mode = config['count_mode']
    if mode not in ('token', 'character'):
        raise ProjectError('INVALID_REQUEST', 'count_mode must be token or character')
    for key in ('max_tokens','overlap_tokens','max_chars','overlap_chars'):
        if not isinstance(config[key], int) or isinstance(config[key], bool) or config[key] < 0:
            raise ProjectError('INVALID_REQUEST', f'{key} must be a nonnegative integer')
    maximum, overlap = (config['max_tokens'], config['overlap_tokens']) if mode == 'token' else (config['max_chars'], config['overlap_chars'])
    if maximum <= 0 or overlap >= maximum:
        raise ProjectError('INVALID_REQUEST', 'Require 0 <= overlap < maximum')
    if mode == 'token' and not isinstance(config['tokenizer_name'], str):
        raise ProjectError('TOKENIZER_NOT_CONFIGURED', 'Set tokenizer_name or explicitly select character mode')
    if mode == 'token':
        if not config['tokenizer_name'].startswith('tiktoken:'):
            raise ProjectError('TOKENIZER_NOT_CONFIGURED', 'Supported identifier: tiktoken:<encoding>')
        try:
            installed = version('tiktoken')
        except PackageNotFoundError:
            installed = None
        requested = config['tokenizer_revision']
        if requested is not None and requested != installed:
            raise ProjectError('TOKENIZER_NOT_CONFIGURED', 'Requested tiktoken revision is unavailable')
        config['tokenizer_revision'] = installed
    if mode == 'character':
        config['tokenizer_name'] = None
        config['tokenizer_revision'] = None
    return config


class TokenCounter:
    def __init__(self, name):
        # tiktoken is optional and lazy: importing ingestion never downloads anything.
        if not name.startswith('tiktoken:'):
            raise ProjectError('TOKENIZER_NOT_CONFIGURED', 'Supported identifier: tiktoken:<encoding>')
        try:
            import tiktoken
            self.encoding = tiktoken.get_encoding(name.split(':', 1)[1])
        except Exception as exc:
            raise ProjectError('TOKENIZER_NOT_CONFIGURED', 'Tokenizer unavailable; explicitly select character mode') from exc

    def count(self, text):
        return len(self.encoding.encode(text, disallowed_special=()))


def chunk_pages(doc_id, pages, config):
    counter = TokenCounter(config['tokenizer_name']) if config['count_mode'] == 'token' else None
    count = counter.count if counter else len
    maximum = config['max_tokens'] if counter else config['max_chars']
    overlap = config['overlap_tokens'] if counter else config['overlap_chars']
    chunks = []
    for page in pages:
        text = page['normalized_text']
        paragraph_boundaries = [m.end() for m in re.finditer(r'\n\n', text)]
        sentence_boundaries = [m.end() for m in re.finditer(r'[.!?。！？](?:\s+|$)', text)]
        boundaries = paragraph_boundaries + sentence_boundaries
        start, order = 0, 0
        while start < len(text):
            # Extend exact substrings until the unit budget is exhausted. Token mode
            # checks every prefix, avoiding assumptions about tokenizer monotonicity.
            if counter:
                end = start
                for candidate in range(start+1, len(text)+1):
                    if count(text[start:candidate]) > maximum:
                        break
                    end = candidate
                if end == start:
                    raise ProjectError('INVALID_REQUEST', 'Token budget cannot fit one Unicode character')
            else:
                end = min(len(text), start + maximum)
            if end < len(text):
                preferred = [b for b in paragraph_boundaries if start < b <= end]
                if not preferred:
                    preferred = [b for b in sentence_boundaries if start < b <= end]
                if preferred:
                    end = preferred[-1]
            if text[start:end].strip():
                order += 1
                chunks.append({'chunk_id':f'c_{doc_id[2:]}_p{page["pdf_page"]:04d}_{order:04d}',
                    'pdf_page':page['pdf_page'], 'chunk_order':order, 'section':None,
                    'text':text[start:end], 'page_char_start':start, 'page_char_end':end,
                    'token_count':count(text[start:end]) if counter else None})
            if end == len(text):
                break
            # Overlap only a forced split within a long paragraph/sentence.
            next_start = end
            if end not in boundaries and overlap:
                if counter:
                    while next_start > start + 1 and count(text[next_start-1:end]) <= overlap:
                        next_start -= 1
                else:
                    next_start = max(start+1, end-overlap)
            start = next_start
    return chunks
