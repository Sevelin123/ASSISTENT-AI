<#
    J.A.R.V.I.S. — автоматическая установка на Windows
    ---------------------------------------------------
    Запуск:  INSTALL_WINDOWS.bat   (двойной клик)
    Или:     powershell -ExecutionPolicy Bypass -File windows\setup.ps1

    Параметры:
      -InstallDir <path>   куда ставить  (по умолчанию %LOCALAPPDATA%\JARVIS)
      -Port <n>            порт HUD     (по умолчанию 8080)
      -BindAddress <ip>    127.0.0.1 (по умолчанию) или 0.0.0.0
      -Lan                 слушать всю сеть + открыть порт в брандмауэре
      -NoAutostart         не добавлять в автозагрузку
      -NoTray              не показывать иконку в трее
      -NoLaunch            не открывать браузер после установки
      -Source <path>       папка с исходниками (иначе — рядом или GitHub)
      -Branch <name>       ветка GitHub для загрузки исходников
      -PythonPath <path>   явный путь к python.exe
      -Update              обновить файлы, сохранив данные и настройки
      -Uninstall           удалить сервисы и ярлыки
      -Purge               вместе с -Uninstall удалить все данные
      -Silent              не задавать вопросов
#>

[CmdletBinding()]
param(
    [string]$InstallDir   = (Join-Path $env:LOCALAPPDATA 'JARVIS'),
    [int]$Port            = 8080,
    [string]$BindAddress  = '127.0.0.1',
    [switch]$Lan,
    [switch]$NoAutostart,
    [switch]$NoTray,
    [switch]$NoLaunch,
    [string]$Source       = '',
    [string]$Branch       = '',
    [string]$PythonPath   = '',
    [switch]$Update,
    [switch]$Uninstall,
    [switch]$Purge,
    [switch]$Silent
)

$ErrorActionPreference = 'Stop'
$RepoOwner  = 'Sevelin123'
$RepoName   = 'ASSISTENT-AI'
$AppName    = 'J.A.R.V.I.S.'
$Utf8NoBom  = New-Object System.Text.UTF8Encoding($false)

if ($Lan) { $BindAddress = '0.0.0.0' }
$HudHost = if ($BindAddress -eq '0.0.0.0') { '127.0.0.1' } else { $BindAddress }
$HudUrl  = "http://${HudHost}:$Port"

$AppDir    = Join-Path $InstallDir 'app'
$LogDir    = Join-Path $InstallDir 'logs'
$DataDir   = Join-Path $AppDir    '.jarvis_data'
$LogFile   = Join-Path $InstallDir 'install.log'
$Startup   = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
$Programs  = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\J.A.R.V.I.S'
$Desktop   = [Environment]::GetFolderPath('Desktop')

# ---------------------------------------------------------------- helpers
function Write-Log {
    param([string]$Message, [string]$Level = 'INFO')
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format 'HH:mm:ss'), $Level, $Message
    try {
        if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null }
        Add-Content -Path $LogFile -Value $line -Encoding UTF8
    } catch { }
    switch ($Level) {
        'OK'    { Write-Host "  [OK]  $Message" -ForegroundColor Green }
        'WARN'  { Write-Host "  [!]   $Message" -ForegroundColor Yellow }
        'ERROR' { Write-Host "  [X]   $Message" -ForegroundColor Red }
        default { Write-Host "  ...   $Message" -ForegroundColor Gray }
    }
}

function ConvertTo-Crlf {
    param([string]$Text)
    return (($Text -replace "`r`n", "`n") -replace "`n", "`r`n")
}

function Write-TextFile {
    param([string]$Path, [string]$Content)
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($Path, (ConvertTo-Crlf $Content), $Utf8NoBom)
}

function New-Shortcut {
    param([string]$Path, [string]$Target, [string]$Arguments = '',
          [string]$WorkDir = '', [string]$Icon = '', [string]$Description = '')
    try {
        $ws  = New-Object -ComObject WScript.Shell
        $lnk = $ws.CreateShortcut($Path)
        $lnk.TargetPath = $Target
        if ($Arguments)    { $lnk.Arguments = $Arguments }
        if ($WorkDir)      { $lnk.WorkingDirectory = $WorkDir }
        if ($Icon)         { $lnk.IconLocation = $Icon }
        if ($Description)  { $lnk.Description = $Description }
        $lnk.Save()
        return $true
    } catch {
        Write-Log "Не удалось создать ярлык $Path : $_" 'WARN'
        return $false
    }
}

