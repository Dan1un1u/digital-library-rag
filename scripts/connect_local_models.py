"""Configure this isolated library using the private local proxy client key."""
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
proxy = json.loads(Path('D:/cliproxyapi-local/config.yaml').read_text(encoding='utf-8'))
revision = json.loads(Path('D:/bge-m3-local/models/bge-m3-fp16/provenance.json').read_text(encoding='utf-8'))['source_revision']
updates = {
    'APP_MODE': 'real', 'EMBEDDING_PROVIDER': 'local_bge',
    'EMBEDDING_BASE_URL': 'http://127.0.0.1:18080/v1', 'EMBEDDING_MODEL': 'BAAI/bge-m3',
    'EMBEDDING_REVISION': revision, 'EMBEDDING_DIMENSION': '1024',
    'LLM_PROVIDER': 'cliproxyapi', 'LLM_BASE_URL': 'http://127.0.0.1:8317/v1',
    'LLM_MODEL': 'gpt-6-luna', 'LLM_API_KEY': proxy['api-keys'][0],
    'LLM_REASONING_EFFORT': 'none', 'LLM_ENABLE_THINKING': '',
    'LLM_MAX_OUTPUT_TOKENS': '2600', 'LLM_CONTEXT_WINDOW_TOKENS': '262144',
    'LLM_TIMEOUT_SECONDS': '120', 'LLM_CLIENT_FACTORY': 'dlrag.api.qa_factory:create_client',
    'QA_RERANK_PROVIDER': 'llm', 'QA_RERANK_MODEL': 'gpt-6-luna',
    'QA_RERANK_TIMEOUT_SECONDS': '90', 'QA_SEMANTIC_RERANK_ENABLED': 'true',
    'METADATA_API_PROVIDER': 'cliproxyapi', 'METADATA_API_MODEL': 'gpt-6-luna',
    'METADATA_API_ENABLED': 'true', 'METADATA_API_TIMEOUT_SECONDS': '90',
}
# Optional bool settings must be omitted, not set to an empty string.
env_path = ROOT / 'app/.env'
lines, seen = [], set()
for line in env_path.read_text(encoding='utf-8').splitlines():
    key = line.partition('=')[0].strip()
    if key in updates:
        if updates[key]:
            lines.append(key + '=' + updates[key])
        seen.add(key)
    else:
        lines.append(line)
lines.extend(key + '=' + value for key, value in updates.items() if key not in seen and value)
env_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
backup = ROOT / 'evidence/before_local_models_20261018'
database = ROOT / 'runtime/real_arxiv/library.sqlite'
if not (backup / 'library.sqlite').exists():
    with sqlite3.connect(database) as source, sqlite3.connect(backup / 'library.sqlite') as destination:
        source.backup(destination)
pointer = ROOT / 'runtime/real_arxiv/indexes/current.json'
if pointer.exists() and not (backup / 'index-current.json').exists():
    (backup / 'index-current.json').write_bytes(pointer.read_bytes())
print('Configured local BGE and gpt-6-luna for generation, reranking and page recognition; credentials were not printed.')
