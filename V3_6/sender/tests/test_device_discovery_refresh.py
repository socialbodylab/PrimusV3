import os
import sys
import unittest
from unittest.mock import patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from state import ControllerState


class DeviceDiscoveryRefreshTests(unittest.TestCase):
    def test_existing_generic_device_refreshes_from_capability_reply(self):
        state = ControllerState(None)
        state.add_device_from_node({
            "ip": "192.168.1.50",
            "short_name": "NewPrimus1",
            "long_name": "",
            "num_ports": 0,
            "universes": [0, 1],
        }, auto_save=False)

        self.assertFalse(state.devices[0]["capabilities"]["rename"])
        self.assertEqual(state.devices[0]["outputs"][0]["type"], "long_strip")

        result = state.add_device_from_node({
            "ip": "192.168.1.50",
            "short_name": "NewPrimus1",
            "long_name": "PrimusV3.5 LED Node | A0:Grid 8x4 A1:Long Strip",
            "node_report": "#0001 [0000] OK|PV3CAP1|0:4:0|1:2:1|B:v1|IP:S|F:RIOH",
            "ip_mode": "static",
            "static_ip": "192.168.1.50",
            "num_ports": 2,
            "universes": [0, 1],
        }, auto_save=False)

        dev = state.devices[0]
        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["device_index"], 0)
        self.assertEqual(dev["name"], "NewPrimus1")
        self.assertTrue(dev["capabilities"]["rename"])
        self.assertTrue(dev["capabilities"]["hello"])
        self.assertTrue(dev["capabilities"]["output_config"])
        self.assertEqual(dev["hardware_profile"], "v1")
        self.assertEqual(dev["ip_mode"], "static")
        self.assertEqual(dev["static_ip"], "192.168.1.50")
        self.assertEqual(dev["outputs"][0]["type"], "small_grid")
        self.assertEqual(dev["outputs"][0]["universe"], 0)
        self.assertEqual(dev["outputs"][1]["type"], "long_strip")
        self.assertEqual(dev["outputs"][1]["universe"], 1)

    def test_existing_bare_manual_add_does_not_erase_discovered_metadata(self):
        state = ControllerState(None)
        state.add_device_from_node({
            "ip": "192.168.1.51",
            "short_name": "NewPrimus1",
            "long_name": "PrimusV3.5 LED Node | A0:Grid 8x4 A1:Long Strip",
            "node_report": "#0001 [0000] OK|PV3CAP1|0:4:0|1:2:1|B:v1|F:RIOH",
            "num_ports": 2,
            "universes": [0, 1],
        }, auto_save=False)

        result = state.add_device_from_node({
            "ip": "192.168.1.51",
            "short_name": "192.168.1.51",
            "long_name": "",
            "num_ports": 0,
            "universes": [0, 1],
        }, auto_save=False)

        dev = state.devices[0]
        self.assertEqual(result["status"], "exists")
        self.assertTrue(dev["capabilities"]["rename"])
        self.assertTrue(dev["capabilities"]["hello"])
        self.assertEqual(dev["name"], "NewPrimus1")
        self.assertEqual(dev["outputs"][0]["type"], "small_grid")

    def test_discovered_device_with_new_ip_refreshes_unique_saved_name(self):
        state = ControllerState(None)
        state.add_device_from_node({
            "ip": "192.168.1.6",
            "short_name": "NewPrimus1",
            "long_name": "",
            "num_ports": 0,
            "universes": [0, 1],
            "hardware_profile": "v31",
            "hardware_label": "V3.1 Reverse TFT",
        }, auto_save=False)

        result = state.add_device_from_node({
            "ip": "192.168.1.2",
            "short_name": "NewPrimus1",
            "long_name": "PrimusV3.5 LED Node | A0:Short Strip A1:Long Strip ",
            "node_report": "#0001 [0000] OK|PV3CAP1|0:1:0|1:2:1|B:v31|IP:D|F:RIOH",
            "capabilities": {
                "profile": "pv3cap1",
                "hardware_profile": "v31",
                "hardware_label": "V3.1 Reverse TFT",
                "firmware_version": "3.5",
                "ip_mode": "dhcp",
                "known": True,
                "rename": True,
                "hello": True,
                "ip_config": True,
                "output_config": True,
            },
            "hardware_profile": "v31",
            "hardware_label": "V3.1 Reverse TFT",
            "firmware_version": "3.5",
            "num_ports": 2,
            "universes": [0, 1],
        }, auto_save=False)

        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["device_index"], 0)
        self.assertEqual(len(state.devices), 1)
        dev = state.devices[0]
        self.assertEqual(dev["ip"], "192.168.1.2")
        self.assertEqual(dev["sender"].ip, "192.168.1.2")
        self.assertTrue(dev["capabilities"]["rename"])
        self.assertTrue(dev["capabilities"]["hello"])
        self.assertEqual(dev["ip_mode"], "dhcp")
        self.assertEqual(dev["outputs"][0]["type"], "short_strip")
        self.assertEqual(dev["outputs"][1]["type"], "long_strip")

    def test_pending_static_ip_is_refreshed_without_readding_device(self):
        state = ControllerState(None)
        state.add_device_from_node({
            "ip": "192.168.1.6",
            "short_name": "StageLeft",
            "long_name": "PrimusV3.5 LED Node | A0:Short Strip A1:Long Strip ",
            "node_report": "#0001 [0000] OK|PV3CAP1|0:1:0|1:2:1|B:v31|IP:D|F:RIOH",
            "num_ports": 2,
            "universes": [0, 1],
        }, auto_save=False)
        state.devices[0]["ip_config_pending"] = "static"
        state.devices[0]["ip_mode"] = "static"
        state.devices[0]["static_ip"] = "192.168.1.50"
        state.device_groups = [{
            "id": "group-a",
            "name": "Stage Group",
            "device_ips": ["192.168.1.6"],
        }]
        state._controller_device_ips = {"192.168.1.6"}

        self.assertEqual(state.discovery_targets(), ["192.168.1.6", "192.168.1.50"])

        refreshed = state.refresh_devices_from_nodes([{
            "ip": "192.168.1.50",
            "short_name": "StageLeft",
            "long_name": "PrimusV3.5 LED Node | A0:Short Strip A1:Long Strip ",
            "node_report": "#0001 [0000] OK|PV3CAP1|0:1:0|1:2:1|B:v31|IP:S|F:RIOH",
            "num_ports": 2,
            "universes": [0, 1],
        }], auto_save=False)

        self.assertEqual(refreshed[0]["old_ip"], "192.168.1.6")
        self.assertEqual(len(state.devices), 1)
        dev = state.devices[0]
        self.assertEqual(dev["ip"], "192.168.1.50")
        self.assertEqual(dev["sender"].ip, "192.168.1.50")
        self.assertIsNone(dev["ip_config_pending"])
        self.assertEqual(dev["ip_mode"], "static")
        self.assertEqual(dev["static_ip"], "192.168.1.50")
        self.assertEqual(state.device_groups[0]["device_ips"], ["192.168.1.50"])
        self.assertEqual(state._controller_device_ips, {"192.168.1.50"})

    def test_restore_devices_follows_saved_name_to_new_ip(self):
        saved = [{
            "ip": "192.168.1.6",
            "name": "NewPrimus1",
            "hardware_profile": "v31",
            "hardware_label": "V3.1 Reverse TFT",
        }]
        discovered = [{
            "ip": "192.168.1.2",
            "short_name": "NewPrimus1",
            "long_name": "PrimusV3.5 LED Node | A0:Short Strip A1:Long Strip ",
            "node_report": "#0001 [0000] OK|PV3CAP1|0:1:0|1:2:1|B:v31|F:RIOH",
            "capabilities": {
                "profile": "pv3cap1",
                "hardware_profile": "v31",
                "hardware_label": "V3.1 Reverse TFT",
                "firmware_version": "3.5",
                "known": True,
                "rename": True,
                "hello": True,
                "ip_config": True,
                "output_config": True,
            },
            "hardware_profile": "v31",
            "hardware_label": "V3.1 Reverse TFT",
            "firmware_version": "3.5",
            "num_ports": 2,
            "universes": [0, 1],
        }]

        state = ControllerState(None)
        with patch("state._load_devices", return_value=saved), \
                patch("artnet.discover_artnet_nodes", return_value=discovered), \
                patch("state._save_devices") as save_devices:
            state.restore_devices()

        self.assertEqual(len(state.devices), 1)
        dev = state.devices[0]
        self.assertEqual(dev["ip"], "192.168.1.2")
        self.assertTrue(dev["capabilities"]["rename"])
        self.assertTrue(dev["capabilities"]["hello"])
        save_devices.assert_called_once()

    def test_connect_all_can_skip_not_discovered_saved_devices(self):
        state = ControllerState(None)
        self.addCleanup(state.shutdown)
        state.add_device_from_node({
            "ip": "127.0.0.1",
            "short_name": "OnlineNode",
            "long_name": "",
            "num_ports": 0,
            "universes": [0, 1],
        }, auto_save=False)
        state.add_device_from_node({
            "ip": "127.0.0.2",
            "short_name": "StaleNode",
            "long_name": "",
            "num_ports": 0,
            "universes": [0, 1],
        }, auto_save=False)

        results = state.connect_all(only_ips={"127.0.0.1"})

        self.assertEqual(len(results), 2)
        self.assertTrue(results[0]["ok"])
        self.assertNotIn("skipped", results[0])
        self.assertTrue(state.devices[0]["connected"])
        self.assertTrue(results[1]["ok"])
        self.assertTrue(results[1]["skipped"])
        self.assertEqual(results[1]["reason"], "not discovered")
        self.assertFalse(state.devices[1]["connected"])


if __name__ == "__main__":
    unittest.main()
