"""Tests for Primus and Radius PBT battery telemetry."""

import os
import socket
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from artnet import (
    BATTERY_MAGIC,
    BATTERY_POWER_MODE_BATTERY,
    BATTERY_POWER_MODE_CHARGING,
    BATTERY_POWER_MODE_SWITCH_OFF,
    FPS_MAGIC,
    PrimusTelemetryListener,
    RadiusTelemetryListener,
    parse_node_capabilities,
    parse_pbt_packet,
    parse_pfp_packet,
)


class BatteryTelemetryTests(unittest.TestCase):
    def test_parse_pbt_packet_valid_battery(self):
        raw = bytes([
            *BATTERY_MAGIC,
            BATTERY_POWER_MODE_BATTERY,
            0x0E, 0x74,  # 3700 mV
            72,
            7, 3,
        ])
        parsed = parse_pbt_packet(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["battery_power_mode"], "battery")
        self.assertEqual(parsed["battery_mv"], 3700)
        self.assertEqual(parsed["battery_pct"], 72)
        self.assertEqual(parsed["live_firmware_version"], "3.7")
        self.assertIsNone(parsed["battery_warning"])

    def test_parse_pbt_packet_charging(self):
        raw = bytes([
            *BATTERY_MAGIC,
            BATTERY_POWER_MODE_CHARGING,
            0x0F, 0x3A,  # 3898 mV
            85,
            7, 3,
        ])
        parsed = parse_pbt_packet(raw)
        self.assertEqual(parsed["battery_power_mode"], "charging")
        self.assertEqual(parsed["battery_mv"], 3898)
        self.assertEqual(parsed["battery_pct"], 85)

    def test_parse_pbt_packet_switch_off_warning(self):
        raw = bytes([
            *BATTERY_MAGIC,
            BATTERY_POWER_MODE_SWITCH_OFF,
            0x00, 0x00,
            255,
            7, 3,
        ])
        parsed = parse_pbt_packet(raw)
        self.assertEqual(parsed["battery_power_mode"], "switch_off")
        self.assertIsNone(parsed["battery_mv"])
        self.assertIsNone(parsed["battery_pct"])
        self.assertEqual(parsed["battery_warning"], "Power switch off — turn on to charge")

    def test_parse_pbt_packet_rejects_short_or_wrong_magic(self):
        self.assertIsNone(parse_pbt_packet(b"PFP\x00\x00\x00\x00\x00\x00"))
        self.assertIsNone(parse_pbt_packet(bytes([*BATTERY_MAGIC, 0])))

    def test_parse_pfp_packet(self):
        raw = bytes([*FPS_MAGIC, 0x00, 0x1E, 0x00, 0x3C])
        parsed = parse_pfp_packet(raw)
        self.assertEqual(parsed["fps"], 30)
        self.assertEqual(parsed["pkt_rate"], 60)

    def test_pv3cap1_battery_capability(self):
        report = "PV3CAP1|0:4:0|1:2:1|B:v1|IP:D|F:RIOHB"
        caps = parse_node_capabilities(report, "PrimusV3", "PrimusV3.6 LED Node")
        self.assertTrue(caps["battery"])
        self.assertTrue(caps["output_config"])
        self.assertEqual(caps["hardware_profile"], "v1")

    def test_primus_telemetry_listener_merges_pfp_and_pbt(self):
        # port=0 binds an ephemeral port — the real 6455 belongs to any
        # running Central, and grabbing it from a test steals live telemetry
        listener = PrimusTelemetryListener(port=0)
        ip = "192.168.1.77"
        pbt = bytes([*BATTERY_MAGIC, BATTERY_POWER_MODE_BATTERY, 0x0E, 0x74, 72, 7, 3])
        pfp = bytes([*FPS_MAGIC, 0x00, 0x1E, 0x00, 0x3C])
        with listener.lock:
            listener.data[ip] = {"ts": __import__("time").monotonic()}
            listener.data[ip].update(parse_pbt_packet(pbt))
            listener.data[ip].update(parse_pfp_packet(pfp))
        merged = listener.get(ip)
        self.assertIsNotNone(merged)
        self.assertEqual(merged["battery_mv"], 3700)
        self.assertEqual(merged["fps"], 30)
        listener.stop()

    def test_radius_telemetry_listener_merges_pbt_with_track_status(self):
        # Radius nodes send PBT battery, PTR track names, and PFP packet
        # rates on the same port — a later track update must not wipe the
        # battery fields (the listener merges rather than replaces).
        listener = RadiusTelemetryListener(port=0)
        port = listener._sock.getsockname()[1]
        thread = threading.Thread(target=listener.run, daemon=True)
        thread.start()
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            pbt = bytes([*BATTERY_MAGIC, BATTERY_POWER_MODE_BATTERY, 0x0E, 0x74, 72, 0, 4])
            sender.sendto(pbt, ("127.0.0.1", port))
            deadline = time.monotonic() + 2.0
            entry = None
            while time.monotonic() < deadline:
                entry = listener.get("127.0.0.1")
                if entry and entry.get("battery_mv"):
                    break
                time.sleep(0.02)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.get("battery_mv"), 3700)
            self.assertEqual(entry.get("battery_pct"), 72)

            name = b"hello.wav"
            ptr = b"PTR" + bytes([1, len(name)]) + name
            sender.sendto(ptr, ("127.0.0.1", port))
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                entry = listener.get("127.0.0.1")
                if entry and entry.get("current_track"):
                    break
                time.sleep(0.02)
            self.assertEqual(entry.get("current_track"), "hello.wav")
            self.assertEqual(
                entry.get("battery_mv"), 3700,
                "track status replaced the entry — battery telemetry lost")
        finally:
            sender.close()
            listener.stop()


if __name__ == "__main__":
    unittest.main()
