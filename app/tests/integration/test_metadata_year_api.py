"""Exercise MQ-003 through actual preview/import jobs with a stub model reply."""
import json
import time

import fitz
from pydantic import SecretStr
import pytest


def wait(client, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = client.get('/document-jobs/' + job_id).json()
        if result['stage'] in {'done', 'error'}:
            return result
        time.sleep(0.01)
    pytest.fail('metadata/import job did not finish')


@pytest.mark.parametrize('revision_only', [True, False])
def test_enhanced_job_year_policy_is_visible_and_manual_correction_can_import(
        client, services, monkeypatch, revision_only):
    services.settings.app_mode = 'real'
    services.settings.siliconflow_api_key = SecretStr('synthetic-test-key')
    evidence = '17 Feb 2023' if revision_only else 'Published as a conference paper at ICLR 2022'
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 70), 'Evidence Search for Libraries', fontsize=18)
        page.insert_text((40, 110), 'Alice Smith and Bob Jones')
        page.insert_text((40, 150), 'arXiv:2111.13824v4 ' + evidence if revision_only else evidence)
        data = pdf.tobytes()
    reply = {
        'title': {'value': 'Evidence Search for Libraries', 'pdf_page': 1, 'excerpt': 'Evidence Search for Libraries'},
        'authors': {'value': ['Alice Smith', 'Bob Jones'], 'pdf_page': 1, 'excerpt': 'Alice Smith and Bob Jones'},
        'year': {'value': 2023 if revision_only else 2022, 'pdf_page': 1,
                 'excerpt': evidence, 'date_type': 'publication'},
    }
    monkeypatch.setattr('dlrag.ingestion.metadata_api.request_candidates', lambda *args: reply)
    uploaded = client.post('/documents/metadata/jobs', files={'file': ('synthetic.pdf', data, 'application/pdf')},
                           data={'use_api': 'true'})
    assert uploaded.status_code == 202
    job = wait(client, uploaded.json()['job_id'])
    assert job['stage'] == 'done'
    preview = job['result']
    assert preview['api_assistance']['status'] == 'completed'
    assert preview['metadata']['year'] == (2023 if revision_only else 2022)
    assert preview['requires_confirmation'] is True
    assert services.library.list_documents(include_nonready=True) == []
    assert services.manifest() is None
    if revision_only:
        assert preview['year_review']['date_type'] == 'version'
        assert preview['field_sources']['year']['date_type'] == 'version'
    metadata = preview['metadata']
    metadata['year'] = 2022  # An explicit user correction remains allowed.
    imported = client.post('/documents/jobs', files={'file': ('synthetic.pdf', data, 'application/pdf')},
                           data={'metadata_json': json.dumps(metadata)})
    job = wait(client, imported.json()['job_id'])
    assert job['stage'] == 'done' and job['result']['document']['year'] == 2022
