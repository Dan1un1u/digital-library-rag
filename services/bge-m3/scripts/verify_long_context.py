"""Exercise the advertised 8192-token boundary on the real FP16 service."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
import requests
from transformers import AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
tokenizer = AutoTokenizer.from_pretrained(str(ROOT / 'models/bge-m3-fp16'),
                                         local_files_only=True, trust_remote_code=False,
                                         fix_mistral_regex=False)
source_tokenizer = AutoTokenizer.from_pretrained(str(ROOT / 'models/bge-m3-source'),
                                                local_files_only=True, trust_remote_code=False)
tokenizer_samples = ['数字图书馆的元数据质量评价。', 'A digital library supports literature search.',
                     '2026-10-18 DOI:10.1000/182', 'hello  world\n\tnew line',
                     '中 English 文 mixed text；标点!?', 'Unicode: café naïve 🏛️ 📚',
                     '<s> <mask> </s>', '']
tokenizer_parity = all(tokenizer(text)['input_ids'] == source_tokenizer(text)['input_ids']
                       for text in tokenizer_samples)
if not tokenizer_parity:
    raise RuntimeError('Converted tokenizer differs from the official source tokenizer')
client = requests.Session()
client.trust_env = False
base = 'http://127.0.0.1:18080'
limit = client.get(base + '/health', timeout=10).json()['max_input_tokens']
fixtures = {}
for repeats in range(limit // 2 - 4, limit // 2 + 4):
    for suffix in ('', ' ', ' a', '。'):
        candidate = ('hello ' * repeats).rstrip() + suffix
        length = len(tokenizer(candidate, truncation=False)['input_ids'])
        if length in (limit, limit + 1):
            fixtures[length] = candidate
if len(fixtures) != 2:
    raise RuntimeError('Could not construct exact tokenizer length boundary fixtures')
text = fixtures[limit]
tokens = len(tokenizer(text, truncation=False)['input_ids'])
started = time.perf_counter()
response = client.post(base + '/v1/embeddings', json={'input': text}, timeout=120)
elapsed = time.perf_counter() - started
response.raise_for_status()
payload = response.json()
vector = payload['data'][0]['embedding']
norm = math.sqrt(sum(value * value for value in vector))
oversized = fixtures[limit + 1]
oversized_tokens = len(tokenizer(oversized, truncation=False)['input_ids'])
rejected = client.post(base + '/v1/embeddings', json={'input': oversized}, timeout=30)
health = client.get(base + '/health', timeout=10).json()
passed = (len(vector) == 1024 and abs(norm - 1) < 1e-5 and
          payload['usage']['total_tokens'] == limit and oversized_tokens == limit + 1 and
          rejected.status_code == 422 and health['status'] == 'ready')
report = {'created_at': datetime.now(timezone.utc).isoformat(), 'passed': passed,
          'official_tokenizer_parity': tokenizer_parity, 'tokenizer_samples': len(tokenizer_samples),
          'accepted_tokens': tokens, 'rejected_tokens': oversized_tokens,
          'rejected_status': rejected.status_code, 'dimension': len(vector),
          'l2_norm': norm, 'long_input_seconds': elapsed, 'health': health,
          'scope': 'Capacity and boundary smoke check with repetitive text, not retrieval quality evaluation'}
(ROOT / 'reports/long_context.json').write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
raise SystemExit(0 if passed else 1)
