"""UI-002: bilingual controls keep user data and canonical API values intact."""
import copy
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from test_metadata_upload import paper_bytes
from test_sources import source

APP = str(Path(__file__).parents[2] / 'src/dlrag/ui/app.py')


def open_app(client, monkeypatch, language=None):
    calls = []
    def api(base, method, path, **kwargs):
        calls.append((method, path, copy.deepcopy(kwargs.get('json'))))
        r = client.request(method, path, **kwargs)
        return {'_failure': r.json()['error']} if r.is_error else r.json()
    monkeypatch.setattr('dlrag.ui.client.call_api', api)
    app = AppTest.from_file(APP, default_timeout=25)
    if language is not None:
        app.query_params['lang'] = language
    app.run()
    assert not app.exception
    return app, calls


def switch(app, language):
    app.selectbox(key='ui_language').set_value(language).run()
    assert not app.exception


def test_default_chinese_and_query_language_choice(client, monkeypatch):
    app, _ = open_app(client, monkeypatch)
    assert app.selectbox(key='ui_language').value == 'zh'
    assert app.title[0].value == '专题数字图书馆'
    switch(app, 'en')
    assert app.title[0].value == 'Digital Library'
    assert app.query_params['lang'] == 'en'
    assert app.sidebar.radio[0].options == ['Collection', 'Search and Q&A', 'Upload and manage']
    switch(app, 'zh')
    assert app.title[0].value == '专题数字图书馆'


@pytest.mark.parametrize('language,expected', [('en', 'Digital Library'), ('zh', '专题数字图书馆'), ('invalid', '专题数字图书馆')])
def test_url_language_initialization(client, monkeypatch, language, expected):
    app, _ = open_app(client, monkeypatch, language)
    assert app.title[0].value == expected


def test_switch_resends_selected_choices_with_translated_labels(client, monkeypatch):
    app, _ = open_app(client, monkeypatch)
    app.selectbox(key='browse_domain').set_value('自然科学').run()
    switch(app, 'en')
    assert app.radio(key='navigation_page').value == '馆藏展示'
    assert app.selectbox(key='browse_domain').value == '自然科学'
    assert app.radio(key='navigation_page').proto.set_value
    assert app.selectbox(key='browse_domain').proto.set_value
    assert app.selectbox(key='browse_domain').proto.raw_value == 'Natural sciences'


@pytest.mark.parametrize('page,section,heading', [
    ('馆藏展示', '馆藏文献分类', 'Collection by subject'),
    ('馆藏展示', '热门电子文献资源', 'Featured documents'),
    ('搜索与问答', None, 'Search and Q&A'),
    ('上传与管理', '上传文献', 'Upload a PDF'),
    ('上传与管理', '文献管理', 'Manage documents'),
    ('上传与管理', '系统设置', 'System settings'),
])
def test_all_navigation_pages_are_available_in_english(client, imported, monkeypatch, page, section, heading):
    app, _ = open_app(client, monkeypatch, 'en')
    app.sidebar.radio[0].set_value(page).run()
    if section:
        app.sidebar.radio[1].set_value(section).run()
    assert not app.exception
    assert heading in [h.value for h in app.subheader] or heading in [c.value for c in app.caption]
    assert app.sidebar.radio[0].value == page  # Internal IDs stay independent of display language.


def test_switch_keeps_search_draft_filters_and_results(client, imported, monkeypatch):
    app, calls = open_app(client, monkeypatch)
    app.sidebar.radio[0].set_value('搜索与问答').run()
    app.text_area(key='query_question').set_value('BM25')
    app.text_input(key='filter_year_from').set_value('2024')
    app.text_input(key='filter_topics').set_value('合成测试')
    next(b for b in app.button if b.label == '提交').click().run()
    before = copy.deepcopy(app.session_state['search_result'])
    posts = len([c for c in calls if c[0] == 'POST'])
    switch(app, 'en')
    assert app.text_area(key='query_question').value == 'BM25'
    assert app.text_input(key='filter_year_from').value == '2024'
    assert app.text_input(key='filter_topics').value == '合成测试'
    assert app.session_state['search_result'] == before
    assert len([c for c in calls if c[0] == 'POST']) == posts
    switch(app, 'zh')
    assert app.session_state['search_result'] == before


def test_switch_keeps_original_answer_and_selected_citation(client, imported, monkeypatch):
    app, calls = open_app(client, monkeypatch)
    app.sidebar.radio[0].set_value('搜索与问答').run()
    app.text_area(key='query_question').set_value('BM25')
    app.radio(key='query_action').set_value('问答')
    next(b for b in app.button if b.label == '提交').click().run()
    next(b for b in app.button if '查看原文' in b.label).click().run()
    answer = copy.deepcopy(app.session_state['answer'])
    selected = app.session_state['selected_evidence']
    posts = len([c for c in calls if c[0] == 'POST'])
    switch(app, 'en')
    assert app.session_state['answer'] == answer
    assert app.session_state['selected_evidence'] == selected
    assert any(b.label == '[1] View source' for b in app.button)
    assert len([c for c in calls if c[0] == 'POST']) == posts


