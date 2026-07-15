"""Reusable output preset persistence for Primus sender output descriptors."""

import errno
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager

import paths
from primus_protocol import Layout, OutputDescriptor, ScanPattern, StartCorner, TraversalAxis


OUTPUT_PRESETS_FILE = "output_presets.json"
_OUTPUT_PRESETS_SCHEMA_VERSION = 1
_DESCRIPTOR_FIELDS = frozenset({
    "enabled",
    "physical_pixels",
    "layout",
    "rows",
    "columns",
    "traversal_axis",
    "scan_pattern",
    "start_corner",
    "virtual_pixels",
})
_STORE_LOCKS = {}
_STORE_LOCKS_GUARD = threading.Lock()


class OutputPresetError(Exception):
    """Base error for output preset operations."""


class OutputPresetValidationError(OutputPresetError, ValueError):
    """Raised when a preset payload or descriptor is invalid."""


class OutputPresetNotFoundError(OutputPresetError, KeyError):
    """Raised when a preset ID is unknown."""


class DuplicateOutputPresetNameError(OutputPresetError):
    """Raised when a preset name collides with an existing preset."""


class DuplicateOutputPresetIdError(OutputPresetError):
    """Raised when a preset ID collides with an existing preset."""


class BuiltInOutputPresetError(OutputPresetError):
    """Raised when attempting to mutate a built-in preset."""


class MalformedOutputPresetsError(OutputPresetError):
    """Raised when the persisted presets file is invalid."""


_DEF_BUILTIN_PRESETS = (
    (
        "builtin-off",
        "Off",
        {
            "enabled": False,
        },
    ),
    (
        "builtin-short-strip",
        "Short Strip",
        {
            "enabled": True,
            "layout": "linear",
            "physical_pixels": 30,
            "virtual_pixels": 30,
        },
    ),
    (
        "builtin-long-strip",
        "Long Strip",
        {
            "enabled": True,
            "layout": "linear",
            "physical_pixels": 72,
            "virtual_pixels": 72,
        },
    ),
    (
        "builtin-grid",
        "Grid",
        {
            "enabled": True,
            "layout": "grid",
            "rows": 8,
            "columns": 8,
            "physical_pixels": 64,
            "scan_pattern": "serpentine",
            "virtual_pixels": 64,
        },
    ),
    (
        "builtin-small-grid",
        "Small Grid",
        {
            "enabled": True,
            "layout": "grid",
            "rows": 4,
            "columns": 8,
            "physical_pixels": 32,
            "scan_pattern": "serpentine",
            "virtual_pixels": 1,
        },
    ),
    (
        "builtin-extra-long-strip",
        "Extra Long Strip",
        {
            "enabled": True,
            "layout": "linear",
            "physical_pixels": 122,
            "virtual_pixels": 122,
        },
    ),
)


def normalize_output_descriptor_template(template):
    """Validate and normalize an API-friendly output descriptor template."""
    return _descriptor_to_dict(_coerce_output_descriptor(template))


