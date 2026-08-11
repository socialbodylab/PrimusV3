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

from launcher_dialog import notify
from paths import sender_dir, uses_app_data_dir
from ui_focus import request_ui_focus


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

# Why a running Central cannot serve this launcher.
MISMATCH_WRONG_PRODUCT = "wrong_product"
MISMATCH_MONITOR_ONLY = "monitor_only"


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
    return os.path.join(_app_support_base(), "PrimusV3", "V5", REGISTRY_FILENAME)


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
    """Return /api/runtime JSON when a V5 Central server responds, else None."""
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


def evaluate_server(runtime, *, need_product=None, needs_output=False):
    """Return None when a running Central can serve this launcher, else a reason.

    The launcher has to answer three questions before attaching, and for a long
    time it only answered the first: is something running, can it serve my
    product, and can it do what I need. Skipping the last two is what let
    RadiusCentral attach to a Primus backend and PrimusCentral inherit
    DeviceManager's monitor-only mode, both silently.
    """
    runtime = runtime if isinstance(runtime, dict) else {}
    backend_product = str(runtime.get("product") or "").strip().lower()

    if need_product:
        need_product = str(need_product).strip().lower()
        if backend_product and backend_product != need_product:
            return {
                "reason": MISMATCH_WRONG_PRODUCT,
                "backend_product": backend_product,
                "need_product": need_product,
            }

    # monitor_only exists so DeviceManager is safe beside a live console: the
    # server never opens standing DMX output. A client that needs to drive
    # cannot borrow that backend.
    if needs_output and bool(runtime.get("monitor_only")):
        return {
            "reason": MISMATCH_MONITOR_ONLY,
            "backend_product": backend_product,
            "need_product": need_product,
        }
    return None


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


def register_central_server(
    port,
    product,
    pid=None,
    host="127.0.0.1",
    monitor_only=False,
    lan_enabled=False,
    app_version=None,
):
    """Record where the Central is *and* what it is able to do.

    The capability fields matter as much as the address: a launcher that finds
    this entry needs to decide whether attaching is appropriate before it opens
    a browser, not after.
    """
    payload = {
        "host": host,
        "port": int(port),
        "pid": int(pid if pid is not None else os.getpid()),
        "product": str(product or "").strip().lower() or "unknown",
        "monitor_only": bool(monitor_only),
        "lan_enabled": bool(lan_enabled),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if app_version:
        payload["app_version"] = str(app_version)
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


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError, TypeError, OSError):
        return False


def _remove_registry_file(path):
    try:
        os.remove(path)
    except OSError:
        pass


def clear_stale_registry(host="127.0.0.1"):
    """Drop registry files when the recorded server is no longer reachable."""
    for path in registry_read_paths():
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            _remove_registry_file(path)
            continue
        if not isinstance(payload, dict):
            _remove_registry_file(path)
            continue
        try:
            port = int(payload.get("port"))
        except (TypeError, ValueError):
            port = None
        pid = payload.get("pid")
        if port and probe_central_server(host, port):
            continue
        if pid and _pid_alive(pid):
            continue
        _remove_registry_file(path)


def find_running_central_server(requested_port=DEFAULT_HTTP_PORT, host="127.0.0.1"):
    clear_stale_registry(host=host)
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


def _raise_existing_ui(host, port, url, open_browser):
    """Focus an existing UI without opening a new browser window."""
    if request_ui_focus(port, host=host):
        return "raised existing browser window"
    result = open_browser(url, attach=True)
    if result == "raised existing browser window":
        return result
    return (
        f"{result} (Central is already running at {url})"
    )


def reserve_ui_session(host, port, session_id=None):
    """Keep Central alive while an attach-mode browser window is opening."""
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    if port <= 0:
        return False
    session_id = str(session_id or f"attach-{os.getpid()}").strip() or f"attach-{os.getpid()}"
    url = f"http://{host}:{port}/api/ui/heartbeat"
    payload = json.dumps({"session_id": session_id}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=1.0):
            return True
    except (OSError, urllib.error.URLError, ValueError):
        return False


