import os
import sys
import unittest
from unittest.mock import patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from state import ControllerState


def _bare_node(ip, short_name):
    return {
        "ip": ip,
        "short_name": short_name,
        "long_name": "",
        "num_ports": 0,
        "universes": [0, 1],
    }


class RecordingSender:
    def __init__(self, ip):
        self.ip = ip
        self.connected = False
        self.last_error = None
        self.sent = []

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def send_output(self, universe, data):
        self.sent.append((universe, data))
        return True

    def advance_sequence(self):
        pass

    def blackout(self, info):
        pass


class TickSkipsAudioDevicesTests(unittest.TestCase):

    def _connected_state(self, short_name):
        state = ControllerState(None)
        self.addCleanup(state.shutdown)
        state.add_device_from_node(_bare_node("192.168.1.10", short_name), auto_save=False)
        sender = RecordingSender("192.168.1.10")
        sender.connected = True
        state.devices[0]["sender"] = sender
        state.devices[0]["connected"] = True
        state.set_playback_source("designer")
        return state, sender

    def test_audio_device_receives_no_artdmx_in_tick(self):
        state, sender = self._connected_state("Radius1")
        state.tick()
        self.assertEqual(sender.sent, [])

    def test_led_device_receives_artdmx_in_tick(self):
        state, sender = self._connected_state("PrimusLED")
        # Force a non-empty pixel buffer so a packet is actually sent
        for lo in state.active_look["outputs"]:
            if lo["count"] > 0:
                lo["pixels"] = [[255, 0, 0]] * lo["count"]
        state.tick()
        self.assertGreater(len(sender.sent), 0)

    def test_mixed_devices_only_led_gets_artdmx(self):
        state = ControllerState(None)
        self.addCleanup(state.shutdown)

        for ip, name in [("192.168.1.10", "Radius1"), ("192.168.1.20", "PrimusLED")]:
            state.add_device_from_node(_bare_node(ip, name), auto_save=False)

        radius_sender = RecordingSender("192.168.1.10")
        radius_sender.connected = True
        state.devices[0]["sender"] = radius_sender
        state.devices[0]["connected"] = True

        led_sender = RecordingSender("192.168.1.20")
        led_sender.connected = True
        state.devices[1]["sender"] = led_sender
        state.devices[1]["connected"] = True

        state.set_playback_source("designer")
        for lo in state.active_look["outputs"]:
            if lo["count"] > 0:
                lo["pixels"] = [[0, 255, 0]] * lo["count"]

        state.tick()

        self.assertEqual(radius_sender.sent, [])
        self.assertGreater(len(led_sender.sent), 0)


if __name__ == "__main__":
    unittest.main()
