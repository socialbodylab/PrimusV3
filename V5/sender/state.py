"""
state.py — Output type tables, controller state, animation tick, persistence.
"""

import copy
import json
import os
import re
import sys
import threading
import time

from effects import (
    EFFECTS, fx_none, compute_anim_factor,
    apply_grid_rotation,
    normalize_brightness, scale_pixels,
)
from artnet import (
    ArtNetSender,
    parse_node_capabilities,
    parse_node_outputs,
    resolve_lane_ports,
    device_show_port,
    device_setup_port,
    FPS_LISTEN_PORT,
    send_lane_ports,
    set_primus_lane_ports,
    get_primus_config,
    set_primus_output_descriptors,
    set_primus_telemetry_target,
    set_primus_operating_mode,
    set_primus_receive_config,
    set_primus_ip_config,
    set_primus_identity,
    unlock_primus_boot_window,
    PrimusManagementError,
    PrimusManagementInvalidPayload,
    PrimusManagementInternalError,
    PrimusManagementLocked,
    PrimusManagementNotAvailable,
    PrimusManagementOutOfRange,
    PrimusManagementProtocolError,
    PrimusManagementTimeout,
    PrimusManagementUnsupportedOperation,
    send_output_config,
    send_virtual_resolution,
    send_receive_config,
    send_ip_config,
    send_show_info,
    sync_show_info_to_device,
    sync_device_name_to_receiver,
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
    ipv4_octets,
)
from output_presets import OutputPresetStore, normalize_output_descriptor_template
from paths import state_file
from primus_protocol import (
    DeviceConfig,
    IpMode,
    Layout,
    MAX_COMBINED_VIRTUAL_PIXELS,
    MAX_PHYSICAL_PIXELS,
    OFF_DESCRIPTOR,
    OperatingMode,
    OutputDescriptor,
    ReceiveMode,
    ScanPattern,
    StartCorner,
    TraversalAxis,
    descriptor_from_legacy,
    validate_receive_config,
)
import show_info_store
from virtual_resolution import (
    default_virtual_pixels,
    resolve_virtual_pixels,
    virtual_percent_to_count,
    transport_rgb_bytes,
)


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
    "device_class": "unknown",
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
    "receive_mode": "combined",
    "base_universe": 0,
    "battery": False,
    "audio": False,
    "ftp": False,
    "show_info": False,
    "management": False,
    "management_protocol_version": None,
    "max_pixels_per_port": MAX_PHYSICAL_PIXELS,
    "max_combined_pixels": MAX_COMBINED_VIRTUAL_PIXELS,
    "port_show": None,
    "port_setup": None,
    "port_watch": None,
    "ftp_port": None,
    # Firmware binds a separate Setup lane. Nodes on default ports advertise no
    # lane token (it does not fit the 64-byte Node Report), so this flag is the
    # only thing distinguishing them from pre-lane firmware whose management
    # still lives on the Show port. Dropping it here would silently route every
    # Setup opcode back to 6454.
    "lane_aware": False,
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
CUSTOM_OUTPUT_TYPE = "custom"
OUTPUT_SLOT_COUNT = 2
MANAGEMENT_PROTOCOL_NAME = "primus"
MANAGEMENT_TOKEN_RE = re.compile(r"(?:^|\|)G:(\d+)([A-Z])(?:\||$)")
LAYOUT_NAMES = {
    Layout.OFF: "off",
    Layout.LINEAR: "linear",
    Layout.GRID: "grid",
}
LAYOUT_BY_NAME = {
    "none": Layout.OFF,
    "off": Layout.OFF,
    "linear": Layout.LINEAR,
    "grid": Layout.GRID,
}
TRAVERSAL_AXIS_NAMES = {
    TraversalAxis.ROW_MAJOR: "row_major",
    TraversalAxis.COLUMN_MAJOR: "column_major",
}
TRAVERSAL_AXIS_BY_NAME = {
    name: value
    for value, name in TRAVERSAL_AXIS_NAMES.items()
}
SCAN_PATTERN_NAMES = {
    ScanPattern.PROGRESSIVE: "progressive",
    ScanPattern.SERPENTINE: "serpentine",
}
SCAN_PATTERN_BY_NAME = {
    name: value
    for value, name in SCAN_PATTERN_NAMES.items()
}
START_CORNER_NAMES = {
    StartCorner.TOP_LEFT: "top_left",
    StartCorner.TOP_RIGHT: "top_right",
    StartCorner.BOTTOM_LEFT: "bottom_left",
    StartCorner.BOTTOM_RIGHT: "bottom_right",
}
START_CORNER_BY_NAME = {
    name: value
    for value, name in START_CORNER_NAMES.items()
}
BUILTIN_DESCRIPTOR_BY_TYPE = {
    output_type: descriptor_from_legacy(index)
    for index, output_type in enumerate(LOOK_OUTPUT_TYPES)
}
BUILTIN_TYPE_BY_DESCRIPTOR = {
    descriptor: output_type
    for output_type, descriptor in BUILTIN_DESCRIPTOR_BY_TYPE.items()
}
MANAGEMENT_ERROR_DETAILS = {
    PrimusManagementLocked: ("Locked", 409),
    PrimusManagementInvalidPayload: ("InvalidPayload", 400),
    PrimusManagementOutOfRange: ("OutOfRange", 400),
    PrimusManagementUnsupportedOperation: ("UnsupportedOperation", 409),
    PrimusManagementNotAvailable: ("NotAvailable", 409),
    PrimusManagementInternalError: ("InternalError", 502),
    PrimusManagementTimeout: ("Timeout", 504),
    PrimusManagementProtocolError: ("ProtocolError", 502),
    PrimusManagementError: ("ManagementError", 502),
}
MANAGEMENT_CALL_ERRORS = (PrimusManagementError, OSError, ValueError)
AUTHORITATIVE_MANAGEMENT_FIELDS = (
    "name",
    "character_name",
    "performer_name",
    "receive_mode",
    "base_universe",
    "outputs",
    "ip_mode",
    "static_ip",
    "gateway",
    "subnet",
    "ip_config_pending",
    "operating_mode",
    "production_mode",
    "management_locked",
    "unlock_window_open",
    "unlock_remaining_seconds",
    "telemetry_target",
    "telemetry_configured",
)

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

