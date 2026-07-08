"""Tests for Radius Central Art-Net extensions."""

import os
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from artnet import (
    ARTNET_HEADER,
    ARTNET_OPCODE_AUDIO_CMD,
    ARTNET_OPCODE_FTP_CMD,
    ARTNET_OPCODE_IP_CONFIG,
    AUDIO_CMD_LOOP_CUE,
    AUDIO_CMD_PLAY_CUE,
    AUDIO_CMD_TEST_TONE,
    parse_node_capabilities,
    send_audio_cmd,
    send_ftp_cmd,
)


class RadiusArtNetTests(unittest.TestCase):
    def test_opcodes_do_not_collide(self):
        self.assertEqual(ARTNET_OPCODE_IP_CONFIG, 0x8200)
        self.assertEqual(ARTNET_OPCODE_AUDIO_CMD, 0x8300)
        self.assertEqual(ARTNET_OPCODE_FTP_CMD, 0x8301)

    def test_pvrad1_capability_parsing(self):
        report = "PVRAD1|B:v1|IP:D|F:RIHAS"
        caps = parse_node_capabilities(report, "Radius", "Radius Central V1")
        self.assertEqual(caps["profile"], "pvrad1")
        self.assertEqual(caps["device_class"], "radius")
        self.assertTrue(caps["rename"])
        self.assertTrue(caps["audio"])
        self.assertTrue(caps["ftp"])
        self.assertTrue(caps["ip_config"])
        self.assertTrue(caps["show_info"])

    def test_audio_cmd_packet_builder(self):
        sent = []

        def fake_send(ip, packet, source_ip=None):
            sent.append(bytes(packet))

        import artnet as artnet_mod
        original = artnet_mod._send_udp_packet
        artnet_mod._send_udp_packet = fake_send
        try:
            send_audio_cmd("192.168.1.50", 1, filename="test.wav", volume=80)
        finally:
            artnet_mod._send_udp_packet = original

        self.assertEqual(len(sent), 1)
        pkt = sent[0]
        self.assertEqual(pkt[:8], ARTNET_HEADER)
        opcode = struct.unpack("<H", pkt[8:10])[0]
        self.assertEqual(opcode, ARTNET_OPCODE_AUDIO_CMD)
        self.assertEqual(pkt[12], 1)
        self.assertEqual(pkt[13], 80)

    def test_audio_cmd_with_duration(self):
        sent = []

        def fake_send(ip, packet, source_ip=None):
            sent.append(bytes(packet))

        import artnet as artnet_mod
        original = artnet_mod._send_udp_packet
        artnet_mod._send_udp_packet = fake_send
        try:
            send_audio_cmd(
                "192.168.1.50", 1, filename="clip.wav", volume=50, duration=30,
            )
        finally:
            artnet_mod._send_udp_packet = original

        pkt = sent[0]
        name_start = 14
        null_idx = pkt.index(0, name_start)
        self.assertEqual(pkt[name_start:null_idx], b"clip.wav")
        duration = struct.unpack("<H", pkt[null_idx + 1:null_idx + 3])[0]
        self.assertEqual(duration, 30)

    def test_audio_cmd_constants(self):
        self.assertEqual(AUDIO_CMD_TEST_TONE, 5)
        self.assertEqual(AUDIO_CMD_PLAY_CUE, 6)
        self.assertEqual(AUDIO_CMD_LOOP_CUE, 7)

    def test_ftp_download_returns_bytes(self):
        class FakeFTP:
            def retrbinary(self, cmd, callback):
                callback(b"file-data")

        from contextlib import contextmanager

        @contextmanager
        def fake_session(ip, source_ip=None, timeout=8.0):
            yield FakeFTP()

        import artnet as artnet_mod
        with patch.object(artnet_mod, "_ftp_session", fake_session):
            data = artnet_mod.ftp_download("192.168.1.50", "/cues.json")
        self.assertEqual(data, b"file-data")

    def test_ftp_cmd_packet_builder(self):
        sent = []

        def fake_send(ip, packet, source_ip=None):
            sent.append(bytes(packet))

        import artnet as artnet_mod
        original = artnet_mod._send_udp_packet
        artnet_mod._send_udp_packet = fake_send
        try:
            send_ftp_cmd("192.168.1.50", True)
        finally:
            artnet_mod._send_udp_packet = original

        opcode = struct.unpack("<H", sent[0][8:10])[0]
        self.assertEqual(opcode, ARTNET_OPCODE_FTP_CMD)
        self.assertEqual(sent[0][12], 1)


if __name__ == "__main__":
    unittest.main()
