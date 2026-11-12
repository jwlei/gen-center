"""The panel's Video side: films from an image and a prompt, whose prompts you can read and change before rendering."""
import json
import os
import re
import secrets
import sys
from types import SimpleNamespace

from flask import abort, request, send_file

from core import director, h3_refiner, pills, run_form, seeds, workflow_options
from core.upscale_eta import UpscaleEta
from panel.server import (OUTCOME_FILE, read_outcome, form_options, PIPELINES, VIDEO_TIMINGS, _runs_cache, active_runs, app, busy_runs, item_images, job,
                          password_required, safe_video_path, saved_at, run_queue, saved_runs, saved_workflows, queue_form_snapshot)
from panel.shorts import VOICES
from pipelines.image import media as image_media
from pipelines.video import h3_infinite, h3_multishot, h3_prompt, media, output_metadata, paths, planner, roles
from pipelines.video.comfy import workflow_model
from pipelines.video.main import BUILT_IN
from pipelines.video.run_eta import RunEta
from core.saved_workflows import display_label, shorthand
from pipelines.video.run_state import STAGES, UPSCALED, RunState, claimed_films, films_of_runs, folder_size, list_runs, run_of_film
from pipelines.video import upscale as film_upscale

COMMAND = [sys.executable, "-m", "pipelines.video.main"]
DEFAULT_FILM_SECONDS = 30
BUILT_IN_TAKES = {"min_images": 1, "max_images": 1, "max_videos": 0, "max_audios": 0, "max_references": 1}
# The most the form offers, however many a workflow could take.
MOST_IMAGES = 20
# The most reference video and audio boxes it offers: MiniMax H3 takes 3 of each.
MOST_MEDIA = 6


def option(flags, name, default=None):
    return flags[flags.index(name) + 1] if name in flags[:-1] else default


def chosen_workflow(form):
    """What makes a run use the workflow chosen on the form, and the images it takes. Returns (env, takes, error)."""
    name = form.get("workflow")
    if not name:
        return {}, BUILT_IN_TAKES, None
    entry = next((w for w in saved_workflows() if w["name"] == name), None)
    if not entry:
        return None, None, f"ComfyUI has no saved workflow called {display_label(name)} any more."
    if "problem" in entry:
        return None, None, f"{display_label(entry['label'])} can't run: {entry['problem']}"
    return {"COMFYUI_WORKFLOW": entry["path"]}, entry["takes"], None


def clean_inputs(keep=()):
    """Images and audio whose job has finished or gone: the run keeps its own copy, so nothing needs these any more."""
    # A failed job that can go back to Pending still needs its uploads.
    jobs = run_queue.pending() + run_queue.recoverable()
    needed = {path for item in jobs for path in [*item_images(item), *(item.get("form_files") or {}).values()]} | set(keep)
    try:
        for name in os.listdir(paths.INPUTS_DIR):
            path = os.path.join(paths.INPUTS_DIR, name)
            if path not in needed:
                os.remove(path)
    except OSError:
        pass  # Only costs a little disk until the next one


def resume_argv(state, redo=None):
    argv = [*COMMAND, "--resume", state.id]
    return argv + ["--redo", str(redo)] if redo else argv


def describe_run(state):
    """A saved run, as the panel lists it."""
    parts = []
    if state.final:
        parts.append("Finished")
    elif not state.clips:
        parts.append(f"Plan ready, {len(state.shots)} shots")
    elif state.next_stage() == "Clips":
        parts.append(f"{len(state.clips)} of {len(state.shots)} clips kept")
    else:
        parts.append("Every clip is done, only stitching is left")
    parts.append(f"{folder_size(state.folder) / 2 ** 20:.0f} MB")
    return {"id": state.id, "pipeline": "video", "label": state.title or state.brief, "detail": " · ".join(parts), "when": saved_at(state.path),
            "clips": len(state.clips), "finished": bool(state.final), "outcome": read_outcome(state.folder),
            "prompt_warnings": state.prompt_warnings if state.prompt_warning_pending else [],
            "size": f"{state.width}x{state.height}",
            "estimate": RunEta(resume_argv(state), VIDEO_TIMINGS).plan()["total"]}