# Workshop kit default: Badge + Collar
DEFAULT_TEMPLATE = [
    {"name": "A0", "type": "small_grid"},
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
    out["device_class"] = str(out.get("device_class") or "unknown")
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
    out["audio"] = bool(out.get("audio"))
    out["ftp"] = bool(out.get("ftp"))
    out["show_info"] = bool(out.get("show_info"))
    out["lane_aware"] = bool(out.get("lane_aware"))
    out["management"] = bool(out.get("management"))
    version = out.get("management_protocol_version")
    out["management_protocol_version"] = int(version) if version is not None else None
    max_pixels = out.get("max_pixels_per_port")
    out["max_pixels_per_port"] = (
        int(max_pixels) if max_pixels is not None else MAX_PHYSICAL_PIXELS
    )
    max_combined = out.get("max_combined_pixels")
    out["max_combined_pixels"] = (
        int(max_combined)
        if max_combined is not None
        else MAX_COMBINED_VIRTUAL_PIXELS
    )
    for key in ("port_show", "port_setup", "port_watch", "ftp_port"):
        value = out.get(key)
        if value is None or value == "":
            out[key] = None
        else:
            try:
                out[key] = int(value)
            except (TypeError, ValueError):
                out[key] = None
    return out


def _apply_lane_ports_to_device(dev, capabilities=None):
    """Copy resolved Show/Setup/Watch ports onto the device record."""
    caps = _normalize_device_capabilities(capabilities or dev.get("capabilities"))
    ports = resolve_lane_ports(caps, is_radius=_is_radius_capabilities(caps))
    for key, value in ports.items():
        if value is not None:
            dev[key] = int(value)
    dev["capabilities"] = caps


def _validate_device_lane_ports(port_show, port_setup, port_watch):
    """Raise ValueError if the requested per-device lane ports are unusable."""
    ports = {"port_show": port_show, "port_setup": port_setup, "port_watch": port_watch}
    for name, value in ports.items():
        if value < 1 or value > 65535:
            raise ValueError(f"{name} must be 1-65535")
    if port_setup == port_show:
        raise ValueError("port_setup must differ from port_show")
    if port_setup == port_watch:
        raise ValueError("port_setup must differ from port_watch")


def _management_state_defaults(capabilities=None):
    caps = _normalize_device_capabilities(capabilities)
    supported = bool(caps.get("management"))
    version = caps.get("management_protocol_version")
    return {
        "management_supported": supported,
        "management_protocol": MANAGEMENT_PROTOCOL_NAME if supported or version else None,
        "management_protocol_version": version,
        "max_pixels_per_port": caps.get("max_pixels_per_port", MAX_PHYSICAL_PIXELS),
        "max_combined_pixels": caps.get(
            "max_combined_pixels", MAX_COMBINED_VIRTUAL_PIXELS
        ),
        "operating_mode": None,
        "production_mode": False,
        "management_locked": False,
        "unlock_window_open": False,
        "unlock_remaining_seconds": 0,
        "telemetry_target": "0.0.0.0" if supported else None,
        "telemetry_configured": False,
    }


def _management_token_state(node_report):
    if not node_report:
        return None
    match = MANAGEMENT_TOKEN_RE.search(str(node_report))
    if not match:
        return None
    version = int(match.group(1))
    mode_code = match.group(2)
    production = mode_code == "L"
    return {
        "management": True,
        "management_protocol_version": version,
        "operating_mode": "production" if production else "prototype",
        "production_mode": production,
        "management_locked": production,
    }


def _slot_index(name=None, physical_slot=None, fallback=0):
    try:
        slot = int(physical_slot)
        if 0 <= slot < OUTPUT_SLOT_COUNT:
            return slot
    except (TypeError, ValueError):
        pass
    label = str(name or "")
    if label.startswith("A") and label[1:].isdigit():
        slot = int(label[1:])
        if 0 <= slot < OUTPUT_SLOT_COUNT:
            return slot
    return int(fallback)


def _enum_name(value, names):
    return names[value]


def _coerce_enum(enum_type, value, by_name, field_name):
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        key = value.strip().lower()
        if key in by_name:
            return by_name[key]
    try:
        return enum_type(int(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field_name}") from exc


def _output_type_for_descriptor(descriptor):
    return BUILTIN_TYPE_BY_DESCRIPTOR.get(descriptor, CUSTOM_OUTPUT_TYPE)


def _descriptor_layout_name(descriptor):
    return _enum_name(descriptor.layout, LAYOUT_NAMES)


def _legacy_layout_for_descriptor(descriptor):
    if not descriptor.enabled:
        return "none"
    if descriptor.layout == Layout.GRID:
        return "grid"
    return "linear"


def _grid_shape_for_descriptor(descriptor):
    if descriptor.layout != Layout.GRID or not descriptor.enabled:
        return None
    return [descriptor.columns, descriptor.rows]


def _output_record_from_descriptor(
    descriptor,
    *,
    slot,
    universe=0,
    prior=None,
    grid_rotation=None,
):
    prior = prior or {}
    output_type = _output_type_for_descriptor(descriptor)
    if grid_rotation is None:
        grid_rotation = prior.get("grid_rotation", 0)
    grid_rotation = int(grid_rotation or 0)
    return {
        "name": f"A{slot}",
        "physical_slot": slot,
        "type": output_type,
        "enabled": bool(descriptor.enabled),
        "count": descriptor.physical_pixels,
        "physical_pixels": descriptor.physical_pixels,
        "layout": _legacy_layout_for_descriptor(descriptor),
        "descriptor_layout": _descriptor_layout_name(descriptor),
        "grid": _grid_shape_for_descriptor(descriptor),
        "rows": descriptor.rows,
        "columns": descriptor.columns,
        "traversal_axis": _enum_name(descriptor.traversal_axis, TRAVERSAL_AXIS_NAMES),
        "scan_pattern": _enum_name(descriptor.scan_pattern, SCAN_PATTERN_NAMES),
        "start_corner": _enum_name(descriptor.start_corner, START_CORNER_NAMES),
        "grid_order": (
            _enum_name(descriptor.scan_pattern, SCAN_PATTERN_NAMES)
            if descriptor.layout == Layout.GRID and descriptor.enabled
            else "progressive"
        ),
        "grid_rotation": grid_rotation,
        "virtual_pixels": descriptor.virtual_pixels,
        "universe": int(universe),
    }


def _descriptor_from_output_dict(output):
    if not isinstance(output, dict):
        raise ValueError("output descriptor must be a dict")
    output_type = output.get("type")
    if output_type in OUTPUT_TYPES:
        return descriptor_from_legacy(
            LOOK_OUTPUT_TYPES.index(output_type),
            output.get("virtual_pixels"),
        )
    enabled = bool(
        output.get("enabled")
        if output.get("enabled") is not None
        else (
            output.get("type") != "none"
            and int(output.get("physical_pixels") or output.get("count") or 0) > 0
        )
    )
    if not enabled:
        return OFF_DESCRIPTOR
    layout = _coerce_enum(
        Layout,
        output.get("descriptor_layout") or output.get("layout") or "off",
        LAYOUT_BY_NAME,
        "layout",
    )
    physical_pixels = int(output.get("physical_pixels") or output.get("count") or 0)
    grid = output.get("grid") if isinstance(output.get("grid"), (list, tuple)) else None
    rows = int(output.get("rows") or (grid[1] if grid and len(grid) > 1 else 0) or 0)
    columns = int(
        output.get("columns") or (grid[0] if grid and len(grid) > 0 else 0) or 0
    )
    virtual_pixels = int(output.get("virtual_pixels") or 0)
    descriptor = OutputDescriptor(
        True,
        physical_pixels,
        layout,
        rows if layout == Layout.GRID else 0,
        columns if layout == Layout.GRID else 0,
        _coerce_enum(
            TraversalAxis,
            output.get("traversal_axis", "row_major"),
            TRAVERSAL_AXIS_BY_NAME,
            "traversal_axis",
        ),
        _coerce_enum(
            ScanPattern,
            output.get("scan_pattern", output.get("grid_order", "progressive")),
            SCAN_PATTERN_BY_NAME,
            "scan_pattern",
        ),
        _coerce_enum(
            StartCorner,
            output.get("start_corner", "top_left"),
            START_CORNER_BY_NAME,
            "start_corner",
        ),
        virtual_pixels,
    )
    descriptor.validate()
    return descriptor


def _build_output_record(output, fallback_slot=0):
    slot = _slot_index(
        output.get("name"),
        output.get("physical_slot"),
        fallback=fallback_slot,
    )
    descriptor = _descriptor_from_output_dict(output)
    universe = output.get("universe", slot)
    return _output_record_from_descriptor(
        descriptor,
        slot=slot,
        universe=universe,
        prior=output,
        grid_rotation=output.get("grid_rotation", 0),
    )


def _descriptor_template_to_descriptor(template):
    if isinstance(template, OutputDescriptor):
        template.validate()
        return template
    normalized = normalize_output_descriptor_template(template)
    return _descriptor_from_output_dict({
        **normalized,
        "type": CUSTOM_OUTPUT_TYPE,
        "descriptor_layout": normalized.get("layout"),
    })


def _apply_descriptor_wiring(send_pixels, output):
    grid = output.get("grid")
    if not grid:
        return list(send_pixels)
    cols, rows = grid
    pixels = list(send_pixels)
    rotation = int(output.get("grid_rotation", 0) or 0)
    if rotation:
        pixels = apply_grid_rotation(pixels, cols, rows, rotation)
    matrix = [
        pixels[row * cols:(row + 1) * cols]
        for row in range(rows)
    ]
    if len(matrix) != rows or any(len(row) != cols for row in matrix):
        return pixels

    if output.get("start_corner") in ("bottom_left", "bottom_right"):
        matrix = list(reversed(matrix))
    if output.get("start_corner") in ("top_right", "bottom_right"):
        matrix = [list(reversed(row)) for row in matrix]

    serpentine = output.get("scan_pattern") == "serpentine"
    by_column = output.get("traversal_axis") == "column_major"
    ordered = []
    if by_column:
        for col in range(cols):
            column = [matrix[row][col] for row in range(rows)]
            if serpentine and (col % 2 == 1):
                column.reverse()
            ordered.extend(column)
    else:
        for row_index, row in enumerate(matrix):
            row_pixels = list(row)
            if serpentine and (row_index % 2 == 1):
                row_pixels.reverse()
            ordered.extend(row_pixels)
    return ordered


def _management_error_result(error):
    for error_type, (error_code, http_status) in MANAGEMENT_ERROR_DETAILS.items():
        if isinstance(error, error_type):
            return {
                "ok": False,
                "error": str(error),
                "error_code": error_code,
                "http_status": http_status,
            }
    if isinstance(error, ValueError):
        return {
            "ok": False,
            "error": str(error),
            "error_code": "InvalidPayload",
            "http_status": 400,
        }
    if isinstance(error, OSError):
        return {
            "ok": False,
            "error": str(error),
            "error_code": "TransportError",
            "http_status": 502,
        }
    raise TypeError(f"unsupported management error type: {type(error).__name__}")


def _normalize_show_info_value(value):
    return show_info_store.normalize_show_info_value(value)


def _show_info_storage_path(dev=None, is_radius=None):
    if is_radius is None and isinstance(dev, dict):
        is_radius = dev.get("is_radius") or (
            (dev.get("capabilities") or {}).get("device_class") == "radius"
        )
    return show_info_store.storage_path_for_device(bool(is_radius))


def _show_info_from_saved(saved):
    return show_info_store.show_info_from_saved(saved)


def _apply_saved_show_info(dev, saved):
    character_name, performer_name = _show_info_from_saved(saved)
    if character_name and not dev.get("character_name"):
        dev["character_name"] = character_name
    if performer_name and not dev.get("performer_name"):
        dev["performer_name"] = performer_name


def _preferred_device_name(dev, node_info=None, saved_name=None):
    return show_info_store.preferred_device_name(
        (node_info or {}).get("short_name"),
        saved_name if saved_name is not None else (dev or {}).get("name"),
        fallback="Radius" if (dev or {}).get("is_radius") else "Node",
    )


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
    return show_info_store.device_show_info_map_from_data(data)


def _show_info_entry(device_name, character_name, performer_name):
    return show_info_store.show_info_entry(device_name, character_name, performer_name)


def _lookup_device_show_info(ip=None, device_name=None, is_radius=False):
    return show_info_store.lookup_device_show_info(
        _show_info_storage_path(is_radius=is_radius), ip, device_name)


def _persist_device_show_info(ip, device_name, character_name, performer_name, is_radius=False):
    show_info_store.persist_device_show_info(
        _show_info_storage_path(is_radius=is_radius),
        ip,
        device_name,
        character_name,
        performer_name,
    )


def _migrate_device_show_info_key(old_ip, new_ip, device_name=None, is_radius=False):
    show_info_store.migrate_device_show_info_key(
        _show_info_storage_path(is_radius=is_radius),
        old_ip,
        new_ip,
        device_name,
    )


def _show_info_from_node(node_info):
    return show_info_store.show_info_from_node(node_info)


def _merge_show_info_fields(character_name, performer_name, ip=None, device_name=None, is_radius=False):
    return show_info_store.merge_show_info_fields(
        _show_info_storage_path(is_radius=is_radius),
        character_name,
        performer_name,
        ip,
        device_name,
    )


def _apply_persisted_show_info(dev, node_info=None):
    show_info_store.apply_persisted_show_info(
        _show_info_storage_path(dev),
        dev,
        node_info,
    )


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
                "physical_slot": output.get("physical_slot"),
                "type": output.get("type", "long_strip"),
                "enabled": output.get("enabled"),
                "physical_pixels": output.get("physical_pixels", output.get("count", 0)),
                "layout": output.get("layout", "none"),
                "descriptor_layout": output.get("descriptor_layout"),
                "rows": output.get("rows"),
                "columns": output.get("columns"),
                "traversal_axis": output.get("traversal_axis"),
                "scan_pattern": output.get("scan_pattern"),
                "start_corner": output.get("start_corner"),
                "universe": output.get("universe", 0),
                "grid_order": output.get("grid_order", "progressive"),
                "grid_rotation": output.get("grid_rotation", 0),
                "virtual_pixels": output.get("virtual_pixels"),
            })
        saved_devices.append({
            "ip": d["ip"],
            "name": d["name"],
            "mac": d.get("mac"),
            "device_uid": d.get("device_uid"),
            "is_radius": bool(d.get("is_radius")),
            "hardware_profile": d.get("hardware_profile", "unknown"),
            "hardware_label": d.get("hardware_label", "Unknown hardware"),
            "firmware_version": d.get("firmware_version"),
            "capabilities": _normalize_device_capabilities(d.get("capabilities")),
            "ip_mode": d.get("ip_mode", "unknown"),
            "static_ip": d.get("static_ip"),
            "gateway": d.get("gateway"),
            "subnet": d.get("subnet"),
            "receive_mode": d.get("receive_mode", "combined"),
            "base_universe": d.get("base_universe", 0),
            "management_supported": bool(d.get("management_supported")),
            "management_protocol": d.get("management_protocol"),
            "management_protocol_version": d.get("management_protocol_version"),
            "max_pixels_per_port": d.get("max_pixels_per_port", MAX_PHYSICAL_PIXELS),
            "max_combined_pixels": d.get(
                "max_combined_pixels", MAX_COMBINED_VIRTUAL_PIXELS),
            "operating_mode": d.get("operating_mode"),
            "production_mode": bool(d.get("production_mode")),
            "management_locked": bool(d.get("management_locked")),
            "unlock_window_open": bool(d.get("unlock_window_open")),
            "unlock_remaining_seconds": int(d.get("unlock_remaining_seconds") or 0),
            "telemetry_target": d.get("telemetry_target"),
            "telemetry_configured": bool(d.get("telemetry_configured")),
            "character_name": _normalize_show_info_value(d.get("character_name")),
            "performer_name": _normalize_show_info_value(d.get("performer_name")),
            "outputs": saved_outputs,
        })
    data["devices"] = saved_devices
    data["device_show_info"] = info_map
    radius_data = show_info_store.read_state_data(show_info_store.radius_state_path())
    radius_info_map = show_info_store.device_show_info_map_from_data(radius_data)
    for d in devices:
        ip = d.get("ip")
        if not ip:
            continue
        entry = _show_info_entry(
            d.get("name"),
            d.get("character_name"),
            d.get("performer_name"),
        )
        if d.get("is_radius"):
            radius_info_map[ip] = entry
        else:
            info_map[ip] = entry
    data["device_show_info"] = info_map
    radius_data["device_show_info"] = radius_info_map
    _write_state_data(data)
    show_info_store.write_state_data(show_info_store.radius_state_path(), radius_data)


def _load_devices():
    try:
        with open(_state_file(), "r") as f:
            data = json.load(f)
        return data.get("devices", [])
    except (OSError, json.JSONDecodeError):
        return []


def _load_legacy_radius_devices():
    """Device list saved by a standalone RadiusCentral backend, if any.

    The unified backend keeps its device list in the primus state file, but
    a fleet configured through standalone RadiusCentral lives in the radius
    state file's own "devices" list. Read-only here — the unified backend
    never writes that list back.
    """
    try:
        data = show_info_store.read_state_data(show_info_store.radius_state_path())
    except Exception:
        return []
    devices = data.get("devices", []) if isinstance(data, dict) else []
    return devices if isinstance(devices, list) else []


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
    management = _management_token_state(node_info.get("node_report", ""))
    if management:
        capabilities["management"] = True
        capabilities["management_protocol_version"] = management["management_protocol_version"]
        capabilities["max_pixels_per_port"] = MAX_PHYSICAL_PIXELS
        capabilities["max_combined_pixels"] = MAX_COMBINED_VIRTUAL_PIXELS
    if node_info.get("firmware_version") is not None:
        capabilities["firmware_version"] = node_info.get("firmware_version")
    for key in ("ip_mode", "static_ip", "gateway", "subnet"):
        if node_info.get(key) is not None:
            capabilities[key] = node_info.get(key)
    return _normalize_device_capabilities(capabilities)


def _is_radius_capabilities(capabilities):
    caps = capabilities or {}
    return caps.get("device_class") == "radius" or caps.get("profile") == "pvrad1"


def _promote_device_to_radius(dev):
    dev["is_radius"] = True
    dev.pop("sender", None)
    dev.pop("outputs", None)
    dev.pop("base_universe", None)
    dev.pop("receive_mode", None)
    dev.setdefault("current_track", "")
    dev.setdefault("playback_state", 0)


def _apply_network_capabilities_to_device(dev, capabilities, fallback_ip=None):
    _apply_lane_ports_to_device(dev, capabilities)
    dev["ip_mode"] = capabilities.get("ip_mode", "unknown")
    static_ip = capabilities.get("static_ip")
    if dev["ip_mode"] == "static" and not static_ip:
        static_ip = fallback_ip
    dev["static_ip"] = static_ip
    dev["gateway"] = capabilities.get("gateway")
    dev["subnet"] = capabilities.get("subnet")


def _apply_management_state_to_device(dev, node_info=None, capabilities=None):
    node_info = node_info or {}
    caps = _normalize_device_capabilities(capabilities or dev.get("capabilities"))
    defaults = _management_state_defaults(caps)
    token_state = _management_token_state(node_info.get("node_report", ""))
    if token_state:
        defaults.update({
            "management_supported": True,
            "management_protocol": MANAGEMENT_PROTOCOL_NAME,
            "management_protocol_version": token_state["management_protocol_version"],
            "operating_mode": token_state["operating_mode"],
            "production_mode": token_state["production_mode"],
            "management_locked": token_state["management_locked"],
        })
    for key in (
        "management_supported",
        "management_protocol",
        "management_protocol_version",
        "max_pixels_per_port",
        "max_combined_pixels",
    ):
        dev[key] = defaults[key]
    for key, value in defaults.items():
        dev.setdefault(key, value)
    for key in defaults:
        if node_info.get(key) is not None:
            dev[key] = node_info.get(key)
    if dev.get("telemetry_target") == "0.0.0.0":
        dev["telemetry_configured"] = False
    elif dev.get("telemetry_target"):
        dev["telemetry_configured"] = bool(node_info.get("telemetry_configured", True))


def _output_configs_from_node(node_info):
    explicit_outputs = node_info.get("outputs")
    if isinstance(explicit_outputs, list):
        output_cfgs = []
        for idx, output in enumerate(explicit_outputs):
            if not isinstance(output, dict):
                continue
            output_type = output.get("type", "long_strip")
            cfg = {
                "name": output.get("name", f"A{idx}"),
                "type": output_type,
                "physical_slot": output.get("physical_slot"),
            }
            for key in (
                "enabled",
                "physical_pixels",
                "layout",
                "descriptor_layout",
                "rows",
                "columns",
                "traversal_axis",
                "scan_pattern",
                "start_corner",
            ):
                if key in output:
                    cfg[key] = output.get(key)
            if "universe" in output:
                cfg["universe"] = output.get("universe", idx)
            if "grid_order" in output:
                cfg["grid_order"] = output.get("grid_order")
            if "grid_rotation" in output:
                cfg["grid_rotation"] = output.get("grid_rotation")
            if "virtual_pixels" in output:
                cfg["virtual_pixels"] = output.get("virtual_pixels")
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
        mode = "combined"
    if base is None:
        base = fallback_base
    return mode, int(base)


