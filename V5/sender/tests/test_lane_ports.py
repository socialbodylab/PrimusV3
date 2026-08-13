"""Tests for Show/Setup/Watch lane port advertisement and resolution."""

import os
import tempfile
import unittest

from artnet import (
    PORT_DISCOVERY,
    PORT_SETUP,
    PORT_SHOW_PRIMUS,
    PORT_SHOW_RADIUS,
    PORT_WATCH,
    device_setup_port,
    device_show_port,
    parse_node_capabilities,
    resolve_lane_ports,
)
import network_settings
from primus_protocol import (
    CONFIG_VERSION_V1,
    CONFIG_VERSION_V2,
    DeviceConfig,
    IpMode,
    OperatingMode,
    ReceiveMode,
    pack_config,
    unpack_config,
)
from primus_protocol import Layout, OutputDescriptor, ScanPattern, StartCorner, TraversalAxis


def _minimal_outputs():
    return (
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
    )


class LanePortCapabilityTests(unittest.TestCase):
    def test_primus_advertises_show_mgmt_tele(self):
        report = (
            "#0001 [0001] OK|PV3CAP1|F:RIOHBMSG|B:v31|"
            "SHOW:6454|MGMT:6457|TELE:6455|IP:D|U:C:0"
        )
        caps = parse_node_capabilities(report, "Badge", "Primus")
        self.assertEqual(caps["port_show"], 6454)
        self.assertEqual(caps["port_setup"], 6457)
        self.assertEqual(caps["port_watch"], 6455)
        ports = resolve_lane_ports(caps, is_radius=False)
        self.assertEqual(ports["port_setup"], PORT_SETUP)

    def test_radius_advertises_aud_mgmt_tele_ftp(self):
        report = "PVRAD1|B:v1|AUD:6456|MGMT:6457|TELE:6455|FTP:21|IP:D|F:RIHAS"
        caps = parse_node_capabilities(report, "Radius", "Radius Central V1")
        self.assertEqual(caps["port_show"], 6456)
        self.assertEqual(caps["port_setup"], 6457)
        self.assertEqual(caps["ftp_port"], 21)
        ports = resolve_lane_ports(caps, is_radius=True)
        self.assertEqual(ports["port_show"], PORT_SHOW_RADIUS)

    def test_radius_without_aud_defaults_to_audio_lane(self):
        """No AUD: token means the default audio lane, 6456 — never 6454.

        Every Radius firmware since 4.1 listens for ArtAudioCmd on 6456, and
        a lane-aware node on defaults advertises no token at all. Routing to
        the 6454 discovery port silenced real hardware (audio is accepted
        there only while dual-listen is compiled in).
        """
        report = "PVRAD1|B:v1|IP:D|F:RIHAS"
        caps = parse_node_capabilities(report, "Radius", "")
        ports = resolve_lane_ports(caps, is_radius=True)
        self.assertEqual(ports["port_show"], PORT_SHOW_RADIUS)
        self.assertEqual(ports["port_setup"], PORT_SHOW_RADIUS)

    def test_legacy_primus_without_mgmt_falls_back_setup_to_show(self):
        report = "PV3CAP1|F:RIOH|B:v1|IP:D"
        caps = parse_node_capabilities(report, "PrimusV3", "")
        ports = resolve_lane_ports(caps, is_radius=False)
        self.assertEqual(ports["port_show"], PORT_SHOW_PRIMUS)
        self.assertEqual(ports["port_setup"], ports["port_show"])

    def test_lane_aware_primus_on_defaults_advertises_no_lane_token(self):
        """Firmware on default lanes emits no SHOW:/MGMT:/TELE: at all.

        The 64-byte Node Report cannot hold the 30-byte lane triple alongside
        IP:/U:, so lane-awareness rides on the L feature flag and the sender
        infers the documented defaults from it.
        """
        report = "#0001 [0000] OK|PV3CAP1|F:RIOHBMSGL|B:v1|IP:D|U:S:0|0:1:0:30"
        self.assertLessEqual(len(report), 63)
        caps = parse_node_capabilities(report, "PrimusV3", "")
        self.assertTrue(caps["lane_aware"])
        self.assertIsNone(caps.get("port_setup"))
        ports = resolve_lane_ports(caps, is_radius=False)
        self.assertEqual(ports["port_show"], PORT_SHOW_PRIMUS)
        self.assertEqual(ports["port_setup"], PORT_SETUP)
        self.assertEqual(ports["port_watch"], PORT_WATCH)

    def test_lane_aware_report_keeps_ip_and_universe(self):
        """Regression: the lane triple used to overflow and eat IP:/U:.

        A device on defaults must still report its IP mode and universe base;
        losing them left every freshly flashed node showing "unknown".
        """
        report = "#0001 [0000] OK|PV3CAP1|F:RIOHBMSGL|B:v1|IP:D|U:S:0|0:1:0:30"
        caps = parse_node_capabilities(report, "PrimusV3", "")
        self.assertEqual(caps["ip_mode"], "dhcp")
        self.assertEqual(caps["base_universe"], 0)
        self.assertEqual(caps["receive_mode"], "split")

    def test_moved_setup_lane_is_advertised_and_wins(self):
        """A moved lane must still fit — otherwise the node is unmanageable."""
        report = "#0001 [0000] OK|PV3CAP1|F:RIOHBMSGL|B:v1|IP:D|U:S:0|MGMT:7000"
        self.assertLessEqual(len(report), 63)
        caps = parse_node_capabilities(report, "PrimusV3", "")
        ports = resolve_lane_ports(caps, is_radius=False)
        self.assertEqual(ports["port_setup"], 7000)
        self.assertEqual(ports["port_show"], PORT_SHOW_PRIMUS)

    def test_legacy_primus_without_lane_flag_still_falls_back_to_show(self):
        """No L flag means pre-lane firmware: Setup stays on the Show port."""
        report = "#0001 [0000] OK|PV3CAP1|F:RIOHBMSG|B:v1|IP:D|U:S:0"
        caps = parse_node_capabilities(report, "PrimusV3", "")
        self.assertFalse(caps["lane_aware"])
        ports = resolve_lane_ports(caps, is_radius=False)
        self.assertEqual(ports["port_setup"], PORT_SHOW_PRIMUS)

    def test_device_port_helpers(self):
        primus = {"port_show": 6454, "port_setup": 6457, "is_radius": False}
        radius = {"port_show": 6456, "port_setup": 6457, "is_radius": True}
        self.assertEqual(device_show_port(primus), 6454)
        self.assertEqual(device_setup_port(primus), 6457)
        self.assertEqual(device_show_port(radius), 6456)
        self.assertEqual(device_setup_port(radius), 6457)


