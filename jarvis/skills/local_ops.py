"""Real computer actions, implemented with the Python standard library only.

Used in two places:
  * by the server when no on-PC agent is connected (demo mode),
  * mirrored (independently, single-file) in ../jarvis_agent.py.

Everything here is best-effort: a missing utility returns a friendly message
instead of crashing the assistant.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

from .. import util

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = not (IS_WIN or IS_MAC)

APP_ALIASES: dict[str, tuple[str, str, str]] = {
    # alias: (Windows command, macOS app name, Linux binary)
    "браузер": ("msedge.exe", "Safari", "firefox"),
    "browser": ("msedge.exe", "Safari", "firefox"),
    "chrome": ("chrome.exe", "Google Chrome", "google-chrome"),
    "гугл": ("chrome.exe", "Google Chrome", "google-chrome"),
    "firefox": ("firefox.exe", "Firefox", "firefox"),
    "проводник": ("explorer.exe", "Finder", "xdg-open"),
    "файлы": ("explorer.exe", "Finder", "xdg-open"),
    "explorer": ("explorer.exe", "Finder", "xdg-open"),
    "finder": ("explorer.exe", "Finder", "xdg-open"),
    "блокнот": ("notepad.exe", "TextEdit", "gedit"),
    "notepad": ("notepad.exe", "TextEdit", "gedit"),
    "калькулятор": ("calc.exe", "Calculator", "gnome-calculator"),
    "calculator": ("calc.exe", "Calculator", "gnome-calculator"),
    "терминал": ("cmd.exe", "Terminal", "x-terminal-emulator"),
    "terminal": ("cmd.exe", "Terminal", "x-terminal-emulator"),
    "код": ("Code.exe", "Visual Studio Code", "code"),
    "vscode": ("Code.exe", "Visual Studio Code", "code"),
    "word": ("WINWORD.EXE", "Microsoft Word", "libreoffice"),
    "excel": ("EXCEL.EXE", "Microsoft Excel", "libreoffice"),
    "spotify": ("Spotify.exe", "Spotify", "spotify"),
    "музыка": ("Spotify.exe", "Spotify", "spotify"),
    "telegram": ("Telegram.exe", "Telegram", "telegram-desktop"),
    "discord": ("Discord.exe", "Discord", "discord"),
    "камера": ("microsoft.windows.camera:", "Photo Booth", "cheese"),
    "steam": ("steam.exe", "Steam", "steam"),
    "стим": ("steam.exe", "Steam", "steam"),
    "epic": ("EpicGamesLauncher.exe", "Epic Games Launcher", "epic-games-launcher"),
    "эпик": ("EpicGamesLauncher.exe", "Epic Games Launcher", "epic-games-launcher"),
    "epic games": ("EpicGamesLauncher.exe", "Epic Games Launcher", "epic-games-launcher"),
    "edge": ("msedge.exe", "Microsoft Edge", "microsoft-edge"),
    "микрософт эдж": ("msedge.exe", "Microsoft Edge", "microsoft-edge"),
    "vk": ("VK.exe", "VK", "vk"),
    "вконтакте": ("VK.exe", "VK", "vk"),
}

FOLDER_ALIASES = {
    "загрузки": "Downloads", "downloads": "Downloads", "загрузка": "Downloads",
    "документы": "Documents", "documents": "Documents", "документ": "Documents",
    "рабочий стол": "Desktop", "desktop": "Desktop", "стол": "Desktop",
    "картинки": "Pictures", "pictures": "Pictures", "изображения": "Pictures",
    "музыка": "Music", "music": "Music", "видео": "Videos", "videos": "Videos",
    "дом": "", "home": "", "домашняя папка": "",
}

SEARCH_ENGINES = {
    "google": "https://www.google.com/search?q=",
    "яндекс": "https://yandex.ru/search/?text=",
    "yandex": "https://yandex.ru/search/?text=",
    "duckduckgo": "https://duckduckgo.com/?q=",
    "youtube": "https://www.youtube.com/results?search_query=",
    "github": "https://github.com/search?q=",
    "wikipedia": "https://ru.wikipedia.org/w/index.php?search=",
}

DANGEROUS_SHELL = re.compile(
    r"(rm\s+-rf|mkfs|dd\s+if=|:(){|format\s+[a-z]:|del\s+/[sq]|shutdown|reboot|"
    r"chmod\s+-R\s+777|>\s*/dev/sd|curl[^\n]*\|\s*(ba)?sh|wget[^\n]*\|\s*(ba)?sh)",
    re.I,
)


def _opts(o: dict) -> dict:
    return {
        "sandbox_root": o.get("sandbox_root") or str(Path.home()),
        "allow_shell": bool(o.get("allow_shell")),
        "allow_power": bool(o.get("allow_power")),
        "allow_file_write": bool(o.get("allow_file_write", True)),
        "shell_timeout": float(o.get("shell_timeout", 15)),
    }


def _root(o: dict) -> Path:
    return Path(o["sandbox_root"]).expanduser().resolve()


def _ok(message: str, **data) -> dict:
    return {"ok": True, "message": message, "data": data}


def _fail(message: str, **data) -> dict:
    return {"ok": False, "message": message, "data": data}


# ---------------------------------------------------------------- system
def _cpu_percent() -> float | None:
    try:
        if IS_LINUX:
            def read():
                with open("/proc/stat") as f:
                    p = f.readline().split()[1:]
                v = list(map(float, p))
                idle = v[3] + (v[4] if len(v) > 4 else 0)
                return sum(v), idle
            a1, i1 = read()
            time.sleep(0.12)
            a2, i2 = read()
            da, di = a2 - a1, i2 - i1
            return round(100 * (1 - di / da), 1) if da else None
        if IS_MAC:
            code, out, _ = util.run(["top", "-l", "1", "-n", "0", "-stats", "cpu"], timeout=5)
            m = re.search(r"([\d.]+)%\s*user.*?([\d.]+)%\s*idle", out, re.S)
            if m:
                return round(100 - float(m.group(2)), 1)
        if IS_WIN:
            code, out, _ = util.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average"],
                timeout=8)
            try:
                return round(float(out.strip()), 1)
            except ValueError:
                pass
    except Exception:
        pass
    return None


def _memory() -> dict:
    try:
        if IS_LINUX:
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":")
                    info[k] = int(v.strip().split()[0]) * 1024
            total, avail = info.get("MemTotal", 0), info.get("MemAvailable", 0)
            return {"total": total, "used": total - avail,
                    "percent": round(100 * (1 - avail / total), 1) if total else 0}
        if IS_MAC:
            code, out, _ = util.run(["vm_stat"], timeout=5)
            pages = {k.lower(): int(v.strip(".")) for k, v in re.findall(r"^(.+?):\s+(\d+)\.", out, re.M)}
            free = pages.get("pages free", 0) + pages.get("pages inactive", 0)
            total = util.run(["sysctl", "-n", "hw.memsize"], timeout=5)[1]
            total_b = int(total or 0)
            used = max(0, total_b - free * 4096)
            return {"total": total_b, "used": used,
                    "percent": round(100 * used / total_b, 1) if total_b else 0}
        if IS_WIN:
            code, out, _ = util.run(
                ["powershell", "-NoProfile", "-Command",
                 "$o=Get-CimInstance Win32_OperatingSystem; \"$($o.TotalVisibleMemorySize*1024),$($o.FreePhysicalMemory*1024)\""],
                timeout=8)
            t, f = (out.strip().split(",") + ["0", "0"])[:2]
            total_b, free_b = int(float(t)), int(float(f))
            return {"total": total_b, "used": total_b - free_b,
                    "percent": round(100 * (1 - free_b / total_b), 1) if total_b else 0}
    except Exception:
        pass
    return {"total": 0, "used": 0, "percent": 0}


def system_status(args: dict, o: dict) -> dict:
    mem = _memory()
    cpu = _cpu_percent()
    try:
        du = shutil.disk_usage(str(_root(o)))
        disk = {"total": du.total, "used": du.used, "percent": round(100 * du.used / du.total, 1)}
    except Exception:
        disk = {"total": 0, "used": 0, "percent": 0}
    uptime = ""
    try:
        if IS_LINUX:
            with open("/proc/uptime") as f:
                secs = float(f.read().split()[0])
            uptime = f"{int(secs // 3600)} ч {int(secs % 3600 // 60)} мин"
        elif IS_MAC:
            code, out, _ = util.run(["sysctl", "-n", "kern.boottime"], timeout=5)
            m = re.search(r"sec\s*=\s*(\d+)", out)
            if m:
                secs = time.time() - int(m.group(1))
                uptime = f"{int(secs // 3600)} ч {int(secs % 3600 // 60)} мин"
    except Exception:
        pass
    battery = None
    try:
        for p in Path("/sys/class/power_supply").glob("BAT*"):
            cap = (p / "capacity").read_text().strip()
            battery = int(cap)
            break
    except Exception:
        pass
    msg = (f"Система: CPU {cpu if cpu is not None else 'н/д'}%, "
           f"ОЗУ {mem['percent']}% ({util.fmt_bytes(mem['used'])} из {util.fmt_bytes(mem['total'])}), "
           f"диск {disk['percent']}%.")
    if battery is not None:
        msg += f" Батарея {battery}%."
    if uptime:
        msg += f" Аптайм {uptime}."
    return _ok(msg, cpu=cpu, memory=mem, disk=disk, battery=battery, uptime=uptime,
               platform=util.platform_info())


def system_time(args: dict, o: dict) -> dict:
    d = dt.datetime.now().astimezone()
    return _ok(f"Сейчас {d.strftime('%H:%M')}, {util.human_date(d)}. Часовой пояс {d.tzinfo}.",
               time=d.strftime("%H:%M:%S"), date=d.strftime("%Y-%m-%d"),
               weekday=util.human_date(d).split(",")[0], timezone=str(d.tzinfo))


def system_processes(args: dict, o: dict) -> dict:
    limit = max(1, min(25, int(args.get("limit") or 8)))
    if IS_WIN:
        code, out, err = util.run(["tasklist", "/FO", "CSV", "/NH"], timeout=8)
        procs = [l.split(",")[0].strip('"') for l in out.splitlines()[:limit] if l]
    else:
        cmd = ["ps", "-Ao", "pid,comm,%cpu" if IS_MAC else "pid,comm,%cpu,%mem",
               "-r" if IS_MAC else "--sort=-%cpu"]
        code, out, err = util.run(cmd, timeout=8)
        procs = out.splitlines()[1: limit + 1]
    msg = "Самые активные процессы:\n" + "\n".join(f"• {p}" for p in procs[:limit]) if procs else "Не удалось получить список процессов."
    return _ok(msg, processes=procs)


# ---------------------------------------------------------------- apps
# Virtual Windows shell folders, URI schemes and installed-application lookup.
SPECIAL_SHELL_FOLDERS = {
    "компьютер": ("shell:MyComputerFolder", "Этот компьютер"),
    "мой компьютер": ("shell:MyComputerFolder", "Этот компьютер"),
    "этот компьютер": ("shell:MyComputerFolder", "Этот компьютер"),
    "мой пк": ("shell:MyComputerFolder", "Этот компьютер"),
    "этот пк": ("shell:MyComputerFolder", "Этот компьютер"),
    "пк": ("shell:MyComputerFolder", "Этот компьютер"),
    "computer": ("shell:MyComputerFolder", "Этот компьютер"),
    "my computer": ("shell:MyComputerFolder", "Этот компьютер"),
    "this pc": ("shell:MyComputerFolder", "Этот компьютер"),
    "pc": ("shell:MyComputerFolder", "Этот компьютер"),
    "диски": ("shell:MyComputerFolder", "Этот компьютер"),
    "drives": ("shell:MyComputerFolder", "Этот компьютер"),
    "проводник": ("shell:MyComputerFolder", "Этот компьютер"),
    "панель управления": ("shell:ControlPanelFolder", "Панель управления"),
    "control panel": ("shell:ControlPanelFolder", "Панель управления"),
    "корзина": ("shell:RecycleBinFolder", "Корзина"),
    "recycle bin": ("shell:RecycleBinFolder", "Корзина"),
    "сеть": ("shell:NetworkPlacesFolder", "Сеть"),
    "network": ("shell:NetworkPlacesFolder", "Сеть"),
}

# Friendly names for apps whose real Start-menu/AppID name differs from the
# spoken alias. Used only to search installed applications on Windows.
APP_QUERY_EXTRA = {
    "браузер": "Microsoft Edge",
    "browser": "Microsoft Edge",
    "edge": "Microsoft Edge",
    "микрософт эдж": "Microsoft Edge",
    "steam": "Steam",
    "стим": "Steam",
    "код": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "epic": "Epic Games Launcher",
    "эпик": "Epic Games Launcher",
    "epic games": "Epic Games Launcher",
}

# Last-resort literal paths for popular apps that are not on PATH and may not
# be exposed through Get-StartApps on older Windows builds.
COMMON_WIN_APP_PATHS: dict[str, tuple[str, ...]] = {
    "steam": (
        r"%ProgramFiles(x86)%\Steam\steam.exe",
        r"%ProgramFiles%\Steam\steam.exe",
        r"%LOCALAPPDATA%\Steam\steam.exe",
    ),
    "стим": (
        r"%ProgramFiles(x86)%\Steam\steam.exe",
        r"%ProgramFiles%\Steam\steam.exe",
        r"%LOCALAPPDATA%\Steam\steam.exe",
    ),
    "chrome": (
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
    ),
    "msedge": (
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe",
    ),
    "code": (
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        r"%ProgramFiles%\Microsoft VS Code\Code.exe",
    ),
    "vscode": (
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        r"%ProgramFiles%\Microsoft VS Code\Code.exe",
    ),
    "telegram": (
        r"%APPDATA%\Telegram Desktop\Telegram.exe",
        r"%LOCALAPPDATA%\Telegram Desktop\Telegram.exe",
    ),
    "discord": (
        r"%LOCALAPPDATA%\Discord\app-*\Discord.exe",
        r"%APPDATA%\Discord\Discord.exe",
    ),
    "epic": (
        r"%ProgramFiles(x86)%\Epic Games\Launcher\Portal\Binaries\Win32\EpicGamesLauncher.exe",
        r"%ProgramFiles%\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
    ),
    "эпик": (
        r"%ProgramFiles(x86)%\Epic Games\Launcher\Portal\Binaries\Win32\EpicGamesLauncher.exe",
        r"%ProgramFiles%\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
    ),
    "epic games": (
        r"%ProgramFiles(x86)%\Epic Games\Launcher\Portal\Binaries\Win32\EpicGamesLauncher.exe",
        r"%ProgramFiles%\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
    ),
}

# PowerShell asks Windows itself where the app is: Start-menu AppIDs,
# .lnk shortcuts, App Paths, uninstall DisplayIcon/InstallLocation and PATH.
# The spoken query arrives via an environment variable, so quotes/Cyrillic
# cannot break the command line. JSON is the only stdout we parse.
POWERSHELL_FIND_APP = r"""
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$q = $env:JARVIS_APP_QUERY
if (-not $q) { '{}'; exit 0 }
$escaped = [System.Management.Automation.WildcardPattern]::Escape($q)
$needle = '*' + $escaped + '*'
$global:found = $null
function Add-Candidate {
    param([string]$kind, [string]$value, [string]$display)
    if ($value -and -not $global:found) {
        $global:found = [pscustomobject]@{ kind = $kind; value = $value; display = $display }
    }
}
if (Get-Command Get-StartApps -ErrorAction SilentlyContinue) {
    $a = Get-StartApps | Where-Object { $_.Name -like $needle } | Select-Object -First 1
    if ($a) { Add-Candidate 'appid' $a.AppID $a.Name }
}
if (-not $global:found) {
    $roots = @(
        (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'),
        (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs'),
        [Environment]::GetFolderPath('Desktop')
    )
    foreach ($root in $roots) {
        if (-not (Test-Path $root)) { continue }
        $lnk = Get-ChildItem -Path $root -Recurse -Filter '*.lnk' -File -ErrorAction SilentlyContinue |
            Where-Object { $_.BaseName -like $needle } | Select-Object -First 1
        if ($lnk) { Add-Candidate 'path' $lnk.FullName $lnk.BaseName; break }
    }
}
if (-not $global:found) {
    $appPathPatterns = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\*',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\*'
    )
    foreach ($pattern in $appPathPatterns) {
        $k = Get-Item $pattern -ErrorAction SilentlyContinue |
            Where-Object { $_.PSChildName -like $needle } | Select-Object -First 1
        if ($k) {
            $v = $k.GetValue('')
            if (-not $v) { $v = $k.PSChildName }
            Add-Candidate 'path' ([string]$v) $k.PSChildName
            break
        }
    }
}
if (-not $global:found) {
    $uninstallPatterns = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    foreach ($pattern in $uninstallPatterns) {
        $item = Get-ItemProperty $pattern -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -like $needle } | Select-Object -First 1
        if ($item) {
            $icon = ([string]$item.DisplayIcon).Split(',')[0].Trim('"')
            if ($icon -and (Test-Path $icon)) {
                Add-Candidate 'path' $icon $item.DisplayName
                break
            }
            $loc = [string]$item.InstallLocation
            if ($loc -and (Test-Path $loc)) {
                $exe = Get-ChildItem -Path $loc -Filter '*.exe' -File -ErrorAction SilentlyContinue |
                    Where-Object { $_.BaseName -like $needle -or $_.Name -like $needle } |
                    Select-Object -First 1
                if ($exe) { Add-Candidate 'path' $exe.FullName $item.DisplayName; break }
            }
        }
    }
}
if (-not $global:found) {
    $cmd = Get-Command -Name $q -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($cmd) { Add-Candidate 'path' $cmd.Source $q }
}
if ($global:found) { $global:found | ConvertTo-Json -Compress } else { '{}' }
"""

_URI_OR_SHELL_RE = re.compile(
    r"^(?:[A-Za-z][\w+.-]*://|[A-Za-z][\w+.-]*:|shell:|::\{)", re.I)
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
_LAUNCH_PREFIX_RE = re.compile(
    r"^(?:приложение|программу|программа|программы|игру|файл|папку|папка)\s+", re.I)


def _strip_launch_prefix(text: str) -> str:
    return _LAUNCH_PREFIX_RE.sub("", str(text or "").strip()).strip()


def _is_uri_or_shell(value: str) -> bool:
    s = str(value or "").strip()
    if _DRIVE_PATH_RE.match(s):
        return False
    return bool(_URI_OR_SHELL_RE.match(s))


def _can_shell_open(target: str) -> bool:
    """Never hand a bare program name to cmd/start or os.startfile.

    That is exactly what produced Windows' "Не удается найти Steam" dialog.
    """
    s = str(target or "").strip()
    if _is_uri_or_shell(s):
        return True
    if _DRIVE_PATH_RE.match(s) or os.path.isabs(s):
        return True
    try:
        return Path(s).expanduser().exists()
    except Exception:
        return False


def _explorer_path() -> str:
    found = util.which("explorer.exe")
    if found:
        return str(found)
    return str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe")


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)


def _open_shell_location(location: str, label: str, o: dict) -> dict:
    """Open a virtual Explorer folder such as 'Этот компьютер'."""
    if IS_WIN:
        try:
            proc = subprocess.Popen(
                [_explorer_path(), location],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_creation_flags(),
            )
            return _ok(f"Открываю «{label}».", launched=True, kind="shell",
                       shell=location, pid=proc.pid)
        except Exception as exc:
            launched, detail = _open_native(location, o)
            return _ok(f"Открываю «{label}».", launched=launched, kind="shell",
                       shell=location, detail=detail or str(exc))
    launched, detail = _open_native(str(Path.home()), o)
    return _ok(f"Открываю домашнюю папку — аналог «{label}» на этой системе.",
               launched=launched, kind="shell", shell=location, detail=detail)


def _powershell_find_app(query: str) -> dict | None:
    """Ask Windows for an AppID/shortcut/executable matching the spoken name."""
    if not IS_WIN or not query:
        return None
    exe = util.which("powershell.exe")
    if not exe:
        exe = str(Path(os.environ.get("WINDIR", r"C:\Windows")) /
                  "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
    env = dict(os.environ)
    env["JARVIS_APP_QUERY"] = query
    try:
        p = subprocess.run(
            [str(exe), "-NoProfile", "-NonInteractive", "-Command", POWERSHELL_FIND_APP],
            env=env, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=10, creationflags=_creation_flags(),
        )
        out = (p.stdout or "").strip()
        start, end = out.find("{"), out.rfind("}")
        if start < 0 or end < start:
            return None
        data = json.loads(out[start:end + 1])
        if isinstance(data, dict) and data.get("value") and data.get("kind") in ("appid", "path"):
            return data
    except Exception:
        return None
    return None


def _common_windows_app_paths(query: str) -> list[str]:
    key = util.normalize(query)
    if key.endswith(".exe"):
        key = key[:-4]
    out: list[str] = []
    for raw in COMMON_WIN_APP_PATHS.get(key, ()):
        expanded = os.path.expandvars(raw)
        if "*" in expanded:
            import glob
            out.extend(glob.glob(expanded))
        else:
            p = Path(expanded).expanduser()
            if p.exists():
                out.append(str(p))
    return out


def _query_variants(*values: str | None) -> list[str]:
    seen: list[str] = []
    for value in values:
        if not value:
            continue
        text = _strip_launch_prefix(str(value)).strip()
        if not text:
            continue
        candidates = [text]
        if text.lower().endswith(".exe"):
            candidates.append(text[:-4])
        extra = APP_QUERY_EXTRA.get(util.normalize(text))
        if extra:
            candidates.append(extra)
        for candidate in candidates:
            candidate = candidate.strip()
            if candidate and candidate not in seen:
                seen.append(candidate)
    return seen


def _resolve_windows_app(target: str, prog: str | None = None,
                         original: str | None = None) -> dict | None:
    """Find a real app by friendly name. Never uses a guessed bare command."""
    if not IS_WIN:
        return None
    queries = _query_variants(original, target, prog)
    for query in queries:
        candidate = _powershell_find_app(query)
        if candidate:
            return candidate
    for query in queries:
        for path in _common_windows_app_paths(query):
            return {"kind": "path", "value": path, "display": Path(path).stem}
    return None


def _open_uri(value: str, o: dict) -> tuple[bool, str]:
    startfile = getattr(os, "startfile", None)
    if IS_WIN and startfile:
        try:
            startfile(value)
            return True, "os.startfile"
        except Exception as exc:
            return False, str(exc)
    return _open_native(value, o)


def _launch_windows_candidate(candidate: dict, o: dict) -> tuple[bool, str]:
    kind = str(candidate.get("kind") or "")
    value = str(candidate.get("value") or "").strip()
    if not value:
        return False, "пустой результат поиска"
    if kind == "appid":
        # Windows launches Start-menu/AppID apps through shell:AppsFolder.
        result = _open_shell_location("shell:AppsFolder\\" + value,
                                      str(candidate.get("display") or value), o)
        return bool(result.get("launched")), "shell:AppsFolder"
    if _is_uri_or_shell(value) or value.lower().endswith((".lnk", ".url")):
        return _open_uri(value, o)
    expanded = os.path.expandvars(value)
    p = Path(expanded).expanduser()
    if p.exists():
        launched, detail = _open_native(str(p), o)
        if launched:
            return True, detail
        try:
            proc = subprocess.Popen(
                [str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_creation_flags(),
            )
            return True, f"pid {proc.pid}"
        except Exception as exc:
            return False, str(exc)
    return False, f"путь не найден: {value}"


def _open_native(target: str, o: dict) -> tuple[bool, str]:
    """Open an existing path/URL/shell location. Never a bare app name."""
    try:
        if IS_WIN:
            startfile = getattr(os, "startfile", None)
            if startfile and _can_shell_open(target):
                try:
                    startfile(target)
                    return True, "os.startfile"
                except Exception:
                    pass
            if _can_shell_open(target):
                code, out, err = util.run(["cmd", "/c", "start", "", target], timeout=6)
                return code == 0, err or out or "cmd start"
            return False, "голое имя приложения не отправляется в Windows Shell"
        if IS_MAC:
            if not _can_shell_open(target):
                return False, "голое имя приложения не отправляется в Finder"
            code, out, err = util.run(["open", "-a", target], timeout=6)
            if code == 0:
                return True, "open -a"
            code, out, err = util.run(["open", target], timeout=6)
            return code == 0, err or "open"
        for binary in ("xdg-open", "gio", "kde-open"):
            if util.which(binary):
                code, out, err = util.run([binary, target], timeout=6)
                if code == 0:
                    return True, binary
        if not _can_shell_open(target):
            return False, "голое имя приложения не запускается напрямую"
        candidate = Path(target).expanduser()
        if not candidate.exists() or candidate.is_dir() or not os.access(str(candidate), os.X_OK):
            return False, "нет системного открывателя (xdg-open/gio/kde-open) для этого файла/папки"
        p = subprocess.Popen([target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, f"pid {p.pid}"
    except Exception as exc:
        return False, str(exc)


def app_open(args: dict, o: dict) -> dict:
    raw = str(args.get("target") or "").strip().strip('"').strip("'")
    target = _strip_launch_prefix(raw)
    if not target:
        return _fail("Не понял, что именно открыть.")
    low = util.normalize(target)

    # Website / URL
    if re.match(r"^(https?://|www\.)", target, re.I) or (
            re.match(r"^[\w.-]+\.[a-z]{2,}(/.*)?$", target, re.I) and " " not in target):
        url = target if target.startswith("http") else "https://" + target
        try:
            webbrowser.open(url, new=2)
        except Exception:
            pass
        return _ok(f"Открываю {url} в браузере.", url=url, kind="url")

    # Virtual shell folders: «Этот компьютер», Корзина, Панель управления...
    special = SPECIAL_SHELL_FOLDERS.get(low)
    if special:
        return _open_shell_location(special[0], special[1], o)

    # Known folder aliases
    if low in FOLDER_ALIASES:
        folder = Path.home() / FOLDER_ALIASES[low] if FOLDER_ALIASES[low] else Path.home()
        folder.mkdir(parents=True, exist_ok=True)
        launched, detail = _open_native(str(folder), o)
        return _ok(f"Открываю папку {folder}.", path=str(folder),
                   launched=launched, detail=detail, kind="folder")

    # Explicit existing path: file, folder, shortcut or executable.
    p = Path(target).expanduser()
    if p.exists():
        launched, detail = _open_native(str(p.resolve()), o)
        return _ok(f"Открываю {p.name}.", path=str(p.resolve()),
                   launched=launched, detail=detail, kind="path")

    # URI / protocol (steam://, ms-settings:, microsoft.windows.camera:, shell:...)
    if _is_uri_or_shell(target):
        launched, detail = _open_uri(target, o)
        return _ok(f"Открываю «{target}».", target=target,
                   launched=launched, detail=detail, kind="uri") if launched else _fail(
                       f"Не удалось открыть «{target}»: {detail}")

    alias = APP_ALIASES.get(low)
    prog = alias[0] if IS_WIN else alias[1] if IS_MAC else alias[2] if alias else None

    # Known alias: URI scheme, then PATH, then installed-app lookup.
    if alias and prog:
        if _is_uri_or_shell(prog):
            launched, detail = _open_uri(prog, o)
            return _ok(f"Запускаю {target} ({prog}).", program=prog,
                       launched=launched, detail=detail, kind="app") if launched else _fail(
                           f"Не удалось запустить {prog}: {detail}")
        found = util.which(prog)
        if found:
            try:
                proc = subprocess.Popen([str(found)], stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL,
                                        creationflags=_creation_flags())
                return _ok(f"Запускаю {target}.", program=prog,
                           kind="app", pid=proc.pid)
            except Exception as exc:
                return _fail(f"Не удалось запустить {prog}: {exc}")
        candidate = _resolve_windows_app(target, prog=prog, original=raw)
        if candidate:
            launched, detail = _launch_windows_candidate(candidate, o)
            return _ok(f"Запускаю «{target}» — найдено: {candidate.get('display') or candidate['value']}.",
                       program=candidate["value"], kind="app", launched=launched,
                       detail=detail, resolution=candidate) if launched else _fail(
                           f"Нашёл «{target}», но не смог запустить: {detail}")
        return _fail(f"Не смог найти «{target}» среди установленных приложений. "
                    "Проверьте имя, установите программу или укажите полный путь к .exe. "
                    "Окно с ошибкой Windows больше не вызывается.")

    # Direct executable on PATH
    found = util.which(target)
    if found:
        try:
            proc = subprocess.Popen([str(found)], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    creationflags=_creation_flags())
            return _ok(f"Запускаю {target}, процесс {proc.pid}.", kind="app", pid=proc.pid)
        except Exception as exc:
            return _fail(str(exc))

    # Arbitrary friendly name such as "Steam": search the real Windows app list.
    candidate = _resolve_windows_app(target, original=raw)
    if candidate:
        launched, detail = _launch_windows_candidate(candidate, o)
        return _ok(f"Запускаю «{target}» — найдено: {candidate.get('display') or candidate['value']}.",
                   program=candidate["value"], kind="app", launched=launched,
                   detail=detail, resolution=candidate) if launched else _fail(
                       f"Нашёл «{target}», но не смог запустить: {detail}")

    return _fail(f"Не смог найти «{target}» среди установленных приложений. "
                "Проверьте имя, установите программу или укажите полный путь к файлу/.exe. "
                "Окно с ошибкой Windows больше не вызывается.")


def computer_open(args: dict, o: dict) -> dict:
    """Open the real Windows 'This PC' virtual folder."""
    return _open_shell_location("shell:MyComputerFolder", "Этот компьютер", o)


def file_open(args: dict, o: dict) -> dict:
    """Open a file/folder with its system association, optionally by name."""
    raw = str(args.get("path") or args.get("target") or "").strip().strip('"').strip("'")
    target = _strip_launch_prefix(raw)
    if not target:
        return _fail("Не понял, какой файл или папку открыть.")
    low = util.normalize(target)

    special = SPECIAL_SHELL_FOLDERS.get(low)
    if special:
        return _open_shell_location(special[0], special[1], o)

    if low in FOLDER_ALIASES:
        folder = Path.home() / FOLDER_ALIASES[low] if FOLDER_ALIASES[low] else Path.home()
        folder.mkdir(parents=True, exist_ok=True)
        launched, detail = _open_native(str(folder), o)
        return _ok(f"Открываю папку {folder}.", path=str(folder),
                   launched=launched, detail=detail, kind="folder")

    p = Path(target).expanduser()
    if p.exists():
        launched, detail = _open_native(str(p.resolve()), o)
        return _ok(f"Открываю «{p.name}».", path=str(p.resolve()),
                   launched=launched, detail=detail, kind="file") if launched else _fail(
                       f"Нашёл «{p.name}», но системный открыватель недоступен: {detail}")

    if _is_uri_or_shell(target):
        launched, detail = _open_uri(target, o)
        return _ok(f"Открываю «{target}».", target=target,
                   launched=launched, detail=detail, kind="uri") if launched else _fail(
                       f"Не удалось открыть «{target}»: {detail}")

    # If the user named a file rather than a path, find it under the home root.
    query = p.name if ("/" in target or "\\" in target or _DRIVE_PATH_RE.match(target)) else target
    search = file_search({"query": query}, o)
    files = list((search.get("data") or {}).get("files") or [])
    if not files:
        return _fail(f"Файл «{query}» не найден. Скажите точный путь или «найди файл {query}».")
    exact = [f for f in files if Path(f).name.lower() == query.lower()]
    chosen = exact[0] if exact else files[0]
    launched, detail = _open_native(chosen, o)
    if not launched:
        return _fail(f"Нашёл «{chosen}», но системный открыватель недоступен: {detail}",
                     path=chosen, matches=files[:5])
    return _ok(f"Открываю «{Path(chosen).name}».", path=chosen,
               launched=True, detail=detail, kind="file", matches=files[:5])


def app_close(args: dict, o: dict) -> dict:
    target = str(args.get("target") or "").strip()
    if not target:
        return _fail("Укажите имя программы.")
    key = util.normalize(target)
    prog = APP_ALIASES.get(key, (target, target, target))[0 if IS_WIN else 1 if IS_MAC else 2]
    if IS_WIN:
        image = prog if prog.lower().endswith(".exe") else prog + ".exe"
        code, out, err = util.run(["taskkill", "/IM", image, "/F"], timeout=8)
    else:
        code, out, err = util.run(["pkill", "-f", prog], timeout=8) if util.which("pkill") else (127, "", "pkill missing")
    return _ok(f"Закрываю {target}." if code == 0 else f"Не нашёл запущенный процесс «{target}».",
               target=prog, code=code)


def web_search(args: dict, o: dict) -> dict:
    query = str(args.get("query") or "").strip()
    engine = str(args.get("engine") or "google").lower()
    if not query:
        return _fail("Что именно найти?")
    base = SEARCH_ENGINES.get(engine, SEARCH_ENGINES["google"])
    url = base + quote_plus(query)
    try:
        webbrowser.open(url, new=2)
    except Exception:
        pass
    return _ok(f"Ищу «{query}». Открыл результаты поиска.", url=url, query=query, engine=engine)

# ---------------------------------------------------------------- files
def _safe(root: Path, raw: str) -> Path:
    return util.safe_path(root, raw)


def file_search(args: dict, o: dict) -> dict:
    query = str(args.get("query") or "").strip().lstrip("*")
    if not query:
        return _fail("Укажите, какой файл ищем.")
    root = _root(o)
    start = Path(str(args.get("root") or root)).expanduser()
    try:
        start = _safe(root, str(start))
    except PermissionError:
        start = root
    if not start.exists():
        start = root
    needle = util.normalize(query)
    found, scanned = [], 0
    skip = {".git", "node_modules", "__pycache__", ".cache", ".venv", "venv", ".local",
            "proc", "sys", "dev", ".mozilla", ".config", "site-packages",
            "AppData", "Windows", "Program Files", "$Recycle.Bin"}
    try:
        for dirpath, dirnames, filenames in os.walk(start, followlinks=False):
            dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
            depth = str(dirpath).count(os.sep) - str(start).count(os.sep)
            if depth > 5:
                dirnames[:] = []
                continue
            for name in filenames:
                scanned += 1
                if needle.replace(" ", "") in util.normalize(name).replace(" ", ""):
                    found.append(str(Path(dirpath) / name))
                    if len(found) >= 12:
                        break
            if len(found) >= 12 or scanned > 60000:
                break
    except Exception as exc:
        return _fail(f"Поиск прерван: {exc}")
    if found:
        return _ok(f"Нашёл {len(found)} совпадений:\n" + "\n".join(f"• {util.truncate(f, 110)}" for f in found),
                   files=found, count=len(found))
    return _ok(f"По запросу «{query}» ничего не нашёл в {start}.", files=[], count=0)


def file_list(args: dict, o: dict) -> dict:
    root = _root(o)
    try:
        p = _safe(root, str(args.get("path") or root))
    except PermissionError as exc:
        return _fail(str(exc))
    if not p.exists() or not p.is_dir():
        return _fail(f"Папка {p} не найдена.")
    items = []
    try:
        for c in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))[:40]:
            items.append({"name": c.name, "dir": c.is_dir(),
                          "size": c.stat().st_size if c.is_file() else 0})
    except Exception as exc:
        return _fail(str(exc))
    view = "\n".join(f"• {'📁' if i['dir'] else '📄'} {i['name']}" + (f" ({util.fmt_bytes(i['size'])})" if i["size"] else "") for i in items)
    return _ok(f"Содержимое {p}:\n{view}" if items else f"Папка {p} пуста.", items=items, path=str(p))


def file_read(args: dict, o: dict) -> dict:
    root = _root(o)
    try:
        p = _safe(root, str(args.get("path") or ""))
    except PermissionError as exc:
        return _fail(str(exc))
    if not p.is_file():
        return _fail(f"Файл {p} не найден.")
    try:
        text = p.read_text(encoding="utf-8", errors="replace")[:12000]
    except Exception as exc:
        return _fail(f"Не удалось прочитать файл: {exc}")
    return _ok(f"Файл {p.name}:\n{util.truncate(text, 900)}", content=text, path=str(p))


def file_write(args: dict, o: dict) -> dict:
    if not o["allow_file_write"]:
        return _fail("Запись файлов отключена в настройках безопасности.")
    root = _root(o)
    try:
        p = _safe(root, str(args.get("path") or ""))
    except PermissionError as exc:
        return _fail(str(exc))
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(args.get("content") or ""), encoding="utf-8")
    except Exception as exc:
        return _fail(f"Не удалось записать файл: {exc}")
    return _ok(f"Файл {p.name} сохранён.", path=str(p))


# ---------------------------------------------------------------- clipboard & media
def clipboard_set(args: dict, o: dict) -> dict:
    text = str(args.get("text") or "")
    code, out, err = 127, "", ""
    if IS_WIN:
        # $input is unreliable with powershell -Command; read stdin explicitly.
        code, out, err = util.run(
            ["powershell", "-NoProfile", "-Command",
             "[Console]::In.ReadToEnd() | Set-Clipboard"],
            input_text=text, timeout=6)
    elif IS_MAC:
        code, out, err = util.run(["pbcopy"], input_text=text, timeout=6)
    else:
        for binary, flags in (("wl-copy", []), ("xclip", ["-selection", "clipboard"]),
                              ("xsel", ["--clipboard", "--input"])):
            if util.which(binary):
                code, out, err = util.run([binary] + flags, input_text=text, timeout=6)
                break
    ok = code == 0
    return _ok("Скопировал в буфер обмена." if ok else
               "Буфер обмена недоступен в этой среде, но текст готов в ответе.",
               text=text, available=ok)


def clipboard_get(args: dict, o: dict) -> dict:
    if IS_WIN:
        code, out, err = util.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"], timeout=6)
    elif IS_MAC:
        code, out, err = util.run(["pbpaste"], timeout=6)
    else:
        out, code = "", 127
        for binary, flags in (("wl-paste", []), ("xclip", ["-selection", "clipboard", "-o"]), ("xsel", ["--clipboard", "--output"])):
            if util.which(binary):
                code, out, err = util.run([binary] + flags, timeout=6)
                break
    return _ok(f"В буфере обмена: {util.truncate(out, 500)}" if out else "Буфер обмена пуст или недоступен.",
               text=out[:2000])


def media_volume(args: dict, o: dict) -> dict:
    raw = str(args.get("level") or "").strip().lower()
    if raw in ("mute", "выключи", "тишина", "без звука"):
        if util.which("pactl"):
            util.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"], timeout=5)
        return _ok("Переключил режим без звука.", level="mute")
    try:
        if raw.startswith(("+", "-")):
            val = int(raw)
            rel = True
        else:
            val = int(re.sub(r"[^0-9]", "", raw) or 50)
            rel = False
    except ValueError:
        return _fail("Не понял уровень громкости. Скажите, например, «громкость 40».")
    val = max(0, min(100, val))
    detail = ""
    if IS_MAC:
        code, out, err = util.run(["osascript", "-e", f"set volume output volume {val}"], timeout=6)
        detail = err
    elif IS_WIN:
        # Native volume keys via user32.keybd_event: one press = 2%.
        ps = (
            "Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; "
            "public class VK { [DllImport(\"user32.dll\")] public static extern void keybd_event(byte k, byte s, uint f, UIntPtr e); }'; "
            "$downs = 50; "
            f"$ups = {max(0, min(50, (val if not rel else 50 + val // 2) // 2))}; "
            "for($i=0;$i -lt $downs;$i++){ [VK]::keybd_event(0xAE,0,0,[UIntPtr]::Zero); [VK]::keybd_event(0xAE,0,2,[UIntPtr]::Zero) }; "
            "for($i=0;$i -lt $ups;$i++){ [VK]::keybd_event(0xAF,0,0,[UIntPtr]::Zero); [VK]::keybd_event(0xAF,0,2,[UIntPtr]::Zero) }"
        )
        code, out, err = util.run(["powershell", "-NoProfile", "-Command", ps], timeout=15)
        detail = "user32 keybd_event"
    else:
        level = f"{'+' if rel and val >= 0 else '-' if rel else ''}{abs(val)}%" if rel else f"{val}%"
        for cmd in (["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", level],
                    ["pactl", "set-sink-volume", "@DEFAULT_SINK@", level],
                    ["amixer", "-D", "pulse", "sset", "Master", level]):
            if util.which(cmd[0]):
                code, out, err = util.run(cmd, timeout=6)
                detail = cmd[0]
                break
        else:
            detail = "нет аудио-утилиты"
    return _ok(f"Громкость: {val}%." if not detail.startswith("нет") else
               "В этой среде нет аудиоустройства, команда принята.", level=val, detail=detail)


def media_control(args: dict, o: dict) -> dict:
    action = str(args.get("action") or "play").lower()
    key = {"play": "play-pause", "pause": "play-pause", "next": "next", "prev": "previous",
           "previous": "previous", "stop": "stop"}.get(action, "play-pause")
    if util.which("playerctl"):
        code, out, err = util.run(["playerctl", key if IS_LINUX else action], timeout=6)
    elif IS_MAC:
        code, out, err = util.run(["osascript", "-e", "tell application \"Music\" to playpause"], timeout=6)
    elif IS_WIN:
        mapping = {"play-pause": "{SPACE}", "next": "^{RIGHT}", "previous": "^{LEFT}"}
        code, out, err = util.run(["powershell", "-NoProfile", "-Command",
                                   f"$w=New-Object -ComObject WScript.Shell; $w.SendKeys('{mapping.get(key, chr(32))}')"], timeout=6)
    else:
        return _ok("Команда плееру отправлена (в этой среде плеер не обнаружен).", action=action)
    return _ok(f"Плеер: {action}.", action=action)


def screenshot(args: dict, o: dict) -> dict:
    folder = Path.home() / "Pictures" / "JARVIS"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"screen_{dt.datetime.now():%Y%m%d_%H%M%S}.png"
    except Exception:
        path = _root(o) / f"screen_{int(time.time())}.png"
    code, out, err = 127, "", ""
    if IS_MAC:
        code, out, err = util.run(["screencapture", "-x", str(path)], timeout=10)
    elif IS_WIN:
        ps = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
              "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
              "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height; "
              "$g=[System.Drawing.Graphics]::FromImage($bmp); "
              f"$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); $bmp.Save('{path}');")
        code, out, err = util.run(["powershell", "-NoProfile", "-Command", ps], timeout=15)
    else:
        for cmd in (["scrot", str(path)], ["gnome-screenshot", "-f", str(path)],
                    ["import", "-window", "root", str(path)]):
            if util.which(cmd[0]):
                code, out, err = util.run(cmd, timeout=10)
                break
    if code == 0 and path.exists():
        return _ok(f"Скриншот сохранён: {path}", path=str(path))
    return _ok("Сделать снимок в этой среде не удалось (нет графического экрана). "
               "На вашем ПК с запущенным агентом скриншот сохранится в Папку изображений/JARVIS.",
               path=str(path), available=False)


# ---------------------------------------------------------------- dangerous
def shell_run(args: dict, o: dict) -> dict:
    if not o["allow_shell"]:
        return _fail("Выполнение команд отключено. Включите «Разрешить команды» в настройках.")
    command = str(args.get("command") or "").strip()
    if not command or DANGEROUS_SHELL.search(command):
        return _fail("Эта команда заблокирована правилами безопасности.")
    code, out, err = util.run(command, timeout=o["shell_timeout"], shell=True)
    text = (out or err or "(пустой вывод)")[:2500]
    return _ok(f"Команда выполнена, код {code}:\n{util.truncate(text, 700)}",
               code=code, stdout=out[:4000], stderr=err[:1000])


def power(action: str, o: dict) -> dict:
    if not o["allow_power"]:
        return _fail("Управление питанием отключено в настройках безопасности.")
    if IS_WIN:
        cmd = ["shutdown", "/s" if action == "shutdown" else "/r", "/t", "5"] if action != "sleep" else [
            "powershell", "-NoProfile", "-Command",
            "Add-Type -AssemblyName System.Windows.Forms;[System.Windows.Forms.Application]::SetSuspendState('Suspend',$false,$false)"]
    elif IS_MAC:
        cmd = ["pmset", "sleepnow"] if action == "sleep" else ["sudo", "shutdown", "-h" if action == "shutdown" else "-r", "now"]
    else:
        cmd = ["systemctl", "suspend"] if action == "sleep" else ["systemctl", "poweroff" if action == "shutdown" else "reboot"]
    code, out, err = util.run(cmd, timeout=8)
    return _ok(f"Команда «{action}» отправлена системе." if code == 0 else
               f"Система отклонила команду: {err or out}", action=action, code=code)


HANDLERS = {
    "system.status": system_status, "system.time": system_time, "system.processes": system_processes,
    "app.open": app_open, "app.close": app_close, "web.search": web_search,
    "computer.open": computer_open, "file.open": file_open,
    "file.search": file_search, "file.list": file_list, "file.read": file_read, "file.write": file_write,
    "clipboard.set": clipboard_set, "clipboard.get": clipboard_get,
    "media.volume": media_volume, "media.control": media_control, "screenshot": screenshot,
    "shell.run": shell_run,
    "power.sleep": lambda a, o: power("sleep", o),
    "power.shutdown": lambda a, o: power("shutdown", o),
    "power.reboot": lambda a, o: power("reboot", o),
}


def execute(name: str, args: dict, opts: dict | None = None) -> dict:
    """Run a client-side action locally. Always returns a result dict."""
    o = _opts(opts or {})
    handler = HANDLERS.get(name)
    if not handler:
        return _fail(f"Неизвестное действие «{name}».")
    try:
        res = handler(dict(args or {}), o)
        res.setdefault("data", {})
        res.setdefault("ok", True)
        return res
    except Exception as exc:
        return _fail(f"Ошибка при выполнении «{name}»: {exc}")
