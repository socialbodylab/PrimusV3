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

# Device Manager no longer starts a monitor-only backend. Monitoring is
# passive by construction now: the background device sync never
# auto-connects, so no backend sends DMX to a device until an operator
# explicitly connects it (from PrimusCentral, for tests/demos). One shared
# backend, one behavior, regardless of which app started it — in production
# the color data comes from an external console (EOS, TouchDesigner) and
# this suite just monitors alongside it. --monitor-only remains accepted on
# the CLI for scripts but is no longer required for safe coexistence.

# Device Manager is meant to be viewed from a phone/tablet on the same
# network (see Settings > Mobile / Tablet View), so its own fresh backend
# binds to the LAN interface instead of loopback-only. Also inert when
# attaching to an already-running server.
if "--lan" not in sys.argv:
    sys.argv[1:1] = ["--lan"]

from run_primus import main


if __name__ == "__main__":
    main()
