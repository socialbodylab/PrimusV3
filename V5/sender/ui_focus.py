"""Helpers so attach-mode launchers can focus an existing UI window."""

import json
import os
import socket
import tempfile
import threading
import urllib.error
import urllib.request


def activation_socket_path(port):
    return os.path.join(tempfile.gettempdir(), f"primusv4-ui-focus-{int(port)}.sock")


def request_ui_focus_http(host, port, timeout=0.75):
    """Ask a running Central server to raise its dedicated browser window."""
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    if port <= 0:
        return False
    url = f"http://{host}:{port}/api/ui/focus"
    request = urllib.request.Request(
        url,
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.getcode() < 300
    except urllib.error.HTTPError:
        return False
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def request_ui_focus_socket(port):
    path = activation_socket_path(port)
    if not os.path.exists(path):
        return False
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(0.75)
        client.connect(path)
        client.sendall(b"focus\n")
        client.close()
        return True
    except OSError:
        return False


def request_ui_focus(port, host="127.0.0.1"):
    if request_ui_focus_http(host, port):
        return True
    return request_ui_focus_socket(port)


class UiFocusServer:
    def __init__(self, port, focus_callback):
        self.port = int(port)
        self.focus_callback = focus_callback
        self._stop = threading.Event()
        self._thread = None
        self._socket = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="ui-focus-server")
        self._thread.start()

    def stop(self):
        self._stop.set()
        sock = self._socket
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _run(self):
        path = activation_socket_path(self.port)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket = sock
        try:
            sock.bind(path)
        except OSError:
            return
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        sock.listen(5)
        sock.settimeout(0.5)
        while not self._stop.is_set():
            try:
                conn, _ = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                payload = conn.recv(64)
                if payload.strip().startswith(b"focus"):
                    self.focus_callback()
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
        try:
            sock.close()
        except OSError:
            pass
        try:
            os.remove(path)
        except OSError:
            pass
