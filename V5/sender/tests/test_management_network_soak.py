import concurrent.futures
import json
import queue
import select
import socket
import struct
import tempfile
import threading
import time
import unittest
import urllib.request
from unittest.mock import patch

import artnet
import state as state_module
from artnet import ArtNetSender, PrimusTelemetryListener
from output_presets import OutputPresetStore
from primus_protocol import (
    ARTNET_HEADER,
    BatteryMode,
    DeviceConfig,
    IpMode,
    Layout,
    MANAGEMENT_REQUEST_OPCODE,
    OFF_DESCRIPTOR,
    OperatingMode,
    Operation,
    OutputDescriptor,
    ReceiveMode,
    ScanPattern,
    StartCorner,
    STATUS_FLAG_BATTERY_VALID,
    STATUS_FLAG_TELEMETRY_CONFIGURED,
    STATUS_FLAG_WIFI_CONNECTED,
    TraversalAxis,
    UnifiedStatus,
    build_management_reply,
    pack_config,
    pack_status,
    parse_management_packet,
)
from server import create_server
from state import ControllerState


def _output_descriptor(pixels):
    return OutputDescriptor(
        True,
        pixels,
        Layout.LINEAR,
        0,
        0,
        TraversalAxis.ROW_MAJOR,
        ScanPattern.PROGRESSIVE,
        StartCorner.TOP_LEFT,
        pixels,
    )


def _device_config():
    return DeviceConfig(
        operating_mode=OperatingMode.PROTOTYPE,
        unlock_window_open=False,
        unlock_remaining_seconds=0,
        receive_mode=ReceiveMode.SPLIT,
        base_universe=10,
        telemetry_target="127.0.0.50",
        ip_mode=IpMode.DHCP,
        ip="127.0.0.1",
        gateway="0.0.0.0",
        subnet="0.0.0.0",
        outputs=(_output_descriptor(30), OFF_DESCRIPTOR),
        technical_name="Loopback",
        character_name="Soak",
        performer_name="Test",
    )


class _LoopbackPrimusReceiver:
    HOST = "127.0.0.1"

    def __init__(self, config):
        self.config = config
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.HOST, 0))
        self.socket.settimeout(0.1)
        self.port = self.socket.getsockname()[1]
        self.running = True
        self.lock = threading.Lock()
        self.dmx_packets = 0
        self.management_queries = 0
        self.overlapping_queries = 0
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def _record_dmx(self):
        with self.lock:
            self.dmx_packets += 1

    def _reply_to_query(self, raw, address):
        request = parse_management_packet(raw)
        with self.lock:
            self.management_queries += 1

        queued_queries = []
        deadline = time.monotonic() + 0.003
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.socket], [], [], 0.001)
            if not ready:
                continue
            queued, queued_address = self.socket.recvfrom(2048)
            opcode = (
                struct.unpack_from("<H", queued, 8)[0]
                if len(queued) >= 10 and queued[:8] == ARTNET_HEADER
                else None
            )
            if opcode == artnet.ARTNET_OPCODE_DMX:
                self._record_dmx()
            elif opcode == MANAGEMENT_REQUEST_OPCODE:
                with self.lock:
                    self.overlapping_queries += 1
                queued_queries.append((queued, queued_address))

        reply = build_management_reply(
            request.request_id,
            Operation.GET_CONFIG,
            pack_config(self.config),
        )
        self.socket.sendto(reply, address)
        for queued, queued_address in queued_queries:
            queued_request = parse_management_packet(queued)
            queued_reply = build_management_reply(
                queued_request.request_id,
                Operation.GET_CONFIG,
                pack_config(self.config),
            )
            self.socket.sendto(queued_reply, queued_address)

    def run(self):
        while self.running:
            try:
                raw, address = self.socket.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(raw) < 10 or raw[:8] != ARTNET_HEADER:
                continue
            opcode = struct.unpack_from("<H", raw, 8)[0]
            if opcode == artnet.ARTNET_OPCODE_DMX:
                self._record_dmx()
            elif opcode == MANAGEMENT_REQUEST_OPCODE:
                self._reply_to_query(raw, address)

    def stop(self):
        self.running = False
        try:
            self.socket.sendto(b"stop", (self.HOST, self.port))
        except OSError:
            pass
        self.thread.join(timeout=2)
        self.socket.close()


