import os
import sys
import tempfile
import unittest
from unittest import mock

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import network_settings
import paths


SERVICE_ORDER = """An asterisk (*) denotes that a network service is disabled.
(1) Wi-Fi
(Hardware Port: Wi-Fi, Device: en0)

(2) USB 10/100/1000 LAN
(Hardware Port: USB 10/100/1000 LAN, Device: en5)
"""

IFCONFIG = """en0: flags=8863<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> mtu 1500
    inet 10.0.0.20 netmask 0xffffff00 broadcast 10.0.0.255
    status: active
en5: flags=8863<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> mtu 1500
    inet 192.168.10.2 netmask 0xffffff00 broadcast 192.168.10.255
    status: active
"""

ROUTE = """   route to: default
destination: default
       mask: default
    gateway: 10.0.0.1
  interface: en0
"""


def mac_command_output(args, timeout=4.0):
    if "-listnetworkserviceorder" in args:
        return SERVICE_ORDER
    if args[0].endswith("ifconfig"):
        return IFCONFIG
    if args[0].endswith("route"):
        return ROUTE
    if "-getairportnetwork" in args:
        return "Current Wi-Fi Network: PrimusRouter\n"
    raise AssertionError(f"unexpected command: {args}")


def mac_command_output_for_ssid(ssid):
    def output(args, timeout=4.0):
        if "-getairportnetwork" in args:
            return f"Current Wi-Fi Network: {ssid}\n"
        return mac_command_output(args, timeout=timeout)
    return output


def mac_command_output_with_ipconfig_ssid(ssid):
    def output(args, timeout=4.0):
        if "-getairportnetwork" in args:
            return "You are not associated with an AirPort network.\n"
        if len(args) >= 2 and args[0].endswith("ipconfig") and args[1] == "getsummary":
            return f"<dictionary> {{\n  SSID : {ssid}\n}}\n"
        if args and args[0].endswith("airport"):
            return ""
        return mac_command_output(args, timeout=timeout)
    return output


def mac_command_output_hidden_ssid(args, timeout=4.0):
    if "-getairportnetwork" in args:
        return "You are not associated with an AirPort network.\n"
    if len(args) >= 2 and args[0].endswith("ipconfig") and args[1] == "getsummary":
        return "<dictionary> {\n  SSID : <data> 0x00\n}\n"
    if args and args[0].endswith("airport"):
        return ""
    return mac_command_output(args, timeout=timeout)


class NetworkSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.old_data_dir = os.environ.get(paths.DATA_DIR_ENV)
        os.environ[paths.DATA_DIR_ENV] = self.tmpdir.name

    def tearDown(self):
        if self.old_data_dir is None:
            os.environ.pop(paths.DATA_DIR_ENV, None)
        else:
            os.environ[paths.DATA_DIR_ENV] = self.old_data_dir
        self.tmpdir.cleanup()

    def test_status_parses_macos_interfaces_and_preferred_selection(self):
        with mock.patch.object(network_settings.sys, "platform", "darwin"), \
                mock.patch.object(network_settings, "_run_text", side_effect=mac_command_output):
            status = network_settings.get_network_status()

            self.assertTrue(status["supported"])
            self.assertEqual(len(status["interfaces"]), 2)
            wifi = next(item for item in status["interfaces"] if item["device"] == "en0")
            self.assertEqual(wifi["service"], "Wi-Fi")
            self.assertEqual(wifi["type"], "wifi")
            self.assertEqual(wifi["ssid"], "PrimusRouter")
            self.assertEqual(wifi["source_ip"], "10.0.0.20")
            self.assertEqual(wifi["broadcast"], "10.0.0.255")
            self.assertTrue(wifi["is_default"])

            selected = network_settings.set_preferred_interface({"id": wifi["id"]})
            self.assertEqual(selected["selected_interface"]["device"], "en0")
            self.assertEqual(network_settings.load_settings()["preferred"]["device"], "en0")
            self.assertEqual(network_settings.load_settings()["preferred"]["ssid"], "PrimusRouter")
            self.assertEqual(network_settings.get_artnet_interface()["source_ip"], "10.0.0.20")

        with mock.patch.object(network_settings.sys, "platform", "darwin"), \
                mock.patch.object(network_settings, "_run_text", side_effect=mac_command_output_for_ssid("InternetWiFi")):
            status = network_settings.get_network_status()

        self.assertIsNone(status["selected_interface"])

    def test_status_recommends_active_ethernet_for_show_router(self):
        with mock.patch.object(network_settings.sys, "platform", "darwin"), \
                mock.patch.object(network_settings, "_run_text", side_effect=mac_command_output):
            status = network_settings.get_network_status()

        recommended = status["recommended_interface"]
        self.assertEqual(recommended["device"], "en5")
        self.assertEqual(recommended["type"], "ethernet")
        self.assertEqual(recommended["network"]["cidr"], "192.168.10.0/24")
        self.assertEqual(recommended["network"]["usable_first"], "192.168.10.1")
        self.assertEqual(recommended["network"]["usable_last"], "192.168.10.254")
        self.assertEqual(status["recommended_network"]["cidr"], "192.168.10.0/24")

    def test_controller_wifi_tag_selects_matching_active_ssid(self):
        with mock.patch.object(network_settings.sys, "platform", "darwin"), \
                mock.patch.object(network_settings, "_run_text", side_effect=mac_command_output_for_ssid("ControllerNet")):
            status = network_settings.set_controller_connection({
                "id": "en0:Wi-Fi",
                "service": "Wi-Fi",
                "device": "en0",
                "ssid": "ControllerNet",
            })

            self.assertEqual(status["controller_connection"]["ssid"], "ControllerNet")
            self.assertEqual(status["selected_interface"]["ssid"], "ControllerNet")
            self.assertTrue(status["selected_interface"]["is_controller"])
            self.assertEqual(network_settings.get_artnet_interface()["source_ip"], "10.0.0.20")

        with mock.patch.object(network_settings.sys, "platform", "darwin"), \
                mock.patch.object(network_settings, "_run_text", side_effect=mac_command_output_for_ssid("InternetWiFi")):
            status = network_settings.get_network_status()

        self.assertIsNone(status["selected_interface"])

    def test_status_uses_ipconfig_ssid_when_networksetup_is_empty(self):
        with mock.patch.object(network_settings.sys, "platform", "darwin"), \
                mock.patch.object(network_settings, "_run_text", side_effect=mac_command_output_with_ipconfig_ssid("FallbackNet")), \
                mock.patch.object(network_settings, "_run_text_input", return_value=""):
            status = network_settings.get_network_status()

            wifi = next(item for item in status["interfaces"] if item["device"] == "en0")
            self.assertEqual(wifi["type"], "wifi")
            self.assertEqual(wifi["ssid"], "FallbackNet")

    def test_status_prefers_scutil_ssid_when_networksetup_is_empty(self):
        with mock.patch.object(network_settings.sys, "platform", "darwin"), \
                mock.patch.object(network_settings, "_run_text", side_effect=mac_command_output_with_ipconfig_ssid("<redacted>")), \
                mock.patch.object(network_settings, "_run_text_input", return_value='  SSID_STR : "ScutilNet"\n'):
            status = network_settings.get_network_status()

            wifi = next(item for item in status["interfaces"] if item["device"] == "en0")
            self.assertEqual(wifi["ssid"], "ScutilNet")

    def test_redacted_ssid_values_are_ignored(self):
        with mock.patch.object(network_settings.sys, "platform", "darwin"), \
                mock.patch.object(network_settings, "_run_text", side_effect=mac_command_output_with_ipconfig_ssid("<redacted>")), \
                mock.patch.object(network_settings, "_run_text_input", return_value="  SSID_STR : <redacted>\n"):
            status = network_settings.get_network_status()

            wifi = next(item for item in status["interfaces"] if item["device"] == "en0")
            self.assertEqual(wifi["ssid"], "")

    def test_saved_redacted_controller_ssid_is_cleared(self):
        network_settings.save_settings({
            "controller_connection": {
                "id": "en0:Wi-Fi",
                "service": "Wi-Fi",
                "device": "en0",
                "ssid": "<redacted>",
            }
        })

        self.assertEqual(network_settings.load_settings()["controller_connection"]["ssid"], "")

    def test_data_ssid_placeholders_are_ignored(self):
        self.assertEqual(network_settings._clean_ssid("<data> 0x00"), "")
        self.assertEqual(network_settings._clean_ssid("<data> 0x"), "")

    def test_data_ssid_hex_can_decode_real_names(self):
        self.assertEqual(network_settings._clean_ssid("<data> 0x5072696d7573436f6e74726f6c6c6572"), "PrimusController")

    def test_controller_wifi_tag_requires_wifi_ssid(self):
        with mock.patch.object(network_settings.sys, "platform", "darwin"), \
                mock.patch.object(network_settings, "_run_text", side_effect=mac_command_output):
            with self.assertRaises(network_settings.NetworkSettingsError):
                network_settings.set_controller_connection({"id": "en5:USB 10/100/1000 LAN"})

    def test_controller_wifi_ssid_can_be_named_before_it_is_active(self):
        with mock.patch.object(network_settings.sys, "platform", "darwin"), \
                mock.patch.object(network_settings, "_run_text", side_effect=mac_command_output_for_ssid("InternetWiFi")):
            status = network_settings.set_controller_connection({"ssid": "PrimusController"})

            self.assertEqual(status["controller_connection"]["ssid"], "PrimusController")
            self.assertIsNone(status["selected_interface"])

        with mock.patch.object(network_settings.sys, "platform", "darwin"), \
                mock.patch.object(network_settings, "_run_text", side_effect=mac_command_output_for_ssid("PrimusController")):
            status = network_settings.get_network_status()

            self.assertEqual(status["selected_interface"]["ssid"], "PrimusController")
            self.assertTrue(status["selected_interface"]["is_controller"])

    def test_typed_controller_ssid_can_match_hidden_current_wifi_by_source_ip(self):
        with mock.patch.object(network_settings.sys, "platform", "darwin"), \
                mock.patch.object(network_settings, "_run_text", side_effect=mac_command_output_hidden_ssid), \
                mock.patch.object(network_settings, "_run_text_input", return_value="  SSID_STR : <data> 0x00\n"):
            status = network_settings.set_controller_connection({
                "id": "en0:Wi-Fi",
                "service": "Wi-Fi",
                "device": "en0",
                "ssid": "PrimusController",
            })

            self.assertEqual(status["controller_connection"]["ssid"], "PrimusController")
            self.assertEqual(status["selected_interface"]["device"], "en0")
            self.assertEqual(status["selected_interface"]["ssid"], "")
            self.assertTrue(status["selected_interface"]["is_controller"])

    def test_save_profile_validates_and_persists_static_profile(self):
        with mock.patch.object(network_settings.sys, "platform", "darwin"), \
                mock.patch.object(network_settings, "_run_text", side_effect=mac_command_output):
            status = network_settings.save_profile({
                "scope": "ssid",
                "mode": "static",
                "ssid": "PrimusRouter",
                "service": "Wi-Fi",
                "device": "en0",
                "ip": "10.0.0.50",
                "gateway": "10.0.0.1",
                "subnet": "255.255.255.0",
            })

            self.assertEqual(status["ssid_profiles"]["PrimusRouter"]["ip"], "10.0.0.50")
            self.assertEqual(
                network_settings.load_settings()["ssid_profiles"]["PrimusRouter"]["gateway"],
                "10.0.0.1",
            )
            with self.assertRaises(network_settings.NetworkSettingsError):
                network_settings.save_profile({
                    "scope": "ssid",
                    "mode": "static",
                    "ssid": "PrimusRouter",
                    "ip": "10.0.0.999",
                    "gateway": "10.0.0.1",
                    "subnet": "255.255.255.0",
                })

    def test_save_profile_rejects_static_values_outside_router_range(self):
        with mock.patch.object(network_settings.sys, "platform", "darwin"), \
                mock.patch.object(network_settings, "_run_text", side_effect=mac_command_output):
            with self.assertRaises(network_settings.NetworkSettingsError):
                network_settings.save_profile({
                    "scope": "service",
                    "mode": "static",
                    "service": "USB 10/100/1000 LAN",
                    "device": "en5",
                    "ip": "192.168.10.0",
                    "gateway": "192.168.10.1",
                    "subnet": "255.255.255.0",
                })

            with self.assertRaises(network_settings.NetworkSettingsError):
                network_settings.save_profile({
                    "scope": "service",
                    "mode": "static",
                    "service": "USB 10/100/1000 LAN",
                    "device": "en5",
                    "ip": "192.168.10.50",
                    "gateway": "192.168.20.1",
                    "subnet": "255.255.255.0",
                })

    def test_apply_static_ip_uses_privileged_macos_networksetup(self):
        with mock.patch.object(network_settings.sys, "platform", "darwin"), \
                mock.patch.object(network_settings, "_run_text", side_effect=mac_command_output), \
                mock.patch.object(network_settings.subprocess, "run") as run_mock:
            result = network_settings.apply_static_ip({
                "id": "en0:Wi-Fi",
                "scope": "ssid",
                "mode": "static",
                "ssid": "PrimusRouter",
                "ip": "10.0.0.50",
                "gateway": "10.0.0.1",
                "subnet": "255.255.255.0",
            })

            self.assertTrue(run_mock.called)
            osascript_args = run_mock.call_args.args[0]
            self.assertEqual(osascript_args[:2], ["/usr/bin/osascript", "-e"])
            self.assertIn("-setmanual", osascript_args[2])
            self.assertIn("10.0.0.50", osascript_args[2])
            self.assertEqual(result["last_applied"]["ip"], "10.0.0.50")
            self.assertEqual(network_settings.load_settings()["last_applied"]["service"], "Wi-Fi")

    def test_non_macos_status_is_unsupported(self):
        with mock.patch.object(network_settings.sys, "platform", "linux"):
            status = network_settings.get_network_status()
            artnet_interface = network_settings.get_artnet_interface()

        self.assertFalse(status["supported"])
        self.assertEqual(status["interfaces"], [])
        self.assertIsNone(artnet_interface)


if __name__ == "__main__":
    unittest.main()