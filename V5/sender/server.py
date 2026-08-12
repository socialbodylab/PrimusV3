"""
server.py — Unified V5 HTTP server (Primus + Radius APIs, multiple frontends).
"""

import json
import os
import re
import mimetypes
import threading
import time
import uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote

import audio_cues as _audio_cues_mod
import netlog

import clips
from cue_boards import delete_cue_board, list_cue_boards, load_cue_board, save_cue_board
from controller import normalize_cue
from firmware import FirmwareRequestError, firmware_jobs
from output_presets import (
    BuiltInOutputPresetError,
    DuplicateOutputPresetIdError,
    DuplicateOutputPresetNameError,
    MalformedOutputPresetsError,
    OutputPresetNotFoundError,
    OutputPresetValidationError,
)
from serial_monitor import SerialMonitorError, serial_monitor
import mixer
import sharing
from artnet import (
    discover_artnet_nodes,
    device_show_port,
    device_setup_port,
    ftp_list_dir,
    ftp_upload,
    is_compatible_node,
    send_audio_cmd,
    AUDIO_CMD_STOP,
)
from network_settings import (
    NetworkSettingsError,
    apply_static_ip,
    get_artnet_interface,
    get_lane_ports,
    get_network_status,
    save_profile,
    set_controller_connection,
    set_dhcp,
    set_lane_ports,
    set_preferred_interface,
)
from paths import web_dir, frontend_index_path, default_frontend_path, sender_product, app_version
from radius_state import RadiusState
from state import OUTPUT_TYPES, ControllerState
from ui_lifecycle import close_session, init_server, touch_session


DEBUG_API_TIMING = os.environ.get("PRIMUSV3_DEBUG_API_TIMING") == "1"


_WEB_DIR = web_dir()
_sync_lock = threading.Lock()
_sync_job = None
_SAFE_ID_RE = re.compile(r'^[a-zA-Z0-9_-]+$')


def _safe_id(value):
    """Return True if value is a safe resource identifier (no path traversal)."""
    return bool(value) and bool(_SAFE_ID_RE.match(value))


def _safe_ftp_path(path):
    if not path or not path.startswith("/"):
        return False
    if ".." in path or "\\" in path:
        return False
    return True


