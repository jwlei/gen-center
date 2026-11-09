"""ETAs for the upscales: on their own, in Generate (image), latent upscale and FastVideo (video)."""
import json
import os
import tempfile
import unittest
from unittest import mock

import fakes  # noqa: F401  Set isolated paths before importing the application.

from core import upscale_eta
from core.eta_keys import Timings
from pipelines.image import run_eta as image_eta
from pipelines.video import run_eta as video_eta


class UpscaleEtaTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.path = os.path.join(self.folder, "timings.json")

    def eta(self, argv, amount):
        with mock.patch.object(upscale_eta.UpscaleEta, "_amount", return_value=amount):
            return upscale_eta.UpscaleEta(argv, self.path)

    def test_an_image_upscale_is_estimated_per_megapixel_by_method_and_learns(self):
        argv = ["python", "-m", "pipelines.image.upscale", "--resume", "image_1", "--image", "1", "--method", "seedvr2"]
        first = self.eta(argv, 4.0)
        guess = first.plan()["total"]
        self.assertEqual(guess, upscale_eta.START_SECONDS["seedvr2"] + upscale_eta.IMAGE_RATES["seedvr2"] * 4)
        self.assertNotEqual(guess, self.eta([*argv[:-1], "ultrasharp"], 4.0).plan()["total"], "each way its own time")
        first.started -= 200
        first.finish()
        learned = self.eta(argv, 4.0).plan()["total"]
        self.assertEqual(learned, 200, "the next of its kind takes what this one did")
        self.assertEqual(self.eta(argv, 8.0).plan()["total"], upscale_eta.START_SECONDS["seedvr2"] + (200 - 40) / 4 * 8, "per megapixel")

    def test_a_film_upscale_is_per_megapixel_second(self):
        argv = ["python", "-m", "pipelines.video.upscale", "--film", "a.mp4", "--scale", "2", "--quality", "ULTRA"]
        eta = self.eta(argv, 10.0)
        self.assertEqual(eta.method, "vsr")
        self.assertEqual(eta.plan()["total"], round(upscale_eta.START_SECONDS["vsr"] + upscale_eta.FILM_RATE * 10))

    def test_running_it_counts_down_and_says_when_it_drifts(self):
        eta = self.eta(["pipelines.image.upscale", "--method", "fast"], 1.0)
        eta.started -= 5
        self.assertEqual(eta.estimate()["total_left"], eta.original_total - 5)
        eta.started -= 200
        self.assertTrue(eta.estimate()["changes"], "running past its estimate is said")
        eta.stage(1, 2, "x")  # What other runs report does nothing here

    def test_the_target_is_worked_out_as_the_upscaler_does(self):
        self.assertEqual(upscale_eta.image_target(1000, 2000, "fast"), (2000, 4000))
        self.assertEqual(upscale_eta.image_target(3000, 6000, "usdu"), (4096, 8192), "held to 8192")
        self.assertEqual(upscale_eta.image_target(1000, 2000, "seedvr2", 1440), (1440, 2880))
        self.assertTrue(upscale_eta.is_upscale(["x", "pipelines.video.upscale"]))
        self.assertFalse(upscale_eta.is_upscale(["x", "pipelines.image.main"]))


class ImageUpscaleInGenerationTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "image.json")

    def eta(self, *options):
        argv = ["python", "-m", "pipelines.image.main", "--direct", "--count", "1", "--aspect", "1:1", "--megapixels", "1"]
        for option in options:
            argv += ["--option", option]
        return image_eta.RunEta(argv, {}, self.path)

    def test_making_the_image_is_shared_and_the_upscale_added_per_megapixel(self):
        plain = self.eta()
        up = self.eta("image_upscale=SeedVR2", "image_upscale_size=2048x2048", "image_upscale_scale=2")
        self.assertEqual(up.render_keys, plain.render_keys, "made the same way, upscale aside")
        self.assertAlmostEqual(up._image_seconds() - plain._image_seconds(), image_eta.UPSCALE_RATES["SeedVR2"] * 2048 * 2048 / 1e6)

    def test_it_learns_the_image_first_then_the_upscale(self):
        options = ("image_upscale=UltraSharp", "image_upscale_size=2000x2000")
        eta = self.eta(*options)
        eta.image_started = 0
        eta._finish_image(100)
        self.assertTrue(any(key in eta.timings.renders for key in eta.render_keys), "the image is timed first")
        eta = self.eta(*options)
        made = eta.timings.render(eta.render_keys, 0) * eta.size_share
        eta.image_started = 0
        eta._finish_image(made + 40)
        self.assertAlmostEqual(Timings(self.path, {}).step(eta.upscale_keys), 40 / 4.0, msg="then the upscale, per megapixel it ends at")


class VideoLatentAndFastVideoTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "video.json")

    def eta(self, options):
        argv = ["python", "-m", "pipelines.video.main", "--direct", "--duration", "10", "--size", "640x352", "--", "", "x"]
        return video_eta.RunEta(argv, self.path, {"COMFYUI_OPTIONS": json.dumps(options)})

    def test_latent_upscale_adds_its_refine_by_preset_and_shares_the_clip_time(self):
        plain = self.eta({})
        hires = self.eta({"latent_upscale": "Hires fix", "latent_upscale_mp": "0.9"})
        heavy = self.eta({"latent_upscale": "Heavy", "latent_upscale_mp": "0.9"})
        self.assertEqual(hires.render_keys, plain.render_keys)
        extra = hires._render_seconds(5) - plain._render_seconds(5)
        self.assertAlmostEqual(extra, video_eta.LATENT_SECONDS_PER_STEP * 2 * 0.9e6 / video_eta.RENDER_AREA * 5)
        self.assertGreater(heavy._render_seconds(5), hires._render_seconds(5), "more refine steps, longer")

    def test_fastvideo_starts_from_a_share_of_the_standard_model_then_learns_its_own(self):
        standard = self.eta({})
        fast = self.eta({"h3_model": "FastVideo 4-step"})
        self.assertNotEqual(fast.render_keys, standard.render_keys)
        self.assertAlmostEqual(fast._render_seconds(5), standard._render_seconds(5) * video_eta.FASTVIDEO_SHARE)
        fast.attempt_started, fast.attempt_seconds = 0, 5
        fast._finish_attempt(30)
        self.assertAlmostEqual(self.eta({"h3_model": "FastVideo 4-step"})._render_seconds(5), 30, places=3)


if __name__ == "__main__":
    unittest.main()
