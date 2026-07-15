import os
import sys
import unittest
from unittest.mock import patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from state import ControllerState, TRANSPORT_FAIL_STREAK_LIMIT


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


class FlakySender:
    def __init__(self):
        self.connected = True
        self.last_error = "Broken pipe"
        self.ip = "192.168.1.2"
        self.calls = 0

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def send_output(self, universe, rgb_data):
        self.calls += 1
        return False

    def advance_sequence(self):
        pass


class TransportStabilityTests(unittest.TestCase):
    def make_state(self):
        state = ControllerState(None)
        state.add_device_from_node({
            "ip": "192.168.1.2",
            "short_name": "Node1",
            "capabilities": CAPABILITIES,
            "outputs": [
                {"name": "A0", "type": "short_strip", "universe": 0},
                {"name": "A1", "type": "long_strip", "universe": 1},
            ],
            "universes": [0, 1],
        }, auto_save=False)
        return state

    def test_single_tick_send_failure_stays_connected(self):
        state = self.make_state()
        dev = state.devices[0]
        dev["sender"] = FlakySender()
        dev["connected"] = True
        lo = state.active_look["outputs"][0]
        lo.update({
            "type": "short_strip",
            "count": 30,
            "layout": "linear",
            "grid": None,
            "effect": "solid",
            "pixels": [(255, 0, 0)] * 30,
        })
        state.playback_source = state.SOURCE_DESIGNER

        with patch("builtins.print"):
            state.tick()

        self.assertTrue(dev["connected"])
        self.assertTrue(dev["sender"].connected)
        self.assertEqual(dev.get("send_fail_streak"), 1)
        self.assertIsNone(dev.get("transport_error"))

    def test_sustained_send_failures_surface_warning_without_disconnect(self):
        state = self.make_state()
        dev = state.devices[0]
        dev["sender"] = FlakySender()
        dev["connected"] = True
        lo = state.active_look["outputs"][0]
        lo.update({
            "type": "short_strip",
            "count": 30,
            "layout": "linear",
            "grid": None,
            "effect": "solid",
            "pixels": [(255, 0, 0)] * 30,
        })
        state.playback_source = state.SOURCE_DESIGNER

        with patch("builtins.print"):
            for _ in range(TRANSPORT_FAIL_STREAK_LIMIT):
                state.tick()

        self.assertTrue(dev["connected"])
        self.assertTrue(dev["sender"].connected)
        self.assertIn("Broken pipe", dev.get("transport_error", ""))

    def test_send_recovery_clears_warning(self):
        state = self.make_state()
        dev = state.devices[0]
        sender = FlakySender()
        dev["sender"] = sender
        dev["connected"] = True
        dev["send_fail_streak"] = TRANSPORT_FAIL_STREAK_LIMIT
        dev["transport_error"] = "Broken pipe"
        lo = state.active_look["outputs"][0]
        lo.update({
            "type": "short_strip",
            "count": 30,
            "layout": "linear",
            "grid": None,
            "effect": "solid",
            "pixels": [(255, 0, 0)] * 30,
        })
        state.playback_source = state.SOURCE_DESIGNER

        sender.send_output = lambda universe, rgb_data: True

        with patch("builtins.print"):
            state.tick()

        self.assertTrue(dev["connected"])
        self.assertIsNone(dev.get("transport_error"))
        self.assertEqual(dev.get("send_fail_streak"), 0)


if __name__ == "__main__":
    unittest.main()
