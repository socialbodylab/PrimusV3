import os
import sys
import unittest

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from mixer import compute_look_frame


class MixerTimelineWrappingTests(unittest.TestCase):
    def make_look(self, playback, segment_start, segment_duration):
        return {
            "outputs": [{"port": "A0", "type": "short_strip"}],
            "tracks": [
                {
                    "port": "A0",
                    "segments": [
                        {
                            "id": "segment-1",
                            "clip_id": "solid-test",
                            "clip_name": "Solid Test",
                            "start_time": segment_start,
                            "duration": segment_duration,
                            "fade_in": 0.0,
                            "fade_out": 0.0,
                        }
                    ],
                }
            ],
            "playback": playback,
            "total_duration": 2.0,
            "speed": 1.0,
        }

    def solid_clip_cache(self):
        return {
            "solid-test": {
                "effect": "solid",
                "duration": 1.0,
                "playback": "loop",
                "speed": 1.0,
                "start_color": [12, 34, 56],
                "end_color": [0, 0, 0],
            }
        }

    def first_pixel(self, look, t):
        frame = compute_look_frame(look, t, clip_cache=self.solid_clip_cache())
        return frame[0][0]

    def test_loop_uses_shortened_duration_for_late_transport_time(self):
        look = self.make_look("loop", segment_start=0.2, segment_duration=0.4)

        self.assertEqual(self.first_pixel(look, 2.25), (12, 34, 56))

    def test_boomerang_uses_shortened_duration_for_late_transport_time(self):
        look = self.make_look("boomerang", segment_start=1.7, segment_duration=0.2)

        self.assertEqual(self.first_pixel(look, 2.25), (12, 34, 56))


if __name__ == "__main__":
    unittest.main()
