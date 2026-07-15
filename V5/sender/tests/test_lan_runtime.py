"""Tests for DeviceManager LAN bind reporting in /api/runtime."""

import json
import os
import sys
import threading
import unittest
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server
from state import ControllerState


def _get_runtime(base):
    with urllib.request.urlopen(f"{base}/api/runtime", timeout=5) as resp:
        return json.loads(resp.read().decode())


class LanRuntimeTests(unittest.TestCase):
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

    def test_runtime_lan_enabled_defaults_false(self):
        runtime = _get_runtime(self.base)
        self.assertFalse(runtime["lan_enabled"])
        self.assertTrue(runtime["monitor_only"])

    def test_runtime_reports_lan_enabled_when_set(self):
        self.httpd.lan_enabled = True
        runtime = _get_runtime(self.base)
        self.assertTrue(runtime["lan_enabled"])


if __name__ == "__main__":
    unittest.main()
