"""Tests for Primus firmware source resolution and GitHub updates."""

import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

SENDER_DIR = os.path.join(os.path.dirname(__file__), "..")
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import firmware
import firmware_source
import paths


SAMPLE_CONFIG = '#define FIRMWARE_VERSION "3.10.0"\n'


class FirmwareUpdateTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        os.environ["PRIMUSV3_SENDER_PRODUCT"] = "primus"
        os.environ["PRIMUSV3_USE_APP_DATA"] = "1"
        self.temp_dir = tempfile.mkdtemp(prefix="primus-fw-update-")
        self.firmware_root = os.path.join(self.temp_dir, "firmware")
        os.makedirs(self.firmware_root, exist_ok=True)
        self._patches = [
            patch.object(paths, "firmware_dir", return_value=self.firmware_root),
            patch.object(paths, "firmware_active_dir", return_value=os.path.join(self.firmware_root, "active")),
            patch.object(paths, "firmware_manifest_path", return_value=os.path.join(self.firmware_root, "manifest.json")),
            patch.object(paths, "firmware_update_cache_path", return_value=os.path.join(self.firmware_root, "update_cache.json")),
            patch.object(paths, "firmware_downloads_dir", return_value=os.path.join(self.firmware_root, "downloads")),
        ]
        for item in self._patches:
            item.start()

    def tearDown(self):
        for item in reversed(self._patches):
            item.stop()
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_config(self, root, version="3.10.0"):
        sketch_dir = os.path.join(root, "primusV3_receiver")
        os.makedirs(sketch_dir, exist_ok=True)
        with open(os.path.join(sketch_dir, "config.h"), "w", encoding="utf-8") as handle:
            handle.write(f'#define FIRMWARE_VERSION "{version}"\n')
        upload_script = os.path.join(root, "upload.sh")
        with open(upload_script, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/bash\n")
        os.chmod(upload_script, 0o755)

    def test_read_firmware_version(self):
        with tempfile.NamedTemporaryFile("w", suffix=".h", delete=False, encoding="utf-8") as handle:
            handle.write(SAMPLE_CONFIG)
            path = handle.name
        try:
            self.assertEqual(firmware_source.read_firmware_version(path), "3.10.0")
        finally:
            os.unlink(path)

    def test_parse_asset_name_and_compare_semver(self):
        match = firmware_source.FIRMWARE_ASSET_RE.match("PrimusReceiverFirmware-3.10.0.zip")
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "3.10.0")
        self.assertEqual(firmware_source._compare_semver("3.9.0", "3.10.0"), -1)
        self.assertEqual(firmware_source._compare_semver("3.10.0", "3.10.0"), 0)

    def test_best_firmware_release_picks_highest_semver(self):
        releases = [
            {
                "draft": False,
                "prerelease": False,
                "tag_name": "fw-3.9.0",
                "assets": [
                    {"name": "PrimusReceiverFirmware-3.9.0.zip", "browser_download_url": "https://example/3.9.zip"},
                    {"name": "PrimusReceiverFirmware-3.9.0.zip.sha256", "browser_download_url": "https://example/3.9.sha256"},
                ],
            },
            {
                "draft": False,
                "prerelease": False,
                "tag_name": "fw-3.10.0",
                "assets": [
                    {"name": "PrimusReceiverFirmware-3.10.0.zip", "browser_download_url": "https://example/3.10.zip"},
                    {"name": "PrimusReceiverFirmware-3.10.0.zip.sha256", "browser_download_url": "https://example/3.10.sha256"},
                ],
            },
        ]
        best = firmware_source._best_firmware_release(releases)
        self.assertEqual(best["version"], "3.10.0")

    def test_local_firmware_info_prefers_downloaded_active_tree(self):
        active = paths.firmware_active_dir()
        os.makedirs(active, exist_ok=True)
        self._write_config(active, "3.10.0")
        with open(paths.firmware_manifest_path(), "w", encoding="utf-8") as handle:
            json.dump({"version": "3.10.0"}, handle)

        with patch.object(firmware_source, "bundled_firmware_root", return_value="/bundled"):
            with patch.object(firmware_source, "read_firmware_version", side_effect=lambda path: "3.9.0" if "/bundled" in path else "3.10.0"):
                info = firmware_source.local_firmware_info()
        self.assertEqual(info["version"], "3.10.0")
        self.assertEqual(info["source"], "downloaded")
        self.assertEqual(info["path"], active)

    def test_install_firmware_bundle_verifies_sha256_and_installs(self):
        staging_zip = os.path.join(self.temp_dir, "PrimusReceiverFirmware-3.10.0.zip")
        with zipfile.ZipFile(staging_zip, "w") as archive:
            archive.writestr("upload.sh", "#!/bin/bash\n")
            archive.writestr("primusV3_receiver/config.h", SAMPLE_CONFIG)
        checksum = hashlib.sha256()
        with open(staging_zip, "rb") as handle:
            checksum.update(handle.read())
        expected = checksum.hexdigest()

        payload = open(staging_zip, "rb").read()

        class FakeResponse:
            def __init__(self, data):
                self._buffer = io.BytesIO(data)

            def read(self, size=-1):
                return self._buffer.read(size)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("firmware_source.urllib.request.urlopen", return_value=FakeResponse(payload)):
            manifest = firmware_source.install_firmware_bundle(
                asset_url="https://example/PrimusReceiverFirmware-3.10.0.zip",
                expected_sha256=expected,
                release_tag="fw-3.10.0",
                asset_name="PrimusReceiverFirmware-3.10.0.zip",
            )
        self.assertEqual(manifest["version"], "3.10.0")
        self.assertTrue(os.path.isfile(os.path.join(paths.firmware_active_dir(), "upload.sh")))
        self.assertTrue(os.path.isfile(os.path.join(paths.firmware_active_dir(), "primusV3_receiver", "config.h")))

    def test_install_firmware_bundle_rejects_bad_checksum(self):
        staging_zip = os.path.join(self.temp_dir, "bad.zip")
        with zipfile.ZipFile(staging_zip, "w") as archive:
            archive.writestr("upload.sh", "#!/bin/bash\n")
            archive.writestr("primusV3_receiver/config.h", SAMPLE_CONFIG)

        payload = open(staging_zip, "rb").read()

        class FakeResponse:
            def __init__(self, data):
                self._buffer = io.BytesIO(data)

            def read(self, size=-1):
                return self._buffer.read(size)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("firmware_source.urllib.request.urlopen", return_value=FakeResponse(payload)):
            with self.assertRaises(RuntimeError):
                firmware_source.install_firmware_bundle(
                    asset_url="https://example/bad.zip",
                    expected_sha256="0" * 64,
                    asset_name="bad.zip",
                )

    def test_check_github_updates_uses_cache(self):
        cache_path = paths.firmware_update_cache_path()
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump({
                "enabled": True,
                "local_version": "3.9.0",
                "remote_version": "3.10.0",
                "update_available": True,
                "last_checked": firmware_source.time.time(),
                "checking": False,
                "error": None,
            }, handle)
        with patch.object(firmware_source, "_fetch_github_releases") as fetch:
            result = firmware_source.check_github_updates(force=False)
            fetch.assert_not_called()
        self.assertTrue(result["update_available"])

    def test_download_firmware_job_requires_update(self):
        manager = firmware.FirmwareJobManager()
        with patch.object(firmware_source, "check_github_updates", return_value={
            "update_available": False,
            "error": None,
            "remote_version": "3.9.0",
        }):
            with self.assertRaises(firmware.FirmwareRequestError) as ctx:
                manager.build_command({"action": "download_firmware", "profile": "v3"})
        self.assertEqual(ctx.exception.code, 409)


if __name__ == "__main__":
    unittest.main()
