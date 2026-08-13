"""Sender network settings for Radius Central.

This module keeps host-network configuration separate from receiver device
configuration. It is intentionally stdlib-only so packaged sender builds remain
dependency-free.
"""

import copy
import base64
import ipaddress
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time

from artnet import ipv4_octets
from paths import state_file


STATE_KEY = "sender_network"
NETWORKSETUP = "/usr/sbin/networksetup"
SCUTIL = "/usr/sbin/scutil"
AIRPORT = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"
POWERSHELL = "powershell.exe"

# UDP lane defaults — docs/systems/PORT_ORGANIZATION.md. Kept in sync with the
# artnet.py PORT_* constants; duplicated here (rather than imported) so this
# module's DEFAULT_SETTINGS literal stays self-contained and dependency-light.
LANE_PORT_KEYS = ("port_show_primus", "port_show_radius", "port_setup", "port_watch")
DEFAULT_LANE_PORTS = {
    "port_show_primus": 6454,
    "port_show_radius": 6456,
    "port_setup": 6457,
    "port_watch": 6455,
}
LANE_PORT_MIN = 1024
LANE_PORT_MAX = 65535

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
    "lane_ports": dict(DEFAULT_LANE_PORTS),
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
    lane_ports = dict(DEFAULT_LANE_PORTS)
    saved_lane_ports = settings.get("lane_ports")
    if isinstance(saved_lane_ports, dict):
        for key in LANE_PORT_KEYS:
            try:
                value = int(saved_lane_ports.get(key, lane_ports[key]))
            except (TypeError, ValueError):
                continue
            if LANE_PORT_MIN <= value <= LANE_PORT_MAX:
                lane_ports[key] = value
    out["lane_ports"] = lane_ports
    return out


def load_settings():
    return _normalize_settings(_read_state().get(STATE_KEY))


def save_settings(settings):
    data = _read_state()
    data[STATE_KEY] = _normalize_settings(settings)
    _write_state(data)
    return data[STATE_KEY]


def _validate_lane_port_value(name, value):
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise NetworkSettingsError(400, f"{name} must be an integer")
    if port < LANE_PORT_MIN or port > LANE_PORT_MAX:
        raise NetworkSettingsError(400, f"{name} must be {LANE_PORT_MIN}-{LANE_PORT_MAX}")
    return port


def _validate_lane_ports_dict(data):
    data = data or {}
    ports = {}
    for key in LANE_PORT_KEYS:
        if key not in data:
            raise NetworkSettingsError(400, f"{key} required")
        ports[key] = _validate_lane_port_value(key, data[key])
    show_primus = ports["port_show_primus"]
    show_radius = ports["port_show_radius"]
    setup = ports["port_setup"]
    watch = ports["port_watch"]
    # show_primus and show_radius may collide with each other freely, but
    # Setup must never share a lane with either Show port or with Watch, and
    # Watch must never share a lane with Setup.
    if setup in (show_primus, show_radius, watch):
        raise NetworkSettingsError(
            400, "port_setup must differ from port_show_primus, port_show_radius, and port_watch")
    if watch == setup:
        raise NetworkSettingsError(400, "port_watch must differ from port_setup")
    return ports


def get_lane_ports():
    """Current default UDP lane ports (Show/Setup/Watch) as an int dict."""
    return dict(load_settings().get("lane_ports") or DEFAULT_LANE_PORTS)


def set_lane_ports(data):
    """Validate and persist new default UDP lane ports. Returns the saved dict."""
    ports = _validate_lane_ports_dict(data)
    settings = load_settings()
    settings["lane_ports"] = ports
    save_settings(settings)
    return dict(ports)


def _no_window_subprocess_kwargs():
    if os.name != "nt":
        return {}
    kwargs = {}
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creation_flags:
        kwargs["creationflags"] = creation_flags
    startupinfo_class = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_class is not None:
        startupinfo = startupinfo_class()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _run_text(args, timeout=4.0):
    return subprocess.check_output(
        args,
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        **_no_window_subprocess_kwargs(),
    )


