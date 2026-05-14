import os
import sys
import unittest

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from artnet import ArtNetSender, ipv4_octets, parse_node_capabilities, parse_node_outputs
from state import LOOK_OUTPUT_TYPES, OUTPUT_TYPES


class BrokenSocket:
    def __init__(self):
        self.closed = False

    def sendto(self, packet, addr):
        raise BrokenPipeError("test socket closed")

    def close(self):
        self.closed = True


class ArtNetCapabilityTests(unittest.TestCase):
    def test_v35_v1_profile_capabilities(self):
        report = "#0001 [0000] OK|PV3CAP1|0:4:0|1:2:1|B:v1|IP:S|F:RIOH"
        caps = parse_node_capabilities(report, "PrimusV3", "PrimusV3.5 LED Node")
        self.assertTrue(caps["known"])
        self.assertEqual(caps["hardware_profile"], "v1")
        self.assertEqual(caps["hardware_label"], "V1 Huzzah32")
        self.assertEqual(caps["ip_mode"], "static")
        self.assertTrue(caps["rename"])
        self.assertTrue(caps["ip_config"])
        outputs = parse_node_outputs(
            "", [], OUTPUT_TYPES, node_report=report, type_keys=LOOK_OUTPUT_TYPES)
        self.assertEqual(outputs, [
            {"name": "A0", "type": "small_grid", "universe": 0},
            {"name": "A1", "type": "long_strip", "universe": 1},
        ])

    def test_v35_v2_profile_capabilities(self):
        report = "#0001 [0000] OK|PV3CAP1|0:4:0|1:1:1|B:v2|IP:D|F:RIOH"
        caps = parse_node_capabilities(report, "PrimusV3", "PrimusV3.5 LED Node")
        self.assertEqual(caps["hardware_profile"], "v2")
        self.assertEqual(caps["hardware_label"], "V2 Feather")
        self.assertEqual(caps["ip_mode"], "dhcp")
        outputs = parse_node_outputs(
            "", [], OUTPUT_TYPES, node_report=report, type_keys=LOOK_OUTPUT_TYPES)
        self.assertEqual(outputs[0]["type"], "small_grid")
        self.assertEqual(outputs[1]["type"], "short_strip")

    def test_legacy_small_grid_display_names_resolve_to_small_grid(self):
        for display_name in ("Grid 8x4", "Grid 4x8"):
            with self.subTest(display_name=display_name):
                outputs = parse_node_outputs(
                    f"PrimusV3.5 LED Node | A0:{display_name} A1:Long Strip",
                    [0, 1], OUTPUT_TYPES)
                self.assertEqual(outputs[0]["type"], "small_grid")
                self.assertEqual(outputs[1]["type"], "long_strip")

    def test_v31_without_profile_tag_defaults_to_v31(self):
        report = "#0001 [0000] OK|PV3CAP1|0:1:0|1:2:1|F:RIOH"
        caps = parse_node_capabilities(report, "PrimusV3", "PrimusV3 LED Node")
        self.assertTrue(caps["known"])
        self.assertEqual(caps["hardware_profile"], "v31")
        self.assertEqual(caps["hardware_label"], "V3.1 Reverse TFT")

    def test_unknown_profile_tag_remains_usable(self):
        report = "#0001 [0000] OK|PV3CAP1|0:5:0|B:custom|IP:S:192.168.1.77|F:OH"
        caps = parse_node_capabilities(report, "Custom", "Custom LED Node")
        self.assertTrue(caps["known"])
        self.assertEqual(caps["hardware_profile"], "custom")
        self.assertEqual(caps["hardware_label"], "custom")
        self.assertEqual(caps["ip_mode"], "static")
        self.assertEqual(caps["static_ip"], "192.168.1.77")
        self.assertFalse(caps["rename"])
        self.assertTrue(caps["hello"])
        self.assertTrue(caps["output_config"])

    def test_ipv4_octets_validates_dotted_quads(self):
        self.assertEqual(ipv4_octets("192.168.1.50"), [192, 168, 1, 50])
        with self.assertRaises(ValueError):
            ipv4_octets("192.168.1")
        with self.assertRaises(ValueError):
            ipv4_octets("192.168.1.999")

    def test_malformed_capability_outputs_fall_back(self):
        report = "#0001 [0000] OK|PV3CAP1|not-an-output|B:v31|F:RIOH"
        outputs = parse_node_outputs(
            "PrimusV3.5 LED Node | A0:Short Strip A1:Long Strip",
            [0, 1], OUTPUT_TYPES, node_report=report, type_keys=LOOK_OUTPUT_TYPES)
        self.assertEqual(outputs[0]["type"], "short_strip")
        self.assertEqual(outputs[1]["type"], "long_strip")

    def test_sender_disconnects_after_udp_send_error(self):
        sender = ArtNetSender("192.168.1.2")
        sock = BrokenSocket()
        sender.sock = sock
        sender.connected = True

        ok = sender.send_output(0, bytes([0, 0, 0] * 2))

        self.assertFalse(ok)
        self.assertFalse(sender.connected)
        self.assertIsNone(sender.sock)
        self.assertTrue(sock.closed)
        self.assertIn("test socket closed", sender.last_error)


if __name__ == "__main__":
    unittest.main()
