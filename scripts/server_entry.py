"""Dedicated local API entry point; no changes to application source."""
import argparse
import uvicorn
from dlrag.api.main import create_app

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(create_app(), host='127.0.0.1', port=args.port, workers=1)
