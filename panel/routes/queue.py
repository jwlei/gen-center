"""Stopping, skipping and continuing runs, and the queue: its order, its lanes, editing a queued job."""
import json
import math
import os
import secrets
import shutil
import stat
import threading
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import NotFound

from flask import Blueprint, abort, request, send_file

from panel import server

bp = Blueprint("queue", __name__)


@bp.route("/runs/<run_id>/continue", methods=["POST"])
@server.password_required
def continue_run(run_id):
    """Starts a stopped run again from where it got to, or queues that behind the run in progress."""
    return server.run_pipeline(run_id).continue_run(run_id)


@bp.route("/runs/<run_id>/discard", methods=["POST"])
@server.password_required
def discard_run(run_id):
    return server.run_pipeline(run_id).discard_run(run_id)


@bp.route("/runs/<run_id>/discard-unreadable", methods=["POST"])
@server.password_required
def discard_unreadable_run(run_id):
    """Delete only an identified, still-unreadable and idle run folder."""
    with server.run_queue.lock:
        target = next((target for error in server.catalogue_errors()
                       if (target := server.checkpoint_target(error)) and target[1] == run_id), None)
        if not target:
            return {"ok": False, "error": "That unreadable run is no longer listed. Refresh and try again."}, 404
        side, _, folder = target
        if run_id in server.busy_runs():
            return {"ok": False, "error": "That run is going or queued. Stop it or remove it from the queue first."}, 409
        try:
            info = os.lstat(folder)
            if (os.path.islink(folder) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                    or os.path.normcase(os.path.dirname(os.path.realpath(folder))) != os.path.normcase(os.path.realpath(os.path.dirname(folder)))):
                return {"ok": False, "error": "The run folder is a link or has moved; delete it manually after checking its location."}, 409
            try:
                server.PIPELINES[side].load_run(run_id)
            except server.CheckpointError:
                pass
            else:
                return {"ok": False, "error": "The checkpoint is no longer unreadable. Refresh before deleting."}, 409
            shutil.rmtree(folder)
        except OSError as error:
            server.app.logger.error("Could not delete unreadable run %s: %s", folder, error)
            return {"ok": False, "error": f"Could not delete the run folder: {error}"}, 500
        server._runs_cache["at"] = 0.0
    return {"ok": True}


@bp.route("/stop", methods=["POST"])
@server.password_required
def stop():
    server._cancelling["started_at"] = None  # Stop is all of it: a Cancel waiting to happen goes with it
    return {"ok": server.stop_run(), "error": server.STOP_FAILED if server.job.running else None}


# Held by Stop after this one, so taking it back lets the queue go on again; held before stays held.
_held_for_stop_after = False


@bp.route("/stop-after", methods=["POST"])
@server.password_required
def stop_after():
    """
    Stop after this one: a batch ends once the video or image it's making now is done, and what is queued after it
    waits for Resume, as with Stop. Asked again, it takes that back. A film is one video, so it has nothing to stop.
    """
    global _held_for_stop_after
    if not server.job.running:
        return {"ok": False, "error": "Nothing is running."}, 409
    if server.job.pipeline == "video":
        return {"ok": False, "error": "A film is one video, so there is no batch to stop after it: use Stop or Skip."}, 409
    if server.batch_stop.requested():
        server.batch_stop.clear()
        server.job.log("▶️ The batch goes on: Stop after this one taken back.")
        if _held_for_stop_after:
            server.run_queue.resume()
        _held_for_stop_after = False
        return {"ok": True, "stop_after": False}
    _held_for_stop_after = not server.run_queue.held and bool(server.run_queue.items)
    server.batch_stop.request()
    server.run_queue.hold()
    server.job.log("⏸️ The batch stops once the one being made now is done.")
    return {"ok": True, "stop_after": True}


