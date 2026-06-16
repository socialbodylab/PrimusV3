#!/usr/bin/env python3
"""
run.py — V4 unified sender entry point (PrimusCentral or RadiusCentral).

Usage:
    python3 run.py
    python3 run.py --product primus
    python3 run.py --product radius --port 8098 --no-browser
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


_bootstrap_product_from_argv()
_bootstrap_product_from_bundle()

from paths import sender_product


def main():
    if sender_product() == "primus":
        from run_primus import main as primus_main
        primus_main()
    else:
        from run_radius import main as radius_main
        radius_main()


if __name__ == "__main__":
    main()
