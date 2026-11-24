"""J.A.R.V.I.S. — Just A Rather Very Intelligent System.

A voice-first AI assistant for controlling a computer.

Modules:
    config   — runtime configuration (env vars + local JSON file)
    util     — small cross-platform helpers
    memory   — SQLite-backed long-term memory (dialogue, notes, tasks, facts)
    hub      — task bus for the on-PC agent
    skills   — the actual actions the assistant can perform
    nlu      — offline intent recognition (Russian + English)
    brain    — optional OpenAI-compatible LLM, with a local fallback
    router   — orchestrator: text -> intent -> actions -> spoken reply
    server   — HTTP API + static HUD + SSE event stream
"""

__version__ = "1.0.0"
__all__ = ["config", "util", "memory", "hub", "skills", "nlu", "brain", "router", "server"]
