"""Tests for device network sync helpers."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from artnet import is_compatible_node
from server import _sync_network_devices


class IsCompatibleNodeTests(unittest.TestCase):
    def test_primus_accepts_pv3cap1(self):
        node = {
            "ip": "10.0.0.1",
            "node_report": "PV3CAP1|B:v1|IP:D|F:RIOH",
            "short_name": "PrimusV3",
        }
        self.assertTrue(is_compatible_node(node, "primus"))

    def test_primus_accepts_radius_tag(self):
        node = {
            "ip": "10.0.0.2",
            "node_report": "PVRAD1|B:v1|IP:D|F:RA",
            "short_name": "Radius",
        }
        self.assertTrue(is_compatible_node(node, "primus"))

    def test_primus_accepts_legacy_without_radius_name(self):
        node = {
            "ip": "10.0.0.3",
            "node_report": "",
            "short_name": "PrimusV3 LED",
            "long_name": "Legacy node",
        }
        self.assertTrue(is_compatible_node(node, "primus"))

    def test_radius_accepts_pvrad1(self):
        node = {
            "ip": "10.0.0.2",
            "node_report": "PVRAD1|B:v1|IP:D|F:RA",
            "short_name": "Radius",
        }
        self.assertTrue(is_compatible_node(node, "radius"))

    def test_radius_accepts_name_fallback(self):
        node = {
            "ip": "10.0.0.4",
            "node_report": "",
            "short_name": "Radius Node",
            "long_name": "",
        }
        self.assertTrue(is_compatible_node(node, "radius"))

    def test_radius_rejects_primus_tag(self):
        node = {
            "ip": "10.0.0.1",
            "node_report": "PV3CAP1|B:v1|IP:D|F:RIOH",
            "short_name": "PrimusV3",
        }
        self.assertFalse(is_compatible_node(node, "radius"))


class SyncNetworkDevicesTests(unittest.TestCase):
    @patch("server.discover_artnet_nodes")
    @patch("server.sender_product")
    def test_sync_adds_compatible_nodes_and_connects_online(self, mock_product, mock_discover):
        mock_product.return_value = "primus"
        mock_discover.return_value = [
            {
                "ip": "192.168.1.10",
                "node_report": "PV3CAP1|B:v1|IP:D|F:RIOH",
                "short_name": "NodeA",
            },
            {
                "ip": "192.168.1.11",
                "node_report": "PVRAD1|B:v1|IP:D|F:RA",
                "short_name": "Radius",
            },
        ]
        state = MagicMock()
        state.monitor_only = False
        state.discovery_targets.return_value = ["192.168.1.10"]
        state.add_device_from_node.return_value = {
            "status": "added",
            "device_index": 0,
        }
        state.connect_all.return_value = [{"device_index": 0, "ok": True}]

        result = _sync_network_devices(state, interface="en0")

        mock_discover.assert_called_once_with(
            known_ips=["192.168.1.10"],
            timeout=3.5,
            interface="en0",
        )
        state.refresh_devices_from_nodes.assert_called_once()
        self.assertEqual(state.add_device_from_node.call_count, 2)
        state.connect_all.assert_called_once_with(
            only_ips={"192.168.1.10", "192.168.1.11"},
        )
        self.assertEqual(len(result["added"]), 2)
        added_ips = {item["ip"] for item in result["added"]}
        self.assertEqual(added_ips, {"192.168.1.10", "192.168.1.11"})
        self.assertEqual(result["skipped"], [])

    @patch("server.discover_artnet_nodes")
    @patch("server.sender_product")
    def test_sync_skips_existing_compatible_nodes(self, mock_product, mock_discover):
        mock_product.return_value = "radius"
        mock_discover.return_value = [
            {
                "ip": "192.168.1.20",
                "node_report": "PVRAD1|B:v1|IP:D|F:RA",
                "short_name": "Radius",
            },
        ]
        state = MagicMock()
        state.monitor_only = False
        state.discovery_targets.return_value = []
        state.add_device_from_node.return_value = {
            "status": "exists",
            "device_index": 0,
        }
        state.connect_all.return_value = [{"device_index": 0, "ok": True}]

        result = _sync_network_devices(state)

        state.add_device_from_node.assert_called_once()
        self.assertEqual(result["added"], [])

    @patch("server.discover_artnet_nodes")
    @patch("server.sender_product")
    def test_sync_never_connects_when_monitor_only(self, mock_product, mock_discover):
        mock_product.return_value = "primus"
        mock_discover.return_value = [
            {
                "ip": "192.168.1.10",
                "node_report": "PV3CAP1|B:v1|IP:D|F:RIOH",
                "short_name": "NodeA",
            },
        ]
        state = MagicMock()
        state.monitor_only = True
        state.discovery_targets.return_value = []
        state.add_device_from_node.return_value = {
            "status": "added",
            "device_index": 0,
        }

        result = _sync_network_devices(state)

        state.connect_all.assert_not_called()
        self.assertEqual(result["connected"], [])
        self.assertEqual(len(result["added"]), 1)


if __name__ == "__main__":
    unittest.main()