class _QueuedDatagramSocket:
    def __init__(self):
        self.packets = queue.Queue()
        self.closed = False

    def inject(self, raw, address):
        self.packets.put((raw, address))

    def recvfrom(self, _size):
        try:
            raw, address = self.packets.get(timeout=0.1)
        except queue.Empty as exc:
            raise socket.timeout from exc
        if self.closed:
            raise OSError("socket closed")
        return raw, address

    def close(self):
        self.closed = True
        self.inject(b"", ("0.0.0.0", 0))


def _queued_telemetry_listener():
    listener = PrimusTelemetryListener.__new__(PrimusTelemetryListener)
    listener.lock = threading.Lock()
    listener.data = {}
    listener.running = True
    listener._sock = _QueuedDatagramSocket()
    listener.monotonic = time.monotonic
    return listener


def _send_pst_heartbeats(datagram_socket, device_count=12, rounds=60):
    for round_index in range(rounds):
        for device_index in range(device_count):
            sequence = 1000 + round_index
            status = UnifiedStatus(
                sequence=sequence,
                uptime_seconds=1000 + round_index,
                flags=(
                    STATUS_FLAG_WIFI_CONNECTED
                    | STATUS_FLAG_TELEMETRY_CONFIGURED
                    | STATUS_FLAG_BATTERY_VALID
                ),
                rendered_fps_x10=300,
                packet_rate_x10=600,
                rssi_dbm=-45,
                firmware_major=3,
                firmware_minor=12,
                firmware_patch=device_index,
                operating_mode=OperatingMode.PROTOTYPE,
                battery_mode=BatteryMode.BATTERY,
                battery_mv=3800,
                battery_pct=75,
                unlock_remaining_seconds=0,
            )
            address = (f"10.0.0.{device_index + 20}", 6455)
            datagram_socket.inject(pack_status(status), address)
            if round_index == 20:
                reordered = UnifiedStatus(
                    **{
                        **status.__dict__,
                        "sequence": sequence - 2,
                        "uptime_seconds": status.uptime_seconds - 2,
                    }
                )
                datagram_socket.inject(pack_status(reordered), address)
        time.sleep(0.0005)


def _bind_ephemeral_query_socket(_source_ip=None):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    return sock


def _send_eos_like_dmx(port, packets=1200):
    destination = (_LoopbackPrimusReceiver.HOST, port)
    sender = ArtNetSender(_LoopbackPrimusReceiver.HOST)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        payload = bytes((value % 256 for value in range(90)))
        for sequence in range(packets):
            sender.sequence = (sequence % 255) + 1
            sock.sendto(sender._build_packet(10, payload), destination)
            time.sleep(0.0002)
    finally:
        sock.close()


def _post_json(url, payload):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


