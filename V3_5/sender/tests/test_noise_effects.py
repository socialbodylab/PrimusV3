import os
import sys
import unittest

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from effects import EFFECTS, compute_anim_factor


START_COLOR = (12, 24, 36)
END_COLOR = (220, 230, 240)


class NoiseEffectTests(unittest.TestCase):
    def render(self, effect, count=32, grid=None, t=0.5):
        return EFFECTS[effect](
            count=count,
            t=t,
            dt=0.033,
            speed=1.0,
            anim_factor=compute_anim_factor(t, "loop", duration=5.0),
            duration=5.0,
            playback="loop",
            start_color=START_COLOR,
            end_color=END_COLOR,
            state=[],
            grid=grid,
            angle=0,
            highlight_width=5,
            chase_origin="start",
        )

    def assert_valid_pixels(self, pixels, count):
        self.assertEqual(len(pixels), count)
        for pixel in pixels:
            self.assertEqual(len(pixel), 3)
            for channel in pixel:
                self.assertIsInstance(channel, int)
                self.assertGreaterEqual(channel, 0)
                self.assertLessEqual(channel, 255)

    def test_noise_effects_return_valid_pixels_for_all_output_shapes(self):
        shapes = [
            (30, None),
            (64, (8, 8)),
            (32, (8, 4)),
        ]
        for effect in ("noise", "static_noise", "sparkle_noise"):
            for count, grid in shapes:
                with self.subTest(effect=effect, count=count, grid=grid):
                    self.assert_valid_pixels(self.render(effect, count, grid), count)

    def test_smooth_noise_is_deterministic_and_animated(self):
        first = self.render("noise", count=64, grid=(8, 8), t=0.5)
        repeat = self.render("noise", count=64, grid=(8, 8), t=0.5)
        later = self.render("noise", count=64, grid=(8, 8), t=1.5)
        self.assertEqual(first, repeat)
        self.assertNotEqual(first, later)

    def test_static_noise_is_deterministic_and_frame_based(self):
        first = self.render("static_noise", count=30, grid=None, t=0.1)
        repeat = self.render("static_noise", count=30, grid=None, t=0.1)
        later = self.render("static_noise", count=30, grid=None, t=0.2)
        self.assertEqual(first, repeat)
        self.assertNotEqual(first, later)

    def test_sparkle_noise_keeps_most_pixels_at_start_color(self):
        pixels = self.render("sparkle_noise", count=72, grid=None, t=0.25)
        changed = [pixel for pixel in pixels if tuple(pixel) != START_COLOR]
        self.assertGreater(len(changed), 0)
        self.assertLess(len(changed), len(pixels) // 2)


if __name__ == "__main__":
    unittest.main()
