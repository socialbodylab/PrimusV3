"""
audio_cues.py — Sender-side audio cue sheet and project audio library.

Cue sheet:   audio_cues.json   (in sender data directory)
Audio files: audio/            (WAV files imported into the project)
Temp files:  audio/.tmp/       (staged during pull conflict resolution)
Checksums:   audio/.checksums.json
"""

import hashlib
import json
import os
import threading

from paths import data_path


_CUES_FILE     = data_path("audio_cues.json")
_AUDIO_DIR     = data_path("audio")
_TMP_DIR       = data_path("audio", ".tmp")
_CHECKSUM_FILE = data_path("audio", ".checksums.json")

_checksum_lock  = threading.Lock()
_checksum_cache = None  # loaded lazily; protected by _checksum_lock


class ChecksumConflictError(ValueError):
    """Raised when saving a file whose name already exists with different content."""


# ── Directory setup ────────────────────────────────────────────────────────────

def _ensure_audio_dirs():
    os.makedirs(_AUDIO_DIR, exist_ok=True)
    os.makedirs(_TMP_DIR,   exist_ok=True)

# Alias for callers that used the old name
_ensure_audio_dir = _ensure_audio_dirs


# ── Checksum cache ─────────────────────────────────────────────────────────────

def _load_checksum_cache():
    """Load checksum cache from disk (call under _checksum_lock)."""
    global _checksum_cache
    if _checksum_cache is not None:
        return _checksum_cache
    try:
        with open(_CHECKSUM_FILE, "r") as f:
            _checksum_cache = json.load(f)
    except (OSError, json.JSONDecodeError):
        _checksum_cache = {}
    return _checksum_cache


def _save_checksum_cache():
    """Flush checksum cache to disk (call under _checksum_lock)."""
    try:
        with open(_CHECKSUM_FILE, "w") as f:
            json.dump(_checksum_cache, f)
    except OSError:
        pass


def _compute_checksum(path):
    """SHA-256 of a file on disk. Returns 'sha256:<hex>'."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def checksum_bytes(data):
    """SHA-256 of raw bytes. Returns 'sha256:<hex>'."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _get_cached_checksum(filename):
    """Return checksum for a library file, computing and caching it if missing."""
    with _checksum_lock:
        cache = _load_checksum_cache()
        if filename in cache:
            return cache[filename]
        path = os.path.join(_AUDIO_DIR, filename)
        if not os.path.isfile(path):
            return None
        checksum = _compute_checksum(path)
        cache[filename] = checksum
        _save_checksum_cache()
        return checksum


def _set_cached_checksum(filename, checksum):
    with _checksum_lock:
        cache = _load_checksum_cache()
        cache[filename] = checksum
        _save_checksum_cache()


def _remove_cached_checksum(filename):
    with _checksum_lock:
        cache = _load_checksum_cache()
        if filename in cache:
            del cache[filename]
            _save_checksum_cache()


# ── Cue sheet ──────────────────────────────────────────────────────────────────

def load_audio_cues():
    """Return cue sheet dict, or empty default."""
    try:
        with open(_CUES_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and "cues" in data:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"cues": []}


_DEVICE_CUE_CMDS = {"play", "loop", "stop", "volume"}


def derive_device_cue_map(cues, ip):
    """Derive /cues.json content for one device from the sender cue sheet.

    Returns {str(number): entry_dict} ready for JSON upload to the device SD.
    Entries with cmd="none", unknown cmd, or play/loop with empty filename are
    excluded. stop and volume entries require no filename. All other fields
    (volume, duration) are included only when present and non-zero.
    """
    result = {}
    for cue in cues:
        number = cue.get("number")
        if number is None:
            continue
        action = cue.get("actions", {}).get(ip)
        if action is None:
            continue
        cmd = str(action.get("cmd", "none"))
        if cmd not in _DEVICE_CUE_CMDS:
            continue
        entry = {"cmd": cmd}
        if cmd in ("play", "loop"):
            filename = str(action.get("filename", ""))
            if not filename:
                continue
            entry["file"] = filename
        volume = action.get("volume")
        if volume is not None:
            entry["volume"] = int(volume)
        duration = action.get("duration")
        if duration:
            entry["duration"] = int(duration)
        delay = action.get("delay")
        if delay:
            entry["delay"] = int(delay)
        result[str(number)] = entry
    return result


