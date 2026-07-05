"""Tests for ReceiveMode capability parsing and ArtReceiveConfig packets."""

import os
import sys
import struct
import unittest

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from artnet import (
    ARTNET_HEADER,
    ARTNET_OPCODE_RECEIVE_CONFIG,
    build_receive_config_packet,
    parse_node_capabilities,
    send_receive_config,
)


class ReceiveModeCapabilityTests(unittest.TestCase):
    def test_parse_split_universe_token(self):
        report = (
            "#0001 [0001] OK|PV3CAP1|0:4:0|1:2:1|B:v1|IP:D|U:S:6|F:RIOHM"
        )
        caps = parse_node_capabilities(report)
        self.assertEqual(caps["receive_mode"], "split")
        self.assertEqual(caps["base_universe"], 6)
        self.assertTrue(caps["receive_config"])

    def test_parse_combined_universe_token(self):
        report = (
            "#0001 [0001] OK|PV3CAP1|0:4:104|1:2:104|B:v31|IP:D|U:C:104|F:RIOHM"
        )
        caps = parse_node_capabilities(report)
        self.assertEqual(caps["receive_mode"], "combined")
        self.assertEqual(caps["base_universe"], 104)
        self.assertTrue(caps["receive_config"])

    def test_legacy_caps_default_split(self):
        report = "#0001 [0001] OK|PV3CAP1|0:4:0|1:2:1|B:v1|IP:D|F:RIOH"
        caps = parse_node_capabilities(report)
        self.assertEqual(caps.get("receive_mode", "split"), "split")
        self.assertFalse(caps.get("receive_config"))


class ArtReceiveConfigPacketTests(unittest.TestCase):
    def test_build_combined_packet(self):
        pkt = build_receive_config_packet("combined", 104)
        self.assertEqual(pkt[0:8], ARTNET_HEADER)
        opcode = struct.unpack("<H", pkt[8:10])[0]
        self.assertEqual(opcode, ARTNET_OPCODE_RECEIVE_CONFIG)
        self.assertEqual(pkt[12], 1)
        self.assertEqual(struct.unpack("<H", pkt[13:15])[0], 104)

    def test_build_split_packet(self):
        pkt = build_receive_config_packet("split", 0)
        self.assertEqual(pkt[12], 0)
        self.assertEqual(struct.unpack("<H", pkt[13:15])[0], 0)

    def test_send_receive_config_calls_udp(self):
        sent = []

        def fake_send(ip, packet, source_ip=None):
            sent.append((ip, bytes(packet), source_ip))

        import artnet as artnet_module
        original = artnet_module._send_udp_packet
        artnet_module._send_udp_packet = fake_send
        try:
            send_receive_config("192.168.1.50", "combined", 12, source_ip="192.168.1.2")
        finally:
            artnet_module._send_udp_packet = original

        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], "192.168.1.50")
        self.assertEqual(sent[0][2], "192.168.1.2")
        self.assertEqual(sent[0][1][12], 1)


if __name__ == "__main__":
    unittest.main()
