"""Download official, revision-pinned BGE-M3 files; verify LFS SHA256."""
import hashlib
import json
from pathlib import Path
import time
from datetime import datetime, timezone
import requests

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'models' / 'bge-m3-source'
TARGET.mkdir(parents=True, exist_ok=True)
REPO = 'BAAI/bge-m3'
FILES = ['README.md', 'config.json', 'tokenizer_config.json', 'special_tokens_map.json',
         'sentencepiece.bpe.model', 'tokenizer.json', 'modules.json',
         'config_sentence_transformers.json', 'sentence_bert_config.json',
         '1_Pooling/config.json', 'pytorch_model.bin']


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    session = requests.Session()
    metadata_path = ROOT / 'evidence' / 'huggingface_model_info.json'
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    else:
        response = session.get(f'https://huggingface.co/api/models/{REPO}',
                               params={'blobs': 'true'}, timeout=60)
        response.raise_for_status()
        metadata = response.json()
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    revision = metadata['sha']
    available = {entry['rfilename']: entry for entry in metadata['siblings']}
    print(f'Official source: {REPO}, revision: {revision}', flush=True)
    manifest = {'repository': REPO, 'revision': revision,
                'downloaded_at': datetime.now(timezone.utc).isoformat(), 'files': []}
    for name in FILES:
        entry = available[name]
        size = entry.get('size')
        expected_hash = entry.get('lfs', {}).get('sha256')
        destination = TARGET / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + '.part')
        if destination.exists():
            digest = sha256(destination)
            if size is not None and destination.stat().st_size != size:
                raise RuntimeError(f'Existing file size mismatch: {name}')
            if expected_hash and digest != expected_hash:
                raise RuntimeError(f'Existing file hash mismatch: {name}')
            print(f'Using verified existing file: {name}', flush=True)
        else:
            for attempt in range(4):
                offset = partial.stat().st_size if partial.exists() else 0
                headers = {'Range': f'bytes={offset}-'} if offset else {}
                try:
                    url = f'https://huggingface.co/{REPO}/resolve/{revision}/{name}'
                    with session.get(url, headers=headers, stream=True, timeout=(30, 90)) as response:
                        response.raise_for_status()
                        append = bool(offset and response.status_code == 206)
                        completed = offset if append else 0
                        last_report = completed
                        with partial.open('ab' if append else 'wb') as stream:
                            for block in response.iter_content(4 * 1024 * 1024):
                                if block:
                                    stream.write(block)
                                    completed += len(block)
                                    if completed - last_report >= 128 * 1024 * 1024:
                                        print(f'{name}: {completed / 1024**2:.0f} MiB downloaded', flush=True)
                                        last_report = completed
                    if size is not None and partial.stat().st_size != size:
                        raise RuntimeError(f'Download size mismatch: {name}')
                    digest = sha256(partial)
                    if expected_hash and digest != expected_hash:
                        raise RuntimeError(f'Download SHA256 mismatch: {name}')
                    partial.rename(destination)
                    print(f'Verified: {name} ({destination.stat().st_size} bytes)', flush=True)
                    break
                except requests.RequestException as exc:
                    print(f'Retrying {name}: {type(exc).__name__}, attempt {attempt + 1}', flush=True)
                    if attempt == 3:
                        raise
                    time.sleep(2 * (attempt + 1))
            digest = sha256(destination)
        manifest['files'].append({'path': name, 'size': destination.stat().st_size,
                                  'sha256': digest, 'upstream_sha256': expected_hash})
        (ROOT / 'evidence/source_manifest.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Official model download complete and verified.', flush=True)


if __name__ == '__main__':
    main()
