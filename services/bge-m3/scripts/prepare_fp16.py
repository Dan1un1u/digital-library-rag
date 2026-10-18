"""Convert the pinned official dense encoder to a local FP16 safetensors model."""
import hashlib
import json
from pathlib import Path
import time
import torch
from transformers import AutoModel, AutoTokenizer

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'models/bge-m3-source'
TARGET = ROOT / 'models/bge-m3-fp16'


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    manifest = json.loads((ROOT / 'evidence/source_manifest.json').read_text(encoding='utf-8'))
    if len(manifest['files']) != 11:
        raise RuntimeError('Source download has not completed')
    weights = next(item for item in manifest['files'] if item['path'] == 'pytorch_model.bin')
    if sha256(SOURCE / weights['path']) != weights['sha256']:
        raise RuntimeError('Source weight hash has changed')
    if TARGET.exists():
        raise RuntimeError('FP16 output already exists; preserve it and verify before replacing')
    pooling = json.loads((SOURCE / '1_Pooling/config.json').read_text(encoding='utf-8'))
    if not pooling.get('pooling_mode_cls_token') or pooling.get('pooling_mode_mean_tokens'):
        raise RuntimeError('Unexpected upstream pooling recipe')
    started = time.perf_counter()
    print('Loading verified official weights with weights-only deserialization...', flush=True)
    model = AutoModel.from_pretrained(str(SOURCE), local_files_only=True, trust_remote_code=False,
                                      dtype=torch.float16, use_safetensors=False,
                                      attn_implementation='sdpa').eval()
    tokenizer = AutoTokenizer.from_pretrained(str(SOURCE), local_files_only=True,
                                              trust_remote_code=False, use_fast=True)
    if any(parameter.dtype != torch.float16 for parameter in model.parameters()):
        raise RuntimeError('Model contains non-FP16 parameters')
    TARGET.mkdir()
    model.save_pretrained(str(TARGET), safe_serialization=True, max_shard_size='2GB')
    tokenizer.save_pretrained(str(TARGET))
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    output = {'source_repository': manifest['repository'], 'source_revision': manifest['revision'],
              'parameter_count': parameter_count, 'weight_dtype': 'float16',
              'weight_storage_bytes': sum(parameter.numel() * parameter.element_size() for parameter in model.parameters()),
              'conversion_seconds': round(time.perf_counter() - started, 3),
              'pooling': 'CLS token, L2 normalization in float32',
              'dense_dimension': model.config.hidden_size,
              'scope': 'Dense embeddings only; no sparse/ColBERT heads or reranker',
              'files': [{'name': path.name, 'size': path.stat().st_size, 'sha256': sha256(path)}
                        for path in sorted(TARGET.iterdir()) if path.is_file()]}
    (TARGET / 'provenance.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    (ROOT / 'reports/fp16_conversion.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
