"""Smoke tests for Radius Central audio cue, netlog, and cue-map HTTP routes."""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

_tmpdir = tempfile.mkdtemp()
os.environ["RADIUSV4_DATA_DIR"] = _tmpdir

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import netlog
import server
import server_radius
from radius_state import RadiusState


def _http(method, url, body=None, headers=None):
    data = None
    req_headers = dict(headers or {})
    if body is not None:
        if isinstance(body, dict):
            data = json.dumps(body).encode()
            req_headers.setdefault("Content-Type", "application/json")
        else:
            data = body
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
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


class ServerAudioRouteTests(unittest.TestCase):
    def setUp(self):
        netlog.clear()
        server_radius._sync_job = None
        self.state = RadiusState()
        self.state.devices = [
            {
                "ip": "192.168.1.50",
                "connected": True,
                "is_radius": True,
                "name": "Radius-1",
            },
        ]
        self.httpd = server.create_server("127.0.0.1", 0, self.state)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_audio_cues_crud_roundtrip(self):
        payload = {"cues": [{"number": 7, "note": "test", "actions": {}}]}
        status, data = _http("POST", f"{self.base}/api/audio_cues", payload)
        self.assertEqual(status, 200)
        self.assertEqual(data, payload)

        status, data = _http("GET", f"{self.base}/api/audio_cues")
        self.assertEqual(status, 200)
        self.assertEqual(data, payload)

    def test_netlog_roundtrip(self):
        netlog.log("OUT", "audio_cmd", "test event")
        status, data = _http("GET", f"{self.base}/api/netlog?since=0")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(data["entries"]), 1)
        self.assertEqual(data["entries"][-1]["summary"], "test event")

        status, _ = _http("POST", f"{self.base}/api/netlog/clear", {})
        self.assertEqual(status, 200)
        status, data = _http("GET", f"{self.base}/api/netlog?since=0")
        self.assertEqual(data["entries"], [])

    def test_cue_map_invalid_device(self):
        status, data = _http("GET", f"{self.base}/api/audio/cue_map?device=99")
        self.assertEqual(status, 400)
        self.assertIn("error", data)

        status, data = _http(
            "POST",
            f"{self.base}/api/audio/cue_map",
            {"device": 99, "cues": {"1": "x.wav"}},
        )
        self.assertEqual(status, 400)

    @patch.object(RadiusState, "ftp_download", return_value=b'{"1":"intro.wav"}')
    def test_cue_map_get(self, _mock_dl):
        status, data = _http("GET", f"{self.base}/api/audio/cue_map?device=0")
        self.assertEqual(status, 200)
        self.assertEqual(data, {"1": "intro.wav"})

    @patch.object(RadiusState, "ftp_upload")
    def test_cue_map_post(self, mock_upload):
        status, _ = _http(
            "POST",
            f"{self.base}/api/audio/cue_map",
            {"device": 0, "cues": {"2": "hit.wav"}},
        )
        self.assertEqual(status, 200)
        mock_upload.assert_called_once()
        args = mock_upload.call_args[0]
        self.assertEqual(args[1], "/cues.json")

    @patch.object(server.Handler, "_sync_artnet_source", return_value=None)
    @patch.object(RadiusState, "hello_device", return_value=True)
    def test_hello_device(self, mock_hello, _mock_sync):
        status, _ = _http(
            "POST",
            f"{self.base}/api/hello_device",
            {"device": 0, "volume": 70},
        )
        self.assertEqual(status, 200)
        mock_hello.assert_called_once_with(0, volume=70)

    def test_preview_cue_maps(self):
        server_radius.Handler.audio_cues_data = {
            "cues": [
                {"number": 1, "actions": {"192.168.1.50": {"cmd": "play", "filename": "a.wav", "volume": 97}}},
                {"number": 2, "actions": {"192.168.9.99": {"cmd": "play", "filename": "b.wav"}}},
            ],
        }
        status, data = _http("POST", f"{self.base}/api/audio_cues/preview_cue_maps", {})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["devices"]), 1)
        dev = data["devices"][0]
        self.assertEqual(dev["ip"], "192.168.1.50")
        self.assertEqual(dev["cue_count"], 1)
        self.assertEqual(dev["cues"]["1"], {"cmd": "play", "file": "a.wav", "volume": 97})

    @patch.object(RadiusState, "ftp_upload")
    def test_push_cue_maps(self, mock_upload):
        server_radius.Handler.audio_cues_data = {
            "cues": [
                {"number": 1, "actions": {"192.168.1.50": {"cmd": "play", "filename": "a.wav", "volume": 97, "delay_ms": 500}}},
            ],
        }
        status, data = _http("POST", f"{self.base}/api/audio_cues/push_cue_maps", {})
        self.assertEqual(status, 200)
        self.assertEqual(data["results"]["192.168.1.50"]["status"], "ok")
        self.assertEqual(data["results"]["192.168.1.50"]["cue_count"], 1)
        mock_upload.assert_called_once()
        args = mock_upload.call_args[0]
        self.assertEqual(args[1], "/cues.json")
        uploaded = json.loads(args[2].decode())
        self.assertEqual(uploaded["1"],
                         {"cmd": "play", "file": "a.wav", "volume": 97, "delay": 500})

    def test_push_cue_maps_no_connected_devices(self):
        self.state.devices[0]["connected"] = False
        server_radius.Handler.audio_cues_data = {"cues": []}
        status, data = _http("POST", f"{self.base}/api/audio_cues/push_cue_maps", {})
        self.assertEqual(status, 200)
        self.assertEqual(data["results"], {})
        self.assertIn("message", data)

    @patch.object(RadiusState, "fire_audio_cue", return_value={"192.168.1.50": {"status": "sent"}})
    def test_fire_cue(self, mock_fire):
        server_radius.Handler.audio_cues_data = {
            "cues": [{"number": 3, "actions": {"192.168.1.50": {"cmd": "play", "filename": "x.wav"}}}],
        }
        status, data = _http("POST", f"{self.base}/api/audio_cues/fire", {"number": 3})
        self.assertEqual(status, 200)
        self.assertIn("results", data)
        mock_fire.assert_called_once()


if __name__ == "__main__":
    unittest.main()
