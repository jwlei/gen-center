"""An upscaled image keeps the original's ComfyUI workflow, and with it its seed."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fakes  # noqa: E402,F401  Set isolated paths before importing the application.
from PIL import Image  # noqa: E402
from PIL.PngImagePlugin import PngInfo  # noqa: E402

from pipelines.image import media  # noqa: E402
from pipelines.image.upscale import keep_origin  # noqa: E402


def png(path, size, prompt=None):
    info = PngInfo()
    if prompt is not None:
        info.add_text("prompt", json.dumps(prompt))
        info.add_text("workflow", "{}")
    Image.new("RGB", size, "red").save(path, pnginfo=info)


class KeepOriginTest(unittest.TestCase):
    def test_the_upscale_keeps_the_originals_seed_and_says_how_it_was_made(self):
        with tempfile.TemporaryDirectory() as folder:
            source, made = os.path.join(folder, "a.png"), os.path.join(folder, "a_upscaled.png")
            png(source, (8, 8), {"3": {"class_type": "KSampler", "inputs": {"seed": 1234}}})
            png(made, (16, 16), {"1": {"class_type": "SeedVR2VideoUpscaler", "inputs": {"seed": 777}}})
            self.assertEqual(media.seeds_in(made), {777}, "as ComfyUI saves it: the upscaler's seed")
            keep_origin(source, made, "SeedVR2, 3× (2496p)")
            self.assertEqual(media.seeds_in(made), {1234}, "the original's seed")
            with Image.open(made) as image:
                self.assertEqual(image.size, (16, 16), "the upscaled picture itself")
                self.assertEqual((image.info["upscaled_with"], image.info["workflow"]), ("SeedVR2, 3× (2496p)", "{}"))

    def test_an_original_without_a_workflow_leaves_it_be(self):
        with tempfile.TemporaryDirectory() as folder:
            source, made = os.path.join(folder, "a.png"), os.path.join(folder, "b.png")
            png(source, (8, 8))
            png(made, (16, 16), {"1": {"class_type": "X", "inputs": {"seed": 777}}})
            keep_origin(source, made, "Ultimate SD")
            self.assertEqual(media.seeds_in(made), {777})


if __name__ == "__main__":
    unittest.main()
