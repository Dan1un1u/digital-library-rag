$ErrorActionPreference = 'Stop'
& wsl.exe -d Ubuntu-22.04 --cd /mnt/d/bge-m3-local -- env PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv-wsl/bin/python scripts/verify_long_context.py
exit $LASTEXITCODE
