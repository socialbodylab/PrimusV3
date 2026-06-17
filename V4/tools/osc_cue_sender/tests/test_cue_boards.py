import os
import sys
import tempfile
import unittest
from unittest.mock import patch


APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import cue_boards


class OscCueBoardTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.patch = patch.object(cue_boards, "cue_boards_dir", return_value=self.tempdir.name)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tempdir.cleanup()

    def test_save_and_normalize(self):
        board = cue_boards.save_cue_board(
            "Test Board",
            [{"number": 2, "name": "B"}, {"number": 1, "name": "A"}],
        )
        loaded = cue_boards.load_cue_board(board["id"])
        self.assertEqual(loaded["cues"][0]["number"], 1)
        self.assertEqual(loaded["cues"][1]["number"], 2)


if __name__ == "__main__":
    unittest.main()
