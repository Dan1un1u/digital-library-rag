"""Check the FP16 service against the original FP32 encoder on a small text sample."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import requests
import torch
from transformers import AutoModel, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
torch.set_num_threads(4)
texts = ['数字图书馆支持学术文献检索与证据问答。',
         'A digital library supports scholarly literature search and evidence-grounded answers.',
         '植物通过光合作用将太阳能转换成化学能。',
         'Photosynthesis converts sunlight into chemical energy in plants.']
started = time.perf_counter()
source = ROOT / 'models/bge-m3-source'
tokenizer = AutoTokenizer.from_pretrained(str(source), local_files_only=True, trust_remote_code=False)
model = AutoModel.from_pretrained(str(source), local_files_only=True, trust_remote_code=False,
                                  dtype=torch.float32, use_safetensors=False,
                                  attn_implementation='sdpa').eval()
with torch.inference_mode():
    encoded = tokenizer(texts, padding=True, truncation=False, return_tensors='pt')
    reference = torch.nn.functional.normalize(model(**encoded).last_hidden_state[:, 0, :], p=2, dim=1)
client = requests.Session()
client.trust_env = False
response = client.post('http://127.0.0.1:18080/v1/embeddings',
                         json={'model': 'BAAI/bge-m3', 'input': texts}, timeout=120)
response.raise_for_status()
actual = torch.tensor([row['embedding'] for row in response.json()['data']], dtype=torch.float32)
cosines = torch.nn.functional.cosine_similarity(reference, actual, dim=1)
report = {'created_at': datetime.now(timezone.utc).isoformat(), 'samples': len(texts),
          'reference': 'Official original FP32 weights, CPU, CLS pooling, L2 normalization',
          'actual': 'Converted FP16 weights, RTX 5070 Ti, CLS pooling, float32 L2 normalization',
          'cosine_per_sample': cosines.tolist(), 'minimum_cosine': cosines.min().item(),
          'maximum_absolute_difference': (reference - actual).abs().max().item(),
          'mean_absolute_difference': (reference - actual).abs().mean().item(),
          'passed': bool(cosines.min() > .999), 'elapsed_seconds': time.perf_counter() - started,
          'scope': 'Numerical smoke check only, not a retrieval benchmark or formal equivalence proof'}
(ROOT / 'reports/fp32_comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if report['passed'] else 1)
