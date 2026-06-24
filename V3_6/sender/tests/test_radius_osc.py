import os
import sys
import unittest

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from osc_control import (
    OscControlServer,
    OscMessage,
    build_osc_message,
    command_from_message,
    execute_radius_command,
    OscCommandError,
)


class HelloCommandParseTests(unittest.TestCase):

    def test_hello_address_parsed(self):
        cmd = command_from_message(OscMessage("/hello"))
        self.assertEqual(cmd["action"], "hello")

    def test_radius_hello_address_parsed(self):
        cmd = command_from_message(OscMessage("/radius/hello"))
        self.assertEqual(cmd["action"], "hello")

    def test_primus_hello_address_parsed(self):
        cmd = command_from_message(OscMessage("/primus/hello"))
        self.assertEqual(cmd["action"], "hello")


class RadiusExecuteCommandTests(unittest.TestCase):

    def _dispatch(self):
        calls = []
        def fn(action, number=None):
            calls.append((action, number))
            return {"ok": True}
        return fn, calls

    def test_goto_dispatches_fire_with_number(self):
        fn, calls = self._dispatch()
        result = execute_radius_command({"action": "goto", "number": 3}, fn)
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "audio_fire")
        self.assertEqual(result["number"], 3)
        self.assertEqual(calls, [("fire", 3)])

    def test_goto_cue_1(self):
        fn, calls = self._dispatch()
        execute_radius_command({"action": "goto", "number": 1}, fn)
        self.assertEqual(calls, [("fire", 1)])

    def test_goto_without_number_returns_error(self):
        fn, calls = self._dispatch()
        result = execute_radius_command({"action": "goto"}, fn)
        self.assertFalse(result["ok"])
        self.assertEqual(calls, [])

    def test_stop_dispatches_stop(self):
        fn, calls = self._dispatch()
        result = execute_radius_command({"action": "stop"}, fn)
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "audio_stop")
        self.assertEqual(calls[0][0], "stop")

    def test_hello_dispatches_hello(self):
        fn, calls = self._dispatch()
        result = execute_radius_command({"action": "hello"}, fn)
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "audio_hello")
        self.assertEqual(calls[0][0], "hello")

    def test_unknown_action_returns_error(self):
        fn, calls = self._dispatch()
        result = execute_radius_command({"action": "blackout"}, fn)
        self.assertFalse(result["ok"])
        self.assertEqual(calls, [])

    def test_none_action_returns_error(self):
        fn, calls = self._dispatch()
        result = execute_radius_command({}, fn)
        self.assertFalse(result["ok"])


class OscServerRadiusModeTests(unittest.TestCase):
    """OscControlServer routes to audio dispatch when set_audio_dispatch is called."""

    def _server_with_dispatch(self):
        calls = []
        server = OscControlServer(cue_list=None, controller_state=None)
        server.set_audio_dispatch(lambda action, number=None: calls.append((action, number)))
        return server, calls

    def test_cue_address_calls_fire(self):
        server, calls = self._server_with_dispatch()
        server._handle_packet(build_osc_message("/cue/2"), ("127.0.0.1", 1234))
        self.assertEqual(calls, [("fire", 2)])

    def test_cue_5_calls_fire_5(self):
        server, calls = self._server_with_dispatch()
        server._handle_packet(build_osc_message("/cue/5"), ("127.0.0.1", 1234))
        self.assertEqual(calls, [("fire", 5)])

    def test_stop_address_calls_stop(self):
        server, calls = self._server_with_dispatch()
        server._handle_packet(build_osc_message("/stop"), ("127.0.0.1", 1234))
        self.assertEqual(calls[0][0], "stop")

    def test_hello_address_calls_hello(self):
        server, calls = self._server_with_dispatch()
        server._handle_packet(build_osc_message("/hello"), ("127.0.0.1", 1234))
        self.assertEqual(calls[0][0], "hello")

    def test_radius_hello_calls_hello(self):
        server, calls = self._server_with_dispatch()
        server._handle_packet(build_osc_message("/radius/hello"), ("127.0.0.1", 1234))
        self.assertEqual(calls[0][0], "hello")

    def test_dispatch_not_called_when_not_set(self):
        """Without set_audio_dispatch, the server uses LED cue routing (no dispatch call)."""
        called = []
        server = OscControlServer(cue_list=None, controller_state=None)
        # Do NOT set audio dispatch — should attempt LED routing, which will error
        # (no cue_list), but dispatch must NOT be called
        server.set_audio_dispatch(lambda a, n=None: called.append(a))
        server.set_audio_dispatch(None)  # clear it
        # Should not crash; dispatch was cleared
        server._handle_packet(build_osc_message("/cue/1"), ("127.0.0.1", 1234))
        self.assertEqual(called, [])

    def test_history_records_audio_fire(self):
        server, _ = self._server_with_dispatch()
        server._handle_packet(build_osc_message("/cue/3"), ("127.0.0.1", 1234))
        status = server.status()
        history = status["history"]
        self.assertTrue(any(h.get("action") == "audio_fire" for h in history))

    def test_history_records_audio_stop(self):
        server, _ = self._server_with_dispatch()
        server._handle_packet(build_osc_message("/stop"), ("127.0.0.1", 1234))
        status = server.status()
        self.assertTrue(any(h.get("action") == "audio_stop" for h in status["history"]))

    def test_bundle_with_cue_fires_cue(self):
        """OSC bundle containing /cue/4 still dispatches."""
        import struct
        from osc_control import pad_osc_string
        msg_bytes = build_osc_message("/cue/4")
        bundle = (
            pad_osc_string("#bundle")
            + struct.pack(">Q", 1)  # timetag = immediate
            + struct.pack(">i", len(msg_bytes))
            + msg_bytes
        )
        server, calls = self._server_with_dispatch()
        server._handle_packet(bundle, ("127.0.0.1", 1234))
        self.assertEqual(calls, [("fire", 4)])


class OscServerLedModeUnaffectedTests(unittest.TestCase):
    """LED mode routing is unchanged when no audio dispatch is set."""

    def test_set_audio_dispatch_none_leaves_led_mode(self):
        server = OscControlServer(cue_list=None, controller_state=None)
        server.set_audio_dispatch(None)
        self.assertIsNone(server._audio_dispatch)

    def test_audio_dispatch_initially_none(self):
        server = OscControlServer(cue_list=None, controller_state=None)
        self.assertIsNone(server._audio_dispatch)


if __name__ == "__main__":
    unittest.main()
