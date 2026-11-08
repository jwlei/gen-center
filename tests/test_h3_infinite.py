import os
import tempfile
import unittest
from unittest import mock

import fakes  # noqa: F401  Set isolated paths before importing the application.

from panel import video
from pipelines.video import h3_infinite, main, paths
from pipelines.video.run_state import RunState
from test_h3_multishot import graph

# ComfyUI's /object_info for the suite's nodes, cut down to what the graph builder reads.
CONNECTION = ["IMAGE", {}]
INFO = {
    h3_infinite.START: {"input": {"required": {"prompt": ["STRING", {"multiline": True}], "width": ["INT", {"default": 1344}],
                                               "duration": ["FLOAT", {"default": 10.0}],
                                               "ref_image_size": [["match", "max"], {"default": "match"}]},
                                  "optional": {"first_frame": CONNECTION, "last_frame": CONNECTION}}},
    h3_infinite.CONTINUE: {"input": {"required": {"masked_context_frames": [["39", "90", "141", "192"], {}],
                                                  "duration_mode": ["COMBO", {"options": ["Net New Content", "Total Generation"]}],
                                                  "previous_latent": ["LATENT", {}]}}},
    h3_infinite.ANALYZE: {"input": {"required": {"images": CONNECTION, "preset": [["Balanced", "Strict"], {}],
                                                 "min_freeze_frames": ["INT", {"default": 3}]}}},
    h3_infinite.OUTPUT: {"input": {"required": {"images": CONNECTION, "output_mode": [["Full", "Stitch Ready"], {}]},
                                   "optional": {"head_context_frames": ["INT", {"default": 0, "forceInput": True}]}}},
    h3_infinite.SAVE: {"input": {"required": {"filename_prefix": ["STRING", {"default": "h3_continuous/clip"}],
                                              "clip_index": ["INT", {"default": 1}]}}},
    h3_infinite.LOAD: {"input": {"required": {"latent_path": ["STRING", {"default": "h3_continuous"}],
                                              "clip_index": ["INT", {"default": 1}]}}},
    h3_infinite.STITCH: {"input": {"required": {"latent_prefix": ["STRING", {"default": "h3_continuous/clip"}],
                                                "video_crossfade_frames": ["INT", {"default": 4}],
                                                "last_clip": ["INT", {"default": 0}]}}},
}


def of(result, kind):
    return [(node_id, node) for node_id, node in result.items() if node["class_type"] == kind]


