param([ValidateSet('real','mock','both')][string]$Mode = 'both')
$ErrorActionPreference = 'Stop'
$libraryPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $libraryPython)) {
    throw 'Project Python environment is missing. Follow README.md to create .venv first.'
}
& $libraryPython (Join-Path $PSScriptRoot 'scripts/control.py') start --mode $Mode
exit $LASTEXITCODE
