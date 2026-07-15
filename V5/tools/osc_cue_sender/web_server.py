"""HTTP server for OSC Cue Sender."""

import json
import mimetypes
import os
import re
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from osc_client import (
    OscSender,
    normalize_osc_address,
    normalize_style,
    parse_osc_args,
    parse_target_address,
    preview_cue_address,
)
from osc_control import osc_examples
from paths import web_dir
from app_state import AppState, cues_from_import_payload
from cue_boards import delete_cue_board, list_cue_boards, load_cue_board, save_cue_board


_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _safe_id(value):
    return bool(value) and bool(_SAFE_ID_RE.match(value))


def _board_summary(board):
    return {
        "id": board.get("id"),
        "name": board.get("name", ""),
        "cue_count": len(board.get("cues") or []),
        "created": board.get("created", ""),
        "modified": board.get("modified", ""),
    }


def _resolve_send_target(data, config):
    data = data if isinstance(data, dict) else {}
    config = config if isinstance(config, dict) else {}
    default_port = config.get("target_port", 53001)
    if data.get("target_address"):
        return parse_target_address(data.get("target_address"), default_port)
    host = str(data.get("target_host") or config.get("target_host") or "127.0.0.1").strip()
    port = data.get("target_port", config.get("target_port", 53001))
    try:
        port = int(port)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid port") from exc
    if port < 1 or port > 65535:
        raise ValueError("invalid port")
    if not host:
        raise ValueError("target host required")
    return host, port


