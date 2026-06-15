"""
audio_cues.py — Sender-side audio cue sheet and project audio library.

Cue sheet:  audio_cues.json  (in the same directory as this file)
Audio files: audio/           (WAV files imported into the project)
"""

import json
import os

_BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
_CUES_FILE = os.path.join(_BASE_DIR, "audio_cues.json")
_AUDIO_DIR = os.path.join(_BASE_DIR, "audio")


def _ensure_audio_dir():
    os.makedirs(_AUDIO_DIR, exist_ok=True)


# ── Cue sheet ──────────────────────────────────────────────────────────────

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


def save_audio_cues(data):
    """Write cue sheet to disk."""
    try:
        with open(_CUES_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


# ── Project audio library ──────────────────────────────────────────────────

def list_project_audio():
    """Return sorted list of {name, size} for WAV files in audio/ dir."""
    _ensure_audio_dir()
    results = []
    try:
        for name in sorted(os.listdir(_AUDIO_DIR)):
            if name.lower().endswith(".wav") and not name.startswith("."):
                path = os.path.join(_AUDIO_DIR, name)
                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = 0
                results.append({"name": name, "size": size})
    except OSError:
        pass
    return results


def save_project_audio(filename, data):
    """Write a WAV file to the project library. Returns sanitized filename."""
    _ensure_audio_dir()
    filename = os.path.basename(filename)
    if not filename.lower().endswith(".wav"):
        raise ValueError("Only WAV files accepted")
    if "\x00" in filename:
        raise ValueError("Invalid filename")
    path = os.path.join(_AUDIO_DIR, filename)
    with open(path, "wb") as f:
        f.write(data)
    return filename


def delete_project_audio(filename):
    """Remove a file from the project library. Returns True if removed."""
    _ensure_audio_dir()
    filename = os.path.basename(filename)
    path = os.path.join(_AUDIO_DIR, filename)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


def get_project_audio_path(filename):
    """Return absolute path to a project audio file, or None if not found."""
    filename = os.path.basename(filename)
    path = os.path.join(_AUDIO_DIR, filename)
    return path if os.path.isfile(path) else None
