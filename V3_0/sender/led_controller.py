#!/usr/bin/env python3
"""
led_controller.py — PrimusV3 Art-Net LED Controller

Art-Net only.  Each output gets its own standard-compliant universe
(≤512 bytes).  Brightness locked to max.  Receives FPS telemetry
from receivers on port 6455.

Edit OUTPUT_TYPES and DEVICES below to configure your setup.

Usage:
    python3 led_controller.py
    python3 led_controller.py --port 8080

No external dependencies — uses only Python standard library.
"""

import argparse
import json
import math
import os
import re
import random
import socket
import struct
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler


# ======================================================================
#  OUTPUT TYPE TABLE — single source of truth
# ======================================================================
# To change what a "short_strip" means, edit ONE row here.
# To add a new type (e.g. "ring"), add one row.

OUTPUT_TYPES = {
    "none":        {"pixels": 0, "layout": "none"},
    "short_strip": {"pixels": 30, "layout": "linear"},
    "long_strip":  {"pixels": 72, "layout": "linear"},
    "grid":        {"pixels": 64, "layout": "grid", "grid_size": [8, 8]},
}

# Ordered list for UI dropdowns (index matches firmware type IDs 0-3)
LOOK_OUTPUT_TYPES = ["none", "short_strip", "long_strip", "grid"]

# ======================================================================
#  DEVICE CONFIGURATION
# ======================================================================
# Each output references a type by name.  Pixel count and layout are
# derived from OUTPUT_TYPES automatically.
#
# base_universe: first Art-Net universe for this device.
# Output N → universe = base_universe + N.
# For multi-device: set base_universe = 0, 3, 6, … etc.

DEVICES = [
    {
        "name": "Costume 1",
        "ip": "192.168.1.100",
        "base_universe": 0,
        "outputs": [
            {"name": "A0", "type": "short_strip"},
            {"name": "A1", "type": "long_strip"},
            {"name": "A2", "type": "grid"},
        ],
    },
    # Example: second device with 2 outputs
    # {
    #     "name": "Costume 2",
    #     "ip": "192.168.1.101",
    #     "base_universe": 3,
    #     "outputs": [
    #         {"name": "A0", "type": "long_strip"},
    #         {"name": "A1", "type": "long_strip"},
    #     ],
    # },
]

DEFAULT_FPS = 30
DEFAULT_EFFECT = "pulse"
DEFAULT_SPEED = 1.0
DEFAULT_PLAYBACK = "loop"
DEFAULT_START_COLOR = [255, 0, 255]
DEFAULT_END_COLOR = [0, 255, 255]

# Grid outputs get different default colors (magenta→cyan for strips above)
DEFAULT_GRID_START_COLOR = [255, 0, 255]
DEFAULT_GRID_END_COLOR = [0, 255, 255]
DEFAULT_STRIP_START_COLOR = [255, 0, 0]
DEFAULT_STRIP_END_COLOR = [0, 0, 255]

EFFECT_NAMES = ["none", "solid", "pulse", "linear",
                "constrainbow", "rainbow", "wipe",
                "radial", "spiral"]
PLAYBACK_MODES = ["loop", "boomerang", "once"]
GRID_ORDERS = ["progressive", "serpentine"]

# ── Persistence ───────────────────────────────────────────────────────
_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".primus_state.json")

def _save_output_types(types):
    """Save Look output types to disk."""
    try:
        with open(_STATE_FILE, "w") as f:
            json.dump({"output_types": types}, f)
    except OSError:
        pass

def _load_output_types():
    """Load saved Look output types, or return None."""
    try:
        with open(_STATE_FILE, "r") as f:
            data = json.load(f)
        types = data.get("output_types", [])
        if types and all(t in OUTPUT_TYPES for t in types):
            return types
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    return None
GRID_ROTATIONS = [0, 90, 180, 270]


# ======================================================================
#  ART-NET TRANSPORT — one packet per output per frame
# ======================================================================

ARTNET_HEADER     = b"Art-Net\x00"
ARTNET_OPCODE_DMX = 0x5000
ARTNET_OPCODE_POLL = 0x2000
ARTNET_OPCODE_POLLREPLY = 0x2100
ARTNET_VERSION    = 14
ARTNET_PORT       = 6454


class ArtNetSender:
    """Sends one Art-Net ArtDmx packet per output, per frame."""

    def __init__(self, ip):
        self.ip = ip
        self.sock = None
        self.connected = False
        self.sequence = 1  # 1-255: Art-Net spec (0 = disable sequencing)

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.connected = True

    def disconnect(self):
        self.connected = False
        if self.sock:
            self.sock.close()
            self.sock = None

    def _build_packet(self, universe, rgb_data):
        """Build a standard Art-Net ArtDmx packet for one universe."""
        if len(rgb_data) % 2 != 0:
            rgb_data = rgb_data + b'\x00'
        length = len(rgb_data)
        pkt = bytearray()
        pkt += ARTNET_HEADER
        pkt += struct.pack("<H", ARTNET_OPCODE_DMX)
        pkt += struct.pack(">H", ARTNET_VERSION)
        pkt += bytes([self.sequence])
        pkt += bytes([0])                              # Physical
        pkt += struct.pack("<H", universe)             # Universe (LE)
        pkt += struct.pack(">H", length)               # Length (BE)
        pkt += rgb_data
        return bytes(pkt)

    def send_output(self, universe, rgb_data):
        """Send one Art-Net packet for a single output/universe."""
        if not self.connected or not self.sock:
            return
        pkt = self._build_packet(universe, rgb_data)
        self.sock.sendto(pkt, (self.ip, ARTNET_PORT))

    def advance_sequence(self):
        """Advance sequence counter after all outputs in a frame are sent."""
        self.sequence = (self.sequence % 255) + 1

    def blackout(self, outputs_info):
        """Send black to all outputs."""
        if not self.connected:
            return
        for universe, pixel_count in outputs_info:
            self.send_output(universe, bytes(pixel_count * 3))
        self.advance_sequence()


# ======================================================================
#  ART-NET DISCOVERY — ArtPoll broadcast
# ======================================================================

def _get_subnet_broadcast():
    """Derive the subnet broadcast address from the host's local IP."""
    try:
        # Connect trick to find the local IP on the LAN
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        # Assume /24 — replace last octet with 255
        parts = local_ip.split(".")
        parts[3] = "255"
        return ".".join(parts)
    except Exception:
        return None


