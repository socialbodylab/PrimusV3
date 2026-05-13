import os
import sys
import threading
import time
import unittest

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import firmware


def available_status():
    return {
        "available": True,
        "message": "ready",
        "script_path": "/tmp/upload.sh",
        "bash": True,
        "python3": True,
        "arduino_cli": True,
        "source_only": True,
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

        matching_password = manager.build_command({
            "action": "compile",
            "profile": "v3",
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

        auto = manager.build_command({"action": "upload", "profile": "v3", "port_mode": "auto"})
        self.assertEqual(auto.command[-1], "--auto")

        all_ports = manager.build_command({"action": "upload", "profile": "v3", "port_mode": "all"})
        self.assertEqual(all_ports.command[-1], "--all")

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