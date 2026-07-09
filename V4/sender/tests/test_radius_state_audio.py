"""Tests for RadiusState telemetry merge, snapshot audio status, rename,
and device restore.

Guards:
- 5b74165: audio_status crashed on missing telemetry — snapshot must not
  raise and must not invent an audio_status for devices that never reported
- July 2026: saved device name takes priority over discovered short_name;
  rename_device returns a structured result
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from radius_state import RadiusState


class FakeListener:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, ip):
        entry = self.data.get(ip)
        return dict(entry) if entry else None


def make_device(ip="192.168.1.10", name="Node-A"):
    return {
        "ip": ip,
        "name": name,
        "connected": True,
        "is_radius": True,
        "current_track": "",
        "playback_state": 0,
    }


class SnapshotAudioStatusTests(unittest.TestCase):
    def test_no_listener_does_not_crash_or_invent_status(self):
        state = RadiusState(telemetry_listener=None)
        state.devices = [make_device()]
        payload = state.get_json()
        dev = payload["devices"][0]
        self.assertNotIn("audio_status", dev)
        self.assertNotIn("now_playing", dev)

    def test_no_telemetry_for_device_does_not_invent_status(self):
        state = RadiusState(telemetry_listener=FakeListener({}))
        state.devices = [make_device()]
        dev = state.get_json()["devices"][0]
        self.assertNotIn("audio_status", dev)

    def test_playing_device_reports_status_and_track(self):
        listener = FakeListener({
            "192.168.1.10": {"playback_state": 1, "current_track": "show.wav"},
        })
        state = RadiusState(telemetry_listener=listener)
        state.devices = [make_device()]
        dev = state.get_json()["devices"][0]
        self.assertEqual(dev["audio_status"], "playing")
        self.assertEqual(dev["now_playing"], "show.wav")

    def test_paused_device_keeps_now_playing(self):
        listener = FakeListener({
            "192.168.1.10": {"playback_state": 2, "current_track": "show.wav"},
        })
        state = RadiusState(telemetry_listener=listener)
        state.devices = [make_device()]
        dev = state.get_json()["devices"][0]
        self.assertEqual(dev["audio_status"], "paused")
        self.assertEqual(dev["now_playing"], "show.wav")

    def test_stopped_device_clears_now_playing(self):
        listener = FakeListener({
            "192.168.1.10": {"playback_state": 0, "current_track": "show.wav"},
        })
        state = RadiusState(telemetry_listener=listener)
        state.devices = [make_device()]
        dev = state.get_json()["devices"][0]
        self.assertEqual(dev["audio_status"], "stopped")
        self.assertEqual(dev["now_playing"], "")

    def test_internal_flag_not_leaked_to_api(self):
        listener = FakeListener({
            "192.168.1.10": {"playback_state": 1, "current_track": "a.wav"},
        })
        state = RadiusState(telemetry_listener=listener)
        state.devices = [make_device()]
        dev = state.get_json()["devices"][0]
        self.assertNotIn("_has_telemetry", dev)

    def test_fps_telemetry_merged(self):
        listener = FakeListener({
            "192.168.1.10": {"fps": 30, "pkt_rate": 60},
        })
        state = RadiusState(telemetry_listener=listener)
        state.devices = [make_device()]
        dev = state.get_json()["devices"][0]
        self.assertEqual(dev["fps"], 30)
        self.assertEqual(dev["pkt_rate"], 60)


class RenameDeviceTests(unittest.TestCase):
    @patch("radius_state._save_devices")
    @patch("radius_state.send_art_address")
    def test_valid_rename_returns_ok(self, mock_send, mock_save):
        state = RadiusState()
        state.devices = [make_device()]
        result = state.rename_device(0, "NewName")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(state.devices[0]["name"], "NewName")
        mock_send.assert_called_once()

    @patch("radius_state.send_art_address")
    def test_invalid_index_returns_structured_error(self, mock_send):
        state = RadiusState()
        state.devices = [make_device()]
        result = state.rename_device(5, "NewName")
        self.assertFalse(result["ok"])
        self.assertIn("error", result)
        mock_send.assert_not_called()


class RestoreDevicesTests(unittest.TestCase):
    def _restore(self, saved, nodes):
        state = RadiusState()
        with patch("radius_state._load_devices", return_value=saved), \
             patch("radius_state.discover_artnet_nodes", return_value=nodes), \
             patch("radius_state._save_devices"), \
             patch.object(RadiusState, "_discovery_interface", return_value=None):
            state.restore_devices()
        return state

    def test_saved_name_wins_over_discovered_short_name(self):
        state = self._restore(
            saved=[{"ip": "192.168.8.157", "name": "StageLeft"}],
            nodes=[{"ip": "192.168.8.157", "short_name": "Radius", "node_report": ""}],
        )
        self.assertEqual(len(state.devices), 1)
        self.assertEqual(state.devices[0]["name"], "StageLeft")

    def test_discovered_name_used_when_no_saved_name(self):
        state = self._restore(
            saved=[{"ip": "192.168.8.157"}],
            nodes=[{"ip": "192.168.8.157", "short_name": "Radius-E8", "node_report": ""}],
        )
        self.assertEqual(state.devices[0]["name"], "Radius-E8")

    def test_offline_device_restored_with_saved_name(self):
        state = self._restore(
            saved=[{"ip": "192.168.8.157", "name": "StageLeft"}],
            nodes=[],
        )
        self.assertEqual(len(state.devices), 1)
        self.assertEqual(state.devices[0]["name"], "StageLeft")


if __name__ == "__main__":
    unittest.main()
