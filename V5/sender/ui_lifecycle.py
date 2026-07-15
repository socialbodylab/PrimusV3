"""Shared UI lifecycle helpers for packaged Central server shutdown."""

import time

UI_CLOSE_GRACE_SECONDS = 5.0
UI_HEARTBEAT_TIMEOUT_SECONDS = 45.0
UI_INITIAL_HEARTBEAT_TIMEOUT_SECONDS = 30.0


def init_server(server):
    server.ui_sessions = {}
    server.ui_lifecycle_started_at = time.monotonic()
    server.ui_last_session_closed_at = None


def _session_id(value):
    text = str(value or "").strip()
    return text or "default"


def touch_session(server, session_id):
    if not getattr(server, "ui_lifecycle_enabled", False):
        return
    sessions = getattr(server, "ui_sessions", None)
    if sessions is None:
        init_server(server)
        sessions = server.ui_sessions
    sessions[_session_id(session_id)] = time.monotonic()
    server.ui_last_session_closed_at = None


def close_session(server, session_id):
    if not getattr(server, "ui_lifecycle_enabled", False):
        return
    sessions = getattr(server, "ui_sessions", None)
    if not sessions:
        return
    sessions.pop(_session_id(session_id), None)
    if not sessions:
        server.ui_last_session_closed_at = time.monotonic()


def _prune_sessions(server, now):
    sessions = getattr(server, "ui_sessions", None) or {}
    stale_after = UI_HEARTBEAT_TIMEOUT_SECONDS
    active = {
        session_id: last_seen
        for session_id, last_seen in sessions.items()
        if now - last_seen < stale_after
    }
    server.ui_sessions = active
    return active


def monitor(server, app_name="Central", live_output_fn=None):
    """Shut down when every UI window has closed and output is idle."""
    live_output_fn = live_output_fn or (lambda: False)
    while getattr(server, "ui_lifecycle_enabled", False):
        now = time.monotonic()
        active = _prune_sessions(server, now)
        if active:
            time.sleep(0.25)
            continue

        started = getattr(server, "ui_lifecycle_started_at", now)
        if now - started < UI_INITIAL_HEARTBEAT_TIMEOUT_SECONDS:
            time.sleep(0.25)
            continue

        closed_at = getattr(server, "ui_last_session_closed_at", None)
        if closed_at is not None and now - closed_at < UI_CLOSE_GRACE_SECONDS:
            time.sleep(0.25)
            continue

        if live_output_fn(server):
            time.sleep(0.25)
            continue

        print(f"All UI windows closed; shutting down {app_name}.")
        server.ui_lifecycle_enabled = False
        server.shutdown()
        return