def build_options(form):
    """
    Turns the form's options into main.py's flags. Returns (flags, error). The image
    and prompt aren't needed for that: the estimate asks before they are filled in.
    """
    flags = []
    try:
        seconds = int(form.get("duration") or DEFAULT_FILM_SECONDS)
    except ValueError:
        return None, "Film length must be a whole number of seconds."
    if not planner.MIN_FILM_SECONDS <= seconds <= planner.MAX_FILM_SECONDS:
        return None, f"Film length must be {planner.MIN_FILM_SECONDS}-{planner.MAX_FILM_SECONDS} seconds."
    flags += ["--duration", str(seconds)]

    clip = (form.get("clip_seconds") or "").strip()
    if clip:
        match = re.fullmatch(r"(\d{1,2})-(\d{1,2})", clip)
        if not match or not 1 <= int(match.group(1)) <= int(match.group(2)) <= 60:
            return None, "Clip length must be like 5-8, in seconds."
        flags += ["--clip-seconds", clip]
    if form.get("clip_fixed"):
        if not clip or match.group(1) != match.group(2):
            return None, "A fixed clip length needs one matching clip length."
        flags.append("--fixed-clips")

    start = form.get("start") or "chain"
    if start not in ("chain", "image", "director", "multishot", "infinite"):
        return None, "Unknown start mode."
    flags += ["--start", start]
    relationship = form.get("clip_relationship") or "progressive"
    if relationship not in planner.CLIP_RELATIONSHIPS:
        return None, "Unknown clip relationship."
    flags += ["--clip-relationship", relationship]
    if start == "multishot":
        if not form.get("clip_fixed"):
            return None, "H3 Multishot needs a fixed clip length."
        try:
            steps = int(form.get("h3_multishot_steps") or 20)
        except ValueError:
            return None, "H3 Multishot steps must be a whole number from 1 to 50."
        if not 1 <= steps <= 50:
            return None, "H3 Multishot steps must be a whole number from 1 to 50."
        flags += ["--h3-multishot-steps", str(steps)]
        if form.get("h3_first_frame"):
            flags.append("--h3-first-frame")

    # One role per image from image 2, in order. The form only sends one for an image that's chosen.
    for number in range(2, MOST_IMAGES + 1):
        role = form.get(f"image_{number}_role")
        if role is None:
            break
        if role not in planner.IMAGE_ROLES:
            return None, f"Unknown role for image {number}."
        flags += ["--image-role", role]

    if (form.get("prompt_mode") or "llm") == "direct":
        # Your prompt as it is, for every clip: no LLM writes them.
        flags.append("--direct")
    else:
        llm = form.get("llm") or planner.default_llm()
        if llm not in dict(planner.LLMS):
            return None, "Unknown LLM."
        flags += ["--llm", llm]

    size = (form.get("size") or "").strip().lower()
    if size:
        if not re.fullmatch(r"\d{2,4}x\d{2,4}", size):
            return None, "Render size must look like 1280x736."
        flags += ["--size", size]

    try:
        seed = seeds.parse(form.get("seed"))
    except ValueError:
        return None, f"The seed must be a whole number from 0 to {seeds.MOST}, or empty for random."
    if seed is not None:
        flags += ["--seed", str(seed)]

    if form.get("review"):
        flags.append("--plan-only")
    if form.get("try_first"):
        flags.append("--first-only")
    try:
        mode, creativity = h3_refiner.settings(form.get("h3_enhance"), form.get("h3_creativity"))
    except ValueError as e:
        return None, str(e)
    if mode != "off":
        flags += ["--h3-enhance", mode, "--h3-creativity", creativity]
    if start == "multishot" and (form.get("try_first") or mode != "off"):
        return None, "H3 Multishot renders the whole take and does not support preview runs or OpenH3-IR."
    if start == "infinite" and mode != "off":
        return None, "H3 Infinite continuation does not support OpenH3-IR."
    return flags, None


@app.route("/api/estimate/video", methods=["POST"], endpoint="video_estimate")
@password_required
def estimate():
    """What a run with the form's current options should take. Starts nothing."""
    flags, error = build_options(request.form)
    if error:
        return {"ok": False, "error": error}
    env, takes, error = chosen_workflow(request.form)
    if error:
        return {"ok": False, "error": error}
    # The workflow's options too, as Generate sends them: steps and a turbo LoRA change the time several times over.
    chosen, problem = form_options(request.form, takes)
    if chosen and not problem:
        env = {**env, "COMFYUI_OPTIONS": json.dumps(chosen)}
    # Reviewing first only writes the prompts now, but what you're deciding on is the whole film.
    return {"ok": True, **RunEta([arg for arg in flags if arg != "--plan-only"], VIDEO_TIMINGS, env).plan()}


def queue_label(text):
    text = " ".join(text.split())
    return text if len(text) <= 80 else text[:77] + "..."


def form_uploads(files, takes):
    """The images chosen in the form's boxes (image, image_2...), in order. Returns (uploads, error)."""
    field = lambda number: "image" if number == 1 else f"image_{number}"
    filled = {name for name, upload in files.items() if upload.filename and name.startswith("image")}
    uploads = [files[field(number)] for number in range(1, len(filled) + 1) if field(number) in filled]
    if len(uploads) < len(filled):
        return None, "Fill the image boxes in order: each one adds to those before it."
    low, high = takes["min_images"], takes["max_images"]
    # Clips with room for one image still leave image 2 for the LLM.
    room = min(MOST_IMAGES, 2 if high == 1 else high)
    if len(uploads) < low:
        return None, "Choose the image the film opens on." if low == 1 else f"This workflow needs {low} images."
    if len(uploads) > room:
        return None, "This workflow makes its clips from text alone: leave the image out." if not room else f"This workflow takes at most {room} images."
    return uploads, None


def form_references(files, form, takes, images, saved_files=None):
    """
    The reference videos and audio clips chosen in the form's boxes (ref_media, ref_media_2...), saved
    to the inputs folder and sorted by what they are. Returns ([(path, role)] videos, [(path, role)] audio clips, error).
    """
    field = lambda number: "ref_media" if number == 1 else f"ref_media_{number}"
    chosen = [number for number in range(1, MOST_MEDIA + 1) if files.get(field(number)) and files[field(number)].filename]
    videos, audios = [], []
    for number in chosen:
        upload = files[field(number)]
        extension = os.path.splitext(upload.filename)[1].lower()
        path = os.path.join(paths.INPUTS_DIR, f"{secrets.token_hex(8)}{extension if re.fullmatch(r'[.][a-z0-9]{1,5}', extension) else ''}")
        os.makedirs(paths.INPUTS_DIR, exist_ok=True)
        upload.save(path)
        kind = media.media_kind(path)
        if not kind:
            os.remove(path)
            return None, None, f"Reference {number} isn't a video or audio file this can read."
        if saved_files is not None:
            saved_files[field(number)] = path
        role = form.get(f"{field(number)}_role")
        if kind == "video":
            videos.append((path, role if role in roles.VIDEO_ROLES else roles.MOTION))
        else:
            audios.append((path, role if role in roles.AUDIO_ROLES else roles.SOUND))
    error = None
    if len(videos) > takes.get("max_videos", 0):
        error = f"This workflow takes {takes.get('max_videos', 0) or 'no'} reference videos."
    elif len(audios) > takes.get("max_audios", 0):
        error = f"This workflow takes {takes.get('max_audios', 0) or 'no'} reference audio clips."
    elif images + len(videos) + len(audios) > takes.get("max_references", takes["max_images"]):
        error = f"This workflow takes {takes['max_references']} references at most, images, videos and audio together."
    if error:
        for path, _ in videos + audios:
            os.remove(path)
        return None, None, error
    return videos, audios, None


