import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

V5_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if V5_DIR not in sys.path:
    sys.path.insert(0, V5_DIR)

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

    def test_default_release_version_matches_builder(self):
        self.assertEqual(build_sender_app.DEFAULT_APP_VERSION, "0.93")

    def test_radius_product_uses_radius_icon_source(self):
        self.assertEqual(
            build_sender_app._icon_source_for_product("radius"),
            build_sender_app.RADIUS_ICON_SOURCE,
        )
        self.assertEqual(
            build_sender_app._icon_source_for_product("primus"),
            build_sender_app.APP_ICON_SOURCE,
        )
        self.assertEqual(
            build_sender_app._icon_source_for_product("devices"),
            build_sender_app.APP_ICON_SOURCE,
        )
        self.assertTrue((Path(V5_DIR) / build_sender_app.RADIUS_ICON_SOURCE).exists())

    def test_primus_windows_command_uses_v5_product_assets(self):
        args = self.make_args()
        sender_dir = Path(V5_DIR) / "sender"

        cmd = build_sender_app._build_command(
            args,
            sender_dir,
            Path("build") / "windows",
            Path("dist") / "windows",
        )

        self.assertIn("--windowed", cmd)
        self.assertIn("--onefile", cmd)
        self.assertIn(build_sender_app._add_data_arg(Path(V5_DIR) / "Arduino", "Arduino"), cmd)
        self.assertIn(build_sender_app._add_data_arg(sender_dir / "clips", "sender/clips"), cmd)
        self.assertIn(build_sender_app._add_data_arg(sender_dir / "looks", "sender/looks"), cmd)
        self.assertEqual(cmd[-1], str(sender_dir / "run.py"))

    def test_radius_product_omits_primus_show_content(self):
        args = self.make_args(product="radius", name="RadiusCentral")
        sender_dir = Path(V5_DIR) / "sender"

        cmd = build_sender_app._build_command(
            args,
            sender_dir,
            Path("build") / "macos",
            Path("dist") / "macos",
        )

        self.assertEqual(
            args.bundle_id,
            build_sender_app.PRODUCT_DEFAULTS["radius"]["bundle_id"],
        )
        self.assertEqual(cmd[-1], str(sender_dir / "run.py"))
        self.assertIn(build_sender_app._add_data_arg(Path(V5_DIR) / "Arduino", "Arduino"), cmd)
        self.assertIn(build_sender_app._add_data_arg(sender_dir / "web", "sender/web"), cmd)
        self.assertNotIn(build_sender_app._add_data_arg(sender_dir / "clips", "sender/clips"), cmd)
        self.assertNotIn(build_sender_app._add_data_arg(sender_dir / "looks", "sender/looks"), cmd)
        self.assertNotIn(
            build_sender_app._add_data_arg(sender_dir / "cues.json", "sender/cues.json"),
            cmd,
        )

    def test_radius_data_files_exclude_clips_looks_cues(self):
        sender_dir = Path(V5_DIR) / "sender"
        files = build_sender_app._data_files(Path(V5_DIR), sender_dir, product="radius")
        dests = [dest for _source, dest in files]
        self.assertEqual(dests, ["Arduino", "sender/web"])

    def test_devices_product_uses_devices_entry(self):
        args = self.make_args(product="devices", name="DeviceManager")
        sender_dir = Path(V5_DIR) / "sender"

        cmd = build_sender_app._build_command(
            args,
            sender_dir,
            Path("build") / "windows",
            Path("dist") / "windows",
        )

        self.assertEqual(cmd[-1], str(sender_dir / "run_devices.py"))

    def test_release_dmg_path_naming(self):
        dmg_path = build_sender_app._release_dmg_path(
            Path("/tmp/dist"),
            "RadiusCentral",
            "0.92",
            arch="arm64",
        )
        self.assertEqual(dmg_path.name, "RadiusCentral-0.92-macOS-arm64.dmg")

    def test_create_release_dmg_stages_app_and_applications_symlink(self):
        calls = []

        def fake_run(cmd, cwd=None):
            cmd = [str(part) for part in cmd]
            calls.append(cmd)
            if cmd[0] == "ditto":
                import shutil

                shutil.copytree(cmd[1], cmd[2])

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            app_path = temp_path / "RadiusCentral.app"
            (app_path / "Contents").mkdir(parents=True)
            (app_path / "Contents" / "Info.plist").write_text("plist", encoding="utf-8")
            dist_dir = temp_path / "dist"
            build_dir = temp_path / "build"

            with mock.patch.object(build_sender_app, "_run", side_effect=fake_run), mock.patch.object(
                build_sender_app, "_require_tool", return_value=None
            ):
                dmg_path = build_sender_app._create_release_dmg(
                    app_path,
                    dist_dir,
                    build_dir,
                    "0.92",
                    arch="arm64",
                )

            staging = build_dir / "dmg-staging"
            self.assertTrue((staging / "RadiusCentral.app").is_dir())
            applications = staging / "Applications"
            self.assertTrue(applications.is_symlink())
            self.assertEqual(os.readlink(applications), "/Applications")
            self.assertEqual(dmg_path, dist_dir / "RadiusCentral-0.92-macOS-arm64.dmg")
            self.assertEqual(calls[0][:2], ["ditto", str(app_path)])
            self.assertEqual(calls[1][0:2], ["hdiutil", "create"])
            self.assertIn("-format", calls[1])
            self.assertIn("UDZO", calls[1])
            self.assertIn(str(dmg_path), calls[1])
    def test_write_sha256_sidecar_uses_artifact_basename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact = Path(temp_dir) / "RadiusCentral-0.92-macOS-arm64.dmg"
            artifact.write_bytes(b"dmg-bytes")
            sha_path = build_sender_app._write_sha256(artifact)
            self.assertEqual(sha_path.name, "RadiusCentral-0.92-macOS-arm64.dmg.sha256")
            content = sha_path.read_text(encoding="ascii").strip()
            digest, name = content.split("  ", 1)
            self.assertEqual(name, artifact.name)
            self.assertEqual(len(digest), 64)

    def test_sign_notarize_staple_dmg_order(self):
        calls = []

        def fake_run(cmd, cwd=None):
            calls.append([str(part) for part in cmd])

        with tempfile.TemporaryDirectory() as temp_dir:
            dmg_path = Path(temp_dir) / "RadiusCentral-0.92-macOS-arm64.dmg"
            dmg_path.write_bytes(b"dmg")
            with mock.patch.object(build_sender_app, "_run", side_effect=fake_run), mock.patch.object(
                build_sender_app, "_require_tool", return_value=None
            ), mock.patch.object(build_sender_app.shutil, "which", return_value="/usr/bin/spctl"):
                build_sender_app._sign_notarize_staple_dmg(
                    dmg_path,
                    "Developer ID Application: Test",
                    "PrimusCentral Notary",
                    timeout="1h",
                )

        self.assertEqual(calls[0][0], "codesign")
        self.assertIn(str(dmg_path), calls[0])
        self.assertEqual(calls[1][0:3], ["xcrun", "notarytool", "submit"])
        self.assertIn("--timeout", calls[1])
        self.assertEqual(calls[2][0:3], ["xcrun", "stapler", "staple"])
        self.assertEqual(calls[3][0:3], ["xcrun", "stapler", "validate"])
        self.assertEqual(calls[4][0], "spctl")
        self.assertEqual(calls[5][0:2], ["hdiutil", "verify"])

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

            with mock.patch.object(build_sender_app, "_run", side_effect=fake_run), mock.patch.object(
                build_sender_app.os, "name", "nt"
            ):
                build_sender_app._sign_windows_artifact(
                    output_path,
                    metadata_path,
                    dlib_path,
                    signtool_path=signtool_path,
                    timestamp_url="http://timestamp.example.test",
                )

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
