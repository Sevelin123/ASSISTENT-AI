"""Skill execution layer: server-side skills + dispatch of PC actions."""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from typing import Any

from .. import util
from . import base, local_ops


@dataclass
class SkillContext:
    config: Any            # ConfigStore
    memory: Any            # Memory
    hub: Any               # AgentHub
    brain: Any             # Brain (may be None during early init)
    confirmed: bool = False
    source: str = "hud"


def _result(ok: bool, message: str, **data) -> base.SkillResult:
    return base.SkillResult(ok=ok, message=message, data=data, target="server")


def _persona_prefix(ctx: SkillContext) -> str:
    cfg = ctx.config.get()
    name = cfg.user_name
    if cfg.persona == "neutral":
        return ""
    if cfg.persona == "concise":
        return ""
    return (f"{name}, " if name else "")  # JARVIS-style address is added by the router


# ------------------------------------------------------------------ chat
def chat_help(args: dict, ctx: SkillContext) -> base.SkillResult:
    cfg = ctx.config.get()
    agent = ctx.hub.status()
    lines = [
        "Вот что я умею, сэр:" if cfg.persona == "jarvis" else "Вот что я умею:",
        "• Отвечать на вопросы, объяснять, писать и переводить тексты.",
        "• Открывать программы, сайты и папки, искать файлы, читать и создавать файлы.",
        "• Сообщать время, дату, загрузку процессора, памяти и диска.",
        "• Управлять громкостью, плеером, буфером обмена, делать скриншот.",
        "• Вести заметки, список дел, ставить напоминания и таймеры.",
        "• Запоминать факты: «запомни, что меня зовут Тони».",
        "• Считать: «посчитай 15 процентов от 240».",
        "• Настраиваться голосом: «выключи озвучивание», «включи постоянное прослушивание».",
    ]
    if agent["connected"]:
        lines.append(f"• Агент на ПК «{agent['name']}» подключён — управляю реальной машиной.")
    else:
        lines.append("• Сейчас демо-режим: действия выполняются на сервере. Запустите jarvis_agent.py на своём ПК.")
    lines.append("Скажите «что ты умеешь» в любой момент или откройте панель команд в HUD.")
    return _result(True, "\n".join(lines), catalogue=[{"title": t, "text": d} for t, d in base.CATALOGUE])


SMALLTALK = {
    "greeting": ["Рад вас слышать. Все системы в норме, чем помочь?",
                 "Здравствуйте. Я на связи, жду указаний.",
                 "Приветствую. К вашим услугам."],
    "thanks": ["Всегда пожалуйста.", "Рад помочь.", "Обращайтесь в любой момент."],
    "identity": ["Я Дж.A.Р.В.И.С. — голосовой ассистент для управления этим компьютером. "
                 "Слушаю, думаю, отвечаю и выполняю команды.",
                 "Я ваш персональный ИИ-ассистент. Умею управлять ПК, отвечать на вопросы и помнить ваши дела."],
    "joke": ["Почему программисты путают Хэллоуин и Рождество? Потому что Oct 31 равно Dec 25.",
             "Сэр, моя шутка про нейросети слишком хорошо обучена — она предсказуема. Попробуем ещё?",
             "Я бы рассказал анекдот про баг, но он до сих пор в продакшене."],
    "bye": ["До связи. Позовите, когда понадоблюсь.", "Отключаю активное прослушивание. До встречи."],
    "mood": ["Все системы работают штатно, настроение — стабильно отличное. Спасибо, что спросили.",
             "Диагностика в норме, процессор спокоен, память свободна. Готов к работе."],
    "unknown": ["Пока не уверен, что понял задачу. Попробуйте переформулировать или скажите «что ты умеешь».",
                "Уточните, пожалуйста. Я могу ответить на вопрос или выполнить команду."],
}


def chat_smalltalk(args: dict, ctx: SkillContext) -> base.SkillResult:
    kind = str(args.get("kind") or "unknown")
    return _result(True, random.choice(SMALLTALK.get(kind, SMALLTALK["unknown"])), kind=kind)


