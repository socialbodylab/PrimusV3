"""Tests for hello identify hold and serial monitor."""

import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import state as state_module
from state import ControllerState
from serial_monitor import SerialMonitorManager, SerialMonitorError


CAPABILITIES = {
    "profile": "pv3cap1",
    "hardware_profile": "v1_huzzah",
    "hardware_label": "V1 Huzzah32",
    "firmware_version": "3.7",
    "known": True,
    "rename": True,
    "hello": True,
    "ip_config": True,
    "output_config": True,
}


class HelloDeviceTests(unittest.TestCase):
    def setUp(self):
        # Keep state reads/writes in a scratch dir; with a real fleet IP this
        # test rewrote the real .primus_state.json show-info map.
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

    def make_state(self):
        state = ControllerState(None)
        state.add_device_from_node({
            "ip": "192.0.2.163",
            "short_name": "A12",
            "capabilities": CAPABILITIES,
            "outputs": [
                {"name": "A0", "type": "short_strip", "universe": 0, "count": 30},
                {"name": "A1", "type": "short_strip", "universe": 1, "count": 30},
            ],
            "universes": [0, 1],
        }, auto_save=False)
        dev = state.devices[0]
        dev["connected"] = True
        dev["sender"].connected = True
        return state

    @patch("state.time.sleep")
    @patch("state.time.monotonic", return_value=100.0)
    def test_hello_device_sets_identify_hold(self, _mock_mono, mock_sleep):
        state = self.make_state()
        self.assertTrue(state.hello_device(0))
        self.assertEqual(state.devices[0]["_hello_until"], 101.0)
        mock_sleep.assert_not_called()


class SerialMonitorTests(unittest.TestCase):
    def test_start_requires_port(self):
        manager = SerialMonitorManager()
        with self.assertRaises(SerialMonitorError) as ctx:
            manager.start("")
        self.assertEqual(ctx.exception.code, 400)

    def test_stop_when_idle(self):
        manager = SerialMonitorManager()
        status = manager.stop()
        self.assertFalse(status["active"])
        self.assertEqual(status["output"], [])

    @patch("firmware.firmware_jobs")
    def test_start_conflicts_with_firmware_job(self, mock_jobs):
        mock_jobs.has_running_job.return_value = True
        manager = SerialMonitorManager()
        with patch.object(manager, "_arduino_cli_path", return_value="/usr/bin/arduino-cli"):
            with self.assertRaises(SerialMonitorError) as ctx:
                manager.start("/dev/cu.usbserial-1")
        self.assertEqual(ctx.exception.code, 409)


if __name__ == "__main__":
    unittest.main()
