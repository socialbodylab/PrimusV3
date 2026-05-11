import os
import sys
import unittest
from unittest.mock import patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from controller import CueList


LOOK_ID = "look-1"
LOOK_WITH_TARGET = {
    "id": LOOK_ID,
    "name": "Targeted Look",
    "device_ips": ["192.168.1.10", "192.168.1.11"],
    "outputs": [],
    "tracks": [],
}
SECOND_LOOK = {
    "id": "look-2",
    "name": "Second Targeted Look",
    "device_ips": ["192.168.1.12"],
    "outputs": [],
    "tracks": [],
}


class ControllerLookTargetTests(unittest.TestCase):
    def make_cue_list(self):
        with patch.object(CueList, "_load", return_value=None):
            return CueList()

    def device_ips(self, cue_list):
        state = cue_list.get_crossfade_state()
        return set(state["device_ips"]) if state["device_ips"] is not None else None

    def test_direct_activation_uses_saved_look_targets(self):
        cue_list = self.make_cue_list()

        with patch("controller.load_look", return_value=LOOK_WITH_TARGET):
            self.assertTrue(cue_list.activate_look(LOOK_ID, fade_time=0.0))

        self.assertEqual(self.device_ips(cue_list), {"192.168.1.10", "192.168.1.11"})

    def test_direct_activation_preserves_empty_saved_target(self):
        cue_list = self.make_cue_list()
        look = dict(LOOK_WITH_TARGET, device_ips=[])

        with patch("controller.load_look", return_value=look):
            self.assertTrue(cue_list.activate_look(LOOK_ID, fade_time=0.0))

        self.assertEqual(self.device_ips(cue_list), set())

    def test_multi_activation_reports_active_ids_and_target_union(self):
        cue_list = self.make_cue_list()

        def load(look_id):
            return {LOOK_ID: LOOK_WITH_TARGET, "look-2": SECOND_LOOK}.get(look_id)

        with patch("controller.load_look", side_effect=load):
            self.assertTrue(cue_list.activate_looks([LOOK_ID, "look-2"], fade_time=0.0))

        self.assertEqual(cue_list.active_look_ids(), [LOOK_ID, "look-2"])
        self.assertEqual(
            self.device_ips(cue_list),
            {"192.168.1.10", "192.168.1.11", "192.168.1.12"},
        )
        active = cue_list.get_crossfade_state()["active_looks"]
        self.assertEqual([entry["look_id"] for entry in active], [LOOK_ID, "look-2"])

    def test_multi_activation_all_target_keeps_all_scope(self):
        cue_list = self.make_cue_list()
        all_look = dict(LOOK_WITH_TARGET)
        all_look.pop("device_ips")

        def load(look_id):
            return {LOOK_ID: all_look, "look-2": SECOND_LOOK}.get(look_id)

        with patch("controller.load_look", side_effect=load):
            self.assertTrue(cue_list.activate_looks([LOOK_ID, "look-2"], fade_time=0.0))

        self.assertIsNone(self.device_ips(cue_list))

    def test_deactivate_look_removes_single_active_entry(self):
        cue_list = self.make_cue_list()

        def load(look_id):
            return {LOOK_ID: LOOK_WITH_TARGET, "look-2": SECOND_LOOK}.get(look_id)

        with patch("controller.load_look", side_effect=load):
            cue_list.activate_looks([LOOK_ID, "look-2"], fade_time=0.0)

        cue_list.deactivate_look(LOOK_ID)

        self.assertEqual(cue_list.active_look_ids(), ["look-2"])
        self.assertEqual(self.device_ips(cue_list), {"192.168.1.12"})

    def test_cue_inherits_saved_look_targets(self):
        cue_list = self.make_cue_list()
        cue_list.cues = [{"number": 1, "look_id": LOOK_ID, "name": "Cue"}]

        with patch("controller.load_look", return_value=LOOK_WITH_TARGET):
            cue = cue_list.go(device_groups=[])

        self.assertEqual(cue["look_id"], LOOK_ID)
        self.assertEqual(self.device_ips(cue_list), {"192.168.1.10", "192.168.1.11"})

    def test_cue_device_override_wins_over_look_targets(self):
        cue_list = self.make_cue_list()
        cue_list.cues = [{
            "number": 1,
            "look_id": LOOK_ID,
            "name": "Cue",
            "target_mode": "devices",
            "device_ips": ["192.168.1.20"],
        }]

        with patch("controller.load_look", return_value=LOOK_WITH_TARGET):
            cue_list.go(device_groups=[])

        self.assertEqual(self.device_ips(cue_list), {"192.168.1.20"})

    def test_cue_all_override_ignores_look_targets(self):
        cue_list = self.make_cue_list()
        cue_list.cues = [{
            "number": 1,
            "look_id": LOOK_ID,
            "name": "Cue",
            "target_mode": "all",
        }]

        with patch("controller.load_look", return_value=LOOK_WITH_TARGET):
            cue_list.go(device_groups=[])

        self.assertIsNone(self.device_ips(cue_list))

    def test_missing_group_override_does_not_fall_back_to_look_targets(self):
        cue_list = self.make_cue_list()
        cue_list.cues = [{
            "number": 1,
            "look_id": LOOK_ID,
            "name": "Cue",
            "target_mode": "group",
            "device_group_id": "missing",
        }]

        with patch("controller.load_look", return_value=LOOK_WITH_TARGET):
            cue_list.go(device_groups=[])

        self.assertEqual(self.device_ips(cue_list), set())


if __name__ == "__main__":
    unittest.main()
