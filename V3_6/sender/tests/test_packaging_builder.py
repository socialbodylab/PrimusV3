import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

V35_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if V35_DIR not in sys.path:
    sys.path.insert(0, V35_DIR)

import build_sender_app


class PackagingBuilderTests(unittest.TestCase):
    def make_args(
        self,
        target="macos",
        windowed=True,
        onefile=False,
        name="PrimusCentral",
        sign_identity=None,
        notary_profile=None,
        notary_timeout=None,
        entitlements_file=None,
        windows_sign_metadata=None,
        windows_sign_dlib=None,
        windows_signtool=None,
        windows_timestamp_url=build_sender_app.WINDOWS_TIMESTAMP_URL,
        skip_windows_sign_verify=False,
        windows_installer=False,
        windows_installer_tool=None,
        windows_installer_name=None,
        app_version=build_sender_app.DEFAULT_APP_VERSION,
    ):
        return SimpleNamespace(
            target=target,
            windowed=windowed,
            onefile=onefile,
            name=name,
            bundle_id=build_sender_app.MACOS_BUNDLE_ID,
            sign_identity=sign_identity,
            notary_profile=notary_profile,
            notary_timeout=notary_timeout,
            entitlements_file=entitlements_file,
            windows_sign_metadata=windows_sign_metadata,
            windows_sign_dlib=windows_sign_dlib,
            windows_signtool=windows_signtool,
            windows_timestamp_url=windows_timestamp_url,
            skip_windows_sign_verify=skip_windows_sign_verify,
            windows_installer=windows_installer,
            windows_installer_tool=windows_installer_tool,
            windows_installer_name=windows_installer_name,
            app_version=app_version,
        )

    def test_macos_windowed_output_is_app_bundle(self):
        args = self.make_args(target="macos", windowed=True, onefile=False)
        out = build_sender_app._output_path(args, Path("dist") / "macos")
        self.assertEqual(out, Path("dist") / "macos" / "PrimusCentral.app")

    def test_windows_onefile_output_is_exe(self):
        args = self.make_args(target="windows", windowed=True, onefile=True)
        out = build_sender_app._output_path(args, Path("dist") / "windows")
        self.assertEqual(out, Path("dist") / "windows" / "PrimusCentral.exe")

    def test_windows_command_uses_onefile_windowed_and_add_data(self):
        args = self.make_args(target="windows", windowed=True, onefile=True)
        sender_dir = Path(V35_DIR) / "sender"
        cmd = build_sender_app._build_command(
            args,
            sender_dir,
            Path("build") / "windows",
            Path("dist") / "windows",
        )

        self.assertIn("--windowed", cmd)
        self.assertIn("--onefile", cmd)
        self.assertIn("--add-data", cmd)
        self.assertIn(build_sender_app._add_data_arg(Path(V35_DIR) / "Arduino", "Arduino"), cmd)
        self.assertEqual(cmd[-1], str(sender_dir / "run.py"))

    def test_macos_command_uses_prepared_icon_when_available(self):
        args = self.make_args(target="macos", windowed=True, onefile=False)
        sender_dir = Path(V35_DIR) / "sender"
        icon_path = Path("build") / "macos" / "icons" / "PrimusCentral.icns"

        cmd = build_sender_app._build_command(
            args,
            sender_dir,
            Path("build") / "macos",
            Path("dist") / "macos",
            icon_path=icon_path,
        )

        self.assertIn("--icon", cmd)
        self.assertIn(str(icon_path), cmd)

    def test_macos_command_uses_bundle_id_by_default(self):
        args = self.make_args(target="macos", windowed=True, onefile=False)
        sender_dir = Path(V35_DIR) / "sender"

        cmd = build_sender_app._build_command(
            args,
            sender_dir,
            Path("build") / "macos",
            Path("dist") / "macos",
        )

        self.assertIn("--osx-bundle-identifier", cmd)
        self.assertIn(build_sender_app.MACOS_BUNDLE_ID, cmd)

    def test_macos_command_leaves_signing_to_post_build_step(self):
        args = self.make_args(
            target="macos",
            windowed=True,
            onefile=False,
            sign_identity="Developer ID Application: Example (TEAMID)",
            entitlements_file=Path("entitlements.plist"),
        )
        sender_dir = Path(V35_DIR) / "sender"

        cmd = build_sender_app._build_command(
            args,
            sender_dir,
            Path("build") / "macos",
            Path("dist") / "macos",
        )

        self.assertNotIn("--codesign-identity", cmd)
        self.assertNotIn("Developer ID Application: Example (TEAMID)", cmd)
        self.assertNotIn("--osx-entitlements-file", cmd)
        self.assertNotIn("entitlements.plist", [str(part) for part in cmd])

    def test_windows_command_does_not_include_macos_signing_options(self):
        args = self.make_args(
            target="windows",
            windowed=True,
            onefile=True,
            sign_identity="Developer ID Application: Example (TEAMID)",
        )
        sender_dir = Path(V35_DIR) / "sender"

        cmd = build_sender_app._build_command(
            args,
            sender_dir,
            Path("build") / "windows",
            Path("dist") / "windows",
        )

        self.assertNotIn("--osx-bundle-identifier", cmd)
        self.assertNotIn("--codesign-identity", cmd)

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
                metadata_path.write_text("{}")
                dlib_path.write_bytes(b"dlib")
                signtool_path.write_bytes(b"signtool")

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

    def test_windows_installer_script_uses_signed_exe_readme_and_icon(self):
        args = self.make_args(target="windows", app_version="0.7")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            app_path = temp_path / "dist" / "PrimusCentral.exe"
            readme_path = temp_path / "dist" / "README-Windows.txt"
            icon_path = temp_path / "build" / "icons" / "PrimusCentral.ico"
            app_path.parent.mkdir(parents=True)
            icon_path.parent.mkdir(parents=True)
            app_path.write_bytes(b"exe")
            readme_path.write_text("Read me")
            icon_path.write_bytes(b"icon")

            script_path, installer_path = build_sender_app._write_windows_installer_script(
                args,
                app_path,
                readme_path,
                temp_path / "build",
                temp_path / "dist",
                icon_path=icon_path,
            )

            script = script_path.read_text()

        self.assertEqual(installer_path.name, "PrimusCentral-0.7-Windows-x64-Setup.exe")
        self.assertIn("PrivilegesRequired=lowest", script)
        self.assertIn("DefaultDirName={localappdata}\\Programs\\PrimusCentral", script)
        self.assertIn(f'Source: "{app_path}"; DestDir: "{{app}}"', script)
        self.assertIn(f'Source: "{readme_path}"; DestDir: "{{app}}"', script)
        self.assertIn(f"SetupIconFile={icon_path}", script)

    def test_windows_installer_build_uses_inno_compiler(self):
        calls = []

        def fake_run(cmd, cwd=None):
            calls.append(cmd)
            installer_path.write_bytes(b"installer")

        original_run = build_sender_app._run
        try:
            build_sender_app._run = fake_run
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                app_path = temp_path / "dist" / "PrimusCentral.exe"
                readme_path = temp_path / "dist" / "README-Windows.txt"
                compiler_path = temp_path / "ISCC.exe"
                app_path.parent.mkdir(parents=True)
                app_path.write_bytes(b"exe")
                readme_path.write_text("Read me")
                compiler_path.write_bytes(b"compiler")
                args = self.make_args(target="windows", windows_installer_tool=compiler_path)
                installer_path = temp_path / "dist" / "PrimusCentral-0.7-Windows-x64-Setup.exe"

                built_path = build_sender_app._build_windows_installer(
                    args,
                    app_path,
                    readme_path,
                    temp_path / "build",
                    temp_path / "dist",
                )
        finally:
            build_sender_app._run = original_run

        self.assertEqual(built_path, installer_path)
        self.assertEqual(calls[0][0], str(compiler_path))
        self.assertTrue(str(calls[0][1]).endswith("PrimusCentral.iss"))

    def test_windows_main_accepts_custom_icon(self):
        calls = []

        def fake_run(cmd, cwd=None):
            calls.append(cmd)

        original_run = build_sender_app._run
        original_find_spec = build_sender_app.importlib.util.find_spec
        original_refresh_windows_icon_cache = build_sender_app._refresh_windows_icon_cache
        try:
            build_sender_app._run = fake_run
            build_sender_app.importlib.util.find_spec = lambda name: object() if name == "PyInstaller" else None
            build_sender_app._refresh_windows_icon_cache = lambda output_path: None

            with tempfile.TemporaryDirectory() as temp_dir:
                icon_path = Path(temp_dir) / "PrimusCentral.ico"
                icon_path.write_bytes(b"icon")

                exit_code = build_sender_app.main([
                    "--target",
                    "windows",
                    "--icon",
                    str(icon_path),
                ])

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(calls), 1)
            self.assertIn("--icon", calls[0])
            self.assertIn(str(icon_path), calls[0])
        finally:
            build_sender_app._run = original_run
            build_sender_app.importlib.util.find_spec = original_find_spec
            build_sender_app._refresh_windows_icon_cache = original_refresh_windows_icon_cache

    def test_windows_main_auto_prepares_icon_from_shared_png(self):
        calls = []
        prepared_icons = []

        def fake_run(cmd, cwd=None):
            calls.append(cmd)

        def fake_prepare_windows_icon(v35_dir, build_dir, app_name):
            icon_path = build_dir / "icons" / f"{app_name}.ico"
            prepared_icons.append((v35_dir, build_dir, app_name, icon_path))
            return icon_path

        original_run = build_sender_app._run
        original_find_spec = build_sender_app.importlib.util.find_spec
        original_prepare_windows_icon = build_sender_app._prepare_windows_icon
        original_refresh_windows_icon_cache = build_sender_app._refresh_windows_icon_cache
        try:
            build_sender_app._run = fake_run
            build_sender_app.importlib.util.find_spec = lambda name: object() if name == "PyInstaller" else None
            build_sender_app._prepare_windows_icon = fake_prepare_windows_icon
            build_sender_app._refresh_windows_icon_cache = lambda output_path: None

            exit_code = build_sender_app.main(["--target", "windows"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(prepared_icons), 1)
            self.assertEqual(prepared_icons[0][2], "PrimusCentral")
            self.assertIn("--icon", calls[0])
            self.assertIn(str(prepared_icons[0][3]), calls[0])
        finally:
            build_sender_app._run = original_run
            build_sender_app.importlib.util.find_spec = original_find_spec
            build_sender_app._prepare_windows_icon = original_prepare_windows_icon
            build_sender_app._refresh_windows_icon_cache = original_refresh_windows_icon_cache

    def test_notary_zip_path_uses_build_notary_directory(self):
        out = build_sender_app._notary_zip_path(
            Path("dist") / "macos" / "PrimusCentral.app",
            Path("build") / "macos",
        )

        self.assertEqual(out, Path("build") / "macos" / "notary" / "PrimusCentral-notary.zip")

    def test_notarize_command_uses_optional_timeout(self):
        calls = []

        def fake_run(cmd, cwd=None):
            calls.append(cmd)

        original_run = build_sender_app._run
        original_require_tool = build_sender_app._require_tool
        original_make_notary_zip = build_sender_app._make_notary_zip
        original_which = build_sender_app.shutil.which
        try:
            build_sender_app._run = fake_run
            build_sender_app._require_tool = lambda name: None
            build_sender_app._make_notary_zip = lambda app_path, build_dir: Path("build/notary/app.zip")
            build_sender_app.shutil.which = lambda name: None

            build_sender_app._notarize_macos_app(
                Path("dist/macos/PrimusCentral.app"),
                Path("build/macos"),
                "PrimusCentral Notary",
                timeout="45m",
            )
        finally:
            build_sender_app._run = original_run
            build_sender_app._require_tool = original_require_tool
            build_sender_app._make_notary_zip = original_make_notary_zip
            build_sender_app.shutil.which = original_which

        self.assertIn("--timeout", calls[0])
        self.assertIn("45m", calls[0])

    def test_staple_and_verify_uses_stapler_and_gatekeeper_when_available(self):
        calls = []

        def fake_run(cmd, cwd=None):
            calls.append(cmd)

        original_run = build_sender_app._run
        original_require_tool = build_sender_app._require_tool
        original_which = build_sender_app.shutil.which
        try:
            build_sender_app._run = fake_run
            build_sender_app._require_tool = lambda name: None
            build_sender_app.shutil.which = lambda name: "/usr/sbin/spctl" if name == "spctl" else None

            build_sender_app._staple_and_verify_macos_app(Path("dist/macos/PrimusCentral.app"))
        finally:
            build_sender_app._run = original_run
            build_sender_app._require_tool = original_require_tool
            build_sender_app.shutil.which = original_which

        self.assertEqual(calls[0][:3], ["xcrun", "stapler", "staple"])
        self.assertEqual(calls[1][:3], ["xcrun", "stapler", "validate"])
        self.assertEqual(calls[2], ["spctl", "-a", "-vvv", "--type", "exec", str(Path("dist/macos/PrimusCentral.app"))])


if __name__ == "__main__":
    unittest.main()