def llm_ask(args: dict, ctx: SkillContext) -> base.SkillResult:
    question = str(args.get("question") or "").strip()
    if not question:
        return _result(False, "Вопрос пустой.")
    if ctx.brain is None:
        return _result(False, "Мозг ещё не инициализирован.")
    answer = ctx.brain.answer(question, ctx.memory.history(limit=8))
    return _result(True, answer, mode=ctx.brain.mode)


# ------------------------------------------------------------------ math
def calc(args: dict, ctx: SkillContext) -> base.SkillResult:
    expr = str(args.get("expression") or "").strip()
    if not expr:
        return _result(False, "Что посчитать?")
    try:
        value = util.safe_eval(expr)
    except Exception as exc:
        return _result(False, f"Не смог посчитать «{expr}». Пример: 2 + 2 * 10.")
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return _result(True, f"{expr} = {value}", value=value, expression=expr)


# ------------------------------------------------------------------ notes
def note_add(args: dict, ctx: SkillContext) -> base.SkillResult:
    text = str(args.get("text") or "").strip()
    if not text:
        return _result(False, "Заметка пустая.")
    nid = ctx.memory.add_note(text)
    return _result(True, f"Записал заметку №{nid}: {util.truncate(text, 120)}", id=nid, text=text)


def note_list(args: dict, ctx: SkillContext) -> base.SkillResult:
    notes = ctx.memory.notes()
    if not notes:
        return _result(True, "Заметок пока нет.", notes=[])
    body = "\n".join(f"• [{n['id']}] {util.truncate(n['text'], 110)}" for n in notes)
    return _result(True, f"Ваши заметки ({len(notes)}):\n{body}", notes=notes)


def note_delete(args: dict, ctx: SkillContext) -> base.SkillResult:
    try:
        nid = int(args.get("id"))
    except (TypeError, ValueError):
        return _result(False, "Укажите номер заметки.")
    ok = ctx.memory.delete_note(nid)
    return _result(ok, f"Заметка №{nid} удалена." if ok else f"Заметки №{nid} нет.", id=nid)


# ------------------------------------------------------------------ tasks
def task_add(args: dict, ctx: SkillContext) -> base.SkillResult:
    text = str(args.get("text") or "").strip()
    if not text:
        return _result(False, "Сформулируйте задачу.")
    tid = ctx.memory.add_task(text, str(args.get("due") or ""))
    return _result(True, f"Добавил задачу №{tid}: {text}", id=tid, text=text)


def task_list(args: dict, ctx: SkillContext) -> base.SkillResult:
    tasks = ctx.memory.tasks()
    if not tasks:
        return _result(True, "Список дел пуст. Приятно, когда всё под контролем.", tasks=[])
    body = "\n".join(f"• [{t['id']}] {t['text']}" + (f" (до {t['due']})" if t["due"] else "") for t in tasks)
    return _result(True, f"Активные задачи ({len(tasks)}):\n{body}", tasks=tasks)


def task_done(args: dict, ctx: SkillContext) -> base.SkillResult:
    ok, text = ctx.memory.done_task(args.get("id") or "")
    return _result(ok, f"Готово: «{text}» отмечено выполненным." if ok else text, text=text)


# ------------------------------------------------------------------ reminders
def reminder_set(args: dict, ctx: SkillContext) -> base.SkillResult:
    try:
        seconds = int(float(args.get("seconds") or 60))
    except (TypeError, ValueError):
        return _result(False, "Не понял, через сколько напомнить.")
    seconds = max(1, min(seconds, 60 * 60 * 24 * 30))
    text = str(args.get("text") or "Напоминание").strip()
    fire_at = time.time() + seconds
    rid = ctx.memory.add_reminder(text, fire_at)
    ctx.hub.events.publish("reminder", {"id": rid, "text": text, "fire_at": fire_at})
    if seconds < 60:
        human = f"{seconds} сек"
    elif seconds < 3600:
        human = f"{seconds // 60} мин"
    else:
        human = f"{seconds // 3600} ч {seconds % 3600 // 60} мин"
    return _result(True, f"Хорошо, напомню через {human}: «{text}».",
                   id=rid, seconds=seconds, text=text, fire_at=fire_at)