function Stop-JarvisProcesses {
    $killed = 0
    try {
        $procs = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $_.CommandLine -and $_.CommandLine -like "*$InstallDir*" -and
            ($_.CommandLine -like '*jarvis.py*' -or $_.CommandLine -like '*jarvis_agent.py*' -or
             $_.CommandLine -like '*tray.ps1*')
        }
    } catch {
        $procs = Get-WmiObject Win32_Process | Where-Object {
            $_.CommandLine -and $_.CommandLine -like "*$InstallDir*" -and
            ($_.CommandLine -like '*jarvis.py*' -or $_.CommandLine -like '*jarvis_agent.py*')
        }
    }
    foreach ($p in $procs) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue; $killed++ } catch { }
    }
    return $killed
}

# ---------------------------------------------------------------- uninstall
if ($Uninstall) {
    Write-Host ''
    Write-Host '  Удаление J.A.R.V.I.S.' -ForegroundColor Cyan
    $n = Stop-JarvisProcesses
    Write-Log "Остановлено процессов: $n" 'OK'
    $targets = @(
        (Join-Path $Startup 'J.A.R.V.I.S. Background.lnk'),
        (Join-Path $Startup 'J.A.R.V.I.S. Tray.lnk'),
        (Join-Path $Desktop 'J.A.R.V.I.S..lnk'),
        (Join-Path $Desktop 'J.A.R.V.I.S.lnk')
    )
    foreach ($t in $targets) {
        if (Test-Path $t) { Remove-Item $t -Force; Write-Log "Удалён ярлык $t" }
    }
    if (Test-Path $Programs) { Remove-Item $Programs -Recurse -Force; Write-Log 'Удалена папка в меню Пуск' }
    try {
        Get-NetFirewallRule -DisplayName 'J.A.R.V.I.S. HUD' -ErrorAction SilentlyContinue |
            Remove-NetFirewallRule -ErrorAction SilentlyContinue
    } catch { }
    if ($Purge) {
        if (-not $Silent) {
            $answer = Read-Host '  Удалить ВСЕ данные (заметки, задачи, настройки)? [y/N]'
            if ($answer -notmatch '^(y|д|yes)$') { $Purge = $false }
        }
        if ($Purge) {
            Start-Sleep -Milliseconds 500
            Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
            Write-Log "Папка $InstallDir полностью удалена" 'OK'
        }
    }
    if (-not $Purge) { Write-Log "Данные и логи сохранены в $InstallDir" 'OK' }
    Write-Host ''
    Write-Host '  Готово. Для повторной установки запустите INSTALL_WINDOWS.bat' -ForegroundColor Green
    Write-Host ''
    if (-not $Silent) { Read-Host '  Нажмите Enter для выхода' | Out-Null }
    exit 0
}

# ---------------------------------------------------------------- banner
Write-Host ''
Write-Host '     ╔═══════════════════════════════════════════════════════╗' -ForegroundColor Cyan
Write-Host '     ║   J.A.R.V.I.S.  ·  АВТОМАТИЧЕСКАЯ УСТАНОВКА WINDOWS    ║' -ForegroundColor Cyan
Write-Host '     ╚═══════════════════════════════════════════════════════╝' -ForegroundColor Cyan
Write-Host ''
Write-Log "Установка в $InstallDir · HUD $HudUrl"
if ($Update) { Write-Log 'Режим обновления: данные и настройки будут сохранены' }

if ($env:OS -ne 'Windows_NT') {
    Write-Log 'Этот установщик предназначен только для Windows.' 'ERROR'
    exit 1
}

# ---------------------------------------------------------------- 1. Python
function Resolve-Python {
    param([string]$Hint)
    $candidates = @()
    if ($Hint) { $candidates += $Hint }

    # py launcher knows where the real interpreter lives
    try {
        $resolved = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $resolved) { $candidates += ($resolved | Select-Object -First 1).Trim() }
    } catch { }

    foreach ($name in @('python', 'python3')) {
        $c = Get-Command $name -ErrorAction SilentlyContinue
        if ($c) { $candidates += $c.Source }
    }
    $candidates += @(Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python*\python.exe') -ErrorAction SilentlyContinue |
                     ForEach-Object { $_.FullName })
    $candidates += @(Get-ChildItem 'C:\Python*\python.exe' -ErrorAction SilentlyContinue |
                     ForEach-Object { $_.FullName })

    foreach ($exe in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
        if (-not (Test-Path $exe)) { continue }
        try {
            $v = & $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v) {
                $ver = [version]$v.Trim()
                if ($ver.Major -gt 3 -or ($ver.Major -eq 3 -and $ver.Minor -ge 9)) {
                    return @{ Path = $exe; Version = $v.Trim() }
                }
            }
        } catch { }
    }
    return $null
}

