"""Finish conversion and verification after the resumable download completes (Windows)."""
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
deadline = time.monotonic() + 1800
print('Waiting for the verified official model download...', flush=True)
while time.monotonic() < deadline:
    manifest = ROOT / 'evidence/source_manifest.json'
    weights = ROOT / 'models/bge-m3-source/pytorch_model.bin'
    if manifest.exists() and weights.exists():
        try:
            if len(json.loads(manifest.read_text(encoding='utf-8'))['files']) == 11:
                break
        except (ValueError, KeyError):
            pass
    time.sleep(5)
else:
    raise RuntimeError('Official source download has not completed after 30 minutes; preserve files and inspect download log')

commands = [
    ['scripts/prepare_fp16.py'],
    ['scripts/control_wsl.py', 'start'],
    ['scripts/verify_service.py'],
    ['scripts/compare_fp32_reference.py'],
]
for command in commands:
    print('Running ' + ' '.join(command), flush=True)
    subprocess.run(['wsl.exe', '-d', 'Ubuntu-22.04', '--cd', '/mnt/d/bge-m3-local', '--',
                    'env', 'PYTHONDONTWRITEBYTECODE=1', 'PYTHONUTF8=1', 'HF_HUB_OFFLINE=1',
                    'TRANSFORMERS_OFFLINE=1', 'TOKENIZERS_PARALLELISM=false', 'OMP_NUM_THREADS=4',
                    '.venv-wsl/bin/python', *command], check=True)
print('Conversion, service startup and verification completed.', flush=True)
