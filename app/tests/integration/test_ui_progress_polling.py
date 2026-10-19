from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


@pytest.mark.parametrize('stage', ['planning', 'generation', 'citation_grounding'])
def test_repeated_slow_job_stage_keeps_progress_and_renders_answer(client, imported, monkeypatch, stage):
    polls = []

    def local_api(base, method, path, **kwargs):
        if method == 'GET' and path.startswith('/ask/jobs/'):
            polls.append(path)
            if len(polls) <= 2:
                return {'job_id': path.rsplit('/', 1)[-1], 'stage': stage,
                        'elapsed_seconds': float(len(polls)), 'stages': ['queued', stage],
                        'answer': None}
        return client.request(method, path, **kwargs).json()

    monkeypatch.setattr('dlrag.ui.client.call_api', local_api)
    app = AppTest.from_file(str(Path(__file__).parents[2] / 'src/dlrag/ui/app.py'),
                            default_timeout=20).run()
    app.sidebar.radio[0].set_value('搜索与问答').run()
    next(w for w in app.radio if w.label == '操作').set_value('问答')
    app.text_area[0].set_value('BM25')
    next(w for w in app.button if w.label == '提交').click().run()
    assert not app.exception
    assert len(polls) >= 3
    assert app.session_state['answer']['claims']
    assert app.session_state['last_progress']['stage'] == 'done'
    assert any('处理完成' in w.value for w in app.markdown)
    next(w for w in app.button if '查看原文' in w.label).click().run()
    assert not app.exception
    assert app.session_state['selected_evidence'] == 'ev_1'


def test_submission_failure_restores_idle_progress_without_duplicate_key(client, imported, monkeypatch):
    def local_api(base, method, path, **kwargs):
        if method == 'POST' and path == '/ask/jobs':
            return {'_failure': {'code': 'MODEL_UNAVAILABLE', 'message': '测试服务不可用'}}
        return client.request(method, path, **kwargs).json()

    monkeypatch.setattr('dlrag.ui.client.call_api', local_api)
    app = AppTest.from_file(str(Path(__file__).parents[2] / 'src/dlrag/ui/app.py'),
                            default_timeout=20).run()
    app.sidebar.radio[0].set_value('搜索与问答').run()
    next(w for w in app.radio if w.label == '操作').set_value('问答')
    app.text_area[0].set_value('BM25')
    next(w for w in app.button if w.label == '提交').click().run()
    assert not app.exception
    assert any('测试服务不可用' in w.value for w in app.error)
    assert any('提交问答后' in w.value for w in app.caption)
