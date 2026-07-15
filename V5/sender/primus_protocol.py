"""Primus V5 implementation of the compatible management and unified-status wire contract.

This module deliberately has no sender runtime dependencies.  It is the
executable reference for firmware packet layouts used before the HTTP/API layer
is taught to consume the protocol.
"""

from dataclasses import dataclass
from enum import IntEnum
import binascii
import ipaddress
import struct


ARTNET_HEADER = b"Art-Net\x00"
ARTNET_VERSION = 14
MANAGEMENT_REQUEST_OPCODE = 0x8140
MANAGEMENT_REPLY_OPCODE = 0x8141
MANAGEMENT_PROTOCOL_VERSION = 1
MANAGEMENT_HEADER_SIZE = 20
OUTPUT_DESCRIPTOR_SIZE = 12
OUTPUT_SLOT_COUNT = 2
OUTPUT_DESCRIPTOR_STORAGE_SCHEMA = 1
OUTPUT_DESCRIPTOR_BLOB_SIZE = 28
STATUS_MAGIC = b"PST"
STATUS_PROTOCOL_VERSION = 1
STATUS_PACKET_SIZE = 28

MAX_PHYSICAL_PIXELS = 170
MAX_COMBINED_VIRTUAL_PIXELS = 170
TECHNICAL_NAME_MAX_BYTES = 17
SHOW_NAME_MAX_BYTES = 64


class Operation(IntEnum):
    GET_CONFIG = 0x01
    SET_OUTPUT_DESCRIPTORS = 0x10
    SET_TELEMETRY_TARGET = 0x11
    SET_OPERATING_MODE = 0x12
    SET_RECEIVE_CONFIG = 0x13
    SET_IP_CONFIG = 0x14
    SET_IDENTITY = 0x15
    BOOT_WINDOW_UNLOCK = 0x16


class ReplyStatus(IntEnum):
    ACK = 0
    NACK = 1


class ErrorCode(IntEnum):
    NONE = 0
    MALFORMED_PACKET = 1
    UNSUPPORTED_VERSION = 2
    UNSUPPORTED_OPERATION = 3
    INVALID_PAYLOAD = 4
    LOCKED = 5
    OUT_OF_RANGE = 6
    NOT_AVAILABLE = 7
    INTERNAL_ERROR = 8


class Layout(IntEnum):
    OFF = 0
    LINEAR = 1
    GRID = 2


class TraversalAxis(IntEnum):
    ROW_MAJOR = 0
    COLUMN_MAJOR = 1


class ScanPattern(IntEnum):
    PROGRESSIVE = 0
    SERPENTINE = 1


class StartCorner(IntEnum):
    TOP_LEFT = 0
    TOP_RIGHT = 1
    BOTTOM_LEFT = 2
    BOTTOM_RIGHT = 3


class OperatingMode(IntEnum):
    PROTOTYPE = 0
    PRODUCTION = 1


class ReceiveMode(IntEnum):
    SPLIT = 0
    COMBINED = 1


class IpMode(IntEnum):
    DHCP = 0
    STATIC = 1


class BatteryMode(IntEnum):
    BATTERY = 0
    CHARGING = 1
    PLUGGED = 2
    SWITCH_OFF = 3
    FAULT = 4
    UNAVAILABLE = 5


STATUS_FLAG_WIFI_CONNECTED = 1 << 0
STATUS_FLAG_STATIC_IP = 1 << 1
STATUS_FLAG_OUTPUT_POWER = 1 << 2
STATUS_FLAG_TEST_ACTIVE = 1 << 3
STATUS_FLAG_TELEMETRY_CONFIGURED = 1 << 4
STATUS_FLAG_PRODUCTION = 1 << 5
STATUS_FLAG_UNLOCK_WINDOW_OPEN = 1 << 6
STATUS_FLAG_BATTERY_VALID = 1 << 7

_MANAGEMENT_SUFFIX = struct.Struct(">HBBHHBB")
_OUTPUT_DESCRIPTOR = struct.Struct(">BBHBBBBBBH")
_CONFIG_PREFIX = struct.Struct(">BBBBHBBH4sB4s4s4s")
_STATUS = struct.Struct(">3sBHIHHHbBBBBBHBBH")


@dataclass(frozen=True)
class ManagementPacket:
    opcode: int
    protocol_version: int
    operation: int
    request_id: int
    payload: bytes
    status: int
    error: int


