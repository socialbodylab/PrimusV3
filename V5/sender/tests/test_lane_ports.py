"""Tests for Show/Setup/Watch lane port advertisement and resolution."""

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

    def test_legacy_radius_without_aud_stays_on_discovery(self):
        report = "PVRAD1|B:v1|IP:D|F:RIHAS"
        caps = parse_node_capabilities(report, "Radius", "")
        ports = resolve_lane_ports(caps, is_radius=True)
        self.assertEqual(ports["port_show"], PORT_DISCOVERY)
        self.assertEqual(ports["port_setup"], PORT_DISCOVERY)

    def test_legacy_primus_without_mgmt_falls_back_setup_to_show(self):
        report = "PV3CAP1|F:RIOH|B:v1|IP:D"
        caps = parse_node_capabilities(report, "PrimusV3", "")
        ports = resolve_lane_ports(caps, is_radius=False)
        self.assertEqual(ports["port_show"], PORT_SHOW_PRIMUS)
        self.assertEqual(ports["port_setup"], ports["port_show"])

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


if __name__ == "__main__":
    unittest.main()
