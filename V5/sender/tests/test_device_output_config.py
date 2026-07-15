import os
import sys
import unittest
from unittest.mock import patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from state import ControllerState


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


class DeviceOutputConfigTests(unittest.TestCase):
    def make_state(self):
        state = ControllerState(None)
        state.add_device_from_node({
            "ip": "192.168.8.163",
            "short_name": "A12",
            "capabilities": CAPABILITIES,
            "outputs": [
                {"name": "A0", "type": "short_strip", "universe": 0},
                {"name": "A1", "type": "short_strip", "universe": 1},
            ],
            "universes": [0, 1],
        }, auto_save=False)
        return state

    def make_state_with_off_a0(self):
        state = ControllerState(None)
        state.add_device_from_node({
            "ip": "192.168.8.164",
            "short_name": "A13",
            "capabilities": CAPABILITIES,
            "outputs": [
                {"name": "A0", "type": "none", "universe": 0},
                {"name": "A1", "type": "long_strip", "universe": 1},
            ],
            "universes": [0, 1],
        }, auto_save=False)
        return state

    @patch("state._save_devices")
    @patch("state.send_output_config")
    def test_set_device_output_type_updates_device_and_sends_config(self, send_output_config, save_devices):
        state = self.make_state()
        dev = state.devices[0]
        dev["sender"].connected = True
        dev["connected"] = True

        result = state.set_device_output_type(0, 1, "long_strip")

        self.assertTrue(result["ok"])
        self.assertTrue(result["applied_to_device"])
        self.assertFalse(result["requires_restart"])
        self.assertEqual(dev["outputs"][1]["type"], "long_strip")
        self.assertEqual(dev["outputs"][1]["count"], 72)
        self.assertTrue(dev["connected"])
        send_output_config.assert_called_once()
        args = send_output_config.call_args[0]
        self.assertEqual(args[1], ["short_strip", "long_strip"])
        save_devices.assert_called_once()

    @patch("state._save_devices")
    @patch("state.send_output_config")
    def test_set_output_targets_a1_when_a0_is_off(
            self, send_output_config, save_devices):
        state = self.make_state_with_off_a0()
        dev = state.devices[0]
        dev["sender"].connected = True
        dev["connected"] = True

        result = state.set_device_output_type(0, 1, "short_strip")

        self.assertTrue(result["ok"])
        self.assertEqual(
            [(output["name"], output["type"]) for output in dev["outputs"]],
            [("A0", "none"), ("A1", "short_strip")],
        )
        self.assertEqual(
            send_output_config.call_args.args[1],
            ["none", "short_strip"],
        )

    @patch("state._save_devices")
    @patch("state.send_output_config", side_effect=OSError(32, "Broken pipe"))
    def test_set_device_output_type_reverts_on_send_failure(self, send_output_config, save_devices):
        state = self.make_state()
        dev = state.devices[0]
        dev["connected"] = True
        dev["sender"].connected = True
        prior_type = dev["outputs"][0]["type"]

        result = state.set_device_output_type(0, 0, "small_grid")

        self.assertFalse(result["ok"])
        self.assertEqual(dev["outputs"][0]["type"], prior_type)
        self.assertTrue(dev["connected"])
        save_devices.assert_not_called()

    @patch("state._save_devices")
    def test_set_device_output_type_persists_when_disconnected(self, save_devices):
        state = self.make_state()

        result = state.set_device_output_type(0, 0, "small_grid")

        self.assertTrue(result["ok"])
        self.assertFalse(result["applied_to_device"])
        self.assertEqual(state.devices[0]["outputs"][0]["type"], "small_grid")
        self.assertEqual(state.devices[0]["outputs"][0]["count"], 32)
        save_devices.assert_called_once()

    def test_set_device_output_type_rejects_missing_capability(self):
        state = self.make_state()
        state.devices[0]["capabilities"]["output_config"] = False

        result = state.set_device_output_type(0, 0, "small_grid")

        self.assertFalse(result["ok"])
        self.assertIn("output configuration", result["error"])


if __name__ == "__main__":
    unittest.main()
