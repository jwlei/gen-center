"""Pills: what a film or set was made with, and which of those tell it apart from what its prompt made besides."""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import pills  # noqa: E402


def item(prompt, **made):
    return {"_sibling": pills.sibling_key("video", prompt), "_facts": pills.facts(**made)}


class PillsTest(unittest.TestCase):
    def test_always_in_one_order_and_what_differs_is_marked(self):
        latent = item("An elf sways", workflow="Minimax_H3_R2V", upscaled="Latent, Clean, 1.1 MP", clips="image", llm="local", mode="I2V")
        plain = item("  an ELF   sways ", workflow="Minimax_H3_R2V", clips="image", llm="local", mode="I2V")
        wan = item("An elf sways", workflow="Wan 2.2", clips="chain", llm="local", mode="T2V")
        alone = item("Jungle flight", workflow="Minimax_H3_R2V", llm="local")
        pills.with_pills([latent, plain, wan, alone])
        shown = lambda one: [(p["text"], p["diff"]) for p in one["pills"]]
        self.assertEqual(shown(latent), [("Minimax_H3_R2V", True), ("I2V", True), ("local", False),
                                         ("Upscaled: Latent, Clean, 1.1 MP", True), ("Separate moments", True)],
                         "workflow, mode, LLM, then the rest: where they always are, differing or not")
        exact = item("Jungle flight", workflow="Wan 2.2", upscaled="RTX VSR", llm="local", direct=True)
        pills.with_pills([exact, item("Jungle flight", workflow="Minimax_H3_R2V", llm="local")])
        self.assertEqual(shown(exact)[:2], [("Wan 2.2", True), ("Exact prompt", True)], "your own prompt, in the LLM's place")
        self.assertNotIn("No upscale", [text for text, _ in shown(plain)], "no upscale isn't a pill of its own")
        self.assertEqual(shown(wan)[:3], [("Wan 2.2", True), ("T2V", True), ("local", False)])
        self.assertTrue(all(not diff for _, diff in shown(alone)), "no siblings: nothing marked")
        self.assertNotIn("_sibling", latent, "the prompt stays on the server")
        self.assertNotIn("_facts", latent)

    def test_the_order_wanted_most(self):
        made = pills.facts("Krea2", "UltraSharp", loras=["KNPV3"], llm="Gemma 4", prompt_writer="Image to prompt", mode="T2I",
                           sampling="euler, 8 steps", files=[("vae", "VAE qwen")], test="VAE test")
        self.assertEqual([pill["kind"] for pill in pills.pills(made, [])],
                         ["workflow", "mode", "test", "llm", "writer", "lora", "vae", "upscale", "sampling"])
        self.assertIn(("writer", "I2P"), made, "image to prompt, as its pill says it")

    def test_a_comparisons_test_pill_says_so(self):
        compared = {**item("An elf", workflow="Krea2", direct=True, test="VAE test", mode="T2I"), "_comparison": True}
        usual = item("An elf", workflow="Krea2", direct=True, mode="T2I")
        pills.with_pills([compared, usual])
        self.assertEqual([(p["text"], p.get("comparison", False)) for p in compared["pills"]][:4],
                         [("Krea2", False), ("T2I", False), ("VAE test", True), ("Exact prompt", False)], "its test pill, in the theme's colour")
        self.assertFalse(any(p.get("comparison") for p in usual["pills"]))
        self.assertNotIn("_comparison", compared)

    def test_a_sides_prompt_is_its_own(self):
        self.assertNotEqual(pills.sibling_key("video", "x"), pills.sibling_key("image", "x"))
        self.assertIsNone(pills.sibling_key("video", "  "))

    def test_fixed_tag_names_what_differs_else_its_time(self):
        own = pills.facts("Minimax_H3_R2V", "Latent, Clean, 1.1 MP", "image", llm="local")
        before = [pills.facts("Minimax_H3_R2V", None, "image", llm="local")]
        self.assertEqual(pills.fixed_tag(own, before, "1113"), "Upscaled-Latent-Clean-1.1-MP")
        self.assertEqual(pills.fixed_tag(own, [own], "1113"), "1113", "made the same way: its time")
        self.assertEqual(pills.fixed_tag(own, [], "1113"), "", "the first keeps the plain name")
        other_workflow = [pills.facts("Wan 2.2", "Latent, Clean, 1.1 MP", "image", llm="local")]
        self.assertEqual(pills.fixed_tag(own, other_workflow, "1113"), "1113", "the workflow is already in the name")
        self.assertEqual(pills.run_stamp("run_20261109_111347"), "1113")

    def test_run_facts_as_it_was_set_up(self):
        state = types.SimpleNamespace(options={"latent_upscale": "Clean", "latent_upscale_mp": "1.1"}, connection_mode=None,
                                      start="chain", h3_mode="render", h3_creativity="bold", workflow=None, llm="local", direct=False,
                                      image_count=1, ref_videos=[])
        self.assertEqual([(pill["kind"], pill["text"]) for pill in pills.pills(pills.run_facts(state, "video", "LTX"), [])],
                         [("workflow", "LTX"), ("mode", "I2V"), ("llm", "local"), ("openh3", "OpenH3-IR: Bold"),
                          ("upscale", "Upscaled: Latent, Clean, 1.1 MP"), ("clips", "Continuous take")],
                         "OpenH3-IR right after the LLM, as what helped write the prompts")
        state.shots = [{"prompt": "a"}, {"prompt": "b", "workflow_enhanced_prompt": "b, enhanced"}]
        self.assertIn(("writer", "Prompt enhancer"), pills.run_facts(state, "video", "LTX"), "the workflow's enhancer wrote a clip's")

    def test_each_mode_from_what_a_set_keeps_however_old(self):
        def state(**made):
            return types.SimpleNamespace(**{"region": None, "compose": False, "options": None, "image_count": 0, **made})
        self.assertEqual(pills.image_mode(state()), "T2I")
        self.assertEqual(pills.image_mode(state(image_count=1)), "Edit", "a model that edits what it's given")
        self.assertEqual(pills.image_mode(state(image_count=1, options={"one_of_text2image_image2image": "image2image"})), "I2I")
        self.assertEqual(pills.image_mode(state(options={"one_of_text2image_image2image": "text2image"})), "T2I")
        self.assertEqual(pills.image_mode(state(image_count=1, options={"one_of_x": "inpaint"})), "Inpaint")
        self.assertEqual(pills.image_mode(state(image_count=1, options={"image_to_prompt": "1"})), "T2I",
                         "the picture image to prompt describes isn't edited")
        # As the Mode picker says them.
        self.assertEqual(pills.image_mode(state(image_count=2, compose=True)), "R2I")
        self.assertEqual(pills.image_mode(state(image_count=1, region={"kind": "expand"})), "Expand")
        self.assertEqual(pills.image_mode(state(image_count=1, region={"kind": "areas"})), "Inpaint")
        self.assertEqual(pills.image_mode(types.SimpleNamespace()), "T2I", "a set from before any of these were kept")

        def film(**made):
            return types.SimpleNamespace(**{"image_count": 1, "ref_videos": [], **made})
        self.assertEqual([pills.video_mode(film(image_count=0)), pills.video_mode(film()), pills.video_mode(film(image_count=3)),
                          pills.video_mode(film(ref_videos=[{}]))], ["T2V", "I2V", "R2V", "R2V"])

    def test_what_helped_follows_the_llm(self):
        state = types.SimpleNamespace(workflow=None, options={"prompt_enhancer": "1"}, llm=None, direct=True, shots=[],
                                      form={"prompt_mode": ["llm"], "llm": ["prompt_enhancer"]})
        made = pills.run_facts(state, "image", "Text")
        self.assertEqual([fact for fact in made if fact[0] in ("llm", "writer")], [("llm", "Exact prompt"), ("writer", "Prompt enhancer")],
                         "your prompt, then the workflow's enhancer")
        with mock.patch.object(pills.workflow_options, "_made_with", return_value={
                "1": {"class_type": "MiniMaxH3ImageConditioning", "inputs": {}}}):
            self.assertIn(("writer", "Prompt enhancer H3"), pills.run_facts(state, "image", "MiniMax"))
        state.options, state.form = {"image_to_prompt": "1"}, None
        self.assertIn(("writer", "I2P"), pills.run_facts(state, "image", "Edit"))
        state.options, state.llm, state.direct, state.looked = {}, "gemini", False, True
        self.assertEqual([fact for fact in pills.run_facts(state, "image", "Text") if fact[0] in ("llm", "writer")],
                         [("llm", "gemini"), ("writer", "I2P")], "the LLM, then I2P: it looked at a picture of yours")


class PickerLabelTest(unittest.TestCase):
    def test_a_workflow_is_named_as_the_picker_names_it(self):
        import json
        import tempfile
        from core import saved_workflows
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "image_Krea2_T2I__SFW_.json")
            with open(path[:-len(".json")] + ".map.json", "w", encoding="utf-8") as f:
                json.dump({"_saved_as": "image_Krea2 T2I (SFW).json", "_model": "krea2"}, f)
            self.assertEqual(saved_workflows.picker_label(path, "x"), "Krea2 T2I (SFW)", "the name it was saved under, not its file's")
            self.assertEqual(saved_workflows.map_field(path, "_model"), "krea2")
            gone = os.path.join(folder, "video_LTX_old.json")
            self.assertEqual(saved_workflows.picker_label(gone, "x"), "LTX_old", "no map: its file's name")
        self.assertEqual(saved_workflows.picker_label(None, "LTX23_I2V_T2V"), "LTX23_I2V_T2V", "the built-in one")


if __name__ == "__main__":
    unittest.main()
