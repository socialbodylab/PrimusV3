"""
controller.py — Look Controller: control panel activation, cue list,
per-pixel crossfade engine, and auto-follow.
"""

import json
import os
import threading
import time

from mixer import load_look


def _cues_file():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "cues.json")


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
            with open(path, "w") as f:
                json.dump({"cues": self.cues}, f, indent=2)

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------

    def _resolve_device_ips(self, cue, device_groups):
        """Resolve a cue's device targeting to a set of IP strings or None."""
        gid = cue.get("device_group_id")
        if gid and device_groups:
            for g in device_groups:
                if g.get("id") == gid:
                    ips = g.get("device_ips", [])
                    return set(ips) if ips else None
            return None  # group was deleted
        ips = cue.get("device_ips")
        if ips:
            return set(ips)
        return None  # all devices

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
                "crossfade_active": self._prev_look_id is not None and xf_progress < 1.0,
                "crossfade_progress": xf_progress,
                "blackout": self._blackout,
            }

    def set_cues(self, cues):
        """Replace the entire cue list."""
        with self.lock:
            self.cues = cues
            self.current_index = -1
            self.playing = False
            self._auto_follow_time = 0.0
        self.save()

    # ------------------------------------------------------------------
    #  Direct look activation (Control Panel)
    # ------------------------------------------------------------------

    def activate_look(self, look_id, fade_time=0.0, device_ips=None):
        """Directly activate a look (bypasses cue list). Returns True/False."""
        if load_look(look_id) is None:
            return False
        with self.lock:
            self._start_transition(look_id, fade_time)
            self._active_device_ips = set(device_ips) if device_ips else None
            self.playing = True
            self.play_start_time = time.monotonic()
            # Don't change cue index — control panel is independent
            self._auto_follow_time = 0.0
            return True

    def blackout(self, fade_time=0.0):
        """Fade to black."""
        with self.lock:
            self._blackout = True
            self._blackout_fade_start = time.monotonic()
            self._blackout_fade_duration = fade_time

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
            cue = self.cues[next_idx]
            look_id = cue.get("look_id")
            if look_id and load_look(look_id) is None:
                return None  # look was deleted
            fade_time = cue.get("fade_time", 0.0)
            self._start_transition(look_id, fade_time)
            self._active_device_ips = self._resolve_device_ips(cue, device_groups)
            self.current_index = next_idx
            self.playing = True
            self.play_start_time = time.monotonic()
            self._setup_auto_follow(cue)
            return dict(cue)

    def stop(self):
        """Stop playback."""
        with self.lock:
            self.playing = False
            self._auto_follow_time = 0.0

    def go_to_cue(self, number, device_groups=None):
        """Jump to a specific cue number. Returns the cue or None."""
        with self.lock:
            for i, cue in enumerate(self.cues):
                if cue.get("number") == number:
                    look_id = cue.get("look_id")
                    if look_id and load_look(look_id) is None:
                        return None  # look was deleted
                    fade_time = cue.get("fade_time", 0.0)
                    self._start_transition(look_id, fade_time)
                    self._active_device_ips = self._resolve_device_ips(cue, device_groups)
                    self.current_index = i
                    self.playing = True
                    self.play_start_time = time.monotonic()
                    self._setup_auto_follow(cue)
                    return dict(cue)
        return None

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
                "prev_look_id": self._prev_look_id,
                "crossfade_progress": xf,
                "elapsed": time.monotonic() - self.play_start_time if self.playing else 0.0,
                "blackout": self._blackout,
                "blackout_progress": bo_progress,
                "device_ips": list(self._active_device_ips) if self._active_device_ips else None,
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
