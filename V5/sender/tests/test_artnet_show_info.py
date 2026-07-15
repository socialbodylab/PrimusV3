"""Tests for ArtShowInfo (opcode 0x8210) transport helpers."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from artnet import (
    SHOW_INFO_MODE_READ,
    SHOW_INFO_MODE_RESPONSE,
    SHOW_INFO_MODE_WRITE,
    build_show_info_packet,
    parse_node_capabilities,
    parse_show_info_packet,
    sync_show_info_to_device,
    sync_device_name_to_receiver,
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


class ShowInfoSyncTests(unittest.TestCase):
    @patch("artnet.query_show_info")
    @patch("artnet.send_show_info")
    def test_sync_show_info_verifies_read_back(self, send_show_info, query_show_info):
        query_show_info.return_value = {
            "mode": SHOW_INFO_MODE_RESPONSE,
            "character_name": "Chorus",
            "performer_name": "Taylor",
        }
        ok, error = sync_show_info_to_device("192.168.1.50", "Chorus", "Taylor")
        self.assertTrue(ok)
        self.assertEqual(error, "")
        send_show_info.assert_called_once()
        query_show_info.assert_called_once()

    @patch("artnet.query_show_info")
    @patch("artnet.send_show_info")
    def test_sync_show_info_fails_on_mismatch(self, send_show_info, query_show_info):
        query_show_info.return_value = {
            "mode": SHOW_INFO_MODE_RESPONSE,
            "character_name": "Old",
            "performer_name": "Taylor",
        }
        ok, error = sync_show_info_to_device("192.168.1.50", "Chorus", "Taylor")
        self.assertFalse(ok)
        self.assertIn("confirm", error)

    @patch("artnet.query_node_short_name", return_value="Audio-2")
    @patch("artnet.send_art_address")
    def test_sync_device_name_verifies_poll_reply(self, send_art_address, query_node_short_name):
        ok, error = sync_device_name_to_receiver("192.168.1.50", "Audio-2")
        self.assertTrue(ok)
        self.assertEqual(error, "")
        send_art_address.assert_called_once()
        query_node_short_name.assert_called()

    @patch("artnet.time.sleep")
    @patch("artnet.query_node_short_name")
    @patch("artnet.send_art_address")
    def test_sync_device_name_retries_before_failure(
        self, send_art_address, query_node_short_name, sleep_mock,
    ):
        query_node_short_name.side_effect = [None, "Audio-2"]
        ok, error = sync_device_name_to_receiver("192.168.1.50", "Audio-2", timeout=1.5)
        self.assertTrue(ok)
        self.assertEqual(error, "")
        self.assertGreaterEqual(query_node_short_name.call_count, 2)


if __name__ == "__main__":
    unittest.main()
