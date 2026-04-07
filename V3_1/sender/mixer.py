"""
mixer.py — Look data model, timeline engine, per-pixel crossfade.
"""

import json
import os
import uuid
from datetime import datetime, timezone

from clips import load_clip
from effects import EFFECTS, fx_none, compute_anim_factor, blend_pixels
from state import OUTPUT_TYPES


def _looks_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "looks")


def _ensure_dir():
    d = _looks_dir()
    os.makedirs(d, exist_ok=True)
    return d


# ======================================================================
#  LOOK CRUD
# ======================================================================

def new_look(name, outputs, description=""):
    """Create a new Look dict.

    `outputs` is a list like [{"port": "A0", "type": "grid"}, ...]
    """
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "description": description,
        "outputs": outputs,
        "tracks": [{"port": o["port"], "segments": []} for o in outputs],
        "playback": "loop",
        "total_duration": 10.0,
        "created": datetime.now(timezone.utc).isoformat(),
        "modified": datetime.now(timezone.utc).isoformat(),
    }


def save_look(look):
    d = _ensure_dir()
    if not look.get("id"):
        look["id"] = str(uuid.uuid4())
    look["modified"] = datetime.now(timezone.utc).isoformat()
    if not look.get("created"):
        look["created"] = look["modified"]
    path = os.path.join(d, f"{look['id']}.json")
    with open(path, "w") as f:
        json.dump(look, f, indent=2)
    return look


def load_look(look_id):
    path = os.path.join(_looks_dir(), f"{look_id}.json")
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def delete_look(look_id):
    path = os.path.join(_looks_dir(), f"{look_id}.json")
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def list_looks(sort_by="modified"):
    d = _looks_dir()
    if not os.path.isdir(d):
        return []
    looks = []
    for fname in os.listdir(d):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(d, fname)
        try:
            with open(path, "r") as f:
                look = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        looks.append(look)
    reverse = sort_by in ("modified", "created")
    looks.sort(key=lambda l: l.get(sort_by, ""), reverse=reverse)
    return looks


# ======================================================================
#  TIMELINE ENGINE
# ======================================================================

def _wrap_time(t, total_duration, playback):
    """Map absolute time to local time within the look."""
    if total_duration <= 0:
        return 0.0
    if playback == "once":
        return min(t, total_duration)
    elif playback == "boomerang":
        cyc = t % (total_duration * 2)
        return cyc if cyc <= total_duration else total_duration * 2 - cyc
    else:  # loop
        return t % total_duration


def _compute_segment_pixels(segment, local_t, pixel_count, grid, fps=30,
                            clip_cache=None, state_cache=None):
    """Compute pixel output for one segment at local time."""
    clip_id = segment["clip_id"]
    seg_id = segment.get("id", clip_id)

    # Use cache to avoid disk reads every frame
    if clip_cache is not None and clip_id in clip_cache:
        clip = clip_cache[clip_id]
    else:
        clip = load_clip(clip_id)
        if clip_cache is not None and clip is not None:
            clip_cache[clip_id] = clip
    if clip is None:
        return [(0, 0, 0)] * pixel_count

    effect_name = clip.get("effect", "none")
    fn = EFFECTS.get(effect_name, fx_none)
    speed = clip.get("speed", 1.0)
    scaled_t = local_t * speed
    af = compute_anim_factor(scaled_t, clip.get("playback", "loop"))

    # Preserve per-segment effect state (for stateful effects like constrainbow)
    if state_cache is not None:
        if seg_id not in state_cache:
            state_cache[seg_id] = []
        state = state_cache[seg_id]
    else:
        state = []

    return fn(
        count=pixel_count, t=scaled_t, dt=1.0 / max(fps, 1),
        speed=speed, anim_factor=af,
        playback=clip.get("playback", "loop"),
        start_color=tuple(clip.get("start_color", (255, 0, 255))),
        end_color=tuple(clip.get("end_color", (0, 255, 255))),
        state=state,
        grid=grid, angle=clip.get("angle", 0),
        highlight_width=clip.get("highlight_width", 5),
        chase_origin=clip.get("chase_origin", "start"),
    )


def _segment_fade_factor(segment, local_t):
    """Compute fade envelope for a segment at local time within segment."""
    duration = segment.get("duration", 5.0)
    fade_in = segment.get("fade_in", 0.0)
    fade_out = segment.get("fade_out", 0.0)

    if duration <= 0:
        return 1.0

    factor = 1.0
    if fade_in > 0 and local_t < fade_in:
        factor = min(factor, local_t / fade_in)
    if fade_out > 0 and local_t > duration - fade_out:
        remaining = duration - local_t
        factor = min(factor, max(remaining / fade_out, 0.0))
    return max(0.0, min(1.0, factor))


def compute_look_frame(look, t, fps=30, clip_cache=None, state_cache=None):
    """Compute pixel buffers for all tracks at time `t`.

    Returns a list of pixel lists, one per output/track.
    Each pixel list is [(r,g,b), ...] or empty if the output type is 'none'.
    """
    if clip_cache is None:
        clip_cache = {}
    if state_cache is None:
        state_cache = {}

    total_duration = look.get("total_duration", 10.0)
    playback = look.get("playback", "loop")
    local_t = _wrap_time(t, total_duration, playback)

    outputs = look.get("outputs", [])
    tracks = look.get("tracks", [])
    result = []

    for track_idx, track in enumerate(tracks):
        # Determine pixel count and grid from output config
        if track_idx < len(outputs):
            otype = outputs[track_idx].get("type", "none")
        else:
            otype = "none"
        typedef = OUTPUT_TYPES.get(otype, {"pixels": 0, "layout": "none"})
        pixel_count = typedef["pixels"]
        grid = typedef.get("grid_size") if typedef["layout"] == "grid" else None

        if pixel_count == 0:
            result.append([])
            continue

        # Find active segments at local_t
        active = []
        for seg in track.get("segments", []):
            seg_start = seg.get("start_time", 0.0)
            seg_duration = seg.get("duration", 5.0)
            if seg_start <= local_t < seg_start + seg_duration:
                active.append(seg)

        if not active:
            result.append([(0, 0, 0)] * pixel_count)
            continue

        # Compute pixels for each active segment, blend if overlapping
        blended = None
        for seg in active:
            seg_local_t = local_t - seg.get("start_time", 0.0)
            pixels = _compute_segment_pixels(seg, seg_local_t, pixel_count, grid,
                                             fps=fps, clip_cache=clip_cache,
                                             state_cache=state_cache)
            fade = _segment_fade_factor(seg, seg_local_t)

            # Apply fade envelope
            if fade < 1.0:
                black = [(0, 0, 0)] * pixel_count
                pixels = blend_pixels(black, pixels, fade)

            if blended is None:
                blended = pixels
            else:
                # Crossfade: average overlapping segments
                blended = blend_pixels(blended, pixels, 0.5)

        result.append(blended or [(0, 0, 0)] * pixel_count)

    return result
