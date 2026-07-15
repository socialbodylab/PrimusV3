"""Tests for mixed Primus + Radius device discovery on primus product."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from artnet import is_compatible_node, parse_node_capabilities


class MixedDeviceDiscoveryTests(unittest.TestCase):
    def test_primus_product_accepts_pvrad1(self):
        node = {
            "node_report": "PVRAD1|B:v2|IP:D|F:RIHAS",
            "short_name": "Radius",
            "long_name": "Radius Central V2",
        }
        self.assertTrue(is_compatible_node(node, "primus"))

    def test_primus_product_still_accepts_pv3cap1(self):
        node = {
            "node_report": "PV3CAP1|B:v3|IP:D|F:RIOHBS",
            "short_name": "PrimusV3",
            "long_name": "",
        }
        self.assertTrue(is_compatible_node(node, "primus"))

    def test_radius_show_info_flag(self):
        caps = parse_node_capabilities("PVRAD1|B:v1|IP:D|F:RIHAS", "Radius", "")
        self.assertEqual(caps["device_class"], "radius")
        self.assertTrue(caps["show_info"])


if __name__ == "__main__":
    unittest.main()
