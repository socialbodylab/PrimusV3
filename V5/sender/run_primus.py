#!/usr/bin/env python3
"""
run_primus.py — PrimusCentral (V5) entry point.

Usage:
    python3 run.py
    python3 run.py --port 8080
    python3 run.py --no-browser
"""

import argparse
import errno
import json
import os
import signal
import shutil
import subprocess
import sys
import threading
import time

from artnet import PrimusTelemetryListener, FPS_LISTEN_PORT
from state import ControllerState, OUTPUT_TYPES, animation_loop, set_current_thread_qos
from controller import CueList
from mixer import load_look, compute_look_frame
from effects import blend_pixels
from osc_control import OscControlServer
from paths import (
    app_version,
    ensure_runtime_data,
    is_bundled,
    log_path,
    default_frontend_path,
    sender_product,
)
from network_settings import get_artnet_interface, get_lane_ports
from central_launcher import (
    CentralPortInUseByCentral,
    MISMATCH_MONITOR_ONLY,
    MISMATCH_WRONG_PRODUCT,
    MISMATCH_UNKNOWN_PRODUCT,
    describe_backend,
    frontend_path_for,
    probe_central_server,
    register_central_server,
    stop_running_central,
    supports_remote_stop,
    try_attach_before_start,
    unregister_central_server,
    wait_for_port_release,
)
from launcher_dialog import choose as dialog_choose, notify as dialog_notify
from browser_launcher import DedicatedBrowser
from ui_focus import UiFocusServer
from server import create_server
from ui_lifecycle import monitor as ui_lifecycle_monitor


DEFAULT_HTTP_PORT = 8080
DEDICATED_BROWSER_PROFILE_ROOT = "primusv4-browser-profiles"
_dedicated_browser = DedicatedBrowser(DEDICATED_BROWSER_PROFILE_ROOT, ("PRIMUS_BROWSER",))
_MACOS_ACTIVITY_TOKEN = None


def _ui_has_live_output(server):
    state = getattr(server, "controller_state", None)
    if state is None:
        return False
    source = getattr(state, "playback_source", None)
    if source in (
        ControllerState.SOURCE_CONTROLLER,
        ControllerState.SOURCE_MIXER,
        ControllerState.SOURCE_DESIGNER,
    ):
        return True
    # The unified backend also serves RadiusCentral: audio playing on a
    # Radius receiver is live output the same way a running cue is. Fail
    # toward "live" — a broken check must never make a mid-cue quit legal.
    try:
        return bool(state.radius_has_live_playback())
    except Exception:
        return True


