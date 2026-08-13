#!/usr/bin/env python3
"""
Restore character/performer show info from a PrimusNames.xlsx cast sheet.

Pushes names to receivers over Art-Net (0x8210) and updates local sender state.
"""

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SENDER_DIR = os.path.dirname(SCRIPT_DIR)
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import paths
import show_info_store
from artnet import sync_show_info_to_device


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CORRUPT = ("E7", "Soprano5", "Ella-Jeon")
IP_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")
PRIVATE_LAN_RE = re.compile(r"^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)\d")


def _col_index(col):
    n = 0
    for ch in col:
        n = n * 26 + (ord(ch) - 64)
    return n


def _col_row(ref):
    match = re.match(r"([A-Z]+)(\d+)", ref)
    return match.group(1), int(match.group(2))


def read_xlsx_rows(path):
    with zipfile.ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("m:si", NS):
                texts = [node.text or "" for node in item.findall(".//m:t", NS)]
                shared.append("".join(texts))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = workbook.find("m:sheets/m:sheet", NS)
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rid_to_target = {rel.get("Id"): rel.get("Target") for rel in rels}
        rid = sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = "xl/" + rid_to_target[rid].lstrip("/").replace("xl/", "")
        sheet_root = ET.fromstring(archive.read(target))

        cells = {}
        for cell in sheet_root.findall(".//m:sheetData/m:row/m:c", NS):
            ref = cell.get("r")
            col, row = _col_row(ref)
            value_node = cell.find("m:v", NS)
            if value_node is None:
                value = ""
            elif cell.get("t") == "s":
                value = shared[int(value_node.text)]
            else:
                value = value_node.text
            cells.setdefault(row, {})[_col_index(col)] = str(value or "").strip()

        if not cells:
            return []

        header_row = cells.get(1, {})
        headers = [header_row.get(i, "").strip().lower() for i in range(1, max(header_row) + 1)]
        ip_idx = next((i for i, h in enumerate(headers, start=1) if "ip" in h), None)
        char_idx = next((i for i, h in enumerate(headers, start=1) if h == "character"), None)
        perf_idx = next((i for i, h in enumerate(headers, start=1) if h == "performer"), None)
        if not ip_idx or not char_idx or not perf_idx:
            raise SystemExit("Could not find Character, Performer, and Primus IP columns.")

        rows = []
        for row_num in sorted(cells):
            if row_num == 1:
                continue
            row = cells[row_num]
            ip = row.get(ip_idx, "").strip()
            if not IP_RE.match(ip):
                continue
            rows.append({
                "ip": ip,
                "character_name": show_info_store.normalize_show_info_value(row.get(char_idx, "")),
                "performer_name": show_info_store.normalize_show_info_value(row.get(perf_idx, "")),
            })
        return rows


def _source_ip():
    try:
        from network_settings import get_artnet_interface
        interface = get_artnet_interface() or {}
        return interface.get("source_ip")
    except Exception:
        return None


def _state_path():
    paths.ensure_runtime_data()
    return paths.state_file()


def _load_state():
    try:
        with open(_state_path(), "r") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(data):
    directory = os.path.dirname(_state_path())
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(_state_path(), "w") as handle:
        json.dump(data, handle, indent=2)


def _update_local_state(ip, character_name, performer_name, device_name=None):
    data = _load_state()
    info_map = show_info_store.device_show_info_map_from_data(data)
    entry = dict(info_map.get(ip) or {})
    if device_name:
        entry["device_name"] = str(device_name)[:17]
    entry["character_name"] = character_name
    entry["performer_name"] = performer_name
    info_map[ip] = entry
    data["device_show_info"] = info_map

    for dev in data.get("devices", []):
        if dev.get("ip") != ip:
            continue
        dev["character_name"] = character_name
        dev["performer_name"] = performer_name
        if device_name:
            dev["name"] = str(device_name)[:17]
        break

    _save_state(data)
    show_info_store.persist_device_show_info(
        show_info_store.primus_state_path(),
        ip,
        (device_name or entry.get("device_name") or ""),
        character_name,
        performer_name,
    )


def recover_saved_map_entries(source_ip=None, dry_run=False):
    """Re-push entries still correct in device_show_info but wrong on hardware."""
    data = _load_state()
    info_map = show_info_store.device_show_info_map_from_data(data)
    restored = []
    for ip, entry in sorted(info_map.items()):
        if not IP_RE.match(str(ip or "")) or ip.startswith("127."):
            continue
        if not isinstance(entry, dict):
            continue
        saved = (
            str(entry.get("device_name") or "").strip(),
            show_info_store.normalize_show_info_value(entry.get("character_name")),
            show_info_store.normalize_show_info_value(entry.get("performer_name")),
        )
        if saved == CORRUPT or not any(saved):
            continue
        if saved[0] == "E7" and saved[1:] == ("Soprano5", "Ella-Jeon"):
            continue
        device_name, character_name, performer_name = saved
        if dry_run:
            print(f"[dry-run] map restore {ip}: {saved}")
            restored.append(ip)
            continue
        from artnet import sync_device_name_to_receiver
        ok_name = True
        if device_name:
            ok_name, err = sync_device_name_to_receiver(
                ip, device_name, source_ip=source_ip)
            if not ok_name:
                print(f"FAIL {ip} device name: {err}")
                continue
        ok, err = sync_show_info_to_device(
            ip,
            character_name=character_name,
            performer_name=performer_name,
            source_ip=source_ip,
        )
        if ok:
            _update_local_state(ip, character_name, performer_name, device_name=device_name)
            print(f"OK   {ip} map restore -> {device_name!r} / {character_name!r} / {performer_name!r}")
            restored.append(ip)
        else:
            print(f"FAIL {ip} map restore: {err}")
    return restored


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xlsx", help="Path to PrimusNames.xlsx")
    parser.add_argument("--dry-run", action="store_true", help="Print actions only")
    parser.add_argument(
        "--also-recover-saved-map",
        action="store_true",
        default=True,
        help="Also restore IPs whose device_show_info map was not corrupted (default: on)",
    )
    parser.add_argument(
        "--no-also-recover-saved-map",
        action="store_false",
        dest="also_recover_saved_map",
    )
    args = parser.parse_args()

    rows = read_xlsx_rows(args.xlsx)
    if not rows:
        raise SystemExit("No cast rows found in spreadsheet.")

    source_ip = _source_ip()
    if source_ip:
        print(f"Art-Net source IP: {source_ip}")
    print(f"Restoring {len(rows)} cast entries from {args.xlsx}\n")

    ok_count = 0
    for row in rows:
        ip = row["ip"]
        character_name = row["character_name"]
        performer_name = row["performer_name"]
        if args.dry_run:
            print(f"[dry-run] {ip}: {character_name!r} / {performer_name!r}")
            ok_count += 1
            continue
        ok, err = sync_show_info_to_device(
            ip,
            character_name=character_name,
            performer_name=performer_name,
            source_ip=source_ip,
        )
        if ok:
            _update_local_state(ip, character_name, performer_name)
            print(f"OK   {ip} -> {character_name!r} / {performer_name!r}")
            ok_count += 1
        else:
            print(f"FAIL {ip}: {err}")

    print(f"\nSpreadsheet: {ok_count}/{len(rows)} succeeded.")

    if args.also_recover_saved_map:
        print("\nRecovering saved map entries not in spreadsheet...")
        map_ips = recover_saved_map_entries(source_ip=source_ip, dry_run=args.dry_run)
        print(f"Saved map: {len(map_ips)} restored.")


if __name__ == "__main__":
    main()
