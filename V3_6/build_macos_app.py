#!/usr/bin/env python3
"""Compatibility wrapper for building the macOS V3.6 sender app."""

import sys

from build_sender_app import main


if __name__ == "__main__":
    raise SystemExit(main(["--target", "macos", *sys.argv[1:]]))