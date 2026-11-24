"""Small helpers shared across the assistant."""

from __future__ import annotations

import ast
import datetime as dt
import math
import operator
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}
FUNCTIONS = {
    "abs": abs, "round": round, "min": min, "max": max, "sqrt": math.sqrt,
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "log": math.log,
    "log10": math.log10, "floor": math.floor, "ceil": math.ceil,
    "pi": math.pi, "e": math.e,
}
CONSTANTS = {"пи": math.pi, "pi": math.pi, "e": math.e}


def now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def iso(d: dt.datetime | None = None) -> str:
    return (d or now()).isoformat(timespec="seconds")


def human_time(d: dt.datetime | None = None) -> str:
    d = d or now()
    return d.strftime("%H:%M")


def human_date(d: dt.datetime | None = None) -> str:
    d = d or now()
    months = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    week = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    return f"{week[d.weekday()]}, {d.day} {months[d.month - 1]} {d.year} года"


def normalize(text: str) -> str:
    """Lowercase, strip punctuation/diacritics-ish, collapse whitespace.

    A comma between digits is kept as a decimal point; all other commas are
    discarded so 'Привет, Ёжик!' becomes 'привет ежик'.
    """
    t = (text or "").lower().replace("ё", "е").replace("\u00a0", " ")
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)
    t = re.sub(r"[^0-9a-zа-яё\+\-\*\/\%\.\:\s\=\_]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def truncate(text: str, n: int = 260) -> str:
    text = str(text)
    return text if len(text) <= n else text[: n - 1] + "…"


def run(cmd: list[str] | str, timeout: float = 8.0, shell: bool = False,
        cwd: str | None = None, input_text: str | None = None) -> tuple[int, str, str]:
    """Run a command safely; never raises on missing binaries or timeouts."""
    try:
        p = subprocess.run(
            cmd if shell else (cmd if isinstance(cmd, list) else cmd.split()),
            shell=shell, cwd=cwd, capture_output=True, text=True, input=input_text,
            timeout=timeout, errors="replace",
        )
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", "program not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as exc:  # pragma: no cover
        return 1, "", str(exc)


def which(name: str) -> str | None:
    return shutil.which(name)


def os_name() -> str:
    s = platform.system().lower()
    return {"darwin": "macos", "windows": "windows"}.get(s, s or "unknown")


def platform_info() -> dict:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "hostname": platform.node(),
        "os": os_name(),
    }


def safe_eval(expr: str) -> float | int:
    """Evaluate arithmetic without eval(). Only numbers and whitelisted funcs."""
    expr = (expr or "").strip()
    expr = expr.replace(",", ".").replace(" ", "").replace("×", "*").replace("÷", "/")
    expr = expr.replace("^", "**").replace(":", "/")
    for word, value in CONSTANTS.items():
        expr = re.sub(rf"(?<![a-zа-я]){word}(?![a-zа-я])", str(value), expr, flags=re.I)
    tree = ast.parse(expr, mode="eval")

    def _walk(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return _walk(node.body)
        if isinstance(node, (ast.Constant,)) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
            return OPERATORS[type(node.op)](_walk(node.left), _walk(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in OPERATORS:
            return OPERATORS[type(node.op)](_walk(node.operand))
        if isinstance(node, ast.Name) and node.id in FUNCTIONS and not callable(FUNCTIONS[node.id]):
            return FUNCTIONS[node.id]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = FUNCTIONS.get(node.func.id.lower())
            if callable(fn):
                return fn(*[_walk(a) for a in node.args])
        raise ValueError("unsupported expression")
    return _walk(tree)


def parse_duration(text: str) -> int | None:
    """Return seconds from 'через 5 минут', 'in 30 seconds', 'через полтора часа'."""
    t = normalize(text or "")
    if not t:
        return None
    words = {"полтора": 1.5, "полчаса": 0.5, "час": 1, "часа": 1, "часов": 1,
             "минуту": 1, "минуты": 1, "минут": 1, "мин": 1, "секунд": 1, "секунду": 1, "сек": 1,
             "hour": 1, "hours": 1, "minute": 1, "minutes": 1, "second": 1, "seconds": 1,
             "h": 1, "m": 1, "s": 1}
    m = re.search(r"(\d+(?:[\.,]\d+)?)", t)
    num = float(m.group(1).replace(",", ".")) if m else None
    if num is None:
        for w, v in words.items():
            if re.search(rf"\b{w}\b", t):
                num = v
                break
    if num is None:
        return None
    if re.search(r"\b(сек|секунд\w*|second|seconds|sec|secs|s)\b", t):
        mult = 1
    elif re.search(r"\b(мин|минут\w*|minute|minutes|min|mins|m|полчаса)\b", t):
        mult = 60
    elif re.search(r"\b(час|часа|часов|hour|hours|hrs|hr|h|полтора)\b", t):
        mult = 3600
    else:
        mult = 60  # bare numbers default to minutes
    return max(1, int(num * mult))


def safe_path(root: Path, raw: str) -> Path:
    """Resolve a user path and make sure it stays inside the sandbox root."""
    p = Path(raw or ".").expanduser()
    if not p.is_absolute():
        p = root / p
    p = p.resolve()
    if root not in p.parents and p != root:
        raise PermissionError("путь вне разрешённой области")
    return p


def fmt_bytes(n: float) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} ПБ"
