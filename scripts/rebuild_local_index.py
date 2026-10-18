"""Build a new BGE snapshot atomically, retaining every previous index snapshot."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from dlrag.api.services import assemble
from dlrag.shared.config import Settings

ROOT = Path(__file__).resolve().parents[1]
settings = Settings(_env_file=ROOT / 'app/.env')
if settings.app_mode != 'real' or settings.embedding_provider != 'local_bge':
    raise RuntimeError('This script only rebuilds the configured real local BGE index')
services = assemble(settings)
if services.library is None or services.retriever is None:
    raise RuntimeError('Library or local embedding adapter unavailable')
started = time.perf_counter()
manifest = services.rebuild()
report = {'created_at': datetime.now(timezone.utc).isoformat(),
          'elapsed_seconds': time.perf_counter() - started, 'manifest': manifest,
          'embedding_statistics': services.retriever.backend.stats,
          'previous_snapshots_retained': True, 'health': services.health()}
(ROOT / 'reports/local_bge_index.json').write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'elapsed_seconds': report['elapsed_seconds'],
                  'document_count': manifest['document_count'], 'chunk_count': manifest['chunk_count'],
                  'index_version': manifest['index_version'], 'embedding_backend': manifest['embedding_backend'],
                  'statistics': report['embedding_statistics']}, ensure_ascii=False, indent=2))