def discover_artnet_nodes(timeout=2.0):
    """Send ArtPoll via broadcast, subnet broadcast, and unicast to known
    devices.  Collect ArtPollReply responses.

    Returns a list of dicts:
      {"ip", "short_name", "long_name", "num_ports", "universes": [int,...]}
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(0.25)
    # Bind to Art-Net port so we receive replies (nodes reply to port 6454)
    sock.bind(("", ARTNET_PORT))

    # Build ArtPoll packet (14 bytes)
    poll = bytearray()
    poll += ARTNET_HEADER
    poll += struct.pack("<H", ARTNET_OPCODE_POLL)
    poll += struct.pack(">H", ARTNET_VERSION)
    poll += bytes([0x00, 0x00])  # TalkToMe, Priority

    # Send to multiple destinations for maximum reach:
    #  1) limited broadcast  (may be blocked by routers / macOS firewall)
    #  2) subnet broadcast   (usually works on local LAN)
    #  3) unicast to every configured device IP (guaranteed delivery)
    targets = {"255.255.255.255"}
    subnet_bc = _get_subnet_broadcast()
    if subnet_bc:
        targets.add(subnet_bc)
    for dev in DEVICES:
        targets.add(dev["ip"])
    for dest in targets:
        sock.sendto(bytes(poll), (dest, ARTNET_PORT))

    nodes = {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            raw, addr = sock.recvfrom(600)
        except socket.timeout:
            continue

        if len(raw) < 44 or raw[:8] != ARTNET_HEADER:
            continue
        opcode = struct.unpack("<H", raw[8:10])[0]
        if opcode != ARTNET_OPCODE_POLLREPLY:
            continue

        ip = "{}.{}.{}.{}".format(raw[10], raw[11], raw[12], raw[13])
        short_name = raw[26:44].split(b'\x00')[0].decode("ascii", errors="replace")
        long_name = raw[44:108].split(b'\x00')[0].decode("ascii", errors="replace")
        num_ports = raw[173] if len(raw) > 173 else 0
        universes = []
        for i in range(min(num_ports, 4)):
            if len(raw) > 190 + i:
                universes.append(raw[190 + i])

        nodes[ip] = {
            "ip": ip,
            "short_name": short_name,
            "long_name": long_name,
            "num_ports": num_ports,
            "universes": universes,
        }

    sock.close()
    return list(nodes.values())


# ======================================================================
#  NODE OUTPUT PARSING — derive config from ArtPollReply
# ======================================================================

def _match_output_type(display_name):
    """Match an Arduino display name (e.g. 'Short Strip') to an OUTPUT_TYPES key."""
    key = display_name.strip().lower().replace(" ", "_")
    if key in OUTPUT_TYPES:
        return key
    for type_key in OUTPUT_TYPES:
        if key.startswith(type_key):
            return type_key
    return None


def _parse_node_outputs(long_name, universes):
    """Parse ArtPollReply long_name to extract output configuration.

    Expected format: 'PrimusV3 LED Node | A0:Short Strip A1:Long Strip ...'
    Falls back to generic long_strip outputs if parsing fails.
    """
    outputs = []
    parts = long_name.split("|")
    if len(parts) >= 2:
        matches = re.findall(r'(A\d+):([^A]+?)(?=\s+A\d+:|$)', parts[1])
        for name, type_display in matches:
            type_key = _match_output_type(type_display)
            if type_key:
                outputs.append({"name": name, "type": type_key})
    if not outputs:
        for i in range(len(universes)):
            outputs.append({"name": "A{}".format(i), "type": "long_strip"})
    return outputs


# ======================================================================
#  ART-NET NAMING — ArtAddress (opcode 0x6000)
# ======================================================================

def send_art_address(ip, short_name):
    """Send ArtAddress packet to set a node's short name."""
    pkt = bytearray(107)
    pkt[0:8] = ARTNET_HEADER
    struct.pack_into("<H", pkt, 8, 0x6000)
    struct.pack_into(">H", pkt, 10, ARTNET_VERSION)
    pkt[12] = 0x7F  # NetSwitch: no change
    pkt[13] = 0     # BindIndex
    name_bytes = short_name.encode("ascii", errors="replace")[:17]
    pkt[14:14 + len(name_bytes)] = name_bytes
    for i in range(96, 104):
        pkt[i] = 0x7F  # SwIn/SwOut: no change
    pkt[104] = 0x7F  # SubSwitch: no change
    pkt[106] = 0x00  # Command: AcNone
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(bytes(pkt), (ip, ARTNET_PORT))
    sock.close()


# ======================================================================
#  ART-NET OUTPUT CONFIG — ArtOutputConfig (opcode 0x8100)
# ======================================================================

# Maps sender type keys to firmware OutputType enum values
_TYPE_TO_FIRMWARE_ID = {t: i for i, t in enumerate(LOOK_OUTPUT_TYPES)}

def send_output_config(ip, output_types):
    """Send ArtOutputConfig packet to set output types on a receiver.
    output_types: list of type key strings, one per output.
    """
    num = len(output_types)
    pkt = bytearray(13 + num)
    pkt[0:8] = ARTNET_HEADER
    struct.pack_into("<H", pkt, 8, 0x8100)
    struct.pack_into(">H", pkt, 10, ARTNET_VERSION)
    pkt[12] = num
    for i, t in enumerate(output_types):
        pkt[13 + i] = _TYPE_TO_FIRMWARE_ID.get(t, 0)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(bytes(pkt), (ip, ARTNET_PORT))
    sock.close()


# ======================================================================
#  FPS BACK-CHANNEL LISTENER
# ======================================================================

FPS_LISTEN_PORT = 6455
FPS_MAGIC = b"PFP"


class FpsListener:
    """Listens on UDP 6455 for FPS telemetry from receivers."""

    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}       # ip → {"fps": int, "pkt_rate": int, "ts": float}
        self.running = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", FPS_LISTEN_PORT))
        self._sock.settimeout(1.0)

    def run(self):
        while self.running:
            try:
                raw, addr = self._sock.recvfrom(64)
            except socket.timeout:
                continue
            if len(raw) < 7 or raw[:3] != FPS_MAGIC:
                continue
            fps = (raw[3] << 8) | raw[4]
            pkt = (raw[5] << 8) | raw[6]
            with self.lock:
                self.data[addr[0]] = {
                    "fps": fps, "pkt_rate": pkt, "ts": time.monotonic()
                }

    def get(self, ip):
        with self.lock:
            entry = self.data.get(ip)
            if entry and (time.monotonic() - entry["ts"]) < 5.0:
                return entry
        return None

    def stop(self):
        self.running = False
        self._sock.close()


# ======================================================================
#  COLOR UTILITIES
# ======================================================================

def lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def hsv_to_rgb(h, s, v):
    i = int(h * 6.0)
    f = h * 6.0 - i
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t_ = v * (1.0 - (1.0 - f) * s)
    r, g, b = [
        (v, t_, p), (q, v, p), (p, v, t_),
        (p, q, v), (t_, p, v), (v, p, q),
    ][i % 6]
    return (int(r * 255), int(g * 255), int(b * 255))


def random_color_between(c1, c2):
    return lerp_color(c1, c2, random.random())


# ======================================================================
#  EFFECTS ENGINE
# ======================================================================

def compute_anim_factor(scaled_t, playback):
    if playback == "once":
        return min(scaled_t * 0.2, 1.0)
    elif playback == "boomerang":
        cyc = (scaled_t * 0.2) % 2.0
        return cyc if cyc <= 1.0 else 2.0 - cyc
    else:
        return (scaled_t * 0.2) % 1.0


def fx_none(count, **kw):
    return [(0, 0, 0)] * count


def fx_solid(count, start_color, **kw):
    return [start_color] * count


def fx_pulse(count, t, start_color, end_color, **kw):
    f = (math.sin(t) + 1.0) / 2.0
    c = lerp_color(start_color, end_color, f)
    return [c] * count


