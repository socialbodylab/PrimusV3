#!/usr/bin/env python3
"""
run.py — PrimusV3.1 LED Controller entry point.

Usage:
    python3 run.py
    python3 run.py --port 8080
"""

import argparse
import threading
import webbrowser

from artnet import FpsListener
from state import ControllerState, animation_loop
from controller import CueList
from mixer import load_look, compute_look_frame
from server import create_server


def _mixer_controller_loop(state, cue_list):
    """Background thread: when controller is playing, compute look frames."""
    import time
    while state.running:
        look_id = cue_list.get_current_look_id()
        if look_id and cue_list.playing:
            look = load_look(look_id)
            if look:
                elapsed = cue_list.get_elapsed()
                pixels = compute_look_frame(look, elapsed)
                state.set_override_pixels(pixels)
            else:
                state.set_override_pixels(None)
        elif state.playback_source == state.SOURCE_DESIGNER:
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

    fps_listener = FpsListener()
    fps_thread = threading.Thread(target=fps_listener.run, daemon=True)
    fps_thread.start()

    state = ControllerState(fps_listener)
    cue_list = CueList()

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
