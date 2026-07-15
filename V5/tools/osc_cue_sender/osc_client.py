"""OSC address builders and UDP send helpers."""

import json
import re
import socket
import time

from paths import sender_dir

import sys

_sender_path = sender_dir()
if _sender_path not in sys.path:
    sys.path.append(_sender_path)

from osc_control import build_osc_message  # noqa: E402


MESSAGE_STYLES = ("primus", "qlab")
MAX_HISTORY = 20
DEFAULT_TARGET_PORT = 53001


def parse_target_address(value, default_port=DEFAULT_TARGET_PORT):
    """Parse 'host', 'host:port', or '[ipv6]:port' into (host, port)."""
    text = str(value or "").strip()
    if not text:
        return "127.0.0.1", int(default_port)
    try:
        default_port = int(default_port)
    except (TypeError, ValueError):
        default_port = DEFAULT_TARGET_PORT

    if text.startswith("["):
        end = text.find("]")
        if end > 1:
            host = text[1:end]
            remainder = text[end + 1:]
            if remainder.startswith(":"):
                port_text = remainder[1:]
                try:
                    return host, int(port_text)
                except ValueError as exc:
                    raise ValueError("invalid port") from exc
            return host, default_port

    if ":" in text:
        host, _, port_text = text.rpartition(":")
        host = host.strip()
        port_text = port_text.strip()
        if not host:
            raise ValueError("target address required")
        try:
            port = int(port_text)
        except ValueError as exc:
            raise ValueError("invalid port") from exc
        if port < 1 or port > 65535:
            raise ValueError("invalid port")
        return host, port

    return text, default_port


def format_target_address(host, port):
    host = str(host or "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = DEFAULT_TARGET_PORT
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{port}"


def cue_slug(value):
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def normalize_osc_address(address):
    text = str(address or "").strip()
    if not text.startswith("/"):
        raise ValueError("OSC address must start with /")
    return text


def parse_osc_args(value):
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)

    text = str(value).strip()
    if not text:
        return []

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        return [parsed]
    except json.JSONDecodeError:
        pass

    args = []
    for part in [item.strip() for item in text.split(",") if item.strip()]:
        lowered = part.lower()
        if lowered in ("true", "false"):
            args.append(lowered == "true")
            continue
        if re.fullmatch(r"-?\d+", part):
            args.append(int(part))
            continue
        if re.fullmatch(r"-?\d+\.\d+", part):
            args.append(float(part))
            continue
        if (part.startswith('"') and part.endswith('"')) or (part.startswith("'") and part.endswith("'")):
            part = part[1:-1]
        args.append(part)
    return args


def normalize_style(style):
    value = str(style or "primus").strip().lower()
    return value if value in MESSAGE_STYLES else "primus"


def preview_cue_address(style, number=None, name=None):
    address, args = build_cue_message(style, number=number, name=name)
    return {"address": address, "args": list(args)}


def build_go_message(style):
    style = normalize_style(style)
    if style == "qlab":
        return "/cue/go", ()
    return "/primus/cue/go", ()


def build_stop_message(style):
    style = normalize_style(style)
    if style == "qlab":
        return "/stop", ()
    return "/primus/cue/stop", ()


def build_blackout_message(style, fade_time=0.0):
    style = normalize_style(style)
    try:
        fade = max(0.0, float(fade_time or 0.0))
    except (TypeError, ValueError):
        fade = 0.0
    if style == "qlab":
        return ("/blackout", (fade,)) if fade > 0 else ("/blackout", ())
    return ("/primus/blackout", (fade,)) if fade > 0 else ("/primus/blackout", ())


def build_cue_message(style, number=None, name=None):
    style = normalize_style(style)
    if number is not None:
        cue_number = int(number)
        if style == "qlab":
            return f"/cue/{cue_number}/start", ()
        return "/primus/cue/goto", (cue_number,)
    if name:
        text = str(name).strip()
        if not text:
            raise ValueError("cue name required")
        if style == "qlab":
            slug = cue_slug(text)
            if not slug:
                raise ValueError("cue name required")
            return f"/cue/{slug}/start", ()
        return "/primus/cue/name", (text,)
    raise ValueError("cue number or name required")


class OscSender:
    def __init__(self):
        self.history = []

    def send(self, host, port, address, *args):
        host = str(host or "127.0.0.1").strip() or "127.0.0.1"
        try:
            port = int(port)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid port") from exc
        if port < 1 or port > 65535:
            raise ValueError("invalid port")

        packet = build_osc_message(address, *args)
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "ok": True,
            "target": f"{host}:{port}",
            "address": address,
            "args": list(args),
            "error": "",
        }
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(packet, (host, port))
        except OSError as exc:
            entry["ok"] = False
            entry["error"] = str(exc)
        finally:
            sock.close()

        self.history.insert(0, entry)
        del self.history[MAX_HISTORY:]
        return entry

    def send_command(self, host, port, style, command, **kwargs):
        style = normalize_style(style)
        if command == "go":
            address, args = build_go_message(style)
        elif command == "stop":
            address, args = build_stop_message(style)
        elif command == "blackout":
            address, args = build_blackout_message(style, kwargs.get("fade_time", 0.0))
        elif command == "cue":
            address, args = build_cue_message(
                style,
                number=kwargs.get("number"),
                name=kwargs.get("name"),
            )
        else:
            raise ValueError(f"unsupported command {command}")
        return self.send(host, port, address, *args)

    def get_history(self):
        return list(self.history)
