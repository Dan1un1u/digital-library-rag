"""Exercise real GPU inference, API validation, multilingual ranking and latency."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import time
import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:18080'
checks = []
client = requests.Session()
client.trust_env = False


def check(name, passed, **details):
    checks.append({'name': name, 'passed': bool(passed), **details})
    print(('PASS ' if passed else 'FAIL ') + name, flush=True)


def embedding(texts):
    response = client.post(BASE + '/v1/embeddings', json={'input': texts, 'model': 'BAAI/bge-m3'}, timeout=120)
    response.raise_for_status()
    payload = response.json()
    return [row['embedding'] for row in payload['data']], payload['usage']


def dot(left, right):
    return sum(a * b for a, b in zip(left, right))


def main():
    health = client.get(BASE + '/health', timeout=10).json()
    check('actual_cuda_fp16', health['status'] == 'ready' and health['dtype'] == 'float16'
          and health['device'].startswith('cuda') and '5070 Ti' in health['gpu'], health=health)
    check('expected_parameter_count', 560_000_000 <= health['parameter_count'] <= 570_000_000,
          parameter_count=health['parameter_count'])
    catalog = client.get(BASE + '/v1/models', timeout=10).json()
    check('model_catalog', any(row['id'] == 'BAAI/bge-m3' for row in catalog['data']))
    documents = ['Photosynthesis converts sunlight into chemical energy in plants.',
                 'Digital libraries organize scholarly publications and support document search.',
                 'Transformers use self-attention to model relationships between tokens.']
    queries = ['植物如何利用阳光制造养分？', '数字图书馆如何组织和检索学术文献？',
               'What mechanism lets a Transformer attend to other tokens?']
    vectors, usage = embedding(documents + queries)
    check('dimension_1024', len(vectors) == 6 and all(len(vector) == 1024 for vector in vectors))
    norms = [math.sqrt(dot(vector, vector)) for vector in vectors]
    check('finite_l2_normalized', all(math.isfinite(value) for vector in vectors for value in vector)
          and all(abs(norm - 1) < 1e-5 for norm in norms), norms=norms)
    check('real_token_usage', usage['prompt_tokens'] == usage['total_tokens'] and usage['total_tokens'] > 6)
    ranking = []
    for index, query in enumerate(queries):
        scores = [dot(vectors[3 + index], vector) for vector in vectors[:3]]
        predicted = max(range(3), key=lambda candidate: scores[candidate])
        ranking.append({'query': query, 'scores': scores, 'expected_document': index, 'top_document': predicted})
        check(f'semantic_ranking_{index + 1}', predicted == index, scores=scores)
    single, _ = embedding(queries[0])
    check('single_batch_consistency', dot(single[0], vectors[3]) > .999,
          cosine=dot(single[0], vectors[3]))
    repeated, _ = embedding([queries[0], queries[0]])
    check('repeated_input_consistency', dot(*repeated) > .9999, cosine=dot(*repeated))
    invalid = [
        ('empty_list', {'input': []}), ('empty_text', {'input': ''}),
        ('whitespace', {'input': '   '}), ('non_text', {'input': [12]}),
        ('bad_model', {'input': 'hello', 'model': 'missing'}),
        ('bad_dimensions', {'input': 'hello', 'dimensions': 768}),
        ('bad_encoding', {'input': 'hello', 'encoding_format': 'base64'}),
        ('too_many_inputs', {'input': ['hello'] * 65}),
        ('too_many_tokens', {'input': 'hello ' * 9000}),
    ]
    for name, body in invalid:
        response = client.post(BASE + '/v1/embeddings', json=body, timeout=30)
        check('reject_' + name, response.status_code == 422, status_code=response.status_code)
    with ThreadPoolExecutor(max_workers=2) as pool:
        concurrent = list(pool.map(embedding, ['数字图书馆', '学术文献检索']))
    check('two_concurrent_requests', all(len(result[0][0]) == 1024 for result in concurrent))
    short_latencies = []
    for _ in range(5):
        started = time.perf_counter()
        embedding('如何在数字图书馆中检索研究论文？')
        short_latencies.append((time.perf_counter() - started) * 1000)
    batch_texts = [('数字图书馆提供文献组织、学术检索、元数据管理以及基于原文的证据问答。' * 35)[:1200]] * 16
    started = time.perf_counter()
    batch_vectors, batch_usage = embedding(batch_texts)
    batch_seconds = time.perf_counter() - started
    check('sixteen_document_batch', len(batch_vectors) == 16 and all(len(vector) == 1024 for vector in batch_vectors))
    final_health = client.get(BASE + '/health', timeout=10).json()
    check('service_healthy_after_validation_and_load', final_health['status'] == 'ready')
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'checks': checks,
              'passed': sum(row['passed'] for row in checks), 'failed': sum(not row['passed'] for row in checks),
              'semantic_examples': ranking,
              'benchmark': {'warm_single_query_ms': short_latencies,
                            'warm_single_query_median_ms': statistics.median(short_latencies),
                            'batch_texts': 16, 'batch_characters_each': len(batch_texts[0]),
                            'batch_seconds': batch_seconds, 'batch_usage': batch_usage,
                            'scope': 'Small local development smoke benchmark, not a retrieval quality benchmark'},
              'final_health': final_health}
    (ROOT / 'reports/verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'failed': report['failed'],
                      'benchmark': report['benchmark'], 'health': final_health}, ensure_ascii=False, indent=2))
    return 0 if report['failed'] == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
