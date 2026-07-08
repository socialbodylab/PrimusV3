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
import firmware_source


BOARD_PROFILES = {"v1", "v2", "v3", "radius_v1", "radius_v2"}
PRIMUS_PROFILES = {"v1", "v2", "v3"}
RADIUS_PROFILES = {"radius_v1", "radius_v2"}
FIRMWARE_PROFILES = {
    "v1": {
        "family": "primus",
        "script": "upload.sh",
        "label": "Primus V1",
        "detail": "2022 Original RUR performance (Huzzah32)",
    },
    "v2": {
        "family": "primus",
        "script": "upload.sh",
        "label": "Primus V2",
        "detail": "2025 Make Magazine ESP32 Feather",
    },
    "v3": {
        "family": "primus",
        "script": "upload.sh",
        "label": "Primus V3",
        "detail": "2026 Custom PCB / Reverse TFT Feather",
    },
    "radius_v1": {
        "family": "radius",
        "script": "radius_upload.sh",
        "label": "Radius V1",
        "detail": "Feather HUZZAH32 + Music Maker FeatherWing",
    },
    "radius_v2": {
        "family": "radius",
        "script": "radius_upload.sh",
        "label": "Radius V2",
        "detail": "ESP32-S3 Reverse TFT Feather + Music Maker FeatherWing",
    },
}
DEFAULT_PROFILE = "radius_v1"
FIRMWARE_SCOPES = {"product", "mixed"}


def active_board_profiles(scope="product"):
    if scope not in FIRMWARE_SCOPES:
        scope = "product"
    if scope == "mixed":
        return set(BOARD_PROFILES)
    if paths.sender_product() == "primus":
        return set(PRIMUS_PROFILES)
    return set(RADIUS_PROFILES)


def default_profile(scope="product"):
    profiles = active_board_profiles(scope)
    if DEFAULT_PROFILE in profiles:
        return DEFAULT_PROFILE
    if "v3" in profiles:
        return "v3"
    return next(iter(sorted(profiles)))
ACTIONS = {"setup_tools", "list_ports", "install", "compile", "upload", "download_firmware"}


def parse_ports_json_output(raw_lines):
    """Parse upload.sh --ports-json stdout, tolerating leading log lines."""
    text = "".join(raw_lines or [])
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for line in reversed(raw_lines or []):
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        return json.loads(stripped)
    raise json.JSONDecodeError("No JSON object found in port list output", text, 0)
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
    metadata: dict = field(default_factory=dict)


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
    metadata: dict = field(default_factory=dict)
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
                "metadata": dict(self.metadata or {}),
                "output": list(self.output),
            }


def arduino_root():
    if paths.is_primus_product():
        return firmware_source.active_firmware_root()
    return os.path.dirname(paths.resource_path("Arduino", "upload.sh"))


def upload_script_path(profile):
    meta = FIRMWARE_PROFILES.get(profile)
    if not meta:
        raise FirmwareRequestError(400, "invalid profile")
    if meta["family"] == "primus":
        return os.path.abspath(os.path.join(arduino_root(), meta["script"]))
    return os.path.abspath(paths.resource_path("Arduino", meta["script"]))


def default_upload_script_path():
    return upload_script_path("v3")


