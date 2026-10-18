$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    & (Join-Path $PSScriptRoot 'bin/cli-proxy-api.exe') -config (Join-Path $PSScriptRoot 'config.yaml') -codex-login
} finally {
    Pop-Location
}
