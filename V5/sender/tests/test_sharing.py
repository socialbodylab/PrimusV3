import os
import sys
import tempfile
import unittest

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import clips
import mixer
import paths
import sharing


class SharingTests(unittest.TestCase):
    def setUp(self):
        self._old_data_dir = os.environ.get(paths.DATA_DIR_ENV)
        self._tmp = tempfile.TemporaryDirectory()
        os.environ[paths.DATA_DIR_ENV] = self._tmp.name
        paths.ensure_runtime_data()

    def tearDown(self):
        self._tmp.cleanup()
        if self._old_data_dir is None:
            os.environ.pop(paths.DATA_DIR_ENV, None)
        else:
            os.environ[paths.DATA_DIR_ENV] = self._old_data_dir

    def _clip(self, clip_id="clip-one", name="Pulse Clip"):
        return clips.save_clip({
            "id": clip_id,
            "name": name,
            "group": "Sharing",
            "output_type": "short_strip",
            "effect": "pulse",
            "start_color": [255, 0, 0],
            "end_color": [0, 0, 255],
            "speed": 1.0,
            "brightness": 0.5,
            "playback": "loop",
            "duration": 4.0,
        })

    def test_clip_export_import_never_overwrites_existing_clip(self):
        original = self._clip()
        bundle = sharing.export_clip_bundle(original["id"])

        result = sharing.import_bundle(bundle)

        self.assertTrue(result["ok"])
        self.assertEqual(result["kind"], "clip")
        self.assertNotEqual(result["clip"]["id"], original["id"])
        self.assertEqual(result["clip"]["name"], original["name"])
        self.assertEqual(result["clip_id_map"][original["id"]], result["clip"]["id"])
        self.assertIsNotNone(clips.load_clip(result["clip"]["id"]))

    def test_look_export_includes_referenced_clips(self):
        clip = self._clip()
        look = mixer.save_look({
            "id": "look-one",
            "name": "Shared Look",
            "description": "A portable look",
            "device_ips": ["192.168.1.42"],
            "outputs": [{"port": "A0", "type": "short_strip"}],
            "tracks": [{
                "port": "A0",
                "segments": [{
                    "id": "segment-one",
                    "clip_id": clip["id"],
                    "clip_name": clip["name"],
                    "start_time": 0.0,
                    "duration": 2.0,
                }],
            }],
            "playback": "loop",
            "total_duration": 2.0,
            "brightness": 0.75,
        })

        bundle = sharing.export_look_bundle(look["id"])

        self.assertEqual(bundle["kind"], "look")
        self.assertEqual(bundle["look"]["id"], look["id"])
        self.assertEqual([item["id"] for item in bundle["clips"]], [clip["id"]])
        self.assertEqual(bundle["missing_clip_ids"], [])

    def test_look_import_remaps_clips_and_clears_device_targets(self):
        clip = self._clip()
        look = mixer.save_look({
            "id": "look-one",
            "name": "Shared Look",
            "description": "A portable look",
            "device_ips": ["192.168.1.42"],
            "outputs": [{"port": "A0", "type": "short_strip"}],
            "tracks": [{
                "port": "A0",
                "segments": [{
                    "id": "segment-one",
                    "clip_id": clip["id"],
                    "clip_name": clip["name"],
                    "start_time": 0.0,
                    "duration": 2.0,
                }],
            }],
            "playback": "loop",
            "total_duration": 2.0,
            "brightness": 0.75,
        })
        bundle = sharing.export_look_bundle(look["id"])

        result = sharing.import_bundle(bundle)
        imported_look = result["look"]
        imported_segment = imported_look["tracks"][0]["segments"][0]

        self.assertNotEqual(imported_look["id"], look["id"])
        self.assertEqual(imported_look["device_ips"], [])
        self.assertNotEqual(imported_segment["clip_id"], clip["id"])
        self.assertEqual(result["clip_id_map"][clip["id"]], imported_segment["clip_id"])
        self.assertIsNotNone(clips.load_clip(imported_segment["clip_id"]))
        self.assertIsNotNone(mixer.load_look(imported_look["id"]))

    def test_import_unsafe_ids_are_replaced(self):
        result = sharing.import_bundle({
            "kind": "clip",
            "clip": {
                "id": "../not-safe",
                "name": "Unsafe ID",
                "output_type": "short_strip",
                "effect": "solid",
            },
        })

        self.assertNotEqual(result["clip"]["id"], "../not-safe")
        self.assertNotIn("/", result["clip"]["id"])

    def test_invalid_bundle_has_clear_error(self):
        with self.assertRaises(ValueError):
            sharing.import_bundle({"hello": "world"})


if __name__ == "__main__":
    unittest.main()