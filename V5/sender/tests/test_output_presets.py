import json
import multiprocessing
import os
import shutil
import sys
import threading
import time
import unittest
from unittest.mock import patch

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

import output_presets
from output_presets import (
    BUILT_IN_OUTPUT_PRESETS,
    BuiltInOutputPresetError,
    DuplicateOutputPresetIdError,
    DuplicateOutputPresetNameError,
    MalformedOutputPresetsError,
    OutputPresetNotFoundError,
    OutputPresetStore,
    OutputPresetValidationError,
    normalize_output_descriptor_template,
)
from primus_protocol import Layout, ScanPattern, StartCorner, TraversalAxis


def _process_update_preset(path, preset_id, entered_save, allow_save, completed):
    try:
        store = OutputPresetStore(path=path)
        original_save = store._save_user_presets

        def delayed_save():
            entered_save.set()
            if not allow_save.wait(timeout=10):
                raise TimeoutError("timed out waiting to save preset update")
            return original_save()

        store._save_user_presets = delayed_save
        store.update_preset(preset_id, name="Updated In Process")
    finally:
        completed.set()


def _process_delete_preset(path, preset_id, started, completed):
    try:
        started.set()
        store = OutputPresetStore(path=path)
        store.delete_preset(preset_id)
    finally:
        completed.set()


