param([ValidateSet('start','stop','status')][string]$Action = 'status')
$ErrorActionPreference = 'Stop'
$rootDir = Split-Path -Parent $PSScriptRoot
$exePath = Join-Path $rootDir 'bin/cli-proxy-api.exe'
$configPath = Join-Path $rootDir 'config.yaml'
$statePath = Join-Path $rootDir 'runtime/process.json'
$settings = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$saved = if (Test-Path -LiteralPath $statePath) { Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json } else { $null }
$owned = $null
if ($saved) {
    $candidate = Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
    if ($candidate -and $candidate.Path -eq $exePath -and $candidate.StartTime.ToUniversalTime().ToFileTimeUtc().ToString() -eq $saved.created) {
        $owned = $candidate
    }
}
if ($Action -eq 'stop') {
    if ($owned) { Stop-Process -Id $owned.Id; $owned.WaitForExit(10000) | Out-Null }
    Write-Output 'This deployment service is stopped.'
    exit 0
}
if ($Action -eq 'start' -and -not $owned) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $settings.port -ErrorAction SilentlyContinue
    if ($listener) { throw 'The proxy port is occupied by another process. No process was stopped.' }
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $owned = Start-Process -FilePath $exePath -ArgumentList @('-config', $configPath) -WorkingDirectory $rootDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $rootDir "logs/server_$stamp.log") -RedirectStandardError (Join-Path $rootDir "logs/server_$stamp.err.log") -PassThru
    @{ pid = $owned.Id; created = $owned.StartTime.ToUniversalTime().ToFileTimeUtc().ToString(); executable = $exePath } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
}
$headers = @{ Authorization = 'Bearer ' + $settings.'api-keys'[0] }
$modelIds = @()
$ready = $false
$deadline = (Get-Date).AddSeconds($(if ($Action -eq 'start') { 40 } else { 2 }))
do {
    try {
        $result = Invoke-RestMethod -Uri "http://127.0.0.1:$($settings.port)/v1/models" -Headers $headers -TimeoutSec 2
        $modelIds = @($result.data | ForEach-Object { $_.id })
        $ready = $true
    } catch { if ($Action -eq 'start') { Start-Sleep -Milliseconds 500 } }
} until ($ready -or (Get-Date) -gt $deadline)
if ($Action -eq 'start' -and -not $ready) { throw 'Proxy startup did not become ready. Inspect this deployment logs.' }
@{ running = [bool]$owned; reachable = $ready; base_url = "http://127.0.0.1:$($settings.port)/v1"; models = $modelIds } | ConvertTo-Json -Depth 4
