"""
radius_state.py — Slim runtime state for Radius Central device and audio control.
"""

import json
import os
import threading
import time

from artnet import (
    parse_node_capabilities,
    send_art_address,
    send_ip_config,
    send_audio_cmd,
    AUDIO_CMD_STOP,
    AUDIO_CMD_PLAY,
    AUDIO_CMD_LOOP,
    AUDIO_CMD_PAUSE,
    AUDIO_CMD_VOLUME,
    AUDIO_CMD_TEST_TONE,
    ftp_list_dir,
    ftp_upload,
    ftp_download,
    ftp_rename,
    ftp_delete,
    ftp_mkdir,
    discover_artnet_nodes,
    RADIUS_ARTNET_PORT,
)
from paths import state_file


DEFAULT_RADIUS_CAPABILITIES = {
    "profile": "pvrad1",
    "device_class": "radius",
    "hardware_profile": "v1",
    "hardware_label": "V1 Huzzah32",
    "firmware_version": None,
    "ip_mode": "unknown",
    "static_ip": None,
    "gateway": None,
    "subnet": None,
    "known": False,
    "rename": False,
    "hello": False,
    "ip_config": False,
    "audio": False,
    "ftp": False,
}

AUDIO_CMD_MAP = {
    "stop": AUDIO_CMD_STOP,
    "play": AUDIO_CMD_PLAY,
    "loop": AUDIO_CMD_LOOP,
    "pause": AUDIO_CMD_PAUSE,
    "volume": AUDIO_CMD_VOLUME,
}


class PerformanceStats:
    def __init__(self):
        self.lock = threading.Lock()
        self.started_at = time.monotonic()
        self.samples = {}
        self.counters = {}

    def increment(self, name, amount=1):
        with self.lock:
            self.counters[name] = self.counters.get(name, 0) + amount

    def snapshot(self):
        with self.lock:
            uptime_seconds = max(time.monotonic() - self.started_at, 0.001)
            return {
                "uptime_seconds": round(uptime_seconds, 3),
                "samples": {},
                "counters": dict(self.counters),
                "rates_per_second": {
                    name: round(value / uptime_seconds, 3)
                    for name, value in self.counters.items()
                },
            }


def _normalize_capabilities(raw):
    caps = dict(DEFAULT_RADIUS_CAPABILITIES)
    if isinstance(raw, dict):
        caps.update(raw)
    caps["audio"] = bool(caps.get("audio") or caps.get("device_class") == "radius")
    caps["ftp"] = bool(caps.get("ftp") or caps.get("device_class") == "radius")
    if caps.get("device_class") == "radius":
        caps["hello"] = True
    return caps


def _capabilities_from_node(node_info):
    capabilities = node_info.get("capabilities")
    if not isinstance(capabilities, dict):
        capabilities = parse_node_capabilities(
            node_info.get("node_report", ""),
            node_info.get("short_name", ""),
            node_info.get("long_name", ""),
        )
    capabilities = dict(capabilities)
    if node_info.get("firmware_version") is not None:
        capabilities["firmware_version"] = node_info.get("firmware_version")
    for key in ("ip_mode", "static_ip", "gateway", "subnet"):
        if node_info.get(key) is not None:
            capabilities[key] = node_info.get(key)
    return _normalize_capabilities(capabilities)


def _is_radius_node(node_info, capabilities):
    if capabilities.get("device_class") == "radius":
        return True
    if capabilities.get("profile") == "pvrad1":
        return True
    name_blob = f"{node_info.get('short_name', '')} {node_info.get('long_name', '')}".lower()
    return "radius" in name_blob