class OutputPresetStore:
    """Manage reusable output presets separate from clips and looks."""

    def __init__(self, path=None, built_in_presets=None):
        self.path = path or paths.data_path(OUTPUT_PRESETS_FILE)
        self._lock = _shared_store_lock(self.path)
        built_in_presets = _DEF_BUILTIN_PRESETS if built_in_presets is None else built_in_presets
        self._built_in_presets = _normalize_built_in_presets(built_in_presets)
        self._user_presets = {}
        self.reload()

    def reload(self):
        with self._transaction():
            self._reload_user_presets_locked()
            return self._list_presets_locked()

    def list_presets(self, include_built_ins=True):
        with self._transaction():
            self._reload_user_presets_locked()
            return self._list_presets_locked(include_built_ins=include_built_ins)

    def _list_presets_locked(self, include_built_ins=True):
        presets = []
        if include_built_ins:
            presets.extend(_copy_preset(preset) for preset in self._built_in_presets.values())
        presets.extend(_copy_preset(preset) for preset in self._iter_sorted_user_presets())
        return presets

    def get_preset(self, preset_id):
        with self._transaction():
            self._reload_user_presets_locked()
            preset_id = _normalize_preset_id(preset_id)
            preset = self._built_in_presets.get(preset_id) or self._user_presets.get(preset_id)
            if preset is None:
                raise OutputPresetNotFoundError(f"unknown output preset id: {preset_id}")
            return _copy_preset(preset)

    def create_preset(self, name, descriptor_template):
        with self._transaction():
            self._reload_user_presets_locked()
            normalized_name = _normalize_preset_name(name)
            self._assert_name_available(normalized_name)
            preset_id = _generated_preset_id(normalized_name)
            if preset_id in self._built_in_presets or preset_id in self._user_presets:
                raise DuplicateOutputPresetIdError(f"output preset id already exists: {preset_id}")
            preset = _preset_record(
                preset_id,
                normalized_name,
                normalize_output_descriptor_template(descriptor_template),
                built_in=False,
            )
            self._user_presets[preset_id] = preset
            try:
                self._save_user_presets()
            except Exception:
                self._user_presets.pop(preset_id, None)
                raise
            return _copy_preset(preset)

    def update_preset(self, preset_id, *, name=None, descriptor_template=None):
        with self._transaction():
            self._reload_user_presets_locked()
            preset_id = _normalize_preset_id(preset_id)
            if preset_id in self._built_in_presets:
                raise BuiltInOutputPresetError(f"cannot update built-in output preset: {preset_id}")
            current = self._user_presets.get(preset_id)
            if current is None:
                raise OutputPresetNotFoundError(f"unknown output preset id: {preset_id}")

            next_name = current["name"] if name is None else _normalize_preset_name(name)
            if next_name.casefold() != current["name"].casefold():
                self._assert_name_available(next_name, ignore_id=preset_id)
            next_descriptor = (
                current["descriptor"]
                if descriptor_template is None
                else normalize_output_descriptor_template(descriptor_template)
            )
            updated = _preset_record(preset_id, next_name, next_descriptor, built_in=False)
            self._user_presets[preset_id] = updated
            try:
                self._save_user_presets()
            except Exception:
                self._user_presets[preset_id] = current
                raise
            return _copy_preset(updated)

    def delete_preset(self, preset_id):
        with self._transaction():
            self._reload_user_presets_locked()
            preset_id = _normalize_preset_id(preset_id)
            if preset_id in self._built_in_presets:
                raise BuiltInOutputPresetError(f"cannot delete built-in output preset: {preset_id}")
            try:
                deleted = self._user_presets.pop(preset_id)
            except KeyError as exc:
                raise OutputPresetNotFoundError(f"unknown output preset id: {preset_id}") from exc
            try:
                self._save_user_presets()
            except Exception:
                self._user_presets[preset_id] = deleted
                raise
            return _copy_preset(deleted)

    @contextmanager
    def _transaction(self):
        with self._lock:
            with _interprocess_store_lock(self.path):
                yield

    def _reload_user_presets_locked(self):
        self._user_presets = self._load_user_presets()
        return self._user_presets

    def _load_user_presets(self):
        with self._lock:
            if not os.path.exists(self.path):
                return {}
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except json.JSONDecodeError as exc:
                raise MalformedOutputPresetsError(
                    f"output presets file contains invalid JSON: {self.path}"
                ) from exc
            except OSError:
                raise

            if not isinstance(payload, dict):
                raise MalformedOutputPresetsError("output presets file must contain an object")
            version = payload.get("version")
            if version != _OUTPUT_PRESETS_SCHEMA_VERSION:
                raise MalformedOutputPresetsError(
                    f"unsupported output presets file version: {version!r}"
                )
            presets = payload.get("presets")
            if not isinstance(presets, list):
                raise MalformedOutputPresetsError("output presets file must contain a presets list")

            loaded = {}
            seen_names = {_name_key(preset["name"]): preset["id"] for preset in self._built_in_presets.values()}
            for index, entry in enumerate(presets):
                if not isinstance(entry, dict):
                    raise MalformedOutputPresetsError(
                        f"output preset entry {index} must be an object"
                    )
                try:
                    preset_id = _normalize_preset_id(
                        entry.get("id"),
                        field_name=f"presets[{index}].id",
                    )
                    name = _normalize_preset_name(
                        entry.get("name"),
                        field_name=f"presets[{index}].name",
                    )
                except OutputPresetValidationError as exc:
                    raise MalformedOutputPresetsError(
                        f"invalid output preset entry {index}"
                    ) from exc
                if preset_id in self._built_in_presets or preset_id in loaded:
                    raise DuplicateOutputPresetIdError(f"duplicate output preset id: {preset_id}")
                name_key = _name_key(name)
                if name_key in seen_names:
                    raise DuplicateOutputPresetNameError(f"duplicate output preset name: {name}")
                if entry.get("built_in"):
                    raise MalformedOutputPresetsError("persisted output presets cannot mark presets as built-in")
                try:
                    descriptor = normalize_output_descriptor_template(entry.get("descriptor"))
                except OutputPresetValidationError as exc:
                    raise MalformedOutputPresetsError(
                        f"invalid descriptor in output preset entry {index}"
                    ) from exc
                loaded[preset_id] = _preset_record(preset_id, name, descriptor, built_in=False)
                seen_names[name_key] = preset_id
            return loaded

    def _save_user_presets(self):
        with self._lock:
            payload = {
                "version": _OUTPUT_PRESETS_SCHEMA_VERSION,
                "presets": [
                    {
                        "id": preset["id"],
                        "name": preset["name"],
                        "descriptor": dict(preset["descriptor"]),
                    }
                    for preset in self._iter_sorted_user_presets()
                ],
            }
            _atomic_write_json(self.path, payload)

    def _assert_name_available(self, name, ignore_id=None):
        with self._lock:
            name_key = _name_key(name)
            for preset in self._built_in_presets.values():
                if preset["id"] != ignore_id and _name_key(preset["name"]) == name_key:
                    raise DuplicateOutputPresetNameError(f"output preset name already exists: {name}")
            for preset in self._user_presets.values():
                if preset["id"] != ignore_id and _name_key(preset["name"]) == name_key:
                    raise DuplicateOutputPresetNameError(f"output preset name already exists: {name}")

    def _iter_sorted_user_presets(self):
        with self._lock:
            return sorted(
                self._user_presets.values(),
                key=lambda preset: (_name_key(preset["name"]), preset["id"]),
            )


