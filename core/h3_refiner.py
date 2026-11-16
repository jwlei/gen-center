"""Optional OpenH3-IR compilation without changing an H3 render graph."""
import hashlib
import base64
import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import time

import ffmpeg
import requests

from core import comfy_memory, director, h3_refiner_worker, prompt_writer_instructions
from core.llm_reply import CutOff
from core.paths import LOGS_DIR, PROJECT_ROOT
from panel import settings as panel_settings

CREATIVITY = ("restrained", "balanced", "bold", "extreme")
TIMINGS = ("off", "review", "render")
ASPECTS = {"21:9": 21 / 9, "16:9": 16 / 9, "4:3": 4 / 3,
           "1:1": 1, "3:4": 3 / 4, "9:16": 9 / 16}
TIMEOUT = 3600
# The context every local model is started with: the longest request (a plan's prompt, its images, and its answer of
# up to PLAN_TOKENS) is under 16k tokens. What that context costs differs by family: most of Gemma 4's layers only look back
# 1024 tokens, so its cache is about 0.75 GB at 16k; every one of Qwen3 14B's keeps the whole context, 2.5 GB at 16k,
# which with its 8.2 GB of weights is more than a 12 GB card has free. Once it overflows, the driver quietly moves part
# of the model into system memory and writing drops from ~70 to ~10 tok/s. So Qwen's cache is kept at 8 bits: half
# the size, and next to no change in what it writes. (Flash attention, which that needs, is on for both.)
CONTEXT = 16384
# A plan's longest answer: a round of up to 20 image prompts of up to about 300 words each (pipelines/image/planner.py).
PLAN_TOKENS = 12288
KV_CACHE = {"qwen3-14b": "q8_0"}


def settings(mode, creativity):
    mode, creativity = mode or "off", creativity or "balanced"
    if mode not in TIMINGS:
        raise ValueError("Unknown OpenH3-IR timing.")
    if creativity not in CREATIVITY:
        raise ValueError("Unknown OpenH3-IR creativity.")
    return mode, creativity


def supports(workflow):
    directors = [node for node in workflow.values() if node.get("class_type") == director.DIRECTOR]
    if directors:
        inputs = workflow.get(director.INPUTS_ID, {})
        assets = workflow.get(director.ASSETS_ID, {})
        return (len(directors) == 1
                and directors[0].get("inputs", {}).get("director_inputs") == [director.INPUTS_ID, 0]
                and inputs.get("class_type") == director.INPUTS
                and inputs.get("inputs", {}).get("ref_assets_1") == [director.ASSETS_ID, 0]
                and assets.get("class_type") == director.ASSETS)
    return any(node.get("class_type") == "MiniMaxH3ReferenceToVideo" for node in workflow.values())


def supports_path(path):
    if not path:
        return False
    try:
        with open(path, encoding="utf-8") as source:
            return supports(json.load(source))
    except (OSError, ValueError, AttributeError):
        return False


def first_frame(workflow, images):
    if len(images) != 1 or not any(n.get("class_type") == director.DIRECTOR for n in workflow.values()):
        return False
    inputs = workflow.get(director.INPUTS_ID, {})
    return inputs.get("_meta", {}).get(director.IMAGES_AS, "start") == "start"


def selected_model():
    """OpenH3-IR's model (Settings), for reviewing and rendering prompts."""
    return panel_settings.load()["h3_model"]


def local_llm_model():
    """The local model that writes the prompts when the local LLM is chosen (Settings), apart from OpenH3-IR's."""
    return panel_settings.load()["local_llm_model"]


def _gguf_path(folder, projector=False):
    label = "vision projector" if projector else "local model"
    override = "H3IR_PROJECTOR_FILE" if projector else "H3IR_MODEL_FILE"
    if os.getenv(override):
        return os.environ[override]
    matches = []
    if os.path.isdir(folder):
        with os.scandir(folder) as entries:
            matches = sorted(entry.name for entry in entries
                             if entry.is_file() and entry.name.lower().endswith(".gguf")
                             and ("mmproj" in entry.name.lower()) == projector)
    if len(matches) > 1:
        raise RuntimeError(f"Multiple {label} GGUF files in {folder}: {', '.join(matches)}. "
                           f"Keep only one or set {override} to the desired file.")
    return os.path.join(folder, matches[0] if matches else ("mmproj.gguf" if projector else "model.gguf"))


