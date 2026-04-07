"""
clips.py — Clip data model, save/load/delete/list, library queries.
"""

import json
import os
import uuid
from datetime import datetime, timezone


def _clips_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "clips")


def _ensure_dir():
    d = _clips_dir()
    os.makedirs(d, exist_ok=True)
    return d


# ======================================================================
#  CLIP DEFAULTS
# ======================================================================

DEFAULT_CLIP = {
    "effect": "pulse",
    "start_color": [255, 0, 255],
    "end_color": [0, 255, 255],
    "speed": 1.0,
    "playback": "loop",
    "angle": 0,
    "highlight_width": 5,
    "chase_origin": "start",
    "duration": 5.0,
}


# ======================================================================
#  CLIP CRUD
# ======================================================================

def new_clip(name, output_type, group=None, **overrides):
    """Create a new clip dict with defaults."""
    clip = {
        "id": str(uuid.uuid4()),
        "name": name,
        "group": group or name,
        "output_type": output_type,
        **DEFAULT_CLIP,
        "created": datetime.now(timezone.utc).isoformat(),
        "modified": datetime.now(timezone.utc).isoformat(),
    }
    for k, v in overrides.items():
        if k in clip:
            clip[k] = v
    return clip


def save_clip(clip):
    """Write clip JSON to clips/{id}.json. Returns the clip."""
    d = _ensure_dir()
    clip["modified"] = datetime.now(timezone.utc).isoformat()
    path = os.path.join(d, f"{clip['id']}.json")
    with open(path, "w") as f:
        json.dump(clip, f, indent=2)
    return clip


def load_clip(clip_id):
    """Load a clip by ID. Returns dict or None."""
    path = os.path.join(_clips_dir(), f"{clip_id}.json")
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def delete_clip(clip_id):
    """Delete a clip file. Returns True if deleted."""
    path = os.path.join(_clips_dir(), f"{clip_id}.json")
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def list_clips(filter_type=None, search=None, sort_by="modified"):
    """List all clips, with optional filtering and sorting."""
    d = _clips_dir()
    if not os.path.isdir(d):
        return []
    clips = []
    for fname in os.listdir(d):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(d, fname)
        try:
            with open(path, "r") as f:
                clip = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if filter_type and clip.get("output_type") != filter_type:
            continue
        if search and search.lower() not in clip.get("name", "").lower():
            continue
        clips.append(clip)
    reverse = sort_by in ("modified", "created")
    clips.sort(key=lambda c: c.get(sort_by, ""), reverse=reverse)
    return clips


def save_from_designer(name, outputs):
    """Save multi-output design as individual clips.

    `outputs` is a list of dicts like:
        [{"type": "grid", "effect": "spiral", "start_color": ..., ...}, ...]

    Returns list of saved clips.
    """
    saved = []
    type_counts = {}
    for out in outputs:
        otype = out.get("type", "none")
        if otype == "none":
            continue
        type_counts[otype] = type_counts.get(otype, 0) + 1
        n = type_counts[otype]
        clip_name = f"{name}_{otype}{n}"
        clip = new_clip(
            name=clip_name,
            output_type=otype,
            group=name,
            effect=out.get("effect", "pulse"),
            start_color=out.get("start_color", [255, 0, 255]),
            end_color=out.get("end_color", [0, 255, 255]),
            speed=out.get("speed", 1.0),
            playback=out.get("playback", "loop"),
            angle=out.get("angle", 0),
            highlight_width=out.get("highlight_width", 5),
            chase_origin=out.get("chase_origin", "start"),
            duration=out.get("duration", 5.0),
        )
        save_clip(clip)
        saved.append(clip)
    return saved
