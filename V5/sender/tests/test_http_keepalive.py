"""HTTP/1.1 keep-alive contract for the unified server.

The server speaks HTTP/1.1 with persistent connections, so every request
must produce exactly one response. A handled POST route that falls through
to the trailing not-found branch writes a second (404) response onto the
same socket, which desyncs every subsequent request on that connection —
the client reads the stale 404 as the answer to its next call. This
regression appeared when do_POST grew a second dispatch chain whose final
``else`` did not cover the first chain's routes.
"""

import json
import socket
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server as server_module


class _NullState:
    """No product state: exercises pure-dispatch routes only."""


def _read_one_response(sock):
    """Read exactly one HTTP response (headers + Content-Length body)."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise AssertionError("connection closed before headers finished")
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    headers = {}
    lines = head.split(b"\r\n")
    status = lines[0].decode()
    for line in lines[1:]:
        name, _, value = line.partition(b":")
        headers[name.strip().lower()] = value.strip()
    length = int(headers.get(b"content-length", b"0"))
    body = rest
    while len(body) < length:
        chunk = sock.recv(4096)
        if not chunk:
            raise AssertionError("connection closed before body finished")
        body += chunk
    extra = body[length:]
    return status, body[:length], extra


def _post(sock, path, payload):
    body = json.dumps(payload).encode()
    sock.sendall(
        b"POST " + path.encode() + b" HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"\r\n" + body
    )


class KeepAliveSingleResponseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server_module.create_server("127.0.0.1", 0, _NullState())
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=5)

    def test_sequential_posts_on_one_connection_stay_in_sync(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        try:
            # First-chain route (ui lifecycle), second-chain route (netlog),
            # then an unmatched path — each must yield exactly one response,
            # in order, with no stray bytes between them.
            _post(sock, "/api/ui/heartbeat", {"session_id": "keepalive-test"})
            status, body, extra = _read_one_response(sock)
            self.assertIn("200", status)
            self.assertEqual(json.loads(body), {"ok": True})
            self.assertEqual(extra, b"", "stray bytes after first response")

            _post(sock, "/api/netlog/clear", {})
            status, body, extra = _read_one_response(sock)
            self.assertIn("200", status)
            self.assertEqual(json.loads(body), {"ok": True})
            self.assertEqual(extra, b"", "stray bytes after second response")

            _post(sock, "/api/does_not_exist", {})
            status, body, extra = _read_one_response(sock)
            self.assertIn("404", status)
            self.assertEqual(extra, b"", "stray bytes after 404 response")
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
