"""
artnet.py — Art-Net transport, discovery, naming, output config, and FPS telemetry.
"""

import errno
import re
import socket
import struct
import threading
import time

import netlog

# ======================================================================
#  ART-NET CONSTANTS
# ======================================================================

ARTNET_HEADER = b"Art-Net\x00"
ARTNET_OPCODE_DMX = 0x5000
ARTNET_OPCODE_POLL = 0x2000
ARTNET_OPCODE_POLLREPLY = 0x2100
ARTNET_OPCODE_ADDRESS = 0x6000
ARTNET_OPCODE_OUTPUT_CONFIG = 0x8100
ARTNET_OPCODE_RECEIVE_CONFIG = 0x8110
ARTNET_OPCODE_IP_CONFIG = 0x8200
ARTNET_OPCODE_AUDIO_CMD = 0x8300
ARTNET_OPCODE_FTP_CMD = 0x8301
ARTNET_OPCODE_AUDIO_STATUS = 0x8302
ARTNET_VERSION = 14
ARTNET_PORT = 6454
NODE_CAPS_PREFIX = "PV3CAP1"
NODE_CAPS_PREFIX_RADIUS = "PVRAD1"
NODE_CAPS_FEATURE_PREFIX = "F:"
NODE_CAPS_BOARD_PREFIX = "B:"
NODE_CAPS_IP_PREFIX = "IP:"
NODE_CAPS_UNIVERSE_PREFIX = "U:"

BOARD_PROFILE_LABELS = {
    "v1": "V1 Huzzah32",
    "v2": "V2 Feather",
    "v31": "V3.1 Reverse TFT",
}

FPS_LISTEN_PORT = 6455
FPS_MAGIC = b"PFP"
BATTERY_MAGIC = b"PBT"
TRACK_MAGIC = b"PTR"

BATTERY_POWER_MODE_BATTERY = 0
BATTERY_POWER_MODE_CHARGING = 1
BATTERY_POWER_MODE_PLUGGED = 2
BATTERY_POWER_MODE_SWITCH_OFF = 3
BATTERY_POWER_MODE_FAULT = 4
BATTERY_POWER_MODE_UNAVAILABLE = 5

BATTERY_POWER_MODE_LABELS = {
    BATTERY_POWER_MODE_BATTERY: "battery",
    BATTERY_POWER_MODE_CHARGING: "charging",
    BATTERY_POWER_MODE_PLUGGED: "plugged",
    BATTERY_POWER_MODE_SWITCH_OFF: "switch_off",
    BATTERY_POWER_MODE_FAULT: "fault",
    BATTERY_POWER_MODE_UNAVAILABLE: "unavailable",
}

BATTERY_WARNING_MESSAGES = {
    "switch_off": "Power switch off — turn on to charge",
    "fault": "Check power switch and unplug strip to charge",
}

AUDIO_CMD_STOP = 0
AUDIO_CMD_PLAY = 1
AUDIO_CMD_LOOP = 2
AUDIO_CMD_PAUSE = 3
AUDIO_CMD_VOLUME = 4
AUDIO_CMD_TEST_TONE = 5
AUDIO_CMD_PLAY_CUE = 6
AUDIO_CMD_LOOP_CUE = 7

_AUDIO_CMD_NAMES = {
    AUDIO_CMD_STOP: "stop",
    AUDIO_CMD_PLAY: "play",
    AUDIO_CMD_LOOP: "loop",
    AUDIO_CMD_PAUSE: "pause",
    AUDIO_CMD_VOLUME: "volume",
    AUDIO_CMD_TEST_TONE: "test_tone",
    AUDIO_CMD_PLAY_CUE: "play_cue",
    AUDIO_CMD_LOOP_CUE: "loop_cue",
}

FTP_PORT = 21
FTP_USER = "radius"
FTP_PASSWORD = "radius"


# ======================================================================
#  ART-NET SENDER
# ======================================================================

