"""
artnet.py — Art-Net transport, discovery, naming, output config, and FPS telemetry.
"""

from dataclasses import dataclass
import errno
import ipaddress
import os
import re
import secrets
import socket
import struct
import threading
import time

import netlog
from primus_protocol import (
    ErrorCode,
    MANAGEMENT_PROTOCOL_VERSION,
    MANAGEMENT_REPLY_OPCODE,
    Operation,
    ReplyStatus,
    STATUS_FLAG_BATTERY_VALID,
    STATUS_FLAG_OUTPUT_POWER,
    STATUS_FLAG_PRODUCTION,
    STATUS_FLAG_STATIC_IP,
    STATUS_FLAG_TELEMETRY_CONFIGURED,
    STATUS_FLAG_TEST_ACTIVE,
    STATUS_FLAG_UNLOCK_WINDOW_OPEN,
    STATUS_FLAG_WIFI_CONNECTED,
    STATUS_MAGIC,
    STATUS_PACKET_SIZE,
    STATUS_PROTOCOL_VERSION,
    build_management_request,
    pack_identity,
    pack_ip_config,
    pack_operating_mode,
    pack_output_descriptors,
    pack_receive_config,
    pack_telemetry_target,
    parse_management_packet,
    unpack_config,
    unpack_status,
)

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
ARTNET_OPCODE_VIRTUAL_RESOLUTION = 0x8130
ARTNET_OPCODE_IP_CONFIG = 0x8200
ARTNET_OPCODE_SHOW_INFO = 0x8210
ARTNET_OPCODE_AUDIO_CMD = 0x8300
ARTNET_OPCODE_FTP_CMD = 0x8301
ARTNET_OPCODE_AUDIO_STATUS = 0x8302
ARTNET_VERSION = 14
ARTNET_PORT = 6454
RADIUS_ARTNET_PORT = 6456  # Radius on its own Art-Net port — keeps LED/3rd-party 6454 traffic off Radius nodes
RADIUS_OSC_PORT = 53001    # firmware OSC_PORT — device /cue/N listener (cue-map test-fire)
_artnet_query_lock = threading.RLock()
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


def _normalize_decix10(value):
    if value % 10 == 0:
        return value // 10
    return round(value / 10.0, 1)


