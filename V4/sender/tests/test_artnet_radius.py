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
    RADIUS_ARTNET_PORT,
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
        report = "PVRAD1|B:v1|IP:D|F:RA"
        caps = parse_node_capabilities(report, "Radius", "Radius Central V1")
        self.assertEqual(caps["profile"], "pvrad1")
        self.assertEqual(caps["device_class"], "radius")
        self.assertTrue(caps["rename"])
        self.assertTrue(caps["audio"])
        self.assertTrue(caps["ftp"])
        self.assertTrue(caps["ip_config"])

    def test_audio_cmd_packet_builder(self):
        sent = []

        def fake_send(ip, packet, source_ip=None, port=None):
            sent.append((bytes(packet), port))

        import artnet as artnet_mod
        original = artnet_mod._send_udp_packet
        artnet_mod._send_udp_packet = fake_send
        try:
            send_audio_cmd("192.168.1.50", 1, filename="test.wav", volume=80)
        finally:
            artnet_mod._send_udp_packet = original

        self.assertEqual(len(sent), 1)
        pkt, port = sent[0]
        self.assertEqual(pkt[:8], ARTNET_HEADER)
        opcode = struct.unpack("<H", pkt[8:10])[0]
        self.assertEqual(opcode, ARTNET_OPCODE_AUDIO_CMD)
        self.assertEqual(pkt[12], 1)
        self.assertEqual(pkt[13], 80)
        self.assertEqual(port, RADIUS_ARTNET_PORT)

    def test_audio_cmd_with_duration(self):
        sent = []

        def fake_send(ip, packet, source_ip=None, port=None):
            sent.append((bytes(packet), port))

        import artnet as artnet_mod
        original = artnet_mod._send_udp_packet
        artnet_mod._send_udp_packet = fake_send
        try:
            send_audio_cmd(
                "192.168.1.50", 1, filename="clip.wav", volume=50, duration=30,
            )
        finally:
            artnet_mod._send_udp_packet = original

        pkt, _port = sent[0]
        name_start = 14
        null_idx = pkt.index(0, name_start)
        self.assertEqual(pkt[name_start:null_idx], b"clip.wav")
        duration = struct.unpack("<H", pkt[null_idx + 1:null_idx + 3])[0]
        self.assertEqual(duration, 30)

    def test_audio_cmd_full_64_char_filename(self):
        # Regression guard for the 32→64 filename migration (a51b8f9):
        # the whole 64-char name must survive packet encoding.
        name = ("x" * 60) + ".wav"
        self.assertEqual(len(name), 64)
        sent = []

        def fake_send(ip, packet, source_ip=None, port=None):
            sent.append((bytes(packet), port))

        import artnet as artnet_mod
        original = artnet_mod._send_udp_packet
        artnet_mod._send_udp_packet = fake_send
        try:
            send_audio_cmd("192.168.1.50", 1, filename=name, volume=80)
        finally:
            artnet_mod._send_udp_packet = original

        pkt, _port = sent[0]
        self.assertEqual(pkt[14:14 + 64].decode("ascii"), name)
        self.assertEqual(pkt[14 + 64], 0)  # null terminator after full name

    def test_audio_cmd_delay_after_duration(self):
        # delay_ms is encoded as uint16 LE after the uint16 LE duration.
        sent = []

        def fake_send(ip, packet, source_ip=None, port=None):
            sent.append((bytes(packet), port))

        import artnet as artnet_mod
        original = artnet_mod._send_udp_packet
        artnet_mod._send_udp_packet = fake_send
        try:
            send_audio_cmd(
                "192.168.1.50", 1, filename="clip.wav", volume=50,
                duration=30, delay_ms=1500,
            )
        finally:
            artnet_mod._send_udp_packet = original

        pkt, _port = sent[0]
        null_idx = pkt.index(0, 14)
        duration, delay = struct.unpack("<HH", pkt[null_idx + 1:null_idx + 5])
        self.assertEqual(duration, 30)
        self.assertEqual(delay, 1500)

    def test_audio_cmd_delay_without_duration(self):
        # With delay but no duration the firmware still expects both
        # uint16 fields; duration is written as 0.
        sent = []

        def fake_send(ip, packet, source_ip=None, port=None):
            sent.append((bytes(packet), port))

        import artnet as artnet_mod
        original = artnet_mod._send_udp_packet
        artnet_mod._send_udp_packet = fake_send
        try:
            send_audio_cmd(
                "192.168.1.50", 1, filename="clip.wav", volume=50, delay_ms=250,
            )
        finally:
            artnet_mod._send_udp_packet = original

        pkt, _port = sent[0]
        null_idx = pkt.index(0, 14)
        duration, delay = struct.unpack("<HH", pkt[null_idx + 1:null_idx + 5])
        self.assertEqual(duration, 0)
        self.assertEqual(delay, 250)

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

        def fake_send(ip, packet, source_ip=None, port=None):
            sent.append((bytes(packet), port))

        import artnet as artnet_mod
        original = artnet_mod._send_udp_packet
        artnet_mod._send_udp_packet = fake_send
        try:
            send_ftp_cmd("192.168.1.50", True)
        finally:
            artnet_mod._send_udp_packet = original

        ftp_pkt, ftp_port = sent[0]
        opcode = struct.unpack("<H", ftp_pkt[8:10])[0]
        self.assertEqual(opcode, ARTNET_OPCODE_FTP_CMD)
        self.assertEqual(ftp_pkt[12], 1)
        self.assertEqual(ftp_port, RADIUS_ARTNET_PORT)


if __name__ == "__main__":
    unittest.main()
