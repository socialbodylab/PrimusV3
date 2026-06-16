"""
server.py — HTTP server for Radius Central (device, audio, firmware, settings).
"""

import json
import os
import re
import mimetypes
import threading
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote

import audio_cues as _audio_cues_mod
import netlog
from firmware import FirmwareRequestError, firmware_jobs
from artnet import (
    discover_artnet_nodes,
    ftp_list_dir,
    ftp_upload,
    send_audio_cmd,
    AUDIO_CMD_STOP,
)
from network_settings import (
    NetworkSettingsError,
    apply_static_ip,
    get_artnet_interface,
    get_network_status,
    save_profile,
    set_controller_connection,
    set_dhcp,
    set_preferred_interface,
)
from paths import web_dir, sender_product, index_html_path


_WEB_DIR = web_dir()
_SAFE_ID_RE = re.compile(r'^[a-zA-Z0-9_-]+$')
_sync_lock = threading.Lock()
_sync_job = None


def _safe_id(value):
    return bool(value) and bool(_SAFE_ID_RE.match(value))


def _safe_ftp_path(path):
    if not path or not path.startswith("/"):
        return False
    if ".." in path or "\\" in path:
        return False
    return True


class Handler(BaseHTTPRequestHandler):
    controller_state = None
    audio_cues_data = {"cues": []}
    audio_cues_lock = threading.Lock()

    def _json_error(self, code, message):
        body = json.dumps({"error": message}, separators=(",", ":")).encode()
        self._respond(code, "application/json", body)

    def _json_network_error(self, exc):
        self._json_error(exc.code, exc.message)

    def _sync_artnet_source(self):
        interface = get_artnet_interface()
        source_ip = (interface or {}).get("source_ip") or (interface or {}).get("ipv4")
        self.controller_state.set_artnet_source(source_ip)
        return interface

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/api/runtime":
            self._json_response({
                "product": paths.sender_product(),
                "ui_lifecycle": bool(getattr(self.server, "ui_lifecycle_enabled", False)),
            })
            return
        if path == "/api/state":
            self._json_response(self.controller_state.get_json())
            return
        if path == "/api/performance":
            self._json_response(self.controller_state.get_performance_json())
            return
        if path == "/api/network/status":
            self._json_response(get_network_status())
            return
        if path == "/api/firmware/status":
            self._json_response(firmware_jobs.status())
            return
        if path.startswith("/api/firmware/jobs/"):
            job_id = path.split("/api/firmware/jobs/")[1]
            if not _safe_id(job_id):
                self._json_error(400, "invalid firmware job id")
                return
            try:
                self._json_response(firmware_jobs.get_job(job_id))
            except FirmwareRequestError as exc:
                self._json_error(exc.code, exc.message)
            return
        if path == "/api/audio_cues":
            with self.audio_cues_lock:
                self._json_response(dict(self.audio_cues_data))
            return
        if path == "/api/audio_cues/export":
            with self.audio_cues_lock:
                body = json.dumps(self.audio_cues_data, indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Disposition", 'attachment; filename="audio_cues.json"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/netlog":
            params = self._query_params()
            try:
                since = int(params.get("since", 0))
            except (TypeError, ValueError):
                since = 0
            self._json_response({"entries": netlog.get_entries(since_id=since)})
            return
        if path == "/api/audio/cue_map":
            params = self._query_params()
            try:
                di = int(params.get("device", -1))
            except (TypeError, ValueError):
                di = -1
            devices = self.controller_state.devices
            if not (0 <= di < len(devices)) or not devices[di].get("is_radius"):
                self._json_error(400, "invalid device index")
                return
            try:
                raw = self.controller_state.ftp_download(di, "/cues.json")
                self._json_response(json.loads(raw.decode()))
            except Exception as exc:
                self._json_error(500, str(exc))
            return
        if path == "/api/audio_sync/status":
            with _sync_lock:
                job = dict(_sync_job) if _sync_job else None
                if job and "items" in job:
                    job = dict(job)
                    job["items"] = list(job["items"])
            self._json_response(job or {"status": "idle"})
            return
        if path == "/api/project_audio":
            self._json_response({"files": _audio_cues_mod.list_project_audio()})
            return
        if path.startswith("/api/"):
            self._json_error(404, "not found")
            return

        self._serve_static(path)

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/api/audio/upload":
            self._handle_audio_upload()
            return
        if path == "/api/project_audio":
            self._handle_project_audio_upload()
            return
        if path == "/api/audio_cues/import":
            self._handle_audio_cues_import()
            return

        data = self._read_json_body()

        if path == "/api/ui/heartbeat":
            if getattr(self.server, "ui_lifecycle_enabled", False):
                self.server.ui_last_heartbeat = time.monotonic()
                self.server.ui_close_requested_at = None
            self._ok()
            return
        if path == "/api/ui/closed":
            if getattr(self.server, "ui_lifecycle_enabled", False):
                self.server.ui_close_requested_at = time.monotonic()
            self._ok()
            return
        if path == "/api/update":
            self._json_response(self.controller_state.get_json())
            return
        if path == "/api/connect":
            di = data.get("device", 0)
            result = self.controller_state.connect(di)
            if result.get("ok"):
                self._ok()
            else:
                self._json_error(400, result.get("error", "connect failed"))
            return
        if path == "/api/disconnect":
            di = data.get("device", 0)
            result = self.controller_state.disconnect(di)
            if result.get("ok"):
                self._ok()
            else:
                self._json_error(400, result.get("error", "disconnect failed"))
            return
        if path == "/api/connect_all":
            known_ips = self.controller_state.discovery_targets()
            interface = self._sync_artnet_source()
            nodes = discover_artnet_nodes(known_ips=known_ips, timeout=2.0, interface=interface)
            if nodes:
                self.controller_state.refresh_devices_from_nodes(nodes)
            online_ips = {node.get("ip") for node in nodes if node.get("ip")}
            self.controller_state.connect_all(only_ips=online_ips if online_ips else None)
            self._ok()
            return
        if path == "/api/disconnect_all":
            self.controller_state.disconnect_all()
            self._ok()
            return
        if path == "/api/discover":
            known_ips = self.controller_state.discovery_targets()
            interface = self._sync_artnet_source()
            nodes = discover_artnet_nodes(known_ips=known_ips, timeout=2.0, interface=interface)
            self.controller_state.refresh_devices_from_nodes(nodes)
            self._json_response(nodes)
            return
        if path == "/api/add_discovered":
            self._sync_artnet_source()
            result = self.controller_state.add_device_from_node(data)
            if result.get("device_index") is not None:
                connect_result = self.controller_state.connect(result["device_index"])
                if not connect_result.get("ok"):
                    result["connect_error"] = connect_result.get("error")
            self._json_response(result)
            return
        if path == "/api/add_manual":
            ip = str(data.get("ip", "")).strip()
            name = str(data.get("name", ip or "Radius")).strip()
            if not ip:
                self._json_error(400, "ip required")
                return
            self._sync_artnet_source()
            result = self.controller_state.add_device_from_node({
                "ip": ip,
                "short_name": name,
                "long_name": name,
                "num_ports": 0,
                "universes": [],
                "capabilities": {"device_class": "radius", "audio": True, "ftp": True},
            })
            self._json_response(result)
            return
        if path == "/api/remove_device":
            di = data.get("device", 0)
            if self.controller_state.remove_device(di):
                self._ok()
            else:
                self._json_error(400, "invalid device index")
            return
        if path == "/api/rename_node":
            di = data.get("device", 0)
            new_name = str(data.get("name", "")).strip()
            if not new_name:
                self._json_error(400, "name required")
                return
            if self.controller_state.rename_device(di, new_name):
                self._ok()
            else:
                self._json_error(400, "rename failed")
            return
        if path == "/api/set_device_ip":
            di = data.get("device", 0)
            static_ip = str(data.get("ip", "")).strip()
            gateway = str(data.get("gateway", "")).strip()
            subnet = str(data.get("subnet", "")).strip()
            if not (static_ip and gateway and subnet):
                self._json_error(400, "ip, gateway, and subnet required")
                return
            if self.controller_state.set_device_ip(di, static_ip, gateway, subnet):
                self._ok()
            else:
                self._json_error(400, "set device ip failed")
            return
        if path == "/api/revert_device_dhcp":
            di = data.get("device", 0)
            if self.controller_state.revert_device_dhcp(di):
                self._ok()
            else:
                self._json_error(400, "revert dhcp failed")
            return
        if path == "/api/hello_device":
            di = data.get("device", -1)
            try:
                volume = max(0, min(100, int(data.get("volume", 80))))
            except (TypeError, ValueError):
                volume = 80
            if self.controller_state.hello_device(di, volume=volume):
                self._ok()
            else:
                self._json_error(400, "hello failed")
            return
        if path == "/api/firmware/jobs":
            try:
                job = firmware_jobs.start_job(data)
                self._json_response(job)
            except FirmwareRequestError as exc:
                self._json_error(exc.code, exc.message)
            return
        if path == "/api/network/preferred_interface":
            try:
                self._json_response(set_preferred_interface(data))
            except NetworkSettingsError as exc:
                self._json_network_error(exc)
            return
        if path == "/api/network/ssid_profile":
            try:
                self._json_response(save_profile(data))
            except NetworkSettingsError as exc:
                self._json_network_error(exc)
            return
        if path == "/api/network/controller_connection":
            try:
                self._json_response(set_controller_connection(data))
            except NetworkSettingsError as exc:
                self._json_network_error(exc)
            return
        if path == "/api/network/apply_static_ip":
            try:
                self._json_response(apply_static_ip(data))
            except NetworkSettingsError as exc:
                self._json_network_error(exc)
            return
        if path == "/api/network/set_dhcp":
            try:
                self._json_response(set_dhcp(data))
            except NetworkSettingsError as exc:
                self._json_network_error(exc)
            return
        if path == "/api/audio/cmd":
            di = data.get("device", -1)
            cmd = str(data.get("cmd", "stop"))
            filename = str(data.get("filename", ""))
            try:
                volume = max(0, min(100, int(data.get("volume", 100))))
            except (TypeError, ValueError):
                volume = 100
            try:
                duration = max(0, int(data.get("duration", 0)))
            except (TypeError, ValueError):
                duration = 0
            if self.controller_state.send_audio_command(
                    di, cmd, filename, volume, duration=duration):
                self._ok()
            else:
                self._json_error(400, "invalid device index or command")
            return
        if path == "/api/audio/files":
            di = data.get("device", -1)
            ftp_path = str(data.get("path", "/"))
            if not (0 <= di < len(self.controller_state.devices)):
                self._json_error(400, "invalid device index")
            elif not _safe_ftp_path(ftp_path):
                self._json_error(400, "invalid path")
            else:
                try:
                    entries = self.controller_state.ftp_list_dir(di, ftp_path)
                    self._json_response({"entries": entries or []})
                except Exception as exc:
                    self._json_error(500, str(exc))
            return
        if path == "/api/audio/rename":
            di = data.get("device", -1)
            src = str(data.get("src", ""))
            dst = str(data.get("dst", ""))
            if not (0 <= di < len(self.controller_state.devices)):
                self._json_error(400, "invalid device index")
            elif not _safe_ftp_path(src) or not _safe_ftp_path(dst):
                self._json_error(400, "invalid path")
            else:
                try:
                    self.controller_state.ftp_rename(di, src, dst)
                    self._ok()
                except Exception as exc:
                    self._json_error(500, str(exc))
            return
        if path == "/api/audio/delete":
            di = data.get("device", -1)
            ftp_path = str(data.get("path", ""))
            is_dir = bool(data.get("is_dir", False))
            if not (0 <= di < len(self.controller_state.devices)):
                self._json_error(400, "invalid device index")
            elif not _safe_ftp_path(ftp_path):
                self._json_error(400, "invalid path")
            else:
                try:
                    self.controller_state.ftp_delete(di, ftp_path, is_dir=is_dir)
                    self._ok()
                except Exception as exc:
                    self._json_error(500, str(exc))
            return
        if path == "/api/audio/mkdir":
            di = data.get("device", -1)
            ftp_path = str(data.get("path", ""))
            if not (0 <= di < len(self.controller_state.devices)):
                self._json_error(400, "invalid device index")
            elif not _safe_ftp_path(ftp_path):
                self._json_error(400, "invalid path")
            else:
                try:
                    self.controller_state.ftp_mkdir(di, ftp_path)
                    self._ok()
                except Exception as exc:
                    self._json_error(500, str(exc))
            return
        if path == "/api/audio/cue_map":
            di = data.get("device", -1)
            cues = data.get("cues")
            devices = self.controller_state.devices
            if not (0 <= di < len(devices)) or not devices[di].get("is_radius"):
                self._json_error(400, "invalid device index")
                return
            if not isinstance(cues, dict):
                self._json_error(400, "cues must be an object")
                return
            try:
                raw = json.dumps(cues, indent=2).encode()
                self.controller_state.ftp_upload(di, "/cues.json", raw)
                self._ok()
            except Exception as exc:
                self._json_error(500, str(exc))
            return
        if path == "/api/audio_cues":
            with self.audio_cues_lock:
                Handler.audio_cues_data = data
                _audio_cues_mod.save_audio_cues(data)
            self._json_response(data)
            return
        if path == "/api/audio_cues/fire":
            number = data.get("number")
            with self.audio_cues_lock:
                cues = self.audio_cues_data.get("cues", [])
            cue = next((c for c in cues if c.get("number") == number), None)
            if cue is None:
                self._json_error(404, "cue not found")
                return
            results = self.controller_state.fire_audio_cue(cue)
            self._json_response({"results": results})
            return
        if path == "/api/audio_sync":
            global _sync_job
            with _sync_lock:
                if _sync_job and _sync_job.get("status") == "running":
                    self._json_response({
                        "error": "sync already running",
                        "job_id": _sync_job["job_id"],
                    })
                    return
                new_job = {
                    "job_id": str(uuid.uuid4())[:8],
                    "status": "planning",
                    "items": [],
                }
                _sync_job = new_job
            with self.audio_cues_lock:
                cues_snapshot = dict(self.audio_cues_data)
            threading.Thread(
                target=_run_sync_job,
                args=(new_job, self.controller_state, cues_snapshot),
                daemon=True,
            ).start()
            self._json_response({"job_id": new_job["job_id"]})
            return
        if path == "/api/netlog/clear":
            netlog.clear()
            self._ok()
            return

        self._json_error(404, "not found")

    def do_DELETE(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/project_audio/"):
            filename = unquote(path.split("/api/project_audio/")[1])
            if not filename or "/" in filename or "\x00" in filename:
                self._json_error(400, "invalid filename")
                return
            if _audio_cues_mod.delete_project_audio(filename):
                self._ok()
            else:
                self._json_error(404, "not found")
            return
        self._json_error(404, "not found")

    def _handle_audio_upload(self):
        params = self._query_params()
        try:
            di = int(params.get("device", "-1"))
        except ValueError:
            di = -1
        path = unquote(str(params.get("path", "/")).strip())
        if not (0 <= di < len(self.controller_state.devices)):
            self._json_error(400, "invalid device index")
            return
        if not _safe_ftp_path(path):
            self._json_error(400, "invalid path")
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        data = self.rfile.read(length) if length else b""
        if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            self._json_error(400, "not a WAV file - device requires PCM WAV format")
            return
        try:
            self.controller_state.ftp_upload(di, path, data)
            self._ok()
        except Exception as exc:
            self._json_error(500, str(exc))

    def _handle_project_audio_upload(self):
        params = self._query_params()
        filename = unquote(params.get("filename", "")).strip()
        if not filename:
            self._json_error(400, "filename required")
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        data = self.rfile.read(length) if length else b""
        if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            self._json_error(400, "not a WAV file - device requires PCM WAV format")
            return
        try:
            saved = _audio_cues_mod.save_project_audio(filename, data)
            self._json_response({"name": saved, "size": len(data)})
        except Exception as exc:
            self._json_error(500, str(exc))

    def _handle_audio_cues_import(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            self._json_error(400, "empty body")
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json_error(400, "invalid JSON")
            return
        if not isinstance(payload, dict) or "cues" not in payload:
            self._json_error(400, "missing cues key")
            return
        with self.audio_cues_lock:
            Handler.audio_cues_data = payload
            _audio_cues_mod.save_audio_cues(payload)
        self._json_response(payload)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _query_params(self):
        query = self.path.split("?", 1)[-1] if "?" in self.path else ""
        params = {}
        for part in query.split("&"):
            if not part:
                continue
            if "=" in part:
                key, value = part.split("=", 1)
            else:
                key, value = part, ""
            params[key] = value
        return params

    def _json_response(self, payload):
        body = json.dumps(payload, separators=(",", ":")).encode()
        self._respond(200, "application/json", body)

    def _ok(self):
        self._respond(200, "application/json", b'{"ok":true}')

    def _respond(self, code, content_type, body):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"
        if path == "/index.html":
            file_path = index_html_path()
        else:
            rel = path.lstrip("/")
            file_path = os.path.join(_WEB_DIR, rel)
        if not os.path.abspath(file_path).startswith(os.path.abspath(_WEB_DIR)):
            self.send_error(403)
            return
        if not os.path.isfile(file_path):
            self.send_error(404)
            return
        mime, _ = mimetypes.guess_type(file_path)
        with open(file_path, "rb") as f:
            body = f.read()
        self._respond(200, mime or "application/octet-stream", body)

    def log_message(self, fmt, *args):
        return


def _run_sync_job(job, state, cues_data):
    """Background thread: push project library files to connected Radius nodes."""
    try:
        project_files = {f["name"]: f for f in _audio_cues_mod.list_project_audio()}
        source_ip = state.artnet_source_ip

        with state.lock:
            devices_snap = [
                {
                    "ip": d["ip"],
                    "name": d.get("name", d["ip"]),
                    "is_radius": d.get("is_radius", False),
                    "connected": d.get("connected", False),
                }
                for d in state.devices
            ]

        radius_devs = [d for d in devices_snap if d["is_radius"]]
        if not radius_devs:
            with _sync_lock:
                job["status"] = "done"
            return

        for dev in radius_devs:
            if dev["connected"]:
                try:
                    send_audio_cmd(dev["ip"], AUDIO_CMD_STOP, source_ip=source_ip)
                except Exception:
                    pass
        time.sleep(0.3)

        with _sync_lock:
            job["status"] = "running"

        for dev in radius_devs:
            ip = dev["ip"]
            dev_name = dev["name"]
            connected = dev["connected"]

            if not connected:
                with _sync_lock:
                    job["items"].append({
                        "device_ip": ip,
                        "device_name": dev_name,
                        "filename": None,
                        "bytes_total": 0,
                        "bytes_sent": 0,
                        "status": "skipped",
                        "error": "device not connected",
                    })
                continue

            needed = set()
            for cue in cues_data.get("cues", []):
                action = cue.get("actions", {}).get(ip)
                if action and action.get("cmd") in ("play", "loop"):
                    fname = str(action.get("filename", "")).strip()
                    if fname:
                        needed.add(fname)

            if not needed:
                with _sync_lock:
                    job["items"].append({
                        "device_ip": ip,
                        "device_name": dev_name,
                        "filename": None,
                        "bytes_total": 0,
                        "bytes_sent": 0,
                        "status": "skipped",
                        "error": "no files required by cues",
                    })
                continue

            try:
                entries = ftp_list_dir(ip, "/", source_ip=source_ip)
                on_device = {e["name"] for e in entries if not e["is_dir"]}
            except Exception as exc:
                for fname in sorted(needed):
                    with _sync_lock:
                        job["items"].append({
                            "device_ip": ip,
                            "device_name": dev_name,
                            "filename": fname,
                            "bytes_total": project_files.get(fname, {}).get("size", 0),
                            "bytes_sent": 0,
                            "status": "error",
                            "error": f"FTP list failed: {exc}",
                        })
                continue

            device_items = []
            for fname in sorted(needed):
                if fname in on_device:
                    continue
                item = {
                    "device_ip": ip,
                    "device_name": dev_name,
                    "filename": fname,
                    "bytes_total": project_files.get(fname, {}).get("size", 0),
                    "bytes_sent": 0,
                    "status": "pending",
                    "error": None,
                }
                if fname not in project_files:
                    item["status"] = "skipped"
                    item["error"] = "not in project library"
                device_items.append(item)

            with _sync_lock:
                job["items"].extend(device_items)

            for item in device_items:
                if item["status"] != "pending":
                    continue
                fname = item["filename"]
                file_path = _audio_cues_mod.get_project_audio_path(fname)
                if not file_path:
                    item["status"] = "error"
                    item["error"] = "file missing from project library"
                    continue
                try:
                    with open(file_path, "rb") as handle:
                        data = handle.read()
                except OSError as exc:
                    item["status"] = "error"
                    item["error"] = str(exc)
                    continue

                item["status"] = "uploading"
                item["bytes_total"] = len(data)
                item["bytes_sent"] = 0

                def _progress(sent, total, _item=item):
                    _item["bytes_sent"] = sent

                try:
                    ftp_upload(ip, f"/{fname}", data, source_ip=source_ip,
                               progress_callback=_progress)
                    item["bytes_sent"] = len(data)
                    item["status"] = "done"
                except Exception as exc:
                    item["status"] = "error"
                    item["error"] = str(exc)
                    netlog.log("OUT", "ftp_sync", f"sync failed {fname} → {ip}: {exc}")

        with _sync_lock:
            job["status"] = "done"
    except Exception as exc:
        with _sync_lock:
            job["status"] = "error"
            job["error"] = str(exc)


def create_server(host, port, controller_state, ui_lifecycle_enabled=False):
    Handler.controller_state = controller_state
    Handler.audio_cues_data = _audio_cues_mod.load_audio_cues()
    server = HTTPServer((host, port), Handler)
    server.ui_lifecycle_enabled = ui_lifecycle_enabled
    server.ui_lifecycle_started_at = time.monotonic()
    server.ui_last_heartbeat = None
    server.ui_close_requested_at = None
    return server
