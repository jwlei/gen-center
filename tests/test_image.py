"""
The Image side: the panel in-process, starting the real pipelines.image.main as a real process,
which talks to a fake ComfyUI and a fake Gemini. Nothing costs anything.
"""
import io
import json
import re
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fakes import (OBJECT_INFO, caption, captions_reply, close, edit_image_workflow, fake_comfy, fake_gemini, fibo2_workflow, gemini_env,
                   qwen21_edit_workflow, qwen21_text_workflow, switchable_workflow, text_to_image_workflow, versions_reply)

from PIL import Image, ImageDraw

from panel import app as _all_pipelines  # noqa: F401
from panel import image as image_panel
from panel import server as webapp
from core import explicit, variety, workflow_options
from core.llm_reply import CutOff
from pipelines.image import fibo2_prompt, media, models, paths, planner
from pipelines.image.run_eta import RunEta
from pipelines.image.run_state import RunState, list_runs
from pipelines.video import paths as video_paths


def png_bytes(size=(800, 1200), color=(10, 200, 30)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class SizeTest(unittest.TestCase):
    def test_an_exact_size_wins(self):
        self.assertEqual(media.pick_size("1280x736", "1:1", "1"), (1280, 736))
        self.assertEqual(media.pick_size("1920x1080"), (1920, 1080), "what you asked for, on the model's grid or not")

    def test_listing_images_survives_a_file_deleted_during_the_scan(self):
        state = mock.Mock()
        state.shots = [{"file": "gone.png", "number": 1, "title": "Gone"},
                       {"file": "kept.png", "number": 2, "title": "Kept"}]
        with tempfile.TemporaryDirectory() as folder:
            kept = os.path.join(folder, "kept.png")
            Image.new("RGB", (10, 20)).save(kept)
            state.image_path.side_effect = lambda shot: os.path.join(folder, shot["file"])
            with self.assertLogs(image_panel.app.logger, level="WARNING") as logs:
                files = image_panel.image_files(state)
            self.assertEqual([(file["position"], file["file"]) for file in files], [(2, "kept.png")])
            self.assertIn("gone.png", logs.output[0])

    def test_output_tracks_prompt_models_per_image(self):
        state = RunState("image_20261114_120000", "A view", 3, False, 10, 20,
                         llm="local", local_model="gemma-4-12b:gemma-4-12B-it-uncensored-heretic-Q4_K_M")
        state.shots = [
            {"file": "a.png", "number": 1, "title": "a"},
            {"file": "b.png", "number": 2, "title": "b",
             "setup": {"llm": "local", "local_model": "qwen3-14b", "direct": False}},
            {"file": "c.png", "number": 3, "title": "c",
             "setup": {"llm": "local", "local_model": "gemma-4-12b", "direct": True}},
        ]
        with tempfile.TemporaryDirectory() as folder:
            for shot in state.shots:
                Image.new("RGB", (10, 20)).save(os.path.join(folder, shot["file"]))
            with mock.patch.object(state, "image_path", side_effect=lambda shot: os.path.join(folder, shot["file"])), \
                 mock.patch.object(image_panel, "shorthand", return_value="Workflow"), \
                 mock.patch.object(image_panel, "read_outcome", return_value=None), \
                 mock.patch.object(image_panel, "RunEta") as eta:
                eta.return_value.plan.return_value = {"total": 0}
                listed = image_panel.describe_run(state)
            self.assertEqual([image["prompt_llm"] for image in listed["images"]],
                             ["Gemma 4 U-H Q4_K_M", "Qwen3 14B", None])
            self.assertEqual([value for kind, value in listed["_facts"] if kind == "llm"],
                             ["Gemma 4 U-H Q4_K_M", "Qwen3 14B"])
        self.assertEqual(image_panel.prompt_llm_pill({"llm": "local"}), "local")
        self.assertEqual(image_panel.prompt_llm_pill({"llm": "gemini", "local_model": "gemma-4-12b"}), "gemini")
        self.assertEqual(image_panel.prompt_llm_pill({"llm": "local", "local_model": "gemma-4-12b"}),
                         image_panel.settings.short_name("gemma-4-12b"), "no -v: as the model pickers name it")

    def test_a_size_off_the_grid_renders_just_larger(self):
        self.assertEqual(media.render_size(1920, 1080), (1920, 1088))
        self.assertEqual(media.render_size(2560, 1440), (2560, 1440), "already on it")
        self.assertEqual(media.render_size(3840, 2160), (3840, 2160))
        self.assertEqual(media.render_size(1272, 2772), (1280, 2784), "the OnePlus 15")
        self.assertEqual(media.render_size(1360, 768, step=32), (1376, 768), "Qwen-Image 2.1 works in whole 32s")

    def test_an_edit_never_gets_a_size_its_encoder_would_wrap_around(self):
        self.assertEqual(media._reference_latent(1376, 768), (171, 96), "what put a band down the right edge of a real image")
        sizes = [(1376, 768), (800, 1200), (832, 1248)] + [(width, height) for _, width, height in media.DESKTOP_SIZES + media.PHONE_SIZES]
        for width, height in sizes:
            made = media.edit_render_size(width, height)
            self.assertEqual([side % 2 for side in media._reference_latent(*made)], [0, 0], (width, height))
            self.assertGreaterEqual(made, (width, 0), "never narrower, as it's cropped down to the size asked for")
            self.assertGreaterEqual(made[1], height)
            self.assertEqual([side % media.SIZE_STEP for side in made], [0, 0], "and still on the model's grid")
            self.assertLess(made[0] * made[1], width * height * 1.12, "with little to crop")

    def test_a_size_with_nothing_wrong_is_left_as_it_is(self):
        self.assertEqual(media.edit_render_size(1024, 1024), (1024, 1024))
        self.assertEqual(media.edit_render_size(1392, 752), (1392, 752), "what ComfyUI's own template uses")

    def test_the_screens_on_offer(self):
        offered = {(width, height) for _, width, height in media.DESKTOP_SIZES + media.PHONE_SIZES}
        self.assertLessEqual({(1920, 1080), (2560, 1440), (3840, 2160), (1272, 2772)}, offered)
        self.assertTrue(all(height > width for _, width, height in media.PHONE_SIZES), "phones stand upright")

    def test_aspect_and_megapixels_of_your_own(self):
        self.assertEqual(media.pick_size(None, "1:1", "1"), (1024, 1024))
        self.assertEqual(media.pick_size(None, "16:9", "1"), (1360, 768))
        self.assertEqual(media.pick_size(None, "9:16", "2"), (1088, 1936))

    def test_matching_the_image(self):
        source = (800, 1200)
        self.assertEqual(media.pick_size(None, media.FROM_IMAGE, media.FROM_IMAGE, source), (800, 1200), "its own resolution")
        self.assertEqual(media.pick_size(None, media.FROM_IMAGE, "1", source), (832, 1248), "its shape")
        self.assertEqual(media.pick_size(None, "1:1", media.FROM_IMAGE, source), (976, 976), "its pixel count")

    def test_the_same_as_the_image_stays_within_what_the_model_makes(self):
        width, height = media.pick_size(None, media.FROM_IMAGE, media.FROM_IMAGE, (3000, 2000), most_megapixels=1.1)
        self.assertLessEqual(width * height, 1.1 * media.PIXELS_PER_MEGAPIXEL * 1.01)
        self.assertAlmostEqual(width / height, 1.5, delta=0.02, msg="in its shape")

    def test_nothing_to_match_means_a_square_megapixel(self):
        self.assertEqual(media.pick_size(None, media.FROM_IMAGE, media.FROM_IMAGE), (1024, 1024))

    def test_a_huge_photo_is_capped(self):
        width, height = media.pick_size(None, media.FROM_IMAGE, media.FROM_IMAGE, (12000, 9000))
        self.assertLessEqual(width * height, media.MAX_MEGAPIXELS * media.PIXELS_PER_MEGAPIXEL * 1.01)

    def test_what_isnt_a_size(self):
        self.assertIsNone(media.parse_size("big"))
        self.assertIsNone(media.parse_size("10x10"), "too small to make")
        self.assertIsNone(media.parse_size("99999x1024"), "too big to make")
        self.assertIsNone(media.parse_aspect("0:9"))
        self.assertIsNone(media.parse_megapixels("99"))


class FitTest(unittest.TestCase):
    def test_the_image_comes_out_exactly_that_size(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "source.png")
            Image.new("RGB", (800, 1200)).save(source)
            with Image.open(media.fit(source, 1360, 768, os.path.join(folder, "fitted.png"))) as fitted:
                self.assertEqual(fitted.size, (1360, 768))


class TrimTest(unittest.TestCase):
    def trimmed(self, made, rendered, wanted):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "image.png")
            image = Image.new("RGB", made, (200, 0, 0))
            # The centre is blue: a crop that's off centre would take some of the red.
            image.paste((0, 0, 200), (0, 4, made[0], made[1] - 4))
            image.save(path)
            media.trim(path, rendered, wanted)
            with Image.open(path) as result:
                self.assertEqual(os.listdir(folder), ["image.png"], "no part left behind")
                return result.size, result.convert("RGB").getpixel((0, 0))

    def test_it_crops_from_the_middle_to_the_exact_size(self):
        self.assertEqual(self.trimmed((320, 288), (320, 288), (320, 280)), ((320, 280), (0, 0, 200)))

    def test_an_image_already_that_size_is_left_alone(self):
        self.assertEqual(self.trimmed((320, 288), (320, 288), (320, 288))[0], (320, 288))

    def test_a_workflow_that_set_its_own_size_is_left_alone(self):
        self.assertEqual(self.trimmed((512, 512), (320, 288), (320, 280))[0], (512, 512))


class PlannerTest(unittest.TestCase):
    def reply(self, count, title="Set", same=False):
        return json.dumps({"title": title, "versions": [{"title": f"V{i}", "prompt": "the same" if same else f"Prompt {i}"} for i in range(count)]})

    def write(self, *replies, count=3):
        with mock.patch.object(planner.llm, "_ask", side_effect=list(replies)) as call:
            return planner.write_prompts([], "a brief", count, "gemini"), call

    def test_one_request_for_the_whole_set(self):
        (title, versions), call = self.write(self.reply(15), count=15)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(title, "Set")
        self.assertEqual([v["prompt"] for v in versions], [f"Prompt {i}" for i in range(15)])

    def test_too_many_are_left_out_rather_than_asked_for_again(self):
        (_, versions), call = self.write(self.reply(5))
        self.assertEqual((len(versions), call.call_count), (3, 1))

    def test_too_few_or_the_same_are_asked_for_again_saying_what_went_wrong(self):
        (_, versions), call = self.write("not json", self.reply(3, same=True), self.reply(3))
        self.assertEqual((len(versions), call.call_count), (3, 3))
        self.assertIn("1 different prompts instead of 3", call.call_args_list[2].args[1])

    def test_what_it_did_write_beats_paying_for_nothing(self):
        (_, versions), call = self.write(self.reply(2), self.reply(1), "not json")
        self.assertEqual((len(versions), call.call_count), (2, 3))

    def test_more_than_twenty_are_written_in_even_rounds_in_the_manner_of_the_first(self):
        (title, versions), call = self.write(self.reply(13, "First"), self.reply(12, "Second").replace('"Prompt ', '"Later prompt '), count=25)
        self.assertEqual([re.search(r"exactly (\d+) versions", c.args[1]).group(1) for c in call.call_args_list], ["13", "12"])
        self.assertIn("already has 13 versions", call.call_args_list[1].args[1])
        self.assertIn("same level of detail, as this earlier one:\n    Prompt 0", call.call_args_list[1].args[1])
        self.assertEqual(title, "First")
        self.assertEqual(len({v["prompt"] for v in versions}), 25)

    def test_a_reply_cut_off_is_written_in_rounds_each_told_what_came_before(self):
        replies = {15: CutOff("cut off"), 8: self.reply(8, "First"), 6: self.reply(6)}
        asked = []

        def ask(llm, prompt, *args, **kwargs):
            want = int(re.search(r"exactly (\d+) versions", prompt).group(1))
            asked.append(want)
            reply = replies[want]
            if isinstance(reply, Exception):
                raise reply
            # Each round numbers its own from 0: the later one's prompts must still be new.
            return reply.replace('"Prompt ', f'"Round {len(asked)} prompt ')

        with mock.patch.object(planner.llm, "_ask", side_effect=ask) as call:
            title, versions = planner.write_prompts([], "a brief", 30, "local", refiner=object())
        self.assertEqual(asked, [15, 8, 8, 8, 6], "30 in even rounds of 15; halved when cut off anyway, then rounds of that size")
        self.assertEqual((title, len(versions), len({v["prompt"] for v in versions})), ("First", 30, 30))
        self.assertIn("already has 8 versions, written before these: V0; V1", call.call_args_list[2].args[1])
        self.assertIn("already has 24 versions", call.call_args_list[4].args[1])
        with mock.patch.object(planner.llm, "_ask", side_effect=CutOff("cut off")), self.assertRaisesRegex(RuntimeError, "single prompt"):
            planner.write_prompts([], "a brief", 2, "gemini")

    def test_the_words_per_prompt_set_the_length_and_the_rounds(self):
        self.assertIn("120-180 words", planner._instructions("a fox", 3, 0, words=150))
        self.assertIn("320-480 words", planner._instructions("a fox", 3, 2, compose=True, words=400))
        self.assertEqual(planner.word_range(200), (160, 240))
        self.assertIn("20-60 words", planner._instructions("a fox", 3, 1, words=400), "an edit keeps its own length")
        self.assertEqual([planner.round_size(words) for words in (40, 200, 300, 400)], [20, 20, 15, 11])
        (_, versions), call = self.write(*[self.reply(15, f"R{n}").replace('"Prompt ', f'"R{n} prompt ') for n in range(2)],
                                         count=30)
        self.assertEqual(call.call_count, 2, "200 words: 30 as 15 and 15")
        with mock.patch.object(planner.llm, "_ask", side_effect=[self.reply(10).replace('"Prompt ', f'"R{n} prompt ')
                                                                 for n in range(3)]) as call:
            planner.write_prompts([], "a brief", 30, "gemini", words=400)
        self.assertEqual(call.call_count, 3, "400 words: 30 as three rounds of 10 (11 at most each)")
        # Edits are short whatever the slider says: one request for 20.
        self.assertEqual(planner.token_estimate(20, images=1, words=400)["rounds"], 1)

    def test_the_token_estimate_counts_each_prompt_the_set_and_the_largest_request(self):
        one = planner.token_estimate(15, words=200)
        self.assertEqual((one["each"], one["written"], one["rounds"]), (290, 4350, 1))
        two = planner.token_estimate(30, words=200, explicit=True)
        self.assertEqual((two["written"], two["rounds"]), (8700, 2))
        self.assertGreater(two["context"], one["context"], "the later round is told the titles and shown a prompt")
        self.assertLess(two["context"], 16384, "it fits the local model's context")
        self.assertGreaterEqual(planner.token_estimate(1, images=2, compose=True)["context"] - planner.token_estimate(1, images=1, compose=True)["context"], planner.IMAGE_TOKENS)

    def test_nothing_usable_says_so(self):
        with self.assertRaisesRegex(RuntimeError, "usable prompts"):
            self.write("no", "no", "no")

    def test_editing_and_making_get_different_instructions(self):
        edit = planner._instructions("different outfits", 15, 1)
        self.assertIn("edit that image", edit)
        self.assertIn("same person", edit)
        self.assertIn("15 different versions", edit)
        self.assertIn("clearly different", edit)
        make = planner._instructions("a lighthouse", 1, 0)
        self.assertIn("each has to say everything", make)
        self.assertNotIn("edit that image", make)
        self.assertNotIn("clearly different", make, "one image has nothing to differ from")
        self.assertIn("Picture 2", planner._instructions("x", 2, 2, models.QWEN_IMAGE_EDIT))
        self.assertIn("<image2>", planner._instructions("x", 2, 2, models.QWEN_IMAGE_21_EDIT), "Qwen-Image 2.1 names them its own way")

    def test_the_rules_kokon_tested(self):
        edit = planner._instructions("different outfits", 3, 1, models.QWEN_IMAGE_21_EDIT)
        self.assertIn("Start with the operation", edit)
        self.assertIn("Never describe what stays", edit)
        self.assertIn("Keep everything else in the image unchanged.", edit)
        self.assertNotIn("navy", edit, "an example in the instructions turns up in the prompts")
        compose = planner._instructions("her in Paris", 2, 2, models.QWEN_IMAGE_21_EDIT, compose=True)
        self.assertIn("references", compose)
        self.assertIn("Never ask to keep an image unchanged", compose)
        self.assertNotIn("Keep everything else in the image unchanged.", compose, "that turns a new picture into an edit of image 1")
        self.assertIn("transparent background", planner._instructions("a fox", 1, 0, models.QWEN_IMAGE_21, transparent=True))


