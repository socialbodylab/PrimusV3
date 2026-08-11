"""Tests for launcher_dialog fallback behaviour.

The dialogs exist for packaged windowed apps that have no console. Everywhere
else -- source runs, CI, headless -- they must degrade to printing and returning
the default rather than blocking on a prompt nobody can see.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import launcher_dialog


class DialogSuppressionTests(unittest.TestCase):
    def setUp(self):
        self._env = os.environ.get(launcher_dialog.SUPPRESS_ENV)
        os.environ[launcher_dialog.SUPPRESS_ENV] = "1"

    def tearDown(self):
        if self._env is None:
            os.environ.pop(launcher_dialog.SUPPRESS_ENV, None)
        else:
            os.environ[launcher_dialog.SUPPRESS_ENV] = self._env

    def test_dialogs_unavailable_when_suppressed(self):
        self.assertFalse(launcher_dialog.dialogs_available())

    def test_choose_returns_default_without_subprocess(self):
        with patch.object(launcher_dialog.subprocess, "run") as mock_run:
            choice = launcher_dialog.choose(
                "PrimusCentral", "message", ["Restart", "Read-only", "Cancel"], "Cancel")
        self.assertEqual(choice, "Cancel")
        mock_run.assert_not_called()

    def test_notify_does_not_raise(self):
        self.assertFalse(launcher_dialog.notify("PrimusCentral", "message"))


class DialogArgumentTests(unittest.TestCase):
    def test_choose_falls_back_when_default_not_in_buttons(self):
        os.environ[launcher_dialog.SUPPRESS_ENV] = "1"
        try:
            choice = launcher_dialog.choose("t", "m", ["A", "B"], "Nope")
        finally:
            os.environ.pop(launcher_dialog.SUPPRESS_ENV, None)
        self.assertEqual(choice, "B", "should fall back to the last button")

    def test_choose_with_no_buttons_returns_default(self):
        self.assertEqual(launcher_dialog.choose("t", "m", [], "Cancel"), "Cancel")

    def test_applescript_quoting_escapes_quotes_and_backslashes(self):
        """A device or product name with a quote must not break the script."""
        quoted = launcher_dialog._applescript_quote('say "hi"\\path')
        self.assertNotIn('"hi"', quoted)
        self.assertEqual(quoted, 'say \\"hi\\"\\\\path')


if __name__ == "__main__":
    unittest.main()
