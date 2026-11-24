param(
    [string]$InstallDir = '',
    [string]$Model = 'llama3.2:3b'
)

$ErrorActionPreference = 'Continue'
if (-not $InstallDir) { $InstallDir = Split-Path -Parent $PSScriptRoot }

function Resolve-Ollama {
    $cmd = Get-Command ollama.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'),
        (Join-Path $env:ProgramFiles 'Ollama\ollama.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Ollama\ollama.exe')
    )
    foreach ($p in $candidates) { if (Test-Path $p) { return $p } }
    return $null
}

function Resolve-Winget {
    $cmd = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $p = Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\winget.exe'
    if (Test-Path $p) { return $p }
    return $null
}

function Test-OllamaApi {
    try {
        $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 2 -ErrorAction Stop
        return $true
    } catch { return $false }
}

function Get-Models {
    try {
        $tags = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 -ErrorAction Stop
        return @($tags.models | ForEach-Object { $_.name })
    } catch { return @() }
}

Write-Host 'J.A.R.V.I.S. SMART MODE — локальная языковая модель БЕЗ API-ключа' -ForegroundColor Cyan
Write-Host 'Ключ из Arena не используется и не запрашивается.' -ForegroundColor Yellow

$ollama = Resolve-Ollama
if (-not $ollama) {
    $winget = Resolve-Winget
    if ($winget) {
        Write-Host 'Устанавливаю Ollama через winget (Ollama.Ollama)...' -ForegroundColor Cyan
        & $winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
        Start-Sleep -Seconds 2
        $ollama = Resolve-Ollama
    }
}
if (-not $ollama) {
    Write-Host 'Не удалось установить Ollama автоматически. Установите её с https://ollama.com/download/windows' -ForegroundColor Red
    Write-Host 'и запустите SMART-MODE.bat ещё раз.' -ForegroundColor Red
    exit 2
}
Write-Host "Ollama: $ollama" -ForegroundColor Green

if (-not (Test-OllamaApi)) {
    Write-Host 'Запускаю локальный сервер Ollama...' -ForegroundColor Cyan
    Start-Process -FilePath $ollama -ArgumentList @('serve') -WindowStyle Hidden | Out-Null
    for ($i = 0; $i -lt 30; $i++) {
        if (Test-OllamaApi) { break }
        Start-Sleep -Milliseconds 500
    }
}
if (-not (Test-OllamaApi)) {
    Write-Host 'Ollama API на порту 11434 не отвечает. Проверьте брандмауэр/антивирус.' -ForegroundColor Red
    exit 3
}

$models = Get-Models
if ($models.Count -eq 0) {
    Write-Host "Скачиваю локальную модель $Model (один раз, без облачного ключа)..." -ForegroundColor Cyan
    & $ollama pull $Model
    $models = Get-Models
}
if ($models.Count -eq 0) {
    Write-Host 'Модель не найдена. Выполните: ollama pull llama3.2:3b' -ForegroundColor Red
    exit 4
}
Write-Host ('Доступные модели: ' + ($models -join ', ')) -ForegroundColor Green

try {
    $smart = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8080/api/smart' `
        -ContentType 'application/json' -Body '{}' -TimeoutSec 5 -ErrorAction Stop
    Write-Host ('Подключено: ' + $smart.model + ' · ' + $smart.reason) -ForegroundColor Green
} catch {
    Write-Host 'Сервер J.A.R.V.I.S. сейчас не запущен — это нормально.' -ForegroundColor Yellow
    Write-Host 'Запустите JARVIS-APP.exe: он сам подключит локальную модель через --smart.' -ForegroundColor Yellow
}

Write-Host 'Готово. В HUD пилка покажет МОЗГ: LOCAL LLM.' -ForegroundColor Green
exit 0
