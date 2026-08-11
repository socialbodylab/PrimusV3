import os
import shutil
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import output_presets
import state
from primus_protocol import (
    DeviceConfig,
    IpMode,
    OFF_DESCRIPTOR,
    OperatingMode,
    OutputDescriptor,
    Layout,
    ReceiveMode,
    ScanPattern,
    StartCorner,
    TraversalAxis,
)
from state import ControllerState


GRID = OutputDescriptor(
    True,
    32,
    Layout.GRID,
    4,
    8,
    TraversalAxis.ROW_MAJOR,
    ScanPattern.SERPENTINE,
    StartCorner.TOP_LEFT,
    1,
)


class StateScratchMixin:
    def setUp(self):
        root = os.path.dirname(os.path.abspath(__file__))
        unique = f"mgmt-discovery-{os.getpid()}-{time.time_ns()}"
        self.scratch_root = os.path.join(root, ".scratch_management_state")
        self.scratch_dir = os.path.join(self.scratch_root, unique)
        os.makedirs(self.scratch_dir, exist_ok=True)
        self.state_path = os.path.join(self.scratch_dir, ".primus_state.json")
        self.radius_state_path = os.path.join(self.scratch_dir, ".radius_state.json")
        self.output_presets_path = os.path.join(self.scratch_dir, "output_presets.json")
        self.patches = [
            patch.object(state, "_state_file", return_value=self.state_path),
            patch.object(
                state.show_info_store, "primus_state_path", return_value=self.state_path),
            patch.object(
                state.show_info_store, "radius_state_path", return_value=self.radius_state_path),
            patch.object(
                state,
                "OutputPresetStore",
                side_effect=lambda *args, **kwargs: output_presets.OutputPresetStore(
                    path=self.output_presets_path
                ),
            ),
        ]
        for active in self.patches:
            active.start()

    def tearDown(self):
        for active in reversed(self.patches):
            active.stop()
        shutil.rmtree(self.scratch_dir, ignore_errors=True)
        if os.path.isdir(self.scratch_root) and not os.listdir(self.scratch_root):
            os.rmdir(self.scratch_root)


