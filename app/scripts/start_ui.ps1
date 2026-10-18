$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = 'false'
$taskPython = if (Test-Path -LiteralPath '.venv/Scripts/python.exe') { '.venv/Scripts/python.exe' } else { 'python' }
& $taskPython -m streamlit run src/dlrag/ui/app.py --server.address 127.0.0.1 --server.port 8501
exit $LASTEXITCODE
