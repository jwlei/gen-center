"""
The panel in-process, starting the real main.py as a real process, which talks to
a fake ComfyUI and a fake Claude and runs real ffmpeg. Stop really kills it.
"""
import gzip
import io
import json
import os
import types
from datetime import datetime, timedelta
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fakes import (OBJECT_INFO, close, fake_claude, fake_comfy, make_clip, plan_reply, reference_workflow, saved_workflow,
                   text_only_workflow)

import ffmpeg
from PIL import Image

from panel import app as _both_pipelines  # noqa: F401
from panel import image as image_panel, shorts as shorts_panel
from panel import server as webapp
from panel import video as video_panel
from pipelines.shorts.paths import OUTPUT_DIR as SHORTS_READY, UPLOADED_DIR as SHORTS_UPLOADED
from pipelines.shorts import topic_history
from pipelines.video import h3_prompt, media, paths
from pipelines.video import output_metadata, upscale as video_upscale
from pipelines.video import main as video_main
from core import variety
from pipelines.video.run_state import RunState, list_runs


def make_clip_audio(path, seconds):
    ffmpeg.input(f"sine=f=440:d={seconds}", f="lavfi").output(path).run(overwrite_output=True, quiet=True)


def png_bytes(color=(10, 200, 30)):
    buffer = io.BytesIO()
    Image.new("RGB", (640, 368), color).save(buffer, format="PNG")
    return buffer.getvalue()


SAVED_OPTIONS = [{"id": "steps", "kind": "number", "label": "Steps", "default": "20", "min": 1, "max": 150, "step": 1, "advanced": True},
                 {"id": "negative", "kind": "text", "label": "Negative prompt", "default": "saved negative", "advanced": True}]


class RestartReasonTest(unittest.TestCase):
    def job(self, *texts):
        return types.SimpleNamespace(first_line=0, lines=[{"n": n, "text": text} for n, text in enumerate(texts, 1)])

    def test_exit_one_from_a_crash_restarts_comfyui(self):
        self.assertEqual(webapp.restart_reason(self.job("   🖼️ Image 5/24", "Traceback (most recent call last):"), 1), "exit code 1")

    def test_a_failure_before_comfyui_does_not_restart_it(self):
        planning = self.job("▶ Stage 1/3: Prompts", "🧠 claude is writing 4 prompts...", "❌ Set ANTHROPIC_API_KEY in .env")
        self.assertIsNone(webapp.restart_reason(planning, 1), "a fresh ComfyUI can't fix a missing key")
        self.assertEqual(webapp.restart_reason(self.job("🎛️ ComfyUI · started a workflow of 35 nodes", "Traceback"), 1), "exit code 1")

    def test_settings_comfyui_refuses_do_not_restart_it(self):
        refused = self.job("   🖼️ Image 5/24", "      ❌ Can't use the LoRA Krea2\\KNPV3_1.safetensors: LoRA is one of a, b.")
        self.assertIsNone(webapp.restart_reason(refused, 1))
        plain, _ = webapp.explain_failure(refused, 1)
        self.assertTrue(plain.startswith("A LoRA this run saved"), plain)

    def test_aimdo_still_restarts_even_beside_a_refused_setting(self):
        job = self.job("aimdo memory compile error", "LoRA is one of a, b.")
        self.assertEqual(webapp.restart_reason(job, 1), "ComfyUI's aimdo memory compile error")