class ArtNetSender:
    """Sends one Art-Net ArtDmx packet per output, per frame."""

    def __init__(self, ip, source_ip=None):
        self.ip = ip
        self.source_ip = source_ip or None
        self.sock = None
        self.connected = False
        self.sequence = 1
        self.last_error = None
        self._prefer_unbound_send = False
        self._io_lock = threading.Lock()

    def set_source_ip(self, source_ip):
        source_ip = source_ip or None
        if self.source_ip == source_ip:
            return
        self.source_ip = source_ip
        self._prefer_unbound_send = False
        if self.connected:
            self.disconnect()

    def _open_socket_unlocked(self, bind_source=True):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if bind_source and self.source_ip:
            self.sock.bind((self.source_ip, 0))

    @staticmethod
    def _route_retryable(error):
        return _udp_route_retryable(error)

    def connect(self):
        with self._io_lock:
            for bind_source in (True, False):
                if bind_source and not self.source_ip:
                    continue
                try:
                    self._open_socket_unlocked(bind_source=bind_source)
                    break
                except OSError:
                    if bind_source and self.source_ip:
                        continue
                    raise
            self.connected = True
            self.last_error = None

    def disconnect(self):
        with self._io_lock:
            self.connected = False
            if self.sock:
                try:
                    self.sock.close()
                except OSError:
                    pass
                self.sock = None

    def _build_packet(self, universe, rgb_data):
        if len(rgb_data) % 2 != 0:
            rgb_data = rgb_data + b'\x00'
        length = len(rgb_data)
        pkt = bytearray()
        pkt += ARTNET_HEADER
        pkt += struct.pack("<H", ARTNET_OPCODE_DMX)
        pkt += struct.pack(">H", ARTNET_VERSION)
        pkt += bytes([self.sequence])
        pkt += bytes([0])
        pkt += struct.pack("<H", universe)
        pkt += struct.pack(">H", length)
        pkt += rgb_data
        return bytes(pkt)

    def send_output(self, universe, rgb_data):
        with self._io_lock:
            if not self.connected:
                return False
            pkt = self._build_packet(universe, rgb_data)
            bind_attempts = self._send_bind_attempts()
            for bind_source in bind_attempts:
                if bind_source and not self.source_ip:
                    continue
                try:
                    self._open_socket_unlocked(bind_source=bind_source)
                    self.sock.sendto(pkt, (self.ip, ARTNET_PORT))
                    self.last_error = None
                    return True
                except OSError as exc:
                    self.last_error = str(exc) or "UDP send failed"
                    if bind_source and self.source_ip and self._route_retryable(exc):
                        self._prefer_unbound_send = True
                        continue
                    return False
            return False

    def _send_bind_attempts(self):
        if self._prefer_unbound_send or not self.source_ip:
            return [False]
        return [True, False]

    def advance_sequence(self):
        self.sequence = (self.sequence % 255) + 1

    def blackout(self, outputs_info):
        with self._io_lock:
            if not self.connected:
                return False
            bind_attempts = self._send_bind_attempts()
            for bind_source in bind_attempts:
                if bind_source and not self.source_ip:
                    continue
                try:
                    self._open_socket_unlocked(bind_source=bind_source)
                    for universe, pixel_count in outputs_info:
                        pkt = self._build_packet(universe, bytes(pixel_count * 3))
                        self.sock.sendto(pkt, (self.ip, ARTNET_PORT))
                    self.sequence = (self.sequence % 255) + 1
                    self.last_error = None
                    return True
                except OSError as exc:
                    self.last_error = str(exc) or "UDP send failed"
                    if bind_source and self.source_ip and self._route_retryable(exc):
                        self._prefer_unbound_send = True
                        continue
                    return False
            return False


# ======================================================================
#  PRIMUS TELEMETRY (UDP 6455 — PFP + PBT)
# ======================================================================


def parse_pbt_packet(raw):
    """Parse a 9-byte PBT battery telemetry packet. Returns dict or None."""
    if len(raw) < 9 or raw[:3] != BATTERY_MAGIC:
        return None
    power_mode = raw[3]
    battery_mv = (raw[4] << 8) | raw[5]
    battery_pct = raw[6]
    fw_minor = raw[7]
    fw_major = raw[8]
    mode_label = BATTERY_POWER_MODE_LABELS.get(power_mode, "unavailable")
    live_firmware_version = f"{fw_major}.{fw_minor}"
    warning = BATTERY_WARNING_MESSAGES.get(mode_label)
    return {
        "battery_power_mode": mode_label,
        "battery_mv": battery_mv if battery_mv > 0 else None,
        "battery_pct": battery_pct if battery_pct <= 100 else None,
        "live_firmware_version": live_firmware_version,
        "battery_warning": warning,
    }


def parse_pfp_packet(raw):
    """Parse a 7-byte PFP FPS telemetry packet. Returns dict or None."""
    if len(raw) < 7 or raw[:3] != FPS_MAGIC:
        return None
    return {
        "fps": (raw[3] << 8) | raw[4],
        "pkt_rate": (raw[5] << 8) | raw[6],
    }