@bp.route("/skip", methods=["POST"])
@server.password_required
def skip():
    """
    Cancels the running job: it stops and rejoins the queue at the bottom, and the next in the queue starts if the
    queue is going. One with nothing saved yet to continue from stops as soon as it has.
    """
    server._runs_cache["at"] = 0.0
    if not server.job.running:
        return {"ok": True, "cancelling": False}
    if server.run_saved():
        stopped = server.cancel_now()
        return {"ok": stopped, "error": server.STOP_FAILED if server.job.running and not stopped else None}
    started_at = server.job.started_at
    if server._cancelling["started_at"] != started_at:
        server._cancelling["started_at"] = started_at
        server.job.log("⏭️ Cancelling once its plan is saved: then the next in the queue starts.")
        threading.Thread(target=server._cancel_when_saved, args=(started_at,), daemon=True).start()
    return {"ok": True, "cancelling": True}


@bp.route("/publish/stop", methods=["POST"])
@server.password_required
def stop_upload():
    if server.uploads.running:
        server.upload_queue.hold()
    return {"ok": server.uploads.stop(), "error": server.STOP_FAILED if server.uploads.running else None}


@bp.route("/queue/<lane>/remove/<int:item_id>", methods=["POST"])
@server.password_required
def queue_remove(lane, item_id):
    """
    Trash deletes, wherever it is tapped. A stopped or paused run queued to continue goes with what it still had to
    do, as Pending's trash does: taken out of the queue alone, it showed up under Pending, to be deleted a second time.
    What it made stays. A redo or an upscale only works on its run, so the run is left as it is.
    """
    if lane not in server.QUEUES:
        abort(404)
    queue = server.QUEUES[lane]
    with queue.lock:
        item = next((item for item in queue.items if item["id"] == item_id), None)
        continues = queue is server.run_queue and item and item.get("resume") and item.get("pipeline") in server.PIPELINES \
            and "--redo" not in (item.get("argv") or []) and not server.upscale_queue_settings(item)
        if not queue.remove(item_id):
            return {"ok": False}
        if continues and item["resume"] not in server.busy_runs():
            reply = server.PIPELINES[item["pipeline"]].discard_run(item["resume"])
            if isinstance(reply, tuple):  # Gone already, say: the job is out of the queue all the same
                server.app.logger.warning("Removed %s from the queue, but could not discard its run: %s", item["resume"], reply[0].get("error"))
    return {"ok": True}


@bp.route("/queue/finished/clear", methods=["POST"])
@server.password_required
def clear_finished():
    """Clears only the jobs the page showed; hidden or newly finished jobs stay."""
    selected = request.get_json(silent=True)
    if not isinstance(selected, dict) or set(selected) != set(server.QUEUES):
        return {"ok": False, "error": "Say which run and upload results to clear."}, 400
    if any(not isinstance(ids, list) or any(type(job_id) is not int for job_id in ids)
           for ids in selected.values()):
        return {"ok": False, "error": "Finished results are lists of job ids."}, 400
    for lane, queue in server.QUEUES.items():
        queue.clear_results(set(selected[lane]))
    return {"ok": True}


@bp.route("/queue/<lane>/finished/<int:job_id>/forget", methods=["POST"])
@server.password_required
def queue_forget_result(lane, job_id):
    if lane not in server.QUEUES:
        abort(404)
    return {"ok": server.QUEUES[lane].forget_result(job_id)}


@bp.route("/queue/<lane>/failed/<int:job_id>/dismiss", methods=["POST"])
@server.password_required
def queue_dismiss_failure(lane, job_id):
    if lane not in server.QUEUES:
        abort(404)
    return {"ok": server.QUEUES[lane].dismiss_failure(job_id)}


@bp.route("/queue/<lane>/failed/<int:job_id>/requeue", methods=["POST"])
@server.password_required
def queue_requeue_failure(lane, job_id):
    """A failed job with no saved run, back in Pending with its settings."""
    if lane != "run":
        abort(404)
    item_id = server.run_queue.requeue_failure(job_id)
    if item_id is None:
        return {"ok": False, "error": "That failure is gone, or its settings were not kept."}, 404
    return {"ok": True, "id": item_id}


