import os
import sys
import tempfile
import threading
import time
import unittest

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import firmware
import paths


def available_status():
    return {
        "available": True,
        "message": "ready",
        "script_path": "/tmp/upload.sh",
        "bash": True,
        "python3": True,
        "arduino_cli": True,
        "tool_status": "ready",
        "can_install_tools": True,
        "source_only": True,
    }


def unavailable_status():
    return {
        "available": False,
        "message": "missing firmware tools",
        "script_path": "/tmp/upload.sh",
        "bash": True,
        "python3": True,
        "arduino_cli": False,
        "tool_status": "missing_cli",
        "can_install_tools": True,
        "source_only": False,
    }


class FirmwareJobTests(unittest.TestCase):
    def make_manager(self, popen_factory=None):
        return firmware.FirmwareJobManager(
            script_path="/tmp/upload.sh",
            popen_factory=popen_factory,
            availability_checker=available_status,
        )

    def test_compile_command_includes_profile_and_redacts_password(self):
        manager = self.make_manager()
        command = manager.build_command({
            "action": "compile",
            "profile": "v2",
            "device_name": "StageLeft",
            "wifi_ssid": "PrimusRouter",
            "wifi_password": "router-password",
        })

        self.assertEqual(command.command, [
            "bash",
            "/tmp/upload.sh",
            "--board",
            "v2",
            "--compile",
            "--name",
            "StageLeft",
            "-ssid",
            "PrimusRouter",
            "-pw",
            "router-password",
        ])
        self.assertNotIn("router-password", command.redacted_command)
        self.assertIn("********", command.redacted_command)
        self.assertEqual(command.metadata["overrides"], {
            "device_name": "StageLeft",
            "wifi_ssid": "PrimusRouter",
            "wifi_password_set": True,
            "ip_mode": "keep",
            "static_ip": None,
            "gateway": None,
            "subnet": None,
        })
        self.assertTrue(command.metadata["has_overrides"])

        matching_password = manager.build_command({
            "action": "compile",
            "profile": "v3",
            "wifi_ssid": "PrimusRouter",
            "wifi_password": "v3",
        })
        self.assertEqual(matching_password.redacted_command[3], "v3")
        self.assertEqual(matching_password.redacted_command[-1], "********")

    def test_upload_command_supports_selected_auto_and_all_ports(self):
        manager = self.make_manager()

        selected = manager.build_command({
            "action": "upload",
            "profile": "v1",
            "port_mode": "selected",
            "port": "/dev/cu.usbserial-1234",
        })
        self.assertEqual(selected.command[-1], "/dev/cu.usbserial-1234")
        self.assertEqual(selected.metadata["target"], {
            "port_mode": "selected",
            "port": "/dev/cu.usbserial-1234",
        })

        auto = manager.build_command({"action": "upload", "profile": "v3", "port_mode": "auto"})
        self.assertEqual(auto.command[-1], "--auto")
        self.assertEqual(auto.metadata["target"]["port_mode"], "auto")

        all_ports = manager.build_command({"action": "upload", "profile": "v3", "port_mode": "all"})
        self.assertEqual(all_ports.command[-1], "--all")
        self.assertEqual(all_ports.metadata["target"]["port_mode"], "all")

    def test_upload_overrides_are_repeatable_and_redacted_in_job_status(self):
        class EmptyProcess:
            stdout = iter(())

            def wait(self):
                return 0

        manager = self.make_manager(popen_factory=lambda *args, **kwargs: EmptyProcess())
        payload = {
            "action": "upload",
            "profile": "v3",
            "port_mode": "selected",
            "port": "/dev/cu.usbmodem1234",
            "device_name": "StageLeft",
            "wifi_ssid": "PrimusRouter",
            "wifi_password": "router-password",
        }

        first = manager.start_job(payload)
        for _ in range(100):
            current = manager.get_job(first["id"])
            if current["status"] == "succeeded":
                break
            time.sleep(0.01)
        first_done = manager.get_job(first["id"])

        second = manager.build_command(payload)

        self.assertEqual(first_done["metadata"]["overrides"]["device_name"], "StageLeft")
        self.assertEqual(first_done["metadata"]["overrides"]["wifi_ssid"], "PrimusRouter")
        self.assertTrue(first_done["metadata"]["overrides"]["wifi_password_set"])
        self.assertIn("Overrides: device name 'StageLeft'; WiFi SSID 'PrimusRouter'; WiFi password set", first_done["output"])
        self.assertNotIn("router-password", "\n".join(first_done["output"]))
        self.assertEqual(second.command, [
            "bash",
            "/tmp/upload.sh",
            "--board",
            "v3",
            "--name",
            "StageLeft",
            "-ssid",
            "PrimusRouter",
            "-pw",
            "router-password",
            "/dev/cu.usbmodem1234",
        ])

    def test_compile_command_supports_static_ip_and_dhcp_overrides(self):
        manager = self.make_manager()

        static_command = manager.build_command({
            "action": "compile",
            "profile": "v1",
            "ip_mode": "static",
            "static_ip": "192.168.1.50",
            "gateway": "192.168.1.1",
            "subnet": "255.255.255.0",
        })
        self.assertEqual(static_command.command, [
            "bash",
            "/tmp/upload.sh",
            "--board",
            "v1",
            "--compile",
            "--static-ip",
            "192.168.1.50",
            "--gateway",
            "192.168.1.1",
            "--subnet",
            "255.255.255.0",
        ])
        self.assertEqual(static_command.metadata["overrides"]["ip_mode"], "static")
        self.assertEqual(static_command.metadata["overrides"]["static_ip"], "192.168.1.50")
        self.assertTrue(static_command.metadata["has_overrides"])

        dhcp_command = manager.build_command({
            "action": "upload",
            "profile": "v2",
            "ip_mode": "dhcp",
            "port_mode": "auto",
        })
        self.assertIn("--dhcp", dhcp_command.command)
        self.assertEqual(dhcp_command.command[-1], "--auto")
        self.assertEqual(dhcp_command.metadata["overrides"]["ip_mode"], "dhcp")

    def test_wifi_override_requires_ssid_and_password(self):
        manager = self.make_manager()

        with self.assertRaises(firmware.FirmwareRequestError) as ssid_only_error:
            manager.build_command({"action": "compile", "profile": "v3", "wifi_ssid": "PrimusRouter"})
        self.assertEqual(ssid_only_error.exception.code, 400)

        with self.assertRaises(firmware.FirmwareRequestError) as password_only_error:
            manager.build_command({"action": "compile", "profile": "v3", "wifi_password": "router-password"})
        self.assertEqual(password_only_error.exception.code, 400)

    def test_invalid_values_raise_request_errors(self):
        manager = self.make_manager()

        with self.assertRaises(firmware.FirmwareRequestError) as action_error:
            manager.build_command({"action": "erase", "profile": "v3"})
        self.assertEqual(action_error.exception.code, 400)

        with self.assertRaises(firmware.FirmwareRequestError) as profile_error:
            manager.build_command({"action": "compile", "profile": "v4"})
        self.assertEqual(profile_error.exception.code, 400)

        with self.assertRaises(firmware.FirmwareRequestError) as port_error:
            manager.build_command({"action": "upload", "profile": "v3", "port_mode": "selected"})
        self.assertEqual(port_error.exception.code, 400)

        with self.assertRaises(firmware.FirmwareRequestError) as name_error:
            manager.build_command({"action": "compile", "profile": "v3", "device_name": "x" * 18})
        self.assertEqual(name_error.exception.code, 400)

        with self.assertRaises(firmware.FirmwareRequestError) as ip_error:
            manager.build_command({
                "action": "compile",
                "profile": "v3",
                "ip_mode": "static",
                "static_ip": "192.168.1.999",
                "gateway": "192.168.1.1",
                "subnet": "255.255.255.0",
            })
        self.assertEqual(ip_error.exception.code, 400)

    def test_setup_tools_job_bypasses_missing_upload_tools(self):
        def fake_installer(job, manager):
            job.append_output("installed fake tools")
            return {"tools_dir": "/tmp/tools"}

        manager = firmware.FirmwareJobManager(
            script_path="/tmp/upload.sh",
            availability_checker=unavailable_status,
            tool_installer=fake_installer,
        )
        job = manager.start_job({"action": "setup_tools", "profile": "v3"})

        for _ in range(100):
            current = manager.get_job(job["id"])
            if current["status"] == "succeeded":
                break
            time.sleep(0.01)
        current = manager.get_job(job["id"])
        self.assertEqual(current["status"], "succeeded")
        self.assertEqual(current["result"]["tools_dir"], "/tmp/tools")
        self.assertIn("installed fake tools", current["output"])

    def test_managed_arduino_cli_is_added_to_job_environment(self):
        old_tools_dir = os.environ.get(paths.TOOLS_DIR_ENV)
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                os.environ[paths.TOOLS_DIR_ENV] = tmpdir
                paths.ensure_tools_data()
                cli_path = paths.arduino_cli_executable()
                cli_bin_dir = paths.arduino_cli_bin_dir()
                with open(cli_path, "w", encoding="utf-8") as cli_file:
                    cli_file.write("#!/bin/sh\n")
                os.chmod(cli_path, 0o755)

                manager = firmware.FirmwareJobManager(script_path="/tmp/upload.sh")
                env = manager._path_env()
            finally:
                if old_tools_dir is None:
                    os.environ.pop(paths.TOOLS_DIR_ENV, None)
                else:
                    os.environ[paths.TOOLS_DIR_ENV] = old_tools_dir

        self.assertEqual(env["ARDUINO_CLI"], cli_path)
        self.assertIn(cli_bin_dir, env["PATH"])
        self.assertIn("ARDUINO_CONFIG_FILE", env)
        self.assertIn("ARDUINO_DIRECTORIES_DATA", env)

    def test_output_redaction_removes_ansi_and_password(self):
        cleaned = firmware.redact_text("\x1b[1;34msecret-password\x1b[0m done\n", ["secret-password"])
        self.assertEqual(cleaned, "******** done")

    def test_unavailable_script_blocks_job_start(self):
        manager = firmware.FirmwareJobManager(script_path="/definitely/not/upload.sh")

        with self.assertRaises(firmware.FirmwareRequestError) as err:
            manager.start_job({"action": "compile", "profile": "v3"})
        self.assertEqual(err.exception.code, 503)

    def test_only_one_job_can_run_at_a_time(self):
        release = threading.Event()

        class BlockingProcess:
            stdout = iter(())

            def wait(self):
                release.wait(1)
                return 0

        manager = self.make_manager(popen_factory=lambda *args, **kwargs: BlockingProcess())
        first = manager.start_job({"action": "install", "profile": "v3"})

        with self.assertRaises(firmware.FirmwareRequestError) as err:
            manager.start_job({"action": "compile", "profile": "v3"})
        self.assertEqual(err.exception.code, 409)

        release.set()
        for _ in range(100):
            if manager.get_job(first["id"])["status"] == "succeeded":
                break
            time.sleep(0.01)
        self.assertEqual(manager.get_job(first["id"])["status"], "succeeded")

    def test_list_ports_job_parses_json_result(self):
        class JsonProcess:
            stdout = iter(['{"ports":[{"address":"/dev/cu.usbmodem1","candidate":true}],"candidates":[],"others":[]}\n'])

            def wait(self):
                return 0

        manager = self.make_manager(popen_factory=lambda *args, **kwargs: JsonProcess())
        job = manager.start_job({"action": "list_ports", "profile": "v3"})

        for _ in range(100):
            current = manager.get_job(job["id"])
            if current["status"] == "succeeded":
                break
            time.sleep(0.01)
        current = manager.get_job(job["id"])
        self.assertEqual(current["status"], "succeeded")
        self.assertEqual(current["result"]["ports"][0]["address"], "/dev/cu.usbmodem1")


if __name__ == "__main__":
    unittest.main()