@app.route("/generate/video", methods=["POST"], endpoint="video_generate")
@password_required
def generate():
    """Starts a film, or queues it behind the one in progress."""
    flags, error = build_options(request.form)
    if error:
        return {"ok": False, "error": error}, 400
    env, takes, error = chosen_workflow(request.form)
    if error:
        return {"ok": False, "error": error}, 400
    start = option(flags, "--start")
    if start == "multishot" and not h3_multishot.supports_path(env.get("COMFYUI_WORKFLOW")):
        return {"ok": False, "error": "H3 Multishot needs a supported H3 reference-to-video workflow."}, 400
    if start == "infinite" and not h3_infinite.supports_path(env.get("COMFYUI_WORKFLOW")):
        return {"ok": False, "error": "H3 Infinite continuation needs a supported H3 reference-to-video workflow."}, 400
    if start == "director":
        try:
            with open(env.get("COMFYUI_WORKFLOW") or "", encoding="utf-8") as file:
                graph = json.load(file)
            adapted = graph.get(director.INPUTS_ID, {}).get("class_type") == director.INPUTS
        except (OSError, ValueError, AttributeError):
            adapted = False
        if not adapted:
            return {"ok": False, "error": "Motion Director chaining needs a supported H3 Director workflow."}, 400
    if option(flags, "--h3-enhance", "off") != "off" and not h3_refiner.supports_path(env.get("COMFYUI_WORKFLOW")):
        return {"ok": False, "error": "OpenH3-IR requires a supported MiniMax H3 workflow."}, 400
    size = option(flags, "--size")
    if size and env.get("COMFYUI_WORKFLOW"):
        problem = media.size_problem(workflow_model(env["COMFYUI_WORKFLOW"]), *map(int, size.split("x")))
        if problem:
            return {"ok": False, "error": problem}, 400
    chosen, error = form_options(request.form, takes)
    if error:
        return {"ok": False, "error": error}, 400
    if chosen:
        # Kept with the run, for the rest of its clips (pipelines/video/main.py).
        env = {**env, "COMFYUI_OPTIONS": json.dumps(chosen)}
    # The whole form goes with it, so the run can be opened again with every setting it had.
    env = {**env, run_form.ENV: run_form.to_env(queue_form_snapshot())}
    prompt = (request.form.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "Say what should happen in the video."}, 400
    # Your prompt as it is needs no LLM.
    llm = flags[flags.index("--llm") + 1] if "--llm" in flags else None
    if llm and not planner.llm_configured(llm):
        return {"ok": False, "error": f"{llm} has no credentials. See .env.example."}, 400

    voices = dict(VOICES)
    audio_mode = request.form.get("audio_mode") or "none"
    narration = (request.form.get("narration") or "").strip() if audio_mode == "text" else ""
    voice = request.form.get("voice") or ""
    audio_upload = request.files.get("audio_file") if audio_mode == "file" else None
    if audio_mode == "text" and not narration:
        return {"ok": False, "error": "Write the text to voice, or choose no audio."}, 400
    if audio_mode == "text" and voice not in voices:
        return {"ok": False, "error": "Unknown voice."}, 400
    if audio_mode == "file" and not (audio_upload and audio_upload.filename):
        return {"ok": False, "error": "Choose the audio file, or choose no audio."}, 400

    uploads, error = form_uploads(request.files, takes)
    if error:
        return {"ok": False, "error": error}, 400
    if start == "director" and len(uploads) != 1:
        return {"ok": False, "error": "Motion Director continuous takes need exactly one image."}, 400
    if start == "multishot" and "--h3-first-frame" in flags and not uploads:
        return {"ok": False, "error": "Choose image 1 to use it as the first frame."}, 400
    if start == "multishot" and any(name.startswith("ref_media") and upload.filename for name, upload in request.files.items()):
        return {"ok": False, "error": "H3 Multishot does not yet support reference video or audio."}, 400
    if start == "infinite" and (any(name.startswith("ref_media") and upload.filename for name, upload in request.files.items())
                                or narration or (audio_upload and audio_upload.filename)):
        return {"ok": False, "error": "H3 Infinite continuation makes its own sound: it takes no reference video, "
                                     "reference audio, narration or audio file."}, 400
    if llm == "local" and uploads and h3_refiner.local_llm_model() == "qwen3-14b":
        return {"ok": False, "error": "Qwen3 14B is text-only and cannot analyze attached images. Choose Gemma 4 in Settings."}, 400
    try:
        images = [media.load_image(upload.stream) for upload in uploads]
    except RuntimeError:
        return {"ok": False, "error": "That file isn't an image this can read."}, 400

    # One box for image 2 is the LLM's alone when the clips take one image, and doesn't count.
    references = len(images) if takes["max_images"] != 1 else min(len(images), 1)
    saved_files = {}
    ref_videos, ref_audios, error = form_references(request.files, request.form, takes, references, saved_files)
    if error:
        return {"ok": False, "error": error}, 400
    media_paths = [path for path, _ in ref_videos + ref_audios]

    audio_path = None
    if audio_upload:
        extension = os.path.splitext(audio_upload.filename)[1].lower()
        audio_path = os.path.join(paths.INPUTS_DIR, f"{secrets.token_hex(8)}{extension if re.fullmatch(r'[.][a-z0-9]{1,5}', extension) else ''}")
        os.makedirs(paths.INPUTS_DIR, exist_ok=True)
        audio_upload.save(audio_path)
    audio = media.audio_fingerprint(path=audio_path, text=narration or None, voice=voice or None)

    state = None if request.form.get("queue_edit_id") else run_to_continue(prompt, flags, env, takes, images, audio, ref_videos + ref_audios)
    if state:
        for path in ([audio_path] if audio_path else []) + media_paths:
            os.remove(path)
        if "--plan-only" in flags:
            return {"ok": True, "queued": False, "shots": state.id, "continued": state.title}
        # Options change how the rest is made, not the plan: what's paid for stays.
        state.options = json.loads(env.get("COMFYUI_OPTIONS") or "{}") or None
        state.adopt(flags, queue_form_snapshot())
        reply = queue_saved_run(state)
        return reply if isinstance(reply, tuple) else {**reply, "continued": state.title}

    # Kept in a folder of its own, under a name of our own: queued, it may wait for hours.
    clean_inputs(keep=([audio_path] if audio_path else []) + media_paths)
    image_paths = [os.path.join(paths.INPUTS_DIR, f"{secrets.token_hex(8)}.png") for _ in images]
    for image, path in zip(images, image_paths):
        media.save_input(image, path)
    saved_files.update({("image" if i == 0 else f"image_{i + 1}"): path for i, path in enumerate(image_paths)})
    if audio_path:
        saved_files["audio_file"] = audio_path

    references = [flag for path in image_paths[1:] for flag in ("--reference", path)]
    audio_flags = ["--audio", audio_path] if audio_path else ["--narration", narration, *(["--voice", voice] if voice else [])] if narration else []
    media_flags = [flag for path, role in ref_videos for flag in ("--ref-video", path, "--ref-video-role", role)]
    media_flags += [flag for path, role in ref_audios for flag in ("--ref-audio", path, "--ref-audio-role", role)]
    argv = [*COMMAND, *flags, *references, *audio_flags, *media_flags, *([] if images else ["--no-image"]), "--", *image_paths[:1], prompt]
    plan_only = "--plan-only" in flags
    seconds = int(flags[flags.index("--duration") + 1])
    length = f"{seconds}s" if seconds < 60 else f"{seconds // 60}:{seconds % 60:02d}"
    detail = ["film as long as its audio" if audio else f"{length} film", llm or "your prompt, every clip",
              *(["OpenH3-IR " + option(flags, "--h3-creativity", "balanced")] if "--h3-enhance" in flags else []),
              *(["review the prompts first"] if plan_only else [])]
    if request.form.get("workflow"):
        detail.append(request.form["workflow"].removesuffix(".json"))
    chosen_size = size or "x".join(str(side) for side in media.render_size(
        *(images[0].size if images else media.DEFAULT_SHAPE),
        media.default_area(workflow_model(env.get("COMFYUI_WORKFLOW")))))
    item = {"pipeline": "video", "label": f"1 video: {queue_label(prompt)}" if prompt else "1 video", "prompt": prompt, "detail": " · ".join(detail), "argv": argv, "env": env,
            "resolution": chosen_size,
            "image": image_paths[0] if image_paths else None, "references": image_paths[1:] + ([audio_path] if audio_path else []) + media_paths, "plan_only": plan_only, "first_only": "--first-only" in flags,
            "form": queue_form_snapshot(), "form_files": saved_files,
            "estimate": RunEta(argv, VIDEO_TIMINGS, env).plan()["total"]}
    queued = run_queue.add(item)
    if item.get("error"):
        return {"ok": False, "error": item["error"]}, 500
    return {"ok": True, "queued": queued}


