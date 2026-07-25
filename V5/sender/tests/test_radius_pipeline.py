"""Sender-side tests for the Radius forward-port pipeline:
0x8302 audio-status telemetry parsing, port-6456 routing, OSC test-fire,
cue-map derivation, and the cue-delay wire format.
"""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import artnet
import audio_cues


def _capture_send():
    sent = {}

    def fake(ip, packet, source_ip=None, port=artnet.ARTNET_PORT):
        sent["ip"] = ip
        sent["packet"] = bytes(packet)
        sent["port"] = port

    return sent, fake


class AudioStatusTelemetry(unittest.TestCase):
    def test_parse_0x8302_full_64_char_name(self):
        buf = bytearray(78)
        buf[0:8] = artnet.ARTNET_HEADER
        buf[8:10] = struct.pack("<H", artnet.ARTNET_OPCODE_AUDIO_STATUS)
        buf[12] = 1  # playing
        name = ("x" * 60) + ".wav"
        buf[13:13 + len(name)] = name.encode()
        self.assertEqual(
            artnet.parse_audio_status_packet(bytes(buf)),
            {"playback_state": 1, "current_track": name})

    def test_parse_rejects_wrong_opcode(self):
        buf = bytearray(78)
        buf[0:8] = artnet.ARTNET_HEADER
        buf[8:10] = struct.pack("<H", artnet.ARTNET_OPCODE_AUDIO_CMD)
        self.assertIsNone(artnet.parse_audio_status_packet(bytes(buf)))

    def test_parse_track_ptr_fallback(self):
        name = "clip.wav"
        buf = b"PTR" + bytes([2, len(name)]) + name.encode()
        self.assertEqual(
            artnet.parse_track_packet(buf),
            {"playback_state": 2, "current_track": name})


class PrimusListenerAudioStatus(unittest.TestCase):
    """DeviceManager's primus-product listener must ingest 0x8302 so Radius
    now-playing works after the firmware PTR heartbeat was removed."""

    def _listener(self):
        import threading
        lst = artnet.PrimusTelemetryListener.__new__(artnet.PrimusTelemetryListener)
        lst.lock = threading.Lock()
        lst.data = {}
        lst._now = lambda: 1000.0
        return lst

    def _status_packet(self, state, name):
        buf = bytearray(78)
        buf[0:8] = artnet.ARTNET_HEADER
        buf[8:10] = struct.pack("<H", artnet.ARTNET_OPCODE_AUDIO_STATUS)
        buf[12] = state
        buf[13:13 + len(name)] = name.encode()
        return bytes(buf)

    def test_0x8302_populates_now_playing(self):
        lst = self._listener()
        lst._handle_packet(self._status_packet(1, "show1.wav"), "10.0.0.7")
        pub = lst.get("10.0.0.7")
        self.assertEqual(pub["current_track"], "show1.wav")
        self.assertEqual(pub["playback_state"], 1)

    def test_ptr_still_ingested_as_fallback(self):
        lst = self._listener()
        name = "clip.wav"
        lst._handle_packet(b"PTR" + bytes([2, len(name)]) + name.encode(), "10.0.0.8")
        pub = lst.get("10.0.0.8")
        self.assertEqual(pub["current_track"], name)
        self.assertEqual(pub["playback_state"], 2)


class Port6456Routing(unittest.TestCase):
    def setUp(self):
        self._orig = artnet._send_udp_packet
        self.sent, fake = _capture_send()
        artnet._send_udp_packet = fake

    def tearDown(self):
        artnet._send_udp_packet = self._orig

    def test_audio_and_ftp_go_to_radius_port(self):
        artnet.send_audio_cmd("1.2.3.4", 1, filename="a.wav")
        self.assertEqual(self.sent["port"], artnet.RADIUS_ARTNET_PORT)
        artnet.send_ftp_cmd("1.2.3.4", True)
        self.assertEqual(self.sent["port"], artnet.RADIUS_ARTNET_PORT)

    def test_osc_cue_uses_osc_port_and_pads(self):
        artnet.send_osc_cue("1.2.3.4", 12)
        self.assertEqual(self.sent["port"], artnet.RADIUS_OSC_PORT)
        self.assertTrue(self.sent["packet"].startswith(b"/cue/12\x00"))
        self.assertEqual(len(self.sent["packet"]) % 4, 0)

    def test_device_mgmt_defaults_6454_radius_passes_6456(self):
        artnet.send_art_address("1.2.3.4", "Primus")
        self.assertEqual(self.sent["port"], artnet.ARTNET_PORT)
        artnet.send_art_address("1.2.3.4", "Radius", port=artnet.RADIUS_ARTNET_PORT)
        self.assertEqual(self.sent["port"], artnet.RADIUS_ARTNET_PORT)


