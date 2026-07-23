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
- 6bb5750: no setVolume()/sciWrite() after sineTest() at runtime — sciWrite
  does not gate on DREQ, so a write while DREQ is low corrupts SCI state and
  silences the chip until power cycle
- 695f078: no bare softReset() / no setVolume(254) analog-powerdown writes;
  every reset() and hard mute must invalidate the volume cache
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
    # NOTE: rv1-battery and show-info-caps contracts are intentionally
    # omitted for V5 — battery telemetry is not yet forward-ported, and the
    # caps-string format (RIHAS) is npuckett's. Re-add them when battery lands.

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
        # V5 sends 0x8302 on the udpFps back-channel socket.
        self.assertIn("udpFps.write(buf, sizeof(buf))", self.ino)
        self.assertNotIn("udpFps.write(buf, 46)", self.ino)

    def test_audio_status_filename_field_is_64_bytes(self):
        body = function_body(self.ino, "void sendAudioStatus(")
        self.assertIn("strncpy((char*)&buf[13], filename, 64)", body)

    def test_wifi_sleep_disabled_after_connect(self):
        # Calling it only before WiFi.begin() is not enough — association
        # resets modem sleep. It must also run in checkWifiConnection().
        body = function_body(self.ino, "void checkWifiConnection()")
        self.assertIn("WiFi.setSleep(false)", body)

    def test_show_info_handled_and_loaded_at_boot(self):
        # ArtShowInfo must be dispatched from the packet router and the
        # stored names loaded from NVS at boot, or writes silently vanish
        # on restart.
        self.assertIn("handleArtShowInfo(data, len, remoteAddr)", self.ino)
        self.assertIn("loadStoredShowInfo();", self.ino)
        self.assertIn('prefs.putString("characterName"', self.ino)
        self.assertIn('prefs.putString("performerName"', self.ino)


# NOTE: FtpHeaderContracts (cue-map live reload) is omitted for V5 — the
# cue-map reload pipeline is not yet forward-ported. Re-add when it lands.


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

    def test_no_bare_soft_reset(self):
        # Adafruit softReset() is only SM_RESET + delay: the chip's
        # SCI_CLOCKF resets to 1.0x, at which the VS1053 cannot decode —
        # playback streams silently while playingMusic stays true, and a
        # manual sciWrite(CLOCKF) straight after can be dropped while DREQ
        # is low. Always use the library's full reset() (softReset +
        # settle + CLOCKF restore), paired with a volume cache
        # invalidation because reset() sets chip volume to 40/40.
        self.assertNotIn(
            "_musicMaker.softReset()", self.audio,
            "bare softReset() — use _musicMaker.reset(), which restores "
            "SCI_CLOCKF; without it playback is silent",
        )
        for pos in re.finditer(r"_musicMaker\.reset\(\)", self.audio):
            window = self.audio[pos.end():pos.end() + 300]
            self.assertIn(
                "_lastAppliedVolume = 255", window,
                "reset() without volume cache invalidation — next "
                "_applyVolume at the cached value skips the SCI_VOL rewrite",
            )

    def test_chip_mute_always_invalidates_volume_cache(self):
        # A bare hard mute leaves _lastAppliedVolume claiming the old
        # volume, so the next _applyVolume() at the same value skips the
        # unmute — playback proceeds (statuses sent) but is silent. All hard
        # mutes must go through _muteChip(), which invalidates the cache.
        self.assertIn("_muteChip", self.audio)
        mute_body = function_body(self.audio, "static void _muteChip()")
        self.assertIn("VS1053_MAX_SAFE_ATTENUATION", mute_body)
        self.assertIn("_lastAppliedVolume = 255", mute_body)

    def test_no_analog_powerdown_volume_writes(self):
        # setVolume(254, 254) (SCI_VOL ~0xFEFE) is the VS1053's ANALOG
        # POWERDOWN command — the analog stage can stay dead until a full
        # reset. The old boot beep's internal reset() was accidentally
        # rescuing the chip from this; with the beep removed, a 254 write
        # means permanent silence. Attenuation must be clamped to
        # VS1053_MAX_SAFE_ATTENUATION (250).
        self.assertNotIn("_musicMaker.setVolume(254", self.audio)
        self.assertIn("VS1053_MAX_SAFE_ATTENUATION 250", self.audio)
        body = function_body(self.audio, "static void _applyVolume(")
        self.assertIn("VS1053_MAX_SAFE_ATTENUATION", body,
                      "_applyVolume must clamp — volume 0 maps to 254 "
                      "otherwise, entering analog powerdown from the UI")

    def test_no_sci_write_after_sinetest_in_test_tone(self):
        # sciWrite() in the Adafruit VS1053 library does NOT gate on DREQ.
        # After sineTest() the chip is leaving SM_TEST with DREQ still low /
        # transitioning, so any setVolume()/sciWrite() issued before DREQ goes
        # high can be dropped or corrupt SCI state — silencing ALL later
        # playback until a power cycle (the original test-tone regression).
        # The runtime test tone must end on sineTest() with no volume/SCI write
        # after it. audioBootTest() may write volume BEFORE sineTest() (safe:
        # sineTest's internal reset() overrides it), which is why this pins the
        # runtime path only. If a future version must set volume here, it has
        # to poll MM_DREQ_PIN high first — and update this test to require that
        # guard, rather than deleting it.
        body = function_body(self.audio, "void audioTestTone(")
        self.assertIn("sineTest(", body)
        after = body[body.index("sineTest("):]
        for hazard in ("setVolume(", "sciWrite(", "_applyVolume(",
                       "audioSetVolume(", "_muteChip("):
            self.assertNotIn(
                hazard, after,
                f"{hazard} after sineTest() in audioTestTone() — DREQ may be "
                f"low; this SCI write can silence the chip until power cycle",
            )


if __name__ == "__main__":
    unittest.main()
