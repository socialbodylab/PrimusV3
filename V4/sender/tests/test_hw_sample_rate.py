"""Hardware-in-the-loop test for the VS1053 mixed-sample-rate bug.

Requires a real Radius device with SD card and the Music Maker wing.
Skipped unless PRIMUS_HW_TEST_IP is set:

    PRIMUS_HW_TEST_IP=192.168.8.159 python3 -m unittest tests.test_hw_sample_rate -v

Background: the VS1053 holds sample-rate state across tracks. Before the
soft-reset fix in audio.h, playing a 44100 Hz file after a 48000 Hz file
(or vice versa) played at the wrong pitch or wedged the decoder. A wedged
decoder never clears sdBusy, which blocks FTP and suppresses the 0x8302
"stopped" status. This test plays 44100 → 48000 → 44100 and uses both
signals to tell a wedged card from a dropped telemetry packet:

- primary: a 0x8302 "stopped" status arrives after each file ends
- corroborating: an FTP connect succeeds after playback should be over

Both missing  → SD bus wedged (the sample-rate bug, or kin). The test
sends a stop command to recover the card before failing.
Only telemetry missing → infrastructure flake (UDP loss), distinct failure.

Notes:
- The device sends status to the FIRST controller it hears after boot.
  Run this from that machine, or power-cycle the device first.
- Radius Central must not be running: this test needs UDP 6455.
- Fixture WAVs are generated locally and uploaded over FTP if missing;
  they are left on the card for future runs.
- No stop command is sent between files: audioStop() resets the tracked
  sample rate, which would bypass the rate-transition path under test.
"""

import io
import math
import os
import struct
import sys
import threading
import time
import unittest
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from artnet import (
    AUDIO_CMD_PLAY,
    AUDIO_CMD_STOP,
    FPS_LISTEN_PORT,
    RadiusTelemetryListener,
    _ftp_session,
    ftp_upload,
    list_audio_files,
    send_audio_cmd,
)

RADIUS_IP = os.environ.get("PRIMUS_HW_TEST_IP")

FIXTURE_SECONDS = 2.0
FIXTURES = {
    "HWTEST44.WAV": 44100,
    "HWTEST48.WAV": 48000,
}
PLAY_SEQUENCE = ["HWTEST44.WAV", "HWTEST48.WAV", "HWTEST44.WAV"]

STATE_STOPPED = 0
STATE_PLAYING = 1


def make_wav(sample_rate, seconds=FIXTURE_SECONDS, freq=440.0):
    """Generate a 16-bit mono PCM WAV (low-volume sine) in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        n = int(sample_rate * seconds)
        frames = bytearray()
        for i in range(n):
            sample = int(8000 * math.sin(2 * math.pi * freq * i / sample_rate))
            frames += struct.pack("<h", sample)
        w.writeframes(bytes(frames))
    return buf.getvalue()


@unittest.skipUnless(RADIUS_IP, "set PRIMUS_HW_TEST_IP=<device-ip> to run hardware tests")
class SampleRateHardwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.listener = RadiusTelemetryListener()
        if cls.listener._sock.getsockname()[1] != FPS_LISTEN_PORT:
            cls.listener.stop()
            raise unittest.SkipTest(
                f"UDP {FPS_LISTEN_PORT} in use — stop Radius/Primus Central first"
            )
        cls._thread = threading.Thread(target=cls.listener.run, daemon=True)
        cls._thread.start()
        cls._provision_fixtures()

    @classmethod
    def tearDownClass(cls):
        send_audio_cmd(RADIUS_IP, AUDIO_CMD_STOP)
        cls.listener.stop()

    @classmethod
    def _provision_fixtures(cls):
        on_card = set(list_audio_files(RADIUS_IP))
        missing = [name for name in FIXTURES if name not in on_card]
        for name in missing:
            data = make_wav(FIXTURES[name])
            print(f"[hw-test] uploading fixture {name} ({len(data)} bytes)")
            ftp_upload(RADIUS_IP, f"/{name}", data)

    def tearDown(self):
        # Always leave the card unwedged for the next test or the next user.
        send_audio_cmd(RADIUS_IP, AUDIO_CMD_STOP)
        time.sleep(0.5)

    def _wait_for_state(self, state, timeout):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            entry = self.listener.get(RADIUS_IP)
            if entry is not None:
                last = entry.get("playback_state")
                if last == state:
                    return True
            time.sleep(0.1)
        return False

    def _ftp_alive(self):
        try:
            with _ftp_session(RADIUS_IP, timeout=6.0) as ftp:
                ftp.voidcmd("NOOP")
            return True
        except Exception:
            return False

    def test_mixed_sample_rate_round_trip(self):
        for step, name in enumerate(PLAY_SEQUENCE, start=1):
            with self.subTest(step=step, file=name):
                send_audio_cmd(RADIUS_IP, AUDIO_CMD_PLAY, filename=name, volume=60)

                started = self._wait_for_state(STATE_PLAYING, timeout=6.0)
                start_ts = time.monotonic()
                if not started:
                    entry = self.listener.get(RADIUS_IP) or {}
                    self.fail(
                        f"step {step} ({name}): no 'playing' status within 6 s "
                        f"(last telemetry: {entry or 'none'}) — file failed to "
                        f"start or telemetry is not reaching this machine"
                    )

                stopped = self._wait_for_state(
                    STATE_STOPPED, timeout=FIXTURE_SECONDS + 8.0
                )
                if stopped:
                    elapsed = time.monotonic() - start_ts
                    self.assertGreater(
                        elapsed, FIXTURE_SECONDS * 0.5,
                        f"step {step} ({name}): stopped after only {elapsed:.1f}s "
                        f"— file likely failed mid-decode",
                    )
                    continue

                # No stopped status: is the SD bus actually wedged?
                ftp_ok = self._ftp_alive()
                send_audio_cmd(RADIUS_IP, AUDIO_CMD_STOP)  # recover the card
                if ftp_ok:
                    self.fail(
                        f"step {step} ({name}): no 'stopped' status but FTP is "
                        f"alive — telemetry packet lost or device is looping; "
                        f"not necessarily the sample-rate bug"
                    )
                self.fail(
                    f"step {step} ({name}): no 'stopped' status AND FTP blocked "
                    f"— SD bus wedged; the sample-rate soft-reset fix is not "
                    f"working on this device (stop command sent to recover)"
                )


if __name__ == "__main__":
    unittest.main()
