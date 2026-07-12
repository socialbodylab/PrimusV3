import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

V4_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if V4_DIR not in sys.path:
    sys.path.insert(0, V4_DIR)

import build_sender_app


class PackagingBuilderTests(unittest.TestCase):
    def make_args(
        self,
        target="windows",
        product="primus",
        windowed=True,
        onefile=True,
        name="PrimusCentral",
        app_version=build_sender_app.DEFAULT_APP_VERSION,
        windows_installer_tool=None,
        windows_installer_name=None,
    ):
        return SimpleNamespace(
            target=target,
            product=product,
            windowed=windowed,
            onefile=onefile,
            name=name,
            bundle_id=build_sender_app.PRODUCT_DEFAULTS[product]["bundle_id"],
            app_version=app_version,
            windows_installer_tool=windows_installer_tool,
            windows_installer_name=windows_installer_name,
        )

    def test_default_release_version_is_091(self):
        self.assertEqual(build_sender_app.DEFAULT_APP_VERSION, "0.91")

    def test_primus_windows_command_uses_v4_product_assets(self):
        args = self.make_args()
        sender_dir = Path(V4_DIR) / "sender"

        cmd = build_sender_app._build_command(
            args,
            sender_dir,
            Path("build") / "windows",
            Path("dist") / "windows",
        )

        self.assertIn("--windowed", cmd)
        self.assertIn("--onefile", cmd)
        self.assertIn(build_sender_app._add_data_arg(Path(V4_DIR) / "Arduino", "Arduino"), cmd)
        self.assertIn(build_sender_app._add_data_arg(sender_dir / "clips", "sender/clips"), cmd)
        self.assertIn(build_sender_app._add_data_arg(sender_dir / "looks", "sender/looks"), cmd)
        self.assertEqual(cmd[-1], str(sender_dir / "run.py"))

    def test_devices_product_uses_devices_entry(self):
        args = self.make_args(product="devices", name="DeviceManager")
        sender_dir = Path(V4_DIR) / "sender"

        cmd = build_sender_app._build_command(
            args,
            sender_dir,
            Path("build") / "windows",
            Path("dist") / "windows",
        )

        self.assertEqual(cmd[-1], str(sender_dir / "run_devices.py"))

    def test_windows_readme_is_copied_from_tracked_template(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / build_sender_app.WINDOWS_README_SOURCE
            source.write_text("PrimusCentral Windows README\n", encoding="utf-8")

            output = build_sender_app._prepare_windows_readme(temp_path, temp_path / "dist")

            self.assertEqual(output, temp_path / "dist" / "README-Windows.txt")
            self.assertEqual(output.read_text(encoding="utf-8"), "PrimusCentral Windows README\n")

    def test_windows_installer_script_uses_09_release_name_and_user_local_install(self):
        args = self.make_args(app_version="0.9")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            app_path = temp_path / "dist" / "PrimusCentral.exe"
            readme_path = temp_path / "dist" / "README-Windows.txt"
            icon_path = temp_path / "build" / "icons" / "PrimusCentral.ico"
            app_path.parent.mkdir(parents=True)
            icon_path.parent.mkdir(parents=True)
            app_path.write_bytes(b"exe")
            readme_path.write_text("Read me", encoding="utf-8")
            icon_path.write_bytes(b"icon")

            script_path, installer_path = build_sender_app._write_windows_installer_script(
                args,
                app_path,
                readme_path,
                temp_path / "build",
                temp_path / "dist",
                icon_path=icon_path,
            )
            script = script_path.read_text(encoding="utf-8")

        self.assertEqual(installer_path.name, "PrimusCentral-0.9-Windows-x64-Setup.exe")
        self.assertIn("PrivilegesRequired=lowest", script)
        self.assertIn("DefaultDirName={localappdata}\\Programs\\PrimusCentral", script)
        self.assertIn(f'Source: "{app_path}"; DestDir: "{{app}}"', script)
        self.assertIn(f'Source: "{readme_path}"; DestDir: "{{app}}"', script)
        self.assertIn(f'Source: "{icon_path}"; DestDir: "{{app}}"; DestName: "PrimusCentral.ico"', script)
        self.assertIn("UninstallDisplayIcon={app}\\PrimusCentral.ico", script)
        self.assertIn('Name: "{autoprograms}\\PrimusCentral"', script)
        self.assertIn('IconFilename: "{app}\\PrimusCentral.ico"', script)

    def test_windows_artifact_signing_uses_signtool_dlib_and_metadata(self):
        calls = []

        def fake_run(cmd, cwd=None):
            calls.append(cmd)

        original_run = build_sender_app._run
        try:
            build_sender_app._run = fake_run
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                output_path = temp_path / "PrimusCentral.exe"
                metadata_path = temp_path / "metadata.json"
                dlib_path = temp_path / "Azure.CodeSigning.Dlib.dll"
                signtool_path = temp_path / "signtool.exe"
                output_path.write_bytes(b"exe")
                metadata_path.write_text("{}", encoding="utf-8")
                dlib_path.write_bytes(b"dlib")
                signtool_path.write_bytes(b"signtool")

                # The guard requires os.name == "nt"; patch only around the
                # call — a broader patch makes pathlib pick WindowsPath.
                with patch("build_sender_app.os.name", "nt"):
                    build_sender_app._sign_windows_artifact(
                        output_path,
                        metadata_path,
                        dlib_path,
                        signtool_path=signtool_path,
                        timestamp_url="http://timestamp.example.test",
                    )
        finally:
            build_sender_app._run = original_run

        self.assertEqual(calls[0][1], "sign")
        self.assertIn("/fd", calls[0])
        self.assertIn("SHA256", calls[0])
        self.assertIn("/tr", calls[0])
        self.assertIn("http://timestamp.example.test", calls[0])
        self.assertIn("/dlib", calls[0])
        self.assertTrue(any("Azure.CodeSigning.Dlib.dll" in str(part) for part in calls[0]))
        self.assertIn("/dmdf", calls[0])
        self.assertTrue(any("metadata.json" in str(part) for part in calls[0]))


if __name__ == "__main__":
    unittest.main()
