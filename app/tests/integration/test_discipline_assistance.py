"""MQ-006 continuation: keyword classification with opt-in LLM fallback."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import fitz
from pydantic import SecretStr
import pytest
from streamlit.testing.v1 import AppTest
import requests

from dlrag.ingestion.metadata_api import recognize_metadata, request_candidates
from test_fulltext_gate import wait_job


TITLES = [
    'Squeezing Operator Performance Potential for the Ascend Architecture',
    'CSB-RNN: A Faster-than-Realtime RNN Acceleration Framework with Compressed Structured Blocks',
    'ENEC: A Lossless AI Model Compression Method Enabling Fast Inference on Ascend NPUs',
    'Is Your NPU Ready for LLMs? Dissecting the Hidden Efficiency Bottlenecks in Mobile LLM Inference',
    'SpinQuant: LLM Quantization with Learned Rotations',
    'XY-Serve: End-to-End Versatile Production Serving for Dynamic LLM Workloads',
]
PROOF = 'We study efficient execution of computing kernels on AI accelerators.'


def pdf_bytes(title=TITLES[0], proof=PROOF):
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_textbox(fitz.Rect(40, 50, 550, 200), title, fontsize=14)
        page.insert_textbox(fitz.Rect(40, 220, 550, 600), proof, fontsize=11)
        pdf.set_metadata({'title': title})
        return pdf.tobytes()


def response(domain='自然科学'):
    return {'discipline': {'value': domain, 'pdf_page': 1, 'excerpt': PROOF,
                           'reason': '研究计算加速器与计算内核。'}}


def enhanced(services, monkeypatch, reply=None):
    services.settings.app_mode = 'real'
    services.settings.siliconflow_api_key = SecretStr('offline-classification-fixture')
    model = Mock(return_value=copy.deepcopy(response() if reply is None else reply))
    monkeypatch.setattr('dlrag.ingestion.metadata_api.request_candidates', model)
    return model


def preview(client, raw, *, job=False, assist=True):
    r = client.post('/documents/metadata' + ('/jobs' if job else ''),
                    files={'file': ('fixture.pdf', raw, 'application/pdf')},
                    data={'use_api': str(assist).lower()})
    assert r.status_code == (202 if job else 200), r.text
    return wait_job(client, r.json()['job_id'])['result'] if job else r.json()


@pytest.mark.parametrize('title', TITLES)
@pytest.mark.parametrize('job', [False, True])
def test_six_unmatched_titles_receive_llm_discipline_and_can_import(client, services, monkeypatch, title, job):
    model = enhanced(services, monkeypatch)
    raw = pdf_bytes(title)
    result = preview(client, raw, job=job)
    assert result['metadata']['topics'] == ['自然科学']
    decision = result['discipline_classification']
    assert decision['method'] == 'llm_page_classification' and decision['status'] == 'classified'
    assert decision['pdf_page'] == 1 and decision['excerpt'] == PROOF
    assert result['requires_confirmation'] is True
    assert services.library.list_documents(include_nonready=True) == []
    model.assert_called_once()
    imported = client.post('/documents/jobs', files={'file': ('fixture.pdf', raw, 'application/pdf')},
                           data={'metadata_json': json.dumps(result['metadata'])})
    stored = wait_job(client, imported.json()['job_id'])
    assert stored['stage'] == 'done'
    assert '自然科学' in stored['result']['document']['topics']


@pytest.mark.parametrize('title,domain', [('Neural computation methods', '自然科学'),
                                         ('Economics of public policy', '社会科学'),
                                         ('History of art', '哲学与人文科学')])
def test_keywords_take_priority_over_a_conflicting_model_reply(client, services, monkeypatch, title, domain):
    enhanced(services, monkeypatch, response('社会科学' if domain != '社会科学' else '自然科学'))
    result = preview(client, pdf_bytes(title))
    assert result['metadata']['topics'] == [domain]
    assert result['discipline_classification']['method'] == 'keyword'


@pytest.mark.parametrize('gate', ['user_off', 'server_off', 'mock', 'no_key'])
def test_no_llm_call_when_assistance_is_unavailable(client, services, monkeypatch, gate):
    model = enhanced(services, monkeypatch)
    if gate == 'server_off': services.settings.metadata_api_enabled = False
    if gate == 'mock': services.settings.app_mode = 'mock'
    if gate == 'no_key': services.settings.siliconflow_api_key = SecretStr('')
    result = preview(client, pdf_bytes(), assist=gate != 'user_off')
    model.assert_not_called()
    assert result['discipline_classification']['status'] == 'pending'
    assert result['metadata']['topics'] == []


def test_keywords_classify_without_enhancement(client, services, monkeypatch):
    model = enhanced(services, monkeypatch)
    result = preview(client, pdf_bytes('Neural computation methods'), assist=False)
    assert result['metadata']['topics'] == ['自然科学']
    assert result['discipline_classification']['method'] == 'keyword'
    model.assert_not_called()


@pytest.mark.parametrize('bad', [None, {}, {'value': '其他'},
    {'value': ['自然科学'], 'pdf_page': 1, 'excerpt': PROOF},
    {'value': '自然科学', 'pdf_page': True, 'excerpt': PROOF},
    {'value': '自然科学', 'pdf_page': 2, 'excerpt': PROOF},
    {'value': '自然科学', 'pdf_page': 1, 'excerpt': 'Invented evidence nowhere in the PDF.'},
    {'value': '自然科学', 'pdf_page': 1, 'excerpt': ''},
    {'value': '自然科学', 'pdf_page': 1, 'excerpt': PROOF, 'reason': ['bad']}])
def test_unusable_model_classification_remains_pending(client, services, monkeypatch, bad):
    enhanced(services, monkeypatch, {'discipline': bad})
    result = preview(client, pdf_bytes())
    assert result['metadata']['topics'] == []
    assert result['discipline_classification']['status'] == 'pending'
    assert services.library.list_documents(include_nonready=True) == []


@pytest.mark.parametrize('domain', ['社会科学', '哲学与人文科学'])
def test_user_can_override_llm_selection_before_import(client, services, monkeypatch, domain):
    model = enhanced(services, monkeypatch)
    raw = pdf_bytes()
    result = preview(client, raw)
    result['metadata']['topics'] = [domain, 'Custom subject']
    imported = client.post('/documents', files={'file': ('fixture.pdf', raw, 'application/pdf')},
                           data={'metadata_json': json.dumps(result['metadata'])})
    assert imported.status_code == 200
    assert set(imported.json()['document']['topics']) == {domain, 'Custom subject'}
    model.assert_called_once()


@pytest.mark.parametrize('title,requested', [(TITLES[0], True), ('Neural computation methods', False)])
def test_cloud_request_asks_for_classification_only_on_keyword_miss(settings, monkeypatch, title, requested):
    settings.app_mode = 'real'
    settings.siliconflow_api_key = SecretStr('offline-classification-fixture')
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(response())}}]})
    monkeypatch.setattr('requests.post', post)
    request_candidates(settings, [{'pdf_page': 1, 'text': PROOF, 'image': 'data:image/jpeg;base64,AA=='}],
                       {'title': title, 'topics': []})
    payload = json.loads(calls[0][1]['json']['messages'][1]['content'][0]['text'])
    assert payload['classify_discipline'] is requested
    assert calls[0][0] == 'https://api.siliconflow.cn/v1/chat/completions'
    assert len(calls) == 1


def test_upload_page_prefills_llm_selection_and_displays_its_source(client, services, monkeypatch):
    enhanced(services, monkeypatch)
    raw = pdf_bytes()
    monkeypatch.setattr('streamlit.file_uploader', lambda *a, **k: SimpleNamespace(name='fixture.pdf', getvalue=lambda: raw))
    def api(base, method, path, **kwargs):
        return client.request(method, path, **kwargs).json()
    monkeypatch.setattr('dlrag.ui.client.call_api', api)
    app = AppTest.from_file(str(Path(__file__).parents[2] / 'src/dlrag/ui/app.py'), default_timeout=25).run()
    app.sidebar.radio[0].set_value('上传与管理').run()
    assert not app.exception
    assert app.selectbox(key='upload_domain').value == '自然科学'
    assert any('LLM 辅助分类' in w.value for w in app.markdown)


def test_classification_timeout_leaves_an_editable_pending_preview(client, services, monkeypatch):
    model = enhanced(services, monkeypatch)
    model.side_effect = requests.Timeout('private-provider-detail')
    result = preview(client, pdf_bytes())
    assert result['api_assistance']['error_code'] == 'API_TIMEOUT'
    assert result['discipline_classification']['status'] == 'pending'
    assert result['metadata']['topics'] == []
    assert 'private-provider-detail' not in json.dumps(result)
    assert services.library.list_documents(include_nonready=True) == []


def test_ambiguous_keyword_hits_allow_llm_to_resolve_the_main_subject(client, services, monkeypatch):
    enhanced(services, monkeypatch)
    result = preview(client, pdf_bytes('Neural methods in economics'))
    assert result['metadata']['topics'] == ['自然科学']
    assert result['discipline_classification']['method'] == 'llm_page_classification'


@pytest.mark.parametrize('printed', [PROOF.replace('computing', 'comput-\ning'),
                                    PROOF.replace('efficient', 'e\ufb03cient')])
def test_pdf_line_wraps_and_typographic_ligatures_support_the_same_excerpt(printed):
    from dlrag.ingestion.discipline import complete_discipline
    result = {'metadata': {'title': TITLES[0], 'topics': []}}
    accepted = complete_discipline(result, response()['discipline'],
                                  [{'pdf_page': 1, 'text': printed, 'validation_text': printed}])
    assert accepted == 1
    assert result['metadata']['topics'] == ['自然科学']


def test_ellipses_retain_only_a_contiguous_verifiable_excerpt():
    from dlrag.ingestion.discipline import complete_discipline
    result = {'metadata': {'title': TITLES[0], 'topics': []}}
    candidate = response()['discipline']
    candidate['excerpt'] = PROOF + ' ... This unverified second fragment must never be displayed.'
    assert complete_discipline(result, candidate, [{'pdf_page': 1, 'text': PROOF}]) == 1
    assert result['discipline_classification']['excerpt'] == PROOF
