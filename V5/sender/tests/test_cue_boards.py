import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import cue_boards


class CueBoardTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.patch = patch.object(cue_boards, "cue_boards_dir", return_value=self.tempdir.name)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tempdir.cleanup()

    def test_save_list_load_delete(self):
        board = cue_boards.save_cue_board(
            "Opening Night",
            [{"number": 1, "name": "Intro", "fade_time": 1.0}],
        )
        self.assertTrue(board["id"])
        boards = cue_boards.list_cue_boards()
        self.assertEqual(len(boards), 1)
        self.assertEqual(boards[0]["name"], "Opening Night")
        self.assertEqual(boards[0]["cue_count"], 1)

        loaded = cue_boards.load_cue_board(board["id"])
        self.assertEqual(loaded["cues"][0]["name"], "Intro")

        updated = cue_boards.save_cue_board(
            "Opening Night Revised",
            [{"number": 1, "name": "Intro"}, {"number": 2, "name": "Verse"}],
            board_id=board["id"],
        )
        self.assertEqual(updated["id"], board["id"])
        self.assertEqual(len(updated["cues"]), 2)

        self.assertTrue(cue_boards.delete_cue_board(board["id"]))
        self.assertEqual(cue_boards.list_cue_boards(), [])

    def test_requires_name(self):
        with self.assertRaises(ValueError):
            cue_boards.save_cue_board("", [])


if __name__ == "__main__":
    unittest.main()
