"""Tests for Radius Central Art-Net extensions."""

import os
import struct
import sys
import threading
import time
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
        self.assertEqual(caps["ip_mode"], "dhcp")

    def test_pvrad1_firmware_node_report_parses_static_ip(self):
        report = "#0001 [0042] PVRAD1|B:v1|IP:S|F:RIHAS"
        caps = parse_node_capabilities(report, "Audio-1", "Radius Central V1")
        self.assertEqual(caps["profile"], "pvrad1")
        self.assertEqual(caps["ip_mode"], "static")
        self.assertTrue(caps["rename"])
        self.assertTrue(caps["show_info"])

    def test_pvrad1_ok_prefixed_node_report_parses_static_ip(self):
        report = "#0001 [0042] OK|PVRAD1|B:v2|IP:S|F:RIHAS"
        caps = parse_node_capabilities(report, "Audio-1", "Radius Central V2")
        self.assertEqual(caps["hardware_profile"], "v2")
        self.assertEqual(caps["ip_mode"], "static")

    def test_audio_cmd_packet_builder(self):
        sent = []

        def fake_send(ip, packet, source_ip=None, dest_port=None):
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

        def fake_send(ip, packet, source_ip=None, dest_port=None):
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
        def fake_session(ip, source_ip=None, timeout=8.0, dest_port=None):
            yield FakeFTP()

        import artnet as artnet_mod
        with patch.object(artnet_mod, "_ftp_session", fake_session):
            data = artnet_mod.ftp_download("192.168.1.50", "/cues.json")
        self.assertEqual(data, b"file-data")

    def test_ftp_cmd_packet_builder(self):
        sent = []

        def fake_send(ip, packet, source_ip=None, dest_port=None):
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


class _FakeFtp:
    """Minimal ftplib.FTP stand-in. Fails `fail_times` connects, then works."""

    fail_times = 0
    connects = 0

    def connect(self, host, port, timeout=None):
        type(self).connects += 1
        if type(self).connects <= type(self).fail_times:
            raise OSError("timed out")

    def login(self, user, password):
        pass

    def quit(self):
        pass

    def close(self):
        pass


class FtpSessionTests(unittest.TestCase):
    """A receiver serves one FTP connection at a time and `stop` is global, so
    sessions serialize per IP and only the outermost may stop the server.
    """

    def setUp(self):
        import artnet as artnet_mod
        self.artnet = artnet_mod
        _FakeFtp.fail_times = 0
        _FakeFtp.connects = 0
        self.cmds = []
        self._orig_send = artnet_mod.send_ftp_cmd
        artnet_mod.send_ftp_cmd = (
            lambda ip, start, source_ip=None, dest_port=None: self.cmds.append(
                (ip, start)
            )
        )
        self._orig_settle = artnet_mod.FTP_START_SETTLE
        artnet_mod.FTP_START_SETTLE = 0.0
        artnet_mod._ftp_ip_locks.clear()

    def tearDown(self):
        self.artnet.send_ftp_cmd = self._orig_send
        self.artnet.FTP_START_SETTLE = self._orig_settle

    def test_nested_session_sends_one_start_stop_pair(self):
        # A plain (non-reentrant) lock would deadlock here instead.
        with patch("ftplib.FTP", _FakeFtp):
            with self.artnet._ftp_session("10.0.0.5"):
                with self.artnet._ftp_session("10.0.0.5"):
                    pass
        self.assertEqual(self.cmds, [("10.0.0.5", True), ("10.0.0.5", False)])

    def test_retries_connect_before_giving_up(self):
        _FakeFtp.fail_times = 2
        with patch("ftplib.FTP", _FakeFtp):
            with self.artnet._ftp_session("10.0.0.5"):
                pass
        self.assertEqual(_FakeFtp.connects, 3)

    def test_raises_after_exhausting_attempts(self):
        _FakeFtp.fail_times = self.artnet.FTP_CONNECT_ATTEMPTS
        with patch("ftplib.FTP", _FakeFtp):
            with self.assertRaises(OSError):
                with self.artnet._ftp_session("10.0.0.5"):
                    pass
        # The server is still told to stop even when the handshake never landed.
        self.assertEqual(self.cmds[-1], ("10.0.0.5", False))

    def test_concurrent_sessions_to_one_ip_do_not_overlap(self):
        overlaps = []
        active = []
        guard = threading.Lock()

        def worker():
            with self.artnet._ftp_session("10.0.0.5"):
                with guard:
                    active.append(1)
                    if len(active) > 1:
                        overlaps.append(True)
                time.sleep(0.02)
                with guard:
                    active.pop()

        # Patch once around every thread: mock.patch is not thread-safe, and
        # patching per-worker lets one thread restore ftplib under another.
        with patch("ftplib.FTP", _FakeFtp):
            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(overlaps, [])


if __name__ == "__main__":
    unittest.main()
