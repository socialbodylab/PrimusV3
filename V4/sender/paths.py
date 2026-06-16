"""
paths.py — Runtime resource and writable-data paths for the V4 unified sender.
"""

import os
import shutil
import sys


DATA_DIR_ENV = "RADIUSV4_DATA_DIR"
PRIMUS_DATA_DIR_ENV = "PRIMUSV3_DATA_DIR"
TOOLS_DIR_ENV = "RADIUSV4_TOOLS_DIR"
PRIMUS_TOOLS_DIR_ENV = "PRIMUSV3_TOOLS_DIR"
USE_APP_DATA_ENV = "RADIUSV4_USE_APP_DATA"
PRIMUS_USE_APP_DATA_ENV = "PRIMUSV3_USE_APP_DATA"
SENDER_PRODUCT_ENV = "PRIMUSV3_SENDER_PRODUCT"
DEFAULT_SENDER_PRODUCT = "radius"


def sender_dir():
    return os.path.dirname(os.path.abspath(__file__))


def v4_dir():
    return os.path.abspath(os.path.join(sender_dir(), ".."))


def repo_root():
    return os.path.abspath(os.path.join(v4_dir(), ".."))


def is_bundled():
    return bool(getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None))


def sender_product():
    """Sender product id: ``primus`` (LED) or ``radius`` (audio)."""
    value = os.environ.get(SENDER_PRODUCT_ENV, DEFAULT_SENDER_PRODUCT)
    product = str(value or DEFAULT_SENDER_PRODUCT).strip().lower()
    if product not in ("primus", "radius"):
        return DEFAULT_SENDER_PRODUCT
    return product


def is_primus_product():
    return sender_product() == "primus"


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
            os.path.join(bundle_root, "V4", "sender"),
            bundle_root,
        ])
    roots.append(sender_dir())
    roots.append(v4_dir())
    return _dedupe(roots)


def resource_path(*parts):
    for root in _resource_roots():
        candidate = os.path.join(root, *parts)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(_resource_roots()[0], *parts)


def web_dir():
    return resource_path("web")


def index_html_path():
    if is_primus_product():
        primus_index = resource_path("web", "index-primus.html")
        if os.path.isfile(primus_index):
            return primus_index
    return resource_path("web", "index.html")


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


def _default_app_root_dir():
    base = _app_support_base()
    if is_primus_product():
        return os.path.join(base, "PrimusV3", "V4")
    return os.path.join(base, "RadiusV3", "V4")


def _default_app_data_dir():
    return os.path.join(_default_app_root_dir(), "sender")


def uses_app_data_dir():
    return bool(
        os.environ.get(DATA_DIR_ENV)
        or os.environ.get(PRIMUS_DATA_DIR_ENV)
        or os.environ.get(USE_APP_DATA_ENV) == "1"
        or os.environ.get(PRIMUS_USE_APP_DATA_ENV) == "1"
        or is_bundled()
    )


def data_dir():
    for env_key in (DATA_DIR_ENV, PRIMUS_DATA_DIR_ENV):
        override = os.environ.get(env_key)
        if override:
            return os.path.abspath(os.path.expanduser(override))
    if uses_app_data_dir():
        return _default_app_data_dir()
    return sender_dir()


def data_path(*parts):
    return os.path.join(data_dir(), *parts)


def tools_dir():
    for env_key in (TOOLS_DIR_ENV, PRIMUS_TOOLS_DIR_ENV):
        override = os.environ.get(env_key)
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
    if is_primus_product():
        return data_path(".primus_state.json")
    return data_path(".radius_state.json")


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
        with open(dest, "w", encoding="utf-8") as handle:
            handle.write(default_text)


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
    if is_primus_product():
        os.makedirs(clips_dir(), exist_ok=True)
        os.makedirs(looks_dir(), exist_ok=True)
        if uses_app_data_dir():
            os.makedirs(logs_dir(), exist_ok=True)
            _copy_missing_dir(resource_path("clips"), clips_dir())
            _copy_missing_dir(resource_path("looks"), looks_dir())
            _copy_missing_file(resource_path("cues.json"), cues_file(), '{"cues": []}\n')
    if not is_primus_product():
        try:
            import audio_cues as _audio_cues_mod
            _audio_cues_mod._ensure_audio_dirs()
        except Exception:
            pass
    elif uses_app_data_dir():
        try:
            import audio_cues as _audio_cues_mod
            _audio_cues_mod._ensure_audio_dirs()
        except Exception:
            pass
