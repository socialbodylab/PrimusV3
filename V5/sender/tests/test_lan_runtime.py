"""Tests for DeviceManager LAN bind reporting in /api/runtime."""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server
import state as state_module
from state import ControllerState


def _get_runtime(base):
    with urllib.request.urlopen(f"{base}/api/runtime", timeout=5) as resp:
        return json.loads(resp.read().decode())


class LanRuntimeTests(unittest.TestCase):
    def setUp(self):
        # Keep the ControllerState off the real state files in V5/sender/.
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        state_path = os.path.join(scratch.name, ".primus_state.json")
        radius_path = os.path.join(scratch.name, ".radius_state.json")
        for target in (
            patch.object(state_module, "_state_file", return_value=state_path),
            patch.object(state_module.show_info_store, "primus_state_path",
                         return_value=state_path),
            patch.object(state_module.show_info_store, "radius_state_path",
                         return_value=radius_path),
        ):
            target.start()
            self.addCleanup(target.stop)
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
