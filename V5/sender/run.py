#!/usr/bin/env python3
"""
run.py — V5 unified sender entry point (PrimusCentral or RadiusCentral).

Usage:
    python3 run.py
    python3 run.py --product primus
    python3 run.py --product radius --port 8098 --no-browser
    python3 run.py --product primus --frontend devices

If Central is already running, launchers attach by opening the requested view
instead of starting a second server. Use --replace to stop the existing server.

Server control (no product startup required):
    python3 run.py --server-status
    python3 run.py --stop-server [--force]
"""

import os
import sys


def _bootstrap_product_from_argv():
    if "--product" not in sys.argv:
        return
    idx = sys.argv.index("--product")
    if idx + 1 >= len(sys.argv):
        return
    os.environ["PRIMUSV3_SENDER_PRODUCT"] = sys.argv[idx + 1].strip().lower()
    del sys.argv[idx:idx + 2]


def _bootstrap_product_from_bundle():
    if os.environ.get("PRIMUSV3_SENDER_PRODUCT"):
        return
    if not getattr(sys, "frozen", False):
        return
    executable = os.path.basename(sys.executable).lower()
    if "primus" in executable:
        os.environ["PRIMUSV3_SENDER_PRODUCT"] = "primus"
    elif "radius" in executable:
        os.environ["PRIMUSV3_SENDER_PRODUCT"] = "radius"
    elif "device" in executable:
        os.environ["PRIMUSV3_SENDER_PRODUCT"] = "primus"
        os.environ["PRIMUSV3_DEFAULT_FRONTEND"] = "devices"


_bootstrap_product_from_argv()
_bootstrap_product_from_bundle()

from paths import sender_product


def _server_control_commands():
    """Handle --server-status / --stop-server and exit.

    Deliberately ahead of any product startup: these exist so an operator can
    inspect or clear a running Central without launching one, which is the
    supported way out of an orphaned server holding the port.
    """
    want_status = "--server-status" in sys.argv
    want_stop = "--stop-server" in sys.argv
    if not (want_status or want_stop):
        return

    import json
    import urllib.request

    from central_launcher import (
        find_running_central_server,
        read_registry,
        stop_running_central,
    )

    found = find_running_central_server()
    if not found:
        print("No Central server is running.")
        sys.exit(0 if want_status else 1)
    port, runtime = found
    # The registry records where the server is actually reachable; only
    # fall back to loopback when it has nothing to say.
    registry = read_registry() or {}
    host = str(registry.get("host") or "127.0.0.1")

    if want_status:
        status = None
        try:
            with urllib.request.urlopen(
                    f"http://{host}:{port}/api/server/status", timeout=2.0) as response:
                status = json.loads(response.read().decode("utf-8"))
        except Exception:
            status = None
        if status is None:
            # Older server without /api/server/status still answers /api/runtime.
            status = dict(runtime)
            status["port"] = port
        print(f"Central server running on port {status.get('port', port)}")
        for key in ("pid", "product", "app_version", "monitor_only", "lan_enabled",
                    "client_session_count", "live_output", "uptime_seconds"):
            if key in status:
                print(f"  {key}: {status[key]}")
        sys.exit(0)

    force = "--force" in sys.argv
    ok, message = stop_running_central(host=host, port=port, force=force)
    if ok:
        print(f"Stopped Central server on port {port}.")
        sys.exit(0)
    print(f"Could not stop Central server on port {port}: {message}")
    if not force:
        print("Retry with --force to stop it anyway.")
    sys.exit(1)


def _migrate_radius_app_data():
    """Copy standalone-RadiusCentral app data into the unified backend's tree.

    Packaged RadiusCentral used to keep its data under RadiusV3/…; the
    unified backend lives under PrimusV3/…. Copy (never move) the radius
    state, audio cue sheet, and audio library across the first time, so an
    existing fleet and library survive the switch. Source runs share one
    directory and are untouched.
    """
    import shutil
    from paths import data_path
    try:
        dest_state = data_path(".radius_state.json")
    except Exception:
        return
    marker = os.sep + "PrimusV3" + os.sep
    if marker not in dest_state:
        return
    dest_dir = os.path.dirname(dest_state)
    legacy_dir = dest_dir.replace(marker, os.sep + "RadiusV3" + os.sep)
    if legacy_dir == dest_dir or not os.path.isdir(legacy_dir):
        return
    try:
        for name in (".radius_state.json", "audio_cues.json"):
            src = os.path.join(legacy_dir, name)
            dst = os.path.join(dest_dir, name)
            if os.path.isfile(src) and not os.path.exists(dst):
                os.makedirs(dest_dir, exist_ok=True)
                shutil.copy2(src, dst)
        src_audio = os.path.join(legacy_dir, "audio")
        dst_audio = os.path.join(dest_dir, "audio")
        if os.path.isdir(src_audio) and not os.path.isdir(dst_audio):
            shutil.copytree(src_audio, dst_audio)
    except OSError as exc:
        print(f"WARNING: could not migrate RadiusCentral data: {exc}")


def main():
    _server_control_commands()
    product = sender_product()
    if product == "radius" and os.environ.get("PRIMUSV3_RADIUS_STANDALONE") != "1":
        # RadiusCentral is a launcher onto the unified backend: one server
        # process (primus product) hosts the Primus, Radius, and Devices
        # frontends, holds one device list, and owns the single telemetry
        # listener on the Watch port — the same pattern DeviceManager uses.
        # PRIMUSV3_RADIUS_STANDALONE=1 is the escape hatch back to the
        # legacy separate backend.
        os.environ["PRIMUSV3_SENDER_PRODUCT"] = "primus"
        os.environ.setdefault("PRIMUSV3_DEFAULT_FRONTEND", "radius")
        if "--frontend" not in sys.argv:
            sys.argv.extend(["--frontend", "radius"])
        _migrate_radius_app_data()
        from run_primus import main as primus_main
        primus_main()
        return
    if product == "primus":
        from run_primus import main as primus_main
        primus_main()
    else:
        from run_radius import main as radius_main
        radius_main()


if __name__ == "__main__":
    main()