def save_audio_cues(data):
    """Write cue sheet to disk."""
    try:
        with open(_CUES_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


# ── Project audio library ──────────────────────────────────────────────────────

def list_project_audio():
    """Return sorted list of {name, size, checksum} for WAV files in audio/."""
    _ensure_audio_dirs()
    results = []
    try:
        for name in sorted(os.listdir(_AUDIO_DIR)):
            if not name.lower().endswith(".wav") or name.startswith("."):
                continue
            path = os.path.join(_AUDIO_DIR, name)
            if not os.path.isfile(path):
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            checksum = _get_cached_checksum(name)
            results.append({"name": name, "size": size, "checksum": checksum})
    except OSError:
        pass
    return results


def save_project_audio(filename, data):
    """Write a WAV to the project library. Returns sanitized filename.

    Raises ChecksumConflictError if the filename already exists with different
    content. Raises ValueError for invalid filenames or non-WAV data.
    """
    _ensure_audio_dirs()
    filename = os.path.basename(filename)
    if not filename.lower().endswith(".wav"):
        raise ValueError("Only WAV files accepted")
    if "\x00" in filename:
        raise ValueError("Invalid filename")

    incoming_checksum = checksum_bytes(data)
    path = os.path.join(_AUDIO_DIR, filename)

    if os.path.isfile(path):
        existing_checksum = _get_cached_checksum(filename)
        if existing_checksum == incoming_checksum:
            return filename  # identical content — no-op
        raise ChecksumConflictError(
            f"{filename} already exists with different content"
        )

    with open(path, "wb") as f:
        f.write(data)
    _set_cached_checksum(filename, incoming_checksum)
    return filename


def delete_project_audio(filename):
    """Remove a file from the project library. Returns True if removed."""
    _ensure_audio_dirs()
    filename = os.path.basename(filename)
    path = os.path.join(_AUDIO_DIR, filename)
    if os.path.isfile(path):
        os.remove(path)
        _remove_cached_checksum(filename)
        return True
    return False


def get_project_audio_path(filename):
    """Return absolute path to a project audio file, or None if not found."""
    filename = os.path.basename(filename)
    path = os.path.join(_AUDIO_DIR, filename)
    return path if os.path.isfile(path) else None


# ── Temp file staging (pull conflict resolution) ───────────────────────────────

def _temp_filename(checksum):
    """Map a checksum string to a safe temp filename."""
    # Use the hex digits only (strip 'sha256:' prefix)
    digest = checksum.replace("sha256:", "")[:16]
    return digest + ".wav"


def save_project_audio_temp(checksum, data):
    """Save downloaded bytes to a temp path keyed by checksum.

    Returns the absolute temp path. Used to stage conflicting file versions
    during a pull job until the user resolves them.
    """
    _ensure_audio_dirs()
    name = _temp_filename(checksum)
    path = os.path.join(_TMP_DIR, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


def get_project_audio_temp_path(checksum):
    """Return the temp path for a given checksum, or None if not staged."""
    name = _temp_filename(checksum)
    path = os.path.join(_TMP_DIR, name)
    return path if os.path.isfile(path) else None


def discard_project_audio_temp(checksum):
    """Delete a staged temp file. Returns True if it existed."""
    path = get_project_audio_temp_path(checksum)
    if path and os.path.isfile(path):
        os.remove(path)
        return True
    return False


def resolve_project_audio_temp(checksum, save_as):
    """Move a staged temp file into the library under save_as.

    Raises ChecksumConflictError if save_as already exists with different
    content. Raises FileNotFoundError if the temp file is not found.
    """
    temp_path = get_project_audio_temp_path(checksum)
    if not temp_path:
        raise FileNotFoundError(f"No staged temp file for checksum {checksum}")

    save_as = os.path.basename(save_as)
    dest = os.path.join(_AUDIO_DIR, save_as)

    if os.path.isfile(dest):
        existing = _get_cached_checksum(save_as)
        if existing != checksum:
            raise ChecksumConflictError(
                f"{save_as} already exists with different content"
            )
        # Already the right content — discard temp and return
        os.remove(temp_path)
        return save_as

    os.rename(temp_path, dest)
    _set_cached_checksum(save_as, checksum)
    return save_as