@dataclass(frozen=True)
class OutputDescriptor:
    enabled: bool
    physical_pixels: int
    layout: Layout
    rows: int
    columns: int
    traversal_axis: TraversalAxis
    scan_pattern: ScanPattern
    start_corner: StartCorner
    virtual_pixels: int

    def validate(self):
        if not self.enabled:
            if (
                self.physical_pixels != 0
                or self.layout != Layout.OFF
                or self.rows != 0
                or self.columns != 0
                or self.virtual_pixels != 0
                or self.traversal_axis != TraversalAxis.ROW_MAJOR
                or self.scan_pattern != ScanPattern.PROGRESSIVE
                or self.start_corner != StartCorner.TOP_LEFT
            ):
                raise ValueError("disabled descriptors must use the canonical Off shape")
            return

        if not 1 <= self.physical_pixels <= MAX_PHYSICAL_PIXELS:
            raise ValueError("physical_pixels must be between 1 and 170")
        if not 1 <= self.virtual_pixels <= self.physical_pixels:
            raise ValueError("virtual_pixels must be between 1 and physical_pixels")
        if self.layout == Layout.LINEAR:
            if self.rows != 0 or self.columns != 0:
                raise ValueError("linear descriptors must have zero rows and columns")
        elif self.layout == Layout.GRID:
            if self.rows < 1 or self.columns < 1:
                raise ValueError("grid rows and columns must be positive")
            if self.rows * self.columns != self.physical_pixels:
                raise ValueError("grid rows * columns must equal physical_pixels")
        else:
            raise ValueError("enabled descriptors must be linear or grid")

    def pack(self):
        self.validate()
        return _OUTPUT_DESCRIPTOR.pack(
            int(self.enabled),
            int(self.layout),
            self.physical_pixels,
            self.rows,
            self.columns,
            int(self.traversal_axis),
            int(self.scan_pattern),
            int(self.start_corner),
            0,
            self.virtual_pixels,
        )

    @classmethod
    def unpack(cls, data):
        if len(data) != OUTPUT_DESCRIPTOR_SIZE:
            raise ValueError("output descriptor must be exactly 12 bytes")
        (
            enabled,
            layout,
            physical,
            rows,
            columns,
            traversal,
            scan,
            corner,
            reserved,
            virtual,
        ) = _OUTPUT_DESCRIPTOR.unpack(data)
        if reserved != 0:
            raise ValueError("output descriptor reserved byte must be zero")
        try:
            descriptor = cls(
                bool(enabled),
                physical,
                Layout(layout),
                rows,
                columns,
                TraversalAxis(traversal),
                ScanPattern(scan),
                StartCorner(corner),
                virtual,
            )
        except ValueError as exc:
            raise ValueError("invalid output descriptor enum") from exc
        if enabled not in (0, 1):
            raise ValueError("enabled must be zero or one")
        descriptor.validate()
        return descriptor


OFF_DESCRIPTOR = OutputDescriptor(
    False,
    0,
    Layout.OFF,
    0,
    0,
    TraversalAxis.ROW_MAJOR,
    ScanPattern.PROGRESSIVE,
    StartCorner.TOP_LEFT,
    0,
)

_LEGACY_OUTPUT_DEFAULTS = {
    0: OFF_DESCRIPTOR,
    1: OutputDescriptor(
        True, 30, Layout.LINEAR, 0, 0,
        TraversalAxis.ROW_MAJOR, ScanPattern.PROGRESSIVE,
        StartCorner.TOP_LEFT, 30,
    ),
    2: OutputDescriptor(
        True, 72, Layout.LINEAR, 0, 0,
        TraversalAxis.ROW_MAJOR, ScanPattern.PROGRESSIVE,
        StartCorner.TOP_LEFT, 72,
    ),
    3: OutputDescriptor(
        True, 64, Layout.GRID, 8, 8,
        TraversalAxis.ROW_MAJOR, ScanPattern.SERPENTINE,
        StartCorner.TOP_LEFT, 64,
    ),
    4: OutputDescriptor(
        True, 32, Layout.GRID, 4, 8,
        TraversalAxis.ROW_MAJOR, ScanPattern.SERPENTINE,
        StartCorner.TOP_LEFT, 1,
    ),
    5: OutputDescriptor(
        True, 122, Layout.LINEAR, 0, 0,
        TraversalAxis.ROW_MAJOR, ScanPattern.PROGRESSIVE,
        StartCorner.TOP_LEFT, 122,
    ),
}


def descriptor_from_legacy(output_type, virtual_pixels=None):
    """Idempotently translate old ``otype*``/``vpx*`` values."""
    try:
        base = _LEGACY_OUTPUT_DEFAULTS[int(output_type)]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("unknown legacy output type") from exc
    if not base.enabled:
        return base
    virtual = base.virtual_pixels if virtual_pixels in (None, 0) else int(virtual_pixels)
    virtual = max(1, min(virtual, base.physical_pixels))
    return OutputDescriptor(
        base.enabled,
        base.physical_pixels,
        base.layout,
        base.rows,
        base.columns,
        base.traversal_axis,
        base.scan_pattern,
        base.start_corner,
        virtual,
    )


