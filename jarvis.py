#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""J.A.R.V.I.S. — единая точка входа.

    python jarvis.py                  # запустить сервер + голосовой HUD
    python jarvis.py --port 9000      # на другом порту
    python jarvis.py cli              # текстовый режим в терминале
    python jarvis.py agent --server http://localhost:8080
                                      # подключить ЭТУ машину как «ПК»
    python jarvis.py selftest         # быстрая проверка ядра без сети
    python jarvis.py --help
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))


def cmd_server(args) -> int:
    from jarvis.config import ConfigStore
    from jarvis.server import serve

    cfg = ConfigStore()
    if args.host:
        cfg.cfg.host = args.host
    if args.port:
        cfg.cfg.port = args.port
    if args.api_key:
        cfg.cfg.llm_api_key = args.api_key
    if args.model:
        cfg.cfg.llm_model = args.model
    if args.base_url:
        cfg.cfg.llm_base_url = args.base_url
    if args.allow_shell:
        cfg.cfg.allow_shell = True
    if args.allow_power:
        cfg.cfg.allow_power = True

    # Build the app with our (possibly patched) config.
    from jarvis.server import JarvisApp
    app = JarvisApp(cfg)
    server = serve(args.host, args.port, app=app)
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print("\n  Отключаюсь. До встречи, сэр.", flush=True)
    finally:
        app.stop()
        server.server_close()
    return 0


def cmd_cli(args) -> int:
    from jarvis.brain import Brain
    from jarvis.config import ConfigStore
    from jarvis.hub import AgentHub
    from jarvis.memory import Memory
    from jarvis.router import Router

    cfg = ConfigStore()
    mem, hub, brain = Memory(), AgentHub(token=cfg.get().agent_token), Brain(cfg, mem)
    router = Router(cfg, mem, hub, brain)
    print("\n  J.A.R.V.I.S. · текстовый режим.  'выход' — завершить, 'статус' — диагностика.\n", flush=True)
    print(f"  Мозг: {brain.mode} · ПК-агент: {hub.status()['mode']}\n")
    while True:
        try:
            text = input("  ВЫ > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  До связи.")
            return 0
        if not text:
            continue
        if text.lower() in ("выход", "quit", "exit", "пока"):
            print("  До связи, сэр.")
            return 0
        if text.lower() in ("статус", "status"):
            s = router.status()
            print(f"  J.A.R.V.I.S > мозг={s['brain']}, агент={s['agent']['mode']}, действий={s['actions']}")
            continue
        out = router.process(text, source="cli")
        print("  J.A.R.V.I.S > " + out["reply"].replace("\n", "\n  " + " " * 14), flush=True)
        for a in out["actions"]:
            print(f"    [{a['target']:6}] {a['name']:20} {'✓' if a['ok'] else '!'}")


def cmd_agent(args) -> int:
    script = BASE / "jarvis_agent.py"
    cmd = [sys.executable, str(script), "--server", args.server or "http://localhost:8080"]
    if args.token:
        cmd += ["--token", args.token]
    if args.allow_shell:
        cmd.append("--allow-shell")
    if args.allow_power:
        cmd.append("--allow-power")
    return subprocess.call(cmd)


def cmd_selftest(args) -> int:
    from jarvis import nlu
    from jarvis.config import ConfigStore
    from jarvis.hub import AgentHub
    from jarvis.memory import Memory
    from jarvis.brain import Brain
    from jarvis.router import Router
    from jarvis.skills import base

    cases = [
        ("Джарвис, который час?", "system.time"),
        ("открой youtube.com", "app.open"),
        ("загугли рецепт пасты", "web.search"),
        ("посчитай 15 процентов от 240", "calc"),
        ("добавь задачу позвонить маме", "task.add"),
        ("напомни через 5 минут размяться", "reminder.set"),
        ("запомни, что меня зовут Тони", "memory.remember"),
        ("что ты умеешь", "chat.help"),
        ("покажи заметки", "note.list"),
        ("сделай скриншот", "screenshot"),
        ("найди файл отчёт", "file.search"),
        ("выключи озвучивание", "config.set"),
        ("громкость 40", "media.volume"),
        ("выключи компьютер", "power.shutdown"),
        ("привет", "chat.smalltalk"),
        ("объясни, что такое нейросеть", "llm.ask"),
    ]
    ok = 0
    print("\n  Проверка распознавания намерений:\n")
    for phrase, want in cases:
        got = nlu.recognize(phrase)[0].action
        good = got == want
        ok += good
        print(f"  {'✓' if good else '✗'}  {phrase:38} → {got:22} (ожидалось {want})")
    print(f"\n  {ok}/{len(cases)} намерений распознано.")

    print("\n  Проверка выполнения действий:\n")
    cfg = ConfigStore()
    mem = Memory(BASE / ".jarvis_data" / "selftest.db")
    hub = AgentHub()
    brain = Brain(cfg, mem)
    router = Router(cfg, mem, hub, brain)
    for phrase in ("посчитай 2+2*10", "добавь задачу проверить систему", "список дел", "статус системы"):
        try:
            out = router.process(phrase, source="selftest")
            print(f"  ✓ {phrase:35} → {out['reply'].splitlines()[0][:80]}")
        except Exception as exc:
            print(f"  ✗ {phrase:35} → {exc}")
    print(f"\n  Всего действий в реестре: {len(base.ACTIONS)}")
    for suffix in ("", "-wal", "-shm"):
        try:
            (BASE / ".jarvis_data" / f"selftest.db{suffix}").unlink(missing_ok=True)
        except Exception:
            pass
    return 0 if ok == len(cases) else 1


def main() -> int:
    p = argparse.ArgumentParser(description="J.A.R.V.I.S. — голосовой AI-ассистент для управления ПК",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__)
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("server", help="запустить HUD и API (по умолчанию)")
    a = sub.add_parser("agent", help="подключить эту машину как управляемый ПК")
    sub.add_parser("cli", help="текстовый диалог в терминале")
    sub.add_parser("selftest", help="проверить ядро без сети")

    for parser in (p, s):
        parser.add_argument("--host", default="", help="адрес (по умолчанию 0.0.0.0)")
        parser.add_argument("--port", type=int, default=0, help="порт (по умолчанию 8080)")
        parser.add_argument("--api-key", default="", help="ключ OpenAI-совместимого API")
        parser.add_argument("--base-url", default="", help="адрес API, например http://localhost:11434/v1")
        parser.add_argument("--model", default="", help="имя модели")
        parser.add_argument("--allow-shell", action="store_true", help="разрешить команды терминала")
        parser.add_argument("--allow-power", action="store_true", help="разрешить выключение ПК")
    a.add_argument("--server", default="", help="адрес сервера J.A.R.V.I.S.")
    a.add_argument("--token", default="", help="токен агента")
    a.add_argument("--allow-shell", action="store_true")
    a.add_argument("--allow-power", action="store_true")

    args = p.parse_args()
    if args.cmd == "cli":
        return cmd_cli(args)
    if args.cmd == "agent":
        return cmd_agent(args)
    if args.cmd == "selftest":
        return cmd_selftest(args)
    return cmd_server(args)


if __name__ == "__main__":
    sys.exit(main())