def fx_linear(count, anim_factor, start_color, end_color,
              grid=None, angle=0, **kw):
    pixels = []
    if grid:
        cols, rows = grid
        rad = math.radians(angle)
        ax, ay = math.cos(rad), math.sin(rad)
        ox = math.cos(anim_factor * math.tau) * 0.2
        oy = math.sin(anim_factor * math.tau) * 0.2
        for idx in range(count):
            x, y = idx % cols, idx // cols
            nx = x / max(cols - 1, 1) - 0.5
            ny = y / max(rows - 1, 1) - 0.5
            dot = (nx + ox) * ax + (ny + oy) * ay
            pixels.append(lerp_color(start_color, end_color,
                                     max(0.0, min(1.0, dot + 0.5))))
    else:
        for i in range(count):
            pos = i / max(count - 1, 1)
            shifted = (pos + anim_factor) % 1.0
            pixels.append(lerp_color(start_color, end_color, shifted))
    return pixels


def fx_constrainbow(count, dt, speed, playback,
                    start_color, end_color, state, **kw):
    while len(state) < count:
        state.append({
            "cur": random_color_between(start_color, end_color),
            "nxt": random_color_between(start_color, end_color),
            "prg": random.random(),
        })
    inc = dt * 0.3 * speed
    pixels = []
    for i in range(count):
        s = state[i]
        s["prg"] += inc
        if playback == "boomerang":
            cp = (s["prg"] * 2.0) % 2.0
            f = cp if cp < 1.0 else 2.0 - cp
            pixels.append(lerp_color(s["cur"], s["nxt"], f))
            if s["prg"] >= 1.0:
                s["cur"] = s["nxt"]
                s["nxt"] = random_color_between(start_color, end_color)
                s["prg"] = 0.0
        elif playback == "once":
            s["prg"] = min(s["prg"], 1.0)
            pixels.append(lerp_color(s["cur"], s["nxt"], s["prg"]))
        else:
            if s["prg"] >= 1.0:
                s["cur"] = s["nxt"]
                s["nxt"] = random_color_between(start_color, end_color)
                s["prg"] = 0.0
            pixels.append(lerp_color(s["cur"], s["nxt"], s["prg"]))
    return pixels


def fx_rainbow(count, t, grid=None, **kw):
    pixels = []
    if grid:
        cols, rows = grid
        for idx in range(count):
            x, y = idx % cols, idx // cols
            offset = (x / cols + y / rows) * 0.5
            hue = (t * 0.2 + offset) % 1.0
            pixels.append(hsv_to_rgb(hue, 1.0, 1.0))
    else:
        for i in range(count):
            pos = i / max(count - 1, 1)
            hue = (pos + t * 0.2) % 1.0
            pixels.append(hsv_to_rgb(hue, 1.0, 1.0))
    return pixels


def fx_radial(count, t, anim_factor, start_color, end_color,
              grid=None, **kw):
    """Radial gradient from center outward — grid only, falls back to pulse."""
    if not grid:
        f = (math.sin(t) + 1.0) / 2.0
        return [lerp_color(start_color, end_color, f)] * count
    cols, rows = grid
    cx, cy = (cols - 1) / 2.0, (rows - 1) / 2.0
    max_dist = math.hypot(cx, cy)
    pixels = []
    for idx in range(count):
        x, y = idx % cols, idx // cols
        dist = math.hypot(x - cx, y - cy) / max(max_dist, 0.001)
        shifted = (dist + anim_factor) % 1.0
        pixels.append(lerp_color(start_color, end_color, shifted))
    return pixels


def fx_spiral(count, t, anim_factor, start_color, end_color,
              grid=None, **kw):
    """Spiral pattern from center — grid only, falls back to rainbow."""
    if not grid:
        pixels = []
        for i in range(count):
            pos = i / max(count - 1, 1)
            hue = (pos + t * 0.2) % 1.0
            pixels.append(hsv_to_rgb(hue, 1.0, 1.0))
        return pixels
    cols, rows = grid
    cx, cy = (cols - 1) / 2.0, (rows - 1) / 2.0
    max_dist = math.hypot(cx, cy)
    pixels = []
    for idx in range(count):
        x, y = idx % cols, idx // cols
        angle = math.atan2(y - cy, x - cx) / math.tau + 0.5  # 0..1
        dist = math.hypot(x - cx, y - cy) / max(max_dist, 0.001)
        spiral_val = (angle + dist * 2.0 + anim_factor) % 1.0
        pixels.append(lerp_color(start_color, end_color, spiral_val))
    return pixels


def fx_knight_rider(count, t, start_color, end_color,
                    highlight_width=5, **kw):
    """Bouncing highlight bar with smooth falloff — strip effect."""
    if count <= 1:
        return [list(start_color)] * count
    # highlight_width is 1-30; map to pixel radius as fraction of strip
    hw = max(int(highlight_width), 1)
    radius = hw * count / 30.0  # width 30 = full strip, width 1 = ~1 pixel
    # Oscillate position 0 → count-1 → 0
    cyc = (t * 0.3) % 2.0
    pos = cyc if cyc <= 1.0 else 2.0 - cyc
    center = pos * (count - 1)
    pixels = []
    for i in range(count):
        dist = abs(i - center)
        if dist < radius:
            f = 1.0 - (dist / radius)
            pixels.append(lerp_color(end_color, start_color, f))
        else:
            pixels.append(end_color)
    return pixels


def fx_chase(count, anim_factor, start_color, end_color,
             chase_origin="start", grid=None, angle=0, **kw):
    """Color chase / fill with configurable origin and angle (grid)."""
    if grid:
        cols, rows = grid
        rad = math.radians(angle)
        ax, ay = math.cos(rad), math.sin(rad)
        pixels = []
        for idx in range(count):
            x, y = idx % cols, idx // cols
            nx = x / max(cols - 1, 1) - 0.5
            ny = y / max(rows - 1, 1) - 0.5
            if chase_origin == "center":
                proj = abs(nx * ax + ny * ay) * 2.0
            elif chase_origin == "end":
                proj = 1.0 - (nx * ax + ny * ay + 0.5)
            else:
                proj = nx * ax + ny * ay + 0.5
            pixels.append(list(end_color) if proj <= anim_factor
                          else list(start_color))
        return pixels
    else:
        if chase_origin == "center":
            mid = count / 2.0
            fill = anim_factor * mid
            return [list(end_color) if abs(i - mid + 0.5) <= fill
                    else list(start_color) for i in range(count)]
        elif chase_origin == "end":
            wi = math.floor(anim_factor * count)
            return [list(end_color) if i >= count - wi
                    else list(start_color) for i in range(count)]
        else:
            wi = math.floor(anim_factor * count)
            return [list(end_color) if i < wi
                    else list(start_color) for i in range(count)]


# ── Grid pixel reordering ─────────────────────────────────────────────

def _apply_serpentine(pixels, cols, rows):
    """Reorder pixels: even rows L→R, odd rows R→L."""
    out = list(pixels)
    for r in range(rows):
        if r % 2 == 1:
            start = r * cols
            end = start + cols
            out[start:end] = out[start:end][::-1]
    return out


