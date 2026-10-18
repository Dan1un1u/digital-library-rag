"""Reproducible live smoke checks; no paid model requests or corpus mutation."""
import hashlib
import json
from pathlib import Path
import time
from datetime import datetime, timezone
import requests

ROOT = Path(__file__).resolve().parents[1]
results = []
session = requests.Session()
session.trust_env = False


def check(name, actual, expected=True, **details):
    result = {'name': name, 'passed': actual == expected,
              'actual': actual, 'expected': expected, **details}
    results.append(result)
    print(('PASS ' if result['passed'] else 'FAIL ') + name, flush=True)


def get(base, path):
    return session.get(base + path, timeout=20)


def post(base, path, body):
    return session.post(base + path, json=body, timeout=20)


def run():
    for mode, api_port, ui_port in [('real', 18000, 18501), ('mock', 18001, 18502)]:
        base = f'http://127.0.0.1:{api_port}'
        health_response = get(base, '/health')
        check(mode + '_health_http', health_response.status_code, 200)
        health = health_response.json()
        (ROOT / 'evidence' / f'{mode}_health.json').write_text(
            json.dumps(health, ensure_ascii=False, indent=2), encoding='utf-8')
        check(mode + '_mode', health['mode'], mode)
        check(mode + '_index_loaded', health['manifest'] is not None)
        check(mode + '_ui_health', get(f'http://127.0.0.1:{ui_port}', '/_stcore/health').status_code, 200)
        docs = get(base, '/documents').json()['documents']
        minimum = 14 if mode == 'real' else 2
        check(mode + '_document_count', len(docs) >= minimum,
              document_count=len(docs), minimum_documents=minimum)
        (ROOT / 'reports' / f'{mode}_catalogue.json').write_text(
            json.dumps(docs, ensure_ascii=False, indent=2), encoding='utf-8')
        for index, doc in enumerate(docs):
            path = f'/documents/{doc["doc_id"]}/file'
            response = get(base, path)
            check(f'{mode}_pdf_{index + 1}_integrity',
                  response.status_code == 200 and response.content.startswith(b'%PDF')
                  and hashlib.sha256(response.content).hexdigest() == doc['file_sha256'],
                  title=doc['title'])
        cover = get(base, f'/documents/{docs[0]["doc_id"]}/cover')
        check(mode + '_pdf_cover', cover.status_code == 200 and cover.content.startswith(b'\x89PNG'))
        response = post(base, '/search', {'query': 'BM25' if mode == 'mock' else 'attention',
                                         'mode': 'keyword', 'top_k': 5})
        payload = response.json()
        check(mode + '_keyword_search', response.status_code == 200 and bool(payload.get('hits')))
        (ROOT / 'evidence' / f'{mode}_keyword_search.json').write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        if payload.get('hits'):
            chunk_id = payload['hits'][0]['chunk']['chunk_id']
            check(mode + '_chunk_lookup', get(base, '/chunks/' + chunk_id).status_code, 200)
            source = get(base, '/sources/' + chunk_id)
            check(mode + '_source_page', source.status_code == 200 and 'text/html' in source.headers.get('content-type', ''))
        check(mode + '_empty_query_rejected', post(base, '/search', {'query': '', 'mode': 'keyword'}).status_code, 422)
        check(mode + '_invalid_years_rejected', post(base, '/search', {'query': 'BM25', 'mode': 'keyword',
              'filters': {'year_from': 2025, 'year_to': 2020}}).status_code, 422)
        if mode == 'mock':
            check('mock_ready', health['status'], 'ready')
            for search_mode in ('vector', 'hybrid'):
                response = post(base, '/search', {'query': 'BM25', 'mode': search_mode, 'top_k': 5})
                check('mock_' + search_mode + '_search', response.status_code == 200 and bool(response.json().get('hits')))
            for question, status, http in [('BM25', 'answered', 200), ('那个系统', 'needs_clarification', 200),
                                           ('证据不足', 'insufficient_evidence', 200), ('超时', 'error', 503)]:
                response = post(base, '/ask', {'question': question})
                answer = response.json()
                check('mock_ask_' + status, (response.status_code, answer.get('status')), (http, status))
                (ROOT / 'evidence' / f'mock_answer_{status}.json').write_text(
                    json.dumps(answer, ensure_ascii=False, indent=2), encoding='utf-8')
            response = post(base, '/ask/jobs', {'question': 'BM25'})
            check('mock_async_job_created', response.status_code, 202)
            job_id = response.json()['job_id']
            deadline = time.monotonic() + 15
            job = {}
            while time.monotonic() < deadline:
                job = get(base, '/ask/jobs/' + job_id).json()
                if job.get('answer') is not None:
                    break
                time.sleep(.1)
            check('mock_async_job_completed', job.get('stage') == 'done' and job.get('answer', {}).get('status') == 'answered')
            raw = ROOT / 'runtime' / 'mock' / 'raw'
            file = next(raw.glob('*.pdf'))
            before = len(docs)
            with file.open('rb') as stream:
                response = session.post(base + '/documents/metadata',
                    files={'file': (file.name, stream, 'application/pdf')}, data={'use_api': 'false'}, timeout=20)
            check('mock_local_metadata_preview', response.status_code, 200)
            check('mock_preview_no_document_created', len(get(base, '/documents').json()['documents']), before)
        else:
            if not health['embedding_configured'] or not health['llm_configured']:
                check('real_without_keys_not_ready', health['status'], 'not_ready')
            # Never send a paid provider request when keys become available later.
            if not health['embedding_configured']:
                response = post(base, '/search', {'query': 'attention', 'mode': 'vector'})
                check('real_vector_reports_missing_key', response.status_code, 503)
            if not health['llm_configured']:
                response = post(base, '/ask', {'question': 'What is attention?'})
                check('real_ask_reports_missing_key', (response.status_code, response.json().get('error', {}).get('code')),
                      (503, 'MODEL_NOT_CONFIGURED'))


if __name__ == '__main__':
    error = None
    try:
        run()
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
        check('smoke_execution_completed', False, detail=error)
    report = {'created_at': datetime.now(timezone.utc).isoformat(),
              'checks': len(results), 'passed': sum(row['passed'] for row in results),
              'failed': sum(not row['passed'] for row in results),
              'real_model_quality_evaluated': False, 'results': results, 'execution_error': error}
    output = ROOT / 'reports' / 'live_smoke.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('checks', 'passed', 'failed', 'execution_error')}, ensure_ascii=False))
    raise SystemExit(0 if report['failed'] == 0 else 1)
