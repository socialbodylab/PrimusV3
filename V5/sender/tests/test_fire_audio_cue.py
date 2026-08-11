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
            dest_port=6456,
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
            dest_port=6456,
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
            dest_port=6456,
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
            dest_port=6456,
            volume=80,
        )


if __name__ == "__main__":
    unittest.main()