class PrimusTelemetryListener:
    """Listens on UDP 6455 for PFP and PBT telemetry from Primus receivers."""

    _PST_FORWARD_DELTA_MAX = 0x7FFF
    _PST_REBOOT_MAX_UPTIME_SECONDS = 30
    _PST_REBOOT_MAX_SEQUENCE = 64
    _PST_REBOOT_MIN_PREVIOUS_UPTIME_SECONDS = 60
    _PST_REBOOT_MIN_PREVIOUS_SEQUENCE = 0x8000
    _PST_REBOOT_CONFIRM_MAX_GAP = 64
    _PST_REBOOT_GENERATION_GUARD_SECONDS = 30.0

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
        self.monotonic = time.monotonic

    def _now(self):
        clock = getattr(self, "monotonic", None)
        if callable(clock):
            return clock()
        return time.monotonic()

    def _touch_entry(self, entry, key, timestamp):
        entry[key] = timestamp
        if timestamp >= entry.get("ts", 0):
            entry["ts"] = timestamp

    def _fresh(self, entry, key, now):
        timestamp = entry.get(key)
        if timestamp is None:
            return False
        return (now - timestamp) < self.TELEMETRY_STALE_SECONDS

    def _record_counter(self, entry, key, increment=1):
        entry[key] = int(entry.get(key, 0)) + int(increment)

    @classmethod
    def _pst_sequence_order(cls, previous_sequence, sequence):
        delta = (sequence - previous_sequence) & 0xFFFF
        if delta == 0:
            return "duplicate", delta
        if delta <= cls._PST_FORWARD_DELTA_MAX:
            return "forward", delta
        return "older", delta

    @classmethod
    def _pst_is_credible_reboot(
        cls,
        previous_sequence,
        previous_uptime,
        sequence,
        uptime_seconds,
        sequence_order,
    ):
        if (
            previous_sequence is None
            or previous_uptime is None
            or sequence_order != "forward"
            or uptime_seconds >= previous_uptime
            or uptime_seconds > cls._PST_REBOOT_MAX_UPTIME_SECONDS
            or sequence > cls._PST_REBOOT_MAX_SEQUENCE
            or previous_uptime < cls._PST_REBOOT_MIN_PREVIOUS_UPTIME_SECONDS
            or previous_sequence < cls._PST_REBOOT_MIN_PREVIOUS_SEQUENCE
        ):
            return False
        return True

    @classmethod
    def _pst_is_reboot_candidate(
        cls,
        previous_uptime,
        sequence,
        uptime_seconds,
    ):
        return (
            previous_uptime is not None
            and previous_uptime >= cls._PST_REBOOT_MIN_PREVIOUS_UPTIME_SECONDS
            and uptime_seconds < previous_uptime
            and uptime_seconds <= cls._PST_REBOOT_MAX_UPTIME_SECONDS
            and sequence <= cls._PST_REBOOT_MAX_SEQUENCE
        )

    @classmethod
    def _pst_confirms_reboot(cls, candidate, previous_uptime, sequence, uptime_seconds):
        if candidate is None or previous_uptime is None:
            return False, 0
        sequence_order, delta = cls._pst_sequence_order(
            candidate["sequence"], sequence
        )
        uptime_delta = uptime_seconds - candidate["uptime_seconds"]
        return (
            sequence_order == "forward"
            and delta <= cls._PST_REBOOT_CONFIRM_MAX_GAP
            and 0 <= uptime_delta <= cls._PST_REBOOT_CONFIRM_MAX_GAP
            and uptime_seconds < previous_uptime
        ), delta

    def _map_unified_status(self, status):
        flags = status.flags
        battery_mode = BATTERY_POWER_MODE_LABELS.get(
            int(status.battery_mode), "unavailable"
        )
        battery_valid = bool(flags & STATUS_FLAG_BATTERY_VALID)
        battery_mv = status.battery_mv if battery_valid and status.battery_mv > 0 else None
        battery_pct = (
            status.battery_pct
            if battery_valid and status.battery_pct <= 100
            else None
        )
        production_mode = bool(flags & STATUS_FLAG_PRODUCTION)
        return {
            "protocol_version": STATUS_PROTOCOL_VERSION,
            "sequence": status.sequence,
            "uptime_seconds": status.uptime_seconds,
            "status_flags": flags,
            "status_flag_wifi_connected": bool(flags & STATUS_FLAG_WIFI_CONNECTED),
            "status_flag_static_ip": bool(flags & STATUS_FLAG_STATIC_IP),
            "status_flag_output_power": bool(flags & STATUS_FLAG_OUTPUT_POWER),
            "status_flag_test_active": bool(flags & STATUS_FLAG_TEST_ACTIVE),
            "status_flag_telemetry_configured": bool(
                flags & STATUS_FLAG_TELEMETRY_CONFIGURED
            ),
            "status_flag_production": production_mode,
            "status_flag_unlock_window_open": bool(
                flags & STATUS_FLAG_UNLOCK_WINDOW_OPEN
            ),
            "status_flag_battery_valid": battery_valid,
            "wifi_connected": bool(flags & STATUS_FLAG_WIFI_CONNECTED),
            "static_ip": bool(flags & STATUS_FLAG_STATIC_IP),
            "output_power_enabled": bool(flags & STATUS_FLAG_OUTPUT_POWER),
            "test_mode_active": bool(flags & STATUS_FLAG_TEST_ACTIVE),
            "telemetry_configured": bool(flags & STATUS_FLAG_TELEMETRY_CONFIGURED),
            "production_mode": production_mode,
            "operating_mode": "production" if production_mode else "prototype",
            "management_locked": production_mode,
            "operating_mode_locked": production_mode,
            "unlock_window_open": bool(flags & STATUS_FLAG_UNLOCK_WINDOW_OPEN),
            "unlock_remaining_seconds": status.unlock_remaining_seconds,
            "fps": _normalize_decix10(status.rendered_fps_x10),
            "pkt_rate": _normalize_decix10(status.packet_rate_x10),
            "rendered_fps_x10": status.rendered_fps_x10,
            "packet_rate_x10": status.packet_rate_x10,
            "rssi_dbm": status.rssi_dbm,
            "firmware_major": status.firmware_major,
            "firmware_minor": status.firmware_minor,
            "firmware_patch": status.firmware_patch,
            "firmware_version": (
                f"{status.firmware_major}.{status.firmware_minor}.{status.firmware_patch}"
            ),
            "live_firmware_version": (
                f"{status.firmware_major}.{status.firmware_minor}.{status.firmware_patch}"
            ),
            "battery_mode": battery_mode,
            "battery_power_mode": battery_mode,
            "battery_available": battery_valid,
            "battery_mv": battery_mv,
            "battery_pct": battery_pct,
            "battery_warning": BATTERY_WARNING_MESSAGES.get(battery_mode),
        }

    def _merge_public_entry(self, entry, now):
        public = {
            key: value
            for key, value in entry.items()
            if not key.startswith("_")
        }
        if "_pst_ts" in entry or "_pfp_ts" in entry:
            public.pop("fps", None)
            public.pop("pkt_rate", None)
        if "_pst_ts" in entry or "_pbt_ts" in entry:
            public.pop("battery_mv", None)
            public.pop("battery_pct", None)
            public.pop("battery_power_mode", None)
            public.pop("battery_mode", None)
            public.pop("battery_available", None)
            public.pop("battery_warning", None)
            public.pop("live_firmware_version", None)
            public.pop("firmware_version", None)
        if "_ptr_ts" in entry:
            public.pop("current_track", None)
            public.pop("playback_state", None)

        if self._fresh(entry, "_pst_ts", now):
            public.update(entry.get("_pst_public", {}))
        else:
            if self._fresh(entry, "_pfp_ts", now):
                public["fps"] = entry.get("_pfp_fps")
                public["pkt_rate"] = entry.get("_pfp_pkt_rate")
            if self._fresh(entry, "_pbt_ts", now):
                public.update(entry.get("_pbt_public", {}))

        if self._fresh(entry, "_ptr_ts", now):
            public["playback_state"] = entry.get("_ptr_state", 0)
            public["current_track"] = entry.get("_ptr_track", "")

        heartbeat_ts = entry.get("ts")
        if heartbeat_ts is not None:
            age = max(0.0, now - heartbeat_ts)
            public["heartbeat_age_seconds"] = round(age, 2)
            public["heartbeat_fresh"] = age < self.TELEMETRY_STALE_SECONDS
        return public

    def _record_malformed_packet(self, ip):
        with self.lock:
            entry = self.data.setdefault(ip, {})
            self._record_counter(entry, "telemetry_malformed_packets")

    def _record_unified_status(self, ip, status, timestamp):
        with self.lock:
            entry = self.data.setdefault(ip, {})
            self._record_counter(entry, "telemetry_status_packets_received")
            reboot_guard = entry.get("_pst_reboot_guard")
            if reboot_guard is not None:
                if timestamp > reboot_guard["expires_at"]:
                    entry.pop("_pst_reboot_guard", None)
                elif (
                    status.uptime_seconds >= reboot_guard["old_uptime_floor"]
                    and (
                        0
                        < ((status.sequence - reboot_guard["old_sequence"]) & 0xFFFF)
                        <= self._PST_REBOOT_CONFIRM_MAX_GAP
                        or (
                            0
                            < ((reboot_guard["old_sequence"] - status.sequence) & 0xFFFF)
                            <= 8
                        )
                    )
                ):
                    self._record_counter(entry, "telemetry_out_of_order_packets")
                    accepted_packets = int(
                        entry.get("telemetry_status_packets_accepted", 0)
                    )
                    lost_packets = int(entry.get("telemetry_packets_lost", 0))
                    total_packets = accepted_packets + lost_packets
                    entry["telemetry_packet_loss_rate"] = (
                        lost_packets / total_packets if total_packets else 0.0
                    )
                    self._touch_entry(entry, "_pst_ts", timestamp)
                    return
            previous_sequence = entry.get("_pst_sequence")
            previous_uptime = entry.get("_pst_uptime_seconds")
            accept_update = True
            reboot_candidate = entry.get("_pst_reboot_candidate")
            reboot_confirmed, reboot_delta = self._pst_confirms_reboot(
                reboot_candidate,
                previous_uptime,
                status.sequence,
                status.uptime_seconds,
            )
            if reboot_confirmed:
                entry.pop("_pst_reboot_candidate", None)
                if reboot_candidate.get("counted_out_of_order"):
                    entry["telemetry_out_of_order_packets"] = max(
                        0, int(entry.get("telemetry_out_of_order_packets", 0)) - 1
                    )
                self._record_counter(entry, "telemetry_reboot_count")
                self._record_counter(entry, "telemetry_uptime_reset_count")
                self._record_counter(entry, "telemetry_status_packets_accepted")
                entry["_pst_reboot_guard"] = {
                    "old_sequence": previous_sequence,
                    "old_uptime_floor": (
                        previous_uptime + reboot_candidate["uptime_seconds"]
                    ) // 2,
                    "expires_at": (
                        timestamp + self._PST_REBOOT_GENERATION_GUARD_SECONDS
                    ),
                }
                if reboot_delta > 1:
                    lost_packets = reboot_delta - 1
                    self._record_counter(
                        entry, "telemetry_packets_lost", lost_packets
                    )
                    entry["telemetry_last_sequence_gap"] = lost_packets
            if previous_sequence is not None:
                sequence_order, delta = self._pst_sequence_order(
                    previous_sequence, status.sequence
                )
                if reboot_confirmed:
                    pass
                elif sequence_order == "duplicate":
                    self._record_counter(entry, "telemetry_duplicate_packets")
                    accept_update = False
                elif sequence_order == "forward":
                    if (
                        previous_uptime is not None
                        and status.uptime_seconds < previous_uptime
                    ):
                        if self._pst_is_credible_reboot(
                            previous_sequence,
                            previous_uptime,
                            status.sequence,
                            status.uptime_seconds,
                            sequence_order,
                        ):
                            self._record_counter(entry, "telemetry_reboot_count")
                            self._record_counter(entry, "telemetry_uptime_reset_count")
                            entry["_pst_reboot_guard"] = {
                                "old_sequence": previous_sequence,
                                "old_uptime_floor": (
                                    previous_uptime + status.uptime_seconds
                                ) // 2,
                                "expires_at": (
                                    timestamp
                                    + self._PST_REBOOT_GENERATION_GUARD_SECONDS
                                ),
                            }
                            entry.pop("_pst_reboot_candidate", None)
                        else:
                            if self._pst_is_reboot_candidate(
                                previous_uptime,
                                status.sequence,
                                status.uptime_seconds,
                            ):
                                entry["_pst_reboot_candidate"] = {
                                    "sequence": status.sequence,
                                    "uptime_seconds": status.uptime_seconds,
                                    "counted_out_of_order": False,
                                }
                            accept_update = False
                    else:
                        entry.pop("_pst_reboot_candidate", None)
                        if status.sequence < previous_sequence:
                            self._record_counter(entry, "telemetry_sequence_wraps")
                        if delta > 1:
                            lost_packets = delta - 1
                            self._record_counter(
                                entry, "telemetry_packets_lost", lost_packets
                            )
                            entry["telemetry_last_sequence_gap"] = lost_packets
                else:
                    self._record_counter(entry, "telemetry_out_of_order_packets")
                    if self._pst_is_reboot_candidate(
                        previous_uptime,
                        status.sequence,
                        status.uptime_seconds,
                    ):
                        entry["_pst_reboot_candidate"] = {
                            "sequence": status.sequence,
                            "uptime_seconds": status.uptime_seconds,
                            "counted_out_of_order": True,
                        }
                    accept_update = False

            if accept_update:
                entry["_pst_sequence"] = status.sequence
                entry["_pst_uptime_seconds"] = status.uptime_seconds
                entry["_pst_public"] = self._map_unified_status(status)
                entry["telemetry_last_sequence_gap"] = 0
                self._record_counter(entry, "telemetry_status_packets_accepted")

            accepted_packets = int(entry.get("telemetry_status_packets_accepted", 0))
            lost_packets = int(entry.get("telemetry_packets_lost", 0))
            total_packets = accepted_packets + lost_packets
            entry["telemetry_packet_loss_rate"] = (
                lost_packets / total_packets if total_packets else 0.0
            )
            self._touch_entry(entry, "_pst_ts", timestamp)

    def _record_pbt(self, ip, parsed, timestamp):
        with self.lock:
            entry = self.data.setdefault(ip, {})
            entry["_pbt_public"] = dict(parsed)
            self._touch_entry(entry, "_pbt_ts", timestamp)

    def _record_pfp(self, ip, parsed, timestamp):
        with self.lock:
            entry = self.data.setdefault(ip, {})
            entry["_pfp_fps"] = parsed["fps"]
            entry["_pfp_pkt_rate"] = parsed["pkt_rate"]
            self._touch_entry(entry, "_pfp_ts", timestamp)

    def _record_ptr(self, ip, playback_state, current_track, timestamp):
        with self.lock:
            entry = self.data.setdefault(ip, {})
            entry["_ptr_state"] = playback_state
            entry["_ptr_track"] = current_track
            self._touch_entry(entry, "_ptr_ts", timestamp)

    def _handle_packet(self, raw, ip):
        timestamp = self._now()
        if len(raw) >= 3 and raw[:3] == STATUS_MAGIC:
            try:
                status = unpack_status(raw)
            except ValueError:
                self._record_malformed_packet(ip)
                return
            self._record_unified_status(ip, status, timestamp)
            return
        if len(raw) >= 3 and raw[:3] == BATTERY_MAGIC:
            parsed = parse_pbt_packet(raw)
            if parsed is None:
                self._record_malformed_packet(ip)
                return
            self._record_pbt(ip, parsed, timestamp)
            return
        if len(raw) >= 3 and raw[:3] == TRACK_MAGIC:
            if len(raw) < 5:
                self._record_malformed_packet(ip)
                return
            state = raw[3]
            name_len = raw[4]
            name = raw[5:5 + name_len].decode("utf-8", errors="replace") if name_len else ""
            self._record_ptr(ip, state, name, timestamp)
            return
        if len(raw) >= 3 and raw[:3] == FPS_MAGIC:
            parsed = parse_pfp_packet(raw)
            if parsed is None:
                self._record_malformed_packet(ip)
                return
            self._record_pfp(ip, parsed, timestamp)
            netlog.log_fps(ip, parsed["fps"], parsed["pkt_rate"])
            return

    def run(self):
        while self.running:
            try:
                raw, addr = self._sock.recvfrom(256)
            except socket.timeout:
                continue
            self._handle_packet(raw, addr[0])

    TELEMETRY_STALE_SECONDS = 12.0
    TELEMETRY_ONLINE_SECONDS = 3.0

    def get(self, ip):
        now = self._now()
        with self.lock:
            entry = self.data.get(ip)
            if entry and (now - entry.get("ts", 0)) < self.TELEMETRY_STALE_SECONDS:
                return self._merge_public_entry(entry, now)
        return None

    def get_telemetry_status(self, ip):
        """Return (fresh_entry_or_none, age_seconds_or_none, receiver_online)."""
        now = self._now()
        with self.lock:
            entry = self.data.get(ip)
            if not entry or "ts" not in entry:
                return None, None, False
            age = now - entry["ts"]
            fresh = (
                self._merge_public_entry(entry, now)
                if age < self.TELEMETRY_STALE_SECONDS
                else None
            )
            online = age < self.TELEMETRY_ONLINE_SECONDS
            return fresh, round(age, 2), online

    def stop(self):
        self.running = False
        self._sock.close()


