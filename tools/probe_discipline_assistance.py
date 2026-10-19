"""Run six real PDF previews with assistance off/on in a new marked dev store."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.catalog_batch import LocalAPI, code_identity, prepare, apply, write_json
from dlrag.shared.disciplines import DOMAINS
from dlrag.ui.library import domain_counts


def wait(api, ident):
    for _ in range(1200):
        job = api.poll(ident)
        if job['stage'] in {'done', 'error'}:
            if job['stage'] != 'done':
                raise RuntimeError('Preview job failed: ' + job['error']['code'])
            return job
        time.sleep(.25)
    raise RuntimeError('Preview timed out; inspect job before resubmitting')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--api', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    code = code_identity()
    if code['dirty']: raise RuntimeError('Use a clean source commit')
    api = LocalAPI(a.api)
    marker = api.request('GET', '/validation/environment')
    if not marker.get('validation_only') or marker['code']['commit'] != code['commit']:
        raise RuntimeError('Backend source identity does not match this dev checkout')
    before = api.snapshot()
    if before['documents'] or before['manifest']['document_count']:
        raise RuntimeError('Use a new empty dev library')
    a.output.mkdir(parents=True, exist_ok=False)
    write_json(a.output / 'empty-library-checkpoint.json', before)
    manifest = json.loads(a.manifest.read_text(encoding='utf-8'))
    if len(manifest['items']) != 6: raise ValueError('Expected the six source PDFs')
    corrected = copy.deepcopy(manifest)
    corrected['batch_id'] = 'MQ-006-llm-assisted-six'
    results = []
    for original, item in zip(manifest['items'], corrected['items']):
        raw = Path(original['pdf_path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != original['sha256']:
            raise ValueError('PDF source hash changed')
        previews = {}
        for enabled in [False, True]:
            submitted = api.request('POST', '/documents/metadata/jobs',
                files={'file': (item['item_id'] + '.pdf', raw, 'application/pdf')},
                data={'use_api': str(enabled).lower(), 'use_lookup': 'false'})
            previews[str(enabled)] = wait(api, submitted['job_id'])
        off, on = previews['False']['result'], previews['True']['result']
        assert off['api_assistance']['status'] == 'disabled'
        decision = on['discipline_classification']
        assert on['api_assistance']['status'] == 'completed', on['api_assistance']
        assert decision['status'] == 'classified' and decision['value'] == '自然科学', decision
        assert decision['method'] == 'llm_page_classification', decision
        assert '自然科学' in on['metadata']['topics']
        # Retain the previously reviewed title/authors/year; take ONLY the automatic
        # discipline from the fresh preview. No manual discipline tag is inserted.
        item['metadata_before'] = copy.deepcopy(item['metadata'])
        item['metadata']['topics'] = [t for t in item['metadata'].get('topics', []) if t not in DOMAINS]
        item['metadata']['topics'].extend(t for t in on['metadata']['topics'] if t in DOMAINS)
        item['review'] = {'status': 'ready', 'method': 'automated_pdf_check',
            'evidence': 'Original frozen reviewed fields plus fresh enhanced automatic discipline; see paired preview job.'}
        write_json(a.output / (item['item_id'] + '-previews.json'), previews)
        results.append({'item_id': item['item_id'], 'sha256': original['sha256'],
            'off_classification': off['discipline_classification'],
            'on_classification': decision, 'enhanced_stages': previews['True']['stages'],
            'off_job_id': previews['False']['job_id'], 'on_job_id': previews['True']['job_id']})
        print(json.dumps({'item_id':item['item_id'], 'off':off['discipline_classification']['status'],
                          'on':decision['value'], 'method':decision['method']}, ensure_ascii=False), flush=True)
    assert api.snapshot() == before, 'Previews must not write catalogue records'
    write_json(a.output / 'generated-manifest.json', corrected)
    plan, payloads = prepare(a.output / 'generated-manifest.json')
    receipt = apply(plan, payloads, a.output / 'batch', api,
                    backup_ref='empty-library-checkpoint.json; isolated zero-document store')
    assert receipt['collection_delta_verified']
    after = api.snapshot()
    counts, pending = domain_counts(after['documents'])
    assert len(after['documents']) == 6 and pending == 0 and counts['自然科学'] == 6
    assert all(d['status'] == 'ready' for d in after['documents'])
    searches = []
    for item in plan['items']:
        for mode in ['keyword', 'vector', 'hybrid']:
            hits = api.request('POST', '/search', json={'query':item['metadata']['title'], 'mode':mode, 'top_k':5})['hits']
            assert any(h['chunk']['doc_id'] == item['expected_doc_id'] for h in hits)
            searches.append({'item_id':item['item_id'], 'mode':mode, 'found_in_top5':True})
    write_json(a.output / 'result.json', {'code':code, 'passed':True, 'papers':results,
        'scope':'Fresh paired off/on previews; original reviewed non-discipline fields retained for import.',
        'previews_left_store_unchanged':True, 'after':after, 'domain_counts':counts, 'pending_count':pending,
        'searches':searches, 'receipt_tail':receipt['last_event_sha256']})
    print(json.dumps({'passed':True, 'llm_classified':6, 'pending':0, 'searches':len(searches)}))


if __name__ == '__main__': main()
