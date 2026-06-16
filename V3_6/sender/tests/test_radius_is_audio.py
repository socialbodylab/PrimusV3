import os
import sys
import unittest

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from state import ControllerState


def _bare_node(ip, short_name, long_name=""):
    return {
        "ip": ip,
        "short_name": short_name,
        "long_name": long_name,
        "num_ports": 0,
        "universes": [0, 1],
    }


class IsAudioDetectionTests(unittest.TestCase):

    def _add(self, ip, short_name, long_name=""):
        state = ControllerState(None)
        state.add_device_from_node(_bare_node(ip, short_name, long_name), auto_save=False)
        return state

    # -- Detection on add --

    def test_radius_in_short_name_sets_is_audio(self):
        state = self._add("192.168.1.10", "Radius1")
        self.assertTrue(state.devices[0]["is_audio"])

    def test_audio_in_short_name_sets_is_audio(self):
        state = self._add("192.168.1.11", "Audio Node")
        self.assertTrue(state.devices[0]["is_audio"])

    def test_radius_in_long_name_sets_is_audio(self):
        state = self._add("192.168.1.12", "Node12", "Radius V2 Audio Node")
        self.assertTrue(state.devices[0]["is_audio"])

    def test_led_node_is_not_audio(self):
        state = self._add("192.168.1.20", "Primus1")
        self.assertFalse(state.devices[0]["is_audio"])

    def test_generic_ip_name_is_not_audio(self):
        state = self._add("192.168.1.21", "192.168.1.21")
        self.assertFalse(state.devices[0]["is_audio"])

    def test_case_sensitive_match_radius_capitalised(self):
        state = self._add("192.168.1.22", "radius-node")
        # "radius" lowercase should NOT match (check is case-sensitive)
        self.assertFalse(state.devices[0]["is_audio"])

    # -- Refresh keeps is_audio in sync --

    def test_refresh_updates_is_audio_when_name_becomes_radius(self):
        state = ControllerState(None)
        state.add_device_from_node(_bare_node("192.168.1.30", "GenericNode"), auto_save=False)
        self.assertFalse(state.devices[0]["is_audio"])

        # node_report is present in real ArtPollReply packets; triggers the refresh path
        node = _bare_node("192.168.1.30", "Radius1")
        node["node_report"] = "PV3CAP1"
        state.add_device_from_node(node, auto_save=False)
        self.assertTrue(state.devices[0]["is_audio"])

    def test_refresh_clears_is_audio_when_name_changes_to_led(self):
        state = ControllerState(None)
        state.add_device_from_node(_bare_node("192.168.1.31", "Radius1"), auto_save=False)
        self.assertTrue(state.devices[0]["is_audio"])

        node = _bare_node("192.168.1.31", "PrimusNode")
        node["node_report"] = "PV3CAP1"
        state.add_device_from_node(node, auto_save=False)
        self.assertFalse(state.devices[0]["is_audio"])

    # -- Exposed in state snapshot --

    def test_get_json_includes_is_audio_true(self):
        state = ControllerState(None)
        state.add_device_from_node(_bare_node("192.168.1.40", "Radius1"), auto_save=False)
        snap = state.get_json()
        self.assertTrue(snap["devices"][0]["is_audio"])

    def test_get_json_includes_is_audio_false(self):
        state = ControllerState(None)
        state.add_device_from_node(_bare_node("192.168.1.41", "Primus1"), auto_save=False)
        snap = state.get_json()
        self.assertFalse(snap["devices"][0]["is_audio"])


if __name__ == "__main__":
    unittest.main()
