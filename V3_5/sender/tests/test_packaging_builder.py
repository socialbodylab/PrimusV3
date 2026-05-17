import os
import sys
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
        self.assertEqual(calls[2], ["spctl", "-a", "-vvv", "--type", "exec", "dist/macos/PrimusCentral.app"])


if __name__ == "__main__":
    unittest.main()