class GetConfigLanePortsTests(unittest.TestCase):
    def test_round_trip_v2_includes_lane_ports(self):
        config = DeviceConfig(
            OperatingMode.PROTOTYPE,
            False,
            0,
            ReceiveMode.COMBINED,
            0,
            "0.0.0.0",
            IpMode.DHCP,
            "0.0.0.0",
            "0.0.0.0",
            "0.0.0.0",
            _minimal_outputs(),
            "Badge",
            "Char",
            "Perf",
            6454,
            6457,
            6455,
            CONFIG_VERSION_V2,
        )
        packed = pack_config(config)
        unpacked = unpack_config(packed)
        self.assertEqual(unpacked.config_version, CONFIG_VERSION_V2)
        self.assertEqual(unpacked.port_show, 6454)
        self.assertEqual(unpacked.port_setup, 6457)
        self.assertEqual(unpacked.port_watch, PORT_WATCH)

    def test_v1_still_unpacks_with_default_ports(self):
        config = DeviceConfig(
            OperatingMode.PROTOTYPE,
            False,
            0,
            ReceiveMode.COMBINED,
            0,
            "0.0.0.0",
            IpMode.DHCP,
            "0.0.0.0",
            "0.0.0.0",
            "0.0.0.0",
            _minimal_outputs(),
            "Badge",
            "",
            "",
            config_version=CONFIG_VERSION_V1,
        )
        packed = pack_config(config)
        unpacked = unpack_config(packed)
        self.assertEqual(unpacked.config_version, CONFIG_VERSION_V1)
        self.assertEqual(unpacked.port_show, 6454)
        self.assertEqual(unpacked.port_setup, 6457)


class NetworkSettingsLanePortTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._prior_env = os.environ.get("PRIMUSV3_DATA_DIR")
        os.environ["PRIMUSV3_DATA_DIR"] = self._tmpdir.name

    def tearDown(self):
        if self._prior_env is None:
            os.environ.pop("PRIMUSV3_DATA_DIR", None)
        else:
            os.environ["PRIMUSV3_DATA_DIR"] = self._prior_env
        self._tmpdir.cleanup()

    def test_get_lane_ports_defaults(self):
        ports = network_settings.get_lane_ports()
        self.assertEqual(ports, {
            "port_show_primus": 6454,
            "port_show_radius": 6456,
            "port_setup": 6457,
            "port_watch": 6455,
        })

    def test_set_lane_ports_round_trip(self):
        saved = network_settings.set_lane_ports({
            "port_show_primus": 6454,
            "port_show_radius": 6460,
            "port_setup": 6461,
            "port_watch": 6462,
        })
        self.assertEqual(saved["port_show_radius"], 6460)
        self.assertEqual(network_settings.get_lane_ports(), saved)

    def test_set_lane_ports_rejects_missing_field(self):
        with self.assertRaises(network_settings.NetworkSettingsError):
            network_settings.set_lane_ports({
                "port_show_primus": 6454,
                "port_show_radius": 6456,
                "port_setup": 6457,
            })

    def test_set_lane_ports_rejects_below_min(self):
        with self.assertRaises(network_settings.NetworkSettingsError):
            network_settings.set_lane_ports({
                "port_show_primus": 80,
                "port_show_radius": 6456,
                "port_setup": 6457,
                "port_watch": 6455,
            })

    def test_set_lane_ports_rejects_setup_colliding_with_show(self):
        with self.assertRaises(network_settings.NetworkSettingsError):
            network_settings.set_lane_ports({
                "port_show_primus": 6454,
                "port_show_radius": 6456,
                "port_setup": 6454,
                "port_watch": 6455,
            })

    def test_set_lane_ports_rejects_setup_colliding_with_watch(self):
        with self.assertRaises(network_settings.NetworkSettingsError):
            network_settings.set_lane_ports({
                "port_show_primus": 6454,
                "port_show_radius": 6456,
                "port_setup": 6455,
                "port_watch": 6455,
            })

    def test_set_lane_ports_allows_show_primus_and_show_radius_equal(self):
        saved = network_settings.set_lane_ports({
            "port_show_primus": 6454,
            "port_show_radius": 6454,
            "port_setup": 6457,
            "port_watch": 6455,
        })
        self.assertEqual(saved["port_show_primus"], saved["port_show_radius"])


if __name__ == "__main__":
    unittest.main()
