import os
import sys
import unittest

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from clips import compute_clip_preview
from effects import normalize_brightness, scale_pixels
from mixer import compute_look_frame
from state import ControllerState


class BrightnessTests(unittest.TestCase):
    def test_scale_pixels_clamps_and_scales_channels(self):
        self.assertEqual(
            scale_pixels([(100, 200, 255), (300, -10, 20)], 0.5),
            [(50, 100, 127), (150, 0, 10)],
        )
        self.assertEqual(scale_pixels([(100, 200, 255)], -1), [(0, 0, 0)])
        self.assertEqual(scale_pixels([(300, 20, 10)], 2), [(255, 20, 10)])

    def test_normalize_brightness_defaults_and_clamps(self):
        self.assertEqual(normalize_brightness(None), 1.0)
        self.assertEqual(normalize_brightness("bad", default=0.25), 0.25)
        self.assertEqual(normalize_brightness(2.0), 1.0)
        self.assertEqual(normalize_brightness(-0.5), 0.0)

    def test_clip_preview_defaults_to_full_brightness(self):
        clip = {
            "output_type": "short_strip",
            "effect": "solid",
            "start_color": [100, 50, 24],
            "end_color": [0, 0, 0],
        }

        preview = compute_clip_preview(clip, 0.0)

        self.assertEqual(preview["pixels"][0], [100, 50, 24])

    def test_clip_preview_applies_clip_brightness(self):
        clip = {
            "output_type": "short_strip",
            "effect": "solid",
            "start_color": [100, 50, 25],
            "end_color": [0, 0, 0],
            "brightness": 0.5,
        }

        preview = compute_clip_preview(clip, 0.0)

        self.assertEqual(preview["pixels"][0], [50, 25, 12])

    def make_look(self, clip_id="clip", **segment_overrides):
        segment = {
            "id": "segment-1",
            "clip_id": clip_id,
            "clip_name": "Clip",
            "start_time": 0.0,
            "duration": 5.0,
            "fade_in": 0.0,
            "fade_out": 0.0,
        }
        segment.update(segment_overrides)
        return {
            "outputs": [{"port": "A0", "type": "short_strip"}],
            "tracks": [{"port": "A0", "segments": [segment]}],
            "playback": "loop",
            "total_duration": 5.0,
            "speed": 1.0,
        }

    def test_mixer_multiplies_clip_and_look_brightness(self):
        look = self.make_look()
        look["brightness"] = 0.5
        clip_cache = {
            "clip": {
                "effect": "solid",
                "start_color": [100, 80, 60],
                "end_color": [0, 0, 0],
                "brightness": 0.5,
            }
        }

        frame = compute_look_frame(look, 0.0, clip_cache=clip_cache)

        self.assertEqual(frame[0][0], (25, 20, 15))

    def test_mixer_segment_brightness_override_replaces_clip_brightness(self):
        look = self.make_look(brightness_override=0.25)
        clip_cache = {
            "clip": {
                "effect": "solid",
                "start_color": [100, 80, 60],
                "end_color": [0, 0, 0],
                "brightness": 0.75,
            }
        }

        frame = compute_look_frame(look, 0.0, clip_cache=clip_cache)

        self.assertEqual(frame[0][0], (25, 20, 15))

    def test_mixer_brightness_works_through_crossfade(self):
        look = {
            "brightness": 0.5,
            "outputs": [{"port": "A0", "type": "short_strip"}],
            "tracks": [
                {
                    "port": "A0",
                    "segments": [
                        {
                            "id": "a",
                            "clip_id": "a",
                            "clip_name": "A",
                            "start_time": 0.0,
                            "duration": 2.0,
                            "fade_in": 0.0,
                            "fade_out": 0.0,
                        },
                        {
                            "id": "b",
                            "clip_id": "b",
                            "clip_name": "B",
                            "start_time": 1.0,
                            "duration": 2.0,
                            "fade_in": 0.0,
                            "fade_out": 0.0,
                        },
                    ],
                }
            ],
            "playback": "loop",
            "total_duration": 3.0,
            "speed": 1.0,
        }
        clip_cache = {
            "a": {"effect": "solid", "start_color": [100, 0, 0], "brightness": 1.0},
            "b": {"effect": "solid", "start_color": [0, 0, 100], "brightness": 0.5},
        }

        frame = compute_look_frame(look, 1.5, clip_cache=clip_cache)

        self.assertEqual(frame[0][0], (25, 0, 12))

    def test_designer_update_clamps_and_tick_scales_pixels(self):
        state = ControllerState(None)
        state.update({"output": 0, "effect": "solid"})
        state.update({"output": 0, "start_color": [100, 50, 24]})
        state.update({"output": 0, "brightness": 0.5})
        state.set_playback_source(ControllerState.SOURCE_DESIGNER)

        state.tick()
        payload = state.get_json()

        self.assertEqual(payload["look"]["outputs"][0]["brightness"], 0.5)
        self.assertEqual(payload["look"]["outputs"][0]["pixels"][0], [50, 25, 12])

        state.update({"output": 0, "brightness": 2.0})
        self.assertEqual(state.get_json()["look"]["outputs"][0]["brightness"], 1.0)


if __name__ == "__main__":
    unittest.main()