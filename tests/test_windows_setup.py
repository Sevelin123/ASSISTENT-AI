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
        ):
            with self.subTest(file=rel):
                self.assertTrue((ROOT / rel).is_file(), f"missing {rel}")

    def test_powershell_utf8_bom_and_crlf(self):
        for rel in ("windows/setup.ps1", "windows/tray.ps1"):
            with self.subTest(file=rel):
                raw = (ROOT / rel).read_bytes()
                self.assertTrue(raw.startswith(b"\xef\xbb\xbf"),
                                "PowerShell 5.1 needs a UTF-8 BOM for Cyrillic")
                body = raw[3:]
                self.assertIn(b"\r\n", body)
                self.assertNotIn(b"\n", body.replace(b"\r\n", b""), "bare LF found")

    def test_batch_files_crlf_no_bom(self):
        for rel in ("INSTALL_WINDOWS.bat", "UNINSTALL_WINDOWS.bat", "start.bat"):
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
        self.assertIn("$sha", bat)                 # commit SHA handles branch names with '/'
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
            "Speech_OneCore", "VOICE-HELP.txt", "ms-settings:speech",
            "DISM /Online /Cleanup-Image /RestoreHealth", "Home Single Language",
        ]
        for m in markers:
            with self.subTest(marker=m):
                self.assertIn(m, ps, f"setup.ps1 is missing {m!r}")

    def test_tray_script_contents(self):
        ps = (ROOT / "windows/tray.ps1").read_text(encoding="utf-8-sig")
        for m in ("NotifyIcon", "ContextMenuStrip", "Перезапустить сервисы",
                  "api/status", "Application]::Run", "BalloonTip"):
            with self.subTest(marker=m):
                self.assertIn(m, ps)

    def test_no_legacy_new_object_in_ps(self):
        # New-Object with positional constructor args is fragile in PS 5.1.
        for rel in ("windows/setup.ps1", "windows/tray.ps1"):
            text = (ROOT / rel).read_text(encoding="utf-8-sig")
            self.assertNotIn("New-Object System.Drawing.", text)
            self.assertNotIn("New-Object System.Windows.Forms.Tool", text)


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
                      '"/install"', "/windows/README.md"):
            self.assertIn(route, src)

    def test_hud_links_to_install_page(self):
        html = (ROOT / "web/index.html").read_text(encoding="utf-8")
        self.assertIn('href="/install"', html)
        self.assertIn("НА МОЙ ПК", html)
        self.assertIn("boot-install", html)

    def test_install_page_has_permanent_github_link(self):
        page = (ROOT / "web/install.html").read_text(encoding="utf-8")
        self.assertIn("codeload.github.com", page)
        self.assertIn("refs/heads/arena/57b8f59e-assistent-ai", page)
        self.assertNotIn("/zip/6268dbe", page, "stale pinned SHA")
        self.assertIn("data-href-origin", page)  # works on cloud AND local installs

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
                       '"AppData", "Windows"', "endswith(\".exe\")"):
            with self.subTest(marker=marker):
                self.assertIn(marker, server)
                self.assertIn(marker, agent)

    def test_agent_is_standalone(self):
        agent = (ROOT / "jarvis_agent.py").read_text(encoding="utf-8")
        self.assertNotIn("from jarvis", agent)
        self.assertNotIn("import jarvis", agent)
        self.assertIn("class JarvisAgent", agent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
