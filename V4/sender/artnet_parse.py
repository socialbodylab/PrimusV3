"""artnet_parse.py — Parse Art-Net packets for capture/analysis."""

import struct
import zlib

ARTNET_HEADER = b"Art-Net\x00"
ARTNET_PORT = 6454

ARTNET_OPCODE_NAMES = {
    0x2000: "ArtPoll",
    0x2100: "ArtPollReply",
    0x5000: "ArtDmx",
    0x6000: "ArtAddress",
    0x8100: "ArtOutputConfig",
    0x8110: "ArtReceiveConfig",
    0x8130: "ArtVirtualResolution",
    0x8200: "ArtIPConfig",
    0x8210: "ArtShowInfo",
    0x8300: "ArtAudioCmd",
    0x8301: "ArtFtpCmd",
}


def opcode_name(opcode):
    return ARTNET_OPCODE_NAMES.get(opcode, f"0x{opcode:04X}")


def payload_crc32(data):
    return f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"


def build_artdmx_packet(universe, sequence, rgb_data):
    """Build a test/replay ArtDmx packet (mirrors artnet.ArtNetSender._build_packet)."""
    if len(rgb_data) % 2 != 0:
        rgb_data = rgb_data + b"\x00"
    length = len(rgb_data)
    pkt = bytearray()
    pkt += ARTNET_HEADER
    pkt += struct.pack("<H", 0x5000)
    pkt += struct.pack(">H", 14)
    pkt += bytes([sequence])
    pkt += bytes([0])
    pkt += struct.pack("<H", universe)
    pkt += struct.pack(">H", length)
    pkt += rgb_data
    return bytes(pkt)


def parse_artnet_packet(raw, src_ip="", dst_ip="", ts=None, full_payload=False):
    """Parse one Art-Net UDP payload into a capture event dict."""
    if len(raw) < 18 or raw[:8] != ARTNET_HEADER:
        return None
    opcode = struct.unpack("<H", raw[8:10])[0]
    event = {
        "ts": ts,
        "src": src_ip or "",
        "dst": dst_ip or "",
        "opcode": opcode,
        "opcode_name": opcode_name(opcode),
        "universe": None,
        "sequence": None,
        "length": None,
        "payload_crc32": None,
    }
    if opcode == 0x5000 and len(raw) >= 18:
        event["sequence"] = raw[12]
        event["universe"] = struct.unpack("<H", raw[14:16])[0]
        data_len = struct.unpack(">H", raw[16:18])[0]
        payload = raw[18:18 + data_len]
        event["length"] = len(payload)
        event["payload_crc32"] = payload_crc32(payload)
        if full_payload:
            event["payload_hex"] = payload.hex()
    elif len(raw) > 18:
        payload = raw[18:]
        event["length"] = len(payload)
        event["payload_crc32"] = payload_crc32(payload)
        if full_payload:
            event["payload_hex"] = payload.hex()
    return event


def parse_ethernet_udp(raw):
    """Extract (src_ip, dst_ip, udp_payload) from a raw Ethernet frame."""
    if len(raw) < 42:
        return None
    ethertype = struct.unpack(">H", raw[12:14])[0]
    if ethertype != 0x0800:
        return None
    ip_start = 14
    version_ihl = raw[ip_start]
    if (version_ihl >> 4) != 4:
        return None
    ihl = (version_ihl & 0x0F) * 4
    if len(raw) < ip_start + ihl + 8:
        return None
    proto = raw[ip_start + 9]
    if proto != 17:
        return None
    src_ip = ".".join(str(b) for b in raw[ip_start + 12:ip_start + 16])
    dst_ip = ".".join(str(b) for b in raw[ip_start + 16:ip_start + 20])
    udp_start = ip_start + ihl
    dst_port = struct.unpack(">H", raw[udp_start + 2:udp_start + 4])[0]
    if dst_port != ARTNET_PORT:
        return None
    udp_len = struct.unpack(">H", raw[udp_start + 4:udp_start + 6])[0]
    payload_start = udp_start + 8
    payload_end = udp_start + udp_len
    if payload_end > len(raw):
        payload_end = len(raw)
    payload = raw[payload_start:payload_end]
    return src_ip, dst_ip, payload
