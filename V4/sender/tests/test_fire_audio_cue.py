"""Tests for per-device fire_audio_cue() in radius_state.py."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from artnet import AUDIO_CMD_LOOP, AUDIO_CMD_PLAY, AUDIO_CMD_STOP, AUDIO_CMD_TEST_TONE
from radius_state import RadiusState


class FireAudioCueTests(unittest.TestCase):
    def setUp(self):
        self.state = RadiusState()
        self.state.devices = [
            {
                "ip": "192.168.1.10",
                "connected": True,
                "is_radius": True,
                "name": "Node-A",
            },
            {
                "ip": "192.168.1.11",
                "connected": False,
                "is_radius": True,
                "name": "Node-B",
            },
            {
                "ip": "192.168.1.12",
                "connected": True,
                "is_radius": False,
                "name": "Not-Radius",
            },
        ]

    @patch("radius_state.send_audio_cmd")
    def test_per_device_play_actions(self, mock_send):
        cue = {
            "number": 1,
            "actions": {
                "192.168.1.10": {
                    "cmd": "play",
                    "filename": "a.wav",
                    "volume": 60,
                    "duration": 15,
                },
                "192.168.1.11": {"cmd": "stop"},
            },
        }
        results = self.state.fire_audio_cue(cue)
        self.assertEqual(results["192.168.1.10"]["status"], "sent")
        self.assertEqual(results["192.168.1.11"]["status"], "skipped")
        self.assertEqual(results["192.168.1.11"]["reason"], "not connected")
        self.assertNotIn("192.168.1.12", results)
        mock_send.assert_called_once_with(
            "192.168.1.10",
            AUDIO_CMD_PLAY,
            source_ip=None,
            volume=60,
            filename="a.wav",
            duration=15,
        )

    @patch("radius_state.send_audio_cmd")
    def test_skips_none_cmd(self, mock_send):
        cue = {
            "number": 2,
            "actions": {
                "192.168.1.10": {"cmd": "none", "filename": "ignored.wav"},
            },
        }
        results = self.state.fire_audio_cue(cue)
        self.assertEqual(results, {})
        mock_send.assert_not_called()

    @patch("radius_state.send_audio_cmd")
    def test_play_requires_filename(self, mock_send):
        cue = {
            "number": 3,
            "actions": {"192.168.1.10": {"cmd": "play", "filename": ""}},
        }
        results = self.state.fire_audio_cue(cue)
        self.assertEqual(results["192.168.1.10"]["status"], "error")
        self.assertEqual(results["192.168.1.10"]["reason"], "filename required")
        mock_send.assert_not_called()

    @patch("radius_state.send_audio_cmd")
    def test_hello_device_sends_test_tone(self, mock_send):
        self.assertTrue(self.state.hello_device(0, volume=55))
        mock_send.assert_called_once_with(
            "192.168.1.10",
            AUDIO_CMD_TEST_TONE,
            volume=55,
            source_ip=None,
        )

    @patch("radius_state.send_audio_cmd")
    def test_loop_action(self, mock_send):
        cue = {
            "number": 4,
            "actions": {
                "192.168.1.10": {
                    "cmd": "loop",
                    "filename": "loop.wav",
                    "volume": 80,
                    "duration": 0,
                },
            },
        }
        results = self.state.fire_audio_cue(cue)
        self.assertEqual(results["192.168.1.10"]["status"], "sent")
        mock_send.assert_called_once_with(
            "192.168.1.10",
            AUDIO_CMD_LOOP,
            source_ip=None,
            volume=80,
            filename="loop.wav",
            duration=0,
        )

    @patch("radius_state.send_audio_cmd")
    def test_stop_action(self, mock_send):
        cue = {
            "number": 5,
            "actions": {"192.168.1.10": {"cmd": "stop"}},
        }
        results = self.state.fire_audio_cue(cue)
        self.assertEqual(results["192.168.1.10"]["status"], "sent")
        mock_send.assert_called_once_with(
            "192.168.1.10",
            AUDIO_CMD_STOP,
            source_ip=None,
            volume=80,
        )

    # Duration/delay passthrough — guards db64bed, where duration was read
    # from the cue action but silently dropped before send_audio_cmd().

    @patch("radius_state.send_audio_cmd")
    def test_duration_is_cast_to_int(self, mock_send):
        cue = {
            "number": 6,
            "actions": {
                "192.168.1.10": {"cmd": "play", "filename": "a.wav", "duration": 12.7},
            },
        }
        self.state.fire_audio_cue(cue)
        self.assertEqual(mock_send.call_args.kwargs["duration"], 12)

    @patch("radius_state.send_audio_cmd")
    def test_absent_duration_sends_zero(self, mock_send):
        cue = {
            "number": 7,
            "actions": {"192.168.1.10": {"cmd": "play", "filename": "a.wav"}},
        }
        self.state.fire_audio_cue(cue)
        self.assertEqual(mock_send.call_args.kwargs["duration"], 0)

    @patch("radius_state.send_audio_cmd")
    def test_delay_ms_is_passed_through(self, mock_send):
        cue = {
            "number": 8,
            "actions": {
                "192.168.1.10": {
                    "cmd": "play", "filename": "a.wav", "delay_ms": 1500,
                },
            },
        }
        self.state.fire_audio_cue(cue)
        self.assertEqual(mock_send.call_args.kwargs["delay_ms"], 1500)

    @patch("radius_state.send_audio_cmd")
    def test_zero_delay_ms_is_omitted(self, mock_send):
        cue = {
            "number": 9,
            "actions": {
                "192.168.1.10": {"cmd": "play", "filename": "a.wav", "delay_ms": 0},
            },
        }
        self.state.fire_audio_cue(cue)
        self.assertNotIn("delay_ms", mock_send.call_args.kwargs)

    @patch("radius_state.send_audio_cmd")
    def test_volume_duration_and_delay_together(self, mock_send):
        cue = {
            "number": 10,
            "actions": {
                "192.168.1.10": {
                    "cmd": "loop", "filename": "a.wav",
                    "volume": 42, "duration": 30, "delay_ms": 500,
                },
            },
        }
        self.state.fire_audio_cue(cue)
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs["volume"], 42)
        self.assertEqual(kwargs["duration"], 30)
        self.assertEqual(kwargs["delay_ms"], 500)


if __name__ == "__main__":
    unittest.main()
