"""Reproduce and verify discipline admission in an empty, marked dev library."""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import catalog_batch as batch
from dlrag.ui.library import discipline, domain_counts


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=['baseline', 'missing', 'corrected'], required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--api', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    identity = batch.code_identity()
    if identity['dirty']:
        raise RuntimeError('Commit source before this comparison')
    api = batch.LocalAPI(args.api)
    marker = api.request('GET', '/validation/environment')
    if not marker.get('validation_only') or marker['code']['commit'] != identity['commit']:
        raise RuntimeError('Dev backend must use this clean source commit')
    before = api.snapshot()
    if before['documents'] or not before['manifest'] or before['manifest']['document_count']:
        raise RuntimeError('Comparison requires a new empty dev library')
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'work_item': 'MQ-006', 'phase': args.phase, 'code': identity,
              'created_at': datetime.now(timezone.utc).isoformat(), 'before': before,
              'backend_marker': marker, 'passed': False, 'recognition_input':
              'Replay original frozen reviewed metadata; no new recognition accuracy claim.'}
    write(args.output / 'before.json', before)
    if args.phase == 'missing':
        raw = json.loads(args.manifest.read_text(encoding='utf-8'))
        try:
            batch.prepare(args.manifest)
        except (ValueError, batch.BatchError) as error:
            report['plan_rejected'] = True
            report['plan_error_type'] = type(error).__name__
        else:
            raise AssertionError('Missing discipline passed batch preparation')
        report['api_rejections'] = []
        for item in raw['items']:
            for route in ['/documents', '/documents/jobs']:
                response = api.session.post(api.base_url + route,
                    files={'file': (item['item_id'] + '.pdf', Path(item['pdf_path']).read_bytes(), 'application/pdf')},
                    data={'metadata_json': json.dumps(item['metadata'], ensure_ascii=False)}, timeout=30,
                    allow_redirects=False)
                body = response.json()
                assert response.status_code == 422 and body['error']['code'] == 'DISCIPLINE_REQUIRED', body
                report['api_rejections'].append({'item_id': item['item_id'], 'route': route,
                    'http_status': response.status_code, 'error_code': body['error']['code']})
        after = api.snapshot()
        assert after == before
        report['no_store_or_index_change'] = True
    else:
        plan, payloads = batch.prepare(args.manifest)
        assert len(plan['items']) == 6
        write(args.output / 'fixed-plan.json', plan)
        # Preserve a verifiable empty-library checkpoint before the first write.
        write(args.output / 'empty-library-checkpoint.json', before)
        receipt = batch.apply(plan, payloads, args.output / 'batch', api,
            backup_ref='empty-library-checkpoint.json; new isolated library with zero documents')
        assert receipt['outcome'] == 'completed' and receipt['collection_delta_verified']
        after = api.snapshot()
        by_id = {d['doc_id']: d for d in after['documents']}
        assert len(by_id) == 6 and all(d['status'] == 'ready' for d in by_id.values())
        for item in plan['items']:
            stored = by_id[item['expected_doc_id']]
            assert set(stored['topics']) == set(item['metadata']['topics'])
            assert stored['file_sha256'] == item['sha256']
        report['input_sha256'] = {i['item_id']: i['sha256'] for i in plan['items']}
        report['disciplines'] = {i['item_id']: discipline(by_id[i['expected_doc_id']]) for i in plan['items']}
        counts, pending = domain_counts(after['documents'])
        report['domain_counts'], report['pending_count'] = counts, pending
        assert pending == (6 if args.phase == 'baseline' else 0)
        assert counts['自然科学'] == (0 if args.phase == 'baseline' else 6)
        report['searches'] = []
        for item in plan['items']:
            for mode in ['keyword', 'vector', 'hybrid']:
                result = api.request('POST', '/search', json={
                    'query': item['metadata']['title'], 'mode': mode, 'top_k': 5})
                hit = next((h for h in result['hits'] if h['chunk']['doc_id'] == item['expected_doc_id']), None)
                assert hit is not None, (item['item_id'], mode)
                report['searches'].append({'item_id': item['item_id'], 'mode': mode,
                    'found_in_top5': True, 'rank': hit['rank'], 'chunk_id': hit['chunk']['chunk_id']})
        if args.phase == 'corrected':
            stable = copy.deepcopy(after)
            item, data = plan['items'][0], payloads[0]
            job_id = api.submit(item, data)
            import time
            for _ in range(100):
                job = api.poll(job_id)
                if job['stage'] in {'done', 'error'}: break
                time.sleep(.1)
            assert job['stage'] == 'done'
            assert api.snapshot() == stable
            report['duplicate_import_preserved_snapshot'] = True
    report['after'] = api.snapshot()
    report['passed'] = True
    write(args.output / 'result.json', report)
    print(json.dumps({'phase': args.phase, 'passed': True,
        'documents': len(report['after']['documents']), 'pending': report.get('pending_count'),
        'rejections': len(report.get('api_rejections', [])), 'searches': len(report.get('searches', []))}, ensure_ascii=False))


if __name__ == '__main__':
    main()