class CueDelayWireFormat(unittest.TestCase):
    def setUp(self):
        self._orig = artnet._send_udp_packet
        self.sent, fake = _capture_send()
        artnet._send_udp_packet = fake

    def tearDown(self):
        artnet._send_udp_packet = self._orig

    def _trailing_u16s(self):
        pkt = self.sent["packet"]
        nul = pkt.index(0, 14)
        return struct.unpack("<HH", pkt[nul + 1:nul + 5])

    def test_delay_appends_duration_then_delay(self):
        artnet.send_audio_cmd("1.2.3.4", 1, filename="a.wav", duration=30, delay_ms=1500)
        self.assertEqual(self._trailing_u16s(), (30, 1500))

    def test_delay_without_duration_writes_zero_duration(self):
        artnet.send_audio_cmd("1.2.3.4", 1, filename="a.wav", delay_ms=250)
        self.assertEqual(self._trailing_u16s(), (0, 250))

    def test_filename_up_to_64_chars(self):
        name = ("y" * 60) + ".wav"
        artnet.send_audio_cmd("1.2.3.4", 1, filename=name)
        pkt = self.sent["packet"]
        nul = pkt.index(0, 14)
        self.assertEqual(pkt[14:nul].decode(), name)


class DeviceCueMapDerivation(unittest.TestCase):
    def test_derive_maps_delay_and_excludes(self):
        cues = [
            {"number": 1, "actions": {"10.0.0.5": {"cmd": "play", "filename": "a.wav", "volume": 80, "delay_ms": 500}}},
            {"number": 2, "actions": {"10.0.0.5": {"cmd": "stop"}}},
            {"number": 3, "actions": {"10.0.0.9": {"cmd": "play", "filename": "b.wav"}}},   # other device
            {"number": 4, "actions": {"10.0.0.5": {"cmd": "none"}}},                        # skipped
            {"number": 999, "actions": {"10.0.0.5": {"cmd": "play", "filename": "x.wav"}}}, # out of 1-255
            {"number": 5, "actions": {"10.0.0.5": {"cmd": "play", "filename": ""}}},        # empty file
        ]
        self.assertEqual(
            audio_cues.derive_device_cue_map(cues, "10.0.0.5"),
            {"1": {"cmd": "play", "file": "a.wav", "volume": 80, "delay": 500},
             "2": {"cmd": "stop"}})

    def test_volume_zero_kept_delay_zero_omitted(self):
        cues = [{"number": 7, "actions": {"1.1.1.1": {"cmd": "play", "filename": "a.wav", "volume": 0, "delay_ms": 0}}}]
        self.assertEqual(
            audio_cues.derive_device_cue_map(cues, "1.1.1.1")["7"],
            {"cmd": "play", "file": "a.wav", "volume": 0})


class MixedPortDiscovery(unittest.TestCase):
    def test_multi_polls_each_port_and_merges(self):
        seen = []
        orig = artnet.discover_artnet_nodes

        def fake(known_ips=None, timeout=3.5, interface=None, port=artnet.ARTNET_PORT):
            seen.append(port)
            return [{"ip": f"10.0.0.{port}", "port": port}]

        artnet.discover_artnet_nodes = fake
        try:
            res = artnet.discover_artnet_nodes_multi(
                ports=(artnet.ARTNET_PORT, artnet.RADIUS_ARTNET_PORT), timeout=3.0)
        finally:
            artnet.discover_artnet_nodes = orig
        self.assertEqual(seen, [artnet.ARTNET_PORT, artnet.RADIUS_ARTNET_PORT])
        self.assertEqual(sorted(n["ip"] for n in res),
                         ["10.0.0.6454", "10.0.0.6456"])

    def test_multi_dedupes_and_defaults_to_6454(self):
        orig = artnet.discover_artnet_nodes
        artnet.discover_artnet_nodes = lambda **k: []
        try:
            self.assertEqual(artnet.discover_artnet_nodes_multi(ports=()), [])
        finally:
            artnet.discover_artnet_nodes = orig


if __name__ == "__main__":
    unittest.main()