def _attach_mismatch_handler(host="127.0.0.1"):
    """Decide what to do when the running Central cannot serve this launcher.

    Returns a callable for ``try_attach_before_start(on_mismatch=...)``. The
    whole point is that the user sees the choice: packaged apps are windowed
    with no console, so the previous behaviour -- attach anyway, or exit
    silently -- was indistinguishable from a failed launch.
    """
    app_name = _launcher_display_name()

    def _cannot_restart_remotely(backend, port):
        """Old server on the port: say so, and say what to do about it.

        Offering "Restart in full mode" against a pre-0.98 server produced the
        worst outcome available -- the stop 404s, we abort, and the old server
        keeps the port, so every subsequent launch of either app fails the same
        silent way. Never offer an action we cannot carry out.
        """
        choice = dialog_choose(
            app_name,
            f"{backend} is already running on port {port} in Monitor Only mode, "
            "so it will not drive lights.\n\n"
            "That version is too old to be restarted from here. Quit it from its "
            f"own icon in the Dock, then open {app_name} again.",
            ["Open read-only", "Cancel"],
            "Cancel",
        )
        return "attach" if choice == "Open read-only" else "abort"

    def handler(mismatch, port, runtime):
        if mismatch["reason"] == MISMATCH_MONITOR_ONLY:
            backend = describe_backend(runtime)
            if not supports_remote_stop(runtime):
                return _cannot_restart_remotely(backend, port)
            choice = dialog_choose(
                app_name,
                "Another Central server is already running in Monitor Only mode "
                "(started by DeviceManager), so it will not drive lights.\n\n"
                f"{app_name} needs to send output. Restart the shared server in "
                "full mode?",
                ["Restart in full mode", "Open read-only", "Cancel"],
                "Restart in full mode",
            )
            if choice == "Open read-only":
                return "attach"
            if choice != "Restart in full mode":
                return "abort"
            ok, message = stop_running_central(host, port)
            if not ok:
                # A 404 here means the server advertised server_control but does
                # not actually serve the route -- same practical situation as an
                # old server, so give the same actionable instruction.
                if "404" in str(message):
                    return _cannot_restart_remotely(backend, port)
                dialog_notify(
                    app_name,
                    f"Could not stop {backend} on port {port}: {message}\n\n"
                    "Quit it from its own icon in the Dock, then try again.")
                return "abort"
            if not wait_for_port_release(host, port):
                dialog_notify(
                    app_name,
                    f"{backend} on port {port} did not shut down in time.\n\n"
                    "Quit it from its own icon in the Dock, then try again.")
                return "abort"
            return "start"

        if mismatch["reason"] in (MISMATCH_WRONG_PRODUCT, MISMATCH_UNKNOWN_PRODUCT):
            backend = describe_backend(runtime)
            # Never offer to open our frontend on a backend that cannot serve
            # it — that is exactly the silent RadiusCentral-on-Primus failure.
            # The only honest offers are replacing the old server or walking
            # away.
            if not supports_remote_stop(runtime):
                dialog_notify(
                    app_name,
                    f"{backend} is already running on port {port} and cannot "
                    f"serve {app_name}.\n\n"
                    "That version is too old to be restarted from here. Quit "
                    f"it from its own icon in the Dock, then open {app_name} "
                    "again.")
                return "abort"
            choice = dialog_choose(
                app_name,
                f"{backend} is already running on port {port} and cannot "
                f"serve {app_name}.\n\n"
                "Restart it as a shared Central server that serves both apps?",
                ["Restart shared server", "Cancel"],
                "Restart shared server",
            )
            if choice != "Restart shared server":
                return "abort"
            ok, message = stop_running_central(host, port)
            if not ok:
                dialog_notify(
                    app_name,
                    f"Could not stop {backend} on port {port}: {message}\n\n"
                    "Quit it from its own icon in the Dock, then try again.")
                return "abort"
            if not wait_for_port_release(host, port):
                dialog_notify(
                    app_name,
                    f"{backend} on port {port} did not shut down in time.\n\n"
                    "Quit it from its own icon in the Dock, then try again.")
                return "abort"
            return "start"
        return "abort"

    return handler


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
    print(f"PrimusCentral started {time.strftime('%Y-%m-%d %H:%M:%S')}")


def _begin_macos_low_latency_activity():
    """Ask macOS not to throttle PrimusCentral's live-output timers."""
    if sys.platform != "darwin":
        return None
    if os.environ.get("PRIMUSV3_DISABLE_MACOS_ACTIVITY") == "1":
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
    """Kill other V3.6 sender launchers and wait for them to exit."""
    import time
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
    # Wait for killed processes to release their sockets
    for pid in killed:
        for _ in range(20):
            try:
                os.kill(pid, 0)  # check if still alive
                time.sleep(0.1)
            except ProcessLookupError:
                break
    if killed:
        _wait_for_telemetry_port(_watch_port())


def _watch_port():
    try:
        return int(get_lane_ports().get("port_watch") or FPS_LISTEN_PORT)
    except Exception:
        return FPS_LISTEN_PORT


def _wait_for_telemetry_port(port=None, timeout=3.0):
    """Wait until the Watch-lane UDP port is free for PrimusTelemetryListener."""
    import socket
    port = int(port or FPS_LISTEN_PORT)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("0.0.0.0", port))
            probe.close()
            return True
        except OSError:
            probe.close()
            time.sleep(0.1)
    print(f"WARNING: telemetry port {port} still busy after replacing prior sender.")
    return False