class FpsListener(PrimusTelemetryListener):
    """Backward-compatible alias for Primus telemetry listener."""


def parse_audio_status_packet(raw):
    """Parse an ArtAudioStatus (0x8302) packet. Returns dict or None.

    Layout: Art-Net header (8) + opcode LE (2) + protocol version (2) +
    status byte (1) + null-terminated ASCII filename (up to 64 bytes).
    """
    if len(raw) < 13 or raw[:8] != ARTNET_HEADER:
        return None
    opcode = struct.unpack("<H", raw[8:10])[0]
    if opcode != ARTNET_OPCODE_AUDIO_STATUS:
        return None
    name = raw[13:77].split(b'\x00')[0].decode("ascii", errors="replace")
    return {"playback_state": raw[12], "current_track": name}


def parse_track_packet(raw):
    """Parse a legacy PTR track telemetry packet (fallback). Returns dict or None."""
    if len(raw) < 5 or raw[:3] != TRACK_MAGIC:
        return None
    name_len = raw[4]
    name = raw[5:5 + name_len].decode("utf-8", errors="replace") if name_len else ""
    return {"playback_state": raw[3], "current_track": name}


class RadiusTelemetryListener:
    """Listens on UDP 6455 for Radius telemetry: 0x8302 ArtAudioStatus (primary,
    event-driven), legacy PTR track telemetry (fallback), PBT battery, and PFP
    packet rate. Merges keys so a status update never wipes battery/FPS. No
    staleness window — playback state is event-driven and persists until the
    next state-change packet (the periodic PTR heartbeat was removed)."""

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
                    entry = self.data.setdefault(addr[0], {})
                    entry.update(status)
                    entry["ts"] = time.monotonic()
                state = status["playback_state"]
                name = status["current_track"]
                state_str = "playing" if state == 1 else ("paused" if state == 2 else "stopped")
                file_str = f" \"{name}\"" if name else ""
                netlog.log("IN", "audio_status", f"AudioStatus {state_str}{file_str} ← {addr[0]}")
                continue
            if len(raw) >= 13 and raw[:8] == ARTNET_HEADER:
                continue  # other Art-Net traffic on the telemetry port — ignore
            if len(raw) >= 9 and raw[:3] == BATTERY_MAGIC:
                parsed = parse_pbt_packet(raw)
                if parsed:
                    with self.lock:
                        entry = self.data.setdefault(addr[0], {})
                        entry.update(parsed)
                        entry["ts"] = time.monotonic()
                continue
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


