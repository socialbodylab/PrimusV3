"""Tests for ArtNet Recorder parser, analyzer, and HTTP API."""

import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

_tmpdir = tempfile.mkdtemp()
os.environ["PRIMUSV3_DATA_DIR"] = _tmpdir

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import artnet_parse
import capture_analyze
import capture_store
from artnet_capture import capture_manager
import capture_server
import capture_setup


def _http(method, url, body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read()
            parsed = json.loads(raw.decode()) if raw else None
            return resp.status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw.decode()) if raw else None
        except json.JSONDecodeError:
            parsed = None
        return exc.code, parsed


class ArtNetParseTests(unittest.TestCase):
    def test_build_and_parse_artdmx(self):
        payload = bytes([255, 0, 0] * 4)
        raw = artnet_parse.build_artdmx_packet(universe=7, sequence=12, rgb_data=payload)
        event = artnet_parse.parse_artnet_packet(
            raw, src_ip="10.0.0.2", dst_ip="192.168.8.190", ts=1000.0
        )
        self.assertIsNotNone(event)
        self.assertEqual(event["opcode"], 0x5000)
        self.assertEqual(event["opcode_name"], "ArtDmx")
        self.assertEqual(event["universe"], 7)
        self.assertEqual(event["sequence"], 12)
        self.assertEqual(event["length"], 12)
        self.assertEqual(len(event["payload_crc32"]), 8)

    def test_rejects_non_artnet(self):
        self.assertIsNone(artnet_parse.parse_artnet_packet(b"not-artnet"))

    def test_parse_ethernet_udp(self):
        art_payload = artnet_parse.build_artdmx_packet(1, 3, b"\x01\x02\x03")
        udp_len = 8 + len(art_payload)
        ip_len = 20 + udp_len
        eth = bytearray(14 + ip_len)
        eth[12:14] = struct.pack(">H", 0x0800)
        ip_start = 14
        eth[ip_start] = 0x45
        eth[ip_start + 9] = 17
        src = [192, 168, 8, 50]
        dst = [192, 168, 8, 190]
        eth[ip_start + 12:ip_start + 16] = bytes(src)
        eth[ip_start + 16:ip_start + 20] = bytes(dst)
        udp_start = ip_start + 20
        eth[udp_start:udp_start + 2] = struct.pack(">H", 50000)
        eth[udp_start + 2:udp_start + 4] = struct.pack(">H", 6454)
        eth[udp_start + 4:udp_start + 6] = struct.pack(">H", udp_len)
        eth[udp_start + 8:udp_start + 8 + len(art_payload)] = art_payload
        parsed = artnet_parse.parse_ethernet_udp(bytes(eth))
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], "192.168.8.50")
        self.assertEqual(parsed[1], "192.168.8.190")
        self.assertEqual(parsed[2][:8], artnet_parse.ARTNET_HEADER)


class CaptureSetupTests(unittest.TestCase):
    def test_build_device_list_increments_ip_and_universe(self):
        devices = capture_setup.build_device_list("192.168.8.190", 104, 3)
        self.assertEqual(len(devices), 3)
        self.assertEqual(devices[0]["ip"], "192.168.8.190")
        self.assertEqual(devices[0]["universe"], 104)
        self.assertEqual(devices[1]["ip"], "192.168.8.191")
        self.assertEqual(devices[1]["universe"], 105)
        self.assertEqual(devices[2]["universe"], 106)

    def test_bpf_host_filter_multiple_devices(self):
        setup = capture_setup.normalize_setup({
            "devices": [
                {"ip": "192.168.8.190", "universe": 1, "label": "A"},
                {"ip": "192.168.8.191", "universe": 2, "label": "B"},
            ],
        })
        filt = capture_setup.bpf_host_filter(setup)
        self.assertIn("host 192.168.8.190", filt)
        self.assertIn("host 192.168.8.191", filt)