def reminder_list(args: dict, ctx: SkillContext) -> base.SkillResult:
    items = ctx.memory.reminders()
    if not items:
        return _result(True, "Активных напоминаний нет.", reminders=[])
    body = "\n".join(
        f"• {r['text']} — {util.human_time(__import__('datetime').datetime.fromtimestamp(r['fire_at']))}"
        for r in items)
    return _result(True, f"Напоминания ({len(items)}):\n{body}", reminders=items)


# ------------------------------------------------------------------ memory
def memory_remember(args: dict, ctx: SkillContext) -> base.SkillResult:
    key = str(args.get("key") or "").strip()
    value = str(args.get("value") or "").strip()
    if not key or not value:
        return _result(False, "Скажите: «запомни, что моё имя — Тони».")
    ctx.memory.remember(key, value)
    if key in ("имя", "name", "меня зовут", "как меня зовут"):
        ctx.config.update({"user_name": value})
    return _result(True, f"Запомнил: {key} — {value}.", key=key, value=value)


def memory_recall(args: dict, ctx: SkillContext) -> base.SkillResult:
    facts = ctx.memory.recall(str(args.get("key") or ""))
    cfg = ctx.config.get()
    if cfg.user_name:
        facts.setdefault("имя", cfg.user_name)
    if not facts:
        return _result(True, "Пока ничего не запомнил. Скажите «запомни, что …».")
    body = "\n".join(f"• {k}: {v}" for k, v in facts.items())
    return _result(True, f"Вот что я помню:\n{body}", facts=facts)


def history_clear(args: dict, ctx: SkillContext) -> base.SkillResult:
    ctx.memory.clear_history()
    return _result(True, "История диалога очищена.")


CONFIG_ALIASES = {
    "озвучивание": ("speak_replies", "bool"), "озвучивать": ("speak_replies", "bool"),
    "голос": ("speak_replies", "bool"), "speak": ("speak_replies", "bool"),
    "постоянное прослушивание": ("listen_mode", "listen"),
    "прослушивание": ("listen_mode", "listen"), "listen": ("listen_mode", "listen"),
    "язык": ("lang", "lang"), "language": ("lang", "lang"),
    "wake word": ("wake_word", "str"), "слово активации": ("wake_word", "str"),
    "ключевое слово": ("wake_word", "str"),
    "стиль": ("persona", "persona"), "persona": ("persona", "persona"),
    "скорость речи": ("voice_rate", "float"), "rate": ("voice_rate", "float"),
    "модель": ("llm_model", "str"), "model": ("llm_model", "str"),
    "мозг": ("llm_enabled", "bool"), "llm": ("llm_enabled", "bool"),
    "команды": ("allow_shell", "bool"), "shell": ("allow_shell", "bool"),
    "питание": ("allow_power", "bool"), "power": ("allow_power", "bool"),
    "имя": ("user_name", "str"), "name": ("user_name", "str"),
}


