import json
import os
import tempfile
import unittest
from unittest import mock

import fakes  # Set isolated paths before importing the application.

from panel import video
from pipelines.video import h3_multishot, h3_prompt, main, paths
from pipelines.video.run_state import RunState


def graph():
    return {
        "1": {"class_type": "UNETLoader", "inputs": {}},
        "2": {"class_type": "CLIPLoader", "inputs": {}},
        "3": {"class_type": "VAELoader", "inputs": {}},
        "4": {"class_type": "VAELoader", "inputs": {}},
        "5": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
            "clip": ["2", 0], "vae": ["3", 0], "audio_vae": ["4", 0]}},
        "6": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["5", 0]}},
        "7": {"class_type": "SamplerCustomAdvanced", "inputs": {"guider": ["6", 0], "latent_image": ["5", 1]}},
    }


class MultishotTest(unittest.TestCase):
    def test_graph_uses_separate_prompts_and_preserves_model_sources(self):
        source = graph()
        result = h3_multishot.build(source, ["First", "Then"], ["a.png", "b.png"], 10, 864, 480, 17, True, 12)
        sampler = next(node for node in result.values() if node["class_type"] == h3_multishot.SAMPLER)
        inputs = sampler["inputs"]
        self.assertEqual(json.loads(inputs["script"]), {"prompts": ["First", "Then"]})
        self.assertEqual((inputs["shot_count"], inputs["frames_per_shot"], inputs["seed"], inputs["steps"]),
                         (0, h3_prompt.clip_frames(10), 17, 12))
        self.assertEqual(inputs["model"], ["1", 0])
        self.assertEqual(result[inputs["reference_images"][0]]["class_type"], "ImageBatch")
        self.assertEqual(result[inputs["start_image"][0]]["class_type"], "ImageScale")
        save = next(node for node in result.values() if node["class_type"] == "VHS_VideoCombine")
        self.assertEqual(save["inputs"]["audio"], [next(k for k, v in result.items() if v is sampler), 1])
        self.assertFalse(save["inputs"]["save_output"])
        self.assertNotIn("5", result)
        self.assertIn("5", source, "the saved workflow is not modified")

    def test_structured_prompts_are_flattened_for_the_samplers_own_sections(self):
        prompt = ("subject_definitions:\n<Subject 1> is a woman from <Picture 1>: short red hair.\n\n"
                  "summary:\n[reference generation] She takes off the coat.\n\n"
                  "retention_analysis:\n<Subject 1> (appears in [Shot 2]): fully_preserved - red hair, grey coat.\n\n"
                  "detailed_description:\nLive-action. [Shot 2] She unbuttons the grey coat and drops it.\n\n"
                  "overall_soundscape:\nRain on glass.\n\nnon_diegetic_music: N/A")
        flat = h3_multishot.sampler_prompt(prompt, ["a.png"])
        for section in ("subject_definitions:", "summary:", "retention_analysis:", "detailed_description:",
                        "non_diegetic_music", "[reference generation]", "fully_preserved", "[Shot 2]"):
            self.assertNotIn(section, flat)
        for kept in ("Live-action. [Shot 1] She unbuttons", "She takes off the coat.", "<Picture 1>: short red hair",
                     "Sound: Rain on glass."):
            self.assertIn(kept, flat)
        self.assertTrue(flat.startswith("Live-action."))
        text = "integrated_multimodal_description: [Shot 3] A pan.\n\noverall_soundscape: Wind."
        self.assertEqual(h3_multishot.sampler_prompt(text, []), text.replace("[Shot 3]", "[Shot 1]"),
                         "without references the sampler adds no sections, so the prompt goes as it is")
        result = h3_multishot.build(graph(), [prompt], ["a.png"], 10, 864, 480, 1)
        sampler = next(node for node in result.values() if node["class_type"] == h3_multishot.SAMPLER)
        self.assertEqual(json.loads(sampler["inputs"]["script"])["prompts"], [flat])
        from pipelines.video.comfy import ComfyClient
        client = object.__new__(ComfyClient)
        client.workflow = graph()
        captured = mock.Mock()
        with mock.patch.object(client, "_run", return_value={}) as submitted, \
                mock.patch.object(client, "_download", return_value="take.mp4"):
            client.render_take([prompt], ["a.png"], 10, 864, 480, "take", 1, on_prompt=captured)
        captured.assert_called_once_with([flat])
        sent = next(node for node in submitted.call_args.args[0].values() if node["class_type"] == h3_multishot.SAMPLER)
        self.assertEqual(json.loads(sent["inputs"]["script"])["prompts"], captured.call_args.args[0])

    def test_unsupported_graphs_and_missing_start_frame_are_refused(self):
        self.assertFalse(h3_multishot.supports({}))
        with self.assertRaisesRegex(RuntimeError, "first frame"):
            h3_multishot.build(graph(), ["x"], [], 10, 864, 480, 1, True)

    def test_form_requires_fixed_length_and_rejects_preview_or_enhancement(self):
        flags, error = video.build_options({"start": "multishot"})
        self.assertIn("fixed", error)
        form = {"start": "multishot", "clip_seconds": "10-10", "clip_fixed": "1",
                "h3_first_frame": "1", "h3_multishot_steps": "12"}
        flags, error = video.build_options(form)
        self.assertIsNone(error)
        self.assertIn("--h3-first-frame", flags)
        self.assertEqual(flags[flags.index("--h3-multishot-steps") + 1], "12")
        for extra in ({"try_first": "1"}, {"h3_enhance": "render"}, {"h3_multishot_steps": "51"}):
            self.assertIsNotNone(video.build_options({**form, **extra})[1])

    def test_whole_take_is_saved_reloaded_and_redone_as_one_job(self):
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(paths, "RUNS_DIR", os.path.join(temp, "runs")), \
                mock.patch.object(paths, "OUTPUT_DIR", os.path.join(temp, "output")), \
                mock.patch.object(main.media, "clip_problem", return_value=None), \
                mock.patch.object(main.media, "duration", return_value=21) as duration, \
                mock.patch.object(main.requests, "get") as get:
            os.makedirs(paths.OUTPUT_DIR)
            get.return_value.json.return_value = {"H3MultishotSampler": {}}
            state = RunState.new("brief", 20, "multishot", 864, 480, image_count=0)
            state.shots = [{"title": "First", "seconds": 10, "prompt": "One", "seed": 12},
                           {"title": "Next", "seconds": 10, "prompt": "Two", "seed": 13}]
            state.title = "Test"
            state.save()
            comfy = mock.Mock(url="http://comfy")
            def save_take(prompts, images, seconds, width, height, path, seed, first_frame, steps, on_prompt=None):
                if on_prompt:
                    on_prompt(prompts)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path + ".mp4", "wb") as file:
                    file.write(b"master")
                return path + ".mp4"
            comfy.render_take.side_effect = save_take
            main.render_take(state, comfy)
            self.assertEqual(comfy.render_take.call_args.args[0], ["One", "Two"])
            loaded = RunState.load(state.id)
            self.assertEqual(loaded.next_stage(), "Stitching")
            self.assertEqual(loaded.kept_seconds(), 20)
            output = main.stitch_film(loaded)
            with open(output, "rb") as file:
                self.assertEqual(file.read(), b"master")
            loaded.redo(1)
            loaded.save()
            self.assertEqual(RunState.load(state.id).next_stage(), "Clips")
            duration.return_value = 19
            with self.assertRaisesRegex(RuntimeError, "expected about"):
                main.render_take(loaded, comfy)
            self.assertIsNone(RunState.load(state.id).take_file)

    def test_resumed_take_rejects_preview_and_individual_redo(self):
        state = RunState.new("brief", 20, "multishot", 864, 480)
        state.shots = [{"seconds": 10, "prompt": "One"}, {"seconds": 10, "prompt": "Two"}]
        with mock.patch.object(RunState, "load", return_value=state):
            with self.assertRaisesRegex(RuntimeError, "only the first clip"):
                main.run(main.parse_args(["--resume", "run", "--first-only"]))
            with self.assertRaisesRegex(RuntimeError, "whole take"):
                main.run(main.parse_args(["--resume", "run", "--redo", "2"]))


if __name__ == "__main__":
    unittest.main()
