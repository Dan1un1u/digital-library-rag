from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from dlrag.ui.state import reset_question, reset_upload, reset_view


def test_scoped_resets_preserve_navigation_and_preferences():
    state = {'last_progress': {'stage': 'done'}, 'answer': {}, 'search_result': {},
             'selected_evidence': 'old', 'answer_filters': {}, 'last_request_id': 'old',
             'upload_pdf': object(), 'upload_title': 'Old', 'upload_preview': {},
             'upload_fingerprint': 'old', 'upload_success': 'old',
             'navigation_page': '上传与管理', 'preference': True}
    reset_question(state)
    assert 'last_progress' not in state and 'answer' not in state
    reset_upload(state, keep_file=True)
    assert 'upload_pdf' in state and 'upload_title' not in state
    reset_view(state)
    assert state == {'navigation_page': '上传与管理', 'preference': True}


def test_new_submission_and_navigation_clear_old_progress(client, imported, monkeypatch):
    submissions = []
    def local_api(base, method, path, **kwargs):
        if method == 'POST' and path == '/ask/jobs':
            # The reset must run before submitting, including when POST is slow.
            assert 'last_progress' not in st.session_state
            assert 'answer' not in st.session_state
            assert 'search_result' not in st.session_state
            assert 'selected_evidence' not in st.session_state
            submissions.append(kwargs['json']['question'])
        return client.request(method, path, **kwargs).json()
    monkeypatch.setattr('dlrag.ui.client.call_api', local_api)
    app = AppTest.from_file(str(Path(__file__).parents[2] / 'src/dlrag/ui/app.py'), default_timeout=20).run()
    app.sidebar.radio[0].set_value('搜索与问答').run()
    next(w for w in app.radio if w.label == '操作').set_value('问答')
    app.text_area[0].set_value('BM25')
    next(w for w in app.button if w.label == '提交').click().run()
    assert not app.exception
    first_id = app.session_state['last_progress']['job_id']
    next(w for w in app.button if '查看原文' in w.label).click().run()
    assert app.session_state['selected_evidence'] == 'ev_1'
    app.text_area[0].set_value('什么是 BM25')
    next(w for w in app.button if w.label == '提交').click().run()
    assert not app.exception
    assert app.session_state['last_progress']['job_id'] != first_id
    assert submissions == ['BM25', '什么是 BM25']
    app.sidebar.radio[0].set_value('馆藏展示').run()
    assert 'last_progress' not in app.session_state
    assert 'answer' not in app.session_state
    app.sidebar.radio[0].set_value('搜索与问答').run()
    assert not app.exception
    assert any('提交问答后' in c.value for c in app.caption)
    assert not any('已用时' in c.value for c in app.caption)
    assert not any('查看原文' in b.label for b in app.button)


def test_secondary_navigation_clears_upload_candidates(client, monkeypatch):
    monkeypatch.setattr('dlrag.ui.client.call_api', lambda base, method, path, **kwargs: client.request(method, path, **kwargs).json())
    app = AppTest.from_file(str(Path(__file__).parents[2] / 'src/dlrag/ui/app.py'), default_timeout=20).run()
    app.sidebar.radio[0].set_value('上传与管理').run()
    app.session_state['upload_preview'] = {'metadata': {'title': 'Old'}}
    app.session_state['upload_fingerprint'] = 'Old'
    app.session_state['last_progress'] = {'stage': 'done'}
    app.sidebar.radio[1].set_value('文献管理').run()
    assert not app.exception
    assert 'upload_preview' not in app.session_state
    assert 'upload_fingerprint' not in app.session_state
    assert 'last_progress' not in app.session_state
    app.sidebar.radio[1].set_value('上传文献').run()
    assert not app.exception
    assert app.text_input(key='upload_title').value == ''
