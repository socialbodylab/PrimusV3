"""Tests for dedicated-browser attach behavior and UI focus socket."""

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import browser_launcher
import central_launcher
import run_primus
from ui_focus import UiFocusServer, request_ui_focus


class BrowserAttachTests(unittest.TestCase):
    def setUp(self):
        self.browser = browser_launcher.DedicatedBrowser("test-browser-profiles")

    def test_open_attach_raises_existing_window(self):
        with mock.patch.object(self.browser, "focus", return_value=True), \
             mock.patch.object(self.browser, "launch") as launch:
            result = self.browser.open("http://127.0.0.1:8080/devices", attach=True)

        self.assertEqual(result, "raised existing browser window")
        launch.assert_not_called()

    def test_open_attach_never_launches_when_tracked_browser_exists(self):
        with mock.patch.object(self.browser, "focus", return_value=False), \
             mock.patch.object(self.browser, "has_tracked_browser", return_value=True), \
             mock.patch.object(self.browser, "launch") as launch:
            result = self.browser.open("http://127.0.0.1:8080/devices", attach=True)

        self.assertEqual(result, "using existing browser window")
        launch.assert_not_called()

    def test_open_attach_launches_when_no_window_exists(self):
        # Attach means "make this frontend visible": with no window of our
        # own to focus, we must open one. The old behavior (report failure,
        # open nothing) made a windowed launcher attaching a different
        # frontend look exactly like a crashed app.
        with mock.patch.object(self.browser, "focus", return_value=False), \
             mock.patch.object(self.browser, "has_tracked_browser", return_value=False), \
             mock.patch.object(self.browser, "launch",
                               return_value="opened dedicated window") as launch, \
             mock.patch.object(browser_launcher.webbrowser, "open_new") as open_new:
            result = self.browser.open("http://127.0.0.1:8080/devices", attach=True)

        self.assertEqual(result, "opened dedicated window")
        launch.assert_called_once_with("http://127.0.0.1:8080/devices", cleanup_stale=True)
        open_new.assert_not_called()

    def test_open_attach_falls_back_to_default_browser(self):
        with mock.patch.object(self.browser, "focus", return_value=False), \
             mock.patch.object(self.browser, "has_tracked_browser", return_value=False), \
             mock.patch.object(self.browser, "launch", return_value=None), \
             mock.patch.object(browser_launcher.webbrowser, "open_new") as open_new:
            result = self.browser.open("http://127.0.0.1:8080/devices", attach=True)

        self.assertEqual(result, "opened default browser")
        open_new.assert_called_once_with("http://127.0.0.1:8080/devices")

    def test_resolve_profile_dir_reuses_tracked_profile_on_attach(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracked = os.path.join(tmp, "profile-tracked")
            os.makedirs(tracked, exist_ok=True)
            with open(os.path.join(tmp, browser_launcher.PROFILE_MARKER), "w", encoding="utf-8") as marker:
                marker.write(tracked)

            resolved = self.browser._resolve_profile_dir(tmp, cleanup_stale=False)

        self.assertEqual(resolved, tracked)

    def test_run_primus_open_browser_delegates(self):
        with mock.patch.object(run_primus._dedicated_browser, "open", return_value="raised existing browser window") as open_fn:
            result = run_primus._open_browser("http://127.0.0.1:8080/devices", attach=True)

        self.assertEqual(result, "raised existing browser window")
        open_fn.assert_called_once_with("http://127.0.0.1:8080/devices", attach=True)


class UiFocusTests(unittest.TestCase):
    def test_request_ui_focus_when_socket_missing_returns_false(self):
        with mock.patch("ui_focus.request_ui_focus_http", return_value=False), \
             mock.patch("ui_focus.activation_socket_path", return_value="/nonexistent/path.sock"):
            self.assertFalse(request_ui_focus(8080))

    def test_request_ui_focus_prefers_http(self):
        with mock.patch("ui_focus.request_ui_focus_http", return_value=True) as http_focus, \
             mock.patch("ui_focus.request_ui_focus_socket") as socket_focus:
            self.assertTrue(request_ui_focus(8080, host="127.0.0.1"))
        http_focus.assert_called_once_with("127.0.0.1", 8080)
        socket_focus.assert_not_called()

    def test_request_ui_focus_http(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.getcode.return_value = 200
            from ui_focus import request_ui_focus_http
            self.assertTrue(request_ui_focus_http("127.0.0.1", 8080))

    def test_ui_focus_server_invokes_callback(self):
        seen = []
        port = 8123
        with tempfile.TemporaryDirectory() as tmp:
            socket_path = os.path.join(tmp, "focus.sock")
            with mock.patch("ui_focus.activation_socket_path", return_value=socket_path):
                server = UiFocusServer(port, lambda: seen.append(True))
                thread = threading.Thread(target=server._run, daemon=True)
                thread.start()
                time.sleep(0.05)
                self.assertTrue(request_ui_focus(port))
                time.sleep(0.05)
                server.stop()
                thread.join(timeout=1.0)
        self.assertEqual(seen, [True])

    def test_try_attach_uses_ui_focus_before_open_browser(self):
        open_browser = mock.Mock()
        with mock.patch.object(central_launcher, "find_running_central_server", return_value=(8080, {"product": "primus"})), \
             mock.patch.object(central_launcher, "request_ui_focus", return_value=True) as focus, \
             mock.patch("builtins.print"):
            attached = central_launcher.try_attach_before_start(
                port=8080,
                frontend_path="/devices",
                no_browser=False,
                open_browser=open_browser,
                launcher_name="Device Manager",
            )

        self.assertTrue(attached)
        focus.assert_called_once_with(8080, host="127.0.0.1")
        open_browser.assert_not_called()

    def test_try_attach_local_focus_when_remote_focus_fails(self):
        open_browser = mock.Mock(return_value="raised existing browser window")
        with mock.patch.object(central_launcher, "find_running_central_server", return_value=(8080, {"product": "primus"})), \
             mock.patch.object(central_launcher, "request_ui_focus", return_value=False), \
             mock.patch("builtins.print"):
            attached = central_launcher.try_attach_before_start(
                port=8080,
                frontend_path="/devices",
                no_browser=False,
                open_browser=open_browser,
                launcher_name="Device Manager",
            )

        self.assertTrue(attached)
        open_browser.assert_called_once_with("http://127.0.0.1:8080/devices", attach=True)


if __name__ == "__main__":
    unittest.main()
