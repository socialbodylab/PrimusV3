import os
import shutil
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import output_presets
import state
from primus_protocol import (
    DeviceConfig,
    IpMode,
    Layout,
    OFF_DESCRIPTOR,
    OperatingMode,
    OutputDescriptor,
    ReceiveMode,
    ScanPattern,
    StartCorner,
    TraversalAxis,
)
from state import ControllerState, _load_devices, _save_devices


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
        unique = f"mgmt-state-{os.getpid()}-{time.time_ns()}"
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

    def make_config(self, **overrides):
        values = {
            "operating_mode": OperatingMode.PROTOTYPE,
            "unlock_window_open": False,
            "unlock_remaining_seconds": 0,
            "receive_mode": ReceiveMode.SPLIT,
            "base_universe": 10,
            "telemetry_target": "0.0.0.0",
            "ip_mode": IpMode.DHCP,
            "ip": "0.0.0.0",
            "gateway": "0.0.0.0",
            "subnet": "0.0.0.0",
            "outputs": (
                OutputDescriptor(
                    True,
                    30,
                    Layout.LINEAR,
                    0,
                    0,
                    TraversalAxis.ROW_MAJOR,
                    ScanPattern.PROGRESSIVE,
                    StartCorner.TOP_LEFT,
                    30,
                ),
                OutputDescriptor(
                    True,
                    72,
                    Layout.LINEAR,
                    0,
                    0,
                    TraversalAxis.ROW_MAJOR,
                    ScanPattern.PROGRESSIVE,
                    StartCorner.TOP_LEFT,
                    72,
                ),
            ),
            "technical_name": "Badge-A",
            "character_name": "Chorus",
            "performer_name": "Taylor",
        }
        values.update(overrides)
        return DeviceConfig(**values)

    def make_management_device(self, ip="192.168.1.90", name="Badge-A"):
        sender = Mock()
        sender.connected = False
        return {
            "name": name,
            "character_name": "Chorus",
            "performer_name": "Taylor",
            "ip": ip,
            "base_universe": 10,
            "receive_mode": "split",
            "connected": False,
            "sender": sender,
            "transport_error": None,
            "send_fail_streak": 0,
            "capabilities": {
                "profile": "pv3cap1",
                "known": True,
                "rename": True,
                "hello": True,
                "ip_config": True,
                "output_config": True,
                "receive_config": True,
                "show_info": True,
                "management": True,
                "management_protocol_version": 1,
            },
            "management_supported": True,
            "management_protocol": "primus",
            "management_protocol_version": 1,
            "max_pixels_per_port": 170,
            "max_combined_pixels": 170,
            "operating_mode": "prototype",
            "production_mode": False,
            "management_locked": False,
            "unlock_window_open": False,
            "unlock_remaining_seconds": 0,
            "telemetry_target": "0.0.0.0",
            "telemetry_configured": False,
            "ip_mode": "dhcp",
            "static_ip": None,
            "gateway": None,
            "subnet": None,
            "ip_config_pending": None,
            "outputs": [
                {
                    "name": "A0",
                    "physical_slot": 0,
                    "type": "short_strip",
                    "enabled": True,
                    "count": 30,
                    "physical_pixels": 30,
                    "layout": "linear",
                    "descriptor_layout": "linear",
                    "rows": 0,
                    "columns": 0,
                    "traversal_axis": "row_major",
                    "scan_pattern": "progressive",
                    "start_corner": "top_left",
                    "virtual_pixels": 30,
                    "universe": 10,
                    "grid_order": "progressive",
                    "grid_rotation": 0,
                },
                {
                    "name": "A1",
                    "physical_slot": 1,
                    "type": "long_strip",
                    "enabled": True,
                    "count": 72,
                    "physical_pixels": 72,
                    "layout": "linear",
                    "descriptor_layout": "linear",
                    "rows": 0,
                    "columns": 0,
                    "traversal_axis": "row_major",
                    "scan_pattern": "progressive",
                    "start_corner": "top_left",
                    "virtual_pixels": 72,
                    "universe": 11,
                    "grid_order": "progressive",
                    "grid_rotation": 0,
                },
            ],
        }

    def make_controller(self, monitor_only=False, devices=None):
        controller = ControllerState(None, monitor_only=monitor_only)
        controller.devices = devices or [self.make_management_device()]
        return controller