def _create_server_with_fallback(host, port, state, cue_list, ui_lifecycle_enabled=False, osc_service=None):
    try:
        return create_server(host, port, state, cue_list,
                             ui_lifecycle_enabled=ui_lifecycle_enabled,
                             osc_service=osc_service)
    except OSError as exc:
        if port == 0:
            raise
        if exc.errno not in (errno.EADDRINUSE, 48, 98):
            raise
        # Any Central server on this machine is reachable via loopback
        # regardless of what host it bound to, so always probe there.
        runtime = probe_central_server("127.0.0.1", port)
        if runtime:
            raise CentralPortInUseByCentral(port, runtime)
        print(f"Port {port} is busy; using an auto-selected port instead.")
        return create_server(host, 0, state, cue_list,
                             ui_lifecycle_enabled=ui_lifecycle_enabled,
                             osc_service=osc_service)


def _browser_profile_root():
    return _dedicated_browser.profile_root()


def _remove_dedicated_browser_profiles(profile_root):
    _dedicated_browser.remove_profiles()


def _open_browser(url, attach=False):
    return _dedicated_browser.open(url, attach=attach)


def _frame_payload(look, pixels_per_output):
    payload = []
    outputs = look.get("outputs", [])
    for idx, pixels in enumerate(pixels_per_output):
        output_type = outputs[idx].get("type", "none") if idx < len(outputs) else "none"
        typedef = OUTPUT_TYPES.get(output_type, {"layout": "none"})
        grid = typedef.get("grid_size") if typedef.get("layout") == "grid" else None
        payload.append({
            "pixels": pixels,
            "grid": grid,
            "type": output_type,
        })
    return payload


def _resilient_loop(fn, state, *args):
    """Run a render loop, restarting it if it ever dies on an exception.

    The animation and mixer/controller loops ARE the show — a single
    unhandled exception must never silently end DMX output for the rest
    of the night. Log the traceback and re-enter the loop.
    """
    errors = 0
    while getattr(state, "running", False):
        try:
            fn(state, *args)
            return
        except Exception:
            errors += 1
            import traceback
            print(f"ERROR: {fn.__name__} crashed (#{errors}); restarting:")
            traceback.print_exc()
            time.sleep(0.5)