def _shared_store_lock(path):
    normalized_path = os.path.realpath(os.path.abspath(path))
    with _STORE_LOCKS_GUARD:
        lock = _STORE_LOCKS.get(normalized_path)
        if lock is None:
            lock = threading.RLock()
            _STORE_LOCKS[normalized_path] = lock
        return lock


@contextmanager
def _interprocess_store_lock(path):
    lock_path = os.path.realpath(os.path.abspath(path)) + ".lock"
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    handle = open(lock_path, "a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            locked = True
        yield
    finally:
        if locked and os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        elif locked:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _normalize_built_in_presets(built_in_presets):
    normalized = {}
    seen_names = {}
    for preset_id, name, descriptor_template in built_in_presets:
        preset_id = _normalize_preset_id(preset_id)
        if preset_id in normalized:
            raise DuplicateOutputPresetIdError(f"duplicate built-in output preset id: {preset_id}")
        normalized_name = _normalize_preset_name(name)
        name_key = _name_key(normalized_name)
        if name_key in seen_names:
            raise DuplicateOutputPresetNameError(
                f"duplicate built-in output preset name: {normalized_name}"
            )
        normalized[preset_id] = _preset_record(
            preset_id,
            normalized_name,
            normalize_output_descriptor_template(descriptor_template),
            built_in=True,
        )
        seen_names[name_key] = preset_id
    return normalized


def _preset_record(preset_id, name, descriptor, built_in):
    return {
        "id": preset_id,
        "name": name,
        "descriptor": dict(descriptor),
        "built_in": bool(built_in),
        "editable": not built_in,
        "deletable": not built_in,
    }


def _copy_preset(preset):
    return _preset_record(
        preset["id"],
        preset["name"],
        dict(preset["descriptor"]),
        preset["built_in"],
    )


def _generated_preset_id(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "preset"
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]
    return f"preset-{slug}-{digest}"


def _normalize_preset_id(value, field_name="preset_id"):
    if not isinstance(value, str):
        raise OutputPresetValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise OutputPresetValidationError(f"{field_name} cannot be empty")
    return normalized


def _normalize_preset_name(value, field_name="name"):
    if not isinstance(value, str):
        raise OutputPresetValidationError(f"{field_name} must be a string")
    normalized = " ".join(value.split())
    if not normalized:
        raise OutputPresetValidationError(f"{field_name} cannot be empty")
    return normalized


def _name_key(value):
    return value.casefold()


def _coerce_output_descriptor(template):
    if isinstance(template, OutputDescriptor):
        template.validate()
        return template
    if not isinstance(template, dict):
        raise OutputPresetValidationError("descriptor template must be a dict or OutputDescriptor")
    unknown = sorted(set(template) - _DESCRIPTOR_FIELDS)
    if unknown:
        raise OutputPresetValidationError(
            "descriptor template has unknown fields: " + ", ".join(unknown)
        )
    enabled = _resolve_enabled(template)
    if not enabled:
        descriptor = OutputDescriptor(
            enabled=False,
            physical_pixels=_coerce_int(template.get("physical_pixels", 0), "physical_pixels"),
            layout=_coerce_enum(template.get("layout", Layout.OFF), Layout, "layout"),
            rows=_coerce_int(template.get("rows", 0), "rows"),
            columns=_coerce_int(template.get("columns", 0), "columns"),
            traversal_axis=_coerce_enum(
                template.get("traversal_axis", TraversalAxis.ROW_MAJOR),
                TraversalAxis,
                "traversal_axis",
            ),
            scan_pattern=_coerce_enum(
                template.get("scan_pattern", ScanPattern.PROGRESSIVE),
                ScanPattern,
                "scan_pattern",
            ),
            start_corner=_coerce_enum(
                template.get("start_corner", StartCorner.TOP_LEFT),
                StartCorner,
                "start_corner",
            ),
            virtual_pixels=_coerce_int(template.get("virtual_pixels", 0), "virtual_pixels"),
        )
        return _validate_descriptor(descriptor)

    rows = _coerce_optional_int(template.get("rows"), "rows")
    columns = _coerce_optional_int(template.get("columns"), "columns")
    layout = _resolve_layout(template.get("layout"), rows, columns)
    physical_pixels = _coerce_optional_int(template.get("physical_pixels"), "physical_pixels")
    if physical_pixels is None:
        if layout == Layout.GRID and rows is not None and columns is not None:
            physical_pixels = rows * columns
        else:
            raise OutputPresetValidationError(
                "physical_pixels is required for enabled non-grid descriptors"
            )
    if layout == Layout.GRID:
        if rows is None or columns is None:
            raise OutputPresetValidationError("grid descriptors require rows and columns")
    else:
        rows = 0 if rows is None else rows
        columns = 0 if columns is None else columns
    scan_default = ScanPattern.SERPENTINE if layout == Layout.GRID else ScanPattern.PROGRESSIVE
    descriptor = OutputDescriptor(
        enabled=True,
        physical_pixels=physical_pixels,
        layout=layout,
        rows=rows if rows is not None else 0,
        columns=columns if columns is not None else 0,
        traversal_axis=_coerce_enum(
            template.get("traversal_axis", TraversalAxis.ROW_MAJOR),
            TraversalAxis,
            "traversal_axis",
        ),
        scan_pattern=_coerce_enum(
            template.get("scan_pattern", scan_default),
            ScanPattern,
            "scan_pattern",
        ),
        start_corner=_coerce_enum(
            template.get("start_corner", StartCorner.TOP_LEFT),
            StartCorner,
            "start_corner",
        ),
        virtual_pixels=_coerce_int(
            template.get("virtual_pixels", physical_pixels),
            "virtual_pixels",
        ),
    )
    return _validate_descriptor(descriptor)


def _resolve_enabled(template):
    if "enabled" in template:
        return _coerce_bool(template.get("enabled"), "enabled")
    layout = template.get("layout")
    if layout is not None:
        return _coerce_enum(layout, Layout, "layout") != Layout.OFF
    for key in ("physical_pixels", "rows", "columns", "virtual_pixels"):
        value = template.get(key)
        if value is not None and _coerce_int(value, key) > 0:
            return True
    raise OutputPresetValidationError(
        "descriptor template must specify enabled, layout, or pixel dimensions"
    )


def _resolve_layout(layout_value, rows, columns):
    if layout_value is not None:
        return _coerce_enum(layout_value, Layout, "layout")
    if rows not in (None, 0) or columns not in (None, 0):
        return Layout.GRID
    return Layout.LINEAR


def _validate_descriptor(descriptor):
    try:
        descriptor.validate()
    except ValueError as exc:
        raise OutputPresetValidationError(str(exc)) from exc
    return descriptor


def _descriptor_to_dict(descriptor):
    return {
        "enabled": bool(descriptor.enabled),
        "physical_pixels": int(descriptor.physical_pixels),
        "layout": descriptor.layout.name.lower(),
        "rows": int(descriptor.rows),
        "columns": int(descriptor.columns),
        "traversal_axis": descriptor.traversal_axis.name.lower(),
        "scan_pattern": descriptor.scan_pattern.name.lower(),
        "start_corner": descriptor.start_corner.name.lower(),
        "virtual_pixels": int(descriptor.virtual_pixels),
    }


def _coerce_enum(value, enum_cls, field_name):
    if isinstance(value, enum_cls):
        return value
    try:
        if isinstance(value, str):
            name = value.strip()
            if not name:
                raise ValueError
            name = name.rsplit(".", 1)[-1].upper()
            return enum_cls[name]
        if isinstance(value, bool):
            raise ValueError
        return enum_cls(int(value))
    except (KeyError, TypeError, ValueError) as exc:
        raise OutputPresetValidationError(
            f"{field_name} must be one of {[member.name.lower() for member in enum_cls]}"
        ) from exc


def _coerce_bool(value, field_name):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in ("1", "true", "yes", "on"):
            return True
        if normalized in ("0", "false", "no", "off"):
            return False
    raise OutputPresetValidationError(f"{field_name} must be a boolean")


def _coerce_optional_int(value, field_name):
    if value is None:
        return None
    return _coerce_int(value, field_name)


def _coerce_int(value, field_name):
    if isinstance(value, bool):
        raise OutputPresetValidationError(f"{field_name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text and re.fullmatch(r"-?\d+", text):
            return int(text)
    raise OutputPresetValidationError(f"{field_name} must be an integer")


def _atomic_write_json(path, payload):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temp_dir = directory or "."
    fd, temp_path = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.tmp-",
        dir=temp_dir,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_path, path)
    except Exception:
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except OSError:
            pass
        raise


BUILT_IN_OUTPUT_PRESETS = tuple(
    _copy_preset(_normalize_built_in_presets(_DEF_BUILTIN_PRESETS)[preset_id])
    for preset_id, _, _ in _DEF_BUILTIN_PRESETS
)


__all__ = [
    "BUILT_IN_OUTPUT_PRESETS",
    "BuiltInOutputPresetError",
    "DuplicateOutputPresetIdError",
    "DuplicateOutputPresetNameError",
    "MalformedOutputPresetsError",
    "OUTPUT_PRESETS_FILE",
    "OutputPresetError",
    "OutputPresetNotFoundError",
    "OutputPresetStore",
    "OutputPresetValidationError",
    "normalize_output_descriptor_template",
]