class ManagementNetworkSoakTests(unittest.TestCase):
    def test_concurrent_pst_listener_loopback_dmx_and_http_management(self):
        """Exercise the PST listener loop plus real loopback UDP and HTTP handlers."""
        config = _device_config()
        receiver = _LoopbackPrimusReceiver(config)
        listener = _queued_telemetry_listener()
        listener_thread = threading.Thread(target=listener.run, daemon=True)
        http_server = None
        http_thread = None
        tick_thread = None
        pst_thread = None
        dmx_thread = None
        stop_ticks = threading.Event()
        state = None
        receiver.start()
        listener_thread.start()

        started = time.monotonic()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                preset_path = f"{temp_dir}/output_presets.json"
                with (
                    patch.object(artnet, "ARTNET_PORT", receiver.port),
                    patch.object(
                        artnet,
                        "_bind_artnet_query_socket",
                        side_effect=_bind_ephemeral_query_socket,
                    ),
                    patch.object(
                        state_module,
                        "OutputPresetStore",
                        side_effect=lambda: OutputPresetStore(preset_path),
                    ),
                    patch.object(state_module, "_save_devices"),
                ):
                    state = ControllerState(listener)
                    added = state.add_device_from_node(
                        {
                            "ip": _LoopbackPrimusReceiver.HOST,
                            "short_name": "Loopback",
                            "node_report": (
                                "#0001 OK|PV3CAP1|F:RIOHBMSG|B:v31|IP:D|"
                                "U:S:10|G:1L|0:1:10:30|1:0:11:0"
                            ),
                            "capabilities": {
                                "profile": "pv3cap1",
                                "known": True,
                                "management": True,
                                "management_protocol_version": 1,
                            },
                            "outputs": [
                                {"name": "A0", "type": "short_strip", "universe": 10},
                                {"name": "A1", "type": "none", "universe": 11},
                            ],
                            "universes": [10, 11],
                        },
                        auto_save=False,
                    )
                    self.assertEqual(added["status"], "added")
                    self.assertEqual(
                        state.devices[0]["telemetry_target"],
                        config.telemetry_target,
                        (
                            f"device={state.devices[0]!r}; "
                            f"queries={receiver.management_queries}"
                        ),
                    )

                    with receiver.lock:
                        receiver.management_queries = 0
                        receiver.overlapping_queries = 0

                    http_server = create_server("127.0.0.1", 0, state)
                    server_errors = []
                    http_server.handle_error = (
                        lambda request, address: server_errors.append(address)
                    )
                    http_thread = threading.Thread(
                        target=http_server.serve_forever,
                        daemon=True,
                    )
                    http_thread.start()
                    endpoint = (
                        f"http://127.0.0.1:{http_server.server_address[1]}"
                        "/api/refresh_device_full_config"
                    )

                    tick_count = [0]

                    def run_ticks():
                        while not stop_ticks.is_set():
                            state.tick()
                            tick_count[0] += 1
                            time.sleep(0.001)

                    tick_thread = threading.Thread(target=run_ticks, daemon=True)
                    tick_thread.start()
                    pst_thread = threading.Thread(
                        target=_send_pst_heartbeats,
                        args=(listener._sock,),
                    )
                    dmx_thread = threading.Thread(
                        target=_send_eos_like_dmx,
                        args=(receiver.port,),
                    )
                    pst_thread.start()
                    dmx_thread.start()

                    request_count = 24
                    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                        responses = list(
                            pool.map(
                                lambda _: _post_json(endpoint, {"device": 0}),
                                range(request_count),
                            )
                        )

                    pst_thread.join(timeout=3)
                    dmx_thread.join(timeout=3)

                    self.assertFalse(pst_thread.is_alive())
                    self.assertFalse(dmx_thread.is_alive())
                    self.assertTrue(tick_thread.is_alive())
                    self.assertTrue(all(response["ok"] for response in responses))
                    self.assertEqual(server_errors, [])
                    self.assertEqual(
                        state.devices[0]["telemetry_target"],
                        config.telemetry_target,
                    )
                    self.assertTrue(state.devices[0]["telemetry_configured"])
                    self.assertGreater(tick_count[0], 10)

                    with receiver.lock:
                        self.assertEqual(receiver.management_queries, request_count)
                        self.assertEqual(receiver.overlapping_queries, 0)
                        self.assertGreaterEqual(receiver.dmx_packets, 1000)

                    accepted_total = 0
                    reordered_total = 0
                    for index in range(12):
                        telemetry = listener.get(f"10.0.0.{index + 20}")
                        self.assertIsNotNone(telemetry)
                        accepted_total += telemetry.get(
                            "telemetry_status_packets_accepted", 0
                        )
                        reordered_total += telemetry.get(
                            "telemetry_out_of_order_packets", 0
                        )
                        self.assertEqual(
                            telemetry.get("telemetry_reboot_count", 0),
                            0,
                        )
                    self.assertGreaterEqual(accepted_total, 600)
                    self.assertGreaterEqual(reordered_total, 12)
        finally:
            stop_ticks.set()
            if tick_thread is not None:
                tick_thread.join(timeout=2)
            if pst_thread is not None:
                pst_thread.join(timeout=3)
            if dmx_thread is not None:
                dmx_thread.join(timeout=3)
            if http_server is not None:
                http_server.shutdown()
                http_server.server_close()
            if http_thread is not None:
                http_thread.join(timeout=2)
            if state is not None:
                state.running = False
            listener.running = False
            listener._sock.inject(b"", ("0.0.0.0", 0))
            listener_thread.join(timeout=2)
            listener._sock.close()
            receiver.stop()

        self.assertIsNotNone(tick_thread)
        self.assertFalse(tick_thread.is_alive())
        self.assertLess(time.monotonic() - started, 6.0)


if __name__ == "__main__":
    unittest.main()
