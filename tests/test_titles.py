"""Gemini titles (Settings): a short title from Gemini for a new film or set; its own title when off or failing."""
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fakes  # noqa: E402,F401  Set isolated paths before importing the application.
from core import titles  # noqa: E402
from panel import settings  # noqa: E402


class TitlesTest(unittest.TestCase):
    def test_a_reply_becomes_a_clean_title(self):
        self.assertEqual(titles.clean('"Moonlit Library Reading Nook."\nBecause...'), "Moonlit Library Reading Nook")
        self.assertEqual(titles.clean("**Elven Sway**"), "Elven Sway")
        self.assertEqual(titles.clean("one two three four five six seven eight nine ten"), "one two three four five six seven eight")
        self.assertEqual(titles.clean("   "), "")

    def test_on_it_asks_gemini_off_it_keeps_its_own(self):
        reply = types.SimpleNamespace(text="Elven Dancer at Dusk")
        with mock.patch.object(titles, "_generate", return_value=reply) as ask, \
                mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x"}):
            with mock.patch.object(titles.panel_settings, "load", return_value={"gemini_titles": True}):
                self.assertEqual(titles.titled("An elf sways in", "An elf sways in a dim hall", "a short film"), "Elven Dancer at Dusk")
                self.assertIn("An elf sways in a dim hall", ask.call_args.args[0], "from its prompt")
                self.assertEqual(titles.titled("Own", "  ", "a short film"), "Own", "no prompt: nothing to title from")
            with mock.patch.object(titles.panel_settings, "load", return_value={"gemini_titles": False}):
                ask.reset_mock()
                self.assertEqual(titles.titled("Own", "A prompt", "a short film"), "Own")
                ask.assert_not_called()

    def test_without_a_key_or_when_gemini_fails_it_keeps_its_own(self):
        with mock.patch.object(titles.panel_settings, "load", return_value={"gemini_titles": True}):
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}), mock.patch.object(titles, "_generate") as ask:
                self.assertEqual(titles.titled("Own", "A prompt", "a set of images"), "Own")
                ask.assert_not_called()
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x"}), \
                    mock.patch.object(titles, "_generate", side_effect=RuntimeError("quota")):
                self.assertEqual(titles.titled("Own", "A prompt", "a set of images"), "Own")

    def test_refused_by_gemini_the_local_model_titles_it(self):
        refused = types.SimpleNamespace(text=None, prompt_feedback=types.SimpleNamespace(block_reason=types.SimpleNamespace(name="PROHIBITED_CONTENT")))
        with mock.patch.object(titles.panel_settings, "load", return_value={"gemini_titles": True}), \
                mock.patch.dict(os.environ, {"GEMINI_API_KEY": "x"}), mock.patch.object(titles, "_generate", return_value=refused), \
                mock.patch.object(titles, "local_title", return_value="Highborn Portrait") as local:
            self.assertEqual(titles.titled("Own", "A prompt", "a set of images", "http://comfy", "gemini"), "Highborn Portrait")
            local.assert_called_once_with("A prompt", "a set of images", "http://comfy")
            local.reset_mock()
            self.assertEqual(titles.titled("Own", "A prompt", "a set of images", "http://comfy", "local"), "Own",
                             "the local model wrote its prompts, and its title with them")
            local.assert_not_called()
            local.return_value = None
            self.assertEqual(titles.titled("Own", "A prompt", "a set of images", "http://comfy", None), "Own", "both fail: its own")

    def test_the_local_model_answers_in_json(self):
        refiner = mock.MagicMock()
        refiner.__enter__.return_value.plan.return_value = '{"title": "Highborn Portrait."}'
        with mock.patch("core.h3_refiner.Refiner", return_value=refiner), mock.patch("core.h3_refiner.local_llm_model", return_value="gemma-4-12b"):
            self.assertEqual(titles.local_title("A prompt", "a set of images", "http://comfy"), "Highborn Portrait")
        with mock.patch("core.h3_refiner.Refiner", side_effect=RuntimeError("ComfyUI busy")), mock.patch("core.h3_refiner.local_llm_model", return_value="x"):
            self.assertIsNone(titles.local_title("A prompt", "a set of images", "http://comfy"))

    def test_the_setting_is_kept(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(settings, "PATH", os.path.join(folder, "settings.json")):
            self.assertFalse(settings.load()["gemini_titles"], "off until turned on")
            self.assertTrue(settings.update({"gemini_titles": True})["gemini_titles"])
            self.assertTrue(settings.load()["gemini_titles"])


if __name__ == "__main__":
    unittest.main()
