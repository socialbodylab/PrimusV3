"""
server.py — HTTP server serving static files and JSON API.
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
import clips
from firmware import FirmwareRequestError, firmware_jobs
import mixer
import netlog
import sharing
from artnet import discover_artnet_nodes, ftp_list_dir, ftp_upload, ftp_download, send_audio_cmd
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
from paths import web_dir
from state import OUTPUT_TYPES, ControllerState


_WEB_DIR = web_dir()
_SAFE_ID_RE = re.compile(r'^[a-zA-Z0-9_-]+$')

_sync_lock       = threading.Lock()
_sync_job        = None

_inventory_lock  = threading.Lock()
_device_inventory = {}   # {ip: {name, files: [str], scanned_at: float}}


def _is_audio_file(name):
    """True if name is a playable WAV file (not a macOS metadata stub)."""
    return name.lower().endswith(".wav") and not name.startswith("._")


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
    cue_list = None
    audio_cues_data = {"cues": []}
    audio_cues_lock = threading.Lock()

    def _osc_service(self):
        return getattr(self.server, "osc_service", None)

    def _leave_controller_runtime(self, preserve_selection=True):
        if self.cue_list is not None:
            self.cue_list.release_output(preserve_selection=preserve_selection)

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

    # ------------------------------------------------------------------
    #  GET
    # ------------------------------------------------------------------

    def do_GET(self):
        path = self.path.split("?")[0]

        # API routes
        if path == "/api/runtime":
            self._json_response({
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
        if path == "/api/clips":
            params = self._query_params()
            result = clips.list_clips(
                filter_type=params.get("type"),
                search=params.get("search"),
                sort_by=params.get("sort", "modified"),
            )
            self._json_response(result)
            return
        if path.startswith("/api/clips/") and path.endswith("/export"):
            clip_id = path[len("/api/clips/"):-len("/export")]
            if not _safe_id(clip_id):
                self._respond(400, "application/json", b'{"error":"invalid id"}')
                return
            bundle = sharing.export_clip_bundle(clip_id)
            if not bundle:
                self._respond(404, "application/json", b'{"error":"not found"}')
                return
            self._json_download_response(bundle, sharing.export_filename(bundle))
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
        if path.startswith("/api/looks/") and path.endswith("/export"):
            look_id = path[len("/api/looks/"):-len("/export")]
            if not _safe_id(look_id):
                self._respond(400, "application/json", b'{"error":"invalid id"}')
                return
            bundle = sharing.export_look_bundle(look_id)
            if not bundle:
                self._respond(404, "application/json", b'{"error":"not found"}')
                return
            self._json_download_response(bundle, sharing.export_filename(bundle))
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
        if path == "/api/integrations/osc":
            service = self._osc_service()
            if service is None:
                self._json_error(503, "OSC service unavailable")
            else:
                self._json_response(service.status())
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
        if path == "/api/audio/cue_map":
            params = self._query_params()
            try:
                di = int(params.get("device", -1))
            except (ValueError, TypeError):
                di = -1
            devices = self.controller_state.devices
            if not (0 <= di < len(devices)) or not devices[di].get("is_audio"):
                self._respond(400, "application/json", b'{"error":"invalid device index"}')
                return
            ip = devices[di]["ip"]
            try:
                raw = ftp_download(ip, "/cues.json")
                self._json_response(json.loads(raw.decode()))
            except Exception as e:
                self._respond(500, "application/json",
                              json.dumps({"error": str(e)}).encode())
            return
        if path == "/api/audio_sync/status":
            with _sync_lock:
                job = dict(_sync_job) if _sync_job else None
                if job:
                    job = dict(job)
                    job["items"]     = list(job.get("items", []))
                    job["conflicts"] = list(job.get("conflicts", []))
                    job["errors"]    = list(job.get("errors", []))
            self._json_response(job or {"status": "idle"})
            return
        if path == "/api/project_audio":
            local_files = _audio_cues_mod.list_project_audio()
            with _inventory_lock:
                inventory = dict(_device_inventory)
            # annotate each local file with which device IPs also have it
            inv_by_ip = {ip: set(v.get("files", [])) for ip, v in inventory.items()}
            for f in local_files:
                sources = ["local"] + [
                    ip for ip, names in inv_by_ip.items() if f["name"] in names
                ]
                f["sources"] = sources
                f["local"]   = True
            # compute inventory age
            ages = [v["scanned_at"] for v in inventory.values() if "scanned_at" in v]
            age = time.time() - min(ages) if ages else None
            self._json_response({
                "files":             local_files,
                "device_inventory":  inventory,
                "inventory_age_seconds": age,
            })
            return
        if path.startswith("/api/"):
            self._json_error(404, "not found")
            return

        # Static files
        if path in ("/", "", "/primus"):
            path = "/index.html"
        elif path == "/radius":
            path = "/radius.html"
        self._serve_static(path)

    # ------------------------------------------------------------------
    #  POST
    # ------------------------------------------------------------------

    def do_POST(self):
        path = self.path.split("?")[0]

        # Binary uploads: handle before _read_json() consumes the body
        if self.path.split("?")[0] == "/api/audio/upload":
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

        if path == "/api/ui/heartbeat":
            if getattr(self.server, "ui_lifecycle_enabled", False):
                self.server.ui_last_heartbeat = time.monotonic()
                self.server.ui_close_requested_at = None
            self._ok()

        elif path == "/api/ui/closed":
            if getattr(self.server, "ui_lifecycle_enabled", False):
                self.server.ui_close_requested_at = time.monotonic()
            self._ok()

        elif path == "/api/update":
            self.controller_state.update(data)
            self._ok()

        elif path == "/api/connect":
            di = data.get("device", 0)
            if 0 <= di < len(self.controller_state.devices):
                ip = self.controller_state.devices[di]["ip"]
                interface = self._sync_artnet_source()
                nodes = discover_artnet_nodes(known_ips=[ip], timeout=1.0, interface=interface)
                node = next((n for n in nodes if n["ip"] == ip), None)
                if node:
                    self.controller_state.add_device_from_node(node)
                result = self.controller_state.connect(di)
                if result.get("ok"):
                    self._ok()
                else:
                    self._json_error(503, result.get("error", "connect failed"))
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
            known_ips = self.controller_state.discovery_targets()
            interface = self._sync_artnet_source()
            nodes = discover_artnet_nodes(known_ips=known_ips, timeout=2.0, interface=interface)
            if nodes:
                self.controller_state.refresh_devices_from_nodes(nodes)
            online_ips = {node.get("ip") for node in nodes if node.get("ip")}
            results = self.controller_state.connect_all(only_ips=online_ips if online_ips else None)
            failed = [r for r in results if not r.get("ok")]
            if failed:
                self._json_error(503, failed[0].get("error", "connect failed"))
            else:
                self._ok()

        elif path == "/api/disconnect_all":
            self.controller_state.disconnect_all()
            self._ok()

        elif path == "/api/discover":
            known_ips = self.controller_state.discovery_targets()
            interface = self._sync_artnet_source()
            nodes = discover_artnet_nodes(known_ips=known_ips, timeout=2.0, interface=interface)
            self.controller_state.refresh_devices_from_nodes(nodes)
            self._json_response(nodes)

        elif path == "/api/add_discovered":
            self._sync_artnet_source()
            result = self.controller_state.add_device_from_node(data)
            if result.get("device_index") is not None:
                connect_result = self.controller_state.connect(result["device_index"])
                if not connect_result.get("ok"):
                    result["connect_error"] = connect_result.get("error")
            self._json_response(result)

        elif path == "/api/add_manual":
            ip = str(data.get("ip", "")).strip()
            if not ip:
                self._respond(400, "application/json",
                              b'{"error":"ip required"}')
                return
            # Try unicast discovery first to get node info
            interface = self._sync_artnet_source()
            nodes = discover_artnet_nodes(known_ips=[ip], timeout=2.0, interface=interface)
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
            if result.get("device_index") is not None:
                connect_result = self.controller_state.connect(result["device_index"])
                if not connect_result.get("ok"):
                    result["connect_error"] = connect_result.get("error")
            self._json_response(result)

        elif path == "/api/remove_device":
            di = data.get("device", -1)
            self.controller_state.remove_device(di)
            self._ok()

        elif path == "/api/rename_node":
            self._sync_artnet_source()
            di = data.get("device", -1)
            new_name = str(data.get("name", ""))[:17]
            if not new_name:
                self._json_error(400, "name required")
                return
            result = self.controller_state.rename_device(di, new_name)
            if result.get("ok"):
                self._ok()
            else:
                code = 400 if result.get("error") == "invalid device index" else 409
                self._json_error(code, result.get("error", "rename failed"))

        elif path == "/api/hello_device":
            self._sync_artnet_source()
            di = data.get("device", -1)
            status = self.controller_state.device_capability_status(di, "hello")
            if not status.get("ok"):
                code = 400 if status.get("error") == "invalid device index" else 409
                self._json_error(code, status.get("error", "identify failed"))
                return
            if self.controller_state.hello_device(di):
                self._ok()
            else:
                self._json_error(503, "Hello failed; reconnect the device and try again.")

        elif path == "/api/set_device_ip":
            self._sync_artnet_source()
            di = data.get("device", -1)
            static_ip = str(data.get("ip", ""))
            gateway = str(data.get("gateway", ""))
            subnet = str(data.get("subnet", ""))
            if not (static_ip and gateway and subnet):
                self._json_error(400, "ip, gateway, and subnet required")
                return
            result = self.controller_state.set_device_ip(di, static_ip, gateway, subnet)
            if result.get("ok"):
                self._ok()
            else:
                error = result.get("error", "IP update failed")
                code = 400 if result.get("error") == "invalid device index" or "invalid" in error.lower() else 409
                self._json_error(code, error)

        elif path == "/api/revert_device_dhcp":
            self._sync_artnet_source()
            di = data.get("device", -1)
            result = self.controller_state.revert_device_dhcp(di)
            if result.get("ok"):
                self._ok()
            else:
                code = 400 if result.get("error") == "invalid device index" else 409
                self._json_error(code, result.get("error", "DHCP revert failed"))

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

        elif path == "/api/import_bundle":
            try:
                self._json_response(sharing.import_bundle(data))
            except ValueError as exc:
                self._json_error(400, str(exc))

        # -- Look routes --
        elif path == "/api/looks/save":
            look = mixer.save_look(data)
            self._json_response(look)

        # -- Cue routes --
        elif path == "/api/cues":
            self.cue_list.set_cues(data.get("cues", []))
            self._json_response(self.cue_list.get_json())

        elif path == "/api/cues/go":
            groups = self.controller_state.get_device_groups()
            cue = self.cue_list.go(device_groups=groups)
            if cue is not None:
                self.controller_state.set_playback_source(ControllerState.SOURCE_CONTROLLER)
            self._json_response({"cue": cue})

        elif path == "/api/cues/stop":
            self._leave_controller_runtime(preserve_selection=True)
            self.controller_state.set_playback_source(ControllerState.SOURCE_IDLE)
            self._ok()

        elif path == "/api/cues/goto":
            number = data.get("number", 1)
            groups = self.controller_state.get_device_groups()
            cue = self.cue_list.go_to_cue(number, device_groups=groups)
            if cue is not None:
                self.controller_state.set_playback_source(ControllerState.SOURCE_CONTROLLER)
            self._json_response({"cue": cue})

        elif path == "/api/integrations/osc":
            service = self._osc_service()
            if service is None:
                self._json_error(503, "OSC service unavailable")
            else:
                self._json_response(service.update(data))

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
                ok = self.cue_list.activate_look(look_id, fade_time)
                if ok:
                    self.controller_state.set_playback_source(ControllerState.SOURCE_CONTROLLER)
                self._json_response({"ok": ok})

        elif path == "/api/controller/activate_many":
            look_ids = data.get("look_ids", [])
            try:
                fade_time = float(data.get("fade_time", 0))
            except (TypeError, ValueError):
                fade_time = 0.0
            if not isinstance(look_ids, list) or not look_ids:
                self._json_error(400, "look_ids required")
            else:
                ok = self.cue_list.activate_looks(look_ids, fade_time)
                if ok:
                    self.controller_state.set_playback_source(ControllerState.SOURCE_CONTROLLER)
                self._json_response({"ok": ok})

        elif path == "/api/controller/deactivate_look":
            look_id = data.get("look_id")
            if not look_id:
                self._json_error(400, "look_id required")
            else:
                self.cue_list.deactivate_look(str(look_id))
                if not self.cue_list.active_look_ids():
                    self.controller_state.set_playback_source(ControllerState.SOURCE_IDLE)
                self._ok()

        elif path == "/api/controller/blackout":
            try:
                fade_time = float(data.get("fade_time", 0))
            except (TypeError, ValueError):
                fade_time = 0.0
            self.cue_list.blackout(fade_time)
            self.controller_state.set_playback_source(ControllerState.SOURCE_CONTROLLER)
            self._ok()

        elif path == "/api/mixer/frame":
            # Compute a single look frame at time t (for UI preview only)
            look = data.get("look")
            try:
                t = float(data.get("t", 0))
            except (TypeError, ValueError):
                t = 0.0
            if not look or not look.get("tracks"):
                self._respond(400, "application/json",
                              b'{"error":"invalid look"}')
            else:
                frame = mixer.compute_look_frame(look, t)
                outputs_data = []
                look_outputs = look.get("outputs", [])
                for i, pixels in enumerate(frame):
                    otype = look_outputs[i].get("type", "none") if i < len(look_outputs) else "none"
                    typedef = OUTPUT_TYPES.get(otype, {"pixels": 0, "layout": "none"})
                    grid = list(typedef.get("grid_size")) if typedef.get("layout") == "grid" and typedef.get("grid_size") else None
                    outputs_data.append({
                        "pixels": [list(p) for p in pixels],
                        "grid": grid,
                        "type": otype,
                    })
                self._json_response({"outputs": outputs_data})

        elif path == "/api/mixer/preview":
            # Start previewing a look on connected devices
            look = data
            if look and look.get("tracks"):
                self._leave_controller_runtime(preserve_selection=True)
                device_filter = look.pop("device_filter", None)
                play_time = float(look.pop("play_time", 0.0))
                transport_time = float(look.pop("transport_time", play_time))
                playing = bool(look.pop("playing", False))
                seq = look.pop("seq", None)
                if seq is not None:
                    try:
                        seq = int(seq)
                    except (TypeError, ValueError):
                        seq = None
                self.controller_state.start_mixer_preview(
                    look, device_filter, play_time, playing, transport_time, seq=seq)
                self._ok()
            else:
                self._respond(400, "application/json", b'{"error":"invalid look"}')

        elif path == "/api/mixer/update":
            play_time = data.get("play_time")
            transport_time = data.get("transport_time")
            playing = data.get("playing")
            seq = data.get("seq")
            if play_time is not None:
                play_time = float(play_time)
            if transport_time is not None:
                transport_time = float(transport_time)
            if seq is not None:
                try:
                    seq = int(seq)
                except (TypeError, ValueError):
                    seq = None
            update_kwargs = {
                "play_time": play_time,
                "playing": playing,
                "transport_time": transport_time,
                "seq": seq,
            }
            if "device_filter" in data:
                update_kwargs["device_filter"] = data.get("device_filter")
            self.controller_state.update_mixer_preview(**update_kwargs)
            self._ok()

        elif path == "/api/mixer/stop_preview":
            self.controller_state.stop_mixer_preview()
            self._ok()

        elif path == "/api/set_playback_source":
            source = data.get("source", "idle")
            if source in ControllerState.API_PLAYBACK_SOURCES:
                if source != ControllerState.SOURCE_CONTROLLER:
                    self._leave_controller_runtime(preserve_selection=True)
                self.controller_state.set_playback_source(source)
                self._ok()
            else:
                self._respond(400, "application/json",
                              b'{"error":"invalid source"}')

        elif path == "/api/device_groups":
            group = self.controller_state.save_device_group(data)
            self._json_response(group)

        elif path == "/api/firmware/jobs":
            try:
                self._json_response(firmware_jobs.start_job(data))
            except FirmwareRequestError as exc:
                self._json_error(exc.code, exc.message)

        elif path == "/api/network/preferred_interface":
            try:
                result = set_preferred_interface(data)
                interface = result.get("selected_interface")
                source_ip = (interface or {}).get("source_ip") or (interface or {}).get("ipv4")
                self.controller_state.set_artnet_source(source_ip)
                self._json_response(result)
            except NetworkSettingsError as exc:
                self._json_network_error(exc)

        elif path == "/api/network/ssid_profile":
            try:
                self._json_response(save_profile(data))
            except NetworkSettingsError as exc:
                self._json_network_error(exc)

        elif path == "/api/network/controller_connection":
            try:
                result = set_controller_connection(data)
                interface = result.get("selected_interface")
                source_ip = (interface or {}).get("source_ip") or (interface or {}).get("ipv4")
                self.controller_state.set_artnet_source(source_ip)
                self._json_response(result)
            except NetworkSettingsError as exc:
                self._json_network_error(exc)

        elif path == "/api/network/apply_static_ip":
            try:
                result = apply_static_ip(data)
                interface = result.get("selected_interface")
                source_ip = (interface or {}).get("source_ip") or (interface or {}).get("ipv4")
                self.controller_state.set_artnet_source(source_ip)
                self._json_response(result)
            except NetworkSettingsError as exc:
                self._json_network_error(exc)

        elif path == "/api/network/set_dhcp":
            try:
                result = set_dhcp(data)
                interface = result.get("selected_interface")
                source_ip = (interface or {}).get("source_ip") or (interface or {}).get("ipv4")
                self.controller_state.set_artnet_source(source_ip)
                self._json_response(result)
            except NetworkSettingsError as exc:
                self._json_network_error(exc)

        # -- Audio commands (Radius nodes) --
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

        elif path == "/api/audio/cue_map":
            di = data.get("device", -1)
            cues = data.get("cues")
            devices = self.controller_state.devices
            if not (0 <= di < len(devices)) or not devices[di].get("is_audio"):
                self._respond(400, "application/json", b'{"error":"invalid device index"}')
                return
            if not isinstance(cues, dict):
                self._respond(400, "application/json", b'{"error":"cues must be an object"}')
                return
            ip = devices[di]["ip"]
            try:
                raw = json.dumps(cues, indent=2).encode()
                ftp_upload(ip, "/cues.json", raw)
                self._ok()
            except Exception as e:
                self._respond(500, "application/json",
                              json.dumps({"error": str(e)}).encode())

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
                    "job_id":    str(uuid.uuid4())[:8],
                    "type":      "push",
                    "status":    "planning",
                    "items":     [],
                    "conflicts": [],
                    "errors":    [],
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

        elif path == "/api/audio_sync/pull":
            with _sync_lock:
                if _sync_job and _sync_job.get("status") == "running":
                    self._json_response({
                        "error": "sync already running",
                        "job_id": _sync_job["job_id"],
                    })
                    return
                new_job = {
                    "job_id":    str(uuid.uuid4())[:8],
                    "type":      "pull",
                    "status":    "planning",
                    "items":     [],
                    "conflicts": [],
                    "errors":    [],
                }
                _sync_job = new_job

            threading.Thread(
                target=_run_pull_job,
                args=(new_job, self.controller_state),
                daemon=True,
            ).start()
            self._json_response({"job_id": new_job["job_id"]})

        elif path == "/api/audio_sync/rescan":
            threading.Thread(
                target=_run_rescan_job,
                args=(self.controller_state,),
                daemon=True,
            ).start()
            self._ok()

        elif path == "/api/audio_sync/resolve":
            filename    = data.get("filename", "")
            resolutions = data.get("resolutions", [])
            if not filename or not isinstance(resolutions, list):
                self._json_error(400, "filename and resolutions required")
                return
            with _sync_lock:
                job = _sync_job
            if not job:
                self._json_error(400, "no active sync job")
                return
            conflict = next(
                (c for c in job.get("conflicts", []) if c["filename"] == filename),
                None,
            )
            if conflict is None:
                self._json_error(400, f"no conflict for {filename}")
                return
            saved    = []
            discarded = []
            for res in resolutions:
                checksum = res.get("checksum", "")
                action   = res.get("action", "")
                group = next(
                    (g for g in conflict["groups"] if g["checksum"] == checksum),
                    None,
                )
                if group is None:
                    self._json_error(400, f"unknown checksum {checksum}")
                    return
                if action == "discard":
                    if group.get("temp_path"):
                        _audio_cues_mod.discard_project_audio_temp(checksum)
                    discarded.append(checksum)
                elif action == "save":
                    save_as = res.get("save_as", "")
                    if not save_as:
                        self._json_error(400, "save_as required for save action")
                        return
                    try:
                        if group.get("temp_path"):
                            _audio_cues_mod.resolve_project_audio_temp(checksum, save_as)
                        saved.append(save_as)
                    except _audio_cues_mod.ChecksumConflictError as e:
                        self._respond(409, "application/json",
                                      json.dumps({"error": str(e)}).encode())
                        return
                    except FileNotFoundError as e:
                        self._json_error(400, str(e))
                        return
                else:
                    self._json_error(400, f"unknown action {action}")
                    return
            # Remove resolved conflict from job
            with _sync_lock:
                job["conflicts"] = [
                    c for c in job["conflicts"] if c["filename"] != filename
                ]
            self._json_response({"ok": True, "saved": saved, "discarded": discarded})

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
            self.cue_list.deactivate_look(look_id)
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
        """POST /api/audio/upload?device=N&path=/file.wav  (binary WAV body)"""
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

    def _json_download_response(self, obj, filename):
        body = json.dumps(obj, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

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


def _snap_audio_devices(state):
    """Return a list of {ip, name, connected} for all is_audio devices."""
    with state.lock:
        return [
            {
                "ip":        d["ip"],
                "name":      d["name"],
                "connected": d["sender"].connected,
            }
            for d in state.devices
            if d.get("is_audio", False)
        ]


def _stop_all_audio(devices):
    """Send stop command to every device IP and wait 300 ms for SD bus to clear."""
    for dev in devices:
        try:
            send_audio_cmd(dev["ip"], 0)
        except Exception:
            pass
    time.sleep(0.3)


def _update_inventory(devices, entries_by_ip):
    """Update the module-level device inventory cache."""
    now = time.time()
    with _inventory_lock:
        for dev in devices:
            ip = dev["ip"]
            _device_inventory[ip] = {
                "name":       dev["name"],
                "files":      entries_by_ip.get(ip, []),
                "scanned_at": now,
            }


def _run_sync_job(job, state, cues_data):
    """Background thread: build sync plan then upload missing files."""
    try:
        project_files = {f["name"]: f for f in _audio_cues_mod.list_project_audio()}

        devices_snap = _snap_audio_devices(state)
        radius_devs  = [d for d in devices_snap if d["connected"]]

        if not radius_devs:
            with _sync_lock:
                job["status"] = "done"
            return

        with _sync_lock:
            job["status"] = "stopping"
        _stop_all_audio(radius_devs)

        with _sync_lock:
            job["status"] = "running"

        entries_by_ip = {}
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
                entries_by_ip[ip] = sorted(on_device)
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
                    continue  # already present
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

        _update_inventory(radius_devs, entries_by_ip)

        with _sync_lock:
            job["status"] = "done"

    except Exception as e:
        with _sync_lock:
            job["status"] = "error"
            job["error"]  = str(e)


def _run_pull_job(job, state):
    """Background thread: download files from all Radius devices to local library."""
    import hashlib as _hashlib

    def _checksum(data):
        return "sha256:" + _hashlib.sha256(data).hexdigest()

    def _suggested_name(filename, groups):
        base, ext = os.path.splitext(filename)
        # Group with most sources wins the original name
        majority = max(groups, key=lambda g: len(g["sources"]))
        for g in groups:
            if g is majority:
                g["suggested_name"] = filename
            else:
                first_dev = next(
                    (s["device_name"] for s in g["sources"] if s.get("type") == "device"),
                    "unknown",
                )
                slug = first_dev.lower().replace(" ", "-")
                g["suggested_name"] = f"{base}_{slug}{ext}"

    try:
        radius_devs = _snap_audio_devices(state)
        connected   = [d for d in radius_devs if d["connected"]]

        if not connected:
            with _sync_lock:
                job["status"] = "done"
            return

        with _sync_lock:
            job["status"] = "stopping"
        _stop_all_audio(connected)

        with _sync_lock:
            job["status"] = "running"

        # FTP-list all devices — WAV files only, exclude macOS metadata stubs
        listing = {}   # ip → set of filenames
        for dev in connected:
            ip = dev["ip"]
            try:
                entries    = ftp_list_dir(ip, "/")
                listing[ip] = {e["name"] for e in entries if _is_audio_file(e["name"])}
            except Exception as e:
                with _sync_lock:
                    job["errors"].append({
                        "device_ip":   ip,
                        "device_name": dev["name"],
                        "error":       f"FTP list failed: {e}",
                    })

        _update_inventory(connected, {ip: sorted(names) for ip, names in listing.items()})

        # Build filename → [device dicts] map across all devices
        filename_map = {}   # filename → [{ip, name}]
        for dev in connected:
            ip = dev["ip"]
            for fname in listing.get(ip, set()):
                filename_map.setdefault(fname, []).append(dev)

        # Process each filename
        for fname, sources in sorted(filename_map.items()):
            # Download all copies
            downloaded = {}   # checksum → (data, [source_dicts])
            for dev in sources:
                ip       = dev["ip"]
                item = {
                    "filename":       fname,
                    "device_ip":      ip,
                    "device_name":    dev["name"],
                    "bytes_total":    0,
                    "bytes_received": 0,
                    "status":         "downloading",
                }
                with _sync_lock:
                    job["items"].append(item)

                try:
                    def _progress(recv, total, _item=item):
                        _item["bytes_received"] = recv
                        _item["bytes_total"]    = total

                    data = ftp_download(ip, f"/{fname}", progress_callback=_progress)
                    cs   = _checksum(data)
                    item["status"] = "checksumming"

                    if cs in downloaded:
                        downloaded[cs][1].append({"type": "device", "device_ip": ip, "device_name": dev["name"]})
                    else:
                        downloaded[cs] = (data, [{"type": "device", "device_ip": ip, "device_name": dev["name"]}])

                    item["bytes_received"] = item["bytes_total"]
                    item["status"] = "done"

                except Exception as e:
                    item["status"] = "error"
                    item["error"]  = str(e)
                    netlog.log("OUT", "ftp_pull", f"pull failed {fname} from {ip}: {e}")

            if not downloaded:
                continue

            # Check local library
            local_path     = _audio_cues_mod.get_project_audio_path(fname)
            local_checksum = _audio_cues_mod._get_cached_checksum(fname) if local_path else None

            if local_checksum:
                if local_checksum in downloaded:
                    downloaded[local_checksum][1].insert(0, {"type": "local"})
                else:
                    # Read local bytes for staging if needed
                    try:
                        with open(local_path, "rb") as f:
                            local_data = f.read()
                        downloaded[local_checksum] = (local_data, [{"type": "local"}])
                    except OSError:
                        pass

            if len(downloaded) == 1:
                cs, (data, srcs) = next(iter(downloaded.items()))
                has_local = any(s.get("type") == "local" for s in srcs)
                if not has_local:
                    try:
                        _audio_cues_mod.save_project_audio(fname, data)
                    except Exception as e:
                        with _sync_lock:
                            job["errors"].append({"filename": fname, "error": str(e)})
            else:
                # Multiple versions — build conflict groups
                groups = []
                for cs, (data, srcs) in downloaded.items():
                    is_local_group = any(s.get("type") == "local" for s in srcs)
                    temp_path = None
                    if not is_local_group:
                        try:
                            temp_path = _audio_cues_mod.save_project_audio_temp(cs, data)
                        except Exception:
                            pass
                    groups.append({
                        "checksum":       cs,
                        "size":           len(data),
                        "sources":        srcs,
                        "temp_path":      temp_path,
                        "suggested_name": fname,
                    })
                _suggested_name(fname, groups)
                with _sync_lock:
                    job["conflicts"].append({"filename": fname, "groups": groups})

        with _sync_lock:
            job["status"] = "done"

    except Exception as e:
        with _sync_lock:
            job["status"] = "error"
            job["error"]  = str(e)


def _run_rescan_job(state):
    """Background thread: FTP-list all Radius devices and update inventory cache."""
    try:
        radius_devs = _snap_audio_devices(state)
        connected   = [d for d in radius_devs if d["connected"]]
        _stop_all_audio(connected)

        entries_by_ip = {}
        for dev in connected:
            ip = dev["ip"]
            try:
                entries = ftp_list_dir(ip, "/")
                entries_by_ip[ip] = sorted(
                    e["name"] for e in entries if _is_audio_file(e["name"])
                )
            except Exception:
                pass

        _update_inventory(connected, entries_by_ip)

    except Exception:
        pass


def create_server(host, port, controller_state, cue_list, ui_lifecycle_enabled=False, osc_service=None):
    """Create and return an HTTPServer bound to host:port."""
    Handler.controller_state = controller_state
    Handler.cue_list = cue_list
    Handler.audio_cues_data  = _audio_cues_mod.load_audio_cues()
    server = HTTPServer((host, port), Handler)
    server.controller_state = controller_state
    server.cue_list = cue_list
    server.osc_service = osc_service
    server.ui_lifecycle_enabled = bool(ui_lifecycle_enabled)
    server.ui_lifecycle_started_at = time.monotonic()
    server.ui_last_heartbeat = None
    server.ui_close_requested_at = None
    return server