@bp.route("/queue/<lane>/start/<int:item_id>", methods=["POST"])
@server.password_required
def queue_start(lane, item_id):
    if lane not in server.QUEUES:
        abort(404)
    return {"ok": server.QUEUES[lane].start(item_id, top=bool(request.args.get("top")))}


@bp.route("/queue/<lane>/pause/<int:item_id>", methods=["POST"])
@server.password_required
def queue_pause(lane, item_id):
    if lane not in server.QUEUES:
        abort(404)
    return {"ok": server.QUEUES[lane].pause(item_id)}


def legacy_queue_form(item):
    """Reconstruct forms for generation jobs saved before form snapshots were kept."""
    argv, env = item.get("argv") or [], item.get("env") or {}
    pipeline = item.get("pipeline")
    if pipeline not in ("video", "image") or "--resume" in argv or not any(
        name in argv for name in ("pipelines.video.main", "pipelines.image.main")
    ):
        return None
    flag = lambda name, default="": argv[argv.index(name) + 1] if name in argv[:-1] else default
    workflow = next((w["name"] for w in server.saved_workflows() if env.get("COMFYUI_WORKFLOW") and w.get("path")
                     and os.path.normcase(os.path.abspath(w["path"])) == os.path.normcase(os.path.abspath(env["COMFYUI_WORKFLOW"]))), "")
    if env.get("COMFYUI_WORKFLOW") and not workflow:
        return None
    form = {"workflow": workflow, "prompt": item.get("prompt") or "", "seed": flag("--seed"),
            "prompt_mode": "direct" if "--direct" in argv else "llm", "llm": flag("--llm"),
            "size": flag("--size"), "review": "1" if "--plan-only" in argv or "--enhance-only" in argv else "",
            "try_first": "1" if "--first-only" in argv else ""}
    files = {}
    if pipeline == "video":
        form.update(duration=flag("--duration", "120"), clip_seconds=flag("--clip-seconds"), start=flag("--start", "chain"),
                    h3_enhance=flag("--h3-enhance", "off"), h3_creativity=flag("--h3-creativity", "balanced"),
                    audio_mode="file" if "--audio" in argv else "text" if "--narration" in argv else "none",
                    narration=flag("--narration"), voice=flag("--voice"))
        if "--fixed-clips" in argv:
            form["clip_fixed"] = "1"
        images = ([item["image"]] if item.get("image") else []) + [
            argv[i + 1] for i, value in enumerate(argv[:-1]) if value == "--reference"]
        for i, path in enumerate(images):
            files["image" if not i else f"image_{i + 1}"] = path
        image_roles = [argv[i + 1] for i, value in enumerate(argv[:-1]) if value == "--image-role"]
        form.update({f"image_{i + 2}_role": role for i, role in enumerate(image_roles)})
        if flag("--audio"):
            files["audio_file"] = flag("--audio")
        for kind in ("video", "audio"):
            for i, value in enumerate(argv[:-1]):
                if value == f"--ref-{kind}":
                    number = sum(name.startswith("ref_media") for name in files) + 1
                    name = "ref_media" if number == 1 else f"ref_media_{number}"
                    files[name] = argv[i + 1]
                    if i + 3 < len(argv) and argv[i + 2] == f"--ref-{kind}-role":
                        form[name + "_role"] = argv[i + 3]
        options = json.loads(env.get("COMFYUI_OPTIONS") or "{}")
    else:
        if "--areas" in argv:
            return None
        form.update(count=flag("--count", "1"), image_mode="compose" if "--compose" in argv else "expand" if "--expand" in argv else "edit",
                    aspect=flag("--aspect"), megapixels=flag("--megapixels"), detail=flag("--reference-detail"),
                    transparent="1" if "--transparent" in argv else "")
        for i, path in enumerate(argv[index + 1] for index, value in enumerate(argv[:-1]) if value == "--image"):
            files["image" if not i else f"image_{i + 1}"] = path
        options = dict(argv[i + 1].split("=", 1) for i, value in enumerate(argv[:-1]) if value == "--option" and "=" in argv[i + 1])
        if "--expand" in argv:
            for side, value in zip(("left", "top", "right", "bottom"), flag("--expand").split(",")):
                form[f"expand_{side}"] = value
            form["expand_units"] = "pixels"
    return form, files, options


