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
from artnet import ArtNetSender, send_output_config, send_art_address


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
        with open(_STATE_FILE, "w") as f:
            json.dump({"output_types": types}, f)
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

    def __init__(self, fps_listener):
        self.lock = threading.Lock()
        self.running = True
        self.fps = DEFAULT_FPS
        self.fps_listener = fps_listener
        self.start_time = time.monotonic()
        self.last_tick = self.start_time
        self.devices = []
        self.playback_source = self.SOURCE_DESIGNER

        # Active Look — the animation being sent to all connected devices
        saved_types = _load_output_types()
        look_outputs = []
        for i, o_cfg in enumerate(DEFAULT_TEMPLATE):
            cfg = dict(o_cfg)
            if saved_types and i < len(saved_types):
                cfg["type"] = saved_types[i]
            look_outputs.append(_make_look_output(cfg))
        self.active_look = {"name": "Look 1", "outputs": look_outputs}

        # Mixer / controller override pixel buffers (set externally)
        self._override_pixels = None  # list of pixel lists per output, or None
        # Mixer live preview state
        self._mixer_preview_look = None
        self._mixer_preview_start = 0.0

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
                "playback_source": self.playback_source,
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
                                self._send_output_config(dev)
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

    # ------------------------------------------------------------------
    #  Output config
    # ------------------------------------------------------------------

    def _send_output_config(self, dev):
        types = [lo["type"] for lo in self.active_look["outputs"]]
        type_to_id = {name: i for i, name in enumerate(LOOK_OUTPUT_TYPES)}
        send_output_config(dev["ip"], types, type_to_id)

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

    def add_device_from_node(self, node_info):
        with self.lock:
            for dev in self.devices:
                if dev["ip"] == node_info["ip"]:
                    return {"status": "exists"}

            from artnet import parse_node_outputs
            output_cfgs = parse_node_outputs(
                node_info.get("long_name", ""),
                node_info.get("universes", []),
                OUTPUT_TYPES)
            base_u = node_info["universes"][0] if node_info.get("universes") else 0

            dev = {
                "name": node_info.get("short_name", "Node"),
                "ip": node_info["ip"],
                "base_universe": base_u,
                "connected": False,
                "sender": ArtNetSender(node_info["ip"]),
                "outputs": [],
            }
            for idx, o_cfg in enumerate(output_cfgs):
                resolved = resolve_output(o_cfg)
                universe = (node_info["universes"][idx]
                            if idx < len(node_info.get("universes", []))
                            else base_u + idx)
                is_grid = resolved["layout"] == "grid"
                dev["outputs"].append({
                    **resolved,
                    "universe": universe,
                    "grid_order": "serpentine" if is_grid else "progressive",
                    "grid_rotation": 0,
                })
            self.devices.append(dev)
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
                return True
        return False

    def rename_device(self, di, new_name):
        with self.lock:
            if 0 <= di < len(self.devices):
                dev = self.devices[di]
                send_art_address(dev["ip"], new_name)
                dev["name"] = new_name
                return True
        return False

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
    #  Override pixels (for mixer / controller playback)
    # ------------------------------------------------------------------

    def set_override_pixels(self, pixels_per_output):
        """Set override pixels from mixer or controller. Pass None to clear."""
        with self.lock:
            self._override_pixels = pixels_per_output

    def start_mixer_preview(self, look):
        """Start previewing a look from the mixer on connected devices."""
        with self.lock:
            self._mixer_preview_look = look
            self._mixer_preview_start = time.monotonic()
            self.playback_source = self.SOURCE_MIXER

    def stop_mixer_preview(self):
        """Stop mixer preview, return to designer."""
        with self.lock:
            self._mixer_preview_look = None
            self._override_pixels = None
            self.playback_source = self.SOURCE_DESIGNER

    def get_mixer_preview(self):
        """Return (look, elapsed) if mixer preview is active, else (None, 0)."""
        with self.lock:
            if self._mixer_preview_look:
                return self._mixer_preview_look, time.monotonic() - self._mixer_preview_start
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
                        lo["pixels"] = [list(p) for p in self._override_pixels[i]]
                    else:
                        lo["pixels"] = []
            else:
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
                        playback=lo["playback"],
                        start_color=tuple(lo["start_color"]),
                        end_color=tuple(lo["end_color"]),
                        state=lo["led_state"],
                        grid=lo.get("grid"), angle=lo["angle"],
                        highlight_width=lo["highlight_width"],
                        chase_origin=lo["chase_origin"],
                    )
                    lo["pixels"] = [list(p) for p in pixels]

            # Send to connected devices
            for dev in self.devices:
                if not dev["sender"].connected:
                    continue
                for oi, o in enumerate(dev["outputs"]):
                    if oi >= len(self.active_look["outputs"]):
                        continue
                    lo = self.active_look["outputs"][oi]
                    if lo["type"] == "none" or not lo["pixels"]:
                        continue
                    send_pixels = [tuple(p) for p in lo["pixels"]]

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
