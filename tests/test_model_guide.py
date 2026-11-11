"""The model guide under the workflow picker: which guide a workflow gets, and that every guide is complete."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fakes  # noqa: E402,F401  Set isolated paths before importing the application.
from core import model_guide  # noqa: E402


def graph(*classes, **inputs):
    return {str(number): {"class_type": name, "inputs": inputs.get(name, {})} for number, name in enumerate(classes, 1)}


class ModelGuideTest(unittest.TestCase):
    def test_a_workflow_gets_the_guide_of_the_model_its_nodes_say(self):
        self.assertEqual(model_guide.key_of(graph("MiniMaxH3ReferenceToVideo")), "minimax_h3_video")
        self.assertEqual(model_guide.key_of(graph("MiniMaxH3MotionDirector", "H3ClipLoaderAny")), "minimax_h3_video")
        self.assertEqual(model_guide.key_of(graph("MiniMaxH3ImageToVideo")), "minimax_h3_video")
        self.assertEqual(model_guide.key_of(graph("EmptyLTXVLatentVideo", "LTXVConditioning")), "ltx23")
        self.assertEqual(model_guide.key_of(graph("TextEncodeFibo2")), "fibo2")
        self.assertEqual(model_guide.key_of(graph("TextEncodeQwenImageEditPlus")), "qwen_image_edit")
        self.assertEqual(model_guide.key_of(graph("MiniMaxH3ImageConditioning")), "minimax_h3_image", "the picture model isn't the video one")
        self.assertEqual(model_guide.key_of(graph("CLIPLoader", CLIPLoader={"type": "krea2"})), "krea2")
        self.assertEqual(model_guide.key_of(graph("CLIPLoader", CLIPLoader={"type": "moss_image"})), "moss_image")
        self.assertIsNone(model_guide.key_of(graph("KSampler")), "a model with no guide has no link")

    def test_what_makes_and_edits_has_one_guide(self):
        edits = {"images.image_1": ["9", 0]}
        self.assertEqual(model_guide.key_of(graph("TextEncodeQwenImage21", TextEncodeQwenImage21=edits)), "qwen_image_21")
        self.assertEqual(model_guide.key_of(graph("MiniMaxH3ImageConditioning", MiniMaxH3ImageConditioning=edits)), "minimax_h3_image")
        self.assertEqual(model_guide.guide("qwen_image_21_edit")["title"], model_guide.guide("qwen_image_21")["title"])

    def test_every_guide_is_complete_and_says_what_the_panel_holds_it_to(self):
        for key in model_guide.GUIDES:
            found = model_guide.guide(key)
            self.assertTrue(found["lead"] and found["facts"] and found["faq"] and found["sources"], key)
            self.assertEqual(found["sections"][0]["title"], "In this panel", key)
            self.assertTrue(all(item.strip() for part in found["sections"] for item in part["items"]), key)
            self.assertTrue(all(url.startswith("https://") for _, url in found["sources"]), key)
        self.assertIn("1.1 MP", " ".join(model_guide.guide("fibo2")["sections"][0]["items"]))
        self.assertIsNone(model_guide.guide("nothing"))

    def test_how_clips_connect_has_a_guide_that_quotes_the_panels_own_numbers(self):
        found = model_guide.guide(model_guide.CONNECTION)
        self.assertEqual(found["title"], "How clips connect")
        notes = " ".join(found["sections"][0]["items"])
        self.assertIn("0.3 s fade", notes)
        self.assertIn("20 steps", notes)
        self.assertIn("15", notes)

    def test_a_file_that_cant_be_read_has_no_guide(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "w.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(graph("TextEncodeFibo2"), f)
            self.assertEqual(model_guide.key_for_path(path), "fibo2")
            self.assertIsNone(model_guide.key_for_path(os.path.join(folder, "missing.json")))
            self.assertIsNone(model_guide.key_for_path(None))


if __name__ == "__main__":
    unittest.main()