def firmware_profiles_json(scope="product"):
    if scope not in FIRMWARE_SCOPES:
        scope = "product"
    active = active_board_profiles(scope)
    families = {"primus": [], "radius": []}
    profiles = []
    for profile_id, meta in FIRMWARE_PROFILES.items():
        if profile_id not in active:
            continue
        entry = {
            "id": profile_id,
            "family": meta["family"],
            "label": meta["label"],
            "detail": meta["detail"],
            "script": meta["script"],
        }
        profiles.append(entry)
        families[meta["family"]].append(entry)
    return {
        "product": paths.sender_product(),
        "scope": scope,
        "profiles": profiles,
        "families": families,
    }


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

    def availability(self, scope="product"):
        if scope not in FIRMWARE_SCOPES:
            scope = "product"
        if self.availability_checker:
            return self.availability_checker()

        env = self._path_env()
        required_scripts = sorted({
            upload_script_path(profile)
            for profile in active_board_profiles(scope)
        })
        scripts_ok = all(os.path.isfile(path) for path in required_scripts)
        bash_available = shutil.which("bash", path=env.get("PATH")) is not None
        python_available = shutil.which("python3", path=env.get("PATH")) is not None
        arduino_cli_path = self._arduino_cli_path(env)
        arduino_cli_available = arduino_cli_path is not None
        available = scripts_ok and bash_available and python_available and arduino_cli_available
        missing = []
        if not scripts_ok:
            missing.append("firmware upload scripts")
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
            "can_install_tools": scripts_ok and bash_available,
            "source_only": False,
            **firmware_profiles_json(scope),
        }

    def status(self, scope="product"):
        with self._lock:
            current = self._running_job_locked()
            last = self._jobs.get(self._last_job_id) if self._last_job_id else None
            status = {
                **self.availability(scope),
                "current_job": current.to_json() if current else None,
                "last_job": last.to_json() if last else None,
            }
            if current and current.action == "setup_tools":
                status["tool_status"] = "installing"
                status["can_install_tools"] = False
                status["message"] = "Installing firmware tools..."
            if paths.is_primus_product():
                status["firmware"] = firmware_source.local_firmware_info()
                update_info = firmware_source.check_github_updates(force=False)
                status["update"] = update_info
            return status

    def check_firmware_updates(self, force=False):
        if not paths.is_primus_product():
            return {"enabled": False, "error": "Firmware updates are Primus-only."}
        return firmware_source.check_github_updates(force=force)

    def get_job(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise FirmwareRequestError(404, "firmware job not found")
            return job.to_json()

    def start_job(self, data, device_state=None):
        data = data or {}
        scope = data.get("scope", "product")
        command = self.build_command(data)
        availability = self.availability(scope)
        if command.action not in ("setup_tools", "download_firmware") and not availability.get("available"):
            raise FirmwareRequestError(503, availability.get("message", "Firmware upload tools are unavailable."))

        with self._lock:
            running = self._running_job_locked()
            if running:
                raise FirmwareRequestError(409, "Firmware job already running")
            from serial_monitor import serial_monitor
            if serial_monitor.is_active():
                raise FirmwareRequestError(409, "Serial monitor is running")
            job = FirmwareJob(
                id=str(uuid.uuid4()),
                action=command.action,
                profile=command.profile,
                command=command.redacted_command,
                metadata=command.metadata,
                created_at=time.time(),
            )
            job.append_output("$ " + " ".join(command.redacted_command))
            for line in self._metadata_output_lines(command.metadata):
                job.append_output(line)
            self._jobs[job.id] = job
            self._last_job_id = job.id
            self._trim_jobs_locked()

        thread = threading.Thread(
            target=self._run_job,
            args=(job, command, device_state),
            daemon=True,
        )
        thread.start()
        return job.to_json()

    def build_command(self, data):
        data = data or {}
        scope = data.get("scope", "product")
        if scope not in FIRMWARE_SCOPES:
            raise FirmwareRequestError(400, "invalid scope")
        action = self._validate_choice(data.get("action"), ACTIONS, "action")
        profile = self._validate_choice(
            data.get("profile", default_profile(scope)),
            active_board_profiles(scope),
            "profile",
        )
        script_path = upload_script_path(profile)
        if action == "setup_tools":
            command = ["firmware-tools", "setup"]
            return FirmwareCommand(
                action=action,
                profile=profile,
                command=command,
                redacted_command=command,
                metadata={**self._build_metadata(action, profile), "scope": scope},
            )
        if action == "download_firmware":
            if not paths.is_primus_product():
                raise FirmwareRequestError(400, "download_firmware is Primus-only")
            update_info = firmware_source.check_github_updates(force=True)
            if update_info.get("error"):
                raise FirmwareRequestError(502, update_info["error"])
            if not update_info.get("update_available"):
                raise FirmwareRequestError(409, "No firmware update available")
            if not update_info.get("asset_url") or not update_info.get("sha256"):
                raise FirmwareRequestError(502, "Firmware release asset or checksum is unavailable")
            command = ["firmware-download"]
            return FirmwareCommand(
                action=action,
                profile=profile,
                command=command,
                redacted_command=command,
                metadata={
                    **self._build_metadata(action, profile),
                    "update": {
                        "remote_version": update_info.get("remote_version"),
                        "release_tag": update_info.get("release_tag"),
                        "asset_name": update_info.get("asset_name"),
                        "asset_url": update_info.get("asset_url"),
                        "sha256": update_info.get("sha256"),
                    },
                },
            )

        command = ["bash", script_path, "--board", profile]
        secrets = []
        device_name = ""
        character_name = ""
        performer_name = ""
        wifi_ssid = ""
        wifi_password_set = False
        ip_override = None
        receive_override = None
        port_mode = None
        port = ""

        if action == "list_ports":
            command.append("--ports-json")
        elif action == "install":
            command.append("--install")
        elif action == "compile":
            command.append("--compile")
            device_name = self._append_device_name_arg(command, data)
            character_name, performer_name = self._append_show_info_args(command, data)
            wifi_ssid, wifi_password_set = self._append_wifi_args(command, data, secrets)
            ip_override = self._append_ip_args(command, data)
            receive_override = self._append_receive_mode_args(command, data, profile)
        elif action == "upload":
            port_mode = self._validate_choice(data.get("port_mode", "auto"), PORT_MODES, "port_mode")
            device_name = self._append_device_name_arg(command, data)
            character_name, performer_name = self._append_show_info_args(command, data)
            wifi_ssid, wifi_password_set = self._append_wifi_args(command, data, secrets)
            ip_override = self._append_ip_args(command, data)
            receive_override = self._append_receive_mode_args(command, data, profile)
            if port_mode == "selected":
                port = self._validate_string(data.get("port", ""), "port", required=True, max_length=256)
                command.append(port)
            elif port_mode == "all":
                command.append("--all")
            else:
                command.append("--auto")

        redacted = redact_command(command)
        metadata = self._build_metadata(
            action,
            profile,
            device_name=device_name,
            character_name=character_name,
            performer_name=performer_name,
            wifi_ssid=wifi_ssid,
            wifi_password_set=wifi_password_set,
            ip_override=ip_override,
            receive_override=receive_override,
            port_mode=port_mode,
            port=port,
        )
        return FirmwareCommand(
            action=action,
            profile=profile,
            command=command,
            redacted_command=redacted,
            secrets=secrets,
            metadata=metadata,
        )

    def _append_device_name_arg(self, command, data):
        device_name = self._validate_string(data.get("device_name", ""), "device_name", required=False, max_length=17)
        if device_name:
            command.extend(["--name", device_name])
        return device_name

    def _append_show_info_args(self, command, data):
        character_name = self._validate_string(
            data.get("character_name", ""),
            "character_name",
            required=False,
            max_length=64,
        )
        performer_name = self._validate_string(
            data.get("performer_name", ""),
            "performer_name",
            required=False,
            max_length=64,
        )
        if character_name:
            command.extend(["--character-name", character_name])
        if performer_name:
            command.extend(["--performer-name", performer_name])
        return character_name, performer_name

    def _append_wifi_args(self, command, data, secrets):
        ssid = self._validate_string(data.get("wifi_ssid", ""), "wifi_ssid", required=False, max_length=64)
        password = self._validate_string(data.get("wifi_password", ""), "wifi_password", required=False, max_length=128)
        if bool(ssid) != bool(password):
            raise FirmwareRequestError(400, "wifi_ssid and wifi_password must be provided together")
        if ssid:
            command.extend(["-ssid", ssid])
        if password:
            command.extend(["-pw", password])
            secrets.append(password)
        return ssid, bool(password)

    def _append_ip_args(self, command, data):
        mode = self._validate_choice(data.get("ip_mode", "keep"), {"keep", "static", "dhcp"}, "ip_mode")
        if mode == "keep":
            return None
        if mode == "dhcp":
            command.append("--dhcp")
            return {"mode": "dhcp"}

        static_ip = self._validate_ipv4_string(data.get("static_ip", ""), "static_ip")
        gateway = self._validate_ipv4_string(data.get("gateway", ""), "gateway")
        subnet = self._validate_ipv4_string(data.get("subnet", ""), "subnet")
        command.extend(["--static-ip", static_ip, "--gateway", gateway, "--subnet", subnet])
        return {
            "mode": "static",
            "static_ip": static_ip,
            "gateway": gateway,
            "subnet": subnet,
        }

    def _append_receive_mode_args(self, command, data, profile):
        if FIRMWARE_PROFILES.get(profile, {}).get("family") != "primus":
            return None
        mode = self._validate_choice(
            data.get("receive_mode_mode", "keep"),
            {"keep", "split", "combined"},
            "receive_mode_mode",
        )
        if mode == "keep":
            return None
        command.extend(["--receivemode", mode])
        try:
            base_universe = int(data.get("base_universe", 0))
        except (TypeError, ValueError):
            raise FirmwareRequestError(400, "base_universe must be an integer")
        if base_universe < 0 or base_universe > 32767:
            raise FirmwareRequestError(400, "base_universe must be 0-32767")
        command.extend(["--universe", str(base_universe)])
        return {"mode": mode, "base_universe": base_universe}

    def _build_metadata(self, action, profile, device_name="", character_name="", performer_name="",
                        wifi_ssid="", wifi_password_set=False,
                        ip_override=None, receive_override=None, port_mode=None, port=""):
        overrides = {
            "device_name": device_name or None,
            "character_name": character_name or None,
            "performer_name": performer_name or None,
            "wifi_ssid": wifi_ssid or None,
            "wifi_password_set": bool(wifi_password_set),
            "ip_mode": (ip_override or {}).get("mode", "keep"),
            "static_ip": (ip_override or {}).get("static_ip"),
            "gateway": (ip_override or {}).get("gateway"),
            "subnet": (ip_override or {}).get("subnet"),
            "receive_mode_mode": (receive_override or {}).get("mode", "keep"),
            "base_universe": (receive_override or {}).get("base_universe"),
        }
        metadata = {
            "profile": profile,
            "family": FIRMWARE_PROFILES[profile]["family"],
            "overrides": overrides,
            "has_overrides": bool(
                overrides["device_name"]
                or overrides["character_name"]
                or overrides["performer_name"]
                or overrides["wifi_ssid"]
                or overrides["wifi_password_set"]
                or overrides["ip_mode"] != "keep"
                or overrides["receive_mode_mode"] != "keep"
            ),
        }
        if action == "upload":
            metadata["target"] = {
                "port_mode": port_mode or "auto",
                "port": port or None,
            }
        return metadata

    def _metadata_output_lines(self, metadata):
        if not metadata:
            return []
        lines = []
        overrides = metadata.get("overrides") or {}
        if metadata.get("has_overrides"):
            parts = []
            if overrides.get("device_name"):
                parts.append(f"device name '{overrides['device_name']}'")
            if overrides.get("character_name"):
                parts.append(f"character name '{overrides['character_name']}'")
            if overrides.get("performer_name"):
                parts.append(f"performer name '{overrides['performer_name']}'")
            if overrides.get("wifi_ssid"):
                parts.append(f"WiFi SSID '{overrides['wifi_ssid']}'")
            if overrides.get("wifi_password_set"):
                parts.append("WiFi password set")
            if overrides.get("ip_mode") == "static":
                parts.append(
                    "static IP " + overrides.get("static_ip", "")
                    + " gateway " + overrides.get("gateway", "")
                    + " subnet " + overrides.get("subnet", ""))
            elif overrides.get("ip_mode") == "dhcp":
                parts.append("DHCP enabled")
            if overrides.get("receive_mode_mode") == "split":
                parts.append(
                    "receive mode split, base universe "
                    + str(overrides.get("base_universe", 0)))
            elif overrides.get("receive_mode_mode") == "combined":
                parts.append(
                    "receive mode combined, base universe "
                    + str(overrides.get("base_universe", 0)))
            lines.append("Overrides: " + "; ".join(parts))
        else:
            lines.append("Overrides: firmware defaults from config.h")
        target = metadata.get("target") or {}
        if target:
            mode = target.get("port_mode") or "auto"
            if mode == "selected" and target.get("port"):
                lines.append(f"Upload target: {target['port']}")
            elif mode == "all":
                lines.append("Upload target: all detected ESP32-like ports")
            else:
                lines.append("Upload target: auto-detect one ESP32-like port")
        return lines

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

    def _validate_ipv4_string(self, value, name):
        text = self._validate_string(value, name, required=True, max_length=15)
        parts = text.split(".")
        if len(parts) != 4:
            raise FirmwareRequestError(400, f"invalid {name}")
        for part in parts:
            if not part.isdigit():
                raise FirmwareRequestError(400, f"invalid {name}")
            octet = int(part, 10)
            if octet < 0 or octet > 255:
                raise FirmwareRequestError(400, f"invalid {name}")
        return text

    def _has_name_overrides(self, metadata):
        overrides = (metadata or {}).get("overrides") or {}
        return bool(
            overrides.get("device_name")
            or overrides.get("character_name")
            or overrides.get("performer_name")
        )

    def _refresh_device_state_after_upload(self, device_state, metadata):
        if not device_state or not hasattr(device_state, "refresh_after_firmware_upload"):
            return
        if not self._has_name_overrides(metadata):
            return
        try:
            overrides = (metadata or {}).get("overrides") or {}
            device_state.refresh_after_firmware_upload(overrides)
        except Exception as exc:
            return str(exc)

    def _run_job(self, job, firmware_command, device_state=None):
        raw_lines = []
        job.set_status("running", started_at=time.time())
        try:
            if firmware_command.action == "setup_tools":
                self._run_setup_tools_job(job)
                return
            if firmware_command.action == "download_firmware":
                self._run_download_firmware_job(job, firmware_command)
                return
            if firmware_command.action in ("compile", "upload"):
                job.append_output("Launching upload script...")
                job.append_output(
                    "Waiting for compiler output (this may take 10–30 seconds)...")
            proc = self.popen_factory(
                firmware_command.command,
                cwd=os.path.dirname(firmware_command.command[1]),
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
                    result = parse_ports_json_output(raw_lines)
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
            if (
                status == "succeeded"
                and firmware_command.action == "upload"
                and device_state is not None
            ):
                overrides = (firmware_command.metadata or {}).get("overrides") or {}
                if self._has_name_overrides(firmware_command.metadata):
                    job.append_output(
                        "Waiting for receiver reboot, then applying name overrides...")
                refresh_error = self._refresh_device_state_after_upload(
                    device_state, firmware_command.metadata)
                if refresh_error:
                    job.append_output(
                        f"Upload succeeded, but device refresh failed: {refresh_error}")
                elif self._has_name_overrides(firmware_command.metadata):
                    job.append_output("Name overrides applied to online receivers.")
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

    def _run_download_firmware_job(self, job, firmware_command):
        update = (firmware_command.metadata or {}).get("update") or {}
        try:
            result = firmware_source.install_firmware_bundle(
                asset_url=update.get("asset_url"),
                expected_sha256=update.get("sha256"),
                release_tag=update.get("release_tag"),
                asset_name=update.get("asset_name"),
                job=job,
            )
            job.set_status(
                "succeeded",
                finished_at=time.time(),
                returncode=0,
                result=result,
                error="",
            )
        except Exception as exc:
            job.append_output(str(exc))
            job.set_status(
                "failed",
                finished_at=time.time(),
                returncode=None,
                error=str(exc),
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

    def has_running_job(self):
        with self._lock:
            return self._running_job_locked() is not None

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
        for profile in sorted(active_board_profiles((job.metadata or {}).get("scope", "product"))):
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
        script_path = upload_script_path(profile)
        if not os.path.isfile(script_path):
            raise RuntimeError(f"upload script not found: {script_path}")
        self.manager._run_streamed_command(
            job,
            [bash, script_path, "--board", profile, "--install"],
            cwd=os.path.dirname(script_path),
            env=env,
        )


firmware_jobs = FirmwareJobManager()