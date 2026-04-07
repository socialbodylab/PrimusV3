#!/usr/bin/env python3
"""
run.py — PrimusV3.1 LED Controller entry point.

Usage:
    python3 run.py
    python3 run.py --port 8080
"""

import argparse
import os
import signal
import subprocess
import threading
import webbrowser

from artnet import FpsListener
from state import ControllerState, animation_loop
from controller import CueList
from mixer import load_look, compute_look_frame
from server import create_server


def _kill_existing():
    """Kill any other running instances of this script and wait for them to exit."""
    import time
    my_pid = os.getpid()
    my_script = os.path.abspath(__file__)
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", my_script], text=True, stderr=subprocess.DEVNULL
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    killed = []
    for line in out.strip().splitlines():
        pid = int(line.strip())
        if pid == my_pid:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
            print(f"Killed previous instance (PID {pid})")
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


def _mixer_controller_loop(state, cue_list):
    """Background thread: when controller is playing, compute look frames."""
    import time
    # Caches persist across frames for performance and stateful effects
    _look_cache = {}      # look_id -> look dict
    _clip_cache = {}      # clip_id -> clip dict
    _state_cache = {}     # segment_id -> effect state list
    _current_look_id = None

    while state.running:
        # Mixer preview takes priority over controller
        preview_look, preview_elapsed = state.get_mixer_preview()
        if preview_look:
            pixels = compute_look_frame(preview_look, preview_elapsed,
                                        fps=state.fps,
                                        clip_cache=_clip_cache,
                                        state_cache=_state_cache)
            state.set_override_pixels(pixels)
            time.sleep(1.0 / max(1, state.fps))
            continue

        look_id = cue_list.get_current_look_id()
        if look_id and cue_list.playing:
            # Reload look if it changed
            if look_id != _current_look_id:
                _current_look_id = look_id
                _look_cache.pop(look_id, None)
                _state_cache.clear()
            if look_id not in _look_cache:
                look = load_look(look_id)
                if look:
                    _look_cache[look_id] = look
            look = _look_cache.get(look_id)
            if look:
                elapsed = cue_list.get_elapsed()
                pixels = compute_look_frame(look, elapsed, fps=state.fps,
                                            clip_cache=_clip_cache,
                                            state_cache=_state_cache)
                state.set_override_pixels(pixels)
            else:
                state.set_override_pixels(None)
        elif state.playback_source in (state.SOURCE_DESIGNER, state.SOURCE_IDLE):
            if _current_look_id is not None:
                _current_look_id = None
                _state_cache.clear()
            state.set_override_pixels(None)
        time.sleep(1.0 / max(1, state.fps))


def main():
    parser = argparse.ArgumentParser(
        description="PrimusV3.1 LED Controller")
    parser.add_argument("--port", type=int, default=0,
                        help="HTTP port (0 = auto-select)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't open browser on startup")
    args = parser.parse_args()

    _kill_existing()

    fps_listener = FpsListener()
    fps_thread = threading.Thread(target=fps_listener.run, daemon=True)
    fps_thread.start()

    state = ControllerState(fps_listener)
    cue_list = CueList()

    # Restore previously saved devices
    print("Restoring saved devices...")
    state.restore_devices()

    server = create_server("127.0.0.1", args.port, state, cue_list)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}"

    anim = threading.Thread(target=animation_loop, args=(state,), daemon=True)
    anim.start()

    mc_thread = threading.Thread(
        target=_mixer_controller_loop, args=(state, cue_list), daemon=True)
    mc_thread.start()

    print("PrimusV3.1 LED Controller")
    print(f"  URL: {url}")
    print(f"  Devices: {len(state.devices)}")
    print()

    if not args.no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        state.shutdown()
        fps_listener.stop()
        server.server_close()
        print("Done.")


if __name__ == "__main__":
    main()
