import os
import socket
import struct
import sys
import time
import unittest
from unittest import mock

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from controller import cue_slug
from osc_control import (
    OscControlServer,
    OscParseError,
    build_osc_message,
    command_from_message,
    execute_message,
    load_settings,
    normalize_bind_host,
    normalize_settings,
    OSC_LISTEN_HOST,
    public_settings,
    _is_loopback_host,
    pad_osc_string,
    parse_osc_packet,
    save_settings,
)
from state import ControllerState


class FakeCueList:
    def __init__(self):
        self.cues = [
            {"number": 1, "name": "Opening Look"},
            {"number": 2, "name": "Finale"},
        ]
        self.go_calls = 0
        self.goto_calls = []
        self.name_calls = []
        self.stopped = False
        self.blackout_fade = None

    def go(self, device_groups=None):
        self.go_calls += 1
        return self.cues[0]

    def go_to_cue(self, number, device_groups=None):
        self.goto_calls.append(number)
        return next((cue for cue in self.cues if cue["number"] == number), None)

    def go_to_cue_name(self, name, device_groups=None):
        self.name_calls.append(name)
        target = cue_slug(name)
        return next((cue for cue in self.cues if cue_slug(cue["name"]) == target), None)

    def find_cue_by_external_name(self, name):
        cue = self.go_to_cue_name(name)
        if cue:
            return {"cue": cue, "index": self.cues.index(cue), "error": ""}
        return {"cue": None, "index": -1, "error": "cue not found"}

    def stop(self):
        self.stopped = True

    def blackout(self, fade_time=0.0):
        self.blackout_fade = fade_time

    def external_triggers(self):
        return [
            {"number": cue["number"], "name": cue["name"], "slug": cue_slug(cue["name"])}
            for cue in self.cues
        ]


class FakeControllerState:
    def __init__(self):
        self.source = None

    def get_device_groups(self):
        return {}

    def set_playback_source(self, source):
        self.source = source


class OscSettingsTests(unittest.TestCase):
    def test_default_settings_are_enabled_with_default_port(self):
        settings = public_settings(None)
        self.assertTrue(settings["enabled"])
        self.assertEqual(settings["port"], 53001)
        self.assertNotIn("host", settings)

    def test_normalize_bind_host_is_fixed(self):
        self.assertEqual(normalize_bind_host(""), OSC_LISTEN_HOST)
        self.assertEqual(normalize_bind_host("127.0.0.1"), OSC_LISTEN_HOST)
        self.assertEqual(normalize_bind_host("192.168.1.50"), OSC_LISTEN_HOST)

    def test_invalid_port_defaults_to_53001(self):
        settings = normalize_settings({"port": 0})
        self.assertEqual(settings["port"], 53001)

    def test_legacy_saved_host_is_ignored(self):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({
                    "osc_control": {
                        "enabled": True,
                        "host": "192.168.1.50",
                        "port": 53001,
                    }
                }, handle)
            with mock.patch("osc_control._state_file", return_value=path):
                settings = public_settings(load_settings())
            self.assertNotIn("host", settings)
            self.assertEqual(settings["port"], 53001)

    def test_status_uses_cached_listen_targets(self):
        service = OscControlServer(FakeCueList(), FakeControllerState(), settings={
            "enabled": True,
            "port": 53001,
        })
        with service._lock:
            service._running = True
            service._bound = {"host": "0.0.0.0", "port": 53001}
            service._listen_targets_cache = [{
                "ip": "192.168.1.50",
                "label": "Wi-Fi",
                "type": "wifi",
            }]
            service._listen_addresses_cache = ["192.168.1.50:53001"]

        with mock.patch("osc_control._listen_targets", side_effect=AssertionError("live network probe")):
            status = service.status()

        self.assertEqual(status["listen_targets"][0]["ip"], "192.168.1.50")
        self.assertEqual(status["listen_addresses"], ["192.168.1.50:53001"])

    def test_status_returns_stale_snapshot_when_lock_is_busy(self):
        service = OscControlServer(FakeCueList(), FakeControllerState(), settings={
            "enabled": True,
            "port": 53001,
        })
        service._last_status_snapshot = {
            "settings": {"enabled": True, "port": 53001},
            "enabled": True,
            "running": True,
            "last_error": "",
            "bound": {"host": "0.0.0.0", "port": 53001},
            "bind_sockets": [],
            "packets_received": 7,
            "packets_local": 4,
            "packets_remote": 3,
            "listen_targets": [],
            "listen_addresses": [],
            "network_log": [],
            "history": [],
            "examples": [],
            "cue_triggers": [],
        }
        service._lock.acquire()
        try:
            status = service.status()
        finally:
            service._lock.release()

        self.assertTrue(status["stale"])
        self.assertEqual(status["packets_received"], 7)


class OscParserTests(unittest.TestCase):
    def test_parses_int_float_and_string_args(self):
        packet = build_osc_message("/primus/cue/goto", 2, 1.5, "Finale")

        messages = parse_osc_packet(packet, remote="127.0.0.1:9000")

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].address, "/primus/cue/goto")
        self.assertEqual(messages[0].args[0], 2)
        self.assertAlmostEqual(messages[0].args[1], 1.5, places=5)
        self.assertEqual(messages[0].args[2], "Finale")
        self.assertEqual(messages[0].remote, "127.0.0.1:9000")

    def test_rejects_malformed_packet(self):
        with self.assertRaises(OscParseError):
            parse_osc_packet(b"/unterminated")

    def test_parses_bundle_elements_in_order(self):
        first = build_osc_message("/primus/cue/goto", 1)
        second = build_osc_message("/primus/cue/name", "Finale")
        packet = (
            pad_osc_string("#bundle")
            + b"\x00" * 8
            + struct.pack(">i", len(first)) + first
            + struct.pack(">i", len(second)) + second
        )

        messages = parse_osc_packet(packet)

        self.assertEqual([message.address for message in messages], [
            "/primus/cue/goto",
            "/primus/cue/name",
        ])