def run_to_continue(prompt, flags, env, takes, images, audio=None, references=()):
    """
    The stopped run Generate should finish rather than pay for the same plan again:
    the same brief, images, references, audio, length and workflow. Anything else changes the prompts.
    """
    busy = busy_runs()
    inputs = media.inputs_fingerprint(images, [flags[i + 1] for i, flag in enumerate(flags) if flag == "--image-role"], audio, references)
    seconds, start = int(option(flags, "--duration")), option(flags, "--start")
    fixed = "--fixed-clips" in flags
    clip = option(flags, "--clip-seconds", "")
    fixed_seconds = int(clip.split("-")[0]) if fixed else None
    if fixed:
        seconds = planner.fixed_film_seconds(seconds, workflow_model(env.get("COMFYUI_WORKFLOW")), (fixed_seconds, fixed_seconds))
    for state in reversed(list_runs()):
        if (state.id not in busy and state.shots and not state.final and state.inputs == inputs and state.brief == prompt
                and (audio or state.seconds == seconds) and state.workflow == env.get("COMFYUI_WORKFLOW")
                and state.fixed_clip == fixed
                and (not fixed or all(shot["seconds"] == fixed_seconds for shot in state.shots))
                and (not option(flags, "--llm") or state.llm == option(flags, "--llm"))
                and state.h3_mode == option(flags, "--h3-enhance", "off")
                and state.h3_creativity == option(flags, "--h3-creativity", "balanced")
                and (state.connection_mode or state.start) == (start if start in ("director", "multishot", "infinite") or takes["max_images"] == 1 else "image")
                and (start != "multishot" or (state.h3_first_frame == ("--h3-first-frame" in flags)
                     and state.h3_multishot_steps == int(option(flags, "--h3-multishot-steps", 20))))):
            return state
    return None