class QueueTopTest(unittest.TestCase):
    def test_lora_video_comparison_estimate_sums_complete_videos(self):
        from core import workflow_options
        options = workflow_options.lora_options("0", "krea_a.safetensors", 1, ["krea_a.safetensors"])
        takes = {"min_images": 0, "max_images": 0, "max_videos": 0, "max_audios": 0, "options": options}
        form = {"prompt": "same prompt", "duration": "10", "lora_strength_test": "1", "lora_test_step": "1"}
        with webapp.app.test_request_context("/api/estimate/video", method="POST", data=form), \
             mock.patch.object(video_panel, "chosen_workflow", return_value=({}, takes, None)), \
             mock.patch.object(video_panel, "private_mode", return_value=False), \
             mock.patch.object(video_panel, "RunEta") as eta:
            eta.return_value.plan.side_effect = [
                {"total": 20, "clips": 2, "steps": [{"name": "Render", "seconds": 20}]},
                {"total": 30, "clips": 2, "steps": [{"name": "Render", "seconds": 30}]},
            ]
            result = video_panel.estimate.__wrapped__()
        self.assertTrue(result["ok"])
        self.assertEqual((result["videos"], result["clips"], result["total"]), (2, 4, 50))
        self.assertEqual(result["steps"], [{"name": "Render", "seconds": 50}])
        self.assertEqual([json.loads(call.args[2]["COMFYUI_OPTIONS"])["lora_strength"]
                          for call in eta.call_args_list], ["1", "2"])

    def test_a_page_error_is_kept_in_a_log_file(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(webapp, "LOGS_DIR", folder):
            client = webapp.app.test_client()
            with mock.patch.object(webapp, "password_ok", return_value=True, create=True):
                reply = client.post("/api/page-error", json={"error": "uncaught | x is not defined"})
            self.assertEqual(reply.status_code, 200)
            with open(os.path.join(folder, "page_errors.log"), encoding="utf-8") as log:
                self.assertIn("uncaught | x is not defined", log.read())

    def test_lora_image_comparisons_queue_one_set_and_ignore_amount(self):
        from core import lora_tests, workflow_options
        options = workflow_options.lora_options("0", "krea_a.safetensors", 1, ["krea_a.safetensors", "krea_b.safetensors"])
        takes = {"min_images": 0, "max_images": 0, "size": True, "options": options}
        form = {"prompt": "same prompt", "count": "15", "lora_strength_test": "1", "lora_style_test": "1",
                "lora_test_step": "1", "seed": "0", "start_later": "1"}
        with webapp.app.test_request_context("/generate/image", method="POST", data=form), \
             mock.patch.object(image_panel, "chosen_workflow", return_value=({}, takes, None)), \
             mock.patch.object(image_panel, "run_queue", self.queue), mock.patch.object(webapp, "run_queue", self.queue), \
             mock.patch.object(image_panel, "private_mode", return_value=False), mock.patch.object(webapp, "private_mode", return_value=False), \
             mock.patch.object(image_panel, "clean_inputs"), mock.patch.object(image_panel, "RunEta") as eta:
            eta.return_value.plan.return_value = {"total": 10}
            result = image_panel.generate.__wrapped__()
        self.assertTrue(result["ok"])
        self.assertEqual(len(self.queue.items), 1)
        item = self.queue.items[0]
        self.assertTrue(item["label"].startswith("4 images"))
        self.assertEqual(len(lora_tests.in_env(item["env"])), 4)
        self.assertEqual(item["argv"][item["argv"].index("--count") + 1], "1")
        self.assertEqual(item["argv"][item["argv"].index("--seed") + 1], "0")
        self.assertIn("--direct", item["argv"])
        # Named as what it is in the queue, not "exact prompt"; one queued before it was, the same once read.
        self.assertIn(" · LoRA comparison", item["detail"])
        self.assertNotIn("exact prompt", item["detail"])
        older = {**item, "detail": item["detail"].replace("LoRA comparison", "exact prompt")}
        webapp.named_comparison(older)
        self.assertEqual(older["detail"], item["detail"])

    def test_a_workflow_comparison_queues_one_set_through_every_text_to_image_workflow(self):
        from core import workflow_tests
        entry = lambda name, low, high: {"pipeline": "image", "name": name, "label": name, "path": f"/w/{name}.json",
                                         "takes": {"min_images": low, "max_images": high, "size": True, "options": []}}
        entries = [entry("Krea2_T2I", 0, 0), entry("Moss_T2I", 0, 0), entry("Qwen_Edit", 1, 1)]
        form = {"prompt": "same prompt", "count": "15", "prompt_mode": "llm", "llm": "gemini", "workflow_test_t2i": "on",
                "lora_strength_test": "on", "opt_steps": "4", "start_later": "1"}
        with webapp.app.test_request_context("/generate/image", method="POST", data=form), \
             mock.patch.object(image_panel, "saved_workflows", return_value=entries), \
             mock.patch.object(image_panel, "run_queue", self.queue), mock.patch.object(webapp, "run_queue", self.queue), \
             mock.patch.object(image_panel, "private_mode", return_value=False), mock.patch.object(webapp, "private_mode", return_value=False), \
             mock.patch.object(image_panel, "clean_inputs"), mock.patch.object(image_panel, "RunEta") as eta:
            eta.return_value.plan.return_value = {"total": 10}
            result = image_panel.generate.__wrapped__()
        self.assertTrue(result["ok"], result)
        item = self.queue.items[0]
        self.assertTrue(item["label"].startswith("2 images"))
        self.assertEqual([test["label"] for test in workflow_tests.in_env(item["env"])], ["Krea2_T2I", "Moss_T2I"])
        self.assertEqual(item["env"]["COMFYUI_WORKFLOW"], "/w/Krea2_T2I.json")
        self.assertNotIn("GEN_CENTER_LORA_TEST", item["env"], "workflows compared, not LoRAs")
        self.assertEqual(item["argv"][item["argv"].index("--count") + 1], "1")
        self.assertIn("--direct", item["argv"], "your prompt as written")
        self.assertIn("--seed", item["argv"], "one seed for all")
        self.assertNotIn("--option", item["argv"], "each at its own defaults")
        self.assertIn("workflow comparison · All T2I workflows", item["detail"])

    def test_an_llm_comparison_queues_one_image_for_each_prompt_model(self):
        from core import llm_tests
        takes = {"min_images": 0, "max_images": 0, "size": True, "options": []}
        models = [{"id": "gemma-4-12b", "label": "Gemma 4 12B (vision)", "vision": True},
                  {"id": "qwen3-14b", "label": "Qwen3 14B (text only)", "vision": False}]
        form = {"prompt": "a lighthouse", "count": "15", "prompt_mode": "direct", "llm": "prompt_enhancer", "review": "1",
                "llm_test": "on", "local_model": "gemma-4-12b", "start_later": "1"}
        with webapp.app.test_request_context("/generate/image", method="POST", data=form), \
             mock.patch.object(image_panel, "chosen_workflow", return_value=({"COMFYUI_WORKFLOW": "/w/image_Krea2.json"}, takes, None)), \
             mock.patch.object(image_panel.settings, "local_models", return_value=models), \
             mock.patch.object(image_panel.planner, "llm_configured", return_value=True), \
             mock.patch.object(image_panel, "run_queue", self.queue), mock.patch.object(webapp, "run_queue", self.queue), \
             mock.patch.object(image_panel, "private_mode", return_value=False), mock.patch.object(webapp, "private_mode", return_value=False), \
             mock.patch.object(image_panel, "clean_inputs"), mock.patch.object(image_panel, "RunEta") as eta:
            eta.return_value.plan.return_value = {"total": 10}
            result = image_panel.generate.__wrapped__()
        self.assertTrue(result["ok"], result)
        item = self.queue.items[0]
        self.assertEqual([(test["llm"], test["label"]) for test in llm_tests.in_env(item["env"])],
                         [("gemini", "Gemini"), ("local", image_panel.settings.short_name("gemma-4-12b")), ("local", "Qwen3 14B")])
        argv = item["argv"]
        self.assertEqual(argv[argv.index("--count") + 1], "1")
        self.assertNotIn("--direct", argv, "written, whatever the prompt mode said")
        self.assertNotIn("--plan-only", argv, "nothing to read first")
        self.assertIn("--seed", argv, "one seed for all")
        self.assertTrue(item["label"].startswith("3 images"))
        self.assertIn("LLM comparison", item["detail"])
        # With an image, only those that can see it; and never beside a comparison that uses your prompt as written.
        with webapp.app.test_request_context("/", method="POST", data={"llm_test": "on"}), \
             mock.patch.object(image_panel.settings, "local_models", return_value=models), \
             mock.patch.object(image_panel.planner, "llm_configured", return_value=False):
            self.assertEqual([test["label"] for test in image_panel.compared_llms(webapp.request.form, 1)[0]], [image_panel.settings.short_name("gemma-4-12b")])
        self.assertIn("can't go with", image_panel.compared_llms({"llm_test": "on", "workflow_test_t2i": "on"}, 0)[1])

    def test_lora_image_comparison_pills_name_the_loras_tested(self):
        from types import SimpleNamespace
        from core import lora_tests, pills
        tests = [{"lora": "1", "lora_name": name, "lora_strength": strength}
                 for name in ("Krea2_a.safetensors", "Krea2_b.safetensors") for strength in ("0.5", "1.0", "2.0")]
        shots = lora_tests.shots({"prompt": "p", "title": "t"}, tests, 7)
        # The set's own LoRA setting (on, another file) is none of those tested: it isn't what its pills say.
        state = SimpleNamespace(shots=shots, workflow="w.json", options={"lora": "1", "lora_name": "other.safetensors"})
        with mock.patch.object(pills.workflow_options, "loras_used", return_value=["other (1)"]) as used:
            self.assertEqual(pills.image_loras(state), ["a (0.5-2)", "b (0.5-2)"])
            used.assert_not_called()
            self.assertEqual(lora_tests.shot_lora(shots[1]), "a (1)", "each image: its own LoRA and strength")
            self.assertIsNone(lora_tests.shot_lora({"prompt": "p"}))
            state.shots = [{"prompt": "p"}]
            self.assertEqual(pills.image_loras(state), ["other (1)"], "a set that isn't a comparison: its workflow's")

    def test_lora_video_comparisons_queue_complete_videos_with_one_seed(self):
        from core import workflow_options
        options = workflow_options.lora_options("0", "krea_a.safetensors", 1, ["krea_a.safetensors", "krea_b.safetensors"])
        options.append({"id": "additional_loras", "kind": "lora_stack", "default": "[]",
                        "choices": ["krea_a.safetensors", "krea_b.safetensors"], "min": -2, "max": 2})
        takes = {"min_images": 0, "max_images": 0, "max_videos": 0, "max_audios": 0, "options": options}
        stack = json.dumps([{"on": True, "name": "krea_b.safetensors", "strength": "0.5"}])
        form = {"prompt": "same prompt", "duration": "10", "lora_strength_test": "1", "lora_style_test": "1",
                "lora_test_step": "1", "seed": "0", "opt_additional_loras": stack, "start_later": "1"}
        with webapp.app.test_request_context("/generate/video", method="POST", data=form), \
             mock.patch.object(video_panel, "chosen_workflow", return_value=({}, takes, None)), \
             mock.patch.object(video_panel, "run_queue", self.queue), mock.patch.object(webapp, "run_queue", self.queue), \
             mock.patch.object(video_panel, "private_mode", return_value=False), mock.patch.object(webapp, "private_mode", return_value=False), \
             mock.patch.object(video_panel, "clean_inputs"), mock.patch.object(video_panel, "workflow_model", return_value=None), \
             mock.patch.object(video_panel, "RunEta") as eta:
            eta.return_value.plan.return_value = {"total": 10}
            result = video_panel.generate.__wrapped__()
        self.assertEqual(result["queued_count"], 4)
        self.assertEqual(len(self.queue.items), 4)
        expected = [(name, strength) for name in ["krea_a.safetensors", "krea_b.safetensors"] for strength in ["1", "2"]]
        actual = []
        for item in self.queue.items:
            argv = item["argv"]
            self.assertEqual(argv[argv.index("--seed") + 1], "0")
            self.assertEqual(argv[argv.index("--duration") + 1], "10")
            self.assertIn("--direct", argv)
            values = json.loads(item["env"]["COMFYUI_OPTIONS"])
            actual.append((values["lora_name"], values["lora_strength"]))
            self.assertEqual(values["additional_loras"], stack)
            self.assertEqual(item["form"]["lora_style_test"], ["0"])
        self.assertEqual(actual, expected)
        self.job.start.assert_not_called()

    def test_cleanup_blocks_generation_and_failure_holds_the_queue(self):
        from core import comfy_memory
        entered, finish = threading.Event(), threading.Event()

        def delayed(url):
            entered.set()
            if not finish.wait(3):
                raise RuntimeError("test cleanup timeout")
            raise RuntimeError("cleanup did not complete")

        with mock.patch.object(webapp, "_comfy_freeing", False), \
             mock.patch.object(webapp.run_queue, "held", False), \
             mock.patch.object(webapp.run_queue, "_save"), \
             mock.patch.object(webapp.job, "log") as log, \
             mock.patch.object(comfy_memory, "release", side_effect=delayed):
            webapp._comfy_freeing = True
            worker = threading.Thread(target=webapp.free_comfyui)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(webapp.run_queue.blocked())
                self.assertTrue(webapp.restart_blocked())
            finally:
                finish.set()
                worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertFalse(webapp._comfy_freeing)
            self.assertTrue(webapp.run_queue.held)
            self.assertIn("cleanup did not complete", log.call_args.args[0])

    def setUp(self):
        self.job = types.SimpleNamespace(idle=True, running=False, closed=False, batches=False,
                                         start=mock.Mock(return_value=True), log=mock.Mock())
        self.queue = webapp.JobQueue(self.job, prepare=lambda item: None)
        watcher = mock.patch.object(self.queue, "_ensure_watcher")
        watcher.start()
        self.addCleanup(watcher.stop)

    def add(self, label, **fields):
        item = {"label": label, "argv": [label]}
        with webapp.app.test_request_context("/generate/video", method="POST", data=fields):
            queued = self.queue.add(item)
        return item, queued

    def test_idle_top_waits_and_generate_starts_directly(self):
        pending, _ = self.add("pending", start_later="1")
        first, queued = self.add("first", queue_top="1")
        self.assertTrue(queued)
        self.assertTrue(self.queue.held)
        self.queue._advance()
        self.job.start.assert_not_called()
        self.assertEqual(self.queue.items, [first, pending])

        direct, queued = self.add("direct")
        self.assertFalse(queued)
        self.assertIs(self.queue.current, direct)
        self.assertEqual(self.queue.items, [first, pending])
        self.assertTrue(self.queue.held)

    def test_idle_top_in_empty_queue_waits_until_resumed(self):
        top, queued = self.add("top", queue_top="1")
        self.assertTrue(queued)
        self.queue._advance()
        self.job.start.assert_not_called()
        self.queue.held = False
        self.queue._advance()
        self.assertIs(self.queue.current, top)

    def test_top_waits_while_finished_job_is_still_draining(self):
        self.job.idle = False
        top, queued = self.add("top", queue_top="1")
        self.assertTrue(queued)
        self.assertTrue(self.queue.held)
        self.job.idle = True
        self.queue._advance()
        self.assertEqual(self.queue.items, [top])
        self.job.start.assert_not_called()

    def test_top_while_running_is_next_without_pausing_queue(self):
        self.job.idle, self.job.running = False, True
        first, _ = self.add("first")
        top, queued = self.add("top", queue_top="1")
        self.assertTrue(queued)
        self.assertFalse(self.queue.held)
        self.assertEqual(self.queue.items, [top, first])
        self.job.idle, self.job.running = True, False
        self.queue._advance()
        self.assertIs(self.queue.current, top)

    def test_idle_top_of_reopened_continuation_stays_queued(self):
        old, _ = self.add("old", start_later="1")
        old["pipeline"], old["edit_token"] = "video", "token"
        item = {"pipeline": "video", "label": "new", "argv": ["new"]}
        with webapp.app.test_request_context("/generate/video", method="POST",
                                             data={"queue_top": "1", "queue_edit_id": str(old["id"]),
                                                   "queue_edit_token": "token"}):
            self.assertTrue(self.queue.add(item))
        self.queue._advance()
        self.assertEqual(self.queue.items, [item])
        self.assertTrue(self.queue.held)
        self.job.start.assert_not_called()


class VideoMetadataTest(unittest.TestCase):
    def test_probe_is_nonblocking_and_invalidates_changed_files(self):
        started = threading.Event()
        release = threading.Event()
        metadata = {"resolution": "640x360", "duration": 3.0}

        def probe(path):
            started.set()
            if not release.wait(5):
                raise TimeoutError("test probe was not released")
            return metadata

        webapp._video_metadata_task.cache_clear()
        with mock.patch.object(webapp, "_read_video_file_metadata", side_effect=probe) as reader:
            try:
                self.assertEqual(webapp.video_file_metadata("film.mp4", 1, 10),
                                 {"resolution": None, "duration": None})
                self.assertTrue(started.wait(2))
                self.assertEqual(webapp.video_file_metadata("film.mp4", 1, 10),
                                 {"resolution": None, "duration": None})
                release.set()
                webapp._video_metadata_task("film.mp4", 1, 10).result(timeout=5)
                self.assertEqual(webapp.video_file_metadata("film.mp4", 1, 10), metadata)
                webapp.video_file_metadata("film.mp4", 2, 10)
                webapp._video_metadata_task("film.mp4", 2, 10).result(timeout=5)
                self.assertEqual(reader.call_count, 2)
            finally:
                release.set()
                webapp._video_metadata_task.cache_clear()

    def test_probe_failure_is_logged(self):
        with mock.patch.object(webapp.subprocess, "run", side_effect=subprocess.TimeoutExpired("ffprobe", 10)):
            with self.assertLogs(webapp.app.logger, level="WARNING") as logs:
                metadata = webapp._read_video_file_metadata("broken.mp4")
        self.assertEqual(metadata, {"resolution": None, "duration": None})
        self.assertIn("broken.mp4", logs.output[0])


class OutputH3MetadataTest(unittest.TestCase):
    def test_video_captions_include_saved_openh3_settings(self):
        state = types.SimpleNamespace(id="run_1", brief="Brief", direct=False, workflow="h3.json", options={}, llm="local",
                                      h3_mode="review", h3_creativity="bold", connection_mode="infinite", start="image", final=None)
        with mock.patch.object(video_panel, "saved_runs", return_value=[{"id": "run_1", "label": "Film", "pipeline": "video"}]), \
             mock.patch.object(video_panel, "films_of_runs", return_value={"film.mp4": state}), \
             mock.patch.object(video_panel, "run_of_film", return_value="run_1"), \
             mock.patch.object(video_panel.workflow_options, "loras_used", return_value=[]):
            caption = video_panel.captions()("film.mp4")
        self.assertEqual((caption["h3_mode"], caption["h3_creativity"], caption["connection"]), ("review", "bold", "infinite"))

    def test_upscaled_video_inherits_source_run_metadata(self):
        state = types.SimpleNamespace(id="run_20261107_120000", title="Film", brief="Brief", direct=False, workflow="h3.json", options={"lora": "1"}, llm="local",
                                      h3_mode="review", h3_creativity="bold", connection_mode=None, start="chain", final=None)
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.object(video_panel, "saved_runs", return_value=[{"id": state.id, "label": "Film", "pipeline": "video"}]), \
             mock.patch.object(video_panel, "films_of_runs", return_value={"film.mp4": state}), \
             mock.patch.object(video_panel.workflow_options, "loras_used", return_value=["LoRA A"]), \
             mock.patch.dict(webapp.FOLDERS, {"video": temp}), \
             mock.patch.object(paths, "OUTPUT_DIR", temp), \
             mock.patch.object(webapp, "video_file_metadata", side_effect=lambda path, *_: {
                 "resolution": "2048x1024" if "upscaled" in path else "1024x512", "duration": 12}):
            for name in ("film.mp4", "film_upscaled.mp4", "film_upscaled_2.mp4", "film_upscaled_upscaled.mp4", "unknown.mp4"):
                with open(os.path.join(temp, name), "wb") as file:
                    file.write(b"video")
            listed = {item["name"]: item for item in webapp.list_videos("video")}
        original = listed["film.mp4"]
        for name in ("film_upscaled.mp4", "film_upscaled_2.mp4", "film_upscaled_upscaled.mp4"):
            item = listed[name]
            for key in ("run", "title", "model", "llm", "loras", "h3_mode", "h3_creativity", "connection"):
                self.assertEqual(item[key], original[key], (name, key))
            self.assertEqual(item["resolution"], "2048x1024")
        self.assertEqual(original["connection"], "chain")
        self.assertIsNone(listed["unknown.mp4"]["model"])

    def test_upscale_metadata_survives_original_deletion_and_repeat_upscale(self):
        state = types.SimpleNamespace(id="run_20261107_120000", title="Film", brief="Brief", direct=False, workflow="h3.json", options={},
                                      llm="local", h3_mode="render", h3_creativity="bold", connection_mode="director", start="image")
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.object(paths, "OUTPUT_DIR", temp), \
             mock.patch.dict(webapp.FOLDERS, {"video": temp}), \
             mock.patch.object(video_panel, "films_of_runs", return_value={"film.mp4": state}) as films, \
             mock.patch.object(video_panel, "saved_runs", return_value=[{"id": state.id, "label": "Film", "pipeline": "video"}]) as runs, \
             mock.patch.object(video_panel.workflow_options, "loras_used", return_value=["LoRA A"]), \
             mock.patch.object(video_panel, "busy_runs", return_value=set()), \
             mock.patch.object(video_panel.RunState, "load", return_value=None), \
             mock.patch.object(webapp, "video_file_metadata", return_value={"resolution": "2048x1024", "duration": 12}):
            source = os.path.join(temp, "film.mp4")
            upscale = os.path.join(temp, "film_upscaled.mp4")
            for path in (source, upscale):
                with open(path, "wb") as file:
                    file.write(b"video")
            self.assertTrue(video_panel.delete_video("video", source)["ok"])
            self.assertTrue(os.path.isfile(output_metadata.sidecar(upscale)), "deletion backfills an old upscale")
            films.return_value = {}
            runs.return_value = []
            listed = webapp.list_videos("video")[0]
            self.assertEqual((listed["title"], listed["model"], listed["llm"], listed["loras"]),
                             ("Film", "h3", "local", ["LoRA A"]))
            self.assertEqual((listed["h3_mode"], listed["h3_creativity"], listed["run"]), ("render", "bold", None))
            self.assertEqual(listed["connection"], "director", "kept in the upscale's own metadata")

            client = mock.Mock()
            client.upload.return_value = "input.mp4"
            client._run.return_value = {"outputs": {}}
            def download(entry, stem, extensions, description):
                path = stem + ".mp4"
                with open(path, "wb") as file:
                    file.write(b"new video")
                return path
            client._download.side_effect = download
            with mock.patch.object(video_upscale, "probe", return_value=(1024, 512, 12)):
                new_path = video_upscale.upscale(upscale, client)
            self.assertEqual(output_metadata.read(new_path), output_metadata.read(upscale))
            self.assertTrue(video_panel.delete_video("video", upscale)["ok"])
            self.assertFalse(os.path.exists(output_metadata.sidecar(upscale)))
            remaining = webapp.list_videos("video")[0]
            self.assertEqual((remaining["title"], remaining["llm"], remaining["loras"]), ("Film", "local", ["LoRA A"]))

    def test_upscale_metadata_error_prevents_original_deletion(self):
        state = types.SimpleNamespace(id="run_20261107_120000", title="Film", brief="Brief", direct=False, workflow=None, options={},
                                      llm="local", h3_mode="off", h3_creativity="balanced", connection_mode=None, start="image", final=None)
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.object(paths, "OUTPUT_DIR", temp), \
             mock.patch.object(video_panel, "films_of_runs", return_value={"film.mp4": state}), \
             mock.patch.object(video_panel, "busy_runs", return_value=set()), \
             mock.patch.object(output_metadata, "write", side_effect=OSError("disk full")):
            source = os.path.join(temp, "film.mp4")
            for path in (source, os.path.join(temp, "film_upscaled.mp4")):
                with open(path, "wb") as file:
                    file.write(b"video")
            with self.assertRaisesRegex(OSError, "disk full"):
                video_panel.delete_video("video", source)
            self.assertTrue(os.path.exists(source))

    def test_new_upscale_saves_snapshot_before_original_run_is_removed(self):
        state = types.SimpleNamespace(id="run_20261107_120000", title="Film", brief="Brief", direct=False, workflow="h3.json",
                                      options={}, llm="local", h3_mode="review", h3_creativity="bold", connection_mode=None, start="chain", final=None)
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.object(output_metadata, "films_of_runs", return_value={"film.mp4": state}) as films, \
             mock.patch.object(output_metadata.workflow_options, "loras_used", return_value=["LoRA A"]), \
             mock.patch.object(video_upscale, "probe", return_value=(1024, 512, 12)):
            source = os.path.join(temp, "film.mp4")
            with open(source, "wb") as file:
                file.write(b"video")
            client = mock.Mock()
            client.upload.return_value = "input.mp4"
            client._run.return_value = {"outputs": {}}
            def download(entry, stem, extensions, description):
                path = stem + ".mp4"
                with open(path, "wb") as file:
                    file.write(b"upscaled")
                return path
            client._download.side_effect = download
            made = video_upscale.upscale(source, client)
            films.return_value = {}
            os.remove(source)
            metadata = output_metadata.resolve(made)
            self.assertEqual((metadata["title"], metadata["model"], metadata["llm"], metadata["loras"]),
                             ("Film", "h3", "local", ["LoRA A"]))
            self.assertEqual((metadata["h3_mode"], metadata["h3_creativity"]), ("review", "bold"))

    def test_shorts_history_keeps_openh3_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp, \
             mock.patch.object(topic_history, "TOPIC_HISTORY_PATH", os.path.join(temp, "history.jsonl")):
            topic_history.record_successful_topic("Topic", "film.mp4", h3_mode="render", h3_creativity="extreme")
            topic_history.record_successful_topic("Other", "plain.mp4", h3_mode="off", h3_creativity="balanced")
            history = topic_history.read_history()
            self.assertEqual((history[0]["h3_mode"], history[0]["h3_creativity"]), ("render", "extreme"))
            self.assertNotIn("h3_mode", history[1])
            caption = shorts_panel.captions()
            self.assertEqual((caption("film.mp4")["h3_mode"], caption("film.mp4")["h3_creativity"]), ("render", "extreme"))
            self.assertIsNone(caption("plain.mp4")["h3_mode"])


class UnreadableRunTest(unittest.TestCase):
    def setUp(self):
        from pipelines.image import paths as image_paths, run_state as image_state
        self.image_state = image_state
        self.temp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(image_paths, "RUNS_DIR", os.path.join(self.temp.name, "runs"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: (self.temp.cleanup(), image_state.list_runs()))
        self.run_id = "image_20990101_120000"
        self.folder = os.path.join(image_paths.RUNS_DIR, self.run_id)
        os.makedirs(self.folder)
        self.checkpoint = os.path.join(self.folder, "state.json")
        with open(self.checkpoint, "wb") as file:
            file.write(b"\x00")
        with open(os.path.join(self.folder, "input.png"), "wb") as file:
            file.write(b"input")
        self.output = os.path.join(self.temp.name, "output.png")
        with open(self.output, "wb") as file:
            file.write(b"output")
        image_state.list_runs()
        self.client = webapp.app.test_client()

    def delete(self):
        return self.client.post(f"/runs/{self.run_id}/discard-unreadable")

    def test_delete_unreadable_run_folder_preserves_other_output(self):
        with mock.patch.object(webapp, "busy_runs", return_value=set()), mock.patch.dict(os.environ, {"APP_PASSWORD": ""}):
            self.assertTrue(self.delete().get_json()["ok"])
        self.assertFalse(os.path.exists(self.folder))
        self.assertTrue(os.path.exists(self.output))
        self.image_state.list_runs()
        self.assertNotIn(self.checkpoint, [error["path"] for error in webapp.catalogue_errors()])

    def test_busy_or_repaired_checkpoint_cannot_be_deleted(self):
        with mock.patch.dict(os.environ, {"APP_PASSWORD": ""}):
            with mock.patch.object(webapp, "busy_runs", return_value={self.run_id}):
                self.assertEqual(self.delete().status_code, 409)
            repaired = self.image_state.RunState.new("brief", 1, True, 64, 64)
            repaired.id = self.run_id
            repaired.save()
            with mock.patch.object(webapp, "busy_runs", return_value=set()):
                self.assertEqual(self.delete().status_code, 409)
        self.assertTrue(os.path.exists(self.checkpoint))

    def test_unknown_run_and_reparse_folder_are_rejected(self):
        with mock.patch.dict(os.environ, {"APP_PASSWORD": ""}), mock.patch.object(webapp, "busy_runs", return_value=set()):
            self.assertEqual(self.client.post("/runs/image_20990101_120001/discard-unreadable").status_code, 404)
            info = types.SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            with mock.patch.object(webapp.os, "lstat", return_value=info):
                self.assertEqual(self.delete().status_code, 409)
        self.assertTrue(os.path.exists(self.checkpoint))


class WorkPrivacyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.job = types.SimpleNamespace(idle=False, running=False, closed=False, progress={}, log=mock.Mock())
        self.path = os.path.join(self.temp.name, "queue.json")
        self.queue = webapp.JobQueue(self.job, prepare=lambda item: None, path=self.path)
        for patcher in (mock.patch.object(webapp, "run_queue", self.queue),
                        mock.patch.object(webapp, "job", self.job),
                        mock.patch.object(webapp, "NSFW_PATH", os.path.join(self.temp.name, "nsfw.json")),
                        mock.patch.object(webapp, "_panel_closing", False),
                        mock.patch.object(self.queue, "_ensure_watcher"),
                        mock.patch.dict(os.environ, {"APP_PASSWORD": ""})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = webapp.app.test_client()

    def mark(self, kind, identifier):
        return self.client.post("/api/work/nsfw", json={"kind": kind, "id": str(identifier), "nsfw": True})

    def restored(self):
        return webapp.JobQueue(self.job, prepare=lambda item: None, path=self.path)

    def test_waiting_tag_survives_restart_and_edit(self):
        self.queue.items = [{"id": 1, "pipeline": "image", "label": "Waiting", "argv": ["generate"], "edit_token": "token"}]
        self.assertTrue(self.mark("job", 1).get_json()["ok"])
        self.assertTrue(self.restored().items[0]["private"])
        with webapp.app.test_request_context("/generate/image", method="POST",
                                             data={"queue_edit_id": "1", "queue_edit_token": "token"}), \
             mock.patch.object(webapp, "private_mode", return_value=False):
            replacement = {"pipeline": "image", "label": "Edited", "argv": ["generate"]}
            self.queue.add(replacement)
        self.assertTrue(replacement["private"], "editing while Privacy mode is off must not remove the tag")

    def test_running_tag_applies_before_and_after_run_id_arrives(self):
        self.queue.current = {"id": 2, "pipeline": "video", "label": "Running", "argv": ["generate"]}
        self.assertTrue(self.mark("job", 2).get_json()["ok"])
        self.assertTrue(self.queue.current["private"])
        self.job.progress = {"run_id": "run_live"}
        self.queue._advance()
        self.assertIn("run_live", webapp._read_nsfw()["video"])
        self.queue.current.pop("private")
        payload = {"videos": {"video": [{"name": "film.mp4"}]}, "image_sets": [], "made_now": [],
                   "progress": self.job.progress, "queue": {"current": dict(self.queue.current), "results": []}}
        with mock.patch.object(webapp, "_video_nsfw_key", return_value=("video", "run_live")):
            webapp._apply_nsfw(payload, webapp._read_nsfw(), {})
        self.assertTrue(payload["queue"]["current"]["nsfw"], "active runs use their live run ID, not only resume")
        self.assertTrue(payload["videos"]["video"][0]["nsfw"], "the resulting film stays out of normal Output")
        self.assertTrue(self.mark("job", 2).get_json()["ok"])
        self.assertTrue(self.queue.current["private"], "tagging an already saved active run works too")

    def test_saved_video_can_be_tagged_without_a_final_film(self):
        self.queue.items = [{"id": 3, "pipeline": "video", "label": "Retry", "argv": ["generate"], "resume": "run_pending"}]
        with mock.patch.object(webapp.PIPELINES["video"], "load_run", return_value=types.SimpleNamespace(final=None)):
            self.assertTrue(self.mark("video", "run_pending").get_json()["ok"])
        self.assertIn("run_pending", webapp._read_nsfw()["video"])
        self.assertTrue(self.restored().items[0]["private"], "queued continuations keep the saved run's tag")

    def test_unsaved_failure_tag_survives_restart_and_retry(self):
        self.job.progress = {"run_id": "unrelated_previous_run"}
        self.queue.results = [{"job_id": 4, "pipeline": "image", "label": "Failed", "outcome": "failed",
                               "run_id": None, "job": {"pipeline": "image", "label": "Failed", "argv": ["generate"]}}]
        self.assertTrue(self.mark("failed", 4).get_json()["ok"])
        restored = self.restored()
        self.assertTrue(restored.results[0]["private"])
        self.assertTrue(restored.results[0]["job"]["private"])
        self.assertEqual(webapp._read_nsfw()["image"], [], "no tag is applied to an old job's progress")
        self.queue.requeue_failure(4)
        self.assertTrue(self.restored().items[0]["private"])

    def test_tag_follows_job_that_finished_before_request(self):
        self.queue.results = [{"job_id": 5, "pipeline": "image", "label": "Done", "outcome": "done",
                               "run_id": "image_done"}]
        self.assertTrue(self.mark("job", 5).get_json()["ok"])
        self.assertIn("image_done", webapp._read_nsfw()["image"])

    def test_invalid_missing_and_unsaved_tags_report_errors(self):
        self.assertEqual(self.mark("job", "bad").status_code, 400)
        self.assertEqual(self.mark("job", 99).status_code, 404)
        self.assertEqual(self.client.post("/api/work/nsfw", json={"kind": "job", "id": "1", "nsfw": False}).status_code, 400)
        self.queue.items = [{"id": 1, "pipeline": "image", "label": "Waiting"}]
        with mock.patch.object(self.queue, "_save", return_value=False):
            response = self.mark("job", 1)
        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.get_json()["ok"])
        self.queue.current = {"id": 2, "pipeline": "image", "label": "Rendering"}
        self.job.progress = {"run_id": "image_live"}
        with mock.patch.object(webapp, "tag_run_nsfw", return_value=False):
            response = self.mark("job", 2)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private", self.queue.current)


class PanelTest(unittest.TestCase):
    def setUp(self):
        closing = mock.patch.object(webapp, "_panel_closing", False)
        closing.start()
        self.addCleanup(closing.stop)
        self.temp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        timing_path = mock.patch.object(webapp, "PROMPT_WRITER_TIMINGS", os.path.join(self.temp, "writer_timings.json"))
        timing_path.start()
        self.addCleanup(timing_path.stop)
        self.comfy = fake_comfy(self.temp)
        self.addCleanup(close, self.comfy)
        self.claude = fake_claude()
        self.addCleanup(close, self.claude)
        patcher = mock.patch.dict(os.environ, {
            "COMFYUI_URL": self.comfy.url, "ANTHROPIC_BASE_URL": self.claude.url, "ANTHROPIC_API_KEY": "test"})
        patcher.start()
        self.addCleanup(patcher.stop)
        webapp._comfyui_cache["at"] = 0.0
        webapp._runs_cache["at"] = 0.0
        webapp._saved_workflows_cache["at"] = 0.0
        # The fake renders instantly, which would otherwise teach the ETA that all renders do.
        if os.path.exists(webapp.VIDEO_TIMINGS):
            os.remove(webapp.VIDEO_TIMINGS)
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
        for folder in (paths.RUNS_DIR, paths.OUTPUT_DIR, paths.INPUTS_DIR):
            shutil.rmtree(folder, ignore_errors=True)
        self.assertEqual(errors, {}, "the test left a queue unable to save")

    def queue_id(self):
        """A job number from the queue itself: a made-up one could match a real job already in Finished."""
        with webapp.run_queue.lock:
            webapp.run_queue.next_id += 1
            return webapp.run_queue.next_id - 1

    def wait_until(self, condition, what, timeout=90):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if condition():
                return
            time.sleep(0.05)
        self.fail(f"Timed out waiting for {what}. Log: {[l['text'] for l in webapp.job.lines][-15:]}")

    def wait_idle(self):
        def idle():
            webapp.run_queue.pending()
            # A job waiting its turn counts too (an automatic retry while ComfyUI is cleared), unless the queue is held.
            waiting = not webapp.run_queue.held and any(not item.get("later") for item in webapp.run_queue.items)
            return webapp.job.idle and not webapp.run_queue.current and not waiting
        self.wait_until(idle, "the job to end")

    def generate(self, **fields):
        form = {"prompt": "a storm rolls in", "duration": "60", "llm": "claude", "size": "64x64",
                "image": (io.BytesIO(png_bytes()), "harbour.png"), **fields}
        return self.client.post("/generate/video", data={k: v for k, v in form.items() if v is not None},
                                content_type="multipart/form-data")

    def status(self):
        webapp._runs_cache["at"] = 0.0
        reply = self.client.get("/api/status")
        # A status the panel couldn't build says so here, rather than as "None is not subscriptable" further on.
        self.assertEqual(reply.status_code, 200, reply.get_data(as_text=True)[-1500:])
        return reply.get_json()

    def only_run(self):
        runs = list_runs()
        self.assertEqual(len(runs), 1)
        return runs[0]

    def texts_rendered(self):
        return [p["prompt"]["121"]["inputs"]["text"] for p in self.comfy.prompts]

    def test_status_sends_only_the_log_lines_the_page_does_not_have(self):
        lines = [{"n": n, "t": "12:00:00", "k": "", "text": f"line {n}"} for n in range(10, 15)]
        with mock.patch.object(webapp.job, "lines", lines):
            whole = self.client.get("/api/status").get_json()
            self.assertFalse(whole["log_delta"])
            self.assertEqual([line["n"] for line in whole["lines"]], [10, 11, 12, 13, 14])
            # From the last line the page has, that one again: its ETA can be added just after it is logged.
            since = self.client.get("/api/status?log_after=12").get_json()
            self.assertTrue(since["log_delta"])
            self.assertEqual([line["n"] for line in since["lines"]], [12, 13, 14])
            self.assertEqual(since["log_first"], 10)
            # A line the panel no longer has (a new job started a new log): the whole log again.
            gone = self.client.get("/api/status?log_after=3").get_json()
            self.assertFalse(gone["log_delta"])
            self.assertEqual(len(gone["lines"]), 5)

    def test_a_queued_job_says_how_it_is_upscaled(self):
        upscale = webapp.item_upscale
        image = {"pipeline": "image", "argv": ["--count", "2", "--option", "image_upscale=SeedVR2", "--option", "image_upscale_denoise=0.1"]}
        self.assertEqual(upscale(image), "SeedVR2, denoise 0.1")
        self.assertEqual(webapp.run_facts(image)["upscale"], "SeedVR2, denoise 0.1", "in the facts the queue and Pending show")
        self.assertIsNone(upscale({"pipeline": "image", "argv": ["--option", "image_upscale=" + webapp.workflow_options.NO_IMAGE_UPSCALE]}))
        film = {"pipeline": "video", "argv": [], "env": {"COMFYUI_OPTIONS": json.dumps({"latent_upscale": "Fast", "latent_upscale_mp": "1.5"})}}
        self.assertEqual(upscale(film), "Latent, Fast, 1.5 MP")
        self.assertIsNone(upscale({"pipeline": "video", "env": {"COMFYUI_OPTIONS": json.dumps({"latent_upscale": "Off"})}}))
        self.assertNotIn("upscale", webapp.run_facts({"pipeline": "shorts", "argv": []}))
        # A continuation carries no options of its own: its saved run's.
        state = types.SimpleNamespace(options={"image_upscale": "UltraSharp"})
        with mock.patch.object(webapp.PIPELINES["image"], "load_run", return_value=state):
            self.assertEqual(upscale({"pipeline": "image", "argv": ["--resume", "image_1"], "resume": "image_1"}), "UltraSharp")
        self.assertIsNone(upscale({"pipeline": "image", "argv": ["-m", "pipelines.image.upscale", "--scale", "2"]}),
                          "an upscale job says so itself")

    def test_the_next_job_in_the_queue_starts_the_log_as_a_new_run(self):
        line = webapp.new_run_line
        self.assertEqual(line({"label": "20 images: An elf archer", "detail": "20 images · from text"}),
                         "===== New run, 20 images ===== An elf archer")
        self.assertEqual(line({"label": "Midnight Desires", "detail": "1:00 film · local"}),
                         "===== New run, 1:00 film ===== Midnight Desires")
        self.assertEqual(line({"label": "Midnight Desires", "detail": "Continue"}), "===== New run ===== Midnight Desires")
        self.assertEqual(line({"label": "3 videos", "detail": "en-GB"}), "===== New run, 3 videos =====")

    def test_the_status_stream_pushes_a_change_at_once_with_only_what_is_new(self):
        lines = [{"n": n, "t": "12:00:00", "k": "", "text": f"line {n}"} for n in range(1, 4)]
        # The job's own count goes on from the lines it has, as it would.
        with mock.patch.object(webapp.job, "lines", lines), mock.patch.object(webapp.job, "seq", 3), \
                mock.patch.object(webapp, "STREAM_EVERY", 30), mock.patch.object(webapp, "STREAM_GATHER", 0):
            response = self.client.get("/api/status/stream?catalogue_revision=", buffered=False)
            self.assertEqual(response.mimetype, "text/event-stream")
            self.assertNotIn("Content-Encoding", response.headers)
            chunks = response.iter_encoded()
            self.assertEqual(next(chunks), b"retry: 2000\n\n")
            first = json.loads(next(chunks).decode("utf-8").removeprefix("data: "))
            self.assertIn("image_sets", first, "the Output catalogue the first time")
            self.assertEqual([line["n"] for line in first["lines"]], [1, 2, 3])
            started = time.monotonic()
            threading.Timer(0.3, webapp.job.log, args=("a new line",)).start()
            # Anything else changing sends an update too; the one with the new line comes as soon as it is logged.
            for _ in range(20):
                second = json.loads(next(chunks).decode("utf-8").removeprefix("data: "))
                if any(line["text"] == "a new line" for line in second["lines"]):
                    break
            self.assertLess(time.monotonic() - started, 5, "sent on the change, not after STREAM_EVERY")
            self.assertTrue(second["log_delta"])
            self.assertEqual([line["text"] for line in second["lines"]], ["line 3", "a new line"])
            self.assertNotIn("image_sets", second, "the catalogue only again when it changes")
            response.close()

    def test_a_large_status_is_gzipped_for_a_browser_that_takes_it(self):
        lines = [{"n": n, "t": "12:00:00", "k": "", "text": "x" * 100} for n in range(100)]
        with mock.patch.object(webapp.job, "lines", lines):
            zipped = self.client.get("/api/status", headers={"Accept-Encoding": "gzip, deflate"})
            plain = self.client.get("/api/status")
        self.assertEqual(zipped.headers.get("Content-Encoding"), "gzip")
        self.assertEqual(json.loads(gzip.decompress(zipped.data))["lines"], lines)
        self.assertNotIn("Content-Encoding", plain.headers)
        self.assertEqual(plain.get_json()["lines"], lines)

    def test_fixed_clip_form_and_legacy_queue(self):
        fixed, error = video_panel.build_options({"duration": "30", "clip_seconds": "8-8", "clip_fixed": "on"})
        self.assertIsNone(error)
        self.assertIn("--fixed-clips", fixed)
        ordinary, error = video_panel.build_options({"duration": "30", "clip_seconds": "8-8"})
        self.assertIsNone(error)
        self.assertNotIn("--fixed-clips", ordinary)
        self.assertIsNotNone(video_panel.build_options({"clip_seconds": "5-8", "clip_fixed": "on"})[1])
        item = {"pipeline": "video", "argv": ["-m", "pipelines.video.main", "--clip-seconds", "8-8", "--fixed-clips"]}
        self.assertEqual(webapp.legacy_queue_form(item)[0]["clip_fixed"], "1")
        item["argv"].remove("--fixed-clips")
        self.assertNotIn("clip_fixed", webapp.legacy_queue_form(item)[0])

    def test_video_clip_relationship_is_validated_and_passed_to_the_planner(self):
        flags, error = video_panel.build_options({"clip_relationship": "related"})
        self.assertIsNone(error)
        self.assertEqual(flags[flags.index("--clip-relationship") + 1], "related")
        self.assertEqual(video_panel.build_options({"clip_relationship": "unknown"})[1], "Unknown clip relationship.")

    def test_a_films_words_per_prompt_reach_each_models_rules(self):
        flags, error = video_panel.build_options({"llm": "gemini", "words": "150"})
        self.assertIsNone(error)
        self.assertEqual(flags[flags.index("--words") + 1], "150")
        self.assertNotIn("--words", video_panel.build_options({"llm": "gemini", "words": "30"})[0], "Auto: the model's own")
        self.assertIn("Words per prompt", video_panel.build_options({"llm": "gemini", "words": "600"})[1])
        from pipelines.video import h3_prompt, planner as film, wan_prompt
        self.assertIn("120-180 words", film._instructions("x", 10, "image", 1, words=150), "LTX-2")
        self.assertIn("120-180 words", film._instructions("x", 10, "chain", 1, wan_prompt.MODEL, words=150), "Wan")
        self.assertIn("Write 120-180 words", film._instructions("x", 10, "image", 1, h3_prompt.MODEL, words=150), "H3")
        self.assertIn("60-120 words", film._instructions("x", 10, "image", 1), "blank keeps LTX-2's own")

    def test_a_films_variety_and_chips_reach_the_writer(self):
        flags, error = video_panel.build_options({"llm": "gemini", "variety": "wide", "chip_location": "keep"})
        self.assertIsNone(error)
        start = flags.index("--variety")
        self.assertEqual(flags[start:start + 4], ["--variety", "wide", "--keep", "location"])
        direct, error = video_panel.build_options({"prompt_mode": "direct", "variety": "wide"})
        self.assertIsNone(error)
        self.assertNotIn("--variety", direct, "every clip gets your prompt as it is")
        rule = variety.film_rule("slight", ["lighting"], ["outfit"])
        self.assertIn("Keep the clips close together", rule)
        self.assertIn("change only the lighting, a little", rule)
        self.assertIn("Keep the outfit the same in every one of the clips", rule)
        with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
            video_main.parse_args(["a storm", "--vary", "pose", "--keep", "pose"])

    def test_fixed_clip_only_continues_matching_plan(self):
        state = types.SimpleNamespace(id="old", shots=[{"seconds": 8}] * 4, final=None, inputs="same", brief="idea",
                                      seconds=32, workflow=None, llm="gemini", h3_mode="off",
                                      h3_creativity="balanced", start="chain", connection_mode=None, fixed_clip=True)
        flags = ["--duration", "30", "--start", "chain", "--clip-seconds", "8-8", "--fixed-clips"]
        with mock.patch.object(video_panel, "busy_runs", return_value=set()), \
                mock.patch.object(video_panel.media, "inputs_fingerprint", return_value="same"), \
                mock.patch.object(video_panel, "list_runs", return_value=[state]):
            find = lambda chosen: video_panel.run_to_continue("idea", chosen, {}, {"max_images": 1}, [])
            self.assertIs(find(flags), state)
            self.assertIsNone(find(["--duration", "30", "--start", "director", "--clip-seconds", "8-8", "--fixed-clips"]))
            self.assertIs(find(flags + ["--llm", "gemini"]), state)
            self.assertIsNone(find(flags + ["--llm", "claude"]), "a different prompt model needs a new plan")
            self.assertIsNone(find(["--duration", "32", "--start", "chain"]))
            self.assertIsNone(find(["--duration", "30", "--start", "chain", "--clip-seconds", "10-10", "--fixed-clips"]))

    def test_write_prompt_validation_lifecycle_and_exclusivity(self):
        from core import h3_refiner
        for data in ({}, {"pipeline": "shorts", "prompt": "idea"}, {"pipeline": "video", "prompt": " "},
                     {"pipeline": "image", "prompt": "x" * 16001}):
            self.assertEqual(self.client.post("/api/write-prompt", json=data).status_code, 400)
        entered, release = threading.Event(), threading.Event()
        refiner = mock.MagicMock()
        refiner.__enter__.return_value = refiner
        refiner.model_id = "gemma-4-12b"
        refiner.tokens = {"per_second": 62.1, "total": 120}

        def write(text, side):
            entered.set()
            self.assertTrue(release.wait(5))
            return "finished"

        refiner.write_prompt.side_effect = write
        replies = []
        def request_write():
            with webapp.app.test_client() as client:
                replies.append(client.post("/api/write-prompt", json={"pipeline": "video", "prompt": " idea "}))

        with mock.patch.object(h3_refiner, "Refiner", return_value=refiner) as factory:
            thread = threading.Thread(target=request_write)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(self.client.get("/api/status").get_json()["prompt_writer"],
                                 {"running": True, "tokens": {"per_second": 62.1, "total": 120}})
                self.assertTrue(webapp.restart_blocked())
                self.assertTrue(webapp.run_queue.blocked())
                self.assertEqual(self.client.post("/api/write-prompt", json={"pipeline": "image", "prompt": "x"}).status_code, 409)
                self.assertEqual(self.client.post("/shutdown").status_code, 409)
                self.assertEqual(self.client.post("/restart/comfyui").status_code, 409)
                self.assertEqual(self.client.post("/restart/panel").status_code, 409)
                self.assertEqual(self.client.post("/launcher/refresh", data={"code_changed_at": str(time.time() + 60)}).get_json(), {"restarting": False})
            finally:
                release.set()
                thread.join(10)
            self.assertEqual(replies[0].get_json(), {"ok": True, "prompt": "finished"})
            # From words alone: started without the vision projector.
            factory.assert_called_once_with(self.comfy.url, require_compiler=False, model_id=mock.ANY, vision=False)
            refiner.write_prompt.assert_called_once_with("idea", "video")
            # Kept loaded for the next write; closed, it no longer holds the queue back.
            refiner.__exit__.assert_not_called()
            webapp.close_warm_writer()
            refiner.__exit__.assert_called_once()
            self.assertFalse(webapp.run_queue.blocked())
            self.assertEqual(self.client.get("/api/status").get_json()["prompt_writer"],
                             {"running": False, "tokens": None})
            estimate = self.client.get("/api/write-prompt?pipeline=video").get_json()
            self.assertTrue(estimate["ok"])
            self.assertGreater(estimate["seconds"], 0)
            self.assertEqual(self.client.get("/api/write-prompt?pipeline=shorts").status_code, 400)
            with open(webapp.PROMPT_WRITER_TIMINGS, encoding="utf-8") as file:
                self.assertIn("gemma-4-12b | video", json.load(file)["steps"])
        with mock.patch.object(h3_refiner, "Refiner", side_effect=RuntimeError("model failed")):
            result = self.client.post("/api/write-prompt", json={"pipeline": "image", "prompt": "x"})
            self.assertEqual(result.status_code, 500)
            self.assertIn("model failed", result.get_json()["error"])
            self.assertFalse(webapp.run_queue.blocked())

    def test_prompt_writer_estimates_learn_per_model_and_pipeline(self):
        from core import h3_refiner
        refiner = mock.MagicMock()
        refiner.__enter__.return_value = refiner
        refiner.model_id = "gemma-4-12b"
        refiner.write_prompt.return_value = "written"
        clock = mock.Mock(wraps=time)
        clock.monotonic.side_effect = [10, 110, 200, 400, 500, 530]
        with mock.patch.object(h3_refiner, "local_llm_model", return_value="gemma-4-12b"), \
                mock.patch.object(h3_refiner, "Refiner", return_value=refiner), \
                mock.patch.object(webapp, "time", clock):
            estimate = lambda side: self.client.get(f"/api/write-prompt?pipeline={side}").get_json()["seconds"]
            post = lambda side, model="gemma-4-12b": self.client.post(
                "/api/write-prompt", json={"pipeline": side, "prompt": "idea", "model": model})
            self.assertEqual(estimate("video"), 180)
            self.assertEqual(post("video").status_code, 200)
            self.assertEqual(estimate("video"), 100)
            self.assertEqual(estimate("image"), 180)
            self.assertEqual(post("video").status_code, 200)
            self.assertEqual(estimate("video"), 150)
            self.assertEqual(post("image").status_code, 200)
            self.assertEqual(estimate("image"), 30)
            with open(webapp.PROMPT_WRITER_TIMINGS, encoding="utf-8") as file:
                saved = json.load(file)
            self.assertEqual(saved["steps"], {"gemma-4-12b | video": 150, "gemma-4-12b | image": 30})
            self.assertEqual(saved["samples"]["steps"]["gemma-4-12b | video"], [100, 200])
        with mock.patch.object(h3_refiner, "local_llm_model", return_value="qwen3-14b"), \
                mock.patch.object(h3_refiner, "Refiner", return_value=refiner):
            self.assertEqual(self.client.get("/api/write-prompt?pipeline=video").get_json()["seconds"], 300)
            self.assertEqual(self.client.post("/api/write-prompt", json={"pipeline": "video", "prompt": "idea",
                                                                          "model": "qwen3-14b"}).status_code, 409)
            refiner.model_id = "qwen3-14b"
            refiner.write_prompt.side_effect = RuntimeError("failed")
            self.assertEqual(self.client.post("/api/write-prompt", json={"pipeline": "video", "prompt": "idea"}).status_code, 500)
            with open(webapp.PROMPT_WRITER_TIMINGS, encoding="utf-8") as file:
                self.assertEqual(json.load(file), saved)

    def test_prompt_writer_keeps_its_model_loaded_until_something_else_needs_the_gpu(self):
        from core import h3_refiner
        refiner = mock.MagicMock()
        refiner.model_id = "gemma-4-12b"
        refiner.process.poll.return_value = None
        refiner.write_prompt.return_value = "written"
        post = lambda: self.client.post("/api/write-prompt", json={"pipeline": "video", "prompt": "idea", "model": "gemma-4-12b"})
        try:
            with mock.patch.object(h3_refiner, "Refiner", return_value=refiner) as factory:
                self.assertEqual(post().status_code, 200)
                self.assertEqual(webapp.warm_model(), "gemma-4-12b")
                self.assertEqual(post().status_code, 200)
            # Started once, without its vision projector; the second skipped the start, and is timed apart.
            factory.assert_called_once()
            self.assertIs(factory.call_args.kwargs["vision"], False)
            refiner.__enter__.assert_called_once()
            refiner._release_comfy_models.assert_called_once()
            refiner.__exit__.assert_not_called()
            with open(webapp.PROMPT_WRITER_TIMINGS, encoding="utf-8") as file:
                self.assertEqual(set(json.load(file)["steps"]), {"gemma-4-12b | video", "gemma-4-12b | video | warm"})
            # A job about to start: the queue waits while it closes, then may go.
            self.assertTrue(webapp.warm_writer_in_the_way())
            for _ in range(200):
                if not webapp.warm_writer_in_the_way():
                    break
                time.sleep(0.01)
            self.assertFalse(webapp.warm_writer_in_the_way())
            refiner.__exit__.assert_called_once()
            self.assertIsNone(webapp.warm_model())
            # A failed write closes it at once rather than keeping it.
            refiner.write_prompt.side_effect = RuntimeError("failed")
            with mock.patch.object(h3_refiner, "Refiner", return_value=refiner):
                self.assertEqual(post().status_code, 500)
            self.assertIsNone(webapp.warm_model())
            self.assertEqual(refiner.__exit__.call_count, 2)
            # Only its own timer's close applies: a newer model stays.
            newer = mock.MagicMock()
            webapp.keep_warm(newer)
            webapp.close_warm_writer(only=refiner)
            self.assertIs(webapp._warm[0], newer)
        finally:
            webapp.close_warm_writer()

    def test_prompt_writer_can_use_gemini_or_the_selected_image_workflow_enhancer(self):
        from core import gemini
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                mock.patch.object(gemini, "_generate", return_value=types.SimpleNamespace(text="Gemini prompt")):
            response = self.client.post("/api/write-prompt", json={
                "pipeline": "video", "prompt": "idea", "writer": "gemini",
            })
        self.assertEqual(response.get_json()["prompt"], "Gemini prompt")

        enhancer = {"id": "prompt_enhancer", "role": True, "label": "Prompt enhancer"}
        takes = {"min_images": 1, "max_images": 1, "options": [enhancer]}
        comfy = mock.MagicMock()
        comfy.wait_until_reachable.return_value = True
        comfy._send_image.return_value = "input.png"
        comfy.enhance.return_value = "Workflow prompt"
        with mock.patch.object(image_panel, "chosen_workflow", return_value=({"COMFYUI_WORKFLOW": "image_test.json"}, takes, None)), \
                mock.patch("pipelines.image.comfy.ImageClient", return_value=comfy) as client:
            response = self.client.post("/api/write-prompt", data={
                "pipeline": "image", "prompt": "idea", "writer": "prompt_enhancer",
                "image": (io.BytesIO(png_bytes()), "source.png"),
            }, content_type="multipart/form-data")
        self.assertTrue(response.get_json()["ok"], response.get_json())
        self.assertEqual(response.get_json()["prompt"], "Workflow prompt")
        client.assert_called_once_with({"prompt_enhancer": "1"}, workflow_path="image_test.json")
        comfy.enhance.assert_called_once_with("idea", ["input.png"])

    def test_prompt_writer_can_select_qwen_when_gemma_is_configured(self):
        from core import h3_refiner
        refiner = mock.MagicMock()
        refiner.__enter__.return_value = refiner
        refiner.model_id = "qwen3-14b"
        refiner.write_prompt.return_value = "Qwen prompt"
        with mock.patch.object(h3_refiner, "local_llm_model", return_value="gemma-4-12b"), \
                mock.patch.object(h3_refiner, "Refiner", return_value=refiner):
            estimate = self.client.get("/api/write-prompt?pipeline=video&writer=local&model=qwen3-14b")
            response = self.client.post("/api/write-prompt", json={
                "pipeline": "video", "prompt": "idea", "writer": "local", "model": "qwen3-14b",
            })
        self.assertEqual(estimate.get_json()["model"], "qwen3-14b")
        self.assertEqual(response.get_json()["prompt"], "Qwen prompt")
        self.assertEqual(refiner.write_prompt.call_args.args, ("idea", "video"))

    def test_prompt_writer_invalid_timing_and_save_failure_are_logged(self):
        from core import h3_refiner
        with open(webapp.PROMPT_WRITER_TIMINGS, "w", encoding="utf-8") as file:
            json.dump({"steps": {"gemma-4-12b | video": float("inf")}}, file)
        refiner = mock.MagicMock()
        refiner.__enter__.return_value = refiner
        refiner.model_id = "gemma-4-12b"
        refiner.write_prompt.return_value = "written"
        with mock.patch.object(h3_refiner, "local_llm_model", return_value="gemma-4-12b"), \
                mock.patch.object(h3_refiner, "Refiner", return_value=refiner), \
                self.assertLogs(webapp.app.logger, level="WARNING") as logs:
            self.assertEqual(self.client.get("/api/write-prompt?pipeline=video").get_json()["seconds"], 180)
            with mock.patch.object(webapp.os, "replace", side_effect=OSError("disk full")):
                reply = self.client.post("/api/write-prompt", json={"pipeline": "video", "prompt": "idea"})
            self.assertEqual(reply.get_json()["prompt"], "written")
        self.assertTrue(any("Invalid prompt writer timing" in entry for entry in logs.output))
        self.assertTrue(any("disk full" in entry for entry in logs.output))

    def test_prompt_writer_choices_exclude_claude_and_use_valid_default(self):
        for provider, key in (("gemini", "key"), ("claude", ""), ("", "key")):
            with self.subTest(provider=provider), mock.patch.dict(os.environ, {"LLM_PROVIDER": provider, "GEMINI_API_KEY": key}):
                html = self.client.get("/").get_data(as_text=True)
                for name in ("llm", "imageLlm"):
                    select = html.split(f'id="{name}"', 1)[1].split("</select>", 1)[0]
                    self.assertNotIn('value="claude"', select)
                    self.assertIn('value="local"', select)
                    self.assertIn(">Local model</option>", select)
                    # A reset form (editing a queued run) or a choice it can't put back lands here, not on the first one.
                    self.assertRegex(select, r'value="local"[^>]* selected>')
                    self.assertNotRegex(select, r'value="gemini"[^>]* selected>')
                config = json.loads(html.split('<script id="panelConfig" type="application/json">', 1)[1].split("</script>", 1)[0])
                self.assertEqual(config["default_llm"], "local")
        self.assertIn("claude", dict(video_panel.planner.LLMS))

    def test_local_qwen_rejects_attached_images_before_queuing(self):
        with mock.patch.object(video_panel.h3_refiner, "local_llm_model", return_value="qwen3-14b"):
            result = self.generate(llm="local")
            self.assertEqual(result.status_code, 400)
            self.assertIn("text-only", result.get_json()["error"])
            result = self.client.post("/generate/image", data={"prompt": "tree", "llm": "local",
                                      "image": (io.BytesIO(png_bytes()), "tree.png")},
                                      content_type="multipart/form-data")
            self.assertEqual(result.status_code, 400)
            self.assertIn("text-only", result.get_json()["error"])
            self.assertTrue(webapp.job.idle)

    def test_generate_captures_local_model_and_validates_references(self):
        for panel in (video_panel, image_panel):
            with self.subTest(pipeline=panel.__name__):
                flags, error = panel.build_options({"prompt_mode": "direct", "prompt_writer_model": "qwen3-14b"})
                self.assertIsNone(error)
                self.assertEqual(panel.option(flags, "--local-model"), "qwen3-14b")
                flags, error = panel.build_options({"prompt_mode": "direct", "prompt_writer_model": "missing"})
                self.assertIsNone(flags)
                self.assertIn("available local model", error)
        flags, error = video_panel.build_options({"llm": "local", "local_model": "qwen3-14b"})
        self.assertIsNone(error)
        self.assertEqual(video_panel.option(flags, "--local-model"), "qwen3-14b")
        flags, error = video_panel.build_options({"llm": "local", "local_model": "missing"})
        self.assertIsNone(flags)
        self.assertIn("available local model", error)
        flags, error = image_panel.build_options({"llm": "local", "local_model": "qwen3-14b"})
        self.assertIsNone(error)
        self.assertEqual(image_panel.option(flags, "--local-model"), "qwen3-14b")
        flags, error = image_panel.build_options({"llm": "local", "local_model": "missing"})
        self.assertIsNone(flags)
        self.assertIn("available local model", error)
        with mock.patch.object(image_panel.h3_refiner, "local_llm_model", return_value="gemma-4-12b"):
            result = self.client.post("/generate/image", data={"prompt": "tree", "llm": "local",
                                      "local_model": "qwen3-14b", "image": (io.BytesIO(png_bytes()), "tree.png")},
                                      content_type="multipart/form-data")
        self.assertEqual(result.status_code, 400)
        self.assertIn("text-only", result.get_json()["error"])

    def test_generate_does_not_reuse_another_local_models_plan(self):
        state = types.SimpleNamespace(id="image_1", shots=[{}], finished=False, inputs="same", brief="tree",
                                      count=1, direct=False, workflow=None, llm="local", local_model="gemma-4-12b")
        flags = ["--count", "1", "--llm", "local", "--local-model", "qwen3-14b"]
        with mock.patch.object(image_panel, "busy_runs", return_value=set()), \
             mock.patch.object(image_panel, "list_runs", return_value=[state]), \
             mock.patch.object(image_panel.video_media, "inputs_fingerprint", return_value="same"):
            self.assertIsNone(image_panel.run_to_continue("tree", flags, {}, []))
            state.local_model = "qwen3-14b"
            self.assertIs(image_panel.run_to_continue("tree", flags, {}, []), state)

    # --- The whole way through ---

    def test_review_change_a_prompt_render_watch_download_delete(self):
        reply = self.generate(review="1")
        self.assertEqual(reply.get_json(), {"ok": True, "queued": False})
        self.wait_idle()

        status = self.status()
        self.assertEqual(status["returncode"], 0, status["lines"])
        self.assertEqual(self.comfy.prompts, [], "reviewing first renders nothing")
        self.assertEqual(status["progress"]["stage"][:2], [1, 1])
        self.assertIn("--plan-only", status["command"])
        self.assertEqual(self.claude.requests[0]["body"]["messages"][0]["content"][0]["type"], "image")

        run_id = status["progress"]["run_id"]
        self.assertEqual([run["id"] for run in status["stopped_runs"]], [run_id])
        self.assertIn("Plan ready", status["stopped_runs"][0]["detail"])
        # Eight clips to even out for stitching take 48 seconds, and this tiny test film's render comes on top.
        self.assertGreater(status["stopped_runs"][0]["estimate"], 48, "it knows the render is still ahead")

        detail = self.client.get(f"/runs/{run_id}").get_json()
        self.assertEqual(detail["title"], "The Harbour Storm")
        self.assertEqual(detail["llm"], "claude")
        self.assertEqual(len(detail["shots"]), 8)
        self.assertFalse(detail["shots"][0]["rendered"])
        self.assertEqual(self.client.get(f"/runs/{run_id}/image").status_code, 200)
        self.assertEqual(self.client.get(f"/runs/{run_id}/clips/1").status_code, 404)

        prompts = [shot["prompt"] for shot in detail["shots"]]
        prompts[3] = "My better fourth prompt."
        self.assertTrue(self.client.post(f"/runs/{run_id}/shots", json={"prompts": prompts}).get_json()["ok"])
        self.assertEqual(self.client.post(f"/runs/{run_id}/shots", json={"prompts": ["too few"]}).status_code, 400)
        self.assertEqual(self.client.post(f"/runs/{run_id}/shots", json={"prompts": [""] * 8}).status_code, 400)

        self.assertTrue(self.client.post(f"/runs/{run_id}/continue").get_json()["ok"])
        self.wait_idle()
        status = self.status()
        self.assertEqual(status["returncode"], 0, status["lines"])
        self.assertEqual(len(self.comfy.prompts), 8)
        self.assertEqual(self.texts_rendered(), prompts, "each planned or edited prompt reaches its own clip")
        self.assertEqual(status["stopped_runs"], [], "a finished run isn't waiting for anything")
        self.assertEqual(status["progress"]["stage"][:2], [3, 3])

        film = status["videos"]["video"][0]
        self.assertEqual(film["title"], "The Harbour Storm")
        self.assertEqual(film["run"], run_id)
        video = self.client.get(f"/videos/video/{film['name']}")
        self.assertEqual(video.status_code, 200)
        self.assertEqual(video.mimetype, "video/mp4")
        video.close()
        self.assertEqual(self.client.get(f"/runs/{run_id}/clips/8").status_code, 200)

        # A shot redone from a finished film: the shots after it too, and the film anew.
        self.assertTrue(self.client.post(f"/runs/{run_id}/redo/7").get_json()["ok"])
        self.wait_idle()
        self.assertEqual(self.status()["returncode"], 0)
        self.assertEqual(self.texts_rendered()[8:], ["Prompt number 7.", "Prompt number 8."])
        self.assertEqual(self.client.post(f"/runs/{run_id}/redo/99").status_code, 400)

        self.assertTrue(self.client.post(f"/delete/video/{film['name']}").get_json()["ok"])
        status = self.status()
        self.assertEqual(status["videos"]["video"], [])
        self.assertEqual(status["stopped_runs"], [], "deleting a film takes its clips with it")
        self.assertFalse(os.path.exists(os.path.join(paths.RUNS_DIR, run_id)))

    def test_stop_kills_it_cancels_the_clip_and_continue_picks_up(self):
        self.comfy.script = ["ok", "ok", "hang"]
        self.assertTrue(self.generate().get_json()["ok"])
        self.wait_until(lambda: self.comfy.hanging, "the third clip to start")
        self.wait_until(lambda: webapp.job.progress.get("detail", "").startswith("Clip 3"), "the panel to see it")

        status = self.status()
        self.assertTrue(status["running"])
        progress = status["progress"]
        self.assertEqual(progress["stage"][2], "Clips")
        self.assertRegex(progress["detail"], r"^Clip 3 of 8: Shot 3, \ds$")
        self.assertEqual([step["state"] for step in progress["eta"]["steps"]], ["done", "now", "next"])
        self.assertGreater(progress["eta"]["total_left"], 0)

        run_id = progress["run_id"]
        self.assertEqual(status["stopped_runs"], [], "a run that's going can't be continued")
        for refused in (self.client.post(f"/runs/{run_id}/continue"), self.client.post(f"/runs/{run_id}/discard"),
                        self.client.post(f"/runs/{run_id}/redo/1"),
                        self.client.post(f"/runs/{run_id}/shots", json={"prompts": ["x"] * 8})):
            self.assertEqual(refused.status_code, 409)
        self.assertTrue(self.client.get(f"/runs/{run_id}").get_json()["busy"])

        # A second film waits its turn, and Stop puts it on hold.
        self.assertEqual(self.generate(prompt="a second film").get_json(), {"ok": True, "queued": True})
        queue_status = self.status()["queue"]
        self.assertEqual(queue_status["items"][0]["label"], "1 video: a second film")
        self.assertEqual(queue_status["items"][0]["facts"]["prompt"], "a second film", "the prompt is what the title opens")
        self.assertEqual(queue_status["items"][0]["facts"]["resolution"], "64x64")
        # The first film's plan and clips were timed: the fakes are quick, so it is short, but it's there.
        self.assertGreater(queue_status["items"][0]["estimate"], 0)

        pid = webapp.job.process.pid
        self.assertTrue(self.client.post("/stop").get_json()["ok"])
        self.assertFalse(webapp.job.running)
        self.assertNotIn(str(pid), subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True,
                                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout)
        self.assertIn(("/interrupt", {"prompt_id": "p3"}), self.comfy.cancels)

        self.wait_until(lambda: webapp.job.idle, "the job to wind up")
        status = self.status()
        self.assertTrue(status["stopped"])
        self.assertTrue(status["queue"]["held"], "nothing starts by itself after a Stop")
        self.assertEqual(len(self.comfy.prompts), 3)
        waiting = status["stopped_runs"][0]
        self.assertIn("2 of 8 clips kept", waiting["detail"])
        self.assertEqual(waiting["clips"], 2)

        # Take the second film out, and continue the first.
        item = status["queue"]["items"][0]["id"]
        self.assertTrue(self.client.post(f"/queue/run/remove/{item}").get_json()["ok"])
        self.assertTrue(self.client.post(f"/runs/{run_id}/continue").get_json()["ok"])
        self.wait_until(lambda: webapp.job.progress.get("stage"), "the stage to show")
        self.wait_until(lambda: webapp.job.eta.number, "the ETA to see the stage")
        self.assertIn("Plan", webapp.job.eta.kept_stages)
        # Eight 8s shots fitted to 60s lose a second each from the front, so the two kept are 7s.
        self.assertEqual(webapp.job.eta.kept_seconds, 14)
        self.wait_idle()
        status = self.status()
        self.assertEqual(status["returncode"], 0, status["lines"])
        self.assertEqual(self.texts_rendered()[3:], [f"Prompt number {n}." for n in range(3, 9)],
                         "the two finished clips aren't rendered again")
        self.assertEqual(len(status["videos"]["video"]), 1)

    # --- Generate never pays for the same plan twice ---

    def test_generate_continues_the_same_film_without_a_new_plan(self):
        self.assertTrue(self.generate(review="1").get_json()["ok"])
        self.wait_idle()
        run_id = self.only_run().id
        asked = len(self.claude.requests)

        # Asked to read the prompts again: they're there, and nothing starts.
        reply = self.generate(review="1").get_json()
        self.assertEqual(reply["shots"], run_id)
        self.assertEqual(reply["continued"], self.only_run().title)
        self.assertEqual(len(self.claude.requests), asked)

        # Generate, with a stopped run on the same brief and image: that run, and no new plan.
        reply = self.generate().get_json()
        self.assertEqual(reply["continued"], self.only_run().title)
        self.wait_idle()
        status = self.status()
        self.assertEqual(status["returncode"], 0, status["lines"])
        self.assertEqual(len(self.claude.requests), asked, "the plan was already paid for")
        self.assertEqual(len(status["videos"]["video"]), 1)

    def test_generate_plans_anew_when_the_film_differs(self):
        self.assertTrue(self.generate(review="1").get_json()["ok"])
        self.wait_idle()
        asked = len(self.claude.requests)
        for change in ({"prompt": "something else"}, {"duration": "90"},
                       {"image": (io.BytesIO(png_bytes((200, 10, 10))), "other.png")}):
            self.assertNotIn("continued", self.generate(review="1", **change).get_json(), change)
            self.wait_idle()
        self.assertGreaterEqual(len(self.claude.requests), asked + 3, "each one needed its own plan")

    def test_generate_keeps_the_plan_when_the_size_changes(self):
        self.assertTrue(self.generate(review="1").get_json()["ok"])
        self.wait_idle()
        asked = len(self.claude.requests)
        reply = self.generate(size="96x96").get_json()
        self.assertIn("continued", reply)
        self.wait_idle()
        self.assertEqual(len(self.claude.requests), asked)
        self.assertEqual(self.status()["returncode"], 0)

    def audio_file(self, seconds=20):
        path = os.path.join(self.temp, "song.wav")
        make_clip_audio(path, seconds)
        with open(path, "rb") as f:
            return io.BytesIO(f.read()), "song.wav"

    def test_a_film_with_audio_is_as_long_as_it(self):
        self.claude.reply = plan_reply(shots=3, seconds=7)
        reply = self.generate(duration="60", audio_mode="file", audio_file=self.audio_file()).get_json()
        self.assertTrue(reply["ok"], reply)
        self.wait_idle()
        status = self.status()
        self.assertEqual(status["returncode"], 0, status["lines"])
        film = os.path.join(paths.OUTPUT_DIR, status["videos"]["video"][0]["name"])
        self.assertAlmostEqual(media.duration(film), 20, delta=1.5)
        streams = ffmpeg.probe(film)["streams"]
        self.assertEqual(sorted(stream["codec_type"] for stream in streams), ["audio", "video"])

    def test_the_same_audio_keeps_the_plan_and_other_audio_does_not(self):
        self.claude.reply = plan_reply(shots=3, seconds=7)
        self.assertTrue(self.generate(review="1", audio_mode="file", audio_file=self.audio_file()).get_json()["ok"])
        self.wait_idle()
        asked = len(self.claude.requests)
        self.assertIn("continued", self.generate(review="1", audio_mode="file", audio_file=self.audio_file()).get_json())
        self.assertEqual(len(self.claude.requests), asked)
        self.assertNotIn("continued", self.generate(review="1", audio_mode="file", audio_file=self.audio_file(21)).get_json())
        self.wait_idle()
        self.assertEqual(len(self.claude.requests), asked + 1)

    def test_audio_options_are_checked(self):
        self.assertIn("Write the text", self.generate(audio_mode="text").get_json()["error"])
        self.assertIn("Choose the audio", self.generate(audio_mode="file").get_json()["error"])
        self.assertIn("Unknown voice", self.generate(audio_mode="text", narration="Hello", voice="nobody").get_json()["error"])

    def test_a_film_of_one_clip(self):
        self.claude.reply = plan_reply(shots=1, seconds=5)
        self.assertTrue(self.generate(duration="5").get_json()["ok"])
        self.wait_idle()
        status = self.status()
        self.assertEqual(status["returncode"], 0, status["lines"])
        self.assertEqual(len(self.comfy.prompts), 1)
        self.assertEqual(self.comfy.prompts[0]["prompt"]["291"]["inputs"]["value"], 5)
        self.assertEqual(len(status["videos"]["video"]), 1)
        film = os.path.join(paths.OUTPUT_DIR, status["videos"]["video"][0]["name"])
        self.assertAlmostEqual(media.duration(film), 5, delta=0.1, msg="a first clip keeps all its frames")

    def test_the_estimate_covers_the_whole_range(self):
        short = self.client.post("/api/estimate/video", data={"duration": "5"}).get_json()
        long = self.client.post("/api/estimate/video", data={"duration": "600"}).get_json()
        self.assertEqual((short["clips"], long["clips"]), (1, 75))
        share = 864 * 480 / (1280 * 736)
        self.assertGreater(long["total"], 5 * 3600 * share * 0.9, "about 5 hours of full-size rendering, at 480p's pixels")
        self.assertLess(short["total"], 600)

    def test_the_estimate_follows_the_resolution(self):
        clips = lambda **size: self.client.post("/api/estimate/video", data={"duration": "60", **size}).get_json()["steps"][1]["seconds"]
        highest = clips(size="1280x736")
        self.assertEqual(clips(size="736x1280"), highest, "turning it doesn't change the pixels")
        self.assertAlmostEqual(clips(size="640x352") / highest, 640 * 352 / (1280 * 736), places=2)
        self.assertAlmostEqual(clips() / highest, 864 * 480 / (1280 * 736), places=2, msg="with no size chosen, 480p's pixels")

    def test_a_preset_is_what_gets_rendered(self):
        self.comfy.script = []
        self.claude.reply = plan_reply(shots=1, seconds=5)
        self.assertTrue(self.generate(duration="5", size="352x640").get_json()["ok"])
        self.wait_idle()
        run = self.only_run()
        self.assertEqual((run.width, run.height), (352, 640))
        sent = self.comfy.prompts[0]["prompt"]
        self.assertEqual((sent["292"]["inputs"]["value"], sent["293"]["inputs"]["value"]), (352, 640))

    def test_a_short_film_says_so_in_the_queue(self):
        self.comfy.script = ["hang"]
        self.claude.reply = plan_reply(shots=1, seconds=5)
        self.assertTrue(self.generate(duration="5").get_json()["ok"])
        self.wait_until(lambda: self.comfy.hanging, "the clip to start")
        self.assertTrue(self.generate(duration="150", review="1").get_json()["queued"])
        self.assertTrue(self.generate(duration="5", review="1").get_json()["queued"])
        details = [item["detail"] for item in self.status()["queue"]["items"]]
        self.assertTrue(details[0].startswith("2:30 film"), details)
        self.assertTrue(details[1].startswith("5s film"), details)

    def test_a_run_that_fails_can_be_continued(self):
        # Exit code 1 restarts ComfyUI and tries a run once more by itself; here it is the failure that is looked at.
        patch = mock.patch.object(webapp, "restart_reason", return_value=None)
        patch.start()
        self.addCleanup(patch.stop)
        self.comfy.script = ["ok", "error", "error"]
        self.assertTrue(self.generate().get_json()["ok"])
        self.wait_idle()
        status = self.status()
        self.assertEqual(status["returncode"], 1)
        self.assertFalse(status["stopped"])
        self.assertIn("1 of 8 clips kept", status["stopped_runs"][0]["detail"])
        self.assertTrue(any("Kept what's done" in line["text"] for line in status["lines"]))
        changes = webapp.job.eta.changes
        self.assertTrue(any("rendering again" in change["text"] for change in changes), changes)

        # Stopped runs says it failed and why, until it makes its film; Output only lists what was made.
        self.wait_until(lambda: self.status()["stopped_runs"][0].get("outcome"), "the failure to be noted")
        failed = self.status()["stopped_runs"][0]
        self.assertEqual(self.status()["queue"]["results"][-1]["run_id"], failed["id"])
        self.assertEqual(failed["size"], "64x64")
        self.assertEqual(self.status()["videos"]["video"], [])
        self.assertEqual(failed["outcome"]["outcome"], "failed")
        self.assertIn("failed", failed["outcome"]["why"])
        # The fake ComfyUI fails with "out of memory": said in plain words first, its lines under them, and in Finished.
        self.assertTrue(failed["outcome"]["why"].startswith("Out of GPU memory"), failed["outcome"]["why"])
        self.assertIn("From its log:", failed["outcome"]["why"])
        self.assertTrue(self.status()["queue"]["results"][-1]["note"].startswith("Out of GPU memory"))
        self.comfy.script = ["ok"] * 7
        self.assertTrue(self.client.post(f"/runs/{failed['id']}/continue").get_json()["ok"])
        self.wait_until(lambda: self.status()["videos"]["video"], "the film")
        self.wait_until(lambda: not os.path.exists(os.path.join(RunState.load(failed["id"]).folder, webapp.OUTCOME_FILE)),
                        "the note to go once it worked")

    def test_a_queued_film_starts_by_itself_with_its_own_image(self):
        self.comfy.script = ["ok"] * 8
        self.assertFalse(self.generate().get_json()["queued"])
        self.assertTrue(self.generate(prompt="next film", review="1").get_json()["queued"])
        self.wait_until(lambda: len(self.claude.requests) == 2, "the second film to start")
        self.wait_idle()
        self.assertEqual(len(list_runs()), 2)
        self.assertEqual({run.brief for run in list_runs()}, {"a storm rolls in", "next film"})
        results = self.status()["queue"]["results"]
        self.assertEqual([result["outcome"] for result in results], ["done", "done"])
        # Asked to stop at its prompts: listed as not rendered, saying so, rather than missing.
        self.wait_until(lambda: any(run.get("outcome") for run in self.status()["stopped_runs"]), "it to be noted")
        self.assertEqual([run["outcome"]["outcome"] for run in self.status()["stopped_runs"] if run.get("outcome")], ["not rendered"])

    def test_skip_starts_the_next_film_and_continues_later(self):
        self.comfy.script = ["ok", "hang"]
        self.assertTrue(self.generate().get_json()["ok"])
        self.wait_until(lambda: self.comfy.hanging, "the second clip to start")
        self.wait_until(lambda: webapp.job.progress.get("detail", "").startswith("Clip 2"), "the panel to see it")
        skipped = webapp.job.progress["run_id"]
        self.assertTrue(self.generate(prompt="next film", review="1").get_json()["queued"])

        self.assertEqual(self.client.post("/skip").get_json(), {"ok": True, "error": None})
        self.assertIn(("/interrupt", {"prompt_id": "p2"}), self.comfy.cancels)
        self.wait_until(lambda: len(self.claude.requests) == 2, "the next film to start by itself")
        self.wait_idle()
        status = self.status()
        self.assertFalse(status["queue"]["held"])
        self.assertEqual([result["outcome"] for result in status["queue"]["results"]], ["stopped", "done"])
        waiting = next(run for run in status["stopped_runs"] if run["id"] == skipped)
        self.assertIn("1 of 8 clips kept", waiting["detail"])
        self.assertEqual(waiting["outcome"]["outcome"], "stopped", "marked Stopped in Pending")

        parked = self.client.post(f"/runs/{skipped}/continue?later=1").get_json()
        self.assertTrue(parked["ok"] and parked["queued"])
        waiting_items = self.status()["queue"]["items"]
        self.assertEqual([(item["resume"], item.get("later")) for item in waiting_items], [(skipped, True)], "back in Pending, not started")
        self.assertNotIn(skipped, [run["id"] for run in self.status()["stopped_runs"]])
        # The top-of-queue arrow: with nothing running, the one that starts it now.
        self.assertTrue(self.client.post(f"/queue/run/start/{waiting_items[0]['id']}?top=1").get_json()["ok"])
        self.wait_idle()
        self.assertEqual(self.status()["returncode"], 0)
        self.assertEqual(len(self.comfy.prompts), 9, "only the cut-off clip and those after it were rendered")
        self.assertFalse(any(run.get("outcome") for run in self.status()["stopped_runs"] if run["id"] == skipped), "finished, the mark is gone")

    def test_cancel_before_anything_is_saved_waits_for_it_then_goes_on(self):
        self.comfy.script = ["hang"]
        self.assertTrue(self.generate().get_json()["ok"])
        self.wait_until(lambda: self.comfy.hanging, "the clip to start")
        self.wait_until(lambda: webapp.job.progress.get("run_id"), "the panel to see the run")
        self.assertTrue(self.generate(prompt="next film", review="1").get_json()["queued"])
        saved = {"yet": False}
        with mock.patch.object(webapp, "run_saved", lambda: saved["yet"]):
            reply = self.client.post("/skip").get_json()
            self.assertEqual(reply, {"ok": True, "cancelling": True}, "accepted, no error to show")
            time.sleep(0.8)
            self.assertTrue(webapp.job.running, "stopping it now would lose it")
            self.assertTrue(self.status()["cancelling"])
            self.assertEqual(self.client.post("/skip").get_json(), {"ok": True, "cancelling": True}, "asked twice, still once")
            saved["yet"] = True
            self.wait_until(lambda: len(self.claude.requests) == 2, "the next in the queue to start once it is cancelled")
        self.wait_idle()
        status = self.status()
        self.assertFalse(status["queue"]["held"])
        self.assertFalse(status["cancelling"])
        self.assertEqual([result["outcome"] for result in status["queue"]["results"]][:1], ["stopped"])

    def test_cancel_keeps_a_held_queue_held(self):
        self.comfy.script = ["hang"]
        self.assertTrue(self.generate().get_json()["ok"])
        self.wait_until(lambda: self.comfy.hanging, "the clip to start")
        self.assertTrue(self.generate(prompt="next film", review="1").get_json()["queued"])
        self.client.post("/queue/run/hold")
        with mock.patch.object(webapp, "run_saved", return_value=True):
            self.assertTrue(self.client.post("/skip").get_json()["ok"])
        self.wait_idle()
        self.assertTrue(self.status()["queue"]["held"], "held before, held after")
        self.assertEqual(len(self.claude.requests), 1, "the next one waits for Resume")

    def test_presets_are_kept_by_name_per_side(self):
        if os.path.exists(webapp.PRESETS_PATH):
            os.remove(webapp.PRESETS_PATH)
        self.addCleanup(lambda: os.path.exists(webapp.PRESETS_PATH) and os.remove(webapp.PRESETS_PATH))
        post = lambda body: self.client.post("/api/presets", json=body)
        self.assertEqual(post({"side": "image", "name": "Phone wallpaper", "values": {"aspect": "1272x2772", "count": "4"}}).status_code, 200)
        post({"side": "image", "name": "Edits", "values": {"workflow": "image_edit.json"}})
        presets = self.client.get("/api/presets").get_json()["presets"]
        self.assertEqual([p["name"] for p in presets["image"]], ["Edits", "Phone wallpaper"], "by name")
        self.assertEqual(presets["video"], [])
        post({"side": "image", "name": "Edits", "values": {"workflow": "other.json"}})
        presets = self.client.get("/api/presets").get_json()["presets"]
        self.assertEqual(next(p for p in presets["image"] if p["name"] == "Edits")["values"], {"workflow": "other.json"}, "the same name saves over it")
        post({"side": "image", "name": "Edits", "delete": True})
        self.assertEqual([p["name"] for p in self.client.get("/api/presets").get_json()["presets"]["image"]], ["Phone wallpaper"])
        self.assertEqual(post({"side": "nowhere", "name": "x", "values": {}}).status_code, 400)

    def test_a_runs_title_opens_its_workflow_and_resolution(self):
        image = {"pipeline": "image", "argv": ["--count", "3", "--size", "1272x2772"],
                 "env": {"COMFYUI_WORKFLOW": "C:/x/logs/workflows/image_krea2_SFW_NSFW.json"}}
        self.assertEqual(webapp.run_facts(image), {"workflow": "krea2_SFW_NSFW", "resolution": "1272x2772", "count": 3})
        by_aspect = {"pipeline": "image", "argv": ["--aspect", "16:9", "--megapixels", "2"], "env": {}}
        self.assertEqual(webapp.run_facts(by_aspect), {"workflow": "Built-in", "resolution": "16:9 at 2 MP"})
        shorts = {"pipeline": "shorts", "argv": ["--runs", "3"], "env": {"AVATAR_SIZE": "576x1024", "COMFYUI_WORKFLOW": "w/avatar_lipsync.json"}}
        self.assertEqual(webapp.run_facts(shorts), {"workflow": "avatar_lipsync", "resolution": "576x1024", "count": 3})
        self.assertEqual(webapp.run_facts({"pipeline": "video", "argv": ["--resume", "r1"], "env": {}})["resolution"], "As the run was set up")

    def test_a_side_has_one_default_preset_at_most(self):
        if os.path.exists(webapp.PRESETS_PATH):
            os.remove(webapp.PRESETS_PATH)
        self.addCleanup(lambda: os.path.exists(webapp.PRESETS_PATH) and os.remove(webapp.PRESETS_PATH))
        post = lambda body: self.client.post("/api/presets", json=body)
        defaults = lambda: [p["name"] for p in self.client.get("/api/presets").get_json()["presets"]["image"] if p.get("default")]
        post({"side": "image", "name": "Edits", "values": {"workflow": "image_edit.json"}})
        post({"side": "image", "name": "Wallpaper", "values": {"aspect": "16:9"}})
        post({"side": "image", "name": "Edits", "default": True})
        self.assertEqual(defaults(), ["Edits"])
        post({"side": "image", "name": "Wallpaper", "default": True})
        self.assertEqual(defaults(), ["Wallpaper"], "making one the default unmakes the last")
        post({"side": "image", "name": "Wallpaper", "values": {"aspect": "21:9"}})
        self.assertEqual(defaults(), ["Wallpaper"], "saved over, it stays the default")
        post({"side": "image", "name": "Wallpaper", "default": False})
        self.assertEqual(defaults(), [])
        self.assertEqual(post({"side": "image", "name": "Nothing", "default": True}).status_code, 404)

    def test_a_job_started_later_waits_at_the_end_until_it_is_started(self):
        self.assertTrue(self.generate(start_later="1").get_json()["queued"], "it waits, though nothing is running")
        waiting = self.status()["queue"]["items"]
        self.assertEqual([item["later"] for item in waiting], [True])
        self.assertFalse(webapp.job.running)
        self.comfy.script = ["ok"] * 16
        self.assertTrue(self.generate(prompt="busy", review="1").get_json() is not None)
        self.wait_idle()
        self.assertEqual([item["label"] for item in self.status()["queue"]["items"]], [waiting[0]["label"]], "the one added after went first")
        # Added to the queue with nothing running, it doesn't start: the queue goes on hold, and it waits for Resume.
        self.assertTrue(self.client.post(f"/queue/run/start/{waiting[0]['id']}").get_json()["ok"])
        queue = self.status()["queue"]
        self.assertTrue(queue["held"] and not webapp.job.running, "not started")
        self.assertEqual([(item["id"], item.get("later")) for item in queue["items"]], [(waiting[0]["id"], None)], "in the queue, no longer Pending")
        # Its top-of-queue arrow is what starts it with nothing running.
        self.assertTrue(self.client.post(f"/queue/run/start/{waiting[0]['id']}?top=1").get_json()["ok"])
        self.wait_until(lambda: self.status()["queue"]["items"] == [], "started, it left the queue")
        self.wait_idle()

    def test_add_to_top_of_queue_goes_ahead_of_everything_waiting(self):
        with mock.patch.object(webapp.run_queue, "blocked", return_value=True):
            for prompt in ("first", "second"):
                self.assertTrue(self.generate(prompt=prompt).get_json()["queued"])
            self.assertTrue(self.generate(prompt="pending", start_later="1").get_json()["ok"])
            self.assertTrue(self.generate(prompt="top", queue_top="1").get_json()["queued"])
            items = self.status()["queue"]["items"]
        self.assertEqual([item["later"] for item in items], [None, None, None, True])
        self.assertEqual([item["label"] for item in items], ["1 video: top", "1 video: first", "1 video: second", "1 video: pending"])
        webapp.run_queue.items.clear()
        webapp.run_queue._save()

    def test_a_pending_jobs_arrow_puts_it_first_in_the_queue(self):
        with mock.patch.object(webapp.run_queue, "blocked", return_value=True):
            for prompt in ("first", "second"):
                self.assertTrue(self.generate(prompt=prompt).get_json()["queued"])
            self.assertTrue(self.generate(prompt="pending", start_later="1").get_json()["ok"])
            pending = self.status()["queue"]["items"][-1]
            self.assertTrue(self.client.post(f"/queue/run/start/{pending['id']}?top=1").get_json()["ok"])
            items = self.status()["queue"]["items"]
        self.assertEqual([item["label"] for item in items], ["1 video: pending", "1 video: first", "1 video: second"])
        self.assertFalse(any(item.get("later") for item in items))
        webapp.run_queue.items.clear()
        webapp.run_queue._save()

    def test_queueing_a_pending_job_only_queues_it_and_its_play_runs_it_now(self):
        for prompt in ("first", "second"):
            self.assertTrue(self.generate(prompt=prompt, start_later="1").get_json()["ok"])
        first, second = self.status()["queue"]["items"]
        webapp.run_queue.hold()
        self.assertTrue(self.client.post(f"/queue/run/start/{first['id']}").get_json()["ok"])
        items = self.status()["queue"]["items"]
        self.assertFalse(webapp.job.running, "on hold, the queue icon only queues it: nothing starts")
        self.assertEqual([(item["id"], bool(item["later"])) for item in items], [(first["id"], False), (second["id"], True)])
        self.comfy.script = ["ok"] * 16
        self.assertTrue(self.client.post(f"/queue/run/run-now/{second['id']}").get_json()["ok"], "play: it runs now")
        self.wait_idle()
        items = self.status()["queue"]["items"]
        self.assertEqual([item["id"] for item in items], [first["id"]], "the rest stay as they were, on hold")
        self.assertTrue(self.status()["queue"]["held"])

    def test_cancelled_edit_goes_back_where_it_came_from(self):
        for prompt in ("first", "second"):
            self.assertTrue(self.generate(prompt=prompt, start_later="1").get_json()["ok"])
        first, second = self.status()["queue"]["items"]
        webapp.run_queue.hold()
        for item in (first, second):
            self.assertTrue(self.client.post(f"/queue/run/start/{item['id']}").get_json()["ok"])
        edit = self.client.post(f"/queue/run/edit/{first['id']}").get_json()
        self.assertTrue(self.status()["queue"]["items"][0]["later"], "while edited, it waits in Pending")
        self.assertTrue(self.client.post(f"/queue/run/edit/{first['id']}/cancel", json={"token": edit["token"]}).get_json()["ok"])
        items = self.status()["queue"]["items"]
        self.assertEqual([(item["id"], bool(item["later"])) for item in items], [(first["id"], False), (second["id"], False)],
                         "cancelled, it is back in the queue, in its place")
        # One that was pending goes back to Pending.
        self.assertTrue(self.generate(prompt="third", start_later="1").get_json()["ok"])
        third = self.status()["queue"]["items"][-1]
        edit = self.client.post(f"/queue/run/edit/{third['id']}").get_json()
        self.assertTrue(self.client.post(f"/queue/run/edit/{third['id']}/cancel", json={"token": edit["token"]}).get_json()["ok"])
        self.assertTrue(self.status()["queue"]["items"][-1]["later"])

    def test_edit_queued_generation_keeps_inputs_and_replaces_at_front(self):
        self.assertTrue(self.generate(prompt="original", start_later="1").get_json()["ok"])
        original = self.status()["queue"]["items"][0]
        self.assertTrue(self.generate(prompt="other", start_later="1").get_json()["ok"])
        response = self.client.post(f"/queue/run/edit/{original['id']}")
        edit = response.get_json()
        self.assertTrue(edit["ok"])
        self.assertEqual(edit["form"]["prompt"], ["original"])
        self.assertEqual(edit["files"], ["image"])
        with self.client.get(f"/queue/run/edit/{original['id']}/file/image", headers={"X-Queue-Edit-Token": edit["token"]}) as response:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(f"/queue/run/edit/{original['id']}/file/image", headers={"X-Queue-Edit-Token": "wrong"}).status_code, 404)
        self.assertFalse(self.client.post(f"/queue/run/start/{original['id']}").get_json()["ok"])
        # A stale token never replaces the pending original.
        bad = self.generate(prompt="changed", queue_edit_id=str(original["id"]), queue_edit_token="wrong")
        self.assertEqual(bad.status_code, 409)
        self.assertEqual(len(self.status()["queue"]["items"]), 2)
        webapp.run_queue.hold()
        saved = self.generate(prompt="changed", queue_edit_id=str(original["id"]), queue_edit_token=edit["token"])
        self.assertTrue(saved.get_json()["ok"], saved.get_json())
        items = self.status()["queue"]["items"]
        self.assertEqual([item["id"] for item in items], [original["id"], original["id"] + 1])
        self.assertFalse(items[0]["later"])
        self.assertEqual(items[0]["facts"]["prompt"], "changed")
        self.assertEqual(self.client.post(f"/queue/run/edit/{original['id']}/cancel", json={"token": edit["token"]}).status_code, 409)

    def test_edit_legacy_video_reconstructs_original_form_and_inputs(self):
        self.assertTrue(self.generate(prompt="legacy", start_later="1", review="1").get_json()["ok"])
        item = webapp.run_queue.items[0]
        item.pop("form")
        item.pop("form_files")
        result = self.client.post(f"/queue/run/edit/{item['id']}").get_json()
        self.assertTrue(result["ok"])
        self.assertEqual(result["form"]["prompt"], "legacy")
        self.assertEqual(result["form"]["duration"], "60")
        self.assertEqual(result["form"]["review"], "1")
        self.assertEqual(result["files"], ["image"])
        with self.client.get(f"/queue/run/edit/{item['id']}/file/image", headers={"X-Queue-Edit-Token": result["token"]}) as response:
            self.assertEqual(response.status_code, 200)
        self.assertTrue(self.client.post(f"/queue/run/edit/{item['id']}/cancel", json={"token": result["token"]}).get_json()["ok"])
        self.assertTrue(item["later"])
        self.assertNotIn("edit_token", item)

    def test_removing_an_edited_pending_job_invalidates_its_session(self):
        self.assertTrue(self.generate(prompt="editing", start_later="1").get_json()["ok"])
        self.assertTrue(self.generate(prompt="keep", start_later="1").get_json()["ok"])
        first, other = self.status()["queue"]["items"]
        edit = self.client.post(f"/queue/run/edit/{first['id']}").get_json()
        self.assertTrue(edit["ok"])
        self.assertTrue(self.client.post(f"/queue/run/remove/{first['id']}").get_json()["ok"])
        self.assertEqual(self.client.post(f"/queue/run/edit/{first['id']}/cancel", json={"token": edit["token"]}).status_code, 409)
        self.assertEqual(self.generate(prompt="stale", queue_edit_id=str(first["id"]), queue_edit_token=edit["token"]).status_code, 409)
        self.assertEqual([item["id"] for item in self.status()["queue"]["items"]], [other["id"]])
        self.assertTrue(self.generate(prompt="new", start_later="1").get_json()["ok"])
        self.assertEqual(len(self.status()["queue"]["items"]), 2)

    def test_a_paused_queue_can_run_one_generation_without_resuming_the_rest(self):
        self.comfy.script = ["ok"] * 16
        self.assertTrue(self.generate(prompt="leave waiting", start_later="1").get_json()["queued"])
        first = self.status()["queue"]["items"][0]
        webapp.run_queue.hold()
        self.assertTrue(self.generate(prompt="run this one", start_later="1").get_json()["queued"])
        waiting = self.status()["queue"]["items"]
        self.assertEqual(len(waiting), 2)

        reply = self.client.post(f"/queue/run/run-now/{waiting[1]['id']}")
        self.assertEqual(reply.get_json(), {"ok": True})
        self.wait_idle()

        status = self.status()["queue"]
        self.assertTrue(status["held"], "the remaining generation stays paused")
        self.assertEqual([item["id"] for item in status["items"]], [waiting[0]["id"]])
        self.assertEqual(status["results"][-1]["outcome"], "done")

    def test_generate_on_a_paused_idle_queue_starts_at_once_and_leaves_the_rest_paused(self):
        self.comfy.script = ["ok"] * 16
        self.assertTrue(self.generate(prompt="leave waiting", start_later="1").get_json()["queued"])
        webapp.run_queue.hold()
        waiting = self.status()["queue"]["items"]

        self.assertFalse(self.generate(prompt="straight away").get_json()["queued"])
        self.wait_idle()

        status = self.status()["queue"]
        self.assertTrue(status["held"], "what was waiting stays paused")
        self.assertEqual([item["id"] for item in status["items"]], [waiting[0]["id"]])
        self.assertEqual(status["results"][-1]["outcome"], "done")

    def test_your_phone_is_told_when_a_job_ends_if_ntfy_is_set(self):
        sent = []
        with mock.patch.dict(os.environ, {"NTFY_TOPIC": "my-topic"}), \
                mock.patch.object(webapp.requests, "post", side_effect=lambda url, **kw: sent.append((url, kw))):
            webapp.notify_ended({"label": "A storm", "pipeline": "video"}, "done")
            webapp.notify_ended({"label": "Stopped", "pipeline": "video"}, "stopped")
            self.wait_until(lambda: sent, "the message")
        self.assertEqual(len(sent), 1, "only finished or failed")
        url, kw = sent[0]
        self.assertEqual(url, "https://ntfy.sh/my-topic")
        self.assertEqual(kw["headers"]["Title"].decode(), "Finished: A storm")
        sent.clear()
        with mock.patch.dict(os.environ, {"NTFY_TOPIC": ""}), mock.patch.object(webapp.requests, "post", side_effect=lambda *a, **k: sent.append(1)):
            webapp.notify_ended({"label": "x"}, "done")
        self.assertEqual(sent, [], "nothing without a topic")

    def test_a_failure_we_know_is_said_in_plain_words(self):
        job = types.SimpleNamespace(first_line=0, lines=[])
        say = lambda *texts: (job.lines.clear(), job.lines.extend({"n": n, "text": t} for n, t in enumerate(texts, 1)), webapp.explain_failure(job, 1))[2]
        self.assertTrue(say("🎬 Clip 1/3", "❌ ComfyUI reported an error: torch.OutOfMemoryError: CUDA out of memory.")[0].startswith("Out of GPU memory"))
        self.assertTrue(say("⚠️ Gemini: 429 RESOURCE_EXHAUSTED")[0].startswith("The LLM's quota is used up"))
        self.assertTrue(say("❌ ComfyUI isn't running at http://127.0.0.1:8188.")[0].startswith("ComfyUI wasn't running"))
        self.assertTrue(say("Needs the node LayerColor: Brightness Contrast, which isn't installed.")[0].startswith("A node this workflow needs"))
        self.assertIsNone(say("⚠️ Could not write the metadata (no quota). Using the film's title.")[0], "a warning about metadata isn't the LLM's quota")
        plain, said = say("❌ Something odd happened.")
        self.assertIsNone(plain, "one we don't know is left as it said")
        self.assertIn("Something odd happened", said)
        # Its own lines stay under the plain words.
        self.assertIn("CUDA out of memory", say("❌ CUDA out of memory.")[1])

    def test_an_exact_prompt_goes_to_every_clip_without_an_llm(self):
        self.comfy.script = ["ok"] * 16
        self.assertTrue(self.generate(prompt_mode="direct", prompt="A red kite over a grey sea", duration="20").get_json()["ok"])
        self.wait_idle()
        run = self.only_run()
        self.assertEqual(self.claude.requests, [], "no LLM is asked")
        self.assertTrue(run.shots and all(shot["prompt"] == "A red kite over a grey sea" for shot in run.shots))
        self.assertEqual(sum(shot["seconds"] for shot in run.shots), 20)

    def test_discard(self):
        self.assertTrue(self.generate(review="1").get_json()["ok"])
        self.wait_idle()
        run = self.only_run()
        self.assertTrue(self.client.post(f"/runs/{run.id}/discard").get_json()["ok"])
        self.assertEqual(list_runs(), [])
        self.assertEqual(self.client.post(f"/runs/{run.id}/discard").status_code, 404)

    def test_inputs_dont_pile_up(self):
        for _ in range(2):
            self.assertTrue(self.generate(review="1").get_json()["ok"])
            self.wait_idle()
        self.assertEqual(len(os.listdir(paths.INPUTS_DIR)), 1, "only the last one, until the next film")

    def test_failed_plan_says_why_and_leaves_nothing(self):
        self.claude.status = 401
        self.assertTrue(self.generate(review="1").get_json()["ok"])
        self.wait_idle()
        status = self.status()
        self.assertEqual(status["returncode"], 1)
        self.assertTrue(any("ANTHROPIC_API_KEY" in line["text"] for line in status["lines"]), status["lines"])
        self.assertEqual(list_runs(), [])
        self.assertIsNone(status["queue"]["results"][-1]["run_id"])
        self.assertIsNotNone(status["queue"]["results"][-1]["job_id"])

    def test_a_failure_without_a_saved_run_keeps_its_settings(self):
        self.claude.status = 401
        self.assertTrue(self.generate(review="1", prompt="a fox crossing the snow").get_json()["ok"])
        self.wait_idle()
        failure = self.status()["queue"]["results"][-1]
        self.assertTrue(failure["recoverable"])
        self.assertNotIn("job", failure, "its command line and environment stay on the server")
        image = webapp.run_queue.recoverable()[-1]["image"]
        video_panel.clean_inputs()
        self.assertTrue(os.path.exists(image), "its upload outlasts the cleanup")

        reply = self.client.post(f"/queue/run/failed/{failure['job_id']}/requeue").get_json()
        self.assertTrue(reply["ok"])
        status = self.status()
        self.assertFalse(any(result.get("job_id") == failure["job_id"] for result in status["queue"]["results"]))
        pending = next(item for item in status["queue"]["items"] if item["id"] == reply["id"])
        self.assertTrue(pending["later"], "back in Pending, not started")
        edit = self.client.post(f"/queue/run/edit/{reply['id']}").get_json()
        self.assertTrue(edit["ok"], edit)
        self.assertEqual(edit["form"]["prompt"], ["a fox crossing the snow"])
        self.assertEqual(self.client.post(f"/queue/run/failed/{failure['job_id']}/requeue").status_code, 404)

    def test_bad_forms_are_refused(self):
        for fields, expected in (
            ({"prompt": ""}, "what should happen"),
            ({"image": None}, "image"),
            ({"image": (io.BytesIO(b"not an image"), "x.png")}, "isn't an image"),
            ({"duration": "4"}, "5-600"),
            ({"duration": "605"}, "5-600"),
            ({"duration": "soon"}, "whole number"),
            ({"start": "sideways"}, "start mode"),
            ({"llm": "gpt"}, "Unknown LLM"),
            ({"size": "big"}, "1280x736"),
        ):
            reply = self.generate(**fields)
            self.assertEqual(reply.status_code, 400, fields)
            self.assertIn(expected, reply.get_json()["error"])
        self.assertEqual(self.claude.requests, [])

    def test_chosen_llm_without_a_key_is_refused(self):
        with mock.patch.object(video_panel.planner, "llm_configured", return_value=False):
            reply = self.generate()
        self.assertEqual(reply.status_code, 400)
        self.assertIn("no credentials", reply.get_json()["error"])

    def test_an_oversized_image_says_so(self):
        reply = self.generate(image=(io.BytesIO(b"x" * (webapp.MAX_UPLOAD_BYTES + 1)), "huge.png"))
        self.assertEqual(reply.status_code, 413)
        self.assertIn("MB", reply.get_json()["error"])

    def test_nothing_outside_the_folders_can_be_reached(self):
        secret = os.path.join(paths.DATA_ROOT, "secret.mp4")
        with open(secret, "w") as f:
            f.write("x")
        self.addCleanup(os.remove, secret)
        for url in ("/videos/output/..%2Fsecret.mp4", "/download/video/..%2Fsecret.mp4", "/videos/nowhere/secret.mp4"):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(self.client.post("/delete/video/..%2Fsecret.mp4").status_code, 404)
        self.assertTrue(os.path.exists(secret))
        for bad_id in ("..", "run_1", "..%2F..%2Fetc"):
            self.assertEqual(self.client.get(f"/runs/{bad_id}").status_code, 404, bad_id)

    # --- Workflows saved in ComfyUI ---

    def save_workflows(self):
        broken = saved_workflow()
        next(n for n in broken["nodes"] if n["id"] == 1)["widgets_values"] = ["gone.safetensors"]
        self.comfy.saved, self.comfy.object_info = {"wan.json": saved_workflow(), "broken.json": broken,
                                                    "r2v.json": reference_workflow(), "t2v.json": text_only_workflow()}, OBJECT_INFO

    def test_saved_workflows_only_list_what_runs_and_say_why_elsewhere(self):
        self.save_workflows()
        reply = self.client.get("/api/workflows?pipeline=video").get_json()
        self.assertTrue(reply["online"])
        with open(os.path.join(webapp.SAVED_WORKFLOWS_DIR, "not_listed.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"broken": "Needs gone.safetensors, which isn't installed."})
        self.assertEqual(self.client.get("/api/workflows?pipeline=shorts").get_json()["workflows"], [], "none are tuned for Shorts")
        self.assertEqual(reply["workflows"], [
            {"name": "r2v.json", "label": "r2v", "takes": {"min_images": 0, "max_images": 20}, "clip_seconds": [5, 10, 8], "openh3": False, "h3_multishot": False, "h3_director": False},
            {"name": "t2v.json", "label": "t2v", "takes": {"min_images": 0, "max_images": 0, "options": SAVED_OPTIONS}, "clip_seconds": [5, 10, 8], "openh3": False, "h3_multishot": False, "h3_director": False},
            {"name": "wan.json", "label": "wan", "takes": {"min_images": 0, "max_images": 1, "options": SAVED_OPTIONS}, "clip_seconds": [5, 10, 8], "openh3": False, "h3_multishot": False, "h3_director": False}],
            "each with the workflow's own options: a KSampler's steps here")

    def test_a_films_workflow_options_are_used_and_kept(self):
        self.save_workflows()
        self.assertTrue(self.generate(workflow="wan.json", opt_steps="12").get_json()["ok"])
        self.wait_idle()
        run = self.only_run()
        self.assertTrue(run.final, [l["text"] for l in webapp.job.lines][-15:])
        self.assertEqual(run.options, {"steps": "12"})
        self.assertTrue(all(p["prompt"]["6"]["inputs"]["steps"] == 12 for p in self.comfy.prompts), "every clip")
        clips = len(self.comfy.prompts)
        film = os.path.basename(run.final)
        self.assertTrue(film.endswith("_wan.mp4") and run.id not in film, "<title>_<workflow>.mp4")
        self.wait_until(lambda: next(v for v in webapp.list_videos("video") if v["name"] == film)["resolution"] is not None, "video metadata")
        listed = next(v for v in webapp.list_videos("video") if v["name"] == film)
        self.assertEqual(listed["resolution"], "64x64")
        self.assertGreater(listed["duration"], 0)
        self.assertEqual(listed["llm"], run.llm)
        # The same again: what it was made with, and the image it was given.
        settings = self.client.get(f"/runs/{run.id}").get_json()["settings"]
        self.assertEqual((settings["workflow"], settings["options"], settings["images"]), ("wan.json", {"steps": "12"}, 1))
        # Every field of the form it was queued with, so it reopens exactly as it was made.
        self.assertEqual((settings["form"]["workflow"], settings["form"]["opt_steps"]), ("wan.json", "12"))
        self.assertEqual((settings["prompt_mode"], settings["llm"]), ("llm", run.llm))
        self.assertEqual(self.client.get(f"/runs/{run.id}/inputs/image/1").status_code, 200)
        self.assertEqual(self.client.get(f"/runs/{run.id}/inputs/image/2").status_code, 404)
        self.assertEqual(self.client.get(f"/runs/{run.id}/inputs/secret/1").status_code, 404)
        self.assertEqual((listed["run"], listed["model"]), (run.id, "wan"), "the film still finds its run, and shows its workflow")
        self.assertTrue(self.client.post(f"/runs/{run.id}/redo/1").get_json()["ok"])
        self.wait_idle()
        self.assertEqual(os.path.basename(self.only_run().final), film, "made again, it keeps its name")
        self.assertEqual(self.comfy.prompts[clips]["prompt"]["6"]["inputs"]["steps"], 12, "a shot made again is made the same way")
        self.assertEqual(self.generate(workflow="wan.json", opt_steps="0").status_code, 400)

    def test_a_run_renders_with_the_chosen_workflow_and_keeps_it(self):
        self.save_workflows()
        self.assertEqual(self.generate(workflow="broken.json").status_code, 400)
        self.assertEqual(self.generate(workflow="nowhere.json").status_code, 400)
        self.assertTrue(self.generate(workflow="wan.json").get_json()["ok"])
        self.wait_idle()

        run = self.only_run()
        self.assertTrue(run.final, [l["text"] for l in webapp.job.lines][-15:])
        self.assertEqual(os.path.basename(run.workflow), "wan.json")
        sent = self.comfy.prompts[0]["prompt"]
        self.assertEqual(sent["2"]["inputs"]["text"], "Prompt number 1.")
        self.assertEqual(sent["3"]["inputs"]["text"], "saved negative")
        self.assertEqual(sent["4"]["inputs"]["image"], "uploaded.png")
        seconds = run.shots[0]["seconds"]
        self.assertEqual(sent["5"]["inputs"]["length"], seconds * 24 + 1, "in frames, at the workflow's 24 fps")
        self.assertEqual((sent["5"]["inputs"]["width"], sent["5"]["inputs"]["height"]), (64, 64))
        self.assertIs(sent["11"]["inputs"]["save_output"], False)

        rendered = len(self.comfy.prompts)
        self.assertTrue(self.client.post(f"/runs/{run.id}/redo/8").get_json()["ok"])
        self.wait_idle()
        self.assertEqual(len(self.comfy.prompts), rendered + 1)
        self.assertIn("5", self.comfy.prompts[-1]["prompt"], "the redo uses it too")

    def test_without_an_image_the_input_comes_out_of_the_workflow(self):
        self.save_workflows()
        self.assertTrue(self.generate(workflow="wan.json", image=None).get_json()["ok"])
        self.wait_idle()
        run = self.only_run()
        self.assertTrue(run.final, [l["text"] for l in webapp.job.lines][-15:])
        self.assertEqual(run.image_count, 0)
        first, second = (p["prompt"] for p in self.comfy.prompts[:2])
        self.assertNotIn("start_image", first["5"]["inputs"], "text only, so it doesn't load the saved example")
        self.assertEqual(second["5"]["inputs"]["start_image"], ["4", 0], "after that, it continues from the last frame")
        self.assertEqual(second["4"]["inputs"]["image"], "uploaded.png")
        self.assertEqual(len(self.comfy.uploads), len(self.comfy.prompts) - 1)

    def test_a_text_only_workflow_takes_no_image(self):
        self.save_workflows()
        self.assertEqual(self.generate(workflow="t2v.json").status_code, 400, "it has nowhere to put an image")
        self.assertTrue(self.generate(workflow="t2v.json", image=None).get_json()["ok"])
        self.wait_idle()
        run = self.only_run()
        self.assertTrue(run.final, [l["text"] for l in webapp.job.lines][-15:])
        self.assertEqual(run.start, "image", "nothing to start the next clip on")
        self.assertEqual(self.comfy.uploads, [])

    def test_a_reference_workflow_gets_every_clip_all_its_images(self):
        self.save_workflows()
        image = lambda: (io.BytesIO(png_bytes()), "ref.png")
        too_many = {f"image_{number}": image() for number in range(2, 22)}
        self.assertEqual(self.generate(workflow="r2v.json", **too_many).status_code, 400, "twenty references at most")
        self.assertTrue(self.generate(workflow="r2v.json", image_2=image()).get_json()["ok"])
        self.wait_idle()
        run = self.only_run()
        self.assertTrue(run.final, [l["text"] for l in webapp.job.lines][-15:])
        self.assertEqual((run.image_count, run.start), (2, "image"))
        for sent in (p["prompt"] for p in self.comfy.prompts):
            self.assertEqual((sent["2"]["inputs"]["image"], sent["1"]["inputs"]["image"]), ("uploaded.png", "uploaded.png"))
            self.assertEqual(sent["6"]["inputs"]["width"], 64, "the size picker's link is replaced")
            self.assertEqual(sent["3"]["inputs"]["value"][:6], "Prompt")
            added = [node_id for node_id, node in sent.items() if "added by the pipeline" in node["_meta"]["title"]]
            self.assertEqual(added, [], "the references left empty come out, with their links")
            self.assertEqual(sorted(name for name in sent["6"]["inputs"] if name.startswith("ref_images")),
                             ["ref_images.ref_image_0", "ref_images.ref_image_1"])
        self.assertTrue(os.path.exists(run.image_paths[1]))
        guide = self.claude.requests[0]["body"]["messages"][0]["content"][-1]["text"]
        self.assertIn("<Picture 2> adds to it", guide, "extra context, by default")
        self.assertNotIn("for you alone", guide, "the video model sees this one")

    def test_the_built_in_workflow_still_needs_its_image(self):
        self.assertEqual(self.generate(image=None).status_code, 400)
        image = lambda: (io.BytesIO(png_bytes()), "b.png")
        self.assertEqual(self.generate(image_2=image(), image_3=image()).status_code, 400)

    def test_image_2_needs_an_image_1_to_add_to(self):
        self.save_workflows()
        image = lambda: (io.BytesIO(png_bytes()), "b.png")
        for workflow in ("", "wan.json", "r2v.json"):
            reply = self.generate(workflow=workflow, image=None, image_2=image())
            self.assertEqual(reply.status_code, 400, workflow)
            self.assertIn("in order", reply.get_json()["error"])
        self.assertEqual(self.generate(workflow="t2v.json", image_2=image()).status_code, 400)
        self.assertEqual(self.claude.requests, [])

    def test_an_unknown_role_for_image_2_is_refused(self):
        reply = self.generate(image_2_role="villain")
        self.assertEqual(reply.status_code, 400)
        self.assertIn("image 2", reply.get_json()["error"])

    def test_with_one_input_image_2_reaches_the_clips_through_the_prompts(self):
        first, second = png_bytes((200, 10, 30)), png_bytes((10, 30, 200))
        self.assertTrue(self.generate(image=(io.BytesIO(first), "a.png"), image_2=(io.BytesIO(second), "b.png")).get_json()["ok"])
        self.wait_idle()
        run = self.only_run()
        self.assertTrue(run.final, [l["text"] for l in webapp.job.lines][-15:])
        self.assertEqual((run.image_count, run.start), (1, "chain"), "still a continuous take from image 1")
        self.assertEqual(len(run.image_paths), 1)

        content = self.claude.requests[0]["body"]["messages"][0]["content"]
        self.assertEqual([part["type"] for part in content], ["image", "image", "text"], "the LLM sees both")
        self.assertIn("for you alone", content[-1]["text"])
        self.assertIn("It shows a place", content[-1]["text"], "extra context, by default")
        # Every clip after the first starts on the last frame, and none of them starts on image 2.
        with Image.open(run.image_path) as kept:
            self.assertEqual(kept.getpixel((0, 0)), (200, 10, 30), "the run keeps image 1 as its first frame")
        with open(run.image_path, "rb") as f:
            self.assertTrue(self.comfy.uploads[0].startswith(f.read()))
        self.assertEqual(len(self.comfy.uploads), len(self.comfy.prompts))
        self.assertTrue(any("only reaches them through" in l["text"] for l in webapp.job.lines))

    def test_image_2_can_be_another_character(self):
        self.assertTrue(self.generate(image_2=(io.BytesIO(png_bytes()), "b.png"), image_2_role="character").get_json()["ok"])
        self.wait_idle()
        guide = self.claude.requests[0]["body"]["messages"][0]["content"][-1]["text"]
        self.assertIn("another character", guide)
        self.assertIn("describe how they look in full", guide)
        self.assertNotIn("It shows a place", guide)

    def test_each_image_sends_its_role(self):
        flags, error = video_panel.build_options({"image_2_role": "view", "image_3_role": "place", "image_5_role": "character"})
        self.assertIsNone(error)
        self.assertEqual([flags[i + 1] for i, flag in enumerate(flags) if flag == "--image-role"], ["view", "place"],
                         "in order, up to the first box without one")
        self.assertIn("image 3", video_panel.build_options({"image_2_role": "view", "image_3_role": "villain"})[1])

    def test_saved_workflows_stay_listed_with_comfyui_off(self):
        self.save_workflows()
        self.client.get("/api/workflows")
        webapp._comfyui_cache.update(at=0.0)
        with mock.patch.dict(os.environ, {"COMFYUI_URL": "http://127.0.0.1:9"}):
            reply = self.client.get("/api/workflows").get_json()
            self.assertFalse(reply["online"])
            self.assertEqual(reply["workflows"], [
                {"name": "r2v.json", "label": "r2v", "takes": {"min_images": 0, "max_images": 20}, "clip_seconds": [5, 10, 8], "openh3": False, "h3_multishot": False, "h3_director": False},
                {"name": "t2v.json", "label": "t2v", "takes": {"min_images": 0, "max_images": 0, "options": SAVED_OPTIONS}, "clip_seconds": [5, 10, 8], "openh3": False, "h3_multishot": False, "h3_director": False},
                {"name": "wan.json", "label": "wan", "takes": {"min_images": 0, "max_images": 1, "options": SAVED_OPTIONS}, "clip_seconds": [5, 10, 8], "openh3": False, "h3_multishot": False, "h3_director": False}])
            self.assertEqual(os.path.basename(video_panel.chosen_workflow({"workflow": "wan.json"})[0]["COMFYUI_WORKFLOW"]), "wan.json")
        webapp._comfyui_cache.update(at=0.0)

    def test_the_log_says_what_each_line_is(self):
        self.assertEqual([webapp.line_kind(text) for text in ("▶ Stage 1/3: Plan", "❌ failed", "⚠️ careful", "✅ Done", "🎛️ ComfyUI · Sampling · 4s", "plain")],
                         ["stage", "err", "warn", "ok", "comfy", ""])
        webapp.job.log("🎛️ ComfyUI · Sampling · 4s")
        self.assertEqual(webapp.job.lines[-1]["k"], "comfy")

    def test_the_workflow_of_the_last_run_can_be_looked_at(self):
        self.save_workflows()
        self.comfy.saved["video_wan.json"] = saved_workflow()
        self.client.get("/api/workflows?pipeline=video")
        path = os.path.join(webapp.SAVED_WORKFLOWS_DIR, "video_wan.json")
        saved = webapp.job.workflow
        try:
            webapp.job.workflow = None
            self.assertEqual(self.client.get("/api/run-workflow").status_code, 404)
            webapp.job.workflow = {"path": path, "pipeline": "video", "options": {"steps": "7"}}
            reply = self.client.get("/api/run-workflow").get_json()
            self.assertEqual(reply["name"], "wan")
            self.assertEqual(next(option for option in reply["options"] if option["label"] == "Steps")["value"], "7")
            sampler = next(node for node in reply["nodes"] if node["type"] == "KSampler")
            self.assertEqual(sampler["inputs"]["steps"], "7", "the options this run was started with")
        finally:
            webapp.job.workflow = saved

    def test_workflow_display_names_keep_identifiers(self):
        self.comfy.saved, self.comfy.object_info = {"video_Test Name.json": saved_workflow()}, OBJECT_INFO
        reply = self.client.get("/api/workflows?pipeline=video").get_json()["workflows"]
        self.assertEqual([(w["name"], w["label"]) for w in reply], [("video_Test Name.json", "Test Name")])
        self.assertEqual(webapp.display_label("folder\\IMAGE_Test Name.json"), "folder\\Test Name")
        self.assertEqual(webapp.display_label("shorts_name_shorts.json"), "name_shorts")
        self.assertEqual(webapp.display_label("image_.json"), "image_")
        self.assertEqual(webapp.display_label("other_name.json"), "other_name")
        self.assertEqual(video_panel.chosen_workflow({"workflow": "video_missing.json"})[2],
                         "ComfyUI has no saved workflow called missing any more.")
        self.assertEqual(image_panel.chosen_workflow({"workflow": "image_missing.json"})[2],
                         "ComfyUI has no saved workflow called missing any more.")
        self.assertEqual(shorts_panel.saved_workflow_path("shorts_missing.json")[1],
                         "ComfyUI has no saved workflow called missing any more.")

    def test_nsfw_tags_are_persistent_and_hide_finished_output(self):
        path = os.path.join(self.temp, "nsfw.json")
        with mock.patch.object(webapp, "NSFW_PATH", path), \
             mock.patch.object(webapp.PIPELINES["image"], "load_run", return_value=object()), \
             mock.patch.object(webapp, "safe_video_path", return_value="film.mp4"), \
             mock.patch.object(webapp, "_video_nsfw_key", return_value=("video", "run_video")):
            post = lambda kind, identifier, nsfw: self.client.post("/api/output/nsfw",
                                                                  json={"kind": kind, "id": identifier, "nsfw": nsfw})
            self.assertTrue(post("image", "image_a", True).get_json()["ok"])
            self.assertTrue(post("video", "film.mp4", True).get_json()["ok"])
            tags = webapp._read_nsfw()
            self.assertEqual(tags, {"image": ["image_a"], "video": ["run_video"], "video_file": [],
                                    "video_sources": {"film.mp4": "run_video"}})
            payload = {"videos": {"video": [{"name": "film.mp4"}, {"name": "upscaled.mp4"}]},
                       "image_sets": [{"id": "image_a"}, {"id": "image_b"}],
                       "queue": {"results": [{"pipeline": "image", "run_id": "image_a"},
                                             {"pipeline": "video", "run_id": "run_video"},
                                             {"pipeline": "shorts", "run_id": "run_short"}]},
                       "made_now": [{"pipeline": "image", "run_id": "image_a"},
                                    {"pipeline": "image", "run_id": "image_b"}]}
            webapp._apply_nsfw(payload, tags, {})
            self.assertTrue(all(film["nsfw"] for film in payload["videos"]["video"]))
            self.assertEqual([s["nsfw"] for s in payload["image_sets"]], [True, False])
            self.assertEqual([r["nsfw"] for r in payload["finished_results"]], [True, True, False],
                             "marked, so Finished shows them only under the NSFW filter")
            self.assertEqual([r["nsfw"] for r in payload["made_now"]], [True, False])
            self.assertEqual(len(payload["queue"]["results"]), 3, "Failed and queue history remain intact")
            payload["made_now"] = [{"pipeline": "image", "run_id": "image_b"}]
            webapp._apply_nsfw(payload, tags, {}, private=True)
            self.assertEqual([r["nsfw"] for r in payload["finished_results"]], [True, True, False], "Private mode: tags as they are")
            self.assertEqual([r["nsfw"] for r in payload["made_now"]], [True], "made in Private mode: NSFW before it is tagged")
            self.assertTrue(post("video", "upscaled.mp4", False).get_json()["ok"])
            self.assertTrue(post("image", "image_a", False).get_json()["ok"])
            self.assertEqual(webapp._read_nsfw(), {"image": [], "video": [], "video_file": [], "video_sources": {}})
            self.assertEqual(post("shorts", "short.mp4", True).status_code, 400)
            self.assertEqual(self.client.post("/api/output/nsfw", json={"kind": "video", "id": "x", "nsfw": "yes"}).status_code, 400)
            with open(path, "w", encoding="utf-8") as f:
                f.write("{broken")
            failed = post("image", "image_a", True)
            self.assertEqual(failed.status_code, 500)
            self.assertEqual(failed.get_json()["error"], "Could not save private tags. Check the panel log.")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "{broken", "a corrupt tags file is not silently replaced")

    def test_nsfw_video_keys_group_upscales_and_allow_unmatched_files(self):
        film = types.SimpleNamespace(id="run_20260812_193000")
        known = {"film.mp4": film}
        self.assertEqual(webapp._video_nsfw_key("film.mp4", known), ("video", film.id))
        self.assertEqual(webapp._video_nsfw_key("film_upscaled.mp4", known), ("video", film.id))
        self.assertEqual(webapp._video_nsfw_key("orphan.mp4", known), ("video_file", "orphan.mp4"))
        tags = {"image": [], "video": [film.id], "video_file": [], "video_sources": {"film.mp4": film.id}}
        payload = {"videos": {"video": [{"name": "film_upscaled.mp4"}]}, "image_sets": [],
                   "queue": {"results": []}, "made_now": []}
        webapp._apply_nsfw(payload, tags, {})
        self.assertTrue(payload["videos"]["video"][0]["nsfw"], "an upscale stays hidden if its source run is removed")

    def test_the_built_in_workflow_is_still_the_default(self):
        self.assertEqual(video_panel.chosen_workflow({}), ({}, video_panel.BUILT_IN_TAKES, None))
        self.assertEqual(video_panel.chosen_workflow({"workflow": ""}), ({}, video_panel.BUILT_IN_TAKES, None))
        self.assertIn(b'<select id="videoWorkflow"', self.client.get("/").data)

    @unittest.skipUnless(os.name == "nt", "File Explorer is Windows only")
    def test_open_folder_only_on_this_pc(self):
        with mock.patch.object(webapp.os, "startfile") as startfile:
            self.assertTrue(self.client.post("/folders/uploaded/open").get_json()["ok"])
            startfile.assert_called_once_with(SHORTS_UPLOADED)
            self.assertTrue(os.path.isdir(SHORTS_UPLOADED), "it exists before the first upload")
            startfile.reset_mock()
            self.assertEqual(self.client.post("/folders/nowhere/open").status_code, 404)
            phone = {"REMOTE_ADDR": "192.168.1.20"}
            self.assertEqual(self.client.post("/folders/output/open", environ_base=phone).status_code, 403)
            startfile.assert_not_called()
            self.assertIn(b'File Explorer." hidden>', self.client.get("/", environ_base=phone).data)
        self.assertNotIn(b'File Explorer." hidden>', self.client.get("/").data)

    def test_upload_needs_keys(self):
        self.assertEqual(self.client.post("/publish", data={"privacy": "private"}).status_code, 400)
        self.assertIn(b"disabled title", self.client.get("/").data)

    def test_upload_queue(self):
        os.makedirs(SHORTS_READY, exist_ok=True)
        name = "short_20261101_120000_ltx.mp4"
        make_clip(os.path.join(SHORTS_READY, name), 1)
        self.addCleanup(lambda: os.path.exists(os.path.join(SHORTS_READY, name)) and os.remove(os.path.join(SHORTS_READY, name)))
        fake_upload = [sys.executable, "-c", "print('uploading')"]
        keys = {"YOUTUBE_CLIENT_ID": "a", "YOUTUBE_CLIENT_SECRET": "b", "YOUTUBE_REFRESH_TOKEN": "c"}
        with mock.patch.dict(os.environ, keys):
            with mock.patch.object(webapp.uploads, "start", wraps=lambda argv, env=None, keep_log=False, pipeline="shorts": webapp.Job.start(webapp.uploads, fake_upload)) as start:
                self.assertEqual(self.client.post("/publish", data={"video": name, "privacy": "unlisted"}).get_json(), {"ok": True, "queued": False})
                self.assertEqual(self.client.post("/publish", data={"video": name}).status_code, 409, "it's already claimed")
                self.wait_until(lambda: webapp.uploads.idle, "the upload to end")
                self.assertEqual(start.call_args.args[0][-3:], ["--privacy", "unlisted", name])
        webapp.upload_queue.pending()

    # --- Sign in and restarts ---

    def test_password(self):
        with mock.patch.dict(os.environ, {"APP_PASSWORD": "open sesame"}):
            client = webapp.app.test_client()
            self.assertEqual(client.get("/").status_code, 302)
            self.assertEqual(client.get("/api/status").status_code, 302)
            self.assertEqual(client.post("/generate/video").status_code, 302)
            page = client.get("/login").get_data(as_text=True)
            self.assertIn(":root { --accent: var(--neutral); }", page, "the way in is Status's silver")
            self.assertIn('<span class="spinner" aria-hidden="true"></span><span id="loginLabel">Sign in</span>', page)
            self.assertIn('<script defer src="/static/login.js"></script>', page)
            with open(os.path.join(ROOT, "panel", "static", "login.js"), encoding="utf-8") as f:
                self.assertIn("form.classList.add('busy');", f.read(), "sent, it shows it is signing in")
            self.assertNotIn('class="card wrong"', page)
            wrong = client.post("/login", data={"password": "nope"}).get_data(as_text=True)
            self.assertIn("Wrong password", wrong)
            self.assertIn('class="card wrong"', wrong, "a wrong password shakes the card")
            self.assertEqual(client.get("/").status_code, 302)
            reply = client.post("/login?next=//evil.example", data={"password": "open sesame"})
            self.assertEqual(reply.status_code, 302)
            self.assertNotIn("evil", reply.headers["Location"], "a link can't send you elsewhere after signing in")
            self.assertEqual(client.get("/").status_code, 200)
            self.assertIn(b'id="settingsBtn"', client.get("/").data)

    def test_queue_comes_back_on_hold_after_a_restart(self):
        path = os.path.join(self.temp, "queue.json")
        item = {"id": 4, "label": "a film", "detail": "", "argv": ["x"], "env": {}, "estimate": 60}
        with open(path, "w", encoding="utf-8") as f:
            json.dump([item], f)
        queue = webapp.JobQueue(webapp.Job(), lambda item: None, path=path)
        self.assertTrue(queue.held)
        self.assertEqual(queue.snapshot()["items"][0]["label"], "a film")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{broken")
        broken = webapp.JobQueue(webapp.Job(), lambda item: None, path=path)
        self.assertEqual(broken.items, [])
        self.assertTrue(broken.persistence_error)
        self.assertTrue(broken.held, "a corrupt queue cannot start or be silently reset")

    def test_queue_snapshot_exposes_continued_run_for_prompts(self):
        queue = webapp.JobQueue(webapp.Job(), lambda item: None)
        queue.held = True
        queue.items = [{"id": 3, "label": "continued", "pipeline": "video", "resume": "run_1",
                        "argv": ["private"], "env": {"secret": "private"}},
                       {"id": 4, "label": "new", "pipeline": "image", "argv": ["private"]},
                       {"id": 5, "label": "upscale", "pipeline": "image", "resume": "image_1",
                        "argv": ["-m", "pipelines.image.upscale", "--resume", "image_1"]},
                       {"id": 6, "label": "redo", "pipeline": "video", "resume": "run_1",
                        "argv": ["--resume", "run_1", "--redo", "1"]}]
        with mock.patch.object(webapp, "run_facts", return_value={}):
            items = queue.snapshot()["items"]
        item = items[0]
        self.assertEqual(item["resume"], "run_1")
        self.assertEqual([entry["continuation"] for entry in items], [True, False, False, False])
        self.assertNotIn("argv", item)
        self.assertNotIn("env", item)

    def test_settings_are_saved_and_checked(self):
        path = os.path.join(self.temp, "settings.json")
        with mock.patch.object(webapp.settings, "PATH", path), mock.patch.object(webapp, "apply_comfyui_priority"):
            self.assertFalse(self.client.get("/api/settings").get_json()["settings"]["low_priority"])
            saved = self.client.post("/api/settings", json={"low_priority": True, "default_workflow": {"image": "image_x", "bogus": "y"}}).get_json()
            self.assertTrue(saved["settings"]["low_priority"])
            self.assertEqual(saved["settings"]["default_workflow"], {"shorts": "", "video": "", "image": "image_x"})
            self.assertFalse(saved["settings"]["pin_progress"], "the progress bar is not pinned until asked")
            self.assertTrue(self.client.post("/api/settings", json={"pin_progress": True}).get_json()["settings"]["pin_progress"])
            self.assertTrue(webapp.settings.load()["pin_progress"], "kept")
            self.assertTrue(saved["settings"]["top_progress"], "the progress bar at the top is on until turned off")
            self.assertFalse(saved["settings"]["status_progress"])
            both = self.client.post("/api/settings", json={"top_progress": False, "status_progress": True}).get_json()["settings"]
            self.assertEqual((both["top_progress"], both["status_progress"]), (False, True))
            self.assertTrue(webapp.settings.load()["low_priority"], "kept in the file")
            self.assertEqual(self.client.post("/api/settings", json={"h3_model": "qwen3-14b"}).get_json()["settings"]["h3_model"], "qwen3-14b")
            self.assertEqual(self.client.post("/api/settings", json={"h3_model": "unknown"}).status_code, 400)
            self.assertEqual(webapp.settings.load()["h3_model"], "qwen3-14b")
            self.assertEqual(webapp.priority_flags(), webapp.BELOW_NORMAL)
            saved = self.client.post("/api/settings", json={"reserve_ram_gb": "8"}).get_json()["settings"]
            self.assertEqual(saved["reserve_ram_gb"], 8)
            self.assertEqual(self.client.post("/api/settings", json={"reserve_ram_gb": 999}).get_json()["settings"]["reserve_ram_gb"], webapp.settings.MAX_RESERVE_GB)
            self.assertEqual(self.client.post("/api/settings", json={"reserve_ram_gb": "x"}).get_json()["settings"]["reserve_ram_gb"], 3, "unreadable: the 3 GB default")
            bat = os.path.join(self.temp, "run.bat")
            with open(bat, "w") as f:
                f.write("python main.py --enable-manager\n")
            self.client.post("/api/settings", json={"reserve_ram_gb": 8})
            self.assertTrue(webapp.comfyui_command(bat).endswith("--disable-auto-launch --cache-ram 8"))
            self.client.post("/api/settings", json={"reserve_ram_gb": 0})
            self.assertTrue(webapp.comfyui_command(bat).endswith("--cache-ram 3"), "unset, ComfyUI keeps 3 GB free")
            self.assertEqual(self.client.post("/api/settings", data="no").status_code, 400)
            self.assertIn("disk", self.client.get("/api/settings").get_json())

    def test_theme_selection_is_saved_validated_and_rendered(self):
        path = os.path.join(self.temp, "settings.json")
        with mock.patch.object(webapp.settings, "PATH", path):
            self.assertEqual(self.client.get("/api/settings").get_json()["settings"]["theme"], "standard")
            page = self.client.get("/").get_data(as_text=True)
            self.assertEqual(page.count('class="theme-choice"'), 16)
            self.assertIn('data-theme="standard"', page)
            for theme in ("nord", "amoled", "solarized"):
                self.assertIn(f'data-theme="{theme}"', page)
            self.assertEqual(self.client.post("/api/settings", json={"theme": "nord"}).get_json()["settings"]["theme"], "nord")
            self.assertEqual(webapp.settings.load()["theme"], "nord")
            self.assertIn('<html lang="en" data-theme="nord">', self.client.get("/").get_data(as_text=True))
            for invalid in ("unknown", [], None):
                self.assertEqual(self.client.post("/api/settings", json={"theme": invalid}).status_code, 400)
                self.assertEqual(webapp.settings.load()["theme"], "nord")

    def test_output_order_is_kept_and_hidden_batches_keep_their_slots(self):
        path = os.path.join(self.temp, "settings.json")
        with mock.patch.object(webapp.settings, "PATH", path):
            ids = ["image:a", "film:hidden.mp4", "image:b", "image:c"]
            self.assertTrue(self.client.post("/api/settings", json={"output_order": ids}).get_json()["ok"])
            reply = self.client.post("/api/settings", json={"output_order": ["image:new", "image:c", "image:b", "image:a"]})
            expected = ["image:new", "image:c", "film:hidden.mp4", "image:b", "image:a"]
            self.assertEqual(reply.get_json()["settings"]["output_order"], expected)
            self.client.post("/api/settings", json={"theme": "nord"})
            self.assertEqual(webapp.settings.load()["output_order"], expected)
            for invalid in (None, ["image:a", "image:a"], ["bogus:a"], ["image:"], [False]):
                self.assertEqual(self.client.post("/api/settings", json={"output_order": invalid}).status_code, 400)
                self.assertEqual(webapp.settings.load()["output_order"], expected)

    def test_gpu_heat_guard_restarts_once_above_78_and_rearms_at_75(self):
        from panel.gpu_guard import GPUHeatGuard

        note = mock.Mock()
        guard = GPUHeatGuard(note)
        with mock.patch("panel.gpu_guard.restart_afterburner") as restart:
            for temperature in (None, 75, 78):
                guard.check(temperature)
            restart.assert_not_called()
            for temperature in (79, 81, 80, 77, 79):
                guard.check(temperature)
            self.assertEqual(restart.call_count, 1)
            guard.check(75)
            guard.check(79)
            self.assertEqual(restart.call_count, 2)
            guard.check(75)
            restart.side_effect = OSError("Access denied")
            guard.check(79)
            self.assertIn("Access denied", note.call_args.args[0])
            guard.check(80)
            self.assertEqual(restart.call_count, 3, "a failed restart does not loop while hot")

    def test_gpu_heat_guard_follows_its_settings(self):
        from panel.gpu_guard import GPUHeatGuard

        config = {"gpu_guard": True, "gpu_restart_above": 70, "gpu_rearm_at": 60, "gpu_profile": 5}
        guard = GPUHeatGuard(mock.Mock(), lambda: config)
        with mock.patch("panel.gpu_guard.restart_afterburner") as restart:
            guard.check(71)
            restart.assert_called_once_with(5)
            guard.check(65)
            guard.check(72)
            self.assertEqual(restart.call_count, 1, "not again until cooled to the cool-down temperature")
            guard.check(60)
            config["gpu_guard"] = False
            guard.check(90)
            self.assertEqual(restart.call_count, 1, "switched off, it only watches")

    def test_gpu_guard_settings_are_checked_and_kept(self):
        patch = mock.patch.object(webapp.settings, "PATH", os.path.join(self.temp, "settings.json"))
        patch.start()
        self.addCleanup(patch.stop)
        self.assertEqual({key: webapp.settings.load()[key] for key in ("gpu_guard", "gpu_restart_above", "gpu_rearm_at", "gpu_profile")},
                         {"gpu_guard": True, "gpu_restart_above": 78, "gpu_rearm_at": 75, "gpu_profile": 3})
        saved = self.client.post("/api/settings", json={"gpu_restart_above": 82, "gpu_rearm_at": 72, "gpu_profile": 1, "gpu_guard": False}).get_json()
        self.assertTrue(saved["ok"], saved)
        self.assertEqual([saved["settings"][key] for key in ("gpu_guard", "gpu_restart_above", "gpu_rearm_at", "gpu_profile")], [False, 82, 72, 1])
        for bad in ({"gpu_rearm_at": 82}, {"gpu_restart_above": 70}, {"gpu_profile": 6}, {"gpu_profile": "x"}, {"gpu_restart_above": 120}):
            self.assertEqual(self.client.post("/api/settings", json=bad).status_code, 400, bad)
        self.assertEqual(webapp.settings.load()["gpu_restart_above"], 82, "a refused change leaves what was saved")

    def test_temperatures_api_gives_the_range_and_the_guard_lines(self):
        from panel import temperatures

        patch = mock.patch.object(webapp.settings, "PATH", os.path.join(self.temp, "settings.json"))
        patch.start()
        self.addCleanup(patch.stop)
        log = temperatures.TemperatureLog(os.path.join(self.temp, "temperatures.jsonl"))
        log.add(gpu=70, cpu=60)
        from panel import heat
        with mock.patch.object(heat, "_temperature_log", log):
            body = self.client.get("/api/temperatures?hours=24").get_json()
            self.assertTrue(body["ok"], body)
            self.assertEqual(body["summary"]["gpu"]["now"], 70)
            self.assertEqual(body["guard"], {"on": True, "restart_above": 78, "rearm_at": 75})
            self.assertEqual(self.client.get("/api/temperatures?hours=5").status_code, 400)

    def test_restart_afterburner_now_uses_the_chosen_profile(self):
        from panel import gpu_guard

        patch = mock.patch.object(webapp.settings, "PATH", os.path.join(self.temp, "settings.json"))
        patch.start()
        self.addCleanup(patch.stop)
        self.client.post("/api/settings", json={"gpu_profile": 4})
        with mock.patch.object(gpu_guard, "restart_afterburner") as restart:
            self.assertEqual(self.client.post("/restart/afterburner").get_json(), {"ok": True, "profile": 4})
            restart.assert_called_once_with(4)
            restart.side_effect = gpu_guard.Busy("MSI Afterburner is already restarting.")
            self.assertEqual(self.client.post("/restart/afterburner").status_code, 409)
            restart.side_effect = RuntimeError("MSI Afterburner was not found.")
            failed = self.client.post("/restart/afterburner")
            self.assertEqual(failed.status_code, 500)
            self.assertIn("not found", failed.get_json()["error"])

    def test_afterburner_restart_only_stops_the_current_users_instance(self):
        from panel import gpu_guard
        import psutil

        mine = mock.Mock(info={"name": "MSIAfterburner.exe", "username": "mine",
                               "exe": r"C:\Tools\MSI Afterburner\MSIAfterburner.exe"})
        other = mock.Mock(info={"name": "MSIAfterburner.exe", "username": "other", "exe": r"C:\Other\MSIAfterburner.exe"})
        process = mock.Mock()
        process.wait.side_effect = subprocess.TimeoutExpired("Afterburner", 1)
        with mock.patch.object(psutil, "Process") as current, \
                mock.patch.object(psutil, "process_iter", return_value=[mine, other]), \
                mock.patch.object(psutil, "wait_procs", return_value=([mine], [])) as wait, \
                mock.patch.object(gpu_guard.subprocess, "Popen", return_value=process) as launch:
            current.return_value.username.return_value = "mine"
            gpu_guard.restart_afterburner()
            mine.terminate.assert_called_once()
            other.terminate.assert_not_called()
            wait.assert_called_once_with([mine], timeout=5)
            self.assertEqual(launch.call_args.args[0], [mine.info["exe"], "-Profile3"])
            wait.return_value = ([], [mine])
            with self.assertRaisesRegex(RuntimeError, "did not exit"):
                gpu_guard.restart_afterburner()
            self.assertEqual(launch.call_count, 1, "no duplicate instance if the old one is still alive")

    def test_afterburner_restart_asks_for_elevation_when_it_requires_it(self):
        from panel import gpu_guard
        import psutil

        mine = mock.Mock(info={"name": "MSIAfterburner.exe", "username": "mine",
                               "exe": r"C:\Tools\MSI Afterburner\MSIAfterburner.exe"})
        needs_admin = OSError(740, "The requested operation requires elevation")
        needs_admin.winerror = 740
        with mock.patch.object(psutil, "Process") as current, \
                mock.patch.object(psutil, "process_iter", return_value=[mine]), \
                mock.patch.object(psutil, "wait_procs", return_value=([mine], [])), \
                mock.patch.object(gpu_guard.subprocess, "Popen", side_effect=needs_admin), \
                mock.patch("ctypes.windll", create=True) as windll:
            current.return_value.username.return_value = "mine"
            windll.shell32.ShellExecuteW.return_value = 42
            gpu_guard.restart_afterburner()
            self.assertEqual(windll.shell32.ShellExecuteW.call_args.args[1:4],
                             ("runas", mine.info["exe"], "-Profile3"))
            windll.shell32.ShellExecuteW.return_value = 5
            with self.assertRaisesRegex(RuntimeError, "administrator"):
                gpu_guard.restart_afterburner()

    def test_theme_picker_script(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node isn't installed")
        page = os.path.join(self.temp, "page.html")
        with open(page, "wb") as f:
            f.write(self.client.get("/").data)
        result = subprocess.run([node, os.path.join(ROOT, "tests", "theme_check.cjs"), page],
                                capture_output=True, text=True, encoding="utf-8", timeout=60,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_film_upscale_is_queued_and_checked(self):
        added = []
        film = os.path.join(webapp.VIDEO_OUTPUT, "zz_upscale_test.mp4")
        os.makedirs(webapp.VIDEO_OUTPUT, exist_ok=True)
        open(film, "wb").close()
        self.addCleanup(lambda: os.path.exists(film) and os.remove(film))
        with mock.patch.object(webapp.run_queue, "add", lambda item: added.append(item) or 1):
            self.assertEqual(self.client.post("/films/zz_upscale_test.mp4/upscale?scale=9").status_code, 400)
            self.assertEqual(self.client.post("/films/zz_upscale_test.mp4/upscale?quality=NOPE").status_code, 400)
            self.assertEqual(self.client.post("/films/missing.mp4/upscale").status_code, 404)
            body = self.client.post("/films/zz_upscale_test.mp4/upscale?scale=3&quality=ULTRA").get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(added[0]["argv"][-6:], ["--film", "zz_upscale_test.mp4", "--scale", "3", "--quality", "ULTRA"])

    def test_film_latent_upscale_makes_a_copy_on_the_same_seeds(self):
        self.assertTrue(self.generate().get_json()["ok"])
        self.wait_idle()
        state = self.only_run()
        name = os.path.basename(state.final)
        added = []
        with mock.patch.object(webapp.run_queue, "add", lambda item: added.append(item) or 1):
            self.assertEqual(self.client.post(f"/films/{name}/upscale?method=latent").status_code, 400, "the workflow doesn't offer it")
            with mock.patch.object(video_panel, "offers_latent_upscale", return_value=True):
                self.assertEqual(self.client.post(f"/films/{name}/upscale?method=latent&preset=Sideways").status_code, 400)
                self.assertEqual(self.client.post(f"/films/{name}/upscale?method=latent&mp=0.01").status_code, 400)
                body = self.client.post(f"/films/{name}/upscale?method=latent&preset=Heavy&mp=2").get_json()
        self.assertTrue(body["ok"], body)
        copy = RunState.load(added[0]["resume"])
        self.addCleanup(copy.remove)
        self.assertNotEqual(copy.id, state.id)
        self.assertEqual(copy.options["latent_upscale"], "Heavy")
        self.assertEqual(copy.options["latent_upscale_mp"], "2")
        self.assertEqual([shot["seed"] for shot in copy.shots], [shot["used_seed"] for shot in state.shots], "made again as it was")
        self.assertEqual([shot["prompt"] for shot in copy.shots], [shot["prompt"] for shot in state.shots])
        self.assertTrue(copy.film_name.endswith("_latent"))
        self.assertEqual((copy.clips, copy.final, copy.inputs), ({}, None, None))
        self.assertTrue(RunState.load(state.id).final, "the original stays as it is")
        # Queued again before the first is made: its name is taken already, though no file has it yet.
        with mock.patch.object(webapp.run_queue, "add", lambda item: added.append(item) or 1), \
                mock.patch.object(video_panel, "offers_latent_upscale", return_value=True):
            self.assertTrue(self.client.post(f"/films/{name}/upscale?method=latent&preset=Clean&mp=2").get_json()["ok"])
        second = RunState.load(added[1]["resume"])
        self.addCleanup(second.remove)
        self.assertEqual(second.film_name, copy.film_name + "_2", "never the same film as the one queued before it")

    def test_private_mode_tags_new_creations_nsfw_and_is_kept(self):
        self.addCleanup(lambda: webapp.settings.update({"private_mode": False}))
        self.assertFalse(self.client.get("/api/private").get_json()["on"])
        self.assertTrue(self.client.post("/api/private", json={"on": True}).get_json()["on"])
        self.assertTrue(self.client.get("/api/status").get_json()["private"])
        self.assertTrue(webapp.settings.load()["private_mode"], "saved, so a restarted panel keeps it")
        self.assertTrue(self.generate().get_json()["ok"])
        self.wait_idle()
        run_id = self.only_run().id
        with webapp._nsfw_lock:
            self.assertIn(run_id, webapp._read_nsfw()["video"], "made in private mode: tagged NSFW")
        self.assertFalse(self.client.post("/api/private", json={"on": False}).get_json()["on"])
        later = {"pipeline": "video", "label": "x", "argv": [], "resume": run_id}
        with mock.patch.object(webapp.run_queue, "_advance"), mock.patch.object(webapp.run_queue, "_save"):
            webapp.settings.update({"private_mode": True})
            with webapp.app.test_request_context():
                webapp.run_queue.add(later)
            webapp.run_queue.items.remove(later)
        self.assertNotIn("private", later, "a continuation of something made before keeps that one's tag")

    def test_poweroff_is_per_session_and_cancellable(self):
        calls = []
        with mock.patch.object(webapp, "_run_shutdown", lambda cancel=False: calls.append(cancel)), \
                mock.patch.object(webapp, "POWEROFF_IDLE", 0), mock.patch.object(webapp, "work_left", lambda: False), \
                mock.patch.object(webapp, "POWEROFF_POLL", 0.01):
            self.assertFalse(self.client.get("/api/poweroff").get_json()["armed"])
            self.assertTrue(self.client.post("/api/poweroff", json={"armed": True}).get_json()["armed"])
            self.wait_until(lambda: webapp.poweroff_state()["seconds_left"] is not None, "the countdown")
            self.assertEqual(calls, [False])
            self.assertIn("poweroff", self.client.get("/api/status").get_json())
            self.assertFalse(self.client.post("/api/poweroff", json={"armed": False}).get_json()["armed"])
            self.assertEqual(calls, [False, True], "turned off, so the shutdown is cancelled")
            self.assertIsNone(webapp.poweroff_state()["seconds_left"])

    def test_restart_waits_for_work_to_end(self):
        self.comfy.script = ["hang"]
        self.assertTrue(self.generate().get_json()["ok"])
        self.wait_until(lambda: self.comfy.hanging, "the clip to start")
        self.assertEqual(self.client.post("/restart/panel").status_code, 409)
        self.assertEqual(self.client.post("/restart/comfyui").status_code, 409)
        with mock.patch.object(webapp, "comfyui_launcher", return_value="launcher"), \
                mock.patch.object(webapp, "restart_comfyui_in_background") as restart:
            self.assertTrue(self.client.post("/restart/comfyui", json={"force": True}).get_json()["ok"], "forced, it goes ahead of the run")
            restart.assert_called_once_with(force=True)

    def test_pending_continuation_can_edit_prompts_without_duplicate_jobs(self):
        self.assertTrue(self.generate(review="1").get_json()["ok"])
        self.wait_idle()
        run_id = self.only_run().id
        item = {"id": self.queue_id(), "pipeline": "video", "label": "Continue", "resume": run_id, "later": True,
                "argv": webapp.PIPELINES["video"].resume_argv(RunState.load(run_id))}
        with webapp.run_queue.lock:
            webapp.run_queue.items.append(item)
        detail = self.client.get(f"/runs/{run_id}").get_json()
        self.assertFalse(detail["busy"])
        self.assertTrue(detail["pending"])
        prompts = [shot["prompt"] for shot in detail["shots"]]
        prompts[0] = "A revised first shot."
        self.assertTrue(self.client.post(f"/runs/{run_id}/shots", json={"prompts": prompts}).get_json()["ok"])
        self.assertEqual(RunState.load(run_id).shots[0]["prompt"], prompts[0])
        self.assertEqual(self.client.post(f"/runs/{run_id}/continue").status_code, 409)
        self.assertEqual(self.client.post(f"/runs/{run_id}/discard").status_code, 409)
        self.assertFalse(webapp.restart_blocked())
        with webapp.run_queue.lock:
            item.pop("later")
            webapp.run_queue.held = True
        self.assertTrue(self.client.get(f"/runs/{run_id}").get_json()["busy"])
        self.assertEqual(self.client.post(f"/runs/{run_id}/shots", json={"prompts": prompts}).status_code, 409)
        with webapp.run_queue.lock:
            webapp.run_queue.items.remove(item)

    def test_prompt_warning_parks_the_run_and_start_approves_the_saved_plan(self):
        state = RunState.new("Brief", 20, "image", 64, 64, image_count=0)
        prompt = "A woman gently opens the wooden door and looks into the dark room."
        state.shots = [{"title": "First", "seconds": 10, "prompt": prompt, "planner_prompt": prompt},
                       {"title": "Second", "seconds": 10, "prompt": prompt + " Slowly.", "planner_prompt": prompt + " Slowly."}]
        state.check_prompts()
        state.save()
        item = {"id": self.queue_id(), "pipeline": "video", "label": "Warning film", "argv": ["x"], "env": {}, "first_only": True}
        with webapp.run_queue.lock, mock.patch.object(webapp.job, "progress", {"run_id": state.id}), \
                mock.patch.object(webapp.job, "returncode", 0), mock.patch.object(webapp.job, "stopped", False), \
                mock.patch.object(webapp, "free_comfyui"), mock.patch.object(webapp, "_comfy_freeing", False), \
                mock.patch.object(webapp.run_queue, "_advance"):
            webapp.run_queue.current = item
            webapp.run_queue._finish_current()
            self.assertIsNone(webapp.run_queue.current)
            waiting = webapp.run_queue.items[0]
            self.assertEqual(waiting["resume"], state.id)
            self.assertTrue(waiting["later"])
            self.assertIn("--first-only", waiting["argv"])
            self.assertNotIn("--plan-only", waiting["argv"])
            self.assertEqual(webapp.run_queue.results, [], "a warning is not a successful render or failure")
            snapshot = webapp.run_queue.snapshot()["items"][0]
            self.assertEqual(snapshot["prompt_warnings"][0]["items"], [1, 2])
            self.assertTrue(self.client.post(f"/queue/run/start/{item['id']}").get_json()["ok"])
            self.assertFalse(RunState.load(state.id).prompt_warning_pending)
            self.assertNotIn("prompt_warnings", waiting)
            self.assertEqual(RunState.load(state.id).shots, state.shots, "starting approves without rewriting")

    def test_clip_history_survives_edits_and_multishot_clips_can_be_previewed(self):
        state = RunState.new("Original brief", 20, "multishot", 64, 64, image_count=0)
        state.shots = [{"title": "First", "seconds": 10, "prompt": "Enhanced", "planner_prompt": "Planned",
                        "enhanced_prompt": "Enhanced", "comfy_prompt": "Flattened"},
                       {"title": "Second", "seconds": 10, "prompt": "Next", "planner_prompt": "Next"}]
        state.take_file = "take.mp4"
        os.makedirs(state.parts_dir)
        with open(os.path.join(state.parts_dir, state.take_file), "wb") as file:
            file.write(b"take")
        state.save()
        detail = self.client.get(f"/runs/{state.id}").get_json()
        self.assertTrue(all(shot["rendered"] for shot in detail["shots"]))
        self.assertEqual(detail["shots"][0]["comfy_prompt"], "Flattened")
        self.assertTrue(self.client.post(f"/runs/{state.id}/shots", json={"prompts": ["Edited", "Next"]}).get_json()["ok"])
        edited = self.client.get(f"/runs/{state.id}").get_json()["shots"][0]
        self.assertEqual(edited["planner_prompt"], "Planned")
        self.assertEqual(edited["enhancer_prompt"], "Enhanced", "editing does not erase the enhancer history")
        self.assertEqual(edited["comfy_prompt"], "Flattened", "last submitted text remains distinct from a later edit")
        def extract(source, start, seconds, output):
            with open(output, "wb") as file:
                file.write(b"preview")
        with mock.patch.object(media, "video_slice", side_effect=extract) as slice_video:
            for _ in range(2):
                with self.client.get(f"/runs/{state.id}/clips/2") as response:
                    self.assertEqual(response.data, b"preview")
        self.assertEqual(slice_video.call_count, 1, "a take's clip preview is cached")
        self.assertAlmostEqual(slice_video.call_args.args[1], (h3_prompt.clip_frames(10) - 1) / h3_prompt.FPS)
        self.assertEqual(self.client.get(f"/runs/{state.id}/clips/3").status_code, 404)

    def test_a_continued_run_opens_its_setup_and_keeps_its_prompts(self):
        self.assertTrue(self.generate(review="1").get_json()["ok"])
        self.wait_idle()
        state = self.only_run()
        prompts = [shot["prompt"] for shot in state.shots]
        item = {"id": self.queue_id(), "pipeline": "video", "label": "Continue", "resume": state.id, "later": True,
                "argv": webapp.PIPELINES["video"].resume_argv(state)}
        with webapp.run_queue.lock:
            webapp.run_queue.items.append(item)
        self.addCleanup(lambda: webapp.run_queue.items.clear())
        edit = self.client.post(f"/queue/run/edit/{item['id']}").get_json()
        self.assertTrue(edit["ok"], edit)
        self.assertEqual(edit["continued"]["prompts"], prompts)
        self.assertEqual(edit["form"]["prompt"], state.brief, "opens as it was made")

        # The prompt sent along is ignored: only how the rest is made changes.
        reply = self.client.post(f"/queue/run/edit/{item['id']}/continue", data={
            "queue_edit_token": edit["token"], "prompt": "Something else entirely", "size": "640x384", "try_first": "1",
            "start_later": "1"}).get_json()
        self.assertTrue(reply["ok"], reply)
        after = RunState.load(state.id)
        self.assertEqual((after.width, after.height), (640, 384))
        self.assertEqual(after.brief, state.brief)
        self.assertEqual([shot["prompt"] for shot in after.shots], prompts)
        queued = next(entry for entry in webapp.run_queue.items if entry["id"] == item["id"])
        self.assertIn("--first-only", queued["argv"])
        self.assertNotIn("edit_token", queued)
        self.assertTrue(queued["later"])
        self.assertEqual(self.client.post(f"/queue/run/edit/{item['id']}/continue", data={"queue_edit_token": edit["token"]}).status_code, 409,
                         "the session is spent")

    def test_a_continued_run_reopened_as_new_makes_a_new_run_in_pending(self):
        self.assertTrue(self.generate(review="1").get_json()["ok"])
        self.wait_idle()
        state = self.only_run()
        item = {"id": self.queue_id(), "pipeline": "video", "label": "Continue", "resume": state.id, "later": True,
                "argv": webapp.PIPELINES["video"].resume_argv(state)}
        with webapp.run_queue.lock:
            webapp.run_queue.items.append(item)
        self.addCleanup(lambda: webapp.run_queue.items.clear())
        edit = self.client.post(f"/queue/run/edit/{item['id']}").get_json()
        webapp.run_queue.hold()
        saved = self.generate(prompt="A brand new take", start_later="1", queue_edit_id=str(item["id"]), queue_edit_token=edit["token"])
        self.assertTrue(saved.get_json()["ok"], saved.get_json())
        queued = next(entry for entry in webapp.run_queue.items if entry["id"] == item["id"])
        self.assertNotIn("resume", queued, "a new run, not the paused one")
        self.assertTrue(queued["later"], "added to Pending as asked")
        self.assertEqual(RunState.load(state.id).brief, state.brief, "the paused run is untouched")

    def test_pending_jobs_do_not_block_guarded_restart(self):
        with mock.patch.object(webapp.run_queue, "pending", return_value=[{"id": 1, "later": True}]), \
             mock.patch.object(webapp.upload_queue, "pending", return_value=[]), \
             mock.patch.object(webapp.run_queue, "held", False), \
             mock.patch.object(webapp.subprocess, "Popen"), mock.patch.object(webapp.threading, "Timer"):
            self.assertFalse(webapp.restart_blocked())
            self.assertTrue(self.client.post("/restart/panel").get_json()["ok"])
        with mock.patch.object(webapp.run_queue, "pending", return_value=[{"id": 1, "later": True}, {"id": 2}]), \
             mock.patch.object(webapp.upload_queue, "pending", return_value=[]), \
             mock.patch.object(webapp.run_queue, "held", False):
            self.assertTrue(webapp.restart_blocked())

    def test_shutdown_stops_everything_and_keeps_the_queue(self):
        self.comfy.script = ["hang"]
        self.assertTrue(self.generate().get_json()["ok"])
        self.wait_until(lambda: self.comfy.hanging, "the clip to start")
        self.assertTrue(self.generate(prompt="still queued").get_json()["queued"])
        run_id = webapp.job.progress["run_id"]

        def reopen():
            for job in (webapp.job, webapp.uploads):
                job.closed = False
        self.addCleanup(reopen)
        with mock.patch.object(webapp.threading, "Timer") as timer:
            self.assertTrue(self.client.post("/shutdown").get_json()["ok"])
        timer.assert_called_once()
        self.assertFalse(webapp.job.running)
        self.assertIn(("/interrupt", {"prompt_id": "p1"}), self.comfy.cancels)
        with open(webapp.run_queue.ledger_path, encoding="utf-8") as f:
            self.assertEqual([item["prompt"] for item in json.load(f)["items"]], ["still queued"])
        self.assertTrue(RunState.load(run_id).shots, "it can continue after the restart")

    # --- The page ---

    def test_generation_header_keeps_compact_presets_outside_the_forms(self):
        html = self.client.get("/").get_data(as_text=True)
        header_start = html.index('<div class="generation-header">')
        forms_start = html.index('<form class="card pipeline-form')
        header = html[header_start:forms_start]
        self.assertNotIn('id="keepSectionsOpen"', header)
        self.assertEqual(html.count('id="keepSectionsOpen"'), 1)
        self.assertIn('data-workflow-actions="shorts"', html[forms_start:])
        for side in ("shorts", "video", "image"):
            with self.subTest(side=side):
                self.assertIn(f'<dialog id="{side}PresetDialog"', html)
                self.assertIn(f'<label for="{side}Preset">Preset</label>', html)
                self.assertEqual(html.count(f'id="{side}Preset"'), 1)
                self.assertNotIn(f'id="{side}Preset"', header)
                self.assertIn(f'data-preset-open="{side}" aria-haspopup="dialog"', html)
                self.assertIn(f'data-preset-save="{side}"', html)
                self.assertIn(f'data-preset-default="{side}"', html)
                self.assertIn(f'data-preset-delete="{side}"', html)
        self.assertNotIn('class="workflow-top preset-top"', html)

    def test_page_script(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node isn't installed")
        page = os.path.join(self.temp, "page.html")
        with open(page, "wb") as f:
            f.write(self.client.get("/").data)
        result = subprocess.run([node, os.path.join(ROOT, "tests", "page_check.cjs"), page],
                                capture_output=True, text=True, encoding="utf-8", timeout=60,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("all page checks passed", result.stdout, "an unfinished async check must not count as passing")

    def test_upscale_dialog_picks_only_method_buttons(self):
        # The dialog itself carries data-method, so a bare [data-method] lookup swallowed the Add to queue click.
        script = self.client.get("/static/generation-history.js").get_data(as_text=True)
        self.assertIn("closest('button[data-method]')", script)
        self.assertNotIn("closest('[data-method]')", script)

    def test_stale_server_only_restarts_when_idle(self):
        with mock.patch.object(webapp.threading, "Timer") as timer:
            old = self.client.post("/launcher/refresh", data={"code_changed_at": "1"})
            self.assertEqual(old.get_json(), {"restarting": False})
            timer.assert_not_called()
            newer = {"code_changed_at": str(time.time() + 60)}
            # A queue about to start something isn't cut short; one on hold is saved and comes back on hold.
            with mock.patch.object(webapp.run_queue, "pending", return_value=[{"id": 1}]):
                with mock.patch.object(webapp.run_queue, "held", False):
                    self.assertEqual(self.client.post("/launcher/refresh", data=newer).get_json(), {"restarting": False})
                    timer.assert_not_called()
                with mock.patch.object(webapp.run_queue, "held", True):
                    self.assertEqual(self.client.post("/launcher/refresh", data=newer).get_json(), {"restarting": True})
            timer.assert_called_once()


class ComfyFreshStartTest(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows process flags")
    def test_launches_comfyui_without_a_console_window(self):
        with mock.patch.object(webapp, "comfyui_command", return_value="python main.py --disable-auto-launch"), \
                mock.patch.object(webapp, "priority_flags", return_value=0), \
                mock.patch.object(webapp.subprocess, "Popen") as process:
            webapp.launch_comfyui(r"C:\ComfyUI\run_nvidia_gpu.bat")
        flags = process.call_args[1]["creationflags"]
        self.assertTrue(flags & webapp.NO_WINDOW)
        self.assertTrue(flags & subprocess.CREATE_NEW_PROCESS_GROUP)
        self.assertFalse(flags & subprocess.CREATE_NEW_CONSOLE)
        self.assertNotIn("startupinfo", process.call_args[1])

    def test_detects_only_comfyui_python_entry_points(self):
        import psutil
        def process(pid, name, args, cwd=""):
            result = mock.Mock(pid=pid, info={"name": name, "cmdline": args})
            result.cwd.return_value = cwd
            return result
        direct = process(1231, "python.exe", ["python.exe", "-s", r"ComfyUI\main.py"])
        relative = process(1232, "pythonw.exe", ["pythonw.exe", "main.py"], r"C:\Projects\ComfyUI")
        unrelated = process(1233, "python.exe", ["python.exe", r"C:\other\main.py", r"C:\ComfyUI\main.py"])
        other = process(1234, "python.exe", ["python.exe", "main.py"], r"C:\Projects\other")
        with mock.patch.object(psutil, "process_iter", return_value=[direct, relative, unrelated, other]):
            self.assertEqual(webapp.comfyui_processes(), [direct, relative])

    def test_manual_start_kills_and_waits_before_launch(self):
        import psutil
        client = webapp.app.test_client()
        processes = [mock.Mock(pid=1231), mock.Mock(pid=1232)]
        calls = []
        with mock.patch.object(webapp, "restart_blocked", return_value=False), \
                mock.patch.object(webapp, "comfyui_launcher", return_value="launcher"), \
                mock.patch.object(webapp, "comfyui_processes", return_value=processes), \
                mock.patch.object(webapp, "kill_tree", side_effect=lambda pid: calls.append(("kill", pid))), \
                mock.patch.object(psutil, "wait_procs", side_effect=lambda procs, timeout: (calls.append(("wait", timeout)) or (procs, []))), \
                mock.patch.object(webapp, "_port_open", return_value=False), \
                mock.patch.object(webapp, "launch_comfyui", side_effect=lambda launcher: calls.append(("launch", launcher))), \
                mock.patch.object(webapp, "_comfyui_start_requested_at", 0):
            self.assertTrue(client.post("/comfyui/start").get_json()["ok"])
        self.assertEqual(calls, [("kill", 1231), ("kill", 1232), ("wait", 10), ("launch", "launcher")])

    def test_manual_start_refuses_active_or_unstoppable_processes(self):
        import psutil
        client = webapp.app.test_client()
        with mock.patch.object(webapp, "restart_blocked", return_value=True), \
                mock.patch.object(webapp, "start_fresh_comfyui") as start:
            self.assertEqual(client.post("/comfyui/start").status_code, 409)
            start.assert_not_called()
        process = mock.Mock(pid=1231)
        with mock.patch.object(webapp, "restart_blocked", return_value=False), \
                mock.patch.object(webapp, "comfyui_launcher", return_value="launcher"), \
                mock.patch.object(webapp, "comfyui_processes", return_value=[process]), \
                mock.patch.object(webapp, "kill_tree"), mock.patch.object(psutil, "wait_procs", return_value=([], [process])), \
                mock.patch.object(webapp, "launch_comfyui") as launch:
            reply = client.post("/comfyui/start")
            self.assertEqual(reply.status_code, 500)
            self.assertIn("1231", reply.get_json()["error"])
            launch.assert_not_called()
        with mock.patch.object(webapp, "restart_blocked", return_value=False), \
                mock.patch.object(webapp, "comfyui_launcher", return_value="launcher"), \
                mock.patch.object(webapp, "comfyui_processes", return_value=[]), \
                mock.patch.object(psutil, "wait_procs", return_value=([], [])), \
                mock.patch.object(webapp, "_port_open", return_value=True), \
                mock.patch.object(webapp, "launch_comfyui") as launch:
            self.assertEqual(client.post("/comfyui/start").status_code, 500)
            launch.assert_not_called()


class QueueUpscaleEditTest(unittest.TestCase):
    def setUp(self):
        self.client = webapp.app.test_client()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patches = [
            mock.patch.object(webapp.run_queue, "items", []),
            mock.patch.object(webapp.run_queue, "_save"),
            mock.patch.object(webapp.run_queue, "_advance"),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def open(self, item):
        webapp.run_queue.items.extend([{"id": 9, "later": True}, item])
        response = self.client.post(f"/queue/run/edit/{item['id']}")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(item["later"])
        return response.get_json()

    def test_image_upscale_edit_preserves_source_and_handles_errors(self):
        from panel import image as image_panel
        path = os.path.join(self.temp.name, "source.png")
        Image.new("RGB", (640, 368)).save(path)
        state = types.SimpleNamespace(id="image_1", shots=[{"file": "source.png"}], image_path=lambda shot: path)
        item = {"id": 5, "pipeline": "image", "resume": state.id, "label": "Upscale",
                "argv": [*image_panel.UPSCALE, "--resume", state.id, "--image", "1", "--method", "fast", "--strength", "0.5"], "env": {}}
        with mock.patch.object(image_panel.RunState, "load", return_value=state):
            edit = self.open(item)
            self.assertEqual(edit["upscale"]["strength"], "0.5")
            self.assertEqual(edit["upscale"]["size"], [640, 368], "the source's size, for the upscale box's before and after")
            url = "/queue/run/edit/5/upscale"
            # 3x of its 368px shorter side, as the preview's 3x makes it, and SeedVR2's denoise.
            values = {"token": edit["token"], "method": "seedvr2", "strength": "0.5", "resolution": "1104", "denoise": "0.1"}
            self.assertEqual(self.client.post(url, json={**values, "times": "5"}).status_code, 400)
            self.assertEqual(self.client.post(url, json={**values, "token": "stale"}).status_code, 409)
            self.assertEqual(self.client.post(url, json={**values, "resolution": "100"}).status_code, 400)
            self.assertEqual(self.client.post(url, json={**values, "resolution": "9000"}).status_code, 400)
            self.assertEqual(self.client.post(url, json={**values, "denoise": "5"}).status_code, 400)
            os.remove(path)
            self.assertEqual(self.client.post(url, json=values).status_code, 409)
            self.assertIs(webapp.run_queue.items[-1], item)
            Image.new("RGB", (640, 368)).save(path)
            # 3x, as the upscale box sends it: 3 x its 368px shorter side.
            self.assertTrue(self.client.post(url, json={**{k: v for k, v in values.items() if k != "resolution"}, "times": "3"}).get_json()["ok"])
        replacement = webapp.run_queue.items[0]
        self.assertEqual([entry["id"] for entry in webapp.run_queue.items], [5, 9])
        self.assertEqual(replacement["resume"], state.id)
        self.assertIn("--image", replacement["argv"])
        self.assertEqual(replacement["argv"][-4:], ["--resolution", "1104", "--denoise", "0.1"])
        self.assertNotIn("later", replacement)
        self.assertNotIn("edit_token", replacement)

    def test_film_upscale_edit_and_cancel(self):
        item = {"id": 6, "pipeline": "video", "label": "Upscale", "estimate": 100, "env": {},
                "argv": [*video_panel.UPSCALE, "--film", "film.mp4", "--scale", "2", "--quality", "ULTRA"]}
        edit = self.open(item)
        self.assertEqual(edit["upscale"]["quality"], "ULTRA")
        url = "/queue/run/edit/6/upscale"
        values = {"token": edit["token"], "scale": "3", "quality": "STREAMING_ULTRA"}
        self.assertEqual(self.client.post(url, json=values).status_code, 409)
        with mock.patch.object(video_panel, "safe_video_path", return_value="film.mp4"):
            self.assertEqual(self.client.post(url, json={**values, "scale": "nan"}).status_code, 400)
            self.assertEqual(self.client.post(url, json={**values, "quality": "bad"}).status_code, 400)
            self.assertTrue(self.client.post(url, json=values).get_json()["ok"])
        replacement = webapp.run_queue.items[0]
        self.assertEqual([entry["id"] for entry in webapp.run_queue.items], [6, 9])
        self.assertEqual(replacement["argv"][-6:], ["--film", "film.mp4", "--scale", "3", "--quality", "STREAMING_ULTRA"])
        edit = self.client.post("/queue/run/edit/6").get_json()
        self.assertTrue(self.client.post("/queue/run/edit/6/cancel", json={"token": edit["token"]}).get_json()["ok"])
        self.assertFalse(replacement.get("later"), "it was in the queue when opened, so Cancel puts it back there")
        self.assertNotIn("edit_token", replacement)


if __name__ == "__main__":
    unittest.main()
