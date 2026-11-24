param(
    [int]$Port = 0,
    [string]$InstallDir = '',
    [switch]$NoLaunch,
    [switch]$NoAgent
)

# J.A.R.V.I.S. — «Не удаётся связаться с сервером»: проверка и восстановление.
# Работает и из распакованного архива, и из %LOCALAPPDATA%\JARVIS.
# only Windows PowerShell 5.1+, stdlib, без прав администратора.

$ErrorActionPreference = 'Stop'

function Say {
    param([string]$Text, [string]$Color = 'Gray')
    Write-Host ('  ' + $Text) -ForegroundColor $Color
}

$here = Split-Path -Parent $PSCommandPath
$candidates = @()
if ($InstallDir) { $candidates += $InstallDir }
$candidates += (Join-Path $env:LOCALAPPDATA 'JARVIS')
$candidates += (Split-Path -Parent $here)
$candidates += $here
$candidates += (Get-Location).Path

$root = ''
$appDir = ''
foreach ($candidate in $candidates) {
    if (-not $candidate) { continue }
    if (Test-Path (Join-Path $candidate 'app\jarvis.py')) {
        $root = $candidate
        $appDir = Join-Path $candidate 'app'
        break
    }
    if (Test-Path (Join-Path $candidate 'jarvis.py')) {
        $root = $candidate
        $appDir = $candidate
        break
    }
}
if (-not $root) {
    Say 'Не найден jarvis.py. Запустите FIX-SERVER.bat из папки с архивом или переустановите J.A.R.V.I.S.' 'Red'
    exit 2
}

# Порт берём из конфигурации, если он там есть.
if ($Port -le 0) {
    $cfgPath = Join-Path $appDir 'jarvis.config.json'
    if (Test-Path $cfgPath) {
        try {
            $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($cfg.port) { $Port = [int]$cfg.port }
        } catch { }
    }
}
if ($Port -le 0) { $Port = 8080 }
$url = "http://127.0.0.1:$Port"

function Test-Health {
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "$url/api/health" -TimeoutSec 2
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

function Resolve-PythonExe {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        try {
            $exe = (& $py.Source -3 -c 'import sys; print(sys.executable)' 2>$null | Select-Object -First 1)
            if ($exe) {
                $exe = ([string]$exe).Trim()
                if (Test-Path $exe) { return $exe }
            }
        } catch { }
    }
    foreach ($name in @('python', 'python3')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) {
            try {
                $exe = (& $cmd.Source -c 'import sys; print(sys.executable)' 2>$null | Select-Object -First 1)
                if ($exe) {
                    $exe = ([string]$exe).Trim()
                    if (Test-Path $exe) { return $exe }
                }
            } catch { }
        }
    }
    $globs = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python*\python.exe'),
        (Join-Path $env:ProgramFiles 'Python*\python.exe')
    )
    foreach ($glob in $globs) {
        $found = Get-ChildItem -Path $glob -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { return $found.FullName }
    }
    return ''
}

function Show-PortOwner {
    try {
        $conns = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop)
        foreach ($conn in $conns) {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            $pname = if ($proc) { $proc.ProcessName } else { 'неизвестно' }
            Say "Порт $Port слушает PID $($conn.OwningProcess) ($pname)" 'Yellow'
        }
        return $conns.Count
    } catch {
        $lines = @(netstat -ano | Select-String ":$Port\s")
        foreach ($line in $lines) { Say $line.ToString().Trim() 'Yellow' }
        return $lines.Count
    }
}

function Stop-StaleJarvis {
    $list = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and
        ($_.CommandLine -like '*jarvis.py*' -or $_.CommandLine -like '*jarvis_agent.py*') -and
        ($_.CommandLine -like "*$appDir*" -or $_.CommandLine -like '*JARVIS*')
    })
    foreach ($proc in $list) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
    return $list.Count
}

function Start-JarvisServer {
    param([string]$PythonExe)
    $logDir = Join-Path $root 'logs'
    if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
    $outLog = Join-Path $logDir 'server.out.log'
    $errLog = Join-Path $logDir 'server.err.log'
    Remove-Item $outLog, $errLog -Force -ErrorAction SilentlyContinue

    $env:JARVIS_HOST = '127.0.0.1'
    $env:JARVIS_PORT = [string]$Port
    $argList = @('jarvis.py', '--host', '127.0.0.1', '--port', [string]$Port)
    $proc = Start-Process -FilePath $PythonExe -ArgumentList $argList `
                -WorkingDirectory $appDir -WindowStyle Hidden `
                -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
    Say "Сервер запущен: PID $($proc.Id) · лог $outLog" 'Cyan'
}