def edit_continuation(state, form):
    """
    A queued run's new settings, its prompts kept: the size (a new one makes its clips again) and the workflow's
    options. form is the run's form with the changed fields in it. Returns what's wrong, or None.
    """
    flags, error = build_options(form)
    if error:
        return error
    env, takes, error = chosen_workflow(form)
    if error:
        return error
    size = option(flags, "--size")
    if size and env.get("COMFYUI_WORKFLOW"):
        problem = media.size_problem(workflow_model(env["COMFYUI_WORKFLOW"]), *map(int, size.split("x")))
        if problem:
            return problem
    chosen, error = form_options(form, takes)
    if error:
        return error
    state.options = chosen or None
    state.adopt(flags, {name: form.getlist(name) for name in form})
    return None


def queue_saved_run(state, redo=None):
    if state.prompt_warning_pending and not request.args.get("later"):
        state.approve_prompts()
    argv = resume_argv(state, redo)
    what = f"Redo from shot {redo}" if redo else "Continue"
    item = {"pipeline": "video", "label": queue_label(state.title or state.brief), "detail": what, "argv": argv, "env": {},
            "resume": state.id, "estimate": RunEta(argv, VIDEO_TIMINGS).plan()["total"]}
    queued = run_queue.add(item)
    _runs_cache["at"] = 0.0
    if item.get("error"):
        return {"ok": False, "error": item["error"]}, 500
    return {"ok": True, "queued": queued}


def load_idle_run(run_id, allow_pending=False):
    """The saved run, or the reply saying why it can't be touched now."""
    state = RunState.load(run_id)
    if not state or not state.shots:
        return None, ({"ok": False, "error": "That run is no longer saved."}, 404)
    if run_id in (active_runs() if allow_pending else busy_runs()):
        return None, ({"ok": False, "error": "That run is going or queued. Stop it or take it out of the queue first."}, 409)
    return state, None


@app.route("/runs/<run_id>")
@password_required
def run_detail(run_id):
    """A run's shots, for reading and changing its prompts."""
    state = RunState.load(run_id)
    if not state or not state.shots:
        return {"ok": False, "error": "That run is no longer saved."}, 404
    with run_queue.lock:
        busy = run_id in active_runs()
        pending = not busy and run_id in busy_runs()
    return {"ok": True, "id": state.id, "title": state.title, "brief": state.brief, "start": state.start,
            "llm": state.llm, "direct": state.direct, "size": f"{state.width}x{state.height}",
            "h3_mode": state.h3_mode,
            "busy": busy, "pending": pending, "finished": bool(state.final),
            "take_rendered": bool(state.take_file), "settings": settings_of(state),
            "prompt_warnings": state.prompt_warnings if state.prompt_warning_pending else [],
            "shots": [{"title": shot["title"], "seconds": shot["seconds"], "prompt": shot["prompt"],
                       "enhanced_prompt": shot.get("enhanced_prompt"),
                       "enhancer_prompt": shot.get("enhancer_prompt", shot.get("enhanced_prompt")),
                       "planner_prompt": shot.get("planner_prompt"),
                       "comfy_prompt": shot.get("comfy_prompt"),
                       "workflow_enhanced_prompt": shot.get("workflow_enhanced_prompt"),
                       "seed": shot.get("seed"), "used_seed": shot.get("used_seed"),
                       "rendered": i in state.clips or (state.start == "multishot" and bool(state.take_file))}
                      for i, shot in enumerate(state.shots)]}


def run_inputs(state):
    """The files a film was given, by kind: its images, reference videos and audio clips, and its own audio track."""
    return {"image": [path for path in state.image_paths if os.path.exists(path)],
            "video": [state.reference_path(video) for video in state.ref_videos],
            "audio": [state.reference_path(audio) for audio in state.ref_audios],
            "track": [state.audio_path] if state.has_audio and os.path.exists(state.audio_path) else []}


def settings_of(state):
    """What a film was made with, as the form sets it: for "the same again", to change before pressing Generate."""
    workflow = next((w["name"] for w in saved_workflows() if state.workflow and w.get("path") and os.path.abspath(w["path"]) == os.path.abspath(state.workflow)), "")
    files = run_inputs(state)
    return {"prompt": state.brief, "seconds": state.seconds, "start": state.connection_mode or state.start, "llm": state.llm, "workflow": workflow,
            "size": f"{state.width}x{state.height}", "options": state.options or {}, "images": len(files["image"]),
            "h3_enhance": state.h3_mode, "h3_creativity": state.h3_creativity, "image_roles": state.image_roles,
            "h3_first_frame": state.h3_first_frame, "h3_multishot_steps": state.h3_multishot_steps,
            "clip_fixed": state.fixed_clip, "clip_seconds": state.shots[0]["seconds"] if state.fixed_clip and state.shots else None,
            "references": [{"kind": "video", "role": video["role"]} for video in state.ref_videos]
                          + [{"kind": "audio", "role": audio["role"]} for audio in state.ref_audios],
            "track": bool(files["track"]),
            "prompt_mode": "direct" if state.direct else "llm", "seed": state.seed,
            "clip_range": state.clip_seconds, "h3_model": state.h3_model,
            "review": state.plan_only, "try_first": state.first_only,
            "clip_relationship": state.clip_relationship,
            # The form as it was sent: anything above that it doesn't hold comes from the run itself.
            "form": run_form.flat(state.form)}


@app.route("/runs/<run_id>/inputs/<kind>/<int:number>")
@password_required
def run_input(run_id, kind, number):
    """A file a film was given, for making it again."""
    state = RunState.load(run_id)
    found = run_inputs(state).get(kind, []) if state else []
    if not 1 <= number <= len(found) or not os.path.exists(found[number - 1]):
        abort(404)
    return send_file(found[number - 1], conditional=True)


