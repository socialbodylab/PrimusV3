#!/usr/bin/env python3
"""Build the OSC Cue Sender utility with PyInstaller."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = "OscCueSender"
MACOS_BUNDLE_ID = "com.socialbodylab.OscCueSender"
APP_ICON_SOURCE = Path("assets") / "appIcon.png"
MACOS_ICON_SPECS = (
    (16, 1), (16, 2), (32, 1), (32, 2),
    (128, 1), (128, 2), (256, 1), (256, 2),
    (512, 1), (512, 2),
)
WINDOWS_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _platform_default():
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt":
        return "windows"
    return "linux"


def _add_data_arg(source, dest):
    return f"{source}{os.pathsep}{dest}"


def _prepare_macos_icon(v4_dir, build_dir, app_name):
    source = v4_dir / APP_ICON_SOURCE
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


def _prepare_windows_icon(v4_dir, build_dir, app_name):
    source = v4_dir / APP_ICON_SOURCE
    if not source.exists():
        return None
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required to build the Windows app icon. Install with: py -m pip install pillow"
        ) from exc

    icon_dir = build_dir / "icons"
    icon_dir.mkdir(parents=True, exist_ok=True)
    icon_path = icon_dir / f"{app_name}.ico"
    sizes = [(size, size) for size in WINDOWS_ICON_SIZES]
    with Image.open(source) as image:
        image.convert("RGBA").save(icon_path, format="ICO", sizes=sizes)
    return icon_path


def _build_command(args, repo_root, app_dir, sender_dir, build_dir, dist_dir, icon_path=None):
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
        "--paths",
        str(sender_dir),
        "--paths",
        str(app_dir),
    ]

    if args.windowed:
        cmd.append("--windowed")
    if args.onefile:
        cmd.append("--onefile")
    if icon_path is not None:
        cmd.extend(["--icon", str(icon_path)])
    if args.target == "macos" and args.windowed:
        cmd.extend(["--osx-bundle-identifier", args.bundle_id])

    web_dir = app_dir / "web"
    if web_dir.exists():
        cmd.extend(["--add-data", _add_data_arg(web_dir, "web")])

    default_cues = app_dir / "default_cues.json"
    if default_cues.exists():
        cmd.extend(["--add-data", _add_data_arg(default_cues, "default_cues.json")])

    cmd.append(str(app_dir / "run.py"))
    return cmd


def _run(cmd, cwd):
    print(" ".join(str(part) for part in cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def _codesign_macos_app(app_path, identity):
    subprocess.run(
        [
            "codesign",
            "--force",
            "--deep",
            "--strict",
            "--options",
            "runtime",
            "--timestamp",
            "--sign",
            identity,
            str(app_path),
        ],
        check=True,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("auto", "macos", "windows", "linux"), default="auto")
    parser.add_argument("--console", action="store_true", help="Build with console attached")
    parser.add_argument("--onefile", action="store_true", default=None)
    parser.add_argument("--onedir", action="store_false", dest="onefile")
    parser.add_argument("--name", default=APP_NAME)
    parser.add_argument("--bundle-id", default=MACOS_BUNDLE_ID)
    parser.add_argument(
        "--sign-identity",
        default=os.environ.get("PRIMUSV3_CODESIGN_IDENTITY"),
        help="Optional Developer ID identity for macOS codesign",
    )
    args = parser.parse_args(argv)

    args.target = _platform_default() if args.target == "auto" else args.target
    args.windowed = not args.console
    if args.onefile is None:
        args.onefile = args.target == "windows"

    tools_dir = Path(__file__).resolve().parent
    repo_root = tools_dir.parent.parent
    v4_dir = tools_dir.parent
    app_dir = tools_dir / "osc_cue_sender"
    sender_dir = v4_dir / "sender"
    build_dir = tools_dir / "build" / args.target
    dist_dir = tools_dir / "dist" / args.target

    build_dir.mkdir(parents=True, exist_ok=True)
    dist_dir.mkdir(parents=True, exist_ok=True)

    icon_path = None
    if args.target == "macos":
        icon_path = _prepare_macos_icon(v4_dir, build_dir, args.name)
    elif args.target == "windows":
        icon_path = _prepare_windows_icon(v4_dir, build_dir, args.name)

    cmd = _build_command(args, repo_root, app_dir, sender_dir, build_dir, dist_dir, icon_path)
    _run(cmd, cwd=repo_root)

    if args.target == "macos" and args.windowed and args.sign_identity:
        app_path = dist_dir / f"{args.name}.app"
        if app_path.exists():
            _codesign_macos_app(app_path, args.sign_identity)
            print(f"Signed {app_path}")

    if args.target == "macos" and args.windowed:
        print(f"Built {dist_dir / (args.name + '.app')}")
    elif args.target == "windows":
        suffix = ".exe"
        print(f"Built {dist_dir / (args.name + suffix)}")
    else:
        print(f"Built {dist_dir / args.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
