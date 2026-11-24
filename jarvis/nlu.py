"""Offline intent recognition (Russian + English).

A transparent, ordered rule engine. Each rule turns the user's phrase into one
or more actions from skills.base.ACTIONS. When nothing matches, the phrase goes
to `llm.ask` — which uses the LLM if configured, or the built-in knowledge base.

Adding a command = adding one line to RULES. No training, no downloads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import util


@dataclass
class Intent:
    action: str
    args: dict = field(default_factory=dict)
    confidence: float = 1.0


def I(action: str, **args) -> Intent:
    return Intent(action, args)


# ---------------------------------------------------------------- helpers
FILLER = re.compile(
    r"\b(?:пожалуйста|давай(?:те)?|ну-ка|ну ка|could you|please|kindly|would you|"
    r"can you|мне|для меня|на этом компьютере)\b", re.I)


def clean(s: str) -> str:
    s = FILLER.sub(" ", s or "")
    s = re.sub(r"\s+", " ", s).strip(" ,.;:!?–—-\"'`")
    return s


def after(text: str, marker: str) -> str:
    m = re.search(marker, text, re.I)
    return clean(text[m.end():]) if m else clean(text)


def strip_wake(text: str, wake: str = "джарвис") -> str:
    t = (text or "").strip()
    pattern = r"^(?:Эй\s+|Хэй\s+|Hey\s+|OK\s+)?(" + re.escape(wake) + r"|jarvis|джарвис|жарвис|джервис)\b[\s,:-]*"
    return re.sub(pattern, "", t, count=1, flags=re.I).strip() or t


MATH_WORDS = [
    (r"\bплюс\b|\bприбавить\b|\bplus\b", "+"),
    (r"\bминус\b|\bотнять\b|\bminus\b", "-"),
    (r"\bумнож\w*\s*(?:на|by)?\b|\btimes\b|\bx\b", "*"),
    (r"\bраздел\w*\s*(?:на|by)?\b|\bdivided by\b", "/"),
    (r"\bв\s+степени\b|\bстепень\b|\bpower\b|\^", "**"),
    (r"\bкорень\s*(?:из)?\b|\bквадратный корень\b|\bsqrt\b", "sqrt"),
    (r"\bпроцент\w*\s*(?:от|of)\s+(\d+(?:[.,]\d+)?)", r"*0.01*(\1)"),
    (r"\b(?:и|and)\b", ""),
]


def to_expression(text: str) -> str:
    t = util.normalize(text)
    t = t.replace("=", "").replace("равно", "").replace("сколько будет", "").replace("сколько", "")
    # Square roots survive the character filter as sqrt(<number>).
    t = re.sub(r"(?:квадратный\s+)?корень\s*(?:из\s*)?(\d+(?:[.,]\d+)?)", r"sqrt(\1)", t)
    t = re.sub(r"sqrt\s*\(?\s*(\d+(?:[.,]\d+)?)\s*\)?", r"sqrt(\1)", t)
    for pattern, repl in MATH_WORDS:
        t = re.sub(pattern, repl, t)
    t = t.replace("скобка", "(").replace("закрыть скобку", ")")
    # Keep sqrt(<number>) alive through the character filter by swapping it
    # for a marker that contains no letters.
    t = re.sub(r"sqrt\(\s*([\d.,]+)\s*\)", r"§\1§", t)
    t = re.sub(r"[^\d\.\+\-\*\/\%\(\)\,\s§]", " ", t)
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"§([\d.,]+)§", r"sqrt(\1)", t)
    return t.strip("+*/ ")


def _find(rules, text):
    for pattern, builder in rules:
        m = re.search(pattern, text, re.I)
        if m:
            result = builder(text, m)
            if result:
                if isinstance(result, Intent):
                    return [result]
                return list(result)
    return None


# ---------------------------------------------------------------- rules
Rule = tuple[str, Callable[[str, re.Match], Iterable[Intent] | Intent | None]]

RULES: list[Rule] = [
    # ---- FAQ: API key is optional. Answer offline even when '?' is stripped. ----
    (r"(?:нужен ли|нужно ли|обязателен ли|обязательно ли|требуется ли|надо ли|нужен|нужно|обязателен|обязательно|требуется|надо|где (?:взять|получить)|как (?:получить|создать))\s+(?:api[- ]?ключ|ключ\s+(?:api|от openai|для llm)|api key)\b|\b(?:api[- ]?ключ|api key)\s+(?:нужен|нужно|обязателен|обязательно|требуется|надо|где взять)\b",
     lambda t, m: I("llm.ask", question=t)),

    # ---- help & persona ----
    (r"(что ты умеешь|что умеешь|список команд|помощь|help|возможности|команды|что можно|как тобой пользоваться)",
     lambda t, m: I("chat.help")),
    (r"(кто ты|что ты такое|представься|who are you|расскажи о себе)",
     lambda t, m: I("chat.smalltalk", kind="identity")),
    (r"(привет|здравств\w*|добрый (день|вечер|утро)|хай|hello|hi\b|приветствую)",
     lambda t, m: I("chat.smalltalk", kind="greeting")),
    (r"(спасибо|благодар\w*|thanks|thank you|отлично|молодец)",
     lambda t, m: I("chat.smalltalk", kind="thanks")),
    (r"(пока\b|до свидания|до встречи|goodbye|bye\b|отключайся|отключись)",
     lambda t, m: I("chat.smalltalk", kind="bye")),
    (r"(как дела|как ты|как настроение|how are you|ты в порядке|всё в порядке\?)",
     lambda t, m: [I("chat.smalltalk", kind="mood"), I("system.status")]),
    (r"(шутк\w*|анекдот|рассмеши|joke|пошути)",
     lambda t, m: I("chat.smalltalk", kind="joke")),

    # ---- settings by voice ----
    (r"(выключи|отключи|включи|переключи|установи|измени|смени|set|enable|disable|switch)\s+(.+)$",
     lambda t, m: _settings(t, m)),

    # ---- confirmation / cancellation (pseudo-actions handled by router) ----
    (r"^(подтверждаю|да\s*подтверждаю|confirm|подтвердить|точно|выполняй|да,?\s*выполняй)$",
     lambda t, m: I("system.confirm")),
    (r"^(отмена|отмени|cancel|не надо|передумал|отбой)$",
     lambda t, m: I("system.cancel")),

    # ---- memory ----
    (r"(запомни|запомнить|remember|не забывай)\s*(?:,|:|\s)\s*(?:что\s+)?(.+)",
     lambda t, m: _remember(clean(m.group(2)))),
    (r"меня зовут\s+([\wа-яё-]+)",
     lambda t, m: I("memory.remember", key="имя", value=m.group(1).strip().capitalize())),
    (r"(что ты помнишь|что помнишь|какие факты|как меня зовут|вспомни|what do you remember|recall)",
     lambda t, m: I("memory.recall")),
    (r"(очисти|удали|сотри)\s+(историю|диалог|чат|histor)",
     lambda t, m: I("history.clear")),

    # ---- notes ----
    (r"(?:создай|добавь|напиши|сохрани|запиши|make|add|create)\s*(?:новую\s+)?(?:заметку|заметки|note)\s*(?:[:—-]|\s)\s*(.+)",
     lambda t, m: I("note.add", text=clean(m.group(1)))),
    (r"^заметка\s*[:—-]?\s*(.+)", lambda t, m: I("note.add", text=clean(m.group(1)))),
    (r"(покажи|прочитай|выведи|какие|прочти|list|show)\s*(?:мои\s+|все\s+)?(?:заметки|записи|notes?)",
     lambda t, m: I("note.list")),
    (r"(удали|удалить|delete)\s*заметку\s*№?\s*(\d+)",
     lambda t, m: I("note.delete", id=int(m.group(2)))),

    # ---- tasks ----
    (r"(?:добавь|создай|поставь|add)\s*(?:в\s+)?(?:задачу|дело|пункт|todo|task)\s*(?:[:—-]|\s)\s*(.+)",
     lambda t, m: I("task.add", text=clean(m.group(1)))),
    (r"(?:напомни\s+мне\s+сделать|нужно\s+сделать)\s+(.+)",
     lambda t, m: I("task.add", text=clean(m.group(1)))),
    (r"(покажи|какой|выведи|list|show|что в)\s*(?:у меня\s+)?(?:список дел|задачи|планы|todo|tasks?)",
     lambda t, m: I("task.list")),
    (r"^(?:список дел|мои задачи|что в планах|планы на сегодня|todo list|my tasks?)\b",
     lambda t, m: I("task.list")),
    (r"^(?:мои )?заметки$|^все записи$", lambda t, m: I("note.list")),
    (r"(?:задача|дело)\s*№?\s*(\d+)\s*(?:выполнена|готово|сделано|done)|(?:отметь|закрой|выполни)\s*(?:задачу|дело)\s*№?\s*(\d+)|(?:готово|сделано|выполнено)\s*[:—-]?\s*(.+)",
     lambda t, m: I("task.done", id=(m.group(1) or m.group(2) or m.group(3) or "").strip())),

    # ---- reminders & timers ----
    (r"(напомни|напомнить|поставь (?:таймер|будильник|напоминание)|set (?:a )?(?:timer|reminder)|таймер|remind me)\b(.+)?",
     lambda t, m: _reminder(t, m)),

    # ---- math ----
    (r"(посчитай|вычисли|calculate|compute|сколько будет|сколько\s+получится|реши)\b(.+)?",
     lambda t, m: _calc(t, m)),
    (r"^\s*[\d\(\-\+\.][\d\s\+\-\*\/\^\(\)\.,%x×÷:]*\s*=?\s*$",
     lambda t, m: I("calc", expression=to_expression(t))),

    # ---- virtual shell folders (before generic "open") ----
    (r"(открой|открыть|запусти|запустить|покажи|open|launch|start)\s+(?:мой\s+|этот\s+|this\s+|my\s+)?(компьютер|пк|computer|pc|диски|drives)\b",
     lambda t, m: I("computer.open")),

    # ---- system ----
    (r"(который час|сколько времени|какое время|what time|current time|время\?)",
     lambda t, m: I("system.time")),
    (r"(какая сегодня дата|какой сегодня день|какое число|what.*date|today's date|дата\?)",
     lambda t, m: I("system.time")),
    (r"(статус|состояние|диагностика|загрузка|нагрузка|system status|status|cpu|ram|память|диск|батаре[яю])",
     lambda t, m: I("system.status")),
    (r"(список процессов|какие процессы|процессы|running processes|top processes|task manager)",
     lambda t, m: I("system.processes", limit=8)),

    # ---- power (dangerous) ----
    (r"(выключи|выключить|отключи)\s*(компьютер|пк|машину|pc|computer|shutdown)",
     lambda t, m: I("power.shutdown")),
    (r"(перезагрузи|перезагрузка|reboot|restart)\s*(компьютер|пк|машину|pc|computer)?",
     lambda t, m: I("power.reboot")),
    (r"(режим сна|усни|засни|sleep mode|suspend)\b",
     lambda t, m: I("power.sleep")),

    # ---- media ----
    (r"(громкость|звук|volume)\s*[:—-]?\s*(на\s+)?(\+|-|тише|громче|mute|выключи|без звука|\d{1,3})?",
     lambda t, m: _volume(t, m)),
    (r"(сделай громче|прибавь звук|volume up|увеличь громкость)",
     lambda t, m: I("media.volume", level="+10")),
    (r"(сделай тише|убавь звук|volume down|уменьшь громкость|потише)",
     lambda t, m: I("media.volume", level="-10")),
    (r"(выключи звук|без звука|заглуши|mute)", lambda t, m: I("media.volume", level="mute")),
    (r"(пауза|поставь на паузу|pause|останови (?:музыку|плеер))",
     lambda t, m: I("media.control", action="pause")),
    (r"(включи музыку|play music|возобнови|play\b|продолжи)",
     lambda t, m: I("media.control", action="play")),
    (r"(следующий трек|дальше|next track|переключи|next\b)",
     lambda t, m: I("media.control", action="next")),
    (r"(предыдущий трек|назад|previous|prev\b)",
     lambda t, m: I("media.control", action="prev")),
    (r"(скриншот|снимок экрана|screenshot|capture screen)",
     lambda t, m: I("screenshot")),

    # ---- clipboard ----
    (r"(скопируй|в буфер|copy to clipboard|clipboard set)\s*[:—-]?\s*(.+)",
     lambda t, m: I("clipboard.set", text=clean(m.group(2)))),
    (r"(что в буфере|покажи буфер|прочитай буфер|clipboard|paste buffer)",
     lambda t, m: I("clipboard.get")),

    # ---- shell ----
    (r"(выполни команду|запусти команду|run command|terminal command|в терминале)\s*[:—-]?\s*(.+)",
     lambda t, m: I("shell.run", command=clean(m.group(2)))),

    # ---- web search (before generic "open") ----
    (r"(найди в интернете|поищи в интернете|загугли|поиск в сети|search (?:the )?web|google|найди в (?:гугл|google|ютуб|youtube|гитхаб|github|яндекс|википедии)|(?:найди|поищи|ищи) на (?:ютуб|youtube|github|гитхаб|яндекс|википедии|wiki)|найди информацию|search for)\s*[:—-]?\s*(.*)",
     lambda t, m: _web_search(t, m)),

    # ---- files (before generic "open"/"show") ----
    (r"(найди файл|найти файл|поищи файл|где файл|find file|search file|найди документ)\s*[:—-]?\s*(.+)",
     lambda t, m: I("file.search", query=clean(m.group(2)))),
    (r"(покажи (?:содержимое )?папк[уи]|что в папке|list folder|list files|покажи файлы)\s*[:—-]?\s*(.*)",
     lambda t, m: I("file.list", path=clean(m.group(2)))),
    (r"(открой файл|открыть файл|открой папку|открыть папку|открой документ|запусти файл|запустить файл|покажи файл|open file|open folder|launch file)\s*[:—-]?\s*(.+)",
     lambda t, m: I("file.open", path=clean(m.group(2)))),
    (r"(прочитай файл|прочти файл|read file|покажи содержимое файла|прочитай документ)\s*[:—-]?\s*(.+)",
     lambda t, m: I("file.read", path=clean(m.group(2)))),
    (r"(создай файл|запиши в файл|write file|сохрани в файл)\s*[:—-]?\s*(.+)",
     lambda t, m: _write_file(m.group(2))),

    # ---- apps / folders / urls ----
    (r"(закрой|закрыть|close|kill)\s+(.+)", lambda t, m: I("app.close", target=clean(m.group(2)))),
    (r"(открой|открыть|запусти|запустить|покажи|open|launch|start)\s+(.+)",
     lambda t, m: I("app.open", target=clean(m.group(2)))),
]


def _settings(t: str, m: re.Match):
    verb = util.normalize(m.group(1))
    rest = clean(m.group(2))
    low = util.normalize(rest)
    enable = verb.startswith(("включ", "переключ", "установ", "измен", "смен", "enable", "set", "switch"))
    if any(w in low for w in ("озвучиван", "голос", "speak", "voice", "ответы вслух")):
        return I("config.set", key="озвучивание", value="включи" if enable and "выключ" not in verb else "выключи")
    if any(w in low for w in ("постоянн", "непрерывн", "continuous", "прослушиван", "микрофон")):
        return I("config.set", key="прослушивание", value="включи" if enable and "выключ" not in verb else "выключи")
    if any(w in low for w in ("английск", "english", "русск", "russian", "язык")):
        return I("config.set", key="язык", value="английский" if "англ" in low or "english" in low else "русский")
    if any(w in low for w in ("мозг", "нейросет", "llm", "модель")):
        return I("config.set", key="мозг", value="включи" if enable and "выключ" not in verb else "выключи")
    if any(w in low for w in ("команд", "терминал", "shell")):
        return I("config.set", key="команды", value="включи" if enable and "выключ" not in verb else "выключи")
    return None


def _remember(text: str):
    t = clean(text)
    name = re.search(r"(?:меня зовут|мо[ёе] имя|my name is)\s*([\wа-яё-]+)", t, re.I)
    if name:
        return I("memory.remember", key="имя", value=name.group(1).capitalize())
    if ":" in t or " — " in t:
        k, v = re.split(r"\s*[:—-]\s*", t, maxsplit=1)
        return I("memory.remember", key=k.strip(), value=v.strip())
    m = re.match(r"(.{1,40}?)\s+(?:это|равно|составляет|is|equals)\s+(.+)", t, re.I)
    if m:
        return I("memory.remember", key=m.group(1).strip(), value=m.group(2).strip())
    words = t.split()
    if len(words) > 3:
        return I("memory.remember", key=" ".join(words[:2]), value=" ".join(words[2:]))
    return I("memory.remember", key="факт", value=t)


def _reminder(t: str, m: re.Match):
    rest = clean(m.group(2) or "")
    seconds = util.parse_duration(t)
    if seconds is None:
        seconds = 300
    text = re.sub(
        r"(через\s+\d+\s*(?:секунд\w*|минут\w*|час\w*|сек|мин|ч|hours?|minutes?|seconds?|h|m|s)|"
        r"in\s+\d+\s*(?:hours?|minutes?|seconds?|h|m|s)|на\s+\d+\s*(?:минут\w*|час\w*|секунд\w*))",
        "", rest, flags=re.I)
    text = re.sub(r"^(что|о том, что|про то, что|to|about|that)\s+", "", text.strip(), flags=re.I)
    text = clean(text) or "Напоминание от Джарвиса"
    return I("reminder.set", seconds=seconds, text=text)


def _calc(t: str, m: re.Match):
    raw = clean(m.group(2) or "")
    if not raw:
        raw = re.sub(r"(посчитай|вычисли|calculate|сколько будет|реши)", "", t, flags=re.I)
    expr = to_expression(raw)
    return I("calc", expression=expr) if expr else None


def _volume(t: str, m: re.Match):
    val = (m.group(3) or "").strip()
    low = util.normalize(t)
    if re.search(r"(выключ\w*\s+звук|без звука|заглуши|тишина|mute)", low):
        return I("media.volume", level="mute")
    if "громче" in low or "прибав" in low or "увелич" in low:
        return I("media.volume", level="+10")
    if "тише" in low or "убав" in low or "уменьш" in low:
        return I("media.volume", level="-10")
    if not val or val in ("звук", "громкость"):
        return I("media.volume", level="+10")
    if val in ("mute", "выключи", "без звука", "тишина"):
        return I("media.volume", level="mute")
    if val in ("+", "-"):
        return I("media.volume", level=val + "10")
    return I("media.volume", level=val)


def _web_search(t: str, m: re.Match):
    query = clean(m.group(2) or "")
    if not query:
        query = re.sub(r"(найди в интернете|поищи в интернете|загугли|search for|google|поиск в сети)", "", t, flags=re.I)
        query = clean(query)
    low = util.normalize(t)
    engine = "google"
    for key, marker in (("youtube", ("ютуб", "youtube")), ("github", ("гитхаб", "github")),
                        ("yandex", ("яндекс", "yandex")), ("wikipedia", ("википед", "wikipedia")),
                        ("duckduckgo", ("duck", "дакдак"))):
        if any(x in low for x in marker):
            engine = key
            break
    return I("web.search", query=query, engine=engine) if query else None


def _write_file(raw: str):
    text = clean(raw)
    m = re.match(r"(.+?)\s+(?:с текстом|с содержимым|containing|with text)\s*[:—-]?\s*(.*)", text, re.I | re.S)
    if m:
        return I("file.write", path=clean(m.group(1)), content=m.group(2).strip() or "Создано Джарвисом")
    m = re.match(r"(\S+\.\w{1,6})\s+(.+)", text, re.S)
    if m:
        return I("file.write", path=m.group(1), content=m.group(2).strip())
    return I("file.write", path=text, content="Создано Джарвисом")


# ---------------------------------------------------------------- questions
QUESTION_MARKERS = re.compile(
    r"(\?$|^(почему|зачем|как|что такое|кто такой|когда|где|какой|какая|какие|чем|чего|можно ли|"
    r"объясни|расскажи|напиши|переведи|посоветуй|помоги|подскажи|сравни|придумай|составь|"
    r"what|why|how|when|where|who|which|explain|write|translate|suggest|help me|compare|"
    r"tell me|can you|do you know))", re.I)


def recognize(text: str, wake_word: str = "джарвис") -> list[Intent]:
    """Turn a phrase into a list of actions. Never empty."""
    raw = strip_wake(text or "", wake_word)
    t = clean(raw)
    if not t:
        return [I("chat.smalltalk", kind="unknown")]
    found = _find(RULES, t)
    if found:
        return found
    if QUESTION_MARKERS.search(t) or len(t.split()) >= 3:
        return [I("llm.ask", question=raw)]
    return [I("chat.smalltalk", kind="unknown")]
