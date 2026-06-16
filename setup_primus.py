#!/usr/bin/env python3
"""First-time setup helper for PrimusV3.

Python itself is intentionally out of scope: install Python 3 manually, then run
this script from the repository root. The script creates/checks the local Python
environment and prepares Arduino CLI tooling for V3.5 firmware uploads.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import venv
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
TOOLS_DIR = ROOT / ".tools"
PYTHON_SHIM_DIR = TOOLS_DIR / "python-bin"
ARDUINO_TOOL_DIR = TOOLS_DIR / "arduino-cli"
ARDUINO_BIN_DIR = ARDUINO_TOOL_DIR / "bin"
UPLOAD_SCRIPT = ROOT / "V3_5" / "Arduino" / "upload.sh"
SENDER_RUN = ROOT / "V3_5" / "sender" / "run.py"
ESP32_PACKAGE_URL = "https://espressif.github.io/arduino-esp32/package_esp32_index.json"
ARDUINO_RELEASE_API = "https://api.github.com/repos/arduino/arduino-cli/releases/latest"
SUPPORTED_PROFILES = ("v1", "v2", "v3")
REQUIRED_LIBRARIES = {
    "v1": ("Adafruit NeoPixel",),
    "v2": ("Adafruit NeoPixel",),
    "v3": (
        "Adafruit NeoPXL8",
        "Adafruit ST7735 and ST7789 Library",
        "Adafruit GFX Library",
    ),
}


class SetupError(RuntimeError):
    pass


def section(title: str) -> None:
    print(f"\n== {title} ==")


def info(message: str) -> None:
    print(f"[INFO] {message}")


def ok(message: str) -> None:
    print(f"[OK]   {message}")


def warn(message: str) -> None:
    print(f"[WARN] {message}")


def fail(message: str) -> None:
    print(f"[FAIL] {message}")


def command_text(command: list[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in command)


def display_path(path: Path) -> str:
    try:
        return str(path.absolute().relative_to(ROOT))
    except ValueError:
        return str(path)


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path = ROOT,
    capture: bool = False,
    check: bool = True,
    quiet: bool = False,
) -> subprocess.CompletedProcess[str]:
    if not quiet:
        print(f"$ {command_text(command)}")
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
            check=False,
        )
    except FileNotFoundError as exc:
        if check:
            raise SetupError(f"Command not found: {command[0]}") from exc
        return subprocess.CompletedProcess(command, 127, "")

    if capture and result.stdout and not quiet:
        print(result.stdout.rstrip())
    if check and result.returncode != 0:
        output = (result.stdout or "").strip()
        detail = f"\n{output}" if output else ""
        raise SetupError(f"Command failed ({result.returncode}): {command_text(command)}{detail}")
    return result


def is_windows() -> bool:
    return os.name == "nt"


def is_wsl() -> bool:
    if platform.system().lower() != "linux":
        return False
    try:
        text = Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return "microsoft" in text or "wsl" in text


def executable_name(base: str) -> str:
    return f"{base}.exe" if is_windows() else base


def venv_python() -> Path:
    if is_windows():
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def local_arduino_cli() -> Path:
    return ARDUINO_BIN_DIR / executable_name("arduino-cli")


def parse_profiles(value: str) -> tuple[str, ...]:
    if value.strip().lower() == "all":
        return SUPPORTED_PROFILES
    profiles = []
    for raw in value.split(","):
        profile = raw.strip().lower().lstrip("-")
        if not profile:
            continue
        if profile not in SUPPORTED_PROFILES:
            raise argparse.ArgumentTypeError(
                f"unknown profile {raw!r}; expected comma-separated v1,v2,v3"
            )
        profiles.append(profile)
    if not profiles:
        raise argparse.ArgumentTypeError("at least one profile is required")
    return tuple(dict.fromkeys(profiles))


def prepend_path(env: dict[str, str], *paths: Path) -> dict[str, str]:
    existing = env.get("PATH", "")
    parts = [str(path) for path in paths if path and path.exists()]
    env["PATH"] = os.pathsep.join(parts + ([existing] if existing else []))
    return env


class PrimusSetup:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.profiles: tuple[str, ...] = args.profiles
        self.issues: list[str] = []
        self.arduino_cli: Path | None = None

    def issue(self, message: str) -> None:
        self.issues.append(message)
        fail(message)

    def base_env(self) -> dict[str, str]:
        env = os.environ.copy()
        paths = []
        if self.arduino_cli:
            paths.append(self.arduino_cli.parent)
        if local_arduino_cli().exists():
            paths.append(ARDUINO_BIN_DIR)
        if PYTHON_SHIM_DIR.exists():
            paths.append(PYTHON_SHIM_DIR)
        return prepend_path(env, *paths)

    def find_arduino_cli(self) -> Path | None:
        if self.args.arduino_cli:
            candidate = Path(self.args.arduino_cli).expanduser()
            if candidate.exists():
                return candidate.resolve()
            raise SetupError(f"Arduino CLI path does not exist: {candidate}")

        path_cli = shutil.which("arduino-cli")
        if path_cli:
            return Path(path_cli).resolve()

        local_cli = local_arduino_cli()
        if local_cli.exists():
            return local_cli.resolve()
        return None

    def ensure_python_environment(self) -> None:
        section("Python environment")
        if sys.version_info < (3, 9):
            raise SetupError("Python 3.9 or newer is recommended for PrimusV3 setup.")
        ok(f"Python {platform.python_version()} at {sys.executable}")

        if self.args.skip_venv:
            warn("Skipping .venv setup (--skip-venv).")
            return

        python_path = venv_python()
        if python_path.exists() and not self.args.force:
            ok(f"Virtual environment already exists: {python_path}")
        else:
            action = "Recreating" if VENV_DIR.exists() and self.args.force else "Creating"
            info(f"{action} virtual environment: {VENV_DIR}")
            try:
                venv.EnvBuilder(with_pip=True, clear=self.args.force).create(VENV_DIR)
            except Exception as exc:
                raise SetupError(
                    "Could not create .venv. On Debian/Ubuntu, install python3-venv first."
                ) from exc
            ok(f"Virtual environment ready: {python_path}")

        self.install_python_requirements(python_path)
        self.ensure_python3_shim()

    def install_python_requirements(self, python_path: Path) -> None:
        requirements = [
            ROOT / "requirements.txt",
            ROOT / "V3_5" / "sender" / "requirements.txt",
        ]
        existing = [path for path in requirements if path.exists()]
        if not existing:
            ok("No Python package requirements found; sender uses Python stdlib only.")
            return
        for requirements_file in existing:
            info(f"Installing Python packages from {requirements_file.relative_to(ROOT)}")
            run([str(python_path), "-m", "pip", "install", "-r", str(requirements_file)])

    def ensure_python3_shim(self) -> None:
        if shutil.which("python3"):
            ok("python3 command is available for upload.sh.")
            return
        if is_windows():
            warn("python3 is not on PATH. Git Bash/WSL users may need to add it before upload.sh can run.")
            return
        PYTHON_SHIM_DIR.mkdir(parents=True, exist_ok=True)
        shim = PYTHON_SHIM_DIR / "python3"
        shim.write_text(f"#!/usr/bin/env sh\nexec {shlex.quote(sys.executable)} \"$@\"\n", encoding="utf-8")
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        ok(f"Created python3 shim for upload.sh: {shim}")

    def check_python_environment(self) -> None:
        section("Python environment")
        if sys.version_info >= (3, 9):
            ok(f"Python {platform.python_version()} at {sys.executable}")
        else:
            self.issue("Python 3.9 or newer is recommended.")

        if self.args.skip_venv:
            warn("Skipping .venv check (--skip-venv).")
        elif venv_python().exists():
            ok(f"Virtual environment exists: {venv_python()}")
        else:
            self.issue("Virtual environment is missing. Run without --check to create .venv.")

        if shutil.which("python3") or (PYTHON_SHIM_DIR / "python3").exists():
            ok("python3 command is available for upload.sh.")
        else:
            self.issue("python3 command is missing for upload.sh.")

    def ensure_arduino_cli(self) -> None:
        section("Arduino CLI")
        self.arduino_cli = self.find_arduino_cli()
        if self.arduino_cli:
            ok(f"Arduino CLI found: {self.arduino_cli}")
            self.print_arduino_version()
            return

        info("Arduino CLI was not found on PATH or in .tools.")
        self.install_arduino_cli()
        self.arduino_cli = self.find_arduino_cli()
        if not self.arduino_cli:
            raise SetupError("Arduino CLI installation did not produce an arduino-cli executable.")
        ok(f"Arduino CLI installed: {self.arduino_cli}")
        self.print_arduino_version()

    def print_arduino_version(self) -> None:
        if not self.arduino_cli:
            return
        result = run([str(self.arduino_cli), "version"], capture=True, quiet=True, check=False)
        if result.returncode == 0 and result.stdout:
            ok(result.stdout.strip())
        else:
            warn("Could not read Arduino CLI version.")

    def check_arduino_cli(self) -> None:
        section("Arduino CLI")
        self.arduino_cli = self.find_arduino_cli()
        if not self.arduino_cli:
            self.issue("Arduino CLI is missing. Run without --check to install or configure it.")
            return
        ok(f"Arduino CLI found: {self.arduino_cli}")
        self.print_arduino_version()

    def install_arduino_cli(self) -> None:
        if is_windows() and not is_wsl():
            winget = shutil.which("winget")
            if winget:
                info("Installing Arduino CLI with winget.")
                run([winget, "install", "--id", "ArduinoSA.CLI", "-e"])
                return
            raise SetupError(
                "Arduino CLI is missing. On native Windows, install it with "
                "winget install ArduinoSA.CLI or use WSL/Git Bash."
            )

        ARDUINO_BIN_DIR.mkdir(parents=True, exist_ok=True)
        info("Downloading latest Arduino CLI release into .tools/arduino-cli/bin.")
        asset = self.find_arduino_release_asset()
        with tempfile.TemporaryDirectory() as tmp_dir:
            archive_path = Path(tmp_dir) / asset["name"]
            request = urllib.request.Request(
                asset["browser_download_url"],
                headers={"User-Agent": "PrimusV3 setup_primus.py"},
            )
            with urllib.request.urlopen(request) as response, archive_path.open("wb") as output:
                shutil.copyfileobj(response, output)
            self.extract_arduino_cli(archive_path)

    def find_arduino_release_asset(self) -> dict[str, str]:
        request = urllib.request.Request(
            ARDUINO_RELEASE_API,
            headers={"User-Agent": "PrimusV3 setup_primus.py"},
        )
        with urllib.request.urlopen(request) as response:
            release = json.loads(response.read().decode("utf-8"))

        os_token = {
            "Darwin": "macOS",
            "Linux": "Linux",
            "Windows": "Windows",
        }.get(platform.system())
        if not os_token:
            raise SetupError(f"Unsupported OS for automatic Arduino CLI install: {platform.system()}")

        machine = platform.machine().lower()
        if machine in ("x86_64", "amd64"):
            arch_tokens = ("64bit", "x86_64", "amd64")
        elif machine in ("arm64", "aarch64"):
            arch_tokens = ("arm64", "aarch64")
        elif machine.startswith("arm"):
            arch_tokens = ("arm",)
        else:
            raise SetupError(f"Unsupported CPU architecture for Arduino CLI install: {platform.machine()}")

        assets = release.get("assets", [])
        for asset in assets:
            name = asset.get("name", "")
            lower = name.lower()
            if not (lower.endswith(".tar.gz") or lower.endswith(".zip")):
                continue
            if os_token.lower() not in lower:
                continue
            if any(token.lower() in lower for token in arch_tokens):
                return asset
        raise SetupError("Could not find a matching Arduino CLI release asset.")

    def extract_arduino_cli(self, archive_path: Path) -> None:
        exe = executable_name("arduino-cli")
        target = ARDUINO_BIN_DIR / exe
        if archive_path.suffix == ".zip":
            with zipfile.ZipFile(archive_path) as archive:
                for member in archive.namelist():
                    if Path(member).name == exe:
                        with archive.open(member) as source, target.open("wb") as output:
                            shutil.copyfileobj(source, output)
                        break
                else:
                    raise SetupError("Arduino CLI executable not found in downloaded zip.")
        else:
            with tarfile.open(archive_path, "r:gz") as archive:
                for member in archive.getmembers():
                    if Path(member.name).name == exe:
                        source = archive.extractfile(member)
                        if source is None:
                            continue
                        with source, target.open("wb") as output:
                            shutil.copyfileobj(source, output)
                        break
                else:
                    raise SetupError("Arduino CLI executable not found in downloaded archive.")
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def configure_arduino(self) -> None:
        if not self.arduino_cli:
            raise SetupError("Arduino CLI is not configured.")
        section("ESP32 Arduino core")
        env = self.base_env()
        run([str(self.arduino_cli), "config", "init"], env=env, capture=True, check=False, quiet=True)
        dump = run([str(self.arduino_cli), "config", "dump"], env=env, capture=True, quiet=True)
        config_changed = False
        if ESP32_PACKAGE_URL in (dump.stdout or ""):
            ok("ESP32 package URL already configured.")
        else:
            info("Adding Espressif ESP32 package URL.")
            run([str(self.arduino_cli), "config", "add", "board_manager.additional_urls", ESP32_PACKAGE_URL], env=env)
            config_changed = True

        core_list = run([str(self.arduino_cli), "core", "list"], env=env, capture=True, quiet=True, check=False)
        core_installed = "esp32:esp32" in (core_list.stdout or "")
        if core_installed and not self.args.force:
            ok("ESP32 Arduino core already installed.")
            return

        if config_changed or not core_installed or self.args.force:
            info("Updating Arduino core index. This may take a few minutes on first setup.")
            run([str(self.arduino_cli), "core", "update-index"], env=env)
        if core_installed and self.args.force:
            info("ESP32 core is installed; --force requested, running install anyway.")
        else:
            info("Installing ESP32 Arduino core. This may take a few minutes.")
        run([str(self.arduino_cli), "core", "install", "esp32:esp32"], env=env)

    def check_arduino_core(self) -> None:
        if not self.arduino_cli:
            return
        section("ESP32 Arduino core")
        env = self.base_env()
        dump = run([str(self.arduino_cli), "config", "dump"], env=env, capture=True, quiet=True, check=False)
        if dump.returncode == 0 and ESP32_PACKAGE_URL in (dump.stdout or ""):
            ok("ESP32 package URL is configured.")
        else:
            self.issue("ESP32 package URL is not configured in Arduino CLI.")
        core_list = run([str(self.arduino_cli), "core", "list"], env=env, capture=True, quiet=True, check=False)
        if core_list.returncode == 0 and "esp32:esp32" in (core_list.stdout or ""):
            ok("ESP32 Arduino core is installed.")
        else:
            self.issue("ESP32 Arduino core is missing.")

    def installed_library_text(self) -> str:
        if not self.arduino_cli:
            return ""
        result = run(
            [str(self.arduino_cli), "lib", "list"],
            env=self.base_env(),
            capture=True,
            quiet=True,
            check=False,
        )
        return (result.stdout or "").lower()

    def missing_libraries(self, profile: str, installed_text: str) -> list[str]:
        missing = []
        for library in REQUIRED_LIBRARIES[profile]:
            if library.lower() not in installed_text:
                missing.append(library)
        return missing

    def ensure_arduino_libraries(self) -> None:
        section("Arduino libraries")
        if not self.arduino_cli:
            raise SetupError("Arduino CLI is required before installing libraries.")
        installed_text = self.installed_library_text()
        for profile in self.profiles:
            missing = self.missing_libraries(profile, installed_text)
            if not missing and not self.args.force:
                ok(f"Libraries already installed for {profile}: {', '.join(REQUIRED_LIBRARIES[profile])}")
                continue
            if missing:
                info(f"Installing libraries for {profile}: {', '.join(missing)}")
            else:
                info(f"Checking libraries for {profile} (--force).")
            self.run_upload_script([f"-{profile}", "--install"])
            installed_text = self.installed_library_text()

    def check_arduino_libraries(self) -> None:
        if not self.arduino_cli:
            return
        section("Arduino libraries")
        installed_text = self.installed_library_text()
        for profile in self.profiles:
            missing = self.missing_libraries(profile, installed_text)
            if missing:
                self.issue(f"Missing libraries for {profile}: {', '.join(missing)}")
            else:
                ok(f"Libraries installed for {profile}: {', '.join(REQUIRED_LIBRARIES[profile])}")

    def run_upload_script(self, extra_args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        if not UPLOAD_SCRIPT.exists():
            raise SetupError(f"Upload script not found: {UPLOAD_SCRIPT}")
        env = self.base_env()
        bash = shutil.which("bash", path=env.get("PATH")) or shutil.which("bash")
        if not bash:
            raise SetupError("bash is required to run V3_5/Arduino/upload.sh.")
        return run([bash, str(UPLOAD_SCRIPT), *extra_args], env=env, check=check)

    def check_upload_script(self) -> None:
        section("Upload script")
        if not UPLOAD_SCRIPT.exists():
            self.issue(f"Upload script is missing: {UPLOAD_SCRIPT}")
            return
        ok(f"Upload script exists: {UPLOAD_SCRIPT}")
        if self.arduino_cli:
            result = self.run_upload_script(["--ports"], check=False)
            if result.returncode == 0:
                ok("upload.sh --ports ran successfully.")
            else:
                self.issue("upload.sh --ports failed. Check Arduino CLI and python3 availability.")

    def check_linux_serial_permissions(self) -> None:
        if platform.system().lower() != "linux":
            return
        section("Linux serial permissions")
        groups = []
        try:
            import grp

            username = getpass.getuser()
            groups = [group.gr_name for group in grp.getgrall() if username in group.gr_mem]
            groups.append(grp.getgrgid(os.getgid()).gr_name)
        except Exception:
            groups = []
        if "dialout" in set(groups):
            ok("Current user appears to be in the dialout group.")
        else:
            warn("If uploads fail with permission denied, run: sudo usermod -aG dialout \"$USER\" and log out/back in.")

    def check(self) -> int:
        self.check_python_environment()
        if not self.args.skip_arduino:
            self.check_arduino_cli()
            self.check_arduino_core()
            self.check_arduino_libraries()
            self.check_upload_script()
            self.check_linux_serial_permissions()
        self.print_next_steps()
        return 1 if self.issues else 0

    def setup(self) -> int:
        self.ensure_python_environment()
        if not self.args.skip_arduino:
            self.ensure_arduino_cli()
            self.configure_arduino()
            self.ensure_arduino_libraries()
            self.check_linux_serial_permissions()
        self.print_next_steps()
        return 0

    def print_next_steps(self) -> None:
        section("Next steps")
        python_path = venv_python() if venv_python().exists() else Path(sys.executable)
        print("Launch the V3.5 sender:")
        print(f"  {command_text([display_path(python_path), str(SENDER_RUN.relative_to(ROOT))])}")
        print("\nInspect connected boards:")
        print("  ./V3_5/Arduino/upload.sh --ports")
        print("\nUpload one detected board, choosing the right profile:")
        print("  ./V3_5/Arduino/upload.sh -v2 --auto")
        print("\nUse WiFi overrides for a different router:")
        print('  ./V3_5/Arduino/upload.sh -v2 -ssid "PrimusRouter" -pw "router-password" --auto')


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set up PrimusV3 development and upload tools.")
    parser.add_argument("--check", action="store_true", help="Report setup status without installing anything.")
    parser.add_argument("--skip-arduino", action="store_true", help="Only prepare/check the Python environment.")
    parser.add_argument("--skip-venv", action="store_true", help="Do not create or check the local .venv.")
    parser.add_argument("--force", action="store_true", help="Refresh/reinstall setup artifacts where possible.")
    parser.add_argument("--yes", action="store_true", help="Reserved for non-interactive installs; setup currently does not prompt.")
    parser.add_argument("--profiles", type=parse_profiles, default=SUPPORTED_PROFILES,
                        help="Comma-separated board profiles for Arduino libraries (default: v1,v2,v3).")
    parser.add_argument("--arduino-cli", help="Path to an existing arduino-cli executable.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    setup = PrimusSetup(args)
    try:
        return setup.check() if args.check else setup.setup()
    except KeyboardInterrupt:
        print("\nSetup interrupted.")
        return 130
    except SetupError as exc:
        fail(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())