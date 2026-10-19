"""MQ-006: require an explicit discipline at every new-ingestion boundary."""
import copy
import hashlib
import json
import time
from unittest.mock import Mock

import pytest

from dlrag.api.services import ProjectError
from dlrag.ui.library import discipline
from tools import catalog_batch as batch


PAPERS = [
    ('Squeezing Operator Performance Potential for the Ascend Architecture', ['AI accelerators', 'Ascend NPU']),
    ('CSB-RNN: A Faster-than-Realtime RNN Acceleration Framework with Compressed Structured Blocks', ['FPGA', 'RNN acceleration']),
    ('ENEC: A Lossless AI Model Compression Method Enabling Fast Inference on Ascend NPUs', ['LLM inference', 'Lossless compression']),
    ('Is Your NPU Ready for LLMs? Dissecting the Hidden Efficiency Bottlenecks in Mobile LLM Inference', ['Mobile LLM', 'NPU']),
    ('SpinQuant: LLM Quantization with Learned Rotations', ['LLM inference', 'Learned rotations']),
    ('XY-Serve: End-to-End Versatile Production Serving for Dynamic LLM Workloads', ['LLM serving', 'Ascend NPU']),
]
DOMAINS = ['自然科学', '社会科学', '哲学与人文科学']


def post(client, route, pdf, metadata):
    return client.post(route, files={'file': ('fixture.pdf', pdf.read_bytes(), 'application/pdf')},
                       data={'metadata_json': json.dumps(metadata, ensure_ascii=False)})


def completed(client, response, route):
    if route == '/documents':
        assert response.status_code == 200, response.text
        return response.json()
    assert response.status_code == 202, response.text
    for _ in range(200):
        job = client.get('/document-jobs/' + response.json()['job_id']).json()
        if job['stage'] in {'done', 'error'}:
            assert job['stage'] == 'done', job
            return job['result']
        time.sleep(.01)
    raise AssertionError('Import did not finish')


@pytest.mark.parametrize('route', ['/documents', '/documents/jobs'])
@pytest.mark.parametrize('title,topics', PAPERS)
def test_six_original_subject_lists_rejected_before_any_write(client, services, pdf, monkeypatch, route, title, topics):
    before = services.manifest()
    store = Mock(side_effect=AssertionError('Missing discipline must not reach storage'))
    submit = Mock(side_effect=AssertionError('Missing discipline must not enqueue a job'))
    monkeypatch.setattr(services, 'ingest', store)
    monkeypatch.setattr(client.app.state.document_jobs, 'submit', submit)
    response = post(client, route, pdf, {'title': title, 'topics': topics})
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'DISCIPLINE_REQUIRED'
    assert '学科' in response.json()['error']['message']
    assert services.library.list_documents(include_nonready=True) == []
    assert services.manifest() == before
    store.assert_not_called()
    submit.assert_not_called()


@pytest.mark.parametrize('route', ['/documents', '/documents/jobs'])
def test_conflicting_disciplines_rejected(client, services, pdf, route):
    response = post(client, route, pdf, {'title': 'Mixed subject terms', 'topics': DOMAINS[:2]})
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'DISCIPLINE_CONFLICT'
    assert services.library.list_documents(include_nonready=True) == []


@pytest.mark.parametrize('route', ['/documents', '/documents/jobs'])
@pytest.mark.parametrize('domain', DOMAINS)
def test_explicit_discipline_survives_import_and_overrides_conflicting_keywords(client, pdf, route, domain):
    metadata = {'title': 'Language models in education and philosophy', 'topics': [domain, 'NPU']}
    result = completed(client, post(client, route, pdf, metadata), route)
    document = result['document']
    assert set(document['topics']) == {domain, 'NPU'}
    assert discipline(document) == domain
    stored = client.get('/documents/' + document['doc_id']).json()['document']
    assert stored['topics'] == document['topics']


