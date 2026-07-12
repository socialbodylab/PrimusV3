"""Tests for character/performer show info on Radius and Primus device state."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import radius_state
import show_info_store
import state
from radius_state import RadiusState
from state import ControllerState

RADIUS_CAPS = {
    "profile": "pvrad1",
    "device_class": "radius",
    "show_info": True,
    "audio": True,
}

PRIMUS_CAPS = {
    "profile": "pv3cap1",
    "known": True,
    "rename": True,
    "show_info": True,
}


class ShowInfoStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, ".radius_state.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_persist_and_lookup_round_trip(self):
        show_info_store.persist_device_show_info(
            self.path, "192.168.8.155", "E6", "Radius Robot", "Alex Kim")
        char, perf = show_info_store.lookup_device_show_info(self.path, "192.168.8.155")
        self.assertEqual(char, "Radius Robot")
        self.assertEqual(perf, "Alex Kim")

    def test_lookup_falls_back_to_device_name(self):
        show_info_store.persist_device_show_info(
            self.path, "192.168.8.155", "E6", "Radius Robot", "Alex Kim")
        char, perf = show_info_store.lookup_device_show_info(
            self.path, "10.0.0.99", "E6")
        self.assertEqual(char, "Radius Robot")
        self.assertEqual(perf, "Alex Kim")

    def test_migrate_moves_entry_to_new_ip(self):
        show_info_store.persist_device_show_info(
            self.path, "192.168.8.155", "E6", "Radius Robot", "Alex Kim")
        show_info_store.migrate_device_show_info_key(
            self.path, "192.168.8.155", "192.168.8.200", "E6")
        char, _ = show_info_store.lookup_device_show_info(self.path, "192.168.8.200")
        self.assertEqual(char, "Radius Robot")
        char, _ = show_info_store.lookup_device_show_info(self.path, "192.168.8.155")
        self.assertEqual(char, "")


class RadiusShowInfoTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, ".radius_state.json")
        self.path_patch = patch.object(
            radius_state, "state_file", return_value=self.path)
        self.path_patch.start()
        self.state = RadiusState()

    def tearDown(self):
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def _add_device(self, caps=RADIUS_CAPS):
        self.state.devices.append({
            "name": "E6",
            "ip": "192.168.8.155",
            "connected": False,
            "is_radius": True,
            "capabilities": dict(caps),
            "character_name": "",
            "performer_name": "",
        })

    @patch("radius_state.sync_show_info_to_device", return_value=(True, ""))
    def test_update_writes_device_and_persists(self, mock_sync):
        self._add_device()
        result = self.state.update_device_show_info(
            0, character_name="Radius Robot", performer_name="Alex Kim")
        self.assertTrue(result["ok"])
        self.assertTrue(result["applied_to_device"])
        # Radius nodes live on the dedicated Art-Net port.
        self.assertEqual(
            mock_sync.call_args.kwargs.get("port"), radius_state.RADIUS_ARTNET_PORT)
        char, perf = show_info_store.lookup_device_show_info(self.path, "192.168.8.155")
        self.assertEqual(char, "Radius Robot")
        self.assertEqual(perf, "Alex Kim")
        # Device entries in the saved state carry the fields too.
        with open(self.path) as f:
            data = json.load(f)
        self.assertEqual(data["devices"][0]["character_name"], "Radius Robot")

    @patch("radius_state.sync_show_info_to_device")
    def test_update_without_show_info_capability_saves_locally(self, mock_sync):
        self._add_device(caps={"profile": "pvrad1", "device_class": "radius"})
        result = self.state.update_device_show_info(0, character_name="Radius Robot")
        self.assertTrue(result["ok"])
        self.assertFalse(result["applied_to_device"])
        mock_sync.assert_not_called()

    @patch("radius_state.sync_show_info_to_device",
           return_value=(False, "receiver did not confirm show info save"))
    def test_update_fails_when_receiver_does_not_confirm(self, mock_sync):
        self._add_device()
        result = self.state.update_device_show_info(0, character_name="Radius Robot")
        self.assertFalse(result["ok"])
        self.assertIn("confirm", result["error"])

    def test_save_devices_preserves_show_info_map(self):
        show_info_store.persist_device_show_info(
            self.path, "192.168.8.155", "E6", "Radius Robot", "Alex Kim")
        self._add_device()
        radius_state._save_devices(self.state.devices)
        with open(self.path) as f:
            data = json.load(f)
        self.assertIn("device_show_info", data)
        self.assertEqual(
            data["device_show_info"]["192.168.8.155"]["character_name"],
            "Radius Robot")

    def test_new_device_inherits_persisted_show_info(self):
        show_info_store.persist_device_show_info(
            self.path, "192.168.8.155", "E6", "Radius Robot", "Alex Kim")
        self.state.add_device_from_node({
            "ip": "192.168.8.155",
            "short_name": "E6",
            "node_report": "PVRAD1|B:v1|IP:D|F:RAS",
        })
        dev = self.state.devices[0]
        self.assertEqual(dev["character_name"], "Radius Robot")
        self.assertEqual(dev["performer_name"], "Alex Kim")

    def test_get_json_includes_show_info_fields(self):
        self._add_device()
        self.state.devices[0]["character_name"] = "Radius Robot"
        payload = self.state.get_json()
        self.assertEqual(payload["devices"][0]["character_name"], "Radius Robot")
        self.assertIn("battery_pct", payload["devices"][0])


class PrimusShowInfoTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp_dir.name, ".primus_state.json")
        self.path_patch = patch.object(
            state, "_state_file", return_value=self.path)
        self.path_patch.start()
        self.state = ControllerState(fps_listener=None)

    def tearDown(self):
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def _add_device(self, caps=PRIMUS_CAPS):
        self.state.devices.append({
            "name": "Badge-A",
            "ip": "192.168.8.60",
            "connected": False,
            "capabilities": dict(caps),
            "character_name": "",
            "performer_name": "",
            "base_universe": 0,
            "outputs": [],
        })

    @patch("state.sync_show_info_to_device", return_value=(True, ""))
    def test_update_writes_device_and_persists(self, mock_sync):
        self._add_device()
        result = self.state.update_device_show_info(
            0, character_name="Marius", performer_name="Jamie")
        self.assertTrue(result["ok"])
        self.assertTrue(result["applied_to_device"])
        char, perf = show_info_store.lookup_device_show_info(self.path, "192.168.8.60")
        self.assertEqual(char, "Marius")
        self.assertEqual(perf, "Jamie")

    @patch("state.sync_show_info_to_device")
    def test_update_without_capability_saves_locally(self, mock_sync):
        self._add_device(caps={"profile": "pv3cap1", "known": True})
        result = self.state.update_device_show_info(0, performer_name="Jamie")
        self.assertTrue(result["ok"])
        self.assertFalse(result["applied_to_device"])
        mock_sync.assert_not_called()


if __name__ == "__main__":
    unittest.main()
