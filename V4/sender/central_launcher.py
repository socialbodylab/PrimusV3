"""
central_launcher.py — Shared Central server discovery and UI attach helpers.

Multiple frontends (/primus, /radius, /devices) can open against one running
HTTP server. Launchers probe for an existing instance before starting another.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

from paths import sender_dir, uses_app_data_dir


DEFAULT_HTTP_PORT = 8080
RUNTIME_API_PATH = "/api/runtime"
REGISTRY_ENV = "PRIMUSV3_CENTRAL_REGISTRY"
REGISTRY_FILENAME = "central_server.json"
SOURCE_REGISTRY_FILENAME = ".central_server.json"

FRONTEND_PATHS = {
    "primus": "/primus",
    "radius": "/radius",
    "devices": "/devices",
}


class CentralPortInUseByCentral(Exception):
    """Raised when bind fails because another Central server owns the port."""

    def __init__(self, port, runtime):
        super().__init__(f"Central already listening on port {port}")
        self.port = int(port)
        self.runtime = runtime


def _app_support_base():
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support")
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        if not base:
            base = os.path.expanduser("~/AppData/Roaming")
        return base
    base = os.environ.get("XDG_DATA_HOME")
    if not base:
        base = os.path.expanduser("~/.local/share")
    return base


def shared_registry_path():
    override = os.environ.get(REGISTRY_ENV)
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(_app_support_base(), "PrimusV3", "V4", REGISTRY_FILENAME)


def source_registry_path():
    return os.path.join(sender_dir(), SOURCE_REGISTRY_FILENAME)


def registry_read_paths():
    paths = []
    override = os.environ.get(REGISTRY_ENV)
    if override:
        paths.append(os.path.abspath(os.path.expanduser(override)))
    shared = shared_registry_path()
    if shared not in paths:
        paths.append(shared)
    if not uses_app_data_dir():
        local = source_registry_path()
        if local not in paths:
            paths.append(local)
    return paths


def registry_write_paths():
    paths = [shared_registry_path()]
    if not uses_app_data_dir():
        local = source_registry_path()
        if local not in paths:
            paths.append(local)
    return paths


def frontend_path_for(frontend, product):
    key = str(frontend or "").strip().lower()
    if key in FRONTEND_PATHS:
        return FRONTEND_PATHS[key]
    product = str(product or "").strip().lower()
    if product == "primus":
        return FRONTEND_PATHS["primus"]
    return FRONTEND_PATHS["radius"]


def build_central_url(port, frontend_path, host="127.0.0.1"):
    path = frontend_path if str(frontend_path or "").startswith("/") else f"/{frontend_path or ''}"
    return f"http://{host}:{port}{path}"


def probe_central_server(host="127.0.0.1", port=DEFAULT_HTTP_PORT, timeout=0.75):
    """Return /api/runtime JSON when a V4 Central server responds, else None."""
    try:
        port = int(port)
    except (TypeError, ValueError):
        return None
    if port <= 0:
        return None
    url = f"http://{host}:{port}{RUNTIME_API_PATH}"
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    frontends = payload.get("frontends")
    if not isinstance(frontends, dict):
        return None
    if not any(key in frontends for key in FRONTEND_PATHS):
        return None
    return payload


def read_registry():
    for path in registry_read_paths():
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("port"):
            payload["_path"] = path
            return payload
    return None


def _write_json(path, payload):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temp_path = f"{path}.tmp-{os.getpid()}"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temp_path, path)


def register_central_server(port, product, pid=None, host="127.0.0.1"):
    payload = {
        "host": host,
        "port": int(port),
        "pid": int(pid if pid is not None else os.getpid()),
        "product": str(product or "").strip().lower() or "unknown",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    for path in registry_write_paths():
        try:
            _write_json(path, payload)
        except OSError:
            continue
    return payload


def unregister_central_server(pid=None):
    pid = int(pid if pid is not None else os.getpid())
    for path in registry_read_paths():
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("pid") not in (pid, None):
            continue
        try:
            os.remove(path)
        except OSError:
            pass


def candidate_ports(requested_port=DEFAULT_HTTP_PORT):
    ports = []
    for value in (requested_port,):
        try:
            port = int(value)
        except (TypeError, ValueError):
            continue
        if port > 0 and port not in ports:
            ports.append(port)
    registry = read_registry()
    if registry:
        try:
            reg_port = int(registry.get("port"))
        except (TypeError, ValueError):
            reg_port = None
        if reg_port and reg_port > 0 and reg_port not in ports:
            ports.append(reg_port)
    if DEFAULT_HTTP_PORT not in ports:
        ports.append(DEFAULT_HTTP_PORT)
    return ports


def find_running_central_server(requested_port=DEFAULT_HTTP_PORT, host="127.0.0.1"):
    registry = read_registry()
    registry_port = None
    if registry:
        try:
            registry_port = int(registry.get("port"))
        except (TypeError, ValueError):
            registry_port = None
    ports = candidate_ports(requested_port)
    if registry_port and registry_port not in ports:
        ports.insert(0, registry_port)
    for port in ports:
        runtime = probe_central_server(host, port)
        if runtime:
            return port, runtime
    return None


def try_attach_before_start(
    *,
    port,
    frontend_path,
    no_browser,
    open_browser,
    launcher_name,
    host="127.0.0.1",
):
    """Open a frontend against an existing server instead of starting a new one."""
    found = find_running_central_server(port, host=host)
    if not found:
        return False
    actual_port, runtime = found
    url = build_central_url(actual_port, frontend_path, host=host)
    backend = runtime.get("product", "unknown")
    print(f"{launcher_name}: Central already running on port {actual_port} (backend: {backend})")
    print(f"  View URL: {url}")
    if no_browser:
        print("  Browser: not opened (--no-browser)")
    else:
        print(f"  Browser: {open_browser(url)}")
    print()
    return True


def probe_port_is_central(host="127.0.0.1", port=DEFAULT_HTTP_PORT):
    return probe_central_server(host, port) is not None
