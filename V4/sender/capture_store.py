"""capture_store.py — Thread-safe capture buffer and JSONL file writer."""

import json
import os
import sys
import threading
import time
from datetime import datetime

_MAX_RING = 5000
_lock = threading.RLock()
_entries = []
_next_id = 1
_recording = False
_session = None
_file_handle = None
_full_payload = False
_last_key_ts = {}


def _app_support_base():
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support")
    if os.name == "nt":
        return os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def capture_dir():
    path = os.path.join(_app_support_base(), "PrimusV3", "V4", "captures")
    os.makedirs(path, exist_ok=True)
    return path


def _new_session_path():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return os.path.join(capture_dir(), f"capture-{stamp}.jsonl")


class CaptureSession:
    def __init__(self, path, mode, device_ip, interface, show_setup=None, expected_universe=None):
        self.path = path
        self.mode = mode
        self.device_ip = device_ip
        self.interface = interface
        self.show_setup = show_setup or {}
        self.expected_universe = expected_universe
        self.started_at = time.time()
        self.stopped_at = None
        self.packet_count = 0


def status():
    with _lock:
        session = None
        if _session:
            session = {
                "path": _session.path,
                "mode": _session.mode,
                "device_ip": _session.device_ip,
                "interface": _session.interface,
                "show_setup": _session.show_setup,
                "expected_universe": _session.expected_universe,
                "started_at": _session.started_at,
                "stopped_at": _session.stopped_at,
                "packet_count": _session.packet_count,
            }
        return {
            "recording": _recording,
            "full_payload": _full_payload,
            "session": session,
        }


def start_recording(mode, device_ip, interface="", full_payload=False, show_setup=None, expected_universe=None):
    global _recording, _session, _file_handle, _full_payload, _entries, _next_id, _last_key_ts
    with _lock:
        if _recording:
            raise RuntimeError("capture already running")
        _full_payload = bool(full_payload)
        path = _new_session_path()
        _file_handle = open(path, "w", encoding="utf-8")
        _session = CaptureSession(
            path, mode, device_ip, interface,
            show_setup=show_setup or {},
            expected_universe=expected_universe,
        )
        _entries = []
        _next_id = 1
        _last_key_ts = {}
        _recording = True
        return status()


def stop_recording():
    global _recording, _session, _file_handle
    with _lock:
        if not _recording:
            return status()
        _recording = False
        if _session:
            _session.stopped_at = time.time()
        if _file_handle:
            _file_handle.close()
            _file_handle = None
        return status()


def record_event(event):
    """Append one parsed capture event; compute delta_ms per (src, universe)."""
    global _next_id
    with _lock:
        if not _recording:
            return None
        entry = dict(event)
        entry["id"] = _next_id
        _next_id += 1
        if entry.get("ts") is None:
            entry["ts"] = time.time()
        key = (entry.get("src", ""), entry.get("universe"))
        prev_ts = _last_key_ts.get(key)
        if prev_ts is not None:
            entry["delta_ms"] = round((entry["ts"] - prev_ts) * 1000.0, 2)
        else:
            entry["delta_ms"] = None
        if key[1] is not None:
            _last_key_ts[key] = entry["ts"]
        _entries.append(entry)
        if len(_entries) > _MAX_RING:
            del _entries[0]
        if _session:
            _session.packet_count += 1
        if _file_handle:
            _file_handle.write(json.dumps(entry, separators=(",", ":")) + "\n")
            _file_handle.flush()
        return entry


def get_events(since_id=0):
    with _lock:
        return [e for e in _entries if e.get("id", 0) > since_id]


def export_session_path():
    with _lock:
        if _session:
            return _session.path
        return None