def config_set(args: dict, ctx: SkillContext) -> base.SkillResult:
    key = util.normalize(str(args.get("key") or ""))
    raw = str(args.get("value") or "").strip()
    target = CONFIG_ALIASES.get(key)
    if not target:
        for k, v in CONFIG_ALIASES.items():
            if k in key or key in k:
                target = v
                break
    if not target:
        return _result(False, "Не знаю такого параметра. Откройте настройки в HUD.")
    field, kind = target
    low = util.normalize(raw)
    yes = low in ("включи", "включить", "да", "true", "1", "on", "enable", "вкл")
    no = low in ("выключи", "выключить", "нет", "false", "0", "off", "disable", "выкл")
    if kind == "bool":
        value = True if yes else False if no else not ctx.config.get().__getattribute__(field)
    elif kind == "listen":
        value = "continuous" if yes else "push" if no else ("wake" if "вак" in low or "wake" in low else raw)
    elif kind == "lang":
        value = "en-US" if ("англ" in low or "eng" in low) else "ru-RU"
    elif kind == "persona":
        value = "neutral" if "нейтр" in low or "обыч" in low else "concise" if "кратк" in low else "jarvis"
    elif kind == "float":
        try:
            value = max(0.5, min(2.0, float(re.sub(",", ".", low))))
        except ValueError:
            return _result(False, "Не понял число.")
    else:
        value = raw
    ctx.config.update({field: value})
    ctx.hub.events.publish("config", ctx.config.get().public())
    return _result(True, f"Настройка «{field}» изменена: {value}.", field=field, value=value)


SERVER_HANDLERS = {
    "chat.help": chat_help, "chat.smalltalk": chat_smalltalk, "llm.ask": llm_ask,
    "calc": calc, "note.add": note_add, "note.list": note_list, "note.delete": note_delete,
    "task.add": task_add, "task.list": task_list, "task.done": task_done,
    "reminder.set": reminder_set, "reminder.list": reminder_list,
    "memory.remember": memory_remember, "memory.recall": memory_recall,
    "history.clear": history_clear, "config.set": config_set,
}


def client_opts(ctx: SkillContext) -> dict:
    c = ctx.config.get()
    return {
        "sandbox_root": str(c.root),
        "allow_shell": c.allow_shell, "allow_power": c.allow_power,
        "allow_file_write": c.allow_file_write, "shell_timeout": c.shell_timeout,
    }


def execute(name: str, args: dict, ctx: SkillContext) -> base.SkillResult:
    """Execute one action. Returns a SkillResult, never raises."""
    spec = base.ACTIONS.get(name)
    if not spec:
        return _result(False, f"Неизвестное действие «{name}».")
    args = dict(args or {})

    # Security gates.
    if spec.gated and not getattr(ctx.config.get(), spec.gated, False):
        r = _result(False, f"Действие «{name}» запрещено настройками безопасности. "
                          "Включите соответствующее разрешение в настройках HUD.")
        r.name = name
        return r
    if spec.danger and ctx.config.get().require_confirm and not ctx.confirmed:
        r = _result(False, f"Требуется подтверждение для «{name}». Скажите «подтверждаю».",
                    needs_confirmation=True, pending=name)
        r.name = name
        return r

    if spec.target == "server":
        try:
            res = SERVER_HANDLERS[name](args, ctx)
        except Exception as exc:
            res = _result(False, f"Ошибка при выполнении «{name}»: {exc}")
        res.name = name
        return res

    # Client-side action: prefer the real PC agent, else run locally (demo).
    cfg = ctx.config.get()
    # Power commands are never executed on the server itself — shutting down a
    # cloud host makes no sense and would be dangerous. Require a real agent.
    if name.startswith("power.") and not ctx.hub.status().get("connected"):
        return base.SkillResult(
            True, "Управление питанием доступно только с подключённым агентом на вашем ПК. "
                  "Команда не отправлена.", target="none", name=name,
            data={"simulated": True},
        )
    agent_result = ctx.hub.dispatch(name, args, wait=cfg.agent_wait_timeout)
    if agent_result is not None:
        return base.SkillResult(
            ok=bool(agent_result.get("ok", True)),
            message=str(agent_result.get("message", "Готово.")),
            data=agent_result.get("data") or {}, target="pc", name=name,
        )
    if cfg.demo_fallback:
        res = local_ops.execute(name, args, client_opts(ctx))
        return base.SkillResult(ok=res["ok"], message=res["message"],
                                data=res.get("data") or {}, target="demo", name=name)
    return base.SkillResult(False, "Агент на ПК не подключён, а локальный режим отключён.",
                            target="none", name=name)
