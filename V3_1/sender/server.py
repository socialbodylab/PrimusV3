"""
server.py — HTTP server serving static files and JSON API.
"""

import json
import os
import re
import mimetypes
import threading
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote

import clips
import mixer
import netlog
import audio_cues as _audio_cues_mod
from artnet import discover_artnet_nodes, ftp_list_dir, ftp_upload


# ── Sync job state ──────────────────────────────────────────────────────────
_sync_lock = threading.Lock()
_sync_job   = None   # dict or None; mutated in place by background thread


_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
_SAFE_ID_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


def _safe_id(value):
    """Return True if value is a safe resource identifier (no path traversal)."""
    return bool(value) and bool(_SAFE_ID_RE.match(value))


def _safe_ftp_path(path):
    """Return True if path is a safe absolute FTP path (no traversal)."""
    if not isinstance(path, str) or not path.startswith("/") or "\x00" in path:
        return False
    for part in path.split("/"):
        if part == "..":
            return False
    return True


class Handler(BaseHTTPRequestHandler):
    controller_state = None
    cue_list         = None
    audio_cues_data  = {"cues": []}
    audio_cues_lock  = threading.Lock()

    # ------------------------------------------------------------------
    #  GET
    # ------------------------------------------------------------------

    def do_GET(self):
        path = self.path.split("?")[0]

        # API routes
        if path == "/api/state":
            self._json_response(self.controller_state.get_json())
            return
        if path == "/api/clips":
            params = self._query_params()
            result = clips.list_clips(
                filter_type=params.get("type"),
                search=params.get("search"),
                sort_by=params.get("sort", "modified"),
            )
            self._json_response(result)
            return
        if path.startswith("/api/clips/"):
            clip_id = path.split("/api/clips/")[1]
            if not _safe_id(clip_id):
                self._respond(400, "application/json", b'{"error":"invalid id"}')
                return
            clip = clips.load_clip(clip_id)
            if clip:
                self._json_response(clip)
            else:
                self._respond(404, "application/json", b'{"error":"not found"}')
            return
        if path == "/api/looks":
            result = mixer.list_looks()
            self._json_response(result)
            return
        if path.startswith("/api/looks/"):
            look_id = path.split("/api/looks/")[1]
            if not _safe_id(look_id):
                self._respond(400, "application/json", b'{"error":"invalid id"}')
                return
            look = mixer.load_look(look_id)
            if look:
                self._json_response(look)
            else:
                self._respond(404, "application/json", b'{"error":"not found"}')
            return
        if path == "/api/cues":
            self._json_response(self.cue_list.get_json())
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
            self.send_header("Content-Disposition",
                             'attachment; filename="audio_cues.json"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/netlog":
            params = self._query_params()
            try:
                since = int(params.get("since", 0))
            except (ValueError, TypeError):
                since = 0
            entries = netlog.get_entries(since_id=since)
            self._json_response({"entries": entries})
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

        # Static files
        if path == "/" or path == "":
            path = "/index.html"
        self._serve_static(path)

    # ------------------------------------------------------------------
    #  POST
    # ------------------------------------------------------------------

    def do_POST(self):
        path = self.path.split("?")[0]

        # Binary uploads: handle before _read_json() consumes the body
        if path == "/api/audio/upload":
            self._handle_audio_upload()
            return
        if path == "/api/project_audio":
            self._handle_project_audio_upload()
            return
        if path == "/api/audio_cues/import":
            self._handle_audio_cues_import()
            return

        data = self._read_json()
        if data is None:
            self._respond(400, "application/json", b'{"error":"invalid JSON"}')
            return

        if path == "/api/update":
            self.controller_state.update(data)
            self._ok()

        elif path == "/api/connect":
            di = data.get("device", 0)
            if 0 <= di < len(self.controller_state.devices):
                self.controller_state.connect(di)
                self._ok()
            else:
                self._respond(400, "application/json", b'{"error":"invalid device index"}')

        elif path == "/api/disconnect":
            di = data.get("device", 0)
            if 0 <= di < len(self.controller_state.devices):
                self.controller_state.disconnect(di)
                self._ok()
            else:
                self._respond(400, "application/json", b'{"error":"invalid device index"}')

        elif path == "/api/connect_all":
            self.controller_state.connect_all()
            self._ok()

        elif path == "/api/disconnect_all":
            self.controller_state.disconnect_all()
            self._ok()

        elif path == "/api/discover":
            known_ips = [d["ip"] for d in self.controller_state.devices]
            nodes = discover_artnet_nodes(known_ips=known_ips, timeout=2.0)
            self._json_response(nodes)

        elif path == "/api/add_discovered":
            result = self.controller_state.add_device_from_node(data)
            if result.get("status") == "added":
                self.controller_state.connect(result["device_index"])
            self._json_response(result)

        elif path == "/api/add_manual":
            ip = str(data.get("ip", "")).strip()
            if not ip:
                self._respond(400, "application/json",
                              b'{"error":"ip required"}')
                return
            # Try unicast discovery first to get node info
            nodes = discover_artnet_nodes(known_ips=[ip], timeout=2.0)
            node = next((n for n in nodes if n["ip"] == ip), None)
            if node:
                result = self.controller_state.add_device_from_node(node)
            else:
                # No reply -- add as bare device with default outputs
                result = self.controller_state.add_device_from_node({
                    "ip": ip,
                    "short_name": ip,
                    "long_name": "",
                    "num_ports": 0,
                    "universes": [0, 1],
                })
            if result.get("status") == "added":
                self.controller_state.connect(result["device_index"])
            self._json_response(result)

        elif path == "/api/remove_device":
            di = data.get("device", -1)
            self.controller_state.remove_device(di)
            self._ok()

        elif path == "/api/rename_node":
            di = data.get("device", -1)
            new_name = str(data.get("name", ""))[:17]
            if new_name:
                self.controller_state.rename_device(di, new_name)
            self._ok()

        elif path == "/api/hello_device":
            di = data.get("device", -1)
            try:
                volume = max(0, min(100, int(data.get("volume", 80))))
            except (TypeError, ValueError):
                volume = 80
            threading.Thread(
                target=self.controller_state.hello_device,
                args=(di, volume), daemon=True).start()
            self._ok()

        elif path == "/api/clip/preview":
            clip_id = data.get("clip_id")
            try:
                t = float(data.get("t", 0))
            except (TypeError, ValueError):
                t = 0.0
            clip = clips.load_clip(clip_id) if clip_id else None
            if not clip:
                self._respond(404, "application/json", b'{"error":"not found"}')
            else:
                result = clips.compute_clip_preview(clip, t)
                self._json_response(result)

        # -- Clip routes --
        elif path == "/api/clips/save":
            if "outputs" in data:
                saved = clips.save_from_designer(
                    data.get("name", "Untitled"), data["outputs"])
                self._json_response(saved)
            else:
                clip = clips.save_clip(data)
                self._json_response(clip)

        elif path == "/api/clips/save_single":
            clip = clips.save_clip(data)
            self._json_response(clip)

        # -- Look routes --
        elif path == "/api/looks/save":
            look = mixer.save_look(data)
            self._json_response(look)

        # -- Cue routes --
        elif path == "/api/cues":
            self.cue_list.set_cues(data.get("cues", []))
            self._json_response(self.cue_list.get_json())

        elif path == "/api/cues/go":
            self.controller_state.set_playback_source("controller")
            groups = self.controller_state.get_device_groups()
            cue = self.cue_list.go(device_groups=groups)
            self._json_response({"cue": cue})

        elif path == "/api/cues/stop":
            self.cue_list.stop()
            self._ok()

        elif path == "/api/cues/goto":
            number = data.get("number", 1)
            self.controller_state.set_playback_source("controller")
            groups = self.controller_state.get_device_groups()
            cue = self.cue_list.go_to_cue(number, device_groups=groups)
            self._json_response({"cue": cue})

        # -- Controller routes (control panel) --
        elif path == "/api/controller/activate":
            look_id = data.get("look_id")
            try:
                fade_time = float(data.get("fade_time", 0))
            except (TypeError, ValueError):
                fade_time = 0.0
            if not look_id:
                self._respond(400, "application/json",
                              b'{"error":"look_id required"}')
            else:
                self.controller_state.set_playback_source("controller")
                ok = self.cue_list.activate_look(look_id, fade_time)
                self._json_response({"ok": ok})

        elif path == "/api/controller/blackout":
            try:
                fade_time = float(data.get("fade_time", 0))
            except (TypeError, ValueError):
                fade_time = 0.0
            self.cue_list.blackout(fade_time)
            self._ok()

        elif path == "/api/mixer/preview":
            # Start previewing a look on connected devices
            look = data
            if look and look.get("tracks"):
                device_filter = look.pop("device_filter", None)
                self.controller_state.start_mixer_preview(look, device_filter)
                self._ok()
            else:
                self._respond(400, "application/json", b'{"error":"invalid look"}')

        elif path == "/api/mixer/stop_preview":
            self.controller_state.stop_mixer_preview()
            self._ok()

        elif path == "/api/set_playback_source":
            source = data.get("source", "idle")
            if source in ("designer", "idle", "controller"):
                self.controller_state.set_playback_source(source)
                self._ok()
            else:
                self._respond(400, "application/json",
                              b'{"error":"invalid source"}')

        elif path == "/api/device_groups":
            group = self.controller_state.save_device_group(data)
            self._json_response(group)

        elif path == "/api/audio/cmd":
            di = data.get("device", -1)
            cmd = str(data.get("cmd", "stop"))
            filename = str(data.get("filename", ""))
            try:
                volume = max(0, min(100, int(data.get("volume", 100))))
            except (TypeError, ValueError):
                volume = 100
            ok = self.controller_state.send_audio_command(di, cmd, filename, volume)
            if ok:
                self._ok()
            else:
                self._respond(400, "application/json", b'{"error":"invalid device index"}')

        elif path == "/api/audio/files":
            di = data.get("device", -1)
            ftp_path = str(data.get("path", "/"))
            if not (0 <= di < len(self.controller_state.devices)):
                self._respond(400, "application/json", b'{"error":"invalid device index"}')
            elif not _safe_ftp_path(ftp_path):
                self._respond(400, "application/json", b'{"error":"invalid path"}')
            else:
                try:
                    entries = self.controller_state.ftp_list_dir(di, ftp_path)
                    self._json_response({"entries": entries or []})
                except Exception as e:
                    self._respond(500, "application/json",
                                  json.dumps({"error": str(e)}).encode())

        elif path == "/api/audio/rename":
            di = data.get("device", -1)
            src = str(data.get("src", ""))
            dst = str(data.get("dst", ""))
            if not (0 <= di < len(self.controller_state.devices)):
                self._respond(400, "application/json", b'{"error":"invalid device index"}')
            elif not _safe_ftp_path(src) or not _safe_ftp_path(dst):
                self._respond(400, "application/json", b'{"error":"invalid path"}')
            else:
                try:
                    self.controller_state.ftp_rename(di, src, dst)
                    self._ok()
                except Exception as e:
                    self._respond(500, "application/json",
                                  json.dumps({"error": str(e)}).encode())

        elif path == "/api/audio/delete":
            di = data.get("device", -1)
            ftp_path = str(data.get("path", ""))
            is_dir = bool(data.get("is_dir", False))
            if not (0 <= di < len(self.controller_state.devices)):
                self._respond(400, "application/json", b'{"error":"invalid device index"}')
            elif not _safe_ftp_path(ftp_path):
                self._respond(400, "application/json", b'{"error":"invalid path"}')
            else:
                try:
                    self.controller_state.ftp_delete(di, ftp_path, is_dir=is_dir)
                    self._ok()
                except Exception as e:
                    self._respond(500, "application/json",
                                  json.dumps({"error": str(e)}).encode())

        elif path == "/api/audio/mkdir":
            di = data.get("device", -1)
            ftp_path = str(data.get("path", ""))
            if not (0 <= di < len(self.controller_state.devices)):
                self._respond(400, "application/json", b'{"error":"invalid device index"}')
            elif not _safe_ftp_path(ftp_path):
                self._respond(400, "application/json", b'{"error":"invalid path"}')
            else:
                try:
                    self.controller_state.ftp_mkdir(di, ftp_path)
                    self._ok()
                except Exception as e:
                    self._respond(500, "application/json",
                                  json.dumps({"error": str(e)}).encode())

        # ── Audio cues ─────────────────────────────────────────────────
        elif path == "/api/audio_cues":
            with self.audio_cues_lock:
                Handler.audio_cues_data = data
                _audio_cues_mod.save_audio_cues(data)
            self._json_response(data)

        elif path == "/api/audio_cues/fire":
            number = data.get("number")
            with self.audio_cues_lock:
                cues = self.audio_cues_data.get("cues", [])
            cue = next((c for c in cues if c.get("number") == number), None)
            if cue is None:
                self._respond(404, "application/json", b'{"error":"cue not found"}')
            else:
                results = self.controller_state.fire_audio_cue(cue)
                self._json_response({"results": results})

        elif path == "/api/audio_sync":
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

        # ── Net log ────────────────────────────────────────────────────
        elif path == "/api/netlog/clear":
            netlog.clear()
            self._ok()

        else:
            self._respond(404, "application/json", b'{"error":"not found"}')

    # ------------------------------------------------------------------
    #  DELETE
    # ------------------------------------------------------------------

    def do_DELETE(self):
        path = self.path
        if path.startswith("/api/clips/"):
            clip_id = path.split("/api/clips/")[1]
            if not _safe_id(clip_id):
                self._respond(400, "application/json", b'{"error":"invalid id"}')
                return
            clips.delete_clip(clip_id)
            self._ok()
        elif path.startswith("/api/looks/"):
            look_id = path.split("/api/looks/")[1]
            if not _safe_id(look_id):
                self._respond(400, "application/json", b'{"error":"invalid id"}')
                return
            mixer.delete_look(look_id)
            self._ok()
        elif path.startswith("/api/device_groups/"):
            gid = path.split("/api/device_groups/")[1]
            if not _safe_id(gid):
                self._respond(400, "application/json", b'{"error":"invalid id"}')
                return
            self.controller_state.delete_device_group(gid)
            self._ok()
        elif path.startswith("/api/project_audio/"):
            filename = unquote(path.split("/api/project_audio/")[1])
            if not filename or "/" in filename or "\x00" in filename:
                self._respond(400, "application/json", b'{"error":"invalid filename"}')
                return
            ok = _audio_cues_mod.delete_project_audio(filename)
            if ok:
                self._ok()
            else:
                self._respond(404, "application/json", b'{"error":"not found"}')
        else:
            self._respond(404, "application/json", b'{"error":"not found"}')

    def _handle_audio_upload(self):
        params = self._query_params()
        try:
            di = int(params.get("device", -1))
        except (TypeError, ValueError):
            di = -1
        ftp_path = unquote(params.get("path", ""))
        if not (0 <= di < len(self.controller_state.devices)):
            self._respond(400, "application/json", b'{"error":"invalid device index"}')
            return
        if not _safe_ftp_path(ftp_path):
            self._respond(400, "application/json", b'{"error":"invalid path"}')
            return
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self._respond(400, "application/json", b'{"error":"empty upload"}')
            return
        file_data = self.rfile.read(length)
        if len(file_data) < 12 or file_data[:4] != b'RIFF' or file_data[8:12] != b'WAVE':
            self._respond(400, "application/json",
                          b'{"error":"not a WAV file - device requires PCM WAV format"}')
            return
        try:
            self.controller_state.ftp_upload(di, ftp_path, file_data)
            self._ok()
        except Exception as e:
            self._respond(500, "application/json",
                          json.dumps({"error": str(e)}).encode())

    def _handle_project_audio_upload(self):
        """POST /api/project_audio  (binary WAV body, ?filename=<name>)"""
        params = self._query_params()
        filename = unquote(params.get("filename", "")).strip()
        if not filename:
            self._respond(400, "application/json", b'{"error":"filename required"}')
            return
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self._respond(400, "application/json", b'{"error":"empty upload"}')
            return
        file_data = self.rfile.read(length)
        if len(file_data) < 12 or file_data[:4] != b'RIFF' or file_data[8:12] != b'WAVE':
            self._respond(400, "application/json",
                          b'{"error":"not a WAV file - device requires PCM WAV format"}')
            return
        try:
            saved = _audio_cues_mod.save_project_audio(filename, file_data)
            self._json_response({"name": saved, "size": len(file_data)})
        except Exception as e:
            self._respond(500, "application/json",
                          json.dumps({"error": str(e)}).encode())

    def _handle_audio_cues_import(self):
        """POST /api/audio_cues/import  (JSON body — replaces current cue sheet)"""
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self._respond(400, "application/json", b'{"error":"empty body"}')
            return
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            self._respond(400, "application/json", b'{"error":"invalid JSON"}')
            return
        if not isinstance(data, dict) or "cues" not in data:
            self._respond(400, "application/json",
                          b'{"error":"missing cues key"}')
            return
        with self.audio_cues_lock:
            Handler.audio_cues_data = data
            _audio_cues_mod.save_audio_cues(data)
        self._json_response(data)

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            try:
                return json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, ValueError):
                return None
        return {}

    def _query_params(self):
        params = {}
        if "?" in self.path:
            qs = self.path.split("?", 1)[1]
            for part in qs.split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    params[k] = v
        return params

    def _json_response(self, obj):
        body = json.dumps(obj, separators=(",", ":")).encode()
        self._respond(200, "application/json", body)

    def _ok(self):
        self._respond(200, "application/json", b'{"ok":true}')

    def _respond(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, url_path):
        # Sanitize: prevent directory traversal
        clean = os.path.normpath(url_path.lstrip("/"))
        if clean.startswith("..") or os.path.isabs(clean):
            self._respond(403, "text/plain", b"Forbidden")
            return
        file_path = os.path.join(_WEB_DIR, clean)
        if not os.path.isfile(file_path):
            self._respond(404, "text/plain", b"Not Found")
            return
        ctype, _ = mimetypes.guess_type(file_path)
        if ctype is None:
            ctype = "application/octet-stream"
        with open(file_path, "rb") as f:
            body = f.read()
        self._respond(200, ctype, body)

    def log_message(self, fmt, *args):
        pass