def _discovery_bind_addr(interface=None, port=ARTNET_PORT):
    source_ip = (interface or {}).get("source_ip") or (interface or {}).get("ipv4")
    return (source_ip or "", port)


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


def discover_artnet_nodes(known_ips=None, timeout=3.5, interface=None, port=ARTNET_PORT):
    with _artnet_query_lock:
        return _discover_artnet_nodes_unlocked(
            known_ips=known_ips,
            timeout=timeout,
            interface=interface,
            port=port,
        )


def _discover_artnet_nodes_unlocked(known_ips=None, timeout=3.5, interface=None, port=ARTNET_PORT):
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
            sock.bind(_discovery_bind_addr(interface, port))
        except OSError:
            sock.bind(("", port))

        poll = bytearray()
        poll += ARTNET_HEADER
        poll += struct.pack("<H", ARTNET_OPCODE_POLL)
        poll += struct.pack(">H", ARTNET_VERSION)
        poll += bytes([0x00, 0x00])

        destinations = _discovery_destinations(known_ips, interface)
        for dest in destinations:
            try:
                sock.sendto(bytes(poll), (dest, port))
            except OSError:
                pass

        nodes = {}
        poll_budget = max(0.5, timeout * 0.6)
        poll_deadline = time.monotonic() + poll_budget
        show_deadline = time.monotonic() + timeout
        while time.monotonic() < poll_deadline:
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
                "character_name": "",
                "performer_name": "",
            }

        node_list = list(nodes.values())
        show_info_nodes = [
            node for node in node_list
            if (node.get("capabilities") or {}).get("show_info")
            or (node.get("capabilities") or {}).get("device_class") == "radius"
        ]
        known = set(known_ips or [])
        if known:
            show_info_nodes.sort(key=lambda node: 0 if node.get("ip") in known else 1)
        per_node_timeout = 0.35
        if show_info_nodes:
            remaining_budget = max(0.0, show_deadline - time.monotonic())
            per_node_timeout = min(0.35, remaining_budget / len(show_info_nodes))
        for node in show_info_nodes:
            remaining = show_deadline - time.monotonic()
            if remaining <= 0:
                break
            show = query_show_info(
                node["ip"],
                timeout=min(per_node_timeout, remaining),
                sock=sock,
            )
            if show:
                node["character_name"] = show.get("character_name", "")
                node["performer_name"] = show.get("performer_name", "")

    finally:
        sock.close()
    return node_list


# ======================================================================
#  NODE OUTPUT PARSING
# ======================================================================

