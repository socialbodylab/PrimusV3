#!/usr/bin/env python3
"""Live-hardware check for Radius firmware override seeding.

Requires a Radius receiver on the LAN. Binds Art-Net queries to UDP 6454 because
receiver show-info replies are sent to the controller port, not the ephemeral
source port.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

SENDER_DIR = Path(__file__).resolve().parents[1]
if str(SENDER_DIR) not in sys.path:
    sys.path.insert(0, str(SENDER_DIR))

from artnet import discover_artnet_nodes, query_show_info, sync_show_info_to_device  # noqa: E402


def find_radius_node(ip=None, timeout=3.0):
    known = [ip] if ip else None
    nodes = discover_artnet_nodes(known_ips=known, timeout=timeout)
    radius = [n for n in nodes if "PVRAD1" in (n.get("node_report") or "")]
    if ip:
        radius = [n for n in radius if n.get("ip") == ip] or radius
    return radius[0] if radius else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", help="Expected device IP (optional; auto-discover if omitted)")
    parser.add_argument("--name", default="TestRad01")
    parser.add_argument("--character-name", default="TestChar")
    parser.add_argument("--performer-name", default="TestPerf")
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()

    print("Discovering Radius device...")
    node = find_radius_node(ip=args.ip, timeout=args.timeout)
    if not node:
        print("FAIL: no Radius node found on the network")
        return 1

    ip = node["ip"]
    print(f"Found {ip}: short_name={node.get('short_name')!r} fw={node.get('firmware_version')!r}")

    show = query_show_info(ip, timeout=args.timeout)
    print(f"ArtShowInfo read: {show}")

    failures = []
    if (node.get("short_name") or "").strip() != args.name:
        failures.append(f"short_name expected {args.name!r}, got {node.get('short_name')!r}")
    if not show:
        failures.append("ArtShowInfo read returned no response")
    else:
        if (show.get("character_name") or "").strip() != args.character_name:
            failures.append(
                f"character_name expected {args.character_name!r}, got {show.get('character_name')!r}"
            )
        if (show.get("performer_name") or "").strip() != args.performer_name:
            failures.append(
                f"performer_name expected {args.performer_name!r}, got {show.get('performer_name')!r}"
            )

    ok, err = sync_show_info_to_device(
        ip,
        character_name=args.character_name,
        performer_name=args.performer_name,
        timeout=args.timeout,
    )
    print(f"sync_show_info_to_device: ok={ok} err={err!r}")
    if not ok:
        failures.append(f"sync_show_info_to_device failed: {err}")

    if failures:
        print("FAIL:")
        for item in failures:
            print(f"  - {item}")
        return 1

    print("PASS: device name and show info overrides verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