class ManagementDiscoveryTests(StateScratchMixin, unittest.TestCase):
    def sample_config(self, **overrides):
        values = {
            "operating_mode": OperatingMode.PRODUCTION,
            "unlock_window_open": False,
            "unlock_remaining_seconds": 0,
            "receive_mode": ReceiveMode.COMBINED,
            "base_universe": 27,
            "telemetry_target": "192.168.1.20",
            "ip_mode": IpMode.DHCP,
            "ip": "0.0.0.0",
            "gateway": "0.0.0.0",
            "subnet": "0.0.0.0",
            "outputs": (GRID, OFF_DESCRIPTOR),
            "technical_name": "Badge-A",
            "character_name": "Ariel",
            "performer_name": "Sam",
        }
        values.update(overrides)
        return DeviceConfig(**values)

    @patch("state._save_devices")
    @patch("state.get_primus_config")
    def test_add_device_prefers_authoritative_management_config(
        self, get_primus_config, save_devices
    ):
        get_primus_config.return_value = SimpleNamespace(config=self.sample_config())
        controller = ControllerState(None)

        result = controller.add_device_from_node({
            "ip": "192.168.1.50",
            "short_name": "Discovery-Short",
            "node_report": "#0001 [0123] OK|PV3CAP1|F:RIOHBMSG|B:v31|IP:D|U:C:0|G:1L|0:1:0:30|1:2:0:72",
            "capabilities": {
                "profile": "pv3cap1",
                "known": True,
                "rename": True,
                "hello": True,
                "ip_config": True,
                "output_config": True,
                "receive_config": True,
                "show_info": True,
            },
            "outputs": [
                {"name": "A0", "type": "short_strip", "universe": 0},
                {"name": "A1", "type": "long_strip", "universe": 0},
            ],
            "universes": [0, 0],
        }, auto_save=False)

        dev = controller.devices[result["device_index"]]
        self.assertEqual(dev["name"], "Badge-A")
        self.assertEqual(dev["character_name"], "Ariel")
        self.assertEqual(dev["performer_name"], "Sam")
        self.assertEqual(dev["receive_mode"], "combined")
        self.assertEqual(dev["base_universe"], 27)
        self.assertTrue(dev["management_supported"])
        self.assertEqual(dev["management_protocol_version"], 1)
        self.assertEqual(dev["telemetry_target"], "192.168.1.20")
        self.assertTrue(dev["management_locked"])
        self.assertEqual(
            [(output["name"], output["type"], output["virtual_pixels"]) for output in dev["outputs"]],
            [("A0", "small_grid", 1), ("A1", "none", 0)],
        )
        get_primus_config.assert_called_once_with(
            "192.168.1.50", source_ip=None, dest_port=6454)
        save_devices.assert_not_called()

    @patch("state._save_devices")
    @patch("state.get_primus_config")
    def test_refresh_timeout_preserves_existing_management_state(
        self, get_primus_config, save_devices
    ):
        linear = OutputDescriptor(
            True,
            72,
            Layout.LINEAR,
            0,
            0,
            TraversalAxis.ROW_MAJOR,
            ScanPattern.PROGRESSIVE,
            StartCorner.TOP_LEFT,
            72,
        )
        get_primus_config.return_value = SimpleNamespace(config=self.sample_config(
            receive_mode=ReceiveMode.SPLIT,
            base_universe=20,
            ip_mode=IpMode.STATIC,
            ip="192.168.1.51",
            gateway="192.168.1.1",
            subnet="255.255.255.0",
            outputs=(OFF_DESCRIPTOR, linear),
        ))
        controller = ControllerState(None)
        result = controller.add_device_from_node({
            "ip": "192.168.1.51",
            "short_name": "Badge-A",
            "node_report": "#0001 [0123] OK|PV3CAP1|F:RIOHBMSG|B:v31|IP:D|U:S:20|G:1P|0:0:20:0|1:2:21:72",
            "capabilities": {
                "profile": "pv3cap1",
                "known": True,
                "rename": True,
                "hello": True,
                "ip_config": True,
                "output_config": True,
                "receive_config": True,
                "show_info": True,
            },
            "outputs": [
                {"name": "A0", "type": "none", "universe": 20},
                {"name": "A1", "type": "long_strip", "universe": 21},
            ],
            "universes": [20, 21],
        }, auto_save=False)
        dev = controller.devices[result["device_index"]]
        prior = (
            dev["name"],
            dev["receive_mode"],
            dev["base_universe"],
            [(item["name"], item["type"], item["universe"]) for item in dev["outputs"]],
        )

        get_primus_config.side_effect = state.PrimusManagementTimeout("timed out")
        controller.refresh_devices_from_nodes([{
            "ip": "192.168.1.51",
            "short_name": "Discovery-Rename",
            "node_report": "#0001 [0124] OK|PV3CAP1|F:RIOHBMSG|B:v31|IP:D|U:C:0|G:1L|1:1:0:30",
            "capabilities": {
                "profile": "pv3cap1",
                "known": True,
                "rename": True,
                "hello": True,
                "ip_config": True,
                "output_config": True,
                "receive_config": True,
                "show_info": True,
            },
            "outputs": [
                {"name": "A1", "type": "short_strip", "universe": 0},
            ],
            "universes": [0, 0],
        }], auto_save=False)

        self.assertEqual(
            (
                dev["name"],
                dev["receive_mode"],
                dev["base_universe"],
                [(item["name"], item["type"], item["universe"]) for item in dev["outputs"]],
            ),
            prior,
        )
        self.assertTrue(dev["management_supported"])
        self.assertEqual(dev["management_protocol_version"], 1)
        self.assertEqual(
            [(item["name"], item["type"]) for item in dev["outputs"]],
            [("A0", "none"), ("A1", "long_strip")],
        )
        self.assertEqual(dev["outputs"][0]["universe"], 20)
        self.assertEqual(dev["outputs"][1]["universe"], 21)
        self.assertEqual(dev["ip_mode"], "static")
        self.assertEqual(dev["static_ip"], "192.168.1.51")
        self.assertEqual(dev["gateway"], "192.168.1.1")
        self.assertEqual(dev["subnet"], "255.255.255.0")
        save_devices.assert_not_called()

    @patch("state.get_primus_config")
    def test_radius_nodes_never_query_primus_management(self, get_primus_config):
        controller = ControllerState(None)
        controller.add_device_from_node({
            "ip": "192.168.1.60",
            "short_name": "Radius",
            "node_report": "PVRAD1|B:v1|IP:D|F:RA",
            "capabilities": {
                "profile": "pvrad1",
                "device_class": "radius",
                "known": True,
                "show_info": True,
            },
        }, auto_save=False)
        self.assertFalse(get_primus_config.called)

    @patch("state.get_primus_config")
    def test_add_device_authoritative_query_releases_main_lock(self, get_primus_config):
        controller = ControllerState(None)
        entered = threading.Event()
        release = threading.Event()
        result = {}

        def block_query(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(1.0))
            return SimpleNamespace(config=self.sample_config())

        get_primus_config.side_effect = block_query

        node = {
            "ip": "192.168.1.50",
            "short_name": "Discovery-Short",
            "node_report": "#0001 [0123] OK|PV3CAP1|F:RIOHBMSG|B:v31|IP:D|U:C:0|G:1L|0:1:0:30|1:2:0:72",
            "capabilities": {
                "profile": "pv3cap1",
                "known": True,
                "rename": True,
                "hello": True,
                "ip_config": True,
                "output_config": True,
                "receive_config": True,
                "show_info": True,
            },
            "outputs": [
                {"name": "A0", "type": "short_strip", "universe": 0},
                {"name": "A1", "type": "long_strip", "universe": 0},
            ],
            "universes": [0, 0],
        }

        thread = threading.Thread(
            target=lambda: result.setdefault("value", controller.add_device_from_node(node, auto_save=False))
        )
        thread.start()
        self.assertTrue(entered.wait(1.0))
        self.assertTrue(controller.lock.acquire(timeout=0.5))
        controller.lock.release()
        release.set()
        thread.join(1.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result["value"]["status"], "added")


if __name__ == "__main__":
    unittest.main()
