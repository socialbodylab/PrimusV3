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
            "long_name": "PrimusV3.5 LED Node | A0:Grid 4x8 A1:Long Strip",
            "node_report": "#0001 [0000] OK|PV3CAP1|0:4:0|1:2:1|B:v1|F:RIOH",
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
        self.assertEqual(dev["outputs"][0]["type"], "small_grid")
        self.assertEqual(dev["outputs"][0]["universe"], 0)
        self.assertEqual(dev["outputs"][1]["type"], "long_strip")
        self.assertEqual(dev["outputs"][1]["universe"], 1)

    def test_existing_bare_manual_add_does_not_erase_discovered_metadata(self):
        state = ControllerState(None)
        state.add_device_from_node({
            "ip": "192.168.1.51",
            "short_name": "NewPrimus1",
            "long_name": "PrimusV3.5 LED Node | A0:Grid 4x8 A1:Long Strip",
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
        }, auto_save=False)

        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["device_index"], 0)
        self.assertEqual(len(state.devices), 1)
        dev = state.devices[0]
        self.assertEqual(dev["ip"], "192.168.1.2")
        self.assertEqual(dev["sender"].ip, "192.168.1.2")
        self.assertTrue(dev["capabilities"]["rename"])
        self.assertTrue(dev["capabilities"]["hello"])
        self.assertEqual(dev["outputs"][0]["type"], "short_strip")
        self.assertEqual(dev["outputs"][1]["type"], "long_strip")

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


if __name__ == "__main__":
    unittest.main()