def pack_output_descriptors(descriptors):
    descriptors = tuple(descriptors)
    if len(descriptors) != OUTPUT_SLOT_COUNT:
        raise ValueError("exactly two output descriptors are required")
    return b"".join(descriptor.pack() for descriptor in descriptors)


def unpack_output_descriptors(data):
    if len(data) != OUTPUT_SLOT_COUNT * OUTPUT_DESCRIPTOR_SIZE:
        raise ValueError("two packed output descriptors must be exactly 24 bytes")
    return tuple(
        OutputDescriptor.unpack(data[offset:offset + OUTPUT_DESCRIPTOR_SIZE])
        for offset in range(0, len(data), OUTPUT_DESCRIPTOR_SIZE)
    )


def pack_output_descriptor_blob(descriptors):
    body = (
        bytes((OUTPUT_DESCRIPTOR_STORAGE_SCHEMA, OUTPUT_SLOT_COUNT))
        + pack_output_descriptors(descriptors)
    )
    checksum = binascii.crc_hqx(body, 0xFFFF)
    return body + struct.pack(">H", checksum)


def unpack_output_descriptor_blob(data):
    data = bytes(data)
    if len(data) != OUTPUT_DESCRIPTOR_BLOB_SIZE:
        raise ValueError("output descriptor blob must be exactly 28 bytes")
    if data[0] != OUTPUT_DESCRIPTOR_STORAGE_SCHEMA or data[1] != OUTPUT_SLOT_COUNT:
        raise ValueError("unsupported output descriptor blob schema")
    expected = struct.unpack_from(">H", data, OUTPUT_DESCRIPTOR_BLOB_SIZE - 2)[0]
    actual = binascii.crc_hqx(data[:-2], 0xFFFF)
    if actual != expected:
        raise ValueError("output descriptor blob checksum mismatch")
    return unpack_output_descriptors(data[2:-2])


def validate_receive_config(mode, descriptors):
    try:
        mode = ReceiveMode(mode)
    except ValueError as exc:
        raise ValueError("invalid receive mode") from exc
    descriptors = tuple(descriptors)
    for descriptor in descriptors:
        descriptor.validate()
    if (
        mode == ReceiveMode.COMBINED
        and sum(item.virtual_pixels for item in descriptors)
        > MAX_COMBINED_VIRTUAL_PIXELS
    ):
        raise ValueError("combined virtual pixel total exceeds 170")


def _validate_base_universe(mode, base_universe):
    mode = ReceiveMode(mode)
    base_universe = int(base_universe)
    maximum = 0x7FFE if mode == ReceiveMode.SPLIT else 0x7FFF
    if not 0 <= base_universe <= maximum:
        raise ValueError(
            f"base_universe must be between 0 and {maximum} for {mode.name.lower()}"
        )
    return mode, base_universe


def build_management_packet(
    opcode,
    request_id,
    operation,
    payload=b"",
    *,
    status=ReplyStatus.ACK,
    error=ErrorCode.NONE,
):
    if opcode not in (MANAGEMENT_REQUEST_OPCODE, MANAGEMENT_REPLY_OPCODE):
        raise ValueError("invalid Primus management opcode")
    payload = bytes(payload)
    if not 0 <= request_id <= 0xFFFF:
        raise ValueError("request_id must fit uint16")
    if len(payload) > 0xFFFF:
        raise ValueError("payload is too large")
    if opcode == MANAGEMENT_REQUEST_OPCODE and (
        int(status) != ReplyStatus.ACK or int(error) != ErrorCode.NONE
    ):
        raise ValueError("management requests must have zero status and error")
    return (
        ARTNET_HEADER
        + struct.pack("<H", opcode)
        + _MANAGEMENT_SUFFIX.pack(
            ARTNET_VERSION,
            MANAGEMENT_PROTOCOL_VERSION,
            int(operation),
            request_id,
            len(payload),
            int(status),
            int(error),
        )
        + payload
    )


def build_management_request(request_id, operation, payload=b""):
    return build_management_packet(
        MANAGEMENT_REQUEST_OPCODE, request_id, operation, payload
    )


def build_management_reply(
    request_id,
    operation,
    payload=b"",
    *,
    status=ReplyStatus.ACK,
    error=ErrorCode.NONE,
):
    return build_management_packet(
        MANAGEMENT_REPLY_OPCODE,
        request_id,
        operation,
        payload,
        status=status,
        error=error,
    )