class ModelLimitTest(unittest.TestCase):
    def test_fibo2_stays_near_the_megapixel_it_was_trained_at(self):
        self.assertIsNone(models.size_problem(models.FIBO2, 1024, 1024))
        self.assertIsNone(models.size_problem(models.FIBO2, 1248, 832), "Bria's own 3:2")
        self.assertIn("1.1 megapixels", models.size_problem(models.FIBO2, 1920, 1080))
        self.assertIsNotNone(models.size_problem(models.FIBO2, 1272, 2772), "nor a phone")

    def test_krea2_goes_up_to_2k(self):
        self.assertIsNone(models.size_problem(models.KREA2, 2048, 2048))
        self.assertIsNone(models.size_problem(models.KREA2, 2560, 1440))
        self.assertIn("4.2 megapixels", models.size_problem(models.KREA2, 3840, 2160))

    def test_every_model_has_a_limit_and_the_defaults_fit_in_it(self):
        self.assertIn("4.2 megapixels", models.size_problem(models.MOSS_IMAGE, 3840, 2160))
        self.assertIsNone(models.size_problem(models.QWEN_IMAGE_EDIT, 2560, 2560))
        self.assertIsNotNone(models.size_problem(models.QWEN_IMAGE_EDIT, 3840, 2160))
        self.assertIsNone(models.size_problem(models.MINIMAX_H3_IMAGE, 5472, 3648), "20 MP")
        self.assertIsNotNone(models.size_problem(models.MINIMAX_H3_IMAGE, 6000, 4000))
        self.assertIsNone(models.size_problem(None, 3840, 2160), "a workflow that isn't known has none")
        for model, start in models.DEFAULT_MEGAPIXELS.items():
            self.assertLessEqual(start, models.MOST_MEGAPIXELS[model])
        self.assertEqual((models.DEFAULT_MEGAPIXELS[models.MOSS_IMAGE], models.DEFAULT_MEGAPIXELS[models.QWEN_IMAGE_EDIT], models.DEFAULT_MEGAPIXELS[models.MINIMAX_H3_IMAGE]), (2, 1, 16))

    def test_the_llm_writes_so_many_fibo2_captions(self):
        self.assertIsNone(models.count_problem(models.FIBO2, 30, False))
        self.assertIn("at most 30", models.count_problem(models.FIBO2, 31, False))
        self.assertIsNone(models.count_problem(models.FIBO2, 100, True), "your own prompt needs no writing")
        self.assertIsNone(models.count_problem(models.KREA2, 100, False))


class Fibo2PromptTest(unittest.TestCase):
    def test_a_caption_goes_in_compact(self):
        self.assertEqual(fibo2_prompt.tidy('```json\n{"short_description": "x", "edit_instruction": "Change it."}\n```', True),
                         '{"short_description":"x","edit_instruction":"Change it."}')

    def test_what_isnt_the_caption_asked_for_is_refused(self):
        self.assertIsNone(fibo2_prompt.tidy("Change her coat to red.", True), "prose")
        self.assertIsNone(fibo2_prompt.tidy('{"short_description": "x"}', True), "an edit with no instruction")
        self.assertIsNone(fibo2_prompt.tidy('{"objects": []}', False), "no description")
        self.assertIsNone(fibo2_prompt.tidy('["x"]', False))

    def test_an_image_from_text_has_nothing_to_edit(self):
        self.assertEqual(fibo2_prompt.tidy('{"short_description": "x", "edit_instruction": "Add it."}', False), '{"short_description":"x"}')

    def test_the_llm_is_told_to_write_captions(self):
        edit = planner._instructions("different outfits", 15, 1, models.FIBO2)
        self.assertIn("ONE JSON object", edit)
        self.assertIn("edit_instruction", edit)
        self.assertIn('Never write "keep X unchanged"', edit, "which made Fibo 2.0 redraw everything in Bria's tests")
        self.assertIn("<image_2>", planner._instructions("x", 2, 2, models.FIBO2))
        self.assertNotIn("edit_instruction: also required", planner._instructions("a lighthouse", 3, 0, models.FIBO2))

    def test_prose_is_asked_for_again(self):
        prose = json.dumps({"title": "Set", "versions": [{"title": "One", "prompt": "Change her coat to red."}]})
        good = json.dumps({"title": "Set", "versions": [{"title": "One", "prompt": caption(1)}]})
        with mock.patch.object(planner.llm, "_ask", side_effect=[prose, good]) as call:
            _, versions = planner.write_prompts([b"image"], "a red coat", 1, "gemini", models.FIBO2)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(json.loads(versions[0]["prompt"])["edit_instruction"], "Change her outfit to look number 1.")


    def test_a_local_model_writes_fibo2_captions_as_objects(self):
        # Held to the caption's own shape, rather than JSON written inside a string, which it got wrong every time.
        refiner = mock.Mock()
        refiner.plan.return_value = json.dumps({"title": "Faces", "versions": [
            {"title": f"Look {n}", "prompt": json.loads(caption(n))} for n in range(1, 6)]})
        title, versions = planner.write_prompts([b"image", b"face"], "put the face of 2 on 1", 5, "local", models.FIBO2, refiner=refiner)
        schema = refiner.plan.call_args.args[1]
        prompt_shape = schema["properties"]["versions"]["items"]["properties"]["prompt"]
        self.assertEqual(prompt_shape["type"], "object", "the caption is asked for as an object")
        self.assertIn("edit_instruction", prompt_shape["required"], "an edit must say what it changes")
        self.assertEqual((title, len(versions)), ("Faces", 5))
        self.assertEqual(len({version["prompt"] for version in versions}), 5, "five different prompts, one per image")
        self.assertEqual(json.loads(versions[0]["prompt"])["edit_instruction"], "Change her outfit to look number 1.")
        # Any other model, or Gemini on Fibo 2.0, keeps writing them as text.
        with mock.patch.object(planner.llm, "_ask", return_value=json.dumps({"title": "Set", "versions": [{"title": "One", "prompt": caption(1)}]})) as call:
            planner.write_prompts([b"image"], "a red coat", 1, "gemini", models.FIBO2)
        self.assertIs(call.call_args.args[3], planner.VERSIONS_SCHEMA)

    def test_a_reply_that_is_not_json_is_asked_for_again(self):
        refiner = mock.Mock()
        good = json.dumps({"title": "Set", "versions": [{"title": "One", "prompt": json.loads(caption(1))}]})
        refiner.plan.side_effect = ["not json at all", good]
        _, versions = planner.write_prompts([b"image"], "a red coat", 1, "local", models.FIBO2, refiner=refiner)
        self.assertEqual((refiner.plan.call_count, len(versions)), (2, 1))


