"""Tests for unified Primus + Radius firmware profile routing."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import firmware
from firmware import FirmwareRequestError


class FirmwareProfileTests(unittest.TestCase):
    def test_full_catalog_registered(self):
        self.assertEqual(
            firmware.BOARD_PROFILES,
            {"v1", "v2", "v3", "radius_v1", "radius_v2"},
        )

    def test_radius_product_exposes_radius_profiles_only(self):
        os.environ.pop("PRIMUSV3_SENDER_PRODUCT", None)
        self.assertEqual(firmware.active_board_profiles(), {"radius_v1", "radius_v2"})
        data = firmware.firmware_profiles_json()
        self.assertEqual(data["product"], "radius")
        self.assertEqual(len(data["profiles"]), 2)
        self.assertEqual(data["profiles"][0]["id"], "radius_v1")

    def test_primus_product_exposes_primus_profiles_only(self):
        os.environ["PRIMUSV3_SENDER_PRODUCT"] = "primus"
        try:
            self.assertEqual(firmware.active_board_profiles(), {"v1", "v2", "v3"})
            data = firmware.firmware_profiles_json()
            self.assertEqual(data["product"], "primus")
            self.assertEqual(len(data["profiles"]), 3)
        finally:
            os.environ.pop("PRIMUSV3_SENDER_PRODUCT", None)

    def test_mixed_scope_exposes_all_profiles(self):
        os.environ["PRIMUSV3_SENDER_PRODUCT"] = "primus"
        try:
            self.assertEqual(
                firmware.active_board_profiles("mixed"),
                {"v1", "v2", "v3", "radius_v1", "radius_v2"},
            )
            data = firmware.firmware_profiles_json("mixed")
            self.assertEqual(data["scope"], "mixed")
            self.assertEqual(len(data["profiles"]), 5)
            self.assertEqual(len(data["families"]["primus"]), 3)
            self.assertEqual(len(data["families"]["radius"]), 2)
        finally:
            os.environ.pop("PRIMUSV3_SENDER_PRODUCT", None)

    def test_mixed_scope_allows_radius_profile_on_primus_product(self):
        os.environ["PRIMUSV3_SENDER_PRODUCT"] = "primus"
        try:
            manager = firmware.FirmwareJobManager()
            cmd = manager.build_command({
                "action": "compile",
                "profile": "radius_v2",
                "scope": "mixed",
            })
            self.assertIn("radius_upload.sh", cmd.command[1])
            self.assertIn("radius_v2", cmd.command)
        finally:
            os.environ.pop("PRIMUSV3_SENDER_PRODUCT", None)

    def test_product_scope_rejects_cross_family_profile(self):
        os.environ["PRIMUSV3_SENDER_PRODUCT"] = "primus"
        try:
            manager = firmware.FirmwareJobManager()
            with self.assertRaises(FirmwareRequestError):
                manager.build_command({"action": "compile", "profile": "radius_v1"})
        finally:
            os.environ.pop("PRIMUSV3_SENDER_PRODUCT", None)

    def test_script_routing(self):
        primus = firmware.upload_script_path("v3")
        radius = firmware.upload_script_path("radius_v1")
        radius_v2 = firmware.upload_script_path("radius_v2")
        self.assertTrue(primus.endswith(os.path.join("Arduino", "upload.sh")))
        self.assertTrue(radius.endswith(os.path.join("Arduino", "radius_upload.sh")))
        self.assertTrue(radius_v2.endswith(os.path.join("Arduino", "radius_upload.sh")))
        self.assertTrue(os.path.isfile(primus))
        self.assertTrue(os.path.isfile(radius))

    def test_build_command_uses_profile_script(self):
        manager = firmware.FirmwareJobManager()
        cmd_radius = manager.build_command({"action": "compile", "profile": "radius_v1"})
        self.assertIn("radius_upload.sh", cmd_radius.command[1])

    def test_primus_profile_rejected_on_radius_product(self):
        manager = firmware.FirmwareJobManager()
        with self.assertRaises(FirmwareRequestError):
            manager.build_command({"action": "compile", "profile": "v3"})

    def test_availability_includes_profiles(self):
        os.environ["PRIMUSV3_SENDER_PRODUCT"] = "radius"
        try:
            manager = firmware.FirmwareJobManager()
            status = manager.availability()
            self.assertIn("profiles", status)
            self.assertEqual(len(status["profiles"]), 2)
            self.assertTrue(status["can_install_tools"])
        finally:
            os.environ.pop("PRIMUSV3_SENDER_PRODUCT", None)

    def test_mixed_availability_includes_all_profiles(self):
        os.environ["PRIMUSV3_SENDER_PRODUCT"] = "primus"
        try:
            manager = firmware.FirmwareJobManager()
            status = manager.availability("mixed")
            self.assertEqual(status["scope"], "mixed")
            self.assertEqual(len(status["profiles"]), 5)
        finally:
            os.environ.pop("PRIMUSV3_SENDER_PRODUCT", None)

    def test_build_command_includes_receive_mode_override(self):
        os.environ["PRIMUSV3_SENDER_PRODUCT"] = "primus"
        try:
            manager = firmware.FirmwareJobManager()
            cmd = manager.build_command({
                "action": "compile",
                "profile": "v3",
                "receive_mode_mode": "combined",
                "base_universe": 12,
            })
            self.assertIn("--receivemode", cmd.command)
            self.assertIn("combined", cmd.command)
            self.assertIn("--universe", cmd.command)
            self.assertIn("12", cmd.command)
            self.assertEqual(cmd.metadata["overrides"]["receive_mode_mode"], "combined")
            self.assertEqual(cmd.metadata["overrides"]["base_universe"], 12)
        finally:
            os.environ.pop("PRIMUSV3_SENDER_PRODUCT", None)

    def test_radius_profile_skips_receive_mode_override(self):
        os.environ["PRIMUSV3_SENDER_PRODUCT"] = "radius"
        try:
            manager = firmware.FirmwareJobManager()
            cmd = manager.build_command({
                "action": "compile",
                "profile": "radius_v1",
                "receive_mode_mode": "combined",
                "base_universe": 12,
            })
            self.assertNotIn("--receivemode", cmd.command)
        finally:
            os.environ.pop("PRIMUSV3_SENDER_PRODUCT", None)

    def test_setup_tools_mixed_scope_metadata(self):
        os.environ["PRIMUSV3_SENDER_PRODUCT"] = "primus"
        try:
            manager = firmware.FirmwareJobManager()
            cmd = manager.build_command({"action": "setup_tools", "scope": "mixed"})
            self.assertEqual(cmd.metadata["scope"], "mixed")
        finally:
            os.environ.pop("PRIMUSV3_SENDER_PRODUCT", None)

    def test_parse_ports_json_output_tolerates_leading_log_lines(self):
        payload = {"ports": [{"address": "/dev/cu.usbserial-1", "candidate": True}]}
        raw = [
            "\033[1;34m[INFO]\033[0m  Checking Arduino CLI...\n",
            json.dumps(payload) + "\n",
        ]
        parsed = firmware.parse_ports_json_output(raw)
        self.assertEqual(parsed["ports"][0]["address"], "/dev/cu.usbserial-1")


if __name__ == "__main__":
    unittest.main()
