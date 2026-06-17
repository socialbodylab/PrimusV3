"""Inbound OSC control for Primus cue playback.

The sender stays dependency-free, so this module implements the small OSC 1.0
subset needed for QLab-style cue triggers using only the Python standard
library.
"""

import copy
import errno
import json
import os
import socket
import struct
import threading
import time
from collections import deque
from urllib.parse import unquote

from paths import state_file
from state import ControllerState


STATE_KEY = "osc_control"
OSC_LISTEN_HOST = "0.0.0.0"
DEFAULT_OSC_SETTINGS = {
    "enabled": True,
    "host": OSC_LISTEN_HOST,
    "port": 53001,
}
MAX_PACKET_BYTES = 65535
MAX_HISTORY = 100


class OscParseError(ValueError):
    pass


class OscCommandError(ValueError):
    pass


class OscMessage:
    def __init__(self, address, args=None, remote=None):
        self.address = address
        self.args = list(args or [])
        self.remote = remote

    def to_dict(self):
        return {
            "address": self.address,
            "args": list(self.args),
            "remote": self.remote,
        }


def _state_file():
    return state_file()


def _read_state():
    try:
        with open(_state_file(), "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(data):
    directory = os.path.dirname(_state_file())
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(_state_file(), "w") as f:
        json.dump(data, f)


def normalize_bind_host(host=None):
    """OSC always listens on all interfaces for local and LAN traffic."""
    return OSC_LISTEN_HOST


def normalize_settings(settings=None):
    out = copy.deepcopy(DEFAULT_OSC_SETTINGS)
    if not isinstance(settings, dict):
        return out
    out["enabled"] = bool(settings.get("enabled", out["enabled"]))
    out["host"] = OSC_LISTEN_HOST
    try:
        port = int(settings.get("port", out["port"]))
    except (TypeError, ValueError):
        port = out["port"]
    if port < 1 or port > 65535:
        port = DEFAULT_OSC_SETTINGS["port"]
    out["port"] = port
    return out


def load_settings():
    return normalize_settings(_read_state().get(STATE_KEY))


def save_settings(settings):
    data = _read_state()
    data[STATE_KEY] = normalize_settings(settings)
    _write_state(data)
    return data[STATE_KEY]


def _align4(offset):
    return (offset + 3) & ~3


def _read_padded_string(data, offset):
    end = data.find(b"\x00", offset)
    if end < 0:
        raise OscParseError("unterminated OSC string")
    try:
        value = data[offset:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OscParseError("invalid OSC string") from exc
    return value, _align4(end + 1)


def _read_int32(data, offset):
    if offset + 4 > len(data):
        raise OscParseError("truncated int32")
    return struct.unpack(">i", data[offset:offset + 4])[0], offset + 4


def _read_float32(data, offset):
    if offset + 4 > len(data):
        raise OscParseError("truncated float32")
    return struct.unpack(">f", data[offset:offset + 4])[0], offset + 4


def _read_blob(data, offset):
    size, offset = _read_int32(data, offset)
    if size < 0 or offset + size > len(data):
        raise OscParseError("invalid blob size")
    blob = data[offset:offset + size]
    return blob, _align4(offset + size)


def parse_osc_packet(data, remote=None):
    if not isinstance(data, (bytes, bytearray)):
        raise OscParseError("OSC packet must be bytes")
    packet = bytes(data)
    if not packet:
        raise OscParseError("empty OSC packet")
    messages = []
    _parse_packet_into(packet, remote, messages)
    return messages


def _parse_packet_into(data, remote, messages):
    address, offset = _read_padded_string(data, 0)
    if address == "#bundle":
        if offset + 8 > len(data):
            raise OscParseError("truncated OSC bundle")
        offset += 8  # timetag; first pass processes bundle elements immediately
        while offset < len(data):
            size, offset = _read_int32(data, offset)
            if size <= 0 or offset + size > len(data):
                raise OscParseError("invalid bundle element size")
            _parse_packet_into(data[offset:offset + size], remote, messages)
            offset += size
        return
    if not address.startswith("/"):
        raise OscParseError("OSC address must start with /")
    if offset >= len(data):
        messages.append(OscMessage(address, [], remote=remote))
        return
    tags, offset = _read_padded_string(data, offset)
    if not tags.startswith(","):
        raise OscParseError("OSC type tag string must start with comma")
    args = []
    for tag in tags[1:]:
        if tag == "i":
            value, offset = _read_int32(data, offset)
            args.append(value)
        elif tag == "f":
            value, offset = _read_float32(data, offset)
            args.append(value)
        elif tag == "s":
            value, offset = _read_padded_string(data, offset)
            args.append(value)
        elif tag == "b":
            value, offset = _read_blob(data, offset)
            args.append(value)
        elif tag == "T":
            args.append(True)
        elif tag == "F":
            args.append(False)
        elif tag in ("N", "I"):
            args.append(None)
        else:
            raise OscParseError(f"unsupported OSC type tag {tag!r}")
    messages.append(OscMessage(address, args, remote=remote))


def pad_osc_string(value):
    raw = str(value).encode("utf-8") + b"\x00"
    return raw + (b"\x00" * ((_align4(len(raw)) - len(raw)) % 4))


def build_osc_message(address, *args):
    tags = [","]
    payload = []
    for arg in args:
        if isinstance(arg, bool):
            tags.append("T" if arg else "F")
        elif isinstance(arg, int):
            tags.append("i")
            payload.append(struct.pack(">i", arg))
        elif isinstance(arg, float):
            tags.append("f")
            payload.append(struct.pack(">f", arg))
        else:
            tags.append("s")
            payload.append(pad_osc_string(str(arg)))
    return pad_osc_string(address) + pad_osc_string("".join(tags)) + b"".join(payload)


def _path_parts(address):
    return [unquote(part) for part in str(address or "").strip().split("/") if part]


def _coerce_number(value):
    if isinstance(value, bool):
        raise OscCommandError("cue number required")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value or "").strip()
    if not text:
        raise OscCommandError("cue number required")
    try:
        number = float(text)
    except ValueError as exc:
        raise OscCommandError("cue number must be numeric") from exc
    if not number.is_integer():
        raise OscCommandError("cue number must be an integer")
    return int(number)


def _coerce_fade(value, default=0.0):
    if value is None:
        return default
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def command_from_message(message):
    address = str(message.address or "")
    args = list(message.args or [])
    parts = _path_parts(address)
    lower = [part.lower() for part in parts]

    if lower in (["go"], ["cue", "go"], ["primus", "cue", "go"]):
        return {"action": "go"}
    if lower in (["stop"], ["cue", "stop"], ["primus", "cue", "stop"]):
        return {"action": "stop"}
    if lower in (["panic"], ["blackout"], ["primus", "blackout"], ["cue", "blackout"], ["primus", "cue", "blackout"]):
        return {"action": "blackout", "fade_time": _coerce_fade(args[0] if args else 0.0)}

    if lower in (["primus", "cue", "goto"], ["cue", "goto"]):
        if not args:
            raise OscCommandError("cue number required")
        return {"action": "goto", "number": _coerce_number(args[0])}
    if lower in (["primus", "cue", "name"], ["cue", "name"]):
        if not args:
            raise OscCommandError("cue name required")
        return {"action": "name", "name": str(args[0]).strip()}

    token = None
    if len(lower) >= 3 and lower[0:2] == ["primus", "cue"]:
        token = parts[2]
    elif len(lower) >= 2 and lower[0] == "cue" and (len(lower) == 2 or lower[-1] in ("start", "go", "fire")):
        token = parts[1]
    if token:
        try:
            return {"action": "goto", "number": _coerce_number(token)}
        except OscCommandError:
            return {"action": "name", "name": token}

    raise OscCommandError(f"unsupported OSC address {address}")


def execute_command(command, cue_list, controller_state):
    action = command.get("action")
    if action == "go":
        cue = cue_list.go(device_groups=controller_state.get_device_groups())
        if cue is not None:
            controller_state.set_playback_source(ControllerState.SOURCE_CONTROLLER)
            return {"ok": True, "action": "go", "cue": cue}
        return {"ok": False, "action": "go", "error": "no cue available"}
    if action == "goto":
        cue = cue_list.go_to_cue(command.get("number"), device_groups=controller_state.get_device_groups())
        if cue is not None:
            controller_state.set_playback_source(ControllerState.SOURCE_CONTROLLER)
            return {"ok": True, "action": "goto", "cue": cue}
        return {"ok": False, "action": "goto", "error": "cue not found"}
    if action == "name":
        cue = cue_list.go_to_cue_name(command.get("name"), device_groups=controller_state.get_device_groups())
        if cue is not None:
            controller_state.set_playback_source(ControllerState.SOURCE_CONTROLLER)
            return {"ok": True, "action": "name", "cue": cue}
        match = cue_list.find_cue_by_external_name(command.get("name"))
        return {"ok": False, "action": "name", "error": match.get("error") or "cue not found"}
    if action == "stop":
        cue_list.stop()
        controller_state.set_playback_source(ControllerState.SOURCE_IDLE)
        return {"ok": True, "action": "stop"}
    if action == "blackout":
        cue_list.blackout(command.get("fade_time", 0.0))
        controller_state.set_playback_source(ControllerState.SOURCE_CONTROLLER)
        return {"ok": True, "action": "blackout", "fade_time": command.get("fade_time", 0.0)}
    return {"ok": False, "action": action or "unknown", "error": "unsupported command"}


def execute_message(message, cue_list, controller_state):
    command = command_from_message(message)
    return execute_command(command, cue_list, controller_state)


def _timestamp_label():
    now = time.time()
    return time.strftime("%H:%M:%S", time.localtime(now)) + f".{int((now % 1) * 1000):03d}"


def _is_loopback_host(host):
    text = str(host or "").strip().lower()
    if not text:
        return False
    if text == "::1":
        return True
    if text.startswith("127."):
        return True
    return False


def _remote_label(remote):
    if not remote:
        return ""
    return f"{remote[0]}:{remote[1]}"


def _packet_preview(data, limit=48):
    packet = bytes(data or b"")
    if not packet:
        return "<empty>"
    shown = packet[:limit]
    hex_text = shown.hex()
    if len(packet) > limit:
        hex_text += "…"
    return f"{len(packet)} bytes {hex_text}"


def _listen_targets():
    try:
        from network_settings import get_network_status
    except ImportError:
        return []
    status = get_network_status()
    targets = []
    seen = set()
    for interface in status.get("interfaces", []):
        if not interface.get("connected"):
            continue
        ip = interface.get("ipv4") or interface.get("source_ip")
        if not ip or ip in seen:
            continue
        seen.add(ip)
        label = interface.get("service") or interface.get("device") or interface.get("type") or "interface"
        targets.append({
            "ip": ip,
            "label": str(label),
            "type": interface.get("type") or "",
        })
    return targets


def _listen_target_strings(port):
    port = int(port or DEFAULT_OSC_SETTINGS["port"])
    return [f"{target['ip']}:{port}" for target in _listen_targets()]


def osc_examples():
    return [
        {"address": "/primus/cue/go", "description": "Advance to the next cue"},
        {"address": "/primus/cue/goto", "args": [1], "description": "Jump to cue number 1"},
        {"address": "/primus/cue/name", "args": ["Blackout"], "description": "Jump to cue named Blackout"},
        {"address": "/cue/blackout/start", "description": "QLab-friendly cue-name slug trigger"},
        {"address": "/primus/cue/stop", "description": "Stop cue playback"},
        {"address": "/primus/blackout", "args": [0.5], "description": "Fade to blackout"},
    ]


class OscControlServer:
    def __init__(self, cue_list, controller_state, settings=None):
        self.cue_list = cue_list
        self.controller_state = controller_state
        self.settings = normalize_settings(settings or load_settings())
        self._thread = None
        self._sock = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._history = deque(maxlen=MAX_HISTORY)
        self._packets_received = 0
        self._packets_local = 0
        self._packets_remote = 0
        self._running = False
        self._last_error = ""
        self._bound = {"host": "", "port": 0}

    def start(self):
        self.stop()
        self.settings = normalize_settings(self.settings)
        if not self.settings.get("enabled"):
            with self._lock:
                self._running = False
                self._last_error = ""
                self._bound = {"host": "", "port": 0}
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="PrimusOSC", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1.0)
        self._thread = None
        self._sock = None
        with self._lock:
            self._running = False

    def update(self, data):
        self.settings = save_settings({**self.settings, **(data or {})})
        self.start()
        return self.status()

    def _run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        sock.settimeout(0.25)
        bind_host = OSC_LISTEN_HOST
        bind_port = int(self.settings["port"])
        try:
            sock.bind((bind_host, bind_port))
        except OSError as exc:
            with self._lock:
                self._running = False
                error_number = getattr(exc, "errno", None)
                if error_number is not None:
                    self._last_error = f"{exc} (errno {error_number})"
                else:
                    self._last_error = str(exc)
                self._bound = {"host": "", "port": 0}
            try:
                sock.close()
            except OSError:
                pass
            return
        self._sock = sock
        host, port = sock.getsockname()[:2]
        with self._lock:
            self._running = True
            self._last_error = ""
            self._bound = {"host": host, "port": port}
        while not self._stop_event.is_set():
            try:
                data, remote = sock.recvfrom(MAX_PACKET_BYTES)
            except socket.timeout:
                continue
            except OSError:
                break
            self._handle_packet(data, remote)
        try:
            sock.close()
        except OSError:
            pass
        with self._lock:
            self._running = False

    def _handle_packet(self, data, remote):
        remote_label = _remote_label(remote)
        is_local = _is_loopback_host(remote[0] if remote else "")
        with self._lock:
            self._packets_received += 1
            if is_local:
                self._packets_local += 1
            else:
                self._packets_remote += 1
        try:
            messages = parse_osc_packet(data, remote=remote_label)
        except OscParseError as exc:
            self._record({
                "ok": False,
                "remote": remote_label,
                "local": is_local,
                "address": "",
                "message": _packet_preview(data),
                "error": str(exc),
            })
            return
        for message in messages:
            try:
                result = execute_message(message, self.cue_list, self.controller_state)
            except OscCommandError as exc:
                result = {"ok": False, "error": str(exc)}
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            entry = {
                "ok": bool(result.get("ok")),
                "remote": remote_label,
                "local": is_local,
                "address": message.address,
                "args": _safe_args(message.args),
                "message": _format_message_label(message.address, message.args),
                "action": result.get("action"),
                "error": result.get("error", ""),
            }
            cue = result.get("cue") if isinstance(result, dict) else None
            if isinstance(cue, dict):
                entry["cue_number"] = cue.get("number")
                entry["cue_name"] = cue.get("name")
            self._record(entry)

    def _record(self, entry):
        row = {
            "time": _timestamp_label(),
            **entry,
        }
        if not row.get("message"):
            row["message"] = _format_message_label(row.get("address"), row.get("args"))
        with self._lock:
            self._history.appendleft(row)
            if row.get("error") and not row.get("ok"):
                self._last_error = row.get("error")

    def status(self):
        with self._lock:
            running = self._running
            last_error = self._last_error
            bound = dict(self._bound)
            history = list(self._history)
            packets_received = self._packets_received
            packets_local = self._packets_local
            packets_remote = self._packets_remote
        port = bound.get("port") or self.settings.get("port") or DEFAULT_OSC_SETTINGS["port"]
        return {
            "settings": normalize_settings(self.settings),
            "enabled": bool(self.settings.get("enabled")),
            "running": running,
            "last_error": last_error,
            "bound": bound,
            "packets_received": packets_received,
            "packets_local": packets_local,
            "packets_remote": packets_remote,
            "listen_targets": _listen_targets(),
            "listen_addresses": _listen_target_strings(port),
            "history": history,
            "examples": osc_examples(),
            "cue_triggers": self.cue_list.external_triggers(),
        }


def _format_message_label(address, args):
    text = str(address or "(packet)")
    safe_args = _safe_args(args)
    if safe_args:
        rendered = []
        for arg in safe_args:
            if isinstance(arg, str):
                rendered.append(json.dumps(arg))
            else:
                rendered.append(str(arg))
        text += " " + " ".join(rendered)
    return text


def _safe_args(args):
    out = []
    for arg in args or []:
        if isinstance(arg, bytes):
            out.append(f"<blob {len(arg)} bytes>")
        else:
            out.append(arg)
    return out
