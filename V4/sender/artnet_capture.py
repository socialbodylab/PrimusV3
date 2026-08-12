"""artnet_capture.py — Stand-in UDP listener and tcpdump sniff backends."""

import os
import shutil
import socket
import struct
import subprocess
import threading
import time

from artnet_parse import ARTNET_PORT, parse_artnet_packet, parse_ethernet_udp
import capture_store
from capture_setup import bpf_host_filter, device_ips, universe_for_ip

FPS_PORT = 6455


class CaptureError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)


class _StandInBackend:
    def __init__(self, device_ip, interface, full_payload, show_setup=None):
        self.device_ip = device_ip
        self.interface = interface
        self.full_payload = full_payload
        self.show_setup = show_setup or {}
        self.expected_universe = universe_for_ip(self.show_setup, device_ip)
        self._socks = []
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        bind_ip = self._resolve_bind_ip()
        ports = (ARTNET_PORT, FPS_PORT)
        for port in ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((bind_ip, port))
            except OSError as exc:
                for s in self._socks:
                    s.close()
                self._socks = []
                raise CaptureError(
                    f"Could not bind UDP {port} on {bind_ip or '0.0.0.0'}: {exc}. "
                    f"For stand-in mode, set this laptop to {self.device_ip} and power off the real device."
                ) from exc
            sock.settimeout(0.5)
            self._socks.append(sock)
        self._stop.clear()
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        for sock in self._socks:
            try:
                sock.close()
            except OSError:
                pass
        self._socks = []
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _resolve_bind_ip(self):
        if self.interface:
            return self.interface
        return ""

    def _listen_loop(self):
        while not self._stop.is_set():
            for sock in list(self._socks):
                try:
                    raw, addr = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    continue
                event = parse_artnet_packet(
                    raw,
                    src_ip=addr[0],
                    dst_ip=self.device_ip,
                    ts=time.time(),
                    full_payload=self.full_payload,
                )
                if event:
                    if self.expected_universe is not None:
                        event["expected_universe"] = self.expected_universe
                    capture_store.record_event(event)


class _SniffBackend:
    PCAP_GLOBAL_HDR = 24
    PCAP_RECORD_HDR = 16

    def __init__(self, device_ip, interface, full_payload, show_setup=None):
        self.device_ip = device_ip
        self.interface = interface or "en0"
        self.full_payload = full_payload
        self.show_setup = show_setup or {}
        self._target_ips = set(device_ips(self.show_setup) or [device_ip])
        self._proc = None
        self._thread = None
        self._stop = threading.Event()
        self._pcap_path = None
        self._offset = 0

    def start(self):
        tcpdump = shutil.which("tcpdump")
        if not tcpdump:
            raise CaptureError("tcpdump not found. Install tcpdump or use stand-in mode.")
        self._pcap_path = os.path.join(
            capture_store.capture_dir(),
            f"sniff-{int(time.time())}.pcap",
        )
        bpf = f"udp port {ARTNET_PORT} and {bpf_host_filter(self.show_setup, self.device_ip)}"
        cmd = [
            "sudo",
            tcpdump,
            "-i",
            self.interface,
            "-n",
            "-U",
            "-w",
            self._pcap_path,
            bpf,
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as exc:
            raise CaptureError(f"Failed to start tcpdump: {exc}") from exc
        time.sleep(0.3)
        if self._proc.poll() is not None:
            err = (self._proc.stderr.read() if self._proc.stderr else "") or "tcpdump exited"
            raise CaptureError(
                f"tcpdump failed (admin required for sniff mode): {err.strip()}"
            )
        self._offset = self.PCAP_GLOBAL_HDR
        self._stop.clear()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        self._proc = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _read_loop(self):
        while not self._stop.is_set():
            if not self._pcap_path or not os.path.isfile(self._pcap_path):
                time.sleep(0.1)
                continue
            try:
                size = os.path.getsize(self._pcap_path)
            except OSError:
                time.sleep(0.1)
                continue
            if size < self._offset:
                self._offset = self.PCAP_GLOBAL_HDR
            while self._offset + self.PCAP_RECORD_HDR <= size:
                with open(self._pcap_path, "rb") as handle:
                    handle.seek(self._offset)
                    rec_hdr = handle.read(self.PCAP_RECORD_HDR)
                    if len(rec_hdr) < self.PCAP_RECORD_HDR:
                        break
                    _ts_sec, _ts_usec, incl_len, _orig_len = struct.unpack("<IIII", rec_hdr)
                    frame = handle.read(incl_len)
                    self._offset += self.PCAP_RECORD_HDR + incl_len
                    if len(frame) < incl_len:
                        self._offset -= self.PCAP_RECORD_HDR + incl_len
                        break
                    parsed = parse_ethernet_udp(frame)
                    if not parsed:
                        continue
                    src_ip, dst_ip, payload = parsed
                    if dst_ip not in self._target_ips:
                        continue
                    ts = time.time()
                    event = parse_artnet_packet(
                        payload,
                        src_ip=src_ip,
                        dst_ip=dst_ip,
                        ts=ts,
                        full_payload=self.full_payload,
                    )
                    if event:
                        expected = universe_for_ip(self.show_setup, dst_ip)
                        if expected is not None:
                            event["expected_universe"] = expected
                        capture_store.record_event(event)
            time.sleep(0.05)


class ArtNetCaptureManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._backend = None
        self._mode = ""
        self._device_ip = ""
        self._interface = ""
        self._show_setup = {}
        self._duration_timer = None

    def is_active(self):
        with self._lock:
            return self._backend is not None

    def runtime(self):
        with self._lock:
            store_status = capture_store.status()
            return {
                "active": self._backend is not None,
                "mode": self._mode,
                "device_ip": self._device_ip,
                "interface": self._interface,
                "show_setup": self._show_setup,
                "recording": store_status["recording"],
                "session": store_status.get("session"),
                "full_payload": store_status.get("full_payload", False),
            }

    def start(self, mode, device_ip, interface="", full_payload=False, duration_s=None, show_setup=None):
        mode = str(mode or "standin").strip().lower()
        device_ip = str(device_ip or "192.168.8.190").strip()
        interface = str(interface or "").strip()
        show_setup = show_setup or {}
        expected_universe = universe_for_ip(show_setup, device_ip)
        with self._lock:
            if self._backend:
                raise CaptureError("capture already running")
            capture_store.start_recording(
                mode, device_ip, interface,
                full_payload=full_payload,
                show_setup=show_setup,
                expected_universe=expected_universe,
            )
            if mode == "sniff":
                backend = _SniffBackend(device_ip, interface, full_payload, show_setup=show_setup)
            else:
                backend = _StandInBackend(device_ip, interface, full_payload, show_setup=show_setup)
            try:
                backend.start()
            except Exception:
                capture_store.stop_recording()
                raise
            self._backend = backend
            self._mode = mode
            self._device_ip = device_ip
            self._interface = interface
            self._show_setup = show_setup
            if duration_s and duration_s > 0:
                timer = threading.Timer(float(duration_s), self._auto_stop)
                timer.daemon = True
                timer.start()
                self._duration_timer = timer
            return self.runtime()

    def stop(self):
        with self._lock:
            if self._duration_timer:
                self._duration_timer.cancel()
                self._duration_timer = None
            backend = self._backend
            self._backend = None
            self._mode = ""
        if backend:
            backend.stop()
        capture_store.stop_recording()
        return self.runtime()

    def _auto_stop(self):
        try:
            self.stop()
        except Exception:
            pass


capture_manager = ArtNetCaptureManager()
