import os
import socket
import struct
import sys
import time
import unittest

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
    pad_osc_string,
    parse_osc_packet,
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

    def test_udp_listener_accepts_port_zero(self):
        cues = FakeCueList()
        state = FakeControllerState()
        service = OscControlServer(cues, state, settings={
            "enabled": True,
            "host": "127.0.0.1",
            "port": 0,
        })
        service.start()
        try:
            deadline = time.monotonic() + 1.0
            status = service.status()
            while not status["running"] and time.monotonic() < deadline:
                time.sleep(0.01)
                status = service.status()
            self.assertTrue(status["running"], status)
            port = status["bound"]["port"]
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(build_osc_message("/primus/cue/go"), ("127.0.0.1", port))
            deadline = time.monotonic() + 1.0
            while cues.go_calls == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(cues.go_calls, 1)
            self.assertEqual(state.source, ControllerState.SOURCE_CONTROLLER)
        finally:
            service.stop()


if __name__ == "__main__":
    unittest.main()
