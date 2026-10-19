import threading
import time
import json

import fitz
import pytest

from dlrag.ingestion.metadata_api import merge_candidates, recognize_metadata


def wait_job(client, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get('/document-jobs/' + job_id).json()
        if job['stage'] in {'done', 'error'}:
            return job
        time.sleep(.01)
    pytest.fail('document job did not finish')


def scanned_pdf(tmp_path):
    path = tmp_path / 'scan.pdf'
    with fitz.open() as source:
        page = source.new_page()
        page.insert_text((40, 60), 'Reading Long Documents', fontsize=20)
        page.insert_text((40, 110), 'Alice Smith and Bob Jones')
        image = page.get_pixmap().tobytes('png')
    with fitz.open() as scan:
        page = scan.new_page()
        page.insert_image(page.rect, stream=image)
        scan.save(path)
    return path


def candidates():
    return {'title': {'value': 'Reading Long Documents', 'pdf_page': 1, 'excerpt': 'Reading Long Documents'},
            'authors': {'value': ['Alice Smith', 'Bob Jones'], 'pdf_page': 1, 'excerpt': 'Alice Smith and Bob Jones'},
            'year': {'value': 2024, 'pdf_page': 1, 'excerpt': 'Published in 2024'},
            'language': {'value': 'en', 'pdf_page': 1, 'excerpt': 'Reading Long Documents'}}


def test_vision_enriches_scanned_pdf_without_ingesting(settings, tmp_path, monkeypatch):
    path = scanned_pdf(tmp_path)
    original = path.read_bytes()
    settings.app_mode = 'real'
    from pydantic import SecretStr
    settings.siliconflow_api_key = SecretStr('test-secret')
    seen = []
    def api(settings, pages, local):
        assert pages[0]['image'].startswith('data:image/jpeg;base64,')
        assert pages[0]['text'] == ''
        assert len(pages) == 1
        seen.append('api')
        return candidates()
    monkeypatch.setattr('dlrag.ingestion.metadata_api.request_candidates', api)
    stages = []
    result = recognize_metadata(path, settings, progress=stages.append)
    assert result['metadata']['title'] == 'Reading Long Documents'
    assert result['metadata']['authors'] == ['Alice Smith', 'Bob Jones']
    assert result['api_assistance']['status'] == 'completed'
    assert result['requires_confirmation']
    assert result['field_sources']['title']['pdf_page'] == 1
    assert stages == ['local_reading', 'page_preparation', 'api_recognition', 'metadata_validation']
    assert path.read_bytes() == original
    recognize_metadata(path, settings, assist=False)
    settings.app_mode = 'mock'
    recognize_metadata(path, settings)
    assert seen == ['api']


def test_api_failure_is_safe_and_local_fields_survive(settings, pdf, monkeypatch):
    from pydantic import SecretStr
    settings.app_mode = 'real'
    settings.siliconflow_api_key = SecretStr('secret-do-not-expose')
    def broken(*args):
        raise RuntimeError('secret-do-not-expose provider private body')
    monkeypatch.setattr('dlrag.ingestion.metadata_api.request_candidates', broken)
    result = recognize_metadata(pdf, settings)
    assert result['api_assistance']['status'] == 'failed'
    assert 'secret-do-not-expose' not in str(result)
    assert result['metadata']['language'] in {'zh', 'en', 'mixed'}
    assert any('保留本机' in w for w in result['warnings'])


def test_candidates_reject_invented_excerpt_invalid_types_and_links():
    result = {'metadata': {}, 'field_sources': {}}
    rows = candidates()
    rows['title']['excerpt'] = 'unrelated'
    rows['authors']['value'] = ['Unknown Author']
    rows['year']['value'] = True
    rows['source_url'] = {'value': 'https://attacker.invalid/?key=secret', 'pdf_page': 1, 'excerpt': 'secret'}
    rows['language']['pdf_page'] = 3
    assert merge_candidates(result, rows, [{}]) == 0
    assert result['metadata'] == {}


def test_interleaved_author_tokens_are_supported_but_affiliations_are_not():
    result = {'metadata': {}, 'field_sources': {}}
    row = {'authors': {'value': ['Łukasz Kaiser', 'Aidan N. Gomez'], 'pdf_page': 1,
                       'excerpt': 'Łukasz usz@google.com Kaiser · Aidan N. Gomez'}}
    assert merge_candidates(result, row, [{}]) == 1
    assert result['metadata']['authors'] == ['Łukasz Kaiser', 'Aidan N. Gomez']
    row['authors']['value'] = ['Google Brain']
    row['authors']['excerpt'] = 'Google Brain'
    assert merge_candidates(result, row, [{}]) == 0


def test_metadata_progress_does_not_hold_library_lock(client, services, pdf, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def blocked(path, settings, filename=None, assist=True, progress=None):
        progress('api_recognition')
        entered.set()
        assert release.wait(5)
        return {'metadata': {'title': 'Recognized'}}
    monkeypatch.setattr('dlrag.ingestion.metadata_api.recognize_metadata', blocked)
    try:
        response = client.post('/documents/metadata/jobs', files={'file': ('a.pdf', pdf.read_bytes(), 'application/pdf')})
        assert response.status_code == 202
        job_id = response.json()['job_id']
        assert entered.wait(2)
        assert services.lock.acquire(blocking=False)
        services.lock.release()
        job = client.get('/document-jobs/' + job_id).json()
        assert job['stage'] == 'api_recognition' and job['result'] is None
        assert job['elapsed_seconds'] >= 0
    finally:
        release.set()
    assert wait_job(client, job_id)['stage'] == 'done'
    assert services.library.list_documents(include_nonready=True) == []
    assert not list((services.settings.data_dir / 'tmp').iterdir())


def test_import_jobs_and_validation(client, services, pdf):
    assert client.post('/documents/metadata/jobs', files={'file': ('a.txt', b'no', 'text/plain')}).status_code == 415
    assert client.post('/documents/jobs', files={'file': ('a.pdf', b'bad', 'application/pdf')}, data={'metadata_json': '{bad'}).status_code == 422
    response = client.post('/documents/jobs', files={'file': ('a.pdf', pdf.read_bytes(), 'application/pdf')}, data={"metadata_json": json.dumps({"topics": ["自然科学"]})})
    job = wait_job(client, response.json()['job_id'])
    assert job['stage'] == 'done'
    assert 'document_parsing' in job['stages'] and 'document_processing' in job['stages']
    assert job['result']['document']['status'] == 'ready'
    assert not list((services.settings.data_dir / 'tmp').iterdir())
    assert client.get('/document-jobs/missing').status_code == 404
    jobs = client.app.state.document_jobs
    jobs.jobs[job['job_id']]['updated'] -= 901
    assert client.get('/document-jobs/' + job['job_id']).status_code == 404


def test_queue_limit_and_safe_job_errors(client, services, pdf, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def broken(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        raise RuntimeError('secret provider response')
    monkeypatch.setattr('dlrag.ingestion.metadata_api.recognize_metadata', broken)
    client.app.state.document_jobs.capacity = 1
    try:
        job_id = client.post('/documents/metadata/jobs', files={'file': ('a.pdf', pdf.read_bytes(), 'application/pdf')}).json()['job_id']
        assert entered.wait(2)
        assert client.post('/documents/metadata/jobs', files={'file': ('a.pdf', pdf.read_bytes(), 'application/pdf')}).status_code == 503
    finally:
        release.set()
    job = wait_job(client, job_id)
    assert job['stage'] == 'error' and 'secret' not in str(job)
    assert not list((services.settings.data_dir / 'tmp').iterdir())
