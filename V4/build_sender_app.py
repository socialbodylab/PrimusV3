#!/usr/bin/env python3
"""Build a one-click V4 sender app with PyInstaller.

V4 is the unified sender tree (Primus + Radius). Build on the target OS: macOS builds a `.app`, while Windows builds an `.exe`.
PyInstaller does not reliably cross-compile desktop apps between macOS and Windows.
"""

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = "RadiusCentral"
MACOS_BUNDLE_ID = "com.socialbodylab.RadiusCentral"
PRODUCT_DEFAULTS = {
    "radius": {
        "name": "RadiusCentral",
        "bundle_id": "com.socialbodylab.RadiusCentral",
    },
    "primus": {
        "name": "PrimusCentral",
        "bundle_id": "com.socialbodylab.PrimusCentral",
    },
    "devices": {
        "name": "DeviceManager",
        "bundle_id": "com.socialbodylab.DeviceManager",
        "entry": "run_devices.py",
    },
}
APP_ICON_SOURCE = Path("assets") / "appIcon.png"
MACOS_ICON_SOURCE = APP_ICON_SOURCE
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
WINDOWS_ICON_SOURCE = APP_ICON_SOURCE
WINDOWS_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
WINDOWS_TIMESTAMP_URL = "http://timestamp.acs.microsoft.com"
WINDOWS_INSTALLER_APP_ID = "{{E8573E10-0D2C-4C6E-91C8-D1F5927A9328}"
DEFAULT_APP_VERSION = "0.83"


def _platform_default():
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt":
        return "windows"
    return "linux"


def _add_data_arg(source, dest):
    return f"{source}{os.pathsep}{dest}"


def _data_files(v4_dir, sender_dir, product="radius"):
    files = [
        (v4_dir / "Arduino", "Arduino"),
        (sender_dir / "web", "sender/web"),
    ]
    if product in ("primus", "devices"):
        files.extend([
            (sender_dir / "clips", "sender/clips"),
            (sender_dir / "looks", "sender/looks"),
            (sender_dir / "cues.json", "sender/cues.json"),
        ])
    return files


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


def _prepare_windows_icon(v35_dir, build_dir, app_name):
    source = v35_dir / WINDOWS_ICON_SOURCE
    if not source.exists():
        return None
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required to build the Windows app icon from appIcon.png. "
            "Install it with: py -m pip install pillow"
        ) from exc

    icon_dir = build_dir / "icons"
    icon_dir.mkdir(parents=True, exist_ok=True)
    icon_path = icon_dir / f"{app_name}.ico"
    sizes = [(size, size) for size in WINDOWS_ICON_SIZES]
    with Image.open(source) as image:
        image.convert("RGBA").save(icon_path, format="ICO", sizes=sizes)
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
    for source, dest in _data_files(v35_dir, sender_dir, product=args.product):
        if source.exists():
            cmd.extend(["--add-data", _add_data_arg(source, dest)])

    entry_name = PRODUCT_DEFAULTS.get(args.product, {}).get("entry", "run.py")
    cmd.append(str(sender_dir / entry_name))
    return cmd