@bp.route("/queue/run/edit/<int:item_id>", methods=["POST"])
@server.password_required
def queue_edit(item_id):
    with server.run_queue.lock:
        item = next((entry for entry in server.run_queue.items if entry["id"] == item_id), None)
        if not item:
            return {"ok": False, "error": "That job has already started or is no longer queued."}, 409
        upscale = server.upscale_queue_settings(item)
        continued = continued_setup(item) if item.get("resume") and not upscale else None
        if continued:
            # Its prompts are written: the setup opens as it was, to change how the rest is made, not what.
            item["edit_from_queue"] = not item.get("later")
            item["later"] = True
            item["edit_token"] = secrets.token_urlsafe(24)
            server.run_queue._save()
            return {"ok": True, "id": item_id, "token": item["edit_token"], "pipeline": item.get("pipeline"),
                    "form": continued["form"], "files": [], "filenames": {}, "options": {}, "continued": continued["run"]}
        if item.get("resume") and not upscale:
            return {"ok": False, "error": "Setup for a continued run cannot be edited here. The job was not changed."}, 409
        if upscale:
            # Where it was, Queue or Pending, so Cancel puts it back there.
            item["edit_from_queue"] = not item.get("later")
            item["later"] = True
            item["edit_token"] = secrets.token_urlsafe(24)
            server.run_queue._save()
            return {"ok": True, "id": item_id, "token": item["edit_token"], "pipeline": item.get("pipeline"),
                    "upscale": {**upscale, "size": server.upscale_source_size(item)}}
        restored = (item["form"], item.get("form_files", {}), {}) if item.get("form") else legacy_queue_form(item)
        if not restored:
            return {"ok": False, "error": "Setup is unavailable for this job. It remains in the queue unchanged."}, 409
        form, files, options = restored
        missing = [name for name, path in files.items() if not os.path.isfile(path)]
        if missing:
            return {"ok": False, "error": "A queued input file is missing. The job was not changed."}, 409
        item["edit_from_queue"] = not item.get("later")
        item["later"] = True
        item["edit_token"] = secrets.token_urlsafe(24)
        server.run_queue._save()
        return {"ok": True, "id": item_id, "token": item["edit_token"], "pipeline": item.get("pipeline"),
                "form": form, "files": list(files), "filenames": {name: os.path.basename(path) for name, path in files.items()}, "options": options}


# What can change for a run whose prompts are written: how the rest is made. Its prompt, images, length, workflow and
# LLM made those prompts, so they stay as they were.
CONTINUED_FIELDS = ("size", "aspect", "megapixels", "try_first")
CONTINUED_PREFIXES = ("opt_", "latent_upscale")


def continued_field(name):
    return name in CONTINUED_FIELDS or name.startswith(CONTINUED_PREFIXES)


def continued_form(saved, sent):
    """The run's form as it was made, with the fields that may change taken from what was sent now."""
    merged = MultiDict()
    for name, values in (saved or {}).items():
        if not continued_field(name):
            for value in values if isinstance(values, list) else [values]:
                merged.add(name, value)
    for name in sent:
        if continued_field(name):
            for value in sent.getlist(name):
                merged.add(name, value)
    return merged


