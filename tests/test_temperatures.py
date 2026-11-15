"""Settings' temperature graph: the minute buckets it keeps and what a range gives."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fakes  # noqa: F401,E402  (keeps live data out of the tests)

from panel import temperatures  # noqa: E402


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class TemperatureLogTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = os.path.join(self.folder.name, "temperatures.jsonl")

    def test_each_minute_keeps_lowest_average_and_highest(self):
        clock = Clock(1_000_020)
        log = temperatures.TemperatureLog(self.path, clock)
        for gpu, cpu in ((60, 50), (70, None), (80, 56)):
            log.add(gpu=gpu, cpu=cpu)
            clock.now += 3
        clock.now += 60
        log.add(gpu=65)
        with open(self.path, encoding="utf-8") as f:
            saved = [json.loads(line) for line in f]
        self.assertEqual(saved, [{"t": 1_000_020 // 60 * 60, "gpu": [60, 70.0, 80, 3], "cpu": [50, 53.0, 56, 2]}])
        result = log.query(1)
        self.assertEqual(result["summary"]["gpu"], {"min": 60, "avg": 68.8, "max": 80, "now": 65})
        self.assertEqual(result["summary"]["cpu"]["max"], 56)
        self.assertEqual(len(result["points"]), 2, "the minute going is shown too")

    def test_a_week_is_kept_and_long_ranges_are_merged(self):
        clock = Clock(10_000_000)
        log = temperatures.TemperatureLog(self.path, clock)
        start = clock.now - 8 * 24 * 3600
        for minute in range(0, 8 * 24 * 60, 10):
            clock.now = start + minute * 60
            log.add(gpu=50 + minute % 30, cpu=40)
        clock.now += 60
        log.add(gpu=50)
        result = log.query(168)
        self.assertLessEqual(len(result["points"]), temperatures.MOST_POINTS)
        self.assertGreaterEqual(result["points"][0]["t"], clock.now - 7 * 24 * 3600 - result["step"])
        reopened = temperatures.TemperatureLog(self.path, clock)
        self.assertTrue(all(bucket["t"] >= clock.now - temperatures.KEEP_SECONDS for bucket in reopened.buckets),
                        "a week, no more, after the panel starts again")

    def test_missing_cpu_reading_leaves_cpu_out(self):
        log = temperatures.TemperatureLog(self.path, Clock(5_000_000))
        log.add(gpu=55, cpu=None)
        self.assertIsNone(log.query(1)["summary"]["cpu"])


if __name__ == "__main__":
    unittest.main()
