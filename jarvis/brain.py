"""The 'brain': optional OpenAI-compatible LLM + a real offline fallback.

Works with OpenAI, Groq, OpenRouter, Together, LM Studio, Ollama, vLLM —
anything that speaks /chat/completions. With no key and no local server the
assistant stays fully functional through nlu.py and this knowledge base.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from . import nlu, util
from .skills import base


PERSONA = {
    "jarvis": "Ты ДЖАРВИС — невозмутимый, ироничный, предельно компетентный ИИ-ассистент"
              " в духе помощника Тони Старка. Обращайся к пользователю «сэр» изредка,"
              " говори кратко, уверенно, по делу. Отвечай на языке пользователя.",
    "neutral": "Ты вежливый и полезный голосовой ассистент. Отвечай кратко и по делу на языке пользователя.",
    "concise": "Ты лаконичный ассистент. Отвечай одной-двумя фразами, без лишних слов.",
}

PLAN_PROMPT = """{persona}

Ты управляешь компьютером пользователя голосом. Твоя задача — понять фразу и вернуть ТОЛЬКО валидный JSON без пояснений и без markdown:
{{"reply": "короткий ответ, который будет озвучен", "actions": [{{"name": "действие", "args": {{}}}}]}}

Доступные действия (используй ТОЛЬКО имена из списка):
{actions}

Правила:
- Если фраза — просьба выполнить действие, добавь его в actions. reply — короткое подтверждение, БЕЗ дублирования результата действия.
- Если фраза — вопрос, обычно actions пустой, а reply содержит ответ. Можно добавить действие, если оно нужно для ответа (например system.time на вопрос «который час»).
- Аргументы — только те, что описаны у действия. Не выдумывай действий.
- Опасные действия (shell.run, power.*) добавляй только при явной просьбе; система сама запросит подтверждение.
- reply: максимум 2–3 коротких предложения, без списков и markdown. Ответ будет прочитан вслух.
- Язык ответа: {lang}.

Факты о пользователе: {facts}
История диалога (последние реплики): {history}
"""

ANSWER_PROMPT = """{persona}

Ответь на вопрос пользователя. Коротко, по существу, без markdown-разметки и без списков,
потому что ответ будет озвучен вслух. Если не знаешь точного ответа — честно скажи об этом
и предложи конкретный следующий шаг. Язык ответа: {lang}.