@app.route("/runs/<run_id>/image")
@password_required
def run_image(run_id):
    state = RunState.load(run_id)
    if not state or not os.path.exists(state.image_path):
        abort(404)
    # Only ever a film's small cover; the full start image is never needed by the lists.
    small = os.path.join(state.folder, "thumbnails", "input.jpg")
    try:
        return send_file(image_media.thumbnail(state.image_path, small), mimetype="image/jpeg", max_age=3600)
    except OSError:
        abort(404)


@app.route("/runs/<run_id>/clips/<int:shot>")
@password_required
def run_clip(run_id, shot):
    state = RunState.load(run_id)
    if not state or not 1 <= shot <= len(state.shots or []):
        abort(404)
    if state.start == "multishot" and state.take_file:
        source = os.path.join(state.parts_dir, state.take_file)
        preview = os.path.join(state.parts_dir, f"preview_shot_{shot}.mp4")
        if not os.path.exists(preview) or os.path.getmtime(preview) < os.path.getmtime(source):
            temporary = os.path.join(state.parts_dir, f"preview_{secrets.token_hex(8)}.mp4")
            frames = h3_prompt.clip_frames(state.shots[0]["seconds"])
            try:
                media.video_slice(source, (shot - 1) * (frames - 1) / h3_prompt.FPS, frames / h3_prompt.FPS, temporary)
                os.replace(temporary, preview)
            except (RuntimeError, OSError) as error:
                app.logger.error("Could not preview clip %s of %s: %s", shot, run_id, error)
                abort(500, description="Could not extract this clip preview.")
            finally:
                if os.path.exists(temporary):
                    os.remove(temporary)
        return send_file(preview, mimetype="video/mp4", conditional=True)
    if shot - 1 not in state.clips:
        abort(404)
    return send_file(state.clip_path(shot - 1), mimetype="video/mp4", conditional=True)


@app.route("/runs/<run_id>/shots", methods=["POST"])
@password_required
def save_shots(run_id):
    """Saves changed prompts. A clip already rendered stays as it is until you redo it."""
    with run_queue.lock:
        state, refused = load_idle_run(run_id, allow_pending=True)
        if refused:
            return refused
        body = request.get_json(silent=True) or {}
        prompts = body.get("prompts")
        if not isinstance(prompts, list) or len(prompts) != len(state.shots) or not all(isinstance(p, str) and p.strip() for p in prompts):
            return {"ok": False, "error": "Every shot needs a prompt."}, 400
        chosen, error = shot_seeds(body, len(state.shots))
        if error:
            return {"ok": False, "error": error}, 400
        for shot, prompt, seed in zip(state.shots, prompts, chosen):
            if shot["prompt"] != prompt.strip():
                if shot.get("enhanced_prompt"):
                    shot.setdefault("enhancer_prompt", shot["enhanced_prompt"])
                shot.pop("enhanced_prompt", None)
                shot.pop("h3_key", None)
                shot.pop("h3_reviewed", None)
            shot["prompt"] = prompt.strip()
            shot["seed"] = seed
        state.check_prompts()
        state.save()
        for item in run_queue.items:
            if item.get("resume") == state.id:
                item["prompt_warnings"] = state.prompt_warnings if state.prompt_warning_pending else []
        run_queue._save()
        _runs_cache["at"] = 0.0
    return {"ok": True}


def shot_seeds(body, count):
    """The seed set for each shot or image in the editor, None for random. Without any sent, every one is random."""
    given = body.get("seeds")
    if given is None:
        return [None] * count, None
    if not isinstance(given, list) or len(given) != count:
        return None, "Every shot needs a seed, or none for random."
    try:
        return [seeds.parse(seed) for seed in given], None
    except ValueError:
        return None, f"A seed must be a whole number from 0 to {seeds.MOST}, or empty for random."


def continue_run(run_id):
    """Renders a planned or stopped run from where it got to, or queues that behind the run in progress."""
    state, refused = load_idle_run(run_id)
    return refused or queue_saved_run(state)


@app.route("/runs/<run_id>/redo/<int:shot>", methods=["POST"])
@password_required
def redo_shot(run_id, shot):
    """Renders a shot again and joins the film anew. In a chain, the shots after it start from it, so they go too."""
    state, refused = load_idle_run(run_id)
    if refused:
        return refused
    if not 1 <= shot <= len(state.shots):
        return {"ok": False, "error": "That shot isn't in this film."}, 400
    if state.start == "multishot" and shot != 1:
        return {"ok": False, "error": "H3 Multishot can only render the whole take again."}, 400
    return queue_saved_run(state, redo=shot)


def discard_run(run_id):
    """Deletes a run's plan and clips. A film already finished from it stays."""
    state, refused = load_idle_run(run_id)
    if refused:
        return refused
    preserve_upscales(run_id)
    state.remove()
    _runs_cache["at"] = 0.0
    return {"ok": True}


UPSCALE = [sys.executable, "-m", "pipelines.video.upscale"]


@app.route("/films/<name>/upscale", methods=["POST"])
@password_required
def upscale_film(name):
    """Queues a finished film to be made bigger with NVIDIA RTX VSR, as a new film beside it."""
    path = safe_video_path("video", name)
    if request.args.get("method") == "latent":
        return latent_upscale_film(name, path)
    try:
        scale = float(request.args.get("scale") or 2)
    except ValueError:
        return {"ok": False, "error": "Scale is a number from 1 to 4."}, 400
    quality = request.args.get("quality") or film_upscale.DEFAULT_QUALITY
    if not 1 <= scale <= 4 or quality not in film_upscale.QUALITIES:
        return {"ok": False, "error": "Unknown scale or quality."}, 400
    argv = [*UPSCALE, "--film", name, "--scale", f"{scale:g}", "--quality", quality]
    item = {"pipeline": "video", "label": queue_label(f"Upscale: {name}"), "detail": f"RTX VSR, {scale:g}x, {quality}",
            "argv": argv, "env": {}, "estimate": UpscaleEta(argv, VIDEO_TIMINGS).plan()["total"]}
    queued = run_queue.add(item)
    _runs_cache["at"] = 0.0
    if item.get("error"):
        return {"ok": False, "error": item["error"]}, 500
    return {"ok": True, "queued": queued}


