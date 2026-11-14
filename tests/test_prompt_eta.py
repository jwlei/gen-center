"""Writing prompts takes longer the more of them: the estimate scales with how many are written."""
import json
import os
import tempfile
import unittest
from unittest import mock

import fakes  # noqa: F401  Set isolated paths before importing the application.

from core.eta_keys import Timings
from pipelines.image import run_eta as image_eta
from pipelines.video import run_eta as video_eta


class TimingHistoryTest(unittest.TestCase):
    def test_trimming_starts_at_twenty_and_history_survives_reload(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "timings.json")
            timings = Timings(path, {})
            values = [1] + [10] * 17 + [1000]
            for value in values:
                timings.learn_step(["Plan | local:gemma", "Plan | local"], value)
                timings.learn_render(["render"], value)
            self.assertAlmostEqual(timings.step("Plan | local:gemma"), sum(values) / 19)
            timings.save()
            timings = Timings(path, {})
            timings.learn_step(["Plan | local:gemma", "Plan | local"], 10)
            timings.learn_render(["render"], 10)
            self.assertEqual(timings.step("Plan | local:gemma"), 10)
            self.assertEqual(timings.step("Plan | local"), 10)
            self.assertEqual(timings.render(["render"], None), 10)
            timings.learn_step("another model", 200)
            self.assertEqual(timings.step("another model"), 200)
            self.assertEqual(timings.step("Plan | local:gemma"), 10)

    def test_only_the_latest_hundred_measurements_affect_the_estimate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "timings.json")
            timings = Timings(path, {})
            for value in range(1, 121):
                timings.learn_step("Plan", value)
                timings.learn_render(["render"], value)
            self.assertEqual(timings.step("Plan"), 70.5)
            self.assertEqual(timings.render(["render"], None), 70.5)
            timings.save()
            with open(path, encoding="utf-8") as file:
                saved = json.load(file)
            self.assertEqual(saved["samples"]["steps"]["Plan"], list(range(21, 121)))
            self.assertEqual(saved["samples"]["renders"]["render"], list(range(21, 121)))
            timings = Timings(path, {})
            timings.learn_step("Plan", 121)
            self.assertEqual(timings.step("Plan"), 71.5)

    def test_old_estimates_remain_until_remeasured_without_becoming_fake_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "timings.json")
            with open(path, "w", encoding="utf-8") as file:
                json.dump({"steps": {"Plan": 42, "Voice": 9}, "renders": {"render": 75}}, file)
            timings = Timings(path, {})
            self.assertEqual(timings.step("Plan"), 42)
            self.assertEqual(timings.render(["render"], None), 75)
            timings.learn_step("Plan", 100)
            timings.learn_step("Plan", 200)
            self.assertEqual(timings.step("Plan"), 150)
            self.assertEqual(timings.step("Voice"), 9)
            self.assertEqual(timings.render(["render"], None), 75)

    def test_invalid_history_is_logged_and_invalid_measurements_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "timings.json")
            with open(path, "w", encoding="utf-8") as file:
                json.dump({"steps": {"Plan": 42}, "samples": {"steps": {"Plan": [10, float("nan")]}}}, file)
            with self.assertLogs("core.eta_keys", level="WARNING"):
                timings = Timings(path, {})
            self.assertEqual(timings.step("Plan"), 42)
            for value in (float("inf"), float("nan"), -1, True):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    timings.learn_step("Plan", value)
            timings.learn_step("Plan", 0)
            self.assertEqual(timings.step("Plan"), 0)


class ImagePromptEtaTest(unittest.TestCase):
    def eta(self, path, count, *extra):
        return image_eta.RunEta(["--count", str(count), "--llm", "gemini", *extra, "--", "a brief"], {}, path)

    def prompts(self, eta):
        return next(step["seconds"] for step in eta.plan()["steps"] if step["name"] == "Prompts")

    def test_more_prompts_take_longer_until_and_after_it_is_timed(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch("time.time") as clock:
            path = os.path.join(folder, "timings.json")
            clock.return_value = 100
            self.assertEqual(self.prompts(self.eta(path, 1)), image_eta.DEFAULT_SECONDS_PER_PROMPT)
            five = self.eta(path, 5)
            self.assertEqual(self.prompts(five), 5 * image_eta.DEFAULT_SECONDS_PER_PROMPT, "five prompts, five times one")

            five.stage(1, 2, "Prompts")
            clock.return_value = 200  # Five written in 100 s
            five.stage(2, 2, "Images")
            self.assertEqual(self.prompts(self.eta(path, 5)), 100, "as timed, for this many")
            self.assertEqual(self.prompts(self.eta(path, 10)), 200, "another number: 20 s a prompt, times ten")
            self.assertEqual(self.prompts(self.eta(path, 1)), 20)

    def test_a_preview_run_still_writes_every_prompt(self):
        with tempfile.TemporaryDirectory() as folder:
            eta = self.eta(os.path.join(folder, "timings.json"), 5, "--first-only")
            self.assertEqual(eta.images, 1, "one image rendered now")
            self.assertEqual(self.prompts(eta), 5 * image_eta.DEFAULT_SECONDS_PER_PROMPT, "but five prompts written")


class VideoPlanEtaTest(unittest.TestCase):
    def test_the_plan_scales_with_its_shots_once_timed(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch("time.time") as clock:
            path = os.path.join(folder, "timings.json")
            clock.return_value = 100
            argv = ["--duration", "20", "--clip-seconds", "5-5", "--fixed-clips", "--llm", "gemini"]
            eta = video_eta.RunEta(argv, path)
            self.assertEqual(eta.shots, 4)
            eta.stage(1, 3, "Plan")
            clock.return_value = 180  # Four shots planned in 80 s
            eta.event("planned")
            longer = video_eta.RunEta(["--duration", "40", "--clip-seconds", "5-5", "--fixed-clips", "--llm", "gemini"], path)
            self.assertEqual(longer.shots, 8)
            plan = next(step["seconds"] for step in longer.plan()["steps"] if step["name"] == "Plan")
            self.assertEqual(plan, 160, "twice the shots: 20 s a shot, times eight")


if __name__ == "__main__":
    unittest.main()
