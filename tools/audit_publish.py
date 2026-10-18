"""Audit staged files; optional local credential references are never printed or copied."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--env-file', type=Path, action='append', default=[])
parser.add_argument('--oauth-dir', type=Path, action='append', default=[])
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
paths = [path for path in paths if path]
secrets = []
for path in args.env_file:
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        key, separator, value = line.partition('=')
        if separator and re.search(r'KEY|TOKEN|SECRET|PASSWORD', key, re.I):
            value = value.strip().strip('\"\'')
            if len(value) >= 12:
                secrets.append(value.encode('utf-8'))
for directory in args.oauth_dir:
    for path in directory.glob('*.json'):
        record = json.loads(path.read_text(encoding='utf-8-sig'))
        for key in ('access_token', 'refresh_token', 'id_token'):
            if isinstance(record.get(key), str) and len(record[key]) >= 20:
                secrets.append(record[key].encode('utf-8'))
patterns = {
    'github_or_provider_token': re.compile(rb'\b(?:github_pat_|gh[pousr]_|sk-(?:proj-|svcacct-)?)[A-Za-z0-9_-]{20,}'),
    'jwt': re.compile(rb'\beyJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_-]{20,}'),
    'private_key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
}
forbidden_dirs = {'.venv', 'auth', 'data', 'models', 'model_cache', 'runtime', 'logs', 'reports',
                  'evidence', 'cache', '.cache', '.git', '__pycache__', '.pytest_cache'}
findings, total, pdfs = [], 0, []
for name in paths:
    path = Path(name)
    if (any(part in forbidden_dirs or part.startswith('.venv') for part in path.parts[:-1])
            or (path.name.startswith('.env') and path.name != '.env.example')
            or path.name == 'config.yaml'):
        findings.append({'path': name, 'rule': 'private_or_runtime_path'})
    content = subprocess.check_output(['git', 'show', ':' + name], cwd=ROOT)
    total += len(content)
    for label, pattern in patterns.items():
        if pattern.search(content):
            findings.append({'path': name, 'rule': label})
    if any(secret in content for secret in secrets):
        findings.append({'path': name, 'rule': 'matches_local_live_credential'})
    if path.suffix.lower() == '.pdf':
        pdfs.append(name)
        if not name.startswith('app/tests/ingestion/samples/'):
            findings.append({'path': name, 'rule': 'non_fixture_pdf'})
    if len(content) > 2 * 1024 * 1024:
        findings.append({'path': name, 'rule': 'large_artifact'})
report = {'created_at': datetime.now(timezone.utc).isoformat(), 'staged_files': len(paths),
          'total_staged_bytes': total, 'synthetic_pdf_fixtures': pdfs,
          'local_credential_references_checked': len(secrets), 'findings': findings,
          'passed': not findings}
destination = ROOT / 'reports/publish_audit.json'
destination.parent.mkdir(exist_ok=True)
destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
raise SystemExit(0 if report['passed'] else 1)
