"""Tests for Primus unified telemetry transport."""

import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from artnet import BATTERY_MAGIC, FPS_MAGIC, TRACK_MAGIC, PrimusTelemetryListener
from primus_protocol import (
    BatteryMode,
    STATUS_FLAG_BATTERY_VALID,
    STATUS_FLAG_OUTPUT_POWER,
    STATUS_FLAG_PRODUCTION,
    STATUS_FLAG_TELEMETRY_CONFIGURED,
    STATUS_FLAG_UNLOCK_WINDOW_OPEN,
    STATUS_FLAG_WIFI_CONNECTED,
    OperatingMode,
    STATUS_PROTOCOL_VERSION,
    UnifiedStatus,
    pack_status,
)


def make_listener():
    listener = PrimusTelemetryListener.__new__(PrimusTelemetryListener)
    listener.lock = threading.Lock()
    listener.data = {}
    listener.TELEMETRY_STALE_SECONDS = 12.0
    listener.TELEMETRY_ONLINE_SECONDS = 3.0
    listener.running = False
    return listener


def make_status_packet(sequence, uptime, rssi_dbm=-50):
    return pack_status(
        UnifiedStatus(
            sequence=sequence,
            uptime_seconds=uptime,
            flags=STATUS_FLAG_WIFI_CONNECTED,
            rendered_fps_x10=300,
            packet_rate_x10=300,
            rssi_dbm=rssi_dbm,
            firmware_major=3,
            firmware_minor=14,
            firmware_patch=0,
            operating_mode=OperatingMode.PROTOTYPE,
            battery_mode=BatteryMode.UNAVAILABLE,
            battery_mv=0,
            battery_pct=255,
            unlock_remaining_seconds=0,
        )
    )