def _load_devices():
    try:
        with open(state_file(), "r") as f:
            data = json.load(f)
        devices = data.get("devices", [])
        return devices if isinstance(devices, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_devices(devices):
    directory = os.path.dirname(state_file())
    if directory:
        os.makedirs(directory, exist_ok=True)
    payload = {"devices": []}
    for dev in devices:
        payload["devices"].append({
            "name": dev.get("name"),
            "ip": dev.get("ip"),
            "hardware_profile": dev.get("hardware_profile"),
            "hardware_label": dev.get("hardware_label"),
            "firmware_version": dev.get("firmware_version"),
            "capabilities": dev.get("capabilities"),
            "ip_mode": dev.get("ip_mode"),
            "static_ip": dev.get("static_ip"),
            "gateway": dev.get("gateway"),
            "subnet": dev.get("subnet"),
        })
    with open(state_file(), "w") as f:
        json.dump(payload, f, indent=2)


class RadiusState:
    """Device discovery, network config, and audio/FTP command routing."""

    def __init__(self, telemetry_listener=None):
        self.lock = threading.Lock()
        self.performance = PerformanceStats()
        self.running = True
        self.telemetry_listener = telemetry_listener
        self.devices = []
        self.artnet_source_ip = None

    def restore_devices(self):
        saved = _load_devices()
        if not saved:
            return set()
        known_ips = []
        seen = set()
        for device in saved:
            for ip in (device.get("ip"), device.get("static_ip")):
                if ip and ip not in seen:
                    known_ips.append(ip)
                    seen.add(ip)
        nodes = discover_artnet_nodes(
            known_ips=known_ips,
            timeout=2.0,
            interface=self._discovery_interface(),
            port=RADIUS_ARTNET_PORT,
        )
        discovered_ips = {n["ip"] for n in nodes}
        node_map = {n["ip"]: n for n in nodes}
        nodes_by_name = {}
        duplicate_names = set()
        for node in nodes:
            name = node.get("short_name")
            if not name:
                continue
            if name in nodes_by_name:
                duplicate_names.add(name)
            nodes_by_name[name] = node
        for name in duplicate_names:
            nodes_by_name.pop(name, None)
        refreshed = False
        for saved_dev in saved:
            ip = saved_dev["ip"]
            if any(d["ip"] == ip for d in self.devices):
                continue
            node = node_map.get(ip) or nodes_by_name.get(saved_dev.get("name"))
            if node:
                node["short_name"] = saved_dev.get("name") or node.get("short_name") or "Node"
                self.add_device_from_node(node, auto_save=False)
                if node.get("ip") != ip:
                    refreshed = True
            else:
                self.add_device_from_node({
                    "ip": ip,
                    "short_name": saved_dev.get("name", ip),
                    "long_name": "",
                    "num_ports": 0,
                    "universes": [],
                    "hardware_profile": saved_dev.get("hardware_profile", "v1"),
                    "hardware_label": saved_dev.get("hardware_label", "V1 Huzzah32"),
                    "firmware_version": saved_dev.get("firmware_version"),
                    "capabilities": saved_dev.get("capabilities"),
                    "ip_mode": saved_dev.get("ip_mode"),
                    "static_ip": saved_dev.get("static_ip"),
                    "gateway": saved_dev.get("gateway"),
                    "subnet": saved_dev.get("subnet"),
                }, auto_save=False)
        if refreshed:
            _save_devices(self.devices)
        return discovered_ips

    def _discovery_interface(self):
        try:
            from network_settings import get_artnet_interface
            return get_artnet_interface()
        except Exception:
            return None

    def discovery_targets(self):
        targets = []
        seen = set()
        with self.lock:
            for dev in self.devices:
                for ip in (dev.get("ip"), dev.get("static_ip")):
                    if ip and ip not in seen:
                        targets.append(ip)
                        seen.add(ip)
        return targets

    def set_artnet_source(self, source_ip=None):
        self.artnet_source_ip = source_ip or None

    def refresh_devices_from_nodes(self, nodes, auto_save=True):
        refreshed = []
        with self.lock:
            for node_info in nodes or []:
                idx = self._find_existing_device_index_unlocked(node_info)
                if idx is None:
                    continue
                dev = self.devices[idx]
                old_ip = dev.get("ip")
                new_ip = node_info.get("ip")
                ip_changed = bool(new_ip and new_ip != old_ip)
                if ip_changed:
                    dev["ip"] = new_ip
                updated = self._refresh_device_from_node_unlocked(dev, node_info)
                if updated or ip_changed:
                    refreshed.append({"device_index": idx, "ip": dev.get("ip"), "old_ip": old_ip})
            if refreshed and auto_save:
                _save_devices(self.devices)
        return refreshed

    def _find_existing_device_index_unlocked(self, node_info):
        ip = node_info.get("ip")
        short_name = node_info.get("short_name")
        for idx, dev in enumerate(self.devices):
            if ip and dev.get("ip") == ip:
                return idx
            if short_name and dev.get("name") == short_name:
                return idx
        return None

    def _refresh_device_from_node_unlocked(self, dev, node_info):
        updated = False
        name = node_info.get("short_name")
        if name and name != dev.get("name"):
            dev["name"] = name
            updated = True
        caps = _capabilities_from_node(node_info)
        if caps != dev.get("capabilities"):
            dev["capabilities"] = caps
            updated = True
        for key in ("hardware_profile", "hardware_label", "firmware_version"):
            value = node_info.get(key) or caps.get(key)
            if value and dev.get(key) != value:
                dev[key] = value
                updated = True
        dev["is_radius"] = _is_radius_node(node_info, caps)
        dev["ip_mode"] = caps.get("ip_mode", dev.get("ip_mode", "unknown"))
        dev["static_ip"] = caps.get("static_ip")
        dev["gateway"] = caps.get("gateway")
        dev["subnet"] = caps.get("subnet")
        return updated

    def add_device_from_node(self, node_info, auto_save=True):
        with self.lock:
            idx = self._find_existing_device_index_unlocked(node_info)
            if idx is not None:
                dev = self.devices[idx]
                ip_changed = dev.get("ip") != node_info.get("ip")
                if ip_changed and node_info.get("ip"):
                    dev["ip"] = node_info["ip"]
                updated = self._refresh_device_from_node_unlocked(dev, node_info)
                if (updated or ip_changed) and auto_save:
                    _save_devices(self.devices)
                return {"status": "updated" if (updated or ip_changed) else "exists", "device_index": idx}

            caps = _capabilities_from_node(node_info)
            dev = {
                "name": node_info.get("short_name") or "Radius",
                "ip": node_info.get("ip"),
                "connected": False,
                "is_radius": _is_radius_node(node_info, caps),
                "hardware_profile": node_info.get("hardware_profile") or caps.get("hardware_profile", "v1"),
                "hardware_label": node_info.get("hardware_label") or caps.get("hardware_label", "V1 Huzzah32"),
                "firmware_version": node_info.get("firmware_version") or caps.get("firmware_version"),
                "capabilities": caps,
                "ip_mode": caps.get("ip_mode", "unknown"),
                "static_ip": caps.get("static_ip"),
                "gateway": caps.get("gateway"),
                "subnet": caps.get("subnet"),
                "current_track": "",
                "playback_state": 0,
            }
            self.devices.append(dev)
            if auto_save:
                _save_devices(self.devices)
            return {"status": "added", "device_index": len(self.devices) - 1}

    def connect(self, di):
        with self.lock:
            if not (0 <= di < len(self.devices)):
                return {"ok": False, "error": "invalid device index"}
            self.devices[di]["connected"] = True
            return {"ok": True}

    def disconnect(self, di):
        with self.lock:
            if not (0 <= di < len(self.devices)):
                return {"ok": False, "error": "invalid device index"}
            self.devices[di]["connected"] = False
            return {"ok": True}

    def connect_all(self, only_ips=None):
        results = []
        with self.lock:
            for idx, dev in enumerate(self.devices):
                if only_ips is not None and dev.get("ip") not in only_ips:
                    continue
                dev["connected"] = True
                results.append({"device_index": idx, "ok": True})
        return results

    def disconnect_all(self):
        with self.lock:
            for dev in self.devices:
                dev["connected"] = False

    def remove_device(self, di):
        with self.lock:
            if 0 <= di < len(self.devices):
                self.devices.pop(di)
                _save_devices(self.devices)
                return True
        return False

    def rename_device(self, di, new_name):
        with self.lock:
            if not (0 <= di < len(self.devices)):
                return {"ok": False, "error": "invalid device index"}
            dev = self.devices[di]
            send_art_address(dev["ip"], new_name, source_ip=self.artnet_source_ip,
                             port=RADIUS_ARTNET_PORT)
            dev["name"] = new_name
            _save_devices(self.devices)
            return {"ok": True}

    def set_device_ip(self, di, static_ip, gateway, subnet):
        with self.lock:
            if not (0 <= di < len(self.devices)):
                return False
            dev = self.devices[di]
            send_ip_config(
                dev["ip"], 1, static_ip=static_ip, gateway=gateway, subnet=subnet,
                source_ip=self.artnet_source_ip, port=RADIUS_ARTNET_PORT,
            )
            dev["ip_mode"] = "static"
            dev["static_ip"] = static_ip
            dev["gateway"] = gateway
            dev["subnet"] = subnet
            _save_devices(self.devices)
            return True

    def revert_device_dhcp(self, di):
        with self.lock:
            if not (0 <= di < len(self.devices)):
                return False
            dev = self.devices[di]
            send_ip_config(dev["ip"], 0, source_ip=self.artnet_source_ip,
                           port=RADIUS_ARTNET_PORT)
            dev["ip_mode"] = "dhcp"
            dev["static_ip"] = None
            dev["gateway"] = None
            dev["subnet"] = None
            _save_devices(self.devices)
            return True

    def device_capability_status(self, di, capability):
        with self.lock:
            if not (0 <= di < len(self.devices)):
                return {"supported": False, "reason": "invalid device index"}
            caps = self.devices[di].get("capabilities") or {}
            supported = bool(caps.get(capability))
            return {"supported": supported, "reason": "" if supported else "not supported by device"}

    def _device_ip(self, di):
        with self.lock:
            if not (0 <= di < len(self.devices)):
                return None
            return self.devices[di]["ip"]

    def send_audio_command(self, di, cmd, filename="", volume=100, duration=0):
        ip = self._device_ip(di)
        if not ip:
            return False
        code = AUDIO_CMD_MAP.get(str(cmd).lower())
        if code is None:
            return False
        send_audio_cmd(
            ip, code, filename=filename, volume=volume, duration=duration,
            source_ip=self.artnet_source_ip,
        )
        self.performance.increment("audio_commands")
        return True

    def hello_device(self, di, volume=80):
        ip = self._device_ip(di)
        if not ip:
            return False
        send_audio_cmd(
            ip, AUDIO_CMD_TEST_TONE, volume=int(volume),
            source_ip=self.artnet_source_ip,
        )
        self.performance.increment("audio_commands")
        return True

    def fire_audio_cue(self, cue):
        """Fire per-device actions from a sender-side audio cue."""
        cmd_map = {
            "play": AUDIO_CMD_PLAY,
            "loop": AUDIO_CMD_LOOP,
            "stop": AUDIO_CMD_STOP,
        }
        results = {}
        with self.lock:
            snapshot = [
                (d["ip"], d.get("connected", False), d.get("is_radius", False))
                for d in self.devices
            ]
        actions = cue.get("actions") or {}
        for ip, connected, is_radius in snapshot:
            if not is_radius:
                continue
            action = actions.get(ip) or {}
            cmd_str = str(action.get("cmd", "none")).lower()
            if cmd_str == "none":
                continue
            if not connected:
                results[ip] = {"status": "skipped", "reason": "not connected"}
                continue
            cmd_code = cmd_map.get(cmd_str)
            if cmd_code is None:
                results[ip] = {"status": "skipped", "reason": f"unsupported cmd {cmd_str}"}
                continue
            filename = str(action.get("filename", "")).strip()
            if cmd_str in ("play", "loop") and not filename:
                results[ip] = {"status": "error", "reason": "filename required"}
                continue
            try:
                volume = action.get("volume")
                duration = action.get("duration") or 0
                delay_ms = action.get("delay_ms")
                kwargs = {"source_ip": self.artnet_source_ip}
                if volume is not None:
                    kwargs["volume"] = int(volume)
                else:
                    kwargs["volume"] = 80
                if cmd_str in ("play", "loop"):
                    kwargs["filename"] = filename
                    kwargs["duration"] = int(duration)
                if delay_ms:
                    kwargs["delay_ms"] = int(delay_ms)
                send_audio_cmd(ip, cmd_code, **kwargs)
                results[ip] = {"status": "sent", "reason": None}
                self.performance.increment("audio_commands")
            except Exception as exc:
                results[ip] = {"status": "error", "reason": str(exc)}
        return results

    def ftp_download(self, di, path):
        ip = self._device_ip(di)
        if not ip:
            raise ValueError("invalid device index")
        return ftp_download(ip, path, source_ip=self.artnet_source_ip)

    def ftp_list_dir(self, di, path="/"):
        ip = self._device_ip(di)
        if not ip:
            return []
        return ftp_list_dir(ip, path, source_ip=self.artnet_source_ip)

    def ftp_upload(self, di, path, data, progress_callback=None):
        ip = self._device_ip(di)
        if not ip:
            raise ValueError("invalid device index")
        ftp_upload(ip, path, data, source_ip=self.artnet_source_ip,
                   progress_callback=progress_callback)

    def ftp_rename(self, di, src, dst):
        ip = self._device_ip(di)
        if not ip:
            raise ValueError("invalid device index")
        ftp_rename(ip, src, dst, source_ip=self.artnet_source_ip)

    def ftp_delete(self, di, path, is_dir=False):
        ip = self._device_ip(di)
        if not ip:
            raise ValueError("invalid device index")
        ftp_delete(ip, path, is_dir=is_dir, source_ip=self.artnet_source_ip)

    def ftp_mkdir(self, di, path):
        ip = self._device_ip(di)
        if not ip:
            raise ValueError("invalid device index")
        ftp_mkdir(ip, path, source_ip=self.artnet_source_ip)

    def _merge_telemetry_unlocked(self, dev):
        listener = self.telemetry_listener
        if listener is None:
            return
        telemetry = listener.get(dev.get("ip"))
        if not telemetry:
            return
        dev["_has_telemetry"] = True
        if "current_track" in telemetry:
            dev["current_track"] = telemetry.get("current_track") or ""
        if "playback_state" in telemetry:
            dev["playback_state"] = telemetry.get("playback_state", 0)
        if "fps" in telemetry:
            dev["fps"] = telemetry.get("fps")
        if "pkt_rate" in telemetry:
            dev["pkt_rate"] = telemetry.get("pkt_rate")

    def get_json(self):
        with self.lock:
            devices = []
            for dev in self.devices:
                item = {
                    "name": dev.get("name"),
                    "ip": dev.get("ip"),
                    "connected": bool(dev.get("connected")),
                    "is_radius": bool(dev.get("is_radius")),
                    "is_audio": bool(dev.get("is_radius")),
                    "hardware_profile": dev.get("hardware_profile"),
                    "hardware_label": dev.get("hardware_label"),
                    "firmware_version": dev.get("firmware_version"),
                    "capabilities": dev.get("capabilities") or {},
                    "ip_mode": dev.get("ip_mode"),
                    "static_ip": dev.get("static_ip"),
                    "gateway": dev.get("gateway"),
                    "subnet": dev.get("subnet"),
                    "current_track": dev.get("current_track", ""),
                    "playback_state": dev.get("playback_state", 0),
                }
                self._merge_telemetry_unlocked(item)
                if item.pop("_has_telemetry", False):
                    ps = item.get("playback_state", 0)
                    item["audio_status"] = "playing" if ps == 1 else ("paused" if ps == 2 else "stopped")
                    item["now_playing"] = item.get("current_track", "") if ps in (1, 2) else ""
                devices.append(item)
            return {
                "product": "radius",
                "devices": devices,
            }

    def get_performance_json(self):
        return self.performance.snapshot()

    def shutdown(self):
        self.running = False