def _apply_grid_rotation(pixels, cols, rows, rotation):
    """Rotate grid output by 0/90/180/270 degrees."""
    if rotation == 0:
        return pixels
    # Build 2D array
    grid_2d = []
    for r in range(rows):
        grid_2d.append(pixels[r * cols:(r + 1) * cols])
    if rotation == 90:
        # Transpose + reverse each row
        rotated = []
        for c in range(cols):
            row = [grid_2d[rows - 1 - r][c] for r in range(rows)]
            rotated.append(row)
        new_rows, new_cols = cols, rows
    elif rotation == 180:
        rotated = [row[::-1] for row in reversed(grid_2d)]
        new_rows, new_cols = rows, cols
    elif rotation == 270:
        rotated = []
        for c in range(cols - 1, -1, -1):
            row = [grid_2d[r][c] for r in range(rows)]
            rotated.append(row)
        new_rows, new_cols = cols, rows
    else:
        return pixels
    # Flatten back
    out = []
    for row in rotated:
        out.extend(row)
    return out


EFFECTS = {
    "none":         fx_none,
    "solid":        fx_solid,
    "pulse":        fx_pulse,
    "linear":       fx_linear,
    "constrainbow": fx_constrainbow,
    "rainbow":      fx_rainbow,
    "knight_rider": fx_knight_rider,
    "chase":        fx_chase,
    "radial":       fx_radial,
    "spiral":       fx_spiral,
}


# ======================================================================
#  CONTROLLER STATE
# ======================================================================

def _resolve_output(cfg):
    """Resolve an output config entry, deriving pixel count from type."""
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
    """Change a Look output's type, updating count/grid/layout and resetting state."""
    typedef = OUTPUT_TYPES.get(new_type)
    if typedef is None:
        return
    lo["type"] = new_type
    lo["count"] = typedef["pixels"]
    lo["layout"] = typedef["layout"]
    lo["grid"] = typedef.get("grid_size") if typedef["layout"] == "grid" else None
    lo["led_state"] = []
    lo["pixels"] = []
    # Reset colors to type-appropriate defaults
    is_grid = typedef["layout"] == "grid"
    lo["start_color"] = list(DEFAULT_GRID_START_COLOR if is_grid else DEFAULT_STRIP_START_COLOR)
    lo["end_color"] = list(DEFAULT_GRID_END_COLOR if is_grid else DEFAULT_STRIP_END_COLOR)
    # Reset effect for 'none' type
    if new_type == "none":
        lo["effect"] = "none"


class ControllerState:
    """Holds all settings, computes animations, sends Art-Net frames."""

    def __init__(self, fps_listener):
        self.lock = threading.Lock()
        self.running = True
        self.fps = DEFAULT_FPS
        self.fps_listener = fps_listener
        self.start_time = time.monotonic()
        self.last_tick = self.start_time
        self.devices = []

        # Active Look — the animation being sent to all connected costumes
        template = DEVICES[0]["outputs"] if DEVICES else [
            {"name": "A0", "type": "short_strip"},
            {"name": "A1", "type": "long_strip"},
            {"name": "A2", "type": "grid"},
        ]
        # Restore saved output types if available
        saved_types = _load_output_types()
        look_outputs = []
        for i, o_cfg in enumerate(template):
            cfg = dict(o_cfg)
            if saved_types and i < len(saved_types):
                cfg["type"] = saved_types[i]
            resolved = _resolve_output(cfg)
            is_grid = resolved["layout"] == "grid"
            look_outputs.append({
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
            })
        self.active_look = {"name": "Look 1", "outputs": look_outputs}

        # Devices (costumes) — physical connection + hardware settings only
        for dev_cfg in DEVICES:
            base_u = dev_cfg.get("base_universe", 0)
            dev = {
                "name": dev_cfg["name"],
                "ip": dev_cfg["ip"],
                "base_universe": base_u,
                "connected": False,
                "sender": ArtNetSender(dev_cfg["ip"]),
                "outputs": [],
            }
            for idx, o_cfg in enumerate(dev_cfg["outputs"]):
                resolved = _resolve_output(o_cfg)
                is_grid = resolved["layout"] == "grid"
                dev["outputs"].append({
                    **resolved,
                    "universe": base_u + idx,
                    "grid_order": "serpentine" if is_grid else "progressive",
                    "grid_rotation": 0,
                })
            self.devices.append(dev)

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
            out = {"fps": self.fps, "output_types": OUTPUT_TYPES,
                   "look_output_types": LOOK_OUTPUT_TYPES,
                   "look": look, "devices": []}
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

    def update(self, data):
        with self.lock:
            if "fps" in data:
                self.fps = max(1, min(120, int(data["fps"])))
            if "look_name" in data:
                self.active_look["name"] = str(data["look_name"])[:32]

            di = data.get("device")
            oi = data.get("output")

            if di is not None and 0 <= di < len(self.devices):
                # Device-level update (IP, hardware settings)
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
                # Look output update (animation settings)
                lo = self.active_look["outputs"][oi]
                if "output_type" in data:
                    new_type = str(data["output_type"])
                    if new_type in OUTPUT_TYPES:
                        _apply_type_to_look_output(lo, new_type)
                        # Persist output types to disk
                        _save_output_types([o["type"] for o in self.active_look["outputs"]])
                        # Send updated config to all connected devices
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

    def _send_output_config(self, dev):
        """Send current Look output types to a device."""
        types = [lo["type"] for lo in self.active_look["outputs"]]
        send_output_config(dev["ip"], types)

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
        """Add a device from ArtPoll discovery data. Returns status dict."""
        with self.lock:
            for dev in self.devices:
                if dev["ip"] == node_info["ip"]:
                    return {"status": "exists"}

            output_cfgs = _parse_node_outputs(
                node_info.get("long_name", ""),
                node_info.get("universes", []))
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
                resolved = _resolve_output(o_cfg)
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
        """Remove a device by index."""
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
        """Rename a device locally and send ArtAddress to the node."""
        with self.lock:
            if 0 <= di < len(self.devices):
                dev = self.devices[di]
                send_art_address(dev["ip"], new_name)
                dev["name"] = new_name
                return True
        return False

    def tick(self):
        """Compute one frame and send per-universe Art-Net packets."""
        now = time.monotonic()
        send_queue = []  # [(sender, universe, rgb_bytes), ...]

        with self.lock:
            t = now - self.start_time
            dt = max(now - self.last_tick, 0.001)
            self.last_tick = now

            # Compute animation once per Look output
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

            # Send to all connected devices
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

                    # Apply device-specific hardware transformations
                    # Use Look output's grid info (reflects current type)
                    grid = lo.get("grid")
                    if grid:
                        cols, rows = grid
                        if o.get("grid_rotation", 0) != 0:
                            send_pixels = _apply_grid_rotation(
                                send_pixels, cols, rows, o["grid_rotation"])
                        send_pixels = _apply_serpentine(
                            send_pixels, cols, rows)

                    buf = bytearray()
                    for r, g, b in send_pixels:
                        buf.extend((r & 0xFF, g & 0xFF, b & 0xFF))
                    send_queue.append((dev["sender"], o["universe"], bytes(buf)))

        # Send outside lock — one packet per output
        senders_used = set()
        for sender, universe, data in send_queue:
            sender.send_output(universe, data)
            senders_used.add(id(sender))

        # Advance sequence once per frame per sender
        seen = set()
        for sender, _, _ in send_queue:
            sid = id(sender)
            if sid not in seen:
                seen.add(sid)
                sender.advance_sequence()

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


