"""Runtime configuration for J.A.R.V.I.S.

Priority: environment variables > ./jarvis.config.json > defaults.
The JSON file is created by the Settings panel of the HUD and is git-ignored,
so API keys never end up in the repository.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

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

    def get(self) -> Config:
        with self._lock:
            return self.cfg

    def update(self, patch: dict) -> Config:
        allowed = {
            "user_name", "persona", "lang", "wake_word", "speak_replies", "listen_mode",
            "voice_rate", "voice_pitch", "llm_base_url", "llm_api_key", "llm_model",
            "llm_enabled", "allow_shell", "allow_power", "require_confirm", "sandbox_root",
            "agent_token",
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
            return self.cfg

    def save(self) -> None:
        with self._lock:
            d = asdict(self.cfg)
            # Persist user-editable settings only; secrets stay in this local file.
            keys = (
                "host", "port", "llm_base_url", "llm_api_key", "llm_model", "llm_enabled",
                "user_name", "persona", "lang", "wake_word", "speak_replies", "listen_mode",
                "voice_rate", "voice_pitch", "allow_shell", "allow_power", "require_confirm",
                "sandbox_root", "agent_token",
            )
            CONFIG_FILE.write_text(
                json.dumps({k: d[k] for k in keys}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