def _combined_pixel_total(outputs):
    total = 0
    for output in outputs:
        if output.get("type") == "none" or int(output.get("count") or 0) <= 0:
            continue
        total += resolve_virtual_pixels(output)
    return total


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
    for fallback_slot, output in enumerate(outputs):
        name = str(output.get("name") or "")
        slot = int(name[1:]) if name.startswith("A") and name[1:].isdigit() else fallback_slot
        if receive_mode == "combined":
            output["universe"] = base_u
        else:
            output["universe"] = base_u + slot


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
        virtual = resolve_virtual_pixels(output)
        if virtual <= 0:
            continue
        info.append((output["universe"], virtual))
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
            virtual = resolve_virtual_pixels(output)
            if virtual <= 0:
                continue
            data = frame_buffers.get(oi)
            if data is None:
                combined.extend(bytes(virtual * 3))
            else:
                transport = transport_rgb_bytes(output, rgb_bytes=data)
                expected = virtual * 3
                if len(transport) >= expected:
                    combined.extend(transport[:expected])
                else:
                    combined.extend(transport)
                    combined.extend(bytes(expected - len(transport)))
        if combined:
            send_queue.append(
                (di, sender, dev.get("base_universe", 0), bytes(combined)))
        return

    for oi, data in frame_buffers.items():
        if oi >= len(outputs):
            continue
        output = outputs[oi]
        transport = transport_rgb_bytes(output, rgb_bytes=data)
        if transport:
            send_queue.append((di, sender, output["universe"], transport))


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


def _serialize_output_json(output):
    return {
        "name": output.get("name", "A0"),
        "physical_slot": _slot_index(
            output.get("name"), output.get("physical_slot"), fallback=0),
        "type": output.get("type", "none"),
        "enabled": bool(output.get("enabled")),
        "count": int(output.get("count") or 0),
        "physical_pixels": int(
            output.get("physical_pixels", output.get("count") or 0) or 0),
        "layout": output.get("layout", "none"),
        "descriptor_layout": output.get(
            "descriptor_layout", "off" if output.get("type") == "none" else None),
        "grid": list(output.get("grid")) if output.get("grid") else None,
        "rows": int(output.get("rows") or 0),
        "columns": int(output.get("columns") or 0),
        "traversal_axis": output.get("traversal_axis", "row_major"),
        "scan_pattern": output.get("scan_pattern", output.get("grid_order", "progressive")),
        "start_corner": output.get("start_corner", "top_left"),
        "virtual_pixels": resolve_virtual_pixels(output),
        "universe": int(output.get("universe") or 0),
        "grid_order": output.get("grid_order", "progressive"),
        "grid_rotation": int(output.get("grid_rotation") or 0),
    }


