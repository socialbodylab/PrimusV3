"""capture_server.py — Minimal HTTP server for ArtNet Recorder."""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from artnet_capture import CaptureError, capture_manager
import capture_analyze
import capture_store
from capture_setup import load_setup, normalize_setup, save_setup, universe_for_ip
from paths import web_dir

APP_VERSION = "0.1.0"
DEFAULT_DEVICE_IP = "192.168.8.190"


def _list_interfaces():
    try:
        from network_settings import get_network_status
        status = get_network_status()
        interfaces = []
        for item in status.get("interfaces", []):
            if not item.get("connected"):
                continue
            interfaces.append({
                "id": item.get("id", ""),
                "device": item.get("device", ""),
                "label": item.get("label", item.get("device", "")),
                "source_ip": item.get("source_ip", ""),
                "type": item.get("type", ""),
                "is_preferred": bool(item.get("is_preferred")),
            })
        recommended = status.get("recommended_interface") or {}
        return {
            "interfaces": interfaces,
            "recommended": recommended.get("device", ""),
        }
    except Exception as exc:
        return {"interfaces": [], "recommended": "", "error": str(exc)}


class CaptureHandler(BaseHTTPRequestHandler):
    server_version = "ArtNetRecorder/0.1"

    def log_message(self, format, *args):
        return

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body, content_type, filename=None, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _serve_static(self, rel_path, content_type):
        path = os.path.join(web_dir(), rel_path)
        if not os.path.isfile(path):
            self.send_error(404)
            return
        with open(path, "rb") as handle:
            body = handle.read()
        self._send_bytes(body, content_type)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/recorder"):
            index = os.path.join(web_dir(), "index-artnet-recorder.html")
            if not os.path.isfile(index):
                self.send_error(404, "index-artnet-recorder.html not found")
                return
            with open(index, "rb") as handle:
                self._send_bytes(handle.read(), "text/html; charset=utf-8")
            return

        if path.startswith("/css/"):
            self._serve_static(path[1:], "text/css; charset=utf-8")
            return
        if path.startswith("/js/"):
            self._serve_static(path[1:], "application/javascript; charset=utf-8")
            return

        if path == "/api/runtime":
            iface = _list_interfaces()
            setup = load_setup()
            self._send_json({
                "app": "ArtNetRecorder",
                "version": APP_VERSION,
                "device_ip_default": DEFAULT_DEVICE_IP,
                "show_setup": setup,
                "capture": capture_manager.runtime(),
                "network": iface,
            })
            return

        if path == "/api/capture/setup":
            self._send_json({"show_setup": load_setup()})
            return

        if path == "/api/capture/stats":
            setup = load_setup()
            status = capture_store.status()
            session_setup = (status.get("session") or {}).get("show_setup")
            self._send_json(capture_analyze.analyze_events(show_setup=session_setup or setup))
            return

        if path == "/api/capture/events":
            qs = parse_qs(parsed.query)
            since = int(qs.get("since", ["0"])[0])
            self._send_json({"events": capture_store.get_events(since_id=since)})
            return

        if path == "/api/capture/export":
            session_path = capture_store.export_session_path()
            if not session_path or not os.path.isfile(session_path):
                self._send_json({"error": "no capture file available"}, status=404)
                return
            with open(session_path, "rb") as handle:
                jsonl = handle.read()
            summary = json.dumps(capture_analyze.summary_report(), indent=2).encode("utf-8")
            bundle = {
                "jsonl": jsonl.decode("utf-8"),
                "summary": json.loads(summary.decode("utf-8")),
                "filename": os.path.basename(session_path),
            }
            self._send_json(bundle)
            return

        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/capture/start":
            try:
                body = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "invalid JSON"}, status=400)
                return
            mode = body.get("mode", "standin")
            device_ip = body.get("device_ip", DEFAULT_DEVICE_IP)
            interface = body.get("interface", "")
            full_payload = bool(body.get("full_payload", False))
            duration_s = body.get("duration_s")
            show_setup = normalize_setup(body.get("show_setup") or load_setup())
            save_setup(show_setup)
            try:
                runtime = capture_manager.start(
                    mode=mode,
                    device_ip=device_ip,
                    interface=interface,
                    full_payload=full_payload,
                    duration_s=duration_s,
                    show_setup=show_setup,
                )
            except CaptureError as exc:
                self._send_json({"error": exc.message}, status=409)
                return
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, status=409)
                return
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=500)
                return
            self._send_json({"ok": True, "capture": runtime})
            return

        if path == "/api/capture/setup":
            try:
                body = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json({"error": "invalid JSON"}, status=400)
                return
            setup = save_setup(body.get("show_setup") or body)
            self._send_json({"ok": True, "show_setup": setup})
            return

        if path == "/api/capture/stop":
            runtime = capture_manager.stop()
            self._send_json({"ok": True, "capture": runtime})
            return

        self.send_error(404)


def create_server(host, port):
    return ThreadingHTTPServer((host, port), CaptureHandler)
