"""Local catalogue presentation; no model or external image requests."""
from html import escape
from urllib.parse import quote
from dlrag.shared.disciplines import DOMAINS, rule_discipline as discipline
from dlrag.shared.i18n import t, get_language


def document_status(document):
    if document.get("error_code") in {"FULLTEXT_REVIEW_REQUIRED", "TEXT_LAYER_REVIEW_REQUIRED"}:
        return t("待核对正文（未加入检索）")
    return t({"ready": "可阅读", "uploaded": "处理中", "parsing": "处理中",
              "indexing": "正在建立检索", "failed": "处理失败"}.get(document["status"], document["status"]))


def display_topics(topics):
    return (", " if get_language() == "en" else "、").join(t(x) if x in DOMAINS else x for x in topics)


def domain_counts(documents):
    counts = dict.fromkeys(DOMAINS, 0)
    pending = 0
    for document in documents:
        domain = discipline(document)
        if domain:
            counts[domain] += 1
        else:
            pending += 1
    return counts, pending


def cover_card(document, base):
    url = base.rstrip("/") + "/documents/" + quote(document["doc_id"], safe="")
    title = escape(document["title"])
    authors = escape("、".join(document.get("authors", [])) or t("作者未标注"))
    domain = escape(t(discipline(document) or "待分类"))
    year = escape(str(document.get("year") or t("年份未标注")))
    return f'''<a class="book-card" href="{escape(url + '/file', quote=True)}" target="_blank" rel="noopener noreferrer">
    <div class="book-cover"><img loading="lazy" src="{escape(url + '/cover', quote=True)}" alt="{title} · {t('PDF 首页')}" /></div>
    <div class="book-info"><span class="book-domain">{domain} · {year}</span>
    <h3>{title}</h3><p>{authors}</p><span class="book-open">{t('阅读原文')} ↗</span></div></a>'''


STYLE = """<style>
.block-container {padding-top:2.2rem;max-width:1500px}
[data-testid="stSidebar"] {border-right:1px solid #94a3b826}
[data-testid="stSidebar"] [role="radiogroup"] {gap:.5rem}
.library-hero {background:linear-gradient(110deg,#122e45,#216d78);border-radius:18px;padding:28px 32px;color:#fff;margin:0 0 24px}
.library-hero small {letter-spacing:.16em;color:#bde1df}
.library-hero h2 {font-size:1.85rem;color:#fff;margin:.5rem 0}
.library-hero p {color:#d7e9ee;margin:0;line-height:1.8}
.book-card {display:block;border:1px solid #94a3b833;border-radius:14px;overflow:hidden;text-decoration:none!important;color:inherit!important;margin:0 0 22px;transition:transform .18s,box-shadow .18s}
.book-card:hover {transform:translateY(-4px);box-shadow:0 12px 26px #122e4520;border-color:#369693}
.book-cover {height:255px;background:#edf1f3;padding:14px;display:flex;justify-content:center}
.book-cover img {width:100%;height:100%;object-fit:contain;filter:drop-shadow(0 3px 5px #0002)}
.book-info {padding:18px 20px}.book-domain {font-size:.78rem;color:#32847f}
.book-info h3 {font-size:1rem!important;line-height:1.55;padding:.65rem 0 .4rem!important;margin:0;min-height:5.2rem}
.book-info p {font-size:.8rem;opacity:.7;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin:.4rem 0 1rem}
.book-open {font-size:.82rem;color:#32847f;font-weight:600}
</style>"""