class OscCommandTests(unittest.TestCase):
    def _free_udp_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def test_normalizes_primus_and_qlab_style_addresses(self):
        self.assertEqual(command_from_message(parse_osc_packet(build_osc_message("/primus/cue/go"))[0]), {"action": "go"})
        self.assertEqual(command_from_message(parse_osc_packet(build_osc_message("/cue/goto", 2))[0]), {"action": "goto", "number": 2})
        self.assertEqual(command_from_message(parse_osc_packet(build_osc_message("/cue/name", "Finale"))[0]), {"action": "name", "name": "Finale"})
        self.assertEqual(command_from_message(parse_osc_packet(build_osc_message("/cue/2/start"))[0]), {"action": "goto", "number": 2})
        self.assertEqual(command_from_message(parse_osc_packet(build_osc_message("/cue/opening-look/start"))[0]), {"action": "name", "name": "opening-look"})

    def test_routes_go_goto_name_stop_and_blackout(self):
        cues = FakeCueList()
        state = FakeControllerState()

        execute_message(parse_osc_packet(build_osc_message("/primus/cue/go"))[0], cues, state)
        execute_message(parse_osc_packet(build_osc_message("/primus/cue/goto", 2))[0], cues, state)
        execute_message(parse_osc_packet(build_osc_message("/cue/opening-look/start"))[0], cues, state)
        execute_message(parse_osc_packet(build_osc_message("/primus/blackout", 0.75))[0], cues, state)
        execute_message(parse_osc_packet(build_osc_message("/stop"))[0], cues, state)

        self.assertEqual(cues.go_calls, 1)
        self.assertEqual(cues.goto_calls, [2])
        self.assertEqual(cues.name_calls[0], "opening-look")
        self.assertAlmostEqual(cues.blackout_fade, 0.75, places=5)
        self.assertTrue(cues.stopped)
        self.assertEqual(state.source, ControllerState.SOURCE_IDLE)

    def test_udp_listener_accepts_ephemeral_port(self):
        cues = FakeCueList()
        state = FakeControllerState()
        port = self._free_udp_port()
        service = OscControlServer(cues, state, settings={
            "enabled": True,
            "port": port,
        })
        with mock.patch("osc_control._listen_targets", return_value=[]):
            service.start()
            try:
                deadline = time.monotonic() + 3.0
                status = service.status()
                while not status["running"] and time.monotonic() < deadline:
                    time.sleep(0.01)
                    status = service.status()
                self.assertTrue(status["running"], status)
                port = status["bound"]["port"]
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.sendto(build_osc_message("/primus/cue/go"), ("127.0.0.1", port))
                deadline = time.monotonic() + 3.0
                while cues.go_calls == 0 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(cues.go_calls, 1)
                self.assertEqual(state.source, ControllerState.SOURCE_CONTROLLER)
            finally:
                service.stop()

    def test_udp_listener_on_all_interfaces_accepts_localhost(self):
        cues = FakeCueList()
        state = FakeControllerState()
        port = self._free_udp_port()
        service = OscControlServer(cues, state, settings={
            "enabled": True,
            "port": port,
        })
        with mock.patch("osc_control._listen_targets", return_value=[]):
            service.start()
            try:
                deadline = time.monotonic() + 3.0
                status = service.status()
                while not status["running"] and time.monotonic() < deadline:
                    time.sleep(0.01)
                    status = service.status()
                self.assertTrue(status["running"], status)
                self.assertGreaterEqual(len(status["bind_sockets"]), 1)
                port = status["bound"]["port"]
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.sendto(build_osc_message("/primus/cue/go"), ("127.0.0.1", port))
                deadline = time.monotonic() + 3.0
                while cues.go_calls == 0 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(cues.go_calls, 1)
                status = service.status()
                self.assertEqual(status["packets_local"], 1)
                self.assertEqual(status["packets_remote"], 0)
            finally:
                service.stop()

    def test_udp_listener_counts_lan_packets_separately(self):
        cues = FakeCueList()
        state = FakeControllerState()
        port = self._free_udp_port()
        service = OscControlServer(cues, state, settings={
            "enabled": True,
            "port": port,
        })
        with mock.patch("osc_control._listen_targets", return_value=[]):
            service.start()
            try:
                deadline = time.monotonic() + 3.0
                status = service.status()
                while not status["running"] and time.monotonic() < deadline:
                    time.sleep(0.01)
                    status = service.status()
                port = status["bound"]["port"]
                local_ip = None
                probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    probe.connect(("8.8.8.8", 80))
                    local_ip = probe.getsockname()[0]
                except OSError:
                    pass
                finally:
                    probe.close()
                if not local_ip or _is_loopback_host(local_ip):
                    self.skipTest("no routable local IPv4 available for LAN packet test")
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.sendto(build_osc_message("/primus/cue/go"), (local_ip, port))
                deadline = time.monotonic() + 3.0
                while cues.go_calls == 0 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(cues.go_calls, 1)
                status = service.status()
                self.assertEqual(status["packets_remote"], 1)
                self.assertEqual(status["packets_local"], 0)
                self.assertTrue(any(row.get("message") == "packet received" for row in status["network_log"]))
                self.assertTrue(status["history"][0]["message"].startswith("/primus/cue/go"))
            finally:
                service.stop()


if __name__ == "__main__":
    unittest.main()
