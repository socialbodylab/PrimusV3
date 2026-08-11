"""Tests for Net Log emission on show-info writes and confirmations.

Covers the logging added alongside the ArtShowInfo (0x8210) feature:
  * send_show_info           -> OUT show_info write (with char/perf values)
  * sync_show_info_to_device -> IN show_info confirmation (confirmed / NOT confirmed)
  * update_device_show_info  -> OUT show_info local-only save (no capability)
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import artnet
import netlog


def _show_info_entries():
    return [e for e in netlog.get_entries() if e["type"] == "show_info"]


class ShowInfoWriteLogTests(unittest.TestCase):
    def setUp(self):
        netlog.clear()

    @patch("artnet._send_udp_packet")
    def test_send_show_info_logs_out_write_with_values(self, _send):
        artnet.send_show_info("10.0.0.5", "Robot", "Alex")

        entries = _show_info_entries()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["dir"], "OUT")
        self.assertIn("write", entry["summary"])
        self.assertIn("10.0.0.5", entry["summary"])
        self.assertIn("Robot", entry["summary"])
        self.assertIn("Alex", entry["summary"])


class ShowInfoConfirmationLogTests(unittest.TestCase):
    def setUp(self):
        netlog.clear()

    @patch("artnet._send_udp_packet")
    @patch("artnet.query_show_info")
    def test_confirmed_on_match(self, query, _send):
        query.return_value = {
            "character_name": "Robot",
            "performer_name": "Alex",
            "mode": artnet.SHOW_INFO_MODE_RESPONSE,
        }

        ok, error = artnet.sync_show_info_to_device("10.0.0.5", "Robot", "Alex")

        self.assertTrue(ok)
        self.assertEqual(error, "")
        entries = _show_info_entries()
        # one OUT write + one IN confirmation
        self.assertEqual([e["dir"] for e in entries], ["OUT", "IN"])
        confirm = entries[1]
        self.assertIn("confirmed", confirm["summary"])
        self.assertNotIn("NOT confirmed", confirm["summary"])
        self.assertIn("Robot", confirm["summary"])

    @patch("artnet._send_udp_packet")
    @patch("artnet.query_show_info")
    def test_not_confirmed_on_mismatch(self, query, _send):
        query.return_value = {
            "character_name": "Wrong",
            "performer_name": "Person",
            "mode": artnet.SHOW_INFO_MODE_RESPONSE,
        }

        ok, error = artnet.sync_show_info_to_device("10.0.0.5", "Robot", "Alex")

        self.assertFalse(ok)
        in_entries = [e for e in _show_info_entries() if e["dir"] == "IN"]
        self.assertEqual(len(in_entries), 1)
        self.assertIn("NOT confirmed", in_entries[0]["summary"])

    @patch("artnet._send_udp_packet")
    @patch("artnet.query_show_info", return_value=None)
    def test_not_confirmed_on_no_response(self, _query, _send):
        ok, error = artnet.sync_show_info_to_device("10.0.0.5", "Robot", "Alex")

        self.assertFalse(ok)
        in_entries = [e for e in _show_info_entries() if e["dir"] == "IN"]
        self.assertEqual(len(in_entries), 1)
        self.assertIn("NOT confirmed", in_entries[0]["summary"])
        self.assertIn("did not respond", in_entries[0]["summary"])


class ShowInfoLocalSaveLogTests(unittest.TestCase):
    def setUp(self):
        netlog.clear()
        import radius_state
        self.temp_dir = tempfile.TemporaryDirectory()
        self.radius_state_path = os.path.join(self.temp_dir.name, ".radius_state.json")
        self.path_patch = patch.object(
            radius_state.show_info_store,
            "radius_state_path",
            return_value=self.radius_state_path,
        )
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.temp_dir.cleanup()

    @patch("radius_state._save_devices")
    def test_local_save_logs_when_no_capability(self, _save):
        from radius_state import RadiusState

        radius = RadiusState()
        radius.devices = [{
            "ip": "192.168.1.70",
            "name": "Plain",
            "capabilities": {"show_info": False},
            "is_radius": False,
            "character_name": "",
            "performer_name": "",
        }]

        result = radius.update_device_show_info(0, character_name="Robot", performer_name="Alex")

        self.assertTrue(result["ok"])
        self.assertFalse(result["applied_to_device"])
        entries = _show_info_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["dir"], "OUT")
        self.assertIn("saved locally", entries[0]["summary"])
        self.assertIn("Plain", entries[0]["summary"])
        self.assertIn("Robot", entries[0]["summary"])


if __name__ == "__main__":
    unittest.main()
