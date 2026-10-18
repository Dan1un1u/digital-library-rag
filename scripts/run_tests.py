"""Run the supplied test suite in this deployment and save current evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
env = os.environ.copy()
env.update(APP_MODE='mock', PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
           TIKTOKEN_CACHE_DIR=str(ROOT / 'app/data/tokenizer-cache'))
env['SILICONFLOW_API_KEY'] = ''
env['LLM_API_KEY'] = ''
env['SD_EMBEDDING_KEY'] = ''
env.update(EMBEDDING_PROVIDER='siliconflow', LLM_PROVIDER='siliconflow',
           QA_RERANK_PROVIDER='siliconflow', METADATA_API_PROVIDER='siliconflow')
stamp = time.strftime('%Y%m%d_%H%M%S')
xml_path = ROOT / 'reports' / f'pytest_{stamp}.xml'
log_path = ROOT / 'reports' / f'pytest_{stamp}.txt'
command = [sys.executable, '-m', 'pytest', '-q', f'--junitxml={xml_path}']
started = time.monotonic()
result = subprocess.run(command, cwd=ROOT / 'app', env=env, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, encoding='utf-8', errors='replace')
log_path.write_text(result.stdout, encoding='utf-8')
print(result.stdout)
summary = {'exit_code': result.returncode, 'duration_seconds': round(time.monotonic() - started, 2),
           'log': str(log_path), 'junit': str(xml_path)}
if xml_path.exists():
    suite = ET.parse(xml_path).getroot().find('testsuite')
    summary.update({key: int(suite.attrib.get(key, 0)) for key in ('tests', 'failures', 'errors', 'skipped')})
(ROOT / 'reports/pytest_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False))
raise SystemExit(result.returncode)
