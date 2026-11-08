"""Writing prompts takes longer the more of them: the estimate scales with how many are written."""
import os
import tempfile
import unittest
from unittest import mock

import fakes  # noqa: F401  Set isolated paths before importing the application.

from pipelines.image import run_eta as image_eta
from pipelines.video import run_eta as video_eta


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