class PrimusUnifiedTelemetryTests(unittest.TestCase):
    def send_status(self, listener, now, ip, sequence, uptime, rssi_dbm=-50):
        listener._handle_packet(
            make_status_packet(sequence, uptime, rssi_dbm=rssi_dbm),
            ip,
        )
        now["value"] += 1.0

    def test_unified_status_maps_to_state_friendly_fields(self):
        listener = make_listener()
        now = {"value": 100.0}
        listener.monotonic = lambda: now["value"]
        packet = pack_status(
            UnifiedStatus(
                sequence=0x1234,
                uptime_seconds=123,
                flags=(
                    STATUS_FLAG_WIFI_CONNECTED
                    | STATUS_FLAG_OUTPUT_POWER
                    | STATUS_FLAG_TELEMETRY_CONFIGURED
                    | STATUS_FLAG_PRODUCTION
                    | STATUS_FLAG_UNLOCK_WINDOW_OPEN
                    | STATUS_FLAG_BATTERY_VALID
                ),
                rendered_fps_x10=299,
                packet_rate_x10=301,
                rssi_dbm=-62,
                firmware_major=3,
                firmware_minor=14,
                firmware_patch=1,
                operating_mode=OperatingMode.PRODUCTION,
                battery_mode=BatteryMode.BATTERY,
                battery_mv=4875,
                battery_pct=76,
                unlock_remaining_seconds=42,
            )
        )
        listener._handle_packet(packet, "192.168.1.50")

        fresh, age, online = listener.get_telemetry_status("192.168.1.50")
        self.assertEqual(age, 0.0)
        self.assertTrue(online)
        self.assertEqual(fresh["protocol_version"], STATUS_PROTOCOL_VERSION)
        self.assertEqual(fresh["sequence"], 0x1234)
        self.assertEqual(fresh["uptime_seconds"], 123)
        self.assertEqual(fresh["fps"], 29.9)
        self.assertEqual(fresh["pkt_rate"], 30.1)
        self.assertEqual(fresh["rssi_dbm"], -62)
        self.assertEqual(fresh["firmware_version"], "3.14.1")
        self.assertEqual(fresh["live_firmware_version"], "3.14.1")
        self.assertEqual(fresh["operating_mode"], "production")
        self.assertTrue(fresh["management_locked"])
        self.assertEqual(fresh["battery_power_mode"], "battery")
        self.assertTrue(fresh["battery_available"])
        self.assertEqual(fresh["battery_mv"], 4875)
        self.assertEqual(fresh["battery_pct"], 76)
        self.assertTrue(fresh["wifi_connected"])
        self.assertTrue(fresh["output_power_enabled"])
        self.assertTrue(fresh["telemetry_configured"])
        self.assertTrue(fresh["unlock_window_open"])
        self.assertEqual(fresh["unlock_remaining_seconds"], 42)
        self.assertTrue(fresh["status_flag_battery_valid"])
        self.assertTrue(fresh["heartbeat_fresh"])

    def test_legacy_packet_timestamps_are_independent(self):
        listener = make_listener()
        now = {"value": 10.0}
        listener.monotonic = lambda: now["value"]
        listener._handle_packet(
            bytes([*BATTERY_MAGIC, 0, 0x0E, 0x74, 72, 7, 3]),
            "192.168.1.51",
        )
        now["value"] = 20.0
        listener._handle_packet(
            bytes([*FPS_MAGIC, 0x00, 0x1E, 0x00, 0x3C]),
            "192.168.1.51",
        )
        now["value"] = 31.0

        merged = listener.get("192.168.1.51")
        self.assertIsNotNone(merged)
        self.assertEqual(merged["fps"], 30)
        self.assertEqual(merged["pkt_rate"], 60)
        self.assertNotIn("battery_mv", merged)
        self.assertNotIn("battery_pct", merged)

    def test_duplicate_status_packet_keeps_existing_public_fields(self):
        listener = make_listener()
        now = {"value": 1.0}
        listener.monotonic = lambda: now["value"]
        ip = "192.168.1.52"

        self.send_status(listener, now, ip, 10, 100, rssi_dbm=-50)
        self.send_status(listener, now, ip, 10, 100, rssi_dbm=-50)

        merged = listener.get(ip)
        self.assertEqual(merged["sequence"], 10)
        self.assertEqual(merged["uptime_seconds"], 100)
        self.assertEqual(merged["rssi_dbm"], -50)
        self.assertEqual(merged["telemetry_duplicate_packets"], 1)
        self.assertEqual(merged.get("telemetry_packets_lost", 0), 0)
        self.assertEqual(merged.get("telemetry_reboot_count", 0), 0)
        self.assertEqual(merged["telemetry_status_packets_accepted"], 1)

    def test_lower_uptime_reordered_packet_is_ignored_without_reboot(self):
        listener = make_listener()
        now = {"value": 1.0}
        listener.monotonic = lambda: now["value"]
        ip = "192.168.1.53"

        self.send_status(listener, now, ip, 50, 200, rssi_dbm=-50)
        self.send_status(listener, now, ip, 49, 20, rssi_dbm=-80)
        self.send_status(listener, now, ip, 51, 201, rssi_dbm=-55)

        merged = listener.get(ip)
        self.assertEqual(merged["sequence"], 51)
        self.assertEqual(merged["uptime_seconds"], 201)
        self.assertEqual(merged["rssi_dbm"], -55)
        self.assertEqual(merged["telemetry_out_of_order_packets"], 1)
        self.assertEqual(merged.get("telemetry_packets_lost", 0), 0)
        self.assertEqual(merged.get("telemetry_reboot_count", 0), 0)
        self.assertEqual(merged["telemetry_status_packets_accepted"], 2)

    def test_forward_sequence_wrap_tracks_loss_without_reboot(self):
        listener = make_listener()
        now = {"value": 1.0}
        listener.monotonic = lambda: now["value"]
        ip = "192.168.1.54"

        self.send_status(listener, now, ip, 65534, 100)
        self.send_status(listener, now, ip, 1, 103)

        merged = listener.get(ip)
        self.assertEqual(merged["sequence"], 1)
        self.assertEqual(merged["uptime_seconds"], 103)
        self.assertEqual(merged["telemetry_sequence_wraps"], 1)
        self.assertEqual(merged["telemetry_packets_lost"], 2)
        self.assertEqual(merged.get("telemetry_reboot_count", 0), 0)
        self.assertEqual(merged["telemetry_status_packets_accepted"], 2)
        self.assertAlmostEqual(merged["telemetry_packet_loss_rate"], 0.5)

    def test_credible_reboot_resets_sequence_baseline(self):
        listener = make_listener()
        now = {"value": 1.0}
        listener.monotonic = lambda: now["value"]
        ip = "192.168.1.55"

        self.send_status(listener, now, ip, 65000, 500, rssi_dbm=-50)
        self.send_status(listener, now, ip, 4, 2, rssi_dbm=-60)
        self.send_status(listener, now, ip, 7, 5, rssi_dbm=-70)

        merged = listener.get(ip)
        self.assertEqual(merged["sequence"], 7)
        self.assertEqual(merged["uptime_seconds"], 5)
        self.assertEqual(merged["rssi_dbm"], -70)
        self.assertEqual(merged["telemetry_reboot_count"], 1)
        self.assertEqual(merged["telemetry_uptime_reset_count"], 1)
        self.assertEqual(merged["telemetry_packets_lost"], 2)
        self.assertEqual(merged.get("telemetry_sequence_wraps", 0), 0)
        self.assertEqual(merged["telemetry_status_packets_accepted"], 3)
        self.assertAlmostEqual(merged["telemetry_packet_loss_rate"], 0.4)

    def test_early_reboot_requires_and_accepts_confirming_packet(self):
        listener = make_listener()
        now = {"value": 1.0}
        listener.monotonic = lambda: now["value"]
        ip = "192.168.1.58"

        self.send_status(listener, now, ip, 100, 200, rssi_dbm=-50)
        self.send_status(listener, now, ip, 10, 5, rssi_dbm=-60)

        unconfirmed = listener.get(ip)
        self.assertEqual(unconfirmed["sequence"], 100)
        self.assertEqual(unconfirmed["uptime_seconds"], 200)
        self.assertEqual(unconfirmed.get("telemetry_reboot_count", 0), 0)

        self.send_status(listener, now, ip, 11, 6, rssi_dbm=-70)

        merged = listener.get(ip)
        self.assertEqual(merged["sequence"], 11)
        self.assertEqual(merged["uptime_seconds"], 6)
        self.assertEqual(merged["rssi_dbm"], -70)
        self.assertEqual(merged["telemetry_reboot_count"], 1)
        self.assertEqual(merged["telemetry_uptime_reset_count"], 1)
        self.assertEqual(merged.get("telemetry_out_of_order_packets", 0), 0)
        self.assertEqual(merged["telemetry_status_packets_accepted"], 3)

    def test_delayed_previous_boot_packet_is_rejected_after_reboot_confirmation(self):
        listener = make_listener()
        now = {"value": 1.0}
        listener.monotonic = lambda: now["value"]
        ip = "192.168.1.59"

        self.send_status(listener, now, ip, 100, 200, rssi_dbm=-50)
        self.send_status(listener, now, ip, 10, 5, rssi_dbm=-60)
        self.send_status(listener, now, ip, 11, 6, rssi_dbm=-70)
        self.send_status(listener, now, ip, 101, 201, rssi_dbm=-90)
        self.send_status(listener, now, ip, 12, 7, rssi_dbm=-71)
        self.send_status(listener, now, ip, 13, 8, rssi_dbm=-72)

        merged = listener.get(ip)
        self.assertEqual(merged["sequence"], 13)
        self.assertEqual(merged["uptime_seconds"], 8)
        self.assertEqual(merged["rssi_dbm"], -72)
        self.assertEqual(merged["telemetry_reboot_count"], 1)
        self.assertEqual(merged["telemetry_uptime_reset_count"], 1)
        self.assertEqual(merged["telemetry_out_of_order_packets"], 1)
        self.assertEqual(merged["telemetry_status_packets_accepted"], 5)

    def test_reboot_guard_does_not_reject_current_generation_uptime_progress(self):
        listener = make_listener()
        now = {"value": 1.0}
        listener.monotonic = lambda: now["value"]
        ip = "192.168.1.60"

        self.send_status(listener, now, ip, 100, 60, rssi_dbm=-50)
        self.send_status(listener, now, ip, 10, 1, rssi_dbm=-60)
        self.send_status(listener, now, ip, 11, 2, rssi_dbm=-70)
        self.send_status(listener, now, ip, 40, 31, rssi_dbm=-75)

        merged = listener.get(ip)
        self.assertEqual(merged["sequence"], 40)
        self.assertEqual(merged["uptime_seconds"], 31)
        self.assertEqual(merged["rssi_dbm"], -75)
        self.assertEqual(merged["telemetry_reboot_count"], 1)
        self.assertEqual(merged.get("telemetry_out_of_order_packets", 0), 0)

    def test_ambiguous_uptime_reset_is_ignored(self):
        listener = make_listener()
        now = {"value": 1.0}
        listener.monotonic = lambda: now["value"]
        ip = "192.168.1.56"

        self.send_status(listener, now, ip, 100, 200, rssi_dbm=-50)
        self.send_status(listener, now, ip, 103, 2, rssi_dbm=-80)

        merged = listener.get(ip)
        self.assertEqual(merged["sequence"], 100)
        self.assertEqual(merged["uptime_seconds"], 200)
        self.assertEqual(merged["rssi_dbm"], -50)
        self.assertEqual(merged.get("telemetry_packets_lost", 0), 0)
        self.assertEqual(merged.get("telemetry_reboot_count", 0), 0)
        self.assertEqual(merged["telemetry_status_packets_accepted"], 1)

    def test_ptr_is_preserved_and_malformed_status_does_not_refresh(self):
        listener = make_listener()
        now = {"value": 50.0}
        listener.monotonic = lambda: now["value"]
        ip = "192.168.1.57"
        listener._handle_packet(
            pack_status(
                UnifiedStatus(
                    sequence=1,
                    uptime_seconds=10,
                    flags=STATUS_FLAG_WIFI_CONNECTED,
                    rendered_fps_x10=300,
                    packet_rate_x10=300,
                    rssi_dbm=-55,
                    firmware_major=3,
                    firmware_minor=14,
                    firmware_patch=0,
                    operating_mode=OperatingMode.PROTOTYPE,
                    battery_mode=BatteryMode.UNAVAILABLE,
                    battery_mv=0,
                    battery_pct=255,
                    unlock_remaining_seconds=0,
                )
            ),
            ip,
        )
        listener._handle_packet(bytes([*TRACK_MAGIC, 2, 4]) + b"Song", ip)
        valid_ts = listener.data[ip]["ts"]
        now["value"] = 55.0
        listener._handle_packet(b"PST\x02" + b"\x00" * 24, ip)

        self.assertEqual(listener.data[ip]["telemetry_malformed_packets"], 1)
        self.assertEqual(listener.data[ip]["ts"], valid_ts)
        fresh, age, online = listener.get_telemetry_status(ip)
        self.assertEqual(fresh["playback_state"], 2)
        self.assertEqual(fresh["current_track"], "Song")
        self.assertEqual(age, 5.0)
        self.assertFalse(online)


if __name__ == "__main__":
    unittest.main()
