#!/usr/bin/env python3
"""Build a one-click V3.5 sender app with PyInstaller.

Build on the target OS: macOS builds a `.app`, while Windows builds an `.exe`.
PyInstaller does not reliably cross-compile desktop apps between macOS and
Windows.
"""

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = "PrimusCentral"
MACOS_ICON_SOURCE = Path("assets") / "appIcon.png"
MACOS_ICON_SPECS = (
    (16, 1),
    (16, 2),
    (32, 1),
    (32, 2),
    (128, 1),
    (128, 2),
    (256, 1),
    (256, 2),
    (512, 1),
    (512, 2),
)


def _platform_default():
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt":
        return "windows"
    return "linux"


def _add_data_arg(source, dest):
    return f"{source}{os.pathsep}{dest}"


def _data_files(v35_dir, sender_dir):
    return [
        (v35_dir / "Arduino", "Arduino"),
        (sender_dir / "web", "sender/web"),
        (sender_dir / "clips", "sender/clips"),
        (sender_dir / "looks", "sender/looks"),
        (sender_dir / "cues.json", "sender/cues.json"),
    ]


def _prepare_macos_icon(v35_dir, build_dir, app_name):
    source = v35_dir / MACOS_ICON_SOURCE
    if not source.exists():
        return None
    if shutil.which("sips") is None or shutil.which("iconutil") is None:
        raise RuntimeError("macOS icon tools sips and iconutil are required to build the app icon")

    icon_dir = build_dir / "icons"
    iconset_dir = icon_dir / f"{app_name}.iconset"
    icon_path = icon_dir / f"{app_name}.icns"
    if iconset_dir.exists():
        shutil.rmtree(iconset_dir)
    iconset_dir.mkdir(parents=True, exist_ok=True)

    for point_size, scale in MACOS_ICON_SPECS:
        pixel_size = point_size * scale
        suffix = "" if scale == 1 else "@2x"
        output = iconset_dir / f"icon_{point_size}x{point_size}{suffix}.png"
        subprocess.run(
            ["sips", "-z", str(pixel_size), str(pixel_size), str(source), "--out", str(output)],
            check=True,
            stdout=subprocess.DEVNULL,
        )

    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icon_path)],
        check=True,
    )
    shutil.rmtree(iconset_dir)
    return icon_path


def _build_command(args, sender_dir, build_dir, dist_dir, icon_path=None):
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        args.name,
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir / "pyinstaller"),
        "--specpath",
        str(build_dir),
    ]

    if args.windowed:
        cmd.append("--windowed")
    if args.onefile:
        cmd.append("--onefile")
    if icon_path is not None:
        cmd.extend(["--icon", str(icon_path)])

    v35_dir = sender_dir.parent
    for source, dest in _data_files(v35_dir, sender_dir):
        if source.exists():
            cmd.extend(["--add-data", _add_data_arg(source, dest)])

    cmd.append(str(sender_dir / "run.py"))
    return cmd


def _output_path(args, dist_dir):
    if args.target == "macos" and args.windowed:
        return dist_dir / f"{args.name}.app"
    suffix = ".exe" if args.target == "windows" else ""
    if args.onefile:
        return dist_dir / f"{args.name}{suffix}"
    return dist_dir / args.name / f"{args.name}{suffix}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        choices=("auto", "macos", "windows", "linux"),
        default="auto",
        help="Target platform for naming/defaults. Build on that OS. Default: auto.",
    )
    parser.add_argument(
        "--console",
        action="store_true",
        help="Keep a console attached instead of building a windowed app.",
    )
    parser.add_argument(
        "--onefile",
        action="store_true",
        default=None,
        help="Build a single-file executable. Default on Windows.",
    )
    parser.add_argument(
        "--onedir",
        action="store_false",
        dest="onefile",
        help="Build a one-folder app/executable instead of one-file.",
    )
    parser.add_argument(
        "--name",
        default=APP_NAME,
        help=f"App/executable name (default: {APP_NAME!r}).",
    )
    args = parser.parse_args(argv)

    args.target = _platform_default() if args.target == "auto" else args.target
    current_platform = _platform_default()
    if args.target in ("macos", "windows") and args.target != current_platform:
        print(
            f"Warning: target {args.target!r} differs from this OS ({current_platform!r}). "
            "PyInstaller should be run on the target OS for real release builds."
        )

    args.windowed = not args.console
    if args.onefile is None:
        args.onefile = args.target == "windows"

    v35_dir = Path(__file__).resolve().parent
    repo_root = v35_dir.parent
    sender_dir = v35_dir / "sender"
    build_dir = v35_dir / "build" / args.target
    dist_dir = v35_dir / "dist" / args.target

    if importlib.util.find_spec("PyInstaller") is None:
        print("PyInstaller is not installed. Install it with: python -m pip install pyinstaller")
        return 1

    try:
        icon_path = _prepare_macos_icon(v35_dir, build_dir, args.name) if args.target == "macos" else None
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Could not prepare macOS app icon: {exc}")
        return 1

    cmd = _build_command(args, sender_dir, build_dir, dist_dir, icon_path=icon_path)
    print(f"Building {args.target} sender app with PyInstaller...")
    print(" ".join(str(part) for part in cmd))
    try:
        subprocess.run(cmd, cwd=repo_root, check=True)
    except subprocess.CalledProcessError as exc:
        return exc.returncode

    print()
    print(f"Built: {_output_path(args, dist_dir)}")
    if args.console:
        print("Run the executable from Terminal/Command Prompt to test console logging.")
    elif args.target == "macos":
        print("Double-click the app in Finder to start the sender.")
    elif args.target == "windows":
        print("Double-click the .exe to start the sender.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())