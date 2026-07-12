"""Tests for shared Central server discovery and attach helpers."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import central_launcher


class CentralLauncherTests(unittest.TestCase):
    def test_frontend_path_for(self):
        self.assertEqual(central_launcher.frontend_path_for(None, "primus"), "/primus")
        self.assertEqual(central_launcher.frontend_path_for("devices", "primus"), "/devices")
        self.assertEqual(central_launcher.frontend_path_for(None, "radius"), "/radius")

    def test_build_central_url(self):
        self.assertEqual(
            central_launcher.build_central_url(8080, "/devices"),
            "http://127.0.0.1:8080/devices",
        )

    @patch("central_launcher.urllib.request.urlopen")
    def test_probe_central_server_accepts_runtime_payload(self, mock_urlopen):
        payload = {
            "product": "primus",
            "frontends": {"primus": "/primus", "radius": "/radius", "devices": "/devices"},
        }
        mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        runtime = central_launcher.probe_central_server("127.0.0.1", 8080)
        self.assertEqual(runtime["product"], "primus")

    @patch("central_launcher.urllib.request.urlopen")
    def test_probe_central_server_rejects_non_central_payload(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps({"ok": True}).encode()
        self.assertIsNone(central_launcher.probe_central_server("127.0.0.1", 8080))

    def test_register_and_read_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = os.path.join(tmp, "central_server.json")
            with patch.object(central_launcher, "registry_write_paths", return_value=[registry_path]):
                with patch.object(central_launcher, "registry_read_paths", return_value=[registry_path]):
                    central_launcher.register_central_server(8099, "primus", pid=4242)
                    payload = central_launcher.read_registry()
            self.assertEqual(payload["port"], 8099)
            self.assertEqual(payload["product"], "primus")
            self.assertEqual(payload["pid"], 4242)

    @patch("central_launcher.probe_central_server")
    @patch("central_launcher.read_registry")
    def test_find_running_central_server_checks_registry_port(self, mock_read, mock_probe):
        mock_read.return_value = {"port": 8099}
        mock_probe.side_effect = lambda host, port, timeout=0.75: (
            {"product": "radius", "frontends": central_launcher.FRONTEND_PATHS}
            if port == 8099 else None
        )
        found = central_launcher.find_running_central_server(8080)
        self.assertEqual(found[0], 8099)
        self.assertEqual(found[1]["product"], "radius")

    @patch("central_launcher.find_running_central_server")
    def test_try_attach_before_start_opens_view(self, mock_find):
        mock_find.return_value = (8080, {"product": "primus", "frontends": central_launcher.FRONTEND_PATHS})
        opened = []

        def _open(url, attach=False):
            opened.append((url, attach))
            return "opened"

        with contextlib.redirect_stdout(io.StringIO()):
            attached = central_launcher.try_attach_before_start(
                port=8080,
                frontend_path="/devices",
                no_browser=False,
                open_browser=_open,
                launcher_name="Device Manager",
            )
        self.assertTrue(attached)
        self.assertEqual(opened, [("http://127.0.0.1:8080/devices", True)])


if __name__ == "__main__":
    unittest.main()