def _mixer_controller_loop(state, cue_list):
    """Background thread: render look frames for mixer preview and controller.

    Handles:
      - Mixer preview (highest priority)
      - Controller playback with per-pixel crossfade between looks
      - Blackout fade
      - Auto-follow cue advancement
    """
    import time
    if set_current_thread_qos():
        state.performance.increment("mixer_controller_thread_qos_enabled")
    # Caches persist across frames for performance and stateful effects.
    # Separate state caches for current/prev looks to avoid collision.
    _look_cache = {}          # look_id -> look dict
    _clip_cache = {}          # clip_id -> clip dict
    _state_cache_cur = {}     # segment_id -> effect state (current look)
    _state_cache_prev = {}    # segment_id -> effect state (prev look during xfade)
    _state_cache_multi = {}   # look_id -> segment effect state caches
    _current_look_id = None
    _prev_look_id = None
    _prev_elapsed_base = 0.0  # elapsed offset for outgoing look continuity
    _idle_override_cleared = False

    def record_loop(start):
        state.performance.observe(
            "mixer_controller_loop_ms", (time.perf_counter() - start) * 1000.0)

    while state.running:
        loop_start = time.perf_counter()
        # Mixer preview takes priority over controller
        preview_look, preview_elapsed = state.get_mixer_preview()
        if preview_look:
            _idle_override_cleared = False
            pixels = compute_look_frame(preview_look, preview_elapsed,
                                        fps=state.fps,
                                        clip_cache=_clip_cache,
                                        state_cache=_state_cache_cur)
            state.set_override_pixels(pixels)
            record_loop(loop_start)
            time.sleep(1.0 / max(1, state.fps))
            continue

        # Controller only runs when source is "controller"
        # Note: reading playback_source without lock is safe on CPython
        # due to the GIL — str reads are atomic. The lock is only needed
        # for compound state updates.
        if state.playback_source != state.SOURCE_CONTROLLER:
            # Always clear override pixels so tick() can use the designer
            # branch.  Without this, a race between stop_mixer_preview()
            # and the loop above can leave one stale frame in
            # _override_pixels permanently.
            if not _idle_override_cleared:
                state.clear_override_pixels_if_present()
                _idle_override_cleared = True
            if _current_look_id is not None:
                _current_look_id = None
                _prev_look_id = None
                _state_cache_cur.clear()
                _state_cache_prev.clear()
            state.performance.increment("mixer_controller_idle_waits")
            record_loop(loop_start)
            state.wait_for_render_work(timeout=0.25)
            continue

        _idle_override_cleared = False

        # Check auto-follow timer
        cue_list.check_auto_follow(device_groups=state.get_device_groups())

        # Get crossfade state from controller
        xf = cue_list.get_crossfade_state()
        look_id = xf["current_look_id"]
        prev_id = xf["prev_look_id"]
        xf_progress = xf["crossfade_progress"]
        is_blackout = xf["blackout"]
        bo_progress = xf["blackout_progress"]
        device_ips = None if xf["device_ips"] is None else set(xf["device_ips"])
        active_looks = xf.get("active_looks") or []

        if active_looks:
            frames_by_ip = {}
            default_frames = None
            active_ids = {entry["look_id"] for entry in active_looks}
            for look_id in list(_state_cache_multi.keys()):
                if look_id not in active_ids:
                    _state_cache_multi.pop(look_id, None)

            for entry in active_looks:
                active_look_id = entry["look_id"]
                if active_look_id not in _look_cache:
                    look = load_look(active_look_id)
                    if look:
                        _look_cache[active_look_id] = look
                look = _look_cache.get(active_look_id)
                if not look:
                    continue
                pixels = compute_look_frame(
                    look,
                    entry.get("elapsed", 0.0),
                    fps=state.fps,
                    clip_cache=_clip_cache,
                    state_cache=_state_cache_multi.setdefault(active_look_id, {}),
                )
                payload = _frame_payload(look, pixels)
                entry_ips = entry.get("device_ips")
                if entry_ips is None:
                    default_frames = payload
                else:
                    for ip in entry_ips:
                        frames_by_ip[ip] = payload
            state.set_override_frames_by_device(frames_by_ip, default_frames)
            record_loop(loop_start)
            time.sleep(1.0 / max(1, state.fps))
            continue

        if look_id:
            # Track look changes and reset caches
            if look_id != _current_look_id:
                _current_look_id = look_id
                _look_cache.pop(look_id, None)
                _state_cache_cur.clear()
            if prev_id != _prev_look_id:
                _prev_look_id = prev_id
                if prev_id:
                    _look_cache.pop(prev_id, None)
                _state_cache_prev.clear()

            # Load looks
            if look_id not in _look_cache:
                look = load_look(look_id)
                if look:
                    _look_cache[look_id] = look
            if prev_id and prev_id not in _look_cache:
                look = load_look(prev_id)
                if look:
                    _look_cache[prev_id] = look

            cur_look = _look_cache.get(look_id)
            if cur_look:
                elapsed = xf["elapsed"]
                cur_pixels = compute_look_frame(cur_look, elapsed,
                                                fps=state.fps,
                                                clip_cache=_clip_cache,
                                                state_cache=_state_cache_cur)

                # Crossfade blending
                if prev_id and xf_progress < 1.0:
                    prev_look = _look_cache.get(prev_id)
                    if prev_look:
                        prev_pixels = compute_look_frame(prev_look, elapsed,
                                                         fps=state.fps,
                                                         clip_cache=_clip_cache,
                                                         state_cache=_state_cache_prev)
                        # Blend: prev -> cur by xf_progress
                        blended = []
                        for oi in range(max(len(cur_pixels), len(prev_pixels))):
                            cp = cur_pixels[oi] if oi < len(cur_pixels) else []
                            pp = prev_pixels[oi] if oi < len(prev_pixels) else []
                            if cp and pp and len(cp) == len(pp):
                                blended.append(blend_pixels(pp, cp, xf_progress))
                            elif cp:
                                # Fade from black to cur
                                black = [(0, 0, 0)] * len(cp)
                                blended.append(blend_pixels(black, cp, xf_progress))
                            else:
                                blended.append(cp)
                        cur_pixels = blended

                # Blackout overlay
                if is_blackout:
                    blacked = []
                    for output_pixels in cur_pixels:
                        if output_pixels:
                            black = [(0, 0, 0)] * len(output_pixels)
                            blacked.append(blend_pixels(output_pixels, black, bo_progress))
                        else:
                            blacked.append(output_pixels)
                    cur_pixels = blacked

                state.set_override_pixels(cur_pixels, device_ips=device_ips)
            else:
                state.set_override_pixels(None)
        else:
            if is_blackout:
                state.set_override_pixels(state.build_black_frame(), device_ips=device_ips)
            else:
                state.set_override_pixels(None)
        record_loop(loop_start)
        time.sleep(1.0 / max(1, state.fps))