function Install-Python {
    Write-Log 'Python 3.9+ не найден. Пытаюсь установить автоматически...' 'WARN'
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        try {
            Write-Log 'Установка Python через winget (это может занять пару минут)...'
            & winget install --id Python.Python.3.12 -e --silent `
                --accept-source-agreements --accept-package-eula 2>&1 | Out-Null
        } catch { Write-Log "winget: $_" 'WARN' }
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                    [Environment]::GetEnvironmentVariable('Path', 'User')
        $found = Resolve-Python ''
        if ($found) { return $found }
    }
    # Fallback: официальный тихий установщик
    $url = 'https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe'
    $installer = Join-Path $env:TEMP 'jarvis-python-installer.exe'
    try {
        Write-Log 'Загрузка официального установщика Python...'
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $installer -TimeoutSec 180
        Start-Process -FilePath $installer -ArgumentList '/quiet','InstallAllUsers=0','PrependPath=1',`
            'Include_test=0','Include_launcher=1' -Wait
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                    [Environment]::GetEnvironmentVariable('Path', 'User')
        $found = Resolve-Python ''
        if ($found) { return $found }
    } catch { Write-Log "Загрузка Python не удалась: $_" 'WARN' }
    return $null
}

$py = Resolve-Python $PythonPath
if (-not $py) { $py = Install-Python }
if (-not $py) {
    Write-Log 'Не удалось установить Python автоматически.' 'ERROR'
    Write-Host ''
    Write-Host '  Установите Python 3.9+ вручную: https://www.python.org/downloads/' -ForegroundColor Yellow
    Write-Host '  Во время установки ОБЯЗАТЕЛЬНО поставьте галочку "Add Python to PATH".' -ForegroundColor Yellow
    Write-Host '  Затем запустите INSTALL_WINDOWS.bat снова.' -ForegroundColor Yellow
    Write-Host ''
    if (-not $Silent) { Read-Host '  Нажмите Enter для выхода' | Out-Null }
    exit 1
}
$PythonExe = $py.Path
Write-Log "Python $($py.Version): $PythonExe" 'OK'

# ---------------------------------------------------------------- 2. источник файлов
function Get-SourceFiles {
    if ($Source -and (Test-Path (Join-Path $Source 'jarvis.py'))) { return (Resolve-Path $Source).Path }

    $scriptDir = Split-Path -Parent $PSCommandPath
    foreach ($candidate in @((Split-Path -Parent $scriptDir), $scriptDir, (Get-Location).Path)) {
        if (Test-Path (Join-Path $candidate 'jarvis.py')) { return (Resolve-Path $candidate).Path }
    }

    Write-Log 'Исходники рядом не найдены — загружаю репозиторий с GitHub...' 'WARN'
    $branch  = $Branch
    $repoSha = ''
    $defaultBranch = 'arena/57b8f59e-assistent-ai'
    if (-not $branch) { $branch = $defaultBranch }
    try {
        $branches = Invoke-RestMethod -Uri "https://api.github.com/repos/$RepoOwner/$RepoName/branches?per_page=100" `
                    -TimeoutSec 20 -Headers @{ 'User-Agent' = 'JARVIS-Setup' }
        $chosen = $branches | Where-Object { $_.name -eq $branch } | Select-Object -First 1
        if ($chosen) { $repoSha = $chosen.commit.sha }
        elseif (-not $Branch) {
            # Fall back to the newest arena branch if the session branch was renamed.
            $arena = $branches | Where-Object { $_.name -like 'arena/*' } | Select-Object -First 1
            if ($arena) { $branch = $arena.name; $repoSha = $arena.commit.sha }
        }
    } catch { }
    # A commit SHA works even for branch names containing '/'; if the API is
    # unavailable, codeload's refs/heads/<branch> URL still works with slashes.
    if (-not $repoSha -and $branch -notmatch '/') {
        try {
            $repoSha = (Invoke-RestMethod -Uri "https://api.github.com/repos/$RepoOwner/$RepoName/branches/$branch" `
                        -TimeoutSec 15 -Headers @{ 'User-Agent' = 'JARVIS-Setup' }).commit.sha
        } catch { }
    }
    $zipUrl = if ($repoSha) {
        "https://codeload.github.com/$RepoOwner/$RepoName/zip/$repoSha"
    } else {
        "https://codeload.github.com/$RepoOwner/$RepoName/zip/refs/heads/$branch"
    }
    Write-Log "Ветка: $branch · источник: $zipUrl"
    $tmpZip = Join-Path $env:TEMP 'jarvis-windows.zip'
    $tmpDir = Join-Path $env:TEMP 'jarvis-windows-src'
    Invoke-WebRequest -UseBasicParsing -Uri $zipUrl -OutFile $tmpZip -TimeoutSec 180
    if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }
    Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force
    $root = Get-ChildItem $tmpDir -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'jarvis.py') } |
            Select-Object -First 1
    if (-not $root) { throw 'В загруженном архиве нет jarvis.py. Укажите -Source с путём к распакованному проекту.' }
    return $root.FullName
}

