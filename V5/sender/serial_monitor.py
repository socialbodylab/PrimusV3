"""serial_monitor.py — Background serial monitor via arduino-cli monitor."""

import os
import shutil
import subprocess
import threading
import time

import paths

MAX_OUTPUT_LINES = 800


class SerialMonitorError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message


class SerialMonitorManager:
    def __init__(self, popen_factory=None):
        self.popen_factory = popen_factory or subprocess.Popen
        self._lock = threading.RLock()
        self._proc = None
        self._thread = None
        self._port = ""
        self._started_at = None
        self._output = []
        self._active = False
        self._stop_requested = False

    def status(self):
        with self._lock:
            return {
                "active": self._active,
                "port": self._port if self._active else "",
                "started_at": self._started_at,
                "output": list(self._output),
            }

    def is_active(self):
        with self._lock:
            return self._active

    def start(self, port, baud=115200):
        port = str(port or "").strip()
        if not port:
            raise SerialMonitorError(400, "port required")
        with self._lock:
            if self._active:
                raise SerialMonitorError(409, "Serial monitor already running")
            from firmware import firmware_jobs
            if firmware_jobs.has_running_job():
                raise SerialMonitorError(409, "Firmware job is running")
            cli = self._arduino_cli_path()
            if not cli:
                raise SerialMonitorError(503, "arduino-cli not available")
            command = [
                cli,
                "monitor",
                "-p",
                port,
                "-c",
                f"baudrate={int(baud)}",
            ]
            self._output = [f"$ {' '.join(command)}"]
            self._port = port
            self._started_at = time.time()
            self._stop_requested = False
            self._active = True
            proc = self.popen_factory(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=self._path_env(),
            )
            self._proc = proc
            self._thread = threading.Thread(
                target=self._read_loop,
                args=(proc,),
                daemon=True,
            )
            self._thread.start()
            return self.status()

    def stop(self):
        with self._lock:
            if not self._active:
                return self.status()
            self._stop_requested = True
            proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        with self._lock:
            self._active = False
            self._proc = None
            self._append_output("[monitor stopped]")
            return self.status()

    def _read_loop(self, proc):
        try:
            stdout = proc.stdout or []
            for line in stdout:
                if self._stop_requested:
                    break
                clean = line.rstrip("\r\n")
                if clean:
                    self._append_output(clean)
            proc.wait()
        except Exception as exc:
            self._append_output(str(exc))
        finally:
            with self._lock:
                if self._active:
                    self._active = False
                    self._append_output(
                        f"[monitor exited with code {proc.returncode}]")

    def _append_output(self, line):
        with self._lock:
            self._output.append(line)
            if len(self._output) > MAX_OUTPUT_LINES:
                self._output = self._output[-MAX_OUTPUT_LINES:]

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
        return shutil.which("arduino-cli", path=search_path)


serial_monitor = SerialMonitorManager()