def _sync_network_devices(device_state, interface=None):
    """Discover nodes, add compatible new devices, and connect all online targets."""
    product = sender_product()
    known_ips = device_state.discovery_targets()
    nodes = discover_artnet_nodes(known_ips=known_ips, timeout=3.5, interface=interface)
    if nodes:
        device_state.refresh_devices_from_nodes(nodes)

    added = []
    skipped = []
    for node in nodes or []:
        node_ip = node.get("ip")
        if not is_compatible_node(node, product):
            skipped.append({"ip": node_ip, "reason": "incompatible"})
            continue
        result = device_state.add_device_from_node(node)
        if result.get("status") == "added":
            added.append({
                "ip": node_ip,
                "name": node.get("short_name") or node_ip,
                "device_index": result.get("device_index"),
            })

    # Sync is discovery + refresh ONLY — it never opens an output
    # connection. Connecting is what arms DMX to a device (including
    # per-frame keepalive blackout frames), and in production the color
    # data usually comes from an external console (EOS, TouchDesigner):
    # a background sync that auto-connects would fight it. Connecting is
    # always an explicit operator action (/api/connect, Connect All).
    # This is also what made the old monitor_only mode unnecessary — every
    # backend is passive until an operator arms output.
    connected = []
    return {
        "added": added,
        "skipped": skipped,
        "connected": connected,
        "nodes": nodes or [],
    }


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.1 keep-alive: the UIs poll several times per second, and
    # without persistent connections every poll pays a TCP handshake —
    # invisible on loopback, real cost for network clients. Every response
    # path sets Content-Length, which keep-alive requires.
    protocol_version = "HTTP/1.1"
    # Reap idle or hung keep-alive connections so they don't pin a server
    # thread forever.
    timeout = 65

    controller_state = None
    primus_state = None
    radius_state = None
    cue_list = None
    audio_cues_data = {"cues": []}
    audio_cues_lock = threading.Lock()

    def _primus_state(self):
        return getattr(self.server, "primus_state", None)

    def _radius_state(self):
        return getattr(self.server, "radius_state", None)

    def _device_state(self):
        return self._primus_state() or self._radius_state()

    def _backend_products(self):
        """Products this server can serve.

        A ControllerState with the Radius audio/FTP surface makes the
        unified backend a valid host for the RadiusCentral frontend, so it
        advertises both products; a standalone RadiusState backend stays
        radius-only.
        """
        products = [sender_product()]
        primus = self._primus_state()
        if primus is not None and hasattr(primus, "send_audio_command"):
            if "radius" not in products:
                products.append("radius")
        return products

    def _osc_service(self):
        return getattr(self.server, "osc_service", None)

    def _server_has_live_output(self):
        """True when this Central is actively driving a show.

        Reuses the same callable the UI-lifecycle monitor uses to decide whether
        it is safe to auto-quit, so /api/server/stop and the auto-shutdown path
        can never disagree about whether output is live.
        """
        live_output_fn = getattr(self.server, "live_output_fn", None)
        if not callable(live_output_fn):
            return False
        try:
            return bool(live_output_fn(self.server))
        except Exception:
            # A broken predicate must not make the server look idle, or a stop
            # request would black out a running show.
            return True

    def _leave_controller_runtime(self, preserve_selection=True):
        if self.cue_list is not None:
            self.cue_list.release_output(preserve_selection=preserve_selection)

    def _json_error(self, code, message):
        body = json.dumps({"error": message}, separators=(",", ":")).encode()
        self._respond(code, "application/json", body)

    def _json_error_with_details(self, code, message, error_code=None, extra=None):
        payload = {"error": message}
        if error_code:
            payload["error_code"] = error_code
        if isinstance(extra, dict):
            payload.update(extra)
        body = json.dumps(payload, separators=(",", ":")).encode()
        self._respond(code, "application/json", body)

    def _json_network_error(self, exc):
        self._json_error(exc.code, exc.message)

    def _sync_artnet_source(self):
        interface = get_artnet_interface()
        source_ip = (interface or {}).get("source_ip") or (interface or {}).get("ipv4")
        self._device_state().set_artnet_source(source_ip)
        return interface

    def _json_state_result(self, result, default_error_status=400):
        if result.get("ok"):
            self._json_response(result)
            return
        self._json_error_with_details(
            result.get("http_status") or default_error_status,
            result.get("error", "request failed"),
            error_code=result.get("error_code"),
        )

    def _parse_int_field(self, value, field_name, location="body"):
        try:
            return int(value)
        except (TypeError, ValueError):
            label = f"{field_name} query parameter" if location == "query" else field_name
            raise ValueError(f"{label} must be an integer")

    def _primus_management_state(self):
        state = self._primus_state()
        if state is None:
            self._json_error_with_details(
                409,
                "Primus management routes are not available when the sender is running in Radius mode.",
                error_code="NotAvailable",
            )
            return None
        return state

    def _handle_output_preset_error(self, exc):
        if isinstance(exc, OutputPresetValidationError):
            self._json_error_with_details(400, str(exc), error_code="OutputPresetValidation")
            return
        if isinstance(exc, OutputPresetNotFoundError):
            self._json_error_with_details(404, str(exc), error_code="OutputPresetNotFound")
            return
        if isinstance(exc, (DuplicateOutputPresetNameError, DuplicateOutputPresetIdError)):
            self._json_error_with_details(409, str(exc), error_code=type(exc).__name__.replace("Error", ""))
            return
        if isinstance(exc, BuiltInOutputPresetError):
            self._json_error_with_details(409, str(exc), error_code="BuiltInOutputPreset")
            return
        if isinstance(exc, MalformedOutputPresetsError):
            self._json_error_with_details(409, str(exc), error_code="MalformedOutputPresets")
            return
        raise exc

    # ------------------------------------------------------------------
    #  GET
    # ------------------------------------------------------------------

    def do_GET(self):
        path = self.path.split("?")[0]

        # API routes
        if path == "/api/runtime":
            self._json_response({
                "product": sender_product(),
                "products": self._backend_products(),
                "app_version": app_version(),
                "ui_lifecycle": bool(getattr(self.server, "ui_lifecycle_enabled", False)),
                "frontends": {
                    "primus": "/primus",
                    "radius": "/radius",
                    "devices": "/devices",
                },
                "default_frontend": default_frontend_path(),
                "monitor_only": bool(getattr(self._device_state(), "monitor_only", False)),
                "lan_enabled": bool(getattr(self.server, "lan_enabled", False)),
                # Advertise that POST /api/server/stop exists. A launcher must
                # never assume it: servers before 0.98 answer that route with
                # 404, and a launcher that tried anyway aborted with a generic
                # failure while the old server kept holding the port -- both
                # apps then looked dead. Absent means "cannot stop remotely".
                "server_control": True,
            })
            return
        if path == "/api/server/status":
            # Richer than /api/runtime on purpose: /api/runtime is the discovery
            # probe and has to stay stable for older clients, so operational
            # detail that changes shape over time lives here instead.
            sessions = getattr(self.server, "ui_sessions", None) or {}
            started_at = getattr(self.server, "ui_lifecycle_started_at", None)
            uptime = None
            if started_at is not None:
                uptime = round(time.monotonic() - started_at, 1)
            self._json_response({
                "pid": os.getpid(),
                "host": self.server.server_address[0],
                "port": self.server.server_address[1],
                "product": sender_product(),
                "products": self._backend_products(),
                "app_version": app_version(),
                "monitor_only": bool(
                    getattr(self._device_state(), "monitor_only", False)),
                "lan_enabled": bool(getattr(self.server, "lan_enabled", False)),
                "ui_lifecycle": bool(
                    getattr(self.server, "ui_lifecycle_enabled", False)),
                "client_sessions": sorted(sessions.keys()),
                "client_session_count": len(sessions),
                "live_output": self._server_has_live_output(),
                "uptime_seconds": uptime,
            })
            return
        if path == "/api/state":
            state = self._device_state()
            wanted = (self._query_params().get("product") or "").strip().lower()
            if wanted == "radius" and hasattr(state, "get_radius_json"):
                # Unified backend: the RadiusCentral frontend asks for the
                # radius-shaped view of the shared device list. Indices stay
                # aligned with the unified list. A standalone RadiusState
                # (no get_radius_json) already returns the radius shape.
                self._json_response(state.get_radius_json())
                return
            self._json_response(state.get_json())
            return
        if path == "/api/device_full_config":
            state = self._primus_management_state()
            if state is None:
                return
            params = self._query_params()
            try:
                di = self._parse_int_field(params.get("device"), "device", location="query")
            except ValueError as exc:
                self._json_error(400, str(exc))
                return
            self._json_state_result(state.get_device_full_config(di))
            return
        if path == "/api/device_lock_state":
            state = self._primus_management_state()
            if state is None:
                return
            params = self._query_params()
            try:
                di = self._parse_int_field(params.get("device"), "device", location="query")
            except ValueError as exc:
                self._json_error(400, str(exc))
                return
            self._json_state_result(state.get_device_lock_state(di))
            return
        if path == "/api/output_presets":
            state = self._primus_management_state()
            if state is None:
                return
            self._json_response({"presets": state.list_output_presets()})
            return
        if path.startswith("/api/output_presets/"):
            state = self._primus_management_state()
            if state is None:
                return
            preset_id = path.split("/api/output_presets/")[1]
            if not _safe_id(preset_id):
                self._json_error(400, "invalid id")
                return
            try:
                self._json_response({"preset": state.get_output_preset(preset_id)})
            except (
                BuiltInOutputPresetError,
                DuplicateOutputPresetIdError,
                DuplicateOutputPresetNameError,
                MalformedOutputPresetsError,
                OutputPresetNotFoundError,
                OutputPresetValidationError,
            ) as exc:
                self._handle_output_preset_error(exc)
            return
        if path == "/api/performance":
            started = time.perf_counter()
            payload = self._device_state().get_performance_json()
            built = time.perf_counter()
            if DEBUG_API_TIMING:
                print(f"api timing {path}: build={(built - started) * 1000.0:.1f}ms")
            self._json_response(payload)
            if DEBUG_API_TIMING:
                print(f"api timing {path}: total={(time.perf_counter() - started) * 1000.0:.1f}ms")
            return
        if path == "/api/network/status":
            self._json_response(get_network_status())
            return
        if path == "/api/network/lane_ports":
            self._json_response(get_lane_ports())
            return
        if path == "/api/device_lane_ports":
            params = self._query_params()
            try:
                di = self._parse_int_field(params.get("device"), "device", location="query")
            except ValueError as exc:
                self._json_error(400, str(exc))
                return
            self._json_state_result(self._device_state().get_device_lane_ports(di))
            return
        if path == "/api/firmware/status":
            params = self._query_params()
            scope = params.get("scope", "product")
            self._json_response(firmware_jobs.status(scope=scope))
            return
        if path == "/api/serial/status":
            self._json_response(serial_monitor.status())
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
        if path == "/api/cue_boards":
            self._json_response({"boards": list_cue_boards()})
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
            self._json_response(board)
            return
        if path == "/api/integrations/osc":
            service = self._osc_service()
            if service is None:
                self._json_error(503, "OSC service unavailable")
            else:
                started = time.perf_counter()
                payload = service.status()
                built = time.perf_counter()
                if DEBUG_API_TIMING:
                    print(f"api timing {path}: build={(built - started) * 1000.0:.1f}ms")
                self._json_response(payload)
                if DEBUG_API_TIMING:
                    print(f"api timing {path}: total={(time.perf_counter() - started) * 1000.0:.1f}ms")
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
            devices = self._device_state().devices
            if not (0 <= di < len(devices)) or not devices[di].get("is_radius"):
                self._json_error(400, "invalid device index")
                return
            try:
                raw = self._device_state().ftp_download(di, "/cues.json")
            except Exception as exc:
                # A node with no cue map yet is a normal state, not an error:
                # the editor should open an empty table. Only the FTP session
                # itself failing outright is worth surfacing.
                message = str(exc)
                if "550" in message or "no such file" in message.lower():
                    self._json_response({})
                    return
                self._json_error(500, message)
                return
            try:
                self._json_response(json.loads(raw.decode()))
            except Exception:
                # Corrupt cue map on the SD card: let the operator start over
                # rather than blocking the editor behind a 500.
                self._json_response({})
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

    # ------------------------------------------------------------------
    #  POST
    # ------------------------------------------------------------------

    def do_POST(self):
        path = self.path.split("?")[0]
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

        data = self._read_json()
        if data is None:
            self._respond(400, "application/json", b'{"error":"invalid JSON"}')
            return
        path = self.path.split("?")[0]

        if path == "/api/ui/heartbeat":
            touch_session(self.server, data.get("session_id"))
            self._ok()

        elif path == "/api/ui/closed":
            close_session(self.server, data.get("session_id"))
            self._ok()

        elif path == "/api/server/stop":
            # Guarded by default: another app asking this Central to step aside
            # must not be able to black out a running show. --force is the
            # deliberate override.
            if self._server_has_live_output() and not data.get("force"):
                self._json_error(
                    409,
                    "Central is driving output; stop playback first or retry with force.",
                )
                return
            self._json_response({"ok": True, "message": "stopping"})
            # Shut down off-thread: shutdown() blocks until serve_forever exits,
            # which cannot happen while this handler is still running.
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        elif path == "/api/ui/focus":
            callback = getattr(self.server, "ui_focus_callback", None)
            if not callable(callback):
                self._json_error(404, "ui focus not available")
                return
            try:
                callback()
            except Exception:
                pass
            self._ok()

        elif path == "/api/update":
            primus = self._primus_state()
            if primus is not None:
                primus.update(data)
                self._ok()
            else:
                self._json_response(self._device_state().get_json())

        elif path == "/api/refresh_device_full_config":
            state = self._primus_management_state()
            if state is None:
                return
            try:
                di = self._parse_int_field(data.get("device"), "device")
            except ValueError as exc:
                self._json_error(400, str(exc))
                return
            self._sync_artnet_source()
            self._json_state_result(state.refresh_device_full_config(di))
            return

        elif path == "/api/apply_device_output_descriptor":
            state = self._primus_management_state()
            if state is None:
                return
            if not isinstance(data.get("descriptor"), dict):
                self._json_error(400, "descriptor must be an object")
                return
            try:
                di = self._parse_int_field(data.get("device"), "device")
                oi = self._parse_int_field(data.get("output"), "output")
            except ValueError as exc:
                self._json_error(400, str(exc))
                return
            self._sync_artnet_source()
            self._json_state_result(
                state.apply_device_output_descriptor(di, oi, data.get("descriptor")))
            return

        elif path == "/api/set_device_telemetry_target":
            state = self._primus_management_state()
            if state is None:
                return
            if "telemetry_target" not in data:
                self._json_error(400, "telemetry_target is required")
                return
            try:
                di = self._parse_int_field(data.get("device"), "device")
            except ValueError as exc:
                self._json_error(400, str(exc))
                return
            telemetry_target = data.get("telemetry_target")
            if telemetry_target is None or telemetry_target == "0.0.0.0":
                pass
            elif not isinstance(telemetry_target, str):
                self._json_error(400, "telemetry_target must be a string or null")
                return
            else:
                telemetry_target = telemetry_target.strip()
                if not telemetry_target:
                    self._json_error(
                        400,
                        "telemetry_target must be an IPv4 string or null to clear",
                    )
                    return
            self._sync_artnet_source()
            if telemetry_target is None or telemetry_target == "0.0.0.0":
                result = state.clear_device_telemetry_target(di)
            else:
                result = state.set_device_telemetry_target(di, telemetry_target)
            self._json_state_result(result)
            return

        elif path == "/api/enter_device_production_mode":
            state = self._primus_management_state()
            if state is None:
                return
            try:
                di = self._parse_int_field(data.get("device"), "device")
            except ValueError as exc:
                self._json_error(400, str(exc))
                return
            self._sync_artnet_source()
            self._json_state_result(state.enter_device_production_mode(di))
            return

        elif path == "/api/unlock_device_boot_window":
            state = self._primus_management_state()
            if state is None:
                return
            try:
                di = self._parse_int_field(data.get("device"), "device")
            except ValueError as exc:
                self._json_error(400, str(exc))
                return
            self._sync_artnet_source()
            self._json_state_result(state.unlock_device_boot_window(di))
            return

        elif path == "/api/output_presets":
            state = self._primus_management_state()
            if state is None:
                return
            preset_id = data.get("id")
            has_name = "name" in data
            has_descriptor = "descriptor" in data
            if has_descriptor and not isinstance(data.get("descriptor"), dict):
                self._json_error(400, "descriptor must be an object")
                return
            if preset_id is None:
                if not has_name or not has_descriptor:
                    self._json_error(400, "name and descriptor are required")
                    return
                try:
                    preset = state.create_output_preset(data.get("name"), data.get("descriptor"))
                except (
                    BuiltInOutputPresetError,
                    DuplicateOutputPresetIdError,
                    DuplicateOutputPresetNameError,
                    MalformedOutputPresetsError,
                    OutputPresetNotFoundError,
                    OutputPresetValidationError,
                ) as exc:
                    self._handle_output_preset_error(exc)
                    return
            else:
                if preset_id == "":
                    self._json_error(400, "id must not be empty")
                    return
                if not has_name and not has_descriptor:
                    self._json_error(400, "name or descriptor is required when updating a preset")
                    return
                try:
                    preset = state.update_output_preset(
                        preset_id,
                        name=data.get("name") if has_name else None,
                        descriptor_template=data.get("descriptor") if has_descriptor else None,
                    )
                except (
                    BuiltInOutputPresetError,
                    DuplicateOutputPresetIdError,
                    DuplicateOutputPresetNameError,
                    MalformedOutputPresetsError,
                    OutputPresetNotFoundError,
                    OutputPresetValidationError,
                ) as exc:
                    self._handle_output_preset_error(exc)
                    return
            self._json_response({"ok": True, "preset": preset})
            return

        elif path == "/api/connect":
            if getattr(self._device_state(), "monitor_only", False):
                self._json_error(409, "this instance is running in monitor-only mode")
                return
            try:
                # Snapshot the IP in one step: a concurrent remove between a
                # separate length check and the index read raised IndexError
                # (an uncaught 500) on this route.
                di = int(data.get("device", 0))
                if di < 0:
                    raise IndexError(di)
                ip = self._device_state().devices[di]["ip"]
            except (IndexError, TypeError, ValueError, KeyError):
                self._respond(400, "application/json", b'{"error":"invalid device index"}')
                return
            interface = self._sync_artnet_source()
            nodes = discover_artnet_nodes(known_ips=[ip], timeout=1.0, interface=interface)
            node = next((n for n in nodes if n["ip"] == ip), None)
            if node:
                self._device_state().add_device_from_node(node)
            result = self._device_state().connect(di)
            if result.get("ok"):
                self._ok()
            else:
                self._json_error(503, result.get("error", "connect failed"))

        elif path == "/api/disconnect":
            di = data.get("device", 0)
            if 0 <= di < len(self._device_state().devices):
                self._device_state().disconnect(di)
                self._ok()
            else:
                self._respond(400, "application/json", b'{"error":"invalid device index"}')

        elif path == "/api/connect_all":
            if getattr(self._device_state(), "monitor_only", False):
                self._json_error(409, "this instance is running in monitor-only mode")
                return
            known_ips = self._device_state().discovery_targets()
            interface = self._sync_artnet_source()
            nodes = discover_artnet_nodes(known_ips=known_ips, timeout=3.5, interface=interface)
            if nodes:
                self._device_state().refresh_devices_from_nodes(nodes)
            online_ips = {node.get("ip") for node in nodes if node.get("ip")}
            results = self._device_state().connect_all(only_ips=online_ips if online_ips else None)
            failed = [r for r in results if not r.get("ok")]
            if failed:
                self._json_error(503, failed[0].get("error", "connect failed"))
            else:
                self._ok()

        elif path == "/api/disconnect_all":
            self._device_state().disconnect_all()
            self._ok()

        elif path == "/api/discover":
            known_ips = self._device_state().discovery_targets()
            interface = self._sync_artnet_source()
            nodes = discover_artnet_nodes(known_ips=known_ips, timeout=3.5, interface=interface)
            self._device_state().refresh_devices_from_nodes(nodes)
            self._json_response(nodes)

        elif path == "/api/devices/sync":
            interface = self._sync_artnet_source()
            self._json_response(_sync_network_devices(self._device_state(), interface=interface))

        elif path == "/api/add_discovered":
            self._sync_artnet_source()
            result = self._device_state().add_device_from_node(data)
            if result.get("device_index") is not None:
                connect_result = self._device_state().connect(result["device_index"])
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
            nodes = discover_artnet_nodes(known_ips=[ip], timeout=3.5, interface=interface)
            node = next((n for n in nodes if n["ip"] == ip), None)
            if node:
                result = self._device_state().add_device_from_node(node)
            else:
                # No reply -- add as bare device with default outputs
                result = self._device_state().add_device_from_node({
                    "ip": ip,
                    "short_name": ip,
                    "long_name": "",
                    "num_ports": 0,
                    "universes": [0, 1],
                })
            if result.get("device_index") is not None:
                connect_result = self._device_state().connect(result["device_index"])
                if not connect_result.get("ok"):
                    result["connect_error"] = connect_result.get("error")
            self._json_response(result)

        elif path == "/api/remove_device":
            di = data.get("device", -1)
            self._device_state().remove_device(di)
            self._ok()

        elif path == "/api/rename_node":
            self._sync_artnet_source()
            di = data.get("device", -1)
            new_name = str(data.get("name", ""))[:17]
            if not new_name:
                self._json_error(400, "name required")
                return
            result = self._device_state().rename_device(di, new_name)
            if result.get("ok"):
                self._ok()
            else:
                self._json_error_with_details(
                    result.get("http_status") or (400 if result.get("error") == "invalid device index" else 409),
                    result.get("error", "rename failed"),
                    error_code=result.get("error_code"),
                )

        elif path == "/api/device_show_info":
            di = data.get("device", -1)
            if "character_name" not in data and "performer_name" not in data:
                self._json_error(400, "character_name or performer_name required")
                return
            kwargs = {}
            if "character_name" in data:
                kwargs["character_name"] = data.get("character_name")
            if "performer_name" in data:
                kwargs["performer_name"] = data.get("performer_name")
            result = self._device_state().update_device_show_info(di, **kwargs)
            if result.get("ok"):
                self._json_response({
                    "ok": True,
                    "applied_to_device": bool(result.get("applied_to_device")),
                })
            else:
                self._json_error_with_details(
                    result.get("http_status") or (400 if result.get("error") == "invalid device index" else 409),
                    result.get("error", "update failed"),
                    error_code=result.get("error_code"),
                )

        elif path == "/api/hello_device":
            self._sync_artnet_source()
            di = data.get("device", -1)
            state = self._device_state()
            devices = state.devices
            if not (0 <= di < len(devices)):
                self._json_error(400, "invalid device index")
            elif devices[di].get("is_radius"):
                try:
                    volume = max(0, min(100, int(data.get("volume", 80))))
                except (TypeError, ValueError):
                    volume = 80
                if state.hello_device(di, volume=volume):
                    self._ok()
                else:
                    self._json_error(400, "hello failed")
            else:
                status = state.device_capability_status(di, "hello")
                if not status.get("ok"):
                    code = 400 if status.get("error") == "invalid device index" else 409
                    self._json_error(code, status.get("error", "identify failed"))
                elif state.hello_device(di):
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
            result = self._device_state().set_device_ip(di, static_ip, gateway, subnet)
            if result.get("ok"):
                self._ok()
            else:
                error = result.get("error", "IP update failed")
                self._json_error_with_details(
                    result.get("http_status")
                    or (400 if result.get("error") == "invalid device index" or "invalid" in error.lower() else 409),
                    error,
                    error_code=result.get("error_code"),
                )

        elif path == "/api/revert_device_dhcp":
            self._sync_artnet_source()
            di = data.get("device", -1)
            result = self._device_state().revert_device_dhcp(di)
            if result.get("ok"):
                self._ok()
            else:
                self._json_error_with_details(
                    result.get("http_status") or (400 if result.get("error") == "invalid device index" else 409),
                    result.get("error", "DHCP revert failed"),
                    error_code=result.get("error_code"),
                )

        elif path == "/api/set_device_output":
            self._sync_artnet_source()
            di = data.get("device", -1)
            oi = data.get("output", -1)
            output_type = str(data.get("output_type", ""))
            if not output_type:
                self._json_error(400, "output_type required")
                return
            try:
                di = int(di)
                oi = int(oi)
            except (TypeError, ValueError):
                self._json_error(400, "invalid device or output index")
                return
            result = self._device_state().set_device_output_type(di, oi, output_type)
            if result.get("ok"):
                self._json_response(result)
            else:
                error = result.get("error", "output update failed")
                self._json_error_with_details(
                    result.get("http_status")
                    or (400 if "invalid" in error.lower() or "unknown" in error.lower() else 409),
                    error,
                    error_code=result.get("error_code"),
                )

        elif path == "/api/set_device_virtual_resolution":
            self._sync_artnet_source()
            di = data.get("device", -1)
            oi = data.get("output", -1)
            virtual_pixels = data.get("virtual_pixels")
            virtual_percent = data.get("virtual_percent")
            try:
                di = int(di)
                oi = int(oi)
            except (TypeError, ValueError):
                self._json_error(400, "invalid device or output index")
                return
            result = self._device_state().set_device_virtual_resolution(
                di, oi,
                virtual_pixels=virtual_pixels,
                virtual_percent=virtual_percent,
            )
            if result.get("ok"):
                self._json_response(result)
            else:
                error = result.get("error", "virtual resolution update failed")
                self._json_error_with_details(
                    result.get("http_status")
                    or (400 if "invalid" in error.lower() or "unknown" in error.lower() else 409),
                    error,
                    error_code=result.get("error_code"),
                )

        elif path == "/api/set_device_receive_mode":
            self._sync_artnet_source()
            di = data.get("device", -1)
            receive_mode = str(data.get("receive_mode", "")).strip().lower()
            base_universe = data.get("base_universe", 0)
            if receive_mode not in ("split", "combined"):
                self._json_error(400, "receive_mode must be split or combined")
                return
            try:
                di = int(di)
            except (TypeError, ValueError):
                self._json_error(400, "invalid device index")
                return
            result = self._device_state().set_device_receive_mode(
                di, receive_mode, base_universe)
            if result.get("ok"):
                self._json_response(result)
            else:
                error = result.get("error", "receive mode update failed")
                self._json_error_with_details(
                    result.get("http_status") or (400 if "invalid" in error.lower() else 409),
                    error,
                    error_code=result.get("error_code"),
                )

        elif path == "/api/device_lane_ports":
            self._sync_artnet_source()
            di = data.get("device", -1)
            try:
                di = int(di)
                port_show = self._parse_int_field(data.get("port_show"), "port_show")
                port_setup = self._parse_int_field(data.get("port_setup"), "port_setup")
                port_watch = self._parse_int_field(data.get("port_watch"), "port_watch")
            except (TypeError, ValueError) as exc:
                self._json_error(400, str(exc) or "invalid device or port value")
                return
            result = self._device_state().set_device_lane_ports(
                di, port_show, port_setup, port_watch)
            if result.get("ok"):
                self._json_response(result)
            else:
                error = result.get("error", "lane port update failed")
                self._json_error_with_details(
                    result.get("http_status")
                    or (400 if "invalid" in error.lower() or "must" in error.lower() else 409),
                    error,
                    error_code=result.get("error_code"),
                )

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

        elif path.startswith("/api/cue_boards/") and path.endswith("/load"):
            board_id = path[len("/api/cue_boards/"):-len("/load")]
            if not _safe_id(board_id):
                self._json_error(400, "invalid id")
                return
            board = load_cue_board(board_id)
            if board is None:
                self._json_error(404, "cue board not found")
                return
            self.cue_list.set_cues(board.get("cues", []))
            response = self.cue_list.get_json()
            response["board"] = {
                "id": board.get("id"),
                "name": board.get("name", ""),
            }
            self._json_response(response)

        elif path == "/api/cue_boards":
            try:
                cues = data.get("cues")
                if cues is None:
                    with self.cue_list.lock:
                        cues = list(self.cue_list.cues)
                else:
                    cues = [
                        normalize_cue(cue, index + 1)
                        for index, cue in enumerate(cues or [])
                    ]
                board = save_cue_board(data.get("name"), cues, board_id=data.get("id"))
            except ValueError as exc:
                self._json_error(400, str(exc))
                return
            self._json_response({"board": {
                "id": board.get("id"),
                "name": board.get("name", ""),
                "cue_count": len(board.get("cues") or []),
                "created": board.get("created", ""),
                "modified": board.get("modified", ""),
            }})

        elif path.startswith("/api/cue_boards/"):
            board_id = path.split("/api/cue_boards/")[1]
            if not _safe_id(board_id):
                self._json_error(400, "invalid id")
                return
            board = load_cue_board(board_id)
            if board is None:
                self._json_error(404, "cue board not found")
                return
            try:
                name = data.get("name", board.get("name"))
                cues = data.get("cues")
                if cues is None:
                    with self.cue_list.lock:
                        cues = list(self.cue_list.cues)
                else:
                    cues = [
                        normalize_cue(cue, index + 1)
                        for index, cue in enumerate(cues or [])
                    ]
                board = save_cue_board(name, cues, board_id=board_id)
            except ValueError as exc:
                self._json_error(400, str(exc))
                return
            self._json_response({"board": {
                "id": board.get("id"),
                "name": board.get("name", ""),
                "cue_count": len(board.get("cues") or []),
                "created": board.get("created", ""),
                "modified": board.get("modified", ""),
            }})

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
                self._json_response(
                    firmware_jobs.start_job(data, device_state=self._device_state()))
            except FirmwareRequestError as exc:
                self._json_error(exc.code, exc.message)

        elif path == "/api/firmware/updates/check":
            force = bool(data.get("force", False))
            self._json_response(firmware_jobs.check_firmware_updates(force=force))

        elif path == "/api/serial/monitor/start":
            port = str(data.get("port", "")).strip()
            try:
                baud = int(data.get("baud", 115200))
            except (TypeError, ValueError):
                baud = 115200
            try:
                self._json_response(serial_monitor.start(port, baud=baud))
            except SerialMonitorError as exc:
                self._json_error(exc.code, exc.message)

        elif path == "/api/serial/monitor/stop":
            self._json_response(serial_monitor.stop())

        elif path == "/api/network/preferred_interface":
            try:
                result = set_preferred_interface(data)
                interface = result.get("selected_interface")
                source_ip = (interface or {}).get("source_ip") or (interface or {}).get("ipv4")
                self._device_state().set_artnet_source(source_ip)
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
                self._device_state().set_artnet_source(source_ip)
                self._json_response(result)
            except NetworkSettingsError as exc:
                self._json_network_error(exc)

        elif path == "/api/network/apply_static_ip":
            try:
                result = apply_static_ip(data)
                interface = result.get("selected_interface")
                source_ip = (interface or {}).get("source_ip") or (interface or {}).get("ipv4")
                self._device_state().set_artnet_source(source_ip)
                self._json_response(result)
            except NetworkSettingsError as exc:
                self._json_network_error(exc)

        elif path == "/api/network/set_dhcp":
            try:
                result = set_dhcp(data)
                interface = result.get("selected_interface")
                source_ip = (interface or {}).get("source_ip") or (interface or {}).get("ipv4")
                self._device_state().set_artnet_source(source_ip)
                self._json_response(result)
            except NetworkSettingsError as exc:
                self._json_network_error(exc)

        elif path == "/api/network/lane_ports":
            try:
                self._json_response(set_lane_ports(data))
            except NetworkSettingsError as exc:
                self._json_network_error(exc)

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
            if self._device_state().send_audio_command(
                    di, cmd, filename, volume, duration=duration):
                self._ok()
            else:
                self._json_error(400, "invalid device index or command")
            return
        if path == "/api/audio/files":
            di = data.get("device", -1)
            ftp_path = str(data.get("path", "/"))
            if not (0 <= di < len(self._device_state().devices)):
                self._json_error(400, "invalid device index")
            elif not _safe_ftp_path(ftp_path):
                self._json_error(400, "invalid path")
            else:
                try:
                    entries = self._device_state().ftp_list_dir(di, ftp_path)
                    self._json_response({"entries": entries or []})
                except Exception as exc:
                    self._json_error(500, str(exc))
            return
        if path == "/api/audio/rename":
            di = data.get("device", -1)
            src = str(data.get("src", ""))
            dst = str(data.get("dst", ""))
            if not (0 <= di < len(self._device_state().devices)):
                self._json_error(400, "invalid device index")
            elif not _safe_ftp_path(src) or not _safe_ftp_path(dst):
                self._json_error(400, "invalid path")
            else:
                try:
                    self._device_state().ftp_rename(di, src, dst)
                    self._ok()
                except Exception as exc:
                    self._json_error(500, str(exc))
            return
        if path == "/api/audio/delete":
            di = data.get("device", -1)
            ftp_path = str(data.get("path", ""))
            is_dir = bool(data.get("is_dir", False))
            if not (0 <= di < len(self._device_state().devices)):
                self._json_error(400, "invalid device index")
            elif not _safe_ftp_path(ftp_path):
                self._json_error(400, "invalid path")
            else:
                try:
                    self._device_state().ftp_delete(di, ftp_path, is_dir=is_dir)
                    self._ok()
                except Exception as exc:
                    self._json_error(500, str(exc))
            return
        if path == "/api/audio/mkdir":
            di = data.get("device", -1)
            ftp_path = str(data.get("path", ""))
            if not (0 <= di < len(self._device_state().devices)):
                self._json_error(400, "invalid device index")
            elif not _safe_ftp_path(ftp_path):
                self._json_error(400, "invalid path")
            else:
                try:
                    self._device_state().ftp_mkdir(di, ftp_path)
                    self._ok()
                except Exception as exc:
                    self._json_error(500, str(exc))
            return
        if path == "/api/audio/cue_map":
            di = data.get("device", -1)
            cues = data.get("cues")
            devices = self._device_state().devices
            if not (0 <= di < len(devices)) or not devices[di].get("is_radius"):
                self._json_error(400, "invalid device index")
                return
            if not isinstance(cues, dict):
                self._json_error(400, "cues must be an object")
                return
            try:
                raw = json.dumps(cues, indent=2).encode()
                self._device_state().ftp_upload(di, "/cues.json", raw)
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
            results = self._device_state().fire_audio_cue(cue)
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
                args=(new_job, self._device_state(), cues_snapshot),
                daemon=True,
            ).start()
            self._json_response({"job_id": new_job["job_id"]})
            return
        if path == "/api/netlog/clear":
            netlog.clear()
            self._ok()
            return

        else:
            self._respond(404, "application/json", b'{"error":"not found"}')

    # ------------------------------------------------------------------
    #  DELETE
    # ------------------------------------------------------------------

    def do_DELETE(self):
        path = self.path.split("?")[0]
        if path.startswith("/api/output_presets/"):
            state = self._primus_management_state()
            if state is None:
                return
            preset_id = path.split("/api/output_presets/")[1]
            if not _safe_id(preset_id):
                self._json_error(400, "invalid id")
                return
            try:
                deleted = state.delete_output_preset(preset_id)
            except (
                BuiltInOutputPresetError,
                DuplicateOutputPresetIdError,
                DuplicateOutputPresetNameError,
                MalformedOutputPresetsError,
                OutputPresetNotFoundError,
                OutputPresetValidationError,
            ) as exc:
                self._handle_output_preset_error(exc)
                return
            self._json_response({"ok": True, "preset": deleted})
            return
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
        elif path.startswith("/api/cue_boards/"):
            board_id = path.split("/api/cue_boards/")[1]
            if not _safe_id(board_id):
                self._respond(400, "application/json", b'{"error":"invalid id"}')
                return
            if delete_cue_board(board_id):
                self._ok()
            else:
                self._json_error(404, "cue board not found")
        elif path.startswith("/api/device_groups/"):
            gid = path.split("/api/device_groups/")[1]
            if not _safe_id(gid):
                self._respond(400, "application/json", b'{"error":"invalid id"}')
                return
            self._device_state().delete_device_group(gid)
            self._ok()
        else:
            self._respond(404, "application/json", b'{"error":"not found"}')

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
        self.wfile.flush()

    def _serve_static(self, url_path):
        path = url_path.split("?")[0]
        if path in ("/", ""):
            path = default_frontend_path()
        if path in ("/primus", "/primus/"):
            file_path = frontend_index_path("primus")
        elif path in ("/radius", "/radius/"):
            file_path = frontend_index_path("radius")
        elif path in ("/devices", "/devices/"):
            file_path = frontend_index_path("devices")
        elif path == "/index-primus.html":
            file_path = frontend_index_path("primus")
        elif path in ("/index.html",):
            file_path = frontend_index_path("radius")
        else:
            clean = os.path.normpath(path.lstrip("/"))
            if clean.startswith("..") or os.path.isabs(clean):
                self._respond(403, "text/plain", b"Forbidden")
                return
            file_path = os.path.join(_WEB_DIR, clean)
        if not file_path or not os.path.isfile(file_path):
            self._respond(404, "text/plain", b"Not Found")
            return
        if not os.path.abspath(file_path).startswith(os.path.abspath(_WEB_DIR)):
            self._respond(403, "text/plain", b"Forbidden")
            return
        ctype, _ = mimetypes.guess_type(file_path)
        if ctype is None:
            ctype = "application/octet-stream"
        with open(file_path, "rb") as f:
            body = f.read()
        self._respond(200, ctype, body)

    def _handle_audio_upload(self):
        params = self._query_params()
        try:
            di = int(params.get("device", "-1"))
        except ValueError:
            di = -1
        path = unquote(str(params.get("path", "/")).strip())
        if not (0 <= di < len(self._device_state().devices)):
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
            self._device_state().ftp_upload(di, path, data)
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

    def log_message(self, fmt, *args):
        pass



