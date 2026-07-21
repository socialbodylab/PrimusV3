"""Tests for device show metadata and telemetry liveness fields."""

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import state
from artnet import PrimusTelemetryListener
from state import (
    ControllerState,
    _load_devices,
    _lookup_device_show_info,
    _persist_device_show_info,
    _save_devices,
)


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


class DeviceShowInfoPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.temp_dir.name, ".primus_state.json")
        self.radius_state_path = os.path.join(self.temp_dir.name, ".radius_state.json")
        self.state_patch = patch.object(state, "_state_file", return_value=self.state_path)
        self.primus_path_patch = patch.object(
            state.show_info_store, "primus_state_path", return_value=self.state_path)
        self.radius_path_patch = patch.object(
            state.show_info_store, "radius_state_path", return_value=self.radius_state_path)
        self.state_patch.start()
        self.primus_path_patch.start()
        self.radius_path_patch.start()

    def tearDown(self):
        self.radius_path_patch.stop()
        self.primus_path_patch.stop()
        self.state_patch.stop()
        self.temp_dir.cleanup()

    def test_save_and_load_round_trip(self):
        devices = [{
            "ip": "192.168.1.50",
            "name": "Badge-A",
            "hardware_profile": "v1_huzzah",
            "hardware_label": "V1 Huzzah32",
            "firmware_version": "3.7",
            "capabilities": CAPABILITIES,
            "ip_mode": "dhcp",
            "static_ip": None,
            "gateway": None,
            "subnet": None,
            "receive_mode": "split",
            "base_universe": 0,
            "character_name": "Ensemble Lead",
            "performer_name": "Alex Kim",
            "outputs": [],
        }]
        _save_devices(devices)
        loaded = _load_devices()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["character_name"], "Ensemble Lead")
        self.assertEqual(loaded[0]["performer_name"], "Alex Kim")

    @patch("state._save_devices")
    @patch("state.sync_show_info_to_device", return_value=(True, ""))
    def test_update_device_show_info_writes_receiver(self, sync_show_info, save_devices):
        controller = ControllerState(None)
        controller.add_device_from_node({
            "ip": "192.168.1.50",
            "short_name": "Badge-A",
            "capabilities": {**CAPABILITIES, "show_info": True},
            "outputs": [
                {"name": "A0", "type": "short_strip", "universe": 0},
            ],
            "universes": [0, 1],
        }, auto_save=False)

        result = controller.update_device_show_info(
            0,
            character_name="Chorus",
            performer_name="Taylor",
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["applied_to_device"])
        sync_show_info.assert_called_once_with(
            "192.168.1.50",
            "Chorus",
            "Taylor",
            source_ip=None,
            dest_port=6454,
        )
        self.assertIsNotNone(controller.devices[0].get("show_info_edited_at"))
        save_devices.assert_called_once()

    @patch("state._save_devices")
    @patch("state.sync_show_info_to_device", return_value=(False, "receiver did not confirm show info save"))
    def test_update_device_show_info_fails_when_verify_fails(self, sync_show_info, save_devices):
        controller = ControllerState(None)
        controller.add_device_from_node({
            "ip": "192.168.1.50",
            "short_name": "Badge-A",
            "capabilities": {**CAPABILITIES, "show_info": True},
            "outputs": [
                {"name": "A0", "type": "short_strip", "universe": 0},
            ],
            "universes": [0, 1],
        }, auto_save=False)

        result = controller.update_device_show_info(0, character_name="Chorus")

        self.assertFalse(result["ok"])
        self.assertIn("confirm", result["error"])
        save_devices.assert_not_called()

    def test_get_json_includes_show_info_and_liveness(self):
        controller = ControllerState(None)
        controller.add_device_from_node({
            "ip": "192.168.1.50",
            "short_name": "Badge-A",
            "character_name": "Chorus",
            "performer_name": "Taylor",
            "capabilities": CAPABILITIES,
            "outputs": [
                {"name": "A0", "type": "short_strip", "universe": 0},
            ],
            "universes": [0, 1],
        }, auto_save=False)
        controller.devices[0]["connected"] = True

        class FakeListener:
            def get_telemetry_status(self, ip):
                return {"fps": 29, "pkt_rate": 30}, 0.5, True

        controller.fps_listener = FakeListener()
        payload = controller.get_json()
        device = payload["devices"][0]
        self.assertEqual(device["character_name"], "Chorus")
        self.assertEqual(device["performer_name"], "Taylor")
        self.assertTrue(device["receiver_online"])
        self.assertEqual(device["telemetry_age_seconds"], 0.5)
        self.assertEqual(device["receiver_fps"], 29)

    def test_show_info_persists_after_device_removed_from_list(self):
        devices = [{
            "ip": "192.168.1.50",
            "name": "Badge-A",
            "hardware_profile": "v1_huzzah",
            "hardware_label": "V1 Huzzah32",
            "firmware_version": "3.7",
            "capabilities": CAPABILITIES,
            "ip_mode": "dhcp",
            "static_ip": None,
            "gateway": None,
            "subnet": None,
            "receive_mode": "split",
            "base_universe": 0,
            "character_name": "Lead",
            "performer_name": "Alex Kim",
            "outputs": [],
        }]
        _save_devices(devices)
        _save_devices([])

        character_name, performer_name = _lookup_device_show_info("192.168.1.50", "Badge-A")
        self.assertEqual(character_name, "Lead")
        self.assertEqual(performer_name, "Alex Kim")

    def test_radius_show_info_persists_in_radius_state_file(self):
        radius_path = self.radius_state_path
        show_info_store = state.show_info_store
        show_info_store.persist_device_show_info(
            radius_path, "192.168.1.60", "Radius-A", "Narrator", "Jamie")
        char, perf = show_info_store.lookup_device_show_info(
            radius_path, "192.168.1.60", "Radius-A")
        self.assertEqual(char, "Narrator")
        self.assertEqual(perf, "Jamie")
        with open(radius_path, "r") as f:
            data = json.load(f)
        self.assertIn("device_show_info", data)
        self.assertEqual(data["device_show_info"]["192.168.1.60"]["character_name"], "Narrator")

    @patch("state._save_devices")
    def test_readded_device_restores_persisted_show_info(self, save_devices):
        _persist_device_show_info("192.168.1.50", "Badge-A", "Chorus", "Taylor")
        controller = ControllerState(None)
        result = controller.add_device_from_node({
            "ip": "192.168.1.50",
            "short_name": "Badge-A",
            "capabilities": CAPABILITIES,
            "outputs": [
                {"name": "A0", "type": "short_strip", "universe": 0},
            ],
            "universes": [0, 1],
        }, auto_save=False)

        dev = controller.devices[result["device_index"]]
        self.assertEqual(dev["character_name"], "Chorus")
        self.assertEqual(dev["performer_name"], "Taylor")
        save_devices.assert_not_called()

    def test_apply_persisted_prefers_discovery_show_info(self):
        _persist_device_show_info("192.168.1.50", "Radius-A", "Old Character", "Old Performer")
        dev = {"ip": "192.168.1.50", "name": "Radius-A"}
        state.show_info_store.apply_persisted_show_info(
            self.radius_state_path,
            dev,
            {
                "ip": "192.168.1.50",
                "short_name": "Radius-A",
                "character_name": "Flash Character",
                "performer_name": "Flash Performer",
            },
        )
        self.assertEqual(dev["character_name"], "Flash Character")
        self.assertEqual(dev["performer_name"], "Flash Performer")
        char, perf = state.show_info_store.lookup_device_show_info(
            self.radius_state_path, "192.168.1.50")
        self.assertEqual(char, "Flash Character")
        self.assertEqual(perf, "Flash Performer")

    def test_preferred_device_name_keeps_saved_custom_name_over_generic_discovery(self):
        name = state.show_info_store.preferred_device_name("Radius", "Audio-1", fallback="Radius")
        self.assertEqual(name, "Audio-1")

    def test_preferred_device_name_uses_discovered_custom_name(self):
        name = state.show_info_store.preferred_device_name("Audio-1", "Radius", fallback="Radius")
        self.assertEqual(name, "Audio-1")

    @patch("state.send_show_info")
    def test_add_device_does_not_push_show_info_to_receiver(self, send_show_info):
        _persist_device_show_info("192.168.1.50", "Radius", "Old Character", "Old Performer")
        controller = ControllerState(None)
        controller.add_device_from_node({
            "ip": "192.168.1.50",
            "short_name": "Radius",
            "character_name": "Flash Character",
            "performer_name": "Flash Performer",
            "capabilities": {
                "profile": "pvrad1",
                "device_class": "radius",
                "show_info": True,
            },
            "node_report": "PVRAD1|B:v1|IP:D|F:RIHAS",
        }, auto_save=False)
        send_show_info.assert_not_called()
        dev = controller.devices[0]
        self.assertEqual(dev["character_name"], "Flash Character")
        self.assertEqual(dev["performer_name"], "Flash Performer")

    def test_empty_string_show_info_persists_and_restores(self):
        state.show_info_store.persist_device_show_info(
            self.radius_state_path,
            "192.168.1.60",
            "Radius-A",
            "",
            "Jamie",
        )
        dev = {"ip": "192.168.1.60", "name": "Radius-A"}
        state.show_info_store.apply_persisted_show_info(self.radius_state_path, dev, {})
        self.assertEqual(dev["character_name"], "")
        self.assertEqual(dev["performer_name"], "Jamie")

    def test_discovery_grace_period_blocks_refresh_overwrite(self):
        controller = ControllerState(None)
        controller.add_device_from_node({
            "ip": "192.168.1.50",
            "short_name": "Radius-A",
            "character_name": "User Character",
            "performer_name": "User Performer",
            "capabilities": {
                "profile": "pvrad1",
                "device_class": "radius",
                "show_info": True,
            },
            "node_report": "PVRAD1|B:v1|IP:D|F:RIHAS",
        }, auto_save=False)
        controller.devices[0]["show_info_edited_at"] = time.time()
        controller._refresh_device_from_node_unlocked(controller.devices[0], {
            "ip": "192.168.1.50",
            "short_name": "Radius-A",
            "character_name": "Stale Character",
            "performer_name": "Stale Performer",
            "capabilities": {
                "profile": "pvrad1",
                "device_class": "radius",
                "show_info": True,
            },
            "node_report": "PVRAD1|B:v1|IP:D|F:RIHAS",
        })
        self.assertEqual(controller.devices[0]["character_name"], "User Character")
        self.assertEqual(controller.devices[0]["performer_name"], "User Performer")


class RadiusStateShowInfoTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.radius_state_path = os.path.join(self.temp_dir.name, ".radius_state.json")
        self.radius_path_patch = patch.object(
            state.show_info_store, "radius_state_path", return_value=self.radius_state_path)
        self.radius_path_patch.start()

    def tearDown(self):
        self.radius_path_patch.stop()
        self.temp_dir.cleanup()

    @patch("radius_state.sync_device_name_to_receiver", return_value=(True, ""))
    @patch("radius_state._save_devices")
    def test_radius_rename_returns_dict(self, save_devices, sync_rename):
        from radius_state import RadiusState

        radius = RadiusState()
        radius.add_device_from_node({
            "ip": "192.168.1.60",
            "short_name": "Radius-A",
            "capabilities": {
                "profile": "pvrad1",
                "device_class": "radius",
                "rename": True,
                "show_info": True,
            },
            "node_report": "PVRAD1|B:v1|IP:D|F:RIHAS",
        }, auto_save=False)

        result = radius.rename_device(0, "Audio-2")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(radius.devices[0]["name"], "Audio-2")

    @patch("radius_state.sync_show_info_to_device", return_value=(True, ""))
    @patch("radius_state._save_devices")
    def test_radius_update_show_info_sets_applied_to_device(self, save_devices, sync_show_info):
        from radius_state import RadiusState

        radius = RadiusState()
        radius.add_device_from_node({
            "ip": "192.168.1.60",
            "short_name": "Radius-A",
            "capabilities": {
                "profile": "pvrad1",
                "device_class": "radius",
                "show_info": True,
            },
            "node_report": "PVRAD1|B:v1|IP:D|F:RIHAS",
        }, auto_save=False)

        result = radius.update_device_show_info(0, character_name="Narrator")
        self.assertTrue(result["ok"])
        self.assertTrue(result["applied_to_device"])


class PrimusTelemetryStatusTests(unittest.TestCase):
    def test_get_telemetry_status_online_and_stale(self):
        listener = PrimusTelemetryListener.__new__(PrimusTelemetryListener)
        listener.lock = __import__("threading").Lock()
        listener.data = {
            "192.168.1.50": {
                "fps": 30,
                "pkt_rate": 30,
                "ts": time.monotonic() - 1.0,
            }
        }
        listener.TELEMETRY_STALE_SECONDS = 12.0
        listener.TELEMETRY_ONLINE_SECONDS = 3.0

        fresh, age, online = listener.get_telemetry_status("192.168.1.50")
        self.assertIsNotNone(fresh)
        self.assertAlmostEqual(age, 1.0, places=1)
        self.assertTrue(online)

        listener.data["192.168.1.50"]["ts"] = time.monotonic() - 15.0
        fresh, age, online = listener.get_telemetry_status("192.168.1.50")
        self.assertIsNone(fresh)
        self.assertFalse(online)


if __name__ == "__main__":
    unittest.main()
