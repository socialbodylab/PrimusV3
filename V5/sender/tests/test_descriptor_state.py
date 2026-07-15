import os
import shutil
import sys
import time
import unittest
from unittest.mock import patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import output_presets
import state
from state import ControllerState, _apply_output_universes


class StateScratchMixin:
    def setUp(self):
        root = os.path.dirname(os.path.abspath(__file__))
        unique = f"descriptor-state-{os.getpid()}-{time.time_ns()}"
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


class DescriptorStateTests(StateScratchMixin, unittest.TestCase):
    def test_build_device_outputs_keeps_stable_a0_a1_slots(self):
        controller = ControllerState(None)
        outputs = controller._build_device_outputs_unlocked(
            {},
            [{"name": "A1", "type": "long_strip", "universe": 21}],
            20,
            receive_mode="split",
        )
        self.assertEqual(
            [(output["name"], output["type"], output["universe"]) for output in outputs],
            [("A0", "none", 20), ("A1", "long_strip", 21)],
        )

    def test_custom_descriptor_uses_custom_marker_and_keeps_grid_fields(self):
        controller = ControllerState(None)
        controller.add_device_from_node({
            "ip": "192.168.1.70",
            "short_name": "Custom-A",
            "capabilities": {
                "profile": "primus-legacy",
                "output_config": True,
            },
            "outputs": [
                {
                    "name": "A0",
                    "type": state.CUSTOM_OUTPUT_TYPE,
                    "enabled": True,
                    "physical_pixels": 32,
                    "descriptor_layout": "grid",
                    "rows": 4,
                    "columns": 8,
                    "traversal_axis": "column_major",
                    "scan_pattern": "progressive",
                    "start_corner": "bottom_right",
                    "virtual_pixels": 7,
                    "universe": 0,
                },
                {"name": "A1", "type": "none", "universe": 1},
            ],
            "universes": [0, 1],
        }, auto_save=False)
        output = controller.devices[0]["outputs"][0]
        self.assertEqual(output["type"], state.CUSTOM_OUTPUT_TYPE)
        self.assertEqual(output["count"], 32)
        self.assertEqual(output["grid"], [8, 4])
        self.assertEqual(output["traversal_axis"], "column_major")
        self.assertEqual(output["scan_pattern"], "progressive")
        self.assertEqual(output["start_corner"], "bottom_right")
        self.assertEqual(output["virtual_pixels"], 7)

    def test_apply_device_output_descriptor_validates_combined_virtual_limit(self):
        controller = ControllerState(None)
        controller.devices = [{
            "name": "Mgmt-A",
            "ip": "192.168.1.71",
            "connected": False,
            "sender": type("Sender", (), {"connected": False})(),
            "capabilities": {
                "profile": "pv3cap1",
                "management": True,
                "management_protocol_version": 1,
                "output_config": True,
            },
            "management_supported": True,
            "management_protocol": "primus",
            "management_protocol_version": 1,
            "receive_mode": "combined",
            "base_universe": 0,
            "outputs": [
                {
                    "name": "A0",
                    "type": "extra_long_strip",
                    "enabled": True,
                    "count": 122,
                    "physical_pixels": 122,
                    "layout": "linear",
                    "descriptor_layout": "linear",
                    "rows": 0,
                    "columns": 0,
                    "traversal_axis": "row_major",
                    "scan_pattern": "progressive",
                    "start_corner": "top_left",
                    "virtual_pixels": 122,
                    "universe": 0,
                    "grid_order": "progressive",
                    "grid_rotation": 0,
                },
                {
                    "name": "A1",
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
                    "universe": 0,
                    "grid_order": "progressive",
                    "grid_rotation": 0,
                },
            ],
        }]

        result = controller.apply_device_output_descriptor(0, 0, {
            "enabled": True,
            "layout": "linear",
            "physical_pixels": 122,
            "virtual_pixels": 122,
        })

        self.assertFalse(result["ok"])
        self.assertIn("exceeds 170", result["error"])

    def test_apply_output_universes_keeps_off_slot_numbering(self):
        outputs = [
            {"name": "A0", "type": "none", "count": 0, "universe": 0},
            {"name": "A1", "type": "long_strip", "count": 72, "universe": 1},
        ]
        _apply_output_universes(outputs, "split", 33)
        self.assertEqual(outputs[0]["universe"], 33)
        self.assertEqual(outputs[1]["universe"], 34)


if __name__ == "__main__":
    unittest.main()
