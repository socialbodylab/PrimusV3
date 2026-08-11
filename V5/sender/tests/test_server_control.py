"""Tests for the Central server control surface (/api/server/*).

These endpoints exist so a launcher can inspect a running Central and ask it to
step aside. The stop guard is the important part: another app must never be able
to black out a show that is mid-cue.
"""

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server
from state import ControllerState


def _get_json(base, path):
    with urllib.request.urlopen(f"{base}{path}", timeout=5) as resp:
        return json.loads(resp.read().decode())


def _post_json(base, path, payload):
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


class ServerStatusTests(unittest.TestCase):
    def setUp(self):
        self.state = ControllerState(fps_listener=None, monitor_only=True)
        self.httpd = server.create_server("127.0.0.1", 0, self.state)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_status_reports_identity_and_capabilities(self):
        status = _get_json(self.base, "/api/server/status")
        self.assertEqual(status["pid"], os.getpid())
        self.assertEqual(status["port"], self.port)
        self.assertTrue(status["monitor_only"])
        self.assertIn("app_version", status)
        self.assertIn("client_session_count", status)

    def test_status_reports_no_live_output_without_a_predicate(self):
        status = _get_json(self.base, "/api/server/status")
        self.assertFalse(status["live_output"])

    def test_status_reflects_live_output_predicate(self):
        self.httpd.live_output_fn = lambda srv: True
        status = _get_json(self.base, "/api/server/status")
        self.assertTrue(status["live_output"])

    def test_broken_predicate_is_treated_as_live(self):
        """Never report idle on error -- that would permit a stop mid-show."""
        def _boom(srv):
            raise RuntimeError("nope")

        self.httpd.live_output_fn = _boom
        status = _get_json(self.base, "/api/server/status")
        self.assertTrue(status["live_output"])


class ServerStopTests(unittest.TestCase):
    def setUp(self):
        self.state = ControllerState(fps_listener=None, monitor_only=True)
        self.httpd = server.create_server("127.0.0.1", 0, self.state)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.stopped = False

    def tearDown(self):
        if not self.stopped:
            self.httpd.shutdown()
        self.httpd.server_close()

    def test_stop_refused_while_output_is_live(self):
        self.httpd.live_output_fn = lambda srv: True
        status, body = _post_json(self.base, "/api/server/stop", {})
        self.assertEqual(status, 409)
        self.assertIn("driving output", body.get("error", ""))

    def test_force_overrides_the_live_output_guard(self):
        self.httpd.live_output_fn = lambda srv: True
        status, body = _post_json(self.base, "/api/server/stop", {"force": True})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.stopped = True
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive(), "server should have shut down")

    def test_stop_succeeds_when_idle(self):
        status, body = _post_json(self.base, "/api/server/stop", {})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.stopped = True
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
