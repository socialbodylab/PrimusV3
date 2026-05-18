import json
import os
import sys
import threading
import unittest
from urllib.request import Request, urlopen

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from server import create_server


class ServerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(
            "127.0.0.1", 0, object(), object(),
            ui_lifecycle_enabled=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=1.0)
        self.server.server_close()

    def url(self, path):
        host, port = self.server.server_address
        return f"http://{host}:{port}{path}"

    def get_json(self, path):
        with urlopen(self.url(path), timeout=2.0) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, path, payload=None):
        body = json.dumps(payload or {}).encode("utf-8")
        request = Request(
            self.url(path), data=body, method="POST",
            headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=2.0) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_runtime_reports_lifecycle_enabled(self):
        result = self.get_json("/api/runtime")

        self.assertEqual(result, {"ui_lifecycle": True})

    def test_heartbeat_updates_timestamp_and_clears_close_request(self):
        self.server.ui_close_requested_at = 1.0

        result = self.post_json("/api/ui/heartbeat")

        self.assertEqual(result, {"ok": True})
        self.assertIsNotNone(self.server.ui_last_heartbeat)
        self.assertIsNone(self.server.ui_close_requested_at)

    def test_closed_records_close_request(self):
        result = self.post_json("/api/ui/closed", {"reason": "pagehide"})

        self.assertEqual(result, {"ok": True})
        self.assertIsNotNone(self.server.ui_close_requested_at)


if __name__ == "__main__":
    unittest.main()