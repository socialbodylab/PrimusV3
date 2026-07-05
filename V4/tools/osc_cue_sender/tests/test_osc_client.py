import os
import sys
import unittest


APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from osc_client import (
    build_blackout_message,
    build_cue_message,
    build_go_message,
    build_stop_message,
    cue_slug,
    format_target_address,
    normalize_osc_address,
    parse_osc_args,
    parse_target_address,
)
from app_state import cues_from_import_payload


class OscAddressTests(unittest.TestCase):
    def test_primus_go(self):
        address, args = build_go_message("primus")
        self.assertEqual(address, "/primus/cue/go")
        self.assertEqual(args, ())

    def test_qlab_go(self):
        address, args = build_go_message("qlab")
        self.assertEqual(address, "/cue/go")
        self.assertEqual(args, ())

    def test_primus_goto(self):
        address, args = build_cue_message("primus", number=3)
        self.assertEqual(address, "/primus/cue/goto")
        self.assertEqual(args, (3,))

    def test_qlab_number(self):
        address, args = build_cue_message("qlab", number=3)
        self.assertEqual(address, "/cue/3/start")
        self.assertEqual(args, ())

    def test_primus_name(self):
        address, args = build_cue_message("primus", name="Opening Look")
        self.assertEqual(address, "/primus/cue/name")
        self.assertEqual(args, ("Opening Look",))

    def test_qlab_slug(self):
        address, args = build_cue_message("qlab", name="Opening Look")
        self.assertEqual(address, "/cue/opening-look/start")
        self.assertEqual(args, ())

    def test_blackout_fade(self):
        address, args = build_blackout_message("primus", 0.5)
        self.assertEqual(address, "/primus/blackout")
        self.assertEqual(args, (0.5,))

    def test_stop_aliases(self):
        self.assertEqual(build_stop_message("primus")[0], "/primus/cue/stop")
        self.assertEqual(build_stop_message("qlab")[0], "/stop")

    def test_cue_slug(self):
        self.assertEqual(cue_slug("Opening Look"), "opening-look")


class TargetAddressTests(unittest.TestCase):
    def test_host_only(self):
        self.assertEqual(parse_target_address("192.168.1.50"), ("192.168.1.50", 53001))

    def test_host_and_port(self):
        self.assertEqual(parse_target_address("192.168.1.50:53002"), ("192.168.1.50", 53002))

    def test_ipv6(self):
        self.assertEqual(parse_target_address("[fe80::1]:53003"), ("fe80::1", 53003))

    def test_format_target_address(self):
        self.assertEqual(format_target_address("192.168.1.50", 53001), "192.168.1.50:53001")

    def test_invalid_port(self):
        with self.assertRaises(ValueError):
            parse_target_address("192.168.1.50:notaport")


class RawOscTests(unittest.TestCase):
    def test_normalize_osc_address(self):
        self.assertEqual(normalize_osc_address(" /primus/cue/go "), "/primus/cue/go")

    def test_invalid_osc_address(self):
        with self.assertRaises(ValueError):
            normalize_osc_address("primus/cue/go")

    def test_parse_osc_args_json(self):
        self.assertEqual(parse_osc_args("[1, 2.5, \"Blackout\"]"), [1, 2.5, "Blackout"])

    def test_parse_osc_args_csv(self):
        self.assertEqual(parse_osc_args("1, 0.5, Blackout"), [1, 0.5, "Blackout"])

    def test_parse_osc_args_empty(self):
        self.assertEqual(parse_osc_args(""), [])
        self.assertEqual(parse_osc_args(None), [])


class ImportTests(unittest.TestCase):
    def test_import_payload(self):
        cues = cues_from_import_payload(
            {"cues": [{"number": 2, "name": "Verse"}, {"number": 1, "name": "Intro"}]}
        )
        self.assertEqual(cues[0]["number"], 1)
        self.assertEqual(cues[1]["name"], "Verse")


if __name__ == "__main__":
    unittest.main()
