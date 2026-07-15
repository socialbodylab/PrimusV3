#!/usr/bin/env python3
"""
Build Primus receiver firmware release assets for GitHub.

Creates:
  PrimusReceiverFirmware-<version>.zip
  PrimusReceiverFirmware-<version>.zip.sha256
"""

import argparse
import hashlib
import os
import re
import sys
import zipfile
from pathlib import Path

V5_DIR = Path(__file__).resolve().parent
ARDUINO_DIR = V5_DIR / "Arduino"
UPLOAD_SCRIPT = ARDUINO_DIR / "upload.sh"
SKETCH_DIR = ARDUINO_DIR / "primusV3_receiver"
CONFIG_H = SKETCH_DIR / "config.h"
VERSION_RE = re.compile(r'#define\s+FIRMWARE_VERSION\s+"([^"]+)"')
ASSET_PREFIX = "PrimusReceiverFirmware"


def read_firmware_version():
    text = CONFIG_H.read_text(encoding="utf-8")
    match = VERSION_RE.search(text)
    if not match:
        raise SystemExit(f"Could not read FIRMWARE_VERSION from {CONFIG_H}")
    return match.group(1)


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_zip(output_dir, version):
    if not UPLOAD_SCRIPT.is_file():
        raise SystemExit(f"Missing upload script: {UPLOAD_SCRIPT}")
    if not CONFIG_H.is_file():
        raise SystemExit(f"Missing config.h: {CONFIG_H}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_name = f"{ASSET_PREFIX}-{version}.zip"
    zip_path = output_dir / zip_name

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(UPLOAD_SCRIPT, arcname="upload.sh")
        for root, _, files in os.walk(SKETCH_DIR):
            for filename in files:
                full_path = Path(root) / filename
                rel_path = full_path.relative_to(ARDUINO_DIR)
                archive.write(full_path, arcname=str(rel_path).replace("\\", "/"))

    checksum = sha256_file(zip_path)
    sidecar_path = output_dir / f"{zip_name}.sha256"
    sidecar_path.write_text(f"{checksum}  {zip_name}\n", encoding="utf-8")
    return zip_path, sidecar_path, checksum


def main():
    parser = argparse.ArgumentParser(description="Build Primus receiver firmware GitHub release assets.")
    parser.add_argument(
        "--output-dir",
        default=str(V5_DIR / "dist" / "firmware"),
        help="Directory for zip and sha256 output",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Override firmware version (defaults to config.h FIRMWARE_VERSION)",
    )
    args = parser.parse_args()

    version = args.version or read_firmware_version()
    zip_path, sidecar_path, checksum = build_zip(args.output_dir, version)
    print(f"Built {zip_path.name}")
    print(f"SHA-256 {checksum}")
    print(f"Wrote {sidecar_path.name}")
    print()
    print("Attach these assets to a GitHub release:")
    print(f"  {zip_path.name}")
    print(f"  {sidecar_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
