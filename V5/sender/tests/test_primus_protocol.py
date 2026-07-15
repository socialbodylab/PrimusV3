"""Golden tests for the Primus firmware management/status contract."""

import binascii
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from primus_protocol import (
    BatteryMode,
    DeviceConfig,
    ErrorCode,
    IpMode,
    Layout,
    MANAGEMENT_REPLY_OPCODE,
    MANAGEMENT_REQUEST_OPCODE,
    OFF_DESCRIPTOR,
    OperatingMode,
    Operation,
    OutputDescriptor,
    ReceiveMode,
    ReplyStatus,
    ScanPattern,
    StartCorner,
    STATUS_FLAG_BATTERY_VALID,
    STATUS_FLAG_OUTPUT_POWER,
    STATUS_FLAG_PRODUCTION,
    STATUS_FLAG_TELEMETRY_CONFIGURED,
    STATUS_FLAG_WIFI_CONNECTED,
    TraversalAxis,
    UnifiedStatus,
    build_management_reply,
    build_management_request,
    descriptor_from_legacy,
    pack_config,
    pack_ip_config,
    pack_operating_mode,
    pack_output_descriptor_blob,
    pack_output_descriptors,
    pack_receive_config,
    pack_status,
    pack_telemetry_target,
    parse_management_packet,
    unpack_config,
    unpack_output_descriptor_blob,
    unpack_output_descriptors,
    unpack_status,
    validate_receive_config,
)


GRID = OutputDescriptor(
    True,
    32,
    Layout.GRID,
    4,
    8,
    TraversalAxis.ROW_MAJOR,
    ScanPattern.SERPENTINE,
    StartCorner.TOP_LEFT,
    1,
)


def _macro_value(text, name):
    match = re.search(
        rf"^#define\s+{re.escape(name)}\s+([^\s/]+)",
        text,
        re.MULTILINE,
    )
    if not match:
        raise AssertionError(name)
    return match.group(1)


def _parse_macro_int(text, name):
    return int(re.sub(r"[uUlL]+$", "", _macro_value(text, name)), 0)


@dataclass(frozen=True)
class ReplayCacheKeyModel:
    source_ip: tuple[int, int, int, int]
    request_id: int
    operation: int
    protocol_version: int
    declared_payload_len: int
    actual_payload_len: int
    payload: bytes
    request_status: int
    request_error: int


@dataclass(frozen=True)
class ReplayReplyModel:
    status: int
    error: int
    payload: bytes = b""


def _replay_key(
    source_ip,
    request_id,
    operation,
    protocol_version,
    payload=b"",
    *,
    declared_payload_len=None,
    request_status=0,
    request_error=0,
):
    payload = bytes(payload)
    if declared_payload_len is None:
        declared_payload_len = len(payload)
    return ReplayCacheKeyModel(
        tuple(source_ip),
        request_id,
        int(operation),
        protocol_version,
        declared_payload_len,
        len(payload),
        payload,
        request_status,
        request_error,
    )


class ReplayCacheModel:
    def __init__(self, size, ttl_ms):
        self.size = size
        self.ttl_ms = ttl_ms
        self.entries = [None] * size
        self.next_slot = 0

    def _fresh(self, entry, now_ms):
        return entry is not None and now_ms - entry["stored_at_ms"] <= self.ttl_ms

    def lookup(self, key, now_ms):
        for index, entry in enumerate(self.entries):
            if entry is None:
                continue
            if not self._fresh(entry, now_ms):
                self.entries[index] = None
                continue
            if entry["key"] == key:
                entry["stored_at_ms"] = now_ms
                return entry["reply"]
        return None

    def store(self, key, reply, now_ms):
        for index, entry in enumerate(self.entries):
            if entry is None or not self._fresh(entry, now_ms):
                self.entries[index] = {
                    "key": key,
                    "reply": reply,
                    "stored_at_ms": now_ms,
                }
                return index
        index = self.next_slot % self.size
        self.entries[index] = {
            "key": key,
            "reply": reply,
            "stored_at_ms": now_ms,
        }
        self.next_slot = (self.next_slot + 1) % self.size
        return index