class GraphTest(unittest.TestCase):
    def test_defaults_are_the_nodes_own_and_leave_connections_out(self):
        self.assertEqual(h3_infinite.defaults(INFO[h3_infinite.CONTINUE]),
                         {"masked_context_frames": "39", "duration_mode": "Net New Content"})
        self.assertEqual(h3_infinite.defaults(INFO[h3_infinite.OUTPUT]), {"output_mode": "Full"},
                         "an input that must be connected gets no value")

    def test_first_clip_starts_from_its_frames_on_the_fl2va_model_and_saves_slot_1(self):
        result = h3_infinite.build_clip(graph(), INFO, "run_1", 0, "She turns", 6, 864, 480, 7, "a.png", "b.png")
        [(start_id, start)] = of(result, h3_infinite.START)
        inputs = start["inputs"]
        self.assertEqual((inputs["clip"], inputs["vae"], inputs["prompt"], inputs["duration"], inputs["width"]),
                         (["2", 0], ["3", 0], "She turns", 6.0, 864), "the workflow's encoder and video VAE, our size")
        for frame, image in (("first_frame", "a.png"), ("last_frame", "b.png")):
            scale = result[inputs[frame][0]]
            self.assertEqual((scale["class_type"], scale["inputs"]["width"], scale["inputs"]["height"]), ("ImageScale", 864, 480))
            self.assertEqual(result[scale["inputs"]["image"][0]]["inputs"]["image"], image)
        self.assertFalse(of(result, h3_infinite.LOAD) or of(result, h3_infinite.CONTINUE))
        [(_, unet)] = of(result, "UNETLoader")
        self.assertEqual(unet["inputs"]["unet_name"], h3_infinite.FL2VA_MODEL)
        self.assertNotIn("1", result, "the reference model and what hangs off it stay out")
        [(_, save)] = of(result, h3_infinite.SAVE)
        self.assertEqual((save["inputs"]["filename_prefix"], save["inputs"]["clip_index"]), ("autogen_h3_infinite/run_1/clip", 1))
        self.assertNotIn("head_context_frames", save["inputs"])
        [(_, sampler)] = of(result, "SamplerCustomAdvanced")
        self.assertEqual(sampler["inputs"]["latent_image"], [start_id, 1])
        [(_, noise)] = of(result, "RandomNoise")
        self.assertEqual(noise["inputs"]["noise_seed"], 7)
        [(_, analyze)] = of(result, h3_infinite.ANALYZE)
        self.assertEqual(analyze["inputs"]["preset"], "Balanced")
        [(output_id, output)] = of(result, h3_infinite.OUTPUT)
        self.assertEqual(output["inputs"]["output_mode"], "Full")
        [(_, combine)] = of(result, "VHS_VideoCombine")
        self.assertEqual((combine["inputs"]["images"], combine["inputs"]["audio"]), ([output_id, 0], [output_id, 1]))
        self.assertFalse(combine["inputs"]["save_output"])

    def test_a_later_clip_continues_from_the_one_before_and_the_cache_knows_its_version(self):
        result = h3_infinite.build_clip(graph(), INFO, "run_1", 2, "She sits", 5, 864, 480, 7, "a.png", None, "shot_002.mp4@1")
        [(load_id, load)] = of(result, h3_infinite.LOAD)
        self.assertEqual((load["inputs"]["latent_path"], load["inputs"]["clip_index"], load["inputs"]["autogen_previous"]),
                         ("autogen_h3_infinite/run_1", 2, "shot_002.mp4@1"))
        [(cont_id, cont)] = of(result, h3_infinite.CONTINUE)
        inputs = cont["inputs"]
        self.assertEqual((inputs["previous_latent"], inputs["handover"]), ([load_id, 0], [load_id, 3]))
        self.assertEqual((inputs["masked_context_frames"], inputs["duration_mode"], inputs["audio_tail_carryover"]),
                         ("39", "Net New Content", "Full Previous Tail"))
        self.assertNotIn("first_frame", inputs, "only clip 1 has a first frame: the rest continue")
        self.assertNotIn("last_frame", inputs)
        [(_, save)] = of(result, h3_infinite.SAVE)
        self.assertEqual((save["inputs"]["clip_index"], save["inputs"]["head_context_frames"]), (3, [cont_id, 2]))
        [(_, output)] = of(result, h3_infinite.OUTPUT)
        self.assertEqual(output["inputs"]["head_context_frames"], [cont_id, 2])
        changed = h3_infinite.build_clip(graph(), INFO, "run_1", 2, "She sits", 5, 864, 480, 7, previous="shot_002.mp4@2")
        self.assertNotEqual(of(changed, h3_infinite.LOAD)[0][1]["inputs"], load["inputs"])

    def test_the_film_is_stitched_from_every_saved_clip(self):
        result = h3_infinite.build_stitch(graph(), INFO, "run_1", 4, "autogen_h3_infinite/run_1/film_9")
        [(_, stitch)] = of(result, h3_infinite.STITCH)
        inputs = stitch["inputs"]
        self.assertEqual((inputs["video_vae"], inputs["audio_vae"]), (["3", 0], ["4", 0]))
        self.assertEqual((inputs["latent_prefix"], inputs["first_clip"], inputs["last_clip"], inputs["filename_prefix"],
                          inputs["video_crossfade_frames"]),
                         ("autogen_h3_infinite/run_1/clip", 1, 4, "autogen_h3_infinite/run_1/film_9", 4))

    def test_unsupported_workflows_and_empty_prompts_are_refused(self):
        self.assertFalse(h3_infinite.supports({}))
        self.assertTrue(h3_infinite.supports(graph()))
        with self.assertRaisesRegex(RuntimeError, "prompt"):
            h3_infinite.build_clip(graph(), INFO, "run_1", 0, " ", 5, 864, 480, 1)


