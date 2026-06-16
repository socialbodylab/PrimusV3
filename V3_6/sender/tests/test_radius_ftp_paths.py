import os
import sys
import unittest

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from server import _safe_ftp_path


class SafeFtpPathTests(unittest.TestCase):

    # -- Valid paths --

    def test_root_is_valid(self):
        self.assertTrue(_safe_ftp_path("/"))

    def test_simple_file_is_valid(self):
        self.assertTrue(_safe_ftp_path("/track.wav"))

    def test_nested_path_is_valid(self):
        self.assertTrue(_safe_ftp_path("/songs/show/intro.wav"))

    def test_path_with_spaces_is_valid(self):
        self.assertTrue(_safe_ftp_path("/my files/track 01.wav"))

    def test_path_with_dots_in_filename_is_valid(self):
        self.assertTrue(_safe_ftp_path("/audio/cue.v2.wav"))

    # -- Traversal attacks --

    def test_dotdot_segment_is_rejected(self):
        self.assertFalse(_safe_ftp_path("/audio/../etc/passwd"))

    def test_dotdot_at_root_is_rejected(self):
        self.assertFalse(_safe_ftp_path("/../etc"))

    def test_dotdot_only_is_rejected(self):
        self.assertFalse(_safe_ftp_path("/.."))

    # -- Non-absolute paths --

    def test_relative_path_is_rejected(self):
        self.assertFalse(_safe_ftp_path("audio/track.wav"))

    def test_empty_string_is_rejected(self):
        self.assertFalse(_safe_ftp_path(""))

    # -- Bad types and null bytes --

    def test_null_byte_is_rejected(self):
        self.assertFalse(_safe_ftp_path("/audio/\x00track.wav"))

    def test_none_is_rejected(self):
        self.assertFalse(_safe_ftp_path(None))

    def test_integer_is_rejected(self):
        self.assertFalse(_safe_ftp_path(42))


if __name__ == "__main__":
    unittest.main()
