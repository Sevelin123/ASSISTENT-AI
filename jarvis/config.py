"""Runtime configuration for J.A.R.V.I.S.

Priority: environment variables > ./jarvis.config.json > defaults.
The JSON file is created by the Settings panel of the HUD and is git-ignored,
so API keys never end up in the repository.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from shutil import which

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
DATA_DIR = BASE_DIR / ".jarvis_data"
CONFIG_FILE = BASE_DIR / "jarvis.config.json"


@dataclass
class Config:
    # --- server ---
    host: str = "0.0.0.0"
    port: int = 8080

    # --- brain ---
    # Works with OpenAI, Groq, OpenRouter, Together, LM Studio, Ollama, vLLM...
    # Ollama example:  JARVIS_BASE_URL=http://localhost:11434/v1  JARVIS_MODEL=llama3.1
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout: float = 25.0
    llm_enabled: bool = True  # auto-disabled when no key and no local endpoint
    auto_local_llm: bool = True  # detect and use a local Ollama model without any API key

    # --- persona & voice ---
    user_name: str = ""
    persona: str = "jarvis"          # jarvis | neutral | concise
    lang: str = "ru-RU"              # ru-RU | en-US
    wake_word: str = "джарвис"
    speak_replies: bool = True
    listen_mode: str = "push"        # push | wake | continuous
    voice_rate: float = 1.0
    voice_pitch: float = 1.0

    # --- security ---
    allow_shell: bool = False        # arbitrary shell commands on the PC
    allow_power: bool = False        # shutdown / reboot / sleep
    allow_file_write: bool = True
    require_confirm: bool = True     # dangerous actions need "подтверждаю"
    shell_timeout: float = 15.0
    sandbox_root: str = ""           # empty -> user's home directory

    # --- agent ---
    agent_token: str = "jarvis-local-agent"
    agent_wait_timeout: float = 6.0  # seconds to wait for the on-PC agent
    demo_fallback: bool = True       # run client actions on the server if no agent

    extra: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    @property
    def root(self) -> Path:
        """Filesystem sandbox root for file operations."""
        return Path(self.sandbox_root).expanduser().resolve() if self.sandbox_root else Path.home().resolve()

    @property
    def has_llm_key(self) -> bool:
        return bool(self.llm_api_key.strip())

    @property
    def local_llm(self) -> bool:
        url = self.llm_base_url.lower()
        return any(h in url for h in ("localhost", "127.0.0.1", "0.0.0.0", "::1"))

    @property
    def brain_available(self) -> bool:
        return self.llm_enabled and (self.has_llm_key or self.local_llm)

    def public(self) -> dict:
        """Config safe to send to the browser (never includes the API key)."""
        d = {k: v for k, v in asdict(self).items() if k not in ("llm_api_key", "agent_token", "extra")}
        d["has_llm_key"] = self.has_llm_key
        d["brain_mode"] = "llm" if self.brain_available else "offline"
        d["version"] = "1.0.0"
        return d


def _env(name: str, default: str = "") -> str:
    return os.environ.get("JARVIS_" + name, os.environ.get(name, default))


def load_config() -> Config:
    cfg = Config()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    # Environment variables (also accept OPENAI_API_KEY / OPENAI_BASE_URL).
    env_map = {
        "host": ("JARVIS_HOST", "HOST"),
        "port": ("JARVIS_PORT", "PORT"),
        "llm_base_url": ("JARVIS_BASE_URL", "OPENAI_BASE_URL"),
        "llm_api_key": ("JARVIS_API_KEY", "OPENAI_API_KEY"),
        "llm_model": ("JARVIS_MODEL", "OPENAI_MODEL"),
        "agent_token": ("JARVIS_AGENT_TOKEN", ""),
        "wake_word": ("JARVIS_WAKE_WORD", ""),
        "user_name": ("JARVIS_USER_NAME", ""),
        "sandbox_root": ("JARVIS_SANDBOX_ROOT", ""),
    }
    bool_map = {
        "allow_shell": "JARVIS_ALLOW_SHELL",
        "allow_power": "JARVIS_ALLOW_POWER",
        "allow_file_write": "JARVIS_ALLOW_FILE_WRITE",
        "require_confirm": "JARVIS_REQUIRE_CONFIRM",
        "demo_fallback": "JARVIS_DEMO_FALLBACK",
        "llm_enabled": "JARVIS_LLM_ENABLED",
        "auto_local_llm": "JARVIS_AUTO_LOCAL_LLM",
    }

    for key, value in data.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    for key, names in env_map.items():
        for n in names:
            if n and n in os.environ and os.environ[n]:
                val = os.environ[n]
                if key == "port":
                    try:
                        val = int(val)
                    except ValueError:
                        continue
                setattr(cfg, key, val)
                break
    for key, name in bool_map.items():
        if name in os.environ:
            setattr(cfg, key, os.environ[name].strip().lower() in ("1", "true", "yes", "on"))

    return cfg


class ConfigStore:
    """Thread-safe mutable config shared by the HTTP handlers."""

    def __init__(self, cfg: Config | None = None):
        self._lock = threading.RLock()
        self.cfg = cfg or load_config()
        if self.cfg.llm_enabled and self.cfg.local_llm:
            self.smart_status = "ollama:" + self.cfg.llm_model
        elif self.cfg.has_llm_key:
            self.smart_status = "cloud"
        else:
            self.smart_status = "offline"

    @staticmethod
    def _ollama_models(timeout: float = 0.5) -> list[str]:
        """Return installed Ollama model ids, without requiring an API key."""
        urls = (
            "http://127.0.0.1:11434/v1/models",
            "http://127.0.0.1:11434/api/tags",
        )
        for url in urls:
            try:
                with urllib.request.urlopen(url, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8", "replace"))
                if not isinstance(data, dict):
                    continue
                items = data.get("data") or data.get("models") or []
                ids = [str(x.get("id") or x.get("name") or "").strip()
                       for x in items if isinstance(x, dict)]
                ids = [x for x in ids if x]
                if ids:
                    return ids
            except Exception:
                continue
        return []

    @staticmethod
    def _ollama_ready() -> bool:
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=0.3) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False

    def _start_ollama(self) -> bool:
        exe = which("ollama") or which("ollama.exe")
        if not exe or self._ollama_ready():
            return False
        try:
            kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                  "stderr": subprocess.DEVNULL}
            if os.name == "nt":
                kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen([exe, "serve"], **kw)
            for _ in range(12):
                time.sleep(0.25)
                if self._ollama_ready():
                    return True
        except Exception:
            return False
        return False

    def enable_local_ollama(self, force: bool = False) -> dict:
        """Make the app smarter with a local model; no Arena/provider key used."""
        cfg = self.get()
        if not force and (cfg.has_llm_key or not cfg.llm_enabled or not cfg.auto_local_llm):
            self.smart_status = "cloud" if cfg.has_llm_key else "offline"
            return {"ok": False, "mode": self.smart_status,
                    "reason": "Автоподключение пропущено согласно настройкам. Нажмите «Умный режим», --smart или SMART-MODE.bat."}

        models = self._ollama_models()
        # Explicit --smart / /api/smart may also start a local Ollama service.
        # Ordinary startup only detects an already-running service, so it stays fast.
        if force and not models and self._start_ollama():
            models = self._ollama_models(timeout=1.0)
        if not models:
            self.smart_status = "offline"
            return {"ok": False, "mode": "offline",
                    "reason": "Локальная Ollama не найдена. Запустите SMART-MODE.bat один раз."}

        preferred = [m for m in models if m.startswith(("llama3.1", "llama3.2", "qwen2.5"))]
        model = preferred[0] if preferred else models[0]
        with self._lock:
            self.cfg.llm_enabled = True
            self.cfg.llm_base_url = "http://localhost:11434/v1"
            self.cfg.llm_model = model
            self.save()
        self.smart_status = "ollama:" + model
        return {"ok": True, "mode": "ollama", "model": model,
                "base_url": self.cfg.llm_base_url,
                "reason": "Локальная языковая модель подключена без API-ключа."}

    def get(self) -> Config:
        with self._lock:
            return self.cfg

    def update(self, patch: dict) -> Config:
        allowed = {
            "user_name", "persona", "lang", "wake_word", "speak_replies", "listen_mode",
            "voice_rate", "voice_pitch", "llm_base_url", "llm_api_key", "llm_model",
            "llm_enabled", "auto_local_llm", "allow_shell", "allow_power", "require_confirm",
            "sandbox_root", "agent_token",
        }
        with self._lock:
            for k, v in patch.items():
                if k in allowed and hasattr(self.cfg, k):
                    if isinstance(getattr(self.cfg, k), bool):
                        v = bool(v)
                    elif isinstance(getattr(self.cfg, k), float):
                        try:
                            v = float(v)
                        except (TypeError, ValueError):
                            continue
                    setattr(self.cfg, k, v)
            self.save()
            if not self.cfg.brain_available:
                self.smart_status = "offline"
            elif self.cfg.local_llm:
                self.smart_status = "ollama:" + self.cfg.llm_model
            else:
                self.smart_status = "cloud"
            return self.cfg

    def save(self) -> None:
        with self._lock:
            d = asdict(self.cfg)
            # Persist user-editable settings only; secrets stay in this local file.
            keys = (
                "host", "port", "llm_base_url", "llm_api_key", "llm_model", "llm_enabled",
                "auto_local_llm", "user_name", "persona", "lang", "wake_word", "speak_replies", "listen_mode",
                "voice_rate", "voice_pitch", "allow_shell", "allow_power", "require_confirm",
                "sandbox_root", "agent_token",
            )
            CONFIG_FILE.write_text(
                json.dumps({k: d[k] for k in keys}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