def _run_sync_job(job, state, cues_data):
    """Background thread: build sync plan then upload missing files."""
    try:
        project_files = {f["name"]: f for f in _audio_cues_mod.list_project_audio()}

        with state.lock:
            devices_snap = [
                {
                    "ip":        d["ip"],
                    "name":      d["name"],
                    "is_audio":  d.get("is_audio", False),
                    "connected": d["sender"].connected,
                }
                for d in state.devices
            ]

        radius_devs = [d for d in devices_snap if d["is_audio"]]

        if not radius_devs:
            with _sync_lock:
                job["status"] = "done"
            return

        with _sync_lock:
            job["status"] = "running"

        for dev in radius_devs:
            ip        = dev["ip"]
            dev_name  = dev["name"]
            connected = dev["connected"]

            if not connected:
                with _sync_lock:
                    job["items"].append({
                        "device_ip":   ip,
                        "device_name": dev_name,
                        "filename":    None,
                        "bytes_total": 0,
                        "bytes_sent":  0,
                        "status":      "skipped",
                        "error":       "device not connected",
                    })
                continue

            # Collect filenames this device needs across all cues
            needed = set()
            for cue in cues_data.get("cues", []):
                action = cue.get("actions", {}).get(ip)
                if action and action.get("cmd") in ("play", "loop"):
                    fname = action.get("filename", "").strip()
                    if fname:
                        needed.add(fname)

            if not needed:
                with _sync_lock:
                    job["items"].append({
                        "device_ip":   ip,
                        "device_name": dev_name,
                        "filename":    None,
                        "bytes_total": 0,
                        "bytes_sent":  0,
                        "status":      "skipped",
                        "error":       "no files required by cues",
                    })
                continue

            # FTP list the device
            try:
                entries   = ftp_list_dir(ip, "/")
                on_device = {e["name"] for e in entries if not e["is_dir"]}
            except Exception as e:
                for fname in sorted(needed):
                    with _sync_lock:
                        job["items"].append({
                            "device_ip":   ip,
                            "device_name": dev_name,
                            "filename":    fname,
                            "bytes_total": project_files.get(fname, {}).get("size", 0),
                            "bytes_sent":  0,
                            "status":      "error",
                            "error":       f"FTP list failed: {e}",
                        })
                continue

            # Build per-file plan items for this device
            device_items = []
            for fname in sorted(needed):
                if fname in on_device:
                    continue  # already present — nothing to do
                item = {
                    "device_ip":   ip,
                    "device_name": dev_name,
                    "filename":    fname,
                    "bytes_total": project_files.get(fname, {}).get("size", 0),
                    "bytes_sent":  0,
                    "status":      "pending",
                    "error":       None,
                }
                if fname not in project_files:
                    item["status"] = "skipped"
                    item["error"]  = "not in project library"
                device_items.append(item)

            with _sync_lock:
                job["items"].extend(device_items)

            # Upload pending items for this device
            for item in device_items:
                if item["status"] != "pending":
                    continue
                fname = item["filename"]
                path  = _audio_cues_mod.get_project_audio_path(fname)
                if not path:
                    item["status"] = "error"
                    item["error"]  = "file missing from project library"
                    continue
                try:
                    with open(path, "rb") as f:
                        data = f.read()
                except OSError as e:
                    item["status"] = "error"
                    item["error"]  = str(e)
                    continue

                item["status"]      = "uploading"
                item["bytes_total"] = len(data)
                item["bytes_sent"]  = 0

                def _progress(sent, total, _item=item):
                    _item["bytes_sent"] = sent

                try:
                    ftp_upload(ip, f"/{fname}", data, progress_callback=_progress)
                    item["bytes_sent"] = len(data)
                    item["status"]     = "done"
                except Exception as e:
                    item["status"] = "error"
                    item["error"]  = str(e)
                    netlog.log("OUT", "ftp_sync",
                               f"sync failed {fname} → {ip}: {e}")

        with _sync_lock:
            job["status"] = "done"

    except Exception as e:
        with _sync_lock:
            job["status"] = "error"
            job["error"]  = str(e)


def create_server(host, port, controller_state, cue_list):
    """Create and return an HTTPServer bound to host:port."""
    Handler.controller_state = controller_state
    Handler.cue_list         = cue_list
    Handler.audio_cues_data  = _audio_cues_mod.load_audio_cues()
    return HTTPServer((host, port), Handler)