def _run_text_input(args, input_text, timeout=4.0):
    return subprocess.check_output(
        args,
        input=input_text,
        text=True,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        **_no_window_subprocess_kwargs(),
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


def _prefix_to_dotted(prefix):
    try:
        value = int(prefix)
    except (TypeError, ValueError):
        return ""
    if value < 0 or value > 32:
        return ""
    mask = (0xFFFFFFFF << (32 - value)) & 0xFFFFFFFF if value else 0
    return ".".join(str((mask >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def _windows_json(script, timeout=8.0):
    text = _run_text([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout=timeout)
    text = str(text or "").strip()
    if not text:
        return {}
    return json.loads(text)


def _windows_network_snapshot():
    script = r'''
$ErrorActionPreference = 'SilentlyContinue'
$defaultRoute = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric, InterfaceMetric | Select-Object -First 1)[0]
$items = foreach ($adapter in Get-NetAdapter) {
    $ipConfig = Get-NetIPConfiguration -InterfaceIndex $adapter.ifIndex
    $ipInterface = @(Get-NetIPInterface -AddressFamily IPv4 -InterfaceIndex $adapter.ifIndex | Select-Object -First 1)[0]
    $addresses = @($ipConfig.IPv4Address | Where-Object { $_.IPAddress -and $_.IPAddress -notlike '169.254.*' })
    if ($addresses.Count -eq 0) { $addresses = @($ipConfig.IPv4Address) }
    $address = @($addresses | Select-Object -First 1)[0]
    $gateway = @($ipConfig.IPv4DefaultGateway | Select-Object -First 1)[0]
    $dhcpText = if ($ipInterface) { [string]$ipInterface.Dhcp } else { '' }
    $mode = if ($dhcpText -match 'Enabled|1') { 'dhcp' } elseif ($dhcpText -match 'Disabled|0') { 'static' } else { 'unknown' }
    $ipv4 = ''
    $prefixLength = $null
    if ($address) {
        $ipv4 = [string]$address.IPAddress
        $prefixLength = [int]$address.PrefixLength
    }
    $gatewayHop = ''
    if ($gateway) { $gatewayHop = [string]$gateway.NextHop }
    [pscustomobject]@{
        service = [string]$adapter.Name
        device = [string]$adapter.ifIndex
        hardware_port = [string]$adapter.InterfaceDescription
        interface_guid = [string]$adapter.InterfaceGuid
        status = [string]$adapter.Status
        media_connection_state = [string]$adapter.MediaConnectionState
        physical_medium = [string]$adapter.NdisPhysicalMedium
        if_type = [int]$adapter.InterfaceType
        mac = [string]$adapter.MacAddress
        ipv4 = $ipv4
        prefix_length = $prefixLength
        gateway = $gatewayHop
        configured_mode = $mode
        connected = (($adapter.Status -eq 'Up') -and ($address -ne $null))
        is_default = (($defaultRoute -ne $null) -and ($defaultRoute.InterfaceIndex -eq $adapter.ifIndex))
    }
}
$routeInterface = ''
$routeGateway = ''
if ($defaultRoute) {
    $routeInterface = [string]$defaultRoute.InterfaceIndex
    $routeGateway = [string]$defaultRoute.NextHop
}
[pscustomobject]@{
    interfaces = @($items)
    default_route = [pscustomobject]@{ interface = $routeInterface; gateway = $routeGateway }
} | ConvertTo-Json -Depth 5 -Compress
'''
    try:
        data = _windows_json(script)
    except Exception:
        return {"interfaces": [], "default_route": {"interface": "", "gateway": ""}}
    if not isinstance(data, dict):
        return {"interfaces": [], "default_route": {"interface": "", "gateway": ""}}
    interfaces = data.get("interfaces") or []
    if isinstance(interfaces, dict):
        interfaces = [interfaces]
    data["interfaces"] = [item for item in interfaces if isinstance(item, dict)]
    if not isinstance(data.get("default_route"), dict):
        data["default_route"] = {"interface": "", "gateway": ""}
    return data


def _parse_windows_wlan_interfaces(text):
    networks = {}
    current = {}

    def flush():
        name = str(current.get("name") or "").strip()
        state = str(current.get("state") or "").strip().lower()
        ssid = _clean_ssid(current.get("ssid"))
        if name and state == "connected" and ssid:
            networks[name] = ssid

    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ":" not in line:
            continue
        key, value = [part.strip() for part in line.split(":", 1)]
        key_lower = key.lower()
        if key_lower == "name":
            flush()
            current = {"name": value}
        elif key_lower in ("state", "ssid", "description"):
            current[key_lower] = value
    flush()
    return networks


def _windows_wifi_ssids():
    try:
        return _parse_windows_wlan_interfaces(_run_text(["netsh", "wlan", "show", "interfaces"], timeout=4.0))
    except Exception:
        return {}


def _windows_interface_type(item):
    if_type = str(item.get("if_type") or "")
    physical_medium = str(item.get("physical_medium") or "").lower()
    if if_type == "71" or physical_medium in ("9", "native 802.11", "wireless lan"):
        return "wifi"
    return _interface_type(" ".join(str(item.get(key) or "") for key in ("service", "hardware_port")))


def _windows_interfaces(settings):
    snapshot = _windows_network_snapshot()
    route = snapshot.get("default_route", {"interface": "", "gateway": ""})
    ssids = _windows_wifi_ssids()
    preferred = settings.get("preferred", {})
    controller_connection = settings.get("controller_connection", {})
    interfaces = []
    for item in snapshot.get("interfaces", []):
        service = str(item.get("service") or "")
        device = str(item.get("device") or "")
        item_type = _windows_interface_type(item)
        ipv4 = str(item.get("ipv4") or "")
        subnet = _prefix_to_dotted(item.get("prefix_length"))
        gateway = str(item.get("gateway") or "") or (route.get("gateway", "") if route.get("interface") == device else "")
        configured_mode = str(item.get("configured_mode") or "unknown")
        connected = bool(item.get("connected") and ipv4)
        interface = {
            "id": _interface_id(service, device),
            "service": service,
            "hardware_port": str(item.get("hardware_port") or service),
            "device": device,
            "type": item_type,
            "ssid": ssids.get(service, "") if item_type == "wifi" else "",
            "ipv4": ipv4,
            "source_ip": ipv4,
            "subnet": subnet,
            "broadcast": _network_summary(ipv4, subnet).get("broadcast", ""),
            "gateway": gateway,
            "network": _network_summary(ipv4, subnet),
            "configured_mode": configured_mode,
            "configured_ip": ipv4 if configured_mode == "static" else "",
            "configured_subnet": subnet if configured_mode == "static" else "",
            "configured_gateway": gateway if configured_mode == "static" else "",
            "configured_network": _network_summary(ipv4, subnet) if configured_mode == "static" else {},
            "connected": connected,
            "is_default": bool(item.get("is_default")) or route.get("interface") == device,
            "is_preferred": False,
            "is_controller": False,
            "warnings": [],
        }
        interface["is_preferred"] = _matches_preferred(interface, preferred)
        interface["is_controller"] = _matches_controller(interface, controller_connection)
        if interface["is_preferred"] and not interface["connected"]:
            interface["warnings"].append("Preferred connection is not active.")
        elif interface["is_preferred"] and not interface["ipv4"]:
            interface["warnings"].append("Preferred connection has no IPv4 address.")
        interfaces.append(interface)
    type_priority = {"ethernet": 0, "wifi": 1, "other": 2}
    interfaces.sort(key=lambda entry: (not entry["connected"], type_priority.get(entry["type"], 3), not entry["is_default"], entry["service"]))
    return interfaces, route


def _clean_network_value(value):
    text = str(value or "").strip()
    return "" if text.lower() in ("", "none", "unknown") else text


def _parse_networksetup_info(text):
    info = {
        "configured_mode": "unknown",
        "configured_ip": "",
        "configured_subnet": "",
        "configured_gateway": "",
    }
    body = str(text or "")
    if "Manual Configuration" in body:
        info["configured_mode"] = "static"
    elif "DHCP Configuration" in body:
        info["configured_mode"] = "dhcp"
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("IP address:"):
            info["configured_ip"] = _clean_network_value(line.split(":", 1)[1])
        elif line.startswith("Subnet mask:"):
            info["configured_subnet"] = _clean_network_value(line.split(":", 1)[1])
        elif line.startswith("Router:"):
            info["configured_gateway"] = _clean_network_value(line.split(":", 1)[1])
    return info


def _mac_service_info(service):
    if not service:
        return {}
    try:
        return _parse_networksetup_info(_run_text([NETWORKSETUP, "-getinfo", service]))
    except Exception:
        return {}


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
        link_status = ifinfo.get("status", "")
        connected = bool(
            ifinfo.get("ipv4", "")
            and ifinfo.get("up")
            and (
                link_status == "active"
                or (not link_status and ifinfo.get("running"))
            )
        )
        item_type = _interface_type(service.get("hardware_port") or service.get("service"))
        ipv4 = ifinfo.get("ipv4", "")
        service_info = _mac_service_info(service.get("service", ""))
        gateway = route.get("gateway", "") if route.get("interface") == device else ""
        gateway = gateway or service_info.get("configured_gateway", "")
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
            "gateway": gateway,
            "network": _network_summary(ipv4, ifinfo.get("subnet", "")),
            "configured_mode": service_info.get("configured_mode", "unknown"),
            "configured_ip": service_info.get("configured_ip", ""),
            "configured_subnet": service_info.get("configured_subnet", ""),
            "configured_gateway": service_info.get("configured_gateway", ""),
            "configured_network": _network_summary(
                service_info.get("configured_ip", ""),
                service_info.get("configured_subnet", ""),
            ),
            "connected": connected,
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
        if item["configured_mode"] == "static" and item["configured_ip"]:
            if item["ipv4"] and item["ipv4"] != item["configured_ip"]:
                item["warnings"].append(
                    f"macOS is configured for {item['configured_ip']}, but the adapter currently reports {item['ipv4']}."
                )
            elif not item["ipv4"]:
                item["warnings"].append(
                    f"macOS is configured for static IP {item['configured_ip']}, but the adapter has no live IPv4 address."
                )
        interfaces.append(item)
    type_priority = {"ethernet": 0, "wifi": 1, "other": 2}
    interfaces.sort(key=lambda item: (not item["connected"], type_priority.get(item["type"], 3), not item["is_default"], item["service"]))
    return interfaces, route


_status_cache_lock = threading.Lock()
_status_cache = {"at": 0.0, "value": None}
_STATUS_CACHE_SECONDS = 2.0


def get_network_status():
    # Memoized briefly: this shells out to networksetup/ifconfig/route
    # (one subprocess per network service) and is called from most device
    # routes plus a 15 s poll from every open frontend. Without a cache an
    # operator action bursts a dozen process spawns, and a hung
    # networksetup call stalls the HTTP thread.
    now = time.monotonic()
    with _status_cache_lock:
        cached = _status_cache["value"]
        if cached is not None and (now - _status_cache["at"]) < _STATUS_CACHE_SECONDS:
            return copy.deepcopy(cached)
    status = _get_network_status_uncached()
    with _status_cache_lock:
        _status_cache["value"] = copy.deepcopy(status)
        _status_cache["at"] = time.monotonic()
    return status


def _get_network_status_uncached():
    settings = load_settings()
    supported = sys.platform == "darwin" or sys.platform.startswith("win")
    status = {
        "supported": supported,
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
    if not supported:
        status["warnings"].append("Host network switching is currently supported on macOS and Windows only.")
        return status

    if sys.platform == "darwin":
        interfaces, route = _mac_interfaces(settings)
    else:
        interfaces, route = _windows_interfaces(settings)
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


def _require_host_network_changes_supported():
    if sys.platform == "darwin" or sys.platform.startswith("win"):
        return
    raise NetworkSettingsError(501, "host network changes are currently supported on macOS and Windows only")


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


def _encoded_powershell(script):
    return base64.b64encode(str(script).encode("utf-16le")).decode("ascii")


def _run_privileged_windows_script(script):
    encoded = _encoded_powershell(script)
    launcher = (
        "$process = Start-Process -FilePath 'powershell.exe' "
        "-ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand','" + encoded + "') "
        "-Verb RunAs -WindowStyle Hidden -Wait -PassThru; "
        "if ($null -eq $process -or $null -eq $process.ExitCode) { exit 1 }; "
        "exit $process.ExitCode"
    )
    try:
        subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", launcher],
            text=True,
            capture_output=True,
            check=True,
            timeout=120,
            **_no_window_subprocess_kwargs(),
        )
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "").strip()
        raise NetworkSettingsError(409, detail or "Windows network setup command failed or was cancelled") from error
    except subprocess.TimeoutExpired as error:
        raise NetworkSettingsError(409, "Windows network setup command timed out") from error


def _ps_single_quote(value):
    return "'" + str(value or "").replace("'", "''") + "'"


def _run_windows_static_ip(interface, profile):
    alias = interface.get("service") or interface.get("device")
    if not alias:
        raise NetworkSettingsError(400, "network interface alias required")
    script = f"""
$ErrorActionPreference = 'Stop'
$alias = {_ps_single_quote(alias)}
& netsh.exe interface ipv4 set address name="$alias" static {profile['ip']} {profile['subnet']} {profile['gateway']} 1
if ($LASTEXITCODE -ne 0) {{ exit $LASTEXITCODE }}
exit 0
"""
    _run_privileged_windows_script(script)


def _run_windows_dhcp(interface):
    alias = interface.get("service") or interface.get("device")
    if not alias:
        raise NetworkSettingsError(400, "network interface alias required")
    script = f"""
$ErrorActionPreference = 'Stop'
$alias = {_ps_single_quote(alias)}
& netsh.exe interface ipv4 set address name="$alias" source=dhcp
if ($LASTEXITCODE -ne 0) {{ exit $LASTEXITCODE }}
& netsh.exe interface ipv4 set dnsservers name="$alias" source=dhcp
exit 0
"""
    _run_privileged_windows_script(script)


def _wait_for_interface_ip(device, expected_ip, expected_subnet, timeout=6.0):
    if not device or not expected_ip:
        return False
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if sys.platform == "darwin":
            info = _mac_ifconfig().get(device, {})
            if info.get("ipv4") == expected_ip:
                if not expected_subnet or info.get("subnet") == expected_subnet:
                    return True
        elif sys.platform.startswith("win"):
            interfaces, _route = _windows_interfaces(load_settings())
            for item in interfaces:
                if item.get("device") == device or item.get("service") == device:
                    if item.get("ipv4") == expected_ip:
                        if not expected_subnet or item.get("subnet") == expected_subnet:
                            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


def _stored_connection_matches(saved, interface):
    saved = saved or {}
    if saved.get("id") and saved.get("id") == interface.get("id"):
        return True
    if saved.get("device") and saved.get("device") == interface.get("device"):
        service = saved.get("service")
        return not service or service == interface.get("service")
    return False


def _update_saved_source_ip(settings, interface, source_ip):
    for key in ("preferred", "controller_connection"):
        if _stored_connection_matches(settings.get(key), interface):
            settings[key]["source_ip"] = source_ip


def apply_static_ip(data):
    _require_host_network_changes_supported()
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
    if sys.platform == "darwin":
        _run_privileged_networksetup([
            NETWORKSETUP,
            "-setmanual",
            interface["service"],
            profile["ip"],
            profile["subnet"],
            profile["gateway"],
        ])
    else:
        _run_windows_static_ip(interface, profile)
    confirmed = _wait_for_interface_ip(interface.get("device", ""), profile["ip"], profile["subnet"])
    settings = load_settings()
    _update_saved_source_ip(settings, interface, profile["ip"])
    settings["last_applied"] = {
        **profile,
        "service": interface["service"],
        "device": interface["device"],
        "confirmed": confirmed,
    }
    save_settings(settings)
    status = get_network_status()
    if not confirmed:
        platform_name = "macOS" if sys.platform == "darwin" else "Windows"
        status["warnings"].append(
            f"{platform_name} accepted the static profile, but the adapter has not reported the new IP yet. Refresh after the link settles, and check the cable/router if it stays pending."
        )
    return status


def set_dhcp(data):
    _require_host_network_changes_supported()
    status = get_network_status()
    interface = _find_interface(status, data)
    if not interface:
        raise NetworkSettingsError(409, "selected connection is not available")
    if not interface.get("service"):
        raise NetworkSettingsError(400, "network service required")
    if sys.platform == "darwin":
        _run_privileged_networksetup([NETWORKSETUP, "-setdhcp", interface["service"]])
    else:
        _run_windows_dhcp(interface)
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