def test_upload_draft_survives_switch_without_recognition_or_data_translation(client, monkeypatch):
    raw = paper_bytes()
    monkeypatch.setattr('streamlit.file_uploader', lambda *a, **k: SimpleNamespace(name='fixture.pdf', getvalue=lambda: raw))
    app, calls = open_app(client, monkeypatch)
    app.sidebar.radio[0].set_value('上传与管理').run()
    app.text_input(key='upload_title').set_value('自然科学 is the original document title')
    app.text_area(key='upload_authors').set_value('张三\nJane Smith')
    app.text_input(key='upload_topics').set_value('原始主题,NPU')
    app.selectbox(key='upload_domain').set_value('自然科学')
    app.run()
    count = len([c for c in calls if c[1] == '/documents/metadata/jobs'])
    switch(app, 'en')
    assert app.text_input(key='upload_title').value == '自然科学 is the original document title'
    assert app.text_area(key='upload_authors').value == '张三\nJane Smith'
    assert app.text_input(key='upload_topics').value == '原始主题,NPU'
    assert app.selectbox(key='upload_domain').value == '自然科学'
    assert len([c for c in calls if c[1] == '/documents/metadata/jobs']) == count
    next(b for b in app.button if b.label == 'Import document').click().run()
    document = client.get('/documents').json()['documents'][0]
    assert document['title'] == '自然科学 is the original document title'
    assert document['authors'] == ['张三', 'Jane Smith']
    assert set(document['topics']) == {'自然科学', '原始主题', 'NPU'}


def test_separate_sessions_do_not_share_interface_language(client, monkeypatch):
    english, _ = open_app(client, monkeypatch, 'en')
    chinese, _ = open_app(client, monkeypatch)
    assert english.title[0].value == 'Digital Library'
    assert chinese.title[0].value == '专题数字图书馆'
    english.run()
    assert english.title[0].value == 'Digital Library'


def test_english_source_page_keeps_exact_quote_and_highlights(client, imported):
    hit, span, params = source(client)
    response = client.get('/sources/' + hit['chunk']['chunk_id'], params={**params, 'lang': 'en'})
    assert response.status_code == 200
    assert '<html lang="en"' in response.text
    assert 'Cited source' in response.text and 'Open original PDF' in response.text
    assert span['text'] in response.text and '<mark ' in response.text


@pytest.mark.parametrize('language,expected', [('zh', '自然科学'), ('en', 'Natural sciences')])
def test_display_labels_do_not_change_classification_or_counts(language, expected):
    from dlrag.shared.i18n import use_language, t
    from dlrag.ui.library import discipline, domain_counts, cover_card
    document = {'doc_id': 'fixture', 'title': '原始题名', 'authors': ['原始作者'], 'topics': ['自然科学'], 'year': 2024}
    original = copy.deepcopy(document)
    with use_language(language):
        assert t('自然科学') == expected
        assert expected in cover_card(document, 'http://127.0.0.1:19040')
        assert '原始题名' in cover_card(document, 'http://127.0.0.1:19040')
        assert discipline(document) == '自然科学'
        assert domain_counts([document]) == ({'自然科学': 1, '社会科学': 0, '哲学与人文科学': 0}, 0)
    assert document == original


@pytest.mark.parametrize('code', ['FULLTEXT_REVIEW_REQUIRED', 'TEXT_LAYER_REVIEW_REQUIRED', 'MODEL_TIMEOUT', 'DISCIPLINE_REQUIRED'])
def test_known_backend_errors_have_english_messages_and_preserve_code(code):
    from dlrag.shared.i18n import use_language, error_message
    with use_language('en'):
        text = error_message({'code': code, 'message': '中文后端提示', 'fulltext_review': {'suspect_pages': [2, 4]}})
        assert '中文后端提示' not in text
        assert text.strip()
        if code in {'FULLTEXT_REVIEW_REQUIRED', 'TEXT_LAYER_REVIEW_REQUIRED'}:
            assert '2' in text and '4' in text


def test_static_interface_messages_have_english_catalogue_entries():
    from dlrag.shared.i18n import MESSAGES
    root = Path(APP).parents[1]
    files = [Path(APP), root / 'ui/library.py', root / 'ui/citations.py', root / 'api/sources.py']
    missing = []
    for file in files:
        for node in ast.walk(ast.parse(file.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 't' and node.args:
                value = node.args[0]
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    if any('\u4e00' <= c <= '\u9fff' for c in value.value) and value.value not in MESSAGES:
                        missing.append(value.value)
    assert not missing


def test_citation_url_carries_locale_and_context_is_restored():
    from urllib.parse import urlparse, parse_qs
    from dlrag.shared.i18n import use_language, get_language
    from dlrag.ui.citations import source_url
    with use_language('zh'):
        with use_language('en'):
            params = parse_qs(urlparse(source_url('http://localhost', {'chunk_id': 'x'}, [], 'v1')).query)
            assert params == {'index_version': ['v1'], 'lang': ['en']}
        assert get_language() == 'zh'
        assert 'lang=' not in source_url('http://localhost', {'chunk_id': 'x'}, [], 'v1')


def test_english_source_error_and_invalid_locale(client):
    response = client.get('/sources/missing?lang=en')
    assert response.status_code == 404
    assert response.json()['error']['code'] == 'NOT_FOUND'
    assert 'does not exist' in response.json()['error']['message']
    assert client.get('/sources/missing?lang=invalid').status_code == 422
