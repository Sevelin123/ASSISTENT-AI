"""Task bus between the brain (server) and the agent running on the user's PC.

The HUD works even with no agent: client-side actions then run on the server
itself (demo mode). As soon as `jarvis_agent.py` connects, the very same
actions are dispatched to the real computer instead.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Task:
    id: str
    name: str
    args: dict
    created: float = field(default_factory=time.time)
    result: dict | None = None
    done: threading.Event = field(default_factory=threading.Event)


@dataclass
class Agent:
    id: str
    name: str
    platform: str
    last_seen: float = field(default_factory=time.time)
    tasks: "queue.Queue[Task]" = field(default_factory=queue.Queue)
    completed: int = 0


class EventBus:
    """Fan-out of server-sent events to every open HUD tab."""

    def __init__(self) -> None:
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, kind: str, data: Any) -> None:
        event = {"kind": kind, "data": data, "ts": time.time()}
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass


class AgentHub:
    def __init__(self, token: str = "", events: EventBus | None = None, stale_after: float = 45.0):
        self.token = token
        self.events = events or EventBus()
        self.stale_after = stale_after
        self._agents: dict[str, Agent] = {}
        self._lock = threading.RLock()

    # ---------------- agent side ----------------
    def register(self, name: str, platform: str, token: str) -> tuple[str | None, str]:
        if self.token and token != self.token:
            return None, "неверный токен агента"
        agent_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._agents[agent_id] = Agent(id=agent_id, name=name[:60], platform=platform[:40])
        self.events.publish("agent", {"connected": True, "name": name, "platform": platform})
        return agent_id, "ok"

    def heartbeat(self, agent_id: str) -> bool:
        with self._lock:
            a = self._agents.get(agent_id)
            if not a:
                return False
            a.last_seen = time.time()
            return True

    def poll(self, agent_id: str, timeout: float = 20.0) -> list[dict]:
        with self._lock:
            a = self._agents.get(agent_id)
        if not a:
            return []
        a.last_seen = time.time()
        try:
            first = a.tasks.get(timeout=timeout)
        except queue.Empty:
            return []
        out = [{"id": first.id, "name": first.name, "args": first.args}]
        while True:
            try:
                t = a.tasks.get_nowait()
                out.append({"id": t.id, "name": t.name, "args": t.args})
            except queue.Empty:
                break
        return out

    def submit_result(self, agent_id: str, task_id: str, result: dict) -> bool:
        with self._lock:
            a = self._agents.get(agent_id)
            pending = self._pending.get(task_id)
        if a:
            a.completed += 1
            a.last_seen = time.time()
        if pending is not None:
            pending.result = result
            pending.done.set()
        return pending is not None

    # ---------------- server side ----------------
    @property
    def _pending(self) -> dict[str, Task]:
        if not hasattr(self, "_pending_map"):
            self._pending_map = {}
        return self._pending_map

    def connected(self) -> Agent | None:
        """Return the most recently seen live agent (a PC may reconnect)."""
        with self._lock:
            now = time.time()
            for aid, a in list(self._agents.items()):
                if now - a.last_seen > self.stale_after:
                    del self._agents[aid]
                    self.events.publish("agent", {"connected": False, "name": a.name})
            alive = list(self._agents.values())
            if not alive:
                return None
            return max(alive, key=lambda a: a.last_seen)

    def status(self) -> dict:
        a = self.connected()
        if not a:
            return {"connected": False, "mode": "demo", "name": "", "platform": "", "completed": 0}
        return {
            "connected": True, "mode": "pc", "name": a.name, "platform": a.platform,
            "completed": a.completed, "last_seen": round(time.time() - a.last_seen, 1),
        }

    def dispatch(self, name: str, args: dict, wait: float = 6.0) -> dict | None:
        """Send an action to the PC agent and wait for its result.

        Returns None when there is no connected agent (or it timed out), so the
        caller can fall back to running the action on the server.
        """
        a = self.connected()
        if not a:
            return None
        task = Task(id=uuid.uuid4().hex[:12], name=name, args=args)
        with self._lock:
            self._pending[task.id] = task
        a.tasks.put(task)
        self.events.publish("action", {"name": name, "args": args, "target": "pc", "id": task.id})
        finished = task.done.wait(timeout=wait)
        with self._lock:
            self._pending.pop(task.id, None)
        if not finished:
            return None
        return task.result
