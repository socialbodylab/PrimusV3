"""
paths.py — Runtime resource and writable-data paths for the V3.6 sender.

Source checkouts keep using the sender directory for editable data. Packaged
apps use a user-writable application data directory and read bundled resources
from the PyInstaller extraction area.
"""

import os
import shutil
import sys


DATA_DIR_ENV = "PRIMUSV3_DATA_DIR"
TOOLS_DIR_ENV = "PRIMUSV3_TOOLS_DIR"
USE_APP_DATA_ENV = "PRIMUSV3_USE_APP_DATA"


def sender_dir():
    return os.path.dirname(os.path.abspath(__file__))


def v36_dir():
    return os.path.abspath(os.path.join(sender_dir(), ".."))


def repo_root():
    return os.path.abspath(os.path.join(v36_dir(), ".."))


def is_bundled():
    return bool(getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None))


def _dedupe(paths):
    seen = set()
    out = []
    for path in paths:
        if not path:
            continue
        full = os.path.abspath(os.path.expanduser(path))
        if full in seen:
            continue
        seen.add(full)
        out.append(full)
    return out


def _resource_roots():
    bundle_root = getattr(sys, "_MEIPASS", None)
    roots = []
    if bundle_root:
        roots.extend([
            os.path.join(bundle_root, "sender"),
            os.path.join(bundle_root, "V3_6", "sender"),
            os.path.join(bundle_root, "V3_5", "sender"),
            bundle_root,
        ])
    roots.append(sender_dir())
    roots.append(v36_dir())
    return _dedupe(roots)


def resource_path(*parts):
    for root in _resource_roots():
        candidate = os.path.join(root, *parts)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(_resource_roots()[0], *parts)


def web_dir():
    return resource_path("web")


def _default_app_root_dir():
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif os.name == "nt":
        base = os.environ.get("APPDATA")
        if not base:
            base = os.path.expanduser("~/AppData/Roaming")
    else:
        base = os.environ.get("XDG_DATA_HOME")
        if not base:
            base = os.path.expanduser("~/.local/share")
    return os.path.join(base, "PrimusV3", "V3_6")


def _default_app_data_dir():
    return os.path.join(_default_app_root_dir(), "sender")


def uses_app_data_dir():
    return bool(
        os.environ.get(DATA_DIR_ENV)
        or os.environ.get(USE_APP_DATA_ENV) == "1"
        or is_bundled()
    )


def data_dir():
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if uses_app_data_dir():
        return _default_app_data_dir()
    return sender_dir()


def data_path(*parts):
    return os.path.join(data_dir(), *parts)


def tools_dir():
    override = os.environ.get(TOOLS_DIR_ENV)
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if uses_app_data_dir():
        return os.path.join(_default_app_root_dir(), "tools")
    return os.path.join(repo_root(), ".tools")


def tools_path(*parts):
    return os.path.join(tools_dir(), *parts)


def arduino_cli_tool_dir():
    return tools_path("arduino-cli")


def arduino_cli_bin_dir():
    return os.path.join(arduino_cli_tool_dir(), "bin")


def arduino_cli_executable():
    exe = "arduino-cli.exe" if os.name == "nt" else "arduino-cli"
    return os.path.join(arduino_cli_bin_dir(), exe)


def python_shim_dir():
    return tools_path("python-bin")


def arduino_data_dir():
    return tools_path("arduino-data")


def arduino_downloads_dir():
    return tools_path("arduino-downloads")


def arduino_user_dir():
    return tools_path("arduino-user")


def arduino_config_file():
    return tools_path("arduino-cli.yaml")


def ensure_tools_data():
    os.makedirs(tools_dir(), exist_ok=True)
    os.makedirs(arduino_cli_bin_dir(), exist_ok=True)
    os.makedirs(python_shim_dir(), exist_ok=True)
    os.makedirs(arduino_data_dir(), exist_ok=True)
    os.makedirs(arduino_downloads_dir(), exist_ok=True)
    os.makedirs(arduino_user_dir(), exist_ok=True)


def clips_dir():
    return data_path("clips")


def looks_dir():
    return data_path("looks")


def cues_file():
    return data_path("cues.json")


def state_file():
    return data_path(".primus_state.json")


def logs_dir():
    return data_path("logs")


def log_path(filename):
    return os.path.join(logs_dir(), filename)


def _copy_missing_file(source, dest, default_text=None):
    if os.path.exists(dest):
        return
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if source and os.path.isfile(source):
        shutil.copy2(source, dest)
    elif default_text is not None:
        with open(dest, "w") as f:
            f.write(default_text)


def _copy_missing_dir(source, dest):
    os.makedirs(dest, exist_ok=True)
    if not source or not os.path.isdir(source):
        return
    for root, dirs, files in os.walk(source):
        rel = os.path.relpath(root, source)
        target_root = dest if rel == "." else os.path.join(dest, rel)
        for dirname in dirs:
            os.makedirs(os.path.join(target_root, dirname), exist_ok=True)
        for filename in files:
            source_file = os.path.join(root, filename)
            dest_file = os.path.join(target_root, filename)
            _copy_missing_file(source_file, dest_file)


def ensure_runtime_data():
    os.makedirs(data_dir(), exist_ok=True)
    os.makedirs(clips_dir(), exist_ok=True)
    os.makedirs(looks_dir(), exist_ok=True)
    if not uses_app_data_dir():
        return

    os.makedirs(logs_dir(), exist_ok=True)
    _copy_missing_dir(resource_path("clips"), clips_dir())
    _copy_missing_dir(resource_path("looks"), looks_dir())
    _copy_missing_file(resource_path("cues.json"), cues_file(), '{"cues": []}\n')
