"""Tests for the monitor-only attach negotiation in run_primus.

Regression coverage for a shipped-adjacent bug: PrimusCentral 0.98 offered
"Restart in full mode" against a DeviceManager 0.97 backend, whose
POST /api/server/stop does not exist and answers 404. The launcher aborted on
that failure and left the old server holding the port, so every subsequent
launch of either app failed the same silent way and both appeared dead.

The rule these tests hold: never offer an action the running server cannot
carry out, and never leave the user without an instruction that fixes it.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import central_launcher
import run_primus


OLD_BACKEND = {
    "product": "primus",
    "app_version": "0.97",
    "monitor_only": True,
    # no server_control key -- this is what a pre-0.98 server looks like
}

NEW_BACKEND = {
    "product": "primus",
    "app_version": "0.98",
    "monitor_only": True,
    "server_control": True,
}

MONITOR_ONLY_MISMATCH = {"reason": central_launcher.MISMATCH_MONITOR_ONLY}


class OldBackendTests(unittest.TestCase):
    def test_restart_is_not_offered_to_an_old_backend(self):
        handler = run_primus._attach_mismatch_handler()
        with mock.patch.object(run_primus, "dialog_choose", return_value="Cancel") as choose:
            with mock.patch.object(run_primus, "stop_running_central") as stop:
                result = handler(MONITOR_ONLY_MISMATCH, 8080, OLD_BACKEND)
        self.assertEqual(result, "abort")
        stop.assert_not_called()
        buttons = choose.call_args[0][2]
        self.assertNotIn("Restart in full mode", buttons)

    def test_old_backend_message_says_how_to_recover(self):
        handler = run_primus._attach_mismatch_handler()
        with mock.patch.object(run_primus, "dialog_choose", return_value="Cancel") as choose:
            with mock.patch.object(run_primus, "stop_running_central"):
                handler(MONITOR_ONLY_MISMATCH, 8080, OLD_BACKEND)
        message = choose.call_args[0][1]
        # Names what is running, and the one action that unblocks the user.
        self.assertIn("0.97", message)
        self.assertIn("Dock", message)

    def test_old_backend_still_allows_read_only_attach(self):
        handler = run_primus._attach_mismatch_handler()
        with mock.patch.object(run_primus, "dialog_choose", return_value="Open read-only"):
            with mock.patch.object(run_primus, "stop_running_central") as stop:
                result = handler(MONITOR_ONLY_MISMATCH, 8080, OLD_BACKEND)
        self.assertEqual(result, "attach")
        stop.assert_not_called()


class NewBackendTests(unittest.TestCase):
    def test_restart_is_offered_and_performed(self):
        handler = run_primus._attach_mismatch_handler()
        with mock.patch.object(run_primus, "dialog_choose", return_value="Restart in full mode"):
            with mock.patch.object(run_primus, "stop_running_central",
                                   return_value=(True, "stopping")) as stop:
                with mock.patch.object(run_primus, "wait_for_port_release", return_value=True):
                    result = handler(MONITOR_ONLY_MISMATCH, 8080, NEW_BACKEND)
        self.assertEqual(result, "start")
        stop.assert_called_once()

    def test_stop_that_404s_falls_back_to_the_recovery_message(self):
        """Belt and braces: advertised the route but does not serve it."""
        handler = run_primus._attach_mismatch_handler()
        calls = []

        def fake_choose(title, message, buttons, default):
            calls.append(buttons)
            return "Restart in full mode" if len(calls) == 1 else "Cancel"

        with mock.patch.object(run_primus, "dialog_choose", side_effect=fake_choose):
            with mock.patch.object(run_primus, "stop_running_central",
                                   return_value=(False, "HTTP 404")):
                result = handler(MONITOR_ONLY_MISMATCH, 8080, NEW_BACKEND)
        self.assertEqual(result, "abort")
        # Second prompt is the recovery one, without a restart option.
        self.assertNotIn("Restart in full mode", calls[-1])

    def test_port_that_never_releases_tells_the_user_what_to_do(self):
        handler = run_primus._attach_mismatch_handler()
        with mock.patch.object(run_primus, "dialog_choose", return_value="Restart in full mode"):
            with mock.patch.object(run_primus, "stop_running_central",
                                   return_value=(True, "stopping")):
                with mock.patch.object(run_primus, "wait_for_port_release", return_value=False):
                    with mock.patch.object(run_primus, "dialog_notify") as notify:
                        result = handler(MONITOR_ONLY_MISMATCH, 8080, NEW_BACKEND)
        self.assertEqual(result, "abort")
        self.assertIn("Dock", notify.call_args[0][1])


if __name__ == "__main__":
    unittest.main()
