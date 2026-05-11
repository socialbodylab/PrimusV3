import os
import sys
import tempfile
import unittest
from unittest import mock

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import paths


class PathsTests(unittest.TestCase):
    def setUp(self):
        self._old_data_dir = os.environ.get(paths.DATA_DIR_ENV)
        self._old_use_app_data = os.environ.get(paths.USE_APP_DATA_ENV)
        os.environ.pop(paths.DATA_DIR_ENV, None)
        os.environ.pop(paths.USE_APP_DATA_ENV, None)

    def tearDown(self):
        if self._old_data_dir is None:
            os.environ.pop(paths.DATA_DIR_ENV, None)
        else:
            os.environ[paths.DATA_DIR_ENV] = self._old_data_dir
        if self._old_use_app_data is None:
            os.environ.pop(paths.USE_APP_DATA_ENV, None)
        else:
            os.environ[paths.USE_APP_DATA_ENV] = self._old_use_app_data

    def test_source_mode_uses_sender_directory_for_data(self):
        self.assertFalse(paths.uses_app_data_dir())
        self.assertEqual(paths.data_dir(), paths.sender_dir())
        self.assertEqual(paths.state_file(), os.path.join(paths.sender_dir(), ".primus_state.json"))

    def test_web_dir_resolves_static_resources(self):
        self.assertTrue(os.path.isfile(os.path.join(paths.web_dir(), "index.html")))

    def test_env_data_dir_seeds_writable_runtime_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ[paths.DATA_DIR_ENV] = tmpdir
            paths.ensure_runtime_data()

            self.assertEqual(paths.data_dir(), tmpdir)
            self.assertTrue(os.path.isdir(paths.clips_dir()))
            self.assertTrue(os.path.isdir(paths.looks_dir()))
            self.assertTrue(os.path.isdir(paths.logs_dir()))
            self.assertTrue(os.path.isfile(paths.cues_file()))

            with open(paths.cues_file(), "r") as f:
                cues_text = f.read()
            self.assertIn("cues", cues_text)

    def test_runtime_seed_does_not_overwrite_existing_cues(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ[paths.DATA_DIR_ENV] = tmpdir
            os.makedirs(tmpdir, exist_ok=True)
            with open(os.path.join(tmpdir, "cues.json"), "w") as f:
                f.write('{"cues":[{"number":99}]}')

            paths.ensure_runtime_data()

            with open(paths.cues_file(), "r") as f:
                cues_text = f.read()
            self.assertIn("99", cues_text)

    def test_windows_app_data_dir_uses_appdata(self):
        with mock.patch.object(paths.sys, "platform", "win32"):
            with mock.patch.object(paths.os, "name", "nt"):
                with mock.patch.dict(paths.os.environ, {"APPDATA": r"C:\\Users\\Tester\\AppData\\Roaming"}, clear=False):
                    expected = os.path.join(
                        r"C:\\Users\\Tester\\AppData\\Roaming",
                        "PrimusV3", "V3_5", "sender")
                    self.assertEqual(paths._default_app_data_dir(), expected)


if __name__ == "__main__":
    unittest.main()