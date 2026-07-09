import os
import sys
import tempfile
import unittest

# Isolate the data directory BEFORE importing audio_cues — its module-level
# _CUES_FILE is resolved at import time, and whichever test module imports
# it first pins the path for the whole test run. Without this, running the
# suite overwrote the real audio_cues.json with test fixtures.
os.environ.setdefault("RADIUSV4_DATA_DIR", tempfile.mkdtemp())

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from audio_cues import derive_device_cue_map


IP_A = "192.168.1.10"
IP_B = "192.168.1.20"


def _cue(number, actions):
    return {"number": number, "actions": actions}


def _action(cmd, filename="", volume=None, duration=None):
    a = {"cmd": cmd, "filename": filename}
    if volume is not None:
        a["volume"] = volume
    if duration is not None:
        a["duration"] = duration
    return a


class DeriveCueMapPlayLoopTests(unittest.TestCase):

    def test_play_action_produces_entry(self):
        cues = [_cue(1, {IP_A: _action("play", "show.wav", 80)})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertEqual(result, {"1": {"cmd": "play", "file": "show.wav", "volume": 80}})

    def test_loop_action_produces_entry(self):
        cues = [_cue(1, {IP_A: _action("loop", "drone.wav", 75)})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertEqual(result["1"]["cmd"], "loop")
        self.assertEqual(result["1"]["file"], "drone.wav")

    def test_duration_included_when_nonzero(self):
        cues = [_cue(3, {IP_A: _action("play", "sting.wav", 100, duration=5)})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertEqual(result["3"]["duration"], 5)

    def test_duration_omitted_when_zero(self):
        cues = [_cue(3, {IP_A: _action("play", "sting.wav", 100, duration=0)})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertNotIn("duration", result["3"])

    def test_duration_omitted_when_absent(self):
        cues = [_cue(3, {IP_A: _action("play", "sting.wav", 100)})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertNotIn("duration", result["3"])

    def test_volume_omitted_when_not_set(self):
        cues = [_cue(1, {IP_A: {"cmd": "play", "filename": "show.wav"}})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertNotIn("volume", result["1"])

    def test_volume_zero_is_included(self):
        cues = [_cue(1, {IP_A: _action("play", "show.wav", volume=0)})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertEqual(result["1"]["volume"], 0)

    def test_empty_filename_skips_play(self):
        cues = [_cue(1, {IP_A: _action("play", "")})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertEqual(result, {})

    def test_empty_filename_skips_loop(self):
        cues = [_cue(1, {IP_A: _action("loop", "")})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertEqual(result, {})

    def test_file_key_used_not_filename(self):
        cues = [_cue(1, {IP_A: _action("play", "show.wav", 80)})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertIn("file", result["1"])
        self.assertNotIn("filename", result["1"])

    def test_cue_number_becomes_string_key(self):
        cues = [_cue(7, {IP_A: _action("play", "file.wav", 80)})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertIn("7", result)
        self.assertNotIn(7, result)


class DeriveCueMapStopVolumeTests(unittest.TestCase):

    def test_stop_action_produces_stop_entry(self):
        cues = [_cue(5, {IP_A: {"cmd": "stop"}})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertEqual(result, {"5": {"cmd": "stop"}})

    def test_stop_entry_has_no_file(self):
        cues = [_cue(5, {IP_A: {"cmd": "stop"}})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertNotIn("file", result["5"])

    def test_volume_action_produces_volume_entry(self):
        cues = [_cue(6, {IP_A: {"cmd": "volume", "volume": 70}})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertEqual(result, {"6": {"cmd": "volume", "volume": 70}})

    def test_volume_entry_has_no_file(self):
        cues = [_cue(6, {IP_A: {"cmd": "volume", "volume": 70}})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertNotIn("file", result["6"])


class DeriveCueMapFilteringTests(unittest.TestCase):

    def test_none_action_excluded(self):
        cues = [_cue(2, {IP_A: {"cmd": "none", "filename": ""}})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertEqual(result, {})

    def test_unknown_cmd_excluded(self):
        cues = [_cue(2, {IP_A: {"cmd": "pause", "filename": "show.wav"}})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertEqual(result, {})

    def test_device_not_in_actions_excluded(self):
        cues = [_cue(1, {IP_B: _action("play", "show.wav", 80)})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertEqual(result, {})

    def test_cue_without_number_skipped(self):
        cues = [{"actions": {IP_A: _action("play", "show.wav", 80)}}]
        result = derive_device_cue_map(cues, IP_A)
        self.assertEqual(result, {})

    def test_empty_cue_list(self):
        result = derive_device_cue_map([], IP_A)
        self.assertEqual(result, {})

    def test_empty_actions_dict(self):
        cues = [_cue(1, {})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertEqual(result, {})


class DeriveCueMapV4FieldTests(unittest.TestCase):
    """V4-specific: the sheet's delay_ms field maps to the device schema's
    delay field, and cue numbers must fit the device's uint8 range."""

    def test_delay_ms_maps_to_delay(self):
        cues = [_cue(1, {IP_A: {"cmd": "play", "filename": "a.wav", "delay_ms": 1500}})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertEqual(result["1"]["delay"], 1500)
        self.assertNotIn("delay_ms", result["1"])

    def test_zero_delay_ms_omitted(self):
        cues = [_cue(1, {IP_A: {"cmd": "play", "filename": "a.wav", "delay_ms": 0}})]
        result = derive_device_cue_map(cues, IP_A)
        self.assertNotIn("delay", result["1"])

    def test_number_above_255_skipped(self):
        cues = [_cue(256, {IP_A: _action("play", "a.wav", 80)})]
        self.assertEqual(derive_device_cue_map(cues, IP_A), {})

    def test_number_zero_skipped(self):
        cues = [_cue(0, {IP_A: _action("play", "a.wav", 80)})]
        self.assertEqual(derive_device_cue_map(cues, IP_A), {})

    def test_number_255_kept(self):
        cues = [_cue(255, {IP_A: _action("play", "a.wav", 80)})]
        self.assertIn("255", derive_device_cue_map(cues, IP_A))


class DeriveCueMapMultiCueTests(unittest.TestCase):

    def test_multiple_cues_for_device(self):
        cues = [
            _cue(1, {IP_A: _action("loop", "drone.wav", 80)}),
            _cue(2, {IP_A: _action("play", "solo.wav", 90)}),
            _cue(3, {IP_B: _action("play", "other.wav", 70)}),
            _cue(5, {IP_A: {"cmd": "stop"}}),
        ]
        result = derive_device_cue_map(cues, IP_A)
        self.assertIn("1", result)
        self.assertIn("2", result)
        self.assertNotIn("3", result)
        self.assertIn("5", result)
        self.assertEqual(result["1"]["cmd"], "loop")
        self.assertEqual(result["5"]["cmd"], "stop")

    def test_per_device_isolation(self):
        cues = [_cue(1, {IP_A: _action("play", "a.wav", 80),
                         IP_B: _action("loop", "b.wav", 60)})]
        result_a = derive_device_cue_map(cues, IP_A)
        result_b = derive_device_cue_map(cues, IP_B)
        self.assertEqual(result_a["1"]["cmd"], "play")
        self.assertEqual(result_a["1"]["file"], "a.wav")
        self.assertEqual(result_b["1"]["cmd"], "loop")
        self.assertEqual(result_b["1"]["file"], "b.wav")

    def test_full_example_stage_left(self):
        """Stage Left (IP_A) from the design-doc example."""
        cues = [
            {"number": 1, "actions": {
                IP_A: {"cmd": "loop", "filename": "drone_L.wav", "volume": 80},
                IP_B: {"cmd": "loop", "filename": "drone_R.wav", "volume": 80},
            }},
            {"number": 2, "actions": {
                IP_A: {"cmd": "play", "filename": "solo_L.wav", "volume": 90},
                IP_B: {"cmd": "none"},
            }},
            {"number": 4, "actions": {
                IP_A: {"cmd": "none"},
                IP_B: {"cmd": "loop", "filename": "ambient_R.wav", "volume": 60},
            }},
            {"number": 5, "actions": {
                IP_A: {"cmd": "stop"},
                IP_B: {"cmd": "stop"},
            }},
        ]
        result = derive_device_cue_map(cues, IP_A)
        self.assertEqual(result["1"], {"cmd": "loop", "file": "drone_L.wav", "volume": 80})
        self.assertEqual(result["2"], {"cmd": "play", "file": "solo_L.wav", "volume": 90})
        self.assertNotIn("4", result)
        self.assertEqual(result["5"], {"cmd": "stop"})

    def test_full_example_stage_right(self):
        """Stage Right (IP_B) gets cue 4 but not cue 2."""
        cues = [
            {"number": 2, "actions": {
                IP_A: {"cmd": "play", "filename": "solo_L.wav", "volume": 90},
                IP_B: {"cmd": "none"},
            }},
            {"number": 4, "actions": {
                IP_A: {"cmd": "none"},
                IP_B: {"cmd": "loop", "filename": "ambient_R.wav", "volume": 60},
            }},
        ]
        result = derive_device_cue_map(cues, IP_B)
        self.assertNotIn("2", result)
        self.assertEqual(result["4"], {"cmd": "loop", "file": "ambient_R.wav", "volume": 60})


if __name__ == "__main__":
    unittest.main()
