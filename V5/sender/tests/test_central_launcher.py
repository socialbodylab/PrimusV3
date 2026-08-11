"""Tests for shared Central server discovery and attach helpers."""

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

        attached = central_launcher.try_attach_before_start(
            port=8080,
            frontend_path="/devices",
            no_browser=False,
            open_browser=_open,
            launcher_name="Device Manager",
        )
        self.assertTrue(attached)
        self.assertEqual(opened, [("http://127.0.0.1:8080/devices", True)])


class EvaluateServerTests(unittest.TestCase):
    """A launcher must not attach to a Central that cannot serve it."""

    PRIMUS = {"product": "primus", "frontends": central_launcher.FRONTEND_PATHS}

    def test_compatible_server_returns_none(self):
        self.assertIsNone(central_launcher.evaluate_server(
            self.PRIMUS, need_product="primus", needs_output=True))

    def test_wrong_product_is_rejected(self):
        mismatch = central_launcher.evaluate_server(
            self.PRIMUS, need_product="radius")
        self.assertEqual(mismatch["reason"], central_launcher.MISMATCH_WRONG_PRODUCT)
        self.assertEqual(mismatch["backend_product"], "primus")

    def test_monitor_only_rejected_when_output_needed(self):
        runtime = dict(self.PRIMUS, monitor_only=True)
        mismatch = central_launcher.evaluate_server(
            runtime, need_product="primus", needs_output=True)
        self.assertEqual(mismatch["reason"], central_launcher.MISMATCH_MONITOR_ONLY)

    def test_monitor_only_allowed_for_watchers(self):
        """DeviceManager only monitors, so a monitor-only backend suits it."""
        runtime = dict(self.PRIMUS, monitor_only=True)
        self.assertIsNone(central_launcher.evaluate_server(
            runtime, need_product="primus", needs_output=False))

    def test_no_requirements_accepts_anything(self):
        self.assertIsNone(central_launcher.evaluate_server(dict(self.PRIMUS)))


class AttachGuardTests(unittest.TestCase):
    MONITOR_ONLY = {
        "product": "primus",
        "monitor_only": True,
        "frontends": central_launcher.FRONTEND_PATHS,
    }

    def _attach(self, **kwargs):
        return central_launcher.try_attach_before_start(
            port=8080,
            frontend_path="/primus",
            no_browser=True,
            open_browser=lambda url, attach=False: "opened",
            launcher_name="PrimusCentral",
            **kwargs,
        )

    @patch("central_launcher.find_running_central_server")
    def test_mismatch_without_handler_refuses(self, mock_find):
        """Silent attach was the bug; the safe default is to refuse loudly."""
        mock_find.return_value = (8080, self.MONITOR_ONLY)
        with self.assertRaises(SystemExit):
            self._attach(need_product="primus", needs_output=True)

    @patch("central_launcher.find_running_central_server")
    def test_handler_can_request_start(self, mock_find):
        mock_find.return_value = (8080, self.MONITOR_ONLY)
        attached = self._attach(
            need_product="primus", needs_output=True,
            on_mismatch=lambda mismatch, port, runtime: "start")
        self.assertFalse(attached, "caller should start its own server")

    @patch("central_launcher.reserve_ui_session")
    @patch("central_launcher.find_running_central_server")
    def test_handler_can_allow_attach(self, mock_find, mock_reserve):
        mock_find.return_value = (8080, self.MONITOR_ONLY)
        attached = self._attach(
            need_product="primus", needs_output=True,
            on_mismatch=lambda mismatch, port, runtime: "attach")
        self.assertTrue(attached)

    @patch("central_launcher.notify")
    @patch("central_launcher.reserve_ui_session")
    @patch("central_launcher.find_running_central_server")
    def test_unraisable_window_notifies_the_user(self, mock_find, mock_reserve, mock_notify):
        """The original silent-launch bug: attached fine, but showed nothing."""
        mock_find.return_value = (8080, {
            "product": "primus", "frontends": central_launcher.FRONTEND_PATHS})
        central_launcher.try_attach_before_start(
            port=8080,
            frontend_path="/primus",
            no_browser=False,
            open_browser=lambda url, attach=False: "could not raise existing browser window",
            launcher_name="PrimusCentral",
            need_product="primus",
        )
        mock_notify.assert_called_once()
        self.assertIn("8080", mock_notify.call_args[0][1])

    @patch("central_launcher.notify")
    @patch("central_launcher.reserve_ui_session")
    @patch("central_launcher.find_running_central_server")
    def test_successful_raise_does_not_notify(self, mock_find, mock_reserve, mock_notify):
        mock_find.return_value = (8080, {
            "product": "primus", "frontends": central_launcher.FRONTEND_PATHS})
        central_launcher.try_attach_before_start(
            port=8080,
            frontend_path="/primus",
            no_browser=False,
            open_browser=lambda url, attach=False: "raised existing browser window",
            launcher_name="PrimusCentral",
            need_product="primus",
        )
        mock_notify.assert_not_called()

    @patch("central_launcher.reserve_ui_session")
    @patch("central_launcher.find_running_central_server")
    def test_attach_reserves_a_ui_session(self, mock_find, mock_reserve):
        """Otherwise the running Central can auto-quit before the browser opens."""
        mock_find.return_value = (8080, {
            "product": "primus", "frontends": central_launcher.FRONTEND_PATHS})
        self._attach(need_product="primus")
        mock_reserve.assert_called_once_with("127.0.0.1", 8080)


class RegistryCapabilityTests(unittest.TestCase):
    def test_registry_records_capabilities(self):
        """The registry must describe what the server can do, not just where."""
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = os.path.join(tmp, "central_server.json")
            with patch.object(central_launcher, "registry_write_paths", return_value=[registry_path]):
                with patch.object(central_launcher, "registry_read_paths", return_value=[registry_path]):
                    central_launcher.register_central_server(
                        8080, "primus", pid=99, monitor_only=True,
                        lan_enabled=True, app_version="0.97")
                    payload = central_launcher.read_registry()
        self.assertTrue(payload["monitor_only"])
        self.assertTrue(payload["lan_enabled"])
        self.assertEqual(payload["app_version"], "0.97")

    def test_registry_defaults_are_conservative(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = os.path.join(tmp, "central_server.json")
            with patch.object(central_launcher, "registry_write_paths", return_value=[registry_path]):
                with patch.object(central_launcher, "registry_read_paths", return_value=[registry_path]):
                    central_launcher.register_central_server(8080, "radius", pid=99)
                    payload = central_launcher.read_registry()
        self.assertFalse(payload["monitor_only"])
        self.assertFalse(payload["lan_enabled"])


if __name__ == "__main__":
    unittest.main()
