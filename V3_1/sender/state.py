"""
state.py — Output type tables, controller state, animation tick, persistence.
"""

import json
import os
import threading
import time

from effects import (
    EFFECTS, fx_none, compute_anim_factor,
    apply_serpentine, apply_grid_rotation,
)
from artnet import ArtNetSender, send_output_config, send_art_address, send_ip_config


# ======================================================================
#  OUTPUT TYPE TABLE — single source of truth
# ======================================================================

OUTPUT_TYPES = {
    "none":        {"pixels": 0,  "layout": "none"},
    "short_strip": {"pixels": 30, "layout": "linear"},
    "long_strip":  {"pixels": 72, "layout": "linear"},
    "grid":        {"pixels": 64, "layout": "grid", "grid_size": [8, 8]},
}

LOOK_OUTPUT_TYPES = ["none", "short_strip", "long_strip", "grid"]
DEFAULT_DEVICE_CAPABILITIES = {
    "profile": "generic",
    "known": False,
    "rename": False,
    "hello": False,
    "ip_config": False,
    "output_config": False,
}
CONTROL_CAPABILITY_LABELS = {
    "rename": "remote rename",
    "hello": "remote identify flash",
    "ip_config": "remote IP configuration",
    "output_config": "remote output configuration",
}

# ======================================================================
#  DEFAULTS
# ======================================================================

DEFAULT_FPS = 30
DEFAULT_EFFECT = "pulse"
DEFAULT_SPEED = 1.0
DEFAULT_PLAYBACK = "loop"

DEFAULT_GRID_START_COLOR = [255, 0, 255]
DEFAULT_GRID_END_COLOR = [0, 255, 255]
DEFAULT_STRIP_START_COLOR = [255, 0, 0]
DEFAULT_STRIP_END_COLOR = [0, 0, 255]

EFFECT_NAMES = list(EFFECTS.keys())
PLAYBACK_MODES = ["loop", "boomerang", "once"]
GRID_ORDERS = ["progressive", "serpentine"]
GRID_ROTATIONS = [0, 90, 180, 270]

# V3.1: default 2-output template (A0 + A1)
DEFAULT_TEMPLATE = [
    {"name": "A0", "type": "short_strip"},
    {"name": "A1", "type": "long_strip"},
]

# ======================================================================
#  PERSISTENCE
# ======================================================================

_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           ".primus_state.json")


