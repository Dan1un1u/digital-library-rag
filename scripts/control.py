"""Start/status/stop only processes belonging to this isolated deployment."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'
STATE = ROOT / 'runtime' / 'processes.json'
PORTS = {'real': (18000, 18501), 'mock': (18001, 18502)}
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = [wintypes.HANDLE]
kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]


def identity(pid):
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
            return None
        fields = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(x) for x in fields]):
            return None
        return (fields[0].dwHighDateTime << 32) | fields[0].dwLowDateTime
    finally:
        kernel.CloseHandle(handle)


def records():
    return json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}


def environment(mode):
    result = os.environ.copy()
    config = {**dotenv_values(APP / '.env'), **os.environ} if mode == 'real' else {}
    def configured_path(name, fallback):
        path = Path(config.get(name) or fallback)
        return str((path if path.is_absolute() else APP / path).resolve())
    data = Path(configured_path('DATA_DIR', ROOT / 'runtime' / mode))
    result.update(APP_MODE=mode, DATA_DIR=str(data),
                  DB_PATH=configured_path('DB_PATH', data / 'library.sqlite'),
                  FILES_DIR=configured_path('FILES_DIR', data / 'raw'),
                  INDEX_DIR=configured_path('INDEX_DIR', data / 'indexes'),
                  API_BASE_URL=f'http://127.0.0.1:{PORTS[mode][0]}',
                  PYTHONUTF8='1', PYTHONIOENCODING='utf-8',
                  TIKTOKEN_CACHE_DIR=str(APP / 'data' / 'tokenizer-cache'),
                  STREAMLIT_BROWSER_GATHER_USAGE_STATS='false')
    if mode == 'mock':
        result['METADATA_API_ENABLED'] = 'false'
        result['SILICONFLOW_API_KEY'] = ''
        result['LLM_API_KEY'] = ''
        result['SD_EMBEDDING_KEY'] = ''
    return result


def listening(port):
    with socket.socket() as connection:
        return connection.connect_ex(('127.0.0.1', port)) == 0


def save(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding='utf-8')


def start(modes):
    (ROOT / 'runtime').mkdir(parents=True, exist_ok=True)
    (ROOT / 'logs').mkdir(parents=True, exist_ok=True)
    state = records()
    for mode in modes:
        env = environment(mode)
        api_port, ui_port = PORTS[mode]
        commands = {
            'api': [sys.executable, str(ROOT / 'scripts' / 'server_entry.py'), '--port', str(api_port)],
            'ui': [sys.executable, '-m', 'streamlit', 'run', str(APP / 'src/dlrag/ui/app.py'),
                   '--server.address', '127.0.0.1', '--server.port', str(ui_port),
                   '--server.headless', 'true', '--browser.gatherUsageStats', 'false'],
        }
        for kind, command in commands.items():
            key = f'{mode}_{kind}'
            previous = state.get(key, {})
            if previous and identity(previous['pid']) == previous['created']:
                print(f'{key}: already running ({previous["pid"]})')
                continue
            port = api_port if kind == 'api' else ui_port
            if listening(port):
                raise RuntimeError(f'Port {port} is occupied by another process; nothing was stopped.')
            stamp = time.strftime('%Y%m%d_%H%M%S')
            log_path = ROOT / 'logs' / f'{key}_{stamp}.log'
            with log_path.open('ab') as log:
                process = subprocess.Popen(command, cwd=APP, env=env, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT,
                                           creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
            created = identity(process.pid)
            if created is None:
                raise RuntimeError(f'{key} exited early; see {log_path}')
            state[key] = {'pid': process.pid, 'created': created, 'port': port,
                          'log': str(log_path), 'command': command}
            save(state)
    deadline = time.monotonic() + 40
    pending = {f'{mode}_{kind}' for mode in modes for kind in ('api', 'ui')}
    while pending and time.monotonic() < deadline:
        for key in list(pending):
            row = state[key]
            if identity(row['pid']) != row['created']:
                raise RuntimeError(f'{key} stopped; see {row["log"]}')
            path = '/health' if key.endswith('_api') else '/_stcore/health'
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{row["port"]}{path}', timeout=1) as response:
                    if response.status == 200:
                        pending.remove(key)
            except (OSError, TimeoutError):
                pass
        if pending:
            time.sleep(.5)
    if pending:
        raise RuntimeError('Not ready within 40 seconds: ' + ', '.join(sorted(pending)))
    status(modes)


def stop(modes):
    state = records()
    for key, row in list(state.items()):
        if key.split('_')[0] not in modes:
            continue
        if identity(row['pid']) == row['created']:
            # Recheck process creation time to avoid terminating a reused PID.
            handle = kernel.OpenProcess(0x1001, False, row['pid'])
            if handle:
                try:
                    if identity(row['pid']) == row['created']:
                        kernel.TerminateProcess(handle, 0)
                finally:
                    kernel.CloseHandle(handle)
            print(f'{key}: stopped owned process {row["pid"]}')
        else:
            print(f'{key}: no matching live process')
        del state[key]
    save(state)


def status(modes):
    state = records()
    result = {key: {**row, 'running': identity(row['pid']) == row['created']}
              for key, row in state.items() if key.split('_')[0] in modes}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    parser.add_argument('--mode', choices=['real', 'mock', 'both'], default='both')
    args = parser.parse_args()
    selected = list(PORTS) if args.mode == 'both' else [args.mode]
    {'start': start, 'stop': stop, 'status': status}[args.action](selected)
