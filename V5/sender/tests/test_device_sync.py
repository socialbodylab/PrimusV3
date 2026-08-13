"""Tests for device network sync helpers."""

import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import server as server_module
import state as state_module
from artnet import is_compatible_node
from server import _sync_network_devices
from state import ControllerState


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
    def tearDown(self):
        # A failed test must not leave a stuck in-flight marker that makes
        # every later sync test wait on a job that will never finish.
        with server_module._device_sync_lock:
            server_module._device_sync_inflight = None

    @patch("server.discover_artnet_nodes")
    @patch("server.sender_product")
    def test_sync_adds_compatible_nodes_without_connecting(self, mock_product, mock_discover):
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
        # add_device_from_node refreshes existing devices itself; a separate
        # refresh pre-pass would repeat every node's work (including the
        # Setup-lane config query for management-capable nodes).
        state.refresh_devices_from_nodes.assert_not_called()
        self.assertEqual(state.add_device_from_node.call_count, 2)
        for call in state.add_device_from_node.call_args_list:
            self.assertFalse(call.kwargs.get("auto_save", True))
        # Batched persistence: one save at the end instead of one per node.
        state.save_devices.assert_called_once()
        # Sync is discovery-only: connecting arms DMX (incl. keepalive
        # frames) and must always be an explicit operator action, because
        # production color data usually comes from an external console.
        state.connect_all.assert_not_called()
        self.assertEqual(result["connected"], [])
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
        # Nothing changed, so nothing was written.
        state.save_devices.assert_not_called()

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

    @patch("server.discover_artnet_nodes")
    @patch("server.sender_product")
    def test_sync_still_refreshes_known_incompatible_nodes(self, mock_product, mock_discover):
        # An incompatible reply can still be a device we already track (e.g.
        # a garbled node report) — its refresh must survive the removal of
        # the refresh pre-pass.
        mock_product.return_value = "radius"
        primus_node = {
            "ip": "192.168.1.30",
            "node_report": "PV3CAP1|B:v1|IP:D|F:RIOH",
            "short_name": "PrimusV3",
        }
        mock_discover.return_value = [primus_node]
        state = MagicMock()
        state.monitor_only = False
        state.discovery_targets.return_value = []
        state.refresh_devices_from_nodes.return_value = []

        result = _sync_network_devices(state)

        state.add_device_from_node.assert_not_called()
        state.refresh_devices_from_nodes.assert_called_once_with(
            [primus_node], auto_save=False)
        state.save_devices.assert_not_called()
        self.assertEqual(result["skipped"], [
            {"ip": "192.168.1.30", "reason": "incompatible"},
        ])

    @patch("server.discover_artnet_nodes")
    @patch("server.sender_product")
    def test_overlapping_syncs_coalesce_to_one_discovery(self, mock_product, mock_discover):
        mock_product.return_value = "primus"
        release = threading.Event()
        discover_calls = []

        def blocking_discover(**_kwargs):
            discover_calls.append(1)
            release.wait(timeout=5.0)
            return []

        mock_discover.side_effect = blocking_discover
        state = MagicMock()
        state.discovery_targets.return_value = []

        results = {}

        def run_sync(slot):
            results[slot] = _sync_network_devices(state)

        first = threading.Thread(target=run_sync, args=("first",))
        first.start()
        # Wait until the first sync is inside discovery, then start a second.
        for _ in range(500):
            if discover_calls:
                break
            first.join(timeout=0.01)
        second = threading.Thread(target=run_sync, args=("second",))
        second.start()
        # Give the second thread a moment to reach the guard, then release.
        second.join(timeout=0.05)
        release.set()
        first.join(timeout=5.0)
        second.join(timeout=5.0)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())

        # One discovery sweep served both callers.
        self.assertEqual(len(discover_calls), 1)
        self.assertEqual(results["first"], results["second"])
        self.assertIsNone(server_module._device_sync_inflight)


class SyncSingleSaveTests(unittest.TestCase):
    """The sync loop batches persistence: one state-file write per pass."""

    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        state_path = os.path.join(scratch.name, ".primus_state.json")
        radius_path = os.path.join(scratch.name, ".radius_state.json")
        for target in (
            patch.object(state_module, "_state_file", return_value=state_path),
            patch.object(state_module.show_info_store, "primus_state_path",
                         return_value=state_path),
            patch.object(state_module.show_info_store, "radius_state_path",
                         return_value=radius_path),
        ):
            target.start()
            self.addCleanup(target.stop)
        with server_module._device_sync_lock:
            server_module._device_sync_inflight = None

    @patch("server.discover_artnet_nodes")
    @patch("server.sender_product")
    @patch("state._save_device_groups")
    @patch("state._save_devices")
    def test_sync_writes_state_file_once_for_many_nodes(
            self, save_devices, save_groups, mock_product, mock_discover):
        mock_product.return_value = "primus"
        mock_discover.return_value = [
            {
                "ip": "192.0.2.10",
                "node_report": "PV3CAP1|B:v1|IP:D|F:RIOH",
                "short_name": "NodeA",
                "universes": [0, 1],
            },
            {
                "ip": "192.0.2.11",
                "node_report": "PV3CAP1|B:v1|IP:D|F:RIOH",
                "short_name": "NodeB",
                "universes": [2, 3],
            },
        ]
        controller = ControllerState(None)

        result = _sync_network_devices(controller)

        self.assertEqual(len(result["added"]), 2)
        self.assertEqual(len(controller.devices), 2)
        self.assertEqual(save_devices.call_count, 1)

    @patch("server.discover_artnet_nodes")
    @patch("server.sender_product")
    @patch("state.get_primus_config")
    @patch("state._save_device_groups")
    @patch("state._save_devices")
    def test_sync_queries_management_config_once_per_node(
            self, save_devices, save_groups, mock_config, mock_product,
            mock_discover):
        # A known management-capable node used to pay two Setup-lane config
        # round trips per sync (refresh pre-pass + add pass), each up to ~1 s.
        mock_product.return_value = "primus"
        node = {
            "ip": "192.0.2.12",
            "node_report": "PV3CAP1|B:v31|IP:D|F:RIOHBMS|G:1P",
            "short_name": "NodeC",
            "universes": [0, 1],
        }
        mock_discover.return_value = [node]
        mock_config.side_effect = OSError("setup lane unreachable")
        controller = ControllerState(None)
        _sync_network_devices(controller)
        self.assertEqual(len(controller.devices), 1)

        mock_config.reset_mock()
        with server_module._device_sync_lock:
            server_module._device_sync_inflight = None
        _sync_network_devices(controller)
        self.assertEqual(mock_config.call_count, 1)


if __name__ == "__main__":
    unittest.main()
