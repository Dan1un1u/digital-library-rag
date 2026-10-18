"""Prepare separate writable data directories and local configuration."""
import json
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
app = root / 'app'
for name in ('mock', 'real_arxiv'):
    destination = root / 'runtime' / name
    if not destination.exists():
        shutil.copytree(app / 'data' / name, destination)
values = (app / '.env.example').read_text(encoding='utf-8')
replacements = {
    'APP_MODE': 'real',
    'DATA_DIR': (root / 'runtime' / 'real_arxiv').as_posix(),
    'API_BASE_URL': 'http://127.0.0.1:18000',
}
lines = []
for line in values.splitlines():
    key = line.partition('=')[0]
    lines.append(f'{key}={replacements[key]}' if key in replacements else line)
(app / '.env').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(json.dumps({'runtime': str(root / 'runtime'), 'default_mode': 'real',
                  'api': 'http://127.0.0.1:18000'}, ensure_ascii=False))
