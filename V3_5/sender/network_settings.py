"""Sender network settings for Primus Central.

This module keeps host-network configuration separate from receiver device
configuration. It is intentionally stdlib-only so packaged sender builds remain
dependency-free.
"""

import copy
import ipaddress
import json
import os
import re
import shlex
import subprocess
import sys

from artnet import ipv4_octets
from paths import state_file


STATE_KEY = "sender_network"
NETWORKSETUP = "/usr/sbin/networksetup"
SCUTIL = "/usr/sbin/scutil"
AIRPORT = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"

DEFAULT_SETTINGS = {
    "preferred": {
        "id": "",
        "service": "",
        "device": "",
        "ssid": "",
        "source_ip": "",
    },
    "controller_connection": {
        "id": "",
        "service": "",
        "device": "",
        "ssid": "",
        "source_ip": "",
    },
    "ssid_profiles": {},
    "service_profiles": {},
    "last_applied": {},
}


def _clean_ssid(value):
    ssid = str(value or "").strip().strip('"')
    if not ssid:
        return ""
    if ssid.lower().startswith("<data>"):
        match = re.search(r"0x([0-9a-fA-F]+)", ssid)
        if not match:
            return ""
        try:
            decoded = bytes.fromhex(match.group(1)).rstrip(b"\x00").decode("utf-8", "ignore").strip()
        except ValueError:
            return ""
        if not decoded or any(ord(char) < 32 for char in decoded):
            return ""
        return decoded
    if ssid.lower() in ("<redacted>", "redacted", "none", "(null)", "not associated"):
        return ""
    return ssid


class NetworkSettingsError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def _state_file():
    return state_file()


