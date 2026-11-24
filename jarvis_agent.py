#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""J.A.R.V.I.S. — локальный агент управления ПК.

ОДИН ФАЙЛ, ТОЛЬКО СТАНДАРТНАЯ БИБЛИОТЕКА PYTHON 3.9+.

Запустите этот скрипт на своём компьютере, и голосовой ассистент в браузере
получит возможность выполнять реальные действия: открывать программы и сайты,
искать и читать файлы, менять громкость, делать скриншоты, копировать в буфер.

    python jarvis_agent.py --server https://ваш-адрес.e2b.app

Скачать файл можно прямо с сервера:  /download/jarvis_agent.py

Безопасность: опасные команды (shell, выключение) ЗАПРЕЩЕНЫ по умолчанию и
включаются только явными флагами --allow-shell / --allow-power. Все файловые
операции ограничены домашней папкой (или --root).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

__version__ = "1.0.0"


class _Util:
    """Мини-версия утилит сервера, чтобы агент оставался одним файлом."""

    @staticmethod
    def normalize(text: str) -> str:
        t = (text or "").lower().replace("ё", "е").replace("\u00a0", " ")
        t = re.sub(r"[^0-9a-zа-яё\+\-\*\/\%\.\,\:\s\=\_]", " ", t)
        return re.sub(r"\s+", " ", t).strip()

    @staticmethod
    def truncate(text: str, n: int = 260) -> str:
        text = str(text)
        return text if len(text) <= n else text[: n - 1] + "…"

    @staticmethod
    def human_date(d: dt.datetime) -> str:
        months = ["января", "февраля", "марта", "апреля", "мая", "июня",
                  "июля", "августа", "сентября", "октября", "ноября", "декабря"]
        week = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
        return f"{week[d.weekday()]}, {d.day} {months[d.month - 1]} {d.year} года"

    @staticmethod
    def fmt_bytes(n: float) -> str:
        for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
            if n < 1024:
                return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} ПБ"

    @staticmethod
    def which(name: str) -> str | None:
        return shutil.which(name)

    @staticmethod
    def platform_info() -> dict:
        return {"system": platform.system(), "release": platform.release(),
                "platform": platform.platform(), "machine": platform.machine(),
                "python": platform.python_version(), "hostname": platform.node()}

    @staticmethod
    def safe_path(root: Path, raw: str) -> Path:
        p = Path(raw or ".").expanduser()
        if not p.is_absolute():
            p = root / p
        p = p.resolve()
        if root not in p.parents and p != root:
            raise PermissionError("путь вне разрешённой области")
        return p

    @staticmethod
    def run(cmd, timeout: float = 8.0, shell: bool = False, cwd: str | None = None,
            input_text: str | None = None):
        try:
            p = subprocess.run(
                cmd if shell else (cmd if isinstance(cmd, list) else cmd.split()),
                shell=shell, cwd=cwd, capture_output=True, text=True, input=input_text,
                timeout=timeout, errors="replace")
            return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
        except FileNotFoundError:
            return 127, "", "program not found"
        except subprocess.TimeoutExpired:
            return 124, "", "timeout"
        except Exception as exc:
            return 1, "", str(exc)


util = _Util()


# === Действия на ПК ( тот же код, что и на сервере ) ===




IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = not (IS_WIN or IS_MAC)

