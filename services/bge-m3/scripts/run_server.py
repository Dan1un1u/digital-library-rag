import json
from pathlib import Path
import sys
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
config = json.loads((ROOT / 'config.json').read_text(encoding='utf-8'))

if __name__ == '__main__':
    uvicorn.run('server:app', host=config['host'], port=config['port'], workers=1,
                limit_concurrency=16, timeout_keep_alive=10)