def _read_state():
    try:
        with open(_state_file(), "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(data):
    directory = os.path.dirname(_state_file())
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(_state_file(), "w") as f:
        json.dump(data, f)


def _normalize_settings(settings=None):
    out = copy.deepcopy(DEFAULT_SETTINGS)
    if not isinstance(settings, dict):
        return out
    preferred = settings.get("preferred")
    if isinstance(preferred, dict):
        for key in out["preferred"]:
            out["preferred"][key] = str(preferred.get(key) or "")
        out["preferred"]["ssid"] = _clean_ssid(out["preferred"].get("ssid"))
    controller_connection = settings.get("controller_connection")
    if isinstance(controller_connection, dict):
        for key in out["controller_connection"]:
            out["controller_connection"][key] = str(controller_connection.get(key) or "")
        out["controller_connection"]["ssid"] = _clean_ssid(out["controller_connection"].get("ssid"))
    for key in ("ssid_profiles", "service_profiles"):
        if isinstance(settings.get(key), dict):
            out[key] = settings[key]
    if isinstance(settings.get("last_applied"), dict):
        out["last_applied"] = settings["last_applied"]
    return out


def load_settings():
    return _normalize_settings(_read_state().get(STATE_KEY))


def save_settings(settings):
    data = _read_state()
    data[STATE_KEY] = _normalize_settings(settings)
    _write_state(data)
    return data[STATE_KEY]


def _run_text(args, timeout=4.0):
    return subprocess.check_output(
        args,
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
    )


def _run_text_input(args, input_text, timeout=4.0):
    return subprocess.check_output(
        args,
        input=input_text,
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
    )


def _interface_type(label):
    text = str(label or "").lower()
    for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        text = text.replace(dash, "-")
    if "wi-fi" in text or "wifi" in text or "airport" in text:
        return "wifi"
    if "ethernet" in text or "lan" in text or "thunderbolt" in text:
        return "ethernet"
    return "other"


def _interface_id(service, device):
    if device and service:
        return f"{device}:{service}"
    return device or service or ""


def _parse_service_order(text):
    services = []
    current = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        service_match = re.match(r"^\(\d+\)\s+(.+)$", line)
        if service_match:
            service = service_match.group(1).lstrip("*").strip()
            current = {"service": service, "hardware_port": service, "device": ""}
            services.append(current)
            continue
        port_match = re.match(r"^\(Hardware Port:\s*(.*?),\s*Device:\s*(.*?)\)$", line)
        if port_match and current is not None:
            current["hardware_port"] = port_match.group(1).strip()
            current["device"] = port_match.group(2).strip()
    return [item for item in services if item.get("device")]


def _parse_hardware_ports(text):
    services = []
    current = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current.get("device"):
                current.setdefault("service", current.get("hardware_port", ""))
                services.append(current)
            current = {}
            continue
        if line.startswith("Hardware Port:"):
            current["hardware_port"] = line.split(":", 1)[1].strip()
            current.setdefault("service", current["hardware_port"])
        elif line.startswith("Device:"):
            current["device"] = line.split(":", 1)[1].strip()
        elif line.startswith("Ethernet Address:"):
            current["mac"] = line.split(":", 1)[1].strip()
    if current.get("device"):
        current.setdefault("service", current.get("hardware_port", ""))
        services.append(current)
    return services


def _mac_services():
    try:
        services = _parse_service_order(_run_text([NETWORKSETUP, "-listnetworkserviceorder"]))
        if services:
            return services
    except Exception:
        pass
    try:
        return _parse_hardware_ports(_run_text([NETWORKSETUP, "-listallhardwareports"]))
    except Exception:
        return []


def _netmask_to_dotted(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("0x"):
        try:
            number = int(text, 16)
        except ValueError:
            return ""
        return ".".join(str((number >> shift) & 0xFF) for shift in (24, 16, 8, 0))
    try:
        ipv4_octets(text, "subnet")
        return text
    except ValueError:
        return ""


def _network_for(ip, subnet):
    ipv4_octets(ip, "ip")
    ipv4_octets(subnet, "subnet")
    return ipaddress.IPv4Interface(f"{ip}/{subnet}").network


def _is_usable_host(ip, network):
    address = ipaddress.IPv4Address(ip)
    if network.prefixlen >= 31:
        return address in network
    return address in network and address not in (network.network_address, network.broadcast_address)


def _network_summary(ip, subnet):
    if not (ip and subnet):
        return {}
    try:
        network = _network_for(ip, subnet)
    except ValueError:
        return {}
    if network.num_addresses > 2:
        usable_first = network.network_address + 1
        usable_last = network.broadcast_address - 1
        usable_count = network.num_addresses - 2
    else:
        usable_first = network.network_address
        usable_last = network.broadcast_address
        usable_count = network.num_addresses
    return {
        "cidr": str(network),
        "network": str(network.network_address),
        "broadcast": str(network.broadcast_address),
        "prefix": network.prefixlen,
        "usable_first": str(usable_first),
        "usable_last": str(usable_last),
        "usable_range": f"{usable_first} - {usable_last}",
        "usable_count": usable_count,
    }


def _same_subnet(ip, reference_ip, subnet):
    if not (ip and reference_ip and subnet):
        return False
    try:
        network = _network_for(reference_ip, subnet)
        address = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return address in network


def _parse_ifconfig(text):
    interfaces = {}
    current_name = None
    current_lines = []

    def flush():
        if not current_name:
            return
        body = "\n".join(current_lines)
        header = current_lines[0] if current_lines else ""
        flags_match = re.search(r"<([^>]*)>", header)
        flags = set()
        if flags_match:
            flags = {part.strip() for part in flags_match.group(1).split(",")}
        inet_match = re.search(
            r"\binet\s+([\d.]+)\s+netmask\s+([^\s]+)(?:\s+broadcast\s+([\d.]+))?",
            body,
        )
        status_match = re.search(r"\bstatus:\s*(\S+)", body)
        interfaces[current_name] = {
            "flags": sorted(flags),
            "up": "UP" in flags,
            "running": "RUNNING" in flags,
            "status": status_match.group(1) if status_match else "",
            "ipv4": inet_match.group(1) if inet_match else "",
            "subnet": _netmask_to_dotted(inet_match.group(2)) if inet_match else "",
            "broadcast": inet_match.group(3) if inet_match and inet_match.group(3) else "",
        }

    for raw_line in text.splitlines():
        header_match = re.match(r"^([a-zA-Z0-9_.-]+):\s+flags=", raw_line)
        if header_match:
            flush()
            current_name = header_match.group(1)
            current_lines = [raw_line]
        elif current_name:
            current_lines.append(raw_line)
    flush()
    return interfaces


def _mac_ifconfig():
    try:
        return _parse_ifconfig(_run_text(["/sbin/ifconfig"]))
    except Exception:
        return {}


def _mac_default_route():
    try:
        text = _run_text(["/sbin/route", "-n", "get", "default"])
    except Exception:
        return {"interface": "", "gateway": ""}
    out = {"interface": "", "gateway": ""}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("interface:"):
            out["interface"] = line.split(":", 1)[1].strip()
        elif line.startswith("gateway:"):
            out["gateway"] = line.split(":", 1)[1].strip()
    return out


def _mac_wifi_ssid(device):
    if not device:
        return ""

    def ssid_from_keyed_lines(text, keys):
        for key in keys:
            pattern = re.compile(rf"^{re.escape(key)}\s*[:=]\s*(.+)$", re.IGNORECASE)
            for raw_line in str(text or "").splitlines():
                match = pattern.match(raw_line.strip())
                if match:
                    ssid = _clean_ssid(match.group(1))
                    if ssid:
                        return ssid
        return ""

    try:
        text = _run_text([NETWORKSETUP, "-getairportnetwork", device])
    except Exception:
        text = ""
    if ":" in text:
        left, right = text.split(":", 1)
        if "network" in left.lower():
            ssid = _clean_ssid(right)
            if ssid:
                return ssid

    try:
        text = _run_text_input([SCUTIL], f"show State:/Network/Interface/{device}/AirPort\n")
    except Exception:
        text = ""
    ssid = ssid_from_keyed_lines(text, ("SSID_STR", "SSID"))
    if ssid:
        return ssid

    for args in (("/usr/sbin/ipconfig", "getsummary", device), (AIRPORT, "-I")):
        try:
            text = _run_text(list(args))
        except Exception:
            continue
        ssid = ssid_from_keyed_lines(text, ("SSID_STR", "SSID"))
        if ssid:
            return ssid
    return ""


def _matches_preferred(interface, preferred):
    preferred = preferred or {}
    preferred_ssid = preferred.get("ssid")
    if preferred_ssid and interface.get("type") == "wifi" and interface.get("ssid") != preferred_ssid:
        return False
    preferred_id = preferred.get("id")
    if preferred_id and interface.get("id") == preferred_id:
        return True
    preferred_device = preferred.get("device")
    preferred_service = preferred.get("service")
    return bool(
        preferred_device
        and interface.get("device") == preferred_device
        and (not preferred_service or interface.get("service") == preferred_service)
    )


def _matches_controller(interface, controller_connection):
    controller_connection = controller_connection or {}
    controller_ssid = controller_connection.get("ssid")
    if controller_ssid:
        if interface.get("type") != "wifi":
            return False
        if interface.get("ssid"):
            return interface.get("ssid") == controller_ssid
        controller_source_ip = controller_connection.get("source_ip")
        return bool(controller_source_ip and interface.get("source_ip") == controller_source_ip)
    controller_id = controller_connection.get("id")
    if controller_id and interface.get("id") == controller_id:
        return True
    controller_device = controller_connection.get("device")
    controller_service = controller_connection.get("service")
    return bool(
        controller_device
        and interface.get("device") == controller_device
        and (not controller_service or interface.get("service") == controller_service)
    )


def _mac_interfaces(settings):
    services = _mac_services()
    ifaces = _mac_ifconfig()
    route = _mac_default_route()
    preferred = settings.get("preferred", {})
    controller_connection = settings.get("controller_connection", {})
    interfaces = []
    for service in services:
        device = service.get("device", "")
        ifinfo = ifaces.get(device, {})
        item_type = _interface_type(service.get("hardware_port") or service.get("service"))
        ipv4 = ifinfo.get("ipv4", "")
        item = {
            "id": _interface_id(service.get("service", ""), device),
            "service": service.get("service", ""),
            "hardware_port": service.get("hardware_port", service.get("service", "")),
            "device": device,
            "type": item_type,
            "ssid": _mac_wifi_ssid(device) if item_type == "wifi" else "",
            "ipv4": ipv4,
            "source_ip": ipv4,
            "subnet": ifinfo.get("subnet", ""),
            "broadcast": ifinfo.get("broadcast", ""),
            "gateway": route.get("gateway", "") if route.get("interface") == device else "",
            "network": _network_summary(ipv4, ifinfo.get("subnet", "")),
            "connected": bool(ipv4 and (ifinfo.get("running") or ifinfo.get("status") == "active")),
            "is_default": route.get("interface") == device,
            "is_preferred": False,
            "is_controller": False,
            "warnings": [],
        }
        item["is_preferred"] = _matches_preferred(item, preferred)
        item["is_controller"] = _matches_controller(item, controller_connection)
        if item["is_preferred"] and not item["connected"]:
            item["warnings"].append("Preferred connection is not active.")
        elif item["is_preferred"] and not item["ipv4"]:
            item["warnings"].append("Preferred connection has no IPv4 address.")
        interfaces.append(item)
    type_priority = {"ethernet": 0, "wifi": 1, "other": 2}
    interfaces.sort(key=lambda item: (not item["connected"], type_priority.get(item["type"], 3), not item["is_default"], item["service"]))
    return interfaces, route


def get_network_status():
    settings = load_settings()
    status = {
        "supported": sys.platform == "darwin",
        "platform": sys.platform,
        "interfaces": [],
        "preferred": settings.get("preferred", {}),
        "controller_connection": settings.get("controller_connection", {}),
        "selected_interface": None,
        "current_route": {"interface": "", "gateway": ""},
        "ssid_profiles": settings.get("ssid_profiles", {}),
        "service_profiles": settings.get("service_profiles", {}),
        "last_applied": settings.get("last_applied", {}),
        "warnings": [],
    }
    if sys.platform != "darwin":
        status["warnings"].append("Host network switching is currently supported on macOS only.")
        return status

    interfaces, route = _mac_interfaces(settings)
    selected = next((item for item in interfaces if item.get("is_preferred") and item.get("connected")), None)
    if selected is None:
        selected = next((item for item in interfaces if item.get("is_controller") and item.get("connected")), None)
    recommended = next((item for item in interfaces if item.get("type") == "ethernet" and item.get("connected")), None)
    if recommended is None:
        recommended = selected or next((item for item in interfaces if item.get("connected")), None)
    if settings.get("preferred", {}).get("id") and selected is None:
        status["warnings"].append("Saved preferred connection is not currently available.")
    status.update({
        "interfaces": interfaces,
        "selected_interface": selected,
        "recommended_interface": recommended,
        "selected_network": selected.get("network", {}) if selected else {},
        "recommended_network": recommended.get("network", {}) if recommended else {},
        "current_route": route,
    })
    return status


def get_artnet_interface():
    status = get_network_status()
    selected = status.get("selected_interface")
    if not selected or not selected.get("connected") or not selected.get("source_ip"):
        return None
    return dict(selected)


def _find_interface(status, data=None):
    data = data or {}
    interface_id = str(data.get("id") or data.get("interface_id") or "")
    service = str(data.get("service") or "")
    device = str(data.get("device") or "")
    if not (interface_id or service or device):
        selected = status.get("selected_interface")
        if selected:
            return selected
    for interface in status.get("interfaces", []):
        if interface_id and interface.get("id") == interface_id:
            return interface
        if service and interface.get("service") == service and (not device or interface.get("device") == device):
            return interface
        if device and interface.get("device") == device and (not service or interface.get("service") == service):
            return interface
    return None


def set_preferred_interface(data):
    settings = load_settings()
    if data.get("mode") == "auto" or data.get("id") in (None, "") and not data.get("service") and not data.get("device"):
        settings["preferred"] = copy.deepcopy(DEFAULT_SETTINGS["preferred"])
        save_settings(settings)
        return get_network_status()
    status = get_network_status()
    interface = _find_interface(status, data)
    if not interface:
        raise NetworkSettingsError(409, "selected connection is not available")
    settings["preferred"] = {
        "id": interface.get("id", ""),
        "service": interface.get("service", ""),
        "device": interface.get("device", ""),
        "ssid": interface.get("ssid", "") if interface.get("type") == "wifi" else "",
        "source_ip": interface.get("source_ip", ""),
    }
    save_settings(settings)
    return get_network_status()


def set_controller_connection(data):
    settings = load_settings()
    if data.get("mode") == "clear":
        settings["controller_connection"] = copy.deepcopy(DEFAULT_SETTINGS["controller_connection"])
        save_settings(settings)
        return get_network_status()
    status = get_network_status()
    has_interface_selector = bool(data.get("id") or data.get("interface_id") or data.get("service") or data.get("device"))
    interface = _find_interface(status, data) if has_interface_selector else None
    controller_ssid = _clean_ssid(data.get("ssid"))
    if interface and interface.get("type") != "wifi":
        raise NetworkSettingsError(400, "controller connection tagging is currently for WiFi services")
    if interface and not controller_ssid:
        controller_ssid = str(interface.get("ssid") or "").strip()
    if not controller_ssid:
        raise NetworkSettingsError(400, "controller WiFi SSID required")
    settings["controller_connection"] = {
        "id": interface.get("id", "") if interface else str(data.get("id") or data.get("interface_id") or ""),
        "service": interface.get("service", "") if interface else str(data.get("service") or ""),
        "device": interface.get("device", "") if interface else str(data.get("device") or ""),
        "ssid": controller_ssid,
        "source_ip": interface.get("source_ip", "") if interface else "",
    }
    save_settings(settings)
    return get_network_status()


def _profile_from_payload(data, interface=None):
    mode = str(data.get("mode") or "static").lower()
    if mode not in ("static", "dhcp"):
        raise NetworkSettingsError(400, "mode must be static or dhcp")
    interface = interface or {}
    profile = {
        "mode": mode,
        "service": str(data.get("service") or interface.get("service") or ""),
        "device": str(data.get("device") or interface.get("device") or ""),
        "ssid": _clean_ssid(data.get("ssid") or interface.get("ssid") or ""),
    }
    if mode == "static":
        static_ip = str(data.get("ip") or data.get("static_ip") or "").strip()
        gateway = str(data.get("gateway") or "").strip()
        subnet = str(data.get("subnet") or "").strip()
        if not (static_ip and gateway and subnet):
            raise NetworkSettingsError(400, "ip, gateway, and subnet required")
        ipv4_octets(static_ip, "ip")
        ipv4_octets(gateway, "gateway")
        ipv4_octets(subnet, "subnet")
        network = _network_for(static_ip, subnet)
        if not _is_usable_host(static_ip, network):
            raise ValueError("ip must be a usable host address in the selected subnet")
        if ipaddress.IPv4Address(gateway) not in network:
            raise ValueError("gateway must be in the same subnet as ip")
        profile.update({"ip": static_ip, "gateway": gateway, "subnet": subnet})
    return profile


def save_profile(data):
    settings = load_settings()
    status = get_network_status()
    interface = _find_interface(status, data) or {}
    try:
        profile = _profile_from_payload(data, interface)
    except ValueError as error:
        raise NetworkSettingsError(400, str(error)) from error
    scope = str(data.get("scope") or ("ssid" if profile.get("ssid") else "service"))
    if scope == "ssid":
        key = profile.get("ssid")
        if not key:
            raise NetworkSettingsError(400, "ssid required")
        settings["ssid_profiles"][key] = profile
    elif scope == "service":
        key = profile.get("service") or profile.get("device")
        if not key:
            raise NetworkSettingsError(400, "service or device required")
        settings["service_profiles"][key] = profile
    else:
        raise NetworkSettingsError(400, "scope must be ssid or service")
    save_settings(settings)
    return get_network_status()


def _require_macos():
    if sys.platform != "darwin":
        raise NetworkSettingsError(501, "host network changes are currently supported on macOS only")


def _run_privileged_networksetup(args):
    command = " ".join(shlex.quote(arg) for arg in args)
    script = "do shell script " + json.dumps(command) + " with administrator privileges"
    try:
        subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            text=True,
            capture_output=True,
            check=True,
            timeout=60,
        )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "").strip()
        raise NetworkSettingsError(409, detail or "network setup command failed") from error
    except subprocess.TimeoutExpired as error:
        raise NetworkSettingsError(409, "network setup command timed out") from error