def continued_setup(item):
    """A queued continuation's run as Edit opens it: its form and prompts. None when it can't be (no form kept, a redo)."""
    if item.get("pipeline") not in ("video", "image") or "--redo" in (item.get("argv") or []):
        return None
    state = server.PIPELINES[item["pipeline"]].load_run(item["resume"])
    if not state or not state.shots or not state.form:
        return None
    form = server.run_form.flat(state.form)
    # A preview run is the job's own choice, not the run's.
    form["try_first"] = "1" if "--first-only" in (item.get("argv") or []) else ""
    return {"form": form, "run": {"id": state.id, "title": state.title or state.brief, "image": item["pipeline"] == "image",
                                  "prompts": [shot.get("prompt") or "" for shot in state.shots]}}


@bp.route("/queue/run/edit/<int:item_id>/continue", methods=["POST"])
@server.password_required
def queue_edit_continue(item_id):
    """Saves a continued run's changed setup (size, workflow options, a preview run) and puts it back in line."""
    token = request.form.get("queue_edit_token", "")
    with server.run_queue.lock:
        old = next((entry for entry in server.run_queue.items if entry["id"] == item_id), None)
        if not old or not old.get("edit_token") or not secrets.compare_digest(old["edit_token"], token):
            return {"ok": False, "error": "That editing session expired. Open the queued job again."}, 409
        if not continued_setup(old):
            return {"ok": False, "error": "This job's setup cannot be edited."}, 409
        pipeline = server.PIPELINES[old["pipeline"]]
        state = pipeline.load_run(old["resume"])
        error = pipeline.edit_continuation(state, continued_form(state.form, request.form))
        if error:
            return {"ok": False, "error": error}, 400
        argv = pipeline.resume_argv(state)
        if request.form.get("try_first"):
            argv = argv + ["--first-only"]
        replacement = {**old, "argv": argv, "waited": True, "first_only": bool(request.form.get("try_first")),
                       "resolution": f"{state.width}x{state.height}",
                       # Its new size and options take another time: estimated again, as the run will be made.
                       "estimate": pipeline.estimate(argv, old.get("env") or {})}
        later, top = bool(request.form.get("start_later")), bool(request.form.get("queue_top"))
        server.run_queue.put_back_edited(old, replacement, later=later, top=top and not later)
        if not replacement.get("later"):
            server.run_queue._approve_prompt_warning(replacement)
        server.run_queue._save()
        server.run_queue._advance()
        server._runs_cache["at"] = 0.0
        return {"ok": True, "queued": replacement in server.run_queue.items, "continued": state.title or state.brief}


