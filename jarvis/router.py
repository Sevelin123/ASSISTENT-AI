"""Orchestrator: voice/text -> brain or NLU -> actions -> spoken reply."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from . import nlu, skills, util
from .skills import base


CONFIRM_RE = re.compile(r"^(?:да,?\s*)?(?:подтверждаю|подтвердить|confirm|точно|выполняй|ok|окей)\b", re.I)
CANCEL_RE = re.compile(r"^(?:отмена|отмени|cancel|не надо|передумал|отбой)\b", re.I)

# Actions whose message IS the answer and must always be spoken.
VERBOSE_ACTIONS = {
    "chat.smalltalk", "chat.help", "llm.ask", "calc", "note.list", "task.list",
    "reminder.list", "memory.recall", "system.time", "system.status", "system.processes",
    "file.list", "file.read", "file.open", "file.search", "computer.open",
    "clipboard.get", "screenshot",
}


@dataclass
class Pending:
    action: str
    args: dict
    created: float
    reason: str


class Router:
    def __init__(self, config_store, memory, hub, brain):
        self.config = config_store
        self.memory = memory
        self.hub = hub
        self.brain = brain
        self.pending: Pending | None = None
        self.started = time.time()
        self._lock = __import__("threading").RLock()

    # ------------------------------------------------------------------ API
    def process(self, text: str, source: str = "hud", lang: str | None = None) -> dict:
        """Main entry point. Returns a JSON-serialisable response."""
        text = (text or "").strip()
        cfg = self.config.get()
        if not text:
            return {"reply": "Я вас не расслышал. Повторите, пожалуйста.", "actions": [], "mode": "offline"}
        self.memory.add_message("user", text, {"source": source})
        low = util.normalize(text)

        with self._lock:
            pending = self.pending
            if pending and time.time() - pending.created > 180:
                self.pending = None
                pending = None

            # ---- confirmation flow ----
            if pending and (CONFIRM_RE.match(low) or "подтверждаю" in low):
                self.pending = None
                return self._finish(text, [nlu.Intent(pending.action, pending.args)], None,
                                    source, confirmed=True)
            if pending and (CANCEL_RE.match(low) or "отмена" in low):
                self.pending = None
                return self._finish(text, [nlu.I("chat.smalltalk", kind="thanks")],
                                    "Отменяю. Команда не выполнена.", source)

        # ---- intent recognition ----
        history = self.memory.history(limit=8)
        plan_reply, intents = (None, [])
        if cfg.brain_available:
            plan_reply, intents = self.brain.plan(text, history)
        if not intents and plan_reply is None:
            intents = nlu.recognize(text, cfg.wake_word)
        # LLM may answer a question with no actions — that's fine.
        if cfg.brain_available and plan_reply and not intents:
            return self._finish(text, [], plan_reply, source)

        # pseudo-actions from the NLU
        if intents and intents[0].action in ("system.confirm", "system.cancel"):
            other = "Ничего не ожидает подтверждения." if intents[0].action == "system.confirm" else "Отменять нечего."
            return self._finish(text, [nlu.I("chat.smalltalk", kind="unknown")], other, source)

        return self._finish(text, intents, plan_reply, source)

    # ------------------------------------------------------------ internals
    def _finish(self, text: str, intents: list[nlu.Intent], plan_reply: str | None,
                source: str, confirmed: bool = False) -> dict:
        cfg = self.config.get()
        ctx = skills.SkillContext(config=self.config, memory=self.memory, hub=self.hub,
                                  brain=self.brain, confirmed=confirmed, source=source)
        results: list[dict] = []
        messages: list[str] = []

        for intent in intents[:6]:
            res: base.SkillResult = skills.execute(intent.action, intent.args, ctx)
            results.append(res.as_dict())
            # Store dangerous action for the confirmation round-trip.
            if res.data.get("needs_confirmation") and not confirmed:
                with self._lock:
                    self.pending = Pending(intent.action, intent.args, time.time(), res.message)
            if plan_reply is None:
                # Offline mode: the action messages ARE the spoken answer.
                if res.message:
                    messages.append(res.message)
            elif (res.name in VERBOSE_ACTIONS
                  and res.name not in ("chat.smalltalk", "llm.ask", "chat.help")
                  and res.message):
                # LLM gave an acknowledgment; append the informative payload.
                messages.append(res.message)
            self.memory.log("action", f"{intent.action}: {'ok' if res.ok else 'fail'} — {util.truncate(res.message, 120)}")
            self.hub.events.publish("action", {**res.as_dict(), "phase": "done"})

        # Compose the spoken reply.
        if plan_reply:
            reply = plan_reply
            extra = " ".join(m for m in messages if m and m not in plan_reply)
            if extra and len(reply) < 100:
                reply = (reply.rstrip() + " " + extra.strip()).strip()
        elif messages:
            reply = "\n".join(dict.fromkeys(messages))
        else:
            reply = "Готово."

        name = cfg.user_name
        if cfg.persona == "jarvis" and name and not plan_reply and source == "voice" and len(reply) < 90:
            if not reply.lower().startswith(name.lower()):
                reply = f"{name}, {reply[0].lower() + reply[1:]}" if reply else reply

        meta = {"actions": results, "mode": self.brain.mode,
                "agent": self.hub.status(), "confirmed": confirmed}
        self.memory.add_message("assistant", reply, meta)
        out = {"reply": reply, "actions": results, "mode": self.brain.mode,
               "agent": self.hub.status(), "ts": util.iso(),
               "pending": bool(self.pending)}
        self.hub.events.publish("chat", {"role": "assistant", "text": reply, "meta": meta})
        return out

    def status(self) -> dict:
        cfg = self.config.get()
        return {
            "version": "1.0.0",
            "brain": self.brain.mode,
            "smart_mode": self.config.smart_status,
            "brain_error": self.brain.last_error if cfg.brain_available else "",
            "brain_hint": self.brain.last_hint if cfg.brain_available else "",
            "agent": self.hub.status(),
            "stats": self.memory.stats(),
            "actions": len(base.ACTIONS),
            "pending": bool(self.pending),
            "uptime": f"{int((time.time() - self.started) // 60)} мин",
            "platform": util.platform_info(),
            "config": cfg.public(),
        }
