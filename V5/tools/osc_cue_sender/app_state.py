"""Persistent app state for OSC Cue Sender."""

import json
import threading

from paths import ensure_runtime_data, state_file


DEFAULT_CONFIG = {
    "target_host": "127.0.0.1",
    "target_port": 53001,
    "message_style": "primus",
    "central_url": "http://127.0.0.1:8080",
}

DEFAULT_CUES = [
    {"number": 1, "name": "Cue 1"},
    {"number": 2, "name": "Cue 2"},
    {"number": 3, "name": "Blackout"},
]


class AppState:
    def __init__(self):
        self._lock = threading.Lock()
        ensure_runtime_data()
        self._load()

    def _load(self):
        path = state_file()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            data = {}
        self.config = {**DEFAULT_CONFIG, **(data.get("config") or {})}
        self.cues = list(data.get("cues") or DEFAULT_CUES)
        self.history = list(data.get("history") or [])[:20]
        board = data.get("active_board") or {}
        self.active_board_id = str(board.get("id") or "") or None
        self.active_board_name = str(board.get("name") or "") or None

    def _save(self):
        path = state_file()
        payload = {
            "config": self.config,
            "cues": self.cues,
            "history": self.history[:20],
            "active_board": {
                "id": self.active_board_id,
                "name": self.active_board_name,
            },
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")

    def get_config(self):
        with self._lock:
            return dict(self.config)

    def update_config(self, updates):
        with self._lock:
            for key in DEFAULT_CONFIG:
                if key in updates:
                    self.config[key] = updates[key]
            if "target_port" in self.config:
                try:
                    self.config["target_port"] = int(self.config["target_port"])
                except (TypeError, ValueError):
                    self.config["target_port"] = DEFAULT_CONFIG["target_port"]
            self._save()
            return dict(self.config)

    def get_cues(self):
        with self._lock:
            return list(self.cues)

    def set_cues(self, cues):
        with self._lock:
            self.cues = _normalize_cues(cues)
            self._save()
            return list(self.cues)

    def record_history(self, entry):
        with self._lock:
            self.history.insert(0, entry)
            self.history = self.history[:20]
            self._save()

    def get_history(self):
        with self._lock:
            return list(self.history)

    def get_active_board(self):
        with self._lock:
            if not self.active_board_id:
                return None
            return {
                "id": self.active_board_id,
                "name": self.active_board_name or "",
            }

    def set_active_board(self, board_id=None, board_name=None):
        with self._lock:
            self.active_board_id = board_id or None
            self.active_board_name = board_name or None
            self._save()
            if not self.active_board_id:
                return None
            return {
                "id": self.active_board_id,
                "name": self.active_board_name or "",
            }


def _normalize_cues(cues):
    normalized = []
    for cue in cues or []:
        if not isinstance(cue, dict):
            continue
        try:
            number = int(cue.get("number"))
        except (TypeError, ValueError):
            continue
        name = str(cue.get("name") or f"Cue {number}").strip() or f"Cue {number}"
        normalized.append({"number": number, "name": name})
    normalized.sort(key=lambda item: item["number"])
    return normalized


def cues_from_import_payload(payload):
    if isinstance(payload, dict):
        raw = payload.get("cues")
    elif isinstance(payload, list):
        raw = payload
    else:
        raw = []
    return _normalize_cues(raw)
