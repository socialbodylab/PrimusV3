#!/usr/bin/env python3
"""
run_devices.py — Device Manager packaged entry point.

Opens the /devices frontend against the Primus Central backend. If Central is
already running, attaches to it instead of starting a second server.
"""

import os
import sys

os.environ.setdefault("PRIMUSV3_SENDER_PRODUCT", "primus")
os.environ.setdefault("PRIMUSV3_DEFAULT_FRONTEND", "devices")

if "--frontend" not in sys.argv:
    sys.argv[1:1] = ["--frontend", "devices"]

# Device Manager's job is to monitor devices, not drive them. This is inert if
# we attach to an already-running Central server (its ControllerState was
# already constructed without this flag) and only takes effect when this
# process starts a fresh backend of its own.
if "--monitor-only" not in sys.argv:
    sys.argv[1:1] = ["--monitor-only"]

# Device Manager is meant to be viewed from a phone/tablet on the same
# network (see Settings > Mobile / Tablet View), so its own fresh backend
# binds to the LAN interface instead of loopback-only. Also inert when
# attaching to an already-running server.
if "--lan" not in sys.argv:
    sys.argv[1:1] = ["--lan"]

from run_primus import main


if __name__ == "__main__":
    main()
