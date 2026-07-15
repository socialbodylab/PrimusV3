"""HTTP route tests for Primus management and output preset APIs."""

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import server
from output_presets import (
    BuiltInOutputPresetError,
    DuplicateOutputPresetNameError,
    OutputPresetNotFoundError,
    OutputPresetValidationError,
)
from radius_state import RadiusState
from state import ControllerState


def _http(method, url, body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw.decode()) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw.decode()) if raw else None


class _PrimusStubState(ControllerState):
    def __init__(self):
        pass


class _RadiusStubState(RadiusState):
    def __init__(self):
        pass


def _make_primus_state():
    state = _PrimusStubState()
    state.monitor_only = False
    state.devices = []
    state.artnet_source_ip = None
    state.set_artnet_source = lambda source_ip: setattr(state, "artnet_source_ip", source_ip)
    state.get_json = lambda: {"devices": []}
    state.get_performance_json = lambda: {}
    return state


def _make_radius_state():
    state = _RadiusStubState()
    state.monitor_only = False
    state.devices = []
    state.artnet_source_ip = None
    state.set_artnet_source = lambda source_ip: setattr(state, "artnet_source_ip", source_ip)
    state.get_json = lambda: {"devices": []}
    state.get_performance_json = lambda: {}
    return state


class ManagementServerRouteTests(unittest.TestCase):
    def setUp(self):
        self._servers = []

    def tearDown(self):
        for httpd in self._servers:
            httpd.shutdown()
            httpd.server_close()

    def _start_server(self, state):
        httpd = server.create_server("127.0.0.1", 0, state)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self._servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def test_get_device_config_and_lock_state_routes(self):
        state = _make_primus_state()
        seen = []

        def get_device_full_config(di):
            seen.append(("config", di))
            return {
                "ok": True,
                "config": {
                    "technical_name": "Badge-A",
                    "telemetry_target": "0.0.0.0",
                },
            }

        def get_device_lock_state(di):
            seen.append(("lock", di))
            return {
                "ok": True,
                "management_supported": True,
                "operating_mode": "prototype",
                "production_mode": False,
                "management_locked": False,
                "unlock_window_open": True,
                "unlock_remaining_seconds": 18,
            }

        state.get_device_full_config = get_device_full_config
        state.get_device_lock_state = get_device_lock_state

        base = self._start_server(state)

        status, data = _http("GET", f"{base}/api/device_full_config?device=3")
        self.assertEqual(status, 200)
        self.assertEqual(data["config"]["technical_name"], "Badge-A")

        status, data = _http("GET", f"{base}/api/device_lock_state?device=3")
        self.assertEqual(status, 200)
        self.assertTrue(data["unlock_window_open"])
        self.assertEqual(data["unlock_remaining_seconds"], 18)

        status, data = _http("GET", f"{base}/api/device_full_config?device=bad")
        self.assertEqual(status, 400)
        self.assertEqual(data["error"], "device query parameter must be an integer")

        self.assertEqual(seen, [("config", 3), ("lock", 3)])

    @patch.object(server.Handler, "_sync_artnet_source", return_value=None)
    def test_management_mutation_routes_and_validation(self, sync_artnet_source):
        state = _make_primus_state()
        calls = {}

        state.refresh_device_full_config = lambda di: {
            "ok": True,
            "applied_to_device": True,
            "config": {"technical_name": "Badge-A", "base_universe": di},
        }

        def apply_descriptor(di, oi, descriptor_template):
            calls["descriptor"] = (di, oi, descriptor_template)
            return {
                "ok": True,
                "applied_to_device": True,
                "config": {"outputs": [descriptor_template]},
            }

        def set_telemetry(di, target):
            calls["telemetry"] = (di, target)
            return {
                "ok": True,
                "applied_to_device": True,
                "config": {"telemetry_target": target},
            }

        def clear_telemetry(di):
            calls["clear_telemetry"] = di
            return {
                "ok": True,
                "applied_to_device": True,
                "config": {"telemetry_target": "0.0.0.0"},
            }

        state.apply_device_output_descriptor = apply_descriptor
        state.set_device_telemetry_target = set_telemetry
        state.clear_device_telemetry_target = clear_telemetry
        state.enter_device_production_mode = lambda di: {
            "ok": True,
            "applied_to_device": True,
            "config": {"operating_mode": "production", "device": di},
        }
        state.unlock_device_boot_window = lambda di: {
            "ok": True,
            "applied_to_device": True,
            "config": {"unlock_window_open": True, "device": di},
        }

        base = self._start_server(state)

        status, data = _http("POST", f"{base}/api/refresh_device_full_config", {"device": 7})
        self.assertEqual(status, 200)
        self.assertEqual(data["config"]["base_universe"], 7)

        descriptor = {
            "enabled": True,
            "layout": "grid",
            "rows": 4,
            "columns": 8,
            "virtual_pixels": 16,
        }
        status, data = _http(
            "POST",
            f"{base}/api/apply_device_output_descriptor",
            {"device": 2, "output": 1, "descriptor": descriptor},
        )
        self.assertEqual(status, 200)
        self.assertEqual(calls["descriptor"], (2, 1, descriptor))
        self.assertEqual(data["config"]["outputs"][0]["layout"], "grid")

        status, data = _http(
            "POST",
            f"{base}/api/set_device_telemetry_target",
            {"device": 2, "telemetry_target": "192.168.1.40"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(calls["telemetry"], (2, "192.168.1.40"))
        self.assertEqual(data["config"]["telemetry_target"], "192.168.1.40")

        status, data = _http(
            "POST",
            f"{base}/api/set_device_telemetry_target",
            {"device": 2, "telemetry_target": None},
        )
        self.assertEqual(status, 200)
        self.assertEqual(calls["clear_telemetry"], 2)
        self.assertEqual(data["config"]["telemetry_target"], "0.0.0.0")

        status, data = _http("POST", f"{base}/api/enter_device_production_mode", {"device": 9})
        self.assertEqual(status, 200)
        self.assertEqual(data["config"]["operating_mode"], "production")

        status, data = _http("POST", f"{base}/api/unlock_device_boot_window", {"device": 9})
        self.assertEqual(status, 200)
        self.assertTrue(data["config"]["unlock_window_open"])

        status, data = _http(
            "POST",
            f"{base}/api/apply_device_output_descriptor",
            {"device": 2, "output": 1, "descriptor": "bad"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(data["error"], "descriptor must be an object")

        status, data = _http(
            "POST",
            f"{base}/api/set_device_telemetry_target",
            {"device": 2, "telemetry_target": ""},
        )
        self.assertEqual(status, 400)
        self.assertIn("telemetry_target", data["error"])
        self.assertEqual(sync_artnet_source.call_count, 6)

    def test_new_management_routes_propagate_locked_conflicts(self):
        state = _make_primus_state()
        state.apply_device_output_descriptor = lambda di, oi, descriptor_template: {
            "ok": False,
            "error": "device is locked",
            "error_code": "Locked",
            "http_status": 409,
        }

        base = self._start_server(state)

        status, data = _http(
            "POST",
            f"{base}/api/apply_device_output_descriptor",
            {
                "device": 0,
                "output": 1,
                "descriptor": {
                    "enabled": True,
                    "layout": "linear",
                    "physical_pixels": 30,
                    "virtual_pixels": 30,
                },
            },
        )
        self.assertEqual(status, 409)
        self.assertEqual(data["error_code"], "Locked")
        self.assertEqual(data["error"], "device is locked")

    @patch.object(server.Handler, "_sync_artnet_source", return_value=None)
    def test_existing_management_routes_propagate_state_http_status_and_error_code(self, _mock_sync):
        state = _make_primus_state()
        locked = {"ok": False, "error": "device is locked", "error_code": "Locked", "http_status": 409}
        state.rename_device = lambda di, name: dict(locked)
        state.update_device_show_info = lambda di, **kwargs: dict(locked)
        state.set_device_ip = lambda di, ip, gateway, subnet: dict(locked)
        state.revert_device_dhcp = lambda di: dict(locked)
        state.set_device_output_type = lambda di, oi, output_type: dict(locked)
        state.set_device_virtual_resolution = lambda di, oi, **kwargs: dict(locked)
        state.set_device_receive_mode = lambda di, receive_mode, base_universe: dict(locked)

        base = self._start_server(state)

        cases = [
            ("/api/rename_node", {"device": 0, "name": "Badge-B"}),
            ("/api/device_show_info", {"device": 0, "character_name": "Lead"}),
            ("/api/set_device_ip", {"device": 0, "ip": "192.168.1.91", "gateway": "192.168.1.1", "subnet": "255.255.255.0"}),
            ("/api/revert_device_dhcp", {"device": 0}),
            ("/api/set_device_output", {"device": 0, "output": 1, "output_type": "small_grid"}),
            ("/api/set_device_virtual_resolution", {"device": 0, "output": 1, "virtual_pixels": 16}),
            ("/api/set_device_receive_mode", {"device": 0, "receive_mode": "split", "base_universe": 9}),
        ]

        for route, body in cases:
            with self.subTest(route=route):
                status, data = _http("POST", f"{base}{route}", body)
                self.assertEqual(status, 409)
                self.assertEqual(data["error_code"], "Locked")
                self.assertEqual(data["error"], "device is locked")

    def test_output_preset_crud_and_error_mapping(self):
        state = _make_primus_state()
        base_descriptor = {
            "enabled": True,
            "layout": "linear",
            "physical_pixels": 30,
            "virtual_pixels": 30,
        }
        preset = {
            "id": "custom-grid",
            "name": "Custom Grid",
            "descriptor": dict(base_descriptor),
            "built_in": False,
            "editable": True,
            "deletable": True,
        }

        state.list_output_presets = lambda: [
            {
                "id": "builtin-off",
                "name": "Off",
                "descriptor": {
                    "enabled": False,
                    "layout": "off",
                    "physical_pixels": 0,
                    "virtual_pixels": 0,
                },
                "built_in": True,
                "editable": False,
                "deletable": False,
            },
            preset,
        ]

        def get_preset(preset_id):
            if preset_id == preset["id"]:
                return dict(preset)
            raise OutputPresetNotFoundError(f"unknown output preset id: {preset_id}")

        def create_preset(name, descriptor_template):
            if name == "Duplicate":
                raise DuplicateOutputPresetNameError(f"output preset name already exists: {name}")
            if name == "Invalid":
                raise OutputPresetValidationError("descriptor invalid")
            created = dict(preset)
            created["id"] = "preset-stage-grid-123456789abc"
            created["name"] = name
            created["descriptor"] = dict(descriptor_template)
            return created

        def update_preset(preset_id, *, name=None, descriptor_template=None):
            if preset_id == "builtin-off":
                raise BuiltInOutputPresetError("cannot update built-in output preset: builtin-off")
            if preset_id == "missing":
                raise OutputPresetNotFoundError("unknown output preset id: missing")
            updated = dict(preset)
            updated["id"] = preset_id
            if name is not None:
                updated["name"] = name
            if descriptor_template is not None:
                updated["descriptor"] = dict(descriptor_template)
            return updated

        def delete_preset(preset_id):
            if preset_id == "builtin-off":
                raise BuiltInOutputPresetError("cannot delete built-in output preset: builtin-off")
            if preset_id == "missing":
                raise OutputPresetNotFoundError("unknown output preset id: missing")
            deleted = dict(preset)
            deleted["id"] = preset_id
            return deleted

        state.get_output_preset = get_preset
        state.create_output_preset = create_preset
        state.update_output_preset = update_preset
        state.delete_output_preset = delete_preset

        base = self._start_server(state)

        status, data = _http("GET", f"{base}/api/output_presets")
        self.assertEqual(status, 200)
        self.assertEqual(data["presets"][1]["id"], "custom-grid")

        status, data = _http("GET", f"{base}/api/output_presets/custom-grid")
        self.assertEqual(status, 200)
        self.assertEqual(data["preset"]["name"], "Custom Grid")

        status, data = _http(
            "POST",
            f"{base}/api/output_presets",
            {"name": "Stage Grid", "descriptor": dict(base_descriptor)},
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["preset"]["id"], "preset-stage-grid-123456789abc")

        status, data = _http(
            "POST",
            f"{base}/api/output_presets",
            {"id": "custom-grid", "name": "Renamed Grid"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["preset"]["id"], "custom-grid")
        self.assertEqual(data["preset"]["name"], "Renamed Grid")

        status, data = _http(
            "POST",
            f"{base}/api/output_presets",
            {"name": "Duplicate", "descriptor": dict(base_descriptor)},
        )
        self.assertEqual(status, 409)
        self.assertEqual(data["error_code"], "DuplicateOutputPresetName")

        status, data = _http("GET", f"{base}/api/output_presets/missing")
        self.assertEqual(status, 404)
        self.assertEqual(data["error_code"], "OutputPresetNotFound")

        status, data = _http(
            "POST",
            f"{base}/api/output_presets",
            {"id": "builtin-off", "name": "Nope"},
        )
        self.assertEqual(status, 409)
        self.assertEqual(data["error_code"], "BuiltInOutputPreset")

        status, data = _http("DELETE", f"{base}/api/output_presets/custom-grid")
        self.assertEqual(status, 200)
        self.assertEqual(data["preset"]["id"], "custom-grid")

        status, data = _http("DELETE", f"{base}/api/output_presets/builtin-off")
        self.assertEqual(status, 409)
        self.assertEqual(data["error_code"], "BuiltInOutputPreset")

        status, data = _http(
            "POST",
            f"{base}/api/output_presets",
            {"name": "Broken", "descriptor": "not-an-object"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(data["error"], "descriptor must be an object")

    def test_radius_backend_returns_explicit_conflict_for_primus_management_routes(self):
        base = self._start_server(_make_radius_state())

        status, data = _http("GET", f"{base}/api/device_full_config?device=0")
        self.assertEqual(status, 409)
        self.assertEqual(data["error_code"], "NotAvailable")

        status, data = _http("POST", f"{base}/api/output_presets", {
            "name": "Stage Grid",
            "descriptor": {"enabled": True, "layout": "linear", "physical_pixels": 30, "virtual_pixels": 30},
        })
        self.assertEqual(status, 409)
        self.assertEqual(data["error_code"], "NotAvailable")


if __name__ == "__main__":
    unittest.main()