try {
    $src = Get-SourceFiles
} catch {
    Write-Log "Не удалось получить файлы проекта: $_" 'ERROR'
    Write-Host ''
    Write-Host '  Положите INSTALL_WINDOWS.bat в папку с проектом (рядом с jarvis.py)' -ForegroundColor Yellow
    Write-Host '  или скачайте полный архив из HUD: Настройки → Агент ПК → Windows.' -ForegroundColor Yellow
    Write-Host ''
    if (-not $Silent) { Read-Host '  Нажмите Enter для выхода' | Out-Null }
    exit 1
}
Write-Log "Исходники: $src" 'OK'

# ---------------------------------------------------------------- 3. развёртывание
Write-Log 'Останавливаю предыдущие процессы J.A.R.V.I.S...'
$n = Stop-JarvisProcesses
if ($n) { Write-Log "Остановлено процессов: $n" }

foreach ($d in @($InstallDir, $AppDir, $LogDir, $DataDir)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

$existingConfig = Join-Path $AppDir 'jarvis.config.json'
$hadConfig = Test-Path $existingConfig

Get-ChildItem -Path $src -File | Where-Object {
    $_.Name -ne 'jarvis.config.json' -and $_.Extension -ne '.db'
} | ForEach-Object { Copy-Item $_.FullName -Destination $AppDir -Force }
foreach ($sub in @('jarvis', 'web', 'tests', 'windows')) {
    $p = Join-Path $src $sub
    if (Test-Path $p) {
        Copy-Item $p -Destination $AppDir -Recurse -Force
        Get-ChildItem (Join-Path $AppDir $sub) -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
}
# Ключевые файлы помощи доступны прямо в корне установки (двойной клик).
foreach ($extra in @('START-JARVIS.bat', 'FIX-SERVER.bat', 'START-HERE.html', 'SMART-MODE.bat', 'JARVIS-APP.vbs')) {
    $extraSrc = Join-Path $src $extra
    if (Test-Path $extraSrc) { Copy-Item $extraSrc -Destination $InstallDir -Force }
}
# windows\fix-server.ps1 должен лежать и в корне установки для FIX-SERVER.bat.
$winSrc = Join-Path $AppDir 'windows'
if (Test-Path $winSrc) { Copy-Item $winSrc -Destination $InstallDir -Recurse -Force }
Write-Log 'Файлы приложения, START-JARVIS.bat и FIX-SERVER.bat скопированы' 'OK'

# ------------------------------------------------ desktop EXE: window, not browser tab
foreach ($shellFile in @('desktop.ps1', 'smart-mode.ps1', 'JARVIS-App.cs')) {
    if (-not (Test-Path (Join-Path $InstallDir "windows\$shellFile"))) {
        Write-Log "Не найден компонент приложения windows\$shellFile" 'WARN'
    }
}

$desktopExe = Join-Path $InstallDir 'JARVIS-APP.exe'
$desktopVbs = Join-Path $InstallDir 'JARVIS-APP.vbs'
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $csc)) { $csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe' }
$csSrc = Join-Path $InstallDir 'windows\JARVIS-App.cs'
Remove-Item $desktopExe -Force -ErrorAction SilentlyContinue
if ((Test-Path $csc) -and (Test-Path $csSrc)) {
    try {
        & $csc /nologo /target:winexe /optimize+ "/out:$desktopExe" `
            /reference:System.Windows.Forms.dll /reference:System.Drawing.dll "$csSrc" 2>&1 |
            ForEach-Object { Write-Log "csc: $_" 'INFO' }
    } catch {
        Write-Log "Не удалось собрать JARVIS-APP.exe: $_" 'WARN'
    }
}
if (Test-Path $desktopExe) {
    Write-Log 'Создан JARVIS-APP.exe — отдельное окно приложения без вкладок браузера' 'OK'
} else {
    Write-Log 'csc недоступен: используется JARVIS-APP.vbs (тот же app-mode)' 'WARN'
}

# Конфигурация (не перезаписываем пользовательские настройки и ключи)
if (-not $hadConfig) {
    $cfg = [ordered]@{
        host            = $BindAddress
        port            = $Port
        llm_enabled     = $false
        llm_base_url    = 'https://api.openai.com/v1'
        llm_model       = 'gpt-4o-mini'
        user_name       = ''
        persona         = 'jarvis'
        lang            = 'ru-RU'
        wake_word       = 'джарвис'
        speak_replies   = $true
        listen_mode     = 'wake'
        voice_rate      = 1.0
        voice_pitch     = 1.0
        allow_shell     = $false
        allow_power     = $false
        require_confirm = $true
        sandbox_root    = ''
        agent_token     = 'jarvis-local-agent'
    }
    Write-TextFile $existingConfig (($cfg | ConvertTo-Json -Depth 4) + "`r`n")
    Write-Log 'Создан jarvis.config.json (без API-ключей)' 'OK'
} else {
    Write-Log 'Существующий jarvis.config.json сохранён' 'OK'
}

# ---------------------------------------------------------------- 4. иконка
$IcoPath = Join-Path $InstallDir 'jarvis.ico'
function New-JarvisIcon {
    try {
        Add-Type -AssemblyName System.Drawing
        $bmp  = [System.Drawing.Bitmap]::new(64, 64)
        $g    = [System.Drawing.Graphics]::FromImage($bmp)
        $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $g.Clear([System.Drawing.Color]::FromArgb(3, 8, 15))
        $cyan = [System.Drawing.Color]::FromArgb(86, 225, 245)
        $pen  = [System.Drawing.Pen]::new($cyan, 3)
        $poly = [System.Drawing.Point[]]@(
            [System.Drawing.Point]::new(32, 3), [System.Drawing.Point]::new(61, 32),
            [System.Drawing.Point]::new(32, 61), [System.Drawing.Point]::new(3, 32)
        )
        $g.DrawPolygon($pen, $poly)
        $g.DrawEllipse([System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(75, 227, 192), 2), 14, 14, 36, 36)
        $font  = [System.Drawing.Font]::new('Consolas', 30, [System.Drawing.FontStyle]::Bold)
        $sf    = [System.Drawing.StringFormat]::new()
        $sf.Alignment = [System.Drawing.StringAlignment]::Center
        $sf.LineAlignment = [System.Drawing.StringAlignment]::Center
        $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::White)
        $g.DrawString('J', $font, $brush, 32, 33, $sf)
        $hIcon = $bmp.GetHicon()
        $icon  = [System.Drawing.Icon]::FromHandle($hIcon)
        $fs    = [System.IO.File]::Create($IcoPath)
        $icon.Save($fs); $fs.Close()
        $g.Dispose(); $bmp.Dispose()
        return $true
    } catch {
        Write-Log "Иконка не создана, использую системную: $_" 'WARN'
        return $false
    }
}
$iconOk = New-JarvisIcon
$IconLocation = if ($iconOk) { $IcoPath } else { "$env:SystemRoot\System32\imageres.dll,109" }

# ---------------------------------------------------------------- 5. запускатели
$token = 'jarvis-local-agent'
try {
    $cfgObj = Get-Content $existingConfig -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cfgObj.agent_token) { $token = $cfgObj.agent_token }
} catch { }

$serverCmd = @"
@echo off
cd /d "%~dp0app"
set "JARVIS_HOST=$BindAddress"
set "JARVIS_PORT=$Port"
set "JARVIS_AGENT_TOKEN=$token"
"$PythonExe" jarvis.py --host $BindAddress --port $Port > "%~dp0logs\server.log" 2>&1
"@
$agentCmd = @"
@echo off
cd /d "%~dp0app"
"$PythonExe" jarvis_agent.py --server $HudUrl --token $token > "%~dp0logs\agent.log" 2>&1
"@
Write-TextFile (Join-Path $InstallDir 'run-server.cmd') $serverCmd
Write-TextFile (Join-Path $InstallDir 'run-agent.cmd')  $agentCmd

$bgVbs = @'
Option Explicit
Dim sh, base
base = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
Set sh = CreateObject("WScript.Shell")
sh.Run """" & base & "run-server.cmd""", 0, False
WScript.Sleep 1800
sh.Run """" & base & "run-agent.cmd""", 0, False
'@
Write-TextFile (Join-Path $InstallDir 'start-background.vbs') $bgVbs

$openVbs = "Set sh = CreateObject(`"WScript.Shell`")`nsh.Run `"$HudUrl`", 1, False`n"
Write-TextFile (Join-Path $InstallDir 'open-hud.vbs') $openVbs

$stopPs = @'
param([string]$Root = (Split-Path -Parent $PSCommandPath))
$list = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -and $_.CommandLine -like "*$Root*" -and
    ($_.CommandLine -like '*jarvis.py*' -or $_.CommandLine -like '*jarvis_agent.py*' -or $_.CommandLine -like '*tray.ps1*')
}
foreach ($p in $list) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Host "Остановлено процессов: $(@($list).Count)"
'@
Write-TextFile (Join-Path $InstallDir 'stop-services.ps1') $stopPs
Write-TextFile (Join-Path $InstallDir 'stop-services.cmd') (
    "@echo off`npowershell -NoProfile -ExecutionPolicy Bypass -File `"%~dp0stop-services.ps1`"`npause`n")
Write-TextFile (Join-Path $InstallDir 'restart-services.cmd') (
    "@echo off`ncall `"%~dp0stop-services.cmd`" >nul`ntimeout /t 2 /nobreak >nul`nwscript `"%~dp0start-background.vbs`"`necho J.A.R.V.I.S. restarted.`n")

$traySrc = Join-Path $src 'windows\tray.ps1'
if (Test-Path $traySrc) { Copy-Item $traySrc (Join-Path $InstallDir 'tray.ps1') -Force }
Write-Log 'Созданы скрытые запускатели сервера и агента' 'OK'

# ---------------------------------------------------------------- 6. ярлыки
if (-not (Test-Path $Programs)) { New-Item -ItemType Directory -Path $Programs -Force | Out-Null }
$wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

$desktopAppExe = Join-Path $InstallDir 'JARVIS-APP.exe'
$desktopAppVbs = Join-Path $InstallDir 'JARVIS-APP.vbs'
if (Test-Path $desktopAppExe) {
    $desktopAppTarget = $desktopAppExe
    $desktopAppArgs = ''
} else {
    $desktopAppTarget = $wscript
    $desktopAppArgs = '"' + $desktopAppVbs + '"'
}
New-Shortcut -Path (Join-Path $Desktop 'J.A.R.V.I.S..lnk') -Target $desktopAppTarget `
    -Arguments $desktopAppArgs -WorkDir $InstallDir -Icon $IconLocation `
    -Description "Открыть приложение J.A.R.V.I.S. (без вкладок браузера)" | Out-Null
New-Shortcut -Path (Join-Path $Desktop 'J.A.R.V.I.S.lnk') -Target $desktopAppTarget `
    -Arguments $desktopAppArgs -WorkDir $InstallDir -Icon $IconLocation `
    -Description "Открыть приложение J.A.R.V.I.S." | Out-Null
New-Shortcut -Path (Join-Path $Programs 'Открыть J.A.R.V.I.S..lnk') -Target $desktopAppTarget `
    -Arguments $desktopAppArgs -WorkDir $InstallDir -Icon $IconLocation | Out-Null
New-Shortcut -Path (Join-Path $Programs 'J.A.R.V.I.S. Приложение.lnk') -Target $desktopAppTarget `
    -Arguments $desktopAppArgs -WorkDir $InstallDir -Icon $IconLocation `
    -Description "Отдельное окно J.A.R.V.I.S." | Out-Null
New-Shortcut -Path (Join-Path $Programs 'Включить умный режим.lnk') `
    -Target (Join-Path $InstallDir 'SMART-MODE.bat') -WorkDir $InstallDir | Out-Null
New-Shortcut -Path (Join-Path $Programs 'Открыть в браузере (legacy).lnk') -Target $wscript `
    -Arguments ('"' + (Join-Path $InstallDir 'open-hud.vbs') + '"') `
    -WorkDir $InstallDir -Icon $IconLocation | Out-Null
New-Shortcut -Path (Join-Path $Programs 'Перезапустить сервисы.lnk') -Target (Join-Path $InstallDir 'restart-services.cmd') -WorkDir $InstallDir | Out-Null
New-Shortcut -Path (Join-Path $Programs 'Запустить сервер (видимое окно).lnk') -Target (Join-Path $InstallDir 'START-JARVIS.bat') -WorkDir $InstallDir | Out-Null
New-Shortcut -Path (Join-Path $Programs 'Починить связь с сервером.lnk') -Target (Join-Path $InstallDir 'FIX-SERVER.bat') -WorkDir $InstallDir | Out-Null
New-Shortcut -Path (Join-Path $Programs 'Остановить.lnk') -Target (Join-Path $InstallDir 'stop-services.cmd') -WorkDir $InstallDir | Out-Null
New-Shortcut -Path (Join-Path $Programs 'Логи.lnk') -Target $LogDir -WorkDir $InstallDir | Out-Null
New-Shortcut -Path (Join-Path $Programs 'Удалить.lnk') -Target (Join-Path $AppDir 'UNINSTALL_WINDOWS.bat') -WorkDir $InstallDir | Out-Null

if ($NoAutostart) {
    foreach ($name in @('J.A.R.V.I.S. Background.lnk', 'J.A.R.V.I.S. Tray.lnk')) {
        $p = Join-Path $Startup $name
        if (Test-Path $p) { Remove-Item $p -Force }
    }
    Write-Log 'Автозагрузка отключена (-NoAutostart)' 'WARN'
} else {
    New-Shortcut -Path (Join-Path $Startup 'J.A.R.V.I.S. Background.lnk') -Target $wscript `
        -Arguments ('"' + (Join-Path $InstallDir 'start-background.vbs') + '"') `
        -WorkDir $InstallDir -Icon $IconLocation -Description 'J.A.R.V.I.S. server + PC agent' | Out-Null
    if ($NoTray -or -not (Test-Path (Join-Path $InstallDir 'tray.ps1'))) {
        $trayLnk = Join-Path $Startup 'J.A.R.V.I.S. Tray.lnk'
        if (Test-Path $trayLnk) { Remove-Item $trayLnk -Force }
    } else {
        New-Shortcut -Path (Join-Path $Startup 'J.A.R.V.I.S. Tray.lnk') -Target $powershell `
            -Arguments ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' +
                        (Join-Path $InstallDir 'tray.ps1') + '" -InstallDir "' + $InstallDir +
                        '" -HudUrl "' + $HudUrl + '"') `
            -WorkDir $InstallDir -Icon $IconLocation -Description 'J.A.R.V.I.S. tray monitor' | Out-Null
    }
    Write-Log 'Добавлено в автозагрузку Windows' 'OK'
}

# ---------------------------------------------------------------- 7. сеть
if ($Lan) {
    try {
        New-NetFirewallRule -DisplayName 'J.A.R.V.I.S. HUD' -Direction Inbound -LocalPort $Port `
            -Protocol TCP -Action Allow -ErrorAction Stop | Out-Null
        Write-Log "Порт $Port открыт в брандмауэре" 'OK'
    } catch {
        Write-Log 'Не удалось открыть порт (нужны права администратора). HUD всё равно доступен локально.' 'WARN'
    }
}

# ---------------------------------------------------------------- 8. запуск
Write-Log 'Запускаю сервер и агент управления ПК...'
$bg = Join-Path $InstallDir 'start-background.vbs'
Start-Process -FilePath $wscript -ArgumentList ('"' + $bg + '"') -WindowStyle Hidden

$ready = $false
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Milliseconds 700
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "$HudUrl/api/health" -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
}
if ($ready) { Write-Log "Сервер отвечает: $HudUrl" 'OK' }
else { Write-Log "Сервер не ответил за 30 с. Проверьте $LogDir\server.log" 'ERROR' }

$agentOk = $false
try {
    $s = Invoke-RestMethod -Uri "$HudUrl/api/agent/status" -TimeoutSec 4
    $agentOk = [bool]$s.connected
} catch { }
if ($agentOk) { Write-Log 'Агент ПК подключён — реальное управление компьютером активно' 'OK' }
else { Write-Log "Агент ещё подключается. Лог: $LogDir\agent.log" 'WARN' }

# ---------------------------------------------------------------- 9. голос TTS
# SAPI5 (Speech\Voices) and OneCore voices live in different registry hives.
$voiceHives = @(
    'HKLM:\SOFTWARE\Microsoft\Speech\Voices\Tokens',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Speech\Voices\Tokens',
    'HKLM:\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Speech_OneCore\Voices\Tokens'
)
$allVoices = @()
foreach ($key in $voiceHives) {
    if (Test-Path $key) {
        $allVoices += @(Get-ChildItem $key -ErrorAction SilentlyContinue |
                        ForEach-Object { $_.PSChildName })
    }
}
$allVoices = @($allVoices | Select-Object -Unique)
$ruVoiceNames = @($allVoices | Where-Object {
    $_ -match 'Irina|Pavel|Svetlana|Dmitry|Russian|ru-RU|Рус|RU-RU' })
$ruVoice = $ruVoiceNames.Count -gt 0
Write-Log "Системных голосов найдено: $($allVoices.Count)" 'INFO'
if ($ruVoice) {
    Write-Log "Русский голос для озвучивания найден: $($ruVoiceNames -join ', ')" 'OK'
} else {
    Write-Log 'Русский СИСТЕМНЫЙ голос не найден — это НЕ блокирует распознавание речи.' 'WARN'
    Write-Log 'Распознавание делает Chrome/Edge (Web Speech API), язык задаётся в HUD: Настройки → Язык распознавания → ru-RU.' 'INFO'
    Write-Log 'Для озвучки проще всего открыть HUD в Microsoft Edge: там облачные голоса «Microsoft ... Online (Natural)» без языкового пакета.' 'INFO'
    Write-Log 'Либо: Параметры → Время и язык → Речь → Добавить голоса → Русский (Россия). Нужны права администратора и Windows Update.' 'INFO'
    Write-Log 'Если голос не ставится: winver (Home Single Language нельзя), регион Россия, удалить/добавить язык заново, DISM /RestoreHealth + sfc /scannow.' 'INFO'
    Write-Log 'После установки голосов ПОЛНОСТЬЮ перезапустите браузер и нажмите «Обновить список» в настройках HUD.' 'INFO'
    $voiceHelp = @"
РУССКИЙ ГОЛОС: ЕСЛИ НЕ СТАВИТСЯ
=================================

1.Распознавание речи (что вы говорите) НЕ зависит от языкового пакета Windows.
  Его делает браузер Chrome/Edge. Язык: HUD -> Настройки -> Язык распознавания -> Русский (ru-RU).

2.Озвучивание ответов: откройте HUD в Microsoft Edge — у него есть онлайн-голоса
  Microsoft ... Online (Natural), включая русские, без установки языкового пакета.
  В HUD: Настройки -> Голос и речь -> Обновить список -> Голос ответа -> русский -> Тест речи.

3.Системный голос Windows:
  Параметры -> Время и язык -> Речь -> Управление голосами -> Добавить голоса -> Русский (Россия).
  Или: Язык и регион -> Добавить язык -> Русский -> Далее -> отметить «Преобразование текста в речь».

4.Если не ставится:
  - Win+R -> winver: «Home Single Language» не даёт добавить языковой пакет;
  - учётная запись Администратор, отключите VPN, обновите Windows, перезагрузитесь;
  - Страна или регион -> Россия;
  - удалите русский язык, перезагрузитесь, добавьте заново со всеми галочками;
  - от админа: DISM /Online /Cleanup-Image /RestoreHealth   затем   sfc /scannow;
  - полностью перезапустите браузер, иначе новые голоса не появятся в getVoices().

5.Можно вообще выключить озвучивание: скажите «Джарвис, выключи озвучивание».

Открыть параметры: ms-settings:speech  и  ms-settings:regionlanguage
"@
    Write-TextFile (Join-Path $InstallDir 'VOICE-HELP.txt') $voiceHelp
}

# ---------------------------------------------------------------- 10. финал
if ($ready -and -not $NoLaunch) {
    Start-Process $HudUrl
    Write-Log 'Открываю HUD в браузере' 'OK'
}

Write-Host ''
Write-Host '  ┌─────────────────────────────────────────────────────────┐' -ForegroundColor Cyan
Write-Host '  │   УСТАНОВКА ЗАВЕРШЕНА                                  │' -ForegroundColor Cyan
Write-Host '  └─────────────────────────────────────────────────────────┘' -ForegroundColor Cyan
Write-Host ''
$desktopAppLabel = if (Test-Path $desktopAppExe) { $desktopAppExe } else { $desktopAppVbs }
Write-Host "    ПРИЛОЖЕНИЕ:     $desktopAppLabel" -ForegroundColor Green
Write-Host '                    отдельное окно без вкладок и адресной строки' -ForegroundColor Gray
Write-Host "    HUD (legacy):   $HudUrl" -ForegroundColor White
Write-Host '    ВАЖНО:          открывать 127.0.0.1, а не localhost / file:// / *.e2b.app' -ForegroundColor Yellow
Write-Host "    Нет связи:      $InstallDir\START-JARVIS.bat  (видимое окно, не закрывать)" -ForegroundColor Yellow
Write-Host "                    $InstallDir\FIX-SERVER.bat   (автопочинка)" -ForegroundColor Yellow
Write-Host "    Папка:          $InstallDir" -ForegroundColor Gray
Write-Host "    Ярлык:          Рабочий стол → J.A.R.V.I.S." -ForegroundColor Gray
Write-Host "    Автозагрузка:   $(if ($NoAutostart) {'выключена'} else {'включена'})" -ForegroundColor Gray
Write-Host "    Логи:           $LogDir" -ForegroundColor Gray
Write-Host ''
Write-Host '    Скажите «Джарвис, который час?» — и пользуйтесь ПК голосом.' -ForegroundColor Green
Write-Host '    УМНЫЙ РЕЖИМ:   SMART-MODE.bat — локальная Ollama без ключа' -ForegroundColor Green
Write-Host '    Ключ Arena:     НЕ используется, не извлекается и не встраивается' -ForegroundColor Yellow
Write-Host '    API-ключ НЕ обязателен: оффлайн-NLU уже работает. Ollama — тоже без ключа.' -ForegroundColor Green
Write-Host '    Хотите облачную LLM? Настройки HUD -> Мозг -> вставьте СВОЙ ключ.' -ForegroundColor Gray
if (-not $ruVoice) {
    Write-Host '    ВНИМАНИЕ: русский системный голос не найден.' -ForegroundColor Yellow
    Write-Host '    Распознавание речи при этом РАБОТАЕТ (Chrome/Edge), а для озвучки откройте HUD в Edge' -ForegroundColor Gray
    Write-Host '    или прочитайте VOICE-HELP.txt в папке установки.' -ForegroundColor Gray
}
Write-Host ''
Write-Log '=== Установка завершена ===' 'OK'
if (-not $Silent) { Read-Host '  Нажмите Enter для выхода' | Out-Null }
exit $(if ($ready) { 0 } else { 2 })