def manifest(tmp_path, pdf, metadata):
    value = {'schema_version': 1, 'batch_id': 'MQ-006-fixture', 'items': [{
        'item_id': 'fixture', 'pdf_path': str(pdf), 'sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(),
        'metadata': metadata, 'review': {'status': 'ready', 'method': 'automated_pdf_check',
                                       'evidence': 'Synthetic PDF and selected discipline.'}}]}
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return path


@pytest.mark.parametrize('title,topics', PAPERS)
def test_batch_plan_rejects_the_six_missing_disciplines(tmp_path, pdf, title, topics):
    path = manifest(tmp_path, pdf, {'title': title, 'topics': topics})
    with pytest.raises(batch.BatchError, match='学科'):
        batch.prepare(path)


def test_batch_plan_rejects_conflicting_disciplines(tmp_path, pdf):
    path = manifest(tmp_path, pdf, {'title': 'fixture', 'topics': DOMAINS[:2]})
    with pytest.raises(batch.BatchError, match='学科'):
        batch.prepare(path)


def test_apply_revalidates_even_an_old_correctly_hashed_plan_before_network(tmp_path, pdf):
    path = manifest(tmp_path, pdf, {'title': 'fixture', 'topics': ['自然科学', 'NPU']})
    plan, payloads = batch.prepare(path)
    plan['items'][0]['metadata']['topics'] = ['NPU']
    plan['plan_sha256'] = batch.digest({k: v for k, v in plan.items() if k != 'plan_sha256'})
    api = Mock()
    with pytest.raises(batch.BatchError, match='学科'):
        batch.apply(plan, payloads, tmp_path / 'output', api, backup_ref='synthetic checkpoint')
    api.snapshot.assert_not_called()
    api.submit.assert_not_called()
    assert not (tmp_path / 'output').exists()


def test_direct_service_cannot_bypass_discipline_admission(services, pdf, monkeypatch):
    store = Mock(side_effect=AssertionError('Must validate before parsing'))
    monkeypatch.setattr(services.library, 'ingest_pdf', store)
    with pytest.raises(ProjectError) as error:
        services.ingest(str(pdf), {'title': 'NPU research', 'topics': ['NPU']})
    assert error.value.code == 'DISCIPLINE_REQUIRED'
    store.assert_not_called()


def test_historical_unclassified_documents_remain_readable(client, services, pdf):
    # Storage/reading still accepts an old record; new-ingestion policy is separate.
    record = services.library.ingest_pdf(str(pdf), {'title': 'Old record', 'topics': []},
                                         services.settings.chunking_config.model_dump())
    services.rebuild()
    response = client.get('/documents/' + record['doc_id'])
    assert response.status_code == 200
    assert response.json()['document']['topics'] == []
    assert discipline(response.json()['document']) is None


def test_duplicate_keeps_selected_discipline_and_index(client, services, pdf):
    metadata = {'title': 'NPU research', 'topics': ['自然科学', 'NPU']}
    first = completed(client, post(client, '/documents', pdf, metadata), '/documents')
    before = copy.deepcopy(services.manifest())
    second = completed(client, post(client, '/documents/jobs', pdf, metadata), '/documents/jobs')
    assert second['document'] == first['document']
    assert services.manifest() == before


def test_repeated_same_discipline_is_not_a_conflict(client, pdf):
    result = completed(client, post(client, '/documents', pdf,
        {'title': 'NPU research', 'topics': ['自然科学', '自然科学', 'NPU']}), '/documents')
    assert result['document']['topics'] == ['NPU', '自然科学']


def test_batch_plan_preserves_explicit_discipline_and_other_metadata(tmp_path, pdf):
    metadata = {'title': PAPERS[0][0], 'authors': ['Synthetic author'], 'year': 2025,
                'topics': ['自然科学', 'NPU'], 'language': 'en'}
    path = manifest(tmp_path, pdf, metadata)
    plan, _ = batch.prepare(path)
    assert all(plan['items'][0]['metadata'][k] == v for k, v in metadata.items())
