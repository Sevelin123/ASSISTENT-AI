"""Tests for the automatic Windows installer (no Windows required to run)."""

from __future__ import annotations

import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestInstallerFiles(unittest.TestCase):
    def test_required_files_exist(self):
        for rel in (
            "INSTALL_WINDOWS.bat", "UNINSTALL_WINDOWS.bat",
            "windows/setup.ps1", "windows/tray.ps1", "windows/README.md",
            "START-HERE.html", "web/install.html", "START-JARVIS.bat",
            "FIX-SERVER.bat", "windows/fix-server.ps1",
            "SMART-MODE.bat", "JARVIS-APP.vbs", "windows/desktop.ps1",
            "windows/smart-mode.ps1", "windows/JARVIS-App.cs",
        ):
            with self.subTest(file=rel):
                self.assertTrue((ROOT / rel).is_file(), f"missing {rel}")

    def test_powershell_utf8_bom_and_crlf(self):
        for rel in ("windows/setup.ps1", "windows/tray.ps1", "windows/fix-server.ps1",
                   "windows/desktop.ps1", "windows/smart-mode.ps1"):
            with self.subTest(file=rel):
                raw = (ROOT / rel).read_bytes()
                self.assertTrue(raw.startswith(b"\xef\xbb\xbf"),
                                "PowerShell 5.1 needs a UTF-8 BOM for Cyrillic")
                body = raw[3:]
                self.assertIn(b"\r\n", body)
                self.assertNotIn(b"\n", body.replace(b"\r\n", b""), "bare LF found")

    def test_batch_files_crlf_no_bom(self):
        for rel in ("INSTALL_WINDOWS.bat", "UNINSTALL_WINDOWS.bat", "START-JARVIS.bat",
                   "FIX-SERVER.bat", "start.bat", "SMART-MODE.bat"):
            with self.subTest(file=rel):
                raw = (ROOT / rel).read_bytes()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
                self.assertIn(b"\r\n", raw)
                self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))

    def test_bat_launches_setup_with_bypass(self):
        bat = (ROOT / "INSTALL_WINDOWS.bat").read_text(encoding="utf-8")
        self.assertIn("-ExecutionPolicy Bypass", bat)
        self.assertIn("setup.ps1", bat)
        self.assertIn("codeload.github.com", bat)  # standalone fallback
        self.assertIn("arena/57b8f59e-assistent-ai", bat)
        self.assertIn("$a.commit.sha", bat)        # commit SHA handles branch names with '/'
        self.assertNotIn("$b='main'", bat, "main is the stale base commit, not the app")
        self.assertIn("START-JARVIS.bat", bat)
        self.assertIn("FIX-SERVER.bat", bat)
        self.assertIn("127.0.0.1:8080", bat)
        uninstall = (ROOT / "UNINSTALL_WINDOWS.bat").read_text(encoding="utf-8")
        self.assertIn("-Uninstall", uninstall)

    def test_setup_script_contents(self):
        ps = (ROOT / "windows/setup.ps1").read_text(encoding="utf-8-sig")
        markers = [
            "Resolve-Python", "Install-Python", "winget", "New-Shortcut",
            "start-background.vbs", "run-server.cmd", "run-agent.cmd",
            "Startup", "/api/health", "/api/agent/status", "jarvis.config.json",
            "ConvertTo-Crlf", "New-JarvisIcon", "-Uninstall", "-NoAutostart", "-Lan",
            "New-NetFirewallRule", "ru-RU", "Get-ChildItem $key", "repoSha",
            "defaultBranch = 'arena/57b8f59e-assistent-ai'", "refs/heads",
            "Speech_OneCore", "VOICE-HELP.txt", "ms-settings:speech",
            "DISM /Online /Cleanup-Image /RestoreHealth", "Home Single Language",
            "START-JARVIS.bat", "FIX-SERVER.bat", "fix-server.ps1",
            "SMART-MODE.bat", "JARVIS-APP.vbs", "JARVIS-APP.exe",
            "JARVIS-App.cs", "desktop.ps1", "smart-mode.ps1", "отдельное окно",
            "Починить связь с сервером", "Запустить сервер (видимое окно)",
            "API-ключ НЕ обязателен",
            "127.0.0.1", "$winSrc = Join-Path $AppDir 'windows'",
        ]
        for m in markers:
            with self.subTest(marker=m):
                self.assertIn(m, ps, f"setup.ps1 is missing {m!r}")

    def test_tray_script_contents(self):
        ps = (ROOT / "windows/tray.ps1").read_text(encoding="utf-8-sig")
        for m in ("NotifyIcon", "ContextMenuStrip", "Перезапустить сервисы",
                  "api/status", "Application]::Run", "BalloonTip",
                  "Open-JarvisApp", "JARVIS-APP.exe", "JARVIS-APP.vbs"):
            with self.subTest(marker=m):
                self.assertIn(m, ps)

    def test_no_legacy_new_object_in_ps(self):
        # New-Object with positional constructor args is fragile in PS 5.1.
        for rel in ("windows/setup.ps1", "windows/tray.ps1"):
            text = (ROOT / rel).read_text(encoding="utf-8-sig")
            self.assertNotIn("New-Object System.Drawing.", text)
            self.assertNotIn("New-Object System.Windows.Forms.Tool", text)


    def test_offline_start_here_is_self_contained(self):
        """The page inside the ZIP must work via file:// with no server."""
        page = (ROOT / "START-HERE.html").read_text(encoding="utf-8")
        for needle in ("502 BAD GATEWAY", "SANDBOX NOT FOUND",
                       "codeload.github.com/Sevelin123/ASSISTENT-AI/zip/refs/heads/arena/57b8f59e-assistent-ai",
                       "INSTALL_WINDOWS.bat", "http://127.0.0.1:8080",
                       "VOICE-HELP.txt", "START-HERE.html", "windows/README.md",
                       "START-JARVIS.bat", "FIX-SERVER.bat", "ERR_CONNECTION_REFUSED",
                       "server.err.log", "--no-proxy-server",
                       "Нужен ли API-ключ?", "platform.openai.com/api-keys",
                       "Ключ из Arena", "SMART-MODE.bat", "JARVIS-APP.exe",
                       "app-mode", "Не удается найти \"Steam\"", "shell:MyComputerFolder"):
            with self.subTest(needle=needle):
                self.assertIn(needle, page)
        self.assertNotIn('<link rel="stylesheet"', page)
        self.assertNotIn("<script", page)
        # Generic "https://8080-….e2b.app" text is OK; a real sandbox URL is not.
        import re
        self.assertIsNone(re.search(r"https://8080-[a-z0-9]{10,}", page),
                          "no hardcoded dead sandbox URL")
        self.assertNotIn("ij8lmut", page, "no stale sandbox id")

    def test_readme_has_permanent_link_and_502_help(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("codeload.github.com/Sevelin123/ASSISTENT-AI/zip/refs/heads/arena/57b8f59e-assistent-ai", readme)
        self.assertIn("START-HERE.html", readme)
        self.assertIn("502 BAD GATEWAY", readme)
        self.assertIn("Не удаётся связаться с сервером", readme)
        self.assertIn("START-JARVIS.bat", readme)
        self.assertIn("FIX-SERVER.bat", readme)
        self.assertIn("--no-proxy-server", readme)
        self.assertIn("Нужен ли API-ключ? НЕТ", readme)
        self.assertIn("console.groq.com/keys", readme)
        self.assertIn("Можно ли взять API-ключ из Arena?", readme)
        self.assertIn("JARVIS-APP.exe", readme)
        self.assertIn("SMART-MODE.bat", readme)
        self.assertIn("Открытие приложений, файлов и «Этот компьютер»", readme)
        self.assertIn("shell:MyComputerFolder", readme)

    def test_api_key_is_optional_everywhere(self):
        """The installer must never imply that an API key is required."""
        checks = {
            "README.md": ["Нужен ли API-ключ? НЕТ", "Ollama (рекомендую для РФ)",
                          "gptunnel.ru/v1", "proxyapi.ru/docs/openai-compatible-api"],
            "START-HERE.html": ["Нужен ли API-ключ?", "НЕТ, не нужен", "gptunnel.ru"],
            "web/install.html": ["Нужен ли API-ключ?", "НЕТ", "gptunnel.ru"],
            "windows/README.md": ["API-ключ: не обязателен", "gptunnel.ru/v1"],
            "windows/setup.ps1": ["API-ключ НЕ обязателен", "Создан jarvis.config.json (без API-ключей)"],
            "jarvis/server.py": ["API-КЛЮЧ НЕ ОБЯЗАТЕЛЕН", "Для РФ", "API-ключ НЕ обязателен"],
            "jarvis/brain.py": ["НЕ обязателен", "я ключи не выдаю"],
            "jarvis/nlu.py": ["FAQ: API key is optional"],
            "web/index.html": ["НЕОБЯЗАТЕЛЬНО", "API-ключ НЕ нужен", "gptunnel.ru"],
            "web/app.js": ["Ключ не задан", "Ollama выбран"],
            ".env.example": ["Всё необязательно", "API-КЛЮЧ НЕ ОБЯЗАТЕЛЕН", "Ключ из Arena"],
            "jarvis/router.py": ["smart_mode"],
            "web/app.js": ["btnSmartMode", "LOCAL LLM"],
            "web/install.html": ["Ключ из Arena", "JARVIS-APP.exe"],
            "windows/README.md": ["Ключ из Arena", "отдельное окно"],
        }
        for rel, needles in checks.items():
            text = (ROOT / rel).read_text(encoding="utf-8-sig" if rel.endswith(".ps1") else "utf-8")
            for needle in needles:
                with self.subTest(file=rel, needle=needle):
                    self.assertIn(needle, text)

    def test_llm_403_guidance_in_docs_and_ui(self):
        checks = {
            "README.md": ["HTTP 403 Forbidden", "brain_hint", "platform.openai.com/docs/guides/error-codes"],
            "START-HERE.html": ["HTTP 403 Forbidden", "OLLAMA_ORIGINS", "Работать оффлайн"],
            "web/install.html": ["403 Forbidden", "Работать оффлайн", "console.groq.com/docs/errors"],
            "windows/README.md": ["403 Forbidden", "ollama serve", "Host: localhost:11434"],
            "jarvis/server.py": ["403 Forbidden = провайдер запретил внешнюю модель"],
            "jarvis/brain.py": ["_friendly_error", "403 Forbidden: провайдер запретил доступ"],
            "jarvis/router.py": ["brain_hint"],
            "web/index.html": ["llmAlert", "403 Forbidden?", "btnLlmOff"],
            "web/styles.css": [".llm-alert", ".llm-alert-actions"],
            "web/app.js": ["goOffline", "llmAlertOffline", "ОШИБКА LLM"],
            ".env.example": ["403 Forbidden", "JARVIS_LLM_ENABLED=0"],
        }
        for rel, needles in checks.items():
            text = (ROOT / rel).read_text(encoding="utf-8-sig" if rel.endswith(".ps1") else "utf-8")
            for needle in needles:
                with self.subTest(file=rel, needle=needle):
                    self.assertIn(needle, text)

    def test_desktop_shell_is_a_real_app_window(self):
        setup = (ROOT / "windows/setup.ps1").read_text(encoding="utf-8-sig")
        for needle in ("JARVIS-APP.exe", "JARVIS-App.cs", "/target:winexe",
                       "System.Windows.Forms.dll", "JARVIS-APP.vbs",
                       "без вкладок браузера", "отдельное окно"):
            with self.subTest(needle=needle):
                self.assertIn(needle, setup)
        cs = (ROOT / "windows/JARVIS-App.cs").read_text(encoding="utf-8")
        for needle in ('--app=', '--user-data-dir=', 'jarvis.py --smart',
                       '/api/health', '127.0.0.1', 'msedge.exe', 'chrome.exe'):
            with self.subTest(needle=needle):
                self.assertIn(needle, cs)
        self.assertNotIn('sh.Run "http://', cs, "no plain browser-tab launch")
        desktop = (ROOT / "windows/desktop.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('--app=', desktop)
        self.assertIn('/api/health', desktop)
        self.assertIn('jarvis.py', desktop)
        vbs = (ROOT / "JARVIS-APP.vbs").read_text(encoding="utf-8")
        self.assertIn("windows\\desktop.ps1", vbs)
        self.assertIn("WindowStyle Hidden", vbs)

    def test_smart_mode_installs_local_ollama_without_arena_key(self):
        smart = (ROOT / "windows/smart-mode.ps1").read_text(encoding="utf-8-sig")
        for needle in ("Ollama.Ollama", "winget", "ollama pull", "/api/smart",
                       "Ключ из Arena не используется", "127.0.0.1:11434"):
            with self.subTest(needle=needle):
                self.assertIn(needle, smart)
        bat = (ROOT / "SMART-MODE.bat").read_text(encoding="utf-8")
        self.assertIn("smart-mode.ps1", bat)
        self.assertIn("Arena/session keys are NOT used", bat)
        self.assertIn("-InstallDir \"%~dp0.\"", bat)
        server = (ROOT / "jarvis/server.py").read_text(encoding="utf-8")
        self.assertIn("/api/smart", server)
        self.assertIn("КЛЮЧ ИЗ ARENA НЕ ИСПОЛЬЗУЕТСЯ", server)
        config = (ROOT / "jarvis/config.py").read_text(encoding="utf-8")
        self.assertIn("enable_local_ollama", config)
        self.assertIn("auto_local_llm", config)
        self.assertNotIn("ARENA_API_KEY", config, "no invented Arena credential")

    def test_visible_launcher_contents(self):
        bat = (ROOT / "START-JARVIS.bat").read_text(encoding="utf-8")
        for marker in ("py -3", "python", "jarvis.py", "--host 127.0.0.1",
                       "--port", "127.0.0.1:8080", "-Port 9000",
                       "DO NOT CLOSE", "leave THIS WINDOW OPEN",
                       "start http://127.0.0.1"):
            with self.subTest(marker=marker):
                self.assertIn(marker, bat)

    def test_fix_server_script_contents(self):
        ps = (ROOT / "windows/fix-server.ps1").read_text(encoding="utf-8-sig")
        for marker in ("Test-Health", "Resolve-PythonExe", "Get-NetTCPConnection",
                       "Start-JarvisServer", "Start-JarvisAgent", "jarvis.config.json",
                       "127.0.0.1", "/api/health", "-Port 9000", "logs",
                       "START-JARVIS.bat"):
            with self.subTest(marker=marker):
                self.assertIn(marker, ps)
        bat = (ROOT / "FIX-SERVER.bat").read_text(encoding="utf-8")
        self.assertIn("windows\\fix-server.ps1", bat)
        self.assertIn("-InstallDir", bat)
        self.assertIn("127.0.0.1:8080", bat)
        self.assertIn("START-JARVIS.bat", bat)

    def test_startup_prints_local_ipv4_not_localhost(self):
        server = (ROOT / "jarvis/server.py").read_text(encoding="utf-8")
        self.assertIn("ОТКРОЙТЕ НА ЭТОМ ПК", server)
        self.assertIn("http://127.0.0.1:", server)
        self.assertNotIn("HUD: http://localhost:", server)
        self.assertIn("START-JARVIS.bat", server)
        start = (ROOT / "start.bat").read_text(encoding="utf-8")
        self.assertIn("http://127.0.0.1:8080", start)
        self.assertNotIn("http://localhost:8080", start)
        self.assertIn("FIX-SERVER.bat", start)
        self.assertIn("START-JARVIS.bat", start)


class TestWindowsBundle(unittest.TestCase):
    def setUp(self):
        from jarvis.config import DATA_DIR
        self.zip_path = DATA_DIR / "JARVIS-Windows.zip"
        if self.zip_path.exists():
            self.zip_path.unlink()

    def tearDown(self):
        if self.zip_path.exists():
            self.zip_path.unlink()

    def test_bundle_is_complete_and_clean(self):
        from jarvis.server import build_windows_bundle

        path = build_windows_bundle()
        self.assertTrue(path.is_file() and path.stat().st_size > 10000)
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            for needed in (
                "JARVIS-Windows/README-WINDOWS.txt",
                "JARVIS-Windows/START-HERE.html",
                "JARVIS-Windows/START-JARVIS.bat",
                "JARVIS-Windows/FIX-SERVER.bat",
                "JARVIS-Windows/SMART-MODE.bat",
                "JARVIS-Windows/JARVIS-APP.vbs",
                "JARVIS-Windows/windows/JARVIS-App.cs",
                "JARVIS-Windows/windows/desktop.ps1",
                "JARVIS-Windows/windows/smart-mode.ps1",
                "JARVIS-Windows/windows/fix-server.ps1",
                "JARVIS-Windows/INSTALL_WINDOWS.bat",
                "JARVIS-Windows/UNINSTALL_WINDOWS.bat",
                "JARVIS-Windows/windows/setup.ps1",
                "JARVIS-Windows/windows/tray.ps1",
                "JARVIS-Windows/windows/README.md",
                "JARVIS-Windows/jarvis.py",
                "JARVIS-Windows/jarvis_agent.py",
                "JARVIS-Windows/web/index.html",
                "JARVIS-Windows/web/install.html",
                "JARVIS-Windows/web/app.js",
                "JARVIS-Windows/jarvis/server.py",
                "JARVIS-Windows/tests/test_core.py",
            ):
                with self.subTest(needed=needed):
                    self.assertIn(needed, names)
            for forbidden in (".git/", ".jarvis_data/", "jarvis.config.json", "__pycache__"):
                with self.subTest(forbidden=forbidden):
                    self.assertFalse(any(forbidden in n for n in names),
                                     f"bundle leaks {forbidden}")
            readme = z.read("JARVIS-Windows/README-WINDOWS.txt").decode("utf-8")
            self.assertIn("INSTALL_WINDOWS.bat", readme)
            self.assertIn("START-HERE.html", readme)
            self.assertIn("502 BAD GATEWAY", readme)
            self.assertIn("START-JARVIS.bat", readme)
            self.assertIn("FIX-SERVER.bat", readme)
            self.assertIn("API-КЛЮЧ НЕ ОБЯЗАТЕЛЕН", readme)
            self.assertIn("Для РФ", readme)
            self.assertIn("403 Forbidden", readme)
            self.assertIn("Работать оффлайн", readme)
            self.assertIn("КЛЮЧ ИЗ ARENA НЕ ИСПОЛЬЗУЕТСЯ", readme)
            self.assertIn("SMART-MODE.bat", readme)
            self.assertIn("JARVIS-APP.exe", readme)
            self.assertIn("ФАЙЛЫ, «ЭТОТ КОМПЬЮТЕР» И ПРИЛОЖЕНИЯ", readme)
            self.assertIn("shell:MyComputerFolder", readme)
            self.assertIn("Steam", readme)
            self.assertTrue(z.testzip() is None)

    def test_bundle_is_cached(self):
        from jarvis.server import build_windows_bundle
        first = build_windows_bundle()
        mtime = first.stat().st_mtime_ns
        second = build_windows_bundle()
        self.assertEqual(first, second)
        self.assertEqual(mtime, second.stat().st_mtime_ns)

    def test_server_routes_registered(self):
        src = (ROOT / "jarvis/server.py").read_text(encoding="utf-8")
        for route in ("/download/JARVIS-Windows.zip", "/download/INSTALL_WINDOWS.bat",
                      "/download/windows/", "/download/UNINSTALL_WINDOWS.bat",
                      '"/install"', "/windows/README.md",
                      "/start-here", "/START-HERE.html",
                      "/download/START-JARVIS.bat", "/download/FIX-SERVER.bat",
                      "/download/windows/", "fix-server.ps1",
                      "/SMART-MODE.bat", "/JARVIS-APP.vbs",
                      "desktop.ps1", "smart-mode.ps1", "JARVIS-App.cs",
                      "/api/smart"):
            self.assertIn(route, src)

    def test_hud_links_to_install_page(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        self.assertIn('href="/install"', html)
        self.assertIn("НА МОЙ ПК", html)
        self.assertIn("boot-install", html)
        self.assertIn('href="/START-HERE.html"', html)
        self.assertIn("OFFLINE-ИНСТРУКЦИЯ", html)
        self.assertIn('href="/download/START-JARVIS.bat"', html)
        self.assertIn('href="/download/FIX-SERVER.bat"', html)
        self.assertIn('id="serverAlert"', html)
        self.assertIn("НЕОБЯЗАТЕЛЬНО", html)
        self.assertIn('id="btnSmartMode"', html)
        self.assertIn("Ключ из Arena", html)

    def test_install_page_has_permanent_github_link(self):
        page = (ROOT / "web/install.html").read_text(encoding="utf-8")
        self.assertIn("codeload.github.com", page)
        self.assertIn("refs/heads/arena/57b8f59e-assistent-ai", page)
        self.assertNotIn("/zip/6268dbe", page, "stale pinned SHA")
        self.assertIn("data-href-origin", page)  # works on cloud AND local installs
        self.assertIn("502 BAD GATEWAY", page)
        self.assertIn("START-HERE.html", page)
        self.assertIn("ERR_CONNECTION_REFUSED", page)
        self.assertIn("START-JARVIS.bat", page)
        self.assertIn("FIX-SERVER.bat", page)
        self.assertIn("--no-proxy-server", page)
        self.assertIn("Нужен ли API-ключ?", page)
        self.assertIn("Как открыть файлы, «Этот компьютер» и приложения?", page)
        self.assertIn("shell:MyComputerFolder", page)
        self.assertIn("Можно ли взять API-ключ из Arena?", page)
        self.assertIn("JARVIS-APP.exe", page)
        self.assertNotIn("http://localhost:8080", page, "local URL must stay 127.0.0.1")

    def test_russian_voice_troubleshooting_everywhere(self):
        """The 'voice won't install' answer must exist in HUD, FAQ, README and installer."""
        js = (ROOT / "web/app.js").read_text(encoding="utf-8")
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        page = (ROOT / "web/install.html").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for marker in ("voiceDiag", "refreshVoices", "voiceschanged",
                       "ms-settings:speech", "isRuVoice", "btnVoiceTest"):
            self.assertIn(marker, js, f"app.js missing {marker}")
        self.assertIn('id="voiceDiag"', html)
        self.assertIn('id="btnVoiceRefresh"', html)
        for marker in ("Home Single Language", "DISM /Online /Cleanup-Image /RestoreHealth",
                       "sfc /scannow", "Set-WinUserLanguageList", "Online (Natural)",
                       "Text-to-speech", "полностью"):
            self.assertIn(marker, page, f"install FAQ missing {marker}")
        self.assertIn("Русский язык/голос не ставится", readme)
        self.assertIn("VOICE-HELP.txt", readme)


class TestWindowsNativeActions(unittest.TestCase):
    def test_server_and_agent_stay_in_sync(self):
        server = (ROOT / "jarvis/skills/local_ops.py").read_text(encoding="utf-8")
        agent = (ROOT / "jarvis_agent.py").read_text(encoding="utf-8")
        for marker in ("os.startfile", "[Console]::In.ReadToEnd() | Set-Clipboard",
                       '"AppData", "Windows"', "endswith(\".exe\")",
                       "Get-StartApps", "shell:MyComputerFolder", "App Paths",
                       "computer.open", "file.open", "POWERSHELL_FIND_APP",
                       "_can_shell_open", "JARVIS_APP_QUERY"):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)
                self.assertIn(marker, agent)

    def test_windows_app_lookup_uses_system_sources(self):
        server = (ROOT / "jarvis/skills/local_ops.py").read_text(encoding="utf-8")
        agent = (ROOT / "jarvis_agent.py").read_text(encoding="utf-8")
        for needle in ("Get-StartApps", "App Paths", "*.lnk", "DisplayName",
                       "shell:AppsFolder", "Get-Command -Name $q -CommandType Application",
                       "Не удается найти"):
            for text in (server, agent):
                with self.subTest(needle=needle, file="local_ops/agent"):
                    self.assertIn(needle, text)

    def test_open_actions_are_documented(self):
        checks = {
            "README.md": ["Открытие приложений, файлов и «Этот компьютер»",
                          "shell:MyComputerFolder", "Steam", "37 действий"],
            "START-HERE.html": ["Не удается найти \"Steam\"", "shell:MyComputerFolder",
                                "открой файл report.docx"],
            "web/install.html": ["Не удается найти \"Steam\"", "shell:MyComputerFolder",
                                  "открой этот компьютер"],
            "windows/README.md": ["Открытие файлов, «Этот компьютер» и приложений",
                                   "App Paths", "37 действий"],
            "jarvis/server.py": ["ФАЙЛЫ, «ЭТОТ КОМПЬЮТЕР» И ПРИЛОЖЕНИЯ",
                                  "shell:MyComputerFolder", "cmd/start"],
            "web/app.js": ["Этот компьютер", "Запусти Steam", "открой файл отчёт.docx"],
        }
        for rel, needles in checks.items():
            text = (ROOT / rel).read_text(encoding="utf-8")
            for needle in needles:
                with self.subTest(file=rel, needle=needle):
                    self.assertIn(needle, text)

    def test_agent_is_standalone(self):
        agent = (ROOT / "jarvis_agent.py").read_text(encoding="utf-8")
        self.assertNotIn("from jarvis", agent)
        self.assertNotIn("import jarvis", agent)
        self.assertIn("class JarvisAgent", agent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
