"""
server.py — HTTP server serving static files and JSON API.
"""

import json
import os
import mimetypes
from http.server import HTTPServer, BaseHTTPRequestHandler

import clips
import mixer
from artnet import discover_artnet_nodes


_WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


class Handler(BaseHTTPRequestHandler):
    controller_state = None
    cue_list = None

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
            look = mixer.load_look(look_id)
            if look:
                self._json_response(look)
            else:
                self._respond(404, "application/json", b'{"error":"not found"}')
            return
        if path == "/api/cues":
            self._json_response(self.cue_list.get_json())
            return

        # Static files
        if path == "/" or path == "":
            path = "/index.html"
        self._serve_static(path)

    # ------------------------------------------------------------------
    #  POST
    # ------------------------------------------------------------------

    def do_POST(self):
        data = self._read_json()
        path = self.path

        if path == "/api/update":
            self.controller_state.update(data)
            self._ok()

        elif path == "/api/connect":
            di = data.get("device", 0)
            if 0 <= di < len(self.controller_state.devices):
                self.controller_state.connect(di)
            self._ok()

        elif path == "/api/disconnect":
            di = data.get("device", 0)
            if 0 <= di < len(self.controller_state.devices):
                self.controller_state.disconnect(di)
            self._ok()

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
            cue = self.cue_list.go()
            self._json_response({"cue": cue})

        elif path == "/api/cues/stop":
            self.cue_list.stop()
            self._ok()

        elif path == "/api/cues/goto":
            number = data.get("number", 1)
            cue = self.cue_list.go_to_cue(number)
            self._json_response({"cue": cue})

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
            if source in ("designer", "idle"):
                self.controller_state.set_playback_source(source)
                self._ok()
            else:
                self._respond(400, "application/json",
                              b'{"error":"invalid source"}')

        elif path == "/api/device_groups":
            group = self.controller_state.save_device_group(data)
            self._json_response(group)

        else:
            self._respond(404, "application/json", b'{"error":"not found"}')

    # ------------------------------------------------------------------
    #  DELETE
    # ------------------------------------------------------------------

    def do_DELETE(self):
        path = self.path
        if path.startswith("/api/clips/"):
            clip_id = path.split("/api/clips/")[1]
            clips.delete_clip(clip_id)
            self._ok()
        elif path.startswith("/api/looks/"):
            look_id = path.split("/api/looks/")[1]
            mixer.delete_look(look_id)
            self._ok()
        elif path.startswith("/api/device_groups/"):
            gid = path.split("/api/device_groups/")[1]
            self.controller_state.delete_device_group(gid)
            self._ok()
        else:
            self._respond(404, "application/json", b'{"error":"not found"}')

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
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


def create_server(host, port, controller_state, cue_list):
    """Create and return an HTTPServer bound to host:port."""
    Handler.controller_state = controller_state
    Handler.cue_list = cue_list
    return HTTPServer((host, port), Handler)
