import os
import sys
import unittest
from unittest.mock import patch, call

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import artnet
from state import ControllerState


def _bare_node(ip, short_name):
    return {
        "ip": ip,
        "short_name": short_name,
        "long_name": "",
        "num_ports": 0,
        "universes": [0, 1],
    }


class AudioOpcodeConstantTests(unittest.TestCase):

    def test_audio_cmd_opcode_is_0x8300(self):
        self.assertEqual(artnet.ARTNET_OPCODE_AUDIO_CMD, 0x8300)

    def test_ftp_cmd_opcode_is_0x8301(self):
        self.assertEqual(artnet.ARTNET_OPCODE_FTP_CMD, 0x8301)

    def test_opcodes_do_not_collide_with_ip_config(self):
        self.assertNotEqual(artnet.ARTNET_OPCODE_AUDIO_CMD, artnet.ARTNET_OPCODE_IP_CONFIG)
        self.assertNotEqual(artnet.ARTNET_OPCODE_FTP_CMD,   artnet.ARTNET_OPCODE_IP_CONFIG)

    def test_audio_cmd_values(self):
        self.assertEqual(artnet.AUDIO_CMD_STOP,      0)
        self.assertEqual(artnet.AUDIO_CMD_PLAY,      1)
        self.assertEqual(artnet.AUDIO_CMD_LOOP,      2)
        self.assertEqual(artnet.AUDIO_CMD_PAUSE,     3)
        self.assertEqual(artnet.AUDIO_CMD_VOLUME,    4)
        self.assertEqual(artnet.AUDIO_CMD_TEST_TONE, 5)
        self.assertEqual(artnet.AUDIO_CMD_PLAY_CUE,  6)
        self.assertEqual(artnet.AUDIO_CMD_LOOP_CUE,  7)


class SendAudioCommandTests(unittest.TestCase):

    def _state_with_device(self, ip, short_name, connected=False):
        state = ControllerState(None)
        state.add_device_from_node(_bare_node(ip, short_name), auto_save=False)
        if connected:
            state.devices[0]["connected"] = True
        return state

    def test_invalid_device_index_returns_false(self):
        state = self._state_with_device("192.168.1.10", "Radius1")
        result = state.send_audio_command(99, "play")
        self.assertFalse(result)

    def test_valid_device_returns_true(self):
        state = self._state_with_device("192.168.1.10", "Radius1")
        with patch("state.send_audio_cmd"):
            result = state.send_audio_command(0, "play", filename="track.wav")
        self.assertTrue(result)

    def test_play_command_calls_artnet_with_correct_code(self):
        state = self._state_with_device("192.168.1.10", "Radius1")
        with patch("state.send_audio_cmd") as mock_send:
            state.send_audio_command(0, "play", filename="track.wav", volume=80)
        mock_send.assert_called_once_with(
            "192.168.1.10", artnet.AUDIO_CMD_PLAY,
            filename="track.wav", volume=80)

    def test_stop_command_calls_artnet_with_correct_code(self):
        state = self._state_with_device("192.168.1.10", "Radius1")
        with patch("state.send_audio_cmd") as mock_send:
            state.send_audio_command(0, "stop")
        mock_send.assert_called_once_with(
            "192.168.1.10", artnet.AUDIO_CMD_STOP,
            filename="", volume=100)

    def test_unknown_command_falls_back_to_stop(self):
        state = self._state_with_device("192.168.1.10", "Radius1")
        with patch("state.send_audio_cmd") as mock_send:
            state.send_audio_command(0, "nonexistent")
        mock_send.assert_called_once_with(
            "192.168.1.10", artnet.AUDIO_CMD_STOP,
            filename="", volume=100)


class FireAudioCueTests(unittest.TestCase):

    def _make_state(self):
        state = ControllerState(None)
        state.add_device_from_node(_bare_node("192.168.1.20", "Radius1"), auto_save=False)
        state.add_device_from_node(_bare_node("192.168.1.21", "Radius2"), auto_save=False)
        state.add_device_from_node(_bare_node("192.168.1.22", "PrimusLED"), auto_save=False)
        return state

    def test_connected_audio_devices_receive_command(self):
        state = self._make_state()
        state.devices[0]["connected"] = True
        state.devices[1]["connected"] = True
        cue = {"cmd": "play", "filename": "show.wav"}
        with patch("state.send_audio_cmd") as mock_send:
            results = state.fire_audio_cue(cue)
        self.assertEqual(results["192.168.1.20"]["status"], "sent")
        self.assertEqual(results["192.168.1.21"]["status"], "sent")
        self.assertEqual(mock_send.call_count, 2)

    def test_disconnected_audio_device_is_skipped(self):
        state = self._make_state()
        state.devices[0]["connected"] = True
        # devices[1] stays disconnected
        cue = {"cmd": "play", "filename": "show.wav"}
        with patch("state.send_audio_cmd") as mock_send:
            results = state.fire_audio_cue(cue)
        self.assertEqual(results["192.168.1.20"]["status"], "sent")
        self.assertEqual(results["192.168.1.21"]["status"], "skipped")
        self.assertEqual(mock_send.call_count, 1)

    def test_led_device_is_not_included_in_results(self):
        state = self._make_state()
        state.devices[2]["connected"] = True
        cue = {"cmd": "play", "filename": "show.wav"}
        with patch("state.send_audio_cmd"):
            results = state.fire_audio_cue(cue)
        self.assertNotIn("192.168.1.22", results)

    def test_loop_command_uses_correct_code(self):
        state = self._make_state()
        state.devices[0]["connected"] = True
        cue = {"cmd": "loop", "filename": "ambient.wav"}
        with patch("state.send_audio_cmd") as mock_send:
            state.fire_audio_cue(cue)
        args = mock_send.call_args
        self.assertEqual(args[0][1], artnet.AUDIO_CMD_LOOP)

    def test_stop_command_uses_correct_code(self):
        state = self._make_state()
        state.devices[0]["connected"] = True
        cue = {"cmd": "stop", "filename": ""}
        with patch("state.send_audio_cmd") as mock_send:
            state.fire_audio_cue(cue)
        args = mock_send.call_args
        self.assertEqual(args[0][1], artnet.AUDIO_CMD_STOP)

    def test_send_error_recorded_in_results(self):
        state = self._make_state()
        state.devices[0]["connected"] = True
        cue = {"cmd": "play", "filename": "show.wav"}
        with patch("state.send_audio_cmd", side_effect=OSError("network unreachable")):
            results = state.fire_audio_cue(cue)
        self.assertEqual(results["192.168.1.20"]["status"], "error")
        self.assertIn("network unreachable", results["192.168.1.20"]["reason"])


if __name__ == "__main__":
    unittest.main()