def _match_output_type(display_name, output_types):
    key = display_name.strip().lower().replace(" ", "_")
    aliases = {
        "off": "none",
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
    caps_start = -1
    for idx, part in enumerate(parts):
        if part == NODE_CAPS_PREFIX_RADIUS:
            caps_start = idx
            break
        if part.endswith(" " + NODE_CAPS_PREFIX_RADIUS):
            caps_start = idx
            break
        if part.endswith(NODE_CAPS_PREFIX_RADIUS) and NODE_CAPS_PREFIX_RADIUS in part:
            caps_start = idx
            break
    if caps_start < 0:
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
        caps["show_info"] = "S" in features
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
        return True
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
            caps["show_info"] = "S" in features
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
        match = re.fullmatch(r"(\d+):(\d+):(\d+)(?::(\d+))?", part)
        if not match:
            continue
        port_index, type_id, universe, virtual_text = match.groups()
        port_index = int(port_index)
        type_id = int(type_id)
        universe = int(universe)
        if 0 <= type_id < len(type_keys):
            type_key = type_keys[type_id]
            entry = {
                "name": f"A{port_index}",
                "type": type_key,
                "universe": universe,
            }
            if virtual_text is not None:
                entry["virtual_pixels"] = int(virtual_text)
            outputs.append(entry)

    outputs.sort(key=lambda output: int(output["name"][1:]))
    return outputs


def _parse_long_name_outputs(long_name, universes, output_types):
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


def _output_port_index(name):
    text = str(name or "")
    if text.startswith("A") and text[1:].isdigit():
        return int(text[1:])
    return None


def _merge_output_configs(capability_outputs, fallback_outputs):
    """Merge capability tuples with Long Name (or prior) outputs.

    Firmware 3.12+ puts F:/B:/IP:/U: before per-output tuples so feature
    discovery survives the 64-byte Node Report limit, but two active outputs
    routinely truncate the trailing tuples. Capability fields win when both
    sources describe the same port; missing ports are kept from the fallback.
    """
    if not capability_outputs:
        return list(fallback_outputs or [])
    if not fallback_outputs:
        return list(capability_outputs)

    cap_by_name = {
        output["name"]: dict(output)
        for output in capability_outputs
        if output.get("name")
    }
    fallback_by_name = {
        output["name"]: dict(output)
        for output in fallback_outputs
        if output.get("name")
    }
    ordered_names = sorted(
        set(cap_by_name) | set(fallback_by_name),
        key=lambda name: (
            _output_port_index(name) is None,
            _output_port_index(name) if _output_port_index(name) is not None else name,
        ),
    )
    merged = []
    for name in ordered_names:
        cap_output = cap_by_name.get(name)
        fallback_output = fallback_by_name.get(name)
        if cap_output and fallback_output:
            merged_output = dict(fallback_output)
            if "universe" in cap_output:
                merged_output["universe"] = cap_output["universe"]
            if "virtual_pixels" in cap_output:
                merged_output["virtual_pixels"] = cap_output["virtual_pixels"]
                merged_output["type"] = cap_output["type"]
            elif cap_output.get("type") and cap_output.get("type") == fallback_output.get("type"):
                merged_output["type"] = cap_output["type"]
            merged.append(merged_output)
        elif cap_output:
            merged.append(cap_output)
        else:
            merged.append(fallback_output)
    return merged


def parse_node_outputs(long_name, universes, output_types, node_report="", type_keys=None):
    """Parse ArtPollReply output configuration.

    Preferred source is a versioned capability tag in Node Report. When that
    tag is truncated — common on firmware 3.12+ with two active outputs —
    missing ports are filled from the human-readable Long Name.
    """
    type_keys = type_keys or list(output_types.keys())
    capability_outputs = _parse_capability_outputs(node_report, type_keys)
    long_name_outputs = _parse_long_name_outputs(long_name, universes, output_types)
    return _merge_output_configs(capability_outputs, long_name_outputs)


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


def _send_udp_packet(ip, packet, source_ip=None, port=ARTNET_PORT):
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
                sock.sendto(bytes(packet), (ip, port))
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


def build_virtual_resolution_packet(virtual_counts):
    """Build an ArtVirtualResolution packet for the given virtual pixel counts."""
    num = len(virtual_counts)
    pkt = bytearray(13 + (num * 2))
    pkt[0:8] = ARTNET_HEADER
    struct.pack_into("<H", pkt, 8, ARTNET_OPCODE_VIRTUAL_RESOLUTION)
    struct.pack_into(">H", pkt, 10, ARTNET_VERSION)
    pkt[12] = num
    for i, count in enumerate(virtual_counts):
        struct.pack_into("<H", pkt, 13 + (i * 2), int(count) & 0xFFFF)
    return bytes(pkt)


def send_virtual_resolution(ip, virtual_counts, source_ip=None):
    """Send ArtVirtualResolution packet."""
    pkt = build_virtual_resolution_packet(virtual_counts)
    _send_udp_packet(ip, pkt, source_ip=source_ip)


def build_receive_config_packet(receive_mode, base_universe):
    """Build an ArtReceiveConfig packet."""
    if receive_mode not in ("split", "combined"):
        raise ValueError(f"invalid receive_mode: {receive_mode!r}")
    try:
        base_universe = int(base_universe)
    except (TypeError, ValueError) as exc:
        raise ValueError("base_universe must be an integer") from exc
    maximum = 32766 if receive_mode == "split" else 32767
    if base_universe < 0 or base_universe > maximum:
        raise ValueError(
            f"base_universe must be 0-{maximum} for {receive_mode} mode"
        )
    mode_id = 1 if receive_mode == "combined" else 0
    pkt = bytearray(15)
    pkt[0:8] = ARTNET_HEADER
    struct.pack_into("<H", pkt, 8, ARTNET_OPCODE_RECEIVE_CONFIG)
    struct.pack_into(">H", pkt, 10, ARTNET_VERSION)
    pkt[12] = mode_id
    struct.pack_into("<H", pkt, 13, base_universe)
    return bytes(pkt)


def send_receive_config(ip, receive_mode, base_universe, source_ip=None):
    """Send ArtReceiveConfig packet."""
    pkt = build_receive_config_packet(receive_mode, base_universe)
    _send_udp_packet(ip, pkt, source_ip=source_ip)


# ======================================================================
#  ART-NET OUTPUT CONFIG — ArtOutputConfig (opcode 0x8100)
# ======================================================================


def send_art_address(ip, short_name, source_ip=None, port=ARTNET_PORT):
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
    _send_udp_packet(ip, pkt, source_ip=source_ip, port=port)


# ======================================================================
#  ART-NET IP CONFIG — ArtIPConfig (opcode 0x8200)
# ======================================================================

def send_ip_config(ip, mode, static_ip=None, gateway=None, subnet=None, source_ip=None, port=ARTNET_PORT):
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
    _send_udp_packet(ip, pkt, source_ip=source_ip, port=port)


# ======================================================================
#  ART-NET SHOW INFO — ArtShowInfo (opcode 0x8210)
# ======================================================================

SHOW_INFO_FIELD_LEN = 64
SHOW_INFO_PACKET_LEN = 143
SHOW_INFO_MODE_READ = 0
SHOW_INFO_MODE_WRITE = 1
SHOW_INFO_MODE_RESPONSE = 2


def _encode_show_info_field(value):
    return str(value or "").encode("utf-8", errors="replace")[:SHOW_INFO_FIELD_LEN]


def build_show_info_packet(mode, character_name="", performer_name=""):
    char_bytes = _encode_show_info_field(character_name)
    perf_bytes = _encode_show_info_field(performer_name)
    pkt = bytearray(SHOW_INFO_PACKET_LEN)
    pkt[0:8] = ARTNET_HEADER
    struct.pack_into("<H", pkt, 8, ARTNET_OPCODE_SHOW_INFO)
    struct.pack_into(">H", pkt, 10, ARTNET_VERSION)
    pkt[12] = mode & 0xFF
    pkt[13] = len(char_bytes)
    pkt[14:14 + SHOW_INFO_FIELD_LEN] = char_bytes.ljust(SHOW_INFO_FIELD_LEN, b"\x00")
    pkt[78] = len(perf_bytes)
    pkt[79:79 + SHOW_INFO_FIELD_LEN] = perf_bytes.ljust(SHOW_INFO_FIELD_LEN, b"\x00")
    return bytes(pkt)


def parse_show_info_packet(raw):
    if len(raw) < SHOW_INFO_PACKET_LEN or raw[:8] != ARTNET_HEADER:
        return None
    if struct.unpack("<H", raw[8:10])[0] != ARTNET_OPCODE_SHOW_INFO:
        return None
    char_len = min(raw[13], SHOW_INFO_FIELD_LEN)
    perf_len = min(raw[78], SHOW_INFO_FIELD_LEN)
    return {
        "mode": raw[12],
        "character_name": raw[14:14 + char_len].decode("utf-8", errors="replace"),
        "performer_name": raw[79:79 + perf_len].decode("utf-8", errors="replace"),
    }


def send_show_info(ip, character_name="", performer_name="", source_ip=None, port=ARTNET_PORT):
    pkt = build_show_info_packet(
        SHOW_INFO_MODE_WRITE,
        character_name=character_name,
        performer_name=performer_name,
    )
    _send_udp_packet(ip, pkt, source_ip=source_ip, port=port)


def _normalize_show_info_compare(value):
    return str(value or "").strip()[:SHOW_INFO_FIELD_LEN]


def sync_show_info_to_device(
    ip,
    character_name="",
    performer_name="",
    source_ip=None,
    timeout=0.5,
    port=ARTNET_PORT,
):
    """Write show info and verify the receiver stored the expected values."""
    send_show_info(
        ip,
        character_name=character_name,
        performer_name=performer_name,
        source_ip=source_ip,
        port=port,
    )
    result = query_show_info(ip, timeout=timeout, source_ip=source_ip, port=port)
    if not result:
        return False, "receiver did not respond to show info read"
    expected_char = _normalize_show_info_compare(character_name)
    expected_perf = _normalize_show_info_compare(performer_name)
    actual_char = _normalize_show_info_compare(result.get("character_name"))
    actual_perf = _normalize_show_info_compare(result.get("performer_name"))
    if actual_char != expected_char or actual_perf != expected_perf:
        return False, "receiver did not confirm show info save"
    return True, ""


def _bind_artnet_query_socket(source_ip=None, port=ARTNET_PORT):
    """Bind a UDP socket for Art-Net request/response pairs.

    Receivers reply to UDP 6454 (controller port), not the ephemeral source port.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    bind_addrs = []
    if source_ip:
        bind_addrs.append((source_ip, port))
    bind_addrs.append(("", port))
    for addr in bind_addrs:
        try:
            sock.bind(addr)
            return sock
        except OSError:
            continue
    sock.close()
    raise OSError("unable to bind Art-Net query socket")


_management_request_id_lock = threading.Lock()


def _new_management_request_id_seed():
    return secrets.randbelow(0x10000)


_management_request_id = _new_management_request_id_seed()
_management_request_pid = os.getpid()


@dataclass(frozen=True)
class PrimusManagementResult:
    ip: str
    request_id: int
    operation: int
    payload: bytes
    reply: object
    config: object = None


class PrimusManagementError(Exception):
    """Base class for acknowledged Primus management transport failures."""


class PrimusManagementTimeout(PrimusManagementError):
    pass


class PrimusManagementProtocolError(PrimusManagementError):
    pass


class PrimusManagementNack(PrimusManagementError):
    def __init__(self, ip, operation, request_id, error_code, message=None):
        self.ip = ip
        self.operation = int(operation)
        self.request_id = int(request_id)
        self.error_code = ErrorCode(error_code)
        super().__init__(
            message
            or (
                f"Primus management request {self.operation:#04x} "
                f"to {self.ip} failed with {self.error_code.name}"
            )
        )


class PrimusManagementMalformedPacket(PrimusManagementNack):
    pass


class PrimusManagementUnsupportedVersion(PrimusManagementNack):
    pass


class PrimusManagementUnsupportedOperation(PrimusManagementNack):
    pass


class PrimusManagementInvalidPayload(PrimusManagementNack):
    pass


class PrimusManagementLocked(PrimusManagementNack):
    pass


class PrimusManagementOutOfRange(PrimusManagementNack):
    pass


class PrimusManagementNotAvailable(PrimusManagementNack):
    pass


class PrimusManagementInternalError(PrimusManagementNack):
    pass


_MANAGEMENT_NACK_EXCEPTIONS = {
    ErrorCode.MALFORMED_PACKET: PrimusManagementMalformedPacket,
    ErrorCode.UNSUPPORTED_VERSION: PrimusManagementUnsupportedVersion,
    ErrorCode.UNSUPPORTED_OPERATION: PrimusManagementUnsupportedOperation,
    ErrorCode.INVALID_PAYLOAD: PrimusManagementInvalidPayload,
    ErrorCode.LOCKED: PrimusManagementLocked,
    ErrorCode.OUT_OF_RANGE: PrimusManagementOutOfRange,
    ErrorCode.NOT_AVAILABLE: PrimusManagementNotAvailable,
    ErrorCode.INTERNAL_ERROR: PrimusManagementInternalError,
}


def _next_management_request_id():
    global _management_request_id, _management_request_pid
    with _management_request_id_lock:
        current_pid = os.getpid()
        if current_pid != _management_request_pid:
            _management_request_id = _new_management_request_id_seed()
            _management_request_pid = current_pid
        request_id = _management_request_id
        _management_request_id = (_management_request_id + 1) & 0xFFFF
    return request_id


def _normalize_management_target(ip):
    return str(ipaddress.IPv4Address(ip))


def _raise_management_nack(ip, operation, request_id, error_code):
    error_code = ErrorCode(error_code)
    exception_type = _MANAGEMENT_NACK_EXCEPTIONS.get(error_code, PrimusManagementNack)
    raise exception_type(ip, operation, request_id, error_code)


def _decode_management_reply(ip, operation, request_id, packet):
    if packet.opcode != MANAGEMENT_REPLY_OPCODE:
        raise PrimusManagementProtocolError(
            f"unexpected Primus management opcode {packet.opcode:#06x} from {ip}"
        )
    if packet.protocol_version != MANAGEMENT_PROTOCOL_VERSION:
        raise PrimusManagementProtocolError(
            f"unexpected Primus management protocol version {packet.protocol_version} from {ip}"
        )
    if packet.request_id != request_id:
        raise PrimusManagementProtocolError(
            f"unexpected Primus request_id {packet.request_id} from {ip}"
        )
    if packet.operation != int(operation):
        raise PrimusManagementProtocolError(
            f"unexpected Primus operation {packet.operation:#04x} from {ip}"
        )

    if packet.status == int(ReplyStatus.ACK):
        if packet.error != int(ErrorCode.NONE):
            raise PrimusManagementProtocolError(
                f"Primus management ACK from {ip} carried error {packet.error}"
            )
        config = None
        if int(operation) == int(Operation.GET_CONFIG):
            try:
                config = unpack_config(packet.payload)
            except ValueError as exc:
                raise PrimusManagementProtocolError(
                    f"invalid Primus GET_CONFIG payload from {ip}: {exc}"
                ) from exc
        return PrimusManagementResult(
            ip=ip,
            request_id=request_id,
            operation=int(operation),
            payload=packet.payload,
            reply=packet,
            config=config,
        )

    if packet.status == int(ReplyStatus.NACK):
        if packet.error == int(ErrorCode.NONE):
            raise PrimusManagementProtocolError(
                f"Primus management NACK from {ip} omitted an error code"
            )
        _raise_management_nack(ip, operation, request_id, packet.error)

    raise PrimusManagementProtocolError(
        f"unknown Primus management status {packet.status} from {ip}"
    )


def request_primus_management(
    ip,
    operation,
    payload=b"",
    *,
    source_ip=None,
    timeout=0.35,
    retries=2,
    request_id=None,
):
    with _artnet_query_lock:
        return _request_primus_management_unlocked(
            ip,
            operation,
            payload,
            source_ip=source_ip,
            timeout=timeout,
            retries=retries,
            request_id=request_id,
        )


def _request_primus_management_unlocked(
    ip,
    operation,
    payload=b"",
    *,
    source_ip=None,
    timeout=0.35,
    retries=2,
    request_id=None,
):
    ip = _normalize_management_target(ip)
    operation = Operation(operation)
    timeout = float(timeout)
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    retries = int(retries)
    if retries < 0:
        raise ValueError("retries must be non-negative")
    if request_id is None:
        request_id = _next_management_request_id()
    else:
        request_id = int(request_id)
        if not 0 <= request_id <= 0xFFFF:
            raise ValueError("request_id must fit uint16")

    packet = build_management_request(request_id, operation, payload)
    prefer_unbound = False
    attempts = retries + 1
    receive_timeout = min(0.1, max(0.05, timeout))
    for attempt_index in range(attempts):
        bind_attempts = [False] if (prefer_unbound or not source_ip) else [True, False]
        last_send_error = None
        sent = False
        for bind_source in bind_attempts:
            sock = _bind_artnet_query_socket(source_ip if bind_source else None)
            try:
                sock.settimeout(receive_timeout)
                try:
                    sock.sendto(packet, (ip, ARTNET_PORT))
                except OSError as exc:
                    last_send_error = exc
                    if bind_source and source_ip and _udp_route_retryable(exc):
                        prefer_unbound = True
                        continue
                    raise
                sent = True
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    try:
                        raw, addr = sock.recvfrom(512)
                    except socket.timeout:
                        continue
                    if addr[0] != ip:
                        continue
                    try:
                        reply = parse_management_packet(raw)
                    except ValueError:
                        continue
                    if reply.opcode != MANAGEMENT_REPLY_OPCODE:
                        continue
                    if reply.request_id != request_id:
                        continue
                    if reply.operation != int(operation):
                        continue
                    return _decode_management_reply(ip, operation, request_id, reply)
            finally:
                sock.close()
            break
        if sent:
            continue
        if last_send_error is not None and attempt_index == attempts - 1:
            raise last_send_error

    raise PrimusManagementTimeout(
        f"timed out waiting for Primus management reply from {ip} "
        f"for operation {int(operation):#04x} after {attempts} attempt(s)"
    )


def get_primus_config(ip, *, source_ip=None, timeout=0.35, retries=2, request_id=None):
    return request_primus_management(
        ip,
        Operation.GET_CONFIG,
        source_ip=source_ip,
        timeout=timeout,
        retries=retries,
        request_id=request_id,
    )


def set_primus_output_descriptors(
    ip,
    descriptors,
    *,
    source_ip=None,
    timeout=0.35,
    retries=2,
    request_id=None,
):
    return request_primus_management(
        ip,
        Operation.SET_OUTPUT_DESCRIPTORS,
        pack_output_descriptors(descriptors),
        source_ip=source_ip,
        timeout=timeout,
        retries=retries,
        request_id=request_id,
    )


def set_primus_telemetry_target(
    ip,
    address,
    *,
    source_ip=None,
    timeout=0.35,
    retries=2,
    request_id=None,
):
    return request_primus_management(
        ip,
        Operation.SET_TELEMETRY_TARGET,
        pack_telemetry_target(address),
        source_ip=source_ip,
        timeout=timeout,
        retries=retries,
        request_id=request_id,
    )


def set_primus_operating_mode(
    ip,
    mode,
    *,
    source_ip=None,
    timeout=0.35,
    retries=2,
    request_id=None,
):
    return request_primus_management(
        ip,
        Operation.SET_OPERATING_MODE,
        pack_operating_mode(mode),
        source_ip=source_ip,
        timeout=timeout,
        retries=retries,
        request_id=request_id,
    )


def set_primus_receive_config(
    ip,
    mode,
    base_universe,
    *,
    source_ip=None,
    timeout=0.35,
    retries=2,
    request_id=None,
):
    return request_primus_management(
        ip,
        Operation.SET_RECEIVE_CONFIG,
        pack_receive_config(mode, base_universe),
        source_ip=source_ip,
        timeout=timeout,
        retries=retries,
        request_id=request_id,
    )


def set_primus_ip_config(
    ip,
    mode,
    static_ip="0.0.0.0",
    gateway="0.0.0.0",
    subnet="0.0.0.0",
    *,
    source_ip=None,
    timeout=0.35,
    retries=2,
    request_id=None,
):
    return request_primus_management(
        ip,
        Operation.SET_IP_CONFIG,
        pack_ip_config(mode, static_ip, gateway, subnet),
        source_ip=source_ip,
        timeout=timeout,
        retries=retries,
        request_id=request_id,
    )


def set_primus_identity(
    ip,
    technical_name,
    character_name,
    performer_name,
    *,
    source_ip=None,
    timeout=0.35,
    retries=2,
    request_id=None,
):
    return request_primus_management(
        ip,
        Operation.SET_IDENTITY,
        pack_identity(technical_name, character_name, performer_name),
        source_ip=source_ip,
        timeout=timeout,
        retries=retries,
        request_id=request_id,
    )


def unlock_primus_boot_window(
    ip,
    *,
    source_ip=None,
    timeout=0.35,
    retries=2,
    request_id=None,
):
    return request_primus_management(
        ip,
        Operation.BOOT_WINDOW_UNLOCK,
        source_ip=source_ip,
        timeout=timeout,
        retries=retries,
        request_id=request_id,
    )


def query_node_short_name(ip, timeout=0.5, source_ip=None, port=ARTNET_PORT):
    with _artnet_query_lock:
        return _query_node_short_name_unlocked(
            ip, timeout=timeout, source_ip=source_ip, port=port)


def _query_node_short_name_unlocked(ip, timeout=0.5, source_ip=None, port=ARTNET_PORT):
    """Read the short name advertised by a single receiver."""
    sock = _bind_artnet_query_socket(source_ip=source_ip, port=port)
    recv_timeout = min(0.25, max(0.05, timeout))
    sock.settimeout(recv_timeout)
    try:
        poll = bytearray()
        poll += ARTNET_HEADER
        poll += struct.pack("<H", ARTNET_OPCODE_POLL)
        poll += struct.pack(">H", ARTNET_VERSION)
        poll += bytes([0x00, 0x00])
        sock.sendto(bytes(poll), (ip, port))

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw, addr = sock.recvfrom(600)
            except socket.timeout:
                continue
            if addr[0] != ip:
                continue
            if len(raw) < 44 or raw[:8] != ARTNET_HEADER:
                continue
            opcode = struct.unpack("<H", raw[8:10])[0]
            if opcode != ARTNET_OPCODE_POLLREPLY:
                continue
            return raw[26:44].split(b"\x00")[0].decode("ascii", errors="replace")
    finally:
        sock.close()
    return None


def sync_device_name_to_receiver(ip, short_name, source_ip=None, timeout=1.5, port=ARTNET_PORT):
    """Send ArtAddress and verify the receiver advertised the new short name."""
    send_art_address(ip, short_name, source_ip=source_ip, port=port)
    expected = str(short_name or "").strip()[:17]
    # Radius nodes may still be finishing NVS/display updates when the first
    # ArtPollReply arrives; retry briefly before reporting failure.
    time.sleep(0.08)
    deadline = time.monotonic() + max(0.5, timeout)
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        actual = query_node_short_name(
            ip,
            timeout=min(0.5, remaining),
            source_ip=source_ip,
            port=port,
        )
        if actual and actual.strip()[:17] == expected:
            return True, ""
        time.sleep(0.08)
    return False, "receiver did not confirm name save"


def query_show_info(ip, timeout=0.35, sock=None, source_ip=None, port=ARTNET_PORT):
    if sock is not None:
        return _query_show_info_unlocked(
            ip, timeout=timeout, sock=sock, source_ip=source_ip, port=port)
    with _artnet_query_lock:
        return _query_show_info_unlocked(
            ip, timeout=timeout, source_ip=source_ip, port=port)


def _query_show_info_unlocked(ip, timeout=0.35, sock=None, source_ip=None, port=ARTNET_PORT):
    """Read character/performer strings stored on a receiver."""
    owns_sock = sock is None
    if owns_sock:
        sock = _bind_artnet_query_socket(source_ip=source_ip, port=port)
        sock.settimeout(max(0.05, timeout))
    else:
        sock.settimeout(max(0.05, timeout))

    try:
        pkt = build_show_info_packet(SHOW_INFO_MODE_READ)
        sock.sendto(pkt, (ip, port))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw, addr = sock.recvfrom(512)
            except socket.timeout:
                continue
            if addr[0] != ip:
                continue
            parsed = parse_show_info_packet(raw)
            if parsed and parsed.get("mode") == SHOW_INFO_MODE_RESPONSE:
                return parsed
    finally:
        if owns_sock:
            sock.close()
    return None


# ======================================================================
#  AUDIO COMMAND — ArtAudioCmd (opcode 0x8300)
# ======================================================================

def send_audio_cmd(ip, cmd, filename="", volume=100, duration=0, source_ip=None):
    name_bytes = filename.encode("ascii", errors="replace")[:32] + b'\x00'
    if duration and duration > 0:
        name_bytes += struct.pack("<H", min(int(duration), 65535))
    pkt = bytearray(14 + len(name_bytes))
    pkt[0:8] = ARTNET_HEADER
    struct.pack_into("<H", pkt, 8, ARTNET_OPCODE_AUDIO_CMD)
    struct.pack_into(">H", pkt, 10, ARTNET_VERSION)
    pkt[12] = cmd & 0xFF
    pkt[13] = max(0, min(100, volume)) & 0xFF
    pkt[14:14 + len(name_bytes)] = name_bytes
    _send_udp_packet(ip, pkt, source_ip=source_ip, port=RADIUS_ARTNET_PORT)
    cmd_name = _AUDIO_CMD_NAMES.get(cmd, str(cmd))
    dur_str = f" [{duration}s]" if duration else ""
    file_str = f" \"{filename}\"" if filename else ""
    netlog.log("OUT", "audio_cmd",
               f"AudioCmd {cmd_name}{file_str} vol={volume}{dur_str} → {ip}")


# ======================================================================
#  FTP CONTROL — ArtFtpCmd (opcode 0x8301)
# ======================================================================

def send_ftp_cmd(ip, start, source_ip=None):
    pkt = bytearray(13)
    pkt[0:8] = ARTNET_HEADER
    struct.pack_into("<H", pkt, 8, ARTNET_OPCODE_FTP_CMD)
    struct.pack_into(">H", pkt, 10, ARTNET_VERSION)
    pkt[12] = 1 if start else 0
    _send_udp_packet(ip, pkt, source_ip=source_ip, port=RADIUS_ARTNET_PORT)
    netlog.log("OUT", "ftp_cmd", f"FTP {'start' if start else 'stop'} → {ip}")


def _osc_pad(data):
    """Null-pad to a 4-byte boundary (OSC spec: 1-4 trailing nulls)."""
    return data + b"\x00" * (4 - len(data) % 4)


def send_osc_cue(ip, number, source_ip=None):
    """Fire a device cue over OSC (/cue/N) — the same path an external OSC
    controller uses, so it tests the device's boot-loaded cue map directly."""
    address = f"/cue/{int(number)}".encode("ascii")
    packet = _osc_pad(address) + _osc_pad(b",")
    _send_udp_packet(ip, packet, source_ip=source_ip, port=RADIUS_OSC_PORT)
    netlog.log("OUT", "osc_cmd", f"OSC /cue/{int(number)} → {ip}")


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
    parts = line.split(None, 8)
    if len(parts) < 9:
        return None
    try:
        size = int(parts[4])
    except ValueError:
        size = 0
    return {"name": parts[8], "is_dir": parts[0].startswith("d"), "size": size}


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
