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
    def make_args(self, target="macos", windowed=True, onefile=False, name="PrimusCentral"):
        return SimpleNamespace(
            target=target,
            windowed=windowed,
            onefile=onefile,
            name=name,
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


if __name__ == "__main__":
    unittest.main()