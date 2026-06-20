import os
import sys
import unittest

SENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SENDER_DIR not in sys.path:
    sys.path.insert(0, SENDER_DIR)

from state import PerformanceStats


class PerformanceStatsTests(unittest.TestCase):
    def test_snapshot_returns_stale_copy_when_lock_is_busy(self):
        stats = PerformanceStats()
        stats.increment("frames", 2)
        fresh = stats.snapshot()
        self.assertFalse(fresh.get("stale", False))

        stats.lock.acquire()
        try:
            stale = stats.snapshot()
        finally:
            stats.lock.release()

        self.assertTrue(stale["stale"])
        self.assertEqual(stale["counters"]["frames"], 2)


if __name__ == "__main__":
    unittest.main()