Факты о пользователе: {facts}
История: {history}
"""

OFFLINE_KB = [
    (r"(что такое|кто такой|объясни|расскажи про|define|what is)\s+(?:такой\s+)?(искусственн\w+ интеллект|ии|ai|нейросет\w*|машинн\w+ обучени[ея])",
     "Искусственный интеллект — это область информатики, где модели обучаются на данных и решают задачи, "
     "раньше требовавшие человека: понимание речи, зрения, текста и принятие решений. "
     "Нейросети — один из таких инструментов: слои искусственных нейронов учатся выделять закономерности."),
    (r"(что такое|объясни|what is)\s+(python|пайтон)",
     "Python — интерпретируемый язык программирования с простым синтаксисом. "
     "Его используют для автоматизации, анализа данных, веб-сервисов и ИИ. Именно на нём написан я."),
    (r"(что такое|объясни|what is)\s+(api|апи)",
     "API — программный интерфейс: набор правил, по которым одна программа обращается к другой. "
     "Например, я общаюсь с языковой моделью через HTTP API метода /chat/completions."),
    (r"(что такое|объясни|what is)\s+(ollama|оллама|llm|языковая модель)",
     "Языковая модель — нейросеть, предсказывающая следующее слово в тексте. "
     "Ollama запускает такие модели локально на вашем компьютере, без облака и ключа. "
     "Укажите в настройках адрес http://localhost:11434/v1 — и я стану заметно сообразительнее."),
    (r"(погод[ауе]|weather|температур[ау] на улице)",
     "Прогноз погоды требует внешнего сервиса. Скажите «найди в интернете погода» — открою поиск, "
     "либо подключите языковую модель с доступом к сети в настройках."),
    (r"(курс (доллара|евро|валют)|crypto|биткоин|акции|цен[аы] на)",
     "Без подключённого источника данных я не назову актуальную цену. "
     "Могу открыть поиск: скажите «найди в интернете курс доллара»."),
    (r"(как (мне )?(сделать|решить|написать|создать|запустить)|помоги (мне )?с|подскажи|посоветуй|help me)",
     None),  # generated plan
    (r"(переведи|translate|напиши (текст|письмо|код)|сочини|придумай (рассказ|стих))",
     "Для качественного перевода и генерации текстов нужна языковая модель. "
     "Откройте настройки и укажите API-ключ или адрес локальной Ollama — "
     "тогда я буду отвечать на любые свободные вопросы полноценно."),
]


class Brain:
    def __init__(self, config_store, memory):
        self.config = config_store
        self.memory = memory
        self.last_error = ""

    @property
    def mode(self) -> str:
        return "llm" if self.config.get().brain_available else "offline"

    # ------------------------------------------------------------ LLM plumbing
    def _chat(self, system: str, user: str, max_tokens: int = 600) -> str | None:
        cfg = self.config.get()
        url = cfg.llm_base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": cfg.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.5,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if cfg.llm_api_key:
            headers["Authorization"] = "Bearer " + cfg.llm_api_key
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=cfg.llm_timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
            data = json.loads(raw)
            return (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {util.truncate(str(exc), 140)}"
            return None

    def _context(self, history: list[dict], limit: int = 6) -> tuple[str, str]:
        cfg = self.config.get()
        facts = self.memory.recall()
        if cfg.user_name:
            facts.setdefault("имя", cfg.user_name)
        facts_s = ", ".join(f"{k}: {v}" for k, v in list(facts.items())[:8]) or "пока нет"
        hist = " | ".join(f"{h['role']}: {util.truncate(h['text'], 120)}" for h in history[-limit:]) or "пусто"
        return facts_s, hist

    # ------------------------------------------------------------ planning
    def plan(self, text: str, history: list[dict]) -> tuple[str | None, list[nlu.Intent]]:
        """Return (spoken_reply, actions) or (None, []) to defer to the NLU."""
        if not self.config.get().brain_available:
            return None, []
        cfg = self.config.get()
        facts, hist = self._context(history)
        system = PLAN_PROMPT.format(
            persona=PERSONA.get(cfg.persona, PERSONA["jarvis"]),
            actions=base.describe_for_llm(), lang="русском" if cfg.lang.startswith("ru") else "английском",
            facts=facts, history=hist,
        )
        raw = self._chat(system, text, max_tokens=600)
        if not raw:
            return None, []
        parsed = self._parse_json(raw)
        if not parsed:
            return None, []
        reply = str(parsed.get("reply") or "").strip()
        actions: list[nlu.Intent] = []
        for item in parsed.get("actions") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name not in base.ACTIONS:
                continue
            args = item.get("args") if isinstance(item.get("args"), dict) else {}
            actions.append(nlu.Intent(name, dict(args)))
        return reply or None, actions

    @staticmethod
    def _parse_json(raw: str) -> dict | None:
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
        try:
            d = json.loads(raw)
            return d if isinstance(d, dict) else None
        except json.JSONDecodeError:
            pass
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            try:
                d = json.loads(m.group(0))
                return d if isinstance(d, dict) else None
            except json.JSONDecodeError:
                return None
        return None

    # ------------------------------------------------------------ free-form Q&A
    def answer(self, question: str, history: list[dict] | None = None) -> str:
        history = history or []
        if self.config.get().brain_available:
            cfg = self.config.get()
            facts, hist = self._context(history)
            system = ANSWER_PROMPT.format(
                persona=PERSONA.get(cfg.persona, PERSONA["jarvis"]),
                lang="русском" if cfg.lang.startswith("ru") else "английском",
                facts=facts, history=hist,
            )
            out = self._chat(system, question, max_tokens=700)
            if out:
                return re.sub(r"[*_`#>]", "", out).strip()
            return (f"Языковая модель недоступна ({self.last_error}). "
                    "Продолжаю работать в оффлайн-режиме: команды ПК, заметки и расчёты выполняются как обычно.")
        return self.offline_answer(question)

    def offline_answer(self, question: str) -> str:
        q = util.normalize(question)
        for pattern, answer in OFFLINE_KB:
            if re.search(pattern, q, re.I):
                if answer is None:
                    return self._plan_for(question)
                return answer
        # Generic, honest fallback with a useful decomposition of the task.
        if re.search(r"(как|почему|зачем|объясни|расскажи|what|why|how)", q):
            return self._plan_for(question)
        return ("Я вас услышал, но без подключённой языковой модели могу лишь выполнять команды, "
                "а не отвечать на свободные вопросы. Откройте настройки и добавьте API-ключ "
                "или адрес локальной Ollama — либо скажите «что ты умеешь», чтобы увидеть все команды.")

    @staticmethod
    def _plan_for(question: str) -> str:
        topic = re.sub(
            r"^(как\s+(мне\s+)?(сделать|решить|написать|создать|запустить)|помоги\s+(мне\s+)?с|"
            r"подскажи|посоветуй|расскажи|объясни|что такое|how do i|how to|help me)\s*",
            "", util.normalize(question)).strip(" ?.,")
        topic = util.truncate(topic or "эту задачу", 60)
        return (f"Разложим задачу «{topic}» на шаги. Сначала уточним цель и исходные данные, "
                "затем разобьём работу на небольшие проверяемые этапы, выполним первый из них "
                "и зафиксируем результат в заметках. Скажите «добавь задачу …», чтобы я сохранил план, "
                "или подключите языковую модель для подробного разбора.")
