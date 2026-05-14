"""
firmware.py — Background jobs for compiling and uploading receiver firmware.
"""

import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.request
import uuid
import zipfile
from collections import OrderedDict
from dataclasses import dataclass, field

import paths


BOARD_PROFILES = {"v1", "v2", "v3"}
ACTIONS = {"setup_tools", "list_ports", "install", "compile", "upload"}
PORT_MODES = {"auto", "selected", "all"}
RUNNING_STATES = {"queued", "running"}
MAX_OUTPUT_LINES = 800
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
ESP32_PACKAGE_URL = "https://espressif.github.io/arduino-esp32/package_esp32_index.json"
ARDUINO_RELEASE_API = "https://api.github.com/repos/arduino/arduino-cli/releases/latest"


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
    return os.path.abspath(paths.resource_path("Arduino", "upload.sh"))


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
    def __init__(self, script_path=None, popen_factory=None, availability_checker=None,
                 tool_installer=None, max_jobs=20):
        self.script_path = script_path or default_upload_script_path()
        self.popen_factory = popen_factory or subprocess.Popen
        self.availability_checker = availability_checker
        self.tool_installer = tool_installer
        self.max_jobs = max_jobs
        self._jobs = OrderedDict()
        self._last_job_id = None
        self._lock = threading.RLock()

    def _path_env(self):
        env = os.environ.copy()
        repo_root = paths.repo_root()
        prefixes = [
            paths.arduino_cli_bin_dir(),
            paths.python_shim_dir(),
            os.path.join(repo_root, ".tools", "arduino-cli", "bin"),
            os.path.join(repo_root, ".tools", "python-bin"),
        ]
        path_parts = [p for p in prefixes if os.path.isdir(p)]
        path_parts.append(env.get("PATH", ""))
        env["PATH"] = os.pathsep.join(path_parts)
        cli_path = self._arduino_cli_path(env)
        if cli_path:
            env["ARDUINO_CLI"] = cli_path
        env.setdefault("PRIMUSV3_PYTHON_BIN_DIR", paths.python_shim_dir())
        env.setdefault("ARDUINO_CONFIG_FILE", paths.arduino_config_file())
        env.setdefault("ARDUINO_DIRECTORIES_DATA", paths.arduino_data_dir())
        env.setdefault("ARDUINO_DIRECTORIES_DOWNLOADS", paths.arduino_downloads_dir())
        env.setdefault("ARDUINO_DIRECTORIES_USER", paths.arduino_user_dir())
        return env

    def _arduino_cli_path(self, env=None):
        managed_cli = paths.arduino_cli_executable()
        if os.path.isfile(managed_cli):
            return managed_cli
        search_path = (env or os.environ).get("PATH")
        found = shutil.which("arduino-cli", path=search_path)
        return found

    def availability(self):
        if self.availability_checker:
            return self.availability_checker()

        env = self._path_env()
        script_exists = os.path.isfile(self.script_path)
        bash_available = shutil.which("bash", path=env.get("PATH")) is not None
        python_available = shutil.which("python3", path=env.get("PATH")) is not None
        arduino_cli_path = self._arduino_cli_path(env)
        arduino_cli_available = arduino_cli_path is not None
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
        if missing == ["arduino-cli"]:
            message = "Firmware tools are not installed. Install Firmware Tools to enable compile and upload."
        if available:
            tool_status = "ready"
        elif not arduino_cli_available:
            tool_status = "missing_cli"
        else:
            tool_status = "missing_requirements"
        return {
            "available": available,
            "message": message,
            "script_path": self.script_path,
            "bash": bash_available,
            "python3": python_available,
            "arduino_cli": arduino_cli_available,
            "arduino_cli_path": arduino_cli_path,
            "tools_dir": paths.tools_dir(),
            "tool_status": tool_status,
            "can_install_tools": script_exists and bash_available,
            "source_only": False,
        }

    def status(self):
        with self._lock:
            current = self._running_job_locked()
            last = self._jobs.get(self._last_job_id) if self._last_job_id else None
            status = {
                **self.availability(),
                "current_job": current.to_json() if current else None,
                "last_job": last.to_json() if last else None,
            }
            if current and current.action == "setup_tools":
                status["tool_status"] = "installing"
                status["can_install_tools"] = False
                status["message"] = "Installing firmware tools..."
            return status

    def get_job(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise FirmwareRequestError(404, "firmware job not found")
            return job.to_json()

    def start_job(self, data):
        command = self.build_command(data or {})
        availability = self.availability()
        if command.action != "setup_tools" and not availability.get("available"):
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
        if action == "setup_tools":
            command = ["firmware-tools", "setup"]
            return FirmwareCommand(action=action, profile=profile, command=command, redacted_command=command)

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
            if firmware_command.action == "setup_tools":
                self._run_setup_tools_job(job)
                return
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

    def _run_setup_tools_job(self, job):
        if self.tool_installer:
            result = self.tool_installer(job, self) or {}
        else:
            result = ArduinoCliInstaller(self).install(job)
        job.set_status(
            "succeeded",
            finished_at=time.time(),
            returncode=0,
            result=result,
            error="",
        )

    def _run_streamed_command(self, job, command, cwd=None, env=None, check=True):
        job.append_output("$ " + " ".join(redact_command(command)))
        proc = self.popen_factory(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env or self._path_env(),
        )
        stdout = proc.stdout or []
        for line in stdout:
            clean = redact_text(line, [])
            if clean:
                job.append_output(clean)
        returncode = proc.wait()
        if check and returncode != 0:
            raise RuntimeError(f"Command failed with code {returncode}: {' '.join(command)}")
        return returncode

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


class ArduinoCliInstaller:
    def __init__(self, manager):
        self.manager = manager

    def install(self, job):
        paths.ensure_tools_data()
        cli_path = paths.arduino_cli_executable()
        job.append_output(f"Tools directory: {paths.tools_dir()}")
        if os.path.isfile(cli_path):
            job.append_output(f"Arduino CLI already installed: {cli_path}")
        else:
            self._download_arduino_cli(job, cli_path)

        env = self.manager._path_env()
        self._run_cli(job, ["version"], env=env, check=False)
        self._configure_esp32(job, env)
        for profile in ("v1", "v2", "v3"):
            self._run_upload_install(job, profile, env)
        job.append_output("Firmware tools are ready.")
        return {
            "tools_dir": paths.tools_dir(),
            "arduino_cli": cli_path,
        }

    def _download_arduino_cli(self, job, cli_path):
        asset = self._find_arduino_release_asset()
        job.append_output(f"Downloading Arduino CLI: {asset['name']}")
        with tempfile.TemporaryDirectory() as tmp_dir:
            archive_path = os.path.join(tmp_dir, asset["name"])
            request = urllib.request.Request(
                asset["browser_download_url"],
                headers={"User-Agent": "PrimusCentral firmware tools"},
            )
            with urllib.request.urlopen(request) as response, open(archive_path, "wb") as output:
                shutil.copyfileobj(response, output)
            self._extract_arduino_cli(archive_path, cli_path)
        job.append_output(f"Installed Arduino CLI: {cli_path}")

    def _find_arduino_release_asset(self):
        request = urllib.request.Request(
            ARDUINO_RELEASE_API,
            headers={"User-Agent": "PrimusCentral firmware tools"},
        )
        with urllib.request.urlopen(request) as response:
            release = json.loads(response.read().decode("utf-8"))

        os_token = {
            "Darwin": "macOS",
            "Linux": "Linux",
            "Windows": "Windows",
        }.get(platform.system())
        if not os_token:
            raise RuntimeError(f"Unsupported OS for Arduino CLI install: {platform.system()}")

        machine = platform.machine().lower()
        if machine in ("x86_64", "amd64"):
            arch_tokens = ("64bit", "x86_64", "amd64")
        elif machine in ("arm64", "aarch64"):
            arch_tokens = ("arm64", "aarch64")
        elif machine.startswith("arm"):
            arch_tokens = ("arm",)
        else:
            raise RuntimeError(f"Unsupported CPU architecture for Arduino CLI install: {platform.machine()}")

        for asset in release.get("assets", []):
            name = asset.get("name", "")
            lower = name.lower()
            if not (lower.endswith(".tar.gz") or lower.endswith(".zip")):
                continue
            if os_token.lower() not in lower:
                continue
            if any(token.lower() in lower for token in arch_tokens):
                return asset
        raise RuntimeError("Could not find a matching Arduino CLI release asset.")

    def _extract_arduino_cli(self, archive_path, cli_path):
        exe = os.path.basename(cli_path)
        os.makedirs(os.path.dirname(cli_path), exist_ok=True)
        if archive_path.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as archive:
                for member in archive.namelist():
                    if os.path.basename(member) == exe:
                        with archive.open(member) as source, open(cli_path, "wb") as output:
                            shutil.copyfileobj(source, output)
                        break
                else:
                    raise RuntimeError("Arduino CLI executable not found in downloaded zip.")
        else:
            with tarfile.open(archive_path, "r:gz") as archive:
                for member in archive.getmembers():
                    if os.path.basename(member.name) == exe:
                        source = archive.extractfile(member)
                        if source is None:
                            continue
                        with source, open(cli_path, "wb") as output:
                            shutil.copyfileobj(source, output)
                        break
                else:
                    raise RuntimeError("Arduino CLI executable not found in downloaded archive.")
        os.chmod(cli_path, os.stat(cli_path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def _run_cli(self, job, args, env, check=True):
        command = [paths.arduino_cli_executable(), *args]
        return self.manager._run_streamed_command(job, command, env=env, check=check)

    def _configure_esp32(self, job, env):
        self._run_cli(job, ["config", "init"], env=env, check=False)
        self._run_cli(job, ["config", "add", "board_manager.additional_urls", ESP32_PACKAGE_URL], env=env, check=False)
        self._run_cli(job, ["core", "update-index"], env=env)

    def _run_upload_install(self, job, profile, env):
        bash = shutil.which("bash", path=env.get("PATH"))
        if not bash:
            raise RuntimeError("bash is required to install firmware libraries.")
        if not os.path.isfile(self.manager.script_path):
            raise RuntimeError(f"upload.sh not found: {self.manager.script_path}")
        self.manager._run_streamed_command(
            job,
            [bash, self.manager.script_path, "--board", profile, "--install"],
            cwd=os.path.dirname(self.manager.script_path),
            env=env,
        )


firmware_jobs = FirmwareJobManager()