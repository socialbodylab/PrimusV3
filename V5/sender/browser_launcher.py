"""Dedicated Chromium app-window launcher and attach-mode focus helpers."""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import webbrowser

PID_FILE = "browser.pid"
PROFILE_MARKER = "current-profile.txt"
LABEL_MARKER = "browser.label"


class DedicatedBrowser:
    def __init__(self, profile_root_name, browser_env=()):
        self.profile_root_name = profile_root_name
        self.browser_env = tuple(browser_env)

    def profile_root(self):
        return os.path.join(tempfile.gettempdir(), self.profile_root_name)

    def has_tracked_browser(self):
        """True only when a tracked browser PROCESS is actually alive.

        The marker files persist after the window closes, and treating a
        stale marker as a live window made a relaunch exit without ever
        showing anything — indistinguishable from a crashed app.
        """
        root = self.profile_root()
        pid = self._read_tracked_pid(root)
        if pid and self._process_is_running(pid):
            return True
        return self._process_using_profile_root(root)

    def _process_using_profile_root(self, profile_root):
        profile_root = os.path.abspath(profile_root)
        if os.name == "nt":
            # No cheap process scan on Windows; err toward "not running" so
            # a relaunch opens a window instead of silently exiting.
            return False
        try:
            out = subprocess.check_output(
                ["ps", "-axo", "pid=,command="],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
        marker = "--user-data-dir="
        for line in out.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) != 2:
                continue
            command = parts[1]
            if marker in command and profile_root in command:
                return True
        return False

    def open(self, url, attach=False):
        if attach:
            if self.focus():
                return "raised existing browser window"
            if self.has_tracked_browser():
                return "using existing browser window"
            # No window of ours exists — attach means "make this frontend
            # visible", so open one rather than reporting failure. (A
            # windowed launcher that attaches without surfacing a window
            # looks exactly like a crashed app.)
            result = self.launch(url, cleanup_stale=True)
            if result:
                return result
            webbrowser.open_new(url)
            return "opened default browser"
        result = self.launch(url, cleanup_stale=True)
        if result:
            return result
        webbrowser.open_new(url)
        return "opened default browser"

    def focus(self):
        profile_root = self.profile_root()
        pid = self._read_tracked_pid(profile_root)
        if pid and self._process_is_running(pid) and self._activate_process(pid):
            return True
        # Label activation raises the whole browser app (e.g. "Google
        # Chrome") — that is only meaningful while a window on OUR profile
        # still exists. After the user closes it, activating the label
        # fronts an unrelated Chrome window, focus() reports success, and
        # the relaunched app exits without ever showing its own window.
        if not self._process_using_profile_root(profile_root):
            return False
        label = self._read_tracked_label(profile_root)
        if label and self._activate_application(label):
            return True
        return self._activate_process_with_profile_root(profile_root)

    def launch(self, url, cleanup_stale=True):
        candidates = self._chromium_candidates()
        if not candidates:
            return None

        profile_root = self.profile_root()
        profile_dir = self._resolve_profile_dir(profile_root, cleanup_stale)
        for label, executable in candidates:
            args = [
                executable,
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-session-crashed-bubble",
                f"--app={url}",
            ]
            popen_kwargs = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = (
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    | getattr(subprocess, "DETACHED_PROCESS", 0)
                )
            else:
                popen_kwargs["start_new_session"] = True
            try:
                browser_process = subprocess.Popen(args, **popen_kwargs)
            except OSError:
                continue
            self._write_tracked_state(profile_root, browser_process.pid, profile_dir, label)
            return f"opened {label} app window"
        return None

    def remove_profiles(self):
        self._remove_profiles(self.profile_root())

    def _new_profile_dir(self, profile_root):
        profile_name = f"profile-{os.getpid()}-{int(time.time() * 1000)}"
        return os.path.join(profile_root, profile_name)

    def _resolve_profile_dir(self, profile_root, cleanup_stale):
        if cleanup_stale:
            self._remove_profiles(profile_root)
            profile_dir = self._new_profile_dir(profile_root)
        else:
            os.makedirs(profile_root, exist_ok=True)
            profile_dir = self._read_tracked_profile(profile_root) or self._new_profile_dir(profile_root)
        os.makedirs(profile_dir, exist_ok=True)
        return profile_dir

    def _write_tracked_state(self, profile_root, pid, profile_dir, browser_label):
        try:
            with open(os.path.join(profile_root, PID_FILE), "w", encoding="utf-8") as handle:
                handle.write(str(pid))
        except OSError:
            pass
        try:
            with open(os.path.join(profile_root, PROFILE_MARKER), "w", encoding="utf-8") as handle:
                handle.write(profile_dir)
        except OSError:
            pass
        try:
            with open(os.path.join(profile_root, LABEL_MARKER), "w", encoding="utf-8") as handle:
                handle.write(browser_label)
        except OSError:
            pass

    def _read_tracked_pid(self, profile_root):
        try:
            with open(os.path.join(profile_root, PID_FILE), "r", encoding="utf-8") as handle:
                return int(handle.read().strip())
        except (FileNotFoundError, OSError, ValueError):
            return None

    def _read_tracked_profile(self, profile_root):
        try:
            with open(os.path.join(profile_root, PROFILE_MARKER), "r", encoding="utf-8") as handle:
                profile_dir = handle.read().strip()
            if profile_dir and os.path.isdir(profile_dir):
                return profile_dir
        except (FileNotFoundError, OSError):
            pass
        return None

    def _read_tracked_label(self, profile_root):
        try:
            with open(os.path.join(profile_root, LABEL_MARKER), "r", encoding="utf-8") as handle:
                label = handle.read().strip()
            if label:
                return label
        except (FileNotFoundError, OSError):
            pass
        return None

    def _process_is_running(self, pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return False
        else:
            return True

    def _activate_process(self, pid):
        if not self._process_is_running(pid):
            return False
        if sys.platform == "darwin":
            script = (
                "tell application \"System Events\" to set frontmost of "
                f"(first process whose unix id is {int(pid)}) to true"
            )
            try:
                subprocess.run(
                    ["osascript", "-e", script],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except (OSError, subprocess.SubprocessError):
                return False
        return True

    def _activate_application(self, app_name):
        if sys.platform != "darwin":
            return False
        script = f"tell application {json.dumps(app_name)} to activate"
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return True

    def _activate_process_with_profile_root(self, profile_root):
        profile_root = os.path.abspath(profile_root)
        if os.name == "nt":
            return False
        try:
            out = subprocess.check_output(
                ["ps", "-axo", "pid=,command="],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
        marker = "--user-data-dir="
        for line in out.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) != 2:
                continue
            pid = int(parts[0])
            command = parts[1]
            if marker not in command or profile_root not in command:
                continue
            if self._activate_process(pid):
                return True
        return False

    def _terminate_process(self, pid, timeout=1.0):
        if pid == os.getpid():
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError:
            return
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            except OSError:
                return
            time.sleep(0.05)
        if hasattr(signal, "SIGKILL"):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def _terminate_tracked_process(self, profile_root):
        pid = self._read_tracked_pid(profile_root)
        if pid:
            self._terminate_process(pid)

    def _terminate_profile_processes(self, profile_root):
        profile_root = os.path.abspath(profile_root)
        self._terminate_tracked_process(profile_root)
        if os.name == "nt":
            return
        try:
            out = subprocess.check_output(
                ["ps", "-axo", "pid=,command="],
                text=True,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return
        marker = "--user-data-dir="
        for line in out.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) != 2:
                continue
            pid = int(parts[0])
            command = parts[1]
            if marker not in command or profile_root not in command:
                continue
            self._terminate_process(pid)

    def _remove_profiles(self, profile_root):
        self._terminate_profile_processes(profile_root)
        try:
            shutil.rmtree(profile_root)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def _add_browser_candidate(self, candidates, seen, label, executable):
        if not executable:
            return
        path = executable if os.path.isabs(executable) else shutil.which(executable)
        if not path:
            return
        path = os.path.abspath(os.path.expanduser(path))
        if path in seen:
            return
        seen.add(path)
        candidates.append((label, path))

    def _chromium_candidates(self):
        candidates = []
        seen = set()
        for env_name in self.browser_env:
            self._add_browser_candidate(candidates, seen, "configured browser", os.environ.get(env_name))

        if sys.platform == "darwin":
            mac_apps = [
                ("Google Chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                ("Microsoft Edge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                ("Brave Browser", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
                ("Chromium", "/Applications/Chromium.app/Contents/MacOS/Chromium"),
            ]
            for label, path in mac_apps:
                self._add_browser_candidate(candidates, seen, label, path)
        elif os.name == "nt":
            roots = [
                os.environ.get("PROGRAMFILES"),
                os.environ.get("PROGRAMFILES(X86)"),
                os.environ.get("LOCALAPPDATA"),
            ]
            windows_apps = [
                ("Google Chrome", ("Google", "Chrome", "Application", "chrome.exe")),
                ("Microsoft Edge", ("Microsoft", "Edge", "Application", "msedge.exe")),
                ("Brave Browser", ("BraveSoftware", "Brave-Browser", "Application", "brave.exe")),
            ]
            for root in roots:
                if not root:
                    continue
                for label, parts in windows_apps:
                    self._add_browser_candidate(candidates, seen, label, os.path.join(root, *parts))
        else:
            linux_apps = [
                ("Google Chrome", "google-chrome"),
                ("Google Chrome", "google-chrome-stable"),
                ("Microsoft Edge", "microsoft-edge"),
                ("Brave Browser", "brave-browser"),
                ("Chromium", "chromium"),
                ("Chromium", "chromium-browser"),
            ]
            for label, command in linux_apps:
                self._add_browser_candidate(candidates, seen, label, command)

        path_apps = [
            ("Google Chrome", "chrome"),
            ("Google Chrome", "google-chrome"),
            ("Microsoft Edge", "msedge"),
            ("Brave Browser", "brave"),
            ("Brave Browser", "brave-browser"),
            ("Chromium", "chromium"),
            ("Chromium", "chromium-browser"),
        ]
        for label, command in path_apps:
            self._add_browser_candidate(candidates, seen, label, command)
        return candidates
