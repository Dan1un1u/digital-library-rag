"""Download the pinned official Windows release and verify both published hashes."""
import hashlib
import json
from pathlib import Path
import secrets
import zipfile
import requests

ROOT = Path(__file__).resolve().parents[1]
TAG = 'v8.0.33'
NAME = 'CLIProxyAPI_8.0.33_windows_amd64.zip'
EXPECTED = '6a1e04025710f01c528b88c4ae26ea1a332aabc27c7387ae3527107b9096f8a5'
CHECKSUM_EXPECTED = 'a69d87de882f6b8bb84117558dda23c99515ee1f9f38e82095e7e5ae5239bcfc'
base = f'https://github.com/router-for-me/CLIProxyAPI/releases/download/{TAG}/'
client = requests.Session()
for name, expected in [('checksums.txt', CHECKSUM_EXPECTED), (NAME, EXPECTED)]:
    target = ROOT / 'cache' / name
    if not target.exists():
        with client.get(base + name, stream=True, timeout=(20, 120)) as response:
            response.raise_for_status()
            with target.with_suffix(target.suffix + '.part').open('wb') as stream:
                for block in response.iter_content(1024 * 1024):
                    stream.write(block)
        target.with_suffix(target.suffix + '.part').replace(target)
    if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
        raise RuntimeError('Official release hash verification failed: ' + name)
checks = (ROOT / 'cache/checksums.txt').read_text()
if not any(line.split() == [EXPECTED, NAME] for line in checks.splitlines()):
    raise RuntimeError('Archive does not match the release checksum list')
with zipfile.ZipFile(ROOT / 'cache' / NAME) as archive:
    for member in archive.infolist():
        if member.is_dir():
            continue
        name = Path(member.filename).name
        if name in ('cli-proxy-api.exe', 'config.example.yaml', 'LICENSE', 'README.md', 'README_CN.md'):
            destination = ROOT / 'bin' / name
            if not destination.exists():
                destination.write_bytes(archive.read(member))
config_path = ROOT / 'config.yaml'
if not config_path.exists():
    config = {'host': '127.0.0.1', 'port': 8317,
              'auth-dir': str(ROOT / 'auth'), 'api-keys': [secrets.token_urlsafe(32)],
              'proxy-url': 'http://127.0.0.1:7897', 'debug': False,
              'logging-to-file': True, 'logs-max-total-size-mb': 50,
              'usage-statistics-enabled': True, 'request-retry': 0,
              'quota-exceeded': {'switch-project': False, 'switch-preview-model': False},
              'remote-management': {'allow-remote': False, 'secret-key': '', 'disable-control-panel': True}}
    config_path.write_text(json.dumps(config, indent=2), encoding='utf-8')
(ROOT / 'evidence/release.json').write_text(json.dumps({
    'repository': 'https://github.com/router-for-me/CLIProxyAPI', 'tag': TAG,
    'archive': NAME, 'sha256': EXPECTED, 'checksums_sha256': CHECKSUM_EXPECTED,
    'verified': True}, indent=2), encoding='utf-8')
print('Installed verified official release ' + TAG + '; local client key saved privately in config.yaml')