class PrimusTelemetryListener:
    """Listens on UDP 6455 for PFP and PBT telemetry from Primus receivers."""

    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}
        self.running = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bound = False
        for attempt in range(10):
            try:
                self._sock.bind(("0.0.0.0", FPS_LISTEN_PORT))
                bound = True
                break
            except OSError:
                time.sleep(0.2)
        if not bound:
            self._sock.close()
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                self._sock.bind(("0.0.0.0", FPS_LISTEN_PORT))
                bound = True
            except OSError:
                pass
        if not bound:
            self._sock.bind(("0.0.0.0", 0))
            fallback_port = self._sock.getsockname()[1]
            print(
                f"ERROR: telemetry port {FPS_LISTEN_PORT} in use "
                f"(listening on {fallback_port} instead) — receiver telemetry will not display. "
                f"Stop other PrimusCentral/RadiusCentral instances."
            )
        self._sock.settimeout(1.0)
        self._bound_port = self._sock.getsockname()[1]

    def run(self):
        while self.running:
            try:
                raw, addr = self._sock.recvfrom(256)
            except socket.timeout:
                continue
            ip = addr[0]
            if len(raw) >= 9 and raw[:3] == BATTERY_MAGIC:
                parsed = parse_pbt_packet(raw)
                if parsed:
                    with self.lock:
                        entry = self.data.setdefault(ip, {})
                        entry.update(parsed)
                        entry["ts"] = time.monotonic()
                continue
            if len(raw) >= 7 and raw[:3] == FPS_MAGIC:
                parsed = parse_pfp_packet(raw)
                if parsed:
                    with self.lock:
                        entry = self.data.setdefault(ip, {})
                        entry.update(parsed)
                        entry["ts"] = time.monotonic()
                    netlog.log_fps(ip, parsed["fps"], parsed["pkt_rate"])

    TELEMETRY_STALE_SECONDS = 12.0

    def get(self, ip):
        with self.lock:
            entry = self.data.get(ip)
            if entry and (time.monotonic() - entry.get("ts", 0)) < self.TELEMETRY_STALE_SECONDS:
                return dict(entry)
        return None

    def stop(self):
        self.running = False
        self._sock.close()


class FpsListener(PrimusTelemetryListener):
    """Backward-compatible alias for Primus telemetry listener."""


def parse_audio_status_packet(raw):
    """Parse an ArtAudioStatus (0x8302) packet. Returns dict or None.

    Layout: Art-Net header (8) + opcode LE (2) + protocol version (2) +
    status byte (1) + null-terminated ASCII filename (up to 64 bytes).
    The filename field must carry a full 64-char name — the firmware
    once truncated packets to 46 bytes, cutting names at 33 chars.
    """
    if len(raw) < 13 or raw[:8] != ARTNET_HEADER:
        return None
    opcode = struct.unpack("<H", raw[8:10])[0]
    if opcode != ARTNET_OPCODE_AUDIO_STATUS:
        return None
    name = raw[13:77].split(b'\x00')[0].decode("ascii", errors="replace")
    return {"playback_state": raw[12], "current_track": name}


def parse_track_packet(raw):
    """Parse a legacy PTR track telemetry packet. Returns dict or None."""
    if len(raw) < 5 or raw[:3] != TRACK_MAGIC:
        return None
    name_len = raw[4]
    name = raw[5:5 + name_len].decode("utf-8", errors="replace") if name_len else ""
    return {"playback_state": raw[3], "current_track": name}


class RadiusTelemetryListener:
    """Listens on UDP 6455 for PTR track-name telemetry from Radius nodes."""

    def __init__(self):
        self.lock = threading.Lock()
        self.data = {}
        self.running = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bound = False
        for attempt in range(10):
            try:
                self._sock.bind(("0.0.0.0", FPS_LISTEN_PORT))
                bound = True
                break
            except OSError:
                time.sleep(0.2)
        if not bound:
            self._sock.bind(("0.0.0.0", 0))
            print(f"WARNING: telemetry port {FPS_LISTEN_PORT} in use — track telemetry may not display.")
        self._sock.settimeout(1.0)

    def run(self):
        while self.running:
            try:
                raw, addr = self._sock.recvfrom(256)
            except socket.timeout:
                continue
            status = parse_audio_status_packet(raw) or parse_track_packet(raw)
            if status is not None:
                with self.lock:
                    self.data[addr[0]] = {**status, "ts": time.monotonic()}
                state = status["playback_state"]
                name = status["current_track"]
                state_str = "playing" if state == 1 else ("paused" if state == 2 else "stopped")
                file_str = f" \"{name}\"" if name else ""
                netlog.log("IN", "audio_status", f"AudioStatus {state_str}{file_str} ← {addr[0]}")
                continue
            if len(raw) >= 13 and raw[:8] == ARTNET_HEADER:
                continue  # other Art-Net traffic on the telemetry port — ignore
            if len(raw) >= 7 and raw[:3] == FPS_MAGIC:
                fps = (raw[3] << 8) | raw[4]
                pkt = (raw[5] << 8) | raw[6]
                with self.lock:
                    entry = self.data.setdefault(addr[0], {})
                    entry.update({"fps": fps, "pkt_rate": pkt, "ts": time.monotonic()})
                netlog.log_fps(addr[0], fps, pkt)

    def get(self, ip):
        with self.lock:
            entry = self.data.get(ip)
            if entry:
                return dict(entry)
        return None

    def stop(self):
        self.running = False
        self._sock.close()


# ======================================================================
#  DISCOVERY
# ======================================================================