def _run_sync_job(job, state, cues_data):
    """Background thread: push project library files to connected Radius nodes."""
    try:
        project_files = {f["name"]: f for f in _audio_cues_mod.list_project_audio()}
        source_ip = state.artnet_source_ip

        with state.lock:
            # Lane-aware ports resolved per device: a node whose Show or
            # Setup lane has been moved off the legacy defaults would
            # silently ignore commands sent to 6454.
            devices_snap = [
                {
                    "ip": d["ip"],
                    "name": d.get("name", d["ip"]),
                    "is_radius": d.get("is_radius", False),
                    "connected": d.get("connected", False),
                    "port_show": device_show_port(d, is_radius=True),
                    "port_setup": device_setup_port(d, is_radius=True),
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
                    send_audio_cmd(dev["ip"], AUDIO_CMD_STOP, source_ip=source_ip,
                                   dest_port=dev["port_show"])
                except Exception:
                    pass
        time.sleep(0.3)

        with _sync_lock:
            job["status"] = "running"

        for dev in radius_devs:
            ip = dev["ip"]
            dev_name = dev["name"]
            connected = dev["connected"]
            port_setup = dev["port_setup"]

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
                entries = ftp_list_dir(ip, "/", source_ip=source_ip,
                                       dest_port=port_setup)
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
                               progress_callback=_progress,
                               dest_port=port_setup)
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


class PrimusThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


def create_server(host, port, state, cue_list=None, ui_lifecycle_enabled=False, osc_service=None):
    """Create and return a threaded HTTP server bound to host:port."""
    primus_state = state if isinstance(state, ControllerState) else None
    radius_state = state if isinstance(state, RadiusState) else None
    Handler.controller_state = state
    Handler.primus_state = primus_state
    Handler.radius_state = radius_state
    Handler.cue_list = cue_list
    Handler.audio_cues_data = _audio_cues_mod.load_audio_cues()
    server = PrimusThreadingHTTPServer((host, port), Handler)
    server.controller_state = state
    server.primus_state = primus_state
    server.radius_state = radius_state
    server.cue_list = cue_list
    server.osc_service = osc_service
    server.ui_lifecycle_enabled = bool(ui_lifecycle_enabled)
    if ui_lifecycle_enabled:
        init_server(server)
    return server