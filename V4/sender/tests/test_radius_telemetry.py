"""Tests for Radius telemetry parsing (ArtAudioStatus 0x8302 + legacy PTR).

Guards two historical regressions:
- the 32→64 char filename migration (V3.6 commit a51b8f9) missed the
  firmware's udpReport.write(buf, 46), truncating names at 33 chars on
  the wire — the round-trip tests here pin the full 78-byte contract
- the parser must tolerate short/garbage packets without crashing
"""

import os
import struct
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from artnet import (
    ARTNET_HEADER,
    ARTNET_OPCODE_AUDIO_STATUS,
    RadiusTelemetryListener,
    parse_audio_status_packet,
    parse_track_packet,
)


def build_audio_status_packet(state, filename="", size=78):
    """Build an ArtAudioStatus packet the way the firmware does."""
    buf = bytearray(size)
    buf[0:8] = ARTNET_HEADER
    struct.pack_into("<H", buf, 8, ARTNET_OPCODE_AUDIO_STATUS)
    buf[10] = 0x00
    buf[11] = 0x0E
    buf[12] = state
    name = filename.encode("ascii")[:64]
    buf[13:13 + len(name)] = name
    return bytes(buf)


class AudioStatusPacketTests(unittest.TestCase):
    def test_playing_state(self):
        result = parse_audio_status_packet(build_audio_status_packet(1, "track.wav"))
        self.assertEqual(result["playback_state"], 1)
        self.assertEqual(result["current_track"], "track.wav")

    def test_paused_state(self):
        result = parse_audio_status_packet(build_audio_status_packet(2, "track.wav"))
        self.assertEqual(result["playback_state"], 2)

    def test_stopped_state_empty_filename(self):
        result = parse_audio_status_packet(build_audio_status_packet(0))
        self.assertEqual(result["playback_state"], 0)
        self.assertEqual(result["current_track"], "")

    def test_filename_is_null_terminated(self):
        pkt = bytearray(build_audio_status_packet(1, "short.wav"))
        pkt[30:34] = b"junk"  # garbage after the terminator must be ignored
        result = parse_audio_status_packet(bytes(pkt))
        self.assertEqual(result["current_track"], "short.wav")

    def test_filename_longer_than_33_chars_survives(self):
        # Regression: firmware sent write(buf, 46), cutting names at 33 chars.
        name = "a_rather_long_track_name_for_show_cue_007.wav"
        self.assertGreater(len(name), 33)
        result = parse_audio_status_packet(build_audio_status_packet(1, name))
        self.assertEqual(result["current_track"], name)

    def test_full_64_char_filename_round_trips(self):
        name = ("x" * 60) + ".wav"
        self.assertEqual(len(name), 64)
        result = parse_audio_status_packet(build_audio_status_packet(1, name))
        self.assertEqual(result["current_track"], name)

    def test_legacy_46_byte_packet_still_parses(self):
        # Packets from firmware predating the write-length fix are truncated
        # but must not crash the parser.
        result = parse_audio_status_packet(
            build_audio_status_packet(1, "short.wav", size=46)
        )
        self.assertEqual(result["playback_state"], 1)
        self.assertEqual(result["current_track"], "short.wav")

    def test_wrong_opcode_returns_none(self):
        pkt = bytearray(build_audio_status_packet(1, "track.wav"))
        struct.pack_into("<H", pkt, 8, 0x8300)
        self.assertIsNone(parse_audio_status_packet(bytes(pkt)))

    def test_short_packet_returns_none(self):
        self.assertIsNone(parse_audio_status_packet(ARTNET_HEADER + b"\x02\x83"))

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_audio_status_packet(b"not-artnet-data-here"))
        self.assertIsNone(parse_audio_status_packet(b""))


class TrackPacketTests(unittest.TestCase):
    def test_ptr_packet_parses(self):
        name = b"loop.wav"
        pkt = b"PTR" + bytes([1, len(name)]) + name
        result = parse_track_packet(pkt)
        self.assertEqual(result["playback_state"], 1)
        self.assertEqual(result["current_track"], "loop.wav")

    def test_ptr_stopped_no_name(self):
        result = parse_track_packet(b"PTR" + bytes([0, 0]))
        self.assertEqual(result["playback_state"], 0)
        self.assertEqual(result["current_track"], "")

    def test_ptr_short_packet_returns_none(self):
        self.assertIsNone(parse_track_packet(b"PTR\x01"))

    def test_ptr_wrong_magic_returns_none(self):
        self.assertIsNone(parse_track_packet(b"PFP\x01\x00"))


class ListenerGetTests(unittest.TestCase):
    """listener.get() is event-driven: entries never expire by age."""

    def _make_listener(self, data):
        listener = RadiusTelemetryListener.__new__(RadiusTelemetryListener)
        listener.lock = threading.Lock()
        listener.data = data
        return listener

    def test_old_entry_is_still_returned(self):
        entry = {
            "playback_state": 1,
            "current_track": "old.wav",
            "ts": time.monotonic() - 3600,
        }
        listener = self._make_listener({"10.0.0.5": entry})
        result = listener.get("10.0.0.5")
        self.assertIsNotNone(result)
        self.assertEqual(result["current_track"], "old.wav")

    def test_unknown_ip_returns_none(self):
        listener = self._make_listener({})
        self.assertIsNone(listener.get("10.0.0.99"))

    def test_returns_copy_not_reference(self):
        entry = {"playback_state": 1, "current_track": "a.wav", "ts": 0}
        listener = self._make_listener({"10.0.0.5": entry})
        result = listener.get("10.0.0.5")
        result["current_track"] = "mutated"
        self.assertEqual(listener.data["10.0.0.5"]["current_track"], "a.wav")


if __name__ == "__main__":
    unittest.main()
