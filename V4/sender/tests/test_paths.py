"""Tests for Radius Central V4 paths."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import paths


class PathsTests(unittest.TestCase):
    def test_sender_dir_exists(self):
        self.assertTrue(os.path.isdir(paths.sender_dir()))

    def test_state_file_name_radius(self):
        os.environ.pop("PRIMUSV3_SENDER_PRODUCT", None)
        self.assertTrue(paths.state_file().endswith(".radius_state.json"))

    def test_state_file_name_primus(self):
        os.environ["PRIMUSV3_SENDER_PRODUCT"] = "primus"
        try:
            self.assertTrue(paths.state_file().endswith(".primus_state.json"))
            self.assertIn("PrimusV3", paths._default_app_root_dir())
        finally:
            os.environ.pop("PRIMUSV3_SENDER_PRODUCT", None)

    def test_index_html_path(self):
        os.environ["PRIMUSV3_SENDER_PRODUCT"] = "primus"
        try:
            self.assertTrue(paths.index_html_path().endswith("index-primus.html"))
            self.assertTrue(paths.frontend_index_path("primus").endswith("index-primus.html"))
            self.assertTrue(paths.frontend_index_path("radius").endswith("index.html"))
            self.assertEqual(paths.default_frontend_path(), "/primus")
        finally:
            os.environ.pop("PRIMUSV3_SENDER_PRODUCT", None)

    def test_default_frontend_path_radius(self):
        os.environ.pop("PRIMUSV3_SENDER_PRODUCT", None)
        self.assertEqual(paths.default_frontend_path(), "/radius")

    def test_web_dir(self):
        self.assertTrue(os.path.isdir(paths.web_dir()))

    def test_v4_app_data_root(self):
        root = paths._default_app_root_dir()
        self.assertIn("RadiusV3", root)
        self.assertIn("V4", root)


if __name__ == "__main__":
    unittest.main()
