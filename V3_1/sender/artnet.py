"""
artnet.py — Art-Net transport, discovery, naming, output config, and FPS telemetry.
"""

import re
import socket
import struct
import threading
import time

# ======================================================================
#  ART-NET CONSTANTS
# ======================================================================

ARTNET_HEADER = b"Art-Net\x00"
ARTNET_OPCODE_DMX = 0x5000
ARTNET_OPCODE_POLL = 0x2000
ARTNET_OPCODE_POLLREPLY = 0x2100
ARTNET_OPCODE_ADDRESS = 0x6000
ARTNET_OPCODE_OUTPUT_CONFIG = 0x8100
ARTNET_VERSION = 14
ARTNET_PORT = 6454

FPS_LISTEN_PORT = 6455
FPS_MAGIC = b"PFP"


# ======================================================================
#  ART-NET SENDER
# ======================================================================

class ArtNetSender:
    """Sends one Art-Net ArtDmx packet per output, per frame."""

    def __init__(self, ip):
        self.ip = ip
        self.sock = None
        self.connected = False
        self.sequence = 1

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.connected = True

    def disconnect(self):
        self.connected = False
        if self.sock:
            self.sock.close()
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
        if not self.connected or not self.sock:
            return
        pkt = self._build_packet(universe, rgb_data)
        self.sock.sendto(pkt, (self.ip, ARTNET_PORT))

    def advance_sequence(self):
        self.sequence = (self.sequence % 255) + 1

    def blackout(self, outputs_info):
        if not self.connected:
            return
        for universe, pixel_count in outputs_info:
            self.send_output(universe, bytes(pixel_count * 3))
        self.advance_sequence()


# ======================================================================
#  FPS TELEMETRY LISTENER
# ======================================================================

class FpsListener:
    """Listens on UDP 6455 for FPS telemetry from receivers."""

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
            print(f"WARNING: FPS telemetry port {FPS_LISTEN_PORT} in use — receiver FPS will not display.")
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


def discover_artnet_nodes(known_ips=None, timeout=2.0):
    """Send ArtPoll and collect ArtPollReply responses.

    known_ips: list of IP strings to unicast to in addition to broadcast.
    Returns list of dicts: {ip, short_name, long_name, num_ports, universes}
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(0.25)
    sock.bind(("", ARTNET_PORT))

    poll = bytearray()
    poll += ARTNET_HEADER
    poll += struct.pack("<H", ARTNET_OPCODE_POLL)
    poll += struct.pack(">H", ARTNET_VERSION)
    poll += bytes([0x00, 0x00])

    targets = {"255.255.255.255"}
    targets.update(_get_all_broadcast_addresses())
    for ip in (known_ips or []):
        targets.add(ip)
    for dest in targets:
        try:
            sock.sendto(bytes(poll), (dest, ARTNET_PORT))
        except OSError:
            pass

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
#  NODE OUTPUT PARSING
# ======================================================================

def _match_output_type(display_name, output_types):
    key = display_name.strip().lower().replace(" ", "_")
    if key in output_types:
        return key
    for type_key in output_types:
        if key.startswith(type_key):
            return type_key
    return None


def parse_node_outputs(long_name, universes, output_types):
    """Parse ArtPollReply long_name to extract output configuration."""
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

def send_art_address(ip, short_name):
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
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(bytes(pkt), (ip, ARTNET_PORT))
    sock.close()


# ======================================================================
#  ART-NET OUTPUT CONFIG — ArtOutputConfig (opcode 0x8100)
# ======================================================================

def send_output_config(ip, output_types, type_to_id_map):
    """Send ArtOutputConfig packet.
    output_types: list of type key strings.
    type_to_id_map: dict mapping type key -> firmware enum int.
    """
    num = len(output_types)
    pkt = bytearray(13 + num)
    pkt[0:8] = ARTNET_HEADER
    struct.pack_into("<H", pkt, 8, ARTNET_OPCODE_OUTPUT_CONFIG)
    struct.pack_into(">H", pkt, 10, ARTNET_VERSION)
    pkt[12] = num
    for i, t in enumerate(output_types):
        pkt[13 + i] = type_to_id_map.get(t, 0)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(bytes(pkt), (ip, ARTNET_PORT))
    sock.close()
