"""capture_setup.py — Show setup: one Art-Net universe per Primus device."""

import ipaddress
import json
import os
import sys

DEFAULT_DEVICE_IP = "192.168.8.190"
DEFAULT_START_UNIVERSE = 1
DEFAULT_DEVICE_COUNT = 20

_setup_lock = None


def _app_support_base():
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support")
    if os.name == "nt":
        return os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def setup_path():
    path = os.path.join(_app_support_base(), "PrimusV3", "V4", "captures")
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, "show_setup.json")


def default_setup():
    return {
        "layout": "per_device_universe",
        "start_ip": DEFAULT_DEVICE_IP,
        "start_universe": DEFAULT_START_UNIVERSE,
        "device_count": DEFAULT_DEVICE_COUNT,
        "devices": build_device_list(
            DEFAULT_DEVICE_IP,
            DEFAULT_START_UNIVERSE,
            DEFAULT_DEVICE_COUNT,
        ),
    }


def build_device_list(start_ip, start_universe, device_count, labels=None):
    """Build IP→universe rows: each device gets its own universe (EOS combined layout)."""
    start_ip = str(start_ip or DEFAULT_DEVICE_IP).strip()
    start_universe = int(start_universe)
    device_count = max(1, int(device_count))
    labels = labels or {}
    base = ipaddress.ip_address(start_ip)
    if not isinstance(base, ipaddress.IPv4Address):
        raise ValueError("start_ip must be IPv4")
    devices = []
    for offset in range(device_count):
        ip = str(ipaddress.IPv4Address(int(base) + offset))
        universe = start_universe + offset
        label = labels.get(ip) or f"Device {offset + 1}"
        devices.append({
            "ip": ip,
            "universe": universe,
            "label": label,
        })
    return devices


def normalize_setup(data=None):
    data = data if isinstance(data, dict) else {}
    layout = str(data.get("layout") or "per_device_universe").strip()
    start_ip = str(data.get("start_ip") or DEFAULT_DEVICE_IP).strip()
    start_universe = int(data.get("start_universe", DEFAULT_START_UNIVERSE))
    device_count = max(1, int(data.get("device_count", DEFAULT_DEVICE_COUNT)))
    devices = data.get("devices")
    if not isinstance(devices, list) or not devices:
        devices = build_device_list(start_ip, start_universe, device_count)
    else:
        cleaned = []
        for item in devices:
            if not isinstance(item, dict):
                continue
            ip = str(item.get("ip") or "").strip()
            if not _valid_ipv4(ip):
                continue
            universe = item.get("universe")
            if universe is None:
                continue
            cleaned.append({
                "ip": ip,
                "universe": int(universe),
                "label": str(item.get("label") or ip).strip() or ip,
            })
        devices = cleaned or build_device_list(start_ip, start_universe, device_count)
    return {
        "layout": layout,
        "start_ip": start_ip,
        "start_universe": start_universe,
        "device_count": device_count,
        "devices": devices,
    }


def _valid_ipv4(value):
    try:
        addr = ipaddress.ip_address(str(value))
        return isinstance(addr, ipaddress.IPv4Address)
    except ValueError:
        return False


def load_setup():
    path = setup_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return normalize_setup(json.load(handle))
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            pass
    return default_setup()


def save_setup(data):
    setup = normalize_setup(data)
    with open(setup_path(), "w", encoding="utf-8") as handle:
        json.dump(setup, handle, indent=2)
        handle.write("\n")
    return setup


def device_ips(setup):
    return [item["ip"] for item in setup.get("devices", [])]


def universe_for_ip(setup, ip):
    ip = str(ip or "").strip()
    for item in setup.get("devices", []):
        if item.get("ip") == ip:
            return item.get("universe")
    return None


def ip_for_universe(setup, universe):
    if universe is None:
        return None
    for item in setup.get("devices", []):
        if item.get("universe") == universe:
            return item.get("ip")
    return None


def device_label(setup, ip):
    for item in setup.get("devices", []):
        if item.get("ip") == ip:
            return item.get("label") or ip
    return ip


def bpf_host_filter(setup, fallback_ip=""):
    hosts = device_ips(setup)
    if fallback_ip and fallback_ip not in hosts:
        hosts = [fallback_ip] + hosts
    hosts = [h for h in hosts if _valid_ipv4(h)]
    if not hosts:
        hosts = [fallback_ip or DEFAULT_DEVICE_IP]
    if len(hosts) == 1:
        return f"host {hosts[0]}"
    inner = " or ".join(f"host {ip}" for ip in hosts)
    return f"({inner})"