def parse_management_packet(data):
    data = bytes(data)
    if len(data) < MANAGEMENT_HEADER_SIZE:
        raise ValueError("management packet is shorter than 20 bytes")
    if data[:8] != ARTNET_HEADER:
        raise ValueError("invalid Art-Net header")
    opcode = struct.unpack_from("<H", data, 8)[0]
    if opcode not in (MANAGEMENT_REQUEST_OPCODE, MANAGEMENT_REPLY_OPCODE):
        raise ValueError("not a Primus management packet")
    (
        artnet_version,
        protocol_version,
        operation,
        request_id,
        payload_length,
        status,
        error,
    ) = _MANAGEMENT_SUFFIX.unpack_from(data, 10)
    if artnet_version < ARTNET_VERSION:
        raise ValueError("unsupported Art-Net protocol version")
    if len(data) != MANAGEMENT_HEADER_SIZE + payload_length:
        raise ValueError("management payload length mismatch")
    if opcode == MANAGEMENT_REQUEST_OPCODE and (status != 0 or error != 0):
        raise ValueError("management request status and error must be zero")
    return ManagementPacket(
        opcode,
        protocol_version,
        operation,
        request_id,
        data[MANAGEMENT_HEADER_SIZE:],
        status,
        error,
    )


def _pack_name(value, max_bytes, label):
    raw = value.encode("utf-8")
    if b"\x00" in raw:
        raise ValueError(f"{label} cannot contain NUL")
    if len(raw) > max_bytes:
        raise ValueError(f"{label} exceeds {max_bytes} UTF-8 bytes")
    return bytes((len(raw),)) + raw


def _unpack_name(data, offset, max_bytes, label):
    if offset >= len(data):
        raise ValueError(f"missing {label} length")
    length = data[offset]
    offset += 1
    if length > max_bytes or offset + length > len(data):
        raise ValueError(f"invalid {label} length")
    try:
        value = data[offset:offset + length].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} is not UTF-8") from exc
    return value, offset + length


def pack_identity(technical_name, character_name, performer_name):
    return (
        _pack_name(technical_name, TECHNICAL_NAME_MAX_BYTES, "technical_name")
        + _pack_name(character_name, SHOW_NAME_MAX_BYTES, "character_name")
        + _pack_name(performer_name, SHOW_NAME_MAX_BYTES, "performer_name")
    )


def pack_telemetry_target(address):
    packed = _ip_bytes(address)
    if packed == b"\x00\x00\x00\x00":
        return packed
    if packed[0] == 0 or packed[0] >= 224:
        raise ValueError("telemetry target must be unicast IPv4 or 0.0.0.0")
    return packed


def pack_operating_mode(mode):
    return bytes((int(OperatingMode(mode)),))


def pack_receive_config(mode, base_universe):
    mode, base_universe = _validate_base_universe(mode, base_universe)
    return struct.pack(">BH", int(mode), base_universe)


def pack_ip_config(mode, ip="0.0.0.0", gateway="0.0.0.0", subnet="0.0.0.0"):
    mode = IpMode(mode)
    return struct.pack(
        ">B4s4s4s",
        int(mode),
        _ip_bytes(ip),
        _ip_bytes(gateway),
        _ip_bytes(subnet),
    )


def unpack_identity(data, offset=0):
    technical, offset = _unpack_name(
        data, offset, TECHNICAL_NAME_MAX_BYTES, "technical_name"
    )
    character, offset = _unpack_name(
        data, offset, SHOW_NAME_MAX_BYTES, "character_name"
    )
    performer, offset = _unpack_name(
        data, offset, SHOW_NAME_MAX_BYTES, "performer_name"
    )
    return (technical, character, performer), offset


@dataclass(frozen=True)
class DeviceConfig:
    operating_mode: OperatingMode
    unlock_window_open: bool
    unlock_remaining_seconds: int
    receive_mode: ReceiveMode
    base_universe: int
    telemetry_target: str
    ip_mode: IpMode
    ip: str
    gateway: str
    subnet: str
    outputs: tuple
    technical_name: str
    character_name: str
    performer_name: str


def _ip_bytes(value):
    return ipaddress.IPv4Address(value).packed


