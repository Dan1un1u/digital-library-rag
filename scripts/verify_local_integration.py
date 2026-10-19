"""Exercise real local embeddings, Luna text/vision/ranking, and grounded library QA."""
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import secrets
import sys
import time
import fitz
import requests
from dlrag.api.qa_factory import create_client
from dlrag.qa.llm_client import CLIProxyLLM
from dlrag.qa.semantic_reranker import LLMReranker
from dlrag.shared.config import Settings

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:18000'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--env-file', type=Path, default=ROOT / 'app/.env')
parser.add_argument('--expected-documents', type=int)
parser.add_argument('--expected-chunks', type=int)
parser.add_argument('--resume-job', action='store_true')
parser.add_argument('--new-qa-job', action='store_true')
args = parser.parse_args()
if (args.expected_documents is None) != (args.expected_chunks is None):
    parser.error('Provide both expected counts or neither')
if args.expected_documents is not None and (args.expected_documents < 1 or args.expected_chunks < 1):
    parser.error('Expected counts must be positive')
settings = Settings(_env_file=args.env_file)
http = requests.Session()
http.trust_env = False
checks, details = [], {}


def check(name, passed, **data):
    checks.append({'name': name, 'passed': bool(passed), **data})
    print(('PASS ' if passed else 'FAIL ') + name, flush=True)
    if not passed:
        raise RuntimeError(name)


def post(path, payload, timeout=120):
    response = http.post(BASE + path, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def main():
    if '--resume-job' in sys.argv or '--new-qa-job' in sys.argv:
        previous = json.loads((ROOT / 'reports/local_models_integration.json').read_text(encoding='utf-8'))
        details.update(previous['details'])
        checks.extend(row for row in previous['checks'][:8] if row['passed'])
        if '--new-qa-job' in sys.argv:
            exercise_qa(details['health']['manifest'])
            return
        job = http.get(BASE + '/ask/jobs/' + details['qa_job']['job_id'], timeout=10).json()
        details['qa_job'] = job
        verify_answer(job, details['health']['manifest'])
        return
    health = http.get(BASE + '/health', timeout=10).json()
    details['health'] = health
    check('library_ready_with_real_models', health['status'] == 'ready' and health['mode'] == 'real'
          and health['active_models']['llm'] == 'gpt-6-luna'
          and health['active_models']['semantic_reranker'] == 'gpt-6-luna' and not health['issues'])
    manifest = health['manifest']
    response = http.get(BASE + '/documents', params={'include_nonready': True}, timeout=10)
    response.raise_for_status()
    documents = response.json()['documents']
    counts_match = (args.expected_documents is None or (
        manifest['document_count'] == args.expected_documents and manifest['chunk_count'] == args.expected_chunks))
    check('local_fp16_index_and_full_corpus', manifest['document_count'] == len(documents)
          and bool(documents) and all(d['status'] == 'ready' for d in documents)
          and manifest['chunk_count'] > 0 and counts_match
          and manifest['embedding_backend']['provider'] == 'local-bge-fp16'
          and manifest['embedding_backend']['revision_pinned'])
    details['corpus_expectation'] = {'documents': args.expected_documents, 'chunks': args.expected_chunks,
                                     'listed_documents': len(documents)}
    for mode in ('vector', 'hybrid'):
        answer = post('/search', {'query': 'retrieval augmented generation external knowledge', 'mode': mode, 'top_k': 5})
        hits = answer['hits']
        check(mode + '_retrieval_real_corpus', len(hits) == 5 and any(
            'Retrieval-Augmented Generation' in row['chunk']['document']['title'] for row in hits[:3]))
        details[mode + '_search'] = [{'title': row['chunk']['document']['title'],
                                     'pdf_page': row['chunk']['pdf_page'], 'scores': row['scores']} for row in hits]
    client = create_client(settings)
    result = client.generate_json('只输出 JSON 对象，包含 ok=true、purpose="library-integration"。', {})
    check('luna_json_generation', result.get('ok') is True and result.get('purpose') == 'library-integration')
    details['generation_usage'] = client.records
    rerank_client = CLIProxyLLM(api_key=settings.llm_api_key.get_secret_value(), model='gpt-6-luna',
        base_url=settings.llm_base_url, timeout=90, max_output_tokens=6000, context_window_tokens=262144)
    reranker = LLMReranker(rerank_client)
    passages = ['Plants transform sunlight into chemical energy through photosynthesis.',
        'Metadata completeness is evaluated by checking required title, author and publication date fields; validity checks detect malformed values.',
        'A library building has several study rooms.']
    ranked = reranker.rerank('How can metadata quality be evaluated in a digital library?',
        [{'rank': i + 1, 'chunk': {'chunk_id': str(i), 'text': text}, 'scores': {}} for i, text in enumerate(passages)])
    check('luna_semantic_reranking', ranked[0]['chunk']['chunk_id'] == '1' and len(ranked) == 3)
    details['reranking'] = [{'index': row['chunk']['chunk_id'], 'score': row['semantic_relevance']} for row in ranked]
    # Raster-only PDF prevents title/author recovery from embedded text or PDF metadata.
    title = 'Library Metadata Test ' + secrets.token_hex(2).upper()
    scan = ROOT / 'evidence/luna-vision-scan.pdf'
    scan.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open() as source:
        page = source.new_page(width=620, height=800)
        page.insert_text((45, 80), title, fontsize=22)
        page.insert_text((45, 130), 'Alice Stone and Bob Reed', fontsize=18)
        page.insert_text((45, 175), 'Published in 2024', fontsize=16)
        page.insert_text((45, 250), 'Abstract: Quality evaluation for digital library metadata.', fontsize=14)
        image = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).tobytes('png')
    with fitz.open() as output:
        page = output.new_page(width=620, height=800)
        page.insert_image(page.rect, stream=image)
        output.save(scan)
    with fitz.open(scan) as pdf:
        check('vision_fixture_has_no_embedded_text', not pdf[0].get_text().strip())
    with scan.open('rb') as stream:
        response = http.post(BASE + '/documents/metadata',
            files={'file': ('scan.pdf', stream, 'application/pdf')}, data={'use_api': 'true'}, timeout=120)
    response.raise_for_status()
    metadata = response.json()
    details['vision_metadata'] = metadata
    check('luna_image_title_and_author_recognition', metadata['api_assistance']['status'] == 'completed'
          and metadata['metadata']['title'] == title
          and metadata['metadata']['authors'] == ['Alice Stone', 'Bob Reed']
          and metadata['metadata']['year'] == 2024 and metadata['requires_confirmation'])
    exercise_qa(manifest)


