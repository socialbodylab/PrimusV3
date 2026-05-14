#!/usr/bin/env python3
"""
run.py — PrimusV3.5 LED Controller entry point.

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

from artnet import FpsListener
from state import ControllerState, OUTPUT_TYPES, animation_loop
from controller import CueList
from mixer import load_look, compute_look_frame
from effects import blend_pixels
from paths import ensure_runtime_data, is_bundled, log_path
from server import create_server


DEFAULT_HTTP_PORT = 8080
DEDICATED_BROWSER_PROFILE_ROOT = "primusv35-browser-profiles"
DEDICATED_BROWSER_PID_FILE = "browser.pid"
UI_CLOSE_GRACE_SECONDS = 2.0
UI_HEARTBEAT_TIMEOUT_SECONDS = 45.0
UI_INITIAL_HEARTBEAT_TIMEOUT_SECONDS = 30.0


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


def _kill_existing():
    """Kill other V3.5 sender launchers and wait for them to exit."""
    import time
    my_pid = os.getpid()
    sender_dir = os.path.dirname(os.path.abspath(__file__))
    script_patterns = {
        os.path.join(sender_dir, "run.py"),
        os.path.join(sender_dir, "controller.py"),
        "V3_5/sender/run.py",
        "V3_5/sender/controller.py",
        "PrimusCentral",
        "PrimusV3.5 Sender",
        "PrimusV35Sender",
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


def _create_server_with_fallback(host, port, state, cue_list, ui_lifecycle_enabled=False):
    try:
        return create_server(host, port, state, cue_list,
                             ui_lifecycle_enabled=ui_lifecycle_enabled)
    except OSError as exc:
        if port == 0:
            raise
        if exc.errno not in (errno.EADDRINUSE, 48, 98):
            raise
        print(f"Port {port} is busy; using an auto-selected port instead.")
        return create_server(host, 0, state, cue_list,
                             ui_lifecycle_enabled=ui_lifecycle_enabled)


def _ui_lifecycle_monitor(server):
    while getattr(server, "ui_lifecycle_enabled", False):
        now = time.monotonic()
        close_requested_at = getattr(server, "ui_close_requested_at", None)
        last_heartbeat = getattr(server, "ui_last_heartbeat", None)
        if (close_requested_at is not None
                and (last_heartbeat is None or last_heartbeat < close_requested_at)
                and now - close_requested_at >= UI_CLOSE_GRACE_SECONDS):
            print("UI window closed; shutting down PrimusCentral.")
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
            print("UI heartbeat stopped; shutting down PrimusCentral.")
            server.ui_lifecycle_enabled = False
            server.shutdown()
            return

        time.sleep(0.25)


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


def _mixer_controller_loop(state, cue_list):
    """Background thread: render look frames for mixer preview and controller.

    Handles:
      - Mixer preview (highest priority)
      - Controller playback with per-pixel crossfade between looks
      - Blackout fade
      - Auto-follow cue advancement
    """
    import time
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

    while state.running:
        # Mixer preview takes priority over controller
        preview_look, preview_elapsed = state.get_mixer_preview()
        if preview_look:
            pixels = compute_look_frame(preview_look, preview_elapsed,
                                        fps=state.fps,
                                        clip_cache=_clip_cache,
                                        state_cache=_state_cache_cur)
            state.set_override_pixels(pixels)
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
            state.set_override_pixels(None)
            if _current_look_id is not None:
                _current_look_id = None
                _prev_look_id = None
                _state_cache_cur.clear()
                _state_cache_prev.clear()
            time.sleep(1.0 / max(1, state.fps))
            continue

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
        time.sleep(1.0 / max(1, state.fps))


def main():
    parser = argparse.ArgumentParser(
        description="PrimusV3.5 LED Controller")
    parser.add_argument("--port", type=int, default=DEFAULT_HTTP_PORT,
                        help=f"HTTP port (default {DEFAULT_HTTP_PORT}; 0 = auto-select)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Print the URL without opening the browser")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_sigterm)
    ensure_runtime_data()
    _configure_app_logging()
    _kill_existing()

    fps_listener = FpsListener()
    fps_thread = threading.Thread(target=fps_listener.run, daemon=True)
    fps_thread.start()

    state = ControllerState(fps_listener)
    cue_list = CueList()

    # Restore previously saved devices
    print("Restoring saved devices...")
    state.restore_devices()

    ui_lifecycle_enabled = is_bundled() and not args.no_browser
    browser_profile_root = _browser_profile_root() if not args.no_browser else None
    server = _create_server_with_fallback(
        "127.0.0.1", args.port, state, cue_list,
        ui_lifecycle_enabled=ui_lifecycle_enabled)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}"

    anim = threading.Thread(target=animation_loop, args=(state,), daemon=True)
    anim.start()

    mc_thread = threading.Thread(
        target=_mixer_controller_loop, args=(state, cue_list), daemon=True)
    mc_thread.start()

    if ui_lifecycle_enabled:
        ui_thread = threading.Thread(
            target=_ui_lifecycle_monitor, args=(server,), daemon=True)
        ui_thread.start()

    print("PrimusV3.5 LED Controller")
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
        fps_listener.stop()
        server.server_close()
        if browser_profile_root:
            _remove_dedicated_browser_profiles(browser_profile_root)
        print("Done.")


if __name__ == "__main__":
    main()
