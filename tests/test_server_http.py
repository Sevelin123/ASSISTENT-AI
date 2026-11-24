"""Live HTTP smoke tests against an ephemeral in-process server.

These catch the class of breakage that makes a browser preview look dead even
though GET works: unsupported HEAD, missing CORS, or a HEAD probe hanging on SSE.
"""

from __future__ import annotations

import http.client
import json
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class TestHTTPContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from jarvis.config import ConfigStore
        from jarvis.server import JarvisApp, Server
        import jarvis.config as cfgmod

        cls._orig_cfg = cfgmod.CONFIG_FILE
        cls._tmp = Path(ROOT / ".jarvis_data")
        cls._tmp.mkdir(exist_ok=True)
        cfgmod.CONFIG_FILE = cls._tmp / "http-test-config.json"

        cls.app = JarvisApp(ConfigStore())
        cls.srv = Server(("127.0.0.1", 0), cls.app)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever,
                                      kwargs={"poll_interval": 0.1}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.thread.join(timeout=5)
        import jarvis.config as cfgmod
        cfgmod.CONFIG_FILE = cls._orig_cfg
        p = cls._tmp / "http-test-config.json"
        if p.exists():
            p.unlink()

    def request(self, method: str, path: str, timeout: float = 5.0):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            conn.request(method, path)
            r = conn.getresponse()
            body = r.read()
            return r.status, dict(r.getheaders()), body
        finally:
            conn.close()

    def test_head_root(self):
        status, headers, body = self.request("HEAD", "/")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")

    def test_head_api_health(self):
        status, headers, body = self.request("HEAD", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        # HEAD advertises what GET would return but sends no body.
        self.assertGreater(int(headers.get("Content-Length", "0")), 0)

    def test_head_sse_does_not_hang(self):
        status, headers, body = self.request("HEAD", "/api/events", timeout=4)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        self.assertEqual(headers.get("Content-Length"), "0")

    def test_head_unknown_is_404(self):
        status, _, body = self.request("HEAD", "/api/does-not-exist")
        self.assertEqual(status, 404)
        self.assertEqual(body, b"")

    def test_get_health_still_returns_json(self):
        status, _, body = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["version"], "1.0.0")

    def test_get_hud_and_static(self):
        for path, needle in (("/", b"J.A.R.V.I.S."), ("/styles.css", b":root"),
                             ("/app.js", b"SpeechRecognition")):
            with self.subTest(path=path):
                status, _, body = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertIn(needle, body)

    def test_install_page(self):
        for path in ("/install", "/install.html"):
            with self.subTest(path=path):
                status, headers, body = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertIn("text/html", headers.get("Content-Type", ""))
                for needle in (b"INSTALL_WINDOWS.bat", b"JARVIS-Windows.zip",
                               b"jarvis_agent.py", b"127.0.0.1:8080",
                               b"Home Single Language", b"ms-settings:speech",
                               b"502 BAD GATEWAY", b"START-HERE.html",
                               b"ERR_CONNECTION_REFUSED", b"FIX-SERVER.bat"):
                    self.assertIn(needle, body)
        status, _, body = self.request("HEAD", "/install")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")

    def test_offline_start_here_page(self):
        for path in ("/start-here", "/START-HERE.html", "/start", "/offline"):
            with self.subTest(path=path):
                status, headers, body = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertIn("text/html", headers.get("Content-Type", ""))
                for needle in (b"502 BAD GATEWAY", b"INSTALL_WINDOWS.bat",
                               b"codeload.github.com", b"START-HERE.html",
                               b"127.0.0.1:8080", b"FIX-SERVER.bat",
                               b"ERR_CONNECTION_REFUSED"):
                    self.assertIn(needle, body)
        status, _, body = self.request("HEAD", "/start-here")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")

    def test_fix_server_download_routes(self):
        for path, needle in (("/download/FIX-SERVER.bat", b"fix-server.ps1"),
                             ("/download/windows/fix-server.ps1", b"Test-Health")):
            with self.subTest(path=path):
                status, _, body = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertIn(needle, body)

    def test_hud_has_connection_alert(self):
        status, _, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b'id="serverAlert"', body)
        self.assertIn(b"FIX-SERVER.bat", body)
        status, _, js = self.request("GET", "/app.js")
        self.assertEqual(status, 200)
        for needle in (b"serverDiagnosis", b"showServerAlert", b"hideServerAlert",
                       b"127.0.0.1:8080", b"e2b.app"):
            self.assertIn(needle, js)

    def test_windows_readme_route(self):
        status, _, body = self.request("GET", "/windows/README.md")
        self.assertEqual(status, 200)
        self.assertIn(b"INSTALL_WINDOWS.bat", body)
        self.assertIn(b"START-HERE.html", body)

    def test_options_preflight(self):
        status, headers, _ = self.request("OPTIONS", "/api/chat")
        self.assertEqual(status, 204)
        self.assertIn("HEAD", headers.get("Access-Control-Allow-Methods", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
