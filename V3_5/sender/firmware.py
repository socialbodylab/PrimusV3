"""
firmware.py — Background jobs for compiling and uploading receiver firmware.
"""

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field

import paths


BOARD_PROFILES = {"v1", "v2", "v3"}
ACTIONS = {"list_ports", "install", "compile", "upload"}
PORT_MODES = {"auto", "selected", "all"}
RUNNING_STATES = {"queued", "running"}
MAX_OUTPUT_LINES = 800
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class FirmwareRequestError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class FirmwareCommand:
    action: str
    profile: str
    command: list
    redacted_command: list
    secrets: list = field(default_factory=list)


@dataclass
class FirmwareJob:
    id: str
    action: str
    profile: str
    command: list
    created_at: float
    status: str = "queued"
    started_at: float = None
    finished_at: float = None
    returncode: int = None
    error: str = ""
    result: dict = field(default_factory=dict)
    output: list = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def append_output(self, line):
        with self._lock:
            self.output.append(line)
            if len(self.output) > MAX_OUTPUT_LINES:
                self.output = self.output[-MAX_OUTPUT_LINES:]

    def set_status(self, status, **kwargs):
        with self._lock:
            self.status = status
            for key, value in kwargs.items():
                setattr(self, key, value)

    def to_json(self):
        with self._lock:
            duration = None
            if self.started_at and self.finished_at:
                duration = round(self.finished_at - self.started_at, 3)
            return {
                "id": self.id,
                "action": self.action,
                "profile": self.profile,
                "status": self.status,
                "command": list(self.command),
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "duration": duration,
                "returncode": self.returncode,
                "error": self.error,
                "result": dict(self.result or {}),
                "output": list(self.output),
            }


def default_upload_script_path():
    return os.path.abspath(os.path.join(paths.sender_dir(), "..", "Arduino", "upload.sh"))


def redact_text(text, secrets):
    value = ANSI_RE.sub("", str(text).rstrip("\r\n"))
    for secret in secrets:
        if secret:
            value = value.replace(secret, "********")
    return value


def redact_command(command):
    redacted = []
    redact_next = False
    for arg in command:
        if redact_next:
            redacted.append("********")
            redact_next = False
            continue
        redacted.append(arg)
        if arg in {"-pw", "--pw", "--password"}:
            redact_next = True
    return redacted


