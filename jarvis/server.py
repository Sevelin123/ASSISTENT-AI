"""HTTP server: static HUD, REST API, SSE stream and the PC-agent protocol."""

from __future__ import annotations

import json
import mimetypes
import queue
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import util
from .brain import Brain
from .config import BASE_DIR, DATA_DIR, WEB_DIR, ConfigStore
from .hub import AgentHub
from .memory import Memory
from .router import Router
from .skills import base, local_ops

AGENT_FILE = BASE_DIR / "jarvis_agent.py"

MIME = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
    ".py": "text/x-python; charset=utf-8", ".md": "text/markdown; charset=utf-8",
    ".bat": "application/octet-stream", ".cmd": "application/octet-stream",
    ".ps1": "application/octet-stream", ".vbs": "application/octet-stream",
    ".zip": "application/zip",
}


BUNDLE_SKIP_DIRS = {
    ".git", ".jarvis_data", "__pycache__", "node_modules", ".venv", "venv",
    "build", "dist", ".pytest_cache", ".mypy_cache", ".cache", "Unselected files",
}
BUNDLE_SKIP_FILES = {
    "jarvis.config.json", ".env", ".env.local", ".DS_Store", "Thumbs.db",
    "JARVIS-Windows.zip",
}

WINDOWS_README = """J.A.R.V.I.S. — автоматическая установка на Windows
=====================================================

0. Если облачный предпросмотр недоступен (502 BAD GATEWAY / SANDBOX NOT FOUND) —
   это НЕ ошибка установщика. Откройте START-HERE.html из этого архива:
   инструкция работает без сервера и без временных ссылок *.e2b.app.
1. РАСПАКУЙТЕ этот архив в любую папку (Правый клик -> Извлечь все...).
2. ДВОЙНОЙ КЛИК по INSTALL_WINDOWS.bat
3. Всё остальное установщик сделает сам:
   - проверит/установит Python 3.9+
   - скопирует приложение в %LOCALAPPDATA%\\JARVIS
   - запустит сервер HUD и агент управления ПК
   - добавит автозагрузку, ярлык на рабочий стол и иконку в трей
   - откроет http://127.0.0.1:8080 в браузере
4. Разрешите микрофон и скажите: «Джарвис, который час?»

Для распознавания речи нужен Chrome или Edge.
Полная документация: windows/README.md и README.md

Удаление: UNINSTALL_WINDOWS.bat (данные сохранятся)
          UNINSTALL_WINDOWS.bat -Purge (удалит всё)

Параметры: INSTALL_WINDOWS.bat -Port 9000 / -Lan / -NoAutostart / -NoTray
"""


