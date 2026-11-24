<#
    J.A.R.V.I.S. — иконка в системном трее Windows.
    Показывает состояние ядра/агента и даёт быстрое меню управления.
    Запускается автоматически установщиком (можно отключить -NoTray).
#>

param(
    [string]$InstallDir = (Split-Path -Parent $PSCommandPath),
    [string]$HudUrl     = 'http://127.0.0.1:8080'
)

$ErrorActionPreference = 'SilentlyContinue'
$script:InstallDir = $InstallDir
$script:HudUrl     = $HudUrl.TrimEnd('/')
$script:LastState  = ''

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$icoPath = Join-Path $InstallDir 'jarvis.ico'
$script:wscript = Join-Path $env:SystemRoot 'System32\wscript.exe'
$script:bgVbs   = Join-Path $InstallDir 'start-background.vbs'
$script:stopCmd = Join-Path $InstallDir 'stop-services.ps1'

try {
    if (Test-Path $icoPath) { $script:icon = [System.Drawing.Icon]::new($icoPath) }
    else { $script:icon = [System.Drawing.SystemIcons]::Application }
} catch { $script:icon = [System.Drawing.SystemIcons]::Application }

$notify = [System.Windows.Forms.NotifyIcon]::new()
$notify.Icon = $script:icon
$notify.Text = 'J.A.R.V.I.S. — запуск…'
$notify.Visible = $true
$notify.BalloonTipTitle = 'J.A.R.V.I.S.'
$notify.BalloonTipText  = 'Система активна. Откройте приложение J.A.R.V.I.S.'
$notify.ShowBalloonTip(3000)

$menu = [System.Windows.Forms.ContextMenuStrip]::new()

function Add-Item {
    param([string]$Text, [scriptblock]$Action)
    $item = [System.Windows.Forms.ToolStripMenuItem]::new($Text)
    if ($Action) { $item.Add_Click($Action) }
    $menu.Items.Add($item) | Out-Null
}

$script:desktopExe = Join-Path $InstallDir 'JARVIS-APP.exe'
$script:desktopVbs = Join-Path $InstallDir 'JARVIS-APP.vbs'
function Open-JarvisApp {
    if (Test-Path $script:desktopExe) {
        Start-Process -FilePath $script:desktopExe
    } elseif (Test-Path $script:desktopVbs) {
        Start-Process -FilePath $script:wscript -ArgumentList ('"' + $script:desktopVbs + '"')
    } else {
        Start-Process $script:HudUrl
    }
}

Add-Item 'Открыть J.A.R.V.I.S.' { Open-JarvisApp }
Add-Item 'Перезапустить сервисы' {
    & $script:stopCmd 2>$null | Out-Null
    Start-Sleep -Milliseconds 800
    Start-Process -FilePath $script:wscript -ArgumentList ('"' + $script:bgVbs + '"') -WindowStyle Hidden
    Start-Sleep -Seconds 2
    Open-JarvisApp
}
Add-Item 'Остановить сервисы' { & $script:stopCmd 2>$null | Out-Null }
Add-Item 'Открыть логи'       { Start-Process (Join-Path $InstallDir 'logs') }
$menu.Items.Add([System.Windows.Forms.ToolStripSeparator]::new()) | Out-Null
Add-Item 'О состоянии' {
    try {
        $s = Invoke-RestMethod -Uri "$($script:HudUrl)/api/status" -TimeoutSec 3
        [System.Windows.Forms.MessageBox]::Show(
            "Мозг: $($s.brain)`nАгент ПК: $($s.agent.mode)`nДействий: $($s.actions)`nВерсия: $($s.version)",
            'J.A.R.V.I.S.', 'OK', 'Information') | Out-Null
    } catch {
        [System.Windows.Forms.MessageBox]::Show('Ядро не отвечает.', 'J.A.R.V.I.S.', 'OK', 'Warning') | Out-Null
    }
}
$menu.Items.Add([System.Windows.Forms.ToolStripSeparator]::new()) | Out-Null
Add-Item 'Выход из трея' {
    $timer.Stop()
    $notify.Visible = $false
    $notify.Dispose()
    [System.Windows.Forms.Application]::Exit()
}

$notify.ContextMenuStrip = $menu
$notify.Add_DoubleClick({ Open-JarvisApp })

$timer = [System.Windows.Forms.Timer]::new()
$timer.Interval = 10000
$timer.Add_Tick({
    $state = 'offline'
    try {
        $s = Invoke-RestMethod -Uri "$($script:HudUrl)/api/status" -TimeoutSec 3
        $state = if ($s.agent.connected) { 'pc' } else { 'demo' }
    } catch { }
    if ($state -ne $script:LastState) {
        $script:LastState = $state
        switch ($state) {
            'pc'      { $notify.Text = 'J.A.R.V.I.S. — ваш ПК подключён'; $notify.BalloonTipText = 'Агент ПК подключён. Готов к командам.' }
            'demo'    { $notify.Text = 'J.A.R.V.I.S. — демо-режим';      $notify.BalloonTipText = 'Работаю в демо-режиме.' }
            default   { $notify.Text = 'J.A.R.V.I.S. — ядро недоступно'; $notify.BalloonTipText = 'Сервер не отвечает. Используйте «Перезапустить сервисы».' }
        }
        $notify.ShowBalloonTip(2500)
    }
})
$timer.Start()

try {
    [System.Windows.Forms.Application]::Run()
} finally {
    $timer.Stop()
    $notify.Visible = $false
    $notify.Dispose()
}