def _get_all_broadcast_addresses():
    """Return a set of broadcast addresses for all local IPv4 interfaces.

    Parses ifconfig/ip output to get real broadcast addresses (respects
    actual netmask instead of assuming /24).
    """
    addrs = set()
    # Try ifconfig first (macOS / BSD / most Linux)
    try:
        import subprocess
        out = subprocess.check_output(["ifconfig"], text=True,
                                      stderr=subprocess.DEVNULL)
        import re
        for m in re.finditer(
                r"broadcast\s+([\d.]+)", out):
            addrs.add(m.group(1))
    except Exception:
        pass
    # Try 'ip addr' (Linux without ifconfig)
    if not addrs:
        try:
            import subprocess, re
            out = subprocess.check_output(["ip", "addr"], text=True,
                                          stderr=subprocess.DEVNULL)
            for m in re.finditer(r"brd\s+([\d.]+)\s+scope\s+global", out):
                addrs.add(m.group(1))
        except Exception:
            pass
    # Last resort: assume /24 on the default-route interface
    if not addrs:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            parts = ip.split(".")
            parts[3] = "255"
            addrs.add(".".join(parts))
        except Exception:
            pass
    return addrs


def _discovery_bind_addr(interface=None):
    source_ip = (interface or {}).get("source_ip") or (interface or {}).get("ipv4")
    return (source_ip or "", ARTNET_PORT)


def _discovery_destinations(known_ips=None, interface=None):
    destinations = set()
    broadcast = (interface or {}).get("broadcast")
    if broadcast:
        destinations.add(broadcast)
    elif interface:
        source_ip = interface.get("source_ip") or interface.get("ipv4")
        if source_ip:
            parts = source_ip.split(".")
            if len(parts) == 4:
                parts[3] = "255"
                destinations.add(".".join(parts))
    else:
        destinations.update(_get_all_broadcast_addresses())
        destinations.add("255.255.255.255")
    for ip in known_ips or []:
        if ip:
            destinations.add(str(ip))
    return destinations


