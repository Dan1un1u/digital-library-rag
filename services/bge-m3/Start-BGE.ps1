$ErrorActionPreference = 'Stop'
& wsl.exe -d Ubuntu-22.04 --cd /mnt/d/bge-m3-local -- .venv-wsl/bin/python scripts/control_wsl.py start
exit $LASTEXITCODE