def attach_to_running_central(
    *,
    port,
    frontend_path,
    no_browser,
    open_browser,
    launcher_name,
    host="127.0.0.1",
):
    """Open ``frontend_path`` against an already-running Central on ``port``."""
    url = build_central_url(port, frontend_path, host=host)
    print(f"{launcher_name}: Central already running on port {port}")
    print(f"  View URL: {url}")
    # Count this client before the browser exists. Without it there is a window
    # where the running Central sees zero UI sessions and shuts itself down
    # just as we hand it a new one.
    reserve_ui_session(host, port)
    if no_browser:
        print("  Browser: not opened (--no-browser)")
    else:
        browser_result = _raise_existing_ui(host, port, url, open_browser)
        print(f"  Browser: {browser_result}")
        if "could not" in str(browser_result).lower():
            # This is the silent-launch failure: the app attached correctly but
            # could not surface a window, so a windowed build exited showing the
            # user absolutely nothing. Tell them where the UI actually is.
            notify(
                launcher_name,
                f"{launcher_name} is already running on port {port}, but its "
                f"window could not be brought to the front.\n\nOpen this address "
                f"in a browser:\n{url}",
            )
    print()
    return True


def try_attach_before_start(
    *,
    port,
    frontend_path,
    no_browser,
    open_browser,
    launcher_name,
    host="127.0.0.1",
    need_product=None,
    needs_output=False,
    on_mismatch=None,
):
    """Open a frontend against an existing server instead of starting a new one.

    When the running Central cannot serve this launcher, ``on_mismatch`` decides
    what happens instead of attaching regardless. It receives the mismatch dict
    plus the discovered port/runtime and returns one of:

    ``"attach"``  -- attach anyway (e.g. the user chose read-only)
    ``"start"``   -- caller should start its own server (returns False)
    ``"abort"``   -- give up quietly (raises SystemExit)

    With no handler the safe default is to refuse, because silently attaching to
    the wrong backend is the failure this whole path exists to prevent.
    """
    found = find_running_central_server(port, host=host)
    if not found:
        return False
    actual_port, runtime = found

    mismatch = evaluate_server(
        runtime, need_product=need_product, needs_output=needs_output)
    if mismatch:
        decision = "abort"
        if callable(on_mismatch):
            decision = on_mismatch(mismatch, actual_port, runtime) or "abort"
        if decision == "start":
            return False
        if decision != "attach":
            backend = mismatch.get("backend_product") or "unknown"
            print(
                f"{launcher_name}: not attaching to the Central on port "
                f"{actual_port} (backend: {backend}, reason: {mismatch['reason']})."
            )
            raise SystemExit(1)

    return attach_to_running_central(
        port=actual_port,
        frontend_path=frontend_path,
        no_browser=no_browser,
        open_browser=open_browser,
        launcher_name=launcher_name,
        host=host,
    )


def stop_running_central(host="127.0.0.1", port=DEFAULT_HTTP_PORT, force=False,
                         timeout=5.0):
    """Ask a running Central to shut down. Returns (ok, message)."""
    url = f"http://{host}:{int(port)}/api/server/stop"
    payload = json.dumps({"force": bool(force)}).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8") or "{}")
        return True, body.get("message", "stopping")
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8") or "{}")
        except (ValueError, OSError):
            body = {}
        return False, body.get("error", f"HTTP {exc.code}")
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return False, str(exc)


def wait_for_port_release(host="127.0.0.1", port=DEFAULT_HTTP_PORT, timeout=15.0):
    """Block until no Central answers on ``port``. True if it went away."""
    deadline = time.monotonic() + max(0.0, float(timeout))
    while time.monotonic() < deadline:
        if probe_central_server(host, port, timeout=0.5) is None:
            # The HTTP listener is gone; give the OS a moment to release the
            # socket so our own bind() does not race it.
            time.sleep(0.5)
            return True
        time.sleep(0.25)
    return False


def probe_port_is_central(host="127.0.0.1", port=DEFAULT_HTTP_PORT):
    return probe_central_server(host, port) is not None
