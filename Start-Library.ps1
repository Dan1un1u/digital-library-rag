param([ValidateSet('real','mock','both')][string]$Mode = 'both')
$ErrorActionPreference = 'Stop'
if ($Mode -ne 'mock') {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'D:/cliproxyapi-local/Start-CLIProxyAPI.ps1'
    if ($LASTEXITCODE -ne 0) { throw 'CLIProxyAPI startup failed.' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'D:/bge-m3-local/Start-BGE.ps1'
    if ($LASTEXITCODE -ne 0) { throw 'Local BGE startup failed.' }
}
& (Join-Path $PSScriptRoot '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'scripts/control.py') start --mode $Mode
exit $LASTEXITCODE