def pack_config(config):
    validate_receive_config(config.receive_mode, config.outputs)
    receive_mode, base_universe = _validate_base_universe(
        config.receive_mode, config.base_universe
    )
    if not 0 <= config.unlock_remaining_seconds <= 0xFFFF:
        raise ValueError("unlock_remaining_seconds must fit uint16")
    return (
        _CONFIG_PREFIX.pack(
            1,
            int(config.operating_mode),
            int(config.unlock_window_open),
            0,
            config.unlock_remaining_seconds,
            int(receive_mode),
            0,
            base_universe,
            _ip_bytes(config.telemetry_target),
            int(config.ip_mode),
            _ip_bytes(config.ip),
            _ip_bytes(config.gateway),
            _ip_bytes(config.subnet),
        )
        + pack_output_descriptors(config.outputs)
        + pack_identity(
            config.technical_name,
            config.character_name,
            config.performer_name,
        )
    )


def unpack_config(data):
    data = bytes(data)
    minimum = _CONFIG_PREFIX.size + OUTPUT_SLOT_COUNT * OUTPUT_DESCRIPTOR_SIZE + 3
    if len(data) < minimum:
        raise ValueError("GET_CONFIG payload is truncated")
    (
        config_version,
        operating_mode,
        unlock_open,
        reserved,
        unlock_remaining,
        receive_mode,
        receive_reserved,
        base_universe,
        telemetry_target,
        ip_mode,
        ip,
        gateway,
        subnet,
    ) = _CONFIG_PREFIX.unpack_from(data)
    if config_version != 1 or reserved != 0 or receive_reserved != 0:
        raise ValueError("unsupported GET_CONFIG payload version")
    descriptor_start = _CONFIG_PREFIX.size
    descriptor_end = descriptor_start + OUTPUT_SLOT_COUNT * OUTPUT_DESCRIPTOR_SIZE
    outputs = unpack_output_descriptors(data[descriptor_start:descriptor_end])
    receive_mode, base_universe = _validate_base_universe(receive_mode, base_universe)
    validate_receive_config(receive_mode, outputs)
    identity, end = unpack_identity(data, descriptor_end)
    if end != len(data):
        raise ValueError("unexpected bytes after GET_CONFIG identity")
    try:
        return DeviceConfig(
            OperatingMode(operating_mode),
            bool(unlock_open),
            unlock_remaining,
            receive_mode,
            base_universe,
            str(ipaddress.IPv4Address(telemetry_target)),
            IpMode(ip_mode),
            str(ipaddress.IPv4Address(ip)),
            str(ipaddress.IPv4Address(gateway)),
            str(ipaddress.IPv4Address(subnet)),
            outputs,
            identity[0],
            identity[1],
            identity[2],
        )
    except ValueError as exc:
        raise ValueError("invalid GET_CONFIG enum") from exc


@dataclass(frozen=True)
class UnifiedStatus:
    sequence: int
    uptime_seconds: int
    flags: int
    rendered_fps_x10: int
    packet_rate_x10: int
    rssi_dbm: int
    firmware_major: int
    firmware_minor: int
    firmware_patch: int
    operating_mode: OperatingMode
    battery_mode: BatteryMode
    battery_mv: int
    battery_pct: int
    unlock_remaining_seconds: int


def pack_status(status):
    return _STATUS.pack(
        STATUS_MAGIC,
        STATUS_PROTOCOL_VERSION,
        status.sequence,
        status.uptime_seconds,
        status.flags,
        status.rendered_fps_x10,
        status.packet_rate_x10,
        status.rssi_dbm,
        status.firmware_major,
        status.firmware_minor,
        status.firmware_patch,
        int(status.operating_mode),
        int(status.battery_mode),
        status.battery_mv,
        status.battery_pct,
        status.unlock_remaining_seconds,
        0,
    )


def unpack_status(data):
    data = bytes(data)
    if len(data) != STATUS_PACKET_SIZE:
        raise ValueError("unified status packet must be exactly 28 bytes")
    values = _STATUS.unpack(data)
    if values[0] != STATUS_MAGIC or values[1] != STATUS_PROTOCOL_VERSION:
        raise ValueError("unsupported unified status packet")
    if values[16] != 0:
        raise ValueError("unified status reserved bytes must be zero")
    try:
        return UnifiedStatus(
            sequence=values[2],
            uptime_seconds=values[3],
            flags=values[4],
            rendered_fps_x10=values[5],
            packet_rate_x10=values[6],
            rssi_dbm=values[7],
            firmware_major=values[8],
            firmware_minor=values[9],
            firmware_patch=values[10],
            operating_mode=OperatingMode(values[11]),
            battery_mode=BatteryMode(values[12]),
            battery_mv=values[13],
            battery_pct=values[14],
            unlock_remaining_seconds=values[15],
        )
    except ValueError as exc:
        raise ValueError("invalid unified status enum") from exc
