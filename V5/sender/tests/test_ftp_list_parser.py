"""Tests for the FTP LIST line parser.

_parse_list_line broke twice in V3.6, and the 8-field regression recurred in the
V5 forward-port (the function was simplified to require the 9-field standard Unix
format, silently dropping every Radius SD entry — "No WAV files on SD card"):
- SimpleFTPServer's 8-field format (no group column) must be accepted
- the filename must not get the time/year field glued on

Do not revert to requiring the 9-field standard Unix format.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from artnet import _parse_list_line


class FtpListParserTests(unittest.TestCase):
    def test_simpleftpserver_8_field_line(self):
        # SimpleFTPServer SD storage: permissions links user size month day time name
        entry = _parse_list_line("-rw-r--r--   1 owner   245760 Jan 01 2000 HELLO.WAV")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["name"], "HELLO.WAV")
        self.assertEqual(entry["size"], 245760)
        self.assertFalse(entry["is_dir"])

    def test_filename_has_no_time_or_year_prefix(self):
        # Regression: split(None, 7) yielded "2000 HELLO.WAV"
        entry = _parse_list_line("-rw-r--r--   1 owner   245760 Jan 01 2000 HELLO.WAV")
        self.assertNotIn("2000", entry["name"])
        self.assertNotIn(" ", entry["name"])

    def test_standard_unix_9_field_line(self):
        entry = _parse_list_line("-rw-r--r--  1 user group 245760 Jan  1 00:00 HELLO.WAV")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["name"], "HELLO.WAV")
        self.assertEqual(entry["size"], 245760)

    def test_9_field_filename_with_spaces(self):
        entry = _parse_list_line("-rw-r--r--  1 user group 100 Jan  1 00:00 MY TRACK.WAV")
        self.assertEqual(entry["name"], "MY TRACK.WAV")
        self.assertEqual(entry["size"], 100)

    def test_directory_entry(self):
        entry = _parse_list_line("drwxr-xr-x   1 owner   0 Jan 01 2000 SYSTEM~1")
        self.assertTrue(entry["is_dir"])
        self.assertEqual(entry["name"], "SYSTEM~1")

    def test_non_numeric_size_falls_back_to_zero(self):
        entry = _parse_list_line("-rw-r--r--  1 user group xyz Jan  1 00:00 F.WAV")
        self.assertEqual(entry["size"], 0)
        self.assertEqual(entry["name"], "F.WAV")

    def test_too_few_fields_returns_none(self):
        self.assertIsNone(_parse_list_line("total 4"))
        self.assertIsNone(_parse_list_line(""))
        self.assertIsNone(_parse_list_line("-rw-r--r-- 1 owner 100"))


if __name__ == "__main__":
    unittest.main()
