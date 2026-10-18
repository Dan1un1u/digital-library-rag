"""Start and stop this deployment's WSL service, guarding against PID reuse."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / 'runtime/service-wsl.json'
CONFIG = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))
BASE = f'http://127.0.0.1:{CONFIG["port"]}'


def identity(pid):
    try:
        process = Path('/proc') / str(pid)
        stat = (process / 'stat').read_text().rsplit(')', 1)[1].split()
        command = (process / 'cmdline').read_bytes().replace(b'\x00', b' ').decode()
        if stat[0] == 'Z' or str(ROOT / 'scripts/run_server.py') not in command:
            return None
        return {'start_ticks': stat[19], 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    except (OSError, IndexError, UnicodeError):
        return None


def state():
    return json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else None


def health():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(BASE + '/health', timeout=2) as response:
        return json.load(response)


def occupied():
    with socket.socket() as connection:
        return connection.connect_ex(('127.0.0.1', CONFIG['port'])) == 0


def start():
    if CONFIG['host'] != '127.0.0.1':
        raise RuntimeError('This local deployment only permits a loopback listener')
    previous = state()
    if previous and identity(previous['pid']) == previous['identity']:
        print('Owned service is already running.')
        status()
        return
    if occupied():
        raise RuntimeError('Port is occupied; no process was stopped')
    env = os.environ.copy()
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
               HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', TOKENIZERS_PARALLELISM='false',
               HF_HOME=str(ROOT / 'cache/huggingface'), OMP_NUM_THREADS='4')
    log_path = ROOT / 'logs' / ('service_wsl_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.log')
    with log_path.open('ab') as log:
        process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/run_server.py')], cwd=ROOT,
            env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    # The command line can initially still be the parent between fork and exec.
    process_identity = None
    for _ in range(20):
        process_identity = identity(process.pid)
        if process_identity is not None:
            break
        time.sleep(.05)
    if process_identity is None:
        raise RuntimeError('Could not identify child service; inspect ' + str(log_path))
    record = {'pid': process.pid, 'identity': process_identity, 'log': str(log_path), 'base_url': BASE,
              'python': sys.executable, 'started_at': datetime.now().isoformat()}
    STATE.write_text(json.dumps(record, indent=2), encoding='utf-8')
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if identity(process.pid) != process_identity:
            raise RuntimeError('Service stopped; inspect ' + str(log_path))
        try:
            result = health()
            if result['status'] == 'ready':
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return
        except (OSError, ValueError):
            pass
        time.sleep(.5)
    raise RuntimeError('Service startup exceeded 120 seconds; inspect ' + str(log_path))


def stop():
    record = state()
    if not record:
        print('No service process is recorded.')
        return
    if identity(record['pid']) == record['identity']:
        os.kill(record['pid'], signal.SIGTERM)
        deadline = time.monotonic() + 15
        while identity(record['pid']) == record['identity'] and time.monotonic() < deadline:
            time.sleep(.1)
        if identity(record['pid']) == record['identity']:
            raise RuntimeError('Graceful stop has not completed; inspect the service log')
        print('Stopped this deployment service.')
    else:
        print('No matching owned process is running; no other process was stopped.')
    record['stopped_at'] = datetime.now().isoformat()
    STATE.write_text(json.dumps(record, indent=2), encoding='utf-8')


def status():
    record = state()
    result = {'process': record, 'running': bool(record and identity(record['pid']) == record['identity'])}
    try:
        result['health'] = health()
    except (OSError, ValueError):
        result['health'] = None
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    args = parser.parse_args()
    {'start': start, 'stop': stop, 'status': status}[args.action]()