class ManagementGoldenTests(unittest.TestCase):
    def test_get_config_request_exact_bytes(self):
        packet = build_management_request(0x1234, Operation.GET_CONFIG)
        self.assertEqual(
            packet,
            bytes.fromhex(
                "4172742d4e6574004081000e0101123400000000"
            ),
        )
        parsed = parse_management_packet(packet)
        self.assertEqual(parsed.opcode, MANAGEMENT_REQUEST_OPCODE)
        self.assertEqual(parsed.request_id, 0x1234)
        self.assertEqual(parsed.operation, Operation.GET_CONFIG)
        self.assertEqual(parsed.payload, b"")

    def test_locked_reply_exact_bytes(self):
        packet = build_management_reply(
            0x1234,
            Operation.SET_IP_CONFIG,
            status=ReplyStatus.NACK,
            error=ErrorCode.LOCKED,
        )
        self.assertEqual(
            packet,
            bytes.fromhex(
                "4172742d4e6574004181000e0114123400000105"
            ),
        )
        parsed = parse_management_packet(packet)
        self.assertEqual(parsed.opcode, MANAGEMENT_REPLY_OPCODE)
        self.assertEqual(parsed.status, ReplyStatus.NACK)
        self.assertEqual(parsed.error, ErrorCode.LOCKED)

    def test_request_rejects_nonzero_status(self):
        packet = bytearray(build_management_request(1, Operation.GET_CONFIG))
        packet[18] = 1
        with self.assertRaisesRegex(ValueError, "status"):
            parse_management_packet(packet)

    def test_payload_length_is_authoritative(self):
        packet = build_management_request(
            2, Operation.SET_TELEMETRY_TARGET, b"\xc0\xa8\x01\x32"
        )
        self.assertEqual(packet[16:18], b"\x00\x04")
        with self.assertRaisesRegex(ValueError, "length mismatch"):
            parse_management_packet(packet[:-1])

    def test_atomic_setter_payloads_have_fixed_byte_order(self):
        self.assertEqual(pack_telemetry_target("192.168.1.50"), b"\xc0\xa8\x01\x32")
        with self.assertRaisesRegex(ValueError, "unicast"):
            pack_telemetry_target("239.1.2.3")
        self.assertEqual(pack_operating_mode(OperatingMode.PRODUCTION), b"\x01")
        self.assertEqual(
            pack_receive_config(ReceiveMode.SPLIT, 0x1234),
            b"\x00\x12\x34",
        )
        with self.assertRaisesRegex(ValueError, "32766"):
            pack_receive_config(ReceiveMode.SPLIT, 32767)
        self.assertEqual(
            pack_receive_config(ReceiveMode.COMBINED, 32767),
            b"\x01\x7f\xff",
        )
        self.assertEqual(
            pack_ip_config(
                IpMode.STATIC,
                "192.168.1.50",
                "192.168.1.1",
                "255.255.255.0",
            ),
            bytes.fromhex("01c0a80132c0a80101ffffff00"),
        )


class OutputDescriptorTests(unittest.TestCase):
    def test_two_slot_descriptor_golden_bytes(self):
        packed = pack_output_descriptors((GRID, OFF_DESCRIPTOR))
        self.assertEqual(
            packed,
            bytes.fromhex(
                "010200200408000100000001"
                "000000000000000000000000"
            ),
        )
        self.assertEqual(unpack_output_descriptors(packed), (GRID, OFF_DESCRIPTOR))

    def test_supports_170_physical_pixels(self):
        descriptor = OutputDescriptor(
            True,
            170,
            Layout.LINEAR,
            0,
            0,
            TraversalAxis.COLUMN_MAJOR,
            ScanPattern.PROGRESSIVE,
            StartCorner.BOTTOM_RIGHT,
            170,
        )
        self.assertEqual(
            descriptor.pack(),
            bytes.fromhex("010100aa00000100030000aa"),
        )

    def test_rejects_invalid_grid_shape(self):
        descriptor = OutputDescriptor(
            True,
            32,
            Layout.GRID,
            8,
            8,
            TraversalAxis.ROW_MAJOR,
            ScanPattern.SERPENTINE,
            StartCorner.TOP_LEFT,
            1,
        )
        with self.assertRaisesRegex(ValueError, "rows \\* columns"):
            descriptor.validate()

    def test_combined_virtual_total_is_limited(self):
        large = OutputDescriptor(
            True,
            100,
            Layout.LINEAR,
            0,
            0,
            TraversalAxis.ROW_MAJOR,
            ScanPattern.PROGRESSIVE,
            StartCorner.TOP_LEFT,
            100,
        )
        with self.assertRaisesRegex(ValueError, "exceeds 170"):
            validate_receive_config(ReceiveMode.COMBINED, (large, large))
        validate_receive_config(ReceiveMode.SPLIT, (large, large))

    def test_legacy_migration_is_idempotent_and_clamps_virtual_pixels(self):
        migrated = descriptor_from_legacy(4, 999)
        self.assertEqual(migrated.physical_pixels, 32)
        self.assertEqual(migrated.virtual_pixels, 32)
        self.assertEqual(
            OutputDescriptor.unpack(migrated.pack()),
            migrated,
        )
        self.assertEqual(descriptor_from_legacy(0, 50), OFF_DESCRIPTOR)

    def test_atomic_descriptor_blob_exact_bytes_and_checksum(self):
        blob = pack_output_descriptor_blob((GRID, OFF_DESCRIPTOR))
        self.assertEqual(
            blob,
            bytes.fromhex(
                "0102"
                "010200200408000100000001"
                "000000000000000000000000"
                "f49a"
            ),
        )
        self.assertEqual(unpack_output_descriptor_blob(blob), (GRID, OFF_DESCRIPTOR))

        corrupt = bytearray(blob)
        corrupt[5] ^= 1
        with self.assertRaisesRegex(ValueError, "checksum"):
            unpack_output_descriptor_blob(corrupt)