def discover_artnet_nodes(known_ips=None, timeout=2.0, interface=None):
    """Send ArtPoll and collect ArtPollReply responses.

    known_ips: list of IP strings to unicast to in addition to broadcast.
    Returns list of dicts: {ip, short_name, long_name, node_report, num_ports, universes}
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.25)
        try:
            sock.bind(_discovery_bind_addr(interface))
        except OSError:
            sock.bind(("", ARTNET_PORT))

        poll = bytearray()
        poll += ARTNET_HEADER
        poll += struct.pack("<H", ARTNET_OPCODE_POLL)
        poll += struct.pack(">H", ARTNET_VERSION)
        poll += bytes([0x00, 0x00])

        destinations = _discovery_destinations(known_ips, interface)
        for dest in destinations:
            try:
                sock.sendto(bytes(poll), (dest, ARTNET_PORT))
            except OSError:
                pass

        known_ip_set = set(known_ips) if known_ips else set()
        nodes = {}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if known_ip_set and known_ip_set.issubset(nodes):
                break
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
            node_report = raw[108:172].split(b'\x00')[0].decode("ascii", errors="replace")
            num_ports = raw[173] if len(raw) > 173 else 0
            universes = []
            for i in range(min(num_ports, 4)):
                if len(raw) > 190 + i:
                    universes.append(raw[190 + i])

            firmware_version = None
            if len(raw) > 17:
                firmware_version = f"{raw[16]}.{raw[17]}"
            capabilities = parse_node_capabilities(node_report, short_name, long_name)
            capabilities["firmware_version"] = firmware_version
            if capabilities.get("ip_mode") == "static" and not capabilities.get("static_ip"):
                capabilities["static_ip"] = ip

            nodes[ip] = {
                "ip": ip,
                "short_name": short_name,
                "long_name": long_name,
                "node_report": node_report,
                "capabilities": capabilities,
                "hardware_profile": capabilities.get("hardware_profile", "unknown"),
                "hardware_label": capabilities.get("hardware_label", "Unknown hardware"),
                "firmware_version": firmware_version,
                "ip_mode": capabilities.get("ip_mode", "unknown"),
                "static_ip": capabilities.get("static_ip"),
                "gateway": capabilities.get("gateway"),
                "subnet": capabilities.get("subnet"),
                "num_ports": num_ports,
                "universes": universes,
            }

    finally:
        sock.close()
    return list(nodes.values())


# ======================================================================
#  NODE OUTPUT PARSING
# ======================================================================

def _match_output_type(display_name, output_types):
    key = display_name.strip().lower().replace(" ", "_")
    aliases = {
        "grid_8x4": "small_grid",
        "grid_4x8": "small_grid",
    }
    if aliases.get(key) in output_types:
        return aliases[key]
    if key in output_types:
        return key
    for type_key in output_types:
        if key.startswith(type_key):
            return type_key
    return None


def _node_capability_parts(node_report):
    if not node_report:
        return []

    parts = [part.strip() for part in node_report.split("|") if part.strip()]
    try:
        caps_start = parts.index(NODE_CAPS_PREFIX)
    except ValueError:
        return []
    return parts[caps_start + 1:]


def _parse_radius_capability_parts(node_report):
    if not node_report:
        return []
    parts = [part.strip() for part in node_report.split("|") if part.strip()]
    try:
        caps_start = parts.index(NODE_CAPS_PREFIX_RADIUS)
    except ValueError:
        return []
    return parts[caps_start + 1:]


def _parse_radius_capabilities(node_report, short_name="", long_name=""):
    caps = {
        "profile": "pvrad1",
        "device_class": "radius",
        "hardware_profile": "v1",
        "hardware_label": "V1 Huzzah32",
        "firmware_version": None,
        "ip_mode": "unknown",
        "static_ip": None,
        "gateway": None,
        "subnet": None,
        "known": True,
        "rename": False,
        "hello": False,
        "ip_config": False,
        "output_config": False,
        "audio": False,
        "ftp": False,
    }
    parts = _parse_radius_capability_parts(node_report)
    if not parts:
        name_blob = f"{short_name} {long_name}".lower()
        if "radius" in name_blob:
            caps.update({"rename": True, "ip_config": True, "audio": True, "ftp": True})
        return caps
    for part in parts:
        if part.startswith(NODE_CAPS_BOARD_PREFIX):
            board_code = part[len(NODE_CAPS_BOARD_PREFIX):].strip()
            caps["hardware_profile"] = board_code or "v1"
            caps["hardware_label"] = BOARD_PROFILE_LABELS.get(
                board_code, board_code or "V1 Huzzah32")
            continue
        if part.startswith(NODE_CAPS_IP_PREFIX):
            _parse_ip_capability(part, caps)
            caps["ip_config"] = True
            continue
        if not part.startswith(NODE_CAPS_FEATURE_PREFIX):
            continue
        features = part[len(NODE_CAPS_FEATURE_PREFIX):]
        caps["rename"] = "R" in features
        caps["hello"] = "H" in features
        caps["ip_config"] = caps["ip_config"] or "I" in features
        caps["audio"] = "A" in features
        caps["ftp"] = caps["ftp"] or "F" in features or "A" in features
    return caps


def is_compatible_node(node_info, product):
    """Return True when a discovered node should be auto-added for the active product."""
    product = str(product or "").strip().lower()
    node_report = str((node_info or {}).get("node_report") or "")
    short_name = str((node_info or {}).get("short_name") or "")
    long_name = str((node_info or {}).get("long_name") or "")
    name_blob = f"{short_name} {long_name}".lower()

    if product == "radius":
        if NODE_CAPS_PREFIX_RADIUS in node_report:
            return True
        caps = parse_node_capabilities(node_report, short_name, long_name)
        if caps.get("device_class") == "radius":
            return True
        if caps.get("profile") == "pvrad1":
            return True
        return "radius" in name_blob

    if NODE_CAPS_PREFIX_RADIUS in node_report:
        return False
    if NODE_CAPS_PREFIX in node_report:
        return True
    if "radius" in name_blob and NODE_CAPS_PREFIX not in node_report:
        return False
    return True


def parse_node_capabilities(node_report, short_name="", long_name=""):
    if NODE_CAPS_PREFIX_RADIUS in (node_report or ""):
        return _parse_radius_capabilities(node_report, short_name, long_name)

    caps = {
        "profile": "generic",
        "device_class": "unknown",
        "hardware_profile": "unknown",
        "hardware_label": "Unknown hardware",
        "firmware_version": None,
        "ip_mode": "unknown",
        "static_ip": None,
        "gateway": None,
        "subnet": None,
        "known": False,
        "rename": False,
        "hello": False,
        "ip_config": False,
        "output_config": False,
        "receive_config": False,
        "receive_mode": "split",
        "base_universe": None,
        "battery": False,
        "audio": False,
        "ftp": False,
    }
    name_blob = f"{short_name} {long_name}".lower()
    parts = _node_capability_parts(node_report)

    if parts:
        caps["profile"] = "pv3cap1"
        saw_feature_token = False
        for part in parts:
            if part.startswith(NODE_CAPS_BOARD_PREFIX):
                board_code = part[len(NODE_CAPS_BOARD_PREFIX):].strip()
                caps["hardware_profile"] = board_code or "unknown"
                caps["hardware_label"] = BOARD_PROFILE_LABELS.get(
                    board_code, board_code or "Unknown hardware")
                continue
            if part.startswith(NODE_CAPS_IP_PREFIX):
                _parse_ip_capability(part, caps)
                continue
            if part.startswith(NODE_CAPS_UNIVERSE_PREFIX):
                _parse_universe_capability(part, caps)
                continue
            if not part.startswith(NODE_CAPS_FEATURE_PREFIX):
                continue
            saw_feature_token = True
            features = part[len(NODE_CAPS_FEATURE_PREFIX):]
            caps["rename"] = "R" in features
            caps["hello"] = "H" in features
            caps["ip_config"] = "I" in features
            caps["output_config"] = "O" in features
            caps["receive_config"] = "M" in features
            caps["battery"] = "B" in features
        if saw_feature_token:
            if caps["hardware_profile"] == "unknown" and "primusv3" in name_blob:
                caps["hardware_profile"] = "v31"
                caps["hardware_label"] = BOARD_PROFILE_LABELS["v31"]
            caps["known"] = True
            return caps
        if "primusv3" in name_blob:
            caps.update({
                "profile": "pv3cap1-legacy",
                "hardware_profile": "v31",
                "hardware_label": BOARD_PROFILE_LABELS["v31"],
                "rename": True,
                "hello": True,
                "ip_config": True,
                "output_config": True,
            })
            return caps
        return caps

    if "primusv3" in name_blob:
        caps.update({
            "profile": "primus-legacy",
            "hardware_profile": "v31",
            "hardware_label": BOARD_PROFILE_LABELS["v31"],
            "rename": True,
            "hello": True,
            "ip_config": True,
            "output_config": True,
        })
    return caps


def _parse_universe_capability(part, caps):
    match = re.fullmatch(r"U:([SC]):(\d+)", part)
    if not match:
        return
    mode_code, base_text = match.groups()
    caps["receive_mode"] = "combined" if mode_code == "C" else "split"
    caps["base_universe"] = int(base_text)


def _parse_ip_capability(part, caps):
    values = part[len(NODE_CAPS_IP_PREFIX):].split(":")
    mode = values[0].strip().upper() if values else ""
    if mode == "D":
        caps["ip_mode"] = "dhcp"
        caps["static_ip"] = None
        caps["gateway"] = None
        caps["subnet"] = None
    elif mode == "S":
        caps["ip_mode"] = "static"
        if len(values) > 1 and _looks_like_ipv4(values[1]):
            caps["static_ip"] = values[1]
        if len(values) > 2 and _looks_like_ipv4(values[2]):
            caps["gateway"] = values[2]
        if len(values) > 3 and _looks_like_ipv4(values[3]):
            caps["subnet"] = values[3]


def _looks_like_ipv4(value):
    try:
        ipv4_octets(value)
        return True
    except ValueError:
        return False


def ipv4_octets(value, name="ip"):
    text = str(value or "").strip()
    parts = text.split(".")
    if len(parts) != 4:
        raise ValueError(f"invalid {name}: expected dotted IPv4 address")
    octets = []
    for part in parts:
        if not part.isdigit():
            raise ValueError(f"invalid {name}: expected numeric IPv4 octets")
        octet = int(part, 10)
        if octet < 0 or octet > 255:
            raise ValueError(f"invalid {name}: IPv4 octets must be 0-255")
        octets.append(octet)
    return octets


def _parse_capability_outputs(node_report, type_keys):
    if not node_report or not type_keys:
        return []

    parts = _node_capability_parts(node_report)

    outputs = []
    for part in parts:
        match = re.fullmatch(r"(\d+):(\d+):(\d+)", part)
        if not match:
            continue
        port_index, type_id, universe = (int(value) for value in match.groups())
        if 0 <= type_id < len(type_keys):
            type_key = type_keys[type_id]
            if type_key != "none":
                outputs.append({
                    "name": f"A{port_index}",
                    "type": type_key,
                    "universe": universe,
                })

    outputs.sort(key=lambda output: int(output["name"][1:]))
    return outputs


def parse_node_outputs(long_name, universes, output_types, node_report="", type_keys=None):
    """Parse ArtPollReply output configuration.

    Preferred source is a versioned capability tag in Node Report. Legacy
    firmware falls back to parsing the human-readable Long Name.
    """
    outputs = _parse_capability_outputs(node_report, type_keys or list(output_types.keys()))
    if outputs:
        return outputs

    outputs = []
    parts = long_name.split("|")
    if len(parts) >= 2:
        matches = re.findall(r'(A\d+):([^A]+?)(?=\s+A\d+:|$)', parts[1])
        for name, type_display in matches:
            type_key = _match_output_type(type_display, output_types)
            if type_key:
                outputs.append({"name": name, "type": type_key})
    if not outputs:
        for i in range(len(universes)):
            outputs.append({"name": "A{}".format(i), "type": "long_strip"})
    return outputs


# ======================================================================
#  ART-NET NAMING — ArtAddress (opcode 0x6000)
# ======================================================================

def _udp_route_retryable(error):
    error_number = getattr(error, "errno", None)
    return error_number in (
        errno.EHOSTUNREACH,
        errno.ENETUNREACH,
        errno.EHOSTDOWN,
        64,
        65,
    )


def _send_udp_packet(ip, packet, source_ip=None):
    bind_attempts = [True, False] if source_ip else [False]
    last_error = None
    for bind_source in bind_attempts:
        if bind_source and not source_ip:
            continue
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if bind_source and source_ip:
                try:
                    sock.bind((source_ip, 0))
                except OSError:
                    continue
            try:
                sock.sendto(bytes(packet), (ip, ARTNET_PORT))
                return
            except OSError as exc:
                last_error = exc
                if bind_source and source_ip and _udp_route_retryable(exc):
                    continue
                raise
        finally:
            sock.close()
    if last_error:
        raise last_error
    raise OSError("UDP send failed")


def build_output_config_packet(output_types, type_to_id_map):
    """Build an ArtOutputConfig packet for the given output type keys."""
    num = len(output_types)
    pkt = bytearray(13 + num)
    pkt[0:8] = ARTNET_HEADER
    struct.pack_into("<H", pkt, 8, ARTNET_OPCODE_OUTPUT_CONFIG)
    struct.pack_into(">H", pkt, 10, ARTNET_VERSION)
    pkt[12] = num
    for i, t in enumerate(output_types):
        pkt[13 + i] = type_to_id_map.get(t, 0)
    return bytes(pkt)


def send_output_config(ip, output_types, type_to_id_map, source_ip=None):
    """Send ArtOutputConfig packet.
    output_types: list of type key strings.
    type_to_id_map: dict mapping type key -> firmware enum int.
    """
    pkt = build_output_config_packet(output_types, type_to_id_map)
    _send_udp_packet(ip, pkt, source_ip=source_ip)


def build_receive_config_packet(receive_mode, base_universe):
    """Build an ArtReceiveConfig packet."""
    mode_id = 1 if receive_mode == "combined" else 0
    pkt = bytearray(15)
    pkt[0:8] = ARTNET_HEADER
    struct.pack_into("<H", pkt, 8, ARTNET_OPCODE_RECEIVE_CONFIG)
    struct.pack_into(">H", pkt, 10, ARTNET_VERSION)
    pkt[12] = mode_id
    struct.pack_into("<H", pkt, 13, int(base_universe) & 0xFFFF)
    return bytes(pkt)


def send_receive_config(ip, receive_mode, base_universe, source_ip=None):
    """Send ArtReceiveConfig packet."""
    if receive_mode not in ("split", "combined"):
        raise ValueError(f"invalid receive_mode: {receive_mode!r}")
    pkt = build_receive_config_packet(receive_mode, base_universe)
    _send_udp_packet(ip, pkt, source_ip=source_ip)


# ======================================================================
#  ART-NET OUTPUT CONFIG — ArtOutputConfig (opcode 0x8100)
# ======================================================================


def send_art_address(ip, short_name, source_ip=None):
    pkt = bytearray(107)
    pkt[0:8] = ARTNET_HEADER
    struct.pack_into("<H", pkt, 8, ARTNET_OPCODE_ADDRESS)
    struct.pack_into(">H", pkt, 10, ARTNET_VERSION)
    pkt[12] = 0x7F
    pkt[13] = 0
    name_bytes = short_name.encode("ascii", errors="replace")[:17]
    pkt[14:14 + len(name_bytes)] = name_bytes
    for i in range(96, 104):
        pkt[i] = 0x7F
    pkt[104] = 0x7F
    pkt[106] = 0x00
    _send_udp_packet(ip, pkt, source_ip=source_ip)


# ======================================================================
#  ART-NET IP CONFIG — ArtIPConfig (opcode 0x8200)
# ======================================================================

def send_ip_config(ip, mode, static_ip=None, gateway=None, subnet=None, source_ip=None):
    """Send ArtIPConfig packet.
    mode: 0 = DHCP, 1 = static.
    static_ip/gateway/subnet: dotted-quad strings (required when mode=1).
    """
    pkt = bytearray(25)
    pkt[0:8] = ARTNET_HEADER
    struct.pack_into("<H", pkt, 8, ARTNET_OPCODE_IP_CONFIG)
    struct.pack_into(">H", pkt, 10, ARTNET_VERSION)
    pkt[12] = mode
    if mode == 1 and static_ip and gateway and subnet:
        for i, octet in enumerate(ipv4_octets(static_ip, "static_ip")):
            pkt[13 + i] = octet
        for i, octet in enumerate(ipv4_octets(gateway, "gateway")):
            pkt[17 + i] = octet
        for i, octet in enumerate(ipv4_octets(subnet, "subnet")):
            pkt[21 + i] = octet
    elif mode == 1:
        raise ValueError("static IP mode requires ip, gateway, and subnet")
    _send_udp_packet(ip, pkt, source_ip=source_ip)


# ======================================================================
#  AUDIO COMMAND — ArtAudioCmd (opcode 0x8300)
# ======================================================================

def send_audio_cmd(ip, cmd, filename="", volume=100, duration=0, delay_ms=0, source_ip=None):
    name_bytes = filename.encode("ascii", errors="replace")[:64] + b'\x00'
    if delay_ms and delay_ms > 0:
        name_bytes += struct.pack("<H", min(int(duration), 65535) if duration else 0)
        name_bytes += struct.pack("<H", min(int(delay_ms), 65535))
    elif duration and duration > 0:
        name_bytes += struct.pack("<H", min(int(duration), 65535))
    pkt = bytearray(14 + len(name_bytes))
    pkt[0:8] = ARTNET_HEADER
    struct.pack_into("<H", pkt, 8, ARTNET_OPCODE_AUDIO_CMD)
    struct.pack_into(">H", pkt, 10, ARTNET_VERSION)
    pkt[12] = cmd & 0xFF
    pkt[13] = max(0, min(100, volume)) & 0xFF
    pkt[14:14 + len(name_bytes)] = name_bytes
    _send_udp_packet(ip, pkt, source_ip=source_ip)
    cmd_name = _AUDIO_CMD_NAMES.get(cmd, str(cmd))
    dur_str  = f" [{duration}s]"      if duration else ""
    dly_str  = f" delay={delay_ms}ms" if delay_ms else ""
    file_str = f" \"{filename}\""     if filename else ""
    netlog.log("OUT", "audio_cmd",
               f"AudioCmd {cmd_name}{file_str} vol={volume}{dur_str}{dly_str} → {ip}")


# ======================================================================
#  FTP CONTROL — ArtFtpCmd (opcode 0x8301)
# ======================================================================

def send_ftp_cmd(ip, start, source_ip=None):
    pkt = bytearray(13)
    pkt[0:8] = ARTNET_HEADER
    struct.pack_into("<H", pkt, 8, ARTNET_OPCODE_FTP_CMD)
    struct.pack_into(">H", pkt, 10, ARTNET_VERSION)
    pkt[12] = 1 if start else 0
    _send_udp_packet(ip, pkt, source_ip=source_ip)
    netlog.log("OUT", "ftp_cmd", f"FTP {'start' if start else 'stop'} → {ip}")


def list_audio_files(ip, source_ip=None):
    try:
        entries = ftp_list_dir(ip, "/", source_ip=source_ip)
        return sorted(e["name"] for e in entries if e["name"].lower().endswith(".wav"))
    except Exception as exc:
        print(f"[audio] FTP list failed for {ip}: {exc}")
        return []


import contextlib as _contextlib
import io as _io


@_contextlib.contextmanager
def _ftp_session(ip, source_ip=None, timeout=8.0):
    import ftplib
    send_ftp_cmd(ip, start=True, source_ip=source_ip)
    time.sleep(0.5)
    ftp = ftplib.FTP()
    try:
        ftp.connect(ip, FTP_PORT, timeout=timeout)
        ftp.login(FTP_USER, FTP_PASSWORD)
        yield ftp
        try:
            ftp.quit()
        except Exception:
            pass
    except Exception:
        try:
            ftp.close()
        except Exception:
            pass
        raise
    finally:
        send_ftp_cmd(ip, start=False, source_ip=source_ip)


def _parse_list_line(line):
    """Parse a SimpleFTPServer LIST line into {name, is_dir, size}.

    SimpleFTPServer (SD storage) omits the group field, producing 8 fields:
      permissions links user size month day time filename
    Standard Unix ls long format has 9 fields (includes group between user and size):
      permissions links user group size month day time/year filename
    """
    parts = line.split(None, 8)
    n = len(parts)
    if n == 9:
        size_idx, name_idx = 4, 8   # standard: has group field
    elif n == 8:
        size_idx, name_idx = 3, 7   # SimpleFTPServer: no group field
    else:
        return None
    try:
        size = int(parts[size_idx])
    except ValueError:
        size = 0
    return {"name": parts[name_idx], "is_dir": parts[0].startswith("d"), "size": size}


def ftp_list_dir(ip, path="/", source_ip=None):
    entries = []
    with _ftp_session(ip, source_ip=source_ip) as ftp:
        lines = []
        try:
            ftp.retrlines(f"LIST {path}", lines.append)
        except Exception:
            ftp.retrlines("LIST", lines.append)
        for line in lines:
            entry = _parse_list_line(line)
            if entry and entry["name"] not in (".", ".."):
                entries.append(entry)
    return sorted(entries, key=lambda e: (not e["is_dir"], e["name"].lower()))


def ftp_download(ip, path, source_ip=None):
    buf = _io.BytesIO()
    with _ftp_session(ip, source_ip=source_ip) as ftp:
        ftp.retrbinary(f"RETR {path}", buf.write)
    return buf.getvalue()


def ftp_upload(ip, path, data, source_ip=None, progress_callback=None):
    total = len(data)
    with _ftp_session(ip, source_ip=source_ip) as ftp:
        if progress_callback:
            transferred = [0]

            def _cb(block):
                transferred[0] += len(block)
                progress_callback(transferred[0], total)

            ftp.storbinary(f"STOR {path}", _io.BytesIO(data), callback=_cb)
        else:
            ftp.storbinary(f"STOR {path}", _io.BytesIO(data))
    netlog.log("OUT", "ftp_upload", f"FTP upload {path} ({total} bytes) → {ip}")


def ftp_rename(ip, src, dst, source_ip=None):
    with _ftp_session(ip, source_ip=source_ip) as ftp:
        ftp.rename(src, dst)
    netlog.log("OUT", "ftp_rename", f"FTP rename {src} → {dst} on {ip}")


def ftp_delete(ip, path, is_dir=False, source_ip=None):
    with _ftp_session(ip, source_ip=source_ip) as ftp:
        if is_dir:
            ftp.rmd(path)
        else:
            ftp.delete(path)
    netlog.log("OUT", "ftp_delete", f"FTP delete {path} on {ip}")


def ftp_mkdir(ip, path, source_ip=None):
    with _ftp_session(ip, source_ip=source_ip) as ftp:
        ftp.mkd(path)
    netlog.log("OUT", "ftp_mkdir", f"FTP mkdir {path} on {ip}")
