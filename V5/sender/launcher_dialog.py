"""
launcher_dialog.py — Minimal native dialogs for launcher decisions.

Packaged Central apps are built windowed, so they have no console: anything a
launcher prints when it declines to start (already running, wrong product,
monitor-only backend) goes nowhere and the app looks like it failed to launch.
These helpers put that decision in front of the user instead.

Stdlib only, per the project's no-external-dependency rule. Every path degrades
to printing and returning the default, so source runs and headless/CI use stay
non-blocking.
"""

import os
import subprocess
import sys

DIALOG_TIMEOUT_SECONDS = 120

# Set to opt out of blocking dialogs (CI, scripted runs, headless boxes).
SUPPRESS_ENV = "PRIMUSV3_NO_DIALOGS"


def dialogs_available():
    """True when a blocking native dialog can reasonably be shown."""
    if os.environ.get(SUPPRESS_ENV):
        return False
    if sys.platform == "darwin":
        return True
    if os.name == "nt":
        return True
    return False


def _applescript_quote(text):
    """Quote a Python string for embedding in an AppleScript string literal."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def _choose_macos(title, message, buttons, default):
    # `buttons` is capped at 3 by AppleScript itself; callers stay within that.
    button_list = ", ".join(f'"{_applescript_quote(b)}"' for b in buttons)
    script = (
        f'display dialog "{_applescript_quote(message)}" '
        f'with title "{_applescript_quote(title)}" '
        f"buttons {{{button_list}}} "
        f'default button "{_applescript_quote(default)}" '
        f"with icon caution"
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=DIALOG_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        # Non-zero also covers the user dismissing with Escape (error -128),
        # which we treat as "no choice made" so the caller can fall back.
        return None
    # stdout looks like: button returned:Restart
    for chunk in (result.stdout or "").strip().split(","):
        key, sep, value = chunk.partition(":")
        if sep and key.strip() == "button returned":
            return value.strip()
    return None


def _notify_windows(title, message):
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, str(message), str(title), 0x40)
        return True
    except Exception:
        return False


def notify(title, message):
    """Show an informational dialog. Always also prints, so logs keep a record."""
    print(f"{title}: {message}")
    if not dialogs_available():
        return False
    if sys.platform == "darwin":
        return _choose_macos(title, message, ["OK"], "OK") is not None
    if os.name == "nt":
        return _notify_windows(title, message)
    return False


def choose(title, message, buttons, default):
    """Ask the user to pick one of ``buttons``; return the chosen label.

    Returns ``default`` whenever a dialog cannot be shown or the user dismisses
    it, so callers can treat the result as a plain string and never block a
    scripted run. Print first so the reasoning is in the log either way.
    """
    if not buttons:
        return default
    if default not in buttons:
        default = buttons[-1]
    print(f"{title}: {message}")
    print(f"  options: {', '.join(buttons)} (default: {default})")
    if not dialogs_available():
        return default
    if sys.platform == "darwin":
        chosen = _choose_macos(title, message, buttons, default)
        return chosen if chosen in buttons else default
    if os.name == "nt":
        # No native 3-button prompt without extra deps; show the message and
        # take the default rather than guessing at a mapping.
        _notify_windows(title, f"{message}\n\nContinuing with: {default}")
        return default
    return default
