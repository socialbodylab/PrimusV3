"""
controller.py — Look Controller: control panel activation, cue list,
per-pixel crossfade engine, and auto-follow.
"""

import json
import os
import threading
import time

from mixer import load_look
from paths import cues_file


_DEVICE_IPS_UNSET = object()


def _cues_file():
    return cues_file()


def _normalize_device_ips(values):
    ips = []
    seen = set()
    for value in values or []:
        ip = str(value).strip()
        if not ip or ip in seen:
            continue
        seen.add(ip)
        ips.append(ip)
    return set(ips)


class CueList:
    """Theatre-style cue list with crossfade and direct look activation."""

    def __init__(self):
        self.lock = threading.Lock()
        self.cues = []           # [{"number": 1, "look_id": "...", "name": "...", ...}, ...]
        self.current_index = -1  # -1 = no cue active
        self.playing = False
        self.play_start_time = 0.0

        # Active look (may be set by cue GO or direct control-panel activation)
        self._active_look_id = None
        self._active_control_looks = []

        # Device targeting: set of IP strings, or None = all devices
        self._active_device_ips = None

        # Crossfade state
        self._prev_look_id = None
        self._transition_start = 0.0
        self._transition_duration = 0.0  # 0 = instant cut

        # Auto-follow
        self._auto_follow_time = 0.0  # monotonic time when auto-GO fires, 0 = disabled

        # Blackout
        self._blackout = False
        self._blackout_fade_start = 0.0
        self._blackout_fade_duration = 0.0

        self._load()

    # ------------------------------------------------------------------
    #  Persistence
    # ------------------------------------------------------------------

    def _load(self):
        path = _cues_file()
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self.cues = data.get("cues", [])
        except (OSError, json.JSONDecodeError):
            self.cues = []

    def save(self):
        path = _cues_file()
        with self.lock:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump({"cues": self.cues}, f, indent=2)

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------

    def _look_device_ips(self, look):
        if not isinstance(look, dict) or "device_ips" not in look:
            return None
        return _normalize_device_ips(look.get("device_ips"))

    def _target_union(self, entries):
        if any(entry.get("device_ips") is None for entry in entries):
            return None
        out = set()
        for entry in entries:
            out.update(entry.get("device_ips") or set())
        return out

    def _resolve_device_ips(self, cue, device_groups, look=None):
        """Resolve cue/Look device targeting to a set of IP strings or None."""
        if cue.get("target_mode") == "all":
            return None

        gid = cue.get("device_group_id")
        if gid:
            for g in device_groups or []:
                if g.get("id") == gid:
                    ips = g.get("device_ips", [])
                    return _normalize_device_ips(ips)
            return set()  # group was deleted or has not loaded
        if cue.get("target_mode") == "group":
            return set()

        if cue.get("target_mode") == "devices" or (
                "device_ips" in cue and cue.get("target_mode") != "look"):
            return _normalize_device_ips(cue.get("device_ips"))

        return self._look_device_ips(look)

    def _start_transition(self, new_look_id, fade_time):
        """Begin crossfade from current look to new_look_id."""
        now = time.monotonic()
        if self._active_look_id and self._active_look_id != new_look_id and fade_time > 0:
            self._prev_look_id = self._active_look_id
            self._transition_start = now
            self._transition_duration = fade_time
        else:
            self._prev_look_id = None
            self._transition_start = 0.0
            self._transition_duration = 0.0
        self._active_look_id = new_look_id
        self._blackout = False

    def _setup_auto_follow(self, cue):
        """Schedule auto-follow if cue has it enabled."""
        if cue.get("auto_follow") and cue.get("follow_delay", 0) > 0:
            self._auto_follow_time = time.monotonic() + cue["follow_delay"]
        else:
            self._auto_follow_time = 0.0

    # ------------------------------------------------------------------
    #  Cue list queries
    # ------------------------------------------------------------------

    def get_json(self):
        with self.lock:
            elapsed = 0.0
            if self.playing and self.play_start_time > 0:
                elapsed = round(time.monotonic() - self.play_start_time, 1)
            xf_progress = self._crossfade_progress_unlocked()
            return {
                "cues": list(self.cues),
                "current_index": self.current_index,
                "playing": self.playing,
                "elapsed": elapsed,
                "active_look_id": self._active_look_id,
                "active_look_ids": [
                    entry["look_id"] for entry in self._active_control_looks
                ] if self._active_control_looks else (
                    [self._active_look_id] if self._active_look_id and self.playing else []
                ),
                "crossfade_active": self._prev_look_id is not None and xf_progress < 1.0,
                "crossfade_progress": xf_progress,
                "blackout": self._blackout,
            }

    def set_cues(self, cues):
        """Replace the entire cue list."""
        with self.lock:
            self.cues = list(cues)
            self.current_index = -1
            self.playing = False
            self._auto_follow_time = 0.0
        self.save()

    # ------------------------------------------------------------------
    #  Direct look activation (Control Panel)
    # ------------------------------------------------------------------

    def activate_look(self, look_id, fade_time=0.0, device_ips=_DEVICE_IPS_UNSET):
        """Directly activate a look (bypasses cue list). Returns True/False."""
        return self._activate_look_legacy(look_id, fade_time=fade_time, device_ips=device_ips)

    def activate_looks(self, look_ids, fade_time=0.0, device_ips=_DEVICE_IPS_UNSET):
        """Activate one or more Looks from the Control Panel."""
        entries = []
        now = time.monotonic()
        seen = set()
        for look_id in look_ids or []:
            look_id = str(look_id).strip()
            if not look_id or look_id in seen:
                continue
            seen.add(look_id)
            look = load_look(look_id)
            if look is None:
                continue
            if device_ips is _DEVICE_IPS_UNSET:
                resolved_device_ips = self._look_device_ips(look)
            elif device_ips is None:
                resolved_device_ips = None
            else:
                resolved_device_ips = _normalize_device_ips(device_ips)
            entries.append({
                "look_id": look_id,
                "device_ips": resolved_device_ips,
                "start_time": now,
            })
        if not entries:
            return False

        with self.lock:
            self._active_control_looks = entries
            self._active_look_id = entries[0]["look_id"]
            self._active_device_ips = self._target_union(entries)
            self._prev_look_id = None
            self._transition_start = 0.0
            self._transition_duration = 0.0
            self.playing = True
            self.play_start_time = now
            self._auto_follow_time = 0.0
            self._blackout = False
            return True

    def deactivate_look(self, look_id):
        """Remove one Control Panel Look from the active set."""
        with self.lock:
            if not self._active_control_looks:
                if self._active_look_id == look_id:
                    self._active_look_id = None
                    self._active_device_ips = None
                    self.playing = False
                    self.play_start_time = 0.0
                    self._prev_look_id = None
                    self._transition_start = 0.0
                    self._transition_duration = 0.0
                return True
            self._active_control_looks = [
                entry for entry in self._active_control_looks
                if entry["look_id"] != look_id
            ]
            if self._active_control_looks:
                self._active_look_id = self._active_control_looks[0]["look_id"]
                self._active_device_ips = self._target_union(self._active_control_looks)
            else:
                self._active_look_id = None
                self._active_device_ips = None
                self.playing = False
                self.play_start_time = 0.0
            return True

    def active_look_ids(self):
        with self.lock:
            if self._active_control_looks:
                return [entry["look_id"] for entry in self._active_control_looks]
            if self.playing and self._active_look_id:
                return [self._active_look_id]
            return []

    def _activate_look_legacy(self, look_id, fade_time=0.0, device_ips=_DEVICE_IPS_UNSET):
        """Activate a single Look using the older crossfade path."""
        look = load_look(look_id)
        if look is None:
            return False
        if device_ips is _DEVICE_IPS_UNSET:
            resolved_device_ips = self._look_device_ips(look)
        elif device_ips is None:
            resolved_device_ips = None
        else:
            resolved_device_ips = _normalize_device_ips(device_ips)
        with self.lock:
            self._active_control_looks = []
            self._start_transition(look_id, fade_time)
            self._active_device_ips = resolved_device_ips
            self.playing = True
            self.play_start_time = time.monotonic()
            # Don't change cue index — control panel is independent
            self._auto_follow_time = 0.0
            return True

    def blackout(self, fade_time=0.0):
        """Fade to black."""
        with self.lock:
            self._active_control_looks = []
            self._active_look_id = None
            self._active_device_ips = None
            self._blackout = True
            self._blackout_fade_start = time.monotonic()
            self._blackout_fade_duration = fade_time

    def release_output(self, preserve_selection=True):
        """Clear live controller ownership and runtime state.

        preserve_selection=True keeps the cue list position so GO can continue
        from the same point later, while clearing the live look/transition state.
        """
        with self.lock:
            self.playing = False
            self.play_start_time = 0.0
            self._active_look_id = None
            self._active_control_looks = []
            self._active_device_ips = None
            self._prev_look_id = None
            self._transition_start = 0.0
            self._transition_duration = 0.0
            self._auto_follow_time = 0.0
            self._blackout = False
            self._blackout_fade_start = 0.0
            self._blackout_fade_duration = 0.0
            if not preserve_selection:
                self.current_index = -1

    # ------------------------------------------------------------------
    #  Transport
    # ------------------------------------------------------------------

    def go(self, device_groups=None):
        """Trigger the next cue. Returns the cue dict or None."""
        with self.lock:
            if not self.cues:
                return None
            next_idx = self.current_index + 1
            if next_idx >= len(self.cues):
                next_idx = 0  # wrap around
            cue = dict(self.cues[next_idx])
            look_id = cue.get("look_id")

        # Validate look exists outside lock (disk I/O)
        look = load_look(look_id) if look_id else None
        if look_id and look is None:
            return None  # look was deleted

        with self.lock:
            fade_time = cue.get("fade_time", 0.0)
            self._active_control_looks = []
            self._start_transition(look_id, fade_time)
            self._active_device_ips = self._resolve_device_ips(cue, device_groups, look)
            self.current_index = next_idx
            self.playing = True
            self.play_start_time = time.monotonic()
            self._setup_auto_follow(cue)
            return cue

    def stop(self):
        """Stop playback."""
        self.release_output(preserve_selection=True)

    def go_to_cue(self, number, device_groups=None):
        """Jump to a specific cue number. Returns the cue or None."""
        with self.lock:
            match = None
            match_idx = -1
            for i, cue in enumerate(self.cues):
                if cue.get("number") == number:
                    match = dict(cue)
                    match_idx = i
                    break
            if match is None:
                return None
            look_id = match.get("look_id")

        # Validate look exists outside lock (disk I/O)
        look = load_look(look_id) if look_id else None
        if look_id and look is None:
            return None  # look was deleted

        with self.lock:
            fade_time = match.get("fade_time", 0.0)
            self._active_control_looks = []
            self._start_transition(look_id, fade_time)
            self._active_device_ips = self._resolve_device_ips(match, device_groups, look)
            self.current_index = match_idx
            self.playing = True
            self.play_start_time = time.monotonic()
            self._setup_auto_follow(match)
            return match

    def get_elapsed(self):
        """Seconds elapsed since current cue started."""
        with self.lock:
            if not self.playing:
                return 0.0
            return time.monotonic() - self.play_start_time

    def get_current_look_id(self):
        """Return the active look_id, or None."""
        with self.lock:
            if not self.playing:
                return None
            return self._active_look_id

    # ------------------------------------------------------------------
    #  Crossfade state (called by render loop)
    # ------------------------------------------------------------------

    def _crossfade_progress_unlocked(self):
        """Crossfade progress 0.0-1.0. Must be called with lock held."""
        if self._prev_look_id is None or self._transition_duration <= 0:
            return 1.0
        elapsed = time.monotonic() - self._transition_start
        return min(1.0, elapsed / self._transition_duration)

    def get_crossfade_state(self):
        """Return crossfade info for the render loop.

        Returns dict with:
            current_look_id, prev_look_id, crossfade_progress (0-1),
            elapsed (since cue start), blackout, blackout_progress (0-1)
        """
        with self.lock:
            now = time.monotonic()
            xf = self._crossfade_progress_unlocked()
            # If crossfade complete, clear the outgoing look
            if xf >= 1.0 and self._prev_look_id is not None:
                self._prev_look_id = None

            bo_progress = 1.0
            if self._blackout and self._blackout_fade_duration > 0:
                bo_elapsed = time.monotonic() - self._blackout_fade_start
                bo_progress = min(1.0, bo_elapsed / self._blackout_fade_duration)
            elif self._blackout:
                bo_progress = 1.0

            return {
                "current_look_id": self._active_look_id if self.playing else None,
                "active_looks": [
                    {
                        "look_id": entry["look_id"],
                        "elapsed": now - entry["start_time"],
                        "device_ips": (
                            None if entry.get("device_ips") is None
                            else list(entry.get("device_ips") or set())
                        ),
                    }
                    for entry in self._active_control_looks
                ] if self.playing else [],
                "prev_look_id": self._prev_look_id,
                "crossfade_progress": xf,
                "elapsed": now - self.play_start_time if self.playing else 0.0,
                "blackout": self._blackout,
                "blackout_progress": bo_progress,
                "device_ips": (
                    None if self._active_device_ips is None
                    else list(self._active_device_ips)
                ),
            }

    # ------------------------------------------------------------------
    #  Auto-follow (called by render loop)
    # ------------------------------------------------------------------

    def check_auto_follow(self, device_groups=None):
        """Check if auto-follow timer has fired. If so, trigger go().
        Returns the cue dict if auto-triggered, else None.
        """
        with self.lock:
            if self._auto_follow_time <= 0:
                return None
            if time.monotonic() < self._auto_follow_time:
                return None
            self._auto_follow_time = 0.0
        # Release lock before calling go() (which acquires it)
        return self.go(device_groups=device_groups)

if __name__ == "__main__":
    print("controller.py is the cue-controller module. Start the interface with: python3 V3_5/sender/run.py")
