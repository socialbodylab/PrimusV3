import os
import sys
import unittest

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from state import ControllerState


class MixerPreviewTargetTests(unittest.TestCase):
    def make_state(self):
        state = ControllerState(None)
        state.devices = [
            {"ip": "192.168.1.10", "connected": True},
            {"ip": "192.168.1.11", "connected": True},
            {"ip": "192.168.1.12", "connected": False},
        ]
        return state

    def playback_target(self, state):
        with state.lock:
            return state._playback_status_unlocked()

    def test_preview_start_normalizes_multiple_targets(self):
        state = self.make_state()
        state.start_mixer_preview(
            {"outputs": [], "tracks": [{"segments": []}]},
            device_filter=[0, "1", 1, 42, "bad"],
            play_time=0.0,
            playing=True,
        )

        playback = self.playback_target(state)
        self.assertEqual(playback["source"], "mixer")
        self.assertEqual(playback["selected_count"], 2)
        self.assertEqual(playback["connected_count"], 2)
        self.assertEqual(playback["target_label"], "2 selected devices")

    def test_preview_update_changes_live_targets(self):
        state = self.make_state()
        state.start_mixer_preview(
            {"outputs": [], "tracks": [{"segments": []}]},
            device_filter=[0],
            play_time=0.0,
            playing=True,
        )
        self.assertEqual(self.playback_target(state)["target_label"], "1 selected device")

        state.update_mixer_preview(device_filter=[0, 1])
        playback = self.playback_target(state)
        self.assertEqual(playback["selected_count"], 2)
        self.assertEqual(playback["connected_count"], 2)
        self.assertEqual(playback["target_label"], "2 selected devices")

    def test_preview_update_can_return_to_all_targets(self):
        state = self.make_state()
        state.start_mixer_preview(
            {"outputs": [], "tracks": [{"segments": []}]},
            device_filter=[0],
            play_time=0.0,
            playing=True,
        )

        state.update_mixer_preview(device_filter=None)
        playback = self.playback_target(state)
        self.assertEqual(playback["scope"], "all")
        self.assertEqual(playback["selected_count"], 3)
        self.assertEqual(playback["connected_count"], 2)
        self.assertEqual(playback["target_label"], "All devices (2 connected)")

    def test_preview_start_sequence_ignores_stale_update(self):
        state = self.make_state()
        state.start_mixer_preview(
            {"outputs": [], "tracks": [{"segments": []}]},
            play_time=2.0,
            transport_time=8.0,
            playing=False,
            seq=10,
        )

        state.update_mixer_preview(play_time=1.0, transport_time=1.0, seq=9)
        with state.lock:
            self.assertEqual(state._mixer_preview_play_time, 2.0)
            self.assertEqual(state._mixer_preview_transport_time, 8.0)

        state.update_mixer_preview(play_time=3.0, transport_time=9.0, seq=11)
        with state.lock:
            self.assertEqual(state._mixer_preview_play_time, 3.0)
            self.assertEqual(state._mixer_preview_transport_time, 9.0)


if __name__ == "__main__":
    unittest.main()