class CaptureAnalyzeTests(unittest.TestCase):
    def setUp(self):
        capture_store.stop_recording()
        capture_manager.stop()

    def _artdmx_event(self, src, universe, sequence, ts, delta_ms=None):
        return {
            "id": 0,
            "ts": ts,
            "src": src,
            "dst": "192.168.8.190",
            "opcode": 0x5000,
            "opcode_name": "ArtDmx",
            "universe": universe,
            "sequence": sequence,
            "length": 12,
            "payload_crc32": "deadbeef",
            "delta_ms": delta_ms,
        }

    def test_multiple_sources_anomaly(self):
        now = time.time()
        entries = [
            self._artdmx_event("10.0.0.1", 0, 1, now),
            self._artdmx_event("10.0.0.2", 1, 1, now + 0.01),
        ]
        stats = capture_analyze.analyze_events(entries)
        codes = {a["code"] for a in stats["anomalies"]}
        self.assertIn("multiple_sources", codes)

    def test_sequence_gap_detection(self):
        now = time.time()
        entries = [
            self._artdmx_event("10.0.0.1", 0, 1, now),
            self._artdmx_event("10.0.0.1", 0, 4, now + 0.033, delta_ms=33.0),
        ]
        stats = capture_analyze.analyze_events(entries)
        self.assertGreaterEqual(stats["sequence_gaps"], 2)

    def test_burst_rate_anomaly(self):
        now = time.time()
        entries = [
            self._artdmx_event("10.0.0.1", 0, i, now + i * 0.005, delta_ms=5.0)
            for i in range(1, 20)
        ]
        stats = capture_analyze.analyze_events(entries)
        codes = {a["code"] for a in stats["anomalies"]}
        self.assertIn("burst_rate", codes)

    def test_wrong_universe_anomaly(self):
        now = time.time()
        setup = capture_setup.normalize_setup({
            "layout": "per_device_universe",
            "devices": [{"ip": "192.168.8.190", "universe": 104, "label": "Test"}],
        })
        entries = [{
            "ts": now,
            "src": "10.0.0.1",
            "dst": "192.168.8.190",
            "opcode": 0x5000,
            "opcode_name": "ArtDmx",
            "universe": 99,
            "expected_universe": 104,
            "sequence": 1,
            "length": 12,
            "payload_crc32": "deadbeef",
        }]
        stats = capture_analyze.analyze_events(entries, show_setup=setup)
        codes = {a["code"] for a in stats["anomalies"]}
        self.assertIn("wrong_universe", codes)
        self.assertEqual(stats["wrong_universe_packets"], 1)


class CaptureStoreTests(unittest.TestCase):
    def setUp(self):
        capture_store.stop_recording()
        capture_manager.stop()

    def test_record_delta_ms(self):
        capture_store.start_recording("standin", "192.168.8.190", "")
        capture_store.record_event({
            "ts": 1000.0,
            "src": "10.0.0.1",
            "dst": "192.168.8.190",
            "opcode": 0x5000,
            "opcode_name": "ArtDmx",
            "universe": 1,
            "sequence": 1,
        })
        second = capture_store.record_event({
            "ts": 1000.05,
            "src": "10.0.0.1",
            "dst": "192.168.8.190",
            "opcode": 0x5000,
            "opcode_name": "ArtDmx",
            "universe": 1,
            "sequence": 2,
        })
        self.assertAlmostEqual(second["delta_ms"], 50.0)
        path = capture_store.export_session_path()
        self.assertTrue(path and os.path.isfile(path))
        capture_store.stop_recording()


class CaptureServerTests(unittest.TestCase):
    def setUp(self):
        capture_store.stop_recording()
        capture_manager.stop()
        self.httpd = capture_server.create_server("127.0.0.1", 0)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        capture_manager.stop()
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_runtime_endpoint(self):
        status, data = _http("GET", f"{self.base}/api/runtime")
        self.assertEqual(status, 200)
        self.assertEqual(data["app"], "ArtNetRecorder")

    def test_capture_start_stop_roundtrip(self):
        def _sender():
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            pkt = artnet_parse.build_artdmx_packet(0, 1, b"\xff\x00\x00")
            for seq in range(1, 4):
                pkt = artnet_parse.build_artdmx_packet(0, seq, b"\xff\x00\x00")
                s.sendto(pkt, ("127.0.0.1", 6454))
                time.sleep(0.01)
            s.close()

        status, data = _http("POST", f"{self.base}/api/capture/start", {
            "mode": "standin",
            "device_ip": "192.168.8.190",
            "interface": "",
            "show_setup": capture_setup.normalize_setup({
                "start_ip": "192.168.8.190",
                "start_universe": 1,
                "device_count": 2,
            }),
        })
        self.assertEqual(status, 200, data)
        self.assertTrue(data["capture"]["recording"])

        sender = threading.Thread(target=_sender, daemon=True)
        sender.start()
        sender.join(timeout=2)

        status, stats = _http("GET", f"{self.base}/api/capture/stats")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(stats["packet_count"], 1)

        status, data = _http("POST", f"{self.base}/api/capture/stop", {})
        self.assertEqual(status, 200)
        self.assertFalse(data["capture"]["recording"])

        status, export_data = _http("GET", f"{self.base}/api/capture/export")
        self.assertEqual(status, 200)
        self.assertIn("jsonl", export_data)
        self.assertIn("summary", export_data)


if __name__ == "__main__":
    unittest.main()
