"""
sharing.py — Portable Clip and Look import/export bundles.
"""

import copy
import re
import uuid
from datetime import datetime, timezone

import clips
import mixer


EXPORT_SCHEMA = "primus.v3.6.bundle"
EXPORT_VERSION = 1
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _slug(value, fallback="primus"):
    text = str(value or fallback).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or fallback


def _safe_resource_id(value):
    text = str(value or "").strip()
    return text if _SAFE_ID_RE.match(text) else ""


def _copy_dict(value):
    return copy.deepcopy(value or {})


def _clip_ids_for_look(look):
    ids = []
    seen = set()
    for track in look.get("tracks", []) or []:
        for segment in track.get("segments", []) or []:
            clip_id = str(segment.get("clip_id") or "").strip()
            if clip_id and clip_id not in seen:
                seen.add(clip_id)
                ids.append(clip_id)
    return ids


def export_filename(bundle):
    kind = bundle.get("kind")
    if kind == "clip":
        name = (bundle.get("clip") or {}).get("name")
        return f"primus-clip-{_slug(name, 'clip')}.json"
    if kind == "look":
        name = (bundle.get("look") or {}).get("name")
        return f"primus-look-{_slug(name, 'look')}.json"
    return "primus-export.json"


def export_clip_bundle(clip_id):
    clip = clips.load_clip(clip_id)
    if not clip:
        return None
    return {
        "schema": EXPORT_SCHEMA,
        "version": EXPORT_VERSION,
        "kind": "clip",
        "created": _now(),
        "clip": _copy_dict(clip),
    }


def export_look_bundle(look_id):
    look = mixer.load_look(look_id)
    if not look:
        return None

    bundled_clips = []
    missing_clip_ids = []
    for clip_id in _clip_ids_for_look(look):
        clip = clips.load_clip(clip_id)
        if clip:
            bundled_clips.append(_copy_dict(clip))
        else:
            missing_clip_ids.append(clip_id)

    return {
        "schema": EXPORT_SCHEMA,
        "version": EXPORT_VERSION,
        "kind": "look",
        "created": _now(),
        "look": _copy_dict(look),
        "clips": bundled_clips,
        "missing_clip_ids": missing_clip_ids,
    }


def _normalize_bundle(data):
    if not isinstance(data, dict):
        raise ValueError("Import file must contain a JSON object")
    if data.get("schema") == EXPORT_SCHEMA:
        return data
    if data.get("kind") in {"clip", "look"}:
        return data
    if data.get("output_type") and data.get("effect"):
        return {"kind": "clip", "clip": data}
    if data.get("tracks") is not None and data.get("outputs") is not None:
        return {"kind": "look", "look": data, "clips": []}
    raise ValueError("Import file is not a Primus Clip or Look export")


def _unique_clip_id(preferred_id):
    safe_id = _safe_resource_id(preferred_id)
    if safe_id and not clips.load_clip(safe_id):
        return safe_id
    return str(uuid.uuid4())


def _unique_look_id(preferred_id):
    safe_id = _safe_resource_id(preferred_id)
    if safe_id and not mixer.load_look(safe_id):
        return safe_id
    return str(uuid.uuid4())


def _import_clip(clip_data):
    if not isinstance(clip_data, dict):
        raise ValueError("Clip import is missing clip data")
    original_id = str(clip_data.get("id") or "").strip()
    clip = _copy_dict(clip_data)
    clip["id"] = _unique_clip_id(original_id)
    saved = clips.save_clip(clip)
    return saved, original_id


def _remap_look_clip_ids(look, clip_id_map):
    for track in look.get("tracks", []) or []:
        for segment in track.get("segments", []) or []:
            clip_id = segment.get("clip_id")
            if clip_id in clip_id_map:
                segment["clip_id"] = clip_id_map[clip_id]


def import_bundle(data):
    bundle = _normalize_bundle(data)
    kind = bundle.get("kind")

    if kind == "clip":
        saved, original_id = _import_clip(bundle.get("clip"))
        return {
            "ok": True,
            "kind": "clip",
            "clip": saved,
            "clips_imported": 1,
            "clip_id_map": {original_id: saved["id"]} if original_id else {},
        }

    if kind != "look":
        raise ValueError("Import kind must be clip or look")

    look_data = bundle.get("look")
    if not isinstance(look_data, dict):
        raise ValueError("Look import is missing look data")

    clip_id_map = {}
    imported_clips = []
    for clip_data in bundle.get("clips", []) or []:
        saved_clip, original_id = _import_clip(clip_data)
        imported_clips.append(saved_clip)
        if original_id:
            clip_id_map[original_id] = saved_clip["id"]

    look = _copy_dict(look_data)
    original_look_id = str(look.get("id") or "").strip()
    look["id"] = _unique_look_id(original_look_id)
    look["device_ips"] = []
    _remap_look_clip_ids(look, clip_id_map)
    saved_look = mixer.save_look(look)

    return {
        "ok": True,
        "kind": "look",
        "look": saved_look,
        "clips": imported_clips,
        "clips_imported": len(imported_clips),
        "clip_id_map": clip_id_map,
        "look_id_map": {original_look_id: saved_look["id"]} if original_look_id else {},
        "missing_clip_ids": bundle.get("missing_clip_ids", []) or [],
    }