def _save_output_types(types):
    try:
        with open(_STATE_FILE, "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    data["output_types"] = types
    try:
        with open(_STATE_FILE, "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def _load_output_types():
    try:
        with open(_STATE_FILE, "r") as f:
            data = json.load(f)
        types = data.get("output_types", [])
        if types and all(t in OUTPUT_TYPES for t in types):
            return types
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    return None


def _normalize_device_capabilities(capabilities=None):
    out = dict(DEFAULT_DEVICE_CAPABILITIES)
    if isinstance(capabilities, dict):
        for key in out:
            if key in capabilities:
                out[key] = capabilities[key]
    out["profile"] = str(out["profile"] or "generic")
    out["known"] = bool(out["known"])
    out["rename"] = bool(out["rename"])
    out["hello"] = bool(out["hello"])
    out["ip_config"] = bool(out["ip_config"])
    out["output_config"] = bool(out["output_config"])
    return out


def _save_devices(devices):
    """Persist device list (IP + name only) so they survive restarts."""
    try:
        with open(_STATE_FILE, "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    data["devices"] = [{"ip": d["ip"], "name": d["name"]} for d in devices]
    try:
        with open(_STATE_FILE, "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def _load_devices():
    try:
        with open(_STATE_FILE, "r") as f:
            data = json.load(f)
        return data.get("devices", [])
    except (OSError, json.JSONDecodeError):
        return []


def _save_device_groups(groups):
    try:
        with open(_STATE_FILE, "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    data["device_groups"] = groups
    try:
        with open(_STATE_FILE, "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def _load_device_groups():
    try:
        with open(_STATE_FILE, "r") as f:
            data = json.load(f)
        return data.get("device_groups", [])
    except (OSError, json.JSONDecodeError):
        return []


# ======================================================================
#  HELPERS
# ======================================================================

def resolve_output(cfg):
    """Derive pixel count, grid, layout from an output config entry."""
    typedef = OUTPUT_TYPES.get(cfg["type"])
    if typedef is None:
        raise ValueError(f"Unknown output type: {cfg['type']!r}")
    count = typedef["pixels"]
    grid = typedef.get("grid_size") if typedef["layout"] == "grid" else None
    return {
        "name": cfg["name"],
        "type": cfg["type"],
        "count": count,
        "grid": grid,
        "layout": typedef["layout"],
    }


def _apply_type_to_look_output(lo, new_type):
    typedef = OUTPUT_TYPES.get(new_type)
    if typedef is None:
        return
    lo["type"] = new_type
    lo["count"] = typedef["pixels"]
    lo["layout"] = typedef["layout"]
    lo["grid"] = typedef.get("grid_size") if typedef["layout"] == "grid" else None
    lo["led_state"] = []
    lo["pixels"] = []
    is_grid = typedef["layout"] == "grid"
    lo["start_color"] = list(DEFAULT_GRID_START_COLOR if is_grid else DEFAULT_STRIP_START_COLOR)
    lo["end_color"] = list(DEFAULT_GRID_END_COLOR if is_grid else DEFAULT_STRIP_END_COLOR)
    if new_type == "none":
        lo["effect"] = "none"


def _make_look_output(cfg):
    """Create a Look output dict from a resolved output config."""
    resolved = resolve_output(cfg)
    is_grid = resolved["layout"] == "grid"
    return {
        **resolved,
        "effect": DEFAULT_EFFECT,
        "start_color": list(DEFAULT_GRID_START_COLOR if is_grid else DEFAULT_STRIP_START_COLOR),
        "end_color": list(DEFAULT_GRID_END_COLOR if is_grid else DEFAULT_STRIP_END_COLOR),
        "speed": DEFAULT_SPEED,
        "playback": DEFAULT_PLAYBACK,
        "angle": 0,
        "highlight_width": 5,
        "chase_origin": "start",
        "led_state": [],
        "pixels": [],
    }


# ======================================================================
#  CONTROLLER STATE
# ======================================================================

class ControllerState:
    """Holds all settings, computes animations, sends Art-Net frames."""

    # Playback sources
    SOURCE_DESIGNER = "designer"
    SOURCE_MIXER = "mixer"
    SOURCE_CONTROLLER = "controller"
    SOURCE_IDLE = "idle"
    PLAYBACK_SOURCES = (
        SOURCE_DESIGNER,
        SOURCE_MIXER,
        SOURCE_CONTROLLER,
        SOURCE_IDLE,
    )
    API_PLAYBACK_SOURCES = (
        SOURCE_DESIGNER,
        SOURCE_IDLE,
        SOURCE_CONTROLLER,
    )

    def __init__(self, fps_listener):
        self.lock = threading.Lock()
        self.running = True
        self.fps = DEFAULT_FPS
        self.fps_listener = fps_listener
        self.start_time = time.monotonic()
        self.last_tick = self.start_time
        self.devices = []
        self.playback_source = self.SOURCE_IDLE

        # Active Look — the animation being sent to all connected devices
        saved_types = _load_output_types()
        look_outputs = []
        for i, o_cfg in enumerate(DEFAULT_TEMPLATE):
            cfg = dict(o_cfg)
            if saved_types and i < len(saved_types):
                cfg["type"] = saved_types[i]
            look_outputs.append(_make_look_output(cfg))
        self.active_look = {"name": "Look 1", "outputs": look_outputs}

        # Device groups
        self.device_groups = _load_device_groups()

        # Mixer / controller override pixel buffers (set externally)
        self._override_pixels = None  # list of pixel lists per output, or None
        self._controller_device_ips = None  # set of IP strings or None (all)
        # Mixer live preview state
        self._mixer_preview_look = None
        self._mixer_preview_play_time = 0.0   # current wrapped timeline time
        self._mixer_preview_transport_time = 0.0  # unwrapped timeline time
        self._mixer_preview_start_mono = 0.0  # monotonic time when play started
        self._mixer_preview_playing = False    # whether clock is advancing
        self._mixer_preview_device_filter = None
        self._mixer_update_last_seq = 0       # sequence number for update ordering

    def restore_devices(self):
        """Restore saved devices on startup (call after FPS listener is ready)."""
        saved = _load_devices()
        if not saved:
            return
        from artnet import discover_artnet_nodes
        known_ips = [d["ip"] for d in saved]
        nodes = discover_artnet_nodes(known_ips=known_ips, timeout=2.0)
        node_map = {n["ip"]: n for n in nodes}
        for sd in saved:
            ip = sd["ip"]
            if any(d["ip"] == ip for d in self.devices):
                continue
            node = node_map.get(ip)
            if node:
                node["short_name"] = sd.get("name") or node.get("short_name", "Node")
                self.add_device_from_node(node, auto_save=False)
            else:
                # Add offline device with saved name
                self.add_device_from_node({
                    "ip": ip,
                    "short_name": sd.get("name", ip),
                    "long_name": "",
                    "num_ports": 0,
                    "universes": [0, 1],
                }, auto_save=False)

    def _playback_target_info_unlocked(self):
        total = len(self.devices)
        connected_total = sum(1 for dev in self.devices if dev["connected"])

        if self.playback_source == self.SOURCE_MIXER:
            if self._mixer_preview_device_filter is None:
                scope = "all"
                selected = total
                connected = connected_total
            else:
                indices = [
                    idx for idx in self._mixer_preview_device_filter
                    if 0 <= idx < total
                ]
                scope = "selected"
                selected = len(indices)
                connected = sum(1 for idx in indices if self.devices[idx]["connected"])
        elif self.playback_source == self.SOURCE_CONTROLLER:
            if self._controller_device_ips is None:
                scope = "all"
                selected = total
                connected = connected_total
            else:
                scope = "selected"
                selected = len(self._controller_device_ips)
                connected = sum(
                    1 for dev in self.devices
                    if dev["connected"] and dev["ip"] in self._controller_device_ips
                )
        elif self.playback_source == self.SOURCE_DESIGNER:
            scope = "all"
            selected = total
            connected = connected_total
        else:
            scope = "none"
            selected = 0
            connected = 0

        if scope == "none":
            label = "No output"
        elif selected <= 0:
            label = "No devices"
        elif scope == "all":
            label = "All devices"
        elif selected == 1:
            label = "1 selected device"
        else:
            label = f"{selected} selected devices"

        if scope != "none" and selected > 0 and connected != selected:
            label += f" ({connected} connected)"

        return {
            "scope": scope,
            "selected_count": selected,
            "connected_count": connected,
            "label": label,
        }

    def _playback_status_unlocked(self):
        source = self.playback_source
        target = self._playback_target_info_unlocked()

        if source == self.SOURCE_DESIGNER:
            label = "Designer"
            activity = "Live"
            detail = f"Designer output is live on {target['label'].lower()}."
        elif source == self.SOURCE_MIXER:
            label = "Mixer Preview"
            activity = "Running" if self._mixer_preview_playing else "Paused"
            detail = f"Mixer preview is {activity.lower()} on {target['label'].lower()}."
        elif source == self.SOURCE_CONTROLLER:
            label = "Controller"
            activity = "Active"
            detail = f"Controller playback owns output on {target['label'].lower()}."
        else:
            label = "Idle"
            activity = "No output"
            detail = "No live source currently owns output."

        return {
            "source": source,
            "label": label,
            "activity": activity,
            "target_label": target["label"],
            "summary": activity if source == self.SOURCE_IDLE else f"{activity} · {target['label']}",
            "detail": detail,
            "scope": target["scope"],
            "selected_count": target["selected_count"],
            "connected_count": target["connected_count"],
            "using_override": self._override_pixels is not None,
        }

    def build_black_frame(self):
        """Return an all-black frame matching the active look output sizes."""
        with self.lock:
            frame = []
            for lo in self.active_look["outputs"]:
                if lo["type"] == "none" or lo["count"] == 0:
                    frame.append([])
                else:
                    frame.append([(0, 0, 0)] * lo["count"])
            return frame

    # ------------------------------------------------------------------
    #  JSON serialization
    # ------------------------------------------------------------------

    def get_json(self):
        with self.lock:
            look = {
                "name": self.active_look["name"],
                "outputs": [],
            }
            for lo in self.active_look["outputs"]:
                look["outputs"].append({
                    "name": lo["name"],
                    "type": lo["type"],
                    "count": lo["count"],
                    "grid": lo["grid"],
                    "layout": lo["layout"],
                    "effect": lo["effect"],
                    "start_color": lo["start_color"],
                    "end_color": lo["end_color"],
                    "speed": lo["speed"],
                    "playback": lo["playback"],
                    "angle": lo["angle"],
                    "highlight_width": lo["highlight_width"],
                    "chase_origin": lo["chase_origin"],
                    "pixels": lo["pixels"],
                })
            out = {
                "fps": self.fps,
                "output_types": OUTPUT_TYPES,
                "look_output_types": LOOK_OUTPUT_TYPES,
                "look": look,
                "devices": [],
                "device_groups": self.device_groups,
                "playback_source": self.playback_source,
                "playback": self._playback_status_unlocked(),
            }
            for dev in self.devices:
                rx = self.fps_listener.get(dev["ip"]) if self.fps_listener else None
                d = {
                    "name": dev["name"],
                    "ip": dev["ip"],
                    "base_universe": dev["base_universe"],
                    "connected": dev["connected"],
                    "receiver_fps": rx["fps"] if rx else None,
                    "receiver_pkt_rate": rx["pkt_rate"] if rx else None,
                    "capabilities": _normalize_device_capabilities(dev.get("capabilities")),
                    "outputs": [],
                }
                for o in dev["outputs"]:
                    d["outputs"].append({
                        "name": o["name"],
                        "type": o["type"],
                        "count": o["count"],
                        "grid": o["grid"],
                        "universe": o["universe"],
                        "grid_order": o["grid_order"],
                        "grid_rotation": o["grid_rotation"],
                    })
                out["devices"].append(d)
            return out

    # ------------------------------------------------------------------
    #  Update from API
    # ------------------------------------------------------------------

    def update(self, data):
        config_targets = []  # devices needing output config update (sent outside lock)
        with self.lock:
            if "fps" in data:
                self.fps = max(1, min(120, int(data["fps"])))
            if "look_name" in data:
                self.active_look["name"] = str(data["look_name"])[:32]

            di = data.get("device")
            oi = data.get("output")

            if di is not None and 0 <= di < len(self.devices):
                dev = self.devices[di]
                if "ip" in data:
                    dev["ip"] = str(data["ip"])
                    dev["sender"].ip = dev["ip"]
                if oi is not None and 0 <= oi < len(dev["outputs"]):
                    o = dev["outputs"][oi]
                    if "grid_order" in data:
                        val = str(data["grid_order"])
                        if val in GRID_ORDERS:
                            o["grid_order"] = val
                    if "grid_rotation" in data:
                        val = int(data["grid_rotation"])
                        if val in GRID_ROTATIONS:
                            o["grid_rotation"] = val
            elif oi is not None and 0 <= oi < len(self.active_look["outputs"]):
                lo = self.active_look["outputs"][oi]
                if "output_type" in data:
                    new_type = str(data["output_type"])
                    if new_type in OUTPUT_TYPES:
                        _apply_type_to_look_output(lo, new_type)
                        _save_output_types([o["type"] for o in self.active_look["outputs"]])
                        for dev in self.devices:
                            if dev["sender"].connected:
                                config_targets.append(dev)
                if "effect" in data:
                    lo["effect"] = str(data["effect"])
                    lo["led_state"] = []
                if "playback" in data:
                    lo["playback"] = str(data["playback"])
                    lo["led_state"] = []
                if "speed" in data:
                    lo["speed"] = max(0.1, min(10.0, float(data["speed"])))
                if "angle" in data:
                    lo["angle"] = float(data["angle"])
                if "start_color" in data:
                    lo["start_color"] = [int(v) for v in data["start_color"]]
                if "end_color" in data:
                    lo["end_color"] = [int(v) for v in data["end_color"]]
                if "highlight_width" in data:
                    lo["highlight_width"] = max(1, min(30, int(data["highlight_width"])))
                if "chase_origin" in data:
                    val = str(data["chase_origin"])
                    if val in ("start", "center", "end"):
                        lo["chase_origin"] = val

        # Send output config outside lock to avoid blocking animation
        for dev in config_targets:
            self._send_output_config(dev)

    # ------------------------------------------------------------------
    #  Output config
    # ------------------------------------------------------------------

    def _send_output_config(self, dev):
        caps = _normalize_device_capabilities(dev.get("capabilities"))
        if not caps.get("output_config"):
            return False

        types = [lo["type"] for lo in self.active_look["outputs"]]
        type_to_id = {name: i for i, name in enumerate(LOOK_OUTPUT_TYPES)}
        send_output_config(dev["ip"], types, type_to_id)
        # Sync local device output records with the Look output types
        for oi, lo in enumerate(self.active_look["outputs"]):
            if oi < len(dev["outputs"]):
                typedef = OUTPUT_TYPES.get(lo["type"])
                if typedef:
                    dev["outputs"][oi]["type"] = lo["type"]
                    dev["outputs"][oi]["count"] = typedef["pixels"]
                    dev["outputs"][oi]["grid"] = (
                        typedef.get("grid_size")
                        if typedef["layout"] == "grid" else None
                    )
        return True

    # ------------------------------------------------------------------
    #  Device management
    # ------------------------------------------------------------------

    def connect(self, di):
        with self.lock:
            dev = self.devices[di]
            dev["sender"].ip = dev["ip"]
            dev["sender"].connect()
            dev["connected"] = True
            self._send_output_config(dev)

    def disconnect(self, di):
        with self.lock:
            dev = self.devices[di]
            if dev["sender"].connected:
                info = [(o["universe"], o["count"]) for o in dev["outputs"]]
                dev["sender"].blackout(info)
            dev["sender"].disconnect()
            dev["connected"] = False

    def add_device_from_node(self, node_info, auto_save=True):
        with self.lock:
            for dev in self.devices:
                if dev["ip"] == node_info["ip"]:
                    return {"status": "exists"}

            from artnet import parse_node_outputs
            output_cfgs = parse_node_outputs(
                node_info.get("long_name", ""),
                node_info.get("universes", []),
                OUTPUT_TYPES,
                node_report=node_info.get("node_report", ""),
                type_keys=LOOK_OUTPUT_TYPES)
            base_u = (
                output_cfgs[0].get("universe", 0)
                if output_cfgs else
                (node_info["universes"][0] if node_info.get("universes") else 0)
            )

            dev = {
                "name": node_info.get("short_name", "Node"),
                "ip": node_info["ip"],
                "base_universe": base_u,
                "connected": False,
                "sender": ArtNetSender(node_info["ip"]),
                "capabilities": _normalize_device_capabilities(node_info.get("capabilities")),
                "outputs": [],
            }
            for idx, o_cfg in enumerate(output_cfgs):
                resolved = resolve_output(o_cfg)
                universe = o_cfg.get(
                    "universe",
                    node_info["universes"][idx]
                    if idx < len(node_info.get("universes", []))
                    else base_u + idx,
                )
                is_grid = resolved["layout"] == "grid"
                dev["outputs"].append({
                    **resolved,
                    "universe": universe,
                    "grid_order": "serpentine" if is_grid else "progressive",
                    "grid_rotation": 0,
                })
            self.devices.append(dev)
            if auto_save:
                _save_devices(self.devices)
            return {"status": "added", "device_index": len(self.devices) - 1}

    def remove_device(self, di):
        with self.lock:
            if 0 <= di < len(self.devices):
                dev = self.devices[di]
                if dev["sender"].connected:
                    info = [(o["universe"], o["count"]) for o in dev["outputs"]]
                    dev["sender"].blackout(info)
                    dev["sender"].disconnect()
                self.devices.pop(di)
                _save_devices(self.devices)
                return True
        return False

    def _device_capability_status_unlocked(self, di, capability):
        if not (0 <= di < len(self.devices)):
            return {"ok": False, "error": "invalid device index"}

        dev = self.devices[di]
        caps = _normalize_device_capabilities(dev.get("capabilities"))
        if caps.get(capability):
            return {"ok": True, "device": dev["name"]}

        label = CONTROL_CAPABILITY_LABELS.get(capability, capability.replace("_", " "))
        if caps.get("known"):
            return {"ok": False, "error": f'{dev["name"]} does not advertise {label} support.'}
        return {"ok": False, "error": f'{dev["name"]} has not advertised {label} support.'}

    def device_capability_status(self, di, capability):
        with self.lock:
            return self._device_capability_status_unlocked(di, capability)

    def rename_device(self, di, new_name):
        with self.lock:
            status = self._device_capability_status_unlocked(di, "rename")
            if not status["ok"]:
                return status
            dev = self.devices[di]
            send_art_address(dev["ip"], new_name)
            dev["name"] = new_name
            _save_devices(self.devices)
            return {"ok": True}

    def set_device_ip(self, di, static_ip, gateway, subnet):
        with self.lock:
            status = self._device_capability_status_unlocked(di, "ip_config")
            if not status["ok"]:
                return status
            dev = self.devices[di]
            send_ip_config(dev["ip"], 1, static_ip, gateway, subnet)
            return {"ok": True}

    def revert_device_dhcp(self, di):
        with self.lock:
            status = self._device_capability_status_unlocked(di, "ip_config")
            if not status["ok"]:
                return status
            dev = self.devices[di]
            send_ip_config(dev["ip"], 0)
            return {"ok": True}

    def connect_all(self):
        with self.lock:
            for dev in self.devices:
                if not dev["sender"].connected:
                    dev["sender"].ip = dev["ip"]
                    dev["sender"].connect()
                    dev["connected"] = True
                    self._send_output_config(dev)

    def disconnect_all(self):
        with self.lock:
            for dev in self.devices:
                if dev["sender"].connected:
                    info = [(o["universe"], o["count"]) for o in dev["outputs"]]
                    dev["sender"].blackout(info)
                    dev["sender"].disconnect()
                    dev["connected"] = False

    # ------------------------------------------------------------------
    #  Device groups
    # ------------------------------------------------------------------

    def get_device_groups(self):
        with self.lock:
            return list(self.device_groups)

    def save_device_group(self, group):
        """Create or update a device group. group = {id, name, device_ips}."""
        with self.lock:
            gid = group.get("id")
            for i, g in enumerate(self.device_groups):
                if g["id"] == gid:
                    self.device_groups[i] = group
                    _save_device_groups(self.device_groups)
                    return group
            self.device_groups.append(group)
            _save_device_groups(self.device_groups)
            return group

    def delete_device_group(self, gid):
        with self.lock:
            self.device_groups = [g for g in self.device_groups if g["id"] != gid]
            _save_device_groups(self.device_groups)
            return True

    def hello_device(self, di):
        """Send a quick red flash to all outputs on a device to help locate it."""
        with self.lock:
            status = self._device_capability_status_unlocked(di, "hello")
            if not status["ok"]:
                return False
            dev = self.devices[di]
            if not dev["sender"].connected:
                return False
            outputs_info = []
            for o in dev["outputs"]:
                outputs_info.append((o["universe"], o["count"]))
            sender = dev["sender"]

        # Flash red then black (outside lock to avoid blocking animation)
        for universe, count in outputs_info:
            red = bytes([255, 0, 0] * count)
            sender.send_output(universe, red)
        sender.advance_sequence()
        time.sleep(1.0)
        for universe, count in outputs_info:
            sender.send_output(universe, bytes(count * 3))
        sender.advance_sequence()
        return True

    # ------------------------------------------------------------------
    #  Override pixels (for mixer / controller playback)
    # ------------------------------------------------------------------

    def set_override_pixels(self, pixels_per_output, device_ips=None):
        """Set override pixels from mixer or controller. Pass None to clear.
        device_ips: set of IP strings to target, or None for all devices.
        """
        with self.lock:
            self._override_pixels = pixels_per_output
            self._controller_device_ips = device_ips

    def _clear_override_unlocked(self):
        """Clear any cached override frame and controller-specific targeting."""
        self._override_pixels = None
        self._controller_device_ips = None

    def _clear_mixer_preview_unlocked(self):
        """Reset mixer preview bookkeeping without changing playback source."""
        self._mixer_preview_look = None
        self._mixer_preview_play_time = 0.0
        self._mixer_preview_transport_time = 0.0
        self._mixer_preview_start_mono = 0.0
        self._mixer_preview_playing = False
        self._mixer_preview_device_filter = None
        self._mixer_update_last_seq = 0

    def _set_playback_source_unlocked(self, source):
        """Apply playback-source transitions with centralized cleanup rules."""
        if source not in self.PLAYBACK_SOURCES:
            raise ValueError(f"Invalid playback source: {source!r}")

        if source != self.SOURCE_MIXER:
            self._clear_mixer_preview_unlocked()
        if source != self.SOURCE_CONTROLLER:
            self._controller_device_ips = None
        if source in (self.SOURCE_DESIGNER, self.SOURCE_IDLE):
            self._override_pixels = None

        self.playback_source = source

    def start_mixer_preview(self, look, device_filter=None,
                            play_time=0.0, playing=False,
                            transport_time=None):
        """Start previewing a look from the mixer on connected devices.
        play_time: wrapped playhead time shown in the timeline.
        transport_time: unwrapped timeline time for live playback.
        playing: whether the clock should advance.
        """
        with self.lock:
            self._clear_mixer_preview_unlocked()
            self._mixer_preview_look = look
            self._mixer_preview_play_time = play_time
            self._mixer_preview_transport_time = (
                play_time if transport_time is None else transport_time
            )
            self._mixer_preview_start_mono = time.monotonic()
            self._mixer_preview_playing = playing
            self._mixer_preview_device_filter = device_filter
            self._set_playback_source_unlocked(self.SOURCE_MIXER)

    def update_mixer_preview(self, play_time=None, playing=None,
                             transport_time=None, seq=None):
        """Update time / playing state without resending the full look.
        seq: monotonically increasing sequence number from the client. If
        provided and lower than the last processed sequence, the update is
        ignored (stale out-of-order request from browser connection pool).
        """
        with self.lock:
            if self._mixer_preview_look is None:
                return
            if seq is not None:
                if seq < self._mixer_update_last_seq:
                    return  # Stale request, ignore
                self._mixer_update_last_seq = seq
            if play_time is not None:
                self._mixer_preview_play_time = play_time
            if transport_time is not None:
                self._mixer_preview_transport_time = transport_time
            if play_time is not None or transport_time is not None:
                self._mixer_preview_start_mono = time.monotonic()
            if playing is not None:
                if playing and not self._mixer_preview_playing:
                    # Resuming: anchor monotonic clock at the current transport time.
                    self._mixer_preview_start_mono = time.monotonic()
                elif (not playing and self._mixer_preview_playing
                      and transport_time is None):
                    # Pausing: freeze transport time at the current value.
                    self._mixer_preview_transport_time += (
                        time.monotonic() - self._mixer_preview_start_mono)
                self._mixer_preview_playing = playing

    def stop_mixer_preview(self):
        """Stop mixer preview, return to idle (no output)."""
        with self.lock:
            self._set_playback_source_unlocked(self.SOURCE_IDLE)

    def set_playback_source(self, source):
        """Explicitly set the playback source.

        Mixer preview should be started through start_mixer_preview() so the
        preview look and timing state are initialized consistently.
        Returns True when the source is accepted, else False.
        """
        with self.lock:
            if source not in self.API_PLAYBACK_SOURCES:
                return False
            self._set_playback_source_unlocked(source)
            return True

    def get_mixer_preview(self):
        """Return (look, computed_time) if mixer preview is active, else (None, 0)."""
        with self.lock:
            if self._mixer_preview_look:
                if self._mixer_preview_playing:
                    t = self._mixer_preview_transport_time + (
                        time.monotonic() - self._mixer_preview_start_mono)
                else:
                    t = self._mixer_preview_transport_time
                return self._mixer_preview_look, t
            return None, 0.0

    # ------------------------------------------------------------------
    #  Animation tick
    # ------------------------------------------------------------------

    def tick(self):
        now = time.monotonic()
        send_queue = []

        with self.lock:
            t = now - self.start_time
            dt = max(now - self.last_tick, 0.001)
            self.last_tick = now

            if self._override_pixels is not None:
                # Use mixer/controller pre-computed pixels
                for i, lo in enumerate(self.active_look["outputs"]):
                    if i < len(self._override_pixels) and self._override_pixels[i]:
                        lo["pixels"] = self._override_pixels[i]
                    else:
                        lo["pixels"] = []
            elif self.playback_source == self.SOURCE_DESIGNER:
                # Compute from designer (active look)
                for lo in self.active_look["outputs"]:
                    if lo["type"] == "none" or lo["count"] == 0:
                        lo["pixels"] = []
                        continue
                    speed = lo["speed"]
                    scaled_t = t * speed
                    af = compute_anim_factor(scaled_t, lo["playback"])
                    fn = EFFECTS.get(lo["effect"], fx_none)
                    pixels = fn(
                        count=lo["count"], t=scaled_t, dt=dt,
                        speed=speed, anim_factor=af,
                        duration=5.0,
                        playback=lo["playback"],
                        start_color=tuple(lo["start_color"]),
                        end_color=tuple(lo["end_color"]),
                        state=lo["led_state"],
                        grid=lo.get("grid"), angle=lo["angle"],
                        highlight_width=lo["highlight_width"],
                        chase_origin=lo["chase_origin"],
                    )
                    lo["pixels"] = [list(p) for p in pixels]
            else:
                # Idle: no output (black)
                for lo in self.active_look["outputs"]:
                    lo["pixels"] = []

            # Send to connected devices
            dev_filter = self._mixer_preview_device_filter
            ctrl_ips = self._controller_device_ips if self.playback_source == self.SOURCE_CONTROLLER else None
            for di, dev in enumerate(self.devices):
                if not dev["sender"].connected:
                    continue
                if dev_filter is not None and di not in dev_filter:
                    continue
                if ctrl_ips is not None and dev["ip"] not in ctrl_ips:
                    continue
                for oi, o in enumerate(dev["outputs"]):
                    if oi >= len(self.active_look["outputs"]):
                        continue
                    lo = self.active_look["outputs"][oi]
                    if lo["type"] == "none" or not lo["pixels"]:
                        continue
                    send_pixels = list(lo["pixels"])

                    grid = lo.get("grid")
                    if grid:
                        cols, rows = grid
                        if o.get("grid_rotation", 0) != 0:
                            send_pixels = apply_grid_rotation(
                                send_pixels, cols, rows, o["grid_rotation"])
                        send_pixels = apply_serpentine(send_pixels, cols, rows)

                    buf = bytearray()
                    for r, g, b in send_pixels:
                        buf.extend((r & 0xFF, g & 0xFF, b & 0xFF))
                    send_queue.append((dev["sender"], o["universe"], bytes(buf)))

        senders_used = set()
        for sender, universe, data in send_queue:
            sender.send_output(universe, data)
            senders_used.add(id(sender))
        seen = set()
        for sender, _, _ in send_queue:
            sid = id(sender)
            if sid not in seen:
                seen.add(sid)
                sender.advance_sequence()

    def shutdown(self):
        self.running = False
        for dev in self.devices:
            if dev["sender"].connected:
                info = [(o["universe"], o["count"]) for o in dev["outputs"]]
                dev["sender"].blackout(info)
                dev["sender"].disconnect()


# ======================================================================
#  ANIMATION THREAD
# ======================================================================

def animation_loop(state):
    next_frame = time.monotonic()
    while state.running:
        state.tick()
        next_frame += 1.0 / max(1, state.fps)
        sleep_time = next_frame - time.monotonic()
        if sleep_time > 0:
            time.sleep(sleep_time)
        else:
            next_frame = time.monotonic()
