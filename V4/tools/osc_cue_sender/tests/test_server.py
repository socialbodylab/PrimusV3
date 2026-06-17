import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from urllib.request import urlopen


APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from web_server import create_server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        os.environ["OSC_CUE_SENDER_DATA_DIR"] = self.tempdir.name
        self.server = create_server(host="127.0.0.1", port=0)
        self.port = self.server.start()

    def tearDown(self):
        self.server.stop()
        self.tempdir.cleanup()
        os.environ.pop("OSC_CUE_SENDER_DATA_DIR", None)

    def _post(self, path, payload):
        import urllib.request

        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get(self, path):
        with urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_send_go(self):
        config = self._post(
            "/api/config",
            {"target_host": "127.0.0.1", "target_port": 53001, "message_style": "primus"},
        )
        self.assertTrue(config["ok"])

        with mock.patch.object(self.server.osc_sender, "send_command") as send_command:
            send_command.return_value = {
                "time": "12:00:00",
                "ok": True,
                "target": "127.0.0.1:53001",
                "address": "/primus/cue/go",
                "args": [],
                "error": "",
            }
            result = self._post("/api/send/go", {})
            self.assertTrue(result["ok"])
            send_command.assert_called_once_with(
                "127.0.0.1",
                53001,
                "primus",
                "go",
            )

    def test_send_with_target_override(self):
        self._post(
            "/api/config",
            {"target_host": "127.0.0.1", "target_port": 53001, "message_style": "primus"},
        )
        with mock.patch.object(self.server.osc_sender, "send_command") as send_command:
            send_command.return_value = {
                "time": "12:00:00",
                "ok": True,
                "target": "192.168.1.50:53002",
                "address": "/primus/cue/go",
                "args": [],
                "error": "",
            }
            result = self._post("/api/send/go", {"target_address": "192.168.1.50:53002"})
            self.assertTrue(result["ok"])
            send_command.assert_called_once_with(
                "192.168.1.50",
                53002,
                "primus",
                "go",
            )

    def test_send_raw_message(self):
        self._post(
            "/api/config",
            {"target_host": "127.0.0.1", "target_port": 53001, "message_style": "primus"},
        )
        with mock.patch.object(self.server.osc_sender, "send") as send:
            send.return_value = {
                "time": "12:00:00",
                "ok": True,
                "target": "127.0.0.1:53001",
                "address": "/primus/cue/goto",
                "args": [3],
                "error": "",
            }
            result = self._post("/api/send/raw", {
                "address": "/primus/cue/goto",
                "args": "3",
            })
            self.assertTrue(result["ok"])
            send.assert_called_once_with("127.0.0.1", 53001, "/primus/cue/goto", 3)

    def test_osc_examples(self):
        payload = self._get("/api/osc/examples")
        self.assertTrue(payload["ok"])
        self.assertTrue(any(item["address"] == "/primus/cue/go" for item in payload["examples"]))

    def test_import_cues(self):
        payload = self._post(
            "/api/cues/import",
            {"cues": [{"number": 5, "name": "Finale"}]},
        )
        self.assertEqual(payload["cues"][0]["number"], 5)
        cues = self._get("/api/cues")
        self.assertEqual(len(cues["cues"]), 1)

    def test_static_index(self):
        with urlopen(f"http://127.0.0.1:{self.port}/", timeout=5) as response:
            body = response.read().decode("utf-8")
        self.assertIn("OSC Cue Sender", body)

    def test_cue_board_save_and_load(self):
        save = self._post("/api/cue_boards", {
            "name": "Show A",
            "cues": [{"number": 1, "name": "Intro"}],
        })
        board_id = save["board"]["id"]
        boards = self._get("/api/cue_boards")
        self.assertEqual(len(boards["boards"]), 1)

        load = self._post(f"/api/cue_boards/{board_id}/load", {})
        self.assertEqual(load["board"]["name"], "Show A")
        cues = self._get("/api/cues")
        self.assertEqual(len(cues["cues"]), 1)


if __name__ == "__main__":
    unittest.main()
