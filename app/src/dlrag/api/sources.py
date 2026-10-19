"""Read-only source viewer: exact extracted sentences and rendered PDF page highlights."""
import base64
from html import escape

from dlrag.qa.sentences import sentence_spans
from dlrag.ui.citations import marked_text
from dlrag.shared.i18n import t, get_language, use_language
from .services import ProjectError


def read_source(service, chunk_id, spans, index_version):
    with service.lock:
        chunk = service.require('library').get_chunk(chunk_id)
        if not chunk:
            raise ProjectError('NOT_FOUND', '原文片段不存在')
        manifest = service.manifest()
        if index_version and (not manifest or manifest['index_version'] != index_version):
            raise ProjectError('INDEX_NOT_READY', '索引已更新，请重新提问以生成当前版本的引用。')
        if index_version and chunk_id not in service.require('retriever').get_chunk_ids():
            raise ProjectError('INDEX_NOT_READY', '该片段不属于当前索引，请重新提问。')
        if len(spans) > 6:
            raise ProjectError('INVALID_REQUEST', '高亮句子数量超出范围')
        allowed = {(s['start'], s['end']): s for s in sentence_spans(chunk['text'])}
        highlights = []
        for value in spans:
            try:
                start, end = (int(x) for x in value.split(':'))
            except (ValueError, TypeError):
                raise ProjectError('INVALID_REQUEST', '高亮位置格式非法') from None
            if (start, end) not in allowed:
                raise ProjectError('INVALID_REQUEST', '高亮位置不是该片段的完整原文句子')
            highlights.append(allowed[start, end])
        path = service.file_path(chunk['doc_id'])
        return chunk, highlights, path


def pdf_preview(path, page_number, highlights):
    import fitz
    with fitz.open(path) as pdf:
        page = pdf[page_number - 1]
        matched = 0
        # PyMuPDF searches the original text layer, including visual line wraps.
        # Never infer page rectangles from character count or approximate word similarity.
        for span in highlights:
            rects = page.search_for(' '.join(span['text'].split()))
            if rects:
                matched += 1
                annotation = page.add_highlight_annot(rects)
                annotation.set_colors(stroke=(1, .78, .05))
                annotation.set_opacity(.4)
                annotation.update()
        scale = min(1.3, 1800 / max(page.rect.width, page.rect.height))
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pixmap.tobytes('png'), matched


def source_html(chunk, highlights, image, matched, language='zh'):
    with use_language(language):
        return _source_html(chunk, highlights, image, matched)


def _source_html(chunk, highlights, image, matched):
    from urllib.parse import quote
    document = chunk.get('document', {})
    title = document.get('title', t('文献原文'))
    file_url = f"/documents/{quote(chunk['doc_id'], safe='')}/file#page={chunk['pdf_page']}"
    if not highlights:
        notice = t('该引用未包含句子定位信息。请重新提问以生成句子级高亮。')
    elif matched == len(highlights):
        notice = t('黄色区域为该角标选中的支持句子；下方为对应 PDF 原页。')
    else:
        notice = t('提取原文已精确高亮；PDF 文字层定位成功 {p0}/{p1} 句。未匹配句子请核对下方提取原文。', p0=matched, p1=len(highlights))
    lang = 'en' if get_language() == 'en' else 'zh-CN'
    return f'''<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)} · {t('引用原文')}</title><style>body{{font:17px/1.8 system-ui,sans-serif;max-width:1100px;margin:32px auto;padding:0 20px;color:#172033;background:#f5f7fb}}section{{background:white;padding:24px;border-radius:12px;margin:20px 0}}.source{{white-space:pre-wrap;overflow-wrap:anywhere}}img{{width:100%;height:auto}}a{{color:#175bcc}}#source-text{{scroll-margin-top:20px}}</style></head><body>
<h1>{escape(title)}</h1><p>{t('PDF 文件第 {p0} 页', p0=chunk['pdf_page'])} · <a href="{escape(file_url, quote=True)}" target="_blank" rel="noopener">{t('打开 PDF 原文件')}</a></p>
<p>{escape(notice)}</p><section id="source-text"><h2>{t('引用原文')}</h2><div class="source">{marked_text(chunk['text'], highlights)}</div></section>
<section><h2>{t('PDF 原页预览')}</h2><img alt="{t('对应 PDF 页面及可定位的支持句子高亮')}" src="data:image/png;base64,{base64.b64encode(image).decode('ascii')}"></section></body></html>'''