def _paths(model_id, require_compiler=True):
    launcher = os.getenv("COMFYUI_LAUNCHER") or ""
    root = os.getenv("H3IR_COMFY_ROOT") or os.path.join(os.path.dirname(launcher), "ComfyUI")
    python = os.getenv("H3IR_PYTHON") or os.path.join(os.path.dirname(launcher), "python_embeded", "python.exe")
    base = os.path.dirname(os.path.dirname(launcher))
    server = os.getenv("H3IR_LLAMA_SERVER") or os.path.join(base, "1_Misc", "llama.cpp", "b12177-vulkan", "llama-server.exe")
    folder = panel_settings.model_folder(model_id)
    models = os.path.join(PROJECT_ROOT, "models", folder)
    model = _gguf_path(models)
    projector = _gguf_path(models, projector=True) if panel_settings.model_family(model_id) == "gemma-4-12b" else None
    needed = [("llama.cpp server", server), ("local model", model)]
    if require_compiler:
        needed += [("ComfyUI Python", python), ("OpenH3-IR node pack", os.path.join(root, "custom_nodes", "ComfyUI-OpenH3-IR", "compiler.py"))]
    if projector:
        needed.append(("vision projector", projector))
    for label, path in needed:
        if not os.path.isfile(path):
            raise RuntimeError(f"The local model runner needs {label}: {path}. See docs/video.md.")
    return root, python, server, model, projector


