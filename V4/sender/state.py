"""
state.py — Output type tables, controller state, animation tick, persistence.
"""

import copy
import json
import os
import sys
import threading
import time

from effects import (
    EFFECTS, fx_none, compute_anim_factor,
    apply_serpentine, apply_grid_rotation,
    normalize_brightness, scale_pixels,
)
from artnet import (
    ArtNetSender,
    parse_node_capabilities,
    parse_node_outputs,
    send_output_config,
    send_receive_config,
    send_art_address,
    send_ip_config,
    send_show_info,
    ipv4_octets,
)
from paths import state_file


# ======================================================================
#  OUTPUT TYPE TABLE — single source of truth
# ======================================================================

OUTPUT_TYPES = {
    "none":        {"pixels": 0,  "layout": "none"},
    "short_strip": {"pixels": 30, "layout": "linear"},
    "long_strip":  {"pixels": 72, "layout": "linear"},
    "grid":        {"pixels": 64, "layout": "grid", "grid_size": [8, 8]},
    "small_grid":  {"pixels": 32, "layout": "grid", "grid_size": [8, 4]},
    "extra_long_strip": {"pixels": 122, "layout": "linear"},
}

LOOK_OUTPUT_TYPES = [
    "none",
    "short_strip",
    "long_strip",
    "grid",
    "small_grid",
    "extra_long_strip",
]
DEFAULT_DEVICE_CAPABILITIES = {
    "profile": "generic",
    "hardware_profile": "unknown",
    "hardware_label": "Unknown hardware",
    "firmware_version": None,
    "ip_mode": "unknown",
    "static_ip": None,
    "gateway": None,
    "subnet": None,
    "known": False,
    "rename": False,
    "hello": False,
    "ip_config": False,
    "output_config": False,
    "receive_config": False,
    "receive_mode": "split",
    "base_universe": 0,
    "battery": False,
    "show_info": False,
}
CONTROL_CAPABILITY_LABELS = {
    "rename": "remote rename",
    "hello": "remote identify flash",
    "ip_config": "remote IP configuration",
    "output_config": "remote output configuration",
    "receive_config": "remote receive mode configuration",
    "show_info": "remote show info",
}
RECEIVE_MODES = ("split", "combined")
COMBINED_RECEIVE_MAX_PIXELS = 170
DEVICE_SHOW_INFO_MAX_LENGTH = 64
_DEVICE_FILTER_UNCHANGED = object()
TRANSPORT_FAIL_STREAK_LIMIT = 90  # ~3 s at 30 FPS before surfacing a send warning

# ======================================================================
#  DEFAULTS
# ======================================================================

DEFAULT_FPS = 30
DEFAULT_EFFECT = "pulse"
DEFAULT_SPEED = 1.0
DEFAULT_BRIGHTNESS = 0.4
DEFAULT_PLAYBACK = "loop"
LOW_LATENCY_SLEEP_SLICE = 0.004
LOW_LATENCY_SPIN_SECONDS = 0.001

DEFAULT_GRID_START_COLOR = [255, 0, 255]
DEFAULT_GRID_END_COLOR = [0, 255, 255]
DEFAULT_STRIP_START_COLOR = [255, 0, 0]
DEFAULT_STRIP_END_COLOR = [0, 0, 255]

EFFECT_NAMES = list(EFFECTS.keys())
PLAYBACK_MODES = ["loop", "boomerang", "once"]
GRID_ORDERS = ["progressive", "serpentine"]
GRID_ROTATIONS = [0, 90, 180, 270]

# V3.1: default 2-output template (A0 + A1)
DEFAULT_TEMPLATE = [
    {"name": "A0", "type": "short_strip"},
    {"name": "A1", "type": "long_strip"},
]


class PerformanceStats:
    """Small rolling timing summary for live sender diagnostics."""

    def __init__(self):
        self.lock = threading.Lock()
        self.started_at = time.monotonic()
        self.samples = {}
        self.counters = {}
        self._last_snapshot = None

    def observe(self, name, value):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return
        with self.lock:
            self._observe_unlocked(name, numeric)

    def observe_many(self, observations):
        values = []
        for name, value in observations:
            try:
                values.append((name, float(value)))
            except (TypeError, ValueError):
                continue
        if not values:
            return
        with self.lock:
            for name, numeric in values:
                self._observe_unlocked(name, numeric)

    def _observe_unlocked(self, name, numeric):
        sample = self.samples.setdefault(name, {
            "count": 0,
            "last": 0.0,
            "avg": 0.0,
            "max": 0.0,
        })
        sample["count"] += 1
        count = sample["count"]
        sample["last"] = numeric
        sample["avg"] += (numeric - sample["avg"]) / count
        if numeric > sample["max"]:
            sample["max"] = numeric

    def increment(self, name, amount=1):
        with self.lock:
            self.counters[name] = self.counters.get(name, 0) + amount

    def snapshot(self):
        acquired = self.lock.acquire(timeout=0.01)
        if not acquired:
            if self._last_snapshot is not None:
                stale = copy.deepcopy(self._last_snapshot)
                stale["stale"] = True
                return stale
            uptime_seconds = max(time.monotonic() - self.started_at, 0.001)
            return {
                "uptime_seconds": round(uptime_seconds, 3),
                "samples": {},
                "counters": {},
                "rates_per_second": {},
                "stale": True,
            }
        try:
            uptime_seconds = max(time.monotonic() - self.started_at, 0.001)
            snapshot = {
                "uptime_seconds": round(uptime_seconds, 3),
                "samples": {
                    name: {
                        "count": sample["count"],
                        "last": round(sample["last"], 3),
                        "avg": round(sample["avg"], 3),
                        "max": round(sample["max"], 3),
                    }
                    for name, sample in self.samples.items()
                },
                "counters": dict(self.counters),
                "rates_per_second": {
                    name: round(value / uptime_seconds, 3)
                    for name, value in self.counters.items()
                },
            }
            self._last_snapshot = copy.deepcopy(snapshot)
            return snapshot
        finally:
            self.lock.release()


def set_current_thread_qos():
    """Raise the current macOS thread's scheduler class for frame timing."""
    if sys.platform != "darwin":
        return False
    if os.environ.get("PRIMUSV3_DISABLE_THREAD_QOS") == "1":
        return False
    try:
        import ctypes
        libsystem = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        set_qos = libsystem.pthread_set_qos_class_self_np
        set_qos.argtypes = [ctypes.c_int, ctypes.c_int]
        set_qos.restype = ctypes.c_int
        qos_class_user_interactive = 0x21
        return set_qos(qos_class_user_interactive, 0) == 0
    except Exception:
        return False


def _sleep_until_frame(deadline):
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        if remaining > LOW_LATENCY_SPIN_SECONDS:
            sleep_for = min(
                LOW_LATENCY_SLEEP_SLICE,
                max(remaining - LOW_LATENCY_SPIN_SECONDS, 0.0),
            )
            if sleep_for > 0:
                time.sleep(sleep_for)
                continue
        while time.monotonic() < deadline:
            pass
        return

# ======================================================================
#  PERSISTENCE
# ======================================================================

def _state_file():
    return state_file()


def _save_output_types(types):
    try:
        with open(_state_file(), "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    data["output_types"] = types
    try:
        with open(_state_file(), "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def _load_output_types():
    try:
        with open(_state_file(), "r") as f:
            data = json.load(f)
        types = data.get("output_types", [])
        if types and all(t in OUTPUT_TYPES for t in types):
            return types
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    return None


def _normalize_device_capabilities(capabilities=None):
    out = dict(DEFAULT_DEVICE_CAPABILITIES)
    if isinstance(capabilities, dict):
        for key in out:
            if key in capabilities:
                out[key] = capabilities[key]
    out["profile"] = str(out["profile"] or "generic")
    out["hardware_profile"] = str(out["hardware_profile"] or "unknown")
    out["hardware_label"] = str(out["hardware_label"] or "Unknown hardware")
    out["ip_mode"] = str(out.get("ip_mode") or "unknown")
    if out["ip_mode"] not in ("dhcp", "static", "unknown"):
        out["ip_mode"] = "unknown"
    for key in ("static_ip", "gateway", "subnet"):
        out[key] = out.get(key) or None
    out["known"] = bool(out["known"])
    out["rename"] = bool(out["rename"])
    out["hello"] = bool(out["hello"])
    out["ip_config"] = bool(out["ip_config"])
    out["output_config"] = bool(out["output_config"])
    out["receive_config"] = bool(out.get("receive_config"))
    mode = str(out.get("receive_mode") or "split").lower()
    out["receive_mode"] = mode if mode in RECEIVE_MODES else "split"
    base = out.get("base_universe")
    out["base_universe"] = int(base) if base is not None else 0
    out["battery"] = bool(out.get("battery"))
    out["show_info"] = bool(out.get("show_info"))
    return out


def _normalize_show_info_value(value):
    return str(value or "").strip()[:DEVICE_SHOW_INFO_MAX_LENGTH]


def _show_info_from_saved(saved):
    if not isinstance(saved, dict):
        return "", ""
    return (
        _normalize_show_info_value(saved.get("character_name")),
        _normalize_show_info_value(saved.get("performer_name")),
    )


def _apply_saved_show_info(dev, saved):
    character_name, performer_name = _show_info_from_saved(saved)
    dev["character_name"] = character_name
    dev["performer_name"] = performer_name


def _read_state_data():
    try:
        with open(_state_file(), "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state_data(data):
    try:
        with open(_state_file(), "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def _device_show_info_map_from_data(data):
    info_map = data.get("device_show_info")
    return dict(info_map) if isinstance(info_map, dict) else {}


def _show_info_entry(device_name, character_name, performer_name):
    return {
        "device_name": str(device_name or "")[:17],
        "character_name": _normalize_show_info_value(character_name),
        "performer_name": _normalize_show_info_value(performer_name),
    }


def _lookup_device_show_info(ip=None, device_name=None):
    info_map = _device_show_info_map_from_data(_read_state_data())
    entry = info_map.get(ip) if ip else None
    if isinstance(entry, dict):
        return _show_info_from_saved(entry)
    if device_name:
        for candidate in info_map.values():
            if isinstance(candidate, dict) and candidate.get("device_name") == device_name:
                return _show_info_from_saved(candidate)
    return "", ""


def _persist_device_show_info(ip, device_name, character_name, performer_name):
    if not ip:
        return
    data = _read_state_data()
    info_map = _device_show_info_map_from_data(data)
    info_map[ip] = _show_info_entry(device_name, character_name, performer_name)
    data["device_show_info"] = info_map
    _write_state_data(data)


def _migrate_device_show_info_key(old_ip, new_ip, device_name=None):
    if not old_ip or not new_ip or old_ip == new_ip:
        return
    data = _read_state_data()
    info_map = _device_show_info_map_from_data(data)
    entry = info_map.pop(old_ip, None)
    if not isinstance(entry, dict):
        return
    if device_name:
        entry["device_name"] = str(device_name)[:17]
    info_map[new_ip] = entry
    data["device_show_info"] = info_map
    _write_state_data(data)


def _show_info_from_node(node_info):
    if not isinstance(node_info, dict):
        return "", ""
    return (
        _normalize_show_info_value(node_info.get("character_name")),
        _normalize_show_info_value(node_info.get("performer_name")),
    )


def _merge_show_info_fields(character_name, performer_name, ip=None, device_name=None):
    lookup_char, lookup_perf = _lookup_device_show_info(ip, device_name)
    if not character_name and lookup_char:
        character_name = lookup_char
    if not performer_name and lookup_perf:
        performer_name = lookup_perf
    return character_name, performer_name


def _apply_persisted_show_info(dev, node_info=None):
    ip = dev.get("ip") or (node_info or {}).get("ip")
    name = dev.get("name") or (node_info or {}).get("short_name")
    character_name, performer_name = _lookup_device_show_info(ip, name)
    if character_name:
        dev["character_name"] = character_name
    if performer_name:
        dev["performer_name"] = performer_name


def _save_devices(devices):
    """Persist device list so known V3.6 profile hints survive restarts."""
    try:
        data = _read_state_data()
    except (OSError, json.JSONDecodeError):
        data = {}
    info_map = _device_show_info_map_from_data(data)
    saved_devices = []
    for d in devices:
        saved_outputs = []
        for output in d.get("outputs", []):
            saved_outputs.append({
                "name": output.get("name", "A0"),
                "type": output.get("type", "long_strip"),
                "universe": output.get("universe", 0),
                "grid_order": output.get("grid_order", "progressive"),
                "grid_rotation": output.get("grid_rotation", 0),
            })
        saved_devices.append({
            "ip": d["ip"],
            "name": d["name"],
            "hardware_profile": d.get("hardware_profile", "unknown"),
            "hardware_label": d.get("hardware_label", "Unknown hardware"),
            "firmware_version": d.get("firmware_version"),
            "capabilities": _normalize_device_capabilities(d.get("capabilities")),
            "ip_mode": d.get("ip_mode", "unknown"),
            "static_ip": d.get("static_ip"),
            "gateway": d.get("gateway"),
            "subnet": d.get("subnet"),
            "receive_mode": d.get("receive_mode", "split"),
            "base_universe": d.get("base_universe", 0),
            "character_name": _normalize_show_info_value(d.get("character_name")),
            "performer_name": _normalize_show_info_value(d.get("performer_name")),
            "outputs": saved_outputs,
        })
        ip = d.get("ip")
        if ip:
            info_map[ip] = _show_info_entry(
                d.get("name"),
                d.get("character_name"),
                d.get("performer_name"),
            )
    data["devices"] = saved_devices
    data["device_show_info"] = info_map
    _write_state_data(data)


def _load_devices():
    try:
        with open(_state_file(), "r") as f:
            data = json.load(f)
        return data.get("devices", [])
    except (OSError, json.JSONDecodeError):
        return []


def _save_device_groups(groups):
    try:
        with open(_state_file(), "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    data["device_groups"] = groups
    try:
        with open(_state_file(), "w") as f:
            json.dump(data, f)
    except OSError:
        pass


def _load_device_groups():
    try:
        with open(_state_file(), "r") as f:
            data = json.load(f)
        return data.get("device_groups", [])
    except (OSError, json.JSONDecodeError):
        return []


# ======================================================================
#  HELPERS
# ======================================================================

def resolve_output(cfg):
    """Derive pixel count, grid, layout from an output config entry."""
    typedef = OUTPUT_TYPES.get(cfg["type"])
    if typedef is None:
        raise ValueError(f"Unknown output type: {cfg['type']!r}")
    count = typedef["pixels"]
    grid = typedef.get("grid_size") if typedef["layout"] == "grid" else None
    return {
        "name": cfg["name"],
        "type": cfg["type"],
        "count": count,
        "grid": grid,
        "layout": typedef["layout"],
    }


def _apply_type_to_look_output(lo, new_type):
    typedef = OUTPUT_TYPES.get(new_type)
    if typedef is None:
        return
    lo["type"] = new_type
    lo["count"] = typedef["pixels"]
    lo["layout"] = typedef["layout"]
    lo["grid"] = typedef.get("grid_size") if typedef["layout"] == "grid" else None
    lo["led_state"] = []
    lo["pixels"] = []
    is_grid = typedef["layout"] == "grid"
    lo["start_color"] = list(DEFAULT_GRID_START_COLOR if is_grid else DEFAULT_STRIP_START_COLOR)
    lo["end_color"] = list(DEFAULT_GRID_END_COLOR if is_grid else DEFAULT_STRIP_END_COLOR)
    lo.setdefault("brightness", DEFAULT_BRIGHTNESS)
    if new_type == "none":
        lo["effect"] = "none"


def _make_look_output(cfg):
    """Create a Look output dict from a resolved output config."""
    resolved = resolve_output(cfg)
    is_grid = resolved["layout"] == "grid"
    return {
        **resolved,
        "effect": DEFAULT_EFFECT,
        "start_color": list(DEFAULT_GRID_START_COLOR if is_grid else DEFAULT_STRIP_START_COLOR),
        "end_color": list(DEFAULT_GRID_END_COLOR if is_grid else DEFAULT_STRIP_END_COLOR),
        "speed": DEFAULT_SPEED,
        "brightness": DEFAULT_BRIGHTNESS,
        "playback": DEFAULT_PLAYBACK,
        "angle": 0,
        "highlight_width": 5,
        "chase_origin": "start",
        "led_state": [],
        "pixels": [],
    }


def _node_has_discovery_metadata(node_info):
    return bool(
        node_info.get("node_report")
        or node_info.get("long_name")
        or isinstance(node_info.get("capabilities"), dict)
        or node_info.get("hardware_profile")
        or node_info.get("firmware_version")
        or node_info.get("outputs")
    )


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
    return _normalize_device_capabilities(capabilities)


def _apply_network_capabilities_to_device(dev, capabilities, fallback_ip=None):
    dev["ip_mode"] = capabilities.get("ip_mode", "unknown")
    static_ip = capabilities.get("static_ip")
    if dev["ip_mode"] == "static" and not static_ip:
        static_ip = fallback_ip
    dev["static_ip"] = static_ip
    dev["gateway"] = capabilities.get("gateway")
    dev["subnet"] = capabilities.get("subnet")


def _output_configs_from_node(node_info):
    explicit_outputs = node_info.get("outputs")
    if isinstance(explicit_outputs, list):
        output_cfgs = []
        for idx, output in enumerate(explicit_outputs):
            if not isinstance(output, dict):
                continue
            output_type = output.get("type", "long_strip")
            if output_type not in OUTPUT_TYPES:
                continue
            cfg = {
                "name": output.get("name", f"A{idx}"),
                "type": output_type,
            }
            if "universe" in output:
                cfg["universe"] = output.get("universe", idx)
            if "grid_order" in output:
                cfg["grid_order"] = output.get("grid_order")
            if "grid_rotation" in output:
                cfg["grid_rotation"] = output.get("grid_rotation")
            output_cfgs.append(cfg)
        if output_cfgs:
            return output_cfgs

    return parse_node_outputs(
        node_info.get("long_name", ""),
        node_info.get("universes", []),
        OUTPUT_TYPES,
        node_report=node_info.get("node_report", ""),
        type_keys=LOOK_OUTPUT_TYPES)


def _receive_fields_from_node(node_info, capabilities, fallback_base=0):
    mode = node_info.get("receive_mode")
    base = node_info.get("base_universe")
    if mode is None:
        mode = capabilities.get("receive_mode")
    if base is None:
        base = capabilities.get("base_universe")
    if mode not in RECEIVE_MODES:
        mode = "split"
    if base is None:
        base = fallback_base
    return mode, int(base)


def _combined_pixel_total(outputs):
    return sum(int(o.get("count") or 0) for o in outputs)


def _validate_receive_mode_for_device(receive_mode, outputs):
    if receive_mode != "combined":
        return True, None
    total = _combined_pixel_total(outputs)
    if total > COMBINED_RECEIVE_MAX_PIXELS:
        return False, (
            f"combined mode requires at most {COMBINED_RECEIVE_MAX_PIXELS} pixels "
            f"({total} configured)"
        )
    return True, None


def _apply_output_universes(outputs, receive_mode, base_u):
    active_idx = 0
    for output in outputs:
        if output.get("type") == "none" or int(output.get("count") or 0) <= 0:
            continue
        if receive_mode == "combined":
            output["universe"] = base_u
        else:
            output["universe"] = base_u + active_idx
            active_idx += 1


def _device_blackout_info(dev):
    outputs = dev.get("outputs", [])
    receive_mode = dev.get("receive_mode", "split")
    if receive_mode == "combined":
        total = _combined_pixel_total(outputs)
        if total <= 0:
            return []
        return [(dev.get("base_universe", 0), total)]
    info = []
    for output in outputs:
        count = int(output.get("count") or 0)
        if count <= 0:
            continue
        info.append((output["universe"], count))
    return info


def _queue_device_frame_sends(send_queue, di, dev, frame_buffers):
    """Append Art-Net sends for one device frame.

    frame_buffers maps output index -> rgb bytes for outputs with pixel data.
    """
    outputs = dev.get("outputs", [])
    receive_mode = dev.get("receive_mode", "split")
    sender = dev["sender"]
    if receive_mode == "combined":
        combined = bytearray()
        for oi, output in enumerate(outputs):
            count = int(output.get("count") or 0)
            if count <= 0:
                continue
            data = frame_buffers.get(oi)
            if data is None:
                combined.extend(bytes(count * 3))
            else:
                expected = count * 3
                if len(data) >= expected:
                    combined.extend(data[:expected])
                else:
                    combined.extend(data)
                    combined.extend(bytes(expected - len(data)))
        if combined:
            send_queue.append(
                (di, sender, dev.get("base_universe", 0), bytes(combined)))
        return

    for oi, data in frame_buffers.items():
        if oi >= len(outputs):
            continue
        send_queue.append((di, sender, outputs[oi]["universe"], data))


def _config_apply_result(applied_to_device):
    if applied_to_device:
        return {
            "ok": True,
            "applied_to_device": True,
            "requires_restart": False,
            "message": "Applied immediately — no restart required",
        }
    return {
        "ok": True,
        "applied_to_device": False,
        "requires_restart": False,
        "message": "Saved locally — connect device to apply",
    }


def _device_flash_entries(dev, rgb_triplet):
    """Build (universe, bytes) entries for a solid-color flash."""
    outputs = dev.get("outputs", [])
    receive_mode = dev.get("receive_mode", "split")
    if receive_mode == "combined":
        combined = bytearray()
        for output in outputs:
            count = int(output.get("count") or 0)
            if count <= 0:
                continue
            combined.extend(rgb_triplet * count)
        if not combined:
            return []
        return [(dev.get("base_universe", 0), bytes(combined))]

    entries = []
    for output in outputs:
        count = int(output.get("count") or 0)
        if count <= 0:
            continue
        entries.append((output["universe"], rgb_triplet * count))
    return entries


# ======================================================================
#  CONTROLLER STATE
# ======================================================================

class ControllerState:
    """Holds all settings, computes animations, sends Art-Net frames."""

    # Playback sources
    SOURCE_DESIGNER = "designer"
    SOURCE_MIXER = "mixer"
    SOURCE_CONTROLLER = "controller"
    SOURCE_IDLE = "idle"
    PLAYBACK_SOURCES = (
        SOURCE_DESIGNER,
        SOURCE_MIXER,
        SOURCE_CONTROLLER,
        SOURCE_IDLE,
    )
    API_PLAYBACK_SOURCES = (
        SOURCE_DESIGNER,
        SOURCE_IDLE,
        SOURCE_CONTROLLER,
    )

    def __init__(self, fps_listener):
        self.lock = threading.Lock()
        self.render_event = threading.Event()
        self.performance = PerformanceStats()
        self.running = True
        self.fps = DEFAULT_FPS
        self.fps_listener = fps_listener
        self.start_time = time.monotonic()
        self.last_tick = self.start_time
        self.devices = []
        self.playback_source = self.SOURCE_IDLE
        self.artnet_source_ip = None

        # Active Look — the animation being sent to all connected devices
        saved_types = _load_output_types()
        look_outputs = []
        for i, o_cfg in enumerate(DEFAULT_TEMPLATE):
            cfg = dict(o_cfg)
            if saved_types and i < len(saved_types):
                cfg["type"] = saved_types[i]
            look_outputs.append(_make_look_output(cfg))
        self.active_look = {"name": "Look 1", "outputs": look_outputs}

        # Device groups
        self.device_groups = _load_device_groups()

        # Mixer / controller override pixel buffers (set externally)
        self._override_pixels = None  # list of pixel lists per output, or None
        self._override_frames_by_device = None
        self._override_default_frames = None
        self._controller_device_ips = None  # set of IP strings or None (all)
        # Mixer live preview state
        self._mixer_preview_look = None
        self._mixer_preview_play_time = 0.0   # current wrapped timeline time
        self._mixer_preview_transport_time = 0.0  # unwrapped timeline time
        self._mixer_preview_start_mono = 0.0  # monotonic time when play started
        self._mixer_preview_playing = False    # whether clock is advancing
        self._mixer_preview_device_filter = None
        self._mixer_update_last_seq = 0       # sequence number for update ordering

    def restore_devices(self):
        """Restore saved devices on startup (call after FPS listener is ready)."""
        saved = _load_devices()
        if not saved:
            return
        from artnet import discover_artnet_nodes
        known_ips = []
        seen_ips = set()
        for device in saved:
            for ip in (device.get("ip"), device.get("static_ip")):
                if ip and ip not in seen_ips:
                    known_ips.append(ip)
                    seen_ips.add(ip)
        nodes = discover_artnet_nodes(known_ips=known_ips, timeout=2.0)
        node_map = {n["ip"]: n for n in nodes}
        nodes_by_name = {}
        duplicate_node_names = set()
        for node in nodes:
            name = node.get("short_name")
            if not name:
                continue
            if name in nodes_by_name:
                duplicate_node_names.add(name)
            nodes_by_name[name] = node
        for name in duplicate_node_names:
            nodes_by_name.pop(name, None)
        refreshed = False
        for sd in saved:
            ip = sd["ip"]
            if any(d["ip"] == ip for d in self.devices):
                continue
            node = node_map.get(ip) or nodes_by_name.get(sd.get("name"))
            if node:
                node["short_name"] = node.get("short_name") or sd.get("name") or "Node"
                result = self.add_device_from_node(node, auto_save=False)
                _apply_saved_show_info(self.devices[result["device_index"]], sd)
                _apply_persisted_show_info(self.devices[result["device_index"]], node)
                if node.get("ip") != ip:
                    refreshed = True
            else:
                # Add offline device with saved name
                result = self.add_device_from_node({
                    "ip": ip,
                    "short_name": sd.get("name", ip),
                    "long_name": "",
                    "num_ports": 0,
                    "universes": [0, 1],
                    "hardware_profile": sd.get("hardware_profile", "unknown"),
                    "hardware_label": sd.get("hardware_label", "Unknown hardware"),
                    "firmware_version": sd.get("firmware_version"),
                    "capabilities": sd.get("capabilities"),
                    "ip_mode": sd.get("ip_mode"),
                    "static_ip": sd.get("static_ip"),
                    "gateway": sd.get("gateway"),
                    "subnet": sd.get("subnet"),
                    "receive_mode": sd.get("receive_mode", "split"),
                    "base_universe": sd.get("base_universe", 0),
                    "character_name": sd.get("character_name", ""),
                    "performer_name": sd.get("performer_name", ""),
                    "outputs": sd.get("outputs"),
                }, auto_save=False)
                _apply_saved_show_info(self.devices[result["device_index"]], sd)
        if refreshed:
            _save_devices(self.devices)

    def discovery_targets(self):
        """Return known receiver IPs worth probing during discovery."""
        targets = []
        seen = set()
        with self.lock:
            for dev in self.devices:
                for ip in (dev.get("ip"), dev.get("static_ip")):
                    if ip and ip not in seen:
                        targets.append(ip)
                        seen.add(ip)
        for ip in _device_show_info_map_from_data(_read_state_data()):
            if ip and ip not in seen:
                targets.append(ip)
                seen.add(ip)
        return targets

    def set_artnet_source(self, source_ip=None):
        """Set the local IPv4 address used for outgoing Art-Net sockets."""
        source_ip = source_ip or None
        with self.lock:
            if self.artnet_source_ip == source_ip:
                return
            self.artnet_source_ip = source_ip
            for dev in self.devices:
                if hasattr(dev["sender"], "set_source_ip"):
                    dev["sender"].set_source_ip(source_ip)

    def refresh_devices_from_nodes(self, nodes, auto_save=True):
        """Refresh matching existing devices from discovery without adding new ones."""
        refreshed = []
        groups_changed = False
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
                    dev["sender"].ip = new_ip
                    groups_changed = self._replace_device_ip_references_unlocked(old_ip, new_ip) or groups_changed
                updated = self._refresh_device_from_node_unlocked(dev, node_info)
                if updated or ip_changed:
                    refreshed.append({
                        "device_index": idx,
                        "name": dev.get("name"),
                        "old_ip": old_ip,
                        "ip": dev.get("ip"),
                    })
            if refreshed and auto_save:
                _save_devices(self.devices)
            if groups_changed and auto_save:
                _save_device_groups(self.device_groups)
        return refreshed

    def _playback_target_info_unlocked(self):
        total = len(self.devices)
        connected_total = sum(1 for dev in self.devices if dev["connected"])

        if self.playback_source == self.SOURCE_MIXER:
            if self._mixer_preview_device_filter is None:
                scope = "all"
                selected = total
                connected = connected_total
            else:
                indices = [
                    idx for idx in self._mixer_preview_device_filter
                    if 0 <= idx < total
                ]
                scope = "selected"
                selected = len(indices)
                connected = sum(1 for idx in indices if self.devices[idx]["connected"])
        elif self.playback_source == self.SOURCE_CONTROLLER:
            if self._controller_device_ips is None:
                scope = "all"
                selected = total
                connected = connected_total
            else:
                scope = "selected"
                selected = len(self._controller_device_ips)
                connected = sum(
                    1 for dev in self.devices
                    if dev["connected"] and dev["ip"] in self._controller_device_ips
                )
        elif self.playback_source == self.SOURCE_DESIGNER:
            scope = "all"
            selected = total
            connected = connected_total
        else:
            scope = "none"
            selected = 0
            connected = 0

        if scope == "none":
            label = "No output"
        elif selected <= 0:
            label = "No devices"
        elif scope == "all":
            label = "All devices"
        elif selected == 1:
            label = "1 selected device"
        else:
            label = f"{selected} selected devices"

        if scope != "none" and selected > 0 and connected != selected:
            label += f" ({connected} connected)"

        return {
            "scope": scope,
            "selected_count": selected,
            "connected_count": connected,
            "label": label,
        }

    def _playback_status_unlocked(self):
        source = self.playback_source
        target = self._playback_target_info_unlocked()

        if source == self.SOURCE_DESIGNER:
            label = "Designer"
            activity = "Live"
            detail = f"Designer output is live on {target['label'].lower()}."
        elif source == self.SOURCE_MIXER:
            label = "Mixer Preview"
            activity = "Running" if self._mixer_preview_playing else "Paused"
            detail = f"Mixer preview is {activity.lower()} on {target['label'].lower()}."
        elif source == self.SOURCE_CONTROLLER:
            label = "Controller"
            activity = "Active"
            detail = f"Controller playback owns output on {target['label'].lower()}."
        else:
            label = "Idle"
            activity = "No output"
            detail = "No live source currently owns output."

        return {
            "source": source,
            "label": label,
            "activity": activity,
            "target_label": target["label"],
            "summary": activity if source == self.SOURCE_IDLE else f"{activity} · {target['label']}",
            "detail": detail,
            "scope": target["scope"],
            "selected_count": target["selected_count"],
            "connected_count": target["connected_count"],
            "using_override": self._override_pixels is not None,
        }

    def _normalize_mixer_device_filter(self, device_filter):
        if device_filter is None:
            return None
        indices = []
        seen = set()
        for raw_idx in device_filter:
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                continue
            if idx in seen or idx < 0 or idx >= len(self.devices):
                continue
            seen.add(idx)
            indices.append(idx)
        return indices

    def build_black_frame(self):
        """Return an all-black frame matching the active look output sizes."""
        with self.lock:
            frame = []
            for lo in self.active_look["outputs"]:
                if lo["type"] == "none" or lo["count"] == 0:
                    frame.append([])
                else:
                    frame.append([(0, 0, 0)] * lo["count"])
            return frame

    # ------------------------------------------------------------------
    #  JSON serialization
    # ------------------------------------------------------------------

    def get_json(self):
        lock_start = time.perf_counter()
        with self.lock:
            lock_acquired = time.perf_counter()
            look = {
                "name": self.active_look["name"],
                "outputs": [],
            }
            for lo in self.active_look["outputs"]:
                look["outputs"].append({
                    "name": lo["name"],
                    "type": lo["type"],
                    "count": lo["count"],
                    "grid": lo["grid"],
                    "layout": lo["layout"],
                    "effect": lo["effect"],
                    "start_color": lo["start_color"],
                    "end_color": lo["end_color"],
                    "speed": lo["speed"],
                    "brightness": normalize_brightness(
                        lo.get("brightness", DEFAULT_BRIGHTNESS)
                    ),
                    "playback": lo["playback"],
                    "angle": lo["angle"],
                    "highlight_width": lo["highlight_width"],
                    "chase_origin": lo["chase_origin"],
                    "pixels": lo["pixels"],
                })
            out = {
                "fps": self.fps,
                "output_types": OUTPUT_TYPES,
                "look_output_types": LOOK_OUTPUT_TYPES,
                "look": look,
                "devices": [],
                "device_groups": self.device_groups,
                "playback_source": self.playback_source,
                "playback": self._playback_status_unlocked(),
            }
            for dev in self.devices:
                rx = None
                telemetry_age_seconds = None
                receiver_online = False
                if self.fps_listener:
                    rx, telemetry_age_seconds, receiver_online = (
                        self.fps_listener.get_telemetry_status(dev["ip"]))
                d = {
                    "name": dev["name"],
                    "character_name": _normalize_show_info_value(dev.get("character_name")),
                    "performer_name": _normalize_show_info_value(dev.get("performer_name")),
                    "ip": dev["ip"],
                    "base_universe": dev["base_universe"],
                    "receive_mode": dev.get("receive_mode", "split"),
                    "hardware_profile": dev.get("hardware_profile", "unknown"),
                    "hardware_label": dev.get("hardware_label", "Unknown hardware"),
                    "firmware_version": dev.get("firmware_version"),
                    "live_firmware_version": None,
                    "battery_mv": None,
                    "battery_pct": None,
                    "battery_power_mode": None,
                    "battery_warning": None,
                    "ip_mode": dev.get("ip_mode", "unknown"),
                    "static_ip": dev.get("static_ip"),
                    "gateway": dev.get("gateway"),
                    "subnet": dev.get("subnet"),
                    "ip_config_pending": dev.get("ip_config_pending"),
                    "connected": dev["connected"],
                    "transport_error": dev.get("transport_error"),
                    "receiver_fps": rx.get("fps") if rx else None,
                    "receiver_pkt_rate": rx.get("pkt_rate") if rx else None,
                    "receiver_online": receiver_online,
                    "telemetry_age_seconds": telemetry_age_seconds,
                    "capabilities": _normalize_device_capabilities(dev.get("capabilities")),
                    "outputs": [],
                }
                if rx:
                    if "live_firmware_version" in rx:
                        d["live_firmware_version"] = rx.get("live_firmware_version")
                    if "battery_mv" in rx:
                        d["battery_mv"] = rx.get("battery_mv")
                    if "battery_pct" in rx:
                        d["battery_pct"] = rx.get("battery_pct")
                    if "battery_power_mode" in rx:
                        d["battery_power_mode"] = rx.get("battery_power_mode")
                    if "battery_warning" in rx:
                        d["battery_warning"] = rx.get("battery_warning")
                for o in dev["outputs"]:
                    d["outputs"].append({
                        "name": o["name"],
                        "type": o["type"],
                        "count": o["count"],
                        "grid": o["grid"],
                        "universe": o["universe"],
                        "grid_order": o["grid_order"],
                        "grid_rotation": o["grid_rotation"],
                    })
                out["devices"].append(d)
        lock_released = time.perf_counter()
        self.performance.observe_many((
            ("api_state_lock_wait_ms", (lock_acquired - lock_start) * 1000.0),
            ("api_state_lock_held_ms", (lock_released - lock_acquired) * 1000.0),
        ))
        return out

    # ------------------------------------------------------------------
    #  Update from API
    # ------------------------------------------------------------------

    def update(self, data):
        config_targets = []  # devices needing output config update (sent outside lock)
        with self.lock:
            if "fps" in data:
                self.fps = max(1, min(120, int(data["fps"])))
            if "look_name" in data:
                self.active_look["name"] = str(data["look_name"])[:32]

            di = data.get("device")
            oi = data.get("output")

            if di is not None and 0 <= di < len(self.devices):
                dev = self.devices[di]
                if "ip" in data:
                    dev["ip"] = str(data["ip"])
                    dev["sender"].ip = dev["ip"]
                if oi is not None and 0 <= oi < len(dev["outputs"]):
                    o = dev["outputs"][oi]
                    if "grid_order" in data:
                        val = str(data["grid_order"])
                        if val in GRID_ORDERS:
                            o["grid_order"] = val
                    if "grid_rotation" in data:
                        val = int(data["grid_rotation"])
                        if val in GRID_ROTATIONS:
                            o["grid_rotation"] = val
            elif oi is not None and 0 <= oi < len(self.active_look["outputs"]):
                lo = self.active_look["outputs"][oi]
                if "output_type" in data:
                    new_type = str(data["output_type"])
                    if new_type in OUTPUT_TYPES:
                        _apply_type_to_look_output(lo, new_type)
                        _save_output_types([o["type"] for o in self.active_look["outputs"]])
                if "effect" in data:
                    lo["effect"] = str(data["effect"])
                    lo["led_state"] = []
                if "playback" in data:
                    lo["playback"] = str(data["playback"])
                    lo["led_state"] = []
                if "speed" in data:
                    lo["speed"] = max(0.1, min(10.0, float(data["speed"])))
                if "brightness" in data:
                    lo["brightness"] = normalize_brightness(
                        data["brightness"], DEFAULT_BRIGHTNESS
                    )
                if "angle" in data:
                    lo["angle"] = float(data["angle"])
                if "start_color" in data:
                    lo["start_color"] = [int(v) for v in data["start_color"]]
                if "end_color" in data:
                    lo["end_color"] = [int(v) for v in data["end_color"]]
                if "highlight_width" in data:
                    lo["highlight_width"] = max(1, min(30, int(data["highlight_width"])))
                if "chase_origin" in data:
                    val = str(data["chase_origin"])
                    if val in ("start", "center", "end"):
                        lo["chase_origin"] = val

        # Send output config outside lock to avoid blocking animation
        for dev in config_targets:
            self._send_output_config(dev)

    # ------------------------------------------------------------------
    #  Output config
    # ------------------------------------------------------------------

    def _transport_error_text(self, error):
        message = getattr(error, "strerror", None) or str(error) or "UDP send failed"
        error_number = getattr(error, "errno", None)
        if error_number is not None:
            return f"{message} (errno {error_number})"
        return message

    def _mark_transport_error_unlocked(self, dev, error, disconnect=False):
        message = self._transport_error_text(error)
        dev["transport_error"] = message
        if disconnect:
            dev["connected"] = False
            dev["sender"].disconnect()
            dev["send_fail_streak"] = 0
            print(f"Transport error for {dev['name']} ({dev['ip']}): {message}")

    def _record_device_send_result_unlocked(self, dev, ok):
        if ok:
            dev["send_fail_streak"] = 0
            dev["transport_error"] = None
            return
        streak = int(dev.get("send_fail_streak") or 0) + 1
        dev["send_fail_streak"] = streak
        if streak >= TRANSPORT_FAIL_STREAK_LIMIT:
            last_error = dev["sender"].last_error or "UDP send failed"
            dev["transport_error"] = last_error

    def _clear_transport_error_unlocked(self, dev):
        dev["transport_error"] = None
        dev["send_fail_streak"] = 0

    def _ensure_sender_connected_unlocked(self, dev):
        dev["sender"].ip = dev["ip"]
        if hasattr(dev["sender"], "set_source_ip"):
            dev["sender"].set_source_ip(self.artnet_source_ip)
        if not dev["sender"].connected:
            try:
                dev["sender"].connect()
            except OSError as error:
                self._mark_transport_error_unlocked(dev, error, disconnect=True)
                return False
        dev["connected"] = True
        self._clear_transport_error_unlocked(dev)
        return True

    def _apply_type_to_device_output_unlocked(self, dev_output, new_type):
        typedef = OUTPUT_TYPES.get(new_type)
        if typedef is None:
            raise ValueError(f"Unknown output type: {new_type!r}")
        dev_output["type"] = new_type
        dev_output["count"] = typedef["pixels"]
        dev_output["layout"] = typedef["layout"]
        dev_output["grid"] = (
            typedef.get("grid_size") if typedef["layout"] == "grid" else None
        )
        is_grid = typedef["layout"] == "grid"
        if is_grid:
            if dev_output.get("grid_order") not in GRID_ORDERS:
                dev_output["grid_order"] = "serpentine"
            if dev_output.get("grid_rotation") not in GRID_ROTATIONS:
                dev_output["grid_rotation"] = 0
        else:
            dev_output["grid_order"] = "progressive"
            dev_output["grid_rotation"] = 0

    def _send_output_config(self, dev):
        caps = _normalize_device_capabilities(dev.get("capabilities"))
        if not caps.get("output_config"):
            return False, "output configuration is not advertised for this node"

        types = [o["type"] for o in dev.get("outputs", [])]
        if not types:
            return False, "device has no outputs to configure"
        type_to_id = {name: i for i, name in enumerate(LOOK_OUTPUT_TYPES)}
        try:
            send_output_config(
                dev["ip"], types, type_to_id, source_ip=self.artnet_source_ip)
        except OSError as error:
            return False, self._transport_error_text(error)
        for o in dev.get("outputs", []):
            typedef = OUTPUT_TYPES.get(o.get("type"))
            if typedef:
                o["count"] = typedef["pixels"]
                o["layout"] = typedef["layout"]
                o["grid"] = (
                    typedef.get("grid_size") if typedef["layout"] == "grid" else None
                )
        return True, None

    def set_device_output_type(self, di, oi, output_type):
        with self.lock:
            status = self._device_capability_status_unlocked(di, "output_config")
            if not status["ok"]:
                return status
            dev = self.devices[di]
            if not (0 <= oi < len(dev.get("outputs", []))):
                return {"ok": False, "error": "invalid output index"}
            if output_type not in OUTPUT_TYPES:
                return {"ok": False, "error": f"unknown output type: {output_type!r}"}
            prior = copy.deepcopy(dev["outputs"][oi])
            try:
                self._apply_type_to_device_output_unlocked(dev["outputs"][oi], output_type)
            except ValueError as error:
                return {"ok": False, "error": str(error)}
            if dev["sender"].connected:
                if not self._ensure_sender_connected_unlocked(dev):
                    dev["outputs"][oi] = prior
                    return {
                        "ok": False,
                        "error": dev.get("transport_error") or "sender connection failed",
                    }
                config_ok, config_error = self._send_output_config(dev)
                if not config_ok:
                    dev["outputs"][oi] = prior
                    return {
                        "ok": False,
                        "error": config_error or "output configuration failed",
                    }
                _save_devices(self.devices)
                return _config_apply_result(True)
            _save_devices(self.devices)
            return _config_apply_result(False)

    def set_device_receive_mode(self, di, receive_mode, base_universe):
        with self.lock:
            status = self._device_capability_status_unlocked(di, "receive_config")
            if not status["ok"]:
                return status
            if receive_mode not in RECEIVE_MODES:
                return {"ok": False, "error": f"invalid receive_mode: {receive_mode!r}"}
            dev = self.devices[di]
            try:
                base_universe = int(base_universe)
            except (TypeError, ValueError):
                return {"ok": False, "error": "base_universe must be an integer"}
            if base_universe < 0 or base_universe > 32767:
                return {"ok": False, "error": "base_universe must be 0-32767"}
            valid, err = _validate_receive_mode_for_device(receive_mode, dev.get("outputs", []))
            if not valid:
                return {"ok": False, "error": err}
            prior_mode = dev.get("receive_mode", "split")
            prior_base = dev.get("base_universe", 0)
            dev["receive_mode"] = receive_mode
            dev["base_universe"] = base_universe
            _apply_output_universes(dev["outputs"], receive_mode, base_universe)
            try:
                send_receive_config(
                    dev["ip"],
                    receive_mode,
                    base_universe,
                    source_ip=self.artnet_source_ip,
                )
            except OSError as error:
                dev["receive_mode"] = prior_mode
                dev["base_universe"] = prior_base
                _apply_output_universes(dev["outputs"], prior_mode, prior_base)
                self._mark_transport_error_unlocked(dev, error)
                return {"ok": False, "error": self._transport_error_text(error)}
            self._clear_transport_error_unlocked(dev)
            _save_devices(self.devices)
            return _config_apply_result(True)

    # ------------------------------------------------------------------
    #  Device management
    # ------------------------------------------------------------------

    def connect(self, di):
        with self.lock:
            dev = self.devices[di]
            if not self._ensure_sender_connected_unlocked(dev):
                return {
                    "ok": False,
                    "error": dev.get("transport_error") or "sender connection failed",
                }
            config_ok, config_error = self._send_output_config(dev)
            if not config_ok:
                dev["transport_error"] = config_error or "output configuration failed"
                return {
                    "ok": False,
                    "error": config_error or "output configuration failed",
                }
            info = _device_blackout_info(dev)
            dev["sender"].blackout(info)
            self._clear_transport_error_unlocked(dev)
            return {"ok": True}

    def disconnect(self, di):
        with self.lock:
            dev = self.devices[di]
            if dev["sender"].connected:
                info = _device_blackout_info(dev)
                dev["sender"].blackout(info)
            dev["sender"].disconnect()
            dev["connected"] = False

    def add_device_from_node(self, node_info, auto_save=True):
        with self.lock:
            idx = self._find_existing_device_index_unlocked(node_info)
            if idx is not None:
                dev = self.devices[idx]
                ip_changed = dev["ip"] != node_info["ip"]
                groups_changed = False
                if ip_changed:
                    old_ip = dev["ip"]
                    dev["ip"] = node_info["ip"]
                    dev["sender"].ip = dev["ip"]
                    _migrate_device_show_info_key(old_ip, dev["ip"], dev.get("name"))
                    groups_changed = self._replace_device_ip_references_unlocked(old_ip, dev["ip"])
                updated = self._refresh_device_from_node_unlocked(dev, node_info)
                if (updated or ip_changed) and auto_save:
                    _save_devices(self.devices)
                if groups_changed and auto_save:
                    _save_device_groups(self.device_groups)
                return {
                    "status": "updated" if (updated or ip_changed) else "exists",
                    "device_index": idx,
                }

            output_cfgs = _output_configs_from_node(node_info)
            capabilities = _capabilities_from_node(node_info)
            base_u = (
                output_cfgs[0].get("universe", 0)
                if output_cfgs else
                (node_info["universes"][0] if node_info.get("universes") else 0)
            )
            receive_mode, base_u = _receive_fields_from_node(
                node_info, capabilities, fallback_base=base_u)

            character_name, performer_name = _show_info_from_node(node_info)
            character_name, performer_name = _merge_show_info_fields(
                character_name,
                performer_name,
                node_info.get("ip"),
                node_info.get("short_name"),
            )

            dev = {
                "name": node_info.get("short_name", "Node"),
                "character_name": character_name,
                "performer_name": performer_name,
                "ip": node_info["ip"],
                "base_universe": base_u,
                "receive_mode": receive_mode,
                "connected": False,
                "sender": ArtNetSender(node_info["ip"], source_ip=self.artnet_source_ip),
                "transport_error": None,
                "send_fail_streak": 0,
                "capabilities": capabilities,
                "hardware_profile": node_info.get(
                    "hardware_profile", capabilities.get("hardware_profile", "unknown")),
                "hardware_label": node_info.get(
                    "hardware_label", capabilities.get("hardware_label", "Unknown hardware")),
                "firmware_version": node_info.get(
                    "firmware_version", capabilities.get("firmware_version")),
                "ip_config_pending": None,
                "outputs": [],
            }
            _apply_network_capabilities_to_device(dev, capabilities, fallback_ip=dev["ip"])
            dev["outputs"] = self._build_device_outputs_unlocked(
                node_info, output_cfgs, base_u, receive_mode=receive_mode)
            _apply_persisted_show_info(dev, node_info)
            self.devices.append(dev)
            if dev.get("character_name") or dev.get("performer_name"):
                self._sync_show_info_to_device_unlocked(dev)
            if auto_save:
                _save_devices(self.devices)
            return {"status": "added", "device_index": len(self.devices) - 1}

    def _find_existing_device_index_unlocked(self, node_info):
        node_ip = node_info.get("ip")
        for idx, dev in enumerate(self.devices):
            if dev["ip"] == node_ip:
                return idx
            if dev.get("ip_config_pending") == "static" and dev.get("static_ip") == node_ip:
                return idx

        if not _node_has_discovery_metadata(node_info):
            return None

        short_name = str(node_info.get("short_name", "")).strip()
        if not short_name:
            return None
        matches = [
            idx for idx, dev in enumerate(self.devices)
            if dev.get("name") == short_name
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def _build_device_outputs_unlocked(self, node_info, output_cfgs, base_u,
                                       existing_outputs=None,
                                       receive_mode="split"):
        outputs = []
        existing_outputs = existing_outputs or []
        existing_by_name = {
            output.get("name"): output
            for output in existing_outputs
            if isinstance(output, dict)
        }
        universes = node_info.get("universes", [])
        for idx, o_cfg in enumerate(output_cfgs):
            resolved = resolve_output(o_cfg)
            universe = o_cfg.get(
                "universe",
                universes[idx] if idx < len(universes) else base_u + idx,
            )
            prior = existing_by_name.get(resolved["name"])
            if prior is None and idx < len(existing_outputs):
                prior = existing_outputs[idx]
            is_grid = resolved["layout"] == "grid"
            grid_order = o_cfg.get("grid_order")
            if grid_order not in GRID_ORDERS:
                grid_order = prior.get("grid_order") if prior else None
            if grid_order not in GRID_ORDERS:
                grid_order = "serpentine" if is_grid else "progressive"
            grid_rotation = o_cfg.get("grid_rotation")
            if grid_rotation not in GRID_ROTATIONS:
                grid_rotation = prior.get("grid_rotation") if prior else 0
            outputs.append({
                **resolved,
                "universe": universe,
                "grid_order": grid_order if is_grid else "progressive",
                "grid_rotation": grid_rotation if is_grid else 0,
            })
        _apply_output_universes(outputs, receive_mode, base_u)
        return outputs

    def _refresh_device_from_node_unlocked(self, dev, node_info):
        if not _node_has_discovery_metadata(node_info):
            return False

        capabilities = _capabilities_from_node(node_info)
        short_name = node_info.get("short_name")
        if short_name:
            dev["name"] = short_name
        dev["capabilities"] = capabilities
        dev["hardware_profile"] = node_info.get(
            "hardware_profile", capabilities.get("hardware_profile", "unknown"))
        dev["hardware_label"] = node_info.get(
            "hardware_label", capabilities.get("hardware_label", "Unknown hardware"))
        dev["firmware_version"] = node_info.get(
            "firmware_version", capabilities.get("firmware_version"))
        _apply_network_capabilities_to_device(dev, capabilities, fallback_ip=dev["ip"])
        dev["ip_config_pending"] = None

        char, perf = _show_info_from_node(node_info)
        char, perf = _merge_show_info_fields(char, perf, dev.get("ip"), dev.get("name"))
        if char:
            dev["character_name"] = char
        if perf:
            dev["performer_name"] = perf

        output_cfgs = _output_configs_from_node(node_info)
        if output_cfgs:
            fallback_base = output_cfgs[0].get(
                "universe",
                node_info.get("universes", [dev.get("base_universe", 0)])[0]
                if node_info.get("universes") else dev.get("base_universe", 0)
            )
            receive_mode, base_u = _receive_fields_from_node(
                node_info, capabilities, fallback_base=fallback_base)
            dev["receive_mode"] = receive_mode
            dev["base_universe"] = base_u
            dev["outputs"] = self._build_device_outputs_unlocked(
                node_info, output_cfgs, base_u,
                existing_outputs=dev.get("outputs", []),
                receive_mode=receive_mode)
        dev["sender"].ip = dev["ip"]
        return True

    def _replace_device_ip_references_unlocked(self, old_ip, new_ip):
        if not old_ip or not new_ip or old_ip == new_ip:
            return False
        changed = False
        for group in self.device_groups:
            ips = group.get("device_ips")
            if not isinstance(ips, list) or old_ip not in ips:
                continue
            updated_ips = []
            for ip in ips:
                replacement = new_ip if ip == old_ip else ip
                if replacement not in updated_ips:
                    updated_ips.append(replacement)
            group["device_ips"] = updated_ips
            changed = True
        if self._controller_device_ips is not None and old_ip in self._controller_device_ips:
            self._controller_device_ips.discard(old_ip)
            self._controller_device_ips.add(new_ip)
        return changed

    def remove_device(self, di):
        with self.lock:
            if 0 <= di < len(self.devices):
                dev = self.devices[di]
                if dev["sender"].connected:
                    info = _device_blackout_info(dev)
                    dev["sender"].blackout(info)
                    dev["sender"].disconnect()
                self.devices.pop(di)
                _save_devices(self.devices)
                return True
        return False

    def _device_capability_status_unlocked(self, di, capability):
        if not (0 <= di < len(self.devices)):
            return {"ok": False, "error": "invalid device index"}

        dev = self.devices[di]
        caps = _normalize_device_capabilities(dev.get("capabilities"))
        if caps.get(capability):
            return {"ok": True, "device": dev["name"]}

        label = CONTROL_CAPABILITY_LABELS.get(capability, capability.replace("_", " "))
        if caps.get("known"):
            return {"ok": False, "error": f'{dev["name"]} does not advertise {label} support.'}
        return {"ok": False, "error": f'{dev["name"]} has not advertised {label} support.'}

    def device_capability_status(self, di, capability):
        with self.lock:
            return self._device_capability_status_unlocked(di, capability)

    def rename_device(self, di, new_name):
        with self.lock:
            status = self._device_capability_status_unlocked(di, "rename")
            if not status["ok"]:
                return status
            dev = self.devices[di]
            try:
                send_art_address(dev["ip"], new_name, source_ip=self.artnet_source_ip)
            except OSError as error:
                self._mark_transport_error_unlocked(dev, error)
                return {"ok": False, "error": dev.get("transport_error")}
            dev["name"] = new_name
            self._clear_transport_error_unlocked(dev)
            _save_devices(self.devices)
            return {"ok": True}

    def _sync_show_info_to_device_unlocked(self, dev):
        caps = _normalize_device_capabilities(dev.get("capabilities"))
        if not caps.get("show_info"):
            return True
        try:
            send_show_info(
                dev["ip"],
                dev.get("character_name", ""),
                dev.get("performer_name", ""),
                source_ip=self.artnet_source_ip,
            )
        except OSError as error:
            self._mark_transport_error_unlocked(dev, error)
            return False
        self._clear_transport_error_unlocked(dev)
        return True

    def update_device_show_info(self, di, character_name=None, performer_name=None):
        with self.lock:
            if not (0 <= di < len(self.devices)):
                return {"ok": False, "error": "invalid device index"}
            dev = self.devices[di]
            if character_name is not None:
                dev["character_name"] = _normalize_show_info_value(character_name)
            if performer_name is not None:
                dev["performer_name"] = _normalize_show_info_value(performer_name)
            caps = _normalize_device_capabilities(dev.get("capabilities"))
            applied_to_device = False
            if caps.get("show_info"):
                if not self._sync_show_info_to_device_unlocked(dev):
                    return {"ok": False, "error": dev.get("transport_error")}
                applied_to_device = True
            _persist_device_show_info(
                dev["ip"],
                dev.get("name"),
                dev.get("character_name"),
                dev.get("performer_name"),
            )
            _save_devices(self.devices)
            return {"ok": True, "applied_to_device": applied_to_device}

    def set_device_ip(self, di, static_ip, gateway, subnet):
        with self.lock:
            status = self._device_capability_status_unlocked(di, "ip_config")
            if not status["ok"]:
                return status
            dev = self.devices[di]
            try:
                ipv4_octets(static_ip, "ip")
                ipv4_octets(gateway, "gateway")
                ipv4_octets(subnet, "subnet")
                send_ip_config(dev["ip"], 1, static_ip, gateway, subnet, source_ip=self.artnet_source_ip)
            except (OSError, ValueError) as error:
                self._mark_transport_error_unlocked(dev, error)
                return {"ok": False, "error": dev.get("transport_error")}
            dev["ip_mode"] = "static"
            dev["static_ip"] = static_ip
            dev["gateway"] = gateway
            dev["subnet"] = subnet
            dev["ip_config_pending"] = "static"
            self._clear_transport_error_unlocked(dev)
            _save_devices(self.devices)
            return {"ok": True}

    def revert_device_dhcp(self, di):
        with self.lock:
            status = self._device_capability_status_unlocked(di, "ip_config")
            if not status["ok"]:
                return status
            dev = self.devices[di]
            try:
                send_ip_config(dev["ip"], 0, source_ip=self.artnet_source_ip)
            except (OSError, ValueError) as error:
                self._mark_transport_error_unlocked(dev, error)
                return {"ok": False, "error": dev.get("transport_error")}
            dev["ip_mode"] = "dhcp"
            dev["static_ip"] = None
            dev["gateway"] = None
            dev["subnet"] = None
            dev["ip_config_pending"] = "dhcp"
            self._clear_transport_error_unlocked(dev)
            _save_devices(self.devices)
            return {"ok": True}

    def connect_all(self, only_ips=None):
        results = []
        only_ips = set(only_ips) if only_ips is not None else None
        with self.lock:
            for idx, dev in enumerate(self.devices):
                if only_ips is not None and dev.get("ip") not in only_ips:
                    results.append({
                        "device_index": idx,
                        "ok": True,
                        "skipped": True,
                        "reason": "not discovered",
                        "error": None,
                    })
                    continue
                ok = self._ensure_sender_connected_unlocked(dev)
                if ok:
                    caps = _normalize_device_capabilities(dev.get("capabilities"))
                    config_ok, config_error = self._send_output_config(dev)
                    if caps.get("output_config"):
                        ok = config_ok
                        if not ok and config_error:
                            dev["transport_error"] = config_error
                results.append({
                    "device_index": idx,
                    "ok": ok,
                    "error": None if ok else dev.get("transport_error"),
                })
        return results

    def disconnect_all(self):
        with self.lock:
            for dev in self.devices:
                if dev["sender"].connected:
                    info = _device_blackout_info(dev)
                    dev["sender"].blackout(info)
                    dev["sender"].disconnect()
                    dev["connected"] = False

    # ------------------------------------------------------------------
    #  Device groups
    # ------------------------------------------------------------------

    def get_device_groups(self):
        with self.lock:
            return list(self.device_groups)

    def save_device_group(self, group):
        """Create or update a device group. group = {id, name, device_ips}."""
        with self.lock:
            gid = group.get("id")
            for i, g in enumerate(self.device_groups):
                if g["id"] == gid:
                    self.device_groups[i] = group
                    _save_device_groups(self.device_groups)
                    return group
            self.device_groups.append(group)
            _save_device_groups(self.device_groups)
            return group

    def delete_device_group(self, gid):
        with self.lock:
            self.device_groups = [g for g in self.device_groups if g["id"] != gid]
            _save_device_groups(self.device_groups)
            return True

    def hello_device(self, di):
        """Send a quick red flash to all outputs on a device to help locate it."""
        with self.lock:
            status = self._device_capability_status_unlocked(di, "hello")
            if not status["ok"]:
                return False
            dev = self.devices[di]
            if not dev.get("connected"):
                return False
            if not self._ensure_sender_connected_unlocked(dev):
                return False
            dev["_hello_until"] = time.monotonic() + 1.0
            return True

    # ------------------------------------------------------------------
    #  Override pixels (for mixer / controller playback)
    # ------------------------------------------------------------------

    def set_override_pixels(self, pixels_per_output, device_ips=None):
        """Set override pixels from mixer or controller. Pass None to clear.
        device_ips: set of IP strings to target, or None for all devices.
        """
        with self.lock:
            self._override_pixels = pixels_per_output
            self._override_frames_by_device = None
            self._override_default_frames = None
            self._controller_device_ips = device_ips

    def clear_override_pixels_if_present(self):
        """Clear override buffers once when returning to designer/idle output."""
        with self.lock:
            if (self._override_pixels is None
                    and self._override_frames_by_device is None
                    and self._override_default_frames is None
                    and self._controller_device_ips is None):
                return False
            self._clear_override_unlocked()
            return True

    def set_override_frames_by_device(self, frames_by_ip=None, default_frames=None):
        """Set per-device controller frames.

        frames_by_ip maps device IP -> list of output frame dicts.
        default_frames applies to devices without a specific frame; None means
        only explicitly mapped devices receive output.
        """
        frames_by_ip = frames_by_ip or {}
        with self.lock:
            self._override_pixels = None
            self._override_frames_by_device = dict(frames_by_ip)
            self._override_default_frames = default_frames
            if default_frames is None:
                self._controller_device_ips = set(frames_by_ip.keys())
            else:
                self._controller_device_ips = None

    def _clear_override_unlocked(self):
        """Clear any cached override frame and controller-specific targeting."""
        self._override_pixels = None
        self._override_frames_by_device = None
        self._override_default_frames = None
        self._controller_device_ips = None

    def _clear_mixer_preview_unlocked(self):
        """Reset mixer preview bookkeeping without changing playback source."""
        self._mixer_preview_look = None
        self._mixer_preview_play_time = 0.0
        self._mixer_preview_transport_time = 0.0
        self._mixer_preview_start_mono = 0.0
        self._mixer_preview_playing = False
        self._mixer_preview_device_filter = None
        self._mixer_update_last_seq = 0

    def _set_playback_source_unlocked(self, source):
        """Apply playback-source transitions with centralized cleanup rules."""
        if source not in self.PLAYBACK_SOURCES:
            raise ValueError(f"Invalid playback source: {source!r}")

        if source != self.SOURCE_MIXER:
            self._clear_mixer_preview_unlocked()
        if source != self.SOURCE_CONTROLLER:
            self._controller_device_ips = None
            self._override_frames_by_device = None
            self._override_default_frames = None
        if source in (self.SOURCE_DESIGNER, self.SOURCE_IDLE):
            self._override_pixels = None

        self.playback_source = source
        self.render_event.set()

    def start_mixer_preview(self, look, device_filter=None,
                            play_time=0.0, playing=False,
                            transport_time=None, seq=None):
        """Start previewing a look from the mixer on connected devices.
        play_time: wrapped playhead time shown in the timeline.
        transport_time: unwrapped timeline time for live playback.
        playing: whether the clock should advance.
        """
        with self.lock:
            self._clear_mixer_preview_unlocked()
            self._mixer_preview_look = look
            self._mixer_preview_play_time = play_time
            self._mixer_preview_transport_time = (
                play_time if transport_time is None else transport_time
            )
            self._mixer_preview_start_mono = time.monotonic()
            self._mixer_preview_playing = playing
            self._mixer_preview_device_filter = self._normalize_mixer_device_filter(device_filter)
            if seq is not None:
                self._mixer_update_last_seq = seq
            self._set_playback_source_unlocked(self.SOURCE_MIXER)

    def update_mixer_preview(self, play_time=None, playing=None,
                             transport_time=None, seq=None,
                             device_filter=_DEVICE_FILTER_UNCHANGED):
        """Update time / playing state without resending the full look.
        seq: monotonically increasing sequence number from the client. If
        provided and lower than the last processed sequence, the update is
        ignored (stale out-of-order request from browser connection pool).
        """
        with self.lock:
            if self._mixer_preview_look is None:
                return
            if seq is not None:
                if seq < self._mixer_update_last_seq:
                    return  # Stale request, ignore
                self._mixer_update_last_seq = seq
            if device_filter is not _DEVICE_FILTER_UNCHANGED:
                self._mixer_preview_device_filter = self._normalize_mixer_device_filter(device_filter)
            if play_time is not None:
                self._mixer_preview_play_time = play_time
            if transport_time is not None:
                self._mixer_preview_transport_time = transport_time
            if play_time is not None or transport_time is not None:
                self._mixer_preview_start_mono = time.monotonic()
            if playing is not None:
                if playing and not self._mixer_preview_playing:
                    # Resuming: anchor monotonic clock at the current transport time.
                    self._mixer_preview_start_mono = time.monotonic()
                elif (not playing and self._mixer_preview_playing
                      and transport_time is None):
                    # Pausing: freeze transport time at the current value.
                    self._mixer_preview_transport_time += (
                        time.monotonic() - self._mixer_preview_start_mono)
                self._mixer_preview_playing = playing

    def stop_mixer_preview(self):
        """Stop mixer preview, return to idle (no output)."""
        with self.lock:
            self._set_playback_source_unlocked(self.SOURCE_IDLE)

    def set_playback_source(self, source):
        """Explicitly set the playback source.

        Mixer preview should be started through start_mixer_preview() so the
        preview look and timing state are initialized consistently.
        Returns True when the source is accepted, else False.
        """
        with self.lock:
            if source not in self.API_PLAYBACK_SOURCES:
                return False
            self._set_playback_source_unlocked(source)
            return True

    def get_mixer_preview(self):
        """Return (look, computed_time) if mixer preview is active, else (None, 0)."""
        with self.lock:
            if self._mixer_preview_look:
                if self._mixer_preview_playing:
                    t = self._mixer_preview_transport_time + (
                        time.monotonic() - self._mixer_preview_start_mono)
                else:
                    t = self._mixer_preview_transport_time
                return self._mixer_preview_look, t
            return None, 0.0

    def wait_for_render_work(self, timeout=0.25):
        """Wait until mixer/controller work changes or timeout expires."""
        self.render_event.wait(timeout)
        self.render_event.clear()

    def get_performance_json(self):
        return self.performance.snapshot()

    # ------------------------------------------------------------------
    #  Animation tick
    # ------------------------------------------------------------------

    def tick(self):
        tick_start = time.perf_counter()
        now = time.monotonic()
        send_queue = []

        lock_start = time.perf_counter()
        with self.lock:
            lock_acquired = time.perf_counter()
            t = now - self.start_time
            dt = max(now - self.last_tick, 0.001)
            self.last_tick = now

            device_frames_active = (
                self._override_frames_by_device is not None
                or self._override_default_frames is not None
            )

            if device_frames_active:
                for lo in self.active_look["outputs"]:
                    lo["pixels"] = []
            elif self._override_pixels is not None:
                # Use mixer/controller pre-computed pixels
                for i, lo in enumerate(self.active_look["outputs"]):
                    if i < len(self._override_pixels) and self._override_pixels[i]:
                        lo["pixels"] = self._override_pixels[i]
                    else:
                        lo["pixels"] = []
            elif self.playback_source == self.SOURCE_DESIGNER:
                # Compute from designer (active look)
                for lo in self.active_look["outputs"]:
                    if lo["type"] == "none" or lo["count"] == 0:
                        lo["pixels"] = []
                        continue
                    speed = lo["speed"]
                    scaled_t = t * speed
                    af = compute_anim_factor(scaled_t, lo["playback"])
                    fn = EFFECTS.get(lo["effect"], fx_none)
                    pixels = fn(
                        count=lo["count"], t=scaled_t, dt=dt,
                        speed=speed, anim_factor=af,
                        duration=5.0,
                        playback=lo["playback"],
                        start_color=tuple(lo["start_color"]),
                        end_color=tuple(lo["end_color"]),
                        state=lo["led_state"],
                        grid=lo.get("grid"), angle=lo["angle"],
                        highlight_width=lo["highlight_width"],
                        chase_origin=lo["chase_origin"],
                    )
                    pixels = scale_pixels(
                        pixels, lo.get("brightness", DEFAULT_BRIGHTNESS)
                    )
                    lo["pixels"] = [list(p) for p in pixels]
            else:
                # Idle: no output (black)
                for lo in self.active_look["outputs"]:
                    lo["pixels"] = []

            # Send to connected devices
            dev_filter = self._mixer_preview_device_filter
            ctrl_ips = self._controller_device_ips if self.playback_source == self.SOURCE_CONTROLLER else None
            devices_sent = set()
            for di, dev in enumerate(self.devices):
                if not dev.get("connected"):
                    continue
                if not dev["sender"].connected:
                    if not self._ensure_sender_connected_unlocked(dev):
                        continue
                if dev_filter is not None and di not in dev_filter:
                    continue
                if ctrl_ips is not None and dev["ip"] not in ctrl_ips:
                    continue
                hello_until = dev.get("_hello_until", 0)
                if hello_until:
                    if now < hello_until:
                        for universe, data in _device_flash_entries(
                                dev, bytes([255, 0, 0])):
                            send_queue.append((di, dev["sender"], universe, data))
                        devices_sent.add(di)
                        continue
                    dev["_hello_until"] = 0
                if device_frames_active:
                    frames = None
                    if self._override_frames_by_device is not None:
                        frames = self._override_frames_by_device.get(dev["ip"])
                    if frames is None:
                        frames = self._override_default_frames
                    if not frames:
                        continue
                    frame_buffers = {}
                    for oi, o in enumerate(dev["outputs"]):
                        if oi >= len(frames):
                            continue
                        frame = frames[oi] or {}
                        pixels = frame.get("pixels") or []
                        if not pixels:
                            continue
                        send_pixels = list(pixels)
                        grid = frame.get("grid")
                        if grid:
                            cols, rows = grid
                            if o.get("grid_rotation", 0) != 0:
                                send_pixels = apply_grid_rotation(
                                    send_pixels, cols, rows, o["grid_rotation"])
                            send_pixels = apply_serpentine(send_pixels, cols, rows)

                        buf = bytearray()
                        for r, g, b in send_pixels:
                            buf.extend((r & 0xFF, g & 0xFF, b & 0xFF))
                        frame_buffers[oi] = bytes(buf)
                    if frame_buffers:
                        _queue_device_frame_sends(send_queue, di, dev, frame_buffers)
                        devices_sent.add(di)
                    continue
                frame_buffers = {}
                for oi, o in enumerate(dev["outputs"]):
                    if oi >= len(self.active_look["outputs"]):
                        continue
                    lo = self.active_look["outputs"][oi]
                    if lo["type"] == "none" or not lo["pixels"]:
                        continue
                    send_pixels = list(lo["pixels"])

                    grid = lo.get("grid")
                    if grid:
                        cols, rows = grid
                        if o.get("grid_rotation", 0) != 0:
                            send_pixels = apply_grid_rotation(
                                send_pixels, cols, rows, o["grid_rotation"])
                        send_pixels = apply_serpentine(send_pixels, cols, rows)

                    buf = bytearray()
                    for r, g, b in send_pixels:
                        buf.extend((r & 0xFF, g & 0xFF, b & 0xFF))
                    frame_buffers[oi] = bytes(buf)
                if frame_buffers:
                    _queue_device_frame_sends(send_queue, di, dev, frame_buffers)
                    devices_sent.add(di)

            # Keepalive blackout so receivers learn sender IP and report telemetry
            for di, dev in enumerate(self.devices):
                if di in devices_sent:
                    continue
                if not dev.get("connected") or not dev["sender"].connected:
                    continue
                if dev_filter is not None and di not in dev_filter:
                    continue
                if ctrl_ips is not None and dev["ip"] not in ctrl_ips:
                    continue
                keepalive_sent = False
                if dev.get("receive_mode") == "combined":
                    total = _combined_pixel_total(dev.get("outputs", []))
                    pixel_bytes = total * 3 if total > 0 else 3
                    send_queue.append(
                        (di, dev["sender"], dev.get("base_universe", 0), bytes(pixel_bytes)))
                    keepalive_sent = True
                else:
                    for o in dev["outputs"]:
                        count = o.get("count") or 0
                        if count <= 0:
                            continue
                        send_queue.append(
                            (di, dev["sender"], o["universe"], bytes(count * 3)))
                        keepalive_sent = True
                    if not keepalive_sent:
                        send_queue.append(
                            (di, dev["sender"], dev.get("base_universe", 0), bytes(3)))
                        keepalive_sent = True
                if keepalive_sent:
                    devices_sent.add(di)
        lock_released = time.perf_counter()

        failed_indices = set()
        successful_indices = set()
        device_send_ok = {}
        send_start = time.perf_counter()
        for di, sender, universe, data in send_queue:
            one_send_start = time.perf_counter()
            ok = sender.send_output(universe, data)
            if di not in device_send_ok:
                device_send_ok[di] = True
            device_send_ok[di] = device_send_ok[di] and ok
            if ok:
                successful_indices.add(di)
            else:
                failed_indices.add(di)
            self.performance.observe(
                "artnet_send_ms",
                (time.perf_counter() - one_send_start) * 1000.0,
            )
        send_finished = time.perf_counter()
        if send_queue:
            self.performance.increment("artnet_packets", len(send_queue))
            self.performance.increment("artnet_frames_with_packets")
        seen = set()
        for _, sender, _, _ in send_queue:
            sid = id(sender)
            if sid not in seen:
                seen.add(sid)
                sender.advance_sequence()
        if device_send_ok:
            with self.lock:
                for di, all_ok in device_send_ok.items():
                    if 0 <= di < len(self.devices):
                        dev = self.devices[di]
                        if dev.get("connected"):
                            self._record_device_send_result_unlocked(dev, all_ok)
        self.performance.observe_many((
            ("tick_lock_wait_ms", (lock_acquired - lock_start) * 1000.0),
            ("tick_lock_held_ms", (lock_released - lock_acquired) * 1000.0),
            ("tick_send_batch_ms", (send_finished - send_start) * 1000.0),
            ("tick_send_packets", len(send_queue)),
            ("tick_total_ms", (time.perf_counter() - tick_start) * 1000.0),
        ))

    def shutdown(self):
        self.running = False
        for dev in self.devices:
            if dev["sender"].connected:
                info = _device_blackout_info(dev)
                dev["sender"].blackout(info)
                dev["sender"].disconnect()


# ======================================================================
#  ANIMATION THREAD
# ======================================================================

def animation_loop(state):
    if set_current_thread_qos():
        state.performance.increment("animation_thread_qos_enabled")
    next_frame = time.monotonic()
    while state.running:
        frame_start = time.perf_counter()
        state.tick()
        state.performance.increment("animation_frames")
        state.performance.observe(
            "animation_tick_ms", (time.perf_counter() - frame_start) * 1000.0)
        next_frame += 1.0 / max(1, state.fps)
        sleep_time = next_frame - time.monotonic()
        if sleep_time > 0:
            requested_sleep = sleep_time
            _sleep_until_frame(next_frame)
            state.performance.observe(
                "animation_sleep_latency_ms",
                max(0.0, time.monotonic() - next_frame) * 1000.0,
            )
            state.performance.observe(
                "animation_sleep_requested_ms",
                requested_sleep * 1000.0,
            )
        else:
            state.performance.increment("animation_frame_overruns")
            next_frame = time.monotonic()