class OutputPresetStoreTests(unittest.TestCase):
    def setUp(self):
        root = os.path.dirname(os.path.abspath(__file__))
        unique = f"output-presets-{os.getpid()}-{time.time_ns()}"
        self.scratch_root = os.path.join(root, ".scratch_output_presets")
        self.scratch_dir = os.path.join(self.scratch_root, unique)
        os.makedirs(self.scratch_dir, exist_ok=True)
        self.store_path = os.path.join(self.scratch_dir, "output_presets.json")
        self.store = OutputPresetStore(path=self.store_path)

    def tearDown(self):
        shutil.rmtree(self.scratch_dir, ignore_errors=True)
        if os.path.isdir(self.scratch_root) and not os.listdir(self.scratch_root):
            os.rmdir(self.scratch_root)

    def _join_thread(self, thread):
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive(), f"{thread.name} did not finish")

    def test_built_in_defaults_are_listed_non_deletable_and_not_persisted(self):
        presets = self.store.list_presets()
        self.assertEqual([preset["id"] for preset in presets[:len(BUILT_IN_OUTPUT_PRESETS)]], [
            preset["id"] for preset in BUILT_IN_OUTPUT_PRESETS
        ])
        small_grid = self.store.get_preset("builtin-small-grid")
        self.assertTrue(small_grid["built_in"])
        self.assertFalse(small_grid["editable"])
        self.assertFalse(small_grid["deletable"])
        self.assertEqual(small_grid["descriptor"]["layout"], "grid")
        self.assertEqual(small_grid["descriptor"]["rows"], 4)
        self.assertEqual(small_grid["descriptor"]["columns"], 8)
        self.assertEqual(small_grid["descriptor"]["virtual_pixels"], 1)

        with self.assertRaises(BuiltInOutputPresetError):
            self.store.update_preset("builtin-off", name="Disabled")
        with self.assertRaises(BuiltInOutputPresetError):
            self.store.delete_preset("builtin-off")

        created = self.store.create_preset(
            "User Linear",
            {"enabled": True, "layout": "linear", "physical_pixels": 30, "virtual_pixels": 12},
        )
        with open(self.store_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["version"], 1)
        self.assertEqual(len(payload["presets"]), 1)
        self.assertEqual(payload["presets"][0]["id"], created["id"])
        self.assertEqual(payload["presets"][0]["name"], "User Linear")
        self.assertNotIn("builtin-off", json.dumps(payload))

    def test_create_update_delete_and_reload_round_trip(self):
        created = self.store.create_preset(
            "Stage Grid",
            {
                "enabled": True,
                "layout": "grid",
                "rows": 4,
                "columns": 8,
                "scan_pattern": ScanPattern.SERPENTINE.value,
                "virtual_pixels": "16",
            },
        )
        self.assertFalse(created["built_in"])
        self.assertEqual(created["descriptor"]["physical_pixels"], 32)
        self.assertEqual(created["descriptor"]["scan_pattern"], "serpentine")
        self.assertEqual(created["descriptor"]["virtual_pixels"], 16)

        reloaded = OutputPresetStore(path=self.store_path)
        fetched = reloaded.get_preset(created["id"])
        self.assertEqual(fetched, created)

        updated = reloaded.update_preset(
            created["id"],
            name="Stage Strip",
            descriptor_template={
                "enabled": True,
                "layout": "linear",
                "physical_pixels": 72,
                "virtual_pixels": 18,
                "traversal_axis": "column_major",
                "start_corner": StartCorner.BOTTOM_RIGHT.value,
            },
        )
        self.assertEqual(updated["id"], created["id"])
        self.assertEqual(updated["name"], "Stage Strip")
        self.assertEqual(updated["descriptor"]["layout"], "linear")
        self.assertEqual(updated["descriptor"]["physical_pixels"], 72)
        self.assertEqual(updated["descriptor"]["virtual_pixels"], 18)
        self.assertEqual(updated["descriptor"]["traversal_axis"], "column_major")
        self.assertEqual(updated["descriptor"]["start_corner"], "bottom_right")

        deleted = reloaded.delete_preset(created["id"])
        self.assertEqual(deleted["id"], created["id"])
        with self.assertRaises(OutputPresetNotFoundError):
            reloaded.get_preset(created["id"])
        self.assertEqual(len(reloaded.list_presets(include_built_ins=False)), 0)
        with open(self.store_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["presets"], [])

    def test_generated_ids_are_stable_and_names_must_be_unique(self):
        created = self.store.create_preset(
            "Front Wash",
            {"enabled": True, "layout": "linear", "physical_pixels": 30, "virtual_pixels": 30},
        )
        with self.assertRaises(DuplicateOutputPresetNameError):
            self.store.create_preset(
                "  front   wash  ",
                {"enabled": True, "layout": "linear", "physical_pixels": 72, "virtual_pixels": 72},
            )

        updated = self.store.update_preset(created["id"], name="Front Wash Renamed")
        self.assertEqual(updated["id"], created["id"])

        deleted = self.store.delete_preset(created["id"])
        recreated = self.store.create_preset(
            "Front Wash",
            {"enabled": True, "layout": "linear", "physical_pixels": 122, "virtual_pixels": 60},
        )
        self.assertEqual(recreated["id"], deleted["id"])

        other = self.store.create_preset(
            "Side Wash",
            {"enabled": True, "layout": "linear", "physical_pixels": 72, "virtual_pixels": 36},
        )
        with self.assertRaises(DuplicateOutputPresetNameError):
            self.store.update_preset(other["id"], name="front wash")

    def test_atomic_save_uses_replace_and_rolls_back_on_failure(self):
        created = self.store.create_preset(
            "Atomic Target",
            {"enabled": True, "layout": "linear", "physical_pixels": 30, "virtual_pixels": 30},
        )
        with open(self.store_path, "r", encoding="utf-8") as handle:
            before_payload = json.load(handle)

        temp_seen = {}

        def fail_replace(src, dst):
            temp_seen["src"] = src
            temp_seen["dst"] = dst
            self.assertEqual(os.path.dirname(src), self.scratch_dir)
            self.assertEqual(dst, self.store_path)
            self.assertTrue(os.path.exists(src))
            with open(src, "r", encoding="utf-8") as handle:
                staged = json.load(handle)
            self.assertEqual(staged["presets"][0]["name"], "Atomic Renamed")
            raise OSError("replace failed")

        with patch("output_presets.os.replace", side_effect=fail_replace):
            with self.assertRaises(OSError):
                self.store.update_preset(created["id"], name="Atomic Renamed")

        with open(self.store_path, "r", encoding="utf-8") as handle:
            after_payload = json.load(handle)
        self.assertEqual(after_payload, before_payload)
        self.assertEqual(self.store.get_preset(created["id"])["name"], "Atomic Target")
        self.assertTrue(temp_seen["src"].startswith(os.path.join(self.scratch_dir, ".output_presets.json.tmp-")))
        self.assertFalse(os.path.exists(temp_seen["src"]))

    def test_concurrent_create_transactions_serialize_across_store_instances(self):
        primary = OutputPresetStore(path=self.store_path)
        secondary = OutputPresetStore(path=self.store_path)
        save_barrier = threading.Barrier(2)
        allow_save = threading.Event()
        second_done = threading.Event()
        results = {}

        original_save = primary._save_user_presets

        def delayed_save():
            save_barrier.wait(timeout=2)
            self.assertTrue(allow_save.wait(timeout=2))
            return original_save()

        def create_primary():
            try:
                results["primary"] = primary.create_preset(
                    "Concurrent Create",
                    {"enabled": True, "layout": "linear", "physical_pixels": 30, "virtual_pixels": 30},
                )
            except Exception as exc:
                results["primary_error"] = exc

        def create_secondary():
            try:
                results["secondary"] = secondary.create_preset(
                    "Concurrent Create",
                    {"enabled": True, "layout": "linear", "physical_pixels": 72, "virtual_pixels": 72},
                )
            except Exception as exc:
                results["secondary_error"] = exc
            finally:
                second_done.set()

        with patch.object(primary, "_save_user_presets", side_effect=delayed_save):
            primary_thread = threading.Thread(name="primary-create", target=create_primary)
            secondary_thread = threading.Thread(name="secondary-create", target=create_secondary)
            primary_thread.start()
            save_barrier.wait(timeout=2)
            secondary_thread.start()
            self.assertFalse(second_done.wait(timeout=0.1))
            allow_save.set()
            self._join_thread(primary_thread)
            self._join_thread(secondary_thread)

        self.assertNotIn("primary_error", results)
        self.assertIn("secondary_error", results)
        self.assertIsInstance(results["secondary_error"], DuplicateOutputPresetNameError)
        persisted = OutputPresetStore(path=self.store_path).list_presets(include_built_ins=False)
        self.assertEqual([preset["id"] for preset in persisted], [results["primary"]["id"]])

    def test_concurrent_delete_blocks_stale_update_and_prevents_resurrection(self):
        created = self.store.create_preset(
            "Stale Update Target",
            {"enabled": True, "layout": "linear", "physical_pixels": 30, "virtual_pixels": 30},
        )
        deleter = OutputPresetStore(path=self.store_path)
        stale_updater = OutputPresetStore(path=self.store_path)
        replace_barrier = threading.Barrier(2)
        allow_replace = threading.Event()
        update_done = threading.Event()
        results = {}

        original_replace = output_presets.os.replace

        def delayed_replace(src, dst):
            if threading.current_thread().name == "delete-preset-thread":
                replace_barrier.wait(timeout=2)
                self.assertTrue(allow_replace.wait(timeout=2))
            return original_replace(src, dst)

        def delete_preset():
            try:
                results["deleted"] = deleter.delete_preset(created["id"])
            except Exception as exc:
                results["delete_error"] = exc

        def stale_update():
            try:
                results["updated"] = stale_updater.update_preset(created["id"], name="Resurrected")
            except Exception as exc:
                results["update_error"] = exc
            finally:
                update_done.set()

        with patch("output_presets.os.replace", side_effect=delayed_replace):
            delete_thread = threading.Thread(name="delete-preset-thread", target=delete_preset)
            update_thread = threading.Thread(name="stale-update-thread", target=stale_update)
            delete_thread.start()
            replace_barrier.wait(timeout=2)
            update_thread.start()
            self.assertFalse(update_done.wait(timeout=0.1))
            allow_replace.set()
            self._join_thread(delete_thread)
            self._join_thread(update_thread)

        self.assertNotIn("delete_error", results)
        self.assertIn("update_error", results)
        self.assertIsInstance(results["update_error"], OutputPresetNotFoundError)
        self.assertEqual(
            OutputPresetStore(path=self.store_path).list_presets(include_built_ins=False),
            [],
        )
        with self.assertRaises(OutputPresetNotFoundError):
            stale_updater.get_preset(created["id"])

    def test_concurrent_read_waits_for_update_commit_and_skips_half_mutated_state(self):
        created = self.store.create_preset(
            "Read Consistency",
            {"enabled": True, "layout": "linear", "physical_pixels": 30, "virtual_pixels": 30},
        )
        save_barrier = threading.Barrier(2)
        allow_save = threading.Event()
        reader_done = threading.Event()
        results = {}

        original_save = self.store._save_user_presets

        def delayed_save():
            save_barrier.wait(timeout=2)
            self.assertTrue(allow_save.wait(timeout=2))
            return original_save()

        def update_preset():
            try:
                results["updated"] = self.store.update_preset(created["id"], name="Read Committed")
            except Exception as exc:
                results["update_error"] = exc

        def read_preset():
            try:
                results["read"] = self.store.get_preset(created["id"])
            except Exception as exc:
                results["read_error"] = exc
            finally:
                reader_done.set()

        with patch.object(self.store, "_save_user_presets", side_effect=delayed_save):
            update_thread = threading.Thread(name="update-preset-thread", target=update_preset)
            reader_thread = threading.Thread(name="read-preset-thread", target=read_preset)
            update_thread.start()
            save_barrier.wait(timeout=2)
            reader_thread.start()
            self.assertFalse(reader_done.wait(timeout=0.1))
            allow_save.set()
            self._join_thread(update_thread)
            self._join_thread(reader_thread)

        self.assertNotIn("update_error", results)
        self.assertNotIn("read_error", results)
        self.assertEqual(results["read"]["name"], "Read Committed")
        with open(self.store_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(payload["presets"][0]["name"], "Read Committed")

    def test_cross_process_delete_cannot_be_resurrected_by_stale_update(self):
        created = self.store.create_preset(
            "Cross Process",
            {"enabled": True, "layout": "linear", "physical_pixels": 30, "virtual_pixels": 30},
        )
        start_method = (
            "fork"
            if "fork" in multiprocessing.get_all_start_methods()
            else "spawn"
        )
        context = multiprocessing.get_context(start_method)
        entered_save = context.Event()
        allow_save = context.Event()
        update_completed = context.Event()
        delete_started = context.Event()
        delete_completed = context.Event()
        update_process = context.Process(
            target=_process_update_preset,
            args=(self.store_path, created["id"], entered_save, allow_save, update_completed),
        )
        delete_process = context.Process(
            target=_process_delete_preset,
            args=(self.store_path, created["id"], delete_started, delete_completed),
        )

        try:
            update_process.start()
            self.assertTrue(entered_save.wait(timeout=5))
            delete_process.start()
            self.assertTrue(delete_started.wait(timeout=5))
            self.assertFalse(delete_completed.wait(timeout=0.2))
        finally:
            allow_save.set()
            if update_process.pid is not None:
                update_process.join(timeout=10)
            if delete_process.pid is not None:
                delete_process.join(timeout=10)

        self.assertFalse(update_process.is_alive())
        self.assertFalse(delete_process.is_alive())
        self.assertEqual(update_process.exitcode, 0)
        self.assertEqual(delete_process.exitcode, 0)
        self.assertTrue(update_completed.is_set())
        self.assertTrue(delete_completed.is_set())
        with self.assertRaises(OutputPresetNotFoundError):
            OutputPresetStore(path=self.store_path).get_preset(created["id"])

    def test_malformed_persisted_data_and_duplicates_raise_explicit_errors(self):
        cases = [
            (
                "invalid-json",
                "{not json",
                MalformedOutputPresetsError,
            ),
            (
                "invalid-entry-shape",
                {
                    "version": 1,
                    "presets": [
                        {"id": "preset-a", "name": "Broken", "descriptor": {"enabled": True, "layout": "linear"}},
                    ],
                },
                MalformedOutputPresetsError,
            ),
            (
                "duplicate-id",
                {
                    "version": 1,
                    "presets": [
                        {
                            "id": "preset-dup",
                            "name": "One",
                            "descriptor": {"enabled": True, "layout": "linear", "physical_pixels": 30, "virtual_pixels": 30},
                        },
                        {
                            "id": "preset-dup",
                            "name": "Two",
                            "descriptor": {"enabled": True, "layout": "linear", "physical_pixels": 72, "virtual_pixels": 72},
                        },
                    ],
                },
                DuplicateOutputPresetIdError,
            ),
            (
                "duplicate-name",
                {
                    "version": 1,
                    "presets": [
                        {
                            "id": "preset-one",
                            "name": "Same",
                            "descriptor": {"enabled": True, "layout": "linear", "physical_pixels": 30, "virtual_pixels": 30},
                        },
                        {
                            "id": "preset-two",
                            "name": "same",
                            "descriptor": {"enabled": True, "layout": "linear", "physical_pixels": 72, "virtual_pixels": 72},
                        },
                    ],
                },
                DuplicateOutputPresetNameError,
            ),
        ]
        for label, payload, error_type in cases:
            with self.subTest(label=label):
                path = os.path.join(self.scratch_dir, f"{label}.json")
                if isinstance(payload, str):
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write(payload)
                else:
                    with open(path, "w", encoding="utf-8") as handle:
                        json.dump(payload, handle)
                with self.assertRaises(error_type):
                    OutputPresetStore(path=path)

    def test_descriptor_validation_normalizes_off_linear_and_grid(self):
        off = normalize_output_descriptor_template({"layout": "off"})
        self.assertEqual(off, {
            "enabled": False,
            "physical_pixels": 0,
            "layout": "off",
            "rows": 0,
            "columns": 0,
            "traversal_axis": "row_major",
            "scan_pattern": "progressive",
            "start_corner": "top_left",
            "virtual_pixels": 0,
        })

        linear = normalize_output_descriptor_template({
            "enabled": 1,
            "layout": Layout.LINEAR.value,
            "physical_pixels": "30",
            "virtual_pixels": 12,
            "traversal_axis": TraversalAxis.COLUMN_MAJOR.value,
            "scan_pattern": "progressive",
            "start_corner": "bottom_left",
        })
        self.assertEqual(linear["layout"], "linear")
        self.assertEqual(linear["physical_pixels"], 30)
        self.assertEqual(linear["virtual_pixels"], 12)
        self.assertEqual(linear["traversal_axis"], "column_major")
        self.assertEqual(linear["start_corner"], "bottom_left")

        grid = normalize_output_descriptor_template({
            "rows": 4,
            "columns": 8,
            "layout": "grid",
            "virtual_pixels": 1,
        })
        self.assertEqual(grid["enabled"], True)
        self.assertEqual(grid["physical_pixels"], 32)
        self.assertEqual(grid["scan_pattern"], "serpentine")

        with self.assertRaisesRegex(OutputPresetValidationError, "rows \\* columns"):
            normalize_output_descriptor_template({
                "enabled": True,
                "layout": "grid",
                "physical_pixels": 32,
                "rows": 8,
                "columns": 8,
            })
        with self.assertRaisesRegex(OutputPresetValidationError, "between 1 and physical_pixels"):
            normalize_output_descriptor_template({
                "enabled": True,
                "layout": "linear",
                "physical_pixels": 30,
                "virtual_pixels": 31,
            })
        with self.assertRaisesRegex(OutputPresetValidationError, "170"):
            normalize_output_descriptor_template({
                "enabled": True,
                "layout": "linear",
                "physical_pixels": 171,
                "virtual_pixels": 171,
            })


if __name__ == "__main__":
    unittest.main()
