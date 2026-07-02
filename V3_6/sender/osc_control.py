"""Inbound OSC control for Primus cue playback.

The sender stays dependency-free, so this module implements the small OSC 1.0
subset needed for QLab-style cue triggers using only the Python standard
library.
"""

import copy
import json
import os
import socket
import struct
import threading
import time
from collections import deque
from urllib.parse import unquote

import netlog
from paths import state_file
from state import ControllerState


STATE_KEY = "osc_control"
DEFAULT_OSC_SETTINGS = {
    "enabled": True,
    "host": "0.0.0.0",
    "port": 53001,
}
MAX_PACKET_BYTES = 65535
MAX_HISTORY = 20


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


def normalize_settings(settings=None):
    out = copy.deepcopy(DEFAULT_OSC_SETTINGS)
    if not isinstance(settings, dict):
        return out
    out["enabled"] = bool(settings.get("enabled", out["enabled"]))
    host = str(settings.get("host") or out["host"]).strip()
    out["host"] = host or DEFAULT_OSC_SETTINGS["host"]
    try:
        port = int(settings.get("port", out["port"]))
    except (TypeError, ValueError):
        port = out["port"]
    out["port"] = max(0, min(65535, port))
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
    if lower in (["hello"], ["radius", "hello"], ["primus", "hello"]):
        return {"action": "hello"}

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


def execute_radius_command(command, audio_dispatch):
    """Execute an OSC command in Radius (audio-only) mode.

    audio_dispatch(action, number=None) -> dict
      action "fire"  — fire audio cue by number
      action "stop"  — stop all audio
      action "hello" — identify device (test tone + display)
    """
    action = command.get("action")
    if action == "goto":
        number = command.get("number")
        if number is None:
            return {"ok": False, "action": "audio_fire", "error": "cue number required"}
        audio_dispatch("fire", number)
        return {"ok": True, "action": "audio_fire", "number": number}
    if action == "stop":
        audio_dispatch("stop")
        return {"ok": True, "action": "audio_stop"}
    if action == "hello":
        audio_dispatch("hello")
        return {"ok": True, "action": "audio_hello"}
    return {"ok": False, "action": action or "unknown", "error": "unsupported command in radius mode"}


def execute_message(message, cue_list, controller_state):
    command = command_from_message(message)
    return execute_command(command, cue_list, controller_state)


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
        self._running = False
        self._last_error = ""
        self._bound = {"host": "", "port": 0}
        self._audio_dispatch = None

    def set_audio_dispatch(self, fn):
        """Enable radius mode: route /cue/N, /stop, /hello to fn instead of LED cues.

        fn(action, number=None) where action is "fire", "stop", or "hello".
        Pass None to disable radius mode and restore LED cue routing.
        """
        self._audio_dispatch = fn

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
        sock.settimeout(0.25)
        try:
            sock.bind((self.settings["host"], self.settings["port"]))
        except OSError as exc:
            with self._lock:
                self._running = False
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
        remote_label = f"{remote[0]}:{remote[1]}" if remote else ""
        try:
            messages = parse_osc_packet(data, remote=remote_label)
        except OscParseError as exc:
            self._record({"ok": False, "remote": remote_label, "address": "", "error": str(exc)})
            return
        for message in messages:
            try:
                if self._audio_dispatch is not None:
                    command = command_from_message(message)
                    result  = execute_radius_command(command, self._audio_dispatch)
                else:
                    result = execute_message(message, self.cue_list, self.controller_state)
            except OscCommandError as exc:
                result = {"ok": False, "error": str(exc)}
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            entry = {
                "ok": bool(result.get("ok")),
                "remote": remote_label,
                "address": message.address,
                "args": _safe_args(message.args),
                "action": result.get("action"),
                "error": result.get("error", ""),
            }
            cue = result.get("cue") if isinstance(result, dict) else None
            if isinstance(cue, dict):
                entry["cue_number"] = cue.get("number")
                entry["cue_name"] = cue.get("name")
            self._record(entry)
            args_str = " " + str(_safe_args(message.args)) if message.args else ""
            status = "✓" if entry["ok"] else f"✗ {entry['error']}"
            netlog.log("IN", "osc", f"OSC {message.address}{args_str} ← {remote_label} {status}")

    def _record(self, entry):
        row = {
            "time": time.strftime("%H:%M:%S"),
            **entry,
        }
        with self._lock:
            self._history.appendleft(row)
            if row.get("error"):
                self._last_error = row.get("error")

    def status(self):
        with self._lock:
            running = self._running
            last_error = self._last_error
            bound = dict(self._bound)
            history = list(self._history)
        return {
            "settings": normalize_settings(self.settings),
            "enabled": bool(self.settings.get("enabled")),
            "running": running,
            "last_error": last_error,
            "bound": bound,
            "history": history,
            "examples": osc_examples(),
            "cue_triggers": self.cue_list.external_triggers() if self.cue_list else [],
        }


def _safe_args(args):
    out = []
    for arg in args or []:
        if isinstance(arg, bytes):
            out.append(f"<blob {len(arg)} bytes>")
        else:
            out.append(arg)
    return out
