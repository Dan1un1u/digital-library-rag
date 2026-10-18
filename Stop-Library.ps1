param([ValidateSet('real','mock','both')][string]$Mode = 'both')
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'scripts/control.py') stop --mode $Mode
exit $LASTEXITCODE
