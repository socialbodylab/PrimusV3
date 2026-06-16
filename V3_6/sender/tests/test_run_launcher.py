import os
import sys
import tempfile
import unittest
from unittest import mock

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import run


class RunLauncherTests(unittest.TestCase):
    def test_open_browser_uses_dedicated_launcher_when_available(self):
        with mock.patch.object(run, "_launch_dedicated_browser", return_value="opened test app window"):
            with mock.patch.object(run.webbrowser, "open_new") as open_new:
                result = run._open_browser("http://127.0.0.1:8080")

        self.assertEqual(result, "opened test app window")
        open_new.assert_not_called()

    def test_open_browser_falls_back_to_default_browser(self):
        with mock.patch.object(run, "_launch_dedicated_browser", return_value=None):
            with mock.patch.object(run.webbrowser, "open_new") as open_new:
                result = run._open_browser("http://127.0.0.1:8080")

        self.assertEqual(result, "opened default browser")
        open_new.assert_called_once_with("http://127.0.0.1:8080")

    def test_dedicated_launcher_uses_fresh_app_profile(self):
        class FakeProcess:
            pid = 12345

        with tempfile.TemporaryDirectory() as tmpdir:
            profile_root = os.path.join(tmpdir, "profiles")
            with mock.patch.object(run, "_browser_profile_root", return_value=profile_root):
                with mock.patch.object(run, "_cleanup_dedicated_browser_profiles") as cleanup:
                    with mock.patch.object(run, "_chromium_browser_candidates", return_value=[("Test Chrome", "/fake/chrome")]):
                        with mock.patch.object(run.subprocess, "Popen", return_value=FakeProcess()) as popen:
                            result = run._launch_dedicated_browser("http://127.0.0.1:8080")

        self.assertEqual(result, "opened Test Chrome app window")
        cleanup.assert_called_once_with(profile_root)
        args = popen.call_args.args[0]
        self.assertEqual(args[0], "/fake/chrome")
        self.assertIn("--app=http://127.0.0.1:8080", args)
        profile_args = [arg for arg in args if arg.startswith("--user-data-dir=")]
        self.assertEqual(len(profile_args), 1)
        self.assertIn(os.path.join("profiles", "profile-"), profile_args[0])

    def test_ui_lifecycle_monitor_shutdown_after_window_close(self):
        class FakeServer:
            ui_lifecycle_enabled = True
            ui_lifecycle_started_at = 90.0
            ui_last_heartbeat = 99.0
            ui_close_requested_at = 100.0
            controller_state = None

            def __init__(self):
                self.shutdown_called = False

            def shutdown(self):
                self.shutdown_called = True
                self.ui_lifecycle_enabled = False

        server = FakeServer()
        with mock.patch.object(run.time, "monotonic", return_value=103.0), \
                mock.patch.object(run.time, "sleep"), \
                mock.patch("builtins.print"):
            run._ui_lifecycle_monitor(server)

        self.assertTrue(server.shutdown_called)
        self.assertFalse(server.ui_lifecycle_enabled)

    def test_ui_has_live_output_true_for_controller(self):
        class FakeState:
            playback_source = run.ControllerState.SOURCE_CONTROLLER

        class FakeServer:
            controller_state = FakeState()

        self.assertTrue(run._ui_has_live_output(FakeServer()))

    def test_ui_has_live_output_false_for_idle(self):
        class FakeState:
            playback_source = run.ControllerState.SOURCE_IDLE

        class FakeServer:
            controller_state = FakeState()

        self.assertFalse(run._ui_has_live_output(FakeServer()))

    def test_ui_lifecycle_monitor_defers_heartbeat_shutdown_during_live_output(self):
        class FakeState:
            playback_source = run.ControllerState.SOURCE_CONTROLLER

        class FakeServer:
            ui_lifecycle_enabled = True
            ui_lifecycle_started_at = 90.0
            ui_last_heartbeat = 100.0
            ui_close_requested_at = None
            controller_state = FakeState()

            def __init__(self):
                self.shutdown_called = False

            def shutdown(self):
                self.shutdown_called = True
                self.ui_lifecycle_enabled = False

        server = FakeServer()
        times = iter([146.1, 146.35, 146.6])

        def fake_monotonic():
            value = next(times)
            if value >= 146.6:
                server.ui_lifecycle_enabled = False
            return value

        with mock.patch.object(run.time, "monotonic", side_effect=fake_monotonic), \
                mock.patch.object(run.time, "sleep"), \
                mock.patch("builtins.print"):
            run._ui_lifecycle_monitor(server)

        self.assertFalse(server.shutdown_called)
        self.assertGreater(server.ui_last_heartbeat, 100.0)

    def test_ui_lifecycle_monitor_shutdown_after_heartbeat_timeout_when_idle(self):
        class FakeState:
            playback_source = run.ControllerState.SOURCE_IDLE

        class FakeServer:
            ui_lifecycle_enabled = True
            ui_lifecycle_started_at = 90.0
            ui_last_heartbeat = 100.0
            ui_close_requested_at = None
            controller_state = FakeState()

            def __init__(self):
                self.shutdown_called = False

            def shutdown(self):
                self.shutdown_called = True
                self.ui_lifecycle_enabled = False

        server = FakeServer()
        with mock.patch.object(run.time, "monotonic", return_value=146.1), \
                mock.patch.object(run.time, "sleep"), \
                mock.patch("builtins.print"):
            run._ui_lifecycle_monitor(server)

        self.assertTrue(server.shutdown_called)
        self.assertFalse(server.ui_lifecycle_enabled)


if __name__ == "__main__":
    unittest.main()