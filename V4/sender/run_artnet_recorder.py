#!/usr/bin/env python3
"""run_artnet_recorder.py — ArtNet Recorder entry point."""

import argparse
import os
import signal
import sys
import threading
import time
import webbrowser

from capture_server import create_server, DEFAULT_DEVICE_IP

DEFAULT_HTTP_PORT = 8099


def _handle_sigterm(signum, frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description="ArtNet Recorder — capture EOS→Primus Art-Net traffic")
    parser.add_argument("--port", type=int, default=DEFAULT_HTTP_PORT,
                        help=f"HTTP port (default {DEFAULT_HTTP_PORT})")
    parser.add_argument("--host", default="127.0.0.1",
                        help="HTTP bind address (default 127.0.0.1)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Print the URL without opening the browser")
    parser.add_argument("--device-ip", default=DEFAULT_DEVICE_IP,
                        help=f"Default target device IP (default {DEFAULT_DEVICE_IP})")
    parser.add_argument("--mode", choices=("standin", "sniff"), default="standin",
                        help="Default capture mode")
    parser.add_argument("--interface", default="",
                        help="Network interface device name for sniff/stand-in bind")
    parser.add_argument("--lan", action="store_true",
                        help="Bind HTTP to 0.0.0.0 instead of loopback")
    args = parser.parse_args()

    os.environ.setdefault("PRIMUSV3_SENDER_PRODUCT", "primus")
    os.environ.setdefault("PRIMUSV3_DEFAULT_DEVICE_IP", args.device_ip)
    os.environ.setdefault("PRIMUSV3_CAPTURE_MODE", args.mode)
    if args.interface:
        os.environ.setdefault("PRIMUSV3_CAPTURE_INTERFACE", args.interface)

    host = "0.0.0.0" if args.lan else args.host
    httpd = create_server(host, args.port)
    port = httpd.server_address[1]
    url = f"http://127.0.0.1:{port}/"

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    print(f"ArtNet Recorder listening on {url}")
    print(f"Default device IP: {args.device_ip}")
    print(f"Default mode: {args.mode}")

    if not args.no_browser:
        time.sleep(0.3)
        webbrowser.open(url)

    signal.signal(signal.SIGTERM, _handle_sigterm)
    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping ArtNet Recorder...")
    finally:
        from artnet_capture import capture_manager
        capture_manager.stop()
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    main()