def _launcher_display_name():
    if os.environ.get("PRIMUSV3_DEFAULT_FRONTEND") == "devices":
        return "Device Manager"
    if os.environ.get("PRIMUSV3_DEFAULT_FRONTEND") == "radius":
        return "RadiusCentral V5"
    return "PrimusCentral V5"


def main():
    global _MACOS_ACTIVITY_TOKEN
    parser = argparse.ArgumentParser(description="PrimusCentral V5")
    parser.add_argument("--port", type=int, default=DEFAULT_HTTP_PORT,
                        help=f"HTTP port (default {DEFAULT_HTTP_PORT}; 0 = auto-select)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Print the URL without opening the browser")
    parser.add_argument(
        "--frontend",
        choices=["primus", "radius", "devices"],
        default=None,
        help="Web UI to open (default: /primus for this launcher)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Stop any running Central server and start a new one",
    )
    parser.add_argument(
        "--monitor-only",
        action="store_true",
        help="Never auto-connect to discovered devices or drive Art-Net output "
             "(only applies when this process starts a fresh backend; inert if "
             "it attaches to an already-running server)",
    )
    parser.add_argument(
        "--lan",
        action="store_true",
        help="Bind the HTTP server to all interfaces (0.0.0.0) instead of "
             "127.0.0.1, so other devices on the same network can reach it "
             "(only applies when this process starts a fresh backend; inert if "
             "it attaches to an already-running server)",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_sigterm)
    ensure_runtime_data()
    _configure_app_logging()

    frontend_path = frontend_path_for(args.frontend, sender_product())
    # DeviceManager only watches; the show frontends drive DMX. Only the latter
    # are incompatible with a monitor-only backend.
    needs_output = not args.monitor_only and str(args.frontend or "").lower() != "devices"
    # What the launcher needs from a running backend depends on the frontend
    # it will open: a RadiusCentral window needs a backend that can serve the
    # radius product (the unified backend advertises both), not merely any
    # primus server.
    need_product = (
        "radius" if str(args.frontend or "").lower() == "radius" else "primus"
    )
    on_mismatch = _attach_mismatch_handler()
    if not args.replace and try_attach_before_start(
        port=args.port,
        frontend_path=frontend_path,
        no_browser=args.no_browser,
        open_browser=_open_browser,
        launcher_name=_launcher_display_name(),
        need_product=need_product,
        needs_output=needs_output,
        on_mismatch=on_mismatch,
    ):
        return

    _MACOS_ACTIVITY_TOKEN = _begin_macos_low_latency_activity()
    if args.replace:
        _kill_existing()

    fps_listener = PrimusTelemetryListener(listen_port=_watch_port())
    fps_thread = threading.Thread(target=fps_listener.run, daemon=True)
    fps_thread.start()

    state = ControllerState(fps_listener, monitor_only=args.monitor_only)
    cue_list = CueList()
    osc_service = OscControlServer(cue_list, state)
    osc_service.start()

    # Restore previously saved devices
    print("Restoring saved devices...")
    state.restore_devices()

    ui_lifecycle_enabled = is_bundled() and not args.no_browser
    browser_profile_root = _browser_profile_root() if not args.no_browser else None
    ui_focus_server = None
    bind_host = "0.0.0.0" if args.lan else "127.0.0.1"

    # Two passes: the mismatch handler may stop a running server and ask us to
    # bind again. Bounded so a flapping server cannot spin here forever.
    server = None
    for attempt in range(2):
        try:
            server = _create_server_with_fallback(
                bind_host, args.port, state, cue_list,
                ui_lifecycle_enabled=ui_lifecycle_enabled,
                osc_service=osc_service)
            break
        except CentralPortInUseByCentral:
            if try_attach_before_start(
                port=args.port,
                frontend_path=frontend_path,
                no_browser=args.no_browser,
                open_browser=_open_browser,
                launcher_name=_launcher_display_name(),
                need_product=need_product,
                needs_output=needs_output,
                on_mismatch=on_mismatch,
            ):
                osc_service.stop()
                fps_listener.stop()
                return
            if attempt == 0:
                # Handler stopped the old server; retry the bind.
                continue
            raise
    if server is None:
        osc_service.stop()
        fps_listener.stop()
        raise SystemExit(1)
    port = server.server_address[1]
    server.lan_enabled = args.lan
    # Shared by the auto-shutdown monitor and /api/server/stop so both agree on
    # whether it is safe to quit.
    server.live_output_fn = _ui_has_live_output
    if not args.no_browser:
        server.ui_focus_callback = _dedicated_browser.focus
        ui_focus_server = UiFocusServer(port, _dedicated_browser.focus)
        ui_focus_server.start()
    url = f"http://127.0.0.1:{port}{frontend_path}"
    lan_url = None
    if args.lan:
        try:
            lan_interface = get_artnet_interface()
        except Exception:
            lan_interface = None
        lan_ip = (lan_interface or {}).get("source_ip")
        if lan_ip:
            lan_url = f"http://{lan_ip}:{port}{frontend_path}"
    register_central_server(
        port, sender_product(),
        monitor_only=bool(args.monitor_only),
        lan_enabled=bool(args.lan),
        app_version=app_version(),
        # The unified backend carries the Radius audio/FTP surface, so a
        # RadiusCentral launcher may attach to it.
        products=["primus", "radius"],
    )

    anim = threading.Thread(
        target=_resilient_loop, args=(animation_loop, state), daemon=True)
    anim.start()

    mc_thread = threading.Thread(
        target=_resilient_loop,
        args=(_mixer_controller_loop, state, cue_list), daemon=True)
    mc_thread.start()

    if ui_lifecycle_enabled:
        ui_thread = threading.Thread(
            target=ui_lifecycle_monitor,
            args=(server,),
            kwargs={
                "app_name": _launcher_display_name(),
                "live_output_fn": _ui_has_live_output,
            },
            daemon=True)
        ui_thread.start()

    print(_launcher_display_name())
    print(f"  URL: {url}")
    if args.lan:
        print(f"  LAN URL: {lan_url or '(no active network interface found)'}")
    print(f"  Devices: {len(state.devices)}")
    osc_status = osc_service.status()
    if osc_status.get("enabled"):
        bound = osc_status.get("bound") or {}
        osc_host = bound.get("host") or osc_status.get("settings", {}).get("host")
        osc_port = bound.get("port") or osc_status.get("settings", {}).get("port")
        osc_label = f"listening on {osc_host}:{osc_port}" if osc_status.get("running") else f"not listening ({osc_status.get('last_error') or 'startup pending'})"
        print(f"  OSC: {osc_label}")
    else:
        print("  OSC: disabled")
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
        osc_service.stop()
        state.shutdown()
        fps_listener.stop()
        server.server_close()
        if browser_profile_root:
            _remove_dedicated_browser_profiles(browser_profile_root)
        print("Done.")


if __name__ == "__main__":
    main()