class FirmwareJobManager:
    def __init__(self, script_path=None, popen_factory=None, availability_checker=None, max_jobs=20):
        self.script_path = script_path or default_upload_script_path()
        self.popen_factory = popen_factory or subprocess.Popen
        self.availability_checker = availability_checker
        self.max_jobs = max_jobs
        self._jobs = OrderedDict()
        self._last_job_id = None
        self._lock = threading.RLock()

    def _path_env(self):
        env = os.environ.copy()
        repo_root = os.path.abspath(os.path.join(paths.sender_dir(), "..", ".."))
        prefixes = [
            os.path.join(repo_root, ".tools", "arduino-cli", "bin"),
            os.path.join(repo_root, ".tools", "python-bin"),
        ]
        path_parts = [p for p in prefixes if os.path.isdir(p)]
        path_parts.append(env.get("PATH", ""))
        env["PATH"] = os.pathsep.join(path_parts)
        return env

    def availability(self):
        if self.availability_checker:
            return self.availability_checker()

        env = self._path_env()
        script_exists = os.path.isfile(self.script_path)
        bash_available = shutil.which("bash", path=env.get("PATH")) is not None
        python_available = shutil.which("python3", path=env.get("PATH")) is not None
        arduino_cli_available = shutil.which("arduino-cli", path=env.get("PATH")) is not None
        available = script_exists and bash_available and python_available and arduino_cli_available
        missing = []
        if not script_exists:
            missing.append("upload.sh")
        if not bash_available:
            missing.append("bash")
        if not python_available:
            missing.append("python3")
        if not arduino_cli_available:
            missing.append("arduino-cli")
        message = "Firmware upload tools are ready."
        if missing:
            message = "Missing firmware upload requirement: " + ", ".join(missing)
        return {
            "available": available,
            "message": message,
            "script_path": self.script_path,
            "bash": bash_available,
            "python3": python_available,
            "arduino_cli": arduino_cli_available,
            "source_only": True,
        }

    def status(self):
        with self._lock:
            current = self._running_job_locked()
            last = self._jobs.get(self._last_job_id) if self._last_job_id else None
            return {
                **self.availability(),
                "current_job": current.to_json() if current else None,
                "last_job": last.to_json() if last else None,
            }

    def get_job(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise FirmwareRequestError(404, "firmware job not found")
            return job.to_json()

    def start_job(self, data):
        command = self.build_command(data or {})
        availability = self.availability()
        if not availability.get("available"):
            raise FirmwareRequestError(503, availability.get("message", "Firmware upload tools are unavailable."))

        with self._lock:
            running = self._running_job_locked()
            if running:
                raise FirmwareRequestError(409, "Firmware job already running")
            job = FirmwareJob(
                id=str(uuid.uuid4()),
                action=command.action,
                profile=command.profile,
                command=command.redacted_command,
                created_at=time.time(),
            )
            job.append_output("$ " + " ".join(command.redacted_command))
            self._jobs[job.id] = job
            self._last_job_id = job.id
            self._trim_jobs_locked()

        thread = threading.Thread(
            target=self._run_job,
            args=(job, command),
            daemon=True,
        )
        thread.start()
        return job.to_json()

    def build_command(self, data):
        action = self._validate_choice(data.get("action"), ACTIONS, "action")
        profile = self._validate_choice(data.get("profile", "v3"), BOARD_PROFILES, "profile")
        command = ["bash", self.script_path, "--board", profile]
        secrets = []

        if action == "list_ports":
            command.append("--ports-json")
        elif action == "install":
            command.append("--install")
        elif action == "compile":
            command.append("--compile")
            self._append_device_name_arg(command, data)
            self._append_wifi_args(command, data, secrets)
        elif action == "upload":
            port_mode = self._validate_choice(data.get("port_mode", "auto"), PORT_MODES, "port_mode")
            self._append_device_name_arg(command, data)
            self._append_wifi_args(command, data, secrets)
            if port_mode == "selected":
                command.append(self._validate_string(data.get("port", ""), "port", required=True, max_length=256))
            elif port_mode == "all":
                command.append("--all")
            else:
                command.append("--auto")

        redacted = redact_command(command)
        return FirmwareCommand(action=action, profile=profile, command=command, redacted_command=redacted, secrets=secrets)

    def _append_device_name_arg(self, command, data):
        device_name = self._validate_string(data.get("device_name", ""), "device_name", required=False, max_length=17)
        if device_name:
            command.extend(["--name", device_name])

    def _append_wifi_args(self, command, data, secrets):
        ssid = self._validate_string(data.get("wifi_ssid", ""), "wifi_ssid", required=False, max_length=64)
        password = self._validate_string(data.get("wifi_password", ""), "wifi_password", required=False, max_length=128)
        if ssid:
            command.extend(["-ssid", ssid])
        if password:
            command.extend(["-pw", password])
            secrets.append(password)

    def _validate_choice(self, value, choices, name):
        text = str(value or "").strip()
        if text not in choices:
            raise FirmwareRequestError(400, f"invalid {name}")
        return text

    def _validate_string(self, value, name, required=False, max_length=128):
        text = "" if value is None else str(value)
        if "\n" in text or "\r" in text:
            raise FirmwareRequestError(400, f"{name} cannot contain newlines")
        if len(text) > max_length:
            raise FirmwareRequestError(400, f"{name} is too long")
        if required and not text:
            raise FirmwareRequestError(400, f"{name} required")
        return text

    def _run_job(self, job, firmware_command):
        raw_lines = []
        job.set_status("running", started_at=time.time())
        try:
            proc = self.popen_factory(
                firmware_command.command,
                cwd=os.path.dirname(self.script_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=self._path_env(),
            )
            stdout = proc.stdout or []
            for line in stdout:
                raw_lines.append(line)
                clean = redact_text(line, firmware_command.secrets)
                if clean:
                    job.append_output(clean)
            returncode = proc.wait()
            result = {}
            error = ""
            status = "succeeded" if returncode == 0 else "failed"
            if firmware_command.action == "list_ports" and returncode == 0:
                try:
                    result = json.loads("".join(raw_lines) or "{}")
                except json.JSONDecodeError as exc:
                    status = "failed"
                    error = f"Could not parse port list JSON: {exc}"
            elif returncode != 0:
                error = f"upload.sh exited with code {returncode}"
            job.set_status(
                status,
                finished_at=time.time(),
                returncode=returncode,
                result=result,
                error=error,
            )
        except Exception as exc:
            job.append_output(redact_text(str(exc), firmware_command.secrets))
            job.set_status(
                "failed",
                finished_at=time.time(),
                returncode=None,
                error=str(exc),
            )

    def _running_job_locked(self):
        for job in self._jobs.values():
            if job.status in RUNNING_STATES:
                return job
        return None

    def _trim_jobs_locked(self):
        while len(self._jobs) > self.max_jobs:
            first_id, first_job = next(iter(self._jobs.items()))
            if first_job.status in RUNNING_STATES:
                break
            self._jobs.pop(first_id, None)


firmware_jobs = FirmwareJobManager()