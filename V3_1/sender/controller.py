"""
controller.py — Cue list management for Look Controller mode.
"""

import json
import os
import threading
import time


def _cues_file():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "cues.json")


class CueList:
    """Theatre-style cue list. Cues reference Looks by ID."""

    def __init__(self):
        self.lock = threading.Lock()
        self.cues = []           # [{"number": 1, "look_id": "...", "name": "...", ...}, ...]
        self.current_index = -1  # -1 = no cue active
        self.playing = False
        self.play_start_time = 0.0
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
    #  Cue list queries
    # ------------------------------------------------------------------

    def get_json(self):
        with self.lock:
            return {
                "cues": list(self.cues),
                "current_index": self.current_index,
                "playing": self.playing,
            }

    def set_cues(self, cues):
        """Replace the entire cue list."""
        with self.lock:
            self.cues = cues
            self.current_index = -1
            self.playing = False
        self.save()

    # ------------------------------------------------------------------
    #  Transport
    # ------------------------------------------------------------------

    def go(self):
        """Trigger the next cue. Returns the cue dict or None."""
        with self.lock:
            if not self.cues:
                return None
            next_idx = self.current_index + 1
            if next_idx >= len(self.cues):
                next_idx = 0  # wrap around
            self.current_index = next_idx
            self.playing = True
            self.play_start_time = time.monotonic()
            return dict(self.cues[self.current_index])

    def stop(self):
        """Stop playback."""
        with self.lock:
            self.playing = False

    def go_to_cue(self, number):
        """Jump to a specific cue number. Returns the cue or None."""
        with self.lock:
            for i, cue in enumerate(self.cues):
                if cue.get("number") == number:
                    self.current_index = i
                    self.playing = True
                    self.play_start_time = time.monotonic()
                    return dict(cue)
        return None

    def get_elapsed(self):
        """Seconds elapsed since current cue started."""
        with self.lock:
            if not self.playing:
                return 0.0
            return time.monotonic() - self.play_start_time

    def get_current_look_id(self):
        """Return the look_id of the currently active cue, or None."""
        with self.lock:
            if not self.playing or self.current_index < 0:
                return None
            if self.current_index >= len(self.cues):
                return None
            return self.cues[self.current_index].get("look_id")