def build_windows_bundle() -> Path:
    """Create a ready-to-unzip Windows installer bundle, cached on disk."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "JARVIS-Windows.zip"
    files = []
    for p in BASE_DIR.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(BASE_DIR)
        if any(part in BUNDLE_SKIP_DIRS for part in rel.parts):
            continue
        if p.name in BUNDLE_SKIP_FILES or p.suffix in (".db", ".pyc", ".log"):
            continue
        files.append((p, rel))
    newest = max([p.stat().st_mtime for p, _ in files] + [0])
    if out.exists() and out.stat().st_mtime >= newest and out.stat().st_size > 1000:
        return out
    tmp = out.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("JARVIS-Windows/README-WINDOWS.txt", WINDOWS_README)
        for p, rel in sorted(files, key=lambda x: str(x[1])):
            z.write(p, "JARVIS-Windows/" + rel.as_posix())
    tmp.replace(out)
    return out


class JarvisApp:
    """Holds all state; handlers reach it through Server.javavis_app."""

    def __init__(self, config: ConfigStore | None = None):
        self.config = config or ConfigStore()
        self.memory = Memory()
        self.hub = AgentHub(token=self.config.get().agent_token)
        self.brain = Brain(self.config, self.memory)
        self.router = Router(self.config, self.memory, self.hub, self.brain)
        self.started = time.time()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start_workers(self) -> None:
        def reminders():
            while not self._stop.wait(2.0):
                try:
                    for r in self.memory.due_reminders():
                        msg = f"Напоминание: {r['text']}"
                        self.memory.add_message("assistant", msg, {"kind": "reminder"})
                        self.hub.events.publish("speak", {"text": msg, "priority": True})
                        self.memory.log("reminder", msg)
                except Exception as exc:
                    self.memory.log("error", f"reminder worker: {exc}")

        t = threading.Thread(target=reminders, name="jarvis-reminders", daemon=True)
        t.start()
        self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "JARVIS/1.0"
    app: JarvisApp

    # ------------------------------------------------------------ low level
    def log_message(self, fmt: str, *args) -> None:
        # Compact access log — SSE and polling would otherwise flood stdout.
        msg = fmt % args
        if any(x in msg for x in ("/api/agent/poll", "/api/events", "/api/status")):
            return
        print(f"[{util.human_time()}] {self.address_string()} {msg}", flush=True)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Jarvis-Token")
        self.send_header("Cache-Control", "no-store")

    def _write(self, body: bytes) -> None:
        """Client may hang up during long polling / SSE — that is not an error.

        For HEAD requests we send the exact GET headers but no body.
        """
        if getattr(self, "_head_only", False):
            return
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.close_connection = True

    def _json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self._write(body)

    def _text(self, text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self._write(body)

    def _file(self, path: Path, download_name: str | None = None) -> None:
        if not path.is_file():
            self._text("404 — файл не найден", 404)
            return
        data = path.read_bytes()
        self.send_response(200)
        ctype = MIME.get(path.suffix.lower()) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self._cors()
        self.end_headers()
        self._write(data)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            d = json.loads(raw.decode("utf-8") or "{}")
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802
        """Preview proxies and uptime checkers probe with HEAD, not GET."""
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False

    # ------------------------------------------------------------ GET
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        app = self.app

        if path in ("/", "/index.html"):
            return self._file(WEB_DIR / "index.html")
        if path in ("/install", "/install.html"):
            return self._file(WEB_DIR / "install.html")
        if path in ("/start", "/start-here", "/offline", "/START-HERE.html"):
            return self._file(BASE_DIR / "START-HERE.html")
        if path in ("/styles.css", "/app.js", "/favicon.svg", "/manifest.json"):
            return self._file(WEB_DIR / path.lstrip("/"))
        if path in ("/jarvis_agent.py", "/download/jarvis_agent.py"):
            return self._file(AGENT_FILE, "jarvis_agent.py")
        if path in ("/windows/README.md", "/windows/readme.md"):
            return self._file(BASE_DIR / "windows" / "README.md")
        if path == "/README.md":
            return self._file(BASE_DIR / "README.md")
        # ---- Windows installer ----
        if path in ("/INSTALL_WINDOWS.bat", "/download/INSTALL_WINDOWS.bat", "/download/install_windows.bat"):
            return self._file(BASE_DIR / "INSTALL_WINDOWS.bat", "INSTALL_WINDOWS.bat")
        if path in ("/UNINSTALL_WINDOWS.bat", "/download/UNINSTALL_WINDOWS.bat"):
            return self._file(BASE_DIR / "UNINSTALL_WINDOWS.bat", "UNINSTALL_WINDOWS.bat")
        if path.startswith("/download/windows/"):
            name = path.rsplit("/", 1)[-1]
            if name in {"setup.ps1", "tray.ps1", "README.md"}:
                return self._file(BASE_DIR / "windows" / name, name)
        if path in ("/download/JARVIS-Windows.zip", "/download/windows-bundle", "/download/windows.zip"):
            try:
                return self._file(build_windows_bundle(), "JARVIS-Windows.zip")
            except Exception as exc:
                return self._json({"error": f"не удалось собрать архив: {exc}"}, 500)

        if path == "/api/health":
            return self._json({"ok": True, "uptime": round(time.time() - app.started, 1),
                               "version": "1.0.0"})
        if path == "/api/status":
            return self._json(app.router.status())
        if path == "/api/config":
            return self._json(app.config.get().public())
        if path == "/api/history":
            from urllib.parse import parse_qs, urlparse
            limit = int(parse_qs(urlparse(self.path).query).get("limit", ["50"])[0])
            return self._json({"history": app.memory.history(limit=min(200, max(1, limit)))})
        if path == "/api/catalogue":
            return self._json({"catalogue": [{"title": t, "text": d} for t, d in base.CATALOGUE],
                               "actions": [{"name": a.name, "description": a.description,
                                            "args": a.args, "target": a.target, "danger": a.danger}
                                           for a in base.ACTIONS.values()]})
        if path == "/api/reminders":
            return self._json({"reminders": app.memory.reminders()})
        if path == "/api/telemetry":
            # Prefer telemetry from the real PC when the agent is connected.
            if app.hub.status().get("connected"):
                res = app.hub.dispatch("system.status", {}, wait=3.0)
                if res and isinstance(res.get("data"), dict):
                    return self._json({**res["data"], "target": "pc"})
            cfg = app.config.get()
            res = local_ops.execute("system.status", {}, {
                "sandbox_root": str(cfg.root), "allow_shell": False,
                "allow_power": False, "shell_timeout": 5,
            })
            return self._json({**res.get("data", {}), "target": "server"})
        if path == "/api/events":
            return self._sse()
        if path == "/api/agent/status":
            return self._json(app.hub.status())
        if path == "/api/agent/poll":
            # Convenience long-poll via GET for simple firewalls.
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            tasks = app.hub.poll(q.get("agent_id", [""])[0], timeout=15) if q.get("agent_id") else []
            return self._json({"tasks": tasks})
        if path.startswith("/api/"):
            return self._json({"error": "unknown endpoint"}, 404)
        return self._text("404", 404)

    # ------------------------------------------------------------ POST
    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        app = self.app
        body = self._body()

        if path == "/api/chat":
            text = str(body.get("text") or "")
            if not text:
                return self._json({"error": "пустой текст"}, 400)
            if len(text) > 4000:
                text = text[:4000]
            try:
                out = app.router.process(text, source=str(body.get("source") or "hud"))
                return self._json(out)
            except Exception as exc:
                app.memory.log("error", f"chat: {exc}")
                return self._json({"reply": f"Внутренняя ошибка: {exc}", "actions": [], "mode": "error"}, 500)

        if path == "/api/config":
            cfg = app.config.update(body)
            app.hub.token = cfg.agent_token
            return self._json({"config": cfg.public()})

        if path in ("/api/history/clear", "/api/history"):
            app.memory.clear_history()
            return self._json({"ok": True})

        if path == "/api/agent/register":
            aid, err = app.hub.register(str(body.get("name") or "My PC"),
                                        str(body.get("platform") or "unknown"),
                                        str(body.get("token") or ""))
            if not aid:
                return self._json({"error": err}, 403)
            return self._json({"agent_id": aid, "ok": True, "poll": "/api/agent/poll",
                               "interval": 1.0, "server": "JARVIS/1.0"})

        if path == "/api/agent/poll":
            aid = str(body.get("agent_id") or "")
            tasks = app.hub.poll(aid, timeout=float(body.get("timeout") or 15))
            return self._json({"tasks": tasks, "ok": True})

        if path == "/api/agent/heartbeat":
            ok = app.hub.heartbeat(str(body.get("agent_id") or ""))
            return self._json({"ok": ok}, 200 if ok else 404)

        if path == "/api/agent/result":
            ok = app.hub.submit_result(str(body.get("agent_id") or ""),
                                       str(body.get("task_id") or ""),
                                       body.get("result") if isinstance(body.get("result"), dict) else {})
            return self._json({"ok": ok}, 200 if ok else 404)

        if path == "/api/local/test":
            # Lets a curious user check what a PC action would do on the server.
            name, args = str(body.get("name") or ""), body.get("args") or {}
            if name not in local_ops.HANDLERS:
                return self._json({"error": "unknown action"}, 400)
            return self._json(local_ops.execute(name, args, {
                "sandbox_root": str(app.config.get().root),
                "allow_shell": False, "allow_power": False,
                "allow_file_write": False, "shell_timeout": 5,
            }))

        return self._json({"error": "unknown endpoint"}, 404)

    def do_DELETE(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/history":
            self.app.memory.clear_history()
            return self._json({"ok": True})
        return self._json({"error": "unknown endpoint"}, 404)

    # ------------------------------------------------------------ SSE
    def _sse(self) -> None:
        # A HEAD probe must never open a long-lived event stream.
        if getattr(self, "_head_only", False):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self._cors()
            self.end_headers()
            self.close_connection = True
            return
        q = self.app.hub.events.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self._cors()
        self.end_headers()
        deadline = time.time() + 55
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while time.time() < deadline and not self.app._stop.is_set():
                try:
                    ev = q.get(timeout=8)
                    payload = json.dumps(ev, ensure_ascii=False, default=str)
                    self.wfile.write(f"event: {ev.get('kind', 'message')}\ndata: {payload}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.app.hub.events.unsubscribe(q)
            self.close_connection = True


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, app: JarvisApp):
        super().__init__(addr, Handler)
        self.jarvis_app = app
        Handler.app = app


def serve(host: str | None = None, port: int | None = None, app: JarvisApp | None = None) -> Server:
    app = app or JarvisApp()
    cfg = app.config.get()
    h, p = host or cfg.host, int(port or cfg.port)
    server = Server((h, p), app)
    app.start_workers()
    print(f"\n  J.A.R.V.I.S. online  →  http://0.0.0.0:{p}", flush=True)
    print(f"  HUD: http://localhost:{p}   |   Brain: {app.brain.mode}   |   PC agent: /download/jarvis_agent.py",
          flush=True)
    print("  Windows installer: /download/JARVIS-Windows.zip  (or /download/INSTALL_WINDOWS.bat)\n",
          flush=True)
    return server
