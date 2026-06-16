#!/usr/bin/env python3
"""
run.py — Radius Central (V4) entry point.

Usage:
    python3 run.py
    python3 run.py --port 8080
    python3 run.py --no-browser
"""

import argparse
import errno
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser

from artnet import RadiusTelemetryListener
from paths import ensure_runtime_data, is_bundled, log_path
from radius_state import RadiusState
from server import create_server


DEFAULT_HTTP_PORT = 8080
DEDICATED_BROWSER_PROFILE_ROOT = "radiusv4-browser-profiles"
DEDICATED_BROWSER_PID_FILE = "browser.pid"
UI_CLOSE_GRACE_SECONDS = 2.0
UI_HEARTBEAT_TIMEOUT_SECONDS = 45.0
UI_INITIAL_HEARTBEAT_TIMEOUT_SECONDS = 30.0
_MACOS_ACTIVITY_TOKEN = None


def _handle_sigterm(signum, frame):
    raise KeyboardInterrupt


def _configure_app_logging():
    if not is_bundled():
        return
    try:
        log_file = open(log_path("sender.log"), "a", buffering=1)
    except OSError:
        return
    sys.stdout = log_file
    sys.stderr = log_file
    print()
    print(f"RadiusCentral started {time.strftime('%Y-%m-%d %H:%M:%S')}")


