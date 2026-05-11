import os
import sys
import unittest
from unittest.mock import patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from state import ControllerState


CAPABILITIES = {
    "profile": "pv3cap1",
    "hardware_profile": "v31",
    "hardware_label": "V3.1 Reverse TFT",
    "firmware_version": "3.5",
    "known": True,
    "rename": True,
    "hello": True,
    "ip_config": True,
    "output_config": True,
}


class FailingSender:
    def __init__(self):
        self.connected = True
        self.last_error = "No route to host"
        self.ip = "192.168.1.2"
        self.disconnected = False

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False
        self.disconnected = True

    def send_output(self, universe, data):
        return False

    def advance_sequence(self):
        pass


class RecordingSender:
    def __init__(self):
        self.connected = False
        self.last_error = None
        self.ip = "192.168.1.2"
        self.connect_count = 0
        self.sent = []

    def connect(self):
        self.connected = True
        self.connect_count += 1

    def disconnect(self):
        self.connected = False

    def send_output(self, universe, data):
        self.sent.append((universe, data))
        return True

    def advance_sequence(self):
        pass


class TransportRecoveryTests(unittest.TestCase):
    def make_state(self):
        state = ControllerState(None)
        state.add_device_from_node({
            "ip": "192.168.1.2",
            "short_name": "NewPrimus1",
            "capabilities": CAPABILITIES,
            "outputs": [{"name": "A0", "type": "short_strip", "universe": 0}],
            "universes": [0],
        }, auto_save=False)
        return state

    def test_connect_failure_marks_device_offline(self):
        state = self.make_state()

        with patch("state.send_output_config", side_effect=OSError(65, "No route to host")), \
            patch("builtins.print"):
            result = state.connect(0)

        dev = state.devices[0]
        self.assertFalse(result["ok"])
        self.assertFalse(dev["connected"])
        self.assertFalse(dev["sender"].connected)
        self.assertIn("No route to host", dev["transport_error"])

    def test_output_send_failure_marks_device_offline(self):
        state = self.make_state()
        failing_sender = FailingSender()
        dev = state.devices[0]
        dev["sender"] = failing_sender
        dev["connected"] = True

        first_output = state.active_look["outputs"][0]
        first_output.update({
            "type": "short_strip",
            "count": 30,
            "layout": "linear",
            "grid": None,
            "effect": "solid",
            "pixels": [],
        })
        state.playback_source = state.SOURCE_DESIGNER

        with patch("builtins.print"):
            state.tick()

        self.assertFalse(dev["connected"])
        self.assertFalse(failing_sender.connected)
        self.assertTrue(failing_sender.disconnected)
        self.assertEqual(dev["transport_error"], "No route to host")

    def test_hello_reconnects_logically_connected_sender(self):
        state = self.make_state()
        recording_sender = RecordingSender()
        dev = state.devices[0]
        dev["sender"] = recording_sender
        dev["connected"] = True

        with patch("state.time.sleep"):
            ok = state.hello_device(0)

        self.assertTrue(ok)
        self.assertEqual(recording_sender.connect_count, 1)
        self.assertEqual(len(recording_sender.sent), 2)
        self.assertIsNone(dev["transport_error"])


if __name__ == "__main__":
    unittest.main()