#!/usr/bin/env python3
"""
run.py — OSC Cue Sender test utility entry point.

Usage:
    python3 run.py
    python3 run.py --port 8105 --no-browser
"""

import argparse
import os
import sys
import time
import webbrowser

from paths import data_dir, is_bundled
from web_server import create_server


DEFAULT_HTTP_PORT = 8105


def _configure_logging():
    if not is_bundled():
        return
    log_dir = os.path.join(data_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = open(os.path.join(log_dir, "osc_cue_sender.log"), "a", buffering=1)
    sys.stdout = log_file
    sys.stderr = log_file
    print()
    print(f"OscCueSender started {time.strftime('%Y-%m-%d %H:%M:%S')}")


def main():
    parser = argparse.ArgumentParser(description="OSC Cue Sender test utility")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_HTTP_PORT,
        help=f"HTTP port (default {DEFAULT_HTTP_PORT}; 0 = auto-select)",
    )
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser window")
    args = parser.parse_args()

    _configure_logging()
    server = create_server(host=args.host, port=args.port)
    port = server.start()
    url = server.url()
    print(f"OSC Cue Sender running at {url}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        webbrowser.open_new(url)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping OSC Cue Sender...")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
