"""Tests for sender receive mode state and send planning."""

import os
import sys
import unittest
from unittest.mock import Mock, patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from state import (
    COMBINED_RECEIVE_MAX_PIXELS,
    ControllerState,
    _apply_output_universes,
    _device_blackout_info,
    _queue_device_frame_sends,
    _validate_receive_mode_for_device,
)


class ReceiveModeHelperTests(unittest.TestCase):
    def test_validate_combined_pixel_limit(self):
        outputs = [{"count": 32}, {"count": 72}]
        ok, err = _validate_receive_mode_for_device("combined", outputs)
        self.assertTrue(ok)
        self.assertIsNone(err)

        outputs = [{"count": 122}, {"count": 122}]
        ok, err = _validate_receive_mode_for_device("combined", outputs)
        self.assertFalse(ok)
        self.assertIn(str(COMBINED_RECEIVE_MAX_PIXELS), err)

    def test_apply_output_universes(self):
        outputs = [
            {"type": "small_grid", "count": 32, "universe": 0},
            {"type": "long_strip", "count": 72, "universe": 1},
        ]
        _apply_output_universes(outputs, "combined", 104)
        self.assertEqual(outputs[0]["universe"], 104)
        self.assertEqual(outputs[1]["universe"], 104)

        _apply_output_universes(outputs, "split", 6)
        self.assertEqual(outputs[0]["universe"], 6)
        self.assertEqual(outputs[1]["universe"], 7)

    def test_device_blackout_info_combined(self):
        dev = {
            "receive_mode": "combined",
            "base_universe": 12,
            "outputs": [{"count": 32}, {"count": 72}],
        }
        self.assertEqual(_device_blackout_info(dev), [(12, 104)])

    def test_queue_device_frame_sends_combined(self):
        dev = {
            "receive_mode": "combined",
            "base_universe": 0,
            "sender": object(),
            "outputs": [
                {"count": 2, "universe": 0},
                {"count": 1, "universe": 0},
            ],
        }
        send_queue = []
        _queue_device_frame_sends(
            send_queue,
            0,
            dev,
            {
                0: bytes([255, 0, 0, 0, 255, 0]),
                1: bytes([0, 0, 255]),
            },
        )
        self.assertEqual(len(send_queue), 1)
        self.assertEqual(send_queue[0][2], 0)
        self.assertEqual(send_queue[0][3], bytes([255, 0, 0, 0, 255, 0, 0, 0, 255]))


class SetDeviceReceiveModeTests(unittest.TestCase):
    def setUp(self):
        self.state = ControllerState(fps_listener=None)
        self.state.devices = [{
            "name": "Node",
            "ip": "192.168.1.10",
            "base_universe": 0,
            "receive_mode": "split",
            "connected": True,
            "capabilities": {"receive_config": True},
            "sender": Mock(connected=True),
            "outputs": [
                {"type": "small_grid", "count": 32, "universe": 0},
                {"type": "long_strip", "count": 72, "universe": 1},
            ],
        }]

    @patch("state.send_receive_config")
    @patch("state._save_devices")
    def test_set_device_receive_mode_sends_without_connect(self, save_devices, send_receive_config):
        self.state.devices[0]["connected"] = False
        self.state.devices[0]["sender"] = Mock(connected=False)
        send_receive_config.return_value = None
        result = self.state.set_device_receive_mode(0, "split", 9)
        self.assertTrue(result["ok"])
        self.assertTrue(result["applied_to_device"])
        send_receive_config.assert_called_once_with(
            "192.168.1.10", "split", 9, source_ip=None)

    @patch("state.send_receive_config")
    @patch("state._save_devices")
    def test_set_device_receive_mode_updates_state(self, save_devices, send_receive_config):
        send_receive_config.return_value = None
        result = self.state.set_device_receive_mode(0, "combined", 5)
        self.assertTrue(result["ok"])
        self.assertTrue(result["applied_to_device"])
        dev = self.state.devices[0]
        self.assertEqual(dev["receive_mode"], "combined")
        self.assertEqual(dev["base_universe"], 5)
        self.assertEqual(dev["outputs"][0]["universe"], 5)
        send_receive_config.assert_called_once()

    def test_set_device_receive_mode_rejects_missing_capability(self):
        self.state.devices[0]["capabilities"]["receive_config"] = False
        result = self.state.set_device_receive_mode(0, "combined", 0)
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