def exercise_qa(manifest):
    question = 'RAG 如何结合文献检索与文本生成？请根据馆藏论文说明其基本过程。'
    submitted = post('/ask/jobs', {'question': question})
    job_id = submitted['job_id']
    deadline, seen_stages = time.monotonic() + 240, []
    while time.monotonic() < deadline:
        job = http.get(BASE + '/ask/jobs/' + job_id, timeout=10).json()
        stage = job.get('stage')
        if stage not in seen_stages:
            seen_stages.append(stage)
            print('QA stage: ' + str(stage), flush=True)
        if stage in ('done', 'error'):
            break
        time.sleep(1)
    else:
        raise RuntimeError('Grounded QA job did not complete within 240 seconds')
    details['qa_job'] = job
    details['qa_stages_observed'] = seen_stages
    verify_answer(job, manifest)


def verify_answer(job, manifest):
    answer = job.get('answer')
    check('grounded_qa_answered', isinstance(answer, dict) and answer.get('status') == 'answered'
          and answer['claims'] and answer['evidence'])
    diagnostic = answer['diagnostics']
    check('query_planning_and_bilingual_retrieval', diagnostic.get('planning_fallback') is None
          and diagnostic.get('multi_query') is True and answer['query_plan'].get('english_query'))
    check('luna_reranker_used_in_qa', diagnostic.get('semantic_rerank_status') == 'ok'
          and diagnostic.get('rerank_method') == 'llm_relevance:gpt-6-luna'
          and diagnostic.get('rerank_model_calls', 0) > 0)
    check('sentence_grounding_and_coverage', diagnostic.get('sentence_grounding_status') == 'ok'
          and diagnostic.get('coverage_check_status') == 'ok'
          and all(claim['citations'] for claim in answer['claims']))
    evidence_ids = {entry['evidence_id'] for entry in answer['evidence']}
    check('answer_references_current_index', answer['index_version'] == manifest['index_version'] and
          all(set(claim['evidence_ids']) <= evidence_ids for claim in answer['claims']))
    source = http.get(BASE + '/sources/' + answer['evidence'][0]['chunk_id'],
                      params={'index_version': manifest['index_version']}, timeout=20)
    check('citation_pdf_source_available', source.status_code == 200 and 'text/html' in source.headers.get('Content-Type', ''))
    public = json.dumps(details, ensure_ascii=False)
    check('local_client_key_absent_from_public_responses', settings.llm_api_key.get_secret_value() not in public)
    final = http.get(BASE + '/health', timeout=10).json()
    check('library_healthy_after_integration', final['status'] == 'ready')
    details['final_health'] = final


if __name__ == '__main__':
    completed = False
    failure = None
    try:
        main()
        completed = True
    except Exception as exc:
        failure = {'type': type(exc).__name__, 'code': getattr(exc, 'code', 'VERIFICATION_FAILED')}
        raise
    finally:
        report = {'created_at': datetime.now(timezone.utc).isoformat(), 'checks': checks,
                  'completed': completed, 'failure': failure,
                  'passed': sum(row['passed'] for row in checks), 'failed': sum(not row['passed'] for row in checks),
                  'details': details, 'scope': 'Live integration smoke checks; not a formal retrieval quality benchmark'}
        (ROOT / 'reports').mkdir(exist_ok=True)
        (ROOT / 'reports/local_models_integration.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'failed': report['failed']}, indent=2), flush=True)