class EtaTest(unittest.TestCase):
    def workflow(self, folder, name, model):
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"1": {"class_type": "UNETLoader", "inputs": {"unet_name": f"Krea2\\{model}.safetensors"}},
                       "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "4x.safetensors"}},
                       "3": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}}}, f)
        return path

    def test_a_render_is_timed_by_model_workflow_options_and_size(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "timings.json")
            simple = self.workflow(folder, "simple.json", "krea2_turbo")
            argv = lambda *more: ["--count", "1", "--direct", "--size", "1024x1024", *more]
            first = RunEta(argv(), {"COMFYUI_WORKFLOW": simple}, path)
            self.assertEqual(first.render_keys, ["krea2_turbo | simple | as saved | 1024x1024", "krea2_turbo | simple | as saved",
                                                 "krea2_turbo | simple", "krea2_turbo"], "the model by its file, not the upscaler or VAE")
            first.stage(1, 1, "Images")
            first.image(1, 1)
            first.image_started -= 20 * first.size_share
            first.finish()

            again = RunEta(argv(), {"COMFYUI_WORKFLOW": simple}, path)
            self.assertAlmostEqual(again.plan()["image_render"], 20, delta=1)
            self.assertTrue(again.plan()["timed"])
            # A setting not timed yet starts from the same workflow's time, and learns its own.
            steps = RunEta(argv("--option", "steps=12"), {"COMFYUI_WORKFLOW": simple}, path)
            self.assertEqual(steps.render_keys[0], "krea2_turbo | simple | steps=12 | 1024x1024")
            self.assertAlmostEqual(steps.plan()["image_render"], 20, delta=1)
            self.assertFalse(steps.plan()["timed"])
            # A new workflow on the same model starts from the model's time, with nothing set up for it.
            renamed = self.workflow(folder, "brand_new.json", "krea2_turbo")
            self.assertAlmostEqual(RunEta(argv(), {"COMFYUI_WORKFLOW": renamed}, path).plan()["image_render"], 20, delta=1)
            # A new model has nothing to go by but the default, until its first image.
            other = self.workflow(folder, "other.json", "qwen_image")
            self.assertEqual(RunEta(argv(), {"COMFYUI_WORKFLOW": other}, path).plan()["image_render"], 120)

    def test_prompts_are_timed_per_llm_and_count(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "timings.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"steps": {"Prompts | gemini | 3 images": 12, "Prompts | per prompt": 6}}, f)
            prompts = lambda *argv: RunEta(["--plan-only", *argv], {}, path).plan()["total"]
            self.assertEqual(prompts("--llm", "gemini", "--count", "3"), 12, "as timed for this many")
            self.assertEqual(prompts("--llm", "gemini", "--count", "5"), 30, "nothing timed for gemini at 5 yet: any LLM's per prompt, times five")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"steps": {"Prompts | gemini | per prompt": 30, "Prompts | per prompt": 6}}, f)
            self.assertEqual(prompts("--llm", "gemini", "--count", "3"), 90, "gemini's own time per prompt, times three")

    def test_each_workflow_learns_its_own_time(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "timings.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"steps": {"Prompts | per prompt": 10}, "renders": {"fast": 10, "slow": 200}}, f)
            count = ["--count", "3"]
            self.assertEqual(RunEta(count, {"COMFYUI_WORKFLOW": "x/fast.json"}, path).plan()["total"], 30 + 30)
            self.assertEqual(RunEta(count, {"COMFYUI_WORKFLOW": "x/slow.json"}, path).plan()["total"], 30 + 600)
            self.assertEqual(RunEta([*count, "--direct"], {"COMFYUI_WORKFLOW": "x/fast.json"}, path).plan()["total"], 30, "no LLM, no prompts step")
            self.assertEqual(RunEta([*count, "--direct", "--megapixels", "2"], {"COMFYUI_WORKFLOW": "x/fast.json"}, path).plan()["total"], 60, "twice the pixels")
            self.assertEqual(RunEta([*count, "--direct", "--size", "2048x1024"], {"COMFYUI_WORKFLOW": "x/fast.json"}, path).plan()["total"], 60)


class SizeFlagsTest(unittest.TestCase):
    def test_nothing_to_go_by_is_square_at_one_megapixel(self):
        from panel.image import size_flags
        self.assertEqual(size_flags({"aspect": "custom", "size": ""}), (["--aspect", "1:1", "--megapixels", "1.0"], None))
        self.assertIsNotNone(size_flags({"aspect": "custom", "size": "huge"})[1], "something typed that isn't a size is still refused")
        self.assertEqual(size_flags({"aspect": "custom", "size": "1920x1080"}), (["--size", "1920x1080"], None))
        self.assertEqual(media.pick_size(None, "image", "image", None), (1024, 1024), "the same as an image not given: square, one megapixel")


class StopAfterTest(unittest.TestCase):
    def test_the_set_stops_after_the_image_being_made_and_keeps_the_rest_to_continue(self):
        from core import batch_stop
        from pipelines.image import main as image_main
        batch_stop.clear()
        self.addCleanup(batch_stop.clear)
        state = mock.Mock(shots=[{"title": f"Version {n}"} for n in range(1, 4)])

        def render_image(state, comfy, shot, images):
            batch_stop.request()  # Pressed while the first is being made
            return f"{shot['title']}.png"

        with mock.patch.object(image_main, "upload_images", return_value=[]), mock.patch.object(image_main, "render_image", render_image):
            self.assertEqual(image_main.render_images(state, None), 0)
        self.assertEqual([bool(shot.get("file")) for shot in state.shots], [True, False, False])


class PromptSourceTest(unittest.TestCase):
    def test_comparison_plan_has_one_prompt_shared_seed_and_fixed_added_loras(self):
        from core import lora_tests
        from pipelines.image import main
        values = [{"lora": "1", "lora_name": name, "lora_strength": strength}
                  for name in ["krea_a.safetensors", "krea_b.safetensors"] for strength in ["1", "2"]]
        stack = json.dumps([{"on": True, "name": "krea_fixed.safetensors", "strength": "0.5"}])
        args = main.parse_args(["same prompt", "--direct", "--seed", "7", "--option", "additional_loras=" + stack])
        comfy = mock.Mock()
        comfy.model.return_value = None
        comfy.takes.return_value = {"min_images": 0, "max_images": 0}
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(paths, "RUNS_DIR", folder), mock.patch.object(paths, "OUTPUT_DIR", folder), \
             mock.patch.dict(os.environ, {lora_tests.ENV: json.dumps(values), "COMFYUI_WORKFLOW": ""}), \
             mock.patch.object(main, "ImageClient", return_value=comfy), \
             mock.patch.object(main.titles, "titled", return_value="Comparison"):
            state = main.plan_run(args, main.STAGES)
        self.assertEqual(state.count, 4)
        self.assertEqual({shot["prompt"] for shot in state.shots}, {"same prompt"})
        self.assertEqual({shot["seed"] for shot in state.shots}, {7})
        self.assertEqual(state.options["additional_loras"], stack)

    def test_a_workflow_comparison_plans_one_prompt_through_each_workflow(self):
        from core import workflow_tests
        from pipelines.image import main
        values = [{"kind": "t2i", "workflow": f"/w/image_{name}.json", "label": name} for name in ("Krea2", "Moss")]
        args = main.parse_args(["same prompt", "--direct", "--seed", "7"])
        comfy = mock.Mock()
        comfy.model.return_value = None
        comfy.takes.return_value = {"min_images": 0, "max_images": 0}
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(paths, "RUNS_DIR", folder), mock.patch.object(paths, "OUTPUT_DIR", folder), \
             mock.patch.dict(os.environ, {workflow_tests.ENV: json.dumps(values), "COMFYUI_WORKFLOW": "/w/image_Krea2.json"}), \
             mock.patch.object(main, "ImageClient", return_value=comfy), \
             mock.patch.object(main.titles, "titled", return_value="Comparison"):
            state = main.plan_run(args, main.STAGES)
        self.assertEqual(state.count, 2)
        self.assertEqual([shot["title"] for shot in state.shots], ["Krea2", "Moss"])
        self.assertEqual({(shot["prompt"], shot["seed"]) for shot in state.shots}, {("same prompt", 7)})
        self.assertIn("_all_t2i", state.output_name, "named for what it compares")
        self.assertEqual(workflow_tests.pill(state.shots), "All T2I workflows")

    def test_an_llm_comparison_has_each_model_write_the_brief_on_one_seed(self):
        from core import llm_tests
        from pipelines.image import main
        values = [{"llm": "gemini", "local_model": None, "label": "Gemini"},
                  {"llm": "local", "local_model": "gemma-4-12b", "label": "Gemma 4 H Q4_K_M"},
                  {"llm": "local", "local_model": "qwen3-14b", "label": "Qwen3 14B"}]
        args = main.parse_args(["a lighthouse", "--llm", "local", "--local-model", "gemma-4-12b", "--seed", "7"])
        comfy = mock.Mock(url="http://comfy")
        comfy.model.return_value = None
        comfy.takes.return_value = {"min_images": 0, "max_images": 0}
        asked = []

        def write(images, brief, count, llm, model, refiner=None, **rest):
            asked.append((llm, refiner.model_id if refiner else None, count))
            if refiner and refiner.model_id == "qwen3-14b":
                raise RuntimeError("it ran out of tokens")
            return "Lighthouse", [{"title": "Version 1", "prompt": f"written by {refiner.model_id if refiner else llm}"}]

        class Refiner:
            def __init__(self, url, require_compiler=False, model_id=None, vision=False):
                self.model_id = model_id

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch.object(paths, "RUNS_DIR", folder), mock.patch.object(paths, "OUTPUT_DIR", folder), \
             mock.patch.dict(os.environ, {llm_tests.ENV: json.dumps(values), "COMFYUI_WORKFLOW": ""}), \
             mock.patch.object(main, "ImageClient", return_value=comfy), \
             mock.patch.object(main.h3_refiner, "Refiner", Refiner), \
             mock.patch.object(main.planner, "llm_configured", return_value=True), \
             mock.patch.object(main.image_planner, "write_prompts", side_effect=write), \
             mock.patch.object(main.titles, "titled", return_value="Lighthouse"):
            state = main.plan_run(args, main.STAGES)
        self.assertEqual(asked, [("gemini", None, 1), ("local", "gemma-4-12b", 1), ("local", "qwen3-14b", 1)], "each writes one")
        self.assertEqual([(shot["title"], shot["prompt"]) for shot in state.shots],
                         [("Gemini", "written by gemini"), ("Gemma 4 H Q4_K_M", "written by gemma-4-12b")],
                         "one that fails costs its own image")
        self.assertEqual({shot["seed"] for shot in state.shots}, {7}, "one seed for all")
        self.assertEqual(llm_tests.pill(state.shots), "All LLMs")

    def test_each_image_of_a_workflow_comparison_renders_through_its_own_workflow(self):
        from pipelines.image import main
        state = RunState.new("same prompt", 2, True, 512, 512, workflow="/w/image_Krea2.json")
        lora = {"lora": "1", "lora_name": "krea_a.safetensors", "lora_strength": "1"}
        state.shots = [{"number": number, "title": label, "prompt": "same prompt", "seed": 7, "file": None,
                        "workflow_test": {"kind": "t2i", "workflow": f"/w/image_{label}.json", "label": label}}
                       for number, label in ((1, "Krea2"), (2, "Moss"))]
        state.shots[0]["lora_test"] = lora
        clients = {}

        def client(options, workflow_path=None):
            clients[workflow_path] = options
            if workflow_path.endswith("Moss.json"):
                raise RuntimeError("its map is missing")
            return mock.Mock(name=workflow_path)
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(paths, "RUNS_DIR", folder), \
             mock.patch.object(main, "ImageClient", side_effect=client), \
             mock.patch.object(main, "upload_images", return_value=[]), \
             mock.patch.object(main, "render_image", return_value=os.path.join(folder, "a.png")) as render:
            failed = main.render_images(state, mock.Mock())
        self.assertEqual(clients, {"/w/image_Krea2.json": {}, "/w/image_Moss.json": {}}, "each at its own defaults")
        self.assertEqual(failed, 1, "a workflow that can't load costs its own image")
        self.assertEqual(render.call_count, 1)
        self.assertEqual(state.shots[0]["setup"]["workflow"], "/w/image_Krea2.json", "it knows the workflow that made it")
        self.assertEqual(state.shots[0]["setup"]["options"], lora, "and the LoRA it compared")

    def test_comparison_retry_keeps_its_seed_and_applies_only_first_lora_override(self):
        from pipelines.image import main
        variation = {"lora": "1", "lora_name": "krea_test.safetensors", "lora_strength": "0.5"}
        shot = {"title": "Test", "prompt": "unchanged", "seed": 7, "lora_test": variation}
        state = mock.Mock(region=None, width=512, height=512, source_seeds=[], options={"additional_loras": "[]"},
                          output_dir="unused", transparent=False)
        state.file_stem.return_value = "test"
        comfy = mock.Mock(enhanced=None)
        comfy.render_size.return_value = (512, 512)
        comfy.render_image.return_value = "test.png"
        with mock.patch.object(media, "image_problem", side_effect=["retry", None]), mock.patch.object(media, "trim"):
            self.assertEqual(main.render_image(state, comfy, shot, []), "test.png")
        self.assertEqual([call.args[-1] for call in comfy.render_image.call_args_list], [7, 7])
        comfy.set_options.assert_called_once_with({"additional_loras": "[]", **variation})

    def test_comparison_lora_comfyui_no_longer_has_fails_only_its_image(self):
        from pipelines.image import main
        shot = {"title": "Test", "prompt": "unchanged", "seed": 7,
                "lora_test": {"lora": "1", "lora_name": "Krea2\\old.safetensors", "lora_strength": "0.5"}}
        state = mock.Mock(region=None, width=512, height=512, source_seeds=[], options={}, output_dir="unused", transparent=False)
        state.file_stem.return_value = "test"
        comfy = mock.Mock()
        comfy.render_size.return_value = (512, 512)
        comfy.set_options.side_effect = RuntimeError("LoRA is one of Krea2_new.safetensors.")
        self.assertIsNone(main.render_image(state, comfy, shot, []))
        comfy.render_image.assert_not_called()

    def test_reopening_restores_workflow_writer_not_internal_direct_flag(self):
        state = RunState.new("a lighthouse", 2, True, 1024, 1024)
        state.options = {"prompt_enhancer": "1"}
        state.form = {"prompt_mode": ["llm"], "llm": ["prompt_enhancer"]}
        with mock.patch.object(image_panel, "saved_workflows", return_value=[]):
            settings = image_panel.settings_of(state)
        self.assertFalse(settings["direct"])
        self.assertEqual(settings["llm"], "prompt_enhancer")
        self.assertTrue(state.direct, "the execution flag stays unchanged")
        state.form = None
        with mock.patch.object(image_panel, "saved_workflows", return_value=[]):
            self.assertEqual(image_panel.settings_of(state)["llm"], "prompt_enhancer", "older runs keep their writer too")

    def test_reviewed_enhancer_reopens_with_original_writer_but_exact_stays_exact(self):
        state = RunState.new("a lighthouse", 2, True, 1024, 1024)
        state.options = {"prompt_enhancer": "0"}
        state.form = {"prompt_mode": ["llm"], "llm": ["prompt_enhancer"], "review": ["1"]}
        with mock.patch.object(image_panel, "saved_workflows", return_value=[]):
            settings = image_panel.settings_of(state)
            self.assertFalse(settings["direct"])
            self.assertEqual(settings["llm"], "prompt_enhancer")
            state.form = {"prompt_mode": ["direct"], "llm": ["prompt_enhancer"]}
            self.assertTrue(image_panel.settings_of(state)["direct"], "a hidden, unselected writer isn't used")


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.comfy = fake_comfy(self.temp)
        self.addCleanup(close, self.comfy)
        self.llm = fake_gemini()
        self.llm.reply = versions_reply()
        self.addCleanup(close, self.llm)
        patcher = mock.patch.dict(os.environ, {
            "COMFYUI_URL": self.comfy.url, **gemini_env(self.llm)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.comfy.saved = {"image_text.json": text_to_image_workflow(), "image_edit.json": edit_image_workflow(), "Fibo2_test.json": fibo2_workflow()}
        self.comfy.object_info = OBJECT_INFO
        webapp._comfyui_cache["at"] = 0.0
        webapp._runs_cache["at"] = 0.0
        webapp._saved_workflows_cache["at"] = 0.0
        if os.path.exists(webapp.IMAGE_TIMINGS):
            os.remove(webapp.IMAGE_TIMINGS)
        self.client = webapp.app.test_client()
        self.addCleanup(self.clear_everything)

    def clear_everything(self):
        webapp.stop_run()
        self.wait_idle()
        errors = {lane: queue.persistence_error for lane, queue in webapp.QUEUES.items() if queue.persistence_error}
        for queue in webapp.QUEUES.values():
            # Reported below, but reset so one test's broken queue doesn't fail every later one.
            queue.items, queue.held, queue.results, queue.persistence_error = [], False, [], None
            queue._save()
        for folder in (paths.RUNS_DIR, paths.OUTPUT_DIR, video_paths.INPUTS_DIR):
            shutil.rmtree(folder, ignore_errors=True)
        self.assertEqual(errors, {}, "the test left a queue unable to save")

    def queue_id(self):
        """A job number from the queue itself: a made-up one could match a real job already in Finished."""
        with webapp.run_queue.lock:
            webapp.run_queue.next_id += 1
            return webapp.run_queue.next_id - 1

    def wait_idle(self):
        deadline = time.time() + 90
        while time.time() < deadline:
            webapp.run_queue.pending()
            # A job waiting its turn counts too (an automatic retry while ComfyUI is cleared), unless the queue is held.
            waiting = not webapp.run_queue.held and any(not item.get("later") for item in webapp.run_queue.items)
            if webapp.job.idle and not webapp.run_queue.current and not waiting:
                return
            time.sleep(0.05)
        self.fail(f"Timed out. Log: {[l['text'] for l in webapp.job.lines][-15:]}")

    def generate(self, image=False, **fields):
        form = {"prompt": "different outfits", "count": "3", "llm": "gemini", "aspect": "1:1", "megapixels": "1", **fields}
        if image:
            form["image"] = (io.BytesIO(png_bytes()), "woman.png")
        return self.client.post("/generate/image", data={k: v for k, v in form.items() if v is not None}, content_type="multipart/form-data")

    def make(self, image=False, **fields):
        reply = self.generate(image, **fields)
        self.assertTrue(reply.get_json().get("ok"), reply.get_json())
        self.wait_idle()
        return reply.get_json()

    def test_edit_pending_image_restores_inputs_and_replaces_job(self):
        response = self.generate(image=True, start_later="1", prompt="original")
        self.assertTrue(response.get_json()["ok"], response.get_json())
        original = webapp.run_queue.items[0]
        edit = self.client.post(f"/queue/run/edit/{original['id']}").get_json()
        self.assertTrue(edit["ok"], edit)
        self.assertEqual(edit["form"]["prompt"], ["original"])
        self.assertEqual(edit["files"], ["image"])
        with self.client.get(f"/queue/run/edit/{original['id']}/file/image", headers={"X-Queue-Edit-Token": edit["token"]}) as source:
            self.assertEqual(source.status_code, 200)
            self.assertTrue(source.get_data().startswith(b"\x89PNG"))
        webapp.run_queue.hold()
        response = self.generate(image=True, prompt="changed", queue_edit_id=str(original["id"]), queue_edit_token=edit["token"])
        self.assertTrue(response.get_json()["ok"], response.get_json())
        self.assertEqual(len(webapp.run_queue.items), 1)
        self.assertEqual(webapp.run_queue.items[0]["id"], original["id"])
        self.assertEqual(webapp.run_queue.items[0]["prompt"], "changed")
        self.assertNotIn("later", webapp.run_queue.items[0])

    def status(self):
        webapp._runs_cache["at"] = 0.0
        return self.client.get("/api/status").get_json()

    def only_run(self):
        runs = list_runs()
        self.assertEqual(len(runs), 1, [l["text"] for l in webapp.job.lines][-15:])
        return runs[0]

    def inputs(self, prompt, kind):
        return next(node["inputs"] for node in prompt["prompt"].values() if node["class_type"] == kind)

    def sent_prompt(self, prompt):
        return self.inputs(prompt, "PrimitiveStringMultiline")["value"] if any(
            node["class_type"] == "PrimitiveStringMultiline" for node in prompt["prompt"].values()) else next(
            node["inputs"]["prompt"] for node in prompt["prompt"].values() if node["class_type"] == "TextEncodeQwenImageEditPlus" and node["inputs"]["prompt"])

    # --- Which kind of run ---

    def test_text_alone_makes_images_from_text(self):
        self.make()
        run = self.only_run()
        self.assertTrue(run.finished, [l["text"] for l in webapp.job.lines][-15:])
        self.assertEqual(os.path.basename(run.workflow), "image_text.json")
        self.assertEqual(run.title, "Three Looks")
        self.assertEqual(self.comfy.uploads, [], "no image to give it")
        self.assertEqual([self.sent_prompt(p) for p in self.comfy.prompts], [f"Change to look number {n}." for n in (1, 2, 3)])
        self.assertTrue(all("text" in part for part in self.llm.requests[0]["parts"]), "the LLM has no image either")
        self.assertIn("each has to say everything", self.llm.requests[0]["parts"][0]["text"])
        for shot in run.shots:
            self.assertTrue(os.path.exists(run.image_path(shot)))
        self.assertTrue(run.output_dir.startswith(paths.OUTPUT_DIR))
        self.assertEqual(os.path.basename(run.output_dir), "Three_Looks_text")

    def test_an_image_edits_it(self):
        self.make(image=True, aspect="image", megapixels="1")
        run = self.only_run()
        self.assertEqual(os.path.basename(run.workflow), "image_edit.json")
        self.assertIn("image", self.llm.requests[0]["parts"][0], "the LLM sees what it's editing")
        self.assertIn("edit that image", self.llm.requests[0]["parts"][1]["text"])
        self.assertEqual(len(self.comfy.uploads), 1, "uploaded once, however many are made from it")
        self.assertEqual(self.inputs(self.comfy.prompts[0], "LoadImage")["image"], "uploaded.png")
        self.assertEqual([self.sent_prompt(p) for p in self.comfy.prompts], [f"Change to look number {n}." for n in (1, 2, 3)])
        self.assertEqual(len(self.comfy.prompts), 3)

    def test_nothing_reaches_comfyuis_output_folder(self):
        self.make()
        kinds = [node["class_type"] for node in self.comfy.prompts[0]["prompt"].values()]
        self.assertIn("PreviewImage", kinds)
        self.assertFalse({"SaveImage", "SaveImageAdvanced"} & set(kinds))

    def test_each_image_gets_a_new_seed(self):
        self.make()
        seeds = [self.inputs(p, "KSampler")["seed"] for p in self.comfy.prompts]
        self.assertEqual(len(set(seeds)), 3)

    def test_a_chosen_seed_counts_up_and_shows_in_the_set(self):
        self.assertEqual(self.generate(seed="12x").status_code, 400)
        self.make(seed="100")
        self.assertEqual([self.inputs(p, "KSampler")["seed"] for p in self.comfy.prompts], [100, 101, 102])
        run = self.only_run()
        shots = self.client.get(f"/image-runs/{run.id}").get_json()["shots"]
        self.assertEqual([(shot["seed"], shot["used_seed"]) for shot in shots], [(100, 100), (101, 101), (102, 102)])
        prompts = [shot["prompt"] for shot in shots]
        reply = self.client.post(f"/image-runs/{run.id}/shots", json={"prompts": prompts, "seeds": ["7", None, "x"]})
        self.assertEqual(reply.status_code, 400)
        self.assertTrue(self.client.post(f"/image-runs/{run.id}/shots", json={"prompts": prompts, "seeds": ["7", None, "102"]}).get_json()["ok"])
        self.assertEqual([shot["seed"] for shot in self.client.get(f"/image-runs/{run.id}").get_json()["shots"]], [7, None, 102])

    def test_a_workflow_can_be_chosen(self):
        self.assertEqual(self.generate(workflow="image_edit.json").status_code, 400, "it can't run without an image")
        self.assertEqual(self.generate(image=True, workflow="image_text.json").status_code, 400, "and this one has nowhere to put one")
        self.assertEqual(self.generate(workflow="nowhere.json").status_code, 400)

    # --- Whose prompts ---

    def test_a_direct_prompt_goes_in_word_for_word_with_no_llm(self):
        self.make(prompt="Exactly these words", prompt_mode="direct", count="4", llm=None)
        run = self.only_run()
        self.assertEqual(self.llm.requests, [])
        self.assertEqual([self.sent_prompt(p) for p in self.comfy.prompts], ["Exactly these words"] * 4)
        self.assertEqual(len({self.inputs(p, "KSampler")["seed"] for p in self.comfy.prompts}), 4)
        self.assertTrue(run.direct)
        self.assertEqual(run.title, "Exactly these words")

    def test_review_change_a_prompt_then_make_them(self):
        self.make(review="1")
        status = self.status()
        self.assertEqual(status["returncode"], 0, status["lines"])
        self.assertEqual(self.comfy.prompts, [], "reviewing first makes nothing")
        run = self.only_run()
        self.assertEqual([r["id"] for r in status["stopped_runs"]], [run.id])
        self.assertIn("Prompts ready", status["stopped_runs"][0]["detail"])
        self.assertTrue(status["stopped_runs"][0]["when"], "its date is its own, for the box to give it a line")
        self.assertNotIn(status["stopped_runs"][0]["when"], status["stopped_runs"][0]["detail"])
        detail = self.client.get(f"/image-runs/{run.id}").get_json()
        self.assertTrue(detail["is_image"])
        prompts = [shot["prompt"] for shot in detail["shots"]]
        prompts[1] = "My own wording."
        self.assertTrue(self.client.post(f"/image-runs/{run.id}/shots", json={"prompts": prompts}).get_json()["ok"])
        self.assertEqual(self.client.post(f"/image-runs/{run.id}/shots", json={"prompts": ["too few"]}).status_code, 400)
        self.assertTrue(self.client.post(f"/runs/{run.id}/continue").get_json()["ok"])
        self.wait_idle()
        self.assertEqual(self.sent_prompt(self.comfy.prompts[1]), "My own wording.")
        self.assertTrue(self.only_run().finished)
        self.assertEqual(len(self.llm.requests), 1)

    def test_a_continuation_queued_before_its_box_said_more_is_described_from_its_run(self):
        self.make(review="1")
        run = self.only_run()
        for old, end in (("Continue", ""), ("Redo image 1", " · redo image 1")):
            item = {"id": self.queue_id(), "pipeline": "image", "label": "Old", "detail": old, "resume": run.id, "argv": ["x"], "later": True}
            with webapp.run_queue.lock:
                webapp.run_queue.items.append(item)
            try:
                shown = next(i for i in webapp.run_queue.snapshot()["items"] if i["id"] == item["id"])
            finally:
                with webapp.run_queue.lock:
                    webapp.run_queue.items.remove(item)
            self.assertTrue(shown["detail"].startswith(f"{len(run.shots)} image"), shown["detail"])
            self.assertTrue(shown["detail"].endswith(end) and "Continue" not in shown["detail"], shown["detail"])

    def test_pending_continuation_can_edit_prompts_without_duplicate_jobs(self):
        self.make(review="1")
        run = self.only_run()
        item = {"id": self.queue_id(), "pipeline": "image", "label": "Continue", "resume": run.id, "argv": ["x"], "later": True}
        with webapp.run_queue.lock:
            webapp.run_queue.items.append(item)
        detail = self.client.get(f"/image-runs/{run.id}").get_json()
        self.assertFalse(detail["busy"])
        self.assertTrue(detail["pending"])
        prompts = [shot["prompt"] for shot in detail["shots"]]
        prompts[0] = "A revised image."
        self.assertTrue(self.client.post(f"/image-runs/{run.id}/shots", json={"prompts": prompts}).get_json()["ok"])
        self.assertEqual(RunState.load(run.id).shots[0]["prompt"], prompts[0])
        self.assertEqual(self.client.post(f"/runs/{run.id}/continue").status_code, 409)
        self.assertEqual(self.client.post(f"/image-runs/{run.id}/delete/1").status_code, 409)
        with webapp.run_queue.lock:
            item.pop("later")
            webapp.run_queue.held = True
        self.assertTrue(self.client.get(f"/image-runs/{run.id}").get_json()["busy"])
        self.assertEqual(self.client.post(f"/image-runs/{run.id}/shots", json={"prompts": prompts}).status_code, 409)
        with webapp.run_queue.lock:
            webapp.run_queue.items.remove(item)

    # --- Size ---

    def test_the_size_asked_for_reaches_the_latent(self):
        self.make(aspect="16:9", megapixels="1", count="1")
        latent = self.inputs(self.comfy.prompts[0], "EmptyLatentImage")
        self.assertEqual((latent["width"], latent["height"]), (1360, 768))

    def test_an_exact_size(self):
        self.make(aspect="custom", size="512x768", megapixels="image", count="1")
        latent = self.inputs(self.comfy.prompts[0], "EmptyLatentImage")
        self.assertEqual((latent["width"], latent["height"]), (512, 768))

    def test_a_screen_comes_out_exactly_that_size(self):
        for preset, latent_size in (("1920x1080", (1920, 1088)), ("1272x2772", (1280, 2784))):
            self.comfy.prompts.clear()
            self.make(aspect=preset, megapixels="image", count="1", prompt=f"a wallpaper for {preset}")
            latent = self.inputs(self.comfy.prompts[0], "EmptyLatentImage")
            self.assertEqual((latent["width"], latent["height"]), latent_size, "the model gets a size on its grid")
            run = next(run for run in list_runs() if preset in run.brief)
            with Image.open(run.image_path(run.shots[0])) as image:
                self.assertEqual(image.size, tuple(int(side) for side in preset.split("x")), "and what you get is the screen's")

    def test_an_edit_for_a_phone_comes_out_exactly_that_size(self):
        self.make(image=True, aspect="1272x2772", megapixels="image", count="1")
        self.assertEqual(self.uploaded_size(), media.edit_render_size(1272, 2772))
        self.assertEqual(self.finished_size(), (1272, 2772))

    def test_only_the_edit_encoder_gets_the_special_size(self):
        self.make(aspect="1376x768", count="1")
        latent = self.inputs(self.comfy.prompts[0], "EmptyLatentImage")
        self.assertEqual((latent["width"], latent["height"]), (1376, 768), "Krea has no such encoder")

    def uploaded_size(self):
        return Image.open(io.BytesIO(self.comfy.uploads[0])).size

    def finished_size(self):
        run = self.only_run()
        with Image.open(run.image_path(run.shots[0])) as image:
            return image.size

    def test_an_edit_can_match_the_images_resolution(self):
        self.make(image=True, aspect="image", megapixels="image", count="1")
        self.assertEqual(self.uploaded_size(), media.edit_render_size(800, 1200), "a workflow that follows its source comes out this size")
        self.assertEqual(self.finished_size(), (800, 1200), "and what's over is cropped off")

    def test_an_edit_can_match_its_shape_at_a_pixel_count(self):
        self.make(image=True, aspect="image", megapixels="1", count="1")
        self.assertEqual(self.finished_size(), (832, 1248))

    def test_an_edit_can_be_given_a_size_of_its_own(self):
        self.make(image=True, aspect="16:9", megapixels="1", count="1")
        self.assertEqual(self.uploaded_size(), (1360, 768), "nothing wrong with this one")
        self.assertEqual(self.finished_size(), (1360, 768))
        self.assertEqual(self.only_run().image_count, 1)
        with Image.open(self.only_run().input_paths[0]) as source:
            self.assertEqual(source.size, (800, 1200), "the original is kept whole")

    def test_bad_options_are_refused(self):
        for fields in ({"count": "0"}, {"count": "51"}, {"count": "many"}, {"aspect": "wide"}, {"megapixels": "99"}, {"aspect": "custom", "size": "big"},
                       {"prompt_mode": "other"}, {"llm": "nobody"}, {"prompt": " "}):
            self.assertEqual(self.generate(**fields).status_code, 400, fields)
        self.assertEqual(webapp.run_queue.pending(), [])

    def test_an_llm_writes_up_to_30_and_an_exact_prompt_goes_to_50(self):
        written, error = image_panel.build_options({"count": "30", "llm": "gemini", "prompt_mode": "llm"})
        self.assertIsNone(error)
        self.assertIn("--variety", written)
        self.assertIn("An LLM writes up to 30", image_panel.build_options({"count": "31", "llm": "gemini"})[1])
        exact, error = image_panel.build_options({"count": "50", "prompt_mode": "direct"})
        self.assertIsNone(error)
        self.assertNotIn("--variety", exact, "nothing to vary in your own prompt")
        self.assertIsNotNone(image_panel.build_options({"count": "51", "prompt_mode": "direct"})[1])

    def test_words_per_prompt_reach_the_writer_unless_at_the_usual(self):
        flags, error = image_panel.build_options({"count": "5", "llm": "gemini", "words": "300"})
        self.assertIsNone(error)
        self.assertEqual(flags[flags.index("--words") + 1], "300")
        self.assertNotIn("--words", image_panel.build_options({"count": "5", "llm": "gemini", "words": "200"})[0])
        for words in ("30", "500", "many"):
            self.assertIn("Words per prompt", image_panel.build_options({"count": "5", "llm": "gemini", "words": words})[1])
        self.assertNotIn("--words", image_panel.build_options({"count": "5", "prompt_mode": "direct", "words": "300"})[0])

    def test_variety_and_its_chips_reach_the_writer(self):
        flags, error = image_panel.build_options({"count": "5", "llm": "gemini", "variety": "slight", "chip_pose": "vary",
                                                  "chip_outfit": "keep", "chip_style": ""})
        self.assertIsNone(error)
        start = flags.index("--variety")
        self.assertEqual(flags[start:start + 6], ["--variety", "slight", "--vary", "pose", "--keep", "outfit"])
        self.assertEqual(image_panel.build_options({"count": "5", "llm": "gemini", "variety": "huge"})[1], "Unknown variety.")
        self.assertEqual(image_panel.build_options({"count": "5", "llm": "gemini", "chip_pose": "maybe"})[1], "Unknown choice for pose.")
        slight = planner._instructions("a red coat", 5, 0, variety="slight", vary=["pose"], keep=["outfit"])
        self.assertIn("one shoot", slight)
        self.assertIn("change only the pose, a little", slight)
        self.assertIn("Keep the outfit the same in every one", slight)
        self.assertIn("clearly different", planner._instructions("a red coat", 5, 0, variety="wide"))
        self.assertNotIn("one shoot", planner._instructions("a red coat", 1, 0, variety="slight"), "one image has nothing to vary")
        # The chips added later: the writer is told the colour palette, though its chip just says Colour.
        flags = image_panel.build_options({"count": "5", "llm": "gemini", "chip_subject": "keep", "chip_hair": "keep",
                                           "chip_action": "vary", "chip_colour": "keep"})[0]
        self.assertEqual(flags[flags.index("--keep") + 1], "subject,hair,colour")
        kept = planner._instructions("a red coat", 5, 0, vary=["action"], keep=["subject", "hair", "colour"])
        self.assertIn("Keep the subject, hair and colour palette the same in every one", kept)
        self.assertIn("Make the action differ from one to the next", kept)
        self.assertIn(("colour", "colour"), variety.chip_labels())

    def test_the_chips_come_grouped_the_most_used_first_without_time_or_expression(self):
        groups = variety.chip_groups()
        self.assertEqual([heading for heading, _ in groups], ["Most used", "More"])
        self.assertEqual([name for name, _ in groups[0][1]], ["pose", "framing", "outfit", "location", "subject", "hair", "action"])
        self.assertEqual([name for name, _ in groups[1][1]], ["lighting", "colour", "camera", "style"])
        self.assertNotIn("time", variety.NAMES)
        self.assertNotIn("expression", variety.NAMES)
        # A form saved before still sends them: they're let go, not refused.
        self.assertEqual(variety.flags_from_form({"chip_time": "keep", "chip_pose": "vary"})[1], None)

    def test_each_style_lora_has_a_strength_range_worth_using(self):
        from core import lora_hints
        self.assertEqual(lora_hints.range_of("Krea2\\Krea2_PornMaster_Uncensored_V1_NSFW.safetensors"), "0.5–1")
        self.assertEqual(lora_hints.range_of("krea2_ultra_real_v2_pro_SFW.safetensors"), "0.4–0.8")
        self.assertIsNone(lora_hints.range_of("someone_else.safetensors"))

    def test_explicit_content_is_told_to_the_writer_only_in_private_mode(self):
        form = {"count": "3", "llm": "gemini", "explicit": "on"}
        with mock.patch.object(image_panel, "private_mode", return_value=True):
            self.assertIn("--explicit", image_panel.build_options(form)[0])
            self.assertNotIn("--explicit", image_panel.build_options({**form, "prompt_mode": "direct"})[0], "no writer to tell")
        with mock.patch.object(image_panel, "private_mode", return_value=False):
            self.assertNotIn("--explicit", image_panel.build_options(form)[0], "outside Private mode the box does nothing")
        reply = json.dumps({"title": "Set", "versions": [{"title": "One", "prompt": "One"}]})
        with mock.patch.object(planner.llm, "_ask", return_value=reply) as ask:
            planner.write_prompts([], "a red coat", 1, "gemini", explicit=True)
            planner.write_prompts([], "a red coat", 1, "gemini")
        self.assertTrue(ask.call_args_list[0].args[1].endswith(explicit.RULE), "the paragraph shown under the box, word for word")
        self.assertNotIn(explicit.RULE, ask.call_args_list[1].args[1])

    # --- Never making anything twice ---

    def test_continuation_matches_the_chosen_prompt_model(self):
        state = RunState.new("idea", 1, False, 1024, 1024, llm="gemini")
        state.shots = [{"title": "One", "prompt": "One"}]
        state.inputs = "same"
        with mock.patch.object(image_panel, "busy_runs", return_value=set()), \
                mock.patch.object(image_panel.video_media, "inputs_fingerprint", return_value="same"), \
                mock.patch.object(image_panel, "list_runs", return_value=[state]):
            self.assertIs(image_panel.run_to_continue("idea", ["--count", "1", "--llm", "gemini"], {}, []), state)
            self.assertIsNone(image_panel.run_to_continue("idea", ["--count", "1", "--llm", "local"], {}, []))

    def test_generate_continues_a_stopped_set_without_new_prompts(self):
        self.comfy.script = ["fail", "fail", "ok", "ok", "fail", "fail"]
        self.make()
        run = self.only_run()
        status = self.status()
        log = "\n".join(line["text"] for line in webapp.job.lines[-30:])
        self.assertEqual(status["returncode"], 1,
                         f"queue_error={webapp.run_queue.persistence_error!r}\n"
                         f"returncode={status['returncode']!r}\n{log}")
        self.assertEqual(len(run.done), 2, "one that won't come out doesn't cost the rest")
        self.assertFalse(run.finished)
        self.assertEqual(len(self.comfy.prompts), 6, "the failed image also exhausts the panel's one automatic retry")

        reply = self.make()
        self.assertEqual(reply["continued"], "Three Looks")
        run = self.only_run()
        self.assertTrue(run.finished)
        self.assertEqual(len(self.llm.requests), 1, "the prompts weren't paid for again")
        self.assertEqual(len(self.comfy.prompts), 7, "and only the missing one was made")

    def test_a_different_set_gets_its_own_prompts(self):
        self.make(review="1")
        self.make(prompt="something else", review="1")
        self.assertEqual(len(list_runs()), 2)
        self.assertEqual(len(self.llm.requests), 2)

    def test_a_bad_file_is_made_again(self):
        self.comfy.script = ["corrupt"]
        self.make(count="1")
        self.assertTrue(self.only_run().finished)
        self.assertEqual(len(self.comfy.prompts), 2)

    # --- The gallery ---

    def test_images_can_be_seen_opened_and_downloaded(self):
        self.make()
        status = self.status()
        run = self.only_run()
        self.assertEqual(status["stopped_runs"], [], "a finished set isn't waiting for anything")
        self.assertEqual([s["id"] for s in status["image_sets"]], [run.id])
        self.assertEqual(status["image_sets"][0]["size"], "1024x1024")
        self.assertEqual(status["image_sets"][0]["llm"], run.llm)
        self.assertEqual(status["image_sets"][0]["size_bytes"], sum(os.path.getsize(run.image_path(shot)) for shot in run.shots))
        self.assertEqual(status["image_sets"][0]["resolutions"], list(dict.fromkeys(
            image["resolution"] for image in status["image_sets"][0]["images"])))
        self.assertEqual([image["position"] for image in status["image_sets"][0]["images"]], [1, 2, 3])
        self.assertEqual(self.client.get(f"/image-runs/{run.id}/files/1").status_code, 200)
        self.assertIn("attachment", self.client.get(f"/image-runs/{run.id}/files/1?download=1").headers["Content-Disposition"])
        thumbnail = self.client.get(f"/image-runs/{run.id}/thumbnails/1")
        self.assertEqual(thumbnail.mimetype, "image/jpeg")
        self.assertEqual(self.client.get(f"/image-runs/{run.id}/files/9").status_code, 404)
        self.assertEqual(self.client.get("/image-runs/image_19990101_000000/files/1").status_code, 404)
        self.assertEqual(self.client.get("/image-runs/..%2f..%2fetc/files/1").status_code, 404)

    def test_one_image_made_again_leaves_the_others(self):
        self.make()
        run = self.only_run()
        before = {shot["file"]: os.path.getmtime(run.image_path(shot)) for shot in run.shots[1:]}
        first = run.shots[0]["file"]
        self.assertEqual(self.client.post(f"/image-runs/{run.id}/redo/9").status_code, 400)
        self.assertTrue(self.client.post(f"/image-runs/{run.id}/redo/1").get_json()["ok"])
        self.wait_idle()
        run = self.only_run()
        self.assertTrue(run.finished)
        self.assertEqual(len(self.comfy.prompts), 4)
        self.assertEqual({shot["file"]: os.path.getmtime(run.image_path(shot)) for shot in run.shots[1:]}, before)
        # The new one takes the old one's place, under its name: not another set, not another file.
        self.assertEqual(run.shots[0]["file"], first)
        self.assertNotIn("redo", run.shots[0])
        self.assertEqual(sorted(os.listdir(run.output_dir)), sorted(shot["file"] for shot in run.shots))
        # A redo that fails keeps the one there was.
        self.comfy.script = ["error"] * 10
        self.assertTrue(self.client.post(f"/image-runs/{run.id}/redo/1").get_json()["ok"])
        self.wait_idle()
        run = self.only_run()
        self.assertEqual(run.shots[0]["file"], first)
        self.assertTrue(os.path.exists(run.image_path(run.shots[0])))
        self.assertNotIn("redo", run.shots[0])

    def test_discarding_keeps_what_was_made_and_delete_takes_the_set(self):
        self.make()
        run = self.only_run()
        made = run.shots[0]["file"]
        # As if it stopped with one still to make.
        os.remove(run.image_path(run.shots[2]))
        run.shots[2]["file"] = None
        run.save()
        webapp._runs_cache["at"] = 0.0
        self.assertTrue(self.client.post(f"/runs/{run.id}/discard").get_json()["ok"])
        run = self.only_run()
        self.assertEqual((len(run.shots), run.finished), (2, True), "what it made stays, as a set of those")
        self.assertTrue(os.path.exists(os.path.join(run.output_dir, made)))
        self.assertTrue(self.client.post(f"/image-runs/{run.id}/delete").get_json()["ok"])
        self.assertFalse(os.path.exists(run.output_dir), "Output's Delete takes the whole set")

    def test_upscaling_one_adds_it_beside_the_one_it_came_from(self):
        self.make(count="2")
        run = self.only_run()
        self.assertEqual(self.client.post(f"/image-runs/{run.id}/upscale/9").status_code, 400)
        prompts = len(self.comfy.prompts)
        self.assertTrue(self.client.post(f"/image-runs/{run.id}/upscale/1").get_json()["ok"])
        self.wait_idle()
        run = self.only_run()
        self.assertEqual(len(run.shots), 3)
        upscaled = run.shots[1]
        self.assertEqual((upscaled["upscaled_from"], upscaled["title"]), (1, run.shots[0]["title"] + " · upscaled"))
        # Each keeps what made it; the upscaled one its own copy of the original's.
        self.assertEqual(run.shots[0]["setup"]["width"], run.width)
        self.assertEqual(upscaled["setup"], run.shots[0]["setup"])
        self.assertIsNot(upscaled["setup"], run.shots[0]["setup"])
        detail = self.client.get(f"/image-runs/{run.id}").get_json()
        self.assertEqual(detail["shots"][0]["settings"]["size"], f"{run.width}x{run.height}", "more like this from its own setup")
        self.assertTrue(upscaled["file"].endswith("_upscaled.png") and os.path.exists(run.image_path(upscaled)))
        sent = self.comfy.prompts[prompts]["prompt"]
        self.assertEqual({node["class_type"] for node in sent.values()},
                         {"LoadImage", "SeedVR2LoadDiTModel", "SeedVR2LoadVAEModel", "SeedVR2VideoUpscaler", "PreviewImage"})
        self.assertEqual(next(n for n in sent.values() if n["class_type"] == "SeedVR2LoadDiTModel")["inputs"]["attention_mode"], "sageattn_2")
        self.assertEqual(self.client.post(f"/image-runs/{run.id}/upscale/1?method=seedvr2&resolution=999").status_code, 400)
        self.assertEqual(self.client.post(f"/image-runs/{run.id}/upscale/1?method=seedvr2&resolution=1").status_code, 400)
        prompts = len(self.comfy.prompts)
        self.assertTrue(self.client.post(f"/image-runs/{run.id}/upscale/1?method=seedvr2&resolution=1440").get_json()["ok"])
        self.wait_idle()
        sent = self.comfy.prompts[prompts]["prompt"]
        self.assertEqual(next(n for n in sent.values() if n["class_type"] == "SeedVR2VideoUpscaler")["inputs"]["resolution"], 1440)
        # 2, 3 or 4 times its size: its shorter side that many times, within 2560.
        self.assertEqual(self.client.post(f"/image-runs/{run.id}/upscale/1?method=seedvr2&scale=5").status_code, 400)
        shorter = min(Image.open(run.image_path(run.shots[0])).size)
        for scale in (3, 4):
            prompts = len(self.comfy.prompts)
            self.assertTrue(self.client.post(f"/image-runs/{run.id}/upscale/1?method=seedvr2&scale={scale}").get_json()["ok"])
            self.wait_idle()
            sent = self.comfy.prompts[prompts]["prompt"]
            self.assertEqual(next(n for n in sent.values() if n["class_type"] == "SeedVR2VideoUpscaler")["inputs"]["resolution"],
                             min(2560, scale * shorter))
        # Its denoise is SeedVR2's latent noise; none unless asked.
        self.assertEqual(next(n for n in sent.values() if n["class_type"] == "SeedVR2VideoUpscaler")["inputs"]["latent_noise_scale"], 0.0)
        prompts = len(self.comfy.prompts)
        self.assertTrue(self.client.post(f"/image-runs/{run.id}/upscale/1?method=seedvr2&denoise=0.1").get_json()["ok"])
        self.wait_idle()
        sent = self.comfy.prompts[prompts]["prompt"]
        self.assertEqual(next(n for n in sent.values() if n["class_type"] == "SeedVR2VideoUpscaler")["inputs"]["latent_noise_scale"], 0.1)
        self.assertTrue(self.only_run().shots[1]["upscaled_with"].endswith("denoise 0.1"), self.only_run().shots[1]["upscaled_with"])

    def test_upscaling_fast_takes_superscale_and_blends_at_the_strength_asked(self):
        self.make(count="1", aspect="1:1", megapixels="0.5")
        run = self.only_run()
        prompts = len(self.comfy.prompts)
        self.assertEqual(self.client.post(f"/image-runs/{run.id}/upscale/1?method=sideways").status_code, 400)
        self.assertTrue(self.client.post(f"/image-runs/{run.id}/upscale/1?method=fast&strength=0.5").get_json()["ok"])
        self.wait_idle()
        run = self.only_run()
        upscaled = run.shots[1]
        self.assertEqual(upscaled["title"], run.shots[0]["title"] + " · upscaled fast")
        original = Image.open(run.image_path(run.shots[0])).size
        self.assertEqual(Image.open(run.image_path(upscaled)).size, (original[0] * 2, original[1] * 2))
        sent = self.comfy.prompts[prompts]["prompt"]
        self.assertEqual(next(n for n in sent.values() if n["class_type"] == "UpscaleModelLoader")["inputs"]["model_name"],
                         "4x_NMKD-Superscale-SP_178000_G.pth")

    def test_upscaling_with_ultrasharp_takes_its_own_model(self):
        self.make(count="1", aspect="1:1", megapixels="0.5")
        run = self.only_run()
        prompts = len(self.comfy.prompts)
        self.assertTrue(self.client.post(f"/image-runs/{run.id}/upscale/1?method=ultrasharp").get_json()["ok"])
        self.wait_idle()
        run = self.only_run()
        self.assertEqual(run.shots[1]["title"], run.shots[0]["title"] + " · upscaled with UltraSharp")
        sent = self.comfy.prompts[prompts]["prompt"]
        self.assertEqual(next(n for n in sent.values() if n["class_type"] == "UpscaleModelLoader")["inputs"]["model_name"], "4x-UltraSharp.pth")

    def test_seedvr2_takes_a_denoise_and_ultimate_sd_and_hires_fix_are_gone(self):
        self.make(count="1", aspect="1:1", megapixels="0.5")
        run = self.only_run()
        added = []
        with mock.patch.object(webapp.run_queue, "add", lambda item: added.append(item) or 1):
            for gone in ("hires", "usdu"):
                self.assertEqual(self.client.post(f"/image-runs/{run.id}/upscale/1?method={gone}").status_code, 400, gone)
            self.assertEqual(self.client.post(f"/image-runs/{run.id}/upscale/1?method=seedvr2&denoise=2").status_code, 400)
            self.assertTrue(self.client.post(f"/image-runs/{run.id}/upscale/1?method=seedvr2&scale=2&denoise=0.1").get_json()["ok"])
            self.assertTrue(self.client.post(f"/image-runs/{run.id}/upscale/1?method=seedvr2&denoise=0").get_json()["ok"])
        self.assertEqual(added[0]["argv"][added[0]["argv"].index("--denoise") + 1], "0.1")
        self.assertTrue(added[0]["detail"].startswith("SeedVR2, 2× (") and added[0]["detail"].endswith("p), denoise 0.1"), added[0]["detail"])
        self.assertNotIn("--denoise", added[1]["argv"], "none: as it ran before")

    def test_a_screen_stepped_goes_as_its_shape_at_that_many_megapixels(self):
        from panel import image as image_panel
        self.assertEqual(image_panel.size_flags({"aspect": "1272x2772", "megapixels": "image"})[0], ["--size", "1272x2772"])
        self.assertEqual(image_panel.size_flags({"aspect": "1272x2772", "megapixels": "2.0"})[0], ["--aspect", "1272:2772", "--megapixels", "2.0"])
        self.assertEqual(image_panel.size_flags({"aspect": "custom", "size": "1000x500", "megapixels": "1.5"})[0],
                         ["--aspect", "1000:500", "--megapixels", "1.5"])

    def test_a_big_image_takes_the_ways_that_fit_and_says_how_it_was_upscaled(self):
        from panel import image as image_panel
        self.assertIsNotNone(image_panel.upscale_problem("seedvr2", 1568, 2784))
        for method in ("ultrasharp", "fast"):
            self.assertIsNone(image_panel.upscale_problem(method, 1568, 2784), method)
        self.assertIsNotNone(image_panel.upscale_problem("ultrasharp", 3000, 5000))
        self.make(count="1", aspect="1:1", megapixels="0.5")
        run = self.only_run()
        self.assertTrue(self.client.post(f"/image-runs/{run.id}/upscale/1?method=ultrasharp&strength=0.75").get_json()["ok"])
        self.wait_idle()
        listed = image_panel.describe_run(self.only_run())
        self.assertEqual([image["upscaled"] for image in listed["images"]], [None, "4x-UltraSharp, strength 0.75"])
        self.assertEqual(listed["upscaled"], "4x-UltraSharp, strength 0.75")

    def test_several_upscales_of_a_set_queue_at_once_each_by_its_file(self):
        from panel import image as image_panel
        self.make(count="2", aspect="1:1", megapixels="0.5")
        run = self.only_run()
        files = [shot["file"] for shot in run.shots]
        with mock.patch.object(webapp.run_queue, "_advance"):
            for position in (1, 2, 2):
                reply = self.client.post(f"/image-runs/{run.id}/upscale/{position}?method=ultrasharp")
                self.assertTrue(reply.get_json()["ok"], reply.get_json())
            queued = [item for item in webapp.run_queue.items if image_panel.is_upscale(item)]
            self.addCleanup(lambda: [webapp.run_queue.items.remove(item) for item in queued if item in webapp.run_queue.items])
            self.assertEqual(len(queued), 3, "a second and third upscale of the set wait too")
            self.assertEqual([item["argv"][item["argv"].index("--file") + 1] for item in queued], [files[0], files[1], files[1]])
            # Once the first is made, image 2 is third in the set: it is found by its file.
            state = image_panel.RunState.load(run.id)
            state.shots.insert(1, {**state.shots[0], "file": "made.png", "upscaled_from": 1})
            self.assertEqual(image_panel.upscale_position(state, queued[1]["argv"]), "3")
            making = {"id": self.queue_id(), "pipeline": "image", "label": "Set", "resume": run.id, "argv": ["x"], "later": True}
            webapp.run_queue.items.append(making)
            self.addCleanup(lambda: making in webapp.run_queue.items and webapp.run_queue.items.remove(making))
            self.assertEqual(self.client.post(f"/image-runs/{run.id}/upscale/1?method=ultrasharp").status_code, 409,
                             "not while the set itself is queued to be made")

    def test_an_image_can_be_deleted_while_another_of_its_set_waits_to_be_upscaled(self):
        from panel import image as image_panel
        self.make(count="2", aspect="1:1", megapixels="0.5")
        run = self.only_run()
        with mock.patch.object(webapp.run_queue, "_advance"):
            self.assertTrue(self.client.post(f"/image-runs/{run.id}/upscale/1?method=ultrasharp").get_json()["ok"])
            queued = [item for item in webapp.run_queue.items if image_panel.is_upscale(item)]
            self.addCleanup(lambda: [webapp.run_queue.items.remove(i) for i in queued if i in webapp.run_queue.items])
            self.assertEqual(self.client.post(f"/image-runs/{run.id}/delete/1").status_code, 409, "not the one it waits to upscale")
            detail = self.client.get(f"/image-runs/{run.id}").get_json()
            self.assertFalse(detail["busy"] or detail["pending"], "an upscale only waiting doesn't hold the set")
            self.assertEqual([shot["locked"] for shot in detail["shots"]], [True, False], "only the image it waits on")
            reply = self.client.post(f"/image-runs/{run.id}/delete/2").get_json()
            self.assertTrue(reply["ok"], reply)
            self.assertEqual(len(self.only_run().shots), 1)
            # One queued before images were found by file would land on the wrong one: refused.
            queued[0]["argv"] = [arg for arg in queued[0]["argv"] if arg != queued[0]["argv"][queued[0]["argv"].index("--file") + 1] and arg != "--file"]
            self.assertEqual(self.client.post(f"/image-runs/{run.id}/delete/1").status_code, 409)

    def test_trying_one_first_makes_one_and_stops(self):
        self.make(count="3", try_first="1")
        run = self.only_run()
        self.assertEqual([bool(shot.get("file")) for shot in run.shots], [True, False, False])
        self.assertEqual(len(self.comfy.prompts), 1)
        said = lambda: (next((r for r in self.status()["stopped_runs"] if r["id"] == run.id), {}).get("outcome") or {}).get("outcome")
        for _ in range(50):  # The queue notes it on its next look, within half a second
            if said() == "first one made":
                break
            time.sleep(0.1)
        self.assertEqual(said(), "first one made", "it says why it stopped")
        self.assertTrue(self.client.post(f"/runs/{run.id}/continue").get_json()["ok"])
        self.wait_idle()
        self.assertTrue(self.only_run().finished)
        self.assertEqual(len(self.comfy.prompts), 3, "the rest, and the first not again")

    def test_what_the_enhancer_wrote_is_watched_only_when_it_is_used(self):
        from pipelines.image.comfy import generated_text, watch_text_generation
        workflow = {"1": {"class_type": "TextGenerate", "inputs": {"prompt": "x"}},
                    "2": {"class_type": "KSampler", "inputs": {"positive": ["1", 0]}},
                    "3": {"class_type": "PreviewImage", "inputs": {"images": ["2", 0]}},
                    "9": {"class_type": "TextGenerate", "inputs": {"prompt": "switched off"}}}
        self.assertEqual(watch_text_generation(workflow), ["enhanced_1"])
        self.assertEqual(workflow["enhanced_1"]["inputs"]["source"], ["1", 0])
        self.assertNotIn("enhanced_9", workflow, "one nothing reads would run for nothing")
        entry = {"outputs": {"enhanced_1": {"text": ["A bright lighthouse at dusk."]}, "3": {"images": []}}}
        self.assertEqual(generated_text(entry, ["enhanced_1"]), "A bright lighthouse at dusk.")
        self.assertIsNone(generated_text({"outputs": {}}, ["enhanced_1"]))

    def test_deleting_an_image_keeps_it_from_coming_back(self):
        self.make()
        run = self.only_run()
        gone = run.image_path(run.shots[1])
        before = image_panel.image_files(run)
        reply = self.client.post(f"/image-runs/{run.id}/delete/2").get_json()
        self.assertTrue(reply["ok"])
        self.assertEqual([p["position"] for p in reply["images"]], [1, 2])
        self.assertEqual(reply["images"][1]["title"], before[2]["title"])
        self.assertEqual(reply["images"][1]["version"], before[2]["version"])
        self.assertNotEqual(reply["images"][1]["version"], before[1]["version"], "renumbered pictures cannot reuse the deleted image's cached URL")
        self.assertFalse(os.path.exists(gone))
        run = self.only_run()
        self.assertEqual((len(run.shots), run.finished), (2, True), "it isn't owed to the set any more")
        self.assertEqual(self.status()["stopped_runs"], [])
        self.assertEqual(self.client.get(f"/image-runs/{run.id}/files/2").status_code, 200, "the next one moved up")

    def test_deleting_the_last_image_takes_the_set(self):
        self.make(count="1")
        run = self.only_run()
        self.assertEqual(self.client.post(f"/image-runs/{run.id}/delete/1").get_json(), {"ok": True, "images": []})
        self.assertEqual(list_runs(), [])
        self.assertFalse(os.path.exists(run.output_dir))

    def test_deleting_a_set_takes_its_images(self):
        self.make()
        run = self.only_run()
        self.assertTrue(self.client.post(f"/image-runs/{run.id}/delete").get_json()["ok"])
        self.assertEqual(list_runs(), [])
        self.assertFalse(os.path.exists(run.output_dir))
        self.assertEqual(self.status()["image_sets"], [])

    def test_a_missing_file_is_owed_again(self):
        self.make(count="2")
        run = self.only_run()
        os.remove(run.image_path(run.shots[0]))
        self.assertFalse(RunState.load(run.id).finished)

    # --- The form's side of it ---

    def test_the_list_has_only_images_and_says_why_one_cant_run(self):
        broken = edit_image_workflow()
        broken["definitions"]["subgraphs"][0]["nodes"][0]["widgets_values"] = ["gone.safetensors"]
        self.comfy.saved = {"image_text.json": text_to_image_workflow(), "image_edit.json": broken, "film.json": {"nodes": []}}
        listed = self.client.get("/api/workflows?pipeline=image").get_json()["workflows"]
        self.assertEqual(listed, [
            {"name": "image_edit.json", "label": "edit", "problem": "Needs gone.safetensors, which isn't installed."},
            {"name": "image_text.json", "label": "text", "takes": {"min_images": 0, "max_images": 0, "size": True, "model": None, "options": [
                {"id": "face_enable_lora", "kind": "switch", "label": "Enable LoRA", "default": "0", "node": 30, "input": "value_3",
                 "problem": "Needs krea2_darkbrush.safetensors, which isn't installed."},
                {"id": "prompt_enhancer", "kind": "switch", "role": "llm", "label": "Prompt enhancer", "default": "0",
                 "takes": {"min_images": 0, "max_images": 0}},
                {"id": "steps", "kind": "number", "label": "Steps", "default": "8", "min": 1, "max": 150, "step": 1, "advanced": True},
                {"id": "model_file", "kind": "choice", "label": "Model", "default": "model.safetensors", "choices": ["model.safetensors"],
                 "labels": {"model.safetensors": "model"}, "model": True, "problem": "No other model that fits is installed.",
                 "hint": workflow_options.HINTS["model_file"]}]}}])
        self.assertEqual(self.client.get("/api/workflows?pipeline=video").get_json()["workflows"], [], "they don't turn up among the films")
        reply = self.generate(image=True)
        self.assertEqual(reply.status_code, 400)
        self.assertIn("gone.safetensors", reply.get_json()["error"], "Automatic says why it has nothing to edit with")
        self.assertEqual(self.generate(workflow="image_edit.json", image=True).status_code, 400)

    # --- Fibo 2.0 ---

    def fibo(self, **fields):
        return self.generate(workflow="Fibo2_test.json", **fields)

    def test_fibo2_is_listed_for_images_without_image_in_its_name(self):
        listed = {w["name"]: w.get("takes") for w in self.client.get("/api/workflows?pipeline=image").get_json()["workflows"]}
        self.assertEqual({key: value for key, value in listed["Fibo2_test.json"].items() if key != "options"},
                         {"min_images": 0, "max_images": 16, "size": True, "model": "fibo2"})
        self.assertNotIn("Fibo2_test.json", [w["name"] for w in self.client.get("/api/workflows?pipeline=video").get_json()["workflows"]])

    def test_automatic_keeps_to_what_was_made_for_it(self):
        self.make(prompt_mode="direct", count="1", llm=None)
        self.assertEqual(os.path.basename(self.only_run().workflow), "image_text.json", "text alone goes to the one that takes no image")
        self.clear_everything()
        self.make(image=True, prompt_mode="direct", count="1", llm=None)
        self.assertEqual(os.path.basename(self.only_run().workflow), "image_edit.json", "an image to the one that needs one")

    def test_automatic_uses_fibo2_when_nothing_else_fits(self):
        form = {"prompt": "x", "prompt_mode": "direct", "count": "1", "aspect": "1:1", "megapixels": "1",
                "image": (io.BytesIO(png_bytes()), "a.png"), "image_2": (io.BytesIO(png_bytes(color=(1, 2, 3))), "b.png")}
        self.assertTrue(self.client.post("/generate/image", data=form, content_type="multipart/form-data").get_json()["ok"])
        self.wait_idle()
        run = self.only_run()
        self.assertEqual((os.path.basename(run.workflow), run.image_count), ("Fibo2_test.json", 2), "two images: only Fibo 2.0 takes them")
        encoder = self.inputs(self.comfy.prompts[0], "TextEncodeFibo2")
        self.assertEqual(sum(name.startswith("images.") for name in encoder), 2, "the boxes left empty came out")

    def test_fibo2_refuses_what_it_doesnt_make_well(self):
        for fields in ({"aspect": "1920x1080", "megapixels": "image"}, {"aspect": "1:1", "megapixels": "2"}, {"aspect": "custom", "size": "1272x2772", "megapixels": "image"}):
            reply = self.fibo(prompt_mode="direct", llm=None, **fields)
            self.assertEqual(reply.status_code, 400, fields)
            self.assertIn("Fibo 2.0 makes images up to 1.1 megapixels", reply.get_json()["error"])
        reply = self.fibo(count="31")
        self.assertEqual(reply.status_code, 400)
        # Every LLM writes at most 30 now (Fibo 2.0's own limit is the same), so the general limit answers first.
        self.assertIn("writes up to 30", reply.get_json()["error"])
        self.assertEqual(self.llm.requests, [], "refused before anything is paid for")
        self.assertIn("1.1 megapixels", self.client.post("/api/estimate/image", data={"workflow": "Fibo2_test.json", "aspect": "3840x2160"}).get_json()["error"],
                      "and the form hears it before Generate")

    def test_fibo2_matching_a_big_image_stays_within_its_megapixel(self):
        form = {"prompt": "x", "prompt_mode": "direct", "count": "1", "workflow": "Fibo2_test.json", "aspect": "image", "megapixels": "image",
                "image": (io.BytesIO(png_bytes(size=(2400, 1600))), "big.png")}
        self.assertTrue(self.client.post("/generate/image", data=form, content_type="multipart/form-data").get_json()["ok"])
        self.wait_idle()
        run = self.only_run()
        self.assertLessEqual(run.width * run.height, 1.1 * media.PIXELS_PER_MEGAPIXEL)

    def test_fibo2_gets_the_llms_json_captions(self):
        self.llm.reply = captions_reply(edit=False)
        self.make(workflow="Fibo2_test.json")
        run = self.only_run()
        self.assertTrue(run.finished, [l["text"] for l in webapp.job.lines][-15:])
        sent = [self.inputs(p, "TextEncodeFibo2")["prompt"] for p in self.comfy.prompts]
        self.assertEqual([json.loads(prompt)["short_description"] for prompt in sent], [f"A woman in look number {n}." for n in (1, 2, 3)])
        self.assertTrue(all("edit_instruction" not in json.loads(prompt) for prompt in sent), "an image from text has nothing to edit")
        self.assertIn("ONE JSON object", self.llm.requests[0]["parts"][-1]["text"])
        encoder = self.inputs(self.comfy.prompts[0], "TextEncodeFibo2")
        self.assertEqual((encoder["width"], encoder["height"]), (1024, 1024), "the size goes to the encoder, which makes the latent")
        self.assertFalse(any(name.startswith("images.") for name in encoder), "and with no image, none of its inputs are left")

    def test_fibo2_edits_with_an_instruction(self):
        self.llm.reply = captions_reply()
        self.make(image=True, workflow="Fibo2_test.json", aspect="image", megapixels="1")
        prompt = json.loads(self.inputs(self.comfy.prompts[0], "TextEncodeFibo2")["prompt"])
        self.assertEqual(prompt["edit_instruction"], "Change her outfit to look number 1.")
        self.assertIn("images.image_1", self.inputs(self.comfy.prompts[0], "TextEncodeFibo2"))

    # --- A workflow's own options ---

    def switchable(self, **fields):
        self.comfy.saved["Krea2_switchable.json"] = switchable_workflow()
        return self.generate(workflow="Krea2_switchable.json", prompt_mode="direct", count="1", llm=None, **fields)

    def test_the_workflows_own_options_are_listed(self):
        self.comfy.saved["Krea2_switchable.json"] = switchable_workflow()
        listed = {w["name"]: w for w in self.client.get("/api/workflows?pipeline=image").get_json()["workflows"]}
        ids = [option["id"] for option in listed["Krea2_switchable.json"]["takes"]["options"]]
        self.assertIn("group_sharpen", ids)
        self.assertIn("lora", ids)

    def test_a_run_uses_the_options_chosen_and_keeps_them(self):
        reply = self.switchable(opt_group_sharpen=["0", "1"], opt_lora=["0", "1"], opt_lora_strength="0.7",
                                opt_prompt_boost_on=["0"], opt_steps="12")
        self.assertTrue(reply.get_json()["ok"], reply.get_json())
        self.wait_idle()
        run = self.only_run()
        self.assertTrue(run.finished, [l["text"] for l in webapp.job.lines][-15:])
        self.assertLessEqual({"group_sharpen": "1", "lora": "1", "lora_strength": "0.7", "prompt_boost": "0", "steps": "12"}.items(),
                             run.options.items(), "what was chosen, kept with all the rest")
        sent = self.comfy.prompts[0]["prompt"]
        self.assertIn("Image Lucy Sharpen", [node["class_type"] for node in sent.values()])
        self.assertEqual(self.inputs(self.comfy.prompts[0], "KSampler")["steps"], 12)
        self.assertEqual(self.inputs(self.comfy.prompts[0], "Power Lora Loader (rgthree)")["lora_1"]["strength"], 0.7)
        self.assertEqual(self.inputs(self.comfy.prompts[0], "CLIPTextEncode")["text"], "different outfits", "the prompt still goes in")

        self.assertTrue(self.client.post(f"/image-runs/{run.id}/redo/1").get_json()["ok"])
        self.wait_idle()
        self.assertEqual(self.inputs(self.comfy.prompts[1], "KSampler")["steps"], 12, "made again as it was")

    def test_options_as_saved_are_kept_too(self):
        # Every setting goes with the run, so it opens again as it was made after the workflow's defaults change.
        self.assertTrue(self.switchable(opt_group_sharpen=["0"], opt_steps="8").get_json()["ok"])
        self.wait_idle()
        options = self.only_run().options
        self.assertEqual((options["group_sharpen"], options["steps"]), ("0", "8"))
        self.assertIn("lora", options, "one the form didn't send, as the workflow has it")

    def test_the_workflows_own_prompt_enhancer_writes_them(self):
        self.make(llm="prompt_enhancer", prompt="a lighthouse", count="2", workflow="image_text.json")
        run = self.only_run()
        self.assertTrue(run.finished, [l["text"] for l in webapp.job.lines][-15:])
        self.assertEqual(self.llm.requests, [], "no LLM is asked")
        self.assertTrue(run.direct)
        self.assertEqual(run.options["prompt_enhancer"], "1")
        # Named after its title and the workflow that made it: the folder, and each file in it.
        self.assertEqual(run.output_name, "a_lighthouse_text")
        # While a set is going, each image it has made is under Finished already.
        with mock.patch.object(type(webapp.job), "running", new_callable=mock.PropertyMock, return_value=True),                 mock.patch.object(webapp.job, "pipeline", "image"), mock.patch.dict(webapp.job.progress, {"run_id": run.id}):
            made = webapp.made_in_this_run()
        self.assertEqual([entry["label"] for entry in made], [f"{run.title} · Version 1", f"{run.title} · Version 2"])
        self.assertEqual([(entry["run_id"], entry["position"]) for entry in made], [(run.id, 1), (run.id, 2)])
        self.assertEqual({entry["pipeline"] for entry in made}, {"image"})
        self.assertEqual(webapp.made_in_this_run(), [], "and once it is done, the set's own line says so")
        # The same again: what it was made with, for Generate to start from.
        settings = self.client.get(f"/image-runs/{run.id}").get_json()["settings"]
        self.assertEqual((settings["prompt"], settings["direct"], settings["count"], settings["workflow"], settings["options"]["prompt_enhancer"]),
                         ("a lighthouse", False, 2, "image_text.json", "1"))
        self.assertEqual(settings["llm"], "prompt_enhancer")
        # A set that came out short, or lost some since, opens with the number asked for.
        run.shots = run.shots[:1]
        self.assertEqual(image_panel.settings_of(run)["count"], 2)
        listed = image_panel.describe_run(run)
        self.assertIn(("prompt", "Prompt enhancer"), listed["_facts"])
        self.assertNotIn(("prompt", "Exact prompt"), listed["_facts"])
        self.assertEqual(self.client.get(f"/image-runs/{run.id}/inputs/1").status_code, 404, "it was given no image")
        self.assertEqual(sorted(os.listdir(run.output_dir))[0][:len("a_lighthouse_text_001")], "a_lighthouse_text_001")
        self.assertIn("TextGenerate", [node["class_type"] for node in self.comfy.prompts[0]["prompt"].values()])

    def test_its_prompts_can_be_read_before_any_image_is_made(self):
        self.make(llm="prompt_enhancer", prompt="a lighthouse", count="2", workflow="image_text.json", review="1", seed="40")
        run = self.only_run()
        self.assertEqual(len(run.done), 0, "nothing made yet")
        self.assertEqual([shot["prompt"] for shot in run.shots], ["Enhanced: a lighthouse (1)", "Enhanced: a lighthouse (2)"],
                         "one written for each image")
        self.assertEqual([shot["enhanced_from"] for shot in run.shots], ["a lighthouse"] * 2)
        kinds = {node["class_type"] for node in self.comfy.prompts[0]["prompt"].values()}
        self.assertIn("TextGenerate", kinds)
        self.assertFalse(kinds & {"PreviewImage", "KSampler"}, "only what the enhancer needs is run")
        self.assertEqual(run.options["prompt_enhancer"], "0", "what it wrote goes in as it is")
        prompts = [shot["prompt"] for shot in run.shots]
        prompts[1] = "My own wording."
        self.assertTrue(self.client.post(f"/image-runs/{run.id}/shots", json={"prompts": prompts}).get_json()["ok"])
        self.assertTrue(self.client.post(f"/runs/{run.id}/continue").get_json()["ok"])
        self.wait_idle()
        self.assertTrue(self.only_run().finished)
        rendered = [p for p in self.comfy.prompts if any(n["class_type"] == "PreviewImage" for n in p["prompt"].values())]
        self.assertEqual([self.sent_prompt(p) for p in rendered], ["Enhanced: a lighthouse (1)", "My own wording."])
        self.assertFalse(any(n["class_type"] == "TextGenerate" for p in rendered for n in p["prompt"].values()))

    def test_a_workflow_without_one_says_so(self):
        reply = self.generate(llm="image_to_prompt", workflow="image_text.json")
        self.assertEqual(reply.status_code, 400)
        self.assertIn("no image to prompt", reply.get_json()["error"])
        # And the log says so too, for when the page has moved on.
        self.assertTrue(any(line["text"].startswith("🚫 Not added (image): This workflow has no image to prompt") for line in webapp.job.lines))

    def test_an_option_that_cant_run_is_refused(self):
        for fields in ({"opt_group_color_correction": ["0", "1"]}, {"opt_steps": "0"}, {"opt_group_upscaler.choice": "8K"}):
            reply = self.switchable(**fields)
            self.assertEqual(reply.status_code, 400, fields)
        self.assertEqual(self.comfy.prompts, [])

    def test_the_estimate_starts_nothing_and_follows_the_options(self):
        one = self.client.post("/api/estimate/image", data={"count": "1", "image_count": "0"}).get_json()
        many = self.client.post("/api/estimate/image", data={"count": "15", "image_count": "1"}).get_json()
        self.assertEqual(one["images"], 1)
        self.assertEqual(many["images"], 15)
        self.assertGreater(many["total"], one["total"])
        self.assertFalse(self.client.post("/api/estimate/image", data={"count": "0"}).get_json()["ok"])
        self.assertEqual(self.comfy.prompts, [])

    def test_the_estimate_says_what_writing_the_prompts_takes_in_tokens(self):
        written = self.client.post("/api/estimate/image", data={"count": "30", "image_count": "0", "llm": "gemini",
                                                                "prompt_mode": "llm", "words": "300"}).get_json()
        self.assertEqual((written["tokens"]["each"], written["tokens"]["rounds"]), (425, 2))
        exact = self.client.post("/api/estimate/image", data={"count": "30", "prompt_mode": "direct"}).get_json()
        self.assertNotIn("tokens", exact, "nothing is written")

    def test_progress_is_read_from_the_log(self):
        self.make(count="2")
        status = self.status()
        self.assertEqual(status["pipeline"], "image")
        self.assertEqual(status["progress"]["run_id"], self.only_run().id)
        self.assertEqual(status["progress"]["stage"], [2, 2, "Images"])
        self.assertEqual(status["progress"]["detail"], "Image 2 of 2: Look 2")

    def test_the_image_page_opens(self):
        page = self.client.get("/image")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'id="formImage"', page.data)
        self.assertIn(b'"image"', page.data)


class QwenImage21Test(unittest.TestCase):
    """What Qwen-Image 2.1 can do besides edit image 1: references, painted areas, expanding, transparency."""
    clear_everything, wait_idle, only_run, inputs = PanelTest.clear_everything, PanelTest.wait_idle, PanelTest.only_run, PanelTest.inputs

    def setUp(self):
        PanelTest.setUp(self)
        self.comfy.saved = {"image_q21_edit.json": qwen21_edit_workflow(), "image_q21_text.json": qwen21_text_workflow(),
                            "image_edit.json": edit_image_workflow()}

    def sent_prompt(self, prompt):
        return next(node["inputs"]["prompt"] for node in prompt["prompt"].values() if node["class_type"] == "TextEncodeQwenImage21")

    def png(self, size=(800, 600), color=(10, 200, 30)):
        return io.BytesIO(png_bytes(size, color))

    def form(self, **fields):
        form = {"prompt": "x", "count": "1", "prompt_mode": "direct", "aspect": "image", "megapixels": "1", "workflow": "image_q21_edit.json", **fields}
        return {key: value for key, value in form.items() if value is not None}

    def make_with(self, **fields):
        reply = self.client.post("/generate/image", data=self.form(**fields), content_type="multipart/form-data")
        self.assertTrue(reply.get_json().get("ok"), reply.get_json())
        self.wait_idle()
        run = self.only_run()
        self.assertTrue(run.finished, [l["text"] for l in webapp.job.lines][-15:])
        return run

    def test_one_image_to_edit_then_up_to_four(self):
        listed = {w["name"]: w["takes"] for w in self.client.get("/api/workflows?pipeline=image").get_json()["workflows"]}
        self.assertEqual((listed["image_q21_edit.json"]["min_images"], listed["image_q21_edit.json"]["max_images"]), (1, 4))
        reply = self.client.post("/generate/image", data=self.form(**{f"image{'' if n == 1 else f'_{n}'}": (self.png(), f"{n}.png") for n in range(1, 6)}),
                                 content_type="multipart/form-data")
        self.assertEqual(reply.status_code, 400, "a fifth is more than 12 GB holds beside the one it makes")

    def test_the_other_images_are_shown_at_about_a_megapixel(self):
        self.make_with(image=(self.png((1024, 1024)), "a.png"), image_2=(self.png((3000, 2000)), "b.png"))
        second = Image.open(io.BytesIO(self.comfy.uploads[1]))
        self.assertLessEqual(second.width * second.height, 1.05 * 1024 * 1024, second.size)
        self.assertAlmostEqual(second.width / second.height, 1.5, delta=0.05, msg="its shape kept")
        self.comfy.uploads.clear()
        self.clear_everything()
        self.make_with(image=(self.png((1024, 1024)), "a.png"), image_2=(self.png((3000, 2000)), "b.png"), detail="full")
        self.assertEqual(Image.open(io.BytesIO(self.comfy.uploads[1])).size, (3000, 2000), "full detail leaves it as it is")

    def test_a_new_picture_from_references_at_the_size_asked(self):
        run = self.make_with(image=(self.png((900, 900)), "a.png"), image_2=(self.png((700, 500)), "b.png"), image_mode="compose", aspect="16:9")
        self.assertTrue(run.compose)
        self.assertEqual(run.options.get("face_custom_size"), "1", "the template's Custom size, on")
        latent = self.inputs(self.comfy.prompts[0], "EmptyLatentImage")
        self.assertEqual((latent["width"], latent["height"]), (1376, 768), "on Qwen-Image 2.1's 32 grid")
        self.assertEqual(Image.open(run.image_path(run.shots[0])).size, (1360, 768), "then cropped to the size asked for")
        self.assertEqual(Image.open(io.BytesIO(self.comfy.uploads[0])).size, (900, 900), "image 1 is a reference, not fitted to the size")

    def test_compose_on_a_model_that_cant_is_refused(self):
        reply = self.client.post("/generate/image", data=self.form(workflow="image_edit.json", image=(self.png(), "a.png"), image_mode="compose"),
                                 content_type="multipart/form-data")
        self.assertEqual(reply.status_code, 400)
        self.assertIn("new picture from references", reply.get_json()["error"])

    def painted(self, size, box, color=(230, 40, 40, 255)):
        mask = Image.new("RGBA", size)
        ImageDraw.Draw(mask).ellipse(box, fill=color)
        buffer = io.BytesIO()
        mask.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    def test_only_the_painted_area_changes(self):
        source = Image.new("RGB", (1200, 900), (90, 120, 160))
        buffer = io.BytesIO()
        source.save(buffer, format="PNG")
        buffer.seek(0)
        run = self.make_with(prompt="", image=(buffer, "a.png"), image_mode="areas", areas_mask=(self.painted((1200, 900), [500, 350, 700, 550]), "areas.png"),
                             areas=json.dumps([{"colour": "#e62828", "action": "remove", "text": "the bin"}]))
        self.assertEqual(self.llm.requests, [], "its instruction is written from what's painted")
        self.assertEqual(len(self.comfy.uploads), 2, "the part around it, and the same with the area marked")
        sent = self.sent_prompt(self.comfy.prompts[0])
        self.assertIn("<image2>", sent)
        self.assertIn("blurred out to remove the bin", sent)
        made = Image.open(run.image_path(run.shots[0])).convert("RGB")
        self.assertEqual(made.size, (1200, 900), "the image's own size")
        self.assertEqual(made.getpixel((20, 20)), (90, 120, 160), "outside the area, the original")
        self.assertNotEqual(made.getpixel((600, 450)), (90, 120, 160), "inside it, what the model made")

    def test_several_colours_are_several_changes_in_one_go(self):
        mask = Image.new("RGBA", (1000, 800))
        draw = ImageDraw.Draw(mask)
        draw.ellipse([100, 100, 300, 300], fill=(230, 40, 40, 255))
        draw.rectangle([600, 400, 800, 600], fill=(40, 90, 235, 255))
        buffer = io.BytesIO()
        mask.save(buffer, format="PNG")
        buffer.seek(0)
        self.make_with(prompt="", image=(self.png((1000, 800)), "a.png"), image_mode="areas", areas_mask=(buffer, "areas.png"),
                       areas=json.dumps([{"colour": "#e62828", "text": "a sleeping cat"}, {"colour": "#285aeb", "text": "a brass lamp"}]))
        self.assertEqual(len(self.comfy.uploads), 1, "the marks are on image 1 itself")
        sent = self.sent_prompt(self.comfy.prompts[0])
        self.assertIn("marked in red: a sleeping cat", sent)
        self.assertIn("marked in blue: a brass lamp", sent)

    def test_painted_areas_and_expanding_can_be_estimated(self):
        # No size on the form for these (they come out the image's own size): it once failed with a 500.
        for mode in ("areas", "expand"):
            reply = self.client.post("/api/estimate/image", data={"count": "5", "image_count": "1", "workflow": "image_q21_edit.json",
                                                                  "image_mode": mode, "prompt_mode": "direct"})
            self.assertEqual(reply.status_code, 200, mode)
            self.assertTrue(reply.get_json()["ok"], (mode, reply.get_json()))

    def test_painted_areas_need_words(self):
        reply = self.client.post("/generate/image", data=self.form(prompt="", image=(self.png(), "a.png"), image_mode="areas",
                                                                   areas_mask=(self.painted((800, 600), [10, 10, 50, 50]), "a.png"),
                                                                   areas=json.dumps([{"colour": "red", "action": "replace", "text": ""}])),
                                 content_type="multipart/form-data")
        self.assertEqual(reply.status_code, 400)
        self.assertIn("Say what goes", reply.get_json()["error"])

    def test_expanding_keeps_the_picture_and_draws_the_rest(self):
        run = self.make_with(prompt="more sky", image=(self.png((800, 600), (10, 200, 30)), "a.png"), image_mode="expand",
                             expand_right="50", expand_units="percent")
        made = Image.open(run.image_path(run.shots[0])).convert("RGB")
        self.assertEqual(made.size, (1200, 600))
        self.assertEqual(made.getpixel((100, 300)), (10, 200, 30), "the picture, pixel for pixel")
        self.assertNotEqual(made.getpixel((1150, 300)), (10, 200, 30), "the new part, drawn")
        self.assertIn("The new parts show more sky", self.sent_prompt(self.comfy.prompts[0]))

    def test_transparent_says_so_and_keeps_the_alpha_only_then(self):
        run = self.make_with(workflow="image_q21_text.json", prompt="a red fox", aspect="1:1", transparent="1")
        self.assertTrue(run.transparent)
        self.assertTrue(self.sent_prompt(self.comfy.prompts[0]).startswith("This is an RGBA format image with transparency. a red fox"))
        self.assertEqual(run.shots[0]["prompt"], "a red fox", "the prompt kept as written")

    def test_an_edit_never_starts_from_the_seed_that_made_its_image(self):
        self.make_with(image=(self.png(), "a.png"), seed="5", source_seed="5")
        self.assertNotEqual(self.inputs(self.comfy.prompts[0], "KSampler")["seed"], 5)

    def test_out_of_memory_frees_it_then_tries_smaller(self):
        self.comfy.script = ["error", "error"]
        run = self.make_with(workflow="image_q21_text.json", aspect="1:1")
        for _ in range(50):  # The last is sent in the background as the job ends
            if self.comfy.frees == 3:
                break
            time.sleep(0.02)
        self.assertEqual(self.comfy.frees, 3, "freed after each, and once more as the job ends")
        self.assertEqual(len(self.comfy.prompts), 3)
        latents = [self.inputs(p, "EmptyLatentImage") for p in self.comfy.prompts]
        self.assertLess(latents[2]["width"], latents[0]["width"], "the third a size smaller")
        self.assertEqual(Image.open(run.image_path(run.shots[0])).size, (1024, 1024), "enlarged to the size asked for")

    def test_select_finds_what_was_clicked(self):
        reply = self.client.post("/api/select/image", data={"image": (self.png(), "a.png")}, content_type="multipart/form-data")
        key = reply.get_json()["key"]
        with mock.patch("pipelines.image.segment.select", return_value=Image.new("L", (800, 600), 255)) as select:
            mask = self.client.post("/api/select", json={"key": key, "points": [[10, 20, True]]})
        self.assertEqual(mask.mimetype, "image/png")
        self.assertEqual(select.call_args[0][1], [(10.0, 20.0, True)])
        self.assertEqual(self.client.post("/api/select", json={"key": "gone", "points": [[1, 1, True]]}).status_code, 410)


if __name__ == "__main__":
    unittest.main()


class InpaintMaskTest(unittest.TestCase):
    """A workflow's inpaint mode: what's painted over image 1 becomes transparent, which Load Image takes as its mask."""

    def test_the_painted_part_is_transparent_after_the_same_fit(self):
        with tempfile.TemporaryDirectory() as folder:
            source, painted, out = (os.path.join(folder, name) for name in ("source.png", "mask.png", "out.png"))
            Image.new("RGB", (400, 200), "blue").save(source)
            mask = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
            # The right quarter painted. Fitted to a square, only the middle 200 columns are kept, which it doesn't reach.
            ImageDraw.Draw(mask).rectangle([300, 0, 399, 199], fill=(230, 40, 40, 255))
            mask.save(painted)
            fitted = media.fit(source, 100, 100, os.path.join(folder, "fitted.png"))
            media.with_mask(fitted, painted, (100, 100), out)
            with Image.open(out) as image:
                self.assertEqual((image.mode, image.size), ("RGBA", (100, 100)))
                alpha = image.getchannel("A")
                self.assertEqual((alpha.getpixel((10, 50)), alpha.getpixel((90, 50))), (255, 255),
                                 "the middle square, which the paint doesn't reach, is kept")
                self.assertEqual(image.getpixel((10, 50))[:3], (0, 0, 255))

    def test_painting_inside_the_crop_is_redrawn(self):
        with tempfile.TemporaryDirectory() as folder:
            source, painted, out = (os.path.join(folder, name) for name in ("source.png", "mask.png", "out.png"))
            Image.new("RGB", (200, 200), "green").save(source)
            mask = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
            ImageDraw.Draw(mask).rectangle([0, 0, 99, 199], fill=(40, 90, 235, 255))
            mask.save(painted)
            media.with_mask(source, painted, None, out)
            with Image.open(out) as image:
                alpha = image.getchannel("A")
                self.assertEqual((alpha.getpixel((20, 100)), alpha.getpixel((180, 100))), (0, 255), "painted: transparent; the rest kept")
                self.assertEqual(image.getpixel((20, 100))[:3], (0, 128, 0), "the colour under the paint stays for the model to start from")


class ModelFilePillsTest(unittest.TestCase):
    """A set's pills say the files it ran, plainly: from its settings, or what ComfyUI wrote into its image."""

    def png_with(self, folder, api, size=(64, 48)):
        from PIL import PngImagePlugin
        path = os.path.join(folder, "made.png")
        info = PngImagePlugin.PngInfo()
        info.add_text("prompt", json.dumps(api))
        Image.new("RGB", size, "red").save(path, pnginfo=info)
        return path

    API = {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "krea2_turbo_int8_convrot.safetensors"}},
           "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_4b_fp8_scaled.safetensors", "type": "krea2"}},
           "3": {"class_type": "VAELoader", "inputs": {"vae_name": "krea2RealVae_v10.safetensors"}}}

    def test_a_set_made_before_its_settings_kept_them_reads_its_image(self):
        from core import model_files, pills
        with tempfile.TemporaryDirectory() as folder:
            self.png_with(folder, self.API)
            state = mock.Mock(shots=[{"file": "made.png"}], output_dir=folder, options={"steps": "8"})
            self.assertEqual(pills.image_files(state), [("model", "Model: Krea-2 Turbo int8"), ("encoder", "Encoder: Qwen3-VL 4B fp8"),
                                                        ("vae", "VAE: Krea2Real")])
            # Its settings, where it kept them, before what its image says.
            state.options = {"vae_file": "qwen_image_vae.safetensors"}
            self.assertIn(("vae", "VAE: Qwen-Image"), pills.image_files(state))
            self.assertEqual(model_files.friendly("some_new_model_with_a_very_long_name_v2_fp8_scaled.safetensors")[-1], "…",
                             "one it doesn't know: its name, cut to fit")

    def test_cropping_to_the_size_asked_keeps_what_comfyui_wrote_in_it(self):
        from core import model_files
        with tempfile.TemporaryDirectory() as folder:
            path = self.png_with(folder, self.API, size=(64, 64))
            media.trim(path, (64, 64), (64, 48))
            with Image.open(path) as image:
                self.assertEqual(image.size, (64, 48))
            self.assertEqual(model_files.files_of_image(path)["model"], "krea2_turbo_int8_convrot.safetensors")