class ConfigPayloadTests(unittest.TestCase):
    def test_get_config_round_trip_with_off_slot(self):
        config = DeviceConfig(
            operating_mode=OperatingMode.PRODUCTION,
            unlock_window_open=False,
            unlock_remaining_seconds=0,
            receive_mode=ReceiveMode.COMBINED,
            base_universe=27,
            telemetry_target="192.168.1.20",
            ip_mode=IpMode.DHCP,
            ip="0.0.0.0",
            gateway="0.0.0.0",
            subnet="0.0.0.0",
            outputs=(GRID, OFF_DESCRIPTOR),
            technical_name="Badge-A",
            character_name="Ariel",
            performer_name="Sam",
        )
        payload = pack_config(config)
        self.assertEqual(
            payload,
            bytes.fromhex(
                "0101000000000100001bc0a8011400000000000000000000000000"
                "010200200408000100000001000000000000000000000000"
                "0742616467652d4105417269656c0353616d"
            ),
        )
        self.assertEqual(unpack_config(payload), config)

    def test_pack_config_enforces_receive_mode_base_universe_boundaries(self):
        split_config = DeviceConfig(
            operating_mode=OperatingMode.PROTOTYPE,
            unlock_window_open=False,
            unlock_remaining_seconds=0,
            receive_mode=ReceiveMode.SPLIT,
            base_universe=32766,
            telemetry_target="0.0.0.0",
            ip_mode=IpMode.DHCP,
            ip="0.0.0.0",
            gateway="0.0.0.0",
            subnet="0.0.0.0",
            outputs=(GRID, OFF_DESCRIPTOR),
            technical_name="Badge-A",
            character_name="Ariel",
            performer_name="Sam",
        )
        combined_config = DeviceConfig(
            operating_mode=OperatingMode.PROTOTYPE,
            unlock_window_open=False,
            unlock_remaining_seconds=0,
            receive_mode=ReceiveMode.COMBINED,
            base_universe=32767,
            telemetry_target="0.0.0.0",
            ip_mode=IpMode.DHCP,
            ip="0.0.0.0",
            gateway="0.0.0.0",
            subnet="0.0.0.0",
            outputs=(GRID, OFF_DESCRIPTOR),
            technical_name="Badge-A",
            character_name="Ariel",
            performer_name="Sam",
        )
        self.assertEqual(unpack_config(pack_config(split_config)), split_config)
        self.assertEqual(unpack_config(pack_config(combined_config)), combined_config)

        with self.assertRaisesRegex(ValueError, "32766"):
            pack_config(
                DeviceConfig(
                    operating_mode=OperatingMode.PROTOTYPE,
                    unlock_window_open=False,
                    unlock_remaining_seconds=0,
                    receive_mode=ReceiveMode.SPLIT,
                    base_universe=32767,
                    telemetry_target="0.0.0.0",
                    ip_mode=IpMode.DHCP,
                    ip="0.0.0.0",
                    gateway="0.0.0.0",
                    subnet="0.0.0.0",
                    outputs=(GRID, OFF_DESCRIPTOR),
                    technical_name="Badge-A",
                    character_name="Ariel",
                    performer_name="Sam",
                )
            )

    def test_unpack_config_rejects_split_base_universe_above_boundary(self):
        config = DeviceConfig(
            operating_mode=OperatingMode.PRODUCTION,
            unlock_window_open=False,
            unlock_remaining_seconds=0,
            receive_mode=ReceiveMode.COMBINED,
            base_universe=32767,
            telemetry_target="0.0.0.0",
            ip_mode=IpMode.DHCP,
            ip="0.0.0.0",
            gateway="0.0.0.0",
            subnet="0.0.0.0",
            outputs=(GRID, OFF_DESCRIPTOR),
            technical_name="Badge-A",
            character_name="Ariel",
            performer_name="Sam",
        )
        payload = bytearray(pack_config(config))
        payload[6] = int(ReceiveMode.SPLIT)
        with self.assertRaisesRegex(ValueError, "32766"):
            unpack_config(payload)


class ManagementReplyReplayModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[3]
        config = (
            root / "V5" / "Arduino" / "primusV3_receiver" / "config.h"
        ).read_text(encoding="utf-8")
        cls.cache_size = _parse_macro_int(config, "MANAGEMENT_REPLY_CACHE_SIZE")
        cls.cache_ttl_ms = _parse_macro_int(config, "MANAGEMENT_REPLY_CACHE_TTL_MS")

    def test_cache_key_changes_when_identity_fields_change(self):
        base = _replay_key(
            (192, 168, 1, 10),
            0x1234,
            Operation.SET_OPERATING_MODE,
            1,
            pack_operating_mode(OperatingMode.PRODUCTION),
        )
        variants = [
            _replay_key(
                (192, 168, 1, 11),
                0x1234,
                Operation.SET_OPERATING_MODE,
                1,
                pack_operating_mode(OperatingMode.PRODUCTION),
            ),
            _replay_key(
                (192, 168, 1, 10),
                0x1235,
                Operation.SET_OPERATING_MODE,
                1,
                pack_operating_mode(OperatingMode.PRODUCTION),
            ),
            _replay_key(
                (192, 168, 1, 10),
                0x1234,
                Operation.SET_RECEIVE_CONFIG,
                1,
                pack_operating_mode(OperatingMode.PRODUCTION),
            ),
            _replay_key(
                (192, 168, 1, 10),
                0x1234,
                Operation.SET_OPERATING_MODE,
                2,
                pack_operating_mode(OperatingMode.PRODUCTION),
            ),
            _replay_key(
                (192, 168, 1, 10),
                0x1234,
                Operation.SET_OPERATING_MODE,
                1,
                b"",
                declared_payload_len=1,
            ),
            _replay_key(
                (192, 168, 1, 10),
                0x1234,
                Operation.SET_OPERATING_MODE,
                1,
                pack_operating_mode(OperatingMode.PROTOTYPE),
            ),
        ]
        for variant in variants:
            self.assertNotEqual(base, variant)

    def test_exact_duplicate_replays_ack_and_deterministic_nack(self):
        cache = ReplayCacheModel(self.cache_size, self.cache_ttl_ms)
        ack_key = _replay_key(
            (192, 168, 1, 50),
            0x4444,
            Operation.SET_IDENTITY,
            1,
            b"\x05Badge\x05Ariel\x03Sam",
        )
        ack_reply = ReplayReplyModel(ReplyStatus.ACK, ErrorCode.NONE)
        cache.store(ack_key, ack_reply, now_ms=100)
        self.assertEqual(cache.lookup(ack_key, now_ms=101), ack_reply)

        nack_key = _replay_key(
            (192, 168, 1, 50),
            0x5555,
            Operation.SET_IP_CONFIG,
            1,
            b"\x01\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00",
        )
        nack_reply = ReplayReplyModel(ReplyStatus.NACK, ErrorCode.OUT_OF_RANGE)
        cache.store(nack_key, nack_reply, now_ms=200)
        self.assertEqual(cache.lookup(nack_key, now_ms=201), nack_reply)

    def test_changed_payload_is_not_replayed_for_same_request_id(self):
        cache = ReplayCacheModel(self.cache_size, self.cache_ttl_ms)
        cached_key = _replay_key(
            (10, 0, 0, 9),
            7,
            Operation.SET_OPERATING_MODE,
            1,
            pack_operating_mode(OperatingMode.PRODUCTION),
        )
        cache.store(
            cached_key,
            ReplayReplyModel(ReplyStatus.ACK, ErrorCode.NONE),
            now_ms=1,
        )
        changed_payload = _replay_key(
            (10, 0, 0, 9),
            7,
            Operation.SET_OPERATING_MODE,
            1,
            pack_operating_mode(OperatingMode.PROTOTYPE),
        )
        changed_length = _replay_key(
            (10, 0, 0, 9),
            7,
            Operation.SET_OPERATING_MODE,
            1,
            b"",
            declared_payload_len=1,
        )
        self.assertIsNone(cache.lookup(changed_payload, now_ms=2))
        self.assertIsNone(cache.lookup(changed_length, now_ms=2))
        self.assertIsNotNone(cache.lookup(cached_key, now_ms=2))

    def test_crc_collision_payloads_remain_distinct_replay_keys(self):
        first = bytes((10, 0, 16, 33))
        second = bytes((10, 1, 0, 0))
        self.assertEqual(
            binascii.crc_hqx(first, 0xFFFF),
            binascii.crc_hqx(second, 0xFFFF),
        )
        self.assertNotEqual(
            _replay_key((10, 0, 0, 9), 7, Operation.SET_TELEMETRY_TARGET, 1, first),
            _replay_key((10, 0, 0, 9), 7, Operation.SET_TELEMETRY_TARGET, 1, second),
        )
    def test_cache_is_bounded_and_entries_expire(self):
        cache = ReplayCacheModel(self.cache_size, self.cache_ttl_ms)
        inserted = []
        for index in range(self.cache_size + 1):
            key = _replay_key(
                (192, 168, 4, index),
                index,
                Operation.SET_TELEMETRY_TARGET,
                1,
                bytes((192, 168, 1, index)),
            )
            cache.store(
                key,
                ReplayReplyModel(ReplyStatus.ACK, ErrorCode.NONE),
                now_ms=index,
            )
            inserted.append(key)
        self.assertIsNone(cache.lookup(inserted[0], now_ms=self.cache_size + 2))
        self.assertIsNotNone(cache.lookup(inserted[-1], now_ms=self.cache_size + 2))
        self.assertIsNone(
            cache.lookup(inserted[-1], now_ms=self.cache_ttl_ms + self.cache_size + 3)
        )


