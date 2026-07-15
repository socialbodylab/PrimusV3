"""Tests for virtual resolution transport helpers and API wiring."""

import os
import sys
import unittest
from unittest import mock
from unittest.mock import patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from artnet import (
    _parse_capability_outputs,
    build_virtual_resolution_packet,
    parse_node_outputs,
)
from state import (
    ControllerState,
    LOOK_OUTPUT_TYPES,
    OUTPUT_TYPES,
    _combined_pixel_total,
    _queue_device_frame_sends,
    _validate_receive_mode_for_device,
)
from virtual_resolution import (
    default_virtual_pixels,
    downsample_pixels,
    resolve_virtual_pixels,
    transport_rgb_bytes,
    virtual_percent_to_count,
)


class VirtualResolutionHelperTests(unittest.TestCase):
    def test_default_virtual_pixels(self):
        self.assertEqual(default_virtual_pixels("small_grid", 32), 1)
        self.assertEqual(default_virtual_pixels("long_strip", 72), 72)
        self.assertEqual(default_virtual_pixels("none", 0), 0)

    def test_downsample_single_pixel_averages_all(self):
        pixels = [(i, 0, 0) for i in range(32)]
        out = downsample_pixels(pixels, 1)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], 15)

    def test_downsample_half_resolution(self):
        pixels = [(0, 0, 0), (10, 0, 0), (20, 0, 0), (30, 0, 0)]
        out = downsample_pixels(pixels, 2)
        self.assertEqual(out, [(5, 0, 0), (25, 0, 0)])

    def test_transport_rgb_bytes_collapses_badge(self):
        output = {"type": "small_grid", "count": 32, "virtual_pixels": 1}
        pixels = [(255, 0, 0)] * 32
        data = transport_rgb_bytes(output, pixels=pixels)
        self.assertEqual(data, bytes([255, 0, 0]))

    def test_virtual_percent_to_count(self):
        self.assertEqual(virtual_percent_to_count(72, 50), 36)
        self.assertEqual(virtual_percent_to_count(32, 100), 32)
        self.assertEqual(virtual_percent_to_count(72, 1), 1)


class VirtualResolutionTransportTests(unittest.TestCase):
    def test_combined_total_uses_virtual_counts(self):
        outputs = [
            {"type": "small_grid", "count": 32, "virtual_pixels": 1},
            {"type": "long_strip", "count": 72, "virtual_pixels": 72},
        ]
        self.assertEqual(_combined_pixel_total(outputs), 73)

    def test_combined_validation_uses_virtual_total(self):
        outputs = [
            {"type": "extra_long_strip", "count": 122, "virtual_pixels": 122},
            {"type": "long_strip", "count": 72, "virtual_pixels": 72},
        ]
        ok, err = _validate_receive_mode_for_device("combined", outputs)
        self.assertFalse(ok)
        self.assertIn("170", err)

    def test_queue_device_frame_sends_combined_virtual_bytes(self):
        dev = {
            "receive_mode": "combined",
            "base_universe": 104,
            "sender": object(),
            "outputs": [
                {"type": "small_grid", "count": 32, "virtual_pixels": 1},
                {"type": "long_strip", "count": 72, "virtual_pixels": 72},
            ],
        }
        frame_buffers = {
            0: bytes([255, 0, 0] * 32),
            1: bytes([0, 255, 0] * 72),
        }
        send_queue = []
        _queue_device_frame_sends(send_queue, 0, dev, frame_buffers)
        self.assertEqual(len(send_queue), 1)
        _, _, universe, payload = send_queue[0]
        self.assertEqual(universe, 104)
        self.assertEqual(len(payload), (1 + 72) * 3)
        self.assertEqual(payload[:3], bytes([255, 0, 0]))


