"""Verify Windows localhost access and the public start/stop scripts."""
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:18080'
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
checks = []


def fetch(path, body=None):
    data = None if body is None else json.dumps(body).encode('utf-8')
    request = urllib.request.Request(BASE + path, data=data,
                                     headers={'Content-Type': 'application/json'})
    with HTTP.open(request, timeout=120) as response:
        return json.load(response)


def check(name, passed, **details):
    checks.append({'name': name, 'passed': bool(passed), **details})
    print(('PASS ' if passed else 'FAIL ') + name, flush=True)
    if not passed:
        raise RuntimeError(name)


def control(script):
    started = time.perf_counter()
    result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                             '-File', str(ROOT / script)], capture_output=True,
                            text=True, encoding='utf-8', errors='replace', timeout=180)
    check(script, result.returncode == 0, seconds=time.perf_counter() - started,
          stdout=result.stdout, stderr=result.stderr)


def port_open():
    try:
        with socket.create_connection(('127.0.0.1', 18080), timeout=1):
            return True
    except OSError:
        return False


def main():
    initial = fetch('/health')
    initial_pid = json.loads((ROOT / 'runtime/service-wsl.json').read_text())['pid']
    check('windows_health_access', initial['status'] == 'ready' and initial['dtype'] == 'float16',
          health=initial)
    schema = fetch('/openapi.json')
    check('api_documentation', '/v1/embeddings' in schema['paths'])
    answer = fetch('/v1/embeddings', {'input': ['数字图书馆元数据质量评价',
                                               'Metadata quality evaluation in digital libraries'],
                                     'model': 'BAAI/bge-m3'})
    check('windows_real_embeddings', len(answer['data']) == 2 and
          all(len(row['embedding']) == 1024 for row in answer['data']), usage=answer['usage'])
    control('Status-BGE.ps1')
    control('Stop-BGE.ps1')
    try:
        deadline = time.monotonic() + 10
        while port_open() and time.monotonic() < deadline:
            time.sleep(.25)
        check('windows_port_closed_after_stop', not port_open())
    finally:
        control('Start-BGE.ps1')
    deadline = time.monotonic() + 10
    while True:
        try:
            final = fetch('/health')
            break
        except (OSError, ValueError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(.25)
    final_pid = json.loads((ROOT / 'runtime/service-wsl.json').read_text())['pid']
    check('new_process_after_restart', initial_pid != final_pid,
          initial_pid=initial_pid, final_pid=final_pid)
    answer = fetch('/v1/embeddings', {'input': '服务重启后仍可检索数字图书馆文献。'})
    check('windows_inference_after_restart', final['status'] == 'ready' and
          len(answer['data'][0]['embedding']) == 1024, health=final)
    return 0


if __name__ == '__main__':
    try:
        code = main()
    finally:
        report = {'created_at': datetime.now(timezone.utc).isoformat(),
                  'checks': checks, 'passed': sum(row['passed'] for row in checks),
                  'failed': sum(not row['passed'] for row in checks)}
        (ROOT / 'reports/windows_verification.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    raise SystemExit(code)
