"""T-0191: was der lokale Dashboard-Server ausliefert und wer ihn steuern darf.

Zwei Luecken, beide nur auf dem eigenen Rechner sichtbar und deshalb lange
unbemerkt:

1. Der Handler lieferte die gesamte Projektwurzel aus -- inklusive `.git/`,
   `data/manual_pool_tips.json` (Klarnamen und Tipps der Mitspieler) und
   `src/wm_tipps/rounds_local.py` (die privaten Runden-Slugs). Mit
   `serve-dashboard --host 0.0.0.0` liegt das im LAN offen.
2. `POST /api/run-command` prueft weder Origin noch Content-Type. Ein `fetch`
   mit `text/plain` von einer beliebigen fremden Seite ist ein simple request:
   der Browser schickt ihn ohne Preflight ab, samt Cookies, und startet damit
   Pipeline-Kommandos.

Der zweite Teil laeuft gegen einen echten Server auf 127.0.0.1 -- eine reine
Funktionspruefung wuerde nicht zeigen, ob der Riegel im HTTP-Pfad wirklich
greift. Es wird KEIN Kommando ausgefuehrt: die Anfragen werden vorher
abgewiesen, und der erlaubte Fall nutzt einen unbekannten Kommandonamen.
"""
from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wm_tipps.dashboard_server import (  # noqa: E402
    DashboardRequestHandler,
    is_allowed_path,
)


class AllowedPathTests(unittest.TestCase):
    def test_dashboard_assets_are_served(self):
        for path in (
            "/",
            "/index.html",
            "/data/dashboard.json",
            "/data/rival_lab.json",
            "/data/player_board.json",
            "/assets/app.js",
            "/assets/styles.css",
            "/assets/app.js?v=2",
        ):
            with self.subTest(path=path):
                self.assertTrue(is_allowed_path(path))

    def test_private_and_repo_internals_are_not_served(self):
        for path in (
            "/.git/config",
            "/data/manual_pool_tips.json",
            "/data/manual_standings.json",
            "/data/manual_bonus_tips.json",
            "/src/wm_tipps/rounds_local.py",
            "/STATE.md",
            "/data/predictions.json",
            "/assets/../data/manual_pool_tips.json",
            "/assets/secret.txt",
        ):
            with self.subTest(path=path):
                self.assertFalse(is_allowed_path(path))


class _QuietHandler(DashboardRequestHandler):
    """Wie der echte Handler, nur ohne Zugriffslog -- sonst rauscht jeder
    Suite-Lauf mit HTTP-Zeilen zu."""

    def log_message(self, *args, **kwargs) -> None:  # noqa: D102
        return


class _ServerFixture:
    """Echter Server auf einem freien Port, nur fuer die Dauer eines Tests."""

    def __enter__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _QuietHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"


def _post(fixture, *, origin=None, content_type="application/json", body=None):
    request = urllib.request.Request(
        fixture.url("/api/run-command"),
        data=json.dumps(body if body is not None else {"command": "gibt-es-nicht"}).encode(),
        method="POST",
    )
    request.add_header("Content-Type", content_type)
    if origin:
        request.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode() or "{}")


class LiveServerTests(unittest.TestCase):
    def test_private_file_is_not_reachable_over_http(self):
        with _ServerFixture() as fixture:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(fixture.url("/data/manual_pool_tips.json"), timeout=10)
            self.assertEqual(caught.exception.code, 404)

    def test_cross_site_post_is_refused(self):
        with _ServerFixture() as fixture:
            status, payload = _post(fixture, origin="https://fremde-seite.example")
            self.assertEqual(status, 403)
            self.assertFalse(payload["ok"])

    def test_plain_text_post_is_refused(self):
        """Der Content-Type, den ein Browser ohne Preflight erlaubt.

        Der Test prueft die BEGRUENDUNG, nicht nur den Status: ein unbekanntes
        Kommando antwortet ebenfalls mit 400, deshalb wuerde ein reiner
        Status-Vergleich auch dann gruen bleiben, wenn der Riegel fehlt
        (in der Negativprobe genau so passiert).

        Der Body nennt bewusst KEIN echtes Kommando. Faellt der Riegel weg,
        soll die Anfrage bei der Kommando-Pruefung stehenbleiben und nicht
        eine Pipeline starten -- ein Test darf keinen Produktivlauf ausloesen.
        """
        with _ServerFixture() as fixture:
            status, payload = _post(
                fixture, content_type="text/plain", body={"command": "gibt-es-nicht"}
            )
            self.assertEqual(status, 400)
            self.assertFalse(payload["ok"])
            self.assertIn("Content-Type", payload["error"])

    def test_local_json_post_reaches_the_command_lookup(self):
        """Der erlaubte Weg kommt durch -- bis zur Kommando-Pruefung, die den
        unbekannten Namen ablehnt. Kein Kommando wird ausgefuehrt."""
        with _ServerFixture() as fixture:
            status, payload = _post(fixture, origin=fixture.url(""))
            self.assertEqual(status, 400)
            self.assertIn("Unbekanntes Kommando", payload["error"])


if __name__ == "__main__":
    unittest.main()