class UnifiedStatusGoldenTests(unittest.TestCase):
    def test_status_exact_bytes(self):
        flags = (
            STATUS_FLAG_WIFI_CONNECTED
            | STATUS_FLAG_OUTPUT_POWER
            | STATUS_FLAG_TELEMETRY_CONFIGURED
            | STATUS_FLAG_PRODUCTION
            | STATUS_FLAG_BATTERY_VALID
        )
        status = UnifiedStatus(
            sequence=0x1234,
            uptime_seconds=0x01020304,
            flags=flags,
            rendered_fps_x10=299,
            packet_rate_x10=301,
            rssi_dbm=-62,
            firmware_major=3,
            firmware_minor=14,
            firmware_patch=0,
            operating_mode=OperatingMode.PRODUCTION,
            battery_mode=BatteryMode.BATTERY,
            battery_mv=4875,
            battery_pct=76,
            unlock_remaining_seconds=0,
        )
        packet = pack_status(status)
        self.assertEqual(
            packet,
            bytes.fromhex(
                "5053540112340102030400b5012b012dc2030e000100130b4c000000"
            ),
        )
        self.assertEqual(unpack_status(packet), status)

    def test_status_requires_exact_size(self):
        with self.assertRaisesRegex(ValueError, "exactly 28"):
            unpack_status(b"PST\x01")


class FirmwareContractSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[3]
        firmware = root / "V5" / "Arduino" / "primusV3_receiver"
        cls.config = (firmware / "config.h").read_text(encoding="utf-8")
        cls.ino = (firmware / "primusV3_receiver.ino").read_text(encoding="utf-8")
        cls.management = (firmware / "management_protocol.h").read_text(
            encoding="utf-8"
        )
        cls.receive_mode = (firmware / "receive_mode.h").read_text(
            encoding="utf-8"
        )

    def macro(self, name):
        return _macro_value(self.config, name)

    def test_firmware_constants_match_python_contract(self):
        self.assertEqual(self.macro("ARTNET_OPCODE_MANAGEMENT_REQUEST"), "0x8140")
        self.assertEqual(self.macro("ARTNET_OPCODE_MANAGEMENT_REPLY"), "0x8141")
        self.assertEqual(self.macro("MANAGEMENT_PROTOCOL_VERSION"), "1")
        self.assertEqual(self.macro("MANAGEMENT_HEADER_LEN"), "20")
        self.assertEqual(self.macro("MANAGEMENT_REPLY_CACHE_SIZE"), "4")
        self.assertEqual(self.macro("MANAGEMENT_REPLY_CACHE_TTL_MS"), "30000UL")
        self.assertEqual(self.macro("MANAGEMENT_REPLY_PACKET_MAX_LEN"), "256")
        self.assertEqual(self.macro("MANAGEMENT_REQUEST_PAYLOAD_MAX_LEN"), "148")
        self.assertEqual(self.macro("OUTPUT_DESCRIPTOR_WIRE_LEN"), "12")
        self.assertEqual(self.macro("OUTPUT_DESCRIPTOR_BLOB_LEN"), "28")
        self.assertEqual(self.macro("RECEIVE_CONFIG_BLOB_LEN"), "54")
        self.assertEqual(self.macro("NETWORK_CONFIG_BLOB_LEN"), "64")
        self.assertEqual(self.macro("IDENTITY_BLOB_LEN"), "199")
        self.assertEqual(self.macro("STATUS_PROTOCOL_VERSION"), "1")
        self.assertEqual(self.macro("STATUS_PACKET_LEN"), "28")
        self.assertEqual(self.macro("MAX_LEDS_PER_PORT"), "170")

    def test_firmware_has_stable_slots_and_no_source_learning(self):
        self.assertIn("reply[173] = NUM_OUTPUTS;", self.ino)
        self.assertIn("reply[174 + i] = 0xC0;", self.ino)
        self.assertNotIn("senderIP = remoteAddr", self.ino)
        self.assertNotIn("telemetryTarget = remoteAddr", self.ino)
        self.assertIn('prefs.getBytesLength("teleTarget")', self.ino)
        self.assertIn('"None(Custom)"', self.ino)
        self.assertIn("if (outputs[i].type == OUTPUT_CUSTOM) continue;", self.ino)
        self.assertIn("outputs[i].universe = base + i;", self.receive_mode)
        self.assertIn("validateUniverseBase", self.receive_mode)

    def test_firmware_production_recovery_paths_are_present(self):
        self.assertIn("if (isProductionMode()) return;", self.ino)
        self.assertIn("MGMT_ERROR_LOCKED", self.ino)
        self.assertIn("PRODUCTION_UNLOCK_WINDOW_MS", self.ino)
        self.assertIn("saveOperatingMode(OPERATING_MODE_PROTOTYPE)", self.ino)
        self.assertIn("testModeActive = false;", self.ino)
        self.assertIn("validUtf8((const uint8_t*)newCharacter", self.ino)
        self.assertIn("bootUnlockWindowExpired = true;", self.ino)
        self.assertIn("(void)bootUnlockWindowOpen();", self.ino)
        self.assertIn(
            "currentUniverseBase > 32766 ? 32766 : currentUniverseBase",
            self.ino,
        )

    def test_management_setters_persist_before_runtime_mutation(self):
        operating = re.search(
            r"bool saveOperatingMode\(OperatingMode mode\) \{(?P<body>.*?)\n\}",
            self.ino,
            re.DOTALL,
        )
        self.assertIsNotNone(operating)
        body = operating.group("body")
        self.assertLess(
            body.index('prefs.putUChar("opMode"'),
            body.index("currentOperatingMode = mode"),
        )
        self.assertIn("return false;", body)
        management_case = re.search(
            r"case MGMT_SET_OPERATING_MODE:(?P<body>.*?)\n      break;",
            self.ino,
            re.DOTALL,
        )
        self.assertIsNotNone(management_case)
        case_body = management_case.group("body")
        self.assertIn(
            "if (!saveOperatingMode(OPERATING_MODE_PRODUCTION))",
            case_body,
        )
        self.assertIn("error = MGMT_ERROR_INTERNAL;", case_body)
        self.assertLess(
            case_body.index("saveOperatingMode(OPERATING_MODE_PRODUCTION)"),
            case_body.index("testModeActive = false;"),
        )
        self.assertIn(
            "if (!saveReceiveMode(prefs, mode, base)) return false;",
            self.receive_mode,
        )
        self.assertLess(
            self.receive_mode.index(
                "if (!saveReceiveMode(prefs, mode, base)) return false;"
            ),
            self.receive_mode.index(
                "applyReceiveMode(outputs, mode, base);",
                self.receive_mode.index("inline bool setReceiveMode"),
            ),
        )

    def test_multifield_management_records_commit_atomically(self):
        receive_commit = self.receive_mode.index(
            'prefs.putBytes("recvCfg", blob, sizeof(blob))'
        )
        self.assertLess(
            receive_commit,
            self.receive_mode.index('prefs.putUChar("recvMode"', receive_commit),
        )
        self.assertLess(
            receive_commit,
            self.receive_mode.index('prefs.putUShort("univBase"', receive_commit),
        )
        self.assertIn('prefs.isKey("recvCfg")', self.receive_mode)
        self.assertIn("decodeReceiveConfig", self.receive_mode)
        self.assertIn("commitOverrideBuildId = PRIMUSV3_OVERRIDE_BUILD_ID", self.receive_mode)
        self.assertNotIn('"recvOvrBuild"', self.receive_mode)
        self.assertLess(
            self.receive_mode.index(
                "decodeReceiveConfig(blob, mode, base, receiveOverrideBuildId)"
            ),
            self.receive_mode.index("if (overridePending) {"),
        )
        self.assertIn(
            "if (overridePending && !validateReceiveMode(mode, outputs))",
            self.receive_mode,
        )

        ip_case = re.search(
            r"case MGMT_SET_IP_CONFIG:(?P<body>.*?)"
            r"\n\s+case MGMT_SET_IDENTITY:",
            self.ino,
            re.DOTALL,
        )
        self.assertIsNotNone(ip_case)
        ip_body = ip_case.group("body")
        self.assertIn("saveNetworkConfig(", ip_body)
        self.assertNotIn("prefs.", ip_body)

        identity_case = re.search(
            r"case MGMT_SET_IDENTITY: \{(?P<body>.*?)"
            r"\n\s+default:",
            self.ino,
            re.DOTALL,
        )
        self.assertIsNotNone(identity_case)
        identity_body = identity_case.group("body")
        self.assertIn("saveIdentityRecord(technical, character, performer)", identity_body)
        self.assertLess(
            identity_body.index("saveIdentityRecord(technical, character, performer)"),
            identity_body.index("applyIdentityRecord(technical, character, performer)"),
        )
        self.assertNotIn("prefs.", identity_body)

        network_commit = self.ino.index(
            'prefs.putBytes("netCfg", blob, sizeof(blob))'
        )
        self.assertLess(
            network_commit,
            self.ino.index('prefs.putBytes("staticIP"', network_commit),
        )
        identity_commit = self.ino.index(
            'prefs.putBytes("identity", blob, sizeof(blob))'
        )
        self.assertLess(
            identity_commit,
            self.ino.index('prefs.putString("characterName"', identity_commit),
        )
        self.assertIn('prefs.isKey("netCfg")', self.ino)
        self.assertIn('prefs.isKey("identity")', self.ino)
        network_loader = re.search(
            r"void loadStoredNetworkConfig\(\) \{(?P<body>.*?)"
            r"\n\}\n\nvoid printStartupConnectionData",
            self.ino,
            re.DOTALL,
        )
        self.assertIsNotNone(network_loader)
        network_body = network_loader.group("body")
        self.assertLess(
            network_body.index("loadAtomicNetworkConfig()"),
            network_body.index("if (overridePending) {"),
        )
        self.assertIn("saveNetworkConfigWithOverride(", network_body)
        identity_loader = re.search(
            r"void loadStoredIdentity\(\) \{(?P<body>.*?)"
            r"\n\}\n\nvoid printIpBytes",
            self.ino,
            re.DOTALL,
        )
        self.assertIsNotNone(identity_loader)
        loader_body = identity_loader.group("body")
        self.assertLess(
            loader_body.index("loadAtomicIdentityRecord()"),
            loader_body.index("if (overridesPending) {"),
        )
        self.assertIn("saveIdentityRecordWithOverride(", loader_body)
        self.assertNotIn('"identOvrBuild"', self.ino)
        legacy_identity_loaders = self.ino[
            self.ino.index("void loadStoredDeviceName()"):
            self.ino.index("void loadStoredIdentity()")
        ]
        self.assertNotIn("prefs.put", legacy_identity_loaders)
        self.assertNotIn("prefs.remove", legacy_identity_loaders)
        self.assertIn("persistenceCrc16", self.config)

    def test_descriptor_persistence_is_one_checksummed_blob(self):
        self.assertIn('prefs.putBytes("outDescAll", blob, sizeof(blob))', self.management)
        self.assertIn("persistenceCrc16", self.management)
        self.assertNotIn("prefs.putBytes(descriptorKey", self.management)
        self.assertIn("migratePerSlotOutputDescriptors", self.management)

    def test_management_reply_cache_key_and_policy_are_declared(self):
        self.assertIn("struct ManagementReplayKey", self.management)
        for field in (
            "remoteIp[4]",
            "requestId",
            "operation",
            "protocolVersion",
            "declaredPayloadLen",
            "actualPayloadLen",
            "payload[MANAGEMENT_REQUEST_PAYLOAD_MAX_LEN]",
            "requestStatus",
            "requestError",
        ):
            self.assertIn(field, self.management)
        self.assertIn("memcmp(a.payload, b.payload, a.actualPayloadLen)", self.management)
        self.assertIn("findManagementReplyCacheEntry", self.management)
        self.assertIn("reserveManagementReplyCacheEntry", self.management)
        self.assertIn("error != MGMT_ERROR_INTERNAL", self.management)

    def test_management_duplicates_replay_after_version_before_mutation_validation(self):
        handler = re.search(
            r"void handleManagementRequest\(uint8_t\* data, uint16_t len, "
            r"IPAddress remoteAddr\) \{(?P<body>.*?)\n\}",
            self.ino,
            re.DOTALL,
        )
        self.assertIsNotNone(handler)
        body = handler.group("body")
        replay = body.index("if (replayCachedManagementReply(request)) return;")
        self.assertLess(body.index("if (readBe16(data + 10)"), replay)
        self.assertLess(body.index("MGMT_ERROR_UNSUPPORTED_VERSION"), replay)
        self.assertLess(replay, body.index("MGMT_ERROR_MALFORMED_PACKET"))
        self.assertLess(replay, body.index("if (request.operation == MGMT_GET_CONFIG)"))
        self.assertLess(replay, body.index("if (isProductionMode())"))
        self.assertLess(replay, body.index("switch (request.operation)"))

    def test_management_replies_are_cached_before_send(self):
        sender = re.search(
            r"void sendManagementReply\(const ManagementRequestContext& request,"
            r"(?P<body>.*?)\n\}",
            self.ino,
            re.DOTALL,
        )
        self.assertIsNotNone(sender)
        body = sender.group("body")
        self.assertIn("shouldCacheManagementReply(status, error)", body)
        self.assertIn("entry->key = key;", body)
        self.assertLess(body.index("entry->valid = true;"), body.index("sendManagementReplyPacket(request.remoteAddr, entry->reply, entry->replyLen);"))

    def test_enter_production_lost_ack_replay_is_structurally_safe(self):
        handler = re.search(
            r"void handleManagementRequest\(uint8_t\* data, uint16_t len, "
            r"IPAddress remoteAddr\) \{(?P<body>.*?)\n\}",
            self.ino,
            re.DOTALL,
        )
        self.assertIsNotNone(handler)
        body = handler.group("body")
        self.assertLess(
            body.index("if (replayCachedManagementReply(request)) return;"),
            body.index("if (isProductionMode())"),
        )
        self.assertIn("saveOperatingMode(OPERATING_MODE_PRODUCTION)", body)
        success_block = re.search(
            r"if \(error == MGMT_ERROR_NONE\) \{(?P<body>.*?)\n  \} else \{",
            self.ino,
            re.DOTALL,
        )
        self.assertIsNotNone(success_block)
        success_body = success_block.group("body")
        self.assertLess(
            success_body.index("sendManagementReply(request, MGMT_ACK, MGMT_ERROR_NONE);"),
            success_body.index("displaySetPower(false);"),
        )

if __name__ == "__main__":
    unittest.main()
