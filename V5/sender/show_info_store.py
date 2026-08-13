"""
show_info_store.py — Shared character/performer persistence for Primus and Radius state files.
"""

import json
import os
import time

import paths


FIELD_MAX_LENGTH = 64
SHOW_INFO_EDIT_GRACE_SECONDS = 30
GENERIC_DEVICE_NAMES = frozenset({"", "Radius", "PrimusV3", "Primus", "Node"})


def preferred_device_name(discovered="", saved="", fallback="Node"):
    discovered = str(discovered or "").strip()
    saved = str(saved or "").strip()
    if discovered and discovered not in GENERIC_DEVICE_NAMES:
        return discovered[:17]
    if saved:
        return saved[:17]
    return (discovered or saved or fallback)[:17]


def primus_state_path():
    if paths.is_primus_product():
        return paths.state_file()
    return paths.data_path(".primus_state.json")


def radius_state_path():
    return paths.data_path(".radius_state.json")


def storage_path_for_device(is_radius=False):
    return radius_state_path() if is_radius else primus_state_path()


def normalize_show_info_value(value):
    return str(value or "").strip()[:FIELD_MAX_LENGTH]


def discovery_show_info_may_apply(dev, grace_seconds=SHOW_INFO_EDIT_GRACE_SECONDS):
    edited_at = float((dev or {}).get("show_info_edited_at") or 0)
    return (time.time() - edited_at) >= grace_seconds


def show_info_from_saved(saved):
    if not isinstance(saved, dict):
        return "", ""
    return (
        normalize_show_info_value(saved.get("character_name")),
        normalize_show_info_value(saved.get("performer_name")),
    )


def read_state_data(state_path):
    try:
        with open(state_path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def write_state_data(state_path, data):
    directory = os.path.dirname(state_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    try:
        with open(state_path, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def device_show_info_map_from_data(data):
    info_map = data.get("device_show_info")
    return dict(info_map) if isinstance(info_map, dict) else {}


def show_info_entry(device_name, character_name, performer_name):
    return {
        "device_name": str(device_name or "")[:17],
        "character_name": normalize_show_info_value(character_name),
        "performer_name": normalize_show_info_value(performer_name),
    }


def lookup_device_show_info(state_path, ip=None, device_name=None):
    info_map = device_show_info_map_from_data(read_state_data(state_path))
    entry = info_map.get(ip) if ip else None
    if isinstance(entry, dict):
        return show_info_from_saved(entry)
    if device_name:
        for candidate in info_map.values():
            if isinstance(candidate, dict) and candidate.get("device_name") == device_name:
                return show_info_from_saved(candidate)
    return "", ""


def lookup_device_show_info_entry(state_path, ip=None, device_name=None):
    info_map = device_show_info_map_from_data(read_state_data(state_path))
    entry = info_map.get(ip) if ip else None
    if isinstance(entry, dict):
        return entry
    if device_name:
        for candidate in info_map.values():
            if isinstance(candidate, dict) and candidate.get("device_name") == device_name:
                return candidate
    return None


def persist_device_show_info(state_path, ip, device_name, character_name, performer_name):
    if not ip:
        return
    data = read_state_data(state_path)
    info_map = device_show_info_map_from_data(data)
    info_map[ip] = show_info_entry(device_name, character_name, performer_name)
    data["device_show_info"] = info_map
    write_state_data(state_path, data)


def migrate_device_show_info_key(state_path, old_ip, new_ip, device_name=None):
    if not old_ip or not new_ip or old_ip == new_ip:
        return
    data = read_state_data(state_path)
    info_map = device_show_info_map_from_data(data)
    entry = info_map.pop(old_ip, None)
    if not isinstance(entry, dict):
        return
    if device_name:
        entry["device_name"] = str(device_name)[:17]
    info_map[new_ip] = entry
    data["device_show_info"] = info_map
    write_state_data(state_path, data)


def show_info_from_node(node_info):
    if not isinstance(node_info, dict):
        return "", ""
    return (
        normalize_show_info_value(node_info.get("character_name")),
        normalize_show_info_value(node_info.get("performer_name")),
    )


def merge_show_info_fields(state_path, character_name, performer_name, ip=None, device_name=None):
    lookup_char, lookup_perf = lookup_device_show_info(state_path, ip, device_name)
    if not character_name and lookup_char:
        character_name = lookup_char
    if not performer_name and lookup_perf:
        performer_name = lookup_perf
    return character_name, performer_name


def node_matches_firmware_name_overrides(node_info, overrides):
    """True when a discovered node already reports the upload override names.

    This is the guard that keeps post-flash name overrides scoped to the
    device that was actually flashed: pushing overrides to every online
    device smears one performer's identity across the fleet.
    """
    if not isinstance(node_info, dict) or not isinstance(overrides, dict):
        return False
    device_name = overrides.get("device_name")
    character_name = overrides.get("character_name")
    performer_name = overrides.get("performer_name")
    if not any((device_name, character_name, performer_name)):
        return False
    if device_name:
        short = str(node_info.get("short_name") or "").strip()
        if short != str(device_name)[:17]:
            return False
    if character_name:
        actual = normalize_show_info_value(node_info.get("character_name"))
        if actual != normalize_show_info_value(character_name):
            return False
    if performer_name:
        actual = normalize_show_info_value(node_info.get("performer_name"))
        if actual != normalize_show_info_value(performer_name):
            return False
    return True


def apply_persisted_show_info(state_path, dev, node_info=None):
    node_char, node_perf = show_info_from_node(node_info or {})
    if node_char:
        dev["character_name"] = node_char
    if node_perf:
        dev["performer_name"] = node_perf

    ip = dev.get("ip") or (node_info or {}).get("ip")
    name = dev.get("name") or (node_info or {}).get("short_name")
    entry = lookup_device_show_info_entry(state_path, ip, name)
    if isinstance(entry, dict):
        if "character_name" in entry and not dev.get("character_name"):
            dev["character_name"] = normalize_show_info_value(entry.get("character_name"))
        if "performer_name" in entry and not dev.get("performer_name"):
            dev["performer_name"] = normalize_show_info_value(entry.get("performer_name"))

    if ip and (dev.get("character_name") or dev.get("performer_name") or (
            isinstance(entry, dict) and (
                "character_name" in entry or "performer_name" in entry))):
        persist_device_show_info(
            state_path,
            ip,
            name,
            dev.get("character_name", ""),
            dev.get("performer_name", ""),
        )
