"""Runtime paths for the OSC Cue Sender utility."""

import os
import shutil
import sys


DATA_DIR_ENV = "OSC_CUE_SENDER_DATA_DIR"
APP_NAME = "osc_cue_sender"


def app_dir():
    return os.path.dirname(os.path.abspath(__file__))


def tools_dir():
    return os.path.dirname(app_dir())


def v5_dir():
    return os.path.dirname(tools_dir())


def repo_root():
    return os.path.dirname(v5_dir())


def sender_dir():
    return os.path.join(v5_dir(), "sender")


def is_bundled():
    return bool(getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None))


def _resource_roots():
    bundle_root = getattr(sys, "_MEIPASS", None)
    roots = []
    if bundle_root:
        roots.extend([
            os.path.join(bundle_root, "web"),
            os.path.join(bundle_root, "osc_cue_sender", "web"),
            os.path.join(bundle_root, APP_NAME, "web"),
            bundle_root,
        ])
    roots.append(os.path.join(app_dir(), "web"))
    roots.append(app_dir())
    return roots


def web_dir():
    for root in _resource_roots():
        candidate = os.path.join(root, "web") if not root.endswith("web") else root
        if os.path.isdir(candidate):
            return candidate
        if os.path.basename(root) == "web" and os.path.isdir(root):
            return root
    return os.path.join(app_dir(), "web")


def _app_support_base():
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support")
    if os.name == "nt":
        return os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def data_dir():
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return os.path.abspath(os.path.expanduser(override))
    if is_bundled() or os.environ.get("OSC_CUE_SENDER_USE_APP_DATA") == "1":
        return os.path.join(_app_support_base(), "PrimusV3", "V5", "tools", APP_NAME)
    return app_dir()


def data_path(*parts):
    return os.path.join(data_dir(), *parts)


def cue_boards_dir():
    return data_path("cue_boards")


def state_file():
    return data_path(".osc_cue_sender_state.json")


def default_cues_file():
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        bundled = os.path.join(bundle_root, "default_cues.json")
        if os.path.isfile(bundled):
            return bundled
    source = os.path.join(app_dir(), "default_cues.json")
    if os.path.isfile(source):
        return source
    return data_path("default_cues.json")


def ensure_runtime_data():
    os.makedirs(data_dir(), exist_ok=True)
    os.makedirs(cue_boards_dir(), exist_ok=True)
    target = state_file()
    if os.path.isfile(target):
        return target
    source = default_cues_file()
    if os.path.isfile(source):
        dest = data_path("default_cues.json")
        if os.path.abspath(source) != os.path.abspath(dest):
            shutil.copy2(source, dest)
    return target
