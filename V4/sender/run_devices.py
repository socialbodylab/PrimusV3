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

from run_primus import main


if __name__ == "__main__":
    main()
