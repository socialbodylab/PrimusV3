import os
import sys
import unittest

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from state import ControllerState, PerformanceStats


class PerformanceStatsTests(unittest.TestCase):
    def test_snapshot_tracks_samples_and_counters(self):
        stats = PerformanceStats()

        stats.observe("tick_total_ms", 2.0)
        stats.observe("tick_total_ms", 4.0)
        stats.increment("animation_frame_overruns")

        snapshot = stats.snapshot()

        self.assertEqual(snapshot["samples"]["tick_total_ms"]["count"], 2)
        self.assertEqual(snapshot["samples"]["tick_total_ms"]["last"], 4.0)
        self.assertEqual(snapshot["samples"]["tick_total_ms"]["avg"], 3.0)
        self.assertEqual(snapshot["samples"]["tick_total_ms"]["max"], 4.0)
        self.assertEqual(snapshot["counters"]["animation_frame_overruns"], 1)
        self.assertGreater(snapshot["rates_per_second"]["animation_frame_overruns"], 0)

    def test_controller_tick_records_performance_samples(self):
        state = ControllerState(None)

        state.tick()

        snapshot = state.get_performance_json()
        self.assertIn("tick_total_ms", snapshot["samples"])
        self.assertIn("tick_lock_held_ms", snapshot["samples"])
        self.assertIn("tick_send_packets", snapshot["samples"])

    def test_clear_override_pixels_is_noop_when_already_clear(self):
        state = ControllerState(None)

        state.set_override_pixels([[(1, 2, 3)]])

        self.assertTrue(state.clear_override_pixels_if_present())
        self.assertFalse(state.clear_override_pixels_if_present())

    def test_playback_source_wakes_render_loop(self):
        state = ControllerState(None)

        state.set_playback_source(ControllerState.SOURCE_DESIGNER)

        self.assertTrue(state.render_event.is_set())
        state.wait_for_render_work(timeout=0)
        self.assertFalse(state.render_event.is_set())


if __name__ == "__main__":
    unittest.main()