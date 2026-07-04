"""
firmware_source.py — Primus receiver firmware source resolution and GitHub updates.
"""

import hashlib
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
import zipfile

import paths

GITHUB_REPO = "socialbodylab/PrimusV3"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
FIRMWARE_ASSET_RE = re.compile(
    r"^PrimusReceiverFirmware-(\d+\.\d+\.\d+)\.zip$",
    re.IGNORECASE,
)
FIRMWARE_VERSION_RE = re.compile(
    r'#define\s+FIRMWARE_VERSION\s+"([^"]+)"',
)
UPDATE_CACHE_TTL_SECONDS = 15 * 60
USER_AGENT = "PrimusCentral firmware updates"

_lock = threading.RLock()


def read_firmware_version(config_path):
    if not os.path.isfile(config_path):
        return None
    with open(config_path, encoding="utf-8") as handle:
        text = handle.read()
    match = FIRMWARE_VERSION_RE.search(text)
    return match.group(1) if match else None


def _primus_config_path(root):
    return os.path.join(root, "primusV3_receiver", "config.h")


def bundled_firmware_root():
    return paths.bundled_arduino_dir()


def active_firmware_root():
    active = paths.firmware_active_dir()
    if os.path.isfile(os.path.join(active, "upload.sh")):
        return active
    return bundled_firmware_root()


def _load_manifest():
    manifest_path = paths.firmware_manifest_path()
    if not os.path.isfile(manifest_path):
        return None
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def local_firmware_info():
    active = paths.firmware_active_dir()
    manifest = _load_manifest()
    if manifest and os.path.isfile(os.path.join(active, "upload.sh")):
        root = active
        source = "downloaded"
        version = manifest.get("version")
        if not version:
            version = read_firmware_version(_primus_config_path(root))
    else:
        root = bundled_firmware_root()
        source = "bundled"
        version = read_firmware_version(_primus_config_path(root))
    return {
        "version": version,
        "source": source,
        "path": root,
    }


def _parse_semver(version):
    parts = str(version or "").strip().split(".")
    if len(parts) != 3:
        return None
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


def _compare_semver(left, right):
    left_key = _parse_semver(left)
    right_key = _parse_semver(right)
    if left_key is None or right_key is None:
        return None
    if left_key < right_key:
        return -1
    if left_key > right_key:
        return 1
    return 0