def _run(cmd, cwd=None):
    print(" ".join(str(part) for part in cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def _require_tool(name):
    if shutil.which(name) is None:
        raise RuntimeError(f"Required tool not found: {name}")


def _resolve_optional_path(path):
    if path is None:
        return None
    path = Path(path).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _find_windows_signtool():
    signtool = shutil.which("signtool")
    if signtool:
        return Path(signtool)
    kits_bin = Path(os.environ.get("ProgramFiles(x86)", "")) / "Windows Kits" / "10" / "bin"
    candidates = sorted(kits_bin.glob("*/x64/signtool.exe"), reverse=True) if kits_bin.exists() else []
    if candidates:
        return candidates[0]
    raise RuntimeError("SignTool.exe was not found. Install the Windows SDK or Microsoft.Windows.SDK.BuildTools.")


def _find_inno_setup_compiler(inno_setup_compiler=None):
    if inno_setup_compiler:
        return inno_setup_compiler
    compiler = shutil.which("ISCC.exe") or shutil.which("ISCC")
    if compiler:
        return Path(compiler)
    candidates = []
    for env_name in ("ProgramFiles(x86)", "ProgramFiles"):
        program_files = os.environ.get(env_name)
        if program_files:
            candidates.append(Path(program_files) / "Inno Setup 6" / "ISCC.exe")
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Programs" / "Inno Setup 6" / "ISCC.exe")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError("Inno Setup Compiler was not found. Install Inno Setup 6 or pass --windows-installer-tool.")


def _inno_escape(value):
    return str(value).replace('"', '""')


def _windows_installer_base_name(args):
    if args.windows_installer_name:
        return args.windows_installer_name.removesuffix(".exe")
    return f"{args.name}-{args.app_version}-Windows-x64-Setup"


def _write_windows_installer_script(args, app_path, readme_path, build_dir, dist_dir, icon_path=None):
    installer_dir = build_dir / "installer"
    installer_dir.mkdir(parents=True, exist_ok=True)
    script_path = installer_dir / f"{args.name}.iss"
    installer_base_name = _windows_installer_base_name(args)
    setup_icon = icon_path if icon_path is not None else app_path

    script = rf"""[Setup]
AppId={WINDOWS_INSTALLER_APP_ID}
AppName={_inno_escape(args.name)}
AppVersion={_inno_escape(args.app_version)}
AppPublisher=Social Body Lab
DefaultDirName={{localappdata}}\Programs\{_inno_escape(args.name)}
DefaultGroupName={_inno_escape(args.name)}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={_inno_escape(dist_dir)}
OutputBaseFilename={_inno_escape(installer_base_name)}
SetupIconFile={_inno_escape(setup_icon)}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={{app}}\{_inno_escape(app_path.name)}

[Files]
Source: "{_inno_escape(app_path)}"; DestDir: "{{app}}"; Flags: ignoreversion
Source: "{_inno_escape(readme_path)}"; DestDir: "{{app}}"; Flags: ignoreversion

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Icons]
Name: "{{group}}\{_inno_escape(args.name)}"; Filename: "{{app}}\{_inno_escape(app_path.name)}"
Name: "{{userdesktop}}\{_inno_escape(args.name)}"; Filename: "{{app}}\{_inno_escape(app_path.name)}"; Tasks: desktopicon

[Run]
Filename: "{{app}}\{_inno_escape(app_path.name)}"; Description: "Launch {_inno_escape(args.name)}"; Flags: nowait postinstall skipifsilent
"""
    script_path.write_text(script, encoding="utf-8")
    return script_path, dist_dir / f"{installer_base_name}.exe"


def _build_windows_installer(args, app_path, readme_path, build_dir, dist_dir, icon_path=None):
    if os.name != "nt":
        raise RuntimeError("Windows installer builds must run on Windows.")
    if not app_path.exists():
        raise RuntimeError(f"Windows executable not found: {app_path}")
    if not readme_path.exists():
        raise RuntimeError(f"Windows README not found: {readme_path}")

    compiler = _find_inno_setup_compiler(args.windows_installer_tool)
    if not compiler.exists():
        raise RuntimeError(f"Inno Setup Compiler not found: {compiler}")
    script_path, installer_path = _write_windows_installer_script(
        args,
        app_path,
        readme_path,
        build_dir,
        dist_dir,
        icon_path=icon_path,
    )
    if installer_path.exists():
        installer_path.unlink()
    _run([str(compiler), str(script_path)])
    if not installer_path.exists():
        raise RuntimeError(f"Windows installer was not created: {installer_path}")
    return installer_path


def _sign_windows_artifact(output_path, metadata_file, dlib_path, signtool_path=None, timestamp_url=WINDOWS_TIMESTAMP_URL):
    if os.name != "nt":
        raise RuntimeError("Windows Artifact Signing must run on Windows.")
    if not output_path.exists():
        raise RuntimeError(f"Windows output not found: {output_path}")
    if not metadata_file.exists():
        raise RuntimeError(f"Artifact Signing metadata file not found: {metadata_file}")
    if not dlib_path.exists():
        raise RuntimeError(f"Artifact Signing dlib not found: {dlib_path}")

    signtool_path = signtool_path or _find_windows_signtool()
    if not signtool_path.exists():
        raise RuntimeError(f"SignTool.exe not found: {signtool_path}")

    _run([
        str(signtool_path),
        "sign",
        "/v",
        "/debug",
        "/fd",
        "SHA256",
        "/tr",
        timestamp_url,
        "/td",
        "SHA256",
        "/dlib",
        str(dlib_path),
        "/dmdf",
        str(metadata_file),
        str(output_path),
    ])


def _verify_windows_signature(output_path, signtool_path=None):
    signtool_path = signtool_path or _find_windows_signtool()
    _run([str(signtool_path), "verify", "/pa", "/v", str(output_path)])


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


def _refresh_windows_icon_cache(output_path):
    if os.name != "nt" or not output_path.exists():
        return
    try:
        import ctypes
        shell32 = ctypes.windll.shell32
        shell32.SHChangeNotify(0x00002000, 0x0005, str(output_path), None)
        shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    except Exception:
        pass
    try:
        subprocess.run(
            ["ie4uinit.exe", "-show"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except Exception:
        pass


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
        "--product",
        choices=("radius", "primus", "devices"),
        default=os.environ.get("PRIMUSV3_SENDER_PRODUCT", "radius"),
        help="Sender product to build: radius (RadiusCentral), primus (PrimusCentral), or devices (DeviceManager).",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="App/executable name (default depends on --product).",
    )
    parser.add_argument(
        "--bundle-id",
        default=None,
        help="macOS bundle identifier (default depends on --product).",
    )
    parser.add_argument(
        "--icon",
        type=Path,
        default=None,
        help="Optional icon file to pass to PyInstaller. Use .ico on Windows and .icns on macOS.",
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
    parser.add_argument(
        "--windows-sign-metadata",
        type=Path,
        default=os.environ.get("PRIMUSV3_WINDOWS_SIGN_METADATA"),
        help="Local Azure Artifact Signing metadata JSON for Windows Authenticode signing. "
        "May also be set with PRIMUSV3_WINDOWS_SIGN_METADATA.",
    )
    parser.add_argument(
        "--windows-sign-dlib",
        type=Path,
        default=os.environ.get("PRIMUSV3_ARTIFACT_SIGNING_DLIB"),
        help="Path to Azure.CodeSigning.Dlib.dll from the Artifact Signing Client Tools. "
        "May also be set with PRIMUSV3_ARTIFACT_SIGNING_DLIB.",
    )
    parser.add_argument(
        "--windows-signtool",
        type=Path,
        default=os.environ.get("PRIMUSV3_SIGNTOOL"),
        help="Optional path to SignTool.exe. Defaults to PATH or the latest Windows SDK x64 SignTool. "
        "May also be set with PRIMUSV3_SIGNTOOL.",
    )
    parser.add_argument(
        "--windows-timestamp-url",
        default=os.environ.get("PRIMUSV3_WINDOWS_TIMESTAMP_URL", WINDOWS_TIMESTAMP_URL),
        help=f"RFC3161 timestamp URL for Windows signing. Default: {WINDOWS_TIMESTAMP_URL}",
    )
    parser.add_argument(
        "--skip-windows-sign-verify",
        action="store_true",
        help="Skip SignTool signature verification after Windows signing.",
    )
    parser.add_argument(
        "--windows-installer",
        action="store_true",
        help="Build a simple Inno Setup installer alongside the Windows executable.",
    )
    parser.add_argument(
        "--windows-installer-tool",
        type=Path,
        default=os.environ.get("PRIMUSV3_INNO_SETUP_COMPILER"),
        help="Optional path to ISCC.exe from Inno Setup. Defaults to PATH or the standard Inno Setup 6 install path. "
        "May also be set with PRIMUSV3_INNO_SETUP_COMPILER.",
    )
    parser.add_argument(
        "--windows-installer-name",
        default=os.environ.get("PRIMUSV3_WINDOWS_INSTALLER_NAME"),
        help="Optional Windows installer output base filename. Defaults to '<name>-<version>-Windows-x64-Setup'.",
    )
    parser.add_argument(
        "--app-version",
        default=os.environ.get("PRIMUSV3_APP_VERSION", DEFAULT_APP_VERSION),
        help=f"App version used in installer metadata and filenames. Default: {DEFAULT_APP_VERSION}",
    )
    args = parser.parse_args(argv)

    product_defaults = PRODUCT_DEFAULTS[args.product]
    if not args.name:
        args.name = product_defaults["name"]
    if not args.bundle_id:
        args.bundle_id = product_defaults["bundle_id"]

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
    args.icon = _resolve_optional_path(args.icon)
    args.windows_sign_metadata = _resolve_optional_path(args.windows_sign_metadata)
    args.windows_sign_dlib = _resolve_optional_path(args.windows_sign_dlib)
    args.windows_signtool = _resolve_optional_path(args.windows_signtool)
    args.windows_installer_tool = _resolve_optional_path(args.windows_installer_tool)
    if args.icon:
        if not args.icon.exists():
            print(f"Icon file not found: {args.icon}")
            return 1
    if args.windows_sign_metadata and args.target != "windows":
        print("Windows signing requires --target windows.")
        return 1
    if args.windows_sign_metadata and not args.windows_sign_metadata.exists():
        print(f"Windows signing metadata file not found: {args.windows_sign_metadata}")
        return 1
    if args.windows_sign_metadata and not args.windows_sign_dlib:
        print("Windows signing requires --windows-sign-dlib or PRIMUSV3_ARTIFACT_SIGNING_DLIB.")
        return 1
    if args.windows_sign_dlib and not args.windows_sign_dlib.exists():
        print(f"Windows Artifact Signing dlib not found: {args.windows_sign_dlib}")
        return 1
    if args.windows_signtool and not args.windows_signtool.exists():
        print(f"SignTool.exe not found: {args.windows_signtool}")
        return 1
    if args.windows_installer and args.target != "windows":
        print("Windows installer builds require --target windows.")
        return 1
    if args.windows_installer and not args.onefile:
        print("Windows installer builds require a one-file executable. Remove --onedir.")
        return 1
    if args.windows_installer_tool and not args.windows_installer_tool.exists():
        print(f"Inno Setup Compiler not found: {args.windows_installer_tool}")
        return 1

    v35_dir = Path(__file__).resolve().parent
    repo_root = v35_dir.parent
    sender_dir = v35_dir / "sender"
    build_dir = v35_dir / "build" / args.target
    dist_dir = v35_dir / "dist" / args.target
    output_path = _output_path(args, dist_dir)
    windows_readme_path = dist_dir / "README-Windows.txt"

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
        print("PyInstaller is not installed. Install build tools with: python -m pip install -r V4/requirements-build.txt")
        return 1

    try:
        icon_path = args.icon
        if icon_path is None and args.target == "macos":
            icon_path = _prepare_macos_icon(v35_dir, build_dir, args.name)
        if icon_path is None and args.target == "windows":
            icon_path = _prepare_windows_icon(v35_dir, build_dir, args.name)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Could not prepare app icon: {exc}")
        return 1

    cmd = _build_command(args, sender_dir, build_dir, dist_dir, icon_path=icon_path)
    print(f"Building {args.target} sender app with PyInstaller...")
    try:
        _run(cmd, cwd=repo_root)
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    if args.target == "windows":
        _refresh_windows_icon_cache(output_path)

    try:
        if args.target == "macos" and args.windowed and args.sign_identity:
            print()
            print(f"Signing: {output_path}")
            _post_sign_macos_app(output_path, args.sign_identity, args.entitlements_file)
        if args.target == "windows" and args.windows_sign_metadata:
            print()
            print(f"Signing: {output_path}")
            _sign_windows_artifact(
                output_path,
                args.windows_sign_metadata,
                args.windows_sign_dlib,
                signtool_path=args.windows_signtool,
                timestamp_url=args.windows_timestamp_url,
            )
            if not args.skip_windows_sign_verify:
                _verify_windows_signature(output_path, signtool_path=args.windows_signtool)
        installer_path = None
        if args.target == "windows" and args.windows_installer:
            print()
            print(f"Building installer for: {output_path}")
            installer_path = _build_windows_installer(
                args,
                output_path,
                windows_readme_path,
                build_dir,
                dist_dir,
                icon_path=icon_path,
            )
            if args.windows_sign_metadata:
                print()
                print(f"Signing: {installer_path}")
                _sign_windows_artifact(
                    installer_path,
                    args.windows_sign_metadata,
                    args.windows_sign_dlib,
                    signtool_path=args.windows_signtool,
                    timestamp_url=args.windows_timestamp_url,
                )
                if not args.skip_windows_sign_verify:
                    _verify_windows_signature(installer_path, signtool_path=args.windows_signtool)
        if args.notary_profile:
            print()
            print(f"Notarizing: {output_path}")
            _notarize_macos_app(output_path, build_dir, args.notary_profile, args.notary_timeout)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Signing/notarization failed: {exc}")
        return exc.returncode if isinstance(exc, subprocess.CalledProcessError) else 1

    print()
    print(f"Built: {output_path}")
    if args.target == "windows" and args.windows_installer and installer_path:
        print(f"Built installer: {installer_path}")
    if args.notary_profile:
        print("The app was signed, notarized, and stapled.")
    elif args.target == "windows" and args.windows_sign_metadata and args.windows_installer:
        print("The executable and installer were signed and timestamped.")
    elif args.target == "windows" and args.windows_sign_metadata:
        print("The executable was signed and timestamped.")
    elif args.sign_identity:
        print("The app was signed but not notarized.")
    if args.console:
        print("Run the executable from Terminal/Command Prompt to test console logging.")
    elif args.target == "macos":
        print("Double-click the app in Finder to start the sender.")
    elif args.target == "windows":
        if args.windows_installer:
            print("Run the installer or double-click the .exe to start the sender.")
        else:
            print("Double-click the .exe to start the sender.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())