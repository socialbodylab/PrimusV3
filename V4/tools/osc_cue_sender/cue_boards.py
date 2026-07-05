"""Named cue board persistence for OSC Cue Sender."""

import json
import os
import uuid
from datetime import datetime, timezone

from paths import cue_boards_dir


def _boards_dir():
    path = cue_boards_dir()
    os.makedirs(path, exist_ok=True)
    return path


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _board_path(board_id):
    return os.path.join(_boards_dir(), f"{board_id}.json")


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


def _summary(board):
    cues = board.get("cues") or []
    return {
        "id": board.get("id"),
        "name": board.get("name", ""),
        "cue_count": len(cues),
        "created": board.get("created", ""),
        "modified": board.get("modified", ""),
    }


def list_cue_boards():
    directory = _boards_dir()
    boards = []
    for filename in os.listdir(directory):
        if not filename.endswith(".json"):
            continue
        try:
            with open(os.path.join(directory, filename), "r", encoding="utf-8") as handle:
                board = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(board, dict) and board.get("id"):
            boards.append(_summary(board))
    boards.sort(key=lambda item: item.get("modified", ""), reverse=True)
    return boards


def load_cue_board(board_id):
    path = _board_path(board_id)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            board = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(board, dict) or not board.get("id"):
        return None
    board["cues"] = _normalize_cues(board.get("cues"))
    return board


def save_cue_board(name, cues, board_id=None):
    text = str(name or "").strip()
    if not text:
        raise ValueError("board name required")
    normalized = _normalize_cues(cues)
    now = _now_iso()
    if board_id:
        board = load_cue_board(board_id)
        if board is None:
            raise ValueError("cue board not found")
    else:
        board = {
            "id": str(uuid.uuid4()),
            "created": now,
        }
    board["name"] = text
    board["cues"] = normalized
    board["modified"] = now
    if not board.get("created"):
        board["created"] = now
    with open(_board_path(board["id"]), "w", encoding="utf-8") as handle:
        json.dump(board, handle, indent=2)
        handle.write("\n")
    return board


def delete_cue_board(board_id):
    path = _board_path(board_id)
    try:
        os.remove(path)
        return True
    except OSError:
        return False
