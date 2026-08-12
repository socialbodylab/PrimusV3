"""Unified shared-backend behavior: radius ops on ControllerState, the
radius-shaped /api/state view, PRS telemetry parsing, and launcher
multi-product evaluation."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import artnet
import central_launcher
import state as state_mod
from state import ControllerState


def _radius_device(ip="192.168.8.50", name="R1", connected=True, **extra):
    dev = {
        "name": name,
        "ip": ip,
        "connected": connected,
        "is_radius": True,
        "transport_error": None,
        "capabilities": {
            "profile": "pvrad1",
            "device_class": "radius",
            "audio": True,
            "ftp": True,
        },
        "hardware_profile": "v1",
        "hardware_label": "V1 Huzzah32",
        "firmware_version": "4.16",
        "ip_mode": "unknown",
        "static_ip": None,
        "gateway": None,
        "subnet": None,
        "current_track": "",
        "playback_state": 0,
    }
    dev.update(extra)
    return dev


def _prs_packet(
    version=1,
    sequence=7,
    uptime=120,
    flags=0x0581,  # wifi + battery valid + sd ready + audio playing
    rssi=-55,
    power_mode=0,
    battery_mv=3900,
    battery_pct=76,
):
    return bytes(
        [0x50, 0x52, 0x53, version]
        + [(sequence >> 8) & 0xFF, sequence & 0xFF]
        + [
            (uptime >> 24) & 0xFF,
            (uptime >> 16) & 0xFF,
            (uptime >> 8) & 0xFF,
            uptime & 0xFF,
        ]
        + [(flags >> 8) & 0xFF, flags & 0xFF]
        + [rssi & 0xFF, power_mode]
        + [(battery_mv >> 8) & 0xFF, battery_mv & 0xFF, battery_pct]
    )


class ControllerRadiusOpsTests(unittest.TestCase):
    def _state(self):
        st = ControllerState.__new__(ControllerState)
        import threading

        st.lock = threading.Lock()
        st.devices = []
        st.artnet_source_ip = None
        st.fps_listener = None

        class _Perf:
            def increment(self, *_args, **_kwargs):
                pass

        st.performance = _Perf()
        return st

    def test_send_audio_command_uses_show_lane(self):
        st = self._state()
        st.devices.append(_radius_device(port_show=6460))
        with patch.object(state_mod, "send_audio_cmd") as send:
            ok = st.send_audio_command(0, "play", filename="a.wav", volume=90)
        self.assertTrue(ok)
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs["dest_port"], 6460)
        self.assertEqual(kwargs["filename"], "a.wav")

    def test_ftp_ops_use_setup_lane(self):
        st = self._state()
        st.devices.append(_radius_device(port_setup=6470))
        with patch.object(state_mod, "ftp_list_dir", return_value=[]) as lister:
            st.ftp_list_dir(0, "/")
        self.assertEqual(lister.call_args.kwargs["dest_port"], 6470)

    def test_fire_audio_cue_skips_primus_and_disconnected(self):
        st = self._state()
        st.devices.append(_radius_device(ip="192.168.8.50", connected=True))
        st.devices.append(_radius_device(ip="192.168.8.51", connected=False))
        st.devices.append(
            {
                "name": "P1",
                "ip": "192.168.8.60",
                "connected": True,
                "is_radius": False,
            }
        )
        cue = {
            "actions": {
                "192.168.8.50": {"cmd": "play", "filename": "a.wav"},
                "192.168.8.51": {"cmd": "play", "filename": "a.wav"},
                "192.168.8.60": {"cmd": "play", "filename": "a.wav"},
            }
        }
        with patch.object(state_mod, "send_audio_cmd") as send:
            results = st.fire_audio_cue(cue)
        self.assertEqual(results["192.168.8.50"]["status"], "sent")
        self.assertEqual(results["192.168.8.51"]["status"], "skipped")
        self.assertNotIn("192.168.8.60", results)
        self.assertEqual(send.call_count, 1)

    def test_radius_has_live_playback_reads_listener(self):
        st = self._state()
        st.devices.append(_radius_device())

        class _Listener:
            def get(self, _ip):
                return {"playback_state": 1, "current_track": "a.wav"}

        st.fps_listener = _Listener()
        self.assertTrue(st.radius_has_live_playback())

        class _Idle:
            def get(self, _ip):
                return {"playback_state": 0}

        st.fps_listener = _Idle()
        self.assertFalse(st.radius_has_live_playback())


class _TelemetryListener:
    """Minimal FPS-listener stand-in keyed by device IP."""

    def __init__(self, telemetry=None):
        self.telemetry = telemetry or {}

    def get_telemetry_status(self, ip):
        rx = self.telemetry.get(ip)
        if rx is None:
            return None, None, False
        return rx, 1.0, True


def _serialization_state(devices, telemetry=None):
    import threading

    st = ControllerState.__new__(ControllerState)
    st.lock = threading.Lock()
    st.devices = devices
    st.artnet_source_ip = None
    st.fps_listener = _TelemetryListener(telemetry)
    st.performance = state_mod.PerformanceStats()
    # Enough playback/look state for get_json to serialize.
    st.fps = 30
    st.active_look = {"name": "Look 1", "outputs": []}
    st.device_groups = []
    st.playback_source = ControllerState.SOURCE_IDLE
    st._override_pixels = None
    st._mixer_preview_device_filter = None
    st._mixer_preview_playing = False
    st._controller_device_ips = None
    return st


class RadiusJsonViewTests(unittest.TestCase):
    def _devices_and_telemetry(self):
        primus_dev = {
            "name": "P1",
            "ip": "192.168.8.60",
            "connected": True,
            "is_radius": False,
            "capabilities": {},
            "outputs": [],
        }
        radius_dev = _radius_device(current_track="song.wav", playback_state=1)
        telemetry = {
            "192.168.8.50": {
                "fps": 0,
                "pkt_rate": 4,
                "battery_pct": 76,
                "current_track": "song.wav",
                "playback_state": 1,
                "sd_ready": True,
            },
        }
        return [primus_dev, radius_dev], telemetry

    def test_get_radius_json_keeps_indices_aligned(self):
        devices, telemetry = self._devices_and_telemetry()
        st = _serialization_state(devices, telemetry)
        payload = st.get_radius_json()
        self.assertEqual(payload["product"], "radius")
        self.assertIn("radius", payload["products"])
        self.assertEqual(len(payload["devices"]), 2)
        self.assertFalse(payload["devices"][0]["is_radius"])
        self.assertFalse(payload["devices"][0]["is_audio"])
        radius_item = payload["devices"][1]
        self.assertTrue(radius_item["is_audio"])
        self.assertEqual(radius_item["current_track"], "song.wav")
        self.assertEqual(radius_item["battery_pct"], 76)
        self.assertEqual(radius_item["pkt_rate"], 4)
        self.assertTrue(radius_item["receiver_online"])
        self.assertTrue(radius_item["sd_ready"])

    def test_radius_view_matches_primus_view_per_device(self):
        # Both product views serialize each device through the same
        # _device_json_unlocked helper, so the fields they share must agree.
        devices, telemetry = self._devices_and_telemetry()
        st = _serialization_state(devices, telemetry)
        full = st.get_json()
        radius = st.get_radius_json()
        self.assertEqual(len(full["devices"]), len(radius["devices"]))
        for full_dev, radius_item in zip(full["devices"], radius["devices"]):
            for key in (
                "name", "ip", "is_radius", "is_audio", "connected",
                "battery_pct", "receiver_online", "hardware_profile",
                "firmware_version", "capabilities",
            ):
                self.assertEqual(radius_item[key], full_dev[key], key)
            self.assertEqual(
                radius_item.get("fps"), full_dev.get("receiver_fps"))
            self.assertEqual(
                radius_item.get("pkt_rate"), full_dev.get("receiver_pkt_rate"))

    def test_radius_view_skips_look_and_output_serialization(self):
        # The whole point of the direct walk: the radius view never builds
        # the active-look pixel payload or per-device output descriptors.
        devices, telemetry = self._devices_and_telemetry()
        st = _serialization_state(devices, telemetry)
        payload = st.get_radius_json()
        self.assertNotIn("look", payload)
        for item in payload["devices"]:
            self.assertNotIn("outputs", item)
            self.assertNotIn("descriptor_config", item)


class PrsPacketTests(unittest.TestCase):
    def test_parse_prs_packet(self):
        parsed = artnet.parse_prs_packet(_prs_packet())
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["sequence"], 7)
        self.assertEqual(parsed["uptime_seconds"], 120)
        self.assertEqual(parsed["rssi_dbm"], -55)
        self.assertEqual(parsed["battery_mv"], 3900)
        self.assertEqual(parsed["battery_pct"], 76)
        self.assertEqual(parsed["battery_power_mode"], "battery")
        self.assertTrue(parsed["wifi_connected"])
        self.assertTrue(parsed["sd_ready"])
        self.assertTrue(parsed["audio_playing"])
        self.assertFalse(parsed["ftp_running"])

    def test_battery_invalid_flag_clears_values(self):
        parsed = artnet.parse_prs_packet(
            _prs_packet(flags=0x0001, power_mode=5, battery_mv=0, battery_pct=255)
        )
        self.assertIsNone(parsed["battery_mv"])
        self.assertIsNone(parsed["battery_pct"])

    def test_rejects_short_or_wrong_version(self):
        self.assertIsNone(artnet.parse_prs_packet(_prs_packet()[:10]))
        self.assertIsNone(artnet.parse_prs_packet(_prs_packet(version=2)))

    def test_primus_listener_merges_prs_with_ptr(self):
        listener = artnet.PrimusTelemetryListener.__new__(
            artnet.PrimusTelemetryListener
        )
        import threading
        import time as time_mod

        listener.lock = threading.Lock()
        listener.data = {}
        listener.monotonic = time_mod.monotonic
        listener._now = time_mod.monotonic
        ip = "192.168.8.50"
        ptr = b"PTR" + bytes([1, 8]) + b"song.wav"
        listener._handle_packet(ptr, ip)
        listener._handle_packet(_prs_packet(), ip)
        merged = listener.get(ip)
        self.assertIsNotNone(merged)
        self.assertEqual(merged["current_track"], "song.wav")
        self.assertEqual(merged["playback_state"], 1)
        self.assertEqual(merged["battery_pct"], 76)
        self.assertTrue(merged["sd_ready"])


class FtpListParseTests(unittest.TestCase):
    def test_legacy_space_padded_unix_format(self):
        line = "-rw-r--r--    1 owner group     220544 Jan  1 00:00 hwtest.wav"
        parsed = artnet._parse_list_line(line)
        self.assertEqual(parsed["name"], "hwtest.wav")
        self.assertFalse(parsed["is_dir"])
        self.assertEqual(parsed["size"], 220544)

    def test_tab_separated_no_group_format(self):
        # Newer SimpleFTPServer builds (observed on hardware 2026-08-12):
        # perms, nlink, owner, size, date, name — tab-separated, no group.
        line = "-rw-rw-r--\t1\tradius\t19902420\tJan 01 00:00\tpairing2.wav"
        parsed = artnet._parse_list_line(line)
        self.assertEqual(parsed["name"], "pairing2.wav")
        self.assertFalse(parsed["is_dir"])
        self.assertEqual(parsed["size"], 19902420)

    def test_tab_separated_directory(self):
        line = "drwxrwsr-x\t2\tradius\t4096\tJan 01 00:00\t.Spotlight-V100"
        parsed = artnet._parse_list_line(line)
        self.assertEqual(parsed["name"], ".Spotlight-V100")
        self.assertTrue(parsed["is_dir"])

    def test_tab_separated_name_with_spaces(self):
        line = "-rw-rw-r--\t1\tradius\t1024\tJan 01 00:00\tmy cue file.wav"
        parsed = artnet._parse_list_line(line)
        self.assertEqual(parsed["name"], "my cue file.wav")
        self.assertEqual(parsed["size"], 1024)

    def test_unparseable_line_dropped(self):
        self.assertIsNone(artnet._parse_list_line("garbage"))


class EvaluateServerProductsTests(unittest.TestCase):
    def _runtime(self, **overrides):
        runtime = {
            "product": "primus",
            "frontends": {"primus": "/primus", "radius": "/radius"},
        }
        runtime.update(overrides)
        return runtime

    def test_products_list_satisfies_radius_need(self):
        runtime = self._runtime(products=["primus", "radius"])
        self.assertIsNone(
            central_launcher.evaluate_server(runtime, need_product="radius")
        )

    def test_scalar_primus_rejects_radius_need(self):
        mismatch = central_launcher.evaluate_server(
            self._runtime(), need_product="radius"
        )
        self.assertEqual(
            mismatch["reason"], central_launcher.MISMATCH_WRONG_PRODUCT
        )

    def test_unknown_product_is_a_mismatch_when_needed(self):
        mismatch = central_launcher.evaluate_server(
            {"frontends": {"primus": "/primus"}}, need_product="radius"
        )
        self.assertEqual(
            mismatch["reason"], central_launcher.MISMATCH_UNKNOWN_PRODUCT
        )

    def test_no_need_still_accepts_anything(self):
        self.assertIsNone(central_launcher.evaluate_server({}))

    def test_registry_records_products(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            registry = os.path.join(tmp, "central_server.json")
            with patch.dict(
                os.environ, {"PRIMUSV3_CENTRAL_REGISTRY": registry}
            ):
                payload = central_launcher.register_central_server(
                    8080, "primus", products=["primus", "radius"]
                )
        self.assertEqual(payload["products"], ["primus", "radius"])


if __name__ == "__main__":
    unittest.main()