class ManagementStateTests(StateScratchMixin, unittest.TestCase):
    @patch("state._save_devices")
    @patch("state.get_primus_config")
    @patch("state.set_primus_output_descriptors")
    def test_set_device_output_type_uses_management_and_refreshes(
        self, set_descriptors, get_config, save_devices
    ):
        controller = self.make_controller()
        get_config.return_value = SimpleNamespace(config=self.make_config(outputs=(GRID, self.make_config().outputs[1])))

        result = controller.set_device_output_type(0, 0, "small_grid")

        self.assertTrue(result["ok"])
        self.assertTrue(result["applied_to_device"])
        self.assertEqual(controller.devices[0]["outputs"][0]["type"], "small_grid")
        self.assertFalse(controller.devices[0]["connected"])
        controller.devices[0]["sender"].connect.assert_not_called()
        set_descriptors.assert_called_once()
        get_config.assert_called_once_with("192.168.1.90", source_ip=None, dest_port=6454)
        save_devices.assert_called_once()

    @patch("state.get_primus_config", side_effect=state.PrimusManagementTimeout("timed out"))
    @patch("state.set_primus_output_descriptors")
    def test_refresh_failure_after_ack_returns_pending_local_output_state(
        self, set_descriptors, get_config
    ):
        controller = self.make_controller()
        controller.devices[0]["transport_error"] = "existing DMX transport error"
        controller.devices[0]["send_fail_streak"] = 3

        result = controller.set_device_output_type(0, 0, "small_grid")

        self.assertTrue(result["ok"])
        self.assertTrue(result["readback_pending"])
        self.assertIn("readback failed", result["warning"])
        self.assertEqual(
            [(output["name"], output["type"]) for output in controller.devices[0]["outputs"]],
            [("A0", "small_grid"), ("A1", "long_strip")],
        )
        self.assertEqual(result["config"]["outputs"][0]["type"], "small_grid")
        self.assertEqual(
            controller.devices[0]["transport_error"], "existing DMX transport error"
        )
        self.assertEqual(controller.devices[0]["send_fail_streak"], 3)
        set_descriptors.assert_called_once()
        get_config.assert_called_once()

    @patch("state.set_primus_output_descriptors", side_effect=state.PrimusManagementLocked(
        "192.168.1.90", 0x10, 1, 5))
    def test_locked_management_error_returns_conflict_details(self, set_descriptors):
        controller = self.make_controller()

        result = controller.set_device_output_type(0, 0, "small_grid")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "Locked")
        self.assertEqual(result["http_status"], 409)
        self.assertEqual(controller.devices[0]["outputs"][0]["type"], "short_strip")
        set_descriptors.assert_called_once()

    @patch("state._save_devices")
    @patch("state.get_primus_config")
    @patch("state.set_primus_receive_config")
    def test_receive_mode_management_is_monitor_safe(
        self, set_receive_config, get_config, save_devices
    ):
        controller = self.make_controller(monitor_only=True)
        get_config.return_value = SimpleNamespace(config=self.make_config(
            receive_mode=ReceiveMode.COMBINED,
            base_universe=44,
        ))

        result = controller.set_device_receive_mode(0, "combined", 44)

        self.assertTrue(result["ok"])
        self.assertFalse(controller.devices[0]["connected"])
        controller.devices[0]["sender"].connect.assert_not_called()
        set_receive_config.assert_called_once()
        save_devices.assert_called_once()

    @patch("state._save_devices")
    @patch("state.get_primus_config")
    @patch("state.set_primus_identity")
    def test_show_info_and_rename_route_through_identity(
        self, set_identity, get_config, save_devices
    ):
        controller = self.make_controller()
        get_config.return_value = SimpleNamespace(config=self.make_config(
            technical_name="Badge-Renamed",
            character_name="Lead",
            performer_name="Morgan",
        ))

        rename_result = controller.rename_device(0, "Badge-Renamed")
        show_result = controller.update_device_show_info(
            0, character_name="Lead", performer_name="Morgan")

        self.assertTrue(rename_result["ok"])
        self.assertTrue(show_result["ok"])
        self.assertEqual(controller.devices[0]["name"], "Badge-Renamed")
        self.assertEqual(controller.devices[0]["character_name"], "Lead")
        self.assertEqual(controller.devices[0]["performer_name"], "Morgan")
        self.assertEqual(set_identity.call_count, 2)
        save_devices.assert_called()

    @patch("state._save_devices")
    @patch("state.get_primus_config")
    @patch("state.unlock_primus_boot_window")
    @patch("state.set_primus_operating_mode")
    @patch("state.set_primus_telemetry_target")
    @patch("state.set_primus_ip_config")
    def test_management_ip_telemetry_mode_and_unlock_methods(
        self,
        set_ip_config,
        set_telemetry_target,
        set_operating_mode,
        unlock_boot_window,
        get_config,
        save_devices,
    ):
        controller = self.make_controller()
        get_config.side_effect = [
            SimpleNamespace(config=self.make_config(
                telemetry_target="192.168.1.40",
                ip_mode=IpMode.STATIC,
                ip="192.168.1.91",
                gateway="192.168.1.1",
                subnet="255.255.255.0",
            )),
            SimpleNamespace(config=self.make_config(
                operating_mode=OperatingMode.PRODUCTION,
                telemetry_target="192.168.1.40",
                ip_mode=IpMode.STATIC,
                ip="192.168.1.91",
                gateway="192.168.1.1",
                subnet="255.255.255.0",
            )),
            SimpleNamespace(config=self.make_config(
                operating_mode=OperatingMode.PROTOTYPE,
                telemetry_target="192.168.1.40",
                ip_mode=IpMode.STATIC,
                ip="192.168.1.91",
                gateway="192.168.1.1",
                subnet="255.255.255.0",
                unlock_window_open=False,
            )),
        ]

        ip_result = controller.set_device_ip(
            0, "192.168.1.91", "192.168.1.1", "255.255.255.0")
        telemetry_result = controller.set_device_telemetry_target(0, "192.168.1.40")
        production_result = controller.enter_device_production_mode(0)
        unlock_result = controller.unlock_device_boot_window(0)

        self.assertTrue(ip_result["ok"])
        self.assertTrue(ip_result["pending_reconnect"])
        self.assertTrue(telemetry_result["ok"])
        self.assertTrue(production_result["ok"])
        self.assertTrue(unlock_result["ok"])
        self.assertEqual(controller.devices[0]["static_ip"], "192.168.1.91")
        self.assertEqual(controller.devices[0]["telemetry_target"], "192.168.1.40")
        self.assertEqual(controller.devices[0]["operating_mode"], "prototype")
        self.assertFalse(controller.devices[0]["management_locked"])
        set_ip_config.assert_called_once()
        set_telemetry_target.assert_called_once()
        set_operating_mode.assert_called_once()
        unlock_boot_window.assert_called_once()
        self.assertGreaterEqual(save_devices.call_count, 4)

    @patch("state._save_devices")
    @patch("state.get_primus_config")
    @patch("state.set_primus_ip_config")
    def test_management_ip_ack_does_not_query_address_that_is_restarting(
        self, set_ip_config, get_config, save_devices
    ):
        controller = self.make_controller()

        static_result = controller.set_device_ip(
            0, "192.168.1.91", "192.168.1.1", "255.255.255.0")
        dhcp_result = controller.revert_device_dhcp(0)

        self.assertTrue(static_result["ok"])
        self.assertTrue(static_result["pending_reconnect"])
        self.assertTrue(dhcp_result["ok"])
        self.assertTrue(dhcp_result["pending_reconnect"])
        self.assertEqual(controller.devices[0]["ip_mode"], "dhcp")
        self.assertEqual(controller.devices[0]["ip_config_pending"], "dhcp")
        self.assertIsNone(controller.devices[0]["static_ip"])
        self.assertEqual(set_ip_config.call_count, 2)
        get_config.assert_not_called()
        self.assertEqual(save_devices.call_count, 2)

    @patch("state.get_primus_config")
    @patch("state.set_primus_output_descriptors")
    def test_management_mutation_releases_main_lock_during_network_io(
        self, set_descriptors, get_config
    ):
        controller = self.make_controller()
        get_config.return_value = SimpleNamespace(
            config=self.make_config(outputs=(GRID, self.make_config().outputs[1]))
        )
        entered = threading.Event()
        release = threading.Event()
        result = {}

        def block_send(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(1.0))

        set_descriptors.side_effect = block_send

        thread = threading.Thread(
            target=lambda: result.setdefault(
                "value", controller.set_device_output_type(0, 0, "small_grid"))
        )
        thread.start()
        self.assertTrue(entered.wait(1.0))
        self.assertTrue(controller.lock.acquire(timeout=0.5))
        controller.lock.release()
        release.set()
        thread.join(1.0)

        self.assertFalse(thread.is_alive())
        self.assertTrue(result["value"]["ok"])

    @patch("state.get_primus_config")
    def test_explicit_refresh_releases_main_lock_during_readback(self, get_config):
        controller = self.make_controller()
        entered = threading.Event()
        release = threading.Event()
        result = {}

        def block_refresh(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(1.0))
            return SimpleNamespace(config=self.make_config())

        get_config.side_effect = block_refresh

        thread = threading.Thread(
            target=lambda: result.setdefault("value", controller.refresh_device_full_config(0))
        )
        thread.start()
        self.assertTrue(entered.wait(1.0))
        self.assertTrue(controller.lock.acquire(timeout=0.5))
        controller.lock.release()
        release.set()
        thread.join(1.0)

        self.assertFalse(thread.is_alive())
        self.assertTrue(result["value"]["ok"])

    @patch("state.get_primus_config")
    @patch("state.set_primus_output_descriptors")
    def test_same_device_management_mutations_serialize(self, set_descriptors, get_config):
        controller = self.make_controller()
        sent_descriptors = []
        readback_entered = threading.Event()
        release_first_readback = threading.Event()
        results = {}

        def send_side_effect(ip, descriptors, source_ip=None, dest_port=None):
            sent_descriptors.append(tuple(descriptors))

        def readback_side_effect(ip, source_ip=None, dest_port=None):
            if len(sent_descriptors) == 1:
                readback_entered.set()
                self.assertTrue(release_first_readback.wait(1.0))
            return SimpleNamespace(config=self.make_config(outputs=sent_descriptors[-1]))

        set_descriptors.side_effect = send_side_effect
        get_config.side_effect = readback_side_effect

        first = threading.Thread(
            target=lambda: results.setdefault(
                "first", controller.set_device_output_type(0, 0, "small_grid"))
        )
        second = threading.Thread(
            target=lambda: results.setdefault(
                "second", controller.set_device_virtual_resolution(0, 0, virtual_pixels=7))
        )

        first.start()
        self.assertTrue(readback_entered.wait(1.0))
        second.start()
        time.sleep(0.05)
        self.assertEqual(set_descriptors.call_count, 1)
        release_first_readback.set()
        first.join(1.0)
        second.join(1.0)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(set_descriptors.call_count, 2)
        self.assertTrue(results["first"]["ok"])
        self.assertTrue(results["second"]["ok"])

    @patch("state.get_primus_config")
    @patch("state.set_primus_output_descriptors")
    def test_different_devices_can_perform_management_io_concurrently(
        self, set_descriptors, get_config
    ):
        controller = self.make_controller(devices=[
            self.make_management_device(ip="192.168.1.90", name="Badge-A"),
            self.make_management_device(ip="192.168.1.91", name="Badge-B"),
        ])
        active_lock = threading.Lock()
        started = set()
        both_started = threading.Event()
        release = threading.Event()
        active = 0
        max_active = 0
        results = {}
        sent = {}

        def send_side_effect(ip, descriptors, source_ip=None, dest_port=None):
            nonlocal active, max_active
            sent[ip] = tuple(descriptors)
            with active_lock:
                active += 1
                max_active = max(max_active, active)
                started.add(ip)
                if len(started) == 2:
                    both_started.set()
            self.assertTrue(both_started.wait(1.0))
            self.assertTrue(release.wait(1.0))
            with active_lock:
                active -= 1

        def readback_side_effect(ip, source_ip=None, dest_port=None):
            return SimpleNamespace(config=self.make_config(
                technical_name="Badge-A" if ip.endswith(".90") else "Badge-B",
                outputs=sent[ip],
            ))

        set_descriptors.side_effect = send_side_effect
        get_config.side_effect = readback_side_effect

        first = threading.Thread(
            target=lambda: results.setdefault(
                "first", controller.set_device_output_type(0, 0, "small_grid"))
        )
        second = threading.Thread(
            target=lambda: results.setdefault(
                "second", controller.set_device_output_type(1, 0, "small_grid"))
        )
        first.start()
        second.start()
        self.assertTrue(both_started.wait(1.0))
        release.set()
        first.join(1.0)
        second.join(1.0)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(max_active, 2)
        self.assertTrue(results["first"]["ok"])
        self.assertTrue(results["second"]["ok"])

    def test_management_ack_then_readback_timeout_applies_expected_local_state(self):
        cases = [
            {
                "name": "descriptor",
                "patch_target": "state.set_primus_output_descriptors",
                "call": lambda controller: controller.apply_device_output_descriptor(0, 0, {
                    "enabled": True,
                    "layout": "grid",
                    "rows": 4,
                    "columns": 8,
                    "virtual_pixels": 7,
                }),
                "assertions": lambda device, result: (
                    self.assertEqual(device["outputs"][0]["type"], state.CUSTOM_OUTPUT_TYPE),
                    self.assertEqual(device["outputs"][0]["virtual_pixels"], 7),
                    self.assertEqual(result["config"]["outputs"][0]["descriptor_layout"], "grid"),
                ),
            },
            {
                "name": "output type",
                "patch_target": "state.set_primus_output_descriptors",
                "call": lambda controller: controller.set_device_output_type(0, 0, "small_grid"),
                "assertions": lambda device, result: (
                    self.assertEqual(device["outputs"][0]["type"], "small_grid"),
                    self.assertEqual(result["config"]["outputs"][0]["type"], "small_grid"),
                ),
            },
            {
                "name": "virtual resolution",
                "patch_target": "state.set_primus_output_descriptors",
                "call": lambda controller: controller.set_device_virtual_resolution(
                    0, 0, virtual_pixels=7),
                "assertions": lambda device, result: (
                    self.assertEqual(device["outputs"][0]["virtual_pixels"], 7),
                    self.assertEqual(result["config"]["outputs"][0]["virtual_pixels"], 7),
                ),
            },
            {
                "name": "rename",
                "patch_target": "state.set_primus_identity",
                "call": lambda controller: controller.rename_device(0, "Badge-Renamed"),
                "assertions": lambda device, result: (
                    self.assertEqual(device["name"], "Badge-Renamed"),
                    self.assertEqual(result["config"]["technical_name"], "Badge-Renamed"),
                ),
            },
            {
                "name": "show info",
                "patch_target": "state.set_primus_identity",
                "call": lambda controller: controller.update_device_show_info(
                    0, character_name="Lead", performer_name="Morgan"),
                "assertions": lambda device, result: (
                    self.assertEqual(device["character_name"], "Lead"),
                    self.assertEqual(device["performer_name"], "Morgan"),
                    self.assertTrue(result["applied_to_device"]),
                ),
            },
            {
                "name": "receive config",
                "patch_target": "state.set_primus_receive_config",
                "call": lambda controller: controller.set_device_receive_mode(0, "combined", 44),
                "assertions": lambda device, result: (
                    self.assertEqual(device["receive_mode"], "combined"),
                    self.assertEqual(device["base_universe"], 44),
                    self.assertEqual(result["config"]["base_universe"], 44),
                ),
            },
            {
                "name": "telemetry",
                "patch_target": "state.set_primus_telemetry_target",
                "call": lambda controller: controller.set_device_telemetry_target(
                    0, "192.168.1.40"),
                "assertions": lambda device, result: (
                    self.assertEqual(device["telemetry_target"], "192.168.1.40"),
                    self.assertTrue(result["config"]["telemetry_configured"]),
                ),
            },
            {
                "name": "production mode",
                "patch_target": "state.set_primus_operating_mode",
                "call": lambda controller: controller.enter_device_production_mode(0),
                "assertions": lambda device, result: (
                    self.assertEqual(device["operating_mode"], "production"),
                    self.assertTrue(device["management_locked"]),
                    self.assertEqual(result["config"]["operating_mode"], "production"),
                ),
            },
            {
                "name": "boot unlock",
                "patch_target": "state.unlock_primus_boot_window",
                "setup": lambda controller: controller.devices[0].update({
                    "operating_mode": "production",
                    "production_mode": True,
                    "management_locked": True,
                    "unlock_window_open": True,
                    "unlock_remaining_seconds": 9,
                }),
                "call": lambda controller: controller.unlock_device_boot_window(0),
                "assertions": lambda device, result: (
                    self.assertEqual(device["operating_mode"], "prototype"),
                    self.assertFalse(device["management_locked"]),
                    self.assertFalse(device["unlock_window_open"]),
                    self.assertEqual(result["config"]["unlock_remaining_seconds"], 0),
                ),
            },
        ]

        for case in cases:
            with self.subTest(case["name"]):
                controller = self.make_controller()
                if "setup" in case:
                    case["setup"](controller)
                with patch(case["patch_target"]), patch(
                    "state.get_primus_config",
                    side_effect=state.PrimusManagementTimeout("timed out"),
                ):
                    result = case["call"](controller)
                self.assertTrue(result["ok"])
                self.assertTrue(result["readback_pending"])
                self.assertIn("readback failed", result["warning"])
                case["assertions"](controller.devices[0], result)

    def test_management_ip_ack_applies_expected_pending_reconnect_state(self):
        cases = [
            {
                "name": "static",
                "call": lambda controller: controller.set_device_ip(
                    0, "192.168.1.91", "192.168.1.1", "255.255.255.0"),
                "assertions": lambda device, result: (
                    self.assertEqual(device["ip_mode"], "static"),
                    self.assertEqual(device["static_ip"], "192.168.1.91"),
                    self.assertEqual(device["ip_config_pending"], "static"),
                    self.assertTrue(result["pending_reconnect"]),
                ),
            },
            {
                "name": "dhcp",
                "setup": lambda controller: controller.devices[0].update({
                    "ip_mode": "static",
                    "static_ip": "192.168.1.91",
                    "gateway": "192.168.1.1",
                    "subnet": "255.255.255.0",
                }),
                "call": lambda controller: controller.revert_device_dhcp(0),
                "assertions": lambda device, result: (
                    self.assertEqual(device["ip_mode"], "dhcp"),
                    self.assertIsNone(device["static_ip"]),
                    self.assertEqual(device["ip_config_pending"], "dhcp"),
                    self.assertTrue(result["pending_reconnect"]),
                ),
            },
        ]

        for case in cases:
            with self.subTest(case["name"]):
                controller = self.make_controller()
                if "setup" in case:
                    case["setup"](controller)
                with patch("state.set_primus_ip_config") as set_ip, patch("state.get_primus_config") as get_config:
                    result = case["call"](controller)
                self.assertTrue(result["ok"])
                get_config.assert_not_called()
                set_ip.assert_called_once()
                case["assertions"](controller.devices[0], result)

    def test_management_pre_ack_failure_rolls_back_local_state(self):
        cases = [
            {
                "name": "output type",
                "patch_target": "state.set_primus_output_descriptors",
                "call": lambda controller: controller.set_device_output_type(0, 0, "small_grid"),
                "assertions": lambda device: self.assertEqual(
                    device["outputs"][0]["type"], "short_strip"),
            },
            {
                "name": "rename",
                "patch_target": "state.set_primus_identity",
                "call": lambda controller: controller.rename_device(0, "Badge-Renamed"),
                "assertions": lambda device: self.assertEqual(device["name"], "Badge-A"),
            },
            {
                "name": "receive config",
                "patch_target": "state.set_primus_receive_config",
                "call": lambda controller: controller.set_device_receive_mode(0, "combined", 44),
                "assertions": lambda device: (
                    self.assertEqual(device["receive_mode"], "split"),
                    self.assertEqual(device["base_universe"], 10),
                ),
            },
            {
                "name": "telemetry",
                "patch_target": "state.set_primus_telemetry_target",
                "call": lambda controller: controller.set_device_telemetry_target(
                    0, "192.168.1.40"),
                "assertions": lambda device: self.assertEqual(
                    device["telemetry_target"], "0.0.0.0"),
            },
            {
                "name": "production mode",
                "patch_target": "state.set_primus_operating_mode",
                "call": lambda controller: controller.enter_device_production_mode(0),
                "assertions": lambda device: self.assertEqual(
                    device["operating_mode"], "prototype"),
            },
            {
                "name": "boot unlock",
                "patch_target": "state.unlock_primus_boot_window",
                "setup": lambda controller: controller.devices[0].update({
                    "operating_mode": "production",
                    "production_mode": True,
                    "management_locked": True,
                    "unlock_window_open": True,
                    "unlock_remaining_seconds": 9,
                }),
                "call": lambda controller: controller.unlock_device_boot_window(0),
                "assertions": lambda device: self.assertEqual(
                    device["operating_mode"], "production"),
            },
            {
                "name": "ip static",
                "patch_target": "state.set_primus_ip_config",
                "call": lambda controller: controller.set_device_ip(
                    0, "192.168.1.91", "192.168.1.1", "255.255.255.0"),
                "assertions": lambda device: (
                    self.assertEqual(device["ip_mode"], "dhcp"),
                    self.assertIsNone(device["static_ip"]),
                ),
            },
        ]

        for case in cases:
            with self.subTest(case["name"]):
                controller = self.make_controller()
                if "setup" in case:
                    case["setup"](controller)
                with patch(
                    case["patch_target"],
                    side_effect=state.PrimusManagementTimeout("no ack"),
                ), patch("state.get_primus_config") as get_config:
                    result = case["call"](controller)
                self.assertFalse(result["ok"])
                get_config.assert_not_called()
                case["assertions"](controller.devices[0])

    def test_explicit_refresh_timeout_stays_failure(self):
        controller = self.make_controller()
        controller.devices[0]["transport_error"] = "existing DMX transport error"
        controller.devices[0]["send_fail_streak"] = 3
        with patch(
            "state.get_primus_config",
            side_effect=state.PrimusManagementTimeout("timed out"),
        ):
            result = controller.refresh_device_full_config(0)
        self.assertFalse(result["ok"])
        self.assertEqual(controller.devices[0]["name"], "Badge-A")
        self.assertEqual(
            controller.devices[0]["transport_error"], "existing DMX transport error"
        )
        self.assertEqual(controller.devices[0]["send_fail_streak"], 3)

    def test_post_ack_target_removal_returns_success_without_corrupting_other_device(self):
        controller = self.make_controller(devices=[
            self.make_management_device(ip="192.168.1.90", name="Badge-A"),
            self.make_management_device(ip="192.168.1.91", name="Badge-B"),
        ])

        def remove_then_timeout(*args, **kwargs):
            with controller.lock:
                controller.devices.pop(0)
            raise state.PrimusManagementTimeout("timed out")

        with patch("state.set_primus_output_descriptors"), patch(
            "state.get_primus_config",
            side_effect=remove_then_timeout,
        ):
            result = controller.set_device_output_type(0, 0, "small_grid")

        self.assertTrue(result["ok"])
        self.assertTrue(result["readback_pending"])
        self.assertEqual(len(controller.devices), 1)
        self.assertEqual(controller.devices[0]["name"], "Badge-B")
        self.assertEqual(controller.devices[0]["outputs"][0]["type"], "short_strip")
        self.assertEqual(result["config"]["outputs"][0]["type"], "small_grid")

    def test_post_ack_ip_change_returns_success_without_overwriting_changed_device(self):
        controller = self.make_controller()

        def change_ip_then_timeout(*args, **kwargs):
            with controller.lock:
                controller.devices[0]["ip"] = "192.168.1.99"
            raise state.PrimusManagementTimeout("timed out")

        with patch("state.set_primus_identity"), patch(
            "state.get_primus_config",
            side_effect=change_ip_then_timeout,
        ):
            result = controller.rename_device(0, "Badge-Renamed")

        self.assertTrue(result["ok"])
        self.assertTrue(result["readback_pending"])
        self.assertEqual(controller.devices[0]["name"], "Badge-A")
        self.assertEqual(controller.devices[0]["ip"], "192.168.1.99")
        self.assertEqual(result["config"]["technical_name"], "Badge-Renamed")

    def test_get_json_includes_management_descriptors_and_telemetry(self):
        controller = self.make_controller()

        class FakeListener:
            def get_telemetry_status(self, ip):
                return ({
                    "protocol_version": 1,
                    "sequence": 77,
                    "uptime_seconds": 123,
                    "rssi_dbm": -58,
                    "heartbeat_age_seconds": 0.4,
                    "heartbeat_fresh": True,
                    "telemetry_packets_lost": 2,
                    "telemetry_reboot_count": 1,
                    "telemetry_packet_loss_rate": 0.1,
                    "management_locked": True,
                    "operating_mode": "production",
                    "unlock_window_open": True,
                    "unlock_remaining_seconds": 9,
                    "telemetry_configured": True,
                    "fps": 29.9,
                    "pkt_rate": 30.0,
                }, 0.4, True)

        controller.fps_listener = FakeListener()
        payload = controller.get_json()
        device = payload["devices"][0]

        self.assertTrue(device["management_supported"])
        self.assertEqual(device["management_protocol_version"], 1)
        self.assertEqual(device["sequence"], 77)
        self.assertEqual(device["rssi_dbm"], -58)
        self.assertTrue(device["heartbeat_fresh"])
        self.assertEqual(device["telemetry_packets_lost"], 2)
        self.assertEqual(device["descriptor_config"][0]["physical_slot"], 0)
        self.assertEqual(device["descriptor_config"][0]["traversal_axis"], "row_major")
        self.assertEqual(device["telemetry_target"], "0.0.0.0")
        self.assertTrue(device["management_locked"])
        self.assertTrue(device["unlock_window_open"])

    def test_management_fields_persist_round_trip(self):
        devices = [{
            "ip": "192.168.1.92",
            "name": "Badge-A",
            "capabilities": {
                "profile": "pv3cap1",
                "management": True,
                "management_protocol_version": 1,
            },
            "management_supported": True,
            "management_protocol": "primus",
            "management_protocol_version": 1,
            "max_pixels_per_port": 170,
            "max_combined_pixels": 170,
            "operating_mode": "prototype",
            "production_mode": False,
            "management_locked": False,
            "unlock_window_open": False,
            "unlock_remaining_seconds": 0,
            "telemetry_target": "192.168.1.50",
            "telemetry_configured": True,
            "character_name": "Chorus",
            "performer_name": "Taylor",
            "ip_mode": "static",
            "static_ip": "192.168.1.92",
            "gateway": "192.168.1.1",
            "subnet": "255.255.255.0",
            "receive_mode": "split",
            "base_universe": 12,
            "outputs": [{
                "name": "A0",
                "physical_slot": 0,
                "type": state.CUSTOM_OUTPUT_TYPE,
                "enabled": True,
                "count": 32,
                "physical_pixels": 32,
                "layout": "grid",
                "descriptor_layout": "grid",
                "rows": 4,
                "columns": 8,
                "traversal_axis": "column_major",
                "scan_pattern": "progressive",
                "start_corner": "bottom_right",
                "virtual_pixels": 16,
                "universe": 12,
                "grid_order": "progressive",
                "grid_rotation": 0,
            }, {
                "name": "A1",
                "physical_slot": 1,
                "type": "none",
                "enabled": False,
                "count": 0,
                "physical_pixels": 0,
                "layout": "none",
                "descriptor_layout": "off",
                "rows": 0,
                "columns": 0,
                "traversal_axis": "row_major",
                "scan_pattern": "progressive",
                "start_corner": "top_left",
                "virtual_pixels": 0,
                "universe": 13,
                "grid_order": "progressive",
                "grid_rotation": 0,
            }],
        }]

        _save_devices(devices)
        loaded = _load_devices()

        self.assertTrue(loaded[0]["management_supported"])
        self.assertEqual(loaded[0]["telemetry_target"], "192.168.1.50")
        self.assertEqual(loaded[0]["outputs"][0]["type"], state.CUSTOM_OUTPUT_TYPE)
        self.assertEqual(loaded[0]["outputs"][0]["traversal_axis"], "column_major")

    def test_output_preset_delegation_and_malformed_init(self):
        controller = self.make_controller()
        presets = controller.list_output_presets()
        self.assertTrue(any(preset["built_in"] for preset in presets))

        created = controller.create_output_preset("Test Linear", {
            "enabled": True,
            "layout": "linear",
            "physical_pixels": 30,
            "virtual_pixels": 15,
        })
        fetched = controller.get_output_preset(created["id"])
        self.assertEqual(fetched["id"], created["id"])

        controller.update_output_preset(
            created["id"],
            descriptor_template={
                "enabled": True,
                "layout": "grid",
                "rows": 4,
                "columns": 8,
                "virtual_pixels": 4,
            },
        )
        controller.delete_output_preset(created["id"])

        with patch.object(
            state,
            "OutputPresetStore",
            side_effect=output_presets.MalformedOutputPresetsError("broken presets"),
        ):
            with self.assertRaises(output_presets.MalformedOutputPresetsError):
                ControllerState(None)


if __name__ == "__main__":
    unittest.main()