def digest(path):
    with open(path, "rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def video_prompt_format(text):
    text = re.sub(r"^T2VA\s*\n+", "", text.strip(), count=1)
    if text.startswith("[Shot 1]"):
        text = "integrated_multimodal_description: " + text
    names = ("subject_definitions", "summary", "retention_analysis", "detailed_description",
             "integrated_multimodal_description", "overall_soundscape", "non_diegetic_music")
    for name in names:
        text = re.sub(rf"(?m)^{name}[ \t]*$", name + ":", text)
    expected = (("subject_definitions", "summary", "retention_analysis", "detailed_description",
                 "overall_soundscape", "non_diegetic_music") if text.startswith("subject_definitions:")
                else ("integrated_multimodal_description", "overall_soundscape", "non_diegetic_music"))
    positions = [re.search(rf"(?m)^{name}:", text) for name in expected]
    if (any(position is None for position in positions)
            or [position.start() for position in positions if position] != sorted(position.start() for position in positions if position)
            or "[Shot 1]" not in text):
        raise RuntimeError("The model did not return the required video prompt sections. Try again.")
    matches = [position for position in positions if position]
    for index, position in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        if not text[position.end():end].strip():
            raise RuntimeError("The model returned an empty video prompt section. Try again.")
    prefix = text[:matches[0].start()].strip()
    if prefix:
        raise RuntimeError("The model returned unexpected text before the video prompt. Try again.")
    return text


class Refiner:
    def __init__(self, comfy_url=None, require_compiler=True, model_id=None, gpu_layers=None, verbose=False, vision=True):
        # OpenH3-IR's model unless told which: writing prompts asks for the local LLM's.
        self.model_id = model_id or selected_model()
        self.root, self.python, server, model, projector = _paths(self.model_id, require_compiler)
        self.process = None
        self.server = server
        self.model = model
        # vision=False for work with no image to look at: the projector is then not loaded, which leaves its ~0.35 GB
        # of GPU memory to the model.
        self.projector = projector if vision else None
        benchmark = (panel_settings.benchmark_for_model(panel_settings.local_model_benchmarks(), self.model_id,
                                                        model, server) if gpu_layers is None else None)
        self.gpu_layers = gpu_layers if gpu_layers is not None else benchmark["gpu_layers"] if benchmark else "all"
        self.verbose = verbose
        self.comfy_url = comfy_url
        self.tokens = None

    def _release_comfy_models(self):
        self.comfy_memory = None
        wait = int(os.getenv("COMFYUI_STARTUP_WAIT") or 0)
        deadline = time.monotonic() + wait
        try:
            while True:
                try:
                    queue = requests.get(f"{self.comfy_url}/queue", timeout=10)
                    break
                except (requests.ConnectionError, requests.Timeout) as error:
                    cause = error
                    while cause is not None:
                        if not wait and isinstance(cause, ConnectionRefusedError):
                            print("ComfyUI is not listening; starting the local model without unloading it.", flush=True)
                            return
                        cause = cause.__cause__ or cause.__context__
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise
                    time.sleep(min(5, remaining))
            queue.raise_for_status()
            state = queue.json()
            if not isinstance(state, dict) or not all(isinstance(state.get(key), list) for key in ("queue_running", "queue_pending")):
                raise RuntimeError("ComfyUI returned an invalid queue status; cannot safely release its models.")
            if state.get("queue_running") or state.get("queue_pending"):
                raise RuntimeError("ComfyUI has work running or queued; wait for it before using the local model.")
            print("Waiting for ComfyUI to finish clearing its models and caches...", flush=True)
            self.comfy_memory = comfy_memory.release(self.comfy_url)
            for device in self.comfy_memory:
                if device["type"] == "cuda":
                    print(f"ComfyUI cleanup confirmed: {device['vram_free'] / 2**30:.2f} GiB VRAM available.", flush=True)
        except (requests.RequestException, ValueError) as e:
            raise RuntimeError(f"Could not release ComfyUI models before starting the local model: {e}") from e

    def __enter__(self):
        if self.comfy_url:
            self._release_comfy_models()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}/v1"
        args = [self.server, "--model", self.model]
        if self.projector:
            args += ["--mmproj", self.projector]
        args += ["--host", "127.0.0.1",
                "--port", str(port), "--ctx-size", str(CONTEXT), "--parallel", "1", "--threads", "8",
                "--gpu-layers", str(self.gpu_layers), "--alias", "h3-refiner"]
        cache = KV_CACHE.get(panel_settings.model_family(self.model_id))
        if cache:
            args += ["--flash-attn", "on", "--cache-type-k", cache, "--cache-type-v", cache]
        if self.gpu_layers == 0:
            args += ["--device", "none", "--no-mmproj-offload"]
        if self.verbose:
            args += ["-lv", "4"]
        if panel_settings.model_family(self.model_id) == "qwen3-14b":
            args += ["--reasoning-format", "deepseek"]
        os.makedirs(LOGS_DIR, exist_ok=True)
        self.log = tempfile.NamedTemporaryFile(mode="w+t", encoding="utf-8", prefix="local-llm-",
                                               suffix=".log", dir=LOGS_DIR, delete=False)
        try:
            self.process = subprocess.Popen(args, stdout=self.log, stderr=self.log,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            # The runner OpenH3-IR and prompt writing share: named by the model it runs, not by OpenH3-IR.
            label = next((m["label"] for m in panel_settings.local_models() if m["id"] == self.model_id), self.model_id)
            print(f"🧠 Starting the local model ({label})...", flush=True)
            print(f"Local LLM diagnostics: {self.log.name}", flush=True)
            self._token_stop = threading.Event()
            self._token_previous = None
            self._token_event("start", arguments=args, model_mtime=os.path.getmtime(self.model),
                              server_mtime=os.path.getmtime(self.server),
                              comfy_memory=getattr(self, "comfy_memory", None))
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    self.log.seek(0)
                    raise RuntimeError(f"Local model server stopped: {self.log.read()[-3000:]}")
                try:
                    response = requests.get(f"http://127.0.0.1:{port}/v1/models", timeout=2)
                    if response.ok and any(m.get("id") == "h3-refiner" for m in response.json().get("data", [])):
                        # The panel times the start up to here (core/eta_keys.py LocalModelTimer).
                        print("🧠 Local model ready.", flush=True)
                        self._token_thread = threading.Thread(target=self._monitor_tokens, daemon=True)
                        self._token_thread.start()
                        return self
                except (requests.RequestException, ValueError):
                    pass
                time.sleep(1)
            raise RuntimeError("Local model server did not start within 180 seconds.")
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if hasattr(self, "_token_stop"):
            self._token_stop.set()
        if hasattr(self, "_token_thread"):
            self._token_thread.join()
            print("Local LLM: idle", flush=True)
        self.tokens = None
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if hasattr(self, "log"):
            self.log.close()

    def _token_event(self, event, **values):
        with open(os.path.join(LOGS_DIR, "local_llm_tokens.jsonl"), "a", encoding="utf-8") as target:
            target.write(json.dumps({"at": time.time(), "pid": self.process.pid, "model": self.model_id,
                                     "event": event, **values}) + "\n")

    def _sample_tokens(self, slots, now):
        active = next((slot for slot in slots if slot.get("is_processing")), None)
        if active is None:
            self.tokens = None
            if self._token_previous is not None:
                print("Local LLM: idle", flush=True)
                self._token_previous = None
            return
        next_token = active.get("next_token") or [{}]
        decoded = next_token[0].get("n_decoded", 0)
        task = active["id_task"]
        previous = self._token_previous
        if previous is None or previous[0] != task or decoded < previous[1]:
            previous = (task, 0, now)
        elapsed = now - previous[2]
        rate = (decoded - previous[1]) / elapsed if elapsed > 0 else 0
        self._token_previous = (task, decoded, now)
        self.tokens = {"per_second": round(rate, 1), "total": decoded}
        print(f"Local LLM: {rate:.1f} tok/s | {decoded} total tok", flush=True)
        params = active.get("params") or {}
        self._token_event("tokens", task=task, generated=decoded, tokens_per_second=round(rate, 2),
                          input_tokens=active.get("n_prompt_tokens_processed"),
                          remaining=next_token[0].get("n_remain"),
                          chat_format=params.get("chat_format"), generation_prompt=params.get("generation_prompt"))

    def _monitor_tokens(self):
        unavailable = False
        while not self._token_stop.is_set():
            try:
                response = requests.get(f"{self.url.removesuffix('/v1')}/slots", timeout=2)
                response.raise_for_status()
                self._sample_tokens(response.json(), time.monotonic())
                unavailable = False
            except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as e:
                self.tokens = None
                if not unavailable:
                    print(f"Local LLM: telemetry unavailable ({e})", flush=True)
                    unavailable = True
            except OSError as e:
                self.tokens = None
                print(f"Local LLM: telemetry unavailable (could not save diagnostics: {e})", flush=True)
                return
            if self._token_stop.wait(5):
                break

    def _completion_tokens(self, body):
        self.tokens = None
        usage = body.get("usage") or {}
        if not hasattr(self, "_token_stop"):
            return
        self._token_event("completion", usage=usage, timings=body.get("timings"),
                          finish_reason=body["choices"][0].get("finish_reason"),
                          output_chars=len(body["choices"][0]["message"].get("content") or ""),
                          reasoning_chars=len(body["choices"][0]["message"].get("reasoning_content") or ""))
        count = usage.get("completion_tokens")
        timings = body.get("timings") or {}
        rate = timings.get("predicted_per_second")
        if count is not None:
            speed = f"{rate:.1f} tok/s | " if isinstance(rate, (int, float)) else ""
            print(f"Local LLM complete: {speed}{count} total tok", flush=True)

    def write_prompt(self, text, pipeline):
        instruction = prompt_writer_instructions.INSTRUCTIONS[pipeline]
        try:
            if hasattr(self, "_token_stop"):
                self._token_event("request", kind="write_prompt", pipeline=pipeline,
                                  input_sha256=hashlib.sha256((instruction + text).encode()).hexdigest(),
                                  max_tokens=4096 if panel_settings.model_family(self.model_id) == "qwen3-14b" else 2048,
                                  enable_thinking=panel_settings.model_family(self.model_id) == "qwen3-14b", temperature=0.7)
            response = requests.post(f"{self.url}/chat/completions", json={
                "model": "h3-refiner", "messages": [{"role": "system", "content": instruction},
                                                      {"role": "user", "content": text}],
                "max_tokens": 4096 if panel_settings.model_family(self.model_id) == "qwen3-14b" else 2048, "temperature": 0.7,
                "chat_template_kwargs": {"enable_thinking": panel_settings.model_family(self.model_id) == "qwen3-14b"},
            }, timeout=900)
            response.raise_for_status()
            body = response.json()
            self._completion_tokens(body)
            choice = body["choices"][0]
            result = choice["message"]["content"]
            if choice.get("finish_reason") == "length":
                raise RuntimeError("The generated prompt was cut off; try a shorter input.")
            if not isinstance(result, str) or not result.strip():
                raise RuntimeError("The model returned an empty prompt.")
            if panel_settings.model_family(self.model_id) == "qwen3-14b":
                _, result = h3_refiner_worker.split_qwen_reasoning(result)
            if "<think>" in result or "</think>" in result:
                raise RuntimeError("The model returned its reasoning instead of a clean prompt. Try again.")
            if not result.strip():
                raise RuntimeError("The model returned an empty prompt.")
            return video_prompt_format(result) if pipeline == "video" else result.strip()
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"Could not write the prompt: {e}") from e

    def plan(self, prompt, schema, images=()):
        if panel_settings.model_family(self.model_id) == "qwen3-14b" and images:
            raise RuntimeError("Qwen3 14B is text-only and cannot analyze attached images. Choose Gemma 4 in Settings.")
        if images and not self.projector:
            raise RuntimeError("The local model was started without its vision projector, so it can't see the attached images.")
        content = [{"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," +
                    base64.b64encode(image).decode("ascii")}} for image in images]
        content.append({"type": "text", "text": prompt})
        try:
            if hasattr(self, "_token_stop"):
                self._token_event("request", kind="plan", image_count=len(images),
                                  input_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                                  schema_sha256=hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(),
                                  max_tokens=PLAN_TOKENS, enable_thinking=False, temperature=0.7)
            response = requests.post(f"{self.url}/chat/completions", json={
                "model": "h3-refiner", "messages": [{"role": "user", "content": content}],
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": "prompt_plan", "strict": True, "schema": schema}},
                "max_tokens": PLAN_TOKENS, "temperature": 0.7,
                "chat_template_kwargs": {"enable_thinking": False},
            }, timeout=TIMEOUT)
            response.raise_for_status()
            body = response.json()
            self._completion_tokens(body)
            choice = body["choices"][0]
            if choice.get("finish_reason") == "length":
                raise CutOff("The local model's reply was cut off: it ran out of tokens.")
            result = choice["message"]["content"]
            if not isinstance(result, str) or not result.strip():
                raise RuntimeError("The local model returned an empty plan.")
            if panel_settings.model_family(self.model_id) == "qwen3-14b":
                _, result = h3_refiner_worker.split_qwen_reasoning(result)
            return result.strip()
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"Could not get a plan from the local model: {e}") from e

    def compile(self, prompt, seconds, width, height, creativity, images=(), image_roles=(), videos=(), audios=(), seed=7,
                first_frame=False):
        _, creativity = settings("render", creativity)
        if panel_settings.model_family(self.model_id) == "qwen3-14b" and (images or videos):
            raise RuntimeError("Qwen3 14B is text-only and cannot analyze image or video references. Choose Gemma 4 in Settings.")
        ratio = width / height
        aspect = min(ASPECTS, key=lambda a: abs(ASPECTS[a] - ratio))
        assets = []
        with tempfile.TemporaryDirectory(prefix="openh3-") as temp:
            for index, path in enumerate(images):
                role = image_roles[index - 1] if index and index - 1 < len(image_roles) else "context"
                assets.append({"kind": "image", "role": "frame_anchor_first" if first_frame else "environment" if role == "place" else "subject",
                               "path": path, "sizing": "match",
                               "note": "Another view of the first subject." if role == "view" else ""})
            for index, video in enumerate(videos):
                path = video["path"]
                length = video["seconds"]
                assets.append({"kind": "video", "role": "structure" if video["role"] == "motion" else "subject",
                               "path": path, "seconds": length, "frames": round(length * 24),
                               "note": "The environment shown in the video." if video["role"] == "place" else ""})
                if video.get("sound"):
                    sound = os.path.join(temp, f"soundtrack-{index}.wav")
                    try:
                        ffmpeg.input(path).output(sound, vn=None, ac=2, ar=48000).run(overwrite_output=True, quiet=True)
                    except ffmpeg.Error as e:
                        raise RuntimeError(f"Could not extract reference video soundtrack: {e}") from e
                    assets.append({"kind": "audio", "role": "bgm", "path": sound, "seconds": length,
                                   "paired_video_path": path})
            for audio in audios:
                assets.append({"kind": "audio", "role": {"voice": "voice_timbre", "music": "bgm", "sound": "sfx"}[audio["role"]],
                               "path": audio["path"], "seconds": audio["seconds"]})
            hashes = [digest(asset["path"]) for asset in assets]
            if len(set(hashes)) != len(hashes):
                raise RuntimeError("OpenH3-IR cannot safely distinguish identical reference files; use distinct files.")
            # The compiler owns shot headers; incoming prompt markers are prose references, not nested headers.
            intent = re.sub(r"\[Shot\s+(\d+)\]", r"Shot \1", prompt)
            if intent != prompt:
                print("OpenH3-IR: existing shot markers are passed as prose references.", flush=True)
            brief = {"intent": intent, "seconds": seconds, "aspect": aspect, "creativity": creativity,
                     "effort": "fast", "seed": int(seed if seed is not None else 7) % (2 ** 32),
                     "silent": False, "shots": "auto", "assets": assets, "transcripts": {}}
            request = {"comfy_root": self.root, "brief": brief, "url": self.url, "model": "h3-refiner",
                       "model_id": panel_settings.model_family(self.model_id), "timeout": TIMEOUT}
            worker = os.path.join(PROJECT_ROOT, "core", "h3_refiner_worker.py")
            print(f"🧠 OpenH3-IR: writing a brief ({creativity})...", flush=True)
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            if panel_settings.model_family(self.model_id) == "gemma-4-12b":
                env.setdefault("H3IR_GUIDED_DECODING", "1")
            try:
                result = subprocess.run([self.python, worker], input=json.dumps(request), encoding="utf-8",
                                        capture_output=True, timeout=TIMEOUT,
                                        env=env,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except subprocess.TimeoutExpired as e:
                raise RuntimeError("OpenH3-IR timed out while writing the brief.") from e
            if result.returncode:
                raise RuntimeError(f"OpenH3-IR failed: {result.stderr[-4000:]}")
            try:
                body = json.loads(result.stdout)
                prompt_out, wiring, frames = body["prompt"], body["wiring"], body["frames"]
            except (ValueError, KeyError, TypeError) as e:
                raise RuntimeError(f"OpenH3-IR returned an invalid response: {result.stdout[-1000:]}") from e
            expected_frames = max(5, round(seconds * 24))
            expected_frames += (5 - expected_frames % 17) % 17
            if frames != expected_frames:
                raise RuntimeError(f"OpenH3-IR duration mismatch: {frames} frames, expected {expected_frames}.")
            expected_mode = "i2va" if first_frame else "ref2va" if assets else "t2va"
            if body.get("mode") != expected_mode:
                raise RuntimeError(f"OpenH3-IR returned {body.get('mode')!r} instead of {expected_mode}.")
            expected = []
            for kind, prefix in (("image", "ref_image"), ("video", "ref_video")):
                expected += [(f"{prefix}_{i}", hashes[assets.index(a)]) for i, a in enumerate(
                    (a for a in assets if a["kind"] == kind), 1)]
            standalone = [a for a in assets if a["kind"] == "audio" and not a.get("paired_video_path")]
            expected += [(f"ref_audio_{i}", hashes[assets.index(a)]) for i, a in enumerate(standalone, 1)]
            for i, video in enumerate(videos, 1):
                if video.get("sound"):
                    pair = next(a for a in assets if a.get("paired_video_path") == video["path"])
                    expected.append((f"ref_video_audio_{i}", hashes[assets.index(pair)]))
            actual = [(entry["wiring"], entry["sha256"]) for entry in wiring]
            if sorted(expected) != sorted(actual) or not isinstance(prompt_out, str) or not prompt_out.strip():
                raise RuntimeError("OpenH3-IR returned a brief whose reference bindings do not match the render.")
            if body.get("degraded"):
                print(f"⚠️ OpenH3-IR used its fallback: {body.get('fallback_reason')}", flush=True)
            if panel_settings.model_family(self.model_id) == "qwen3-14b" and expected_mode == "t2va":
                start = prompt_out.find("integrated_multimodal_description:")
                if start > 0:
                    print("⚠️ Removed unexpected text before the OpenH3-IR prompt sections.", flush=True)
                    prompt_out = prompt_out[start:]
            return prompt_out
