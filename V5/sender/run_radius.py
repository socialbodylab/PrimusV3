#!/usr/bin/env python3
"""
run.py — Radius Central (V5) entry point.

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
import threading
import time

from artnet import RadiusTelemetryListener, FPS_LISTEN_PORT
from paths import app_version, ensure_runtime_data, is_bundled, log_path, sender_product
from network_settings import get_lane_ports
from radius_state import RadiusState
from central_launcher import (
    CentralPortInUseByCentral,
    MISMATCH_WRONG_PRODUCT,
    frontend_path_for,
    probe_central_server,
    register_central_server,
    try_attach_before_start,
    unregister_central_server,
)
from launcher_dialog import choose as dialog_choose
from browser_launcher import DedicatedBrowser
from ui_focus import UiFocusServer
from server import create_server
from ui_lifecycle import monitor as ui_lifecycle_monitor


DEFAULT_HTTP_PORT = 8080
DEDICATED_BROWSER_PROFILE_ROOT = "radiusv4-browser-profiles"
_dedicated_browser = DedicatedBrowser(
    DEDICATED_BROWSER_PROFILE_ROOT,
    ("RADIUS_BROWSER", "PRIMUS_BROWSER"),
)
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
    if (
        os.environ.get("RADIUSV5_DISABLE_MACOS_ACTIVITY") == "1"
        or os.environ.get("RADIUSV4_DISABLE_MACOS_ACTIVITY") == "1"
    ):
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
        os.path.join(sender_dir, "run_primus.py"),
        os.path.join(sender_dir, "run_radius.py"),
        "V5/sender/run.py",
        "V5/sender/run_primus.py",
        "V5/sender/run_radius.py",
        "PrimusCentral",
        "RadiusCentral",
        "DeviceManager",
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
    return _dedicated_browser.profile_root()


def _remove_dedicated_browser_profiles(profile_root):
    _dedicated_browser.remove_profiles()


def _open_browser(url, attach=False):
    return _dedicated_browser.open(url, attach=attach)


def _create_server_with_fallback(host, port, state, ui_lifecycle_enabled):
    try:
        return create_server(host, port, state, ui_lifecycle_enabled=ui_lifecycle_enabled)
    except OSError as exc:
        if port == 0:
            raise
        if exc.errno not in (errno.EADDRINUSE, 48, 98):
            raise
        runtime = probe_central_server(host, port)
        if runtime:
            raise CentralPortInUseByCentral(port, runtime)
        print(f"Port {port} is busy; using an auto-selected port instead.")
        return create_server(host, 0, state, ui_lifecycle_enabled=ui_lifecycle_enabled)


def _ui_has_live_output(server):
    state = getattr(server, "radius_state", None)
    if state is None:
        return False
    try:
        return bool(state.has_live_playback())
    except Exception:
        # Never report "idle" on error: that would let the server quit during a
        # cue. Mirrors the same conservative choice on the Primus side.
        return True


def _ui_lifecycle_monitor(server):
    ui_lifecycle_monitor(
        server, app_name="RadiusCentral", live_output_fn=_ui_has_live_output)


def _attach_mismatch_handler():
    """RadiusCentral must never be served from a non-Radius backend.

    Attaching anyway produced a /radius UI backed by Primus state: HTTP 200,
    no audio endpoints, no radius_state loaded, and nothing to tell the user.
    """
    def handler(mismatch, port, runtime):
        if mismatch["reason"] != MISMATCH_WRONG_PRODUCT:
            return "abort"
        backend = mismatch.get("backend_product") or "another product"
        choice = dialog_choose(
            "RadiusCentral",
            f"A {backend} Central server is already running on port {port}.\n\n"
            "RadiusCentral needs its own backend and cannot share that one yet, "
            "so its audio and FTP controls would not work.\n\n"
            f"Quit the {backend} server first, or open its interface instead.",
            [f"Open {backend} interface", "Cancel"],
            "Cancel",
        )
        return "attach" if choice.startswith("Open ") else "abort"

    return handler


def main():
    global _MACOS_ACTIVITY_TOKEN
    parser = argparse.ArgumentParser(description="Radius Central V5")
    parser.add_argument("--port", type=int, default=DEFAULT_HTTP_PORT,
                        help=f"HTTP port (default {DEFAULT_HTTP_PORT}; 0 = auto-select)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Print the URL without opening the browser")
    parser.add_argument(
        "--frontend",
        choices=["primus", "radius", "devices"],
        default=None,
        help="Web UI to open (default: /radius for this launcher)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Stop any running Central server and start a new one",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_sigterm)
    ensure_runtime_data()
    _configure_app_logging()

    frontend_path = frontend_path_for(args.frontend, sender_product())
    if not args.replace and try_attach_before_start(
        port=args.port,
        frontend_path=frontend_path,
        no_browser=args.no_browser,
        open_browser=_open_browser,
        launcher_name="Radius Central V5",
        need_product="radius",
        on_mismatch=_attach_mismatch_handler(),
    ):
        return

    _MACOS_ACTIVITY_TOKEN = _begin_macos_low_latency_activity()
    if args.replace:
        _kill_existing()

    try:
        watch_port = int(get_lane_ports().get("port_watch") or FPS_LISTEN_PORT)
    except Exception:
        watch_port = FPS_LISTEN_PORT
    telemetry_listener = RadiusTelemetryListener(listen_port=watch_port)
    telemetry_thread = threading.Thread(target=telemetry_listener.run, daemon=True)
    telemetry_thread.start()

    state = RadiusState(telemetry_listener=telemetry_listener)
    print("Restoring saved Radius devices...")
    state.restore_devices()

    ui_lifecycle_enabled = is_bundled() and not args.no_browser
    browser_profile_root = _browser_profile_root() if not args.no_browser else None
    ui_focus_server = None
    try:
        server = _create_server_with_fallback(
            "127.0.0.1", args.port, state, ui_lifecycle_enabled=ui_lifecycle_enabled)
    except CentralPortInUseByCentral:
        if try_attach_before_start(
            port=args.port,
            frontend_path=frontend_path,
            no_browser=args.no_browser,
            open_browser=_open_browser,
            launcher_name="Radius Central V5",
            need_product="radius",
            on_mismatch=_attach_mismatch_handler(),
        ):
            telemetry_listener.stop()
            return
        raise
    port = server.server_address[1]
    server.live_output_fn = _ui_has_live_output
    if not args.no_browser:
        server.ui_focus_callback = _dedicated_browser.focus
        ui_focus_server = UiFocusServer(port, _dedicated_browser.focus)
        ui_focus_server.start()
    url = f"http://127.0.0.1:{port}{frontend_path}"
    register_central_server(
        port, sender_product(), app_version=app_version())

    if ui_lifecycle_enabled:
        ui_thread = threading.Thread(
            target=_ui_lifecycle_monitor, args=(server,), daemon=True)
        ui_thread.start()

    print("Radius Central V5")
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
        if ui_focus_server is not None:
            ui_focus_server.stop()
        unregister_central_server()
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