LATENT_SUFFIX = "_latent"
# What a run copies to its copy: its inputs. Its clips, the stitching and its state are its own.
NOT_COPIED = ("clips", "parts", "state.json")


def latent_used(state):
    """The latent upscale a film was made with, for the gallery's "Upscaled:" line, or None."""
    return pills.latent_description(state.options if state else None)


def offers_latent_upscale(workflow):
    """Whether the workflow, as last listed, has the H3 latent upscaler among its options."""
    if not workflow:
        return False
    try:
        with open(os.path.splitext(workflow)[0] + ".map.json", "r", encoding="utf-8") as f:
            return any(option.get("id") == "latent_upscale" for option in json.load(f).get("_options") or [])
    except (OSError, ValueError, AttributeError):
        return False


def latent_copy(state, preset, megapixels):
    """
    A copy of a finished run to make again with the latent upscaler: the same prompts, each clip on the seed it was made
    with, so it comes out the same, then bigger. The copy is a run of its own, its film named after the original's.
    """
    import shutil
    from datetime import datetime, timedelta
    from core.saved_workflows import unique_name

    copy = RunState(**{name: getattr(state, name) for name in RunState.__dataclass_fields__})
    when = datetime.now()
    while True:
        copy.id = f"run_{when:%Y%m%d_%H%M%S}"
        if not os.path.exists(copy.folder):
            break
        when += timedelta(seconds=1)
    shots = []
    for shot in state.shots:
        made = {**shot, "seed": shot.get("used_seed", shot.get("seed"))}
        made.pop("used_seed", None)
        shots.append(made)
    base = state.film_name or os.path.splitext(os.path.basename(state.final or state.id))[0]
    copy.shots, copy.clips, copy.final, copy.take_file = shots, {}, None, None
    # Not only the films made: one queued before it has its name already, and would be written over.
    copy.film_name = unique_name(paths.OUTPUT_DIR, base + LATENT_SUFFIX, ".mp4", claimed_films(copy.id))
    copy.options = {**(state.options or {}), "latent_upscale": preset, "latent_upscale_mp": f"{megapixels:g}"}
    copy.plan_only = copy.first_only = False
    copy.inputs = None  # Generate never takes it for the original run to continue
    os.makedirs(copy.folder)
    for name in os.listdir(state.folder):
        source = os.path.join(state.folder, name)
        if name not in NOT_COPIED and name != OUTCOME_FILE and os.path.isfile(source):
            shutil.copy2(source, os.path.join(copy.folder, name))
    copy.save()
    return copy


def latent_upscale_film(name, path):
    """Queues a film to be made again at its size, then latent-upscaled: a new film beside it."""
    from core.workflow_options import LATENT_UPSCALES, UPSCALE_MEGAPIXELS
    state = RunState.load(run_of_film(name)) if not UPSCALED.search(name) else None
    if not state or not state.shots or not state.final:
        return {"ok": False, "error": "Only a finished film whose run is still saved can be latent-upscaled."}, 409
    if (state.connection_mode or state.start) in ("director", "multishot", "infinite") or not offers_latent_upscale(state.workflow):
        return {"ok": False, "error": "Latent upscale needs a film made with an H3 reference-to-video workflow that offers it. "
                                      "Restart ComfyUI after installing the upscaler, then open the panel to list the workflows again."}, 400
    preset = request.args.get("preset") or "Hires fix"
    try:
        megapixels = float(request.args.get("mp") or UPSCALE_MEGAPIXELS[2])
    except ValueError:
        return {"ok": False, "error": "Megapixels is a number."}, 400
    least, most, _ = UPSCALE_MEGAPIXELS
    if preset not in LATENT_UPSCALES or not least <= megapixels <= most:
        return {"ok": False, "error": f"Choose Clean, Hires fix or Heavy, and {least:g} to {most:g} megapixels."}, 400
    if megapixels * 1e6 <= state.width * state.height:
        return {"ok": False, "error": f"It is {state.width}x{state.height} already: choose more megapixels than that."}, 400
    copy = latent_copy(state, preset, megapixels)
    argv = resume_argv(copy)
    item = {"pipeline": "video", "label": queue_label(f"Latent upscale: {name}"), "detail": f"Latent upscale, {preset}, {megapixels:g} MP",
            "argv": argv, "env": {}, "resume": copy.id, "new_run": True, "resolution": f"{state.width}x{state.height}",
            "estimate": RunEta(argv, VIDEO_TIMINGS).plan()["total"]}
    queued = run_queue.add(item)
    _runs_cache["at"] = 0.0
    if item.get("error"):
        copy.remove()
        return {"ok": False, "error": item["error"]}, 500
    return {"ok": True, "queued": queued}