def _begin_macos_low_latency_activity():
    if sys.platform != "darwin":
        return None
    if os.environ.get("RADIUSV4_DISABLE_MACOS_ACTIVITY") == "1":
        return None
    try:
        caffeinate = shutil.which("caffeinate") or "/usr/bin/caffeinate"
        if not os.path.exists(caffeinate):
            return None
        process = subprocess.Popen(
            [caffeinate, "-dimsu", "-w", str(os.getpid())],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("macOS caffeinate activity enabled.")
        return process
    except Exception as exc:
        print(f"macOS low-latency activity unavailable: {exc}")
        return None


def _kill_existing():
    my_pid = os.getpid()
    sender_dir = os.path.dirname(os.path.abspath(__file__))
    script_patterns = {
        os.path.join(sender_dir, "run.py"),
        "V4/sender/run.py",
        "RadiusCentral",
    }
    try:
        out = subprocess.check_output(
            ["ps", "-axo", "pid=,command="], text=True, stderr=subprocess.DEVNULL
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    killed = []
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        pid = int(parts[0])
        command = parts[1]
        if pid == my_pid:
            continue
        if not any(pattern in command for pattern in script_patterns):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
            print(f"Replacing previous sender instance (PID {pid})")
        except ProcessLookupError:
            pass
    for pid in killed:
        for _ in range(20):
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except ProcessLookupError:
                break


def _browser_profile_root():
    return os.path.join(tempfile.gettempdir(), DEDICATED_BROWSER_PROFILE_ROOT)


def _new_browser_profile_dir():
    profile_name = f"profile-{os.getpid()}-{int(time.time() * 1000)}"
    return os.path.join(_browser_profile_root(), profile_name)


def _browser_pid_path(profile_root):
    return os.path.join(profile_root, DEDICATED_BROWSER_PID_FILE)


def _add_browser_candidate(candidates, seen, label, executable):
    if not executable:
        return
    path = executable if os.path.isabs(executable) else shutil.which(executable)
    if not path:
        return
    path = os.path.abspath(os.path.expanduser(path))
    if path in seen:
        return
    seen.add(path)
    candidates.append((label, path))


def _chromium_browser_candidates():
    candidates = []
    seen = set()

    _add_browser_candidate(candidates, seen, "configured browser", os.environ.get("RADIUS_BROWSER"))
    _add_browser_candidate(candidates, seen, "configured browser", os.environ.get("PRIMUS_BROWSER"))

    if sys.platform == "darwin":
        mac_apps = [
            ("Google Chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            ("Microsoft Edge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            ("Brave Browser", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
            ("Chromium", "/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ]
        for label, path in mac_apps:
            _add_browser_candidate(candidates, seen, label, path)
    elif os.name == "nt":
        roots = [
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        windows_apps = [
            ("Google Chrome", ("Google", "Chrome", "Application", "chrome.exe")),
            ("Microsoft Edge", ("Microsoft", "Edge", "Application", "msedge.exe")),
            ("Brave Browser", ("BraveSoftware", "Brave-Browser", "Application", "brave.exe")),
        ]
        for root in roots:
            if not root:
                continue
            for label, parts in windows_apps:
                _add_browser_candidate(candidates, seen, label, os.path.join(root, *parts))
    else:
        linux_apps = [
            ("Google Chrome", "google-chrome"),
            ("Google Chrome", "google-chrome-stable"),
            ("Microsoft Edge", "microsoft-edge"),
            ("Brave Browser", "brave-browser"),
            ("Chromium", "chromium"),
            ("Chromium", "chromium-browser"),
        ]
        for label, command in linux_apps:
            _add_browser_candidate(candidates, seen, label, command)

    path_apps = [
        ("Google Chrome", "chrome"),
        ("Google Chrome", "google-chrome"),
        ("Microsoft Edge", "msedge"),
        ("Brave Browser", "brave"),
        ("Brave Browser", "brave-browser"),
        ("Chromium", "chromium"),
        ("Chromium", "chromium-browser"),
    ]
    for label, command in path_apps:
        _add_browser_candidate(candidates, seen, label, command)

    return candidates


def _terminate_process(pid, timeout=1.0):
    if pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except OSError:
            return
        time.sleep(0.05)
    if hasattr(signal, "SIGKILL"):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def _terminate_tracked_browser_process(profile_root):
    try:
        with open(_browser_pid_path(profile_root), "r", encoding="utf-8") as pid_file:
            pid_text = pid_file.read().strip()
        if pid_text:
            _terminate_process(int(pid_text))
    except (FileNotFoundError, OSError, ValueError):
        return


def _terminate_dedicated_browser_processes(profile_root):
    profile_root = os.path.abspath(profile_root)
    marker = "--user-data-dir="
    _terminate_tracked_browser_process(profile_root)
    if os.name == "nt":
        return
    try:
        out = subprocess.check_output(
            ["ps", "-axo", "pid=,command="], text=True, stderr=subprocess.DEVNULL
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    killed = []
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        pid = int(parts[0])
        command = parts[1]
        if marker not in command or profile_root not in command:
            continue
        killed.append(pid)
    for pid in killed:
        _terminate_process(pid)


def _cleanup_dedicated_browser_profiles(profile_root):
    _remove_dedicated_browser_profiles(profile_root)
    os.makedirs(profile_root, exist_ok=True)


def _remove_dedicated_browser_profiles(profile_root):
    _terminate_dedicated_browser_processes(profile_root)
    try:
        shutil.rmtree(profile_root)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _launch_dedicated_browser(url):
    candidates = _chromium_browser_candidates()
    if not candidates:
        return None

    profile_root = _browser_profile_root()
    _cleanup_dedicated_browser_profiles(profile_root)
    profile_dir = _new_browser_profile_dir()
    os.makedirs(profile_dir, exist_ok=True)
    for label, executable in candidates:
        args = [
            executable,
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            f"--app={url}",
        ]
        popen_kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            )
        else:
            popen_kwargs["start_new_session"] = True
        try:
            browser_process = subprocess.Popen(args, **popen_kwargs)
        except OSError:
            continue
        try:
            with open(_browser_pid_path(profile_root), "w", encoding="utf-8") as pid_file:
                pid_file.write(str(browser_process.pid))
        except OSError:
            pass
        return f"opened {label} app window"
    return None


def _open_browser(url):
    dedicated_result = _launch_dedicated_browser(url)
    if dedicated_result:
        return dedicated_result
    webbrowser.open_new(url)
    return "opened default browser"


def _create_server_with_fallback(host, port, state, ui_lifecycle_enabled):
    try:
        return create_server(host, port, state, ui_lifecycle_enabled=ui_lifecycle_enabled)
    except OSError as exc:
        if port == 0:
            raise
        if exc.errno not in (errno.EADDRINUSE, 48, 98):
            raise
        print(f"Port {port} is busy; using an auto-selected port instead.")
        return create_server(host, 0, state, ui_lifecycle_enabled=ui_lifecycle_enabled)


def _ui_lifecycle_monitor(server):
    while getattr(server, "ui_lifecycle_enabled", False):
        now = time.monotonic()
        close_requested_at = getattr(server, "ui_close_requested_at", None)
        last_heartbeat = getattr(server, "ui_last_heartbeat", None)
        if (close_requested_at is not None
                and (last_heartbeat is None or last_heartbeat < close_requested_at)
                and now - close_requested_at >= UI_CLOSE_GRACE_SECONDS):
            print("UI window closed; shutting down RadiusCentral.")
            server.ui_lifecycle_enabled = False
            server.shutdown()
            return

        if last_heartbeat is None:
            baseline = getattr(server, "ui_lifecycle_started_at", now)
            timeout = UI_INITIAL_HEARTBEAT_TIMEOUT_SECONDS
        else:
            baseline = last_heartbeat
            timeout = UI_HEARTBEAT_TIMEOUT_SECONDS
        if now - baseline >= timeout:
            print("UI heartbeat stopped; shutting down RadiusCentral.")
            server.ui_lifecycle_enabled = False
            server.shutdown()
            return

        time.sleep(0.25)


def main():
    global _MACOS_ACTIVITY_TOKEN
    parser = argparse.ArgumentParser(description="Radius Central V4")
    parser.add_argument("--port", type=int, default=DEFAULT_HTTP_PORT,
                        help=f"HTTP port (default {DEFAULT_HTTP_PORT}; 0 = auto-select)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Print the URL without opening the browser")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_sigterm)
    ensure_runtime_data()
    _configure_app_logging()
    _MACOS_ACTIVITY_TOKEN = _begin_macos_low_latency_activity()
    _kill_existing()

    telemetry_listener = RadiusTelemetryListener()
    telemetry_thread = threading.Thread(target=telemetry_listener.run, daemon=True)
    telemetry_thread.start()

    state = RadiusState(telemetry_listener=telemetry_listener)
    print("Restoring saved Radius devices...")
    state.restore_devices()

    ui_lifecycle_enabled = is_bundled() and not args.no_browser
    browser_profile_root = _browser_profile_root() if not args.no_browser else None
    server = _create_server_with_fallback(
        "127.0.0.1", args.port, state, ui_lifecycle_enabled=ui_lifecycle_enabled)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}"

    if ui_lifecycle_enabled:
        ui_thread = threading.Thread(
            target=_ui_lifecycle_monitor, args=(server,), daemon=True)
        ui_thread.start()

    print("Radius Central V4")
    print(f"  URL: {url}")
    print(f"  Devices: {len(state.devices)}")
    if args.no_browser:
        print("  Browser: not opened (--no-browser)")
    else:
        print(f"  Browser: {_open_browser(url)}")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        server.ui_lifecycle_enabled = False
        state.shutdown()
        telemetry_listener.stop()
        server.server_close()
        if browser_profile_root:
            _remove_dedicated_browser_profiles(browser_profile_root)
        if _MACOS_ACTIVITY_TOKEN is not None:
            _MACOS_ACTIVITY_TOKEN.terminate()
        print("Done.")


if __name__ == "__main__":
    main()