APP_ALIASES: dict[str, tuple[str, str, str]] = {
    # alias: (Windows command, macOS app name, Linux binary)
    "браузер": ("msedge", "Safari", "firefox"),
    "browser": ("msedge", "Safari", "firefox"),
    "chrome": ("chrome", "Google Chrome", "google-chrome"),
    "гугл": ("chrome", "Google Chrome", "google-chrome"),
    "firefox": ("firefox", "Firefox", "firefox"),
    "проводник": ("explorer", "Finder", "xdg-open"),
    "файлы": ("explorer", "Finder", "xdg-open"),
    "explorer": ("explorer", "Finder", "xdg-open"),
    "finder": ("explorer", "Finder", "xdg-open"),
    "блокнот": ("notepad", "TextEdit", "gedit"),
    "notepad": ("notepad", "TextEdit", "gedit"),
    "калькулятор": ("calc", "Calculator", "gnome-calculator"),
    "calculator": ("calc", "Calculator", "gnome-calculator"),
    "терминал": ("cmd", "Terminal", "x-terminal-emulator"),
    "terminal": ("cmd", "Terminal", "x-terminal-emulator"),
    "код": ("code", "Visual Studio Code", "code"),
    "vscode": ("code", "Visual Studio Code", "code"),
    "word": ("winword", "Microsoft Word", "libreoffice"),
    "excel": ("excel", "Microsoft Excel", "libreoffice"),
    "spotify": ("spotify", "Spotify", "spotify"),
    "музыка": ("spotify", "Spotify", "spotify"),
    "telegram": ("telegram", "Telegram", "telegram-desktop"),
    "discord": ("discord", "Discord", "discord"),
    "камера": ("microsoft.windows.camera:", "Photo Booth", "cheese"),
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
def _open_native(target: str, o: dict) -> tuple[bool, str]:
    """Try to launch something on this OS. Returns (launched, detail)."""
    try:
        if IS_WIN:
            # os.startfile uses the real Windows shell association: works for
            # URLs, folders, documents and executables with spaces in the path.
            try:
                os.startfile(target)  # type: ignore[attr-defined]
                return True, "os.startfile"
            except AttributeError:
                pass
            except Exception:
                pass
            code, out, err = util.run(
                ["cmd", "/c", "start", "", target], timeout=6)
            return code == 0, err or "cmd start"
        if IS_MAC:
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
        # Last resort: the binary itself.
        p = subprocess.Popen([target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, f"pid {p.pid}"
    except Exception as exc:
        return False, str(exc)


def app_open(args: dict, o: dict) -> dict:
    target = str(args.get("target") or "").strip().strip('"').strip("'")
    if not target:
        return _fail("Не понял, что именно открыть.")
    low = util.normalize(target)

    # Website / URL
    if re.match(r"^(https?://|www\.)", target, re.I) or (re.match(r"^[\w.-]+\.[a-z]{2,}(/.*)?$", target, re.I) and " " not in target):
        url = target if target.startswith("http") else "https://" + target
        try:
            webbrowser.open(url, new=2)
        except Exception:
            pass
        return _ok(f"Открываю {url} в браузере.", url=url, kind="url")

    # Known folder aliases
    if low in FOLDER_ALIASES:
        folder = Path.home() / FOLDER_ALIASES[low] if FOLDER_ALIASES[low] else Path.home()
        folder.mkdir(parents=True, exist_ok=True)
        launched, detail = _open_native(str(folder), o)
        return _ok(f"Открываю папку {folder}.", path=str(folder), launched=launched, kind="folder")

    # Explicit path
    p = Path(target).expanduser()
    if p.exists():
        launched, detail = _open_native(str(p.resolve()), o)
        return _ok(f"Открываю {p.name}.", path=str(p.resolve()), launched=launched, kind="path")

    # Application aliases
    alias = APP_ALIASES.get(low)
    if alias:
        prog = alias[0] if IS_WIN else alias[1] if IS_MAC else alias[2]
        if util.which(prog):
            try:
                subprocess.Popen([prog], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return _ok(f"Запускаю {target}.", program=prog, kind="app")
            except Exception as exc:
                return _fail(f"Не удалось запустить {prog}: {exc}")
        launched, detail = _open_native(prog, o)
        return _ok(f"Запускаю {target} ({prog}).", program=prog, launched=launched,
                   note="" if launched else "Системный открыватель недоступен в этой среде", kind="app")

    # Direct executable on PATH
    if util.which(target):
        try:
            p = subprocess.Popen([target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return _ok(f"Запускаю {target}, процесс {p.pid}.", kind="app", pid=p.pid)
        except Exception as exc:
            return _fail(str(exc))

    launched, detail = _open_native(target, o)
    if launched:
        return _ok(f"Пытаюсь открыть «{target}».", kind="unknown", target=target)
    return _ok(f"«{target}» не найден в этой системе, но команда принята. "
               "Подключите локальный агент на своём ПК, чтобы открывать реальные приложения.",
               kind="missing", target=target, detail=detail)


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
# =====================================================================
#  Клиентская часть: регистрация на сервере, получение задач, отчёты
# =====================================================================

BANNER = r"""
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
        ЛОКАЛЬНЫЙ АГЕНТ УПРАВЛЕНИЯ ПК   ·   v""" + __version__ + "\n"


def stamp() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")


def log(msg: str, kind: str = "info") -> None:
    icons = {"info": "·", "ok": "✓", "warn": "!", "err": "✗", "task": "→"}
    print(f"[{stamp()}] {icons.get(kind, '·')} {msg}", flush=True)


class JarvisAgent:
    def __init__(self, server: str, token: str, name: str, allow_shell: bool,
                 allow_power: bool, allow_write: bool, root: str, timeout: float):
        self.server = server.rstrip("/")
        self.token = token
        self.name = name or platform.node() or "My PC"
        self.agent_id = ""
        self.running = True
        self.timeout = timeout
        self.opts = {
            "sandbox_root": root or str(Path.home()),
            "allow_shell": allow_shell,
            "allow_power": allow_power,
            "allow_file_write": allow_write,
            "shell_timeout": 15.0,
        }
        self.completed = 0

    def request(self, path: str, payload: dict, timeout: float | None = None) -> dict:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.server + path, data=data,
            headers={"Content-Type": "application/json", "User-Agent": f"JARVIS-Agent/{__version__}"},
            method="POST")
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")

    def register(self) -> bool:
        payload = {"name": self.name, "platform": platform.platform()[:40], "token": self.token}
        try:
            out = self.request("/api/agent/register", payload, timeout=10)
            if out.get("agent_id"):
                self.agent_id = out["agent_id"]
                log(f"Подключён к {self.server} как «{self.name}» (id {self.agent_id})", "ok")
                return True
            log(f"Сервер отклонил регистрацию: {out.get('error', 'нет ответа')}", "err")
        except Exception as exc:
            log(f"Не удалось связаться с сервером: {exc}", "warn")
        return False

    def loop(self) -> None:
        errors = 0
        while self.running:
            try:
                out = self.request("/api/agent/poll", {"agent_id": self.agent_id, "timeout": 15},
                                   timeout=self.timeout + 5)
                if not out.get("ok") and out.get("tasks") is None:
                    log("Сервер потерял сессию, переподключаюсь…", "warn")
                    if self.register():
                        errors = 0
                    continue
                errors = 0
                for task in out.get("tasks") or []:
                    self.handle(task)
            except KeyboardInterrupt:
                break
            except Exception as exc:
                errors += 1
                wait = min(30, 2 * errors)
                log(f"Связь прервана ({util.truncate(str(exc), 90)}), повтор через {wait} с", "warn")
                for _ in range(wait * 2):
                    if not self.running:
                        break
                    time.sleep(0.5)
                if errors > 5 and not self.register():
                    errors = 0

    def handle(self, task: dict) -> None:
        name = str(task.get("name") or "")
        tid = str(task.get("id") or "")
        args = task.get("args") if isinstance(task.get("args"), dict) else {}
        log(f"{name} {json.dumps(args, ensure_ascii=False)[:110]}", "task")
        try:
            res = execute(name, args, self.opts)
        except Exception as exc:
            res = {"ok": False, "message": f"Ошибка агента: {exc}", "data": {}}
        res.setdefault("agent", self.name)
        res.setdefault("platform", platform.system())
        log(util.truncate(str(res.get("message")), 150).replace("\n", " | "),
            "ok" if res.get("ok") else "warn")
        self.completed += 1
        for attempt in range(3):
            try:
                self.request("/api/agent/result",
                             {"agent_id": self.agent_id, "task_id": tid, "result": res}, timeout=10)
                return
            except Exception as exc:
                if attempt == 2:
                    log(f"Не удалось отправить результат: {exc}", "warn")
                time.sleep(1)


def main() -> int:
    p = argparse.ArgumentParser(
        description="J.A.R.V.I.S. — агент, который даёт голосовому ассистенту доступ к вашему ПК",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Пример:\n  python jarvis_agent.py --server https://xxxx-xxxx.e2b.app\n")
    p.add_argument("--server", "-s", default=os.environ.get("JARVIS_SERVER", ""),
                   help="адрес сервера с HUD (http/https)")
    p.add_argument("--token", "-t", default=os.environ.get("JARVIS_AGENT_TOKEN", "jarvis-local-agent"),
                   help="токен агента (по умолчанию jarvis-local-agent)")
    p.add_argument("--name", "-n", default="", help="имя этого компьютера в HUD")
    p.add_argument("--root", default="", help="разрешённая папка для файловых операций")
    p.add_argument("--allow-shell", action="store_true", help="РАЗРЕШИТЬ выполнение команд терминала")
    p.add_argument("--allow-power", action="store_true", help="РАЗРЕШИТЬ выключение/перезагрузку")
    p.add_argument("--no-write", action="store_true", help="запретить запись файлов")
    p.add_argument("--timeout", type=float, default=20.0, help="таймаут long-poll запроса")
    p.add_argument("--version", action="version", version=__version__)
    a = p.parse_args()

    print(BANNER, flush=True)
    server = a.server.strip()
    if not server:
        print("Введите адрес сервера из окна HUD (Настройки → Агент ПК):")
        server = input("  https://").strip()
        if server:
            server = "https://" + server
    if not server:
        print("Адрес не указан. Выход.")
        return 1
    if not server.startswith(("http://", "https://")):
        server = "https://" + server

    agent = JarvisAgent(server, a.token, a.name, a.allow_shell, a.allow_power,
                        not a.no_write, a.root, a.timeout)
    log(f"Платформа: {platform.system()} {platform.release()} · Python {platform.python_version()}")
    log(f"Разрешённая папка: {agent.opts['sandbox_root']}")
    log("Команды терминала: " + ("РАЗРЕШЕНЫ" if a.allow_shell else "запрещены")
        + " · Управление питанием: " + ("РАЗРЕШЕНО" if a.allow_power else "запрещено"))
    while not agent.register():
        log("Повторная попытка через 5 секунд… (Ctrl+C для выхода)", "warn")
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            return 1
    log("Ожидаю голосовых команд. Говорите в HUD — действия выполнятся здесь.", "ok")
    try:
        agent.loop()
    except KeyboardInterrupt:
        pass
    log(f"Агент остановлен. Выполнено действий: {agent.completed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