class OscCueSenderServer:
    def __init__(self, host="127.0.0.1", port=0):
        self.host = host
        self.port = port
        self.app_state = AppState()
        self.osc_sender = OscSender()
        self._httpd = None

    def start(self):
        handler = self._make_handler()
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self.port = self._httpd.server_address[1]
        thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        thread.start()
        return self.port

    def stop(self):
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def url(self):
        return f"http://{self.host}:{self.port}/"

    def _make_handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def _read_json(self):
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0:
                    return {}
                raw = self.rfile.read(length)
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))

            def _json_response(self, payload, status=200):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _json_error(self, status, message):
                self._json_response({"ok": False, "error": message}, status=status)

            def _send_raw_osc(self, data):
                config = server.app_state.get_config()
                try:
                    host, port = _resolve_send_target(data, config)
                    address = normalize_osc_address(data.get("address"))
                    args = parse_osc_args(data.get("args"))
                except ValueError as exc:
                    raise ValueError(str(exc)) from exc
                entry = server.osc_sender.send(host, port, address, *args)
                server.app_state.record_history(entry)
                return entry

            def _send_osc(self, command, data=None, **kwargs):
                config = server.app_state.get_config()
                try:
                    host, port = _resolve_send_target(data, config)
                except ValueError as exc:
                    raise ValueError(str(exc)) from exc
                entry = server.osc_sender.send_command(
                    host,
                    port,
                    config.get("message_style", "primus"),
                    command,
                    **kwargs,
                )
                server.app_state.record_history(entry)
                return entry

            def do_GET(self):
                path = urlparse(self.path).path
                if path == "/api/config":
                    self._json_response({"ok": True, "config": server.app_state.get_config()})
                    return
                if path == "/api/cues":
                    config = server.app_state.get_config()
                    style = normalize_style(config.get("message_style"))
                    cues = []
                    for cue in server.app_state.get_cues():
                        preview = preview_cue_address(style, number=cue["number"], name=cue["name"])
                        cues.append({**cue, **preview})
                    self._json_response({"ok": True, "cues": cues})
                    return
                if path == "/api/history":
                    history = server.app_state.get_history() or server.osc_sender.get_history()
                    self._json_response({"ok": True, "history": history})
                    return
                if path == "/api/osc/examples":
                    self._json_response({"ok": True, "examples": osc_examples()})
                    return
                if path == "/api/cue_boards":
                    self._json_response({
                        "ok": True,
                        "boards": list_cue_boards(),
                        "active_board": server.app_state.get_active_board(),
                    })
                    return
                if path.startswith("/api/cue_boards/"):
                    board_id = path.split("/api/cue_boards/")[1]
                    if not _safe_id(board_id):
                        self._json_error(400, "invalid id")
                        return
                    board = load_cue_board(board_id)
                    if board is None:
                        self._json_error(404, "cue board not found")
                        return
                    self._json_response({"ok": True, "board": board})
                    return
                self._serve_static(path)

            def do_POST(self):
                path = urlparse(self.path).path
                try:
                    data = self._read_json()
                except json.JSONDecodeError:
                    self._json_error(400, "invalid JSON")
                    return

                if path == "/api/config":
                    config = server.app_state.update_config(data)
                    self._json_response({"ok": True, "config": config})
                    return

                if path == "/api/cues":
                    cues = server.app_state.set_cues(data.get("cues") or data)
                    self._json_response({"ok": True, "cues": cues})
                    return

                if path == "/api/cues/import":
                    cues = server.app_state.set_cues(cues_from_import_payload(data))
                    self._json_response({"ok": True, "cues": cues})
                    return

                if path == "/api/cues/sync":
                    config = server.app_state.get_config()
                    central_url = str(data.get("central_url") or config.get("central_url") or "").strip()
                    if not central_url:
                        self._json_error(400, "central_url required")
                        return
                    try:
                        cues = _fetch_central_cues(central_url)
                    except ValueError as exc:
                        self._json_error(502, str(exc))
                        return
                    saved = server.app_state.set_cues(cues)
                    if data.get("central_url"):
                        server.app_state.update_config({"central_url": central_url})
                    self._json_response({"ok": True, "cues": saved, "central_url": central_url})
                    return

                if path == "/api/send/go":
                    try:
                        entry = self._send_osc("go", data)
                    except ValueError as exc:
                        self._json_error(400, str(exc))
                        return
                    self._json_response({"ok": entry["ok"], "entry": entry})
                    return

                if path == "/api/send/stop":
                    try:
                        entry = self._send_osc("stop", data)
                    except ValueError as exc:
                        self._json_error(400, str(exc))
                        return
                    self._json_response({"ok": entry["ok"], "entry": entry})
                    return

                if path == "/api/send/blackout":
                    try:
                        entry = self._send_osc(
                            "blackout",
                            data,
                            fade_time=data.get("fade_time", 0.0),
                        )
                    except ValueError as exc:
                        self._json_error(400, str(exc))
                        return
                    self._json_response({"ok": entry["ok"], "entry": entry})
                    return

                if path == "/api/send/cue":
                    kwargs = {}
                    if "number" in data:
                        kwargs["number"] = data.get("number")
                    elif "name" in data:
                        kwargs["name"] = data.get("name")
                    else:
                        self._json_error(400, "number or name required")
                        return
                    try:
                        entry = self._send_osc("cue", data, **kwargs)
                    except ValueError as exc:
                        self._json_error(400, str(exc))
                        return
                    self._json_response({"ok": entry["ok"], "entry": entry})
                    return

                if path == "/api/send/raw":
                    if not data.get("address"):
                        self._json_error(400, "address required")
                        return
                    try:
                        entry = self._send_raw_osc(data)
                    except ValueError as exc:
                        self._json_error(400, str(exc))
                        return
                    self._json_response({"ok": entry["ok"], "entry": entry})
                    return

                if path.startswith("/api/cue_boards/") and path.endswith("/load"):
                    board_id = path[len("/api/cue_boards/"):-len("/load")]
                    if not _safe_id(board_id):
                        self._json_error(400, "invalid id")
                        return
                    board = load_cue_board(board_id)
                    if board is None:
                        self._json_error(404, "cue board not found")
                        return
                    server.app_state.set_cues(board.get("cues", []))
                    server.app_state.set_active_board(board.get("id"), board.get("name"))
                    self._json_response({
                        "ok": True,
                        "cues": server.app_state.get_cues(),
                        "board": server.app_state.get_active_board(),
                    })
                    return

                if path == "/api/cue_boards":
                    try:
                        cues = data.get("cues")
                        if cues is None:
                            cues = server.app_state.get_cues()
                        board = save_cue_board(
                            data.get("name"),
                            cues,
                            board_id=data.get("id"),
                        )
                    except ValueError as exc:
                        self._json_error(400, str(exc))
                        return
                    server.app_state.set_active_board(board.get("id"), board.get("name"))
                    self._json_response({"ok": True, "board": _board_summary(board)})
                    return

                if path.startswith("/api/cue_boards/"):
                    board_id = path.split("/api/cue_boards/")[1]
                    if not _safe_id(board_id):
                        self._json_error(400, "invalid id")
                        return
                    if load_cue_board(board_id) is None:
                        self._json_error(404, "cue board not found")
                        return
                    try:
                        cues = data.get("cues")
                        if cues is None:
                            cues = server.app_state.get_cues()
                        board = save_cue_board(
                            data.get("name"),
                            cues,
                            board_id=board_id,
                        )
                    except ValueError as exc:
                        self._json_error(400, str(exc))
                        return
                    server.app_state.set_active_board(board.get("id"), board.get("name"))
                    self._json_response({"ok": True, "board": _board_summary(board)})
                    return

                self._json_error(404, "not found")

            def do_DELETE(self):
                path = urlparse(self.path).path
                if not path.startswith("/api/cue_boards/"):
                    self._json_error(404, "not found")
                    return
                board_id = path.split("/api/cue_boards/")[1]
                if not _safe_id(board_id):
                    self._json_error(400, "invalid id")
                    return
                if not delete_cue_board(board_id):
                    self._json_error(404, "cue board not found")
                    return
                active = server.app_state.get_active_board()
                if active and active.get("id") == board_id:
                    server.app_state.set_active_board(None, None)
                self._json_response({"ok": True})

            def _serve_static(self, path):
                if path in ("", "/"):
                    path = "/index.html"
                rel = path.lstrip("/")
                base = web_dir()
                full = os.path.abspath(os.path.join(base, rel))
                if not full.startswith(os.path.abspath(base)):
                    self.send_error(403)
                    return
                if not os.path.isfile(full):
                    self.send_error(404)
                    return
                mime, _ = mimetypes.guess_type(full)
                mime = mime or "application/octet-stream"
                with open(full, "rb") as handle:
                    body = handle.read()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


def _fetch_central_cues(central_url):
    base = str(central_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("central_url required")
    url = f"{base}/api/cues"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Central HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"Could not reach PrimusCentral at {base}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON from PrimusCentral") from exc

    cues = cues_from_import_payload(payload)
    if not cues:
        raise ValueError("No cues returned from PrimusCentral")
    return cues


def create_server(host="127.0.0.1", port=0):
    return OscCueSenderServer(host=host, port=port)