def apply_static_ip(data):
    _require_macos()
    status = get_network_status()
    interface = _find_interface(status, data)
    if not interface:
        raise NetworkSettingsError(409, "selected connection is not available")
    try:
        profile = _profile_from_payload({**data, "mode": "static"}, interface)
    except ValueError as error:
        raise NetworkSettingsError(400, str(error)) from error
    if interface.get("type") == "wifi" and profile.get("ssid") and interface.get("ssid") != profile.get("ssid"):
        raise NetworkSettingsError(409, "selected WiFi service is not connected to the saved SSID")
    save_profile({**profile, "scope": "ssid" if profile.get("ssid") else "service"})
    _run_privileged_networksetup([
        NETWORKSETUP,
        "-setmanual",
        interface["service"],
        profile["ip"],
        profile["subnet"],
        profile["gateway"],
    ])
    settings = load_settings()
    settings["last_applied"] = {**profile, "service": interface["service"], "device": interface["device"]}
    save_settings(settings)
    return get_network_status()


def set_dhcp(data):
    _require_macos()
    status = get_network_status()
    interface = _find_interface(status, data)
    if not interface:
        raise NetworkSettingsError(409, "selected connection is not available")
    if not interface.get("service"):
        raise NetworkSettingsError(400, "network service required")
    _run_privileged_networksetup([NETWORKSETUP, "-setdhcp", interface["service"]])
    settings = load_settings()
    profile = {
        "mode": "dhcp",
        "service": interface.get("service", ""),
        "device": interface.get("device", ""),
        "ssid": interface.get("ssid", ""),
    }
    if profile.get("ssid"):
        settings["ssid_profiles"][profile["ssid"]] = profile
    else:
        settings["service_profiles"][profile["service"] or profile["device"]] = profile
    settings["last_applied"] = profile
    save_settings(settings)
    return get_network_status()