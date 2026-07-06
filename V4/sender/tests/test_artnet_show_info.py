"""Tests for ArtShowInfo (opcode 0x8210) transport helpers."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from artnet import (
    SHOW_INFO_MODE_READ,
    SHOW_INFO_MODE_RESPONSE,
    SHOW_INFO_MODE_WRITE,
    build_show_info_packet,
    parse_node_capabilities,
    parse_show_info_packet,
)


class ArtShowInfoPacketTests(unittest.TestCase):
    def test_build_and_parse_write_packet(self):
        raw = build_show_info_packet(
            SHOW_INFO_MODE_WRITE,
            character_name="Ensemble Lead",
            performer_name="Alex Kim",
        )
        parsed = parse_show_info_packet(raw)
        self.assertEqual(parsed["mode"], SHOW_INFO_MODE_WRITE)
        self.assertEqual(parsed["character_name"], "Ensemble Lead")
        self.assertEqual(parsed["performer_name"], "Alex Kim")

    def test_parse_response_packet(self):
        raw = build_show_info_packet(
            SHOW_INFO_MODE_RESPONSE,
            character_name="Chorus",
            performer_name="Taylor",
        )
        parsed = parse_show_info_packet(raw)
        self.assertEqual(parsed["mode"], SHOW_INFO_MODE_RESPONSE)
        self.assertEqual(parsed["character_name"], "Chorus")
        self.assertEqual(parsed["performer_name"], "Taylor")

    def test_read_packet_has_zero_lengths(self):
        raw = build_show_info_packet(SHOW_INFO_MODE_READ)
        parsed = parse_show_info_packet(raw)
        self.assertEqual(parsed["mode"], SHOW_INFO_MODE_READ)
        self.assertEqual(parsed["character_name"], "")
        self.assertEqual(parsed["performer_name"], "")


class ShowInfoCapabilityTests(unittest.TestCase):
    def test_show_info_flag_parsed_from_node_report(self):
        report = "#0001 [0001] OK|PV3CAP1|B:v3|IP:D|U:S:0|F:RIOHMS"
        caps = parse_node_capabilities(report, "Badge-A", "")
        self.assertTrue(caps.get("show_info"))


if __name__ == "__main__":
    unittest.main()
