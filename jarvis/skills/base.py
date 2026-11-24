"""Action contract shared by the brain, the HUD and the on-PC agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ActionSpec:
    name: str
    target: str                 # "server" | "client"
    description: str
    args: dict                  # arg name -> human description
    danger: bool = False        # requires explicit confirmation
    gated: str | None = None    # config flag that must be True


@dataclass
class SkillResult:
    ok: bool
    message: str
    data: dict = field(default_factory=dict)
    target: str = "server"
    name: str = ""

    def as_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "message": self.message,
                "data": self.data, "target": self.target}


def spec(name, target, description, args=None, danger=False, gated=None) -> ActionSpec:
    return ActionSpec(name, target, description, args or {}, danger, gated)


# The single source of truth. The LLM prompt and the standalone PC agent are
# generated from / kept in sync with this table.
ACTIONS: dict[str, ActionSpec] = {a.name: a for a in [
    # ---- server-side (brain memory, works even without the PC agent) ----
    spec("chat.help", "server", "Рассказать, что умеет ассистент, список команд", {}),
    spec("chat.smalltalk", "server", "Ответить на приветствие, благодарность, вопрос 'кто ты', шутка", {"kind": "greeting|thanks|identity|joke|bye|mood|unknown"}),
    spec("llm.ask", "server", "Ответить на свободный вопрос, объяснить, посоветовать, написать текст", {"question": "текст вопроса"}),
    spec("calc", "server", "Посчитать математическое выражение", {"expression": "например 2+2*10 или sqrt(144)"}),
    spec("note.add", "server", "Сохранить заметку", {"text": "текст заметки"}),
    spec("note.list", "server", "Показать заметки", {}),
    spec("note.delete", "server", "Удалить заметку", {"id": "номер заметки"}),
    spec("task.add", "server", "Добавить задачу в список дел", {"text": "текст задачи", "due": "срок (необязательно)"}),
    spec("task.list", "server", "Показать список дел", {}),
    spec("task.done", "server", "Отметить задачу выполненной", {"id": "номер или часть текста"}),
    spec("reminder.set", "server", "Поставить напоминание / таймер", {"seconds": "через сколько секунд", "text": "о чём напомнить"}),
    spec("reminder.list", "server", "Показать активные напоминания", {}),
    spec("memory.remember", "server", "Запомнить факт (имя, предпочтение)", {"key": "ключ", "value": "значение"}),
    spec("memory.recall", "server", "Вспомнить сохранённые факты", {"key": "ключ (необязательно)"}),
    spec("history.clear", "server", "Очистить историю диалога", {}),
    spec("config.set", "server", "Изменить настройки голосом", {"key": "параметр", "value": "значение"}),

    # ---- client-side (real PC control) ----
    spec("system.status", "client", "Показать загрузку CPU, память, диск, ОС, аптайм", {}),
    spec("system.time", "client", "Сказать текущие время и дату", {}),
    spec("system.processes", "client", "Показать список процессов", {"limit": "сколько (по умолчанию 8)"}),
    spec("app.open", "client", "Открыть установленное приложение, сайт, файл или папку (ищет приложение в Windows)", {"target": "имя программы / URL / путь"}),
    spec("app.close", "client", "Закрыть программу", {"target": "имя процесса"}),
    spec("computer.open", "client", "Открыть «Этот компьютер» / диски Проводником Windows", {}),
    spec("file.open", "client", "Открыть файл или папку системным открывателем, найти файл по имени", {"path": "путь или имя файла"}),
    spec("web.search", "client", "Найти что-то в интернете (открыть поиск)", {"query": "поисковый запрос", "engine": "google|duckduckgo|youtube|github"}),
    spec("file.search", "client", "Найти файлы по имени", {"query": "часть имени", "root": "папка (необязательно)"}),
    spec("file.list", "client", "Показать содержимое папки", {"path": "путь"}),
    spec("file.read", "client", "Прочитать текстовый файл", {"path": "путь"}),
    spec("file.write", "client", "Создать или записать текстовый файл", {"path": "путь", "content": "содержимое"}),
    spec("clipboard.set", "client", "Положить текст в буфер обмена", {"text": "текст"}),
    spec("clipboard.get", "client", "Прочитать буфер обмена", {}),
    spec("media.volume", "client", "Установить/изменить громкость", {"level": "0-100, +10 или -10, либо 'mute'"}),
    spec("media.control", "client", "Управлять плеером", {"action": "play|pause|next|prev|stop"}),
    spec("screenshot", "client", "Сделать скриншот экрана", {}),
    spec("shell.run", "client", "Выполнить команду в терминале", {"command": "команда"}, danger=True, gated="allow_shell"),
    spec("power.sleep", "client", "Перевести ПК в режим сна", {}, danger=True, gated="allow_power"),
    spec("power.shutdown", "client", "Выключить ПК", {}, danger=True, gated="allow_power"),
    spec("power.reboot", "client", "Перезагрузить ПК", {}, danger=True, gated="allow_power"),
]}

# Human-readable catalogue for the HUD's "что умеешь" panel.
CATALOGUE = [
    ("Голос", "Слушаю постоянно, по wake-word «Джарвис» или при нажатии микрофона. Отвечаю вслух."),
    ("ПК", "Открываю приложения по имени (включая Steam), сайты, файлы и папки, «Этот компьютер», ищу файлы, читаю/создаю файлы, управляю громкостью и плеером, делаю скриншот."),
    ("Система", "Сообщаю время, дату, загрузку процессора, память, диск, список процессов."),
    ("Память", "Заметки, список дел, напоминания и таймеры, факты обо мне и о тебе — всё сохраняется."),
    ("Мозг", "Отвечаю на вопросы и решаю задачи: подключи OpenAI-совместимый API или локальную Ollama — или работаю оффлайн на встроенном NLU."),
    ("Безопасность", "Опасные действия требуют голосового «подтверждаю» и вручную включаемых разрешений."),
]


def describe_for_llm() -> str:
    """Compact tool list injected into the LLM system prompt."""
    lines = []
    for a in ACTIONS.values():
        arg = ", ".join(f"{k}: {v}" for k, v in a.args.items()) or "без аргументов"
        flag = " [ОПАСНО: нужно подтверждение]" if a.danger else ""
        lines.append(f"- {a.name} ({arg}) — {a.description}{flag}")
    return "\n".join(lines)