def _load_update_cache():
    cache_path = paths.firmware_update_cache_path()
    if not os.path.isfile(cache_path):
        return None
    try:
        with open(cache_path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _save_update_cache(payload):
    paths.ensure_firmware_data()
    with open(paths.firmware_update_cache_path(), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def _github_request(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_github_releases():
    releases = []
    page = 1
    while page <= 10:
        url = f"{GITHUB_RELEASES_API}?per_page=100&page={page}"
        batch = _github_request(url)
        if not isinstance(batch, list) or not batch:
            break
        releases.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return releases


def _find_sha256_asset(assets, zip_name):
    sidecar = f"{zip_name}.sha256"
    for asset in assets:
        if asset.get("name") == sidecar:
            return asset
    return None


def _parse_sha256_sidecar(text, expected_name):
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == expected_name:
            return parts[0].lower()
        if len(parts) == 1:
            return parts[0].lower()
    return None


def _fetch_sha256_from_asset(asset):
    request = urllib.request.Request(
        asset["browser_download_url"],
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8", errors="replace")
    return _parse_sha256_sidecar(text, asset.get("name", "").replace(".sha256", ""))


def _best_firmware_release(releases):
    best = None
    for release in releases:
        if release.get("draft"):
            continue
        is_prerelease = bool(release.get("prerelease"))
        assets = release.get("assets") or []
        for asset in assets:
            name = asset.get("name", "")
            match = FIRMWARE_ASSET_RE.match(name)
            if not match:
                continue
            version = match.group(1)
            semver = _parse_semver(version)
            if semver is None:
                continue
            sha_asset = _find_sha256_asset(assets, name)
            candidate = {
                "version": version,
                "semver": semver,
                "release_tag": release.get("tag_name"),
                "prerelease": is_prerelease,
                "asset_name": name,
                "asset_url": asset.get("browser_download_url"),
                "sha256_asset_name": sha_asset.get("name") if sha_asset else None,
                "sha256_asset_url": sha_asset.get("browser_download_url") if sha_asset else None,
            }
            if best is None or semver > best["semver"]:
                best = candidate
    return best


def check_github_updates(force=False):
    if not paths.is_primus_product():
        return {
            "enabled": False,
            "local_version": local_firmware_info().get("version"),
            "remote_version": None,
            "update_available": False,
            "last_checked": None,
            "checking": False,
            "error": None,
        }

    with _lock:
        cache = _load_update_cache()
        now = time.time()
        if not force and cache:
            last_checked = cache.get("last_checked")
            if last_checked and (now - float(last_checked)) < UPDATE_CACHE_TTL_SECONDS:
                return dict(cache)

        local = local_firmware_info()
        payload = {
            "enabled": True,
            "local_version": local.get("version"),
            "remote_version": None,
            "update_available": False,
            "release_tag": None,
            "asset_name": None,
            "asset_url": None,
            "sha256": None,
            "last_checked": now,
            "checking": False,
            "error": None,
        }
        try:
            releases = _fetch_github_releases()
            best = _best_firmware_release(releases)
            if not best:
                payload["error"] = "No PrimusReceiverFirmware release assets found on GitHub."
            else:
                payload["remote_version"] = best["version"]
                payload["release_tag"] = best["release_tag"]
                payload["asset_name"] = best["asset_name"]
                payload["asset_url"] = best["asset_url"]
                if best.get("sha256_asset_url"):
                    sha_asset = {"browser_download_url": best["sha256_asset_url"], "name": best["sha256_asset_name"]}
                    payload["sha256"] = _fetch_sha256_from_asset(sha_asset)
                compare = _compare_semver(local.get("version"), best["version"])
                payload["update_available"] = compare is not None and compare < 0
        except urllib.error.URLError as exc:
            payload["error"] = f"Could not reach GitHub: {exc.reason}"
        except Exception as exc:
            payload["error"] = str(exc)

        _save_update_cache(payload)
        return payload


def _safe_zip_extract(archive, dest_dir):
    dest_dir = os.path.abspath(dest_dir)
    for member in archive.namelist():
        member_path = os.path.abspath(os.path.join(dest_dir, member))
        if not member_path.startswith(dest_dir + os.sep) and member_path != dest_dir:
            raise RuntimeError(f"Unsafe zip entry: {member}")
    archive.extractall(dest_dir)


def _verify_file_sha256(path, expected):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest().lower()
    expected_norm = str(expected or "").strip().lower()
    if actual != expected_norm:
        raise RuntimeError(f"SHA-256 mismatch for {os.path.basename(path)}")


def _download_file(url, dest_path, job=None):
    if job:
        job.append_output(f"Downloading {os.path.basename(dest_path)}...")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, open(dest_path, "wb") as output:
        shutil.copyfileobj(response, output)


def install_firmware_bundle(asset_url, expected_sha256, release_tag=None, asset_name=None, job=None):
    if not asset_url:
        raise RuntimeError("Firmware download URL is missing.")
    if not expected_sha256:
        raise RuntimeError("Firmware SHA-256 checksum is required.")

    paths.ensure_firmware_data()
    downloads_dir = paths.firmware_downloads_dir()
    os.makedirs(downloads_dir, exist_ok=True)
    archive_name = asset_name or os.path.basename(asset_url.split("?", 1)[0])
    archive_path = os.path.join(downloads_dir, archive_name)

    _download_file(asset_url, archive_path, job=job)
    if job:
        job.append_output("Verifying SHA-256 checksum...")
    _verify_file_sha256(archive_path, expected_sha256)

    staging_dir = os.path.join(paths.firmware_dir(), "staging")
    if os.path.isdir(staging_dir):
        shutil.rmtree(staging_dir, ignore_errors=True)
    os.makedirs(staging_dir, exist_ok=True)

    if job:
        job.append_output("Extracting firmware bundle...")
    with zipfile.ZipFile(archive_path) as archive:
        _safe_zip_extract(archive, staging_dir)

    upload_script = os.path.join(staging_dir, "upload.sh")
    config_path = _primus_config_path(staging_dir)
    if not os.path.isfile(upload_script):
        raise RuntimeError("Firmware bundle is missing upload.sh")
    if not os.path.isfile(config_path):
        raise RuntimeError("Firmware bundle is missing primusV3_receiver/config.h")

    version = read_firmware_version(config_path)
    if not version:
        raise RuntimeError("Could not read firmware version from downloaded bundle")

    active_dir = paths.firmware_active_dir()
    backup_dir = os.path.join(paths.firmware_dir(), "active_backup")
    if os.path.isdir(backup_dir):
        shutil.rmtree(backup_dir, ignore_errors=True)
    if os.path.isdir(active_dir):
        if job:
            job.append_output("Replacing active firmware source...")
        os.replace(active_dir, backup_dir)
    os.replace(staging_dir, active_dir)
    if os.path.isdir(backup_dir):
        shutil.rmtree(backup_dir, ignore_errors=True)

    active_upload_script = os.path.join(active_dir, "upload.sh")
    os.chmod(active_upload_script, os.stat(active_upload_script).st_mode | 0o111)

    manifest = {
        "version": version,
        "family": "primus",
        "source": "github",
        "release_tag": release_tag,
        "asset_name": asset_name or archive_name,
        "installed_at": time.time(),
        "sha256": expected_sha256.lower(),
    }
    with open(paths.firmware_manifest_path(), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")

    with _lock:
        _save_update_cache({
            "enabled": True,
            "local_version": version,
            "remote_version": version,
            "update_available": False,
            "release_tag": release_tag,
            "asset_name": asset_name or archive_name,
            "asset_url": asset_url,
            "sha256": expected_sha256.lower(),
            "last_checked": time.time(),
            "checking": False,
            "error": None,
        })

    if job:
        job.append_output(f"Installed Primus receiver firmware v{version}.")
    return manifest
