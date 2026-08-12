"""Shared UI lifecycle helpers for packaged Central server shutdown."""

import time

UI_CLOSE_GRACE_SECONDS = 5.0
# Chrome throttles timers in backgrounded windows to once per MINUTE after a
# few minutes hidden — a 45 s timeout auto-quit the packaged Central when the
# operator merely minimized it during a show. The timeout must sit above that
# 60 s throttle floor with margin.
UI_HEARTBEAT_TIMEOUT_SECONDS = 150.0
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


UI_REOPEN_INTERVAL_SECONDS = 30.0


def monitor(server, app_name="Central", live_output_fn=None):
    """Shut down when every UI window has closed and output is idle."""
    live_output_fn = live_output_fn or (lambda _server: False)
    last_reopen_at = 0.0
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

        # A mixer preview is UI-editing state — with every window gone it is
        # a zombie source that would block shutdown forever. Release it;
        # designer GO LIVE and controller cues are real show output and
        # rightly keep the server alive below.
        state = getattr(server, "controller_state", None)
        release = getattr(state, "release_ui_preview", None)
        if callable(release):
            try:
                if release():
                    print("Last UI window closed; released mixer preview.")
            except Exception:
                pass

        if live_output_fn(server):
            # Output is genuinely live, so quitting is forbidden — but a
            # windowless resident app is a trap: macOS swallows a relaunch
            # as "activate the running app", which shows nothing. Reopen
            # our own window instead of lurking headless.
            reopen = getattr(server, "ui_reopen_callback", None)
            if callable(reopen) and now - last_reopen_at >= UI_REOPEN_INTERVAL_SECONDS:
                last_reopen_at = now
                try:
                    print(
                        "UI windows closed while output is live; reopening "
                        f"the {app_name} window."
                    )
                    reopen()
                except Exception:
                    pass
            time.sleep(0.25)
            continue

        print(f"All UI windows closed; shutting down {app_name}.")
        server.ui_lifecycle_enabled = False
        server.shutdown()
        return