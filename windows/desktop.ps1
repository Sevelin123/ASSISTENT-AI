param(
    [string]$InstallDir = '',
    [int]$Port = 8080
)

$ErrorActionPreference = 'SilentlyContinue'
if (-not $InstallDir) {
    $InstallDir = Split-Path -Parent $PSScriptRoot
}
$AppDir = Join-Path $InstallDir 'app'
if (-not (Test-Path (Join-Path $AppDir 'jarvis.py'))) { $AppDir = $InstallDir }
$HudUrl = "http://127.0.0.1:$Port"
$LogDir = Join-Path $InstallDir 'logs'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

function Test-Health {
    try {
        $r = Invoke-WebRequest -Uri "$HudUrl/api/health" -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Resolve-Python {
    foreach ($name in @('pyw.exe', 'pythonw.exe', 'py.exe', 'python.exe')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) {
            $prefix = @()
            if ($name -like 'py*') { $prefix = @('-3') }
            return @{ Path = $cmd.Source; Prefix = $prefix; Name = $name }
        }
    }
    return $null
}

function Start-JarvisServer {
    if (Test-Health) { return }
    $py = Resolve-Python
    if (-not $py) {
        Write-EventLogFallback 'Python 3.9+ not found; run INSTALL_WINDOWS.bat again.'
        return
    }
    $argList = @() + $py.Prefix + @('jarvis.py', '--smart', '--host', '127.0.0.1', '--port', "$Port")
    Start-Process -FilePath $py.Path -ArgumentList $argList -WorkingDirectory $AppDir -WindowStyle Hidden | Out-Null
    for ($i = 0; $i -lt 40; $i++) {
        if (Test-Health) { return }
        Start-Sleep -Milliseconds 500
    }
    Write-EventLogFallback 'JARVIS server did not become healthy in 20 seconds.'
}

function Write-EventLogFallback([string]$Message) {
    try { Add-Content -Path (Join-Path $LogDir 'desktop.log') -Value ((Get-Date -Format o) + ' ' + $Message) -Encoding UTF8 } catch {}
}

function Show-Fatal([string]$Message) {
    Write-EventLogFallback $Message
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        [System.Windows.Forms.MessageBox]::Show($Message, 'J.A.R.V.I.S.',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
    } catch {
        Write-Host $Message
    }
}

function Resolve-Browser {
    $pf = [Environment]::GetFolderPath('ProgramFiles')
    $pf86 = ${env:ProgramFiles(x86)}
    if (-not $pf86) { $pf86 = $pf }
    $local = $env:LOCALAPPDATA
    $candidates = @(
        (Join-Path $pf86 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $pf 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $local 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $pf86 'Google\Chrome\Application\chrome.exe'),
        (Join-Path $pf 'Google\Chrome\Application\chrome.exe'),
        (Join-Path $local 'Google\Chrome\Application\chrome.exe')
    )
    foreach ($p in $candidates) { if (Test-Path $p) { return $p } }
    foreach ($name in @('msedge.exe', 'chrome.exe')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { return $cmd.Source }
    }
    return $null
}

Start-JarvisServer
if (-not (Test-Health)) {
    Show-Fatal 'Локальный сервер J.A.R.V.I.S. не ответил. Запустите START-JARVIS.bat или FIX-SERVER.bat.'
    exit 2
}

$browser = Resolve-Browser
if (-not $browser) {
    Show-Fatal 'Нужен Microsoft Edge или Google Chrome для голосового Web Speech API.'
    exit 3
}
$profile = Join-Path $InstallDir 'DesktopProfile'
if (-not (Test-Path $profile)) { New-Item -ItemType Directory -Path $profile -Force | Out-Null }
$browserArgs = @(
    "--app=$HudUrl",
    "--user-data-dir=`"$profile`"",
    '--window-size=1440,900',
    '--window-position=40,40',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    '--disable-sync',
    '--disable-features=msEdgeSplitScreen,msWebOOUI,msPdfOOUI',
    '--proxy-bypass-list="127.0.0.1;localhost"'
)
Start-Process -FilePath $browser -ArgumentList $browserArgs | Out-Null
exit 0
