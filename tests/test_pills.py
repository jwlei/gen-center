"""Pills: what a film or set was made with, and which of those tell it apart from what its prompt made besides."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import pills  # noqa: E402


def item(prompt, **made):
    return {"_sibling": pills.sibling_key("video", prompt), "_facts": pills.facts(**made)}


class PillsTest(unittest.TestCase):
    def test_what_differs_from_its_siblings_comes_first_and_is_marked(self):
        latent = item("An elf sways", workflow="Minimax_H3_R2V", upscaled="Latent, Clean, 1.1 MP", clips="image", llm="local")
        plain = item("  an ELF   sways ", workflow="Minimax_H3_R2V", clips="image", llm="local")
        wan = item("An elf sways", workflow="Wan 2.2", clips="chain", llm="local")
        alone = item("Jungle flight", workflow="Minimax_H3_R2V", llm="local")
        pills.with_pills([latent, plain, wan, alone])
        shown = lambda one: [(p["text"], p["diff"]) for p in one["pills"]]
        self.assertEqual(shown(latent), [("Minimax_H3_R2V", True), ("LLM", False), ("local", False),
                                         ("Upscaled: Latent, Clean, 1.1 MP", True), ("Separate moments", True)])
        exact = item("Jungle flight", workflow="Wan 2.2", upscaled="RTX VSR", llm="local", direct=True)
        pills.with_pills([exact, item("Jungle flight", workflow="Minimax_H3_R2V", llm="local")])
        self.assertEqual(shown(exact)[0], ("Wan 2.2", True), "the workflow is always first")
        self.assertIn(("Exact prompt", True), shown(exact), "your own prompt, word for word, instead of the LLM")
        self.assertNotIn("No upscale", [text for text, _ in shown(plain)], "no upscale isn't a pill of its own")
        self.assertEqual(shown(wan)[:3], [("Wan 2.2", True), ("LLM", False), ("local", False)])
        self.assertEqual([text for text, _ in shown(exact)[:2]], ["Wan 2.2", "Exact prompt"], "Exact prompt is second, with no LLM after it")
        self.assertTrue(all(not diff for _, diff in shown(alone)), "no siblings: nothing marked")
        self.assertNotIn("_sibling", latent, "the prompt stays on the server")
        self.assertNotIn("_facts", latent)

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
                                      start="chain", h3_mode="render", h3_creativity="bold", workflow=None, llm="local", direct=False)
        self.assertEqual(pills.run_facts(state, "video", "LTX"),
                         [("workflow", "LTX"), ("upscale", "Upscaled: Latent, Clean, 1.1 MP"), ("clips", "Continuous take"),
                          ("openh3", "OpenH3-IR: Bold"), ("prompt", "LLM"), ("llm", "local")])


if __name__ == "__main__":
    unittest.main()
