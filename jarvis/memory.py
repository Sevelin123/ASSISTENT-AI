"""Long-term memory: dialogue, notes, tasks, facts, reminders, event log.

Everything lives in a single SQLite file inside .jarvis_data/ (git-ignored).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .config import DATA_DIR
from .util import iso


class Memory:
    def __init__(self, path: Path | None = None):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.path = Path(path) if path else DATA_DIR / "jarvis.db"
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL, text TEXT NOT NULL, meta TEXT, ts TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL, ts TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL, due TEXT, done INTEGER DEFAULT 0, ts TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS facts (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL, ts TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL, fire_at REAL NOT NULL, fired INTEGER DEFAULT 0,
                    ts TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL, text TEXT NOT NULL, ts TEXT NOT NULL
                );
                """
            )
            self._db.commit()

    # ---------------- dialogue ----------------
    def add_message(self, role: str, text: str, meta: dict | None = None) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO messages(role,text,meta,ts) VALUES(?,?,?,?)",
                (role, text, json.dumps(meta or {}, ensure_ascii=False), iso()),
            )
            self._db.commit()
            return cur.lastrowid

    def history(self, limit: int = 30) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {"id": r["id"], "role": r["role"], "text": r["text"],
             "meta": json.loads(r["meta"] or "{}"), "ts": r["ts"]}
            for r in reversed(rows)
        ]

    def clear_history(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM messages")
            self._db.commit()

    # ---------------- notes ----------------
    def add_note(self, text: str) -> int:
        with self._lock:
            cur = self._db.execute("INSERT INTO notes(text,ts) VALUES(?,?)", (text, iso()))
            self._db.commit()
            return cur.lastrowid

    def notes(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM notes ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def delete_note(self, note_id: int) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM notes WHERE id=?", (note_id,))
            self._db.commit()
            return cur.rowcount > 0

    # ---------------- tasks ----------------
    def add_task(self, text: str, due: str = "") -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO tasks(text,due,done,ts) VALUES(?,?,0,?)", (text, due, iso())
            )
            self._db.commit()
            return cur.lastrowid

    def tasks(self, only_open: bool = True, limit: int = 30) -> list[dict]:
        with self._lock:
            sql = "SELECT * FROM tasks" + (" WHERE done=0" if only_open else "") + " ORDER BY id DESC LIMIT ?"
            rows = self._db.execute(sql, (limit,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def done_task(self, needle: str | int) -> tuple[bool, str]:
        with self._lock:
            if isinstance(needle, int) or (isinstance(needle, str) and needle.isdigit()):
                row = self._db.execute("SELECT * FROM tasks WHERE id=?", (int(needle),)).fetchone()
            else:
                row = self._db.execute(
                    "SELECT * FROM tasks WHERE done=0 AND lower(text) LIKE ? ORDER BY id DESC LIMIT 1",
                    (f"%{str(needle).lower()}%",),
                ).fetchone()
            if not row:
                return False, "Задача не найдена."
            self._db.execute("UPDATE tasks SET done=1 WHERE id=?", (row["id"],))
            self._db.commit()
            return True, str(row["text"])

    # ---------------- facts ----------------
    def remember(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO facts(key,value,ts) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, ts=excluded.ts",
                (key.strip().lower(), value.strip(), iso()),
            )
            self._db.commit()

    def recall(self, key: str = "") -> dict[str, str]:
        with self._lock:
            if key:
                rows = self._db.execute(
                    "SELECT key,value FROM facts WHERE key LIKE ?", (f"%{key.lower()}%",)
                ).fetchall()
            else:
                rows = self._db.execute("SELECT key,value FROM facts ORDER BY key").fetchall()
        return {r["key"]: r["value"] for r in rows}

    # ---------------- reminders ----------------
    def add_reminder(self, text: str, fire_at: float) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO reminders(text,fire_at,ts) VALUES(?,?,?)", (text, fire_at, iso())
            )
            self._db.commit()
            return cur.lastrowid

    def reminders(self, include_fired: bool = False) -> list[dict]:
        with self._lock:
            sql = "SELECT * FROM reminders" + ("" if include_fired else " WHERE fired=0") + " ORDER BY fire_at"
            return [dict(r) for r in self._db.execute(sql).fetchall()]

    def due_reminders(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM reminders WHERE fired=0 AND fire_at<=?", (time.time(),)
            ).fetchall()
            for r in rows:
                self._db.execute("UPDATE reminders SET fired=1 WHERE id=?", (r["id"],))
            self._db.commit()
        return [dict(r) for r in rows]

    def clear_reminders(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM reminders")
            self._db.commit()

    # ---------------- events ----------------
    def log(self, kind: str, text: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO events(kind,text,ts) VALUES(?,?,?)", (kind, text, iso())
            )
            self._db.commit()

    def events(self, limit: int = 40) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def stats(self) -> dict[str, int]:
        with self._lock:
            out = {}
            for table in ("messages", "notes", "tasks", "facts", "reminders"):
                q = "SELECT COUNT(*) FROM " + table + (" WHERE done=0" if table == "tasks" else "")
                if table == "reminders":
                    q += " WHERE fired=0"
                out[table] = self._db.execute(q).fetchone()[0]
            return out