function Start-JarvisAgent {
    param([string]$PythonExe)
    $agent = Join-Path $appDir 'jarvis_agent.py'
    if (-not (Test-Path $agent)) { return }
    $running = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -and $_.CommandLine -like '*jarvis_agent.py*'
    })
    if ($running.Count -gt 0) {
        Say 'Агент ПК уже запущен' 'Gray'
        return
    }
    $token = 'jarvis-local-agent'
    $cfgPath = Join-Path $appDir 'jarvis.config.json'
    if (Test-Path $cfgPath) {
        try {
            $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($cfg.agent_token) { $token = [string]$cfg.agent_token }
        } catch { }
    }
    $logDir = Join-Path $root 'logs'
    $outLog = Join-Path $logDir 'agent.out.log'
    $errLog = Join-Path $logDir 'agent.err.log'
    Remove-Item $outLog, $errLog -Force -ErrorAction SilentlyContinue
    $argList = @('jarvis_agent.py', '--server', $url, '--token', $token)
    $proc = Start-Process -FilePath $PythonExe -ArgumentList $argList `
                -WorkingDirectory $appDir -WindowStyle Hidden `
                -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru
    Say "Агент ПК запущен: PID $($proc.Id)" 'Cyan'
}

Write-Host ''
Write-Host '  J.A.R.V.I.S. — ПРОВЕРКА СВЯЗИ С СЕРВЕРОМ' -ForegroundColor Cyan
Write-Host '  ─────────────────────────────────────────────────────' -ForegroundColor DarkCyan
Say "Папка: $appDir"
Say "Ожидаемый адрес: $url" 'Cyan'
Say 'ВСЕГДА открывайте 127.0.0.1, а не localhost и не старую ссылку *.e2b.app' 'Yellow'
Write-Host ''

if (Test-Health) {
    Say 'Сервер уже отвечает — ничего чинить не нужно.' 'Green'
    if (-not $NoLaunch) { Start-Process $url }
    Write-Host ''
    exit 0
}

Say 'Сервер не отвечает. Проверяю порт и Python...' 'Yellow'
$owners = Show-PortOwner
$pythonExe = Resolve-PythonExe
if (-not $pythonExe) {
    Say 'Python не найден. Запустите INSTALL_WINDOWS.bat ещё раз — он поставит Python 3.9+.' 'Red'
    Write-Host ''
    exit 2
}
Say "Python: $pythonExe" 'Gray'

$stopped = Stop-StaleJarvis
if ($stopped -gt 0) {
    Say "Остановлено зависших процессов J.A.R.V.I.S.: $stopped" 'Yellow'
    Start-Sleep -Milliseconds 900
}

Start-JarvisServer $pythonExe
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 700
    if (Test-Health) { $ready = $true; break }
}

Write-Host ''
if ($ready) {
    Say "ГОТОВО: сервер отвечает на $url" 'Green'
    if (-not $NoAgent) {
        Start-Sleep -Milliseconds 1200
        Start-JarvisAgent $pythonExe
    }
    if (-not $NoLaunch) { Start-Process $url }
    Say 'Если браузер всё ещё пишет «не удаётся связаться», откройте именно http://127.0.0.1:8080' 'Yellow'
    Write-Host ''
    exit 0
}

Say 'Не удалось поднять сервер. Что делать:' 'Red'
Say '1) Откройте именно http://127.0.0.1:8080 (не localhost, не file://, не *.e2b.app).' 'Yellow'
if ($owners -gt 0) {
    Say "2) Порт $Port занят другой программой. Либо закройте её, либо запустите: FIX-SERVER.bat -Port 9000" 'Yellow'
}
Say '3) Посмотрите логи в папке logs (server.err.log, server.out.log, install.log).' 'Yellow'
Say '4) Если Python ставился вручную — перезапустите INSTALL_WINDOWS.bat.' 'Yellow'
$logDir = Join-Path $root 'logs'
foreach ($name in @('server.err.log', 'server.out.log')) {
    $p = Join-Path $logDir $name
    if (Test-Path $p) {
        Say "--- $name (последние строки) ---" 'DarkGray'
        Get-Content $p -Tail 15 -ErrorAction SilentlyContinue | ForEach-Object { Say $_ 'DarkGray' }
    }
}
Write-Host ''
exit 2