class ProgressTest(unittest.TestCase):
    def test_every_node_and_step_says_what_it_is_doing(self):
        from panel import server
        for node in h3_infinite.NODES:
            self.assertIn(node, server.COMFY_LABELS, f"{node} has a hint while ComfyUI runs it")
        job = server.Job()
        job.pipeline, job.eta = "video", mock.Mock()
        job._track("▶ Stage 3/3: Stitching")
        job._track("🧵 Stitching the film...")
        job._track("   🧵 H3 Infinite is stitching 3 saved clips in ComfyUI...")
        self.assertEqual(job.progress["action"], "Stitching in ComfyUI")

    def test_its_clips_and_stitching_are_timed_apart(self):
        from pipelines.video.run_eta import RunEta
        with tempfile.TemporaryDirectory() as temp:
            eta = RunEta(["--start", "infinite", "--duration", "15"], os.path.join(temp, "timings.json"))
            self.assertTrue(all(key.startswith("infinite | ") for key in eta.render_keys))
            self.assertEqual(eta._part_key(), "part | infinite")
            plain = RunEta(["--duration", "15"], os.path.join(temp, "timings.json"))
            self.assertFalse(any(key.startswith("infinite") for key in plain.render_keys))
            self.assertEqual(plain._part_key(), "part")


class RunTest(unittest.TestCase):
    def test_images_are_the_first_frame_then_where_each_clip_ends(self):
        state = RunState.new("brief", 15, "infinite", 864, 480, image_count=3)
        state.shots = [{"seconds": 5, "prompt": "x"}] * 3
        first, second, third = state.image_paths
        self.assertEqual(main.clip_images(state, 0), [first, second])
        self.assertEqual(main.clip_images(state, 1), [None, third])
        self.assertEqual(main.clip_images(state, 2), [None, None])

    def test_clips_continue_one_another_redo_drops_the_rest_and_the_suite_stitches(self):
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(paths, "RUNS_DIR", os.path.join(temp, "runs")), \
                mock.patch.object(paths, "OUTPUT_DIR", os.path.join(temp, "output")), \
                mock.patch.object(main.media, "clip_problem", return_value=None), \
                mock.patch.object(main, "ComfyClient") as client:
            os.makedirs(paths.OUTPUT_DIR)
            state = RunState.new("brief", 10, "infinite", 864, 480, image_count=0)
            state.shots = [{"title": "First", "seconds": 5, "prompt": "One", "seed": 12},
                           {"title": "Next", "seconds": 5, "prompt": "Two", "seed": 13}]
            state.title = "Test"
            state.save()
            comfy = mock.Mock(url="http://comfy")

            def save_clip(run_id, index, prompt, seconds, width, height, path, seed, first, last, previous=None):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path + ".mp4", "wb") as file:
                    file.write(prompt.encode())
                return path + ".mp4"
            comfy.render_continuation.side_effect = save_clip
            self.assertTrue(main.render_clips(state, comfy))
            calls = comfy.render_continuation.call_args_list
            self.assertEqual([(c.args[0], c.args[1], c.args[2]) for c in calls], [(state.id, 0, "One"), (state.id, 1, "Two")])
            self.assertIsNone(calls[0].kwargs["previous"])
            self.assertTrue(calls[1].kwargs["previous"].startswith("shot_001.mp4@"), "clip 2 names the clip 1 it continues")
            comfy.render.assert_not_called()

            loaded = RunState.load(state.id)
            self.assertEqual(loaded.next_stage(), "Stitching")

            def stitched(run_id, count, save_as):
                with open(save_as + ".mp4", "wb") as file:
                    file.write(b"film")
                return save_as + ".mp4"
            client.return_value.stitch_continuation.side_effect = stitched
            output = main.stitch_film(loaded)
            self.assertEqual(client.return_value.stitch_continuation.call_args.args[:2], (state.id, 2))
            with open(output, "rb") as file:
                self.assertEqual(file.read(), b"film")

            loaded.redo(0)
            self.assertEqual(loaded.clips, {}, "every clip after a redone one continued from it, so they go too")

    def test_options_refuse_what_it_cannot_take(self):
        flags, error = video.build_options({"start": "infinite"})
        self.assertIsNone(error)
        self.assertEqual(flags[flags.index("--start") + 1], "infinite")
        self.assertIsNotNone(video.build_options({"start": "infinite", "h3_enhance": "render"})[1])
        with self.assertRaises(SystemExit):
            main.parse_args(["--start", "infinite", "--narration", "Hello", "x.png", "prompt"])


if __name__ == "__main__":
    unittest.main()
