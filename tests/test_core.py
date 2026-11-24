"""Dependency-free unit tests:  python -m unittest discover -s tests -v"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jarvis import nlu, util  # noqa: E402
from jarvis import skills  # noqa: E402
from jarvis.brain import Brain  # noqa: E402
from jarvis.config import Config, ConfigStore  # noqa: E402
from jarvis.hub import AgentHub  # noqa: E402
from jarvis.memory import Memory  # noqa: E402
from jarvis.router import Router  # noqa: E402
from jarvis.skills import base, local_ops  # noqa: E402


class TestNLU(unittest.TestCase):
    CASES = [
        ("Джарвис, который час?", "system.time"),
        ("открой youtube.com", "app.open"),
        ("запусти блокнот", "app.open"),
        ("загугли рецепт пасты", "web.search"),
        ("найди на YouTube лекции по физике", "web.search"),
        ("посчитай 15 процентов от 240", "calc"),
        ("добавь задачу позвонить маме", "task.add"),
        ("список дел", "task.list"),
        ("напомни через 5 минут размяться", "reminder.set"),
        ("запомни, что меня зовут Тони", "memory.remember"),
        ("что ты умеешь", "chat.help"),
        ("покажи заметки", "note.list"),
        ("сделай скриншот", "screenshot"),
        ("найди файл отчёт", "file.search"),
        ("покажи папку загрузки", "file.list"),
        ("выключи озвучивание", "config.set"),
        ("громкость 40", "media.volume"),
        ("выключи компьютер", "power.shutdown"),
        ("привет", "chat.smalltalk"),
        ("объясни, что такое нейросеть", "llm.ask"),
        ("what time is it", "system.time"),
        ("open youtube.com", "app.open"),
    ]

    def test_intents(self):
        for phrase, want in self.CASES:
            with self.subTest(phrase=phrase):
                got = nlu.recognize(phrase)[0].action
                self.assertEqual(got, want, f"{phrase!r} → {got}, expected {want}")

    def test_wake_word_stripped(self):
        intent = nlu.recognize("Джарвис, открой блокнот", "джарвис")[0]
        self.assertEqual(intent.action, "app.open")
        self.assertEqual(intent.args["target"], "блокнот")

    def test_no_empty_result(self):
        for phrase in ("", "   ", "???", "абракадабра"):
            self.assertTrue(nlu.recognize(phrase))

    def test_math_expression(self):
        self.assertEqual(nlu.to_expression("2 плюс 2 умножить на 10"), "2+2*10")
        self.assertIn("sqrt", nlu.to_expression("корень из 144"))


class TestUtil(unittest.TestCase):
    def test_safe_eval(self):
        self.assertEqual(util.safe_eval("2+2*10"), 22)
        self.assertEqual(util.safe_eval("15*0.01*240"), 36)
        self.assertEqual(util.safe_eval("sqrt(144)"), 12)
        self.assertEqual(util.safe_eval("2**10"), 1024)
        with self.assertRaises(Exception):
            util.safe_eval("__import__('os').system('echo hacked')")

    def test_duration(self):
        self.assertEqual(util.parse_duration("через 5 минут"), 300)
        self.assertEqual(util.parse_duration("через 30 секунд"), 30)
        self.assertEqual(util.parse_duration("in 2 hours"), 7200)

    def test_normalize(self):
        self.assertEqual(util.normalize("Привет, Ёжик!"), "привет ежик")

    def test_safe_path(self):
        root = Path(tempfile.gettempdir()).resolve()
        self.assertEqual(util.safe_path(root, "test.txt"), root / "test.txt")
        with self.assertRaises(PermissionError):
            util.safe_path(root, "/etc/passwd")


class TestMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.mem = Memory(Path(self.tmp.name))

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_notes_tasks_facts(self):
        nid = self.mem.add_note("купить молоко")
        tid = self.mem.add_task("позвонить")
        self.mem.remember("имя", "Тони")
        self.assertEqual(self.mem.notes()[0]["text"], "купить молоко")
        self.assertEqual(len(self.mem.tasks()), 1)
        ok, text = self.mem.done_task(tid)
        self.assertTrue(ok)
        self.assertEqual(text, "позвонить")
        self.assertEqual(self.mem.tasks(), [])
        self.assertEqual(self.mem.recall("имя"), {"имя": "Тони"})
        self.assertTrue(self.mem.delete_note(nid))

    def test_history(self):
        self.mem.add_message("user", "привет")
        self.mem.add_message("assistant", "здравствуйте")
        self.assertEqual([m["role"] for m in self.mem.history()], ["user", "assistant"])
        self.mem.clear_history()
        self.assertEqual(self.mem.history(), [])


class TestSkills(unittest.TestCase):
    def setUp(self):
        # Redirect config persistence to a temp file so tests never touch the repo.
        import jarvis.config as cfgmod
        self.orig = cfgmod.CONFIG_FILE
        self.tmpdir = tempfile.TemporaryDirectory()
        cfgmod.CONFIG_FILE = Path(self.tmpdir.name) / "config.json"
        self.cfg = ConfigStore()
        self.mem = Memory(Path(self.tmpdir.name) / "mem.db")
        self.hub = AgentHub(token="")
        self.brain = Brain(self.cfg, self.mem)
        self.ctx = skills.SkillContext(self.cfg, self.mem, self.hub, self.brain)

    def tearDown(self):
        import jarvis.config as cfgmod
        cfgmod.CONFIG_FILE = self.orig
        self.tmpdir.cleanup()

    def test_calc(self):
        r = skills.execute("calc", {"expression": "2+2*10"}, self.ctx)
        self.assertTrue(r.ok)
        self.assertEqual(r.data["value"], 22)

    def test_notes_and_tasks(self):
        self.assertTrue(skills.execute("note.add", {"text": "идея"}, self.ctx).ok)
        self.assertIn("идея", skills.execute("note.list", {}, self.ctx).message)
        self.assertTrue(skills.execute("task.add", {"text": "сделать"}, self.ctx).ok)
        self.assertIn("сделать", skills.execute("task.list", {}, self.ctx).message)

    def test_danger_requires_confirm(self):
        self.cfg.update({"allow_power": True})
        r = skills.execute("power.shutdown", {}, self.ctx)
        self.assertFalse(r.ok)
        self.assertTrue(r.data.get("needs_confirmation"))

    def test_safety_gate_blocks_power(self):
        r = skills.execute("power.shutdown", {}, self.ctx)
        self.assertFalse(r.ok)
        self.assertIn("запрещено", r.message.lower())

    def test_power_never_runs_on_server_without_agent(self):
        self.cfg.update({"allow_power": True})
        self.ctx.confirmed = True
        r = skills.execute("power.shutdown", {}, self.ctx)
        self.assertTrue(r.ok)
        self.assertEqual(r.target, "none")
        self.assertTrue(r.data.get("simulated"))

    def test_shell_gated(self):
        r = skills.execute("shell.run", {"command": "echo hi"}, self.ctx)
        self.assertFalse(r.ok)
        self.assertIn("запрещено", r.message.lower())

    def test_client_action_demo_fallback(self):
        r = skills.execute("system.time", {}, self.ctx)
        self.assertTrue(r.ok)
        self.assertEqual(r.target, "demo")
        self.assertIn("Сейчас", r.message)

    def test_registry_integrity(self):
        for name, spec in base.ACTIONS.items():
            with self.subTest(name=name):
                self.assertEqual(name, spec.name)
                self.assertIn(spec.target, ("server", "client"))
                self.assertTrue(spec.description)
        for name in skills.SERVER_HANDLERS:
            self.assertIn(name, base.ACTIONS)
        for name in local_ops.HANDLERS:
            self.assertIn(name, base.ACTIONS)


class TestRouter(unittest.TestCase):
    def setUp(self):
        import jarvis.config as cfgmod
        self.orig = cfgmod.CONFIG_FILE
        self.tmpdir = tempfile.TemporaryDirectory()
        cfgmod.CONFIG_FILE = Path(self.tmpdir.name) / "c.json"
        self.cfg = ConfigStore()
        self.mem = Memory(Path(self.tmpdir.name) / "m.db")
        self.hub = AgentHub(token="")
        self.router = Router(self.cfg, self.mem, self.hub, Brain(self.cfg, self.mem))

    def tearDown(self):
        import jarvis.config as cfgmod
        cfgmod.CONFIG_FILE = self.orig
        self.tmpdir.cleanup()

    def test_basic_chat(self):
        out = self.router.process("посчитай 2+2", source="test")
        self.assertIn("4", out["reply"])
        self.assertEqual(out["actions"][0]["name"], "calc")

    def test_confirmation_flow(self):
        out = self.router.process("выключи компьютер", source="test")
        # power is gated off, so no pending is created; check the refusal instead.
        self.assertFalse(out["pending"])
        self.assertIn("запрещено", out["reply"].lower() or "")
        self.cfg.update({"allow_power": True})
        out2 = self.router.process("выключи компьютер", source="test")
        self.assertTrue(out2["pending"])
        out3 = self.router.process("подтверждаю", source="test")
        self.assertTrue(out3["actions"][0]["ok"] or "система отклонила" in out3["reply"].lower())

    def test_cancel_flow(self):
        self.cfg.update({"allow_power": True})
        self.router.process("перезагрузи компьютер", source="test")
        out = self.router.process("отмена", source="test")
        self.assertFalse(out["pending"])

    def test_memory_roundtrip(self):
        self.router.process("запомни, что меня зовут Тони", source="test")
        out = self.router.process("что ты помнишь", source="test")
        self.assertIn("Тони", out["reply"])

    def test_status(self):
        s = self.router.status()
        self.assertEqual(s["brain"], "offline")
        self.assertGreater(s["actions"], 30)


class TestLocalOps(unittest.TestCase):
    def test_time(self):
        r = local_ops.execute("system.time", {}, {"sandbox_root": str(Path.home())})
        self.assertTrue(r["ok"])
        self.assertIn("Сейчас", r["message"])

    def test_status(self):
        r = local_ops.execute("system.status", {}, {"sandbox_root": str(Path.home())})
        self.assertTrue(r["ok"])
        self.assertIn("memory", r["data"])

    def test_unknown(self):
        r = local_ops.execute("no.such.action", {}, {})
        self.assertFalse(r["ok"])

    def test_shell_blocked_by_default(self):
        r = local_ops.execute("shell.run", {"command": "echo hi"}, {})
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
