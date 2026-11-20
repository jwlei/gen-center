import asyncio
import json
import os
import sys
import tempfile
import threading
import runpy
import unittest
from types import ModuleType, SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fakes import DATA  # noqa: F401, isolate application data before importing the panel

from core import comfy_memory, director, h3_refiner, h3_refiner_worker
from panel import video
from panel import image
from panel import shorts
from pipelines.image import planner as image_planner
from pipelines.shorts.avatar_generator import AvatarGenerator
from pipelines.video import main
from pipelines.video import planner as video_planner
from pipelines.video.run_state import RunState


class H3RefinerTest(unittest.TestCase):
    def test_local_model_requires_acknowledged_cleanup_and_no_retained_allocations(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.comfy_url = "http://127.0.0.1:8188"
        queue = mock.Mock()
        queue.json.return_value = {"queue_running": [], "queue_pending": []}
        device = {"type": "cuda", "vram_total": 12 * 2**30, "vram_free": 11 * 2**30,
                  "torch_allocated": 0, "torch_reserved": 0}
        bodies = [{}, {"version": 1, "completed": False, "devices": [device]},
                  {"version": 1, "completed": True, "devices": [{**device, "torch_allocated": 2**30}]},
                  {"version": 1, "completed": True, "devices": [{**device, "torch_reserved": 2**30}]},
                  {"version": 1, "completed": True, "devices": [{**device, "vram_free": float("nan")}]}]
        for body in bodies:
            with self.subTest(body=body):
                response = mock.Mock(status_code=200)
                response.json.return_value = body
                with mock.patch.object(h3_refiner.requests, "get", return_value=queue), \
                     mock.patch.object(h3_refiner.requests, "post", return_value=response), \
                     mock.patch.object(h3_refiner.subprocess, "Popen") as launch:
                    with self.assertRaises(RuntimeError):
                        refiner.__enter__()
                    launch.assert_not_called()
        # What an emptied ComfyUI really keeps (PyTorch's cache, measured on the RTX card) is not a model left behind.
        leftovers = {"version": 1, "completed": True, "devices": [{**device, "torch_allocated": 262144, "torch_reserved": 33554432}]}
        with mock.patch.object(comfy_memory.requests, "post", return_value=mock.Mock(status_code=200, json=lambda: leftovers)):
            self.assertEqual(comfy_memory.release(refiner.comfy_url), leftovers["devices"])
        response = mock.Mock(status_code=500)
        response.raise_for_status.side_effect = h3_refiner.requests.HTTPError("cleanup failed")
        with mock.patch.object(comfy_memory.requests, "post", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
                comfy_memory.release(refiner.comfy_url)

    def test_each_local_model_has_a_short_name_to_tell_it_by(self):
        from panel import settings
        named = {
            "qwen3-14b": "Qwen3 14B",
            "gemma-4-12b:gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2-uncensored-heretic-Q5_K_M": "Gemma 4 Fable5-U-H Q5_K_M",
            "gemma-4-12b:gemma-4-12B-it-qat-q4_0-unquantized-heretic-Q4_0": "Gemma 4 QAT-H Q4_0",
            "gemma-4-12b:gemma-4-12B-it-qat-q4_0-unquantized-heretic-Q4_K_M": "Gemma 4 QAT-H Q4_K_M",
            "gemma-4-12b:gemma-4-12B-it-uncensored-heretic-Q5_K_M": "Gemma 4 U-H Q5_K_M",
        }
        # The built-in Gemma, named from its model file.
        self.assertEqual(settings.short_name("gemma-4-12b", "gemma-4-12B-it-heretic-Q4_K_M"), "Gemma 4 H Q4_K_M")
        self.assertEqual({model_id: settings.short_name(model_id) for model_id in named}, named)

    def test_local_model_rates_use_completed_tokens_and_current_model_file(self):
        from panel import settings
        with tempfile.TemporaryDirectory() as root, \
             mock.patch.object(settings, "PROJECT_ROOT", root), \
             mock.patch.object(settings, "LOGS_DIR", root), \
             mock.patch.dict(os.environ, {}, clear=True):
            folder = os.path.join(root, "models", "gemma-4-12b-heretic")
            os.makedirs(folder)
            path = os.path.join(folder, "model.gguf")
            open(path, "wb").close()
            mtime = os.path.getmtime(path)
            events = [
                {"event": "start", "pid": 1, "model": "gemma-4-12b", "model_mtime": mtime},
                {"event": "completion", "pid": 1, "model": "gemma-4-12b", "timings": {"predicted_n": 200, "predicted_ms": 10000}},
                {"event": "completion", "pid": 1, "model": "gemma-4-12b", "timings": {"predicted_n": 300, "predicted_ms": 30000}},
                {"event": "start", "pid": 2, "model": "gemma-4-12b", "model_mtime": mtime - 1},
                {"event": "completion", "pid": 2, "model": "gemma-4-12b", "timings": {"predicted_n": 9999, "predicted_ms": 1}},
                {"event": "completion", "pid": 1, "model": "gemma-4-12b", "timings": {"predicted_n": 10, "predicted_ms": 0}},
            ]
            with open(os.path.join(root, "local_llm_tokens.jsonl"), "w", encoding="utf-8") as target:
                for event in events:
                    target.write(json.dumps(event) + "\n")
            found = {model["id"]: model["tokens_per_second"] for model in settings.local_models()}
            self.assertEqual(found["gemma-4-12b"], 12.5)
            self.assertIsNone(found["qwen3-14b"])
            vision = {model["id"]: model["vision"] for model in settings.local_models()}
            self.assertTrue(vision["gemma-4-12b"])
            self.assertFalse(vision["qwen3-14b"])

    def test_models_are_found_in_llm_models_dir_when_set(self):
        from panel import settings
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as elsewhere, \
             mock.patch.object(settings, "PROJECT_ROOT", root), \
             mock.patch.object(h3_refiner, "PROJECT_ROOT", root), \
             mock.patch.object(settings, "LOGS_DIR", root), \
             mock.patch.dict(os.environ, {"LLM_MODELS_DIR": elsewhere}, clear=True):
            folder = os.path.join(elsewhere, "qwen3-14b-custom")
            os.makedirs(folder)
            model = os.path.join(folder, "Qwen3-14B-Q4_K_M.gguf")
            open(model, "wb").close()
            server = os.path.join(root, "llama-server.exe")
            open(server, "wb").close()
            os.environ["H3IR_LLAMA_SERVER"] = server
            self.assertEqual(settings.llm_models_dir(), elsewhere)
            self.assertIn("qwen3-14b:qwen3-14b-custom", [m["id"] for m in settings.local_models()])
            self.assertEqual(h3_refiner._paths("qwen3-14b:qwen3-14b-custom", require_compiler=False)[3], model)

    def test_benchmark_resets_rates_and_applies_only_to_matching_files(self):
        from panel import settings
        with tempfile.TemporaryDirectory() as root, \
             mock.patch.object(settings, "PROJECT_ROOT", root), \
             mock.patch.object(settings, "LOGS_DIR", root), \
             mock.patch.dict(os.environ, {}, clear=True):
            folder = os.path.join(root, "models", "gemma-4-12b-heretic")
            os.makedirs(folder)
            model, server = os.path.join(folder, "model.gguf"), os.path.join(root, "server.exe")
            open(model, "wb").close()
            open(server, "wb").close()
            result = {"model_path": os.path.normcase(os.path.abspath(model)), "model_mtime": os.path.getmtime(model),
                      "server_path": os.path.normcase(os.path.abspath(server)), "server_mtime": os.path.getmtime(server),
                      "gpu_layers": 24, "tokens": 100, "milliseconds": 10000}
            with open(os.path.join(root, "local_model_benchmarks.json"), "w", encoding="utf-8") as target:
                json.dump({"at": 100, "models": {"gemma-4-12b": result}}, target)
            events = [
                {"event": "start", "pid": 1, "model": "gemma-4-12b", "model_mtime": os.path.getmtime(model)},
                {"event": "completion", "at": 99, "pid": 1, "model": "gemma-4-12b",
                 "timings": {"predicted_n": 1000, "predicted_ms": 1000}},
                {"event": "completion", "at": 101, "pid": 1, "model": "gemma-4-12b",
                 "timings": {"predicted_n": 100, "predicted_ms": 5000}},
            ]
            with open(os.path.join(root, "local_llm_tokens.jsonl"), "w", encoding="utf-8") as target:
                for event in events:
                    target.write(json.dumps(event) + "\n")
            benchmarks = settings.local_model_benchmarks()
            self.assertEqual(settings.local_model_rates([{"id": "gemma-4-12b"}])["gemma-4-12b"], 13.3)
            self.assertEqual(settings.benchmark_for_model(benchmarks, "gemma-4-12b", model, server)["gpu_layers"], 24)
            os.utime(server, (result["server_mtime"] + 1, result["server_mtime"] + 1))
            self.assertIsNone(settings.benchmark_for_model(benchmarks, "gemma-4-12b", model, server))
            os.utime(model, (result["model_mtime"] + 1, result["model_mtime"] + 1))
            self.assertNotIn("gemma-4-12b", settings.local_model_rates([{"id": "gemma-4-12b"}]))

    def test_discovers_model_folders_and_keeps_selections_when_missing(self):
        from panel import settings
        with tempfile.TemporaryDirectory() as root, \
             mock.patch.object(settings, "PROJECT_ROOT", root), \
             mock.patch.object(h3_refiner, "PROJECT_ROOT", root), \
             mock.patch.object(settings, "PATH", os.path.join(root, "settings.json")), \
             mock.patch.dict(os.environ, {}, clear=True):
            folder = os.path.join(root, "models", "gemma-4-12B-it-uncensored-Q5_K_M")
            os.makedirs(folder)
            for name in ("gemma-Q5.gguf", "gemma-mmproj.gguf"):
                open(os.path.join(folder, name), "wb").close()
            server = os.path.join(root, "llama-server.exe")
            open(server, "wb").close()
            os.environ["H3IR_LLAMA_SERVER"] = server
            model_id = "gemma-4-12b:gemma-4-12B-it-uncensored-Q5_K_M"
            self.assertIn(model_id, [item["id"] for item in settings.local_models()])
            self.assertTrue(next(item for item in settings.local_models() if item["id"] == model_id)["vision"])
            settings.update({"local_llm_model": model_id, "h3_model": model_id})
            self.assertEqual(settings.load()["local_llm_model"], model_id)
            self.assertEqual(h3_refiner._paths(model_id, False)[3:],
                             (os.path.join(folder, "gemma-Q5.gguf"), os.path.join(folder, "gemma-mmproj.gguf")))
            with self.assertRaises(ValueError):
                settings.update({"h3_model": "gemma-4-12b:../outside"})
            os.remove(os.path.join(folder, "gemma-Q5.gguf"))
            self.assertEqual(settings.load()["h3_model"], model_id)
            with self.assertRaisesRegex(ValueError, "missing or unsupported"):
                h3_refiner._paths(model_id, False)

    def test_discovered_qwen_keeps_text_only_behavior(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.model_id = "qwen3-14b:qwen3-14b-new"
        with self.assertRaisesRegex(RuntimeError, "text-only"):
            refiner.plan("prompt", {}, [b"image"])
        with self.assertRaisesRegex(RuntimeError, "text-only"):
            refiner.compile("prompt", 5, 640, 384, "balanced", images=["image"])

    def test_discovers_original_and_legacy_gguf_names(self):
        with tempfile.TemporaryDirectory() as root, \
             mock.patch.object(h3_refiner, "PROJECT_ROOT", root), \
             mock.patch.dict(os.environ, {}, clear=True):
            server = os.path.join(root, "llama-server.exe")
            open(server, "wb").close()
            os.environ["H3IR_LLAMA_SERVER"] = server
            for model_id, folder, model, projector in (
                ("gemma-4-12b", "gemma-4-12b-heretic", "gemma-Q4_K_M.gguf", "gemma-mmproj-BF16.gguf"),
                ("qwen3-14b", "qwen3-14b-abliterated", "model.gguf", None),
            ):
                with self.subTest(model_id=model_id):
                    directory = os.path.join(root, "models", folder)
                    os.makedirs(directory)
                    for name in (model, projector):
                        if name:
                            open(os.path.join(directory, name), "wb").close()
                    _, _, _, found_model, found_projector = h3_refiner._paths(model_id, require_compiler=False)
                    self.assertEqual(found_model, os.path.join(directory, model))
                    self.assertEqual(found_projector, os.path.join(directory, projector) if projector else None)

    def test_gguf_discovery_requires_unambiguous_files_and_honors_overrides(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {}, clear=True):
            for name in ("model.gguf", "other.GGUF", "mmproj.gguf", "other-mmproj.gguf"):
                open(os.path.join(folder, name), "wb").close()
            with self.assertRaisesRegex(RuntimeError, "Multiple local model GGUF files.*H3IR_MODEL_FILE"):
                h3_refiner._gguf_path(folder)
            with self.assertRaisesRegex(RuntimeError, "Multiple vision projector GGUF files.*H3IR_PROJECTOR_FILE"):
                h3_refiner._gguf_path(folder, projector=True)
            with mock.patch.dict(os.environ, {"H3IR_MODEL_FILE": "chosen-model",
                                              "H3IR_PROJECTOR_FILE": "chosen-projector"}):
                self.assertEqual(h3_refiner._gguf_path(folder), "chosen-model")
                self.assertEqual(h3_refiner._gguf_path(folder, projector=True), "chosen-projector")

    def test_missing_projector_is_reported(self):
        with tempfile.TemporaryDirectory() as root, \
             mock.patch.object(h3_refiner, "PROJECT_ROOT", root), \
             mock.patch.dict(os.environ, {}, clear=True):
            server = os.path.join(root, "llama-server.exe")
            directory = os.path.join(root, "models", "gemma-4-12b-heretic")
            os.makedirs(directory)
            open(server, "wb").close()
            open(os.path.join(directory, "gemma-Q4_K_M.gguf"), "wb").close()
            os.environ["H3IR_LLAMA_SERVER"] = server
            with self.assertRaisesRegex(RuntimeError, "needs vision projector"):
                h3_refiner._paths("gemma-4-12b", require_compiler=False)

    def test_local_model_launch_uses_selected_gpu_layers(self):
        for model in ("gemma-4-12b", "qwen3-14b"):
            with self.subTest(model=model):
                refiner = object.__new__(h3_refiner.Refiner)
                refiner.comfy_url = None
                refiner.server, refiner.model = "server", "model"
                refiner.projector = "projector" if model == "gemma-4-12b" else None
                refiner.model_id, refiner.process = model, None
                refiner.gpu_layers = 24
                refiner.verbose = False
                with mock.patch.dict(os.environ, {"H3IR_GPU_LAYERS": "16"}), \
                     mock.patch.object(h3_refiner.subprocess, "Popen", side_effect=OSError("launch intercepted")) as launch:
                    with self.assertRaisesRegex(OSError, "launch intercepted"):
                        refiner.__enter__()
                args = launch.call_args.args[0]
                self.assertEqual(args[args.index("--gpu-layers") + 1], "24")

    def _launch_args(self, model, projector):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.comfy_url, refiner.server, refiner.model, refiner.projector = None, "server", "model", projector
        refiner.model_id, refiner.process, refiner.gpu_layers, refiner.verbose = model, None, "all", False
        with mock.patch.object(h3_refiner.subprocess, "Popen", side_effect=OSError("launch intercepted")) as launch:
            with self.assertRaisesRegex(OSError, "launch intercepted"):
                refiner.__enter__()
        return launch.call_args.args[0]

    def test_qwen_keeps_its_cache_at_8_bits_and_gemma_at_full_precision(self):
        qwen = self._launch_args("qwen3-14b", None)
        self.assertEqual(qwen[qwen.index("--ctx-size") + 1], str(h3_refiner.CONTEXT))
        self.assertEqual((qwen[qwen.index("--cache-type-k") + 1], qwen[qwen.index("--cache-type-v") + 1]), ("q8_0", "q8_0"))
        self.assertEqual(qwen[qwen.index("--flash-attn") + 1], "on")
        gemma = self._launch_args("gemma-4-12b", "projector")
        self.assertNotIn("--cache-type-k", gemma)
        self.assertEqual(gemma[gemma.index("--mmproj") + 1], "projector")

    def test_work_without_images_starts_without_the_vision_projector(self):
        with mock.patch.object(h3_refiner, "_paths", return_value=("root", "python", "server", "model", "projector")), \
             mock.patch.object(h3_refiner.panel_settings, "local_model_benchmarks", return_value={"models": {}}):
            self.assertIsNone(h3_refiner.Refiner(model_id="gemma-4-12b", require_compiler=False, vision=False).projector)
            seeing = h3_refiner.Refiner(model_id="gemma-4-12b", require_compiler=False)
        self.assertEqual(seeing.projector, "projector")
        self.assertNotIn("--mmproj", self._launch_args("gemma-4-12b", None))
        blind = object.__new__(h3_refiner.Refiner)
        blind.model_id, blind.projector = "gemma-4-12b", None
        with self.assertRaisesRegex(RuntimeError, "without its vision projector"):
            blind.plan("prompt", {}, [b"jpeg"])

    def test_benchmark_refuses_to_measure_a_model_that_overflows_the_gpu(self):
        from scripts import benchmark_local_models as benchmark
        line = ("0.00.45 I common_memory_breakdown_print: |   - Vulkan0 (RTX 3080 Ti) | 12084 = {free} + "
                "(7897 =  7024 +     736 +     137) +       -7126 |")
        self.assertEqual(benchmark.memory_fits(line.format(free=11312), "all"),
                         {"vram_total_mib": 12084, "vram_free_mib": 11312, "vram_needed_mib": 7897})
        with self.assertRaisesRegex(benchmark.BenchmarkInterrupted, "Only 7900 MiB of 12084 MiB"):
            benchmark.memory_fits(line.format(free=7900), "all")
        self.assertIsNone(benchmark.memory_fits("", 0))
        with self.assertRaisesRegex(RuntimeError, "did not report its GPU memory"):
            benchmark.memory_fits("", 24)

    def test_benchmark_looks_below_all_layers_for_a_model_that_spills(self):
        from scripts import benchmark_local_models as benchmark

        def tried(rates):
            asked = []
            benchmark.layer_counts(48, lambda layers: asked.append(layers) or rates.get(layers))
            return asked
        # It fits: one step down is slower, and that's the end of it.
        self.assertEqual(tried({"all": 73, 46: 30}), ["all", 46])
        # It spills at all layers: faster with fewer, until it isn't.
        self.assertEqual(tried({"all": 14, 46: 40, 44: 52, 42: 24}), ["all", 46, 44, 42])
        # Still spilling two layers down: hardly slower, so it goes on until it is faster, then past its best.
        self.assertEqual(tried({"all": 12.8, 46: 11.1, 44: 13, 42: 38, 40: 30}), ["all", 46, 44, 42, 40])
        # Nothing on the GPU works: then, and only then, the CPU.
        self.assertEqual(tried({0: 5}), ["all"] + list(range(46, 23, -2)) + [0])

    def test_token_samples_measure_rate_and_reset_between_requests(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner._token_previous = None
        slot = {"id_task": 1, "is_processing": True, "n_prompt_tokens_processed": 40,
                "params": {"chat_format": "peg-gemma4"}, "next_token": [{"n_decoded": 10, "n_remain": 90}]}
        with mock.patch.object(refiner, "_token_event") as event, mock.patch("builtins.print") as output:
            refiner._sample_tokens([slot], 100)
            slot["next_token"][0]["n_decoded"] = 35
            refiner._sample_tokens([slot], 105)
            self.assertEqual(event.call_args.kwargs["tokens_per_second"], 5)
            self.assertEqual(event.call_args.kwargs["generated"], 35)
            self.assertEqual(event.call_args.kwargs["input_tokens"], 40)
            self.assertEqual(refiner.tokens, {"per_second": 5.0, "total": 35})
            output.assert_called_with("Local LLM: 5.0 tok/s | 35 total tok", flush=True)
            slot["id_task"] = 2
            slot["next_token"] = []
            refiner._sample_tokens([slot], 110)
            self.assertEqual(event.call_args.kwargs["tokens_per_second"], 0)
            self.assertEqual(event.call_args.kwargs["generated"], 0)
            refiner._sample_tokens([], 115)
            output.assert_called_with("Local LLM: idle", flush=True)
            self.assertIsNone(refiner._token_previous)
            self.assertIsNone(refiner.tokens)

    def test_token_monitor_reports_failure_and_recovers(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.url = "http://127.0.0.1:42/v1"
        refiner._token_previous = None
        refiner._token_stop = mock.Mock()
        refiner._token_stop.is_set.return_value = False
        refiner._token_stop.wait.side_effect = [False, True]
        response = mock.Mock()
        response.json.return_value = []
        with mock.patch.object(h3_refiner.requests, "get",
                               side_effect=[h3_refiner.requests.Timeout("slow"), response]) as get, \
             mock.patch("builtins.print") as output:
            refiner._monitor_tokens()
            self.assertEqual(get.call_args.args[0], "http://127.0.0.1:42/slots")
            output.assert_called_once_with("Local LLM: telemetry unavailable (slow)", flush=True)
            self.assertEqual(get.call_count, 2)

    def test_completion_logs_usage_and_truncation_without_response_text(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner._token_stop = mock.Mock()
        body = {"choices": [{"finish_reason": "length", "message": {"content": "private text"}}],
                "usage": {"prompt_tokens": 40, "completion_tokens": 100},
                "timings": {"predicted_per_second": 4.5}}
        with mock.patch.object(refiner, "_token_event") as event, mock.patch("builtins.print") as output:
            refiner._completion_tokens(body)
            self.assertEqual(event.call_args.kwargs["finish_reason"], "length")
            self.assertEqual(event.call_args.kwargs["usage"]["completion_tokens"], 100)
            self.assertNotIn("private text", str(event.call_args))
            output.assert_called_once_with("Local LLM complete: 4.5 tok/s | 100 total tok", flush=True)

    def test_refiner_waits_for_comfyui_started_by_panel(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.comfy_url = "http://127.0.0.1:8188"
        queue = mock.Mock()
        queue.json.return_value = {"queue_running": [[1]], "queue_pending": []}
        with mock.patch.dict(os.environ, {"COMFYUI_STARTUP_WAIT": "180"}), mock.patch.object(h3_refiner, "COMFY_BUSY_WAIT", 0), \
             mock.patch.object(h3_refiner.requests, "get", side_effect=[h3_refiner.requests.ConnectionError("starting"), queue]) as get, \
             mock.patch.object(h3_refiner.requests, "post") as post, \
             mock.patch.object(h3_refiner.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "running or queued"):
                refiner.__enter__()
            self.assertEqual(get.call_count, 2)
            sleep.assert_called_once()
            post.assert_not_called()

    def test_refiner_reports_offline_comfyui_without_startup_wait(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.comfy_url = "http://127.0.0.1:8188"
        with mock.patch.dict(os.environ, {"COMFYUI_STARTUP_WAIT": "0"}), \
             mock.patch.object(h3_refiner.requests, "get", side_effect=h3_refiner.requests.ConnectionError("offline")) as get, \
             mock.patch.object(h3_refiner.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "Could not release ComfyUI models.*offline"):
                refiner.__enter__()
            self.assertEqual(get.call_count, 1)
            sleep.assert_not_called()

    def test_refiner_releases_models_after_comfyui_becomes_ready(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.comfy_url, refiner.server, refiner.model, refiner.projector = "http://127.0.0.1:8188", "server", "model", None
        refiner.model_id, refiner.process = "gemma-4-12b", None
        refiner.gpu_layers = "all"
        refiner.verbose = False
        queue = mock.Mock()
        queue.json.return_value = {"queue_running": [], "queue_pending": []}
        cleanup = mock.Mock(status_code=200)
        cleanup.json.return_value = {"version": 1, "completed": True, "devices": [
            {"type": "cuda", "vram_total": 12 * 2**30, "vram_free": 11 * 2**30,
             "torch_allocated": 0, "torch_reserved": 0}]}
        with mock.patch.dict(os.environ, {"COMFYUI_STARTUP_WAIT": "180"}), \
             mock.patch.object(h3_refiner.requests, "get", side_effect=[h3_refiner.requests.ConnectionError("starting"), queue]), \
             mock.patch.object(h3_refiner.requests, "post", return_value=cleanup) as post, \
             mock.patch.object(h3_refiner.time, "sleep"), \
             mock.patch.object(h3_refiner.subprocess, "Popen", side_effect=OSError("test launch")):
            with self.assertRaisesRegex(OSError, "test launch"):
                refiner.__enter__()
            post.assert_called_once_with("http://127.0.0.1:8188/gen-center/free", json={}, timeout=125)

    def test_local_model_starts_when_comfyui_connection_is_refused(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.comfy_url, refiner.server, refiner.model, refiner.projector = "http://127.0.0.1:8188", "server", "model", None
        refiner.model_id, refiner.process = "qwen3-14b", None
        refiner.gpu_layers = "all"
        refiner.verbose = False
        error = h3_refiner.requests.ConnectionError("ComfyUI is off")
        error.__context__ = ConnectionRefusedError("No listener")
        with mock.patch.dict(os.environ, {"COMFYUI_STARTUP_WAIT": "0"}), \
             mock.patch.object(h3_refiner.requests, "get", side_effect=error), \
             mock.patch.object(h3_refiner.requests, "post") as post, \
             mock.patch.object(h3_refiner.subprocess, "Popen", side_effect=OSError("launch reached")) as launch, \
             mock.patch("builtins.print") as output:
            with self.assertRaisesRegex(OSError, "launch reached"):
                refiner.__enter__()
            launch.assert_called_once()
            post.assert_not_called()
            output.assert_called_once_with(
                "ComfyUI is not listening; starting the local model without unloading it.", flush=True)

    def test_local_model_does_not_ignore_uncertain_or_failed_comfyui_cleanup(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.comfy_url = "http://127.0.0.1:8188"
        queue = mock.Mock()
        queue.json.return_value = {"queue_running": [], "queue_pending": []}
        for error in (h3_refiner.requests.Timeout("not responding"),
                      h3_refiner.requests.ConnectionError("unknown connection failure")):
            with self.subTest(error=type(error).__name__), \
                 mock.patch.dict(os.environ, {"COMFYUI_STARTUP_WAIT": "0"}), \
                 mock.patch.object(h3_refiner.requests, "get", side_effect=error), \
                 mock.patch.object(h3_refiner.subprocess, "Popen") as launch:
                with self.assertRaisesRegex(RuntimeError, "before starting the local model"):
                    refiner.__enter__()
                launch.assert_not_called()
        error = h3_refiner.requests.ConnectionError("free failed")
        error.__context__ = ConnectionRefusedError("went offline after queue check")
        with mock.patch.object(h3_refiner.requests, "get", return_value=queue), \
             mock.patch.object(h3_refiner.requests, "post", side_effect=error), \
             mock.patch.object(h3_refiner.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(RuntimeError, "free failed"):
                refiner.__enter__()
            launch.assert_not_called()

    def test_local_planner_uses_structured_request_and_vision(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.url = "http://127.0.0.1:42/v1"
        refiner.model_id, refiner.projector = "gemma-4-12b", "projector"
        response = mock.Mock()
        response.json.return_value = {"choices": [{"message": {"content": '{"title":"Test","versions":[]}'}, "finish_reason": "stop"}]}
        with mock.patch.object(h3_refiner.requests, "post", return_value=response) as post:
            result = refiner.plan("write", image_planner.VERSIONS_SCHEMA, [b"jpeg"])
            self.assertEqual(json.loads(result)["title"], "Test")
            body = post.call_args.kwargs["json"]
            self.assertEqual(body["response_format"]["json_schema"]["schema"], image_planner.VERSIONS_SCHEMA)
            self.assertEqual(body["messages"][0]["content"][0]["image_url"]["url"], "data:image/jpeg;base64,anBlZw==")
            refiner.model_id = "qwen3-14b"
            with self.assertRaisesRegex(RuntimeError, "text-only"):
                refiner.plan("write", image_planner.VERSIONS_SCHEMA, [b"jpeg"])
            response.json.return_value["choices"][0]["finish_reason"] = "length"
            with self.assertRaisesRegex(RuntimeError, "cut off"):
                refiner.plan("write", image_planner.VERSIONS_SCHEMA)

    def test_local_choice_is_available_and_plans_each_side(self):
        self.assertIn("local", dict(video_planner.LLMS))
        self.assertTrue(video_planner.llm_configured("local"))
        for build in (video.build_options, image.build_options):
            flags, error = build({"llm": "local", "prompt_mode": "llm"})
            self.assertIsNone(error)
            self.assertIn("local", flags)
        refiner = mock.Mock()
        refiner.plan.return_value = json.dumps({"title": "Set", "versions": [
            {"title": "One", "prompt": "A tree."}, {"title": "Two", "prompt": "A lake."}]})
        title, versions = image_planner.write_prompts([], "landscapes", 2, "local", refiner=refiner)
        self.assertEqual((title, len(versions)), ("Set", 2))
        refiner.plan.return_value = json.dumps({"title": "Film", "shots": [
            {"title": "One", "seconds": 5, "prompt": "A boat moves."}]})
        title, shots = video_planner.plan_film(None, "boat", 5, "image", "local", refiner=refiner)
        self.assertEqual((title, len(shots)), ("Film", 1))

    def test_video_prompt_sections_are_ordered_and_normalized(self):
        formatted = h3_refiner.video_prompt_format(
            "T2VA\n[Shot 1] A boat.\n\noverall_soundscape\nWater.\n\nnon_diegetic_music\nN/A")
        self.assertTrue(formatted.startswith("integrated_multimodal_description: [Shot 1]"))
        self.assertIn("\noverall_soundscape:\n", formatted)
        self.assertIn("\nnon_diegetic_music:\n", formatted)
        for value in ("[Shot 1] Only a shot.", "Here is your prompt:\nintegrated_multimodal_description: [Shot 1]\noverall_soundscape: N/A\nnon_diegetic_music: N/A",
                      "integrated_multimodal_description: [Shot 1]\nnon_diegetic_music: N/A\noverall_soundscape: N/A",
                      "integrated_multimodal_description: [Shot 1]\noverall_soundscape:\nnon_diegetic_music: N/A"):
            with self.assertRaises(RuntimeError):
                h3_refiner.video_prompt_format(value)

    def test_qwen_reasoning_is_separated_without_accepting_incomplete_output(self):
        split = h3_refiner_worker.split_qwen_reasoning
        self.assertEqual(split("<think>private</think> final"), ("private", "final"))
        self.assertEqual(split("private</think> final"), ("private", "final"))
        self.assertEqual(split("final"), ("", "final"))
        for value in ("<think>unfinished", "<think>thought</think>", "answer</think><think>unfinished"):
            with self.assertRaises(ValueError):
                split(value)

    def test_write_prompt_uses_side_specific_instructions_and_checks_output(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.url = "http://127.0.0.1:42/v1"
        refiner.model_id = "gemma-4-12b"
        response = mock.Mock()
        response.json.return_value = {"choices": [{"message": {"content": "  A vivid scene.  "}, "finish_reason": "stop"}]}
        with mock.patch.object(h3_refiner.requests, "post", return_value=response) as post:
            for side in ("video", "image"):
                content = ("integrated_multimodal_description: [Shot 1] A vivid scene.\noverall_soundscape: N/A\nnon_diegetic_music: N/A"
                           if side == "video" else "A vivid scene.")
                response.json.return_value["choices"][0]["message"]["content"] = content
                self.assertEqual(refiner.write_prompt("a harbour", side), content)
                payload = post.call_args.kwargs["json"]
                self.assertIn(side + "-generation", payload["messages"][0]["content"])
                self.assertIn("cannot see", payload["messages"][0]["content"])
                if side == "video":
                    for section in ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music"):
                        self.assertIn(section, payload["messages"][0]["content"])
                else:
                    self.assertIn("single still moment", payload["messages"][0]["content"])
                self.assertEqual(payload["messages"][1]["content"], "a harbour")
                self.assertFalse(payload["chat_template_kwargs"]["enable_thinking"])
            refiner.model_id = "qwen3-14b"
            response.json.return_value["choices"][0]["message"]["content"] = "integrated_multimodal_description: [Shot 1] A boat.\noverall_soundscape: N/A\nnon_diegetic_music: N/A"
            refiner.write_prompt("a harbour", "video")
            self.assertTrue(post.call_args.kwargs["json"]["chat_template_kwargs"]["enable_thinking"])
            response.json.return_value["choices"][0]["finish_reason"] = "length"
            with self.assertRaisesRegex(RuntimeError, "cut off"):
                refiner.write_prompt("a harbour", "video")
            response.json.return_value["choices"][0] = {"message": {"content": ""}}
            with self.assertRaisesRegex(RuntimeError, "empty"):
                refiner.write_prompt("a harbour", "image")
            response.json.return_value["choices"][0] = {"message": {"content": "thought</think>prompt"}}
            self.assertEqual(refiner.write_prompt("a harbour", "image"), "prompt")
            response.json.return_value["choices"][0] = {"message": {"content": "<think>unfinished"}}
            with self.assertRaisesRegex(RuntimeError, "reasoning"):
                refiner.write_prompt("a harbour", "image")

    def test_write_prompt_can_stream_its_answer_and_still_checks_it(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.url = "http://127.0.0.1:42/v1"
        refiner.model_id = "gemma-4-12b"
        response = mock.MagicMock()
        response.__enter__.return_value = response
        chunk = lambda delta, finish=None: "data: " + json.dumps({"choices": [{"delta": delta, "finish_reason": finish}]})
        response.iter_lines.return_value = [chunk({"reasoning_content": "hmm"}), chunk({"content": "A vivid "}),
                                            chunk({"content": "scene. "}), chunk({}, "stop"), "data: [DONE]"]
        pieces = []
        with mock.patch.object(h3_refiner.requests, "post", return_value=response) as post:
            self.assertEqual(refiner.write_prompt("a harbour", "image", on_text=pieces.append), "A vivid scene.")
            self.assertEqual(pieces, ["A vivid ", "scene. "], "its answer as it comes, not its reasoning")
            self.assertTrue(post.call_args.kwargs["json"]["stream"])
            response.iter_lines.return_value = [chunk({"content": "A vivid"}), chunk({}, "length"), "data: [DONE]"]
            with self.assertRaisesRegex(RuntimeError, "cut off"):
                refiner.write_prompt("a harbour", "image", on_text=pieces.append)

    def test_chat_streams_the_reply_and_says_how_it_ended(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.url = "http://127.0.0.1:42/v1"
        refiner.model_id = "gemma-4-12b"
        response = mock.MagicMock()
        response.__enter__.return_value = response
        chunk = lambda content=None, finish=None: "data: " + json.dumps(
            {"choices": [{"delta": {"content": content} if content else {}, "finish_reason": finish}]})
        response.iter_lines.return_value = ["", chunk("Hel"), ": keep-alive", chunk("lo"), chunk(finish="length"), "data: [DONE]"]
        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}]
        with mock.patch.object(h3_refiner.requests, "post", return_value=response) as post:
            self.assertEqual(list(refiner.chat(messages, 100)), [("text", "Hel"), ("text", "lo"), ("finish", "length")])
            payload = post.call_args.kwargs["json"]
            self.assertEqual((payload["messages"], payload["max_tokens"], payload["stream"]), (messages, 100, True))
            self.assertFalse(payload["chat_template_kwargs"]["enable_thinking"])
            self.assertTrue(post.call_args.kwargs["stream"])
            self.assertEqual(post.call_args.kwargs["json"]["stream_options"], {"include_usage": True})
            self.assertTrue(post.call_args.kwargs["json"]["timings_per_token"])
            # The server's own timing of its writing, with each piece: passed on as it comes.
            response.iter_lines.return_value = ["data: " + json.dumps({"choices": [{"delta": {"content": "a"}}], "timings": {"predicted_per_second": 71.5}}),
                                                "data: " + json.dumps({"choices": [{"delta": {"content": "b"}}], "timings": {"predicted_per_second": 72.0}}),
                                                "data: [DONE]"]
            self.assertEqual([event for event in refiner.chat(messages, 100) if event[0] in ("text", "speed")],
                             [("text", "a"), ("speed", 71.5), ("text", "b"), ("speed", 72.0)])
            response.iter_lines.return_value = [chunk("ok"), "data: [DONE]"]
            self.assertEqual(list(refiner.chat(messages, 100))[-1], ("finish", "stop"))
            # What it read and wrote, as the server counted: its usage, or else its timings (cached tokens included).
            response.iter_lines.return_value = [chunk("ok"), "data: " + json.dumps(
                {"choices": [], "usage": {"prompt_tokens": 40, "completion_tokens": 2}}), "data: [DONE]"]
            self.assertEqual(list(refiner.chat(messages, 100))[-2:], [("usage", {"prompt": 40, "completion": 2}), ("finish", "stop")])
            response.iter_lines.return_value = ["data: " + json.dumps({"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}],
                                                                      "timings": {"prompt_n": 5, "cache_n": 30, "predicted_n": 2}}), "data: [DONE]"]
            self.assertIn(("usage", {"prompt": 35, "completion": 2}), list(refiner.chat(messages, 100)))
            response.raise_for_status.side_effect = h3_refiner.requests.HTTPError("500")
            with self.assertRaisesRegex(RuntimeError, "Could not get a reply"):
                list(refiner.chat(messages, 100))

    def test_settings_and_video_form(self):
        self.assertEqual(h3_refiner.settings(None, None), ("off", "balanced"))
        for creativity in h3_refiner.CREATIVITY:
            flags, error = video.build_options({"h3_enhance": "review", "h3_creativity": creativity})
            self.assertIsNone(error)
            self.assertEqual(video.option(flags, "--h3-creativity"), creativity)
            self.assertEqual(video.option(flags, "--h3-enhance"), "review")
        flags, error = video.build_options({"h3_enhance": "render"})
        self.assertIsNone(error)
        self.assertEqual(video.option(flags, "--h3-creativity"), "balanced")
        self.assertIsNotNone(video.build_options({"h3_enhance": "render", "h3_creativity": "invented"})[1])
        self.assertNotIn("--h3-enhance", video.build_options({})[0])

    def test_director_anchor_depends_on_actual_image_mode(self):
        graph = {"1": {"class_type": director.DIRECTOR, "inputs": {"director_inputs": [director.INPUTS_ID, 0]}},
                 director.INPUTS_ID: {"class_type": director.INPUTS, "_meta": {},
                                      "inputs": {"ref_assets_1": [director.ASSETS_ID, 0]}},
                 director.ASSETS_ID: {"class_type": director.ASSETS}}
        self.assertTrue(h3_refiner.supports(graph))
        self.assertTrue(h3_refiner.first_frame(graph, ["one"]))
        self.assertFalse(h3_refiner.first_frame(graph, ["one", "two"]))
        graph[director.INPUTS_ID]["_meta"][director.IMAGES_AS] = "reference"
        self.assertFalse(h3_refiner.first_frame(graph, ["one"]))
        self.assertFalse(h3_refiner.supports({"1": {"class_type": director.DIRECTOR, "inputs": {}}}))

    def test_compiler_passes_creativity_and_checks_wiring(self):
        with tempfile.TemporaryDirectory() as temp:
            image = os.path.join(temp, "image.png")
            with open(image, "wb") as file:
                file.write(b"image")
            refiner = object.__new__(h3_refiner.Refiner)
            refiner.root, refiner.python, refiner.url = temp, "python", "http://127.0.0.1:42/v1"
            refiner.model_id = "gemma-4-12b"
            captured = []
            guided = []

            def invoke(args, **kwargs):
                guided.append(kwargs["env"].get("H3IR_GUIDED_DECODING"))
                request = json.loads(kwargs["input"])
                captured.append(request)
                return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
                    "prompt": "enhanced", "mode": "ref2va", "frames": 124,
                    "wiring": [{"wiring": "ref_image_1", "sha256": h3_refiner.digest(image)}],
                }))

            with mock.patch.dict(os.environ), \
                 mock.patch.object(h3_refiner.subprocess, "run", side_effect=invoke):
                os.environ.pop("H3IR_GUIDED_DECODING", None)
                for creativity in h3_refiner.CREATIVITY:
                    self.assertEqual(refiner.compile("a scene", 5, 1280, 736, creativity, [image]), "enhanced")
                self.assertEqual([x["brief"]["creativity"] for x in captured], list(h3_refiner.CREATIVITY))
                self.assertEqual(captured[0]["brief"]["assets"][0]["role"], "subject")
                self.assertEqual(guided, ["1"] * len(h3_refiner.CREATIVITY))
                os.environ["H3IR_GUIDED_DECODING"] = "0"
                refiner.compile("a scene", 5, 1280, 736, "balanced", [image])
                self.assertEqual(guided[-1], "0")

            def wrong(*args, **kwargs):
                return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
                    "prompt": "enhanced", "mode": "ref2va", "frames": 124,
                    "wiring": [{"wiring": "ref_image_2", "sha256": h3_refiner.digest(image)}],
                }))
            with mock.patch.object(h3_refiner.subprocess, "run", side_effect=wrong):
                with self.assertRaisesRegex(RuntimeError, "bindings"):
                    refiner.compile("a scene", 5, 1280, 736, "balanced", [image])

    def test_compiler_treats_incoming_shot_markers_as_prose_references(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.root, refiner.python, refiner.url = "comfy", "python", "http://127.0.0.1:42/v1"
        refiner.model_id = "gemma-4-12b"
        prompt = ("retention_analysis: <Subject 1> (appears in [Shot 1]): fully_preserved.\n"
                  "detailed_description: [Shot 1] An elf walks. [Shot 2] At 00:02.000, she turns.\n"
                  "overall_soundscape: Leaves rustle.\nnon_diegetic_music: N/A")
        response = SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
            "prompt": "enhanced", "mode": "t2va", "frames": 124, "wiring": []}))
        with mock.patch.object(h3_refiner.subprocess, "run", return_value=response) as run:
            self.assertEqual(refiner.compile(prompt, 5, 1280, 736, "extreme"), "enhanced")
        request = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(request["brief"]["intent"],
                         prompt.replace("[Shot 1]", "Shot 1").replace("[Shot 2]", "Shot 2"))
        self.assertEqual(request["brief"]["creativity"], "extreme")

    def test_video_audio_and_paired_soundtrack_bindings(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = [os.path.join(temp, name) for name in ("image", "video", "audio")]
            for path in paths:
                with open(path, "wb") as file:
                    file.write(path.encode())
            refiner = object.__new__(h3_refiner.Refiner)
            refiner.root, refiner.python, refiner.url = temp, "python", "http://127.0.0.1:42/v1"
            refiner.model_id = "gemma-4-12b"

            def invoke(args, **kwargs):
                request = json.loads(kwargs["input"])
                assets = request["brief"]["assets"]
                self.assertEqual([a["kind"] for a in assets], ["image", "video", "audio", "audio"])
                self.assertEqual(assets[2]["paired_video_path"], paths[1])
                self.assertEqual(assets[3]["role"], "voice_timbre")
                wiring = [dict(wiring=name, sha256=h3_refiner.digest(asset["path"])) for name, asset in
                          zip(("ref_image_1", "ref_video_1", "ref_video_audio_1", "ref_audio_1"), assets)]
                return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(
                    {"prompt": "enhanced", "mode": "ref2va", "frames": 124, "wiring": wiring}))

            def extract(path, **kwargs):
                class Output:
                    def run(self, **kwargs):
                        with open(path, "wb") as file:
                            file.write(b"soundtrack")
                return Output()

            stream = mock.Mock()
            stream.output.side_effect = extract
            with mock.patch.object(h3_refiner.ffmpeg, "input", return_value=stream), \
                 mock.patch.object(h3_refiner.subprocess, "run", side_effect=invoke):
                result = refiner.compile("scene", 5, 1280, 736, "balanced", [paths[0]],
                                         videos=[{"path": paths[1], "role": "motion", "seconds": 2, "sound": True}],
                                         audios=[{"path": paths[2], "role": "voice", "seconds": 2}])
            self.assertEqual(result, "enhanced")

    def test_text_only_model_rejects_visual_references(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.model_id = "qwen3-14b"
        for kwargs in ({"images": ["image.png"]}, {"videos": [{"path": "clip.mp4"}]}):
            with self.assertRaisesRegex(RuntimeError, "text-only"):
                refiner.compile("scene", 5, 640, 384, "balanced", **kwargs)

    def test_model_selection_saved_and_invalid_selection_rejected(self):
        from panel import settings
        path = os.path.join(DATA, "h3-settings-test.json")
        with mock.patch.object(settings, "PATH", path):
            self.assertEqual(settings.load()["h3_model"], "gemma-4-12b")
            settings.update({"h3_model": "qwen3-14b"})
            self.assertEqual(h3_refiner.selected_model(), "qwen3-14b")
            with self.assertRaisesRegex(ValueError, "Unknown"):
                settings.update({"h3_model": "missing"})
            self.assertEqual(settings.load()["h3_model"], "qwen3-14b")

    def test_the_local_llm_has_its_own_model_apart_from_openh3(self):
        from panel import settings
        path = os.path.join(DATA, "local-llm-settings-test.json")
        if os.path.exists(path):
            os.remove(path)
        with mock.patch.object(settings, "PATH", path):
            settings.update({"h3_model": "qwen3-14b"})
            self.assertEqual(h3_refiner.local_llm_model(), "qwen3-14b", "until chosen, it is OpenH3-IR's, as it was")
            settings.update({"local_llm_model": "gemma-4-12b"})
            self.assertEqual((h3_refiner.local_llm_model(), h3_refiner.selected_model()), ("gemma-4-12b", "qwen3-14b"))
            with self.assertRaisesRegex(ValueError, "Unknown local LLM"):
                settings.update({"local_llm_model": "missing"})
            self.assertEqual(settings.load()["edit_preset"], "", "the Qwen edit workflow until a preset is chosen")
            self.assertEqual(settings.update({"edit_preset": "My edit"})["edit_preset"], "My edit")
            with mock.patch.object(h3_refiner, "_paths", return_value=("root", "python", "server", "model", None)):
                self.assertEqual(h3_refiner.Refiner(model_id=h3_refiner.local_llm_model()).model_id, "gemma-4-12b", "writing prompts")
                self.assertEqual(h3_refiner.Refiner().model_id, "qwen3-14b", "OpenH3-IR")

    def test_before_review_saves_each_prompt_and_skips_completed(self):
        state = RunState.new("brief", 10, "image", 1280, 736, image_count=0)
        state.h3_mode, state.h3_creativity = "review", "extreme"
        state.shots = [{"prompt": "first", "planner_prompt": "first", "seconds": 5},
                       {"prompt": "second", "planner_prompt": "second", "seconds": 5}]
        state.approved_prompt_key = state.prompt_key()
        refiner = mock.MagicMock()
        refiner.__enter__.return_value = refiner
        refiner.compile.side_effect = ["first enhanced", "second enhanced"]
        with mock.patch.object(main.requests, "get", side_effect=main.requests.ConnectionError), \
             mock.patch.object(main.h3_refiner, "Refiner", return_value=refiner), \
             mock.patch.object(main, "ComfyClient", return_value=SimpleNamespace(workflow={})), \
             mock.patch.object(state, "save") as save:
            main.refine_review(state)
            main.refine_review(state)
        self.assertEqual([s["prompt"] for s in state.shots], ["first enhanced", "second enhanced"])
        self.assertEqual([s["planner_prompt"] for s in state.shots], ["first", "second"])
        self.assertEqual([s["enhanced_prompt"] for s in state.shots], ["first enhanced", "second enhanced"])
        self.assertEqual(state.approved_prompt_key, state.prompt_key(), "chosen review enhancement does not revoke approval")
        self.assertEqual(refiner.compile.call_count, 2)
        self.assertEqual(save.call_count, 2)
        self.assertEqual(refiner.compile.call_args.args[4], "extreme")

    def test_refined_director_frames_use_h3_grid(self):
        from pipelines.video import comfy
        client = object.__new__(comfy.ComfyClient)
        client.workflow = {"1": {"class_type": "value", "inputs": {"fps": 24, "frames": 0}}}
        client.fields = {"fps": ("1", "fps"), "frames": ("1", "frames")}
        with mock.patch.object(client, "_fill_images"), mock.patch.object(client, "_fill_media"), \
             mock.patch.object(client, "_run", return_value={}) as run, mock.patch.object(client, "_download"):
            client.render("x", [], 5, 640, 384, "out", h3_refined=True)
        self.assertEqual(run.call_args.args[0]["1"]["inputs"]["frames"], 124)

    def test_refinement_cache_tracks_prompt_settings_and_files(self):
        with tempfile.TemporaryDirectory() as temp:
            path = os.path.join(temp, "plate.png")
            with open(path, "wb") as file:
                file.write(b"one")
            state = RunState.new("brief", 5, "image", 640, 384, image_count=0)
            shot = {"prompt": "hello", "seconds": 5, "seed": 1}
            self.assertNotEqual(main.refinement_key(state, shot, [path], "gemma-4-12b"),
                                main.refinement_key(state, shot, [path], "qwen3-14b"))
            old = main.refinement_key(state, shot, [path])
            state.h3_creativity = "bold"
            self.assertNotEqual(old, main.refinement_key(state, shot, [path]))
            state.h3_creativity = "balanced"
            with open(path, "wb") as file:
                file.write(b"two")
            self.assertNotEqual(old, main.refinement_key(state, shot, [path]))

    def test_shorts_option_is_saved_and_limited_to_h3(self):
        form = {"voice": "", "avatar_clips": "auto", "workflow": "h3.json",
                "h3_enhance": "render", "h3_creativity": "extreme"}
        entry = {"name": "h3.json", "path": "h3.json", "takes": {}}
        with mock.patch.object(shorts, "saved_workflows", return_value=[entry]), \
             mock.patch.object(shorts, "workflow_model", return_value="minimax_h3"):
            _, env, error = shorts.build_run(form)
        self.assertIsNone(error)
        self.assertEqual(env["H3IR_ENHANCE"], "render")
        self.assertEqual(env["H3IR_CREATIVITY"], "extreme")
        with mock.patch.object(shorts, "saved_workflows", return_value=[entry]), \
             mock.patch.object(shorts, "workflow_model", return_value=None):
            self.assertIn("MiniMax H3", shorts.build_run(form)[2])

    def test_busy_comfy_is_not_unloaded(self):
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.comfy_url = "http://127.0.0.1:8188"
        refiner.process = None
        response = mock.Mock()
        response.json.return_value = {"queue_running": [[1]], "queue_pending": []}
        with mock.patch.object(h3_refiner.requests, "get", return_value=response), mock.patch.object(h3_refiner, "COMFY_BUSY_WAIT", 0), \
             mock.patch.object(h3_refiner.requests, "post") as post:
            with self.assertRaisesRegex(RuntimeError, "running or queued"):
                refiner.__enter__()
        post.assert_not_called()

    def test_comfy_finishing_a_stopped_image_is_waited_for_before_the_local_model(self):
        # Paused mid-image: ComfyUI ends the interrupted prompt a moment later, then cleans up (refusing while busy).
        from core import comfy_memory
        refiner = object.__new__(h3_refiner.Refiner)
        refiner.comfy_url = "http://127.0.0.1:8188"
        busy, idle = mock.Mock(), mock.Mock()
        busy.json.return_value = {"queue_running": [[1]], "queue_pending": []}
        idle.json.return_value = {"queue_running": [], "queue_pending": []}
        refused, freed = mock.Mock(status_code=409), mock.Mock(status_code=200)
        freed.json.return_value = {"version": 1, "completed": True, "devices": [
            {"type": "cuda", "vram_total": 12e9, "vram_free": 11e9, "torch_allocated": 0, "torch_reserved": 0}]}
        with mock.patch.object(h3_refiner.requests, "get", side_effect=[busy, busy, idle]) as get, \
             mock.patch.object(comfy_memory.requests, "post", side_effect=[refused, freed]) as post, \
             mock.patch.object(h3_refiner.time, "sleep") as sleep:
            refiner._release_comfy_models()
        self.assertEqual((get.call_count, post.call_count), (3, 2), "asked again until it was idle, and freed")
        self.assertEqual(sleep.call_count, 3, "twice for the queue, once for the cleanup")
        self.assertEqual(refiner.comfy_memory[0]["vram_free"], 11e9)
        # Busy past the wait, cleanup says so rather than an HTTP error.
        with mock.patch.object(comfy_memory.requests, "post", return_value=refused), \
             self.assertRaisesRegex(RuntimeError, "still busy after 0 s"):
            comfy_memory.release("http://127.0.0.1:8188", busy_wait=0)

    def test_shorts_enhanced_render_removes_all_extra_reference_links(self):
        avatar = object.__new__(AvatarGenerator)
        avatar.h3_mode, avatar.url, avatar.client_id = "render", "http://comfy", "test"
        avatar.width, avatar.height = 640, 384
        avatar.workflow = {
            "1": {"class_type": "value", "inputs": {"prompt": "", "fps": 24, "frames": 0}},
            "2": {"class_type": "LoadImage", "inputs": {"image": "one"}},
            "3": {"class_type": "LoadImage", "inputs": {"image": "two"}},
            "4": {"class_type": "refs", "inputs": {"first": ["2", 0], "extra": ["3", 0]}},
            "5": {"class_type": "refs", "inputs": {"extra": ["3", 0]}},
        }
        avatar.fields = {"prompt": ("1", "prompt"), "fps": ("1", "fps"), "frames": ("1", "frames"),
                         "image": ("2", "image"), "image_link": ("4", "first"),
                         "image_2": ("3", "image"), "image_2_link": ("4", "extra"),
                         "image_2_also": [("5", "extra")]}
        response = mock.Mock(status_code=200)
        response.json.return_value = {"prompt_id": "id"}
        with mock.patch("pipelines.shorts.avatar_generator.requests.post", return_value=response) as post, \
             mock.patch.object(avatar, "_wait_for", return_value=None):
            avatar._render("brief", "uploaded.png", None, 5, "clip")
        graph = post.call_args.kwargs["json"]["prompt"]
        self.assertEqual(graph["1"]["inputs"]["frames"], 124)
        self.assertEqual(graph["2"]["inputs"]["image"], "uploaded.png")
        self.assertNotIn("3", graph)
        self.assertNotIn("extra", graph["4"]["inputs"])
        self.assertNotIn("extra", graph["5"]["inputs"])


class CleanupBridgeTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.steps = []
        self.flags = {}
        self.remaining = 0
        self.allocated = 2**30
        self.workspace_allocated = 8 * 2**20
        self.routes = {}
        outer = self

        class Executor:
            def reset(self):
                outer.steps.append("reset")

        memory = ModuleType("comfy.model_management")
        memory.current_loaded_models = [object()]
        memory.get_all_torch_devices = lambda: [SimpleNamespace(type="cuda", index=0)]
        memory.get_total_memory = lambda device: 12 * 2**30
        memory.get_free_memory = lambda device: 11 * 2**30
        def clear_workspaces():
            self.steps.append("cublas")
            self.workspace_allocated = 0

        memory.torch = SimpleNamespace(
            _C=SimpleNamespace(_cuda_clearCublasWorkspaces=clear_workspaces),
            cuda=SimpleNamespace(
                synchronize=lambda device: self.steps.append("synchronize"),
                memory_allocated=lambda device: self.allocated + self.workspace_allocated,
                memory_reserved=lambda device: self.allocated + self.workspace_allocated))

        def empty():
            self.steps.append("empty")
            self.allocated = 0

        memory.soft_empty_cache = empty
        comfy = ModuleType("comfy")
        comfy.model_management = memory
        execution = ModuleType("execution")
        execution.PromptExecutor = Executor
        queue = SimpleNamespace(mutex=threading.RLock(), get_tasks_remaining=lambda: self.remaining,
                                set_flag=lambda key, value: self.flags.__setitem__(key, value))

        def register(path):
            def decorate(function):
                self.routes[path] = function
                return function
            return decorate

        server = ModuleType("server")
        server.PromptServer = SimpleNamespace(instance=SimpleNamespace(
            prompt_queue=queue, routes=SimpleNamespace(post=register)))
        aiohttp = ModuleType("aiohttp")
        aiohttp.web = SimpleNamespace(json_response=lambda body, status=200: SimpleNamespace(body=body, status=status))
        with mock.patch.dict(sys.modules, {"comfy": comfy, "comfy.model_management": memory,
                                          "execution": execution, "server": server, "aiohttp": aiohttp}):
            path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "comfyui", "gen_center_cleanup", "__init__.py")
            self.bridge = runpy.run_path(path)
        self.memory, self.executor = memory, Executor()
        collect = mock.patch.object(self.bridge["gc"], "collect", side_effect=lambda: self.steps.append("collect"))
        collect.start()
        self.addCleanup(collect.stop)

    def process_flags(self):
        self.memory.current_loaded_models.clear()
        if self.flags.pop("free_memory"):
            self.executor.reset()

    async def test_ack_waits_for_worker_reset_garbage_collection_and_gpu_cache_release(self):
        task = asyncio.create_task(self.routes["/gen-center/free"](None))
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        self.memory.soft_empty_cache()
        self.assertFalse(task.done(), "unrelated GPU cleanup must not acknowledge our pending flags")
        self.steps.clear()
        self.process_flags()
        response = await asyncio.wait_for(task, 2)
        self.assertEqual(self.steps, ["reset", "collect", "synchronize", "cublas", "empty"])
        self.assertEqual(response.status, 200)
        self.assertTrue(response.body["completed"])
        self.assertEqual(response.body["devices"][0]["torch_allocated"], 0)
        with mock.patch.object(comfy_memory.requests, "post", return_value=mock.Mock(
                status_code=200, json=lambda: response.body)):
            self.assertEqual(comfy_memory.release("http://comfy")[0]["vram_free"], 11 * 2**30)

    async def test_cpu_cleanup_does_not_access_cuda_workspace_hooks(self):
        self.memory.get_all_torch_devices = lambda: [SimpleNamespace(type="cpu", index=None)]
        self.memory.torch = SimpleNamespace()
        task = asyncio.create_task(self.routes["/gen-center/free"](None))
        await asyncio.sleep(0)
        self.process_flags()
        response = await asyncio.wait_for(task, 2)
        self.assertEqual(response.status, 200)
        self.assertEqual(self.steps, ["reset", "collect", "empty"])
        self.assertEqual(response.body["devices"][0]["torch_allocated"], 0)

    async def test_busy_worker_and_late_work_do_not_acknowledge_safe_cleanup(self):
        self.remaining = 1
        response = await self.routes["/gen-center/free"](None)
        self.assertEqual(response.status, 409)
        self.assertFalse(self.flags)
        self.remaining = 0
        task = asyncio.create_task(self.routes["/gen-center/free"](None))
        await asyncio.sleep(0)
        self.process_flags()
        self.remaining = 1
        response = await asyncio.wait_for(task, 2)
        self.assertEqual(response.status, 409)
        self.assertNotIn("completed", response.body)

    async def test_cleanup_timeout_is_not_reported_as_success(self):
        with mock.patch.object(asyncio, "to_thread", new=mock.AsyncMock(return_value=False)):
            response = await self.routes["/gen-center/free"](None)
        self.assertEqual(response.status, 504)
        self.assertNotIn("completed", response.body)
        self.assertFalse(self.flags["free_memory"].done.is_set())
        self.process_flags()


if __name__ == "__main__":
    unittest.main()
