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


if __name__ == "__main__":
    unittest.main()