def _device_flash_entries(dev, rgb_triplet):
    """Build (universe, bytes) entries for a solid-color flash."""
    outputs = dev.get("outputs", [])
    receive_mode = dev.get("receive_mode", "split")
    if receive_mode == "combined":
        combined = bytearray()
        for output in outputs:
            virtual = resolve_virtual_pixels(output)
            if virtual <= 0:
                continue
            combined.extend(rgb_triplet * virtual)
        if not combined:
            return []
        return [(dev.get("base_universe", 0), bytes(combined))]

    entries = []
    for output in outputs:
        virtual = resolve_virtual_pixels(output)
        if virtual <= 0:
            continue
        entries.append((output["universe"], rgb_triplet * virtual))
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

    def __init__(self, fps_listener, monitor_only=False):
        self.lock = threading.Lock()
        self.render_event = threading.Event()
        self.performance = PerformanceStats()
        self.running = True
        self.fps = DEFAULT_FPS
        self.fps_listener = fps_listener
        self.start_time = time.monotonic()
        self.last_tick = self.start_time
        self.devices = []
        self.monitor_only = bool(monitor_only)
        self.playback_source = self.SOURCE_IDLE
        self.artnet_source_ip = None
        self.output_preset_store = OutputPresetStore()

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
        radius_saved = _load_legacy_radius_devices()
        if not saved and not radius_saved:
            return
        from artnet import discover_artnet_nodes
        known_ips = []
        seen_ips = set()
        for device in list(saved) + list(radius_saved):
            for ip in (device.get("ip"), device.get("static_ip")):
                if ip and ip not in seen_ips:
                    known_ips.append(ip)
                    seen_ips.add(ip)
        nodes = discover_artnet_nodes(known_ips=known_ips, timeout=3.5)
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
                result = self.add_device_from_node(node, auto_save=False)
                dev = self.devices[result["device_index"]]
                dev["name"] = _preferred_device_name(dev, node, sd.get("name"))
                _apply_saved_show_info(dev, sd)
                _apply_persisted_show_info(dev, node)
                if node.get("ip") != ip:
                    refreshed = True
            else:
                # Add offline device with saved name
                result = self.add_device_from_node({
                    "ip": ip,
                    "mac": sd.get("mac"),
                    "device_uid": sd.get("device_uid"),
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
                    "management_supported": sd.get("management_supported"),
                    "management_protocol": sd.get("management_protocol"),
                    "management_protocol_version": sd.get(
                        "management_protocol_version"),
                    "max_pixels_per_port": sd.get("max_pixels_per_port"),
                    "max_combined_pixels": sd.get("max_combined_pixels"),
                    "operating_mode": sd.get("operating_mode"),
                    "production_mode": sd.get("production_mode"),
                    "management_locked": sd.get("management_locked"),
                    "unlock_window_open": sd.get("unlock_window_open"),
                    "unlock_remaining_seconds": sd.get(
                        "unlock_remaining_seconds"),
                    "telemetry_target": sd.get("telemetry_target"),
                    "telemetry_configured": sd.get("telemetry_configured"),
                    "character_name": sd.get("character_name", ""),
                    "performer_name": sd.get("performer_name", ""),
                    "outputs": sd.get("outputs"),
                }, auto_save=False)
                _apply_saved_show_info(self.devices[result["device_index"]], sd)

        # Devices saved by a standalone RadiusCentral live in the radius
        # state file; fold them in so the unified backend starts with the
        # same fleet RadiusCentral already knew about.
        for sd in radius_saved:
            ip = sd.get("ip")
            if not ip or any(d["ip"] == ip for d in self.devices):
                continue
            node = node_map.get(ip) or nodes_by_name.get(sd.get("name"))
            if node:
                self.add_device_from_node(node, auto_save=False)
                continue
            capabilities = dict(sd.get("capabilities") or {})
            if capabilities.get("device_class") != "radius":
                capabilities.setdefault("profile", "pvrad1")
                capabilities["device_class"] = "radius"
            self.add_device_from_node({
                "ip": ip,
                "mac": sd.get("mac"),
                "device_uid": sd.get("device_uid"),
                "short_name": sd.get("name", ip),
                "long_name": "",
                "num_ports": 0,
                "universes": [],
                "hardware_profile": sd.get("hardware_profile", "v1"),
                "hardware_label": sd.get("hardware_label", "V1 Huzzah32"),
                "firmware_version": sd.get("firmware_version"),
                "capabilities": capabilities,
                "ip_mode": sd.get("ip_mode"),
                "static_ip": sd.get("static_ip"),
                "gateway": sd.get("gateway"),
                "subnet": sd.get("subnet"),
                "character_name": sd.get("character_name", ""),
                "performer_name": sd.get("performer_name", ""),
            }, auto_save=False)

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
        for ip in show_info_store.device_show_info_map_from_data(
                show_info_store.read_state_data(show_info_store.radius_state_path())):
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
                # Radius records never carry an ArtNetSender on the unified
                # backend — a bare dev["sender"] here 500s every request that
                # syncs the Art-Net source once a Radius device is known.
                sender = dev.get("sender")
                if sender is not None and hasattr(sender, "set_source_ip"):
                    sender.set_source_ip(source_ip)

    def refresh_after_firmware_upload(self, overrides=None):
        """Re-discover devices after firmware upload and push name overrides over Art-Net."""
        from artnet import discover_artnet_nodes, sync_device_name_to_receiver, sync_show_info_to_device
        overrides = overrides or {}
        device_name = overrides.get("device_name")
        character_name = overrides.get("character_name")
        performer_name = overrides.get("performer_name")
        has_name_overrides = any((device_name, character_name, performer_name))

        time.sleep(8)

        interface = None
        try:
            from network_settings import get_artnet_interface
            interface = get_artnet_interface()
        except Exception:
            pass
        known_ips = self.discovery_targets()
        nodes = discover_artnet_nodes(
            known_ips=known_ips,
            timeout=3.0,
            interface=interface,
        )
        # Only devices whose discovered identity already matches the flash
        # overrides may receive the override push — the freshly flashed
        # node reports the new names on its first ArtPollReply. Pushing to
        # every online device smears one performer's names across the fleet
        # (the regression restore_show_info_from_xlsx.py exists to repair).
        override_ips = {
            node.get("ip")
            for node in nodes
            if node.get("ip")
            and show_info_store.node_matches_firmware_name_overrides(node, overrides)
        }
        self.refresh_devices_from_nodes(nodes)

        if not has_name_overrides or not override_ips:
            return

        with self.lock:
            for dev in self.devices:
                ip = dev.get("ip")
                if not ip or ip not in override_ips:
                    continue
                if device_name:
                    sync_device_name_to_receiver(
                        ip, device_name, source_ip=self.artnet_source_ip,
                        dest_port=device_setup_port(dev))
                    dev["name"] = str(device_name)[:17]
                char = dev.get("character_name", "")
                perf = dev.get("performer_name", "")
                if character_name is not None:
                    char = show_info_store.normalize_show_info_value(character_name)
                    dev["character_name"] = char
                if performer_name is not None:
                    perf = show_info_store.normalize_show_info_value(performer_name)
                    dev["performer_name"] = perf
                if character_name is not None or performer_name is not None:
                    sync_show_info_to_device(
                        ip, char, perf, source_ip=self.artnet_source_ip,
                        dest_port=device_setup_port(dev))
                _persist_device_show_info(
                    ip,
                    dev.get("name"),
                    dev.get("character_name", ""),
                    dev.get("performer_name", ""),
                    is_radius=dev.get("is_radius"),
                )
            _save_devices(self.devices)

    def refresh_devices_from_nodes(self, nodes, auto_save=True):
        """Refresh matching existing devices from discovery without adding new ones."""
        refreshed = []
        groups_changed = False
        for node_info in nodes or []:
            with self.lock:
                idx = self._find_existing_device_index_unlocked(node_info)
                if idx is None:
                    continue
                device_ref = self.devices[idx]
                device_lock = self._ensure_device_management_lock_unlocked(device_ref)
            with device_lock:
                with self.lock:
                    idx = self._find_device_index_by_ref_unlocked(device_ref)
                    if idx is None:
                        continue
                    dev = self.devices[idx]
                    old_ip = dev.get("ip")
                    new_ip = node_info.get("ip")
                    ip_changed = bool(new_ip and new_ip != old_ip)
                    if ip_changed:
                        dev["ip"] = new_ip
                        sender = dev.get("sender")
                        if sender is not None:
                            sender.ip = new_ip
                        groups_changed = (
                            self._replace_device_ip_references_unlocked(old_ip, new_ip)
                            or groups_changed
                        )
                    refresh_state = self._refresh_device_from_node_unlocked(dev, node_info)
                if refresh_state["needs_management_refresh"]:
                    self._query_management_config_for_locked_device(
                        device_ref,
                        auto_save=False,
                        on_error_unlocked=lambda current_dev, snapshot=refresh_state["authoritative_state"]: (
                            self._restore_authoritative_management_state_unlocked(
                                current_dev, snapshot)
                        ),
                        return_error=False,
                    )
                with self.lock:
                    idx = self._find_device_index_by_ref_unlocked(device_ref)
                    if idx is None:
                        continue
                    dev = self.devices[idx]
                    if refresh_state["updated"] or ip_changed:
                        refreshed.append({
                            "device_index": idx,
                            "name": dev.get("name"),
                            "old_ip": old_ip,
                            "ip": dev.get("ip"),
                        })
        with self.lock:
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
                    "mac": dev.get("mac"),
                    "device_uid": dev.get("device_uid") or "ip:{}".format(dev["ip"]),
                    "is_radius": bool(dev.get("is_radius")),
                    "is_audio": bool(dev.get("is_radius")),
                    "base_universe": dev.get("base_universe", 0),
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
                    "management_supported": bool(dev.get("management_supported")),
                    "management_protocol": dev.get("management_protocol"),
                    "management_protocol_version": dev.get(
                        "management_protocol_version"),
                    "max_pixels_per_port": dev.get(
                        "max_pixels_per_port", MAX_PHYSICAL_PIXELS),
                    "max_combined_pixels": dev.get(
                        "max_combined_pixels", MAX_COMBINED_VIRTUAL_PIXELS),
                    "operating_mode": dev.get("operating_mode"),
                    "production_mode": bool(dev.get("production_mode")),
                    "management_locked": bool(dev.get("management_locked")),
                    "unlock_window_open": bool(dev.get("unlock_window_open")),
                    "unlock_remaining_seconds": int(
                        dev.get("unlock_remaining_seconds") or 0),
                    "telemetry_target": dev.get("telemetry_target"),
                    "telemetry_configured": bool(dev.get("telemetry_configured")),
                    # Resolved, not raw: the UI prefills its lane editor from these
                    # and warns when Show has moved off 6454, so it needs the port
                    # actually in use rather than None for a node on defaults.
                    "port_show": device_show_port(dev, is_radius=dev.get("is_radius")),
                    "port_setup": device_setup_port(dev, is_radius=dev.get("is_radius")),
                    "port_watch": int(dev.get("port_watch") or FPS_LISTEN_PORT),
                    "outputs": [],
                    "descriptor_config": [],
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
                    for key in (
                        "protocol_version",
                        "sequence",
                        "uptime_seconds",
                        "status_flags",
                        "status_flag_wifi_connected",
                        "status_flag_static_ip",
                        "status_flag_output_power",
                        "status_flag_test_active",
                        "status_flag_telemetry_configured",
                        "status_flag_production",
                        "status_flag_unlock_window_open",
                        "status_flag_battery_valid",
                        "wifi_connected",
                        "output_power_enabled",
                        "test_mode_active",
                        "heartbeat_age_seconds",
                        "heartbeat_fresh",
                        "rendered_fps_x10",
                        "packet_rate_x10",
                        "rssi_dbm",
                        "telemetry_sequence_wraps",
                        "telemetry_packets_lost",
                        "telemetry_duplicate_packets",
                        "telemetry_out_of_order_packets",
                        "telemetry_reboot_count",
                        "telemetry_status_packets_accepted",
                        "telemetry_packet_loss_rate",
                        "telemetry_last_sequence_gap",
                        "management_locked",
                        "production_mode",
                        "operating_mode",
                        "unlock_window_open",
                        "unlock_remaining_seconds",
                        "telemetry_configured",
                    ):
                        if key in rx:
                            d[key] = rx.get(key)
                if dev.get("is_radius"):
                    if rx:
                        if "current_track" in rx:
                            d["current_track"] = rx.get("current_track") or ""
                        if "playback_state" in rx:
                            d["playback_state"] = rx.get("playback_state", 0)
                        # PRS-specific status (Radius firmware 4.16+)
                        for key in (
                            "sd_ready",
                            "ftp_running",
                            "audio_playing",
                            "audio_looping",
                            "marius_configured",
                            "marius_connected",
                        ):
                            if key in rx:
                                d[key] = rx.get(key)
                    out["devices"].append(d)
                    continue
                for o in dev.get("outputs", []):
                    serialized = _serialize_output_json(o)
                    d["outputs"].append(serialized)
                    d["descriptor_config"].append(serialized)
                out["devices"].append(d)
        lock_released = time.perf_counter()
        self.performance.observe_many((
            ("api_state_lock_wait_ms", (lock_acquired - lock_start) * 1000.0),
            ("api_state_lock_held_ms", (lock_released - lock_acquired) * 1000.0),
        ))
        return out

    def get_radius_json(self):
        """Radius-shaped view of the unified device list.

        Serves GET /api/state?product=radius on the shared backend. ALL
        devices are included so array indices stay aligned with the
        unified list (every frontend addresses devices by index); the
        RadiusCentral UI hides non-radius entries client-side.
        """
        full = self.get_json()
        devices = []
        for d in full.get("devices", []):
            item = {
                "name": d.get("name"),
                "character_name": d.get("character_name", ""),
                "performer_name": d.get("performer_name", ""),
                "ip": d.get("ip"),
                "mac": d.get("mac"),
                "device_uid": d.get("device_uid"),
                "connected": bool(d.get("connected")),
                "is_radius": bool(d.get("is_radius")),
                "is_audio": bool(d.get("is_radius")),
                "hardware_profile": d.get("hardware_profile"),
                "hardware_label": d.get("hardware_label"),
                "firmware_version": d.get("firmware_version"),
                "live_firmware_version": d.get("live_firmware_version"),
                "capabilities": d.get("capabilities") or {},
                "ip_mode": d.get("ip_mode"),
                "static_ip": d.get("static_ip"),
                "gateway": d.get("gateway"),
                "subnet": d.get("subnet"),
                "ip_config_pending": d.get("ip_config_pending"),
                "transport_error": d.get("transport_error"),
                "receiver_online": bool(d.get("receiver_online")),
                "telemetry_age_seconds": d.get("telemetry_age_seconds"),
                "battery_mv": d.get("battery_mv"),
                "battery_pct": d.get("battery_pct"),
                "battery_power_mode": d.get("battery_power_mode"),
                "battery_warning": d.get("battery_warning"),
                "port_show": d.get("port_show"),
                "port_setup": d.get("port_setup"),
                "port_watch": d.get("port_watch"),
                "current_track": d.get("current_track", ""),
                "playback_state": d.get("playback_state", 0),
            }
            if d.get("receiver_fps") is not None:
                item["fps"] = d.get("receiver_fps")
            if d.get("receiver_pkt_rate") is not None:
                item["pkt_rate"] = d.get("receiver_pkt_rate")
            for key in (
                "rssi_dbm",
                "uptime_seconds",
                "wifi_connected",
                "test_mode_active",
                "sd_ready",
                "ftp_running",
                "audio_playing",
                "audio_looping",
                "marius_configured",
                "marius_connected",
            ):
                if key in d:
                    item[key] = d.get(key)
            devices.append(item)
        return {
            "product": "radius",
            "products": ["primus", "radius"],
            "devices": devices,
        }

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
                    sender = dev.get("sender")
                    if sender is not None:
                        sender.ip = dev["ip"]
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
            sender = dev.get("sender")
            if sender is not None:
                sender.disconnect()
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
        dev["sender"].set_dest_port(device_show_port(dev))
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

    def _device_supports_management_unlocked(self, dev):
        if dev.get("is_radius"):
            return False
        caps = _normalize_device_capabilities(dev.get("capabilities"))
        return bool(caps.get("management"))

    def _device_management_status_unlocked(self, di):
        if not (0 <= di < len(self.devices)):
            return {"ok": False, "error": "invalid device index", "http_status": 400}
        dev = self.devices[di]
        if dev.get("is_radius"):
            return {
                "ok": False,
                "error": "Primus management is not available for Radius devices.",
                "error_code": "NotAvailable",
                "http_status": 409,
            }
        if self._device_supports_management_unlocked(dev):
            return {"ok": True, "device": dev.get("name")}
        return {
            "ok": False,
            "error": f'{dev.get("name", "Device")} does not advertise Primus management support.',
            "error_code": "UnsupportedOperation",
            "http_status": 409,
        }

    def _serialize_device_outputs_unlocked(self, dev):
        return [_serialize_output_json(output) for output in dev.get("outputs", [])]

    def _device_config_payload_unlocked(self, dev):
        return {
            "technical_name": dev.get("name", ""),
            "character_name": _normalize_show_info_value(dev.get("character_name")),
            "performer_name": _normalize_show_info_value(dev.get("performer_name")),
            "operating_mode": dev.get("operating_mode"),
            "management_locked": bool(dev.get("management_locked")),
            "unlock_window_open": bool(dev.get("unlock_window_open")),
            "unlock_remaining_seconds": int(dev.get("unlock_remaining_seconds") or 0),
            "receive_mode": dev.get("receive_mode", "split"),
            "base_universe": int(dev.get("base_universe") or 0),
            "telemetry_target": dev.get("telemetry_target") or "0.0.0.0",
            "telemetry_configured": bool(dev.get("telemetry_configured")),
            "ip_mode": dev.get("ip_mode", "unknown"),
            "ip": dev.get("static_ip") if dev.get("ip_mode") == "static" else dev.get("ip"),
            "gateway": dev.get("gateway"),
            "subnet": dev.get("subnet"),
            "outputs": self._serialize_device_outputs_unlocked(dev),
        }

    def _apply_management_config_to_device_unlocked(self, dev, config):
        receive_mode = "combined" if config.receive_mode == ReceiveMode.COMBINED else "split"
        dev["name"] = config.technical_name
        dev["character_name"] = _normalize_show_info_value(config.character_name)
        dev["performer_name"] = _normalize_show_info_value(config.performer_name)
        dev["receive_mode"] = receive_mode
        dev["base_universe"] = int(config.base_universe)
        if config.ip_mode == IpMode.STATIC:
            dev["ip_mode"] = "static"
            dev["static_ip"] = config.ip
            dev["gateway"] = config.gateway
            dev["subnet"] = config.subnet
        else:
            dev["ip_mode"] = "dhcp"
            dev["static_ip"] = None
            dev["gateway"] = None
            dev["subnet"] = None
        dev["ip_config_pending"] = None
        dev["management_supported"] = True
        dev["management_protocol"] = MANAGEMENT_PROTOCOL_NAME
        dev["management_protocol_version"] = 1
        dev["max_pixels_per_port"] = MAX_PHYSICAL_PIXELS
        dev["max_combined_pixels"] = MAX_COMBINED_VIRTUAL_PIXELS
        operating_mode = (
            "production" if config.operating_mode == OperatingMode.PRODUCTION else "prototype"
        )
        dev["operating_mode"] = operating_mode
        dev["production_mode"] = operating_mode == "production"
        dev["management_locked"] = dev["production_mode"]
        dev["unlock_window_open"] = bool(config.unlock_window_open)
        dev["unlock_remaining_seconds"] = int(config.unlock_remaining_seconds)
        dev["telemetry_target"] = config.telemetry_target
        dev["telemetry_configured"] = config.telemetry_target != "0.0.0.0"
        # Authoritative lane ports from GET_CONFIG v2 (never invent defaults over these).
        if getattr(config, "config_version", 1) >= 2:
            dev["port_show"] = int(config.port_show)
            dev["port_setup"] = int(config.port_setup)
            dev["port_watch"] = int(config.port_watch)
            caps = _normalize_device_capabilities(dev.get("capabilities"))
            caps["port_show"] = int(config.port_show)
            caps["port_setup"] = int(config.port_setup)
            caps["port_watch"] = int(config.port_watch)
            dev["capabilities"] = caps
            sender = dev.get("sender")
            if sender is not None:
                sender.set_dest_port(device_show_port(dev))
                sender.ip = dev.get("ip") or sender.ip
        existing_outputs = dev.get("outputs", [])
        outputs = []
        for slot in range(OUTPUT_SLOT_COUNT):
            prior = existing_outputs[slot] if slot < len(existing_outputs) else None
            outputs.append(_output_record_from_descriptor(
                config.outputs[slot],
                slot=slot,
                prior=prior,
                grid_rotation=(prior or {}).get("grid_rotation", 0),
            ))
        _apply_output_universes(outputs, receive_mode, config.base_universe)
        dev["outputs"] = outputs
        _persist_device_show_info(
            dev.get("ip"),
            dev.get("name"),
            dev.get("character_name", ""),
            dev.get("performer_name", ""),
        )

    def _snapshot_device_config_state_unlocked(self, dev):
        return {
            "ip": dev.get("ip"),
            "name": dev.get("name", ""),
            "character_name": _normalize_show_info_value(dev.get("character_name")),
            "performer_name": _normalize_show_info_value(dev.get("performer_name")),
            "operating_mode": dev.get("operating_mode"),
            "production_mode": bool(dev.get("production_mode")),
            "management_locked": bool(dev.get("management_locked")),
            "unlock_window_open": bool(dev.get("unlock_window_open")),
            "unlock_remaining_seconds": int(dev.get("unlock_remaining_seconds") or 0),
            "receive_mode": dev.get("receive_mode", "split"),
            "base_universe": int(dev.get("base_universe") or 0),
            "telemetry_target": dev.get("telemetry_target") or "0.0.0.0",
            "telemetry_configured": bool(dev.get("telemetry_configured")),
            "ip_mode": dev.get("ip_mode", "unknown"),
            "static_ip": dev.get("static_ip"),
            "gateway": dev.get("gateway"),
            "subnet": dev.get("subnet"),
            "ip_config_pending": dev.get("ip_config_pending"),
            "outputs": copy.deepcopy(dev.get("outputs", [])),
        }

    def _restore_authoritative_management_state_unlocked(self, dev, snapshot):
        for key, value in (snapshot or {}).items():
            dev[key] = copy.deepcopy(value)

    def _ensure_device_management_lock_unlocked(self, dev):
        lock = dev.get("_management_lock")
        if lock is None:
            lock = threading.Lock()
            dev["_management_lock"] = lock
        return lock

    def _find_device_index_by_ref_unlocked(self, device_ref):
        for idx, dev in enumerate(self.devices):
            if dev is device_ref:
                return idx
        return None

    def _locate_device_ref_unlocked(self, device_ref, expected_ip=None):
        idx = self._find_device_index_by_ref_unlocked(device_ref)
        if idx is None:
            return None, None, "removed"
        dev = self.devices[idx]
        if expected_ip is not None and dev.get("ip") != expected_ip:
            return idx, dev, "ip_changed"
        return idx, dev, None

    def _management_success_with_config(
        self, config, *, warning=None, readback_pending=False, extra=None
    ):
        result = {
            **_config_apply_result(True),
            "config": config,
        }
        if warning:
            result["warning"] = warning
        if readback_pending:
            result["readback_pending"] = True
        if extra:
            result.update(extra)
        return result

    def _management_conflict_result(self, message):
        return {
            "ok": False,
            "error": message,
            "error_code": "Conflict",
            "http_status": 409,
        }

    def _query_management_config_for_locked_device(
        self,
        device_ref,
        *,
        auto_save=True,
        on_error_unlocked=None,
        return_error=True,
    ):
        with self.lock:
            idx = self._find_device_index_by_ref_unlocked(device_ref)
            if idx is None:
                if return_error:
                    return self._management_conflict_result("device no longer exists")
                return None
            dev = self.devices[idx]
            target_ip = dev["ip"]
            source_ip = self.artnet_source_ip
            setup_port = device_setup_port(dev)
        try:
            result = get_primus_config(target_ip, source_ip=source_ip, dest_port=setup_port)
        except MANAGEMENT_CALL_ERRORS as error:
            with self.lock:
                idx, dev, change = self._locate_device_ref_unlocked(
                    device_ref, expected_ip=target_ip)
                if change is None:
                    if on_error_unlocked is not None:
                        on_error_unlocked(dev)
            if return_error:
                return _management_error_result(error)
            return None
        with self.lock:
            idx, dev, change = self._locate_device_ref_unlocked(
                device_ref, expected_ip=target_ip)
            if change is not None:
                if return_error:
                    return self._management_conflict_result(
                        "device changed before the refreshed configuration could be merged; retry the refresh"
                    )
                return None
            self._apply_management_config_to_device_unlocked(dev, result.config)
            self._clear_transport_error_unlocked(dev)
            if auto_save:
                _save_devices(self.devices)
            return self._management_success_with_config(
                self._device_config_payload_unlocked(dev))

    def _run_management_mutation_for_locked_device(
        self,
        device_ref,
        status_getter_unlocked,
        prepare_unlocked,
        send_call,
        apply_expected_unlocked,
        *,
        auto_save=True,
        skip_readback=False,
        success_extra=None,
        changed_warning=None,
    ):
        with self.lock:
            idx = self._find_device_index_by_ref_unlocked(device_ref)
            if idx is None:
                return self._management_conflict_result("device no longer exists")
            status = status_getter_unlocked(idx)
            if not status.get("ok"):
                return status
            dev = self.devices[idx]
            target_ip = dev["ip"]
            source_ip = self.artnet_source_ip
            setup_port = device_setup_port(dev)
            try:
                prepared = prepare_unlocked(dev)
                expected_snapshot = self._snapshot_device_config_state_unlocked(dev)
                apply_expected_unlocked(expected_snapshot, prepared, persist=False)
            except ValueError as error:
                return {"ok": False, "error": str(error), "http_status": 400}
        try:
            send_call(target_ip, source_ip, prepared, setup_port)
        except MANAGEMENT_CALL_ERRORS as error:
            return _management_error_result(error)
        if skip_readback:
            with self.lock:
                idx, dev, change = self._locate_device_ref_unlocked(
                    device_ref, expected_ip=target_ip)
                if change is None:
                    apply_expected_unlocked(dev, prepared, persist=True)
                    self._clear_transport_error_unlocked(dev)
                    if auto_save:
                        _save_devices(self.devices)
                    return self._management_success_with_config(
                        self._device_config_payload_unlocked(dev),
                        extra=success_extra,
                    )
            warning = changed_warning or (
                "Device acknowledged the management update, but the tracked device entry changed "
                "before the pending reconnect state could be saved locally. Refresh or discover "
                "again to reconcile."
            )
            return self._management_success_with_config(
                self._device_config_payload_unlocked(expected_snapshot),
                warning=warning,
                extra=success_extra,
            )
        try:
            readback = get_primus_config(target_ip, source_ip=source_ip, dest_port=setup_port)
        except MANAGEMENT_CALL_ERRORS as error:
            warning = (
                "Device acknowledged the management update, but follow-up config readback failed: "
                f"{error}. Local state was updated and will be reconciled on the next explicit "
                "refresh or discovery."
            )
            with self.lock:
                idx, dev, change = self._locate_device_ref_unlocked(
                    device_ref, expected_ip=target_ip)
                if change is None:
                    apply_expected_unlocked(dev, prepared, persist=True)
                    if auto_save:
                        _save_devices(self.devices)
                    return self._management_success_with_config(
                        self._device_config_payload_unlocked(dev),
                        warning=warning,
                        readback_pending=True,
                        extra=success_extra,
                    )
            changed_warning = changed_warning or (
                "Device acknowledged the management update, but the tracked device entry changed "
                "before local confirmation could be merged. Refresh or discover again to reconcile."
            )
            return self._management_success_with_config(
                self._device_config_payload_unlocked(expected_snapshot),
                warning=changed_warning,
                readback_pending=True,
                extra=success_extra,
            )
        with self.lock:
            idx, dev, change = self._locate_device_ref_unlocked(
                device_ref, expected_ip=target_ip)
            if change is not None:
                changed_warning = changed_warning or (
                    "Device acknowledged the management update, but the tracked device entry "
                    "changed before the authoritative readback could be merged. Refresh or "
                    "discover again to reconcile."
                )
                return self._management_success_with_config(
                    self._device_config_payload_unlocked(expected_snapshot),
                    warning=changed_warning,
                    readback_pending=True,
                    extra=success_extra,
                )
            self._apply_management_config_to_device_unlocked(dev, readback.config)
            self._clear_transport_error_unlocked(dev)
            if auto_save:
                _save_devices(self.devices)
            return self._management_success_with_config(
                self._device_config_payload_unlocked(dev),
                extra=success_extra,
            )

    def _apply_identity_fields_unlocked(
        self, dev, technical_name, character_name, performer_name, *, persist=False
    ):
        dev["name"] = technical_name
        dev["character_name"] = _normalize_show_info_value(character_name)
        dev["performer_name"] = _normalize_show_info_value(performer_name)
        if persist:
            _persist_device_show_info(
                dev.get("ip"),
                dev.get("name"),
                dev.get("character_name", ""),
                dev.get("performer_name", ""),
                is_radius=dev.get("is_radius"),
            )

    def _apply_output_descriptors_to_device_unlocked(self, dev, descriptors, *, persist=False):
        descriptors = tuple(descriptors)
        existing_outputs = dev.get("outputs", [])
        outputs = []
        for slot in range(OUTPUT_SLOT_COUNT):
            prior = existing_outputs[slot] if slot < len(existing_outputs) else None
            outputs.append(_output_record_from_descriptor(
                descriptors[slot],
                slot=slot,
                prior=prior,
                grid_rotation=(prior or {}).get("grid_rotation", 0),
            ))
        _apply_output_universes(
            outputs,
            dev.get("receive_mode", "split"),
            int(dev.get("base_universe") or 0),
        )
        dev["outputs"] = outputs

    def _apply_receive_config_to_device_unlocked(
        self, dev, receive_mode, base_universe, *, persist=False
    ):
        dev["receive_mode"] = receive_mode
        dev["base_universe"] = int(base_universe)
        _apply_output_universes(dev.get("outputs", []), receive_mode, int(base_universe))

    def _apply_telemetry_target_to_device_unlocked(self, dev, address, *, persist=False):
        dev["telemetry_target"] = address
        dev["telemetry_configured"] = address != "0.0.0.0"

    def _apply_operating_mode_to_device_unlocked(self, dev, mode, *, persist=False):
        operating_mode = "production" if mode == OperatingMode.PRODUCTION else "prototype"
        dev["operating_mode"] = operating_mode
        dev["production_mode"] = operating_mode == "production"
        dev["management_locked"] = dev["production_mode"]

    def _apply_boot_window_unlock_to_device_unlocked(self, dev, prepared, *, persist=False):
        dev["operating_mode"] = "prototype"
        dev["production_mode"] = False
        dev["management_locked"] = False
        dev["unlock_window_open"] = False
        dev["unlock_remaining_seconds"] = 0

    def _apply_ip_config_to_device_unlocked(self, dev, prepared, *, persist=False):
        if prepared["ip_mode"] == "static":
            dev["ip_mode"] = "static"
            dev["static_ip"] = prepared["static_ip"]
            dev["gateway"] = prepared["gateway"]
            dev["subnet"] = prepared["subnet"]
            dev["ip_config_pending"] = "static"
        else:
            dev["ip_mode"] = "dhcp"
            dev["static_ip"] = None
            dev["gateway"] = None
            dev["subnet"] = None
            dev["ip_config_pending"] = "dhcp"

    def _apply_type_to_device_output_unlocked(self, dev_output, new_type):
        typedef = OUTPUT_TYPES.get(new_type)
        if typedef is None:
            raise ValueError(f"Unknown output type: {new_type!r}")
        descriptor = BUILTIN_DESCRIPTOR_BY_TYPE[new_type]
        updated = _output_record_from_descriptor(
            descriptor,
            slot=_slot_index(
                dev_output.get("name"),
                dev_output.get("physical_slot"),
                fallback=0,
            ),
            universe=dev_output.get("universe", 0),
            prior=dev_output,
            grid_rotation=dev_output.get("grid_rotation", 0),
        )
        dev_output.clear()
        dev_output.update(updated)

    def _send_output_config(self, dev):
        if self._device_supports_management_unlocked(dev):
            return True, None
        caps = _normalize_device_capabilities(dev.get("capabilities"))
        if not caps.get("output_config"):
            return False, "output configuration is not advertised for this node"

        types = [o["type"] for o in dev.get("outputs", [])]
        if not types:
            return False, "device has no outputs to configure"
        if any(output_type not in OUTPUT_TYPES for output_type in types):
            return False, "custom output descriptors require Primus management"
        type_to_id = {name: i for i, name in enumerate(LOOK_OUTPUT_TYPES)}
        try:
            send_output_config(
                dev["ip"], types, type_to_id, source_ip=self.artnet_source_ip,
                dest_port=device_setup_port(dev))
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

    def _send_virtual_resolution(self, dev):
        if self._device_supports_management_unlocked(dev):
            return True, None
        caps = _normalize_device_capabilities(dev.get("capabilities"))
        if not caps.get("output_config"):
            return False, "output configuration is not advertised for this node"

        outputs = dev.get("outputs", [])
        if not outputs:
            return False, "device has no outputs to configure"
        virtual_counts = [resolve_virtual_pixels(o) for o in outputs]
        try:
            send_virtual_resolution(
                dev["ip"], virtual_counts, source_ip=self.artnet_source_ip,
                dest_port=device_setup_port(dev))
        except OSError as error:
            return False, self._transport_error_text(error)
        return True, None

    def set_device_virtual_resolution(self, di, oi, virtual_pixels=None,
                                      virtual_percent=None):
        device_ref = None
        with self.lock:
            status = self._device_capability_status_unlocked(di, "output_config")
            if not status["ok"]:
                return status
            dev = self.devices[di]
            if self._device_supports_management_unlocked(dev):
                device_ref = dev
                device_lock = self._ensure_device_management_lock_unlocked(dev)
            else:
                if not (0 <= oi < len(dev.get("outputs", []))):
                    return {"ok": False, "error": "invalid output index"}
                output = dev["outputs"][oi]
                physical = int(output.get("count") or 0)
                if physical <= 0 or output.get("type") == "none":
                    return {"ok": False, "error": "output is inactive"}

                if virtual_percent is not None:
                    try:
                        resolved = virtual_percent_to_count(physical, virtual_percent)
                    except (TypeError, ValueError):
                        return {"ok": False, "error": "virtual_percent must be 1-100"}
                elif virtual_pixels is not None:
                    try:
                        resolved = int(virtual_pixels)
                    except (TypeError, ValueError):
                        return {"ok": False, "error": "virtual_pixels must be an integer"}
                else:
                    return {
                        "ok": False,
                        "error": "virtual_pixels or virtual_percent is required",
                    }

                if resolved < 1 or resolved > physical:
                    return {
                        "ok": False,
                        "error": f"virtual_pixels must be 1-{physical}",
                    }

        if device_ref is not None:
            def prepare_unlocked(current_dev):
                if not (0 <= oi < len(current_dev.get("outputs", []))):
                    raise ValueError("invalid output index")
                output = current_dev["outputs"][oi]
                physical = int(output.get("count") or 0)
                if physical <= 0 or output.get("type") == "none":
                    raise ValueError("output is inactive")
                if virtual_percent is not None:
                    try:
                        resolved = virtual_percent_to_count(physical, virtual_percent)
                    except (TypeError, ValueError):
                        raise ValueError("virtual_percent must be 1-100")
                elif virtual_pixels is not None:
                    try:
                        resolved = int(virtual_pixels)
                    except (TypeError, ValueError):
                        raise ValueError("virtual_pixels must be an integer")
                else:
                    raise ValueError("virtual_pixels or virtual_percent is required")
                if resolved < 1 or resolved > physical:
                    raise ValueError(f"virtual_pixels must be 1-{physical}")
                descriptors = [
                    _descriptor_from_output_dict(item)
                    for item in current_dev.get("outputs", [])
                ]
                current = descriptors[oi]
                descriptors[oi] = OutputDescriptor(
                    current.enabled,
                    current.physical_pixels,
                    current.layout,
                    current.rows,
                    current.columns,
                    current.traversal_axis,
                    current.scan_pattern,
                    current.start_corner,
                    resolved,
                )
                validate_receive_config(
                    ReceiveMode.COMBINED
                    if current_dev.get("receive_mode") == "combined"
                    else ReceiveMode.SPLIT,
                    descriptors,
                )
                return {"descriptors": tuple(descriptors)}

            with device_lock:
                return self._run_management_mutation_for_locked_device(
                    device_ref,
                    lambda idx: self._device_capability_status_unlocked(idx, "output_config"),
                    prepare_unlocked,
                    lambda ip, source_ip, prepared, dest_port=None: set_primus_output_descriptors(
                        ip, prepared["descriptors"], source_ip=source_ip, dest_port=dest_port),
                    lambda target, prepared, persist=False: self._apply_output_descriptors_to_device_unlocked(
                        target, prepared["descriptors"], persist=persist),
                )

        with self.lock:
            prior = output.get("virtual_pixels")
            output["virtual_pixels"] = resolved
            valid, err = _validate_receive_mode_for_device(
                dev.get("receive_mode", "split"), dev.get("outputs", []))
            if not valid:
                output["virtual_pixels"] = prior
                return {"ok": False, "error": err}

            was_connected = dev["sender"].connected
            if was_connected or self.monitor_only:
                try:
                    if not self._ensure_sender_connected_unlocked(dev):
                        output["virtual_pixels"] = prior
                        return {
                            "ok": False,
                            "error": dev.get("transport_error") or "sender connection failed",
                        }
                    config_ok, config_error = self._send_virtual_resolution(dev)
                    if not config_ok:
                        output["virtual_pixels"] = prior
                        return {
                            "ok": False,
                            "error": config_error or "virtual resolution configuration failed",
                        }
                    _save_devices(self.devices)
                    return _config_apply_result(True)
                finally:
                    # A monitor-only backend never keeps a device connected
                    # between one-off actions — revert once this config push
                    # is done so the per-frame tick loop doesn't pick it up.
                    if self.monitor_only and not was_connected:
                        dev["connected"] = False
            _save_devices(self.devices)
            return _config_apply_result(False)

    def set_device_output_type(self, di, oi, output_type):
        device_ref = None
        with self.lock:
            status = self._device_capability_status_unlocked(di, "output_config")
            if not status["ok"]:
                return status
            dev = self.devices[di]
            if output_type not in OUTPUT_TYPES:
                return {"ok": False, "error": f"unknown output type: {output_type!r}"}
            if self._device_supports_management_unlocked(dev):
                device_ref = dev
                device_lock = self._ensure_device_management_lock_unlocked(dev)
            else:
                if not (0 <= oi < len(dev.get("outputs", []))):
                    return {"ok": False, "error": "invalid output index"}
                prior = copy.deepcopy(dev["outputs"][oi])
                try:
                    self._apply_type_to_device_output_unlocked(dev["outputs"][oi], output_type)
                except ValueError as error:
                    return {"ok": False, "error": str(error)}

        if device_ref is not None:
            def prepare_unlocked(current_dev):
                if not (0 <= oi < len(current_dev.get("outputs", []))):
                    raise ValueError("invalid output index")
                descriptors = [
                    _descriptor_from_output_dict(item)
                    for item in current_dev.get("outputs", [])
                ]
                descriptors[oi] = BUILTIN_DESCRIPTOR_BY_TYPE[output_type]
                validate_receive_config(
                    ReceiveMode.COMBINED
                    if current_dev.get("receive_mode") == "combined"
                    else ReceiveMode.SPLIT,
                    descriptors,
                )
                return {"descriptors": tuple(descriptors)}

            with device_lock:
                return self._run_management_mutation_for_locked_device(
                    device_ref,
                    lambda idx: self._device_capability_status_unlocked(idx, "output_config"),
                    prepare_unlocked,
                    lambda ip, source_ip, prepared, dest_port=None: set_primus_output_descriptors(
                        ip, prepared["descriptors"], source_ip=source_ip, dest_port=dest_port),
                    lambda target, prepared, persist=False: self._apply_output_descriptors_to_device_unlocked(
                        target, prepared["descriptors"], persist=persist),
                )

        with self.lock:
            was_connected = dev["sender"].connected
            if was_connected or self.monitor_only:
                try:
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
                    virt_ok, virt_error = self._send_virtual_resolution(dev)
                    if not virt_ok:
                        dev["outputs"][oi] = prior
                        return {
                            "ok": False,
                            "error": virt_error or "virtual resolution configuration failed",
                        }
                    _save_devices(self.devices)
                    return _config_apply_result(True)
                finally:
                    if self.monitor_only and not was_connected:
                        dev["connected"] = False
            _save_devices(self.devices)
            return _config_apply_result(False)

    def set_device_receive_mode(self, di, receive_mode, base_universe):
        device_ref = None
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
            if receive_mode == "split" and base_universe > 32766:
                return {
                    "ok": False,
                    "error": "split base_universe must be 0-32766",
                }
            valid, err = _validate_receive_mode_for_device(receive_mode, dev.get("outputs", []))
            if not valid:
                return {"ok": False, "error": err}
            if self._device_supports_management_unlocked(dev):
                device_ref = dev
                device_lock = self._ensure_device_management_lock_unlocked(dev)
            else:
                prior_mode = dev.get("receive_mode", "split")
                prior_base = dev.get("base_universe", 0)
                dev["receive_mode"] = receive_mode
                dev["base_universe"] = base_universe
                _apply_output_universes(dev["outputs"], receive_mode, base_universe)

        if device_ref is not None:
            def prepare_unlocked(current_dev):
                valid, err = _validate_receive_mode_for_device(
                    receive_mode, current_dev.get("outputs", []))
                if not valid:
                    raise ValueError(err)
                return {
                    "receive_mode": receive_mode,
                    "receive_mode_enum": (
                        ReceiveMode.COMBINED if receive_mode == "combined"
                        else ReceiveMode.SPLIT
                    ),
                    "base_universe": base_universe,
                }

            with device_lock:
                return self._run_management_mutation_for_locked_device(
                    device_ref,
                    lambda idx: self._device_capability_status_unlocked(idx, "receive_config"),
                    prepare_unlocked,
                    lambda ip, source_ip, prepared, dest_port=None: set_primus_receive_config(
                        ip,
                        prepared["receive_mode_enum"],
                        prepared["base_universe"],
                        source_ip=source_ip,
                        dest_port=dest_port,
                    ),
                    lambda target, prepared, persist=False: self._apply_receive_config_to_device_unlocked(
                        target,
                        prepared["receive_mode"],
                        prepared["base_universe"],
                        persist=persist,
                    ),
                )

        with self.lock:
            try:
                send_receive_config(
                    dev["ip"],
                    receive_mode,
                    base_universe,
                    source_ip=self.artnet_source_ip,
                    dest_port=device_setup_port(dev),
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
            if dev.get("is_radius"):
                dev["connected"] = True
                self._clear_transport_error_unlocked(dev)
                return {"ok": True}
            if not self._ensure_sender_connected_unlocked(dev):
                return {
                    "ok": False,
                    "error": dev.get("transport_error") or "sender connection failed",
                }
            if not self._device_supports_management_unlocked(dev):
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
            if dev.get("is_radius"):
                dev["connected"] = False
                return
            if dev["sender"].connected:
                info = _device_blackout_info(dev)
                dev["sender"].blackout(info)
            dev["sender"].disconnect()
            dev["connected"] = False

    # ------------------------------------------------------------------
    #  Radius audio / FTP operations (shared backend)
    #
    #  The unified backend serves the RadiusCentral frontend from the same
    #  process as PrimusCentral/DeviceManager, so the Primus device list is
    #  also the Radius device list (records tagged is_radius). These mirror
    #  RadiusState's lane-aware wrappers over the artnet helpers.
    # ------------------------------------------------------------------

    _AUDIO_CMD_MAP = {
        "stop": AUDIO_CMD_STOP,
        "play": AUDIO_CMD_PLAY,
        "loop": AUDIO_CMD_LOOP,
        "pause": AUDIO_CMD_PAUSE,
        "volume": AUDIO_CMD_VOLUME,
    }

    def _radius_device_ref(self, di):
        with self.lock:
            if not (0 <= di < len(self.devices)):
                return None
            return self.devices[di]

    def send_audio_command(self, di, cmd, filename="", volume=100, duration=0):
        dev = self._radius_device_ref(di)
        if not dev or not dev.get("ip"):
            return False
        code = self._AUDIO_CMD_MAP.get(str(cmd).lower())
        if code is None:
            return False
        send_audio_cmd(
            dev["ip"], code, filename=filename, volume=volume, duration=duration,
            source_ip=self.artnet_source_ip, dest_port=device_show_port(dev),
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
                (d["ip"], d.get("connected", False), d.get("is_radius", False),
                 device_show_port(d))
                for d in self.devices
            ]
        actions = cue.get("actions") or {}
        for ip, connected, is_radius, port_show in snapshot:
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
                kwargs = {"source_ip": self.artnet_source_ip, "dest_port": port_show}
                kwargs["volume"] = int(volume) if volume is not None else 80
                if cmd_str in ("play", "loop"):
                    kwargs["filename"] = filename
                    kwargs["duration"] = int(duration)
                send_audio_cmd(ip, cmd_code, **kwargs)
                results[ip] = {"status": "sent", "reason": None}
                self.performance.increment("audio_commands")
            except Exception as exc:
                results[ip] = {"status": "error", "reason": str(exc)}
        return results

    def ftp_download(self, di, path):
        dev = self._radius_device_ref(di)
        if not dev or not dev.get("ip"):
            raise ValueError("invalid device index")
        return ftp_download(
            dev["ip"], path, source_ip=self.artnet_source_ip,
            dest_port=device_setup_port(dev))

    def ftp_list_dir(self, di, path="/"):
        dev = self._radius_device_ref(di)
        if not dev or not dev.get("ip"):
            return []
        return ftp_list_dir(
            dev["ip"], path, source_ip=self.artnet_source_ip,
            dest_port=device_setup_port(dev))

    def ftp_upload(self, di, path, data, progress_callback=None):
        dev = self._radius_device_ref(di)
        if not dev or not dev.get("ip"):
            raise ValueError("invalid device index")
        ftp_upload(dev["ip"], path, data, source_ip=self.artnet_source_ip,
                   progress_callback=progress_callback,
                   dest_port=device_setup_port(dev))

    def ftp_rename(self, di, src, dst):
        dev = self._radius_device_ref(di)
        if not dev or not dev.get("ip"):
            raise ValueError("invalid device index")
        ftp_rename(
            dev["ip"], src, dst, source_ip=self.artnet_source_ip,
            dest_port=device_setup_port(dev))

    def ftp_delete(self, di, path, is_dir=False):
        dev = self._radius_device_ref(di)
        if not dev or not dev.get("ip"):
            raise ValueError("invalid device index")
        ftp_delete(
            dev["ip"], path, is_dir=is_dir, source_ip=self.artnet_source_ip,
            dest_port=device_setup_port(dev))

    def ftp_mkdir(self, di, path):
        dev = self._radius_device_ref(di)
        if not dev or not dev.get("ip"):
            raise ValueError("invalid device index")
        ftp_mkdir(
            dev["ip"], path, source_ip=self.artnet_source_ip,
            dest_port=device_setup_port(dev))

    def radius_has_live_playback(self):
        """True when any Radius receiver reports audio playing (via PTR)."""
        if not self.fps_listener:
            return False
        with self.lock:
            ips = [d.get("ip") for d in self.devices if d.get("is_radius")]
        for ip in ips:
            if not ip:
                continue
            rx = self.fps_listener.get(ip)
            if not rx:
                continue
            try:
                if int(rx.get("playback_state") or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def add_device_from_node(self, node_info, auto_save=True):
        with self.lock:
            idx = self._find_existing_device_index_unlocked(node_info)
            if idx is not None:
                device_ref = self.devices[idx]
                device_lock = self._ensure_device_management_lock_unlocked(device_ref)
            else:
                device_ref = None

        if device_ref is not None:
            groups_changed = False
            with device_lock:
                with self.lock:
                    idx = self._find_device_index_by_ref_unlocked(device_ref)
                    if idx is None:
                        return self._management_conflict_result("device no longer exists")
                    dev = self.devices[idx]
                    old_ip = dev["ip"]
                    ip_changed = dev["ip"] != node_info["ip"]
                    if ip_changed:
                        dev["ip"] = node_info["ip"]
                        sender = dev.get("sender")
                        if sender is not None:
                            sender.ip = dev["ip"]
                        _migrate_device_show_info_key(
                            old_ip,
                            dev["ip"],
                            dev.get("name"),
                            is_radius=dev.get("is_radius"),
                        )
                        groups_changed = self._replace_device_ip_references_unlocked(
                            old_ip, dev["ip"])
                    refresh_state = self._refresh_device_from_node_unlocked(dev, node_info)
                if refresh_state["needs_management_refresh"]:
                    self._query_management_config_for_locked_device(
                        device_ref,
                        auto_save=False,
                        on_error_unlocked=lambda current_dev, snapshot=refresh_state["authoritative_state"]: (
                            self._restore_authoritative_management_state_unlocked(
                                current_dev, snapshot)
                        ),
                        return_error=False,
                    )
                with self.lock:
                    idx = self._find_device_index_by_ref_unlocked(device_ref)
                    if idx is None:
                        return self._management_conflict_result("device no longer exists")
                    dev = self.devices[idx]
                    updated = bool(refresh_state["updated"] or ip_changed)
                    if updated and auto_save:
                        _save_devices(self.devices)
                    if groups_changed and auto_save:
                        _save_device_groups(self.device_groups)
                    return {
                        "status": "updated" if updated else "exists",
                        "device_index": idx,
                    }

        with self.lock:
            output_cfgs = _output_configs_from_node(node_info)
            capabilities = _capabilities_from_node(node_info)
            if capabilities.get("device_class") == "radius":
                character_name, performer_name = _show_info_from_node(node_info)
                character_name, performer_name = _merge_show_info_fields(
                    character_name,
                    performer_name,
                    node_info.get("ip"),
                    node_info.get("short_name"),
                    is_radius=True,
                )
                dev = {
                    "name": _preferred_device_name(
                        {"is_radius": True},
                        node_info,
                        node_info.get("short_name", "Radius"),
                    ),
                    "character_name": character_name,
                    "performer_name": performer_name,
                    "ip": node_info["ip"],
                    "mac": node_info.get("mac"),
                    "device_uid": node_info.get("device_uid")
                    or node_info.get("mac")
                    or "ip:{}".format(node_info["ip"]),
                    "connected": False,
                    "is_radius": True,
                    "transport_error": None,
                    "capabilities": capabilities,
                    "hardware_profile": node_info.get(
                        "hardware_profile", capabilities.get("hardware_profile", "v1")),
                    "hardware_label": node_info.get(
                        "hardware_label", capabilities.get("hardware_label", "V1 Huzzah32")),
                    "firmware_version": node_info.get(
                        "firmware_version", capabilities.get("firmware_version")),
                    "ip_mode": capabilities.get("ip_mode", "unknown"),
                    "static_ip": capabilities.get("static_ip"),
                    "gateway": capabilities.get("gateway"),
                    "subnet": capabilities.get("subnet"),
                    "current_track": "",
                    "playback_state": 0,
                }
                _apply_network_capabilities_to_device(dev, capabilities, fallback_ip=dev["ip"])
                _apply_persisted_show_info(dev, node_info)
                self.devices.append(dev)
                self._ensure_device_management_lock_unlocked(dev)
                if auto_save:
                    _save_devices(self.devices)
                return {"status": "added", "device_index": len(self.devices) - 1}

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
                "name": _preferred_device_name(None, node_info, node_info.get("short_name", "Node")),
                "character_name": character_name,
                "performer_name": performer_name,
                "ip": node_info["ip"],
                "mac": node_info.get("mac"),
                "device_uid": node_info.get("device_uid")
                or node_info.get("mac")
                or "ip:{}".format(node_info["ip"]),
                "base_universe": base_u,
                "receive_mode": receive_mode,
                "connected": False,
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
            _apply_management_state_to_device(dev, node_info, capabilities)
            dev["sender"] = ArtNetSender(
                node_info["ip"],
                source_ip=self.artnet_source_ip,
                dest_port=device_show_port(dev),
            )
            dev["outputs"] = self._build_device_outputs_unlocked(
                node_info, output_cfgs, base_u, receive_mode=receive_mode)
            _apply_persisted_show_info(dev, node_info)
            self.devices.append(dev)
            device_lock = self._ensure_device_management_lock_unlocked(dev)
            added_index = len(self.devices) - 1

        if self._device_supports_management_unlocked(dev):
            with device_lock:
                self._query_management_config_for_locked_device(
                    dev,
                    auto_save=False,
                    return_error=False,
                )

        with self.lock:
            idx = self._find_device_index_by_ref_unlocked(dev)
            if idx is None:
                return self._management_conflict_result("device no longer exists")
            if auto_save:
                _save_devices(self.devices)
            return {"status": "added", "device_index": idx if idx is not None else added_index}

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
                                       receive_mode="combined"):
        outputs = []
        existing_outputs = existing_outputs or []
        existing_by_slot = {
            _slot_index(
                output.get("name"),
                output.get("physical_slot"),
                fallback=index,
            ): output
            for index, output in enumerate(existing_outputs)
            if isinstance(output, dict)
        }
        cfg_by_slot = {}
        for index, output_cfg in enumerate(output_cfgs or []):
            if not isinstance(output_cfg, dict):
                continue
            slot = _slot_index(
                output_cfg.get("name"),
                output_cfg.get("physical_slot"),
                fallback=index,
            )
            cfg_by_slot[slot] = output_cfg
        for slot in range(OUTPUT_SLOT_COUNT):
            prior = existing_by_slot.get(slot)
            output_cfg = cfg_by_slot.get(slot)
            if output_cfg is None:
                descriptor = _descriptor_from_output_dict(prior) if prior else OFF_DESCRIPTOR
                rotation = (prior or {}).get("grid_rotation", 0)
            else:
                descriptor = _descriptor_from_output_dict({
                    **(prior or {}),
                    **output_cfg,
                })
                rotation = output_cfg.get(
                    "grid_rotation", (prior or {}).get("grid_rotation", 0))
            outputs.append(_output_record_from_descriptor(
                descriptor,
                slot=slot,
                universe=base_u + slot,
                prior=prior,
                grid_rotation=rotation,
            ))
        _apply_output_universes(outputs, receive_mode, base_u)
        return outputs

    def _refresh_device_from_node_unlocked(self, dev, node_info):
        if not _node_has_discovery_metadata(node_info):
            return {
                "updated": False,
                "needs_management_refresh": False,
                "authoritative_state": None,
            }

        authoritative_state = {
            key: copy.deepcopy(dev.get(key))
            for key in AUTHORITATIVE_MANAGEMENT_FIELDS
        }
        capabilities = _capabilities_from_node(node_info)
        if _is_radius_capabilities(capabilities):
            _promote_device_to_radius(dev)
        preferred = _preferred_device_name(dev, node_info)
        dev["capabilities"] = capabilities
        if node_info.get("mac"):
            dev["mac"] = node_info["mac"]
            dev["device_uid"] = node_info["mac"]
        elif not dev.get("device_uid"):
            dev["device_uid"] = "ip:{}".format(dev.get("ip"))
        dev["hardware_profile"] = node_info.get(
            "hardware_profile", capabilities.get("hardware_profile", "unknown"))
        dev["hardware_label"] = node_info.get(
            "hardware_label", capabilities.get("hardware_label", "Unknown hardware"))
        dev["firmware_version"] = node_info.get(
            "firmware_version", capabilities.get("firmware_version"))
        _apply_network_capabilities_to_device(dev, capabilities, fallback_ip=dev["ip"])
        _apply_management_state_to_device(dev, node_info, capabilities)
        dev["ip_config_pending"] = None

        if self._device_supports_management_unlocked(dev):
            sender = dev.get("sender")
            if sender is not None:
                sender.ip = dev["ip"]
                sender.set_dest_port(device_show_port(dev))
            return {
                "updated": True,
                "needs_management_refresh": True,
                "authoritative_state": authoritative_state,
            }

        if preferred and preferred != dev.get("name"):
            dev["name"] = preferred

        char, perf = _show_info_from_node(node_info)
        char, perf = _merge_show_info_fields(
            char, perf, dev.get("ip"), dev.get("name"), is_radius=dev.get("is_radius"))
        if show_info_store.discovery_show_info_may_apply(dev):
            dev["character_name"] = char
            dev["performer_name"] = perf
            _persist_device_show_info(
                dev.get("ip"),
                dev.get("name"),
                dev.get("character_name", ""),
                dev.get("performer_name", ""),
                is_radius=dev.get("is_radius"),
            )

        if dev.get("is_radius"):
            return {
                "updated": True,
                "needs_management_refresh": False,
                "authoritative_state": None,
            }

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
        dev["sender"].set_dest_port(device_show_port(dev))
        return {
            "updated": True,
            "needs_management_refresh": False,
            "authoritative_state": None,
        }

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
                if not dev.get("is_radius") and dev["sender"].connected:
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
            if self._device_supports_management_unlocked(dev):
                device_ref = dev
                device_lock = self._ensure_device_management_lock_unlocked(dev)
            else:
                try:
                    ok, error = sync_device_name_to_receiver(
                        dev["ip"], new_name, source_ip=self.artnet_source_ip,
                        dest_port=device_setup_port(dev))
                except OSError as error:
                    if dev.get("is_radius"):
                        dev["transport_error"] = str(error)
                        return {"ok": False, "error": dev.get("transport_error")}
                    self._mark_transport_error_unlocked(dev, error)
                    return {"ok": False, "error": dev.get("transport_error")}
                if not ok:
                    if dev.get("is_radius"):
                        dev["transport_error"] = error
                    else:
                        self._mark_transport_error_unlocked(dev, OSError(error))
                    return {"ok": False, "error": error}
                dev["name"] = new_name
                self._clear_transport_error_unlocked(dev)
                _persist_device_show_info(
                    dev["ip"],
                    dev.get("name"),
                    dev.get("character_name"),
                    dev.get("performer_name"),
                    is_radius=dev.get("is_radius"),
                )
                _save_devices(self.devices)
                return {"ok": True}

        with device_lock:
            return self._run_management_mutation_for_locked_device(
                device_ref,
                lambda idx: self._device_capability_status_unlocked(idx, "rename"),
                lambda current_dev: {
                    "technical_name": new_name,
                    "character_name": current_dev.get("character_name", ""),
                    "performer_name": current_dev.get("performer_name", ""),
                },
                lambda ip, source_ip, prepared, dest_port=None: set_primus_identity(
                    ip,
                    prepared["technical_name"],
                    prepared["character_name"],
                    prepared["performer_name"],
                    source_ip=source_ip,
                    dest_port=dest_port,
                ),
                lambda target, prepared, persist=False: self._apply_identity_fields_unlocked(
                    target,
                    prepared["technical_name"],
                    prepared["character_name"],
                    prepared["performer_name"],
                    persist=persist,
                ),
            )

    def _sync_show_info_to_device_unlocked(self, dev):
        caps = _normalize_device_capabilities(dev.get("capabilities"))
        if not caps.get("show_info") and not dev.get("is_radius"):
            return True
        try:
            ok, error = sync_show_info_to_device(
                dev["ip"],
                dev.get("character_name", ""),
                dev.get("performer_name", ""),
                source_ip=self.artnet_source_ip,
                dest_port=device_setup_port(dev),
            )
        except OSError as error:
            self._mark_transport_error_unlocked(dev, error)
            return False
        if not ok:
            dev["transport_error"] = error
            return False
        self._clear_transport_error_unlocked(dev)
        return True

    def update_device_show_info(self, di, character_name=None, performer_name=None):
        with self.lock:
            if not (0 <= di < len(self.devices)):
                return {"ok": False, "error": "invalid device index"}
            dev = self.devices[di]
            next_character = _normalize_show_info_value(
                character_name if character_name is not None else dev.get("character_name")
            )
            next_performer = _normalize_show_info_value(
                performer_name if performer_name is not None else dev.get("performer_name")
            )
            if self._device_supports_management_unlocked(dev):
                device_ref = dev
                device_lock = self._ensure_device_management_lock_unlocked(dev)
            else:
                if character_name is not None:
                    dev["character_name"] = next_character
                if performer_name is not None:
                    dev["performer_name"] = next_performer
                caps = _normalize_device_capabilities(dev.get("capabilities"))
                applied_to_device = False
                if caps.get("show_info") or dev.get("is_radius"):
                    if not self._sync_show_info_to_device_unlocked(dev):
                        return {"ok": False, "error": dev.get("transport_error")}
                    applied_to_device = True
                _persist_device_show_info(
                    dev["ip"],
                    dev.get("name"),
                    dev.get("character_name"),
                    dev.get("performer_name"),
                    is_radius=dev.get("is_radius"),
                )
                dev["show_info_edited_at"] = time.time()
                _save_devices(self.devices)
                return {"ok": True, "applied_to_device": applied_to_device}

        with device_lock:
            result = self._run_management_mutation_for_locked_device(
                device_ref,
                self._device_management_status_unlocked,
                lambda current_dev: {
                    "technical_name": current_dev.get("name", ""),
                    "character_name": next_character,
                    "performer_name": next_performer,
                },
                lambda ip, source_ip, prepared, dest_port=None: set_primus_identity(
                    ip,
                    prepared["technical_name"],
                    prepared["character_name"],
                    prepared["performer_name"],
                    source_ip=source_ip,
                    dest_port=dest_port,
                ),
                lambda target, prepared, persist=False: self._apply_identity_fields_unlocked(
                    target,
                    prepared["technical_name"],
                    prepared["character_name"],
                    prepared["performer_name"],
                    persist=persist,
                ),
            )
        if result.get("ok"):
            with self.lock:
                idx = self._find_device_index_by_ref_unlocked(device_ref)
                if idx is not None:
                    self.devices[idx]["show_info_edited_at"] = time.time()
            result["applied_to_device"] = True
        return result

    def get_device_full_config(self, di):
        with self.lock:
            if not (0 <= di < len(self.devices)):
                return {"ok": False, "error": "invalid device index", "http_status": 400}
            dev = self.devices[di]
            return {"ok": True, "config": self._device_config_payload_unlocked(dev)}

    def refresh_device_full_config(self, di):
        with self.lock:
            status = self._device_management_status_unlocked(di)
            if not status.get("ok"):
                return status
            device_ref = self.devices[di]
            device_lock = self._ensure_device_management_lock_unlocked(device_ref)
        with device_lock:
            return self._query_management_config_for_locked_device(device_ref)

    def apply_device_output_descriptor(self, di, oi, descriptor_template):
        with self.lock:
            status = self._device_management_status_unlocked(di)
            if not status.get("ok"):
                return status
            dev = self.devices[di]
            device_ref = dev
            device_lock = self._ensure_device_management_lock_unlocked(dev)

        def prepare_unlocked(current_dev):
            if not (0 <= oi < len(current_dev.get("outputs", []))):
                raise ValueError("invalid output index")
            descriptors = [
                _descriptor_from_output_dict(item)
                for item in current_dev.get("outputs", [])
            ]
            descriptors[oi] = _descriptor_template_to_descriptor(descriptor_template)
            validate_receive_config(
                ReceiveMode.COMBINED
                if current_dev.get("receive_mode") == "combined"
                else ReceiveMode.SPLIT,
                descriptors,
            )
            return {"descriptors": tuple(descriptors)}

        with device_lock:
            return self._run_management_mutation_for_locked_device(
                device_ref,
                self._device_management_status_unlocked,
                prepare_unlocked,
                lambda ip, source_ip, prepared, dest_port=None: set_primus_output_descriptors(
                    ip, prepared["descriptors"], source_ip=source_ip, dest_port=dest_port),
                lambda target, prepared, persist=False: self._apply_output_descriptors_to_device_unlocked(
                    target, prepared["descriptors"], persist=persist),
            )

    def set_device_telemetry_target(self, di, address):
        with self.lock:
            status = self._device_management_status_unlocked(di)
            if not status.get("ok"):
                return status
            device_ref = self.devices[di]
            device_lock = self._ensure_device_management_lock_unlocked(device_ref)
        with device_lock:
            return self._run_management_mutation_for_locked_device(
                device_ref,
                self._device_management_status_unlocked,
                lambda current_dev: {"address": address},
                lambda ip, source_ip, prepared, dest_port=None: set_primus_telemetry_target(
                    ip, prepared["address"], source_ip=source_ip, dest_port=dest_port),
                lambda target, prepared, persist=False: self._apply_telemetry_target_to_device_unlocked(
                    target, prepared["address"], persist=persist),
            )

    def clear_device_telemetry_target(self, di):
        return self.set_device_telemetry_target(di, "0.0.0.0")

    def enter_device_production_mode(self, di):
        with self.lock:
            status = self._device_management_status_unlocked(di)
            if not status.get("ok"):
                return status
            device_ref = self.devices[di]
            device_lock = self._ensure_device_management_lock_unlocked(device_ref)
        with device_lock:
            return self._run_management_mutation_for_locked_device(
                device_ref,
                self._device_management_status_unlocked,
                lambda current_dev: {"mode": OperatingMode.PRODUCTION},
                lambda ip, source_ip, prepared, dest_port=None: set_primus_operating_mode(
                    ip, prepared["mode"], source_ip=source_ip, dest_port=dest_port),
                lambda target, prepared, persist=False: self._apply_operating_mode_to_device_unlocked(
                    target, prepared["mode"], persist=persist),
            )

    def unlock_device_boot_window(self, di):
        with self.lock:
            status = self._device_management_status_unlocked(di)
            if not status.get("ok"):
                return status
            device_ref = self.devices[di]
            device_lock = self._ensure_device_management_lock_unlocked(device_ref)
        with device_lock:
            return self._run_management_mutation_for_locked_device(
                device_ref,
                self._device_management_status_unlocked,
                lambda current_dev: {"unlock": True},
                lambda ip, source_ip, prepared, dest_port=None: unlock_primus_boot_window(
                    ip, source_ip=source_ip, dest_port=dest_port),
                self._apply_boot_window_unlock_to_device_unlocked,
            )

    def get_device_lock_state(self, di):
        with self.lock:
            if not (0 <= di < len(self.devices)):
                return {"ok": False, "error": "invalid device index", "http_status": 400}
            dev = self.devices[di]
            return {
                "ok": True,
                "management_supported": bool(dev.get("management_supported")),
                "operating_mode": dev.get("operating_mode"),
                "production_mode": bool(dev.get("production_mode")),
                "management_locked": bool(dev.get("management_locked")),
                "unlock_window_open": bool(dev.get("unlock_window_open")),
                "unlock_remaining_seconds": int(dev.get("unlock_remaining_seconds") or 0),
            }

    def set_device_ip(self, di, static_ip, gateway, subnet):
        with self.lock:
            status = self._device_capability_status_unlocked(di, "ip_config")
            if not status["ok"]:
                return status
            dev = self.devices[di]
            if self._device_supports_management_unlocked(dev):
                device_ref = dev
                device_lock = self._ensure_device_management_lock_unlocked(dev)
            else:
                try:
                    ipv4_octets(static_ip, "ip")
                    ipv4_octets(gateway, "gateway")
                    ipv4_octets(subnet, "subnet")
                    send_ip_config(
                        dev["ip"], 1, static_ip, gateway, subnet,
                        source_ip=self.artnet_source_ip, dest_port=device_setup_port(dev))
                except (OSError, ValueError) as error:
                    if dev.get("is_radius"):
                        dev["transport_error"] = str(error)
                        return {"ok": False, "error": dev.get("transport_error")}
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

        if self._device_supports_management_unlocked(device_ref):
            with device_lock:
                return self._run_management_mutation_for_locked_device(
                    device_ref,
                    lambda idx: self._device_capability_status_unlocked(idx, "ip_config"),
                    lambda current_dev: {
                        "ip_mode": "static",
                        "ip_mode_enum": IpMode.STATIC,
                        "static_ip": static_ip,
                        "gateway": gateway,
                        "subnet": subnet,
                    },
                    lambda ip, source_ip, prepared, dest_port=None: set_primus_ip_config(
                        ip,
                        prepared["ip_mode_enum"],
                        prepared["static_ip"],
                        prepared["gateway"],
                        prepared["subnet"],
                        source_ip=source_ip,
                        dest_port=dest_port,
                    ),
                    self._apply_ip_config_to_device_unlocked,
                    skip_readback=True,
                    success_extra={"pending_reconnect": True},
                )

    def revert_device_dhcp(self, di):
        with self.lock:
            status = self._device_capability_status_unlocked(di, "ip_config")
            if not status["ok"]:
                return status
            dev = self.devices[di]
            if self._device_supports_management_unlocked(dev):
                device_ref = dev
                device_lock = self._ensure_device_management_lock_unlocked(dev)
            else:
                try:
                    send_ip_config(
                        dev["ip"], 0, source_ip=self.artnet_source_ip,
                        dest_port=device_setup_port(dev))
                except (OSError, ValueError) as error:
                    if dev.get("is_radius"):
                        dev["transport_error"] = str(error)
                        return {"ok": False, "error": dev.get("transport_error")}
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

        if self._device_supports_management_unlocked(device_ref):
            with device_lock:
                return self._run_management_mutation_for_locked_device(
                    device_ref,
                    lambda idx: self._device_capability_status_unlocked(idx, "ip_config"),
                    lambda current_dev: {
                        "ip_mode": "dhcp",
                        "ip_mode_enum": IpMode.DHCP,
                    },
                    lambda ip, source_ip, prepared, dest_port=None: set_primus_ip_config(
                        ip,
                        prepared["ip_mode_enum"],
                        source_ip=source_ip,
                        dest_port=dest_port,
                    ),
                    self._apply_ip_config_to_device_unlocked,
                    skip_readback=True,
                    success_extra={"pending_reconnect": True},
                )

    def _apply_lane_ports_result_unlocked(self, dev, prepared, persist=False):
        dev["port_show"] = int(prepared["port_show"])
        dev["port_setup"] = int(prepared["port_setup"])
        dev["port_watch"] = int(prepared["port_watch"])
        caps = _normalize_device_capabilities(dev.get("capabilities"))
        caps["port_show"] = dev["port_show"]
        caps["port_setup"] = dev["port_setup"]
        caps["port_watch"] = dev["port_watch"]
        dev["capabilities"] = caps
        sender = dev.get("sender")
        if sender is not None and hasattr(sender, "set_dest_port"):
            sender.set_dest_port(device_show_port(dev))

    def get_device_lane_ports(self, di):
        with self.lock:
            if not (0 <= di < len(self.devices)):
                return {"ok": False, "error": "invalid device index", "http_status": 400}
            dev = self.devices[di]
            return {
                "ok": True,
                "port_show": device_show_port(dev, is_radius=dev.get("is_radius")),
                "port_setup": device_setup_port(dev, is_radius=dev.get("is_radius")),
                "port_watch": int(dev.get("port_watch") or FPS_LISTEN_PORT),
                "ftp_port": dev.get("ftp_port"),
                "is_radius": bool(dev.get("is_radius")),
                "management_capable": self._device_supports_management_unlocked(dev),
            }

    def set_device_lane_ports(self, di, port_show, port_setup, port_watch):
        try:
            port_show = int(port_show)
            port_setup = int(port_setup)
            port_watch = int(port_watch)
        except (TypeError, ValueError):
            return {"ok": False, "error": "ports must be integers", "http_status": 400}
        try:
            _validate_device_lane_ports(port_show, port_setup, port_watch)
        except ValueError as error:
            return {"ok": False, "error": str(error), "http_status": 400}

        device_ref = None
        device_lock = None
        with self.lock:
            if not (0 <= di < len(self.devices)):
                return {"ok": False, "error": "invalid device index", "http_status": 400}
            dev = self.devices[di]
            if dev.get("is_radius"):
                try:
                    send_lane_ports(
                        dev["ip"], port_show, port_setup, port_watch,
                        source_ip=self.artnet_source_ip, dest_port=device_setup_port(dev),
                    )
                except OSError as error:
                    dev["transport_error"] = str(error)
                    return {"ok": False, "error": dev.get("transport_error")}
                self._apply_lane_ports_result_unlocked(
                    dev,
                    {"port_show": port_show, "port_setup": port_setup, "port_watch": port_watch},
                    persist=True,
                )
                self._clear_transport_error_unlocked(dev)
                _save_devices(self.devices)
                return {
                    "ok": True,
                    "port_show": port_show,
                    "port_setup": port_setup,
                    "port_watch": port_watch,
                }
            if not self._device_supports_management_unlocked(dev):
                return {
                    "ok": False,
                    "error": f'{dev.get("name", "Device")} does not advertise Primus management support.',
                    "error_code": "UnsupportedOperation",
                    "http_status": 409,
                }
            device_ref = dev
            device_lock = self._ensure_device_management_lock_unlocked(dev)

        with device_lock:
            return self._run_management_mutation_for_locked_device(
                device_ref,
                lambda idx: self._device_management_status_unlocked(idx),
                lambda current_dev: {
                    "port_show": port_show,
                    "port_setup": port_setup,
                    "port_watch": port_watch,
                },
                lambda ip, source_ip, prepared, dest_port=None: set_primus_lane_ports(
                    ip,
                    prepared["port_show"],
                    prepared["port_setup"],
                    prepared["port_watch"],
                    source_ip=source_ip,
                    dest_port=dest_port,
                ),
                self._apply_lane_ports_result_unlocked,
                skip_readback=True,
                success_extra={"pending_reconnect": True},
            )

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
                if dev.get("is_radius"):
                    dev["connected"] = True
                    results.append({
                        "device_index": idx,
                        "ok": True,
                        "error": None,
                    })
                    continue
                ok = self._ensure_sender_connected_unlocked(dev)
                if ok:
                    if not self._device_supports_management_unlocked(dev):
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
                if dev.get("is_radius"):
                    dev["connected"] = False
                    continue
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

    def list_output_presets(self, include_built_ins=True):
        return self.output_preset_store.list_presets(include_built_ins=include_built_ins)

    def get_output_preset(self, preset_id):
        return self.output_preset_store.get_preset(preset_id)

    def create_output_preset(self, name, descriptor_template):
        return self.output_preset_store.create_preset(name, descriptor_template)

    def update_output_preset(self, preset_id, *, name=None, descriptor_template=None):
        return self.output_preset_store.update_preset(
            preset_id,
            name=name,
            descriptor_template=descriptor_template,
        )

    def delete_output_preset(self, preset_id):
        return self.output_preset_store.delete_preset(preset_id)

    def delete_device_group(self, gid):
        with self.lock:
            self.device_groups = [g for g in self.device_groups if g["id"] != gid]
            _save_device_groups(self.device_groups)
            return True

    def hello_device(self, di, volume=80):
        """Send identify flash (Primus) or test tone (Radius)."""
        with self.lock:
            if not (0 <= di < len(self.devices)):
                return False
            dev = self.devices[di]
            if dev.get("is_radius"):
                try:
                    send_audio_cmd(
                        dev["ip"],
                        AUDIO_CMD_TEST_TONE,
                        volume=int(volume),
                        source_ip=self.artnet_source_ip,
                        dest_port=device_show_port(dev),
                    )
                    return True
                except OSError:
                    return False
            status = self._device_capability_status_unlocked(di, "hello")
            if not status["ok"]:
                return False
            dev = self.devices[di]
            if not dev.get("connected") and not self.monitor_only:
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
                if dev.get("is_radius"):
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
                    if self.monitor_only:
                        # The flash window is over, but the receiver just holds
                        # whatever pixel data it last got — it won't blackout on
                        # its own once we stop streaming. Push one off frame
                        # before releasing the transient connection, or the
                        # identify flash stays lit red indefinitely.
                        for universe, data in _device_flash_entries(
                                dev, bytes([0, 0, 0])):
                            send_queue.append((di, dev["sender"], universe, data))
                        devices_sent.add(di)
                        dev["connected"] = False
                        continue
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
                        send_pixels = _apply_descriptor_wiring(pixels, o)

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
                    send_pixels = _apply_descriptor_wiring(lo["pixels"], o)

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
                # Radius records have no ArtNetSender and never receive DMX;
                # a bare dev["sender"] here killed the whole tick as soon as
                # a connected Radius device shared the unified device list.
                if dev.get("is_radius"):
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
                        virtual = resolve_virtual_pixels(o)
                        if virtual <= 0:
                            continue
                        send_queue.append(
                            (di, dev["sender"], o["universe"], bytes(virtual * 3)))
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
            if dev.get("is_radius"):
                continue
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
    tick_errors = 0
    while state.running:
        frame_start = time.perf_counter()
        try:
            state.tick()
        except Exception:
            # One bad frame must never kill DMX for the rest of the show.
            # Log loudly (first few + every 100th so a persistent fault
            # cannot flood the log) and keep the loop alive.
            tick_errors += 1
            state.performance.increment("animation_tick_errors")
            if tick_errors <= 5 or tick_errors % 100 == 0:
                import traceback
                print(f"ERROR: animation tick failed (#{tick_errors}):")
                traceback.print_exc()
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
