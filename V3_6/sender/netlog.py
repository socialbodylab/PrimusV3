"""
netlog.py — Thread-safe in-memory ring buffer for network event logging.
"""

import threading
import time

_MAX_ENTRIES = 1000
_lock = threading.Lock()
_entries = []
_next_id = 1
_fps_last_logged = {}   # ip -> monotonic time of last logged fps entry


def log(direction, msg_type, summary, detail=None):
    """Record a network event.

    direction: 'IN' or 'OUT'
    msg_type:  short tag (e.g. 'audio_cmd', 'ftp_upload', 'discovery')
    summary:   human-readable one-liner
    detail:    optional dict with extra fields (not shown in table, available in export)
    """
    global _next_id
    entry = {
        "id":      0,
        "ts":      time.time(),
        "dir":     direction,
        "type":    msg_type,
        "summary": summary,
    }
    if detail is not None:
        entry["detail"] = detail
    with _lock:
        entry["id"] = _next_id
        _next_id += 1
        _entries.append(entry)
        if len(_entries) > _MAX_ENTRIES:
            del _entries[0]


def log_fps(ip, fps, pkt_rate):
    """Log an FPS telemetry event, sampled to at most once per second per IP."""
    now = time.monotonic()
    with _lock:
        last = _fps_last_logged.get(ip, 0)
        if now - last < 1.0:
            return
        _fps_last_logged[ip] = now
    log("IN", "fps_telemetry", f"{fps} fps / {pkt_rate} pkt/s ← {ip}")


def get_entries(since_id=0):
    """Return list of entries with id > since_id."""
    with _lock:
        return [e for e in _entries if e["id"] > since_id]


def clear():
    global _entries, _next_id, _fps_last_logged
    with _lock:
        _entries = []
        _next_id = 1
        _fps_last_logged = {}