def delete_video(folder, path):
    """Deletes a film and the run that made it, whose clips would otherwise sit on the disk unseen. An upscaled copy is only itself."""
    if UPSCALED.search(os.path.basename(path)):
        preserve_upscales(source_name=os.path.basename(path))
        os.remove(path)
        metadata_path = output_metadata.sidecar(path)
        if os.path.exists(metadata_path):
            os.remove(metadata_path)
        return {"ok": True}
    run_id = run_of_film(os.path.basename(path))
    if run_id and run_id in busy_runs():
        return {"ok": False, "error": "That film's run is going or queued. Stop it or take it out of the queue first."}, 409
    preserve_upscales(run_id=run_id, source_name=os.path.basename(path))
    os.remove(path)
    state = RunState.load(run_id)
    if state:
        state.remove()
    # H3 Infinite kept the run's clips in ComfyUI's output folder, to continue and redo it from: they go with it.
    from core import comfy_files
    comfy_files.forget_h3_run(run_id)
    _runs_cache["at"] = 0.0
    return {"ok": True}


def preserve_upscales(run_id=None, source_name=None):
    films = films_of_runs()
    if not os.path.isdir(paths.OUTPUT_DIR):
        return
    for name in os.listdir(paths.OUTPUT_DIR):
        ancestor = name
        is_descendant = False
        while UPSCALED.search(ancestor):
            ancestor = UPSCALED.sub(".mp4", ancestor)
            if ancestor == source_name:
                is_descendant = True
                break
        if UPSCALED.search(name) and (is_descendant or (run_id and run_of_film(name, films) == run_id)):
            path = os.path.join(paths.OUTPUT_DIR, name)
            if output_metadata.read(path) is None:
                metadata = output_metadata.resolve(path, films)
                if metadata is not None:
                    output_metadata.write(path, metadata)


def with_facts(caption, brief):
    """A film's caption, with what Output's pills are made from (core/pills.py): list_videos turns them into pills."""
    caption["_facts"] = pills.facts(caption["model"], caption["upscaled"], caption["connection"], caption["h3_mode"],
                                    caption["h3_creativity"], caption["loras"], caption["llm"], caption.pop("_direct", False),
                                    caption.pop("_sampling", None), caption.pop("_cfg", None))
    caption["_sibling"] = pills.sibling_key("video", brief)
    return caption


def captions():
    titles = {run["id"]: run["label"] for run in saved_runs() if run["pipeline"] == "video"}
    films = films_of_runs()
    runs = {state.id: state for state in films.values()}

    def caption(name):
        path = os.path.join(paths.OUTPUT_DIR, name)
        if UPSCALED.search(name):
            try:
                metadata = output_metadata.read(path)
                if metadata is None:
                    metadata = output_metadata.resolve(path, films)
                    if metadata is not None:
                        output_metadata.write(path, metadata)
                if metadata is not None:
                    return with_facts({**{key: metadata.get(key) for key in ("title", "model", "llm", "h3_mode", "h3_creativity", "connection")},
                                       "loras": metadata.get("loras", []), "upscaled": "RTX VSR", "_direct": bool(metadata.get("direct")),
                                       "run": metadata.get("origin_run") if metadata.get("origin_run") in titles else None},
                                      metadata.get("brief"))
            except (OSError, ValueError) as error:
                app.logger.warning("Could not preserve video metadata for %s: %s", name, error)
        run = run_of_film(name, films)
        made_by = films.get(name) or runs.get(run)
        return with_facts({"run": run if run in titles else None, "title": titles.get(run),
                           "_direct": bool(made_by and made_by.direct),
                "model": shorthand(made_by.workflow, BUILT_IN) if made_by else None,
                "llm": made_by.llm if made_by else None,
                "h3_mode": made_by.h3_mode if made_by else None,
                "h3_creativity": made_by.h3_creativity if made_by else None,
                # How its clips connect: chain, image, director, multishot or infinite.
                "connection": (made_by.connection_mode or made_by.start) if made_by else None,
                "loras": workflow_options.loras_used(made_by.workflow, made_by.options, "video") if made_by else [],
                "_sampling": workflow_options.sampling_used(made_by.workflow, made_by.options, "video") if made_by else None,
                "_cfg": workflow_options.cfg_used(made_by.workflow, made_by.options, "video") if made_by else None,
                "upscaled": "RTX VSR" if UPSCALED.search(name) else latent_used(made_by),
                # The viewer's Latent upscale: greyed out where it can't be used (see latent_upscale_film).
                "latent": bool(made_by and made_by.final and not UPSCALED.search(name)
                               and (made_by.connection_mode or made_by.start) not in ("director", "multishot", "infinite")
                               and offers(made_by.workflow))}, made_by.brief if made_by else None)
    offered = {}

    def offers(workflow):
        if workflow not in offered:
            offered[workflow] = offers_latent_upscale(workflow)
        return offered[workflow]
    return caption


def context():
    return {
        "stages": STAGES,
        "llms": [{"name": name, "label": label, "ready": planner.llm_configured(name)} for name, label in planner.LLMS if name != "claude"],
        "default_llm": "local",
        "film_limits": [planner.MIN_FILM_SECONDS, planner.MAX_FILM_SECONDS, DEFAULT_FILM_SECONDS],
        "most_images": MOST_IMAGES,
        "most_media": MOST_MEDIA,
        "video_roles": [[role, roles.VIDEO_LABELS[role]] for role in roles.VIDEO_ROLES],
        "audio_roles": [[role, roles.AUDIO_LABELS[role]] for role in roles.AUDIO_ROLES],
        "clip_seconds": planner.clip_seconds(workflow_model()),
        "size_presets": media.SIZE_PRESETS[::-1],
    }


PIPELINES["video"] = SimpleNamespace(
    load_run=RunState.load, describe_runs=lambda: [describe_run(state) for state in list_runs() if state.shots], continue_run=continue_run,
    discard_run=discard_run, delete_video=delete_video, captions=captions, context=context,
    resume_argv=resume_argv, edit_continuation=edit_continuation,
    estimate=lambda argv, env: RunEta(argv, VIDEO_TIMINGS, env).plan()["total"])