@bp.route("/queue/run/edit/<int:item_id>/upscale", methods=["POST"])
@server.password_required
def queue_edit_upscale(item_id):
    from panel import image as image_panel, video as video_panel
    from PIL import Image

    data = request.get_json(silent=True) or {}
    token = data.get("token")
    if not isinstance(token, str):
        return {"ok": False, "error": "That editing session expired. Open the queued job again."}, 409
    with server.run_queue.lock:
        old = next((entry for entry in server.run_queue.items if entry["id"] == item_id), None)
        if not old or not old.get("edit_token") or not secrets.compare_digest(old["edit_token"], token):
            return {"ok": False, "error": "That editing session expired. Open the queued job again."}, 409
        settings = server.upscale_queue_settings(old)
        if not settings:
            return {"ok": False, "error": "This job is not an upscale."}, 400
        argv = old["argv"]
        flag = lambda name: argv[argv.index(name) + 1] if name in argv[:-1] else None
        if settings["kind"] == "image_upscale":
            state = image_panel.RunState.load(old.get("resume"))
            position = image_panel.upscale_position(state, argv) if state else None
            if not state or not position or not position.isdigit() or not 1 <= int(position) <= len(state.shots or []):
                return {"ok": False, "error": "The original image is no longer available."}, 409
            shot = state.shots[int(position) - 1]
            if not shot.get("file"):
                return {"ok": False, "error": "The original image is no longer available."}, 409
            try:
                with Image.open(state.image_path(shot)) as source:
                    size = source.size
                    shorter = min(size)
            except OSError:
                return {"ok": False, "error": "The original image could not be read."}, 409
            method = data.get("method")
            try:
                strength = float(data.get("strength", 1))
                resolution = int(data.get("resolution", 0))
            except (TypeError, ValueError):
                return {"ok": False, "error": "Choose a valid strength and resolution."}, 400
            if method not in image_panel.UPSCALE_METHODS or not math.isfinite(strength) or not 0 <= strength <= 1:
                return {"ok": False, "error": "Choose a valid upscale method and strength."}, 400
            problem = image_panel.upscale_problem(method, *size)
            if problem:
                return {"ok": False, "error": problem}, 400
            # A resolution offered, or what 2x, 3x or 4x made it (its shorter side times over, within SeedVR2's most).
            if (method == "seedvr2" and resolution and
                    ((resolution not in image_panel.UPSCALE_RESOLUTIONS and resolution > image_panel.SEEDVR2_MOST_EDGE)
                     or resolution <= shorter)):
                return {"ok": False, "error": "Choose a supported resolution larger than the original image."}, 400
            # 2x, 3x or 4x, as the upscale box says it: its shorter side that many times, within SeedVR2's most.
            times = data.get("times")
            if method == "seedvr2" and times:
                if str(times) not in tuple(str(n) for n in image_panel.UPSCALE_SCALES):
                    return {"ok": False, "error": "SeedVR2 makes it 2, 3 or 4 times its size."}, 400
                resolution = min(image_panel.SEEDVR2_MOST_EDGE, int(times) * shorter)
            if method != "seedvr2":
                resolution = 0
            denoise = None
            if method == "seedvr2":
                try:
                    denoise = image_panel.seedvr2_denoise(data.get("denoise")) or None
                except ValueError as e:
                    return {"ok": False, "error": str(e)}, 400
            if method in image_panel.REFINE_UPSCALES:
                try:
                    denoise = float(data.get("denoise") or 0.3)
                except (TypeError, ValueError):
                    return {"ok": False, "error": "Denoise is a number from 0.05 to 1."}, 400
                if not math.isfinite(denoise) or not 0.05 <= denoise <= 1:
                    return {"ok": False, "error": "Denoise is a number from 0.05 to 1."}, 400
            how = image_panel.upscale_detail(method, strength, resolution, denoise, int(times) if method == "seedvr2" and times else None)
            new_argv = [*image_panel.UPSCALE, "--resume", state.id, "--image", position,
                        *(["--file", flag("--file")] if flag("--file") else []), "--method", method,
                        "--strength", f"{strength:g}", *(["--resolution", str(resolution)] if resolution else []),
                        *(["--denoise", f"{denoise:g}"] if denoise is not None else [])]
            estimate = server.UpscaleEta(new_argv, server.IMAGE_TIMINGS).plan()["total"]
        else:
            name = flag("--film")
            if not name:
                return {"ok": False, "error": "The original film is no longer available."}, 409
            try:
                video_panel.safe_video_path("video", name)
            except NotFound:
                return {"ok": False, "error": "The original film is no longer available."}, 409
            try:
                scale = float(data.get("scale"))
            except (TypeError, ValueError):
                return {"ok": False, "error": "Choose a valid scale."}, 400
            quality = data.get("quality")
            if not math.isfinite(scale) or not 1 <= scale <= 4 or quality not in video_panel.film_upscale.QUALITIES:
                return {"ok": False, "error": "Choose a valid scale and quality."}, 400
            how = f"RTX VSR, {scale:g}x, {quality}"
            new_argv = [*video_panel.UPSCALE, "--film", name, "--scale", f"{scale:g}", "--quality", quality]
            estimate = server.UpscaleEta(new_argv, server.VIDEO_TIMINGS).plan()["total"]
        replacement = {**old, "argv": new_argv, "detail": how, "estimate": estimate, "waited": True}
        server.run_queue.put_back_edited(old, replacement)
        server.run_queue._save()
        server.run_queue._advance()
        return {"ok": True, "queued": replacement in server.run_queue.items}