class VirtualResolutionDiscoveryTests(unittest.TestCase):
    def test_parse_long_name_preserves_off_a0_and_active_a1_slots(self):
        outputs = parse_node_outputs(
            "PrimusV3.6 LED Node | A0:Off A1:Long Strip ",
            [104, 105],
            OUTPUT_TYPES,
            type_keys=LOOK_OUTPUT_TYPES,
        )
        self.assertEqual(
            [(output["name"], output["type"]) for output in outputs],
            [("A0", "none"), ("A1", "long_strip")],
        )

    def test_parse_capability_outputs_preserves_off_slot(self):
        report = "#0001 [0001] OK|PV3CAP1|0:0:104:0|1:2:105:72"
        outputs = _parse_capability_outputs(report, LOOK_OUTPUT_TYPES)
        self.assertEqual(
            [(output["name"], output["type"], output["universe"]) for output in outputs],
            [("A0", "none", 104), ("A1", "long_strip", 105)],
        )

    def test_parse_capability_outputs_with_virtual_field(self):
        report = "#0001 [0001] OK|PV3CAP1|0:4:104:1|1:2:104:72"
        outputs = _parse_capability_outputs(report, LOOK_OUTPUT_TYPES)
        self.assertEqual(len(outputs), 2)
        self.assertEqual(outputs[0]["virtual_pixels"], 1)
        self.assertEqual(outputs[1]["virtual_pixels"], 72)

    def test_parse_capability_outputs_without_virtual_field(self):
        report = "#0001 [0001] OK|PV3CAP1|0:4:104|1:2:105"
        outputs = _parse_capability_outputs(report, LOOK_OUTPUT_TYPES)
        self.assertEqual(len(outputs), 2)
        self.assertNotIn("virtual_pixels", outputs[0])

    def test_parse_node_outputs_merges_truncated_312_report_with_long_name(self):
        report = (
            "#0001 [0123] OK|PV3CAP1|F:RIOHBMS|B:v31|IP:D|U:C:0|0:4:0:1|1:2:0"
        )
        long_name = "PrimusV3.6 LED Node | A0:Grid 8x4 A1:Short Strip "
        outputs = parse_node_outputs(
            long_name,
            [0, 0],
            OUTPUT_TYPES,
            node_report=report,
            type_keys=LOOK_OUTPUT_TYPES,
        )
        self.assertEqual(len(outputs), 2)
        self.assertEqual(outputs[0]["name"], "A0")
        self.assertEqual(outputs[0]["type"], "small_grid")
        self.assertEqual(outputs[0]["universe"], 0)
        self.assertEqual(outputs[0]["virtual_pixels"], 1)
        self.assertEqual(outputs[1]["name"], "A1")
        self.assertEqual(outputs[1]["type"], "short_strip")

    def test_parse_node_outputs_keeps_capability_universe_when_long_name_lacks_it(self):
        report = "#0001 [0001] OK|PV3CAP1|F:RIOHBMS|B:v31|IP:D|U:C:0|0:4:0:1"
        long_name = "PrimusV3.6 LED Node | A0:Grid 8x4 A1:Short Strip "
        outputs = parse_node_outputs(
            long_name,
            [0, 0],
            OUTPUT_TYPES,
            node_report=report,
            type_keys=LOOK_OUTPUT_TYPES,
        )
        self.assertEqual(outputs[0]["universe"], 0)
        self.assertEqual(outputs[0]["virtual_pixels"], 1)
        self.assertEqual(outputs[1]["type"], "short_strip")


class VirtualResolutionPacketTests(unittest.TestCase):
    def test_build_virtual_resolution_packet(self):
        pkt = build_virtual_resolution_packet([1, 72])
        self.assertTrue(pkt.startswith(b"Art-Net\x00"))
        self.assertEqual(pkt[8] | (pkt[9] << 8), 0x8130)
        self.assertEqual(pkt[12], 2)
        self.assertEqual(pkt[13] | (pkt[14] << 8), 1)
        self.assertEqual(pkt[15] | (pkt[16] << 8), 72)


class VirtualResolutionApiTests(unittest.TestCase):
    @patch("state.send_virtual_resolution")
    @patch("state._save_devices")
    def test_set_device_virtual_resolution(self, save_devices, send_virtual_resolution):
        send_virtual_resolution.return_value = None
        controller = ControllerState(None)
        controller.devices = [{
            "name": "Badge-A",
            "ip": "192.168.1.50",
            "connected": True,
            "capabilities": {"output_config": True},
            "sender": mock.Mock(connected=True),
            "receive_mode": "split",
            "outputs": [{
                "name": "A0",
                "type": "small_grid",
                "count": 32,
                "virtual_pixels": 1,
                "universe": 0,
            }],
        }]
        result = controller.set_device_virtual_resolution(0, 0, virtual_pixels=32)
        self.assertTrue(result["ok"])
        self.assertEqual(controller.devices[0]["outputs"][0]["virtual_pixels"], 32)
        send_virtual_resolution.assert_called_once()

    def test_resolve_virtual_pixels_defaults(self):
        self.assertEqual(resolve_virtual_pixels({"type": "small_grid", "count": 32}), 1)
        self.assertEqual(resolve_virtual_pixels({"type": "long_strip", "count": 72}), 72)


if __name__ == "__main__":
    unittest.main()
