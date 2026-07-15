"""Tests for acknowledged Primus management transport helpers."""

import errno
import os
import socket
import struct
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import artnet
from primus_protocol import (
    DeviceConfig,
    ErrorCode,
    IpMode,
    Layout,
    OFF_DESCRIPTOR,
    OperatingMode,
    Operation,
    OutputDescriptor,
    ReceiveMode,
    ReplyStatus,
    ScanPattern,
    StartCorner,
    TraversalAxis,
    build_management_reply,
    build_management_request,
    pack_config,
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


def sample_config():
    return DeviceConfig(
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


class FakeClock:
    def __init__(self, start=0.0, step=0.02):
        self.value = start
        self.step = step

    def __call__(self):
        current = self.value
        self.value += self.step
        return current


class PlannedSocket:
    plans = []
    instances = []

    def __init__(self, *args, **kwargs):
        self.plan = PlannedSocket.plans.pop(0) if PlannedSocket.plans else {}
        self.bound = None
        self.sent = []
        self.closed = False
        PlannedSocket.instances.append(self)

    def setsockopt(self, *args, **kwargs):
        return None

    def bind(self, addr):
        bind_errors = self.plan.get("bind_errors", {})
        error = bind_errors.get(addr)
        if error is not None:
            raise error
        self.bound = addr

    def settimeout(self, value):
        self.timeout = value

    def sendto(self, data, addr):
        self.sent.append((bytes(data), addr, self.bound))
        error = self.plan.get("send_error")
        if error is not None:
            raise error
        return len(data)

    def recvfrom(self, size):
        responses = self.plan.get("responses", [])
        if responses:
            item = responses.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        raise socket.timeout()

    def close(self):
        self.closed = True


class PrimusManagementTransportTests(unittest.TestCase):
    @patch("artnet.secrets.randbelow", return_value=0xA5A5)
    def test_request_id_seed_is_randomized_per_process(self, randbelow):
        self.assertEqual(artnet._new_management_request_id_seed(), 0xA5A5)
        randbelow.assert_called_once_with(0x10000)

    def test_request_id_counter_reseeds_after_fork_pid_change(self):
        with patch.object(artnet, "_management_request_pid", 100), patch.object(
            artnet, "_management_request_id", 7
        ), patch("artnet.os.getpid", return_value=101), patch(
            "artnet._new_management_request_id_seed", return_value=0xB000
        ) as new_seed:
            self.assertEqual(artnet._next_management_request_id(), 0xB000)
            self.assertEqual(artnet._next_management_request_id(), 0xB001)
        new_seed.assert_called_once_with()
    def setUp(self):
        PlannedSocket.instances = []
        PlannedSocket.plans = []

    def test_get_config_request_packet_and_decoded_reply(self):
        ip = "192.168.1.70"
        config = sample_config()
        PlannedSocket.plans = [
            {
                "responses": [
                    (
                        build_management_reply(
                            0x1234,
                            Operation.GET_CONFIG,
                            pack_config(config),
                            status=ReplyStatus.ACK,
                            error=ErrorCode.NONE,
                        ),
                        (ip, artnet.ARTNET_PORT),
                    )
                ]
            }
        ]
        with patch("artnet.socket.socket", PlannedSocket):
            result = artnet.get_primus_config(
                ip,
                request_id=0x1234,
                timeout=0.1,
                retries=0,
            )

        self.assertEqual(
            PlannedSocket.instances[0].sent[0][0],
            build_management_request(0x1234, Operation.GET_CONFIG),
        )
        self.assertEqual(result.request_id, 0x1234)
        self.assertEqual(result.operation, int(Operation.GET_CONFIG))
        self.assertEqual(result.config, config)

    def test_wrong_source_opcode_request_and_operation_are_ignored_until_valid_reply(self):
        ip = "192.168.1.71"
        PlannedSocket.plans = [
            {
                "responses": [
                    (
                        build_management_reply(
                            5,
                            Operation.SET_IP_CONFIG,
                            status=ReplyStatus.ACK,
                            error=ErrorCode.NONE,
                        ),
                        ("192.168.1.99", artnet.ARTNET_PORT),
                    ),
                    (
                        artnet.ARTNET_HEADER
                        + struct.pack("<H", artnet.ARTNET_OPCODE_POLL)
                        + b"\x00" * 12,
                        (ip, artnet.ARTNET_PORT),
                    ),
                    (
                        build_management_reply(
                            6,
                            Operation.SET_IP_CONFIG,
                            status=ReplyStatus.ACK,
                            error=ErrorCode.NONE,
                        ),
                        (ip, artnet.ARTNET_PORT),
                    ),
                    (
                        build_management_reply(
                            5,
                            Operation.SET_OPERATING_MODE,
                            status=ReplyStatus.ACK,
                            error=ErrorCode.NONE,
                        ),
                        (ip, artnet.ARTNET_PORT),
                    ),
                    (
                        build_management_reply(
                            5,
                            Operation.SET_IP_CONFIG,
                            status=ReplyStatus.ACK,
                            error=ErrorCode.NONE,
                        ),
                        (ip, artnet.ARTNET_PORT),
                    ),
                ]
            }
        ]
        with patch("artnet.socket.socket", PlannedSocket):
            result = artnet.request_primus_management(
                ip,
                Operation.SET_IP_CONFIG,
                payload=b"\x00" * 13,
                request_id=5,
                timeout=0.1,
                retries=0,
            )

        self.assertEqual(result.request_id, 5)
        self.assertEqual(result.operation, int(Operation.SET_IP_CONFIG))

    def test_wrong_replies_timeout_when_no_valid_reply_arrives(self):
        ip = "192.168.1.72"
        PlannedSocket.plans = [
            {
                "responses": [
                    (
                        build_management_reply(
                            8,
                            Operation.GET_CONFIG,
                            status=ReplyStatus.ACK,
                            error=ErrorCode.NONE,
                        ),
                        ("192.168.1.99", artnet.ARTNET_PORT),
                    ),
                    (
                        build_management_reply(
                            9,
                            Operation.SET_OPERATING_MODE,
                            status=ReplyStatus.ACK,
                            error=ErrorCode.NONE,
                        ),
                        (ip, artnet.ARTNET_PORT),
                    ),
                    (
                        build_management_reply(
                            10,
                            Operation.GET_CONFIG,
                            status=ReplyStatus.ACK,
                            error=ErrorCode.NONE,
                        ),
                        (ip, artnet.ARTNET_PORT),
                    ),
                ]
            }
        ]
        clock = FakeClock(step=0.02)
        with patch("artnet.socket.socket", PlannedSocket), patch(
            "artnet.time.monotonic", clock
        ):
            with self.assertRaises(artnet.PrimusManagementTimeout):
                artnet.get_primus_config(
                    ip,
                    request_id=9,
                    timeout=0.1,
                    retries=0,
                )

    def test_retries_and_source_bind_fallback_succeed(self):
        ip = "192.168.1.73"
        PlannedSocket.plans = [
            {
                "send_error": OSError(errno.EHOSTUNREACH, "No route to host"),
            },
            {},
            {
                "responses": [
                    (
                        build_management_reply(
                            11,
                            Operation.SET_OPERATING_MODE,
                            status=ReplyStatus.ACK,
                            error=ErrorCode.NONE,
                        ),
                        (ip, artnet.ARTNET_PORT),
                    )
                ]
            },
        ]
        clock = FakeClock(step=0.05)
        with patch("artnet.socket.socket", PlannedSocket), patch(
            "artnet.time.monotonic", clock
        ):
            result = artnet.set_primus_operating_mode(
                ip,
                OperatingMode.PRODUCTION,
                source_ip="10.0.0.5",
                request_id=11,
                timeout=0.1,
                retries=1,
            )

        self.assertEqual(result.request_id, 11)
        self.assertEqual(PlannedSocket.instances[0].bound, ("10.0.0.5", artnet.ARTNET_PORT))
        self.assertEqual(PlannedSocket.instances[1].bound, ("", artnet.ARTNET_PORT))
        self.assertEqual(PlannedSocket.instances[2].bound, ("", artnet.ARTNET_PORT))

    def test_nack_errors_map_to_specific_exceptions(self):
        ip = "192.168.1.74"
        PlannedSocket.plans = [
            {
                "responses": [
                    (
                        build_management_reply(
                            12,
                            Operation.SET_OPERATING_MODE,
                            status=ReplyStatus.NACK,
                            error=ErrorCode.LOCKED,
                        ),
                        (ip, artnet.ARTNET_PORT),
                    )
                ]
            }
        ]
        with patch("artnet.socket.socket", PlannedSocket):
            with self.assertRaises(artnet.PrimusManagementLocked) as ctx:
                artnet.set_primus_operating_mode(
                    ip,
                    OperatingMode.PRODUCTION,
                    request_id=12,
                    timeout=0.1,
                    retries=0,
                )

        self.assertEqual(ctx.exception.error_code, ErrorCode.LOCKED)

    def test_management_requests_serialize_access_to_controller_port(self):
        active = 0
        max_active = 0
        first_entered = threading.Event()
        release_first = threading.Event()
        active_lock = threading.Lock()

        def fake_request(*args, **kwargs):
            nonlocal active, max_active
            with active_lock:
                active += 1
                max_active = max(max_active, active)
                if active == 1:
                    first_entered.set()
            if not release_first.wait(1):
                raise AssertionError("timed out waiting to release request")
            with active_lock:
                active -= 1
            return object()

        with patch("artnet._request_primus_management_unlocked", side_effect=fake_request):
            first = threading.Thread(
                target=artnet.request_primus_management,
                args=("192.168.1.70", Operation.GET_CONFIG),
            )
            second = threading.Thread(
                target=artnet.request_primus_management,
                args=("192.168.1.71", Operation.GET_CONFIG),
            )
            first.start()
            self.assertTrue(first_entered.wait(1))
            second.start()
            time.sleep(0.05)
            self.assertEqual(max_active, 1)
            release_first.set()
            first.join(1)
            second.join(1)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(max_active, 1)


if __name__ == "__main__":
    unittest.main()