@bp.before_app_request
def validate_queue_edit():
    if not request.path.startswith("/generate/") or not request.form.get("queue_edit_id"):
        return None
    item_id = request.form.get("queue_edit_id", type=int)
    token = request.form.get("queue_edit_token", "")
    with server.run_queue.lock:
        item = next((entry for entry in server.run_queue.items if entry["id"] == item_id), None)
        if not item or item.get("pipeline") != request.path.rsplit("/", 1)[-1] or not item.get("edit_token") or not secrets.compare_digest(item["edit_token"], token):
            return {"ok": False, "error": "That editing session expired. Open the queued job again."}, 409
    return None


@bp.route("/queue/run/edit/<int:item_id>/file/<name>")
@server.password_required
def queue_edit_file(item_id, name):
    with server.run_queue.lock:
        item = next((entry for entry in server.run_queue.items if entry["id"] == item_id), None)
        if not item or not item.get("edit_token") or not secrets.compare_digest(item["edit_token"], request.headers.get("X-Queue-Edit-Token", "")):
            abort(404)
        restored = (item["form"], item.get("form_files", {}), {}) if item.get("form") else legacy_queue_form(item)
        path = restored[1].get(name) if restored else None
        if not path or not os.path.isfile(path):
            abort(404)
        return send_file(path, download_name=os.path.basename(path))


@bp.route("/queue/run/edit/<int:item_id>/cancel", methods=["POST"])
@server.password_required
def queue_edit_cancel(item_id):
    token = (request.get_json(silent=True) or {}).get("token", "")
    with server.run_queue.lock:
        item = next((entry for entry in server.run_queue.items if entry["id"] == item_id), None)
        if not item or not item.get("edit_token") or not secrets.compare_digest(item["edit_token"], token):
            return {"ok": False, "error": "That editing session is no longer active."}, 409
        item.pop("edit_token")
        # Back where it came from: in the queue, at the place it held (its place in the list never changed), or in
        # Pending.
        if item.pop("edit_from_queue", False):
            item.pop("later", None)
        server.run_queue._save()
        server.run_queue._advance()
        return {"ok": True}


@bp.route("/queue/<lane>/run-now/<int:item_id>", methods=["POST"])
@server.password_required
def queue_run_now(lane, item_id):
    if lane not in server.QUEUES:
        abort(404)
    if lane != "run":
        abort(404)
    result, error = server.QUEUES[lane].run_now(item_id)
    if result == "not_ready":
        return {"ok": False, "error": "Run this is available only while nothing is running."}, 409
    if result == "not_found":
        return {"ok": False, "error": "That job is no longer in the queue."}, 404
    if result == "failed":
        return {"ok": False, "error": error}, 500
    return {"ok": True, "waiting": result == "waiting"}


@bp.route("/queue/<lane>/order", methods=["POST"])
@server.password_required
def queue_order(lane):
    """The waiting jobs in a new order: {"ids": [...]}, first to start first."""
    if lane not in server.QUEUES:
        abort(404)
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        return {"ok": False, "error": "The order is a list of the queued jobs' ids."}, 400
    return {"ok": True, "changed": server.QUEUES[lane].reorder(ids)}


@bp.route("/queue/<lane>/resume", methods=["POST"])
@server.password_required
def queue_resume(lane):
    if lane not in server.QUEUES:
        abort(404)
    server.QUEUES[lane].resume()
    return {"ok": True}


@bp.route("/queue/<lane>/hold", methods=["POST"])
@server.password_required
def queue_hold(lane):
    if lane not in server.QUEUES:
        abort(404)
    server.QUEUES[lane].hold()
    return {"ok": True}


server.app.register_blueprint(bp)
