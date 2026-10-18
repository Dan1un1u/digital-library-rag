"""Export source and deployment recipes without local data or credential files."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--library', type=Path, required=True)
parser.add_argument('--bge', type=Path, required=True)
parser.add_argument('--proxy', type=Path, required=True)
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
if (ROOT / '.git').exists():
    raise RuntimeError('Export into a fresh directory before initializing Git')
EXCLUDED_DIRS = {'.git', '.venv', '__pycache__', '.pytest_cache', 'data', 'runtime', 'logs',
    'reports', 'evidence', 'models', 'model_cache', 'cache', '.cache', 'build', 'dist', 'auth', 'bin'}
EXCLUDED_SUFFIXES = {'.pyc', '.pyo', '.exe', '.dll', '.so', '.bin', '.safetensors', '.npy', '.npz',
    '.sqlite', '.db', '.zip', '.gz', '.whl', '.key', '.pem', '.p12', '.pfx', '.log', '.png', '.jpg',
    '.jpeg', '.webp', '.gif', '.mp4', '.mp3'}
files = []


def copy_file(source, target, area):
    if source.is_symlink():
        return
    name = source.name
    if name.startswith('.env') and name != '.env.example':
        return
    if name == 'config.yaml' or source.suffix.lower() in EXCLUDED_SUFFIXES or '.sqlite' in name:
        return
    if source.suffix.lower() == '.pdf' and '/tests/ingestion/samples/' not in source.as_posix():
        return
    if name in {'test_results.xml', 'runs.jsonl', 'environment.json', 'source_inventory.json', 'startup_smoke.json'}:
        return
    if source.stat().st_size > 2 * 1024 * 1024:
        raise RuntimeError('Unexpectedly large source file: ' + str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise RuntimeError('Export would overwrite a file: ' + str(target))
    shutil.copy2(source, target)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise RuntimeError('Export hash verification failed')
    files.append({'path': target.relative_to(ROOT).as_posix(), 'area': area, 'sha256': digest,
                  'bytes': target.stat().st_size})


def copy_tree(source, destination, area):
    for current, directories, names in os.walk(source, followlinks=False):
        directories[:] = [name for name in directories if name not in EXCLUDED_DIRS
            and not name.startswith('.venv') and not name.endswith('.egg-info')
            and not re.fullmatch(r'v\d+(?:\.\d+)*', name)
            and not (Path(current) / name).is_symlink()]
        for name in names:
            path = Path(current) / name
            copy_file(path, destination / path.relative_to(source), area)


copy_tree(args.library / 'app', ROOT / 'app', 'library')
copy_tree(args.library / 'scripts', ROOT / 'scripts', 'library')
for name in ('Start-Library.ps1', 'Stop-Library.ps1', 'Status-Library.ps1', 'Run-Tests.ps1', '本地模型使用说明.txt'):
    copy_file(args.library / name, ROOT / name, 'library')
for source, name in ((args.bge, 'bge-m3'), (args.proxy, 'cliproxyapi')):
    copy_tree(source, ROOT / 'services' / name, name)
evidence = ROOT / 'reports'
evidence.mkdir(exist_ok=True)
(evidence / 'export_manifest.json').write_text(json.dumps({'files': files,
    'count': len(files), 'bytes': sum(item['bytes'] for item in files)}, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'exported_files': len(files), 'total_bytes': sum(item['bytes'] for item in files),
                  'hashes_verified': True, 'by_area': {area: sum(item['area'] == area for item in files)
                   for area in ('library', 'bge-m3', 'cliproxyapi')}}))
