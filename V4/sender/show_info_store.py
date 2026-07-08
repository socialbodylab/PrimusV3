"""
show_info_store.py — Shared character/performer persistence for Primus and Radius state files.
"""

import json
import os

import paths


FIELD_MAX_LENGTH = 64


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


def apply_persisted_show_info(state_path, dev, node_info=None):
    ip = dev.get("ip") or (node_info or {}).get("ip")
    name = dev.get("name") or (node_info or {}).get("short_name")
    character_name, performer_name = lookup_device_show_info(state_path, ip, name)
    if character_name:
        dev["character_name"] = character_name
    if performer_name:
        dev["performer_name"] = performer_name
