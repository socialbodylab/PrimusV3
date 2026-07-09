"""Source-level contract tests for the Radius receiver firmware.

Each assertion pins a hardware lesson that cannot be caught by running
Python — ordering-sensitive one-liners that have regressed before (or
did regress when the code was ported from V3.6 to V4):

- 9a104fb: WiFi.setSleep(false) must run AFTER connect; WPA association
  resets modem sleep, causing intermittent UDP loss on HUZZAH32
- 07c4c8e: delay after stopPlaying() so the VS1053 flushes before the
  next file header (pitch bug / silence on re-fire)
- db64bed: _audioLooping must be set AFTER audioPlay(), which resets it
- a51b8f9 + July 2026: the AudioStatus packet carries a 64-char filename
  and must be transmitted at full length (write(buf, 46) truncated names)
"""

import os
import re
import sys
import unittest

FIRMWARE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "Arduino", "radius_receiver")
)


def read_source(filename):
    with open(os.path.join(FIRMWARE_DIR, filename), encoding="utf-8") as f:
        return f.read()


def function_body(source, signature):
    """Return the source slice from a function signature to the next
    top-level function definition (good enough for ordering assertions)."""
    start = source.index(signature)
    match = re.search(r"\n(?:void|bool|int|const|uint)", source[start + len(signature):])
    end = start + len(signature) + (match.start() if match else len(source))
    return source[start:end]


class ConfigContracts(unittest.TestCase):
    def test_artnet_port_matches_sender(self):
        # Radius nodes listen on their own Art-Net port (off 6454 so LED
        # traffic and third-party gear never reach them). Firmware and
        # sender must agree or the fleet goes silent.
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from artnet import RADIUS_ARTNET_PORT
        config = read_source("config.h")
        match = re.search(r"#define\s+ARTNET_PORT\s+(\d+)", config)
        self.assertIsNotNone(match, "ARTNET_PORT define missing from config.h")
        self.assertEqual(int(match.group(1)), RADIUS_ARTNET_PORT)


class ReceiverSketchContracts(unittest.TestCase):
    def setUp(self):
        self.ino = read_source("radius_receiver.ino")

    def test_audio_status_packet_sent_at_full_length(self):
        # write(buf, 46) truncated filenames at 33 chars on the wire.
        self.assertIn("udpReport.write(buf, sizeof(buf))", self.ino)
        self.assertNotIn("udpReport.write(buf, 46)", self.ino)

    def test_audio_status_filename_field_is_64_bytes(self):
        body = function_body(self.ino, "void sendAudioStatus(")
        self.assertIn("strncpy((char*)&buf[13], filename, 64)", body)

    def test_wifi_sleep_disabled_after_connect(self):
        # Calling it only before WiFi.begin() is not enough — association
        # resets modem sleep. It must also run in checkWifiConnection().
        body = function_body(self.ino, "void checkWifiConnection()")
        self.assertIn("WiFi.setSleep(false)", body)


class FtpHeaderContracts(unittest.TestCase):
    def test_cue_map_reloads_after_ftp_upload(self):
        # A pushed /cues.json must take effect without a reboot: ftp.h
        # schedules a reload via the SimpleFTPServer transfer callback and
        # the main loop runs cuesLoad() only while the SD bus is free.
        ftp = read_source("ftp.h")
        self.assertIn("setTransferCallback", ftp)
        self.assertIn("cuesReloadPending = true", ftp)
        ino = read_source("radius_receiver.ino")
        self.assertIn("cuesReloadPending && !sdBusy", ino)


class AudioHeaderContracts(unittest.TestCase):
    def setUp(self):
        self.audio = read_source("audio.h")

    def test_audio_looping_set_after_audio_play(self):
        body = function_body(self.audio, "void audioLoop(")
        self.assertIn("audioPlay(", body)
        self.assertIn("_audioLooping = true", body)
        self.assertLess(
            body.index("audioPlay("),
            body.index("_audioLooping = true"),
            "audioPlay() resets _audioLooping to false — the flag must be "
            "set after the call or loop commands play once and stop",
        )

    def test_delay_after_stop_playing_before_new_file(self):
        # VS1053 needs time to flush before the next file header.
        self.assertRegex(self.audio, r"stopPlaying\(\);\s*\n\s*delay\(")

    def test_chip_mute_always_invalidates_volume_cache(self):
        # A bare setVolume(254, 254) leaves _lastAppliedVolume claiming the
        # old volume, so the next _applyVolume() at the same value skips the
        # unmute — playback proceeds (statuses sent) but is silent. All hard
        # mutes must go through _muteChip(), which invalidates the cache.
        self.assertIn("_muteChip", self.audio)
        mute_body = function_body(self.audio, "static void _muteChip()")
        self.assertIn("_musicMaker.setVolume(254, 254)", mute_body)
        self.assertIn("_lastAppliedVolume = 255", mute_body)
        self.assertEqual(
            self.audio.count("_musicMaker.setVolume(254, 254)"), 1,
            "direct setVolume(254, 254) outside _muteChip() — this desyncs "
            "the volume cache and causes silent playback",
        )


if __name__ == "__main__":
    unittest.main()
