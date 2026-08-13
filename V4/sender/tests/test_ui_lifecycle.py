import os
import sys
import time
import unittest
from unittest.mock import MagicMock

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import ui_lifecycle
import run_primus


class UiLifecycleTests(unittest.TestCase):
    def make_server(self):
        server = MagicMock()
        server.ui_lifecycle_enabled = True
        ui_lifecycle.init_server(server)
        return server

    def test_multiple_sessions_keep_server_alive_after_one_closes(self):
        server = self.make_server()
        ui_lifecycle.touch_session(server, "primus")
        ui_lifecycle.touch_session(server, "devices")
        ui_lifecycle.close_session(server, "devices")
        active = ui_lifecycle._prune_sessions(server, time.monotonic())
        self.assertIn("primus", active)
        self.assertNotIn("devices", active)

    def test_shutdown_after_all_sessions_close(self):
        server = self.make_server()
        server.shutdown = MagicMock()
        server.ui_lifecycle_started_at = time.monotonic() - 60
        ui_lifecycle.touch_session(server, "only")
        ui_lifecycle.close_session(server, "only")
        server.ui_last_session_closed_at = time.monotonic() - 5
        ui_lifecycle.monitor(server, app_name="Central", live_output_fn=lambda _s: False)
        server.shutdown.assert_called_once()

    def test_device_manager_disables_ui_lifecycle_shutdown(self):
        with unittest.mock.patch.object(run_primus, "is_bundled", return_value=True):
            self.assertFalse(run_primus._ui_lifecycle_enabled("devices"))
            self.assertTrue(run_primus._ui_lifecycle_enabled("primus"))

    def test_source_runs_skip_ui_lifecycle_shutdown(self):
        with unittest.mock.patch.object(run_primus, "is_bundled", return_value=False):
            self.assertFalse(run_primus._ui_lifecycle_enabled("devices"))
            self.assertFalse(run_primus._ui_lifecycle_enabled("primus"))


if __name__ == "__main__":
    unittest.main()