# ======================================================================
#  HTML PAGE
# ======================================================================

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PrimusV3 LED Controller</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
  background:#111827;color:#e5e7eb;padding:16px 24px;
  max-width:1100px;margin:0 auto;
}
h1{font-size:22px;color:#818cf8;margin-bottom:16px}
h2.section-title{font-size:17px;color:#818cf8;margin:20px 0 12px;
  border-bottom:1px solid #374151;padding-bottom:6px}
.look-section{background:#1f2937;border-radius:10px;padding:16px;
  margin-bottom:16px;border:1px solid #374151}
.look-header{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.look-header h2{font-size:17px;color:#a5b4fc;margin:0}
.look-name{background:#374151;border:1px solid #4b5563;color:#e5e7eb;
  border-radius:6px;padding:5px 10px;font-size:15px;width:200px;font-weight:600}
canvas{display:block;margin:0 auto 12px;border-radius:6px;background:#0f172a}
.outputs{display:flex;gap:10px;flex-wrap:wrap}
.output-panel{flex:1;min-width:200px;background:#111827;border:1px solid #374151;
  border-radius:8px;padding:12px}
.output-panel h3{font-size:14px;color:#c4b5fd;margin-bottom:10px}
.color-row{display:flex;gap:10px;margin-bottom:10px}
.color-box{display:flex;flex-direction:column;align-items:center;gap:3px}
.color-box label{font-size:11px;color:#9ca3af}
.color-box input[type=color]{width:52px;height:28px;border:none;border-radius:4px;
  cursor:pointer;background:none;padding:0}
.ctrl label{display:block;font-size:12px;color:#9ca3af;margin-bottom:3px}
.ctrl{margin-bottom:8px}
.ctrl select{width:100%;background:#374151;border:1px solid #4b5563;color:#e5e7eb;
  border-radius:5px;padding:5px 8px;font-size:13px}
.ctrl input[type=range]{width:100%}
.ctrl .val{font-size:12px;color:#e5e7eb;float:right}
button{background:#4f46e5;color:#fff;border:none;border-radius:6px;padding:7px 14px;
  font-size:13px;cursor:pointer;font-weight:500}
button:hover{background:#6366f1}
button.danger{background:#b91c1c}
button.danger:hover{background:#dc2626}
button.small{font-size:12px;padding:5px 10px}
.device-card{background:#1f2937;border-radius:8px;padding:12px 16px;
  margin-bottom:8px;border:1px solid #374151}
.dev-top{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.dev-top h3{font-size:15px;color:#a5b4fc;margin:0;white-space:nowrap}
.dev-top input[type=text]{background:#374151;border:1px solid #4b5563;color:#e5e7eb;
  border-radius:6px;padding:5px 10px;font-size:13px;width:140px}
.dev-top input[type=text].connected{border-color:#34d399;box-shadow:0 0 6px #34d39944}
.status-dot{width:10px;height:10px;border-radius:50%;background:#6b7280;
  display:inline-block}
.status-dot.on{background:#34d399}
.status-text{font-size:12px;color:#9ca3af}
.rx-fps{font-size:12px;color:#818cf8;font-weight:600}
.dev-actions{display:flex;gap:5px;margin-left:auto}
.hw-row{display:flex;gap:10px;margin-top:8px;flex-wrap:wrap;align-items:center}
.hw-row .ctrl{margin-bottom:0;min-width:130px;flex:0 0 auto}
.hw-row .hw-label{font-size:12px;color:#6b7280;margin-right:4px}
.toolbar{display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap}
.toolbar button{font-size:14px;padding:8px 16px}
.toolbar button.scan{background:#0d9488}
.toolbar button.scan:hover{background:#14b8a6}
.toolbar button.conn-all{background:#059669}
.toolbar button.conn-all:hover{background:#10b981}
.toolbar button.disc-all{background:#b91c1c}
.toolbar button.disc-all:hover{background:#dc2626}
.toolbar .scan-status{font-size:13px;color:#9ca3af}
.node-list{display:flex;flex-direction:column;gap:8px;margin-bottom:16px}
.node-card{background:#1f2937;border:1px solid #4b5563;border-radius:8px;
  padding:12px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px}
.node-card:hover{border-color:#6366f1}
.node-info{flex:1}.node-title{margin-bottom:4px}
.node-title .nn{color:#a5b4fc;font-weight:600;font-size:15px}
.node-title .ni{color:#9ca3af;font-size:13px;margin-left:8px}
.node-detail{font-size:12px;color:#6b7280}
.node-actions{display:flex;gap:6px;align-items:center}
.node-badge{font-size:12px;padding:4px 10px;border-radius:4px;font-weight:500}
.node-badge.connected{background:#065f4620;color:#34d399;border:1px solid #34d39944}
.scan-empty{color:#6b7280;font-size:13px;padding:12px;text-align:center}
details .section-title{cursor:pointer;list-style:none;user-select:none;
  color:#9ca3af;font-size:14px;padding:12px 0 4px;margin-top:8px}
details .section-title::before{content:'\u25b6 ';font-size:10px}
details[open] .section-title::before{content:'\u25bc '}
details .section-title::-webkit-details-marker{display:none}
.debug{background:#1f2937;border-radius:8px;padding:12px;border:1px solid #374151;
  display:flex;align-items:center;gap:10px;margin-top:16px;flex-wrap:wrap}
.debug label{font-size:13px;color:#9ca3af;white-space:nowrap}
.debug input[type=range]{flex:1;min-width:120px}
.debug .val{font-size:13px;color:#e5e7eb;width:32px;text-align:right}
</style>
</head>
<body>

<h1>PrimusV3 LED Controller</h1>
<div class="toolbar">
  <button class="scan" onclick="doScan()">Scan Network</button>
  <button class="conn-all" onclick="doConnectAll()">Connect All</button>
  <button class="disc-all" onclick="doDisconnectAll()">Disconnect All</button>
  <span class="scan-status" id="scan-status"></span>
</div>
<div class="node-list" id="node-list"></div>
<div id="look-editor"></div>
<details id="devices-details">
  <summary class="section-title">Direct Connection</summary>
  <div id="devices-section"></div>
</details>

<script>
"use strict";

var S = null;
var EFFECTS = ["none","solid","pulse","linear","constrainbow","rainbow","knight_rider","chase","radial","spiral"];
var PLAYBACKS = ["loop","boomerang","once"];
var GRID_ORDERS = ["progressive","serpentine"];
var GRID_ROTATIONS = [0, 90, 180, 270];
var LOOK_OUTPUT_TYPES = ["none","short_strip","long_strip","grid"];
var TYPE_LABELS = {"none":"Nothing Connected","short_strip":"Short Strip","long_strip":"Long Strip","grid":"Grid"};

function apiPost(path, body) {
  return fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body)
  });
}

function fetchState() {
  return fetch("/api/state").then(function(r) { return r.json(); })
    .then(function(j) { S = j; });
}

function rgbHex(c) {
  return "#" + c.map(function(v) { return v.toString(16).padStart(2, "0"); }).join("");
}

function hexRgb(h) {
  return [parseInt(h.slice(1,3),16), parseInt(h.slice(3,5),16), parseInt(h.slice(5,7),16)];
}

function esc(s) {
  var d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function buildUI() {
  // ── Look Editor ──
  var lookDiv = document.getElementById("look-editor");
  lookDiv.innerHTML = "";
  var look = S.look;

  var sec = document.createElement("div");
  sec.className = "look-section";
  var headerHtml = '<div class="look-header">'
    + '<h2>Look:</h2>'
    + '<input class="look-name" type="text" value="' + esc(look.name) + '"'
    + ' onchange="apiPost(\'/api/update\',{look_name:this.value})">'
    + '</div>'
    + '<canvas id="look-cv" height="10"></canvas>'
    + '<div class="outputs" id="look-outputs"></div>';
  sec.innerHTML = headerHtml;
  lookDiv.appendChild(sec);

  var oc = sec.querySelector("#look-outputs");
  look.outputs.forEach(function(out, oi) {
    var p = document.createElement("div");
    p.className = "output-panel";
    var isNone = out.type === "none";
    var gl = out.grid ? out.grid[0] + "x" + out.grid[1] : (out.count > 0 ? out.count + "px" : "");
    var typeOpts = LOOK_OUTPUT_TYPES.map(function(t) {
      return "<option value=\"" + t + "\"" + (t === out.type ? " selected" : "") + ">" + TYPE_LABELS[t] + "</option>";
    }).join("");

    var typeSelect = '<div class="ctrl"><label>Output Type</label>'
      + '<select onchange="apiPost(\'/api/update\',{output:'+oi+',output_type:this.value}).then(function(){fetchState().then(function(){buildUI();sizeCanvas();drawPreview()})})">'
      + typeOpts + '</select></div>';

    if (isNone) {
      p.innerHTML = '<h3>' + esc(out.name) + '</h3>' + typeSelect
        + '<div style="color:#6b7280;font-size:12px;text-align:center;padding:8px 0">No output connected</div>';
      oc.appendChild(p);
      return;
    }

    var sh = rgbHex(out.start_color);
    var eh = rgbHex(out.end_color);

    var angleCtrl = "";
    if (out.grid) {
      angleCtrl = '<div class="ctrl">'
        + '<label>Angle: <span class="val" id="av-'+oi+'">' + Math.round(out.angle) + '&deg;</span></label>'
        + '<input type="range" min="0" max="360" value="' + out.angle + '"'
        + ' oninput="document.getElementById(\'av-'+oi+'\').innerHTML=Math.round(this.value)+\'&deg;\';'
        + 'apiPost(\'/api/update\',{output:'+oi+',angle:+this.value})">'
        + '</div>';
    }

    var knightCtrl = "";
    if (out.effect === "knight_rider") {
      knightCtrl = '<div class="ctrl">'
        + '<label>Highlight Width: <span class="val" id="hw-'+oi+'">' + out.highlight_width + 'px</span></label>'
        + '<input type="range" min="1" max="30" step="1" value="' + out.highlight_width + '"'
        + ' oninput="document.getElementById(\'hw-'+oi+'\').textContent=this.value+\'px\';'
        + 'apiPost(\'/api/update\',{output:'+oi+',highlight_width:+this.value})">'
        + '</div>';
    }

    var chaseCtrl = "";
    if (out.effect === "chase") {
      var origins = ["start","center","end"];
      var originOpts = origins.map(function(v) {
        return "<option" + (v === out.chase_origin ? " selected" : "") + ">" + v + "</option>";
      }).join("");
      chaseCtrl = '<div class="ctrl"><label>Origin</label>'
        + '<select onchange="apiPost(\'/api/update\',{output:'+oi+',chase_origin:this.value})">'
        + originOpts + '</select></div>';
    }

    var effectOpts = EFFECTS.map(function(e) {
      return "<option" + (e === out.effect ? " selected" : "") + ">" + e + "</option>";
    }).join("");
    var playOpts = PLAYBACKS.map(function(m) {
      return "<option" + (m === out.playback ? " selected" : "") + ">" + m + "</option>";
    }).join("");

    p.innerHTML = '<h3>' + esc(out.name) + ' &middot; ' + (TYPE_LABELS[out.type] || out.type) + ' &middot; ' + gl + '</h3>'
      + typeSelect
      + '<div class="color-row">'
      + '<div class="color-box"><label>Start</label>'
      + '<input type="color" value="' + sh + '"'
      + ' oninput="apiPost(\'/api/update\',{output:'+oi+',start_color:hexRgb(this.value)})">'
      + '</div>'
      + '<div class="color-box"><label>End</label>'
      + '<input type="color" value="' + eh + '"'
      + ' oninput="apiPost(\'/api/update\',{output:'+oi+',end_color:hexRgb(this.value)})">'
      + '</div></div>'
      + '<div class="ctrl"><label>Effect</label>'
      + '<select onchange="apiPost(\'/api/update\',{output:'+oi+',effect:this.value}).then(function(){fetchState().then(function(){buildUI()})})">'
      + effectOpts + '</select></div>'
      + knightCtrl
      + chaseCtrl
      + '<div class="ctrl">'
      + '<label>Speed: <span class="val" id="sv-'+oi+'">' + out.speed.toFixed(1) + '</span></label>'
      + '<input type="range" min="0.1" max="10" step="0.1" value="' + out.speed + '"'
      + ' oninput="document.getElementById(\'sv-'+oi+'\').textContent=parseFloat(this.value).toFixed(1);'
      + 'apiPost(\'/api/update\',{output:'+oi+',speed:+this.value})">'
      + '</div>'
      + '<div class="ctrl"><label>Playback</label>'
      + '<select onchange="apiPost(\'/api/update\',{output:'+oi+',playback:this.value})">'
      + playOpts + '</select></div>'
      + angleCtrl;
    oc.appendChild(p);
  });

  // ── Devices / Direct Connection ──
  var devDiv = document.getElementById("devices-section");
  devDiv.innerHTML = "";

  S.devices.forEach(function(dev, di) {
    var card = document.createElement("div");
    card.className = "device-card";
    card.id = "dev-" + di;
    var cclass = dev.connected ? " connected" : "";
    var dotclass = dev.connected ? " on" : "";
    var stxt = dev.connected ? "Connected" : "Disconnected";
    var rxFps = dev.receiver_fps != null
      ? '<span class="rx-fps" id="rxfps-' + di + '">RX: ' + dev.receiver_fps + ' fps</span>'
      : '<span class="rx-fps" id="rxfps-' + di + '"></span>';

    var topHtml = '<div class="dev-top">'
      + '<h3>' + esc(dev.name) + '</h3>'
      + '<input type="text" id="ip-' + di + '" value="' + esc(dev.ip) + '" class="' + cclass + '"'
      + ' onchange="apiPost(\'/api/update\',{device:' + di + ',ip:this.value})">'
      + '<span class="status-dot' + dotclass + '" id="dot-' + di + '"></span>'
      + '<span class="status-text" id="stxt-' + di + '">' + stxt + '</span>'
      + rxFps
      + '<div class="dev-actions">'
      + '<button class="small" onclick="doConnect(' + di + ')">Connect</button>'
      + '<button class="small danger" onclick="doDisconnect(' + di + ')">Disconnect</button>'
      + '<button class="small" onclick="doRename(' + di + ')">Rename</button>'
      + '<button class="small danger" onclick="doRemove(' + di + ')">Remove</button>'
      + '</div>'
      + '</div>';

    var hwHtml = "";
    dev.outputs.forEach(function(o, oi) {
      if (o.grid) {
        var rotOpts = GRID_ROTATIONS.map(function(r) {
          return "<option" + (r === o.grid_rotation ? " selected" : "") + " value=\"" + r + "\">" + r + "&deg;</option>";
        }).join("");
        hwHtml += '<div class="hw-row">'
          + '<span class="hw-label">' + esc(o.name) + ':</span>'
          + '<div class="ctrl"><label>Rotation</label>'
          + '<select onchange="apiPost(\'/api/update\',{device:'+di+',output:'+oi+',grid_rotation:+this.value})">'
          + rotOpts + '</select></div>'
          + '</div>';
      }
    });

    card.innerHTML = topHtml + hwHtml;
    devDiv.appendChild(card);
  });

  if (S.devices.length === 0) {
    var emptyMsg = document.createElement("div");
    emptyMsg.style.cssText = "text-align:center;padding:32px;color:#6b7280;font-size:14px";
    emptyMsg.innerHTML = 'No devices configured. Use <b>Scan Network</b> above to discover and connect Art-Net nodes.';
    devDiv.appendChild(emptyMsg);
  }

  // Global controls
  var dbg = document.createElement("div");
  dbg.className = "debug";
  dbg.innerHTML = '<label>FPS:</label>'
    + '<input type="range" min="1" max="120" value="' + S.fps + '"'
    + ' oninput="document.getElementById(\'fv\').textContent=this.value;'
    + 'apiPost(\'/api/update\',{fps:+this.value})">'
    + '<span class="val" id="fv">' + S.fps + '</span>';
  devDiv.appendChild(dbg);

  sizeCanvas();
}

function sizeCanvas() {
  var cv = document.getElementById("look-cv");
  if (!cv || !S) return;
  cv.width = cv.parentElement.clientWidth - 34;
  var y = 8;
  S.look.outputs.forEach(function(out) {
    if (out.type === "none" || out.count === 0) return;
    y += 16;
    if (out.grid) {
      y += out.grid[1] * 20 + 8;
    } else {
      var cs = 9;
      var maxPer = Math.floor((cv.width - 20) / cs);
      var nrows = Math.ceil(out.count / maxPer);
      y += nrows * cs + 8;
    }
  });
  cv.height = y + 8;
}

function drawPreview() {
  if (!S) return;
  var cv = document.getElementById("look-cv");
  if (!cv) return;
  var ctx = cv.getContext("2d");
  ctx.clearRect(0, 0, cv.width, cv.height);
  var y = 8;
  S.look.outputs.forEach(function(out) {
    if (out.type === "none" || out.count === 0) return;
    ctx.fillStyle = "#6b7280";
    ctx.font = "11px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(out.name + " (" + out.count + "px) " + (TYPE_LABELS[out.type] || out.type), cv.width / 2, y + 10);
    ctx.textAlign = "left";
    y += 16;

    var px = out.pixels || [];
    if (out.grid) {
      var cols = out.grid[0], rows = out.grid[1], cs = 20;
      var gw = cols * cs, x0 = (cv.width - gw) / 2;
      for (var i = 0; i < px.length; i++) {
        var c = i % cols, r = Math.floor(i / cols);
        var rgb = px[i] || [0,0,0];
        ctx.fillStyle = "rgb(" + rgb[0] + "," + rgb[1] + "," + rgb[2] + ")";
        ctx.beginPath();
        ctx.arc(x0 + c*cs + cs/2, y + r*cs + cs/2, cs/2 - 2, 0, Math.PI*2);
        ctx.fill();
      }
      y += rows * cs + 8;
    } else {
      var cs2 = 9;
      var maxPer = Math.floor((cv.width - 20) / cs2);
      var actualCols = Math.min(px.length, maxPer);
      var sx0 = (cv.width - actualCols * cs2) / 2;
      for (var j = 0; j < px.length; j++) {
        var row = Math.floor(j / maxPer), col = j % maxPer;
        var rgb2 = px[j] || [0,0,0];
        ctx.fillStyle = "rgb(" + rgb2[0] + "," + rgb2[1] + "," + rgb2[2] + ")";
        ctx.fillRect(sx0 + col*cs2, y + row*cs2, cs2-1, cs2-1);
      }
      var nrows = Math.ceil(px.length / maxPer);
      y += nrows * cs2 + 8;
    }
  });
}

var _discoveredNodes = [];

function doConnectAll() {
  apiPost("/api/connect_all", {})
    .then(function() { return fetchState(); })
    .then(function() { updateStatus(); });
}

function doDisconnectAll() {
  apiPost("/api/disconnect_all", {})
    .then(function() { return fetchState(); })
    .then(function() { updateStatus(); });
}

function doScan() {
  var st = document.getElementById("scan-status");
  var nl = document.getElementById("node-list");
  st.textContent = "Scanning...";
  nl.innerHTML = "";
  _discoveredNodes = [];
  apiPost("/api/discover", {}).then(function(r) { return r.json(); })
    .then(function(nodes) {
      _discoveredNodes = nodes;
      st.textContent = nodes.length + " node(s) found";
      if (nodes.length === 0) {
        nl.innerHTML = '<div class="scan-empty">No Art-Net nodes found. Make sure devices are powered on and connected to WiFi.</div>';
        return;
      }
      nodes.forEach(function(n, ni) {
        var card = document.createElement("div");
        card.className = "node-card";
        var devMatch = S && S.devices.filter(function(d) { return d.ip === n.ip; });
        var already = devMatch && devMatch.length > 0;
        var isConnected = already && devMatch[0].connected;
        var devIdx = already ? S.devices.indexOf(devMatch[0]) : -1;
        var badge;
        if (isConnected) {
          badge = '<button class="small danger" onclick="doDisconnect(' + devIdx + ');setTimeout(doScan,500)">Disconnect</button>';
        } else if (already) {
          badge = '<button class="small" onclick="doConnect(' + devIdx + ');setTimeout(doScan,500)">Connect</button>';
        } else {
          badge = '<button class="small" onclick="doAddNode(' + ni + ')">Add &amp; Connect</button>';
        }
        var details = n.long_name.split("|");
        var outputInfo = details.length > 1 ? details[1].trim() : "";
        var fpsHtml = "";
        var renameHtml = "";
        if (already && devMatch[0].receiver_fps != null) {
          fpsHtml = ' <span class="rx-fps" id="scan-rxfps-' + devIdx + '">RX: ' + devMatch[0].receiver_fps + ' fps</span>';
        } else if (already) {
          fpsHtml = ' <span class="rx-fps" id="scan-rxfps-' + devIdx + '"></span>';
        }
        if (already) {
          renameHtml = '<button class="small" onclick="doRename(' + devIdx + ');setTimeout(doScan,500)">Rename</button>';
        }
        card.innerHTML = '<div class="node-info">'
          + '<div class="node-title"><span class="nn">' + esc(n.short_name) + '</span>'
          + ' <span class="ni">' + esc(n.ip) + '</span>' + fpsHtml + '</div>'
          + '<div class="node-detail">' + n.num_ports + ' output(s) &middot; Universe '
          + n.universes.join(", ") + (outputInfo ? ' &middot; ' + esc(outputInfo) : '') + '</div>'
          + '</div>'
          + '<div class="node-actions">' + renameHtml + badge + '</div>';
        nl.appendChild(card);
      });
    })
    .catch(function() { st.textContent = "Scan failed"; });
}

function doAddNode(ni) {
  var n = _discoveredNodes[ni];
  if (!n) return;
  apiPost("/api/add_discovered", n)
    .then(function(r) { return r.json(); })
    .then(function() {
      fetchState().then(function() { buildUI(); drawPreview(); doScan(); });
    });
}

function doRename(di) {
  var current = S.devices[di] ? S.devices[di].name : "";
  var name = prompt("Enter new name for this costume:", current);
  if (name !== null && name.trim() !== "") {
    apiPost("/api/rename_node", {device: di, name: name.trim()})
      .then(function() { return fetchState(); })
      .then(function() { buildUI(); drawPreview(); });
  }
}

function doRemove(di) {
  var name = S.devices[di] ? S.devices[di].name : "this costume";
  if (confirm("Remove " + name + "?")) {
    apiPost("/api/remove_device", {device: di})
      .then(function() { return fetchState(); })
      .then(function() { buildUI(); drawPreview(); });
  }
}

function doConnect(di) {
  var ip = document.getElementById("ip-" + di).value;
  apiPost("/api/update", {device: di, ip: ip})
    .then(function() { return apiPost("/api/connect", {device: di}); })
    .then(function() { return fetchState(); })
    .then(function() { updateStatus(); });
}

function doDisconnect(di) {
  apiPost("/api/disconnect", {device: di})
    .then(function() { return fetchState(); })
    .then(function() { updateStatus(); });
}

function updateStatus() {
  S.devices.forEach(function(dev, di) {
    var dot = document.getElementById("dot-" + di);
    var txt = document.getElementById("stxt-" + di);
    var inp = document.getElementById("ip-" + di);
    var rxl = document.getElementById("rxfps-" + di);
    if (dot) dot.className = "status-dot" + (dev.connected ? " on" : "");
    if (txt) txt.textContent = dev.connected ? "Connected" : "Disconnected";
    if (inp) {
      if (dev.connected) inp.classList.add("connected");
      else inp.classList.remove("connected");
    }
    if (rxl) {
      rxl.textContent = dev.receiver_fps != null
        ? "RX: " + dev.receiver_fps + " fps"
        : "";
    }
    // Also update scan-result FPS inline
    var srx = document.getElementById("scan-rxfps-" + di);
    if (srx) {
      srx.textContent = dev.receiver_fps != null
        ? "RX: " + dev.receiver_fps + " fps"
        : "";
    }
  });
}

function init() {
  fetchState().then(function() {
    buildUI();
    drawPreview();
    setInterval(function() {
      fetchState().then(function() {
        drawPreview();
        updateStatus();
      }).catch(function() {});
    }, 66);
    window.addEventListener("resize", function() { sizeCanvas(); drawPreview(); });
  });
}

init();
</script>
</body>
</html>"""


# ======================================================================
#  HTTP SERVER
# ======================================================================

class Handler(BaseHTTPRequestHandler):
    controller = None

    def do_GET(self):
        if self.path == "/":
            self._respond(200, "text/html", HTML_PAGE.encode())
        elif self.path == "/api/state":
            body = json.dumps(self.controller.get_json(),
                              separators=(",", ":")).encode()
            self._respond(200, "application/json", body)
        else:
            self._respond(404, "text/plain", b"Not Found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length)) if length else {}

        if self.path == "/api/update":
            self.controller.update(data)
        elif self.path == "/api/connect":
            di = data.get("device", 0)
            if 0 <= di < len(self.controller.devices):
                self.controller.connect(di)
        elif self.path == "/api/disconnect":
            di = data.get("device", 0)
            if 0 <= di < len(self.controller.devices):
                self.controller.disconnect(di)
        elif self.path == "/api/connect_all":
            self.controller.connect_all()
        elif self.path == "/api/disconnect_all":
            self.controller.disconnect_all()
        elif self.path == "/api/discover":
            nodes = discover_artnet_nodes(timeout=2.0)
            body = json.dumps(nodes, separators=(",", ":")).encode()
            self._respond(200, "application/json", body)
            return
        elif self.path == "/api/add_discovered":
            result = self.controller.add_device_from_node(data)
            if result.get("status") == "added":
                self.controller.connect(result["device_index"])
            body = json.dumps(result, separators=(",", ":")).encode()
            self._respond(200, "application/json", body)
            return
        elif self.path == "/api/remove_device":
            di = data.get("device", -1)
            self.controller.remove_device(di)
        elif self.path == "/api/rename_node":
            di = data.get("device", -1)
            new_name = str(data.get("name", ""))[:17]
            if new_name:
                self.controller.rename_device(di, new_name)

        self._respond(200, "application/json", b'{"ok":true}')

    def _respond(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


# ======================================================================
#  MAIN
# ======================================================================

def main():
    parser = argparse.ArgumentParser(
        description="PrimusV3 LED Controller — Art-Net only")
    parser.add_argument("--port", type=int, default=0,
                        help="HTTP port (0 = auto-select)")
    args = parser.parse_args()

    # Start FPS back-channel listener
    fps_listener = FpsListener()
    fps_thread = threading.Thread(target=fps_listener.run, daemon=True)
    fps_thread.start()

    state = ControllerState(fps_listener)
    Handler.controller = state

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    port = server.server_address[1]
    url = "http://127.0.0.1:{}".format(port)

    anim = threading.Thread(target=animation_loop, args=(state,), daemon=True)
    anim.start()

    print("PrimusV3 LED Controller (Art-Net)")
    print("  URL:      {}".format(url))
    print("  FPS port: {} (receiver telemetry)".format(FPS_LISTEN_PORT))
    print("  Devices:  {}".format(len(DEVICES)))
    for d in DEVICES:
        bu = d.get("base_universe", 0)
        print("    {}: {} (base U{}, {} outputs)".format(
            d["name"], d["ip"], bu, len(d["outputs"])))
        for i, o in enumerate(d["outputs"]):
            td = OUTPUT_TYPES[o["type"]]
            print("      {}: {} ({}px, U{})".format(
                o["name"], o["type"], td["pixels"], bu + i))
    print("")
    print("Opening browser... (Ctrl+C to stop)")
    print("")

    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("")
        print("Shutting down...")
    finally:
        state.shutdown()
        fps_listener.stop()
        server.server_close()
        print("Done.")


if __name__ == "__main__":
    main()
