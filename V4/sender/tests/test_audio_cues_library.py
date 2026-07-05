"""
Tests for audio_cues.py — project audio library, checksum cache, temp staging.
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest

_tmpdir = tempfile.mkdtemp()
os.environ["RADIUSV4_DATA_DIR"] = _tmpdir

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import audio_cues


def _make_wav(content=b"PCM"):
    """Minimal RIFF/WAVE header with custom payload."""
    payload = content
    size = 36 + len(payload)
    return (
        b"RIFF"
        + (size).to_bytes(4, "little")
        + b"WAVE"
        + b"fmt "
        + (16).to_bytes(4, "little")
        + b"\x01\x00"
        + b"\x01\x00"
        + b"\x44\xac\x00\x00"
        + b"\x88\x58\x01\x00"
        + b"\x02\x00"
        + b"\x10\x00"
        + b"data"
        + len(payload).to_bytes(4, "little")
        + payload
    )


WAV_A = _make_wav(b"version-A")
WAV_B = _make_wav(b"version-B")


def _checksum(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


class TestChecksumBytes(unittest.TestCase):
    def test_matches_hashlib(self):
        self.assertEqual(audio_cues.checksum_bytes(WAV_A), _checksum(WAV_A))

    def test_different_data_differs(self):
        self.assertNotEqual(
            audio_cues.checksum_bytes(WAV_A),
            audio_cues.checksum_bytes(WAV_B),
        )


class TestSaveAndList(unittest.TestCase):
    def setUp(self):
        audio_cues._checksum_cache = None

    def test_save_and_list_includes_checksum(self):
        audio_cues.save_project_audio("test_a.wav", WAV_A)
        files = audio_cues.list_project_audio()
        names = [f["name"] for f in files]
        self.assertIn("test_a.wav", names)
        entry = next(f for f in files if f["name"] == "test_a.wav")
        self.assertEqual(entry["checksum"], _checksum(WAV_A))
        self.assertEqual(entry["size"], len(WAV_A))

    def test_save_same_content_is_noop(self):
        audio_cues.save_project_audio("noop.wav", WAV_A)
        result = audio_cues.save_project_audio("noop.wav", WAV_A)
        self.assertEqual(result, "noop.wav")

    def test_save_different_content_raises(self):
        audio_cues.save_project_audio("conflict.wav", WAV_A)
        with self.assertRaises(audio_cues.ChecksumConflictError):
            audio_cues.save_project_audio("conflict.wav", WAV_B)

    def test_save_rejects_non_wav(self):
        with self.assertRaises(ValueError):
            audio_cues.save_project_audio("bad.mp3", WAV_A)

    def test_save_sanitises_path_traversal(self):
        name = audio_cues.save_project_audio("../escape.wav", WAV_A)
        self.assertEqual(name, "escape.wav")
        self.assertTrue(
            audio_cues.get_project_audio_path("escape.wav").startswith(audio_cues._AUDIO_DIR)
        )

    def test_delete_removes_from_list_and_cache(self):
        audio_cues.save_project_audio("del_me.wav", WAV_A)
        self.assertIsNotNone(audio_cues.get_project_audio_path("del_me.wav"))
        ok = audio_cues.delete_project_audio("del_me.wav")
        self.assertTrue(ok)
        self.assertIsNone(audio_cues.get_project_audio_path("del_me.wav"))
        audio_cues._checksum_cache = None
        cache = audio_cues._load_checksum_cache()
        self.assertNotIn("del_me.wav", cache)

    def test_delete_missing_returns_false(self):
        self.assertFalse(audio_cues.delete_project_audio("ghost.wav"))

    def test_list_excludes_hidden_files(self):
        files = audio_cues.list_project_audio()
        for f in files:
            self.assertFalse(f["name"].startswith("."))


class TestChecksumCache(unittest.TestCase):
    def setUp(self):
        audio_cues._checksum_cache = None

    def test_cache_persists_across_reload(self):
        audio_cues.save_project_audio("cached.wav", WAV_A)
        audio_cues._checksum_cache = None
        cs = audio_cues._get_cached_checksum("cached.wav")
        self.assertEqual(cs, _checksum(WAV_A))

    def test_cache_computed_for_existing_file(self):
        audio_cues._ensure_audio_dirs()
        path = os.path.join(audio_cues._AUDIO_DIR, "direct.wav")
        with open(path, "wb") as f:
            f.write(WAV_B)
        audio_cues._checksum_cache = None
        cs = audio_cues._get_cached_checksum("direct.wav")
        self.assertEqual(cs, _checksum(WAV_B))

    def test_missing_file_returns_none(self):
        self.assertIsNone(audio_cues._get_cached_checksum("nonexistent.wav"))


class TestTempStaging(unittest.TestCase):
    def setUp(self):
        audio_cues._checksum_cache = None

    def test_save_and_retrieve_temp(self):
        cs = _checksum(WAV_B)
        path = audio_cues.save_project_audio_temp(cs, WAV_B)
        self.assertTrue(os.path.isfile(path))
        retrieved = audio_cues.get_project_audio_temp_path(cs)
        self.assertEqual(path, retrieved)

    def test_discard_temp(self):
        cs = _checksum(WAV_A)
        audio_cues.save_project_audio_temp(cs, WAV_A)
        ok = audio_cues.discard_project_audio_temp(cs)
        self.assertTrue(ok)
        self.assertIsNone(audio_cues.get_project_audio_temp_path(cs))

    def test_discard_missing_temp_returns_false(self):
        self.assertFalse(audio_cues.discard_project_audio_temp("sha256:" + "0" * 64))

    def test_temp_path_missing_returns_none(self):
        self.assertIsNone(audio_cues.get_project_audio_temp_path("sha256:" + "f" * 64))


class TestResolve(unittest.TestCase):
    def setUp(self):
        audio_cues._checksum_cache = None

    def test_resolve_moves_temp_to_library(self):
        cs = _checksum(WAV_A)
        audio_cues.save_project_audio_temp(cs, WAV_A)
        audio_cues.resolve_project_audio_temp(cs, "resolved.wav")
        self.assertIsNotNone(audio_cues.get_project_audio_path("resolved.wav"))
        self.assertIsNone(audio_cues.get_project_audio_temp_path(cs))

    def test_resolve_checksum_in_cache(self):
        cs = _checksum(WAV_B)
        audio_cues.save_project_audio_temp(cs, WAV_B)
        audio_cues.resolve_project_audio_temp(cs, "from_temp.wav")
        audio_cues._checksum_cache = None
        self.assertEqual(audio_cues._get_cached_checksum("from_temp.wav"), cs)

    def test_resolve_same_content_already_in_library(self):
        cs = _checksum(WAV_A)
        audio_cues.save_project_audio("already.wav", WAV_A)
        audio_cues.save_project_audio_temp(cs, WAV_A)
        result = audio_cues.resolve_project_audio_temp(cs, "already.wav")
        self.assertEqual(result, "already.wav")
        self.assertIsNone(audio_cues.get_project_audio_temp_path(cs))

    def test_resolve_conflict_with_library_raises(self):
        audio_cues.save_project_audio("taken.wav", WAV_A)
        cs_b = _checksum(WAV_B)
        audio_cues.save_project_audio_temp(cs_b, WAV_B)
        with self.assertRaises(audio_cues.ChecksumConflictError):
            audio_cues.resolve_project_audio_temp(cs_b, "taken.wav")

    def test_resolve_missing_temp_raises(self):
        with self.assertRaises(FileNotFoundError):
            audio_cues.resolve_project_audio_temp("sha256:" + "a" * 64, "x.wav")


class TestCueSheet(unittest.TestCase):
    def test_load_missing_returns_default(self):
        if os.path.isfile(audio_cues._CUES_FILE):
            os.remove(audio_cues._CUES_FILE)
        data = audio_cues.load_audio_cues()
        self.assertEqual(data, {"cues": []})

    def test_save_and_load_roundtrip(self):
        cues = {"cues": [{"number": 1, "label": "intro"}]}
        audio_cues.save_audio_cues(cues)
        loaded = audio_cues.load_audio_cues()
        self.assertEqual(loaded, cues)


if __name__ == "__main__":
    unittest.main()
