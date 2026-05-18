#!/usr/bin/env python3
"""Build a one-click V3.6 sender app with PyInstaller.

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
MACOS_BUNDLE_ID = "com.socialbodylab.PrimusCentral"
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
    if args.target == "macos" and args.windowed:
        cmd.extend(["--osx-bundle-identifier", args.bundle_id])

    v35_dir = sender_dir.parent
    for source, dest in _data_files(v35_dir, sender_dir):
        if source.exists():
            cmd.extend(["--add-data", _add_data_arg(source, dest)])

    cmd.append(str(sender_dir / "run.py"))
    return cmd


def _run(cmd, cwd=None):
    print(" ".join(str(part) for part in cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def _require_tool(name):
    if shutil.which(name) is None:
        raise RuntimeError(f"Required tool not found: {name}")


def _post_sign_macos_app(app_path, identity, entitlements_file=None):
    _require_tool("codesign")
    cmd = [
        "codesign",
        "--force",
        "--deep",
        "--strict",
        "--options",
        "runtime",
        "--timestamp",
    ]
    if entitlements_file:
        cmd.extend(["--entitlements", str(entitlements_file)])
    cmd.extend(["--sign", identity, str(app_path)])
    _run(cmd)
    _run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app_path)])


def _notary_zip_path(app_path, build_dir):
    return build_dir / "notary" / f"{app_path.stem}-notary.zip"


def _make_notary_zip(app_path, build_dir):
    _require_tool("ditto")
    zip_path = _notary_zip_path(app_path, build_dir)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    _run(["ditto", "-c", "-k", "--keepParent", str(app_path), str(zip_path)])
    return zip_path


def _staple_and_verify_macos_app(app_path):
    _require_tool("xcrun")
    _run(["xcrun", "stapler", "staple", str(app_path)])
    _run(["xcrun", "stapler", "validate", str(app_path)])
    if shutil.which("spctl") is not None:
        _run(["spctl", "-a", "-vvv", "--type", "exec", str(app_path)])


def _notarize_macos_app(app_path, build_dir, notary_profile, timeout=None):
    _require_tool("xcrun")
    zip_path = _make_notary_zip(app_path, build_dir)
    cmd = [
        "xcrun",
        "notarytool",
        "submit",
        str(zip_path),
        "--keychain-profile",
        notary_profile,
        "--wait",
    ]
    if timeout:
        cmd.extend(["--timeout", timeout])
    _run(cmd)
    _staple_and_verify_macos_app(app_path)


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
    parser.add_argument(
        "--bundle-id",
        default=MACOS_BUNDLE_ID,
        help=f"macOS bundle identifier (default: {MACOS_BUNDLE_ID!r}).",
    )
    parser.add_argument(
        "--sign-identity",
        default=os.environ.get("PRIMUSV3_CODESIGN_IDENTITY"),
        help="Developer ID code signing identity for macOS release builds. "
        "May also be set with PRIMUSV3_CODESIGN_IDENTITY.",
    )
    parser.add_argument(
        "--entitlements-file",
        type=Path,
        default=None,
        help="Optional macOS entitlements file to pass to codesign.",
    )
    parser.add_argument(
        "--notary-profile",
        default=os.environ.get("PRIMUSV3_NOTARY_PROFILE"),
        help="notarytool keychain profile for macOS notarization. "
        "May also be set with PRIMUSV3_NOTARY_PROFILE.",
    )
    parser.add_argument(
        "--notary-timeout",
        default=os.environ.get("PRIMUSV3_NOTARY_TIMEOUT"),
        help="Optional notarytool wait timeout, such as '45m' or '1h'. "
        "Apple continues processing after this timeout.",
    )
    parser.add_argument(
        "--staple-existing",
        action="store_true",
        help="Skip build and staple/verify the existing macOS app output.",
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
    if args.notary_profile and (args.target != "macos" or args.console):
        print("Notarization requires a windowed macOS .app build.")
        return 1
    if args.staple_existing and (args.target != "macos" or args.console):
        print("Stapling requires a windowed macOS .app build.")
        return 1
    if args.notary_profile and not args.sign_identity:
        print("Notarization requires --sign-identity or PRIMUSV3_CODESIGN_IDENTITY.")
        return 1
    if args.entitlements_file and not args.entitlements_file.exists():
        print(f"Entitlements file not found: {args.entitlements_file}")
        return 1

    v35_dir = Path(__file__).resolve().parent
    repo_root = v35_dir.parent
    sender_dir = v35_dir / "sender"
    build_dir = v35_dir / "build" / args.target
    dist_dir = v35_dir / "dist" / args.target
    output_path = _output_path(args, dist_dir)

    if args.staple_existing:
        if not output_path.exists():
            print(f"App output not found: {output_path}")
            return 1
        try:
            _staple_and_verify_macos_app(output_path)
        except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
            print(f"macOS stapling failed: {exc}")
            return exc.returncode if isinstance(exc, subprocess.CalledProcessError) else 1
        print(f"Stapled and verified: {output_path}")
        return 0

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
    try:
        _run(cmd, cwd=repo_root)
    except subprocess.CalledProcessError as exc:
        return exc.returncode

    try:
        if args.target == "macos" and args.windowed and args.sign_identity:
            print()
            print(f"Signing: {output_path}")
            _post_sign_macos_app(output_path, args.sign_identity, args.entitlements_file)
        if args.notary_profile:
            print()
            print(f"Notarizing: {output_path}")
            _notarize_macos_app(output_path, build_dir, args.notary_profile, args.notary_timeout)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"macOS signing/notarization failed: {exc}")
        return exc.returncode if isinstance(exc, subprocess.CalledProcessError) else 1

    print()
    print(f"Built: {output_path}")
    if args.notary_profile:
        print("The app was signed, notarized, and stapled.")
    elif args.sign_identity:
        print("The app was signed but not notarized.")
    if args.console:
        print("Run the executable from Terminal/Command Prompt to test console logging.")
    elif args.target == "macos":
        print("Double-click the app in Finder to start the sender.")
    elif args.target == "windows":
        print("Double-click the .exe to